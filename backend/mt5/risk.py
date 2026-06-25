import math
from typing import Optional
from loguru import logger

# Intento seguro de importar mt5
try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

from backend.mt5.client import MT5Client

# ── FTMO 10k EUR limits ──────────────────────────────────────────────────────
INITIAL_BALANCE = 10_000.0
# ... (mantén todas tus constantes aquí igual que las tenías)
SYS_DAILY_LIMIT = 300.0
MAX_DAILY_LOSS = 500.0
MAX_OPEN_RISK = 200.0
WARN_THRESHOLD = SYS_DAILY_LIMIT * 0.60
RISK_PER_TRADE = 0.01

def get_risk_status(client: MT5Client) -> dict:
    # Si mt5 no está, devolvemos un status "simulado" para que el bot no muera
    if mt5 is None:
        return {"balance": INITIAL_BALANCE, "equity": INITIAL_BALANCE, "is_ok": True}
    
    # ... (el resto de tu función original)
    return {"balance": 10000.0, "is_ok": True}

def calculate_lot_size(symbol: str, sl_pips: float, risk_eur: float) -> float:
    if mt5 is None or mt5.symbol_info(symbol) is None:
        return 0.01 # Valor de emergencia
    
    info = mt5.symbol_info(symbol)
    # ... (aquí mantienes tu lógica original de cálculo)
    return 0.01

def _calculate_open_risk(positions: list[dict]) -> float:
    if mt5 is None: return 0.0
    # ... (tu lógica de cálculo de riesgo)
    return 0.0
