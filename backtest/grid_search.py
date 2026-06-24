"""Grid search de parámetros SMC-FTMO.

Estrategia de ejecución:
  - Datos y detección de señales se cargan UNA SOLA VEZ.
  - Solo el engine se repite (muy rápido, O(n) por combo).
  - Se filtran resultados que respeten el drawdown máximo FTMO del 10%.
  - Se rankean por Profit Factor (primario) y Retorno % (secundario).

Uso:
  python -m backtest.grid_search --symbol EURUSD --tf-chain D1 H1 M15 --bars 20000
  python -m backtest.grid_search --symbol EURUSD --tf-chain D1 H1 M15 --bars 20000 \\
         --min-scores 4 5 6 7 --sl-pips 5 8 10 12 15 20 --rr 2.0 2.5 3.0
"""

from __future__ import annotations

import argparse
import csv
import itertools
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m backtest.grid_search",
        description="Grid search de parámetros SMC-FTMO",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument("--symbol",      default="EURUSD")
    p.add_argument("--tf-chain",    nargs="+", default=["D1", "H1", "M15"],
                   dest="tf_chain", metavar="TF",
                   help="Cadena MTF de mayor a menor TF (default: D1 H1 M15)")
    p.add_argument("--bars",        type=int, default=20000,
                   help="Barras del TF de entrada (default: 20000)")
    p.add_argument("--balance",     type=float, default=10000.0,
                   help="Capital inicial (default: 10000)")
    p.add_argument("--currency",    type=str, default="EUR",
                   help="Divisa de la cuenta (default: EUR)")
    p.add_argument("--risk-pct",    type=float, default=1.0, dest="risk_pct",
                   help="Riesgo por trade en %% del balance (default: 1.0)")
    p.add_argument("--cache-dir",   default="backtest/data", dest="cache_dir")
    p.add_argument("--output-dir",  default="backtest/output", dest="output_dir")

    # Grid axes
    p.add_argument("--min-scores",  nargs="+", type=int,
                   default=[4, 5, 6, 7], dest="min_scores", metavar="N",
                   help="Valores de min_score a probar (default: 4 5 6 7)")
    p.add_argument("--sl-pips",     nargs="+", type=float,
                   default=[5.0, 8.0, 10.0, 12.0, 15.0, 20.0], metavar="P",
                   help="Valores de sl_pips a probar (default: 5 8 10 12 15 20)")
    p.add_argument("--rr",          nargs="+", type=float,
                   default=[2.0, 2.5, 3.0],
                   help="Valores de R:R a probar (default: 2.0 2.5 3.0)")

    # Filters & display
    p.add_argument("--min-trades",  type=int, default=10, dest="min_trades",
                   help="Mínimo de trades cerrados para incluir resultado (default: 10)")
    p.add_argument("--top",         type=int, default=20,
                   help="Mostrar top N resultados FTMO-compliant (default: 20)")
    p.add_argument("--show-all",    action="store_true", dest="show_all",
                   help="Mostrar también resultados no FTMO-compliant")
    p.add_argument("--no-d1-gate",  action="store_true", dest="no_d1_gate",
                   help="Desactivar filtro de gate del TF macro")
    p.add_argument("--only-short",  action="store_true", dest="only_short",
                   help="Solo operar en SHORT (anula todas las señales LONG)")
    p.add_argument("--only-long",   action="store_true", dest="only_long",
                   help="Solo operar en LONG (anula todas las señales SHORT)")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    # ── Lazy imports ──────────────────────────────────────────────────────
    from backtest.data     import download_multi_tf_chain, get_ohlcv
    from backtest.detector import (detect_signals, detect_signals_chain,
                                   DEFAULT_MTF_PARAMS, DEFAULT_PARAMS, MINTICKS)
    from backtest.engine   import run_backtest, EngineParams, PIP_SIZES
    from backtest.metrics  import calculate_metrics

    symbol    = args.symbol.upper()
    tf_chain  = [tf.upper() for tf in args.tf_chain]
    timeframe = tf_chain[-1]
    use_chain = len(tf_chain) > 1
    mintick   = MINTICKS.get(symbol, 0.00001)
    pip_size  = PIP_SIZES.get(symbol, 0.0001)
    cur       = args.currency.upper()

    combos = list(itertools.product(args.min_scores, args.sl_pips, args.rr))

    # ── Header ────────────────────────────────────────────────────────────
    sep  = "═" * 72
    sep2 = "─" * 72
    print(f"\n{sep}")
    print(f"  SMC-FTMO Grid Search  |  {symbol}  |  {'→'.join(tf_chain)}")
    print(f"  Balance: {args.balance:,.0f} {cur}  |  Riesgo: {args.risk_pct}%/trade")
    print(f"  Grid: {len(args.min_scores)} scores × {len(args.sl_pips)} SLs × {len(args.rr)} RRs = {len(combos)} combinaciones")
    print(sep)

    # ── 1. Load data ONCE ─────────────────────────────────────────────────
    print(f"\n⏳ Cargando datos...")
    if use_chain:
        chain_data = download_multi_tf_chain(
            symbol=symbol, tf_chain=tf_chain, n_bars=args.bars,
            cache_dir=args.cache_dir,
        )
        df      = chain_data[timeframe]
        htf_dfs = [chain_data[tf] for tf in tf_chain[:-1]]
    else:
        df      = get_ohlcv(symbol, timeframe, args.bars, cache_dir=args.cache_dir)
        htf_dfs = []

    date_from = str(df["time"].iloc[0].date())  if hasattr(df["time"].iloc[0],  "date") else str(df["time"].iloc[0])
    date_to   = str(df["time"].iloc[-1].date()) if hasattr(df["time"].iloc[-1], "date") else str(df["time"].iloc[-1])
    print(f"  {len(df):,} barras  ({date_from} → {date_to})")

    # ── 2. Detect signals ONCE ────────────────────────────────────────────
    print(f"\n⏳ Detectando señales SMC (una sola vez)...")
    t0 = time.time()

    detector_params = {
        **(DEFAULT_MTF_PARAMS if use_chain else DEFAULT_PARAMS),
        "mintick": mintick,
    }

    if use_chain:
        signals_df = detect_signals_chain(df, htf_dfs, detector_params)
        if not args.no_d1_gate:
            signals_df["score_bull"] = (
                signals_df["score_bull"] * signals_df["gate_bull"].astype(int)
            )
            signals_df["score_bear"] = (
                signals_df["score_bear"] * signals_df["gate_bear"].astype(int)
            )
    else:
        signals_df = detect_signals(df, detector_params)

    if args.only_short:
        signals_df["score_bull"] = 0
    if args.only_long:
        signals_df["score_bear"] = 0

    t_detect = time.time() - t0
    max_bull  = signals_df["score_bull"].max()
    max_bear  = signals_df["score_bear"].max()
    dir_tag   = "  [SOLO SHORT]" if args.only_short else "  [SOLO LONG]" if args.only_long else ""
    print(f"  Detección: {t_detect:.1f}s  |  Score máx LONG: {max_bull}  SHORT: {max_bear}{dir_tag}")

    if max_bull < min(args.min_scores) and max_bear < min(args.min_scores):
        print(f"⚠️  Ninguna señal supera score {min(args.min_scores)}. Revisa los datos o reduce --min-scores.")
        sys.exit(1)

    # ── 3. Run grid ───────────────────────────────────────────────────────
    print(f"\n⏳ Ejecutando {len(combos)} combinaciones...\n")
    t0      = time.time()
    results = []

    for idx, (min_score, sl_pips, rr) in enumerate(combos, 1):

        n_signals = int(
            (signals_df["score_bull"] >= min_score).sum() +
            (signals_df["score_bear"] >= min_score).sum()
        )

        if n_signals == 0:
            results.append({
                "min_score": min_score, "sl_pips": sl_pips, "rr": rr,
                "trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
                "max_dd_pct": 0.0, "max_dd_abs": 0.0, "return_pct": 0.0,
                "net_pnl": 0.0, "sharpe": 0.0, "ftmo_ok": False,
                "reason": "sin señales",
            })
            _print_progress(idx, len(combos), min_score, sl_pips, rr, 0, "-", "-", False)
            continue

        ep = EngineParams(
            symbol          = symbol,
            min_score       = min_score,
            sl_pips         = sl_pips,
            rr              = rr,
            risk_pct        = args.risk_pct,
            initial_balance = args.balance,
            currency        = cur,
            pip_size        = pip_size,
        )
        trades = run_backtest(df, signals_df, ep)
        closed = [t for t in trades if t.outcome in ("WIN", "LOSS")]

        if len(closed) < args.min_trades:
            results.append({
                "min_score": min_score, "sl_pips": sl_pips, "rr": rr,
                "trades": len(closed), "win_rate": 0.0, "profit_factor": 0.0,
                "max_dd_pct": 0.0, "max_dd_abs": 0.0, "return_pct": 0.0,
                "net_pnl": 0.0, "sharpe": 0.0, "ftmo_ok": False,
                "reason": f"pocos trades ({len(closed)}<{args.min_trades})",
            })
            _print_progress(idx, len(combos), min_score, sl_pips, rr,
                            len(closed), "-", "-", False)
            continue

        m = calculate_metrics(trades, initial_balance=args.balance)
        ftmo_ok = (not m["ftmo_blown"]) and (m["max_drawdown_pct"] < 10.0)

        results.append({
            "min_score":    min_score,
            "sl_pips":      sl_pips,
            "rr":           rr,
            "trades":       m["total_trades"],
            "win_rate":     m["win_rate"],
            "profit_factor":m["profit_factor"],
            "max_dd_pct":   m["max_drawdown_pct"],
            "max_dd_abs":   m["max_drawdown_eur"],
            "return_pct":   m["return_pct"],
            "net_pnl":      m["net_pnl"],
            "sharpe":       m["sharpe"],
            "ftmo_ok":      ftmo_ok,
            "reason":       "ok" if ftmo_ok else f"DD {m['max_drawdown_pct']:.1f}%",
        })
        _print_progress(idx, len(combos), min_score, sl_pips, rr,
                        m["total_trades"], f"{m['profit_factor']:.3f}",
                        f"{m['max_drawdown_pct']:.1f}%", ftmo_ok)

    t_grid = time.time() - t0
    print(f"\n  ✅ Grid completado en {t_grid:.1f}s")

    # ── 4. Rank & display ─────────────────────────────────────────────────
    ftmo_ok_list = sorted(
        [r for r in results if r["ftmo_ok"]],
        key=lambda r: (-r["profit_factor"], -r["return_pct"]),
    )
    all_ranked = sorted(
        [r for r in results if r.get("trades", 0) >= args.min_trades],
        key=lambda r: (-int(r["ftmo_ok"]), -r["profit_factor"]),
    )

    print(f"\n{sep}")
    print(f"  RESULTADOS  |  {len(ftmo_ok_list)} FTMO-compliant de {len(combos)} combinaciones")
    print(sep)

    display = all_ranked if args.show_all else ftmo_ok_list

    if not display:
        print(f"\n  ⚠️  Ninguna combinación cumple los criterios FTMO (DD < 10%, trades ≥ {args.min_trades}).")
        best_pf = max((r["profit_factor"] for r in results if r.get("trades", 0) >= args.min_trades), default=0)
        print(f"  Mejor profit factor encontrado: {best_pf:.3f}  (con DD > 10%)")
        print(f"  Opciones: --show-all para ver todo  |  --no-d1-gate para más señales")
    else:
        _print_table_header(cur)
        for i, r in enumerate(display[:args.top], 1):
            _print_table_row(i, r, cur)

        remaining = len(display) - args.top
        if remaining > 0:
            print(f"\n  ... {remaining} resultados más. Usa --top {len(display)} para verlos todos.")

    # ── Best result detail ────────────────────────────────────────────────
    if ftmo_ok_list:
        best = ftmo_ok_list[0]
        chain_arg = " ".join(tf_chain)
        print(f"\n{sep}")
        print(f"  🏆  MEJOR COMBINACIÓN FTMO-COMPLIANT")
        print(sep2)
        print(f"  min_score = {best['min_score']}  |  sl_pips = {best['sl_pips']:.0f}  |  rr = {best['rr']}")
        print(f"  Profit Factor : {best['profit_factor']:.3f}")
        print(f"  Win Rate      : {best['win_rate']:.1f}%   ({best['trades']} trades)")
        print(f"  Retorno       : {best['return_pct']:+.1f}%   ({best['net_pnl']:+,.2f} {cur})")
        print(f"  Max Drawdown  : {best['max_dd_pct']:.1f}%   ({best['max_dd_abs']:,.2f} {cur})")
        print(f"  Sharpe        : {best['sharpe']:.2f}")
        print(sep2)
        dir_flag = " --only-short" if args.only_short else " --only-long" if args.only_long else ""
        print(f"  Comando para correr este resultado completo:")
        print(f"    python -m backtest.run --symbol {symbol} --tf-chain {chain_arg} \\")
        print(f"      --min-score {best['min_score']} --sl-pips {int(best['sl_pips'])} "
              f"--rr {best['rr']} \\")
        print(f"      --bars {args.bars} --balance {int(args.balance)} --currency {cur}{dir_flag}")
        print(sep)

    # ── Save CSV ──────────────────────────────────────────────────────────
    os.makedirs(args.output_dir, exist_ok=True)
    chain_tag = "_".join(tf_chain)
    csv_path  = os.path.join(
        args.output_dir,
        f"grid_{symbol}_{chain_tag}_{int(args.balance)}{cur}.csv",
    )
    fieldnames = [
        "min_score", "sl_pips", "rr", "trades", "win_rate",
        "profit_factor", "max_dd_pct", "max_dd_abs", "return_pct",
        "net_pnl", "sharpe", "ftmo_ok", "reason",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)

    print(f"\n  CSV completo guardado: {csv_path}\n")


# ── Private helpers ────────────────────────────────────────────────────────────

def _print_progress(
    idx: int, total: int,
    score: int, sl: float, rr: float,
    trades: int, pf: str, dd: str, ok: bool,
) -> None:
    status = "✅" if ok else "✗ "
    print(
        f"  [{idx:>3}/{total}] score={score} sl={sl:>4.0f}p rr={rr}  "
        f"trades={trades:>4}  PF={pf:>6}  DD={dd:>6}  {status}",
        flush=True,
    )


def _print_table_header(cur: str) -> None:
    print(
        f"\n  {'#':>3}  {'Score':>5}  {'SL(p)':>5}  {'RR':>4}  "
        f"{'Trades':>6}  {'WR%':>5}  {'PF':>6}  {'DD%':>5}  "
        f"{'Ret%':>6}  {'P&L':>10}  {'FTMO':>5}"
    )
    print(f"  {'─' * 68}")


def _print_table_row(rank: int, r: dict, cur: str) -> None:
    ftmo_tag = "✅ OK" if r["ftmo_ok"] else "⛔ NO"
    sign     = "+" if r["net_pnl"] >= 0 else ""
    print(
        f"  {rank:>3}.  {r['min_score']:>5}  {r['sl_pips']:>5.0f}  {r['rr']:>4.1f}  "
        f"{r['trades']:>6}  {r['win_rate']:>4.1f}%  {r['profit_factor']:>6.3f}  "
        f"{r['max_dd_pct']:>4.1f}%  {r['return_pct']:>+5.1f}%  "
        f"{sign}{r['net_pnl']:>7,.0f}{cur[:1]}  {ftmo_tag}"
    )


if __name__ == "__main__":
    main()
