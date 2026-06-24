"""
SMC-FTMO Live Trader — CLI entry point.

Uso:
  python -m backtest.run_live --symbol EURUSD --tf-chain D1 H1 M15 M5 \\
    --min-score 5 --sl-pips 20 --rr 3.0 --only-short \\
    --balance 10000 --currency EUR --interval 60 \\
    --tg-token 123456:ABC... --tg-chat-id 987654321

Parar: Ctrl+C
"""

import argparse
import logging
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Cargar .env desde la raíz del proyecto (sin dependencias externas)
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

_LIVE_BARS: dict = {
    "M1": 500, "M5": 500, "M15": 300, "M30": 200,
    "H1": 150, "H4": 100, "D1": 80,
}


# ── CLI ────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m backtest.run_live",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    g = p.add_argument_group("Instrumento")
    g.add_argument("--symbol",   default="EURUSD")
    g.add_argument("--tf-chain", nargs="+", default=["D1", "H1", "M15", "M5"],
                   dest="tf_chain", metavar="TF")

    g = p.add_argument_group("Señales SMC")
    g.add_argument("--min-score",   type=int,   default=5,    dest="min_score")
    g.add_argument("--sl-pips",     type=float, default=20.0, dest="sl_pips")
    g.add_argument("--rr",          type=float, default=3.0)
    g.add_argument("--only-short",  action="store_true", dest="only_short")
    g.add_argument("--only-long",   action="store_true", dest="only_long")
    g.add_argument("--window",      type=int, default=10)
    g.add_argument("--ob-lookback", type=int, default=10, dest="ob_lookback")

    g = p.add_argument_group("Cuenta")
    g.add_argument("--balance",     type=float, default=None)
    g.add_argument("--currency",    type=str,   default="EUR")
    g.add_argument("--risk-pct",    type=float, default=1.0,  dest="risk_pct")
    g.add_argument("--daily-limit", type=float, default=None, dest="daily_limit_pct")

    g = p.add_argument_group("Ejecución")
    g.add_argument("--interval",          type=int, default=60)
    g.add_argument("--dry-run",           action="store_true", dest="dry_run")
    g.add_argument("--max-positions",     type=int, default=1, dest="max_positions")
    g.add_argument("--no-session-filter", action="store_true", dest="no_session_filter")
    g.add_argument("--use-forex-factory", action="store_true", dest="use_ff",
                   help="Bloquea nuevas entradas si hay noticias rojas en Forex Factory")
    g.add_argument("--news-buffer-mins",  type=int, default=30, dest="news_buffer",
                   help="Minutos de margen antes/después de una noticia (default: 30)")

    g = p.add_argument_group("MT5")
    g.add_argument("--mt5-login",    type=int, default=0)
    g.add_argument("--mt5-password", type=str, default="")
    g.add_argument("--mt5-server",   type=str, default="")
    g.add_argument("--mt5-path",     type=str, default="")

    g = p.add_argument_group("Telegram")
    g.add_argument("--tg-token",   type=str,
                   default=os.environ.get("TELEGRAM_BOT_TOKEN", ""), dest="tg_token",
                   help="Token del bot (default: var TELEGRAM_BOT_TOKEN del .env)")
    g.add_argument("--tg-chat-id", type=str,
                   default=os.environ.get("TELEGRAM_CHAT_ID", ""), dest="tg_chat_id",
                   help="Chat ID (default: var TELEGRAM_CHAT_ID del .env)")

    g = p.add_argument_group("Salida")
    g.add_argument("--log-file",  type=str, default=None, dest="log_file")
    g.add_argument("--log-level", type=str, default="INFO", dest="log_level",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    return p.parse_args()


# ── Logging ────────────────────────────────────────────────────────────────────

def _setup_logging(log_file: str | None, symbol: str, level: str) -> logging.Logger:
    os.makedirs("logs", exist_ok=True)
    if log_file is None:
        ts = datetime.now().strftime("%Y%m%d")
        log_file = f"logs/smc_live_{symbol}_{ts}.log"
    fmt    = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s",
                               datefmt="%Y-%m-%d %H:%M:%S")
    logger = logging.getLogger("smc_live")
    logger.setLevel(getattr(logging, level))
    logger.handlers.clear()
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    return logger


# ── Telegram helpers ───────────────────────────────────────────────────────────

def _notify(token: str, chat_id: str, text: str) -> None:
    from backtest.live import send_telegram
    if token and chat_id:
        send_telegram(token, chat_id, text)


def _notify_photo(token: str, chat_id: str, chart: bytes, caption: str) -> None:
    from backtest.live import send_telegram_photo
    if token and chat_id and chart:
        send_telegram_photo(token, chat_id, chart, caption)


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    args   = _parse_args()
    symbol = args.symbol.upper()

    tf_chain    = [tf.upper() for tf in args.tf_chain]
    entry_tf    = tf_chain[-1]
    chain_label = "→".join(tf_chain)
    dir_tag     = (" [SOLO SHORT]" if args.only_short
                   else " [SOLO LONG]" if args.only_long else "")

    logger = _setup_logging(args.log_file, symbol, args.log_level)

    tg_token   = args.tg_token
    tg_chat_id = args.tg_chat_id
    tg_enabled = bool(tg_token and tg_chat_id)

    logger.info("═" * 64)
    logger.info(f"SMC-FTMO Live Trader  |  {symbol}  |  {chain_label}{dir_tag}")
    logger.info(f"score≥{args.min_score}  SL={args.sl_pips}p  RR=1:{args.rr}  riesgo={args.risk_pct}%")
    if args.dry_run:
        logger.info("*** DRY RUN — NO se ejecutan órdenes reales ***")
    if args.no_session_filter:
        logger.info("*** Filtro de sesiones DESACTIVADO ***")
    logger.info(f"Telegram: {'activado' if tg_enabled else 'desactivado'}")
    logger.info("═" * 64)

    # ── Imports ───────────────────────────────────────────────────────────
    try:
        import MetaTrader5 as mt5
    except ImportError:
        logger.error("MetaTrader5 no instalado.")
        sys.exit(1)

    from backtest.data     import download_multi_tf_chain
    from backtest.detector import detect_signals_chain, DEFAULT_MTF_PARAMS, MINTICKS
    from backtest.live     import (
        FTMOState, get_lot_size, get_open_positions, place_market_order,
        is_trading_hours, SESSIONS_UTC,
        generate_trade_chart, get_position_pnl,
        fetch_ff_events, is_news_blackout, _SYMBOL_CURRENCIES,
    )

    # ── Mostrar sesiones en hora España ──────────────────────────────────
    logger.info("Sesiones activas (UTC | España verano CEST | España invierno CET):")
    for start, end, name in SESSIONS_UTC:
        cest_s = (start.hour + 2) % 24; cest_e = (end.hour + 2) % 24
        cet_s  = (start.hour + 1) % 24; cet_e  = (end.hour + 1) % 24
        logger.info(
            f"  {name:<12} UTC {start.strftime('%H:%M')}-{end.strftime('%H:%M')}  |  "
            f"Verano {cest_s:02d}:{start.minute:02d}-{cest_e:02d}:{end.minute:02d}  |  "
            f"Invierno {cet_s:02d}:{start.minute:02d}-{cet_e:02d}:{end.minute:02d}"
        )

    # ── Connect MT5 ───────────────────────────────────────────────────────
    mt5_kwargs: dict = {}
    if args.mt5_login:
        mt5_kwargs = {"login": args.mt5_login, "password": args.mt5_password,
                      "server": args.mt5_server}
        if args.mt5_path:
            mt5_kwargs["path"] = args.mt5_path

    if not mt5.initialize(**mt5_kwargs):
        logger.error(f"MT5 initialize() falló: {mt5.last_error()}")
        sys.exit(1)

    acc = mt5.account_info()
    if acc is None:
        logger.error("No se pudo obtener account_info.")
        mt5.shutdown(); sys.exit(1)

    balance  = args.balance if args.balance else acc.balance
    currency = args.currency.upper()

    logger.info(f"MT5 conectado  |  {acc.server}  |  Login: {acc.login}")
    logger.info(f"Balance: {balance:,.2f} {currency}  |  Equity: {acc.equity:,.2f}")

    # ── FTMO Guard ────────────────────────────────────────────────────────
    ftmo = FTMOState(
        initial_balance = balance,
        currency        = currency,
        daily_limit_pct = (args.daily_limit_pct / 100.0 if args.daily_limit_pct else 0.03),
        start_equity    = acc.equity,
    )
    logger.info(
        f"FTMO límites — diario: -{ftmo.daily_limit:,.2f} {currency}  |  "
        f"Suelo DD: {ftmo.max_loss_floor:,.2f} {currency}"
    )

    _notify(tg_token, tg_chat_id,
        f"*SMC-FTMO arrancado* — {symbol}{dir_tag}\n"
        f"Balance: `{balance:,.0f} {currency}`  |  Equity: `{acc.equity:,.0f} {currency}`\n"
        f"Suelo FTMO: `{ftmo.max_loss_floor:,.0f} {currency}`  |  "
        f"Límite diario: `-{ftmo.daily_limit:,.0f} {currency}`"
    )

    # ── Detector params ───────────────────────────────────────────────────
    mintick = MINTICKS.get(symbol, 0.00001)
    detector_params = {
        **DEFAULT_MTF_PARAMS,
        "mintick":     mintick,
        "window":      args.window,
        "ob_lookback": args.ob_lookback,
    }

    entry_bars    = _LIVE_BARS.get(entry_tf, 300)
    last_bar_time = None
    last_off_hours = False
    cycle         = 0

    # Tracking de posiciones abiertas por este bot {ticket: snap_dict}
    pos_snapshots: dict[int, dict] = {}

    # ── Forex Factory calendar ────────────────────────────────────────────
    ff_events:    list = []
    ff_last_fetch: date | None = None
    ff_currencies = _SYMBOL_CURRENCIES.get(symbol, ("USD",))

    if args.use_ff:
        logger.info(
            f"Forex Factory activado — divisas: {'/'.join(ff_currencies)}  "
            f"buffer: ±{args.news_buffer} min"
        )
        ff_events      = fetch_ff_events(ff_currencies)
        ff_last_fetch  = date.today()
        logger.info(f"  {len(ff_events)} noticias rojas cargadas para esta/próxima semana")

    logger.info(f"Loop iniciado — cada {args.interval}s (Ctrl+C para detener)")

    # ── Main loop ─────────────────────────────────────────────────────────
    while True:
        cycle += 1
        try:
            # ── 1. Account info ───────────────────────────────────────────
            acc = mt5.account_info()
            if acc is None:
                logger.warning("MT5 desconectado — reintentando en 30s...")
                time.sleep(30)
                mt5.initialize(**mt5_kwargs)
                continue

            equity = acc.equity

            # ── 2. Filtro de sesión ───────────────────────────────────────
            if not args.no_session_filter:
                now_utc              = datetime.now(timezone.utc)
                in_session, sess_name = is_trading_hours(now_utc)
                if not in_session:
                    if not last_off_hours:
                        hora_esp = datetime.now().strftime("%H:%M")
                        logger.info(
                            f"Fuera de sesión ({sess_name})  |  "
                            f"UTC: {now_utc.strftime('%H:%M')}  |  "
                            f"España: {hora_esp}  |  Bot inactivo"
                        )
                        last_off_hours = True
                    time.sleep(args.interval)
                    continue
                else:
                    if last_off_hours:
                        hora_esp = datetime.now().strftime("%H:%M")
                        logger.info(
                            f"Sesión {sess_name} abierta  |  "
                            f"UTC: {now_utc.strftime('%H:%M')}  |  España: {hora_esp}"
                        )
                        _notify(tg_token, tg_chat_id,
                            f"*Sesion {sess_name} abierta*  —  Bot activo\n"
                            f"Hora España: {hora_esp}"
                        )
                    last_off_hours = False

            # ── 3. Refresco diario del calendario FF ─────────────────────
            if args.use_ff and ff_last_fetch != date.today():
                logger.info("Refrescando calendario Forex Factory (nuevo día)...")
                ff_events     = fetch_ff_events(ff_currencies)
                ff_last_fetch = date.today()
                logger.info(f"  {len(ff_events)} noticias rojas cargadas")

            # ── 4. FTMO check ─────────────────────────────────────────────
            if not ftmo.check(equity):
                _notify(tg_token, tg_chat_id, f"*⛔ BLOQUEADO:* {ftmo.block_reason}")
                logger.error(f"⛔ TRADING BLOQUEADO: {ftmo.block_reason}")
                time.sleep(60)
                continue

            if cycle % 5 == 0:
                logger.info(ftmo.status_line(equity))

            # ── 4. Fetch live data ────────────────────────────────────────
            try:
                chain_data = download_multi_tf_chain(
                    symbol=symbol, tf_chain=tf_chain,
                    n_bars=entry_bars, cache_dir="backtest/data", force_refresh=True,
                )
            except Exception as e:
                logger.warning(f"Error descargando datos: {e}")
                time.sleep(args.interval)
                continue

            df      = chain_data[entry_tf]
            htf_dfs = [chain_data[tf] for tf in tf_chain[:-1]]

            if len(df) < 50:
                logger.warning(f"Datos insuficientes ({len(df)} barras).")
                time.sleep(args.interval)
                continue

            # ── 5. Detectar posiciones cerradas ───────────────────────────
            # Comparamos las posiciones que teníamos tracked vs las que MT5 reporta abiertas
            if pos_snapshots:
                current_tickets = {p.ticket for p in get_open_positions(symbol)}
                for ticket, snap in list(pos_snapshots.items()):
                    if ticket in current_tickets:
                        continue   # sigue abierta

                    # Posición cerrada — obtener P&L desde historial MT5
                    pnl_info    = get_position_pnl(ticket)
                    pnl         = pnl_info["profit"]      if pnl_info else None
                    close_price = pnl_info["close_price"] if pnl_info else None
                    close_time  = pnl_info["close_time"]  if pnl_info else None

                    # Determinar motivo de cierre
                    pip_size    = 0.0001
                    if close_price is not None:
                        if abs(close_price - snap["sl"]) < pip_size * 2:
                            motivo = "🔴 SL alcanzado"
                        elif abs(close_price - snap["tp"]) < pip_size * 2:
                            motivo = "🟢 TP alcanzado"
                        else:
                            motivo = "⚪ Cierre manual"
                    else:
                        motivo = "—"

                    hora_esp = datetime.now().strftime("%H:%M")
                    is_win   = pnl is not None and pnl >= 0
                    emoji    = "✅" if is_win else "❌"
                    result   = "GANANCIA" if is_win else "PÉRDIDA"
                    pnl_str  = f"+{pnl:.2f} {currency}" if (pnl and pnl >= 0) else f"{pnl:.2f} {currency}" if pnl else "N/D"

                    logger.info(
                        f"POSICIÓN CERRADA #{ticket}  {snap['direction']} {symbol}  "
                        f"{motivo}  P&L: {pnl_str}"
                    )

                    caption = (
                        f"{emoji} *ORDEN CERRADA — {symbol}*\n"
                        f"Dirección: `{'VENTA (SHORT)' if snap['direction'] == 'SHORT' else 'COMPRA (LONG)'}`\n"
                        f"Lote: `{snap['lot']}`  |  Ticket: `#{ticket}`\n"
                        f"Entrada: `{snap['entry']}`\n"
                        f"Cierre: `{close_price}`  ←  {motivo}\n"
                        f"*Resultado: {pnl_str}*\n"
                        f"Equity actual: `{equity:,.2f} {currency}`\n"
                        f"España: {hora_esp}"
                    )

                    try:
                        chart = generate_trade_chart(
                            df          = df,
                            symbol      = symbol,
                            direction   = snap["direction"],
                            entry_price = snap["entry"],
                            sl          = snap["sl"],
                            tp          = snap["tp"],
                            close_price = close_price,
                            pnl         = pnl,
                        )
                        _notify_photo(tg_token, tg_chat_id, chart, caption)
                    except Exception as e:
                        logger.warning(f"Error generando gráfico de cierre: {e}")
                        _notify(tg_token, tg_chat_id, caption)

                    del pos_snapshots[ticket]

            # ── 6. Nueva vela cerrada ─────────────────────────────────────
            completed_time = df["time"].iloc[-2]
            if completed_time == last_bar_time:
                logger.debug(f"Sin nueva vela {entry_tf}. Esperando {args.interval}s")
                time.sleep(args.interval)
                continue

            last_bar_time = completed_time
            logger.info(f"── Vela {entry_tf} cerrada: {completed_time} ──")

            # ── 7. Detectar señales ───────────────────────────────────────
            signals_df = detect_signals_chain(df, htf_dfs, detector_params)
            signals_df["score_bull"] *= signals_df["gate_bull"].astype(int)
            signals_df["score_bear"] *= signals_df["gate_bear"].astype(int)
            if args.only_short:
                signals_df["score_bull"] = 0
            if args.only_long:
                signals_df["score_bear"] = 0

            last_sig   = signals_df.iloc[-2]
            score_bull = int(last_sig["score_bull"])
            score_bear = int(last_sig["score_bear"])

            logger.info(f"Señal — LONG={score_bull}  SHORT={score_bear}  (umbral: {args.min_score})")

            # ── 8. Filtro posición abierta ────────────────────────────────
            open_pos = get_open_positions(symbol)
            if len(open_pos) >= args.max_positions:
                logger.info(f"Posición abierta: {[p.ticket for p in open_pos]} — omitiendo señal")
                time.sleep(args.interval)
                continue

            # ── 9. Selección de dirección ─────────────────────────────────
            direction: str | None = None
            active_score: int     = 0

            if score_bear >= args.min_score and score_bull >= args.min_score:
                if score_bear >= score_bull:
                    direction, active_score = "SHORT", score_bear
                else:
                    direction, active_score = "LONG", score_bull
            elif score_bear >= args.min_score:
                direction, active_score = "SHORT", score_bear
            elif score_bull >= args.min_score:
                direction, active_score = "LONG", score_bull

            if direction is None:
                logger.info(f"Sin señal válida (LONG={score_bull}, SHORT={score_bear} < {args.min_score})")
                time.sleep(args.interval)
                continue

            logger.info(f"SEÑAL {direction}  score={active_score}/7")

            # ── 10. Filtro Forex Factory ──────────────────────────────────
            if args.use_ff and ff_events:
                now_utc = datetime.now(timezone.utc)
                blocked, reason = is_news_blackout(ff_events, now_utc, args.news_buffer)
                if blocked:
                    logger.info(
                        f"NOTICIA ROJA — ejecución bloqueada  [{reason}]  "
                        f"(buffer ±{args.news_buffer}min)"
                    )
                    time.sleep(args.interval)
                    continue

            # ── 11. Lot size ──────────────────────────────────────────────
            try:
                lot = get_lot_size(symbol, args.sl_pips, args.risk_pct, acc.balance)
            except Exception as e:
                logger.error(f"Error calculando lote: {e}")
                time.sleep(args.interval)
                continue

            risk_eur = acc.balance * args.risk_pct / 100

            # ── 12. Place order ───────────────────────────────────────────
            result = place_market_order(
                symbol=symbol, direction=direction, lot=lot,
                sl_pips=args.sl_pips, rr=args.rr,
                dry_run=args.dry_run, comment=f"SMC s{active_score} {entry_tf}",
            )

            hora_esp = datetime.now().strftime("%H:%M")

            if result is None:
                logger.error("Fallo al ejecutar la orden.")
                _notify(tg_token, tg_chat_id,
                    f"*ERROR ejecutando orden*\n{direction} {symbol}  lot={lot}")

            elif result.get("dry_run"):
                logger.info(
                    f"[DRY RUN] {direction} {lot} lots {symbol}  "
                    f"@ {result['price']}  SL={result['sl']}  TP={result['tp']}"
                )

            else:
                ticket = result["ticket"]
                price  = result["price"]
                sl_val = result["sl"]
                tp_val = result["tp"]
                arrow  = "⬇️" if direction == "SHORT" else "⬆️"
                tipo   = "VENTA (SHORT)" if direction == "SHORT" else "COMPRA (LONG)"

                logger.info(f"ORDEN ABIERTA #{ticket}  {direction}  @ {price}  SL={sl_val}  TP={tp_val}")

                # Guardar snapshot para detectar el cierre después
                pos_snapshots[ticket] = {
                    "direction": direction,
                    "lot":       lot,
                    "entry":     price,
                    "sl":        sl_val,
                    "tp":        tp_val,
                }

                caption = (
                    f"{arrow} *ORDEN ABIERTA — {symbol}*\n"
                    f"Dirección: `{tipo}`\n"
                    f"Lote: `{lot}`  |  Score: `{active_score}/7`\n"
                    f"Entrada: `{price}`\n"
                    f"Stop Loss: `{sl_val}` ({args.sl_pips:.0f}p)\n"
                    f"Take Profit: `{tp_val}` ({args.sl_pips * args.rr:.0f}p)\n"
                    f"Riesgo: `{risk_eur:.0f} {currency}`  |  RR `1:{args.rr}`\n"
                    f"Ticket: `#{ticket}`  |  España: {hora_esp}"
                )

                try:
                    chart = generate_trade_chart(
                        df=df, symbol=symbol, direction=direction,
                        entry_price=price, sl=sl_val, tp=tp_val,
                    )
                    _notify_photo(tg_token, tg_chat_id, chart, caption)
                except Exception as e:
                    logger.warning(f"Error generando gráfico de apertura: {e}")
                    _notify(tg_token, tg_chat_id, caption)

        except KeyboardInterrupt:
            logger.info("Detenido por el usuario (Ctrl+C)")
            _notify(tg_token, tg_chat_id, f"*SMC-FTMO detenido* — {symbol}")
            break

        except Exception as exc:
            logger.error(f"Error en ciclo {cycle}: {exc}", exc_info=True)
            time.sleep(30)
            continue

        time.sleep(args.interval)

    mt5.shutdown()
    logger.info("MT5 desconectado. Bot detenido.")


if __name__ == "__main__":
    main()
