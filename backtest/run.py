"""
SMC-FTMO Backtester — CLI entry point.

Uso básico (single TF):
  python -m backtest.run --symbol EURUSD --tf M15 --bars 5000

Cadena MTF completa (cualquier combinación):
  python -m backtest.run --symbol EURUSD --tf-chain D1 H1 M15 --bars 20000
  python -m backtest.run --symbol XAUUSD --tf-chain D1 H4 H1 M15 --bars 20000
  python -m backtest.run --symbol EURUSD --tf-chain D1 H4 H1 M15 M5 --bars 30000

Modo MTF rápido (D1+H1+TF_entrada, equivalente a --tf-chain D1 H1 TF):
  python -m backtest.run --symbol EURUSD --tf M15 --mtf --bars 20000

Cuenta personalizada:
  python -m backtest.run --symbol EURUSD --tf M15 --balance 20000 --currency USD

Con parámetros de señal:
  python -m backtest.run --symbol EURUSD --tf-chain D1 H1 M15 \\
         --min-score 5 --sl-pips 10 --rr 2.5 --risk-pct 1.0

Refrescar caché:
  python -m backtest.run --symbol EURUSD --tf M15 --refresh

Ayuda:
  python -m backtest.run --help
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

VALID_TFS = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m backtest.run",
        description="SMC-FTMO Backtester — simula señales SMC sobre datos históricos",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    # ── Data source ──────────────────────────────────────────────────────
    g_data = p.add_argument_group("Datos")
    g_data.add_argument("--symbol",   default="EURUSD", help="Par a testear (default: EURUSD)")
    g_data.add_argument("--tf",       default="H1", choices=VALID_TFS,
                        help="Timeframe de entrada (default: H1). Ignorado si se usa --tf-chain.")
    g_data.add_argument("--tf-chain", nargs="+", default=None, dest="tf_chain",
                        metavar="TF",
                        help="Cadena MTF completa, de mayor a menor TF (último = TF de entrada).\n"
                             "Ej: --tf-chain D1 H1 M15  |  --tf-chain D1 H4 H1 M15 M5")
    g_data.add_argument("--bars",     type=int, default=5000,
                        help="Barras del TF de entrada (default: 5000)")
    g_data.add_argument("--input",    type=str, default=None,
                        help="CSV del TF de entrada en lugar de MT5 (solo single-TF)")
    g_data.add_argument("--refresh",  action="store_true",
                        help="Forzar re-descarga aunque haya caché")
    g_data.add_argument("--cache-dir", default="backtest/data", dest="cache_dir",
                        help="Directorio de CSVs cacheados (default: backtest/data)")

    # ── MT5 credentials ──────────────────────────────────────────────────
    g_mt5 = p.add_argument_group("MT5 (opcional si se provee --input o hay caché)")
    g_mt5.add_argument("--mt5-login",    type=int, default=0)
    g_mt5.add_argument("--mt5-password", type=str, default="")
    g_mt5.add_argument("--mt5-server",   type=str, default="")
    g_mt5.add_argument("--mt5-path",     type=str, default="")

    # ── MTF shortcuts ────────────────────────────────────────────────────
    g_mtf = p.add_argument_group("Modo MTF rápido (alternativa a --tf-chain)")
    g_mtf.add_argument("--mtf", action="store_true",
                       help="Activar MTF D1+H1+TF (equivale a --tf-chain D1 H1 <--tf>)")
    g_mtf.add_argument("--no-d1-gate", action="store_true", dest="no_d1_gate",
                       help="Desactivar filtro de estructura del TF macro (permite señales contra tendencia)")
    g_mtf.add_argument("--h1-window", type=int, default=10, dest="h1_window",
                       help="Barras en TF de confirmación que CHoCH permanece activo (default: 10)")

    # ── Account ──────────────────────────────────────────────────────────
    g_acct = p.add_argument_group("Cuenta (si no se especifica, el bot pregunta al inicio)")
    g_acct.add_argument("--balance",  type=float, default=None,
                        help="Capital inicial (default: te lo pregunta o 10000)")
    g_acct.add_argument("--currency", type=str,   default=None,
                        help="Divisa de la cuenta: EUR, USD, GBP... (default: te lo pregunta o EUR)")
    g_acct.add_argument("--daily-limit", type=float, default=None, dest="daily_limit",
                        help="Límite de pérdida diaria del sistema (default: 3%% del balance)")

    # ── Signal parameters ────────────────────────────────────────────────
    g_sig = p.add_argument_group("Señales SMC")
    g_sig.add_argument("--min-score", type=int,   default=4,  dest="min_score",
                       help="Score mínimo para generar señal 0-7 (default: 4)")
    g_sig.add_argument("--window",    type=int,   default=10,
                       help="Barras que una condición permanece activa (default: 10)")
    g_sig.add_argument("--ob-lookback", type=int, default=10, dest="ob_lookback",
                       help="Barras de lookback para Order Blocks (default: 10)")
    g_sig.add_argument("--only-short", action="store_true", dest="only_short",
                       help="Solo operar en SHORT (anula todas las señales LONG)")
    g_sig.add_argument("--only-long",  action="store_true", dest="only_long",
                       help="Solo operar en LONG (anula todas las señales SHORT)")

    # ── Trade parameters ─────────────────────────────────────────────────
    g_trade = p.add_argument_group("Parámetros de operación")
    g_trade.add_argument("--sl-pips",  type=float, default=20.0, dest="sl_pips",
                         help="Stop Loss en pips (default: 20)")
    g_trade.add_argument("--rr",       type=float, default=2.0,
                         help="Risk:Reward ratio — TP = SL × rr (default: 2.0)")
    g_trade.add_argument("--risk-pct", type=float, default=1.0, dest="risk_pct",
                         help="Riesgo por operación como %% del balance (default: 1.0)")

    # ── Output ───────────────────────────────────────────────────────────
    g_out = p.add_argument_group("Salida")
    g_out.add_argument("--output-dir", default="backtest/output", dest="output_dir")
    g_out.add_argument("--no-plot",    action="store_true", dest="no_plot")
    g_out.add_argument("--no-csv",     action="store_true", dest="no_csv")
    g_out.add_argument("--no-periodic", action="store_true", dest="no_periodic",
                       help="No mostrar ni guardar el desglose semanal/mensual/anual")

    return p.parse_args()


def _prompt_account(args: argparse.Namespace) -> None:
    """Interactive prompt for balance and currency if not provided via CLI."""
    print("\n─" * 50)
    print("  \U0001f4b0 CONFIGURACIÓN DE CUENTA")
    print("─" * 50)

    if args.balance is None:
        raw = input("  Capital inicial [10000]: ").strip()
        args.balance = float(raw) if raw else 10_000.0

    if args.currency is None:
        raw = input("  Divisa de la cuenta [EUR]: ").strip().upper()
        args.currency = raw if raw else "EUR"

    print(f"  → {args.balance:,.2f} {args.currency}")
    print()


def main() -> None:
    args = _parse_args()

    # ── Account setup ─────────────────────────────────────────────────────
    if args.balance is None or args.currency is None:
        if sys.stdin.isatty():
            _prompt_account(args)
        else:
            args.balance  = args.balance  or 10_000.0
            args.currency = args.currency or "EUR"

    args.balance  = args.balance  or 10_000.0
    args.currency = (args.currency or "EUR").upper()

    # ── Lazy imports ──────────────────────────────────────────────────────
    from backtest.data     import get_ohlcv, download_multi_tf_chain
    from backtest.detector import (detect_signals, detect_signals_chain,
                                   detect_signals_mtf,
                                   DEFAULT_PARAMS, DEFAULT_MTF_PARAMS, MINTICKS)
    from backtest.engine   import run_backtest, EngineParams, PIP_SIZES
    from backtest.metrics  import (calculate_metrics, print_report, save_trades_csv,
                                   save_equity_plot, calculate_periodic_metrics,
                                   print_periodic_report)

    # ── Resolve TF chain ──────────────────────────────────────────────────
    if args.tf_chain:
        tf_chain  = [tf.upper() for tf in args.tf_chain]
        timeframe = tf_chain[-1]
        use_chain = True
    elif args.mtf:
        timeframe = args.tf.upper()
        tf_chain  = ["D1", "H1", timeframe]
        use_chain = True
    else:
        timeframe = args.tf.upper()
        tf_chain  = [timeframe]
        use_chain = False

    symbol   = args.symbol.upper()
    mintick  = MINTICKS.get(symbol, 0.00001)
    pip_size = PIP_SIZES.get(symbol, 0.0001)
    mt5_kw   = dict(login=args.mt5_login, password=args.mt5_password,
                    server=args.mt5_server, mt5_path=args.mt5_path)

    chain_label = "→".join(tf_chain) if use_chain else timeframe

    print(f"\n{'─' * 50}")
    print(f"  SMC-FTMO Backtester  |  {symbol}  |  {chain_label}")
    print(f"  Balance: {args.balance:,.0f} {args.currency}  |  Score mín: {args.min_score}  "
          f"|  SL: {args.sl_pips}p  |  R:R 1:{args.rr}")
    print(f"{'─' * 50}")

    # ── 1. Load data ──────────────────────────────────────────────────────
    if use_chain and args.input is None:
        chain_data = download_multi_tf_chain(
            symbol=symbol, tf_chain=tf_chain, n_bars=args.bars,
            cache_dir=args.cache_dir, force_refresh=args.refresh, **mt5_kw,
        )
        df      = chain_data[timeframe]
        htf_dfs = [chain_data[tf] for tf in tf_chain[:-1]]
    else:
        df = get_ohlcv(
            symbol=symbol, timeframe=timeframe, n_bars=args.bars,
            cache_dir=args.cache_dir, force_refresh=args.refresh,
            csv_path=args.input, **mt5_kw,
        )
        htf_dfs = []

    if len(df) < 100:
        print(f"❌ Datos insuficientes ({len(df)} barras). Mínimo 100 barras requeridas.")
        sys.exit(1)

    # ── 2. Detect signals ─────────────────────────────────────────────────
    detector_params = {
        **(DEFAULT_MTF_PARAMS if use_chain else DEFAULT_PARAMS),
        "mintick":     mintick,
        "window":      args.window,
        "ob_lookback": args.ob_lookback,
        "h1_window":   args.h1_window,
    }

    if use_chain:
        print(f"\n⏳ Detección MTF ({chain_label})...")
        signals_df = detect_signals_chain(df, htf_dfs, detector_params)

        if args.no_d1_gate:
            print("  D1 gate: OFF (desactivado por --no-d1-gate)")
            signals_df["gate_bull"] = True
            signals_df["gate_bear"] = True
            signals_df["score_bull"] = signals_df["score_bull"].clip(upper=7)
            signals_df["score_bear"] = signals_df["score_bear"].clip(upper=7)
        else:
            print(f"  Gate ({tf_chain[0]}): ON")
            signals_df["score_bull"] = (
                signals_df["score_bull"] * signals_df["gate_bull"].astype(int)
            )
            signals_df["score_bear"] = (
                signals_df["score_bear"] * signals_df["gate_bear"].astype(int)
            )
    else:
        print(f"\n⏳ Detección SMC single-TF ({len(df):,} barras)...")
        signals_df = detect_signals(df, detector_params)

    if args.only_short:
        signals_df["score_bull"] = 0
    if args.only_long:
        signals_df["score_bear"] = 0

    n_bull = (signals_df["score_bull"] >= args.min_score).sum()
    n_bear = (signals_df["score_bear"] >= args.min_score).sum()
    mode   = "MTF " + chain_label if use_chain else timeframe
    dir_tag = " [SOLO SHORT]" if args.only_short else " [SOLO LONG]" if args.only_long else ""
    print(f"  Señales LONG: {n_bull}  |  SHORT: {n_bear}  (score ≥ {args.min_score}){dir_tag}")

    if n_bull + n_bear == 0:
        print(f"❌ Sin señales con score ≥ {args.min_score}. Prueba con --min-score {args.min_score - 1}")
        sys.exit(1)

    # ── 3. Run backtest ───────────────────────────────────────────────────
    print(f"\n⏳ Simulando operaciones...")
    engine_params = EngineParams(
        symbol          = symbol,
        min_score       = args.min_score,
        sl_pips         = args.sl_pips,
        rr              = args.rr,
        risk_pct        = args.risk_pct,
        initial_balance = args.balance,
        currency        = args.currency,
        ftmo_daily_limit= args.daily_limit,   # None → auto 3%
        pip_size        = pip_size,
    )
    trades = run_backtest(df, signals_df, engine_params)
    closed = [t for t in trades if t.outcome in ("WIN", "LOSS")]
    print(f"  Operaciones simuladas: {len(trades)}  |  Cerradas: {len(closed)}")

    if not closed:
        print("❌ Sin operaciones cerradas. Aumentar --bars o reducir --min-score.")
        sys.exit(1)

    # ── 4. Metrics + report ───────────────────────────────────────────────
    metrics = calculate_metrics(trades, initial_balance=args.balance)

    date_range = (
        str(df["time"].iloc[0].date())  if hasattr(df["time"].iloc[0],  "date") else str(df["time"].iloc[0]),
        str(df["time"].iloc[-1].date()) if hasattr(df["time"].iloc[-1], "date") else str(df["time"].iloc[-1]),
    )
    report_params = {
        "sl_pips":  args.sl_pips,
        "rr":       args.rr,
        "risk_pct": args.risk_pct,
        "min_score":args.min_score,
        "mode":     mode,
    }
    print_report(
        metrics, symbol, timeframe, len(df), report_params, date_range,
        initial_balance=args.balance, currency=args.currency,
    )

    # ── 5. Periodic analysis ──────────────────────────────────────────────
    if not args.no_periodic:
        periodic = calculate_periodic_metrics(trades, args.balance, args.currency)
        print_periodic_report(periodic, args.currency)

    # ── 6. Save outputs ───────────────────────────────────────────────────
    os.makedirs(args.output_dir, exist_ok=True)
    chain_tag = "_".join(tf_chain) if use_chain and len(tf_chain) > 1 else timeframe
    base_name = (
        f"{symbol}_{chain_tag}_score{args.min_score}"
        f"_sl{int(args.sl_pips)}p_rr{args.rr}"
        f"_{int(args.balance)}{args.currency}"
    )

    if not args.no_csv:
        save_trades_csv(trades, os.path.join(args.output_dir, f"{base_name}_trades.csv"))

    if not args.no_plot:
        save_equity_plot(
            trades,
            os.path.join(args.output_dir, f"{base_name}_equity.png"),
            symbol, timeframe,
            initial_balance=args.balance,
            currency=args.currency,
        )

    print(f"\n✅ Backtest completado.\n")


if __name__ == "__main__":
    main()
