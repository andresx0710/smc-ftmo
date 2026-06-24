"""Telegram notifications: señales SMC, estado de cuenta MT5 y órdenes ejecutadas."""

from typing import Optional

import httpx
from loguru import logger

from backend.config import settings
from backend.models import SMCSignal

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

# Checklist pre-entrada FTMO 10k EUR (ftmo-rules.md)
_FTMO_CHECKLIST = (
    "▪ Riesgo máx: <b>100 EUR (1%)</b> por operación\n"
    "▪ R:R mínimo <b>1:2</b> → TP ≥ +200 EUR\n"
    "▪ P&L diario > <b>-300 EUR</b> → verificar en MT5\n"
    "▪ Equity total > <b>9.200 EUR</b> → verificar en MT5\n"
    "▪ Sin noticias de alto impacto en los próximos 15 min\n"
    "▪ Definir SL <i>antes</i> de calcular el tamaño de posición"
)


# ── Low-level send ─────────────────────────────────────────────────────────────

async def _send(text: str) -> bool:
    """Envía un mensaje HTML a Telegram. Nunca lanza excepciones (history.md)."""
    url = TELEGRAM_API.format(token=settings.telegram_bot_token)
    payload = {
        "chat_id":                  settings.telegram_chat_id,
        "text":                     text,
        "parse_mode":               "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            return True
    except httpx.HTTPStatusError as e:
        logger.error("Telegram HTTP {}: {}", e.response.status_code, e.response.text)
    except httpx.RequestError as e:
        logger.error("Telegram connection error: {}", e)
    return False


# ── SMC signal alert (Phase 1) ────────────────────────────────────────────────

def _build_signal_message(signal: SMCSignal) -> str:
    emoji     = "🟢" if signal.action == "LONG" else "🔴"
    direction = "LONG ▲" if signal.action == "LONG" else "SHORT ▼"

    conditions_lines = []
    for name, weight, active in signal.active_conditions:
        mark = "✅" if active else "❌"
        conditions_lines.append(f"{mark} {name} <i>({weight})</i>")

    price_fmt = (
        f"{signal.price:.5f}"
        if "USD" in signal.symbol and "XAU" not in signal.symbol
        else f"{signal.price:.2f}"
    )

    return (
        f"{emoji} <b>SMC — {direction} | {signal.symbol} | {signal.timeframe_label}</b>\n"
        f"\n"
        f"📊 Score: <b>{signal.score}/7</b>  <code>{signal.score_bar}</code>\n"
        f"\n"
        f"<b>Condiciones:</b>\n"
        + "\n".join(conditions_lines) +
        f"\n"
        f"\n"
        f"💵 Precio: <code>{price_fmt}</code>\n"
        f"\n"
        f"📋 <b>Checklist FTMO (10k EUR):</b>\n"
        f"{_FTMO_CHECKLIST}"
    )


async def send_signal_alert(signal: SMCSignal) -> bool:
    """Envía la señal SMC al Telegram configurado.

    Siempre retorna sin lanzar — TradingView espera 200 independientemente
    del estado de Telegram (history.md).
    """
    ok = await _send(_build_signal_message(signal))
    if ok:
        logger.info(
            "Telegram OK | {} {} {} score={}/7",
            signal.action, signal.symbol, signal.timeframe_label, signal.score,
        )
    return ok


# ── MT5 risk alerts (Phase 3) ─────────────────────────────────────────────────

_RISK_ICONS = {
    "warning":   "⚠️",
    "blocked":   "🔴",
    "critical":  "🚨",
    "emergency": "🚨🚨",
}
_RISK_TITLES = {
    "warning":   "PRECAUCIÓN — LÍMITE PRÓXIMO",
    "blocked":   "SISTEMA BLOQUEADO",
    "critical":  "RIESGO CRÍTICO FTMO",
    "emergency": "CIERRE DE EMERGENCIA EJECUTADO",
}
_RISK_ACTIONS = {
    "warning":   "Operar con máxima cautela. Reducir tamaño o detener.",
    "blocked":   "❌ <b>NO abrir nuevas posiciones hoy.</b>",
    "critical":  "🛑 <b>DETENER TRADING INMEDIATAMENTE.</b>",
    "emergency": "⚠️ <b>Todas las posiciones fueron cerradas automáticamente.</b>",
}


async def send_risk_alert(
    status: dict,
    level: str,
    close_summary: Optional[dict] = None,
) -> bool:
    """Alerta de estado de cuenta FTMO.

    level: "warning" | "blocked" | "critical" | "emergency"
    """
    icon   = _RISK_ICONS.get(level, "⚠️")
    title  = _RISK_TITLES.get(level, level.upper())
    action = _RISK_ACTIONS.get(level, "")

    pnl_sign = "+" if status["daily_pnl"] >= 0 else ""

    lines = [
        f"{icon} <b>FTMO — {title}</b>\n",
        f"💵 Equity: <b>{status['equity']:.2f} EUR</b>",
        f"📉 P&L hoy: <b>{pnl_sign}{status['daily_pnl']:.2f} EUR</b>",
        f"📊 Pérdida diaria: <b>{status['daily_loss']:.2f} / {status['sys_limit']:.0f} EUR</b>",
        f"📈 Drawdown total: <b>{status['total_drawdown']:.2f} / 1.000 EUR</b>",
        f"📂 Posiciones abiertas: {status['open_positions']}",
        "",
        action,
    ]

    if close_summary:
        lines += [
            "",
            "<b>Resultado del cierre de emergencia:</b>",
            f"✅ Cerradas: {close_summary['closed']}",
            f"❌ Fallidas: {close_summary['failed']}",
            f"💶 P&L realizado: {close_summary['total_pnl']:.2f} EUR",
            "",
            "Revisar la cuenta en MT5 y contactar con FTMO si es necesario.",
        ]

    ok = await _send("\n".join(lines))
    if ok:
        logger.info("Telegram risk alert | level={}", level)
    return ok


# ── Order execution notification (Phase 3) ────────────────────────────────────

async def send_order_placed(result) -> bool:
    """Notifica que una orden fue ejecutada en MT5."""
    direction = "LONG ▲" if result.action == "BUY" else "SHORT ▼"
    emoji     = "🟢" if result.action == "BUY" else "🔴"

    text = (
        f"{emoji} <b>ORDEN EJECUTADA — {direction} {result.symbol}</b>\n"
        f"\n"
        f"🎫 Ticket: <code>#{result.ticket}</code>\n"
        f"💵 Entrada: <code>{result.entry_price}</code>\n"
        f"🛑 Stop Loss: <code>{result.sl}</code>\n"
        f"🎯 Take Profit: <code>{result.tp}</code>\n"
        f"📊 Volumen: <b>{result.volume} lotes</b>\n"
        f"💶 Riesgo: <b>{result.risk_eur:.2f} EUR</b>\n"
        f"\n"
        f"✅ Confirmar en MT5 que la orden fue aceptada."
    )
    ok = await _send(text)
    if ok:
        logger.info("Telegram order notification | ticket={}", result.ticket)
    return ok
