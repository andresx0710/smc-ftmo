"""FTMO risk validation and position sizing.

All monetary values in EUR (account currency).
Rules sourced from .claude/ftmo-rules.md.
"""

import math
from typing import Optional

import MetaTrader5 as mt5
from loguru import logger

from backend.mt5.client import MT5Client

# ── FTMO 10k EUR limits (ftmo-rules.md) ──────────────────────────────────────
INITIAL_BALANCE  = 10_000.0   # EUR — starting capital
MAX_DAILY_LOSS   = 500.0      # EUR — FTMO absolute daily limit (5%)
SYS_DAILY_LIMIT  = 300.0      # EUR — system conservative limit (3%), buffer of 200
MAX_TOTAL_LOSS   = 1_000.0    # EUR — max total drawdown allowed by FTMO (10%)
RISK_PER_TRADE   = 0.01       # 1% of balance per trade
MIN_RR           = 2.0        # Minimum risk:reward ratio
MAX_OPEN_RISK    = 200.0      # EUR — max simultaneous open risk (2 positions × 1%)
EQUITY_WARN      = 9_200.0    # EUR — internal warning (200 EUR buffer above FTMO min)
EQUITY_MINIMUM   = 9_000.0    # EUR — FTMO absolute minimum; account lost if below
WARN_THRESHOLD   = SYS_DAILY_LIMIT * 0.60   # 180 EUR — 60% of system limit


def get_risk_status(client: MT5Client) -> dict:
    """Full account risk snapshot vs FTMO limits.

    Returns a dict that's safe to serialise to JSON and pass to Telegram.
    On MT5 error, returns {"error": "<reason>"}.
    """
    info      = client.account_info()
    positions = client.positions()
    realized  = client.today_realized_pnl()

    if info is None:
        return {"error": "MT5 no conectado o account_info() falló"}

    float_pnl  = sum(p["profit"] for p in positions)
    daily_pnl  = realized + float_pnl
    daily_loss = max(0.0, -daily_pnl)
    open_risk  = _calculate_open_risk(positions)
    equity     = info["equity"]
    total_dd   = max(0.0, INITIAL_BALANCE - equity)

    is_warning  = daily_loss >= WARN_THRESHOLD
    is_blocked  = daily_loss >= SYS_DAILY_LIMIT
    is_critical = daily_loss >= MAX_DAILY_LOSS * 0.80 or equity < EQUITY_WARN

    return {
        # Account
        "balance":        info["balance"],
        "equity":         equity,
        "free_margin":    info["free_margin"],
        # Daily P&L breakdown
        "daily_pnl":      daily_pnl,
        "daily_loss":     daily_loss,
        "realized_pnl":   realized,
        "float_pnl":      float_pnl,
        # Risk exposure
        "open_risk":      open_risk,
        "open_positions": len(positions),
        "total_drawdown": total_dd,
        # Budget remaining for new trades today
        "budget_left": max(0.0, SYS_DAILY_LIMIT - daily_loss - open_risk),
        # Status flags (exclusive from least to most severe)
        "is_ok":       not (is_warning or is_blocked or is_critical),
        "is_warning":  is_warning and not is_blocked,
        "is_blocked":  is_blocked and not is_critical,
        "is_critical": is_critical,
        # Reference limits
        "sys_limit":   SYS_DAILY_LIMIT,
        "ftmo_limit":  MAX_DAILY_LOSS,
        "equity_min":  EQUITY_MINIMUM,
    }


def validate_entry(status: dict) -> tuple[bool, str]:
    """Pre-entry FTMO checklist. Returns (allowed, reason).

    Call this before placing any order.
    """
    if status.get("error"):
        return False, "MT5 no disponible — no se puede validar la cuenta"

    if status["is_critical"]:
        return False, (
            f"CRÍTICO: pérdida diaria {status['daily_loss']:.0f} EUR "
            f"o equity {status['equity']:.0f} EUR por debajo del umbral"
        )
    if status["is_blocked"]:
        return False, (
            f"BLOQUEADO: pérdida diaria {status['daily_loss']:.0f} EUR "
            f"supera el límite del sistema ({SYS_DAILY_LIMIT:.0f} EUR)"
        )
    if status["open_risk"] >= MAX_OPEN_RISK:
        return False, (
            f"Riesgo abierto {status['open_risk']:.0f} EUR "
            f"alcanza el máximo permitido ({MAX_OPEN_RISK:.0f} EUR)"
        )
    if status["budget_left"] < 50.0:
        return False, (
            f"Presupuesto diario restante insuficiente: {status['budget_left']:.0f} EUR"
        )

    return True, "OK"


def calculate_lot_size(symbol: str, sl_pips: float, risk_eur: float) -> float:
    """Universal lot-size calculator using MT5's own tick values.

    Works correctly for both EURUSD (5 decimals, 1 pip = 10 ticks)
    and XAUUSD (2 decimals, 1 'pip' = 100 ticks).

    Args:
        symbol:   MT5 symbol name ("EURUSD", "XAUUSD")
        sl_pips:  Stop loss in pips (EURUSD) or dollars (XAUUSD)
        risk_eur: Maximum risk in EUR for this trade

    Returns:
        Lot size rounded DOWN to symbol's volume step.
    """
    info = mt5.symbol_info(symbol)
    if info is None:
        logger.error("Symbol {} no encontrado en MT5", symbol)
        return 0.0

    # Pip = 10 ticks for 5-digit brokers (EURUSD, GBPUSD...)
    # Pip = 100 ticks for 2-digit (XAUUSD where "pip" = $1 movement)
    pip_ticks = 10 if info.digits in (3, 5) else 100

    # EUR value of 1 pip for 1 standard lot
    pip_value_per_lot = pip_ticks * info.trade_tick_value

    if pip_value_per_lot == 0.0:
        logger.error("pip_value_per_lot == 0 para {} — comprobar tick values en MT5", symbol)
        return 0.0

    sl_cost_per_lot = sl_pips * pip_value_per_lot
    raw_lot = risk_eur / sl_cost_per_lot

    # Round DOWN to volume step — never exceed the risk budget
    step = info.volume_step
    lot  = math.floor(raw_lot / step) * step

    # Enforce symbol min/max
    lot = max(info.volume_min, min(lot, info.volume_max))
    return round(lot, 2)


# ── Private helpers ───────────────────────────────────────────────────────────

def _calculate_open_risk(positions: list[dict]) -> float:
    """Estimates EUR at risk for each open position using MT5 tick data."""
    total = 0.0
    for p in positions:
        if p["sl"] == 0.0:
            # No SL set — use a conservative 1% placeholder
            total += INITIAL_BALANCE * RISK_PER_TRADE
            continue

        info = mt5.symbol_info(p["symbol"])
        if info is None:
            total += INITIAL_BALANCE * RISK_PER_TRADE
            continue

        sl_distance = abs(p["open_price"] - p["sl"])
        sl_ticks    = sl_distance / info.trade_tick_size
        risk        = sl_ticks * info.trade_tick_value * p["volume"]
        total      += risk

    return round(total, 2)
