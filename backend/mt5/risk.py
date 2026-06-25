import math
from typing import Optional
from loguru import logger

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

from backend.mt5.client import MT5Client

# MANTÉN TUS CONSTANTES AQUÍ (INITIAL_BALANCE, etc.)
INITIAL_BALANCE = 10_000.0
SYS_DAILY_LIMIT = 300.0

# Asegúrate de que estas funciones existan EXACTAMENTE con este nombre:

def get_risk_status(client: MT5Client) -> dict:
    if mt5 is None:
        return {"error": "MT5 no disponible", "is_ok": True}
    # ... tu lógica original ...
    return {"is_ok": True}

def validate_entry(status: dict) -> tuple[bool, str]:
    # ESTA ES LA FUNCIÓN QUE EL BOT ESTÁ BUSCANDO
    if status.get("error"):
        return False, "MT5 no disponible"
    return True, "OK"

def calculate_lot_size(symbol: str, sl_pips: float, risk_eur: float) -> float:
    return 0.01

def _calculate_open_risk(positions: list[dict]) -> float:
    return 0.0
