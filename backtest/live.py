"""Live trading core — MT5 order execution and FTMO risk management.

Responsabilidades:
  - FTMOState: guarda límites diarios y de drawdown en tiempo real
  - get_lot_size: calcula el tamaño del lote basado en riesgo % y SL en pips
  - get_open_positions: devuelve posiciones abiertas por este bot
  - place_market_order: envía orden a MT5 con SL y TP
  - is_trading_hours: filtra sesiones Londres y Nueva York (UTC)
  - send_telegram / send_telegram_photo: notificaciones push a Telegram
  - generate_trade_chart: gráfico de velas con entry/SL/TP como PNG
  - get_position_pnl: consulta historial MT5 para P&L de posición cerrada
"""

from __future__ import annotations

import io
import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timezone
from typing import Optional

try:
    import MetaTrader5 as mt5
    _MT5_AVAILABLE = True
except ImportError:
    _MT5_AVAILABLE = False

from backtest.engine import PIP_SIZES

logger = logging.getLogger("smc_live")

MAGIC_NUMBER = 20260624


# ── Sesiones de trading (UTC) ──────────────────────────────────────────────────

# Londres:    08:00–16:00 UTC  →  10:00–18:00 España (verano) / 09:00–17:00 (invierno)
# Nueva York: 13:30–22:00 UTC  →  15:30–00:00 España (verano) / 14:30–23:00 (invierno)
SESSIONS_UTC: list[tuple[dtime, dtime, str]] = [
    (dtime(8,  0), dtime(16,  0), "Londres"),
    (dtime(13, 30), dtime(22,  0), "Nueva York"),
]


def is_trading_hours(now_utc: datetime | None = None) -> tuple[bool, str]:
    """Devuelve (True, nombre_sesión) si el momento UTC está en sesión activa."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    if now_utc.weekday() >= 5:
        return False, "fin de semana"
    t = now_utc.time().replace(tzinfo=None)
    for start, end, name in SESSIONS_UTC:
        if start <= t < end:
            return True, name
    return False, "fuera de sesión"


# ── Telegram ───────────────────────────────────────────────────────────────────

def send_telegram(token: str, chat_id: str, text: str) -> bool:
    """Envía mensaje de texto vía Telegram Bot API."""
    if not token or not chat_id:
        return False
    url  = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id":    chat_id,
        "text":       text,
        "parse_mode": "Markdown",
    }).encode()
    try:
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
            if not body.get("ok"):
                logger.warning(f"Telegram sendMessage error: {body}")
                return False
        return True
    except Exception as e:
        logger.warning(f"Telegram send falló: {e}")
        return False


def send_telegram_photo(token: str, chat_id: str, photo_bytes: bytes, caption: str = "") -> bool:
    """Envía imagen PNG con caption a Telegram (multipart/form-data, sin dependencias)."""
    if not token or not chat_id or not photo_bytes:
        return False

    boundary = b"----SMCFTMOBoundary9a3f"

    def _field(name: str, value: str) -> bytes:
        return (
            b"--" + boundary + b"\r\n"
            b'Content-Disposition: form-data; name="' + name.encode() + b'"\r\n\r\n'
            + value.encode("utf-8") + b"\r\n"
        )

    def _file(name: str, filename: str, ctype: str, data: bytes) -> bytes:
        return (
            b"--" + boundary + b"\r\n"
            b'Content-Disposition: form-data; name="' + name.encode()
            + b'"; filename="' + filename.encode() + b'"\r\n'
            b"Content-Type: " + ctype.encode() + b"\r\n\r\n"
            + data + b"\r\n"
        )

    body = (
        _field("chat_id",    chat_id)
        + _field("parse_mode", "Markdown")
        + _field("caption",    caption[:1024])
        + _file("photo", "chart.png", "image/png", photo_bytes)
        + b"--" + boundary + b"--\r\n"
    )

    url     = f"https://api.telegram.org/bot{token}/sendPhoto"
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary.decode()}"}

    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            if not result.get("ok"):
                logger.warning(f"Telegram sendPhoto error: {result}")
                return False
        return True
    except Exception as e:
        logger.warning(f"Telegram sendPhoto falló: {e}")
        return False


# ── Chart generator ────────────────────────────────────────────────────────────

def generate_trade_chart(
    df,                          # pandas DataFrame con columnas OHLCV + time
    symbol:      str,
    direction:   str,            # "LONG" o "SHORT"
    entry_price: float,
    sl:          float,
    tp:          float,
    close_price: float | None = None,   # None = trade abierto
    pnl:         float | None = None,   # P&L realizado (al cerrar)
    n_candles:   int          = 50,
) -> bytes:
    """Genera un gráfico de velas OHLC como PNG bytes.

    - Trade abierto:  muestra entry, SL y TP como líneas horizontales.
    - Trade cerrado:  añade línea de cierre y anotación de ganancia/pérdida.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    plot_df = df.tail(n_candles).reset_index(drop=True)
    n       = len(plot_df)

    # Normalizar nombres de columnas: acepta open/high/low/close y o/h/l/c
    cols = plot_df.columns.tolist()
    _o = "open"  if "open"  in cols else "o"
    _h = "high"  if "high"  in cols else "h"
    _l = "low"   if "low"   in cols else "l"
    _c = "close" if "close" in cols else "c"

    # ── Layout ──────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(12, 6), facecolor="#0d1117")
    ax.set_facecolor("#0d1117")

    # ── Velas ────────────────────────────────────────────────────────────
    for i, row in plot_df.iterrows():
        is_bull = float(row[_c]) >= float(row[_o])
        color   = "#26a69a" if is_bull else "#ef5350"
        lo, hi  = float(row[_l]),  float(row[_h])
        op, cl  = float(row[_o]), float(row[_c])
        body_lo = min(op, cl)
        body_h  = max(abs(cl - op), (hi - lo) * 0.005)   # mínimo visible
        ax.plot([i, i], [lo, hi], color=color, linewidth=0.9, zorder=2)
        ax.bar(i, body_h, bottom=body_lo, width=0.6, color=color, zorder=3)

    # ── Líneas de niveles ─────────────────────────────────────────────────
    x_end   = n + 1
    x_label = n + 0.3

    # Entry
    ax.hlines(entry_price, 0, x_end, colors="#e0e0e0", linewidths=1.5,
              linestyles="--", zorder=5)
    ax.text(x_label, entry_price, f" {entry_price}", color="#e0e0e0",
            va="center", fontsize=7.5, fontweight="bold")

    # SL
    ax.hlines(sl, 0, x_end, colors="#ef5350", linewidths=1.2,
              linestyles=":", zorder=5)
    ax.text(x_label, sl, f" SL  {sl}", color="#ef5350",
            va="center", fontsize=7.5)

    # TP
    ax.hlines(tp, 0, x_end, colors="#26a69a", linewidths=1.2,
              linestyles=":", zorder=5)
    ax.text(x_label, tp, f" TP  {tp}", color="#26a69a",
            va="center", fontsize=7.5)

    # Precio de cierre (si el trade ya cerró)
    if close_price is not None:
        ax.hlines(close_price, 0, x_end, colors="#ffd700", linewidths=2.0,
                  linestyles="-.", zorder=6)
        ax.text(x_label, close_price, f" Cierre  {close_price}", color="#ffd700",
                va="center", fontsize=7.5, fontweight="bold")

        # Sombrear zona entre entry y close
        shade_lo = min(entry_price, close_price)
        shade_hi = max(entry_price, close_price)
        is_win   = (
            (direction == "SHORT" and close_price < entry_price) or
            (direction == "LONG"  and close_price > entry_price)
        )
        shade_color = "#26a69a" if is_win else "#ef5350"
        ax.axhspan(shade_lo, shade_hi, alpha=0.10, color=shade_color, zorder=1)

    # ── P&L badge ────────────────────────────────────────────────────────
    if pnl is not None:
        is_win    = pnl >= 0
        pnl_color = "#26a69a" if is_win else "#ef5350"
        pnl_sign  = "+" if pnl >= 0 else ""
        label     = "GANANCIA" if is_win else "PÉRDIDA"
        ax.text(0.02, 0.96,
                f"{label}:  {pnl_sign}{pnl:.2f} EUR",
                transform=ax.transAxes, fontsize=13, fontweight="bold",
                color=pnl_color, va="top",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="#1a1a2e",
                          edgecolor=pnl_color, linewidth=1.5))

    # ── Título ────────────────────────────────────────────────────────────
    status = "CERRADA" if close_price is not None else "ABIERTA"
    arrow  = "SHORT ⬇" if direction == "SHORT" else "LONG ⬆"
    title_color = "#ef5350" if direction == "SHORT" else "#26a69a"
    ax.set_title(f"{symbol}  ·  {arrow}  ·  [{status}]",
                 color=title_color, fontsize=12, fontweight="bold", pad=8)

    # ── Eje Y: zoom centrado en la zona de trading ───────────────────────
    levels = [entry_price, sl, tp]
    if close_price is not None:
        levels.append(close_price)
    # Restringir las velas al rango relevante (5× la distancia SL→TP)
    trade_range = abs(tp - sl)
    margin      = max(trade_range * 1.5, abs(entry_price - sl) * 2.5)
    y_center    = (max(levels) + min(levels)) / 2
    y_lo        = y_center - margin
    y_hi        = y_center + margin
    # Incluir velas que caigan dentro de esa ventana (para no cortar datos relevantes)
    candle_lo = float(plot_df[_l].min())
    candle_hi = float(plot_df[_h].max())
    y_lo = min(y_lo, candle_lo - margin * 0.1) if candle_lo > y_center - margin * 3 else y_lo
    y_hi = max(y_hi, candle_hi + margin * 0.1) if candle_hi < y_center + margin * 3 else y_hi
    ax.set_ylim(y_lo, y_hi)

    # ── Eje X: etiquetas de tiempo ────────────────────────────────────────
    step       = max(1, n // 8)
    tick_idx   = list(range(0, n, step))
    tick_label = []
    for i in tick_idx:
        t = plot_df["time"].iloc[i]
        try:
            tick_label.append(str(t)[:16])   # "2026-06-24 21:00"
        except Exception:
            tick_label.append(str(i))
    ax.set_xticks(tick_idx)
    ax.set_xticklabels(tick_label, rotation=25, ha="right", fontsize=6.5)

    # ── Estilo ────────────────────────────────────────────────────────────
    ax.tick_params(colors="#888888", labelsize=7)
    for spine in ax.spines.values():
        spine.set_color("#333355")
    ax.set_xlim(-0.5, n + 4.5)
    ax.grid(True, color="#1e2533", linewidth=0.5)
    ax.yaxis.tick_right()
    ax.yaxis.set_tick_params(labelcolor="#aaaaaa", labelsize=7)

    plt.tight_layout(pad=1.2)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ── Forex Factory news filter ─────────────────────────────────────────────────

# Currencies relevantes por símbolo — bloquea si hay noticia de alguna de ellas
_SYMBOL_CURRENCIES: dict[str, tuple[str, ...]] = {
    "EURUSD": ("EUR", "USD"),
    "GBPUSD": ("GBP", "USD"),
    "USDJPY": ("USD", "JPY"),
    "XAUUSD": ("USD",),
    "GOLD":   ("USD",),
    "NAS100": ("USD",),
    "US100":  ("USD",),
    "BTCUSD": ("USD",),
}


def fetch_ff_events(
    currencies: tuple[str, ...] = ("EUR", "USD"),
    impacts:    tuple[str, ...] = ("High",),
    retries:    int             = 3,
) -> list[dict]:
    """Descarga el calendario económico de Forex Factory para esta semana y la próxima.

    Filtra por divisa e impacto. Reintenta con backoff en caso de 429.
    No lanza excepciones — si el fetch falla definitivamente devuelve lo que haya.
    """
    import time as _time

    events: list[dict] = []
    for period in ("thisweek", "nextweek"):
        url = f"https://nfs.faireconomy.media/ff_calendar_{period}.json"
        for attempt in range(1, retries + 1):
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 SMC-FTMO-Bot/1.0"},
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read())
                filtered = [
                    e for e in data
                    if e.get("impact") in impacts
                    and e.get("country") in currencies
                ]
                events.extend(filtered)
                logger.info(
                    f"ForexFactory {period}: {len(filtered)} eventos "
                    f"{'/'.join(impacts)} para {'/'.join(currencies)}"
                )
                break   # éxito — salir del retry loop

            except urllib.error.HTTPError as e:
                if e.code == 404:
                    logger.debug(f"ForexFactory {period}: no disponible aún (404)")
                    break   # 404 = semana no publicada, no reintentar
                if e.code == 429 and attempt < retries:
                    wait = 5 * attempt
                    logger.debug(f"ForexFactory {period}: 429 rate-limit, reintentando en {wait}s...")
                    _time.sleep(wait)
                else:
                    logger.warning(f"ForexFactory fetch ({period}) falló: {e}")
                    break

            except Exception as e:
                logger.warning(f"ForexFactory fetch ({period}) falló: {e}")
                break

    return events


def is_news_blackout(
    events:      list[dict],
    now_utc:     datetime,
    buffer_mins: int = 30,
) -> tuple[bool, str]:
    """Devuelve (True, motivo) si now_utc está dentro de la ventana de una noticia.

    La ventana es [evento - buffer_mins, evento + buffer_mins].
    Devuelve (False, "") si no hay conflicto o si events está vacío.
    """
    from datetime import timedelta

    for event in events:
        try:
            dt_str   = event.get("date", "")
            event_dt = datetime.fromisoformat(dt_str)
            if event_dt.tzinfo is None:
                event_dt = event_dt.replace(tzinfo=timezone.utc)
            else:
                event_dt = event_dt.astimezone(timezone.utc).replace(tzinfo=timezone.utc)

            diff_mins = (event_dt - now_utc).total_seconds() / 60

            if -buffer_mins <= diff_mins <= buffer_mins:
                title   = event.get("title",   "Noticia")
                country = event.get("country", "?")
                if diff_mins > 1:
                    timing = f"en {int(diff_mins)} min"
                elif diff_mins < -1:
                    timing = f"hace {int(abs(diff_mins))} min"
                else:
                    timing = "ahora mismo"
                return True, f"{title} ({country}) — {timing}"

        except Exception:
            continue

    return False, ""


# ── MT5 trade history ──────────────────────────────────────────────────────────

def get_position_pnl(ticket: int) -> dict | None:
    """Consulta el historial de MT5 para obtener P&L y precio de cierre de una posición.

    Returns:
        Dict con {profit, close_price, close_time} o None si no se encuentra.
    """
    if not _MT5_AVAILABLE:
        return None

    from datetime import timedelta
    from_dt = datetime(2020, 1, 1, tzinfo=timezone.utc)
    to_dt   = datetime.now(timezone.utc) + timedelta(hours=2)

    deals = mt5.history_deals_get(position=ticket)
    if not deals:
        logger.debug(f"No se encontraron deals para ticket #{ticket}")
        return None

    total_profit = sum(d.profit for d in deals)

    # Deal de salida: entry == DEAL_ENTRY_OUT (1)
    exit_deals = [d for d in deals if d.entry == 1]
    if not exit_deals:
        return {"profit": total_profit, "close_price": None, "close_time": None}

    last_exit = exit_deals[-1]
    return {
        "profit":      round(total_profit, 2),
        "close_price": last_exit.price,
        "close_time":  datetime.fromtimestamp(last_exit.time, tz=timezone.utc),
    }


# ── FTMO Risk Guard ────────────────────────────────────────────────────────────

@dataclass
class FTMOState:
    """Rastrea límites FTMO en tiempo real."""

    initial_balance:  float
    currency:         str   = "EUR"
    daily_limit_pct:  float = 0.03
    max_loss_pct:     float = 0.10
    start_equity:     float | None = None

    daily_start_balance: float = field(init=False)
    _trading_day:        date  = field(init=False)
    blocked:             bool  = field(init=False, default=False)
    block_reason:        str   = field(init=False, default="")

    def __post_init__(self) -> None:
        self.daily_start_balance = (
            self.start_equity if self.start_equity is not None else self.initial_balance
        )
        self._trading_day = date.today()

    @property
    def daily_limit(self) -> float:
        return round(self.initial_balance * self.daily_limit_pct, 2)

    @property
    def max_loss_floor(self) -> float:
        return round(self.initial_balance * (1.0 - self.max_loss_pct), 2)

    def check(self, equity: float) -> bool:
        if self.blocked:
            return False
        today = date.today()
        if today != self._trading_day:
            self._trading_day        = today
            self.daily_start_balance = equity
            logger.info(f"Nuevo día de trading. Equity inicio: {equity:,.2f} {self.currency}")

        daily_loss = self.daily_start_balance - equity
        if daily_loss >= self.daily_limit:
            self.blocked      = True
            self.block_reason = (
                f"Límite diario: -{daily_loss:,.2f} {self.currency} "
                f"(límite: {self.daily_limit:,.2f})"
            )
            logger.error(f"⛔ BLOQUEO DIARIO — {self.block_reason}")
            return False

        if equity <= self.max_loss_floor:
            overall = (self.initial_balance - equity) / self.initial_balance * 100
            self.blocked      = True
            self.block_reason = (
                f"Drawdown FTMO: {equity:,.2f} ≤ suelo {self.max_loss_floor:,.2f} "
                f"({overall:.1f}% pérdida total)"
            )
            logger.error(f"⛔ BLOQUEO DRAWDOWN — {self.block_reason}")
            return False

        return True

    def status_line(self, equity: float) -> str:
        daily_pnl    = equity - self.daily_start_balance
        overall_dd   = (self.initial_balance - equity) / self.initial_balance * 100
        daily_margin = self.daily_limit - max(0.0, self.daily_start_balance - equity)
        return (
            f"Equity: {equity:,.2f} {self.currency}  |  "
            f"Day P&L: {daily_pnl:+,.2f} (margen: {daily_margin:,.0f})  |  "
            f"DD total: {overall_dd:.2f}%  |  "
            f"Suelo FTMO: {self.max_loss_floor:,.2f}"
        )


# ── Lot size calculator ────────────────────────────────────────────────────────

def get_lot_size(symbol: str, sl_pips: float, risk_pct: float, balance: float) -> float:
    if not _MT5_AVAILABLE:
        raise ImportError("MetaTrader5 no instalado.")

    info = mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError(f"Símbolo '{symbol}' no encontrado: {mt5.last_error()}")

    pip_size     = PIP_SIZES.get(symbol, 0.0001)
    risk_amount  = balance * risk_pct / 100.0
    sl_ticks     = (sl_pips * pip_size) / info.trade_tick_size
    sl_value_lot = sl_ticks * info.trade_tick_value

    if sl_value_lot <= 0:
        raise ValueError(f"sl_value_lot inválido para {symbol}")

    raw_lot = risk_amount / sl_value_lot
    step    = info.volume_step
    lot     = round(round(raw_lot / step) * step, 8)
    lot     = max(info.volume_min, min(info.volume_max, lot))

    logger.debug(f"Lot {symbol}: riesgo={risk_amount:.2f} raw={raw_lot:.4f} → {lot}")
    return lot


# ── Position helpers ───────────────────────────────────────────────────────────

def get_open_positions(symbol: str) -> list:
    if not _MT5_AVAILABLE:
        return []
    positions = mt5.positions_get(symbol=symbol)
    if positions is None:
        return []
    return [p for p in positions if p.magic == MAGIC_NUMBER]


def close_position(ticket: int, symbol: str, volume: float, direction: str) -> bool:
    if not _MT5_AVAILABLE:
        return False
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return False
    close_type  = mt5.ORDER_TYPE_SELL if direction == "LONG" else mt5.ORDER_TYPE_BUY
    close_price = tick.bid             if direction == "LONG" else tick.ask
    request = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": volume,
        "type": close_type, "position": ticket, "price": close_price,
        "deviation": 20, "magic": MAGIC_NUMBER, "comment": "SMC-FTMO close",
        "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    ok = result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
    if ok:
        logger.info(f"Posición #{ticket} cerrada @ {close_price}")
    else:
        code = result.retcode if result else "None"
        logger.error(f"Error cerrando #{ticket}: [{code}]")
    return ok


# ── Order placement ────────────────────────────────────────────────────────────

def place_market_order(
    symbol:    str,
    direction: str,
    lot:       float,
    sl_pips:   float,
    rr:        float,
    dry_run:   bool = False,
    comment:   str  = "SMC-FTMO",
) -> Optional[dict]:
    if not _MT5_AVAILABLE:
        raise ImportError("MetaTrader5 no instalado.")

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return None

    info     = mt5.symbol_info(symbol)
    pip_size = PIP_SIZES.get(symbol, 0.0001)
    sl_dist  = sl_pips * pip_size
    tp_dist  = sl_dist * rr
    digits   = info.digits

    if direction == "SHORT":
        order_type = mt5.ORDER_TYPE_SELL
        price      = round(tick.bid, digits)
        sl         = round(price + sl_dist, digits)
        tp         = round(price - tp_dist, digits)
    else:
        order_type = mt5.ORDER_TYPE_BUY
        price      = round(tick.ask, digits)
        sl         = round(price - sl_dist, digits)
        tp         = round(price + tp_dist, digits)

    spread_pips = round((tick.ask - tick.bid) / pip_size, 1)
    logger.info(
        f"{'[DRY RUN] ' if dry_run else ''}{direction} {symbol}  lot={lot}  "
        f"entry={price}  SL={sl}  TP={tp}  spread={spread_pips}p"
    )

    if dry_run:
        return {"dry_run": True, "symbol": symbol, "direction": direction,
                "lot": lot, "price": price, "sl": sl, "tp": tp}

    for fill_mode in (mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN):
        request = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol,
            "volume": lot, "type": order_type, "price": price,
            "sl": sl, "tp": tp, "deviation": 20, "magic": MAGIC_NUMBER,
            "comment": comment[:31], "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": fill_mode,
        }
        result = mt5.order_send(request)
        if result is None:
            continue
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"Orden ejecutada: #{result.order}  {direction} {lot} lots @ {result.price}")
            return {"ticket": result.order, "price": result.price,
                    "sl": sl, "tp": tp, "retcode": result.retcode,
                    "direction": direction, "lot": lot}
        if result.retcode == 10030:
            continue
        logger.error(f"Orden rechazada [{result.retcode}]: {result.comment}")
        return None

    logger.error("No se encontró modo de llenado compatible.")
    return None
