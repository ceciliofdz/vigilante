# Vigilante

Este proyecto contiene varios scripts Python para vigilar precios y señales técnicas de activos usando `yfinance`, `pandas`, `numpy`, `requests` y `schedule`.

## Archivos principales

### `indicador_avanzado.py`

Este módulo contiene la función `calcular_indicadores_y_senal(df, params=None)` que replica un indicador técnico avanzado basado en:
- EMAs (EMA20, EMA50, EMA200)
- RSI
- VWAP
- ADX / DMI
- distancia al EMA200

La función devuelve un diccionario con:
- `senal`: `LONG`, `SHORT` o `WAIT`
- `allow_long` y `allow_short`
- `indicadores`: valores calculados para depuración y análisis

Se usa como núcleo para evaluar la señal técnica de cada ticker.

### `vigilante_precio.py`

Vigila el precio actual de un solo símbolo (`SIMBOLO`) y envía alertas por Telegram cuando se cruza:
- `PRECIO_OBJETIVO_SUPERIOR`
- `PRECIO_OBJETIVO_INFERIOR`

Incluye:
- descarga del precio actual con `yfinance`
- envío de mensajes a Telegram
- ejecución periódica cada 5 minutos con `schedule`

### `vigilante.py`

Vigila un solo símbolo usando la lógica de `indicador_avanzado.py`.

Flujo:
- descarga datos históricos con `yfinance`
- normaliza columnas
- calcula los indicadores avanzados y la señal
- imprime información técnica en consola
- envía alerta por Telegram si la señal es `LONG` o `SHORT`
- se ejecuta cada 15 minutos con `schedule`

### `vigilante_multiticker.py`

Amplía la vigilia a múltiples tickers.

Características:
- lee `cryptos.db` para obtener tickers activos desde la tabla `tickers`
- descarga datos diarios para cada ticker
- calcula la señal usando `calcular_indicadores_y_senal`
- compara la señal actual con la última señal guardada en `ultimas_senales.json`
- envía alertas Telegram solo cuando la señal cambia de estado
- calcula alertas de cercanía a soportes, resistencias y pivotes diarios
- guarda el estado de señales para evitar notificaciones repetidas
- se ejecuta periódicamente con `schedule`

### `vigilante_intradia_multiticker.py`

Vigila múltiples tickers con señales intradía.

Características:
- lee `cryptos.db` para obtener tickers activos desde la tabla `tickers`
- descarga velas de 15 minutos con `yfinance`
- usa parámetros técnicos propios para intradía
- calcula VWAP por sesión
- compara la señal actual con la última señal guardada en `ultimas_senales_intradia_15m.json`
- envía alertas Telegram etiquetadas como `INTRADIA 15m`
- se ejecuta cada 15 minutos con `schedule`

### `test.py`

Script de prueba básico para verificar que `indicador_avanzado.py` funcione correctamente.

Hace:
- descarga datos de ejemplo de `AAPL`
- normaliza columnas
- llama a `calcular_indicadores_y_senal`
- imprime la señal, el RSI y el ADX

## Archivos de datos

### `cryptos.db`

Base de datos SQLite con la tabla `tickers`.

Formato esperado:
```sql
CREATE TABLE tickers (
  ticker TEXT PRIMARY KEY,
  vigilar INTEGER,
  nombre TEXT
);
```

### `ultimas_senales.json`

Archivo JSON usado por `vigilante_multiticker.py` para almacenar la última señal conocida de cada ticker y evitar alertas duplicadas.

## Dependencias

Instala las librerías necesarias con:

```bash
pip install pandas numpy yfinance requests schedule
```

## Uso

- `python vigilante_precio.py`: vigila el precio objetivo de un símbolo único.
- `python vigilante.py`: vigila un símbolo usando señales técnicas avanzadas.
- `python vigilante_multiticker.py`: vigila múltiples tickers con señales diarias.
- `python vigilante_intradia_multiticker.py`: vigila múltiples tickers con señales intradía de 15 minutos.
- `python test.py`: prueba la función de indicadores avanzados.
