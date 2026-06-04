import os
import time
import requests
import schedule
import csv
import logging
import threading
from datetime import datetime
from dotenv import load_dotenv
from logging.handlers import TimedRotatingFileHandler
import sqlite3


# Añade esta constante para la ruta de la base de datos
DB_PATH = "cryptos.db"

# Cargar variables de entorno
load_dotenv()

# Configuración desde variables de entorno
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY")
CRYPTOS_CSV = os.environ.get("CRYPTOS_CSV", "cryptos.csv")

# Validaciones básicas
if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    raise ValueError("Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID en el entorno o .env")
if not FINNHUB_API_KEY:
    raise ValueError("Falta FINNHUB_API_KEY en el entorno o .env")

# ---------- Configuración del logging diario ----------
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)  # Crear carpeta de logs si no existe

# Nombre base del archivo de log: logs/vigilante.log (el handler añadirá la fecha)
log_file = os.path.join(LOG_DIR, "vigilante.log")

# Configurar logger raíz
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Formato: fecha hora - nivel - mensaje
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# Handler para archivo con rotación diaria (se guarda como vigilante.log.2025-03-21)
file_handler = TimedRotatingFileHandler(
    log_file, when="midnight", interval=1, backupCount=30, encoding="utf-8"
)
file_handler.setFormatter(formatter)
file_handler.suffix = "%Y-%m-%d"  # Sufijo para los archivos rotados
logger.addHandler(file_handler)

# Opcional: handler para consola (comenta o elimina si no lo necesitas)
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# ---------- Sesión HTTP compartida ----------
session = requests.Session()
session.headers.update({"User-Agent": "VigilantePrecios/2.0"})

# ---------- Funciones auxiliares ----------
def enviar_telegram(mensaje):
    """Envía un mensaje por Telegram de forma asíncrona"""
    def _send():
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje}
        try:
            session.post(url, json=payload, timeout=5)
            logging.info(f"Alerta enviada: {mensaje[:50]}...")
        except Exception as e:
            logging.error(f"Error al enviar Telegram: {e}")
    threading.Thread(target=_send, daemon=True).start()

def cargar_cryptos_activos():
    """Carga cryptos activas desde la base de datos SQLite."""
    activos = []

    if not os.path.exists(DB_PATH):
        print(f"No se encuentra la base de datos {DB_PATH}. Asegúrate de haber ejecutado el script de migración.")
        return activos

    try:
        conn = sqlite3.connect(DB_PATH)
        # Usar row_factory para acceder a las columnas por nombre
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Seleccionar solo las filas que estén activas (active = 1)
        cursor.execute("SELECT symbol, name, upper, lower FROM cryptos WHERE active = 1")
        rows = cursor.fetchall()

        for row in rows:
            activos.append({
                'symbol': row['symbol'],
                'name': row['name'],
                'upper': row['upper'],
                'lower': row['lower']
            })

        conn.close()
        print(f"Cargados {len(activos)} activos desde la base de datos {DB_PATH}")

    except sqlite3.Error as e:
        print(f"Error al leer la base de datos: {e}")

    return activos

def obtener_precio_actual(symbol):
    """Obtiene el último precio usando Finnhub, con soporte para acciones y criptos."""
    if not FINNHUB_API_KEY or FINNHUB_API_KEY == "TU_API_KEY_AQUI":
        logging.error("No se ha configurado FINNHUB_API_KEY correctamente.")
        return None

    try:
        precio = obtener_precio_quote(symbol)
        if precio is not None:
            return precio

        # Si es símbolo de crypto, intenta con exchanges alternativos compatibles.
        if ":" in symbol:
            logging.info(f"quote no devolvió precio válido para {symbol}, intentando alternativas...")
            precio = obtener_precio_crypto_quote_alternativas(symbol)
            if precio is not None:
                return precio

        logging.warning(f"No se obtuvo precio válido para {symbol}. Revisa el símbolo.")
        return None
    except Exception as e:
        logging.error(f"Error en Finnhub (quote): {e}")
        return None

def obtener_precio_quote(symbol):
    """Consulta el endpoint quote de Finnhub para un símbolo."""
    url = "https://finnhub.io/api/v1/quote"
    params = {"symbol": symbol, "token": FINNHUB_API_KEY}
    try:
        response = session.get(url, params=params, timeout=5)
        response.raise_for_status()
        datos = response.json()
        precio = datos.get("c")
        if precio and precio > 0:
            return round(precio, 2)
        return None
    except Exception as e:
        logging.warning(f"Error en quote para {symbol}: {e}")
        return None

CRYPTO_EXCHANGES_FALLBACK = ["BINANCE", "COINBASE", "KRAKEN", "BITSTAMP"]

def obtener_precio_crypto_quote_alternativas(symbol):
    """Intenta el mismo par crypto en diferentes exchanges si el símbolo original falla."""
    try:
        exchange, pair = symbol.split(":", 1)
    except ValueError:
        return None

    for exchange_name in CRYPTO_EXCHANGES_FALLBACK:
        if exchange_name == exchange:
            continue
        intento = f"{exchange_name}:{pair}"
        try:
            precio = obtener_precio_quote(intento)
            if precio is not None:
                logging.info(f"Se obtuvo precio válido con {intento}.")
                return precio
        except Exception:
            continue
    return None

# Caché para evitar alertas repetitivas
_estado_alertas = {}

def vigilar_accion():
    """Función principal que comprueba los precios y envía alertas para cada ticker activo."""
    activos = cargar_cryptos_activos()
    if not activos:
        logging.warning("No hay cryptos activas en el CSV.")
        return

    hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logging.info(f"🔍 Vigilancia de criptos - {hora}")

    for ticker in activos:
        symbol = ticker.get("symbol")
        name = ticker.get("name")
        upper = ticker.get("upper")
        lower = ticker.get("lower")

        precio_actual = obtener_precio_actual(symbol)
        if precio_actual is None:
            continue

        display = name if name else symbol
        logging.info(f"{display} ({symbol}): ${precio_actual}")

        # Prevenir alertas repetidas
        estado = _estado_alertas.get(symbol, {"upper": False, "lower": False})

        if upper is not None and upper > 0 and precio_actual >= upper:
            if not estado["upper"]:
                mensaje = f"🚨 ALERTA: {display} ({symbol}) superó ${upper}! Precio actual: ${precio_actual}"
                enviar_telegram(mensaje)
                estado["upper"] = True
        else:
            estado["upper"] = False

        if lower is not None and lower > 0 and precio_actual <= lower:
            if not estado["lower"]:
                mensaje = f"⚠️ ATENCIÓN: {display} ({symbol}) cayó por debajo de ${lower}! Precio actual: ${precio_actual}"
                enviar_telegram(mensaje)
                estado["lower"] = True
        else:
            estado["lower"] = False

        _estado_alertas[symbol] = estado

        # Pequeña pausa para no saturar la API
        time.sleep(0.5)

# ---------- Programación y bucle principal ----------
schedule.every(5).minutes.do(vigilar_accion)

logging.info(f"🟢 Agente iniciado. Vigilando las cryptos activas en {CRYPTOS_CSV}...")
vigilar_accion()  # Ejecuta una vez al inicio

while True:
    schedule.run_pending()
    time.sleep(1)