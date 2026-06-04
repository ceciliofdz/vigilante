import yfinance as yf
import time
import requests
import schedule
from datetime import datetime
import os
import json
import logging
import threading
import sqlite3
from dotenv import load_dotenv
from logging.handlers import TimedRotatingFileHandler
from indicador_avanzado import calcular_indicadores_y_senal
from soporte_resistencia import normalizar_columnas_ohlcv

# Cargar variables de entorno
load_dotenv()

# ================= CONFIGURACION INTRADIA =================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
DB_PATH = "cryptos.db"                     # Base de datos con tabla 'tickers' (ticker, vigilar)
ARCHIVO_ESTADO = "ultimas_senales_intradia_15m.json"
INTERVALO_MINUTOS = 15
PERIODO_DATOS = "60d"                      # Maximo habitual de yfinance para intervalos de 15m
INTERVALO_DATOS = "15m"
USAR_ULTIMA_VELA_CERRADA = True            # Evita senales con vela intradia en formacion

INDICADOR_PARAMS = {
    'solo_compras': False,
    'usar_filtro_extension': True,
    'dist_max_ema200': 6.0,
    'dist_estricto_ema200': 4.0,
    'adx_min': 20.0,
    'rsi_long_min': 53.0,
    'rsi_short_max': 47.0,
    'vwap_por_sesion': True
}
# ==========================================================

# ---------- Configuracion del logging diario ----------
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
log_file = os.path.join(LOG_DIR, "vigilante_intradia_multiticker.log")

logger = logging.getLogger()
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

file_handler = TimedRotatingFileHandler(
    log_file, when="midnight", interval=1, backupCount=30, encoding="utf-8"
)
file_handler.setFormatter(formatter)
file_handler.suffix = "%Y-%m-%d"
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# ---------- Funciones auxiliares ----------
def enviar_telegram(mensaje):
    """Envia mensaje por Telegram de forma asincrona."""
    def _send():
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje}
        try:
            requests.post(url, json=payload, timeout=5)
            logging.info(f"Alerta enviada: {mensaje[:50]}...")
        except Exception as e:
            logging.error(f"Error en Telegram: {e}")
    threading.Thread(target=_send, daemon=True).start()

def cargar_tickers_activos():
    """Lee tickers activos desde la tabla 'tickers' de cryptos.db."""
    if not os.path.exists(DB_PATH):
        logging.error(f"No se encuentra la base de datos {DB_PATH}")
        return []
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT ticker FROM tickers WHERE vigilar = 1")
        rows = cursor.fetchall()
        activos = [row['ticker'] for row in rows]
        conn.close()
        logging.info(f"Tickers activos cargados desde {DB_PATH}: {activos}")
        return activos
    except sqlite3.Error as e:
        logging.error(f"Error al leer tickers desde base de datos: {e}")
        return []

def cargar_estado_senales():
    if os.path.exists(ARCHIVO_ESTADO):
        try:
            with open(ARCHIVO_ESTADO, 'r') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error cargando estado señales intradia: {e}")
    return {}

def guardar_estado_senales(estado):
    try:
        with open(ARCHIVO_ESTADO, 'w') as f:
            json.dump(estado, f, indent=2)
    except Exception as e:
        logging.error(f"Error guardando estado señales intradia: {e}")

def seleccionar_velas_para_senal(df):
    """Usa la ultima vela cerrada cuando hay suficiente historico."""
    if USAR_ULTIMA_VELA_CERRADA and len(df) > 1:
        return df.iloc[:-1]
    return df

def obtener_senal_ticker(ticker):
    """Descarga datos intradia y calcula la señal para un ticker."""
    try:
        logging.info(f"Consultando intradia {ticker}...")
        df = yf.download(ticker, period=PERIODO_DATOS, interval=INTERVALO_DATOS, progress=False)
        if df.empty:
            logging.warning(f"Sin datos intradia para {ticker}")
            return None

        df = normalizar_columnas_ohlcv(df)

        columnas_necesarias = ['open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in columnas_necesarias):
            logging.warning(f"Columnas inesperadas en {ticker}: {df.columns.tolist()}")
            return None

        df_senal = seleccionar_velas_para_senal(df)
        resultado = calcular_indicadores_y_senal(df_senal, params=INDICADOR_PARAMS)
        precio_senal = round(float(df_senal['close'].iloc[-1]), 2)
        precio_actual = round(float(df['close'].iloc[-1]), 2)
        fecha_senal = df_senal.index[-1].strftime("%Y-%m-%d %H:%M")

        return {
            'senal': resultado['senal'],
            'precio': precio_senal,
            'precio_actual': precio_actual,
            'fecha_senal': fecha_senal,
            'rsi': round(resultado['indicadores']['rsi'], 1),
            'adx': round(resultado['indicadores']['adx'], 1),
            'dist_ema200': round(resultado['indicadores']['dist_ema200_pct'], 2)
        }
    except Exception as e:
        logging.error(f"Error con {ticker}: {e}")
        return None

def vigilar_todos():
    tickers = cargar_tickers_activos()
    if not tickers:
        logging.warning("No hay tickers activos para vigilar.")
        return

    estado_anterior_senales = cargar_estado_senales()
    estado_nuevo_senales = estado_anterior_senales.copy()

    hora_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logging.info(f"🔍 Ejecutando vigilancia intradia multi-ticker - {hora_actual}")

    for ticker in tickers:
        info = obtener_senal_ticker(ticker)
        if info is None:
            continue

        senal_actual = info['senal']
        precio = info['precio']
        estado_nuevo_senales[ticker] = senal_actual

        senal_previa = estado_anterior_senales.get(ticker, "WAIT")
        if senal_actual != senal_previa and senal_actual != "WAIT":
            emoji = "🟢" if senal_actual == "LONG" else "🔴"
            direccion = "LONG (Compra)" if senal_actual == "LONG" else "SHORT (Venta)"
            mensaje = (f"{emoji} *{ticker}* - Señal INTRADIA {INTERVALO_DATOS} {direccion}\n"
                       f"Vela señal: {info['fecha_senal']}\n"
                       f"Cierre señal: ${precio}\n"
                       f"Precio actual: ${info['precio_actual']}\n"
                       f"RSI: {info['rsi']} | ADX: {info['adx']}\n"
                       f"Dist. EMA200: {info['dist_ema200']}%")
            enviar_telegram(mensaje)
            logging.info(f"Alerta intradia para {ticker}: {senal_previa} -> {senal_actual}")
        else:
            logging.info(f"{ticker}: {senal_actual} intradia (sin cambio de señal)")

    guardar_estado_senales(estado_nuevo_senales)
    logging.info("Vigilancia intradia multi-ticker completada.\n")

# ================= CONFIGURACION DEL SCHEDULER =================
schedule.every(INTERVALO_MINUTOS).minutes.do(vigilar_todos)

logging.info(f"🟢 Agente intradia multi-ticker iniciado. Revisando cada {INTERVALO_MINUTOS} minutos.")
logging.info(f"Usando base de datos: {DB_PATH}")
logging.info(f"Intervalo de datos intradia: {INTERVALO_DATOS}")
vigilar_todos()

while True:
    schedule.run_pending()
    time.sleep(1)
