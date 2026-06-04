import pandas as pd
import numpy as np

def calcular_indicadores_y_senal(df, params=None):
    """
    Replica el Pine Script "Intradía EMA RSI VWAP ADX Multi-Activo Stable".
    Devuelve un diccionario con la señal actual (long, short, wait) y todos los indicadores.

    Parámetros:
    - df: DataFrame con columnas ['open','high','low','close','volume'].
          Debe tener al menos 200 velas para EMA200.
    - params: dict opcional con parámetros (si no se usan, los valores por defecto son los del script).

    Retorna:
    - dict con:
        'senal': 'LONG', 'SHORT' o 'WAIT'
        'allowLong': bool
        'allowShort': bool
        'indicadores': dict con valores actuales de ema_fast, ema_slow, ema_trend, rsi, vwap, adx, etc.
    """
    # Parámetros por defecto (iguales al Pine Script)
    defaults = {
        'ema_fast_len': 20,
        'ema_slow_len': 50,
        'ema_trend_len': 200,
        'rsi_len': 14,
        'adx_len': 14,
        'adx_min': 25.0,
        'rsi_long_min': 52.0,
        'rsi_short_max': 48.0,
        'solo_compras': True,      # Si True, ignora señales de short
        'usar_filtro_manual': False,
        'permite_long_manual': True,
        'vwap_por_sesion': False,
        'usar_filtro_extension': True,
        'dist_max_ema200': 18.0,   # % máximo sobre EMA200
        'dist_estricto_ema200': 12.0
    }
    if params:
        defaults.update(params)
    p = defaults

    # Copia para no modificar original
    data = df.copy()
    
    # ---------- Indicadores base ----------
    # EMAs
    data['ema_fast'] = data['close'].ewm(span=p['ema_fast_len'], adjust=False).mean()
    data['ema_slow'] = data['close'].ewm(span=p['ema_slow_len'], adjust=False).mean()
    data['ema_trend'] = data['close'].ewm(span=p['ema_trend_len'], adjust=False).mean()
    
    # RSI
    delta = data['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=p['rsi_len']).mean()
    avg_loss = loss.rolling(window=p['rsi_len']).mean()
    rs = avg_gain / avg_loss
    data['rsi'] = 100 - (100 / (1 + rs))
    
    # VWAP (precio típico ponderado por volumen acumulado)
    data['typical_price'] = (data['high'] + data['low'] + data['close']) / 3.0
    pv = data['typical_price'] * data['volume']
    if p['vwap_por_sesion'] and isinstance(data.index, pd.DatetimeIndex):
        sesiones = data.index.date
        data['vwap'] = pv.groupby(sesiones).cumsum() / data['volume'].groupby(sesiones).cumsum()
    else:
        data['vwap'] = pv.cumsum() / data['volume'].cumsum()
    
    # ---------- ADX / DMI ----------
    # True Range
    data['high_low'] = data['high'] - data['low']
    data['high_close'] = np.abs(data['high'] - data['close'].shift())
    data['low_close'] = np.abs(data['low'] - data['close'].shift())
    data['tr'] = data[['high_low', 'high_close', 'low_close']].max(axis=1)
    
    # Direccionales +DM, -DM
    data['up_move'] = data['high'] - data['high'].shift()
    data['down_move'] = data['low'].shift() - data['low']
    data['plus_dm'] = np.where((data['up_move'] > data['down_move']) & (data['up_move'] > 0), data['up_move'], 0.0)
    data['minus_dm'] = np.where((data['down_move'] > data['up_move']) & (data['down_move'] > 0), data['down_move'], 0.0)
    
    # Suavizado con RMA (Wilder's smoothing) = EMA con alpha = 1/len
    def rma(series, length):
        return series.ewm(alpha=1/length, adjust=False).mean()
    
    data['tr_smooth'] = rma(data['tr'], p['adx_len'])
    data['plus_dm_smooth'] = rma(data['plus_dm'], p['adx_len'])
    data['minus_dm_smooth'] = rma(data['minus_dm'], p['adx_len'])
    
    data['plus_di'] = np.where(data['tr_smooth'] != 0, 100 * data['plus_dm_smooth'] / data['tr_smooth'], 0)
    data['minus_di'] = np.where(data['tr_smooth'] != 0, 100 * data['minus_dm_smooth'] / data['tr_smooth'], 0)
    
    data['dx'] = np.where((data['plus_di'] + data['minus_di']) != 0,
                          100 * np.abs(data['plus_di'] - data['minus_di']) / (data['plus_di'] + data['minus_di']),
                          0)
    data['adx'] = rma(data['dx'], p['adx_len'])
    
    # ---------- Extensión respecto a EMA200 ----------
    data['dist_ema200_pct'] = (data['close'] / data['ema_trend'] - 1.0) * 100.0
    data['activo_extendido'] = (data['dist_ema200_pct'] > p['dist_estricto_ema200'])
    data['extension_permitida'] = ~p['usar_filtro_extension'] | (data['dist_ema200_pct'] <= p['dist_max_ema200'])
    
    # ---------- Filtro manual (simulado) ----------
    data['fundamental_ok_long'] = (not p['usar_filtro_manual']) or p['permite_long_manual']
    data['fundamental_ok_short'] = True  # En este script se deja siempre True
    
    # ---------- Condiciones técnicas ----------
    # Tendencia para long y short
    data['trend_long'] = (data['ema_fast'] > data['ema_slow']) & (data['close'] > data['ema_trend'])
    data['trend_short'] = (data['ema_fast'] < data['ema_slow']) & (data['close'] < data['ema_trend'])
    
    # Condiciones base
    data['base_long'] = (data['close'] > data['vwap']) & \
                        (data['rsi'] >= p['rsi_long_min']) & \
                        (data['adx'] >= p['adx_min']) & \
                        (data['plus_di'] > data['minus_di'])
    
    data['base_short'] = (data['close'] < data['vwap']) & \
                         (data['rsi'] <= p['rsi_short_max']) & \
                         (data['adx'] >= p['adx_min']) & \
                         (data['minus_di'] > data['plus_di'])
    
    # Condiciones estrictas (cuando activo_extendido)
    data['strict_long'] = (data['close'] > data['vwap']) & \
                          (data['rsi'] >= (p['rsi_long_min'] + 3)) & \
                          (data['adx'] >= (p['adx_min'] + 5)) & \
                          (data['plus_di'] > data['minus_di'])
    
    data['strict_short'] = (data['close'] < data['vwap']) & \
                           (data['rsi'] <= (p['rsi_short_max'] - 3)) & \
                           (data['adx'] >= (p['adx_min'] + 5)) & \
                           (data['minus_di'] > data['plus_di'])
    
    # Selecciona base o estricto según extensión
    data['tech_long'] = np.where(data['activo_extendido'], data['strict_long'], data['base_long'])
    data['tech_short'] = np.where(data['activo_extendido'], data['strict_short'], data['base_short'])
    
    # ---------- Señales finales ----------
    data['allow_long'] = data['trend_long'] & data['tech_long'] & data['fundamental_ok_long'] & data['extension_permitida']
    data['allow_short'] = (~p['solo_compras']) & data['trend_short'] & data['tech_short'] & data['fundamental_ok_short']
    
    # Último valor (más reciente)
    ultimo = data.iloc[-1]
    
    senal = 'WAIT'
    if ultimo['allow_long']:
        senal = 'LONG'
    elif ultimo['allow_short']:
        senal = 'SHORT'
    
    # Recopilar indicadores para debug (opcional)
    indicadores_actuales = {
        'ema_fast': ultimo['ema_fast'],
        'ema_slow': ultimo['ema_slow'],
        'ema_trend': ultimo['ema_trend'],
        'rsi': ultimo['rsi'],
        'vwap': ultimo['vwap'],
        'adx': ultimo['adx'],
        'plus_di': ultimo['plus_di'],
        'minus_di': ultimo['minus_di'],
        'dist_ema200_pct': ultimo['dist_ema200_pct'],
        'activo_extendido': ultimo['activo_extendido'],
        'trend_long': ultimo['trend_long'],
        'tech_long': ultimo['tech_long'],
        'allow_long': ultimo['allow_long'],
        'allow_short': ultimo['allow_short']
    }
    
    return {
        'senal': senal,
        'allow_long': bool(ultimo['allow_long']),
        'allow_short': bool(ultimo['allow_short']),
        'indicadores': indicadores_actuales
    }
