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
from soporte_resistencia import obtener_niveles_sr, esta_cerca_nivel, normalizar_columnas_ohlcv

# Cargar variables de entorno
load_dotenv()

# ================= CONFIGURACIÓN =================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
DB_PATH = "cryptos.db"                     # Base de datos con tabla 'tickers' (ticker, vigilar)
ARCHIVO_ESTADO = "ultimas_senales.json"
ARCHIVO_ESTADO_NIVELES = "ultimos_niveles_alertados.json"
INTERVALO_MINUTOS = 240
PERIODO_DATOS = "250d"                     # Datos para indicadores (EMA200)
INTERVALO_DATOS = "1d"                     # Datos diarios
PERIODO_SR = "3mo"                         # Período histórico para calcular soportes/resistencias
VENTANA_FRACTAL = 5                        # Ventana para fractales
UMBRAL_CERCANIA_PORCENTAJE = 0.5           # 0.5% para alertas de niveles
USAR_CLUSTERING_SR = True                  # Agrupar niveles con KMeans
USAR_ULTIMA_VELA_CERRADA = True            # Evita señales con vela diaria en formación

INDICADOR_PARAMS = {
    'solo_compras': False,
    'usar_filtro_extension': True,
    'dist_max_ema200': 18.0,
    'dist_estricto_ema200': 12.0,
    'adx_min': 25.0,
    'rsi_long_min': 52.0,
    'rsi_short_max': 48.0
}
# ================================================

# ---------- Configuración del logging diario ----------
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
log_file = os.path.join(LOG_DIR, "vigilante_multiticker.log")

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
    """Envía mensaje por Telegram de forma asíncrona"""
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
    """Lee tickers activos desde la tabla 'tickers' de cryptos.db"""
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
            logging.error(f"Error cargando estado señales: {e}")
    return {}

def guardar_estado_senales(estado):
    try:
        with open(ARCHIVO_ESTADO, 'w') as f:
            json.dump(estado, f, indent=2)
    except Exception as e:
        logging.error(f"Error guardando estado señales: {e}")

def cargar_estado_niveles():
    if os.path.exists(ARCHIVO_ESTADO_NIVELES):
        try:
            with open(ARCHIVO_ESTADO_NIVELES, 'r') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error cargando estado niveles: {e}")
    return {}

def guardar_estado_niveles(estado):
    try:
        with open(ARCHIVO_ESTADO_NIVELES, 'w') as f:
            json.dump(estado, f, indent=2)
    except Exception as e:
        logging.error(f"Error guardando estado niveles: {e}")

def seleccionar_velas_para_senal(df):
    """Evita usar la vela diaria en formacion si corresponde a la fecha actual."""
    if not USAR_ULTIMA_VELA_CERRADA or len(df) <= 1:
        return df

    ultima_fecha = df.index[-1].date()
    if ultima_fecha == datetime.now().date():
        return df.iloc[:-1]
    return df

def obtener_senal_ticker(ticker):
    """Descarga datos y calcula la señal para un ticker"""
    try:
        logging.info(f"Consultando {ticker}...")
        df = yf.download(ticker, period=PERIODO_DATOS, interval=INTERVALO_DATOS, progress=False)
        if df.empty:
            logging.warning(f"Sin datos para {ticker}")
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

        return {
            'senal': resultado['senal'],
            'precio': precio_senal,
            'precio_actual': precio_actual,
            'fecha_senal': df_senal.index[-1].strftime("%Y-%m-%d"),
            'rsi': round(resultado['indicadores']['rsi'], 1),
            'adx': round(resultado['indicadores']['adx'], 1),
            'dist_ema200': round(resultado['indicadores']['dist_ema200_pct'], 2),
            'df': df
        }
    except Exception as e:
        logging.error(f"Error con {ticker}: {e}")
        return None

def verificar_y_alertar_niveles(ticker, precio_actual, estado_niveles, df):
    """
    Calcula soportes/resistencias y envía alertas si está cerca de algún nivel.
    Retorna el estado_niveles actualizado.
    """
    hoy = datetime.now().strftime("%Y-%m-%d")
    # Obtener niveles
    soportes, resistencias, pivotes = obtener_niveles_sr(
        ticker, 
        periodo=PERIODO_SR, 
        ventana_fractal=VENTANA_FRACTAL,
        usar_clustering=USAR_CLUSTERING_SR,
        df=df
    )
    
    if not soportes and not resistencias and not pivotes:
        return estado_niveles
    
    # Comprobar cercanía
    cerca_res, nivel_res, dist_res = esta_cerca_nivel(
        precio_actual, resistencias, UMBRAL_CERCANIA_PORCENTAJE, tipo="resistencia"
    )
    cerca_sop, nivel_sop, dist_sop = esta_cerca_nivel(
        precio_actual, soportes, UMBRAL_CERCANIA_PORCENTAJE, tipo="soporte"
    )
    
    # Obtener alertas previas para este ticker
    registro = estado_niveles.get(ticker, {})
    ultima_res = registro.get('ultima_res', '')
    ultima_sop = registro.get('ultima_sop', '')
    ultima_piv = registro.get('ultima_piv', '')
    
    # Alerta de resistencia
    if cerca_res and ultima_res != f"res_{nivel_res}_{hoy}":
        mensaje = (f"⚠️ *{ticker}* cerca de RESISTENCIA\n"
                   f"Nivel: ${nivel_res:.2f}\n"
                   f"Precio actual: ${precio_actual:.2f}\n"
                   f"Distancia: {dist_res}%")
        enviar_telegram(mensaje)
        registro['ultima_res'] = f"res_{nivel_res}_{hoy}"
    
    # Alerta de soporte
    if cerca_sop and ultima_sop != f"sop_{nivel_sop}_{hoy}":
        mensaje = (f"⚠️ *{ticker}* cerca de SOPORTE\n"
                   f"Nivel: ${nivel_sop:.2f}\n"
                   f"Precio actual: ${precio_actual:.2f}\n"
                   f"Distancia: {dist_sop}%")
        enviar_telegram(mensaje)
        registro['ultima_sop'] = f"sop_{nivel_sop}_{hoy}"
    
    # Alerta de pivotes (R1, R2, S1, S2, Pivote)
    if pivotes:
        niveles_pivote = [pivotes['R1'], pivotes['R2'], pivotes['S1'], pivotes['S2'], pivotes['Pivote']]
        cerca_piv, nivel_piv, dist_piv = esta_cerca_nivel(precio_actual, niveles_pivote, UMBRAL_CERCANIA_PORCENTAJE)
        if cerca_piv and ultima_piv != f"piv_{nivel_piv}_{hoy}":
            # Determinar qué tipo de pivote es
            tipo = ""
            if nivel_piv == pivotes['R1']: tipo = "R1"
            elif nivel_piv == pivotes['R2']: tipo = "R2"
            elif nivel_piv == pivotes['S1']: tipo = "S1"
            elif nivel_piv == pivotes['S2']: tipo = "S2"
            elif nivel_piv == pivotes['Pivote']: tipo = "Pivote"
            mensaje = (f"📌 *{ticker}* cerca de nivel pivote {tipo}\n"
                       f"Nivel: ${nivel_piv:.2f}\n"
                       f"Precio actual: ${precio_actual:.2f}\n"
                       f"Distancia: {dist_piv}%")
            enviar_telegram(mensaje)
            registro['ultima_piv'] = f"piv_{nivel_piv}_{hoy}"
    
    estado_niveles[ticker] = registro
    return estado_niveles

def vigilar_todos():
    tickers = cargar_tickers_activos()
    if not tickers:
        logging.warning("No hay tickers activos para vigilar.")
        return

    estado_anterior_senales = cargar_estado_senales()
    estado_niveles = cargar_estado_niveles()
    estado_nuevo_senales = estado_anterior_senales.copy()

    hora_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logging.info(f"🔍 Ejecutando vigilancia multi-ticker - {hora_actual}")

    for ticker in tickers:
        info = obtener_senal_ticker(ticker)
        if info is None:
            continue

        senal_actual = info['senal']
        precio = info['precio']
        df = info['df']
        estado_nuevo_senales[ticker] = senal_actual

        # ----- Alertas por cambio de señal LONG/SHORT -----
        senal_previa = estado_anterior_senales.get(ticker, "WAIT")
        if senal_actual != senal_previa and senal_actual != "WAIT":
            emoji = "🟢" if senal_actual == "LONG" else "🔴"
            direccion = "LONG (Compra)" if senal_actual == "LONG" else "SHORT (Venta)"
            mensaje = (f"{emoji} *{ticker}* - Señal DIARIA {direccion}\n"
                       f"Fecha vela: {info['fecha_senal']}\n"
                       f"Cierre señal: ${precio}\n"
                       f"Precio actual: ${info['precio_actual']}\n"
                       f"RSI: {info['rsi']} | ADX: {info['adx']}\n"
                       f"Dist. EMA200: {info['dist_ema200']}%")
            enviar_telegram(mensaje)
            logging.info(f"Alerta de señal para {ticker}: {senal_previa} -> {senal_actual}")
        else:
            logging.info(f"{ticker}: {senal_actual} (sin cambio de señal)")

        # ----- Alertas por cercanía a soportes/resistencias -----
        estado_niveles = verificar_y_alertar_niveles(ticker, precio, estado_niveles, df)

    guardar_estado_senales(estado_nuevo_senales)
    guardar_estado_niveles(estado_niveles)
    logging.info("Vigilancia multi-ticker completada.\n")

# ================= CONFIGURACIÓN DEL SCHEDULER =================
schedule.every(INTERVALO_MINUTOS).minutes.do(vigilar_todos)

logging.info(f"🟢 Agente diario multi-ticker iniciado. Revisando cada {INTERVALO_MINUTOS} minutos.")
logging.info(f"Usando base de datos: {DB_PATH}")
logging.info(f"Alertas de niveles SR activadas (umbral {UMBRAL_CERCANIA_PORCENTAJE}%)")
vigilar_todos()

while True:
    schedule.run_pending()
    time.sleep(1)
