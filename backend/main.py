"""
SMC Signal Receiver — FastAPI webhook + MT5 risk management.

Fases implementadas:
  Phase 1.3 — POST /webhook: recibe señales SMC de TradingView → Telegram
  Phase 3   — GET /account, GET /positions, POST /order, DELETE /positions/{ticket},
               POST /emergency-close: gestión de cuenta MT5

Ejecutar:
  uvicorn backend.main:app --reload --port 8000

Webhook URL en TradingView:
  http://TU_IP:8000/webhook?secret=TU_WEBHOOK_SECRET
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from loguru import logger

from backend.config import settings
from backend.models import SMCSignal, OrderRequest
from backend.telegram_bot import send_signal_alert, send_order_placed

# MT5 imports — sólo se usan si mt5_configured es True
from backend.mt5.client import MT5Client
from backend.mt5.risk import get_risk_status, validate_entry, calculate_lot_size
from backend.mt5.orders import place_market_order, close_position, close_all_positions
from backend.mt5.monitor import run_monitor

# Loguru: consola + archivo rotativo diario (tech-stack.md)
logger.add(
    "logs/signals.log",
    rotation="00:00",
    retention="7 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
)

# ── MT5 client (global, inicializado en lifespan) ─────────────────────────────
mt5_client = MT5Client()


@asynccontextmanager
async def lifespan(app: FastAPI):
    monitor_task: Optional[asyncio.Task] = None

    if settings.mt5_configured:
        connected = await asyncio.to_thread(
            mt5_client.connect,
            settings.mt5_login,
            settings.mt5_password,
            settings.mt5_server,
            settings.mt5_path,
        )
        if connected:
            monitor_task = asyncio.create_task(
                run_monitor(mt5_client, settings.mt5_monitor_interval)
            )
            logger.info("MT5 conectado — monitor iniciado (intervalo={}s)", settings.mt5_monitor_interval)
        else:
            logger.warning("MT5 no pudo conectar — endpoints /account y /order no disponibles")
    else:
        logger.info("MT5 no configurado — modo webhook+Telegram únicamente")

    logger.info("SMC Signal Receiver v{} iniciado", app.version)
    yield

    if monitor_task:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

    if settings.mt5_configured:
        await asyncio.to_thread(mt5_client.disconnect)

    logger.info("SMC Signal Receiver detenido")


app = FastAPI(
    title="SMC Signal Receiver",
    version="0.3.0",
    description="Webhook SMC de TradingView → Telegram + gestión de cuenta MT5",
    lifespan=lifespan,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _check_secret(secret: str) -> None:
    if settings.webhook_secret and secret != settings.webhook_secret:
        raise HTTPException(status_code=403, detail="Token inválido")


def _require_mt5() -> None:
    if not settings.mt5_configured:
        raise HTTPException(status_code=503, detail="MT5 no configurado — añadir MT5_* en .env")


# ── Phase 1.3 — TradingView webhook ───────────────────────────────────────────

@app.post("/webhook", summary="Recibe señal SMC desde TradingView")
async def receive_signal(
    signal: SMCSignal,
    secret: str = Query(default=""),
):
    """
    Payload de confluence_score.pine:
        {"action":"LONG","symbol":"EURUSD","tf":"60","score":5,"price":1.08450,
         "choch":true,"ob":true,"liq":true,"fvg":true,"pd":true,"bos":false,"sd":false}

    Siempre responde 200 — TradingView desactiva webhooks con errores consecutivos (history.md).
    """
    _check_secret(secret)

    logger.info(
        "Señal recibida | {} {} {} score={}/7 precio={}",
        signal.action, signal.symbol, signal.timeframe_label, signal.score, signal.price,
    )

    sent = await send_signal_alert(signal)
    if not sent:
        logger.warning("Telegram no disponible para esta señal")

    return {
        "status":        "ok",
        "action":        signal.action,
        "symbol":        signal.symbol,
        "timeframe":     signal.timeframe_label,
        "score":         signal.score,
        "telegram_sent": sent,
    }


# ── Phase 3 — MT5 account endpoints ───────────────────────────────────────────

@app.get("/account", summary="Estado actual de la cuenta MT5")
async def account_status():
    """Retorna balance, equity, P&L diario y estado de riesgo vs límites FTMO."""
    _require_mt5()
    status = await asyncio.to_thread(get_risk_status, mt5_client)
    if status.get("error"):
        raise HTTPException(status_code=503, detail=status["error"])
    return status


@app.get("/positions", summary="Posiciones abiertas en MT5")
async def open_positions():
    """Lista todas las posiciones abiertas con ticket, símbolo, volumen, P&L y SL/TP."""
    _require_mt5()
    positions = await asyncio.to_thread(mt5_client.positions)
    return {"count": len(positions), "positions": positions}


@app.post("/order", summary="Coloca una orden de mercado en MT5")
async def place_order(
    order: OrderRequest,
    secret: str = Query(default=""),
):
    """
    Flujo semi-automático (roadmap.md — no autonomous trading):
      1. Valida reglas FTMO (pérdida diaria, equity, riesgo abierto)
      2. Calcula el tamaño de posición (1% del balance, capado al presupuesto diario)
      3. Coloca la orden en MT5
      4. Envía confirmación a Telegram

    Requiere aprobación humana explícita — el usuario llama a este endpoint
    después de revisar la señal de TradingView en Telegram.
    """
    _check_secret(secret)
    _require_mt5()

    # Pre-entry FTMO validation
    status = await asyncio.to_thread(get_risk_status, mt5_client)
    allowed, reason = validate_entry(status)
    if not allowed:
        logger.warning("Orden rechazada por FTMO: {}", reason)
        return {"status": "rejected", "reason": reason}

    # Auto-sizing: 1% del balance, nunca excede el presupuesto diario restante
    risk_eur = min(
        status["balance"] * 0.01,
        status["budget_left"],
    )
    lot_size = await asyncio.to_thread(
        calculate_lot_size, order.symbol, order.sl_pips, risk_eur
    )

    if lot_size <= 0.0:
        return {
            "status": "rejected",
            "reason": "Tamaño de posición calculado es 0 — SL demasiado amplio o riesgo insuficiente",
        }

    result = await asyncio.to_thread(
        place_market_order,
        order.symbol,
        order.action,
        lot_size,
        order.sl_pips,
        order.rr,
        order.comment,
    )

    if result.success:
        await send_order_placed(result)

    return {
        "status":      "ok" if result.success else "failed",
        "ticket":      result.ticket,
        "symbol":      result.symbol,
        "action":      result.action,
        "volume":      result.volume,
        "entry_price": result.entry_price,
        "sl":          result.sl,
        "tp":          result.tp,
        "risk_eur":    result.risk_eur,
        "error":       result.error,
    }


@app.delete("/positions/{ticket}", summary="Cierra una posición específica")
async def close_one_position(
    ticket: int,
    secret: str = Query(default=""),
):
    """Cierra la posición identificada por ticket."""
    _check_secret(secret)
    _require_mt5()
    success = await asyncio.to_thread(close_position, ticket)
    return {"status": "ok" if success else "failed", "ticket": ticket}


@app.post("/emergency-close", summary="Cierra TODAS las posiciones (emergencia)")
async def emergency_close(secret: str = Query(default="")):
    """
    Cierre de emergencia: cierra TODAS las posiciones abiertas inmediatamente.
    Usar sólo si el monitor automático no lo hizo y la equity está en riesgo.
    """
    _check_secret(secret)
    _require_mt5()
    logger.critical("EMERGENCY CLOSE solicitado manualmente vía API")
    summary = await asyncio.to_thread(close_all_positions)
    return {"status": "executed", **summary}


# ── Health check ───────────────────────────────────────────────────────────────

@app.get("/health", summary="Health check")
async def health_check():
    return {
        "status":         "healthy",
        "version":        app.version,
        "mt5_configured": settings.mt5_configured,
    }
