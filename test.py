# prueba.py
import yfinance as yf
from indicador_avanzado import calcular_indicadores_y_senal   # <-- importación

# Descargar datos de ejemplo
df = yf.Ticker("AAPL").history(period="200d")
df.columns = [c.lower() for c in df.columns]   # yfinance devuelve columnas con mayúscula

# Llamar a la función
resultado = calcular_indicadores_y_senal(df)

print("Señal:", resultado['senal'])
print("RSI:", resultado['indicadores']['rsi'])
print("ADX:", resultado['indicadores']['adx'])