"""Background monitor: polls MT5 every N seconds and enforces FTMO limits.

State machine: OK → Warning → Blocked → Critical → Emergency
Alerts fire only on state TRANSITIONS to avoid Telegram spam.
Emergency close fires ONCE (guarded by _state["emergency_triggered"]).
"""

import asyncio

from loguru import logger

from backend.mt5.client import MT5Client
from backend.mt5.risk import (
    EQUITY_MINIMUM,
    SYS_DAILY_LIMIT,
    get_risk_status,
)
from backend.mt5.orders import close_all_positions
from backend.telegram_bot import send_risk_alert


# In-memory state — resets when the server restarts (acceptable for daily use)
_state: dict = {
    "is_warning":          False,
    "is_blocked":          False,
    "is_critical":         False,
    "emergency_triggered": False,
}


async def _poll(client: MT5Client) -> None:
    """Single monitoring cycle."""
    status = await asyncio.to_thread(get_risk_status, client)

    if status.get("error"):
        logger.debug("Monitor: MT5 no disponible — {}", status["error"])
        return

    now_warn  = status["is_warning"]
    now_block = status["is_blocked"]
    now_crit  = status["is_critical"]

    # ── State-change alerts (Telegram) ───────────────────────────────────────
    if now_warn and not _state["is_warning"]:
        logger.warning(
            "FTMO PRECAUCIÓN | pérdida_diaria={:.2f}€ equity={:.2f}€",
            status["daily_loss"], status["equity"],
        )
        await send_risk_alert(status, level="warning")

    if now_block and not _state["is_blocked"]:
        logger.error(
            "FTMO BLOQUEADO | pérdida_diaria={:.2f}€ equity={:.2f}€",
            status["daily_loss"], status["equity"],
        )
        await send_risk_alert(status, level="blocked")

    if now_crit and not _state["is_critical"]:
        logger.critical(
            "FTMO CRÍTICO | pérdida_diaria={:.2f}€ equity={:.2f}€",
            status["daily_loss"], status["equity"],
        )
        await send_risk_alert(status, level="critical")

    # ── Recovery alerts ───────────────────────────────────────────────────────
    if _state["is_blocked"] and not now_block and not now_crit:
        logger.info("Monitor: recuperación — saliendo de estado BLOQUEADO")

    # Update state
    _state["is_warning"]  = now_warn
    _state["is_blocked"]  = now_block
    _state["is_critical"] = now_crit

    # ── Emergency close: equity below FTMO absolute floor ────────────────────
    if status["equity"] < EQUITY_MINIMUM and not _state["emergency_triggered"]:
        logger.critical(
            "CIERRE DE EMERGENCIA | equity={:.2f}€ < mínimo FTMO {:.2f}€",
            status["equity"], EQUITY_MINIMUM,
        )
        _state["emergency_triggered"] = True
        summary = await asyncio.to_thread(close_all_positions)
        await send_risk_alert(status, level="emergency", close_summary=summary)


async def run_monitor(client: MT5Client, interval: int = 30) -> None:
    """Async loop: polls MT5 account every `interval` seconds.

    Run as a background asyncio task from FastAPI's lifespan.
    Cancelled automatically on server shutdown.
    """
    logger.info("Monitor MT5 iniciado (intervalo={}s)", interval)
    while True:
        try:
            await _poll(client)
        except asyncio.CancelledError:
            logger.info("Monitor MT5 detenido")
            return
        except Exception as exc:
            logger.error("Monitor exception (no fatal): {}", exc)
        await asyncio.sleep(interval)
