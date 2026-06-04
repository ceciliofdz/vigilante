import pandas as pd
import numpy as np
import yfinance as yf
import logging

# Configurar logging básico si se usa independientemente
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def calcular_pivotes(df_diario):
    """
    Calcula puntos pivote estándar a partir de la última vela completa.
    df_diario: DataFrame con columnas 'high', 'low', 'close' de al menos 2 días.
    Retorna diccionario con niveles: P, R1, R2, S1, S2
    """
    if len(df_diario) < 2:
        return None
    # Usar la penúltima vela (la última completa)
    alta = df_diario['high'].iloc[-2]
    baja = df_diario['low'].iloc[-2]
    cierre = df_diario['close'].iloc[-2]
    
    P = (alta + baja + cierre) / 3
    R1 = 2 * P - baja
    R2 = P + (alta - baja)
    S1 = 2 * P - alta
    S2 = P - (alta - baja)
    
    return {
        'Pivote': P,
        'R1': R1,
        'R2': R2,
        'S1': S1,
        'S2': S2
    }

def detectar_fractales(df, ventana=5):
    """
    Encuentra máximos y mínimos locales en el histórico usando scipy.
    ventana: número de velas a cada lado para considerar un fractal.
    Retorna listas de precios (soportes, resistencias).
    """
    try:
        from scipy.signal import argrelextrema
    except ImportError:
        logging.error("scipy no instalado. Instalar con: pip install scipy")
        return [], []
    
    if len(df) < ventana * 2 + 1:
        return [], []
    
    highs = df['high'].values
    lows = df['low'].values
    
    maximos_idx = argrelextrema(highs, np.greater, order=ventana)[0]
    minimos_idx = argrelextrema(lows, np.less, order=ventana)[0]
    
    resistencias = highs[maximos_idx].tolist()
    soportes = lows[minimos_idx].tolist()
    return soportes, resistencias

def agrupar_niveles_kmeans(precios, n_clusters=5):
    """
    Agrupa precios cercanos usando KMeans y devuelve los centroides ordenados.
    """
    try:
        from sklearn.cluster import KMeans
    except ImportError:
        logging.warning("sklearn no instalado. Usando niveles sin agrupar.")
        return sorted(set(precios))

    if len(precios) == 0:
        return []
    if len(precios) <= n_clusters:
        n_clusters = max(1, len(precios))
    X = np.array(precios).reshape(-1, 1)
    kmeans = KMeans(n_clusters=n_clusters, random_state=0, n_init=10)
    kmeans.fit(X)
    niveles = sorted([round(c[0], 2) for c in kmeans.cluster_centers_])
    return niveles

def normalizar_columnas_ohlcv(df):
    """Aplana columnas de yfinance y las convierte a minúsculas."""
    data = df.copy()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [col[0] for col in data.columns]
    data.columns = [str(col).lower() for col in data.columns]
    return data

def recortar_por_periodo(df, periodo):
    """Recorta un histórico ya descargado usando periodos simples de yfinance."""
    if df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return df

    unidades = ("mo", "wk", "d", "y")
    unidad = next((u for u in unidades if periodo.endswith(u)), None)
    if unidad is None:
        return df

    cantidad = int(periodo[:-len(unidad)])
    if unidad == "d":
        offset = pd.DateOffset(days=cantidad)
    elif unidad == "wk":
        offset = pd.DateOffset(weeks=cantidad)
    elif unidad == "mo":
        offset = pd.DateOffset(months=cantidad)
    elif unidad == "y":
        offset = pd.DateOffset(years=cantidad)
    else:
        return df

    return df[df.index >= df.index.max() - offset]

def obtener_niveles_sr(ticker, periodo="3mo", ventana_fractal=5, usar_clustering=True, df=None):
    """
    Obtiene niveles de soporte y resistencia combinando fractales + clustering (opcional).
    Retorna (soportes_agrupados, resistencias_agrupadas, pivotes_diarios)
    """
    try:
        df_descargado = df is None
        if df_descargado:
            df = yf.download(ticker, period=periodo, interval="1d", progress=False)
        if df.empty:
            logging.warning(f"No hay datos históricos para {ticker}")
            return [], [], None
        
        df = normalizar_columnas_ohlcv(df)
        if not df_descargado:
            df = recortar_por_periodo(df, periodo)
        
        # Asegurar columnas necesarias
        required = ['high', 'low', 'close']
        if not all(col in df.columns for col in required):
            logging.warning(f"Faltan columnas en {ticker}: {df.columns.tolist()}")
            return [], [], None
        
        # Pivotes diarios
        pivotes = calcular_pivotes(df)
        
        # Fractales
        soportes_brutos, resistencias_brutas = detectar_fractales(df, ventana=ventana_fractal)
        
        if usar_clustering and len(soportes_brutos) > 0:
            soportes = agrupar_niveles_kmeans(soportes_brutos, n_clusters=8)
            resistencias = agrupar_niveles_kmeans(resistencias_brutas, n_clusters=8)
        else:
            soportes = sorted(set(soportes_brutos))
            resistencias = sorted(set(resistencias_brutas))
        
        return soportes, resistencias, pivotes
    except Exception as e:
        logging.error(f"Error obteniendo niveles SR para {ticker}: {e}")
        return [], [], None

def esta_cerca_nivel(precio_actual, niveles, porcentaje=0.5, tipo=None):
    """
    Verifica si el precio actual está dentro de un porcentaje (%) de algún nivel.
    niveles: lista de precios (soportes, resistencias o niveles genéricos)
    tipo: "soporte" para niveles por debajo del precio, "resistencia" para niveles por encima
    retorna (bool, nivel_cercano, distancia_porcentaje)
    """
    if not niveles:
        return False, None, None

    candidatos = []
    for nivel in niveles:
        if nivel <= 0 or precio_actual <= 0:
            continue
        if tipo == "soporte" and nivel > precio_actual:
            continue
        if tipo == "resistencia" and nivel < precio_actual:
            continue
        distancia = abs(precio_actual - nivel)
        porcentaje_dist = (distancia / precio_actual) * 100
        if porcentaje_dist <= porcentaje:
            candidatos.append((porcentaje_dist, nivel))

    if not candidatos:
        return False, None, None

    porcentaje_dist, nivel = min(candidatos, key=lambda item: item[0])
    return True, nivel, round(porcentaje_dist, 2)

# Si se ejecuta directamente, prueba con un ticker
if __name__ == "__main__":
    ticker = "AAPL"
    soportes, resistencias, pivotes = obtener_niveles_sr(ticker, periodo="3mo")
    print(f"Soportes agrupados: {soportes[:5]}")
    print(f"Resistencias agrupadas: {resistencias[:5]}")
    if pivotes:
        print(f"Pivotes: R1={pivotes['R1']:.2f}, S1={pivotes['S1']:.2f}")
