"""MT5 order placement and position management.

All order placement goes through place_market_order() which:
  1. Validates the symbol is visible in Market Watch
  2. Gets the current spread-aware price (ask for BUY, bid for SELL)
  3. Calculates SL and TP from pip distance
  4. Sends the order and returns a structured result

close_position() and close_all_positions() are used by the emergency logic
in monitor.py when equity drops below the FTMO floor.
"""

import math
from dataclasses import dataclass
from typing import Optional

import MetaTrader5 as mt5
from loguru import logger


@dataclass
class OrderResult:
    success:     bool
    ticket:      Optional[int]
    symbol:      str
    action:      str          # "BUY" | "SELL"
    volume:      float        # lots
    entry_price: float
    sl:          float
    tp:          float
    risk_eur:    float        # estimated risk in account currency
    comment:     str
    error:       Optional[str] = None


def place_market_order(
    symbol:   str,
    action:   str,           # "BUY" or "SELL"
    volume:   float,         # lots
    sl_pips:  float,         # stop loss in pips
    rr:       float = 2.0,   # risk:reward (1:2 minimum — ftmo-rules.md)
    comment:  str = "SMC",
) -> OrderResult:
    """Places a market order with FTMO-compliant SL and TP.

    TP is derived from sl_pips × rr so R:R ≥ 1:2 is always enforced.
    """
    info = mt5.symbol_info(symbol)
    if info is None:
        return _err(symbol, action, volume, comment, f"Symbol {symbol} no encontrado en MT5")

    # Make symbol visible if it's not in Market Watch
    if not info.visible:
        if not mt5.symbol_select(symbol, True):
            return _err(symbol, action, volume, comment, f"No se pudo seleccionar {symbol}")

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return _err(symbol, action, volume, comment, "No se pudo obtener el tick actual")

    # Pip size in price terms
    pip_ticks    = 10 if info.digits in (3, 5) else 100
    pip_distance = pip_ticks * info.trade_tick_size    # price distance of 1 pip
    tp_pips      = sl_pips * rr

    if action == "BUY":
        price      = tick.ask
        sl         = round(price - sl_pips * pip_distance, info.digits)
        tp         = round(price + tp_pips * pip_distance, info.digits)
        order_type = mt5.ORDER_TYPE_BUY
    else:
        price      = tick.bid
        sl         = round(price + sl_pips * pip_distance, info.digits)
        tp         = round(price - tp_pips * pip_distance, info.digits)
        order_type = mt5.ORDER_TYPE_SELL

    # Estimated risk (SL ticks × tick value × lots)
    sl_ticks = sl_pips * pip_ticks
    risk_eur = round(sl_ticks * info.trade_tick_value * volume, 2)

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       volume,
        "type":         order_type,
        "price":        price,
        "sl":           sl,
        "tp":           tp,
        "comment":      comment[:31],   # MT5 comment limit
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        if result is None:
            err_msg = str(mt5.last_error())
        else:
            err_msg = f"retcode={result.retcode} ({result.comment})"
        logger.error("Orden fallida | {} {} | {}", action, symbol, err_msg)
        return OrderResult(
            success=False, ticket=None, symbol=symbol, action=action,
            volume=volume, entry_price=price, sl=sl, tp=tp,
            risk_eur=risk_eur, comment=comment, error=err_msg,
        )

    logger.info(
        "Orden ejecutada | {} {} vol={} precio={} sl={} tp={} ticket={} riesgo={}€",
        action, symbol, volume, price, sl, tp, result.order, risk_eur,
    )
    return OrderResult(
        success=True, ticket=result.order, symbol=symbol, action=action,
        volume=volume, entry_price=price, sl=sl, tp=tp,
        risk_eur=risk_eur, comment=comment,
    )


def close_position(ticket: int) -> bool:
    """Closes a specific position by ticket number."""
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        logger.warning("Posición {} no encontrada para cerrar", ticket)
        return False

    pos  = positions[0]
    info = mt5.symbol_info(pos.symbol)
    tick = mt5.symbol_info_tick(pos.symbol)

    if info is None or tick is None:
        logger.error("No se pudo obtener datos de {} para cerrar ticket={}", pos.symbol, ticket)
        return False

    close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
    price      = tick.bid if pos.type == mt5.POSITION_TYPE_BUY else tick.ask

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "position":     ticket,
        "symbol":       pos.symbol,
        "volume":       pos.volume,
        "type":         close_type,
        "price":        price,
        "comment":      "SMC-close",
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        err = str(mt5.last_error()) if result is None else result.comment
        logger.error("Fallo al cerrar ticket={}: {}", ticket, err)
        return False

    logger.info("Posición cerrada | ticket={} symbol={} P&L={:.2f}", ticket, pos.symbol, pos.profit)
    return True


def close_all_positions() -> dict:
    """Emergency: closes ALL open positions immediately.

    Used by monitor.py when equity drops below FTMO absolute minimum.
    Returns a summary dict with closed/failed counts and total P&L.
    """
    positions = mt5.positions_get()
    if not positions:
        logger.info("close_all_positions(): no hay posiciones abiertas")
        return {"closed": 0, "failed": 0, "total_pnl": 0.0}

    closed, failed, total_pnl = 0, 0, 0.0
    for pos in positions:
        total_pnl += pos.profit
        if close_position(pos.ticket):
            closed += 1
        else:
            failed += 1

    logger.warning(
        "Cierre de emergencia completado | cerradas={} fallidas={} P&L={:.2f}€",
        closed, failed, total_pnl,
    )
    return {"closed": closed, "failed": failed, "total_pnl": round(total_pnl, 2)}


# ── Private helpers ───────────────────────────────────────────────────────────

def _err(symbol, action, volume, comment, msg) -> OrderResult:
    logger.error("OrderResult error | {}: {}", symbol, msg)
    return OrderResult(
        success=False, ticket=None, symbol=symbol, action=action,
        volume=volume, entry_price=0.0, sl=0.0, tp=0.0,
        risk_eur=0.0, comment=comment, error=msg,
    )
