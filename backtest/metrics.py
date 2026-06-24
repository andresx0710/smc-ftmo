"""Performance metrics calculator and report generator.

Takes a list of Trade objects from engine.py and produces:
  - Summary statistics (win rate, profit factor, max drawdown, etc.)
  - Breakdown by score level and by direction
  - Console report (rich ASCII table)
  - Optional equity curve plot (matplotlib)
  - CSV export of all trades
"""

from __future__ import annotations

import os
from typing import Optional

import numpy as np
import pandas as pd

from backtest.engine import Trade, INITIAL_BALANCE


# ── Statistics ─────────────────────────────────────────────────────────────────

def calculate_metrics(trades: list[Trade], initial_balance: float = INITIAL_BALANCE) -> dict:
    """Computes all performance metrics from a list of Trade objects."""
    if not trades:
        return _empty_metrics()

    closed = [t for t in trades if t.outcome in ("WIN", "LOSS")]
    wins   = [t for t in closed if t.outcome == "WIN"]
    losses = [t for t in closed if t.outcome == "LOSS"]
    open_  = [t for t in trades if t.outcome == "OPEN"]

    total = len(closed)
    win_rate = len(wins) / total * 100 if total else 0.0

    equity        = _build_equity_curve(trades, initial_balance)
    final_balance = equity[-1] if equity else initial_balance
    net_pnl  = final_balance - initial_balance
    ret_pct  = net_pnl / initial_balance * 100

    # Max drawdown
    max_dd_pct, max_dd_eur = _max_drawdown(equity, initial_balance)

    # Profit factor
    gross_profit = sum(t.pnl for t in wins)
    gross_loss   = abs(sum(t.pnl for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    avg_win  = np.mean([t.pnl for t in wins])  if wins   else 0.0
    avg_loss = np.mean([t.pnl for t in losses]) if losses else 0.0
    expected = win_rate / 100 * avg_win + (1 - win_rate / 100) * avg_loss

    # Sharpe (simplified: daily P&L std)
    pnls = [t.pnl for t in closed]
    sharpe = (np.mean(pnls) / np.std(pnls) * np.sqrt(252)) if len(pnls) > 1 else 0.0

    # FTMO daily block stats
    days_blocked = _count_blocked_days(trades)
    trades_skipped_estimate = max(0, len(trades) - total - len(open_))

    # Breakdown by score
    by_score = _breakdown_by(closed, lambda t: t.score, range(0, 8))
    # Breakdown by direction
    by_direction = _breakdown_by(closed, lambda t: t.direction, ["LONG", "SHORT"])
    # Breakdown by condition (count how many times each condition was active in wins vs all)
    by_condition = _condition_stats(closed)

    # FTMO blown = equity hit the 10% max drawdown floor
    ftmo_blown = final_balance < initial_balance * 0.90

    return {
        "total_trades":    total,
        "wins":            len(wins),
        "losses":          len(losses),
        "open_trades":     len(open_),
        "win_rate":        round(win_rate, 1),
        "net_pnl":         round(net_pnl, 2),
        "return_pct":      round(ret_pct, 2),
        "final_balance":   round(final_balance, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "max_drawdown_eur": round(max_dd_eur, 2),
        "profit_factor":   round(profit_factor, 3),
        "avg_win":         round(avg_win, 2),
        "avg_loss":        round(avg_loss, 2),
        "expected_value":  round(expected, 2),
        "sharpe":          round(sharpe, 2),
        "days_blocked":    days_blocked,
        "ftmo_blown":      ftmo_blown,
        "by_score":        by_score,
        "by_direction":    by_direction,
        "by_condition":    by_condition,
        "equity_curve":    equity,
    }


# ── Console report ─────────────────────────────────────────────────────────────

def print_report(
    metrics:         dict,
    symbol:          str,
    timeframe:       str,
    n_bars:          int,
    params:          dict,
    date_range:      tuple,
    initial_balance: float = INITIAL_BALANCE,
    currency:        str   = "EUR",
) -> None:
    """Prints a formatted performance report to stdout."""
    d_from, d_to = date_range
    sep  = "═" * 58
    sep2 = "─" * 58
    cur  = currency

    print(f"\n{sep}")
    print(f"  SMC-FTMO Backtester — {symbol} {timeframe}")
    print(f"  Período: {d_from} → {d_to}  |  {n_bars:,} barras")
    print(f"  SL: {params.get('sl_pips', 20)} pips  |  R:R 1:{params.get('rr', 2)}  |  Riesgo: {params.get('risk_pct', 1)}%/trade")
    print(f"  Score mínimo: {params.get('min_score', 3)}/7  |  Modo: {params.get('mode', timeframe)}")
    print(sep)

    t = metrics
    print(f"\n📈 RESULTADOS  (balance inicial: {initial_balance:,.0f} {cur})")
    _row("Balance final",       f"{t['final_balance']:>10,.2f} {cur}")
    _row("P&L neto",            f"{t['net_pnl']:>+10,.2f} {cur}")
    _row("Retorno",             f"{t['return_pct']:>+9.1f} %")
    print(sep2)
    _row("Total operaciones",   f"{t['total_trades']:>10}")
    _row("  Ganadoras",         f"{t['wins']:>10}  ({t['win_rate']:.1f}%)")
    _row("  Perdedoras",        f"{t['losses']:>10}  ({100 - t['win_rate']:.1f}%)")
    if t["open_trades"]:
        _row("  Abiertas (EoD)", f"{t['open_trades']:>10}")
    print(sep2)
    _row("Profit Factor",       f"{t['profit_factor']:>10.3f}")
    _row("Max Drawdown",        f"{t['max_drawdown_eur']:>8,.2f} {cur}  ({t['max_drawdown_pct']:.1f}%)")
    _row("Avg ganadora",        f"{t['avg_win']:>+10.2f} {cur}")
    _row("Avg perdedora",       f"{t['avg_loss']:>+10.2f} {cur}")
    _row("Expected Value",      f"{t['expected_value']:>+10.2f} {cur}/trade")
    _row("Sharpe (anualizado)",  f"{t['sharpe']:>10.2f}")

    if t.get("ftmo_blown"):
        print(sep2)
        print(f"  ⛔  CUENTA BLOQUEADA — Max drawdown FTMO alcanzado")

    # ── By score ──────────────────────────────────────────────────────────
    print(f"\n📊 WIN RATE POR SCORE")
    for score in range(7, 0, -1):
        data = t["by_score"].get(score)
        if not data or data["total"] == 0:
            continue
        bar = _mini_bar(data["win_rate"] / 100, 12)
        print(f"  Score {score}/7:  {bar}  {data['win_rate']:5.1f}%  ({data['total']} trades)")

    # ── By direction ──────────────────────────────────────────────────────
    print(f"\n📐 POR DIRECCIÓN")
    for direction in ["LONG", "SHORT"]:
        data = t["by_direction"].get(direction, {})
        if not data or data.get("total", 0) == 0:
            continue
        print(f"  {direction:<5}: {data['win_rate']:5.1f}% win rate  ({data['total']} trades)")

    # ── By condition ──────────────────────────────────────────────────────
    print(f"\n🔍 CONDICIONES EN TRADES GANADORES vs TODOS")
    for cond, data in t["by_condition"].items():
        pct_wins  = data["in_wins"]  / max(t["wins"],   1) * 100
        pct_all   = data["in_total"] / max(t["total_trades"], 1) * 100
        print(f"  {cond.upper():<8}: ganadores {pct_wins:5.1f}%  |  todos {pct_all:5.1f}%")

    print(f"\n{sep}\n")


# ── Export ─────────────────────────────────────────────────────────────────────

def save_trades_csv(trades: list[Trade], path: str) -> None:
    """Saves all trades to a CSV for further analysis."""
    rows = []
    for t in trades:
        row = {
            "entry_time": t.entry_time,
            "exit_time":  t.exit_time,
            "direction":  t.direction,
            "entry":      t.entry,
            "sl":         t.sl,
            "tp":         t.tp,
            "exit_price": t.exit_price,
            "outcome":    t.outcome,
            "score":      t.score,
            "risk_eur":   t.risk_eur,
            "pnl":        t.pnl,
            "balance":    t.balance_after,
        }
        row.update(t.conditions)
        rows.append(row)
    df = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)
    print(f"Trades guardados: {path}")


def calculate_periodic_metrics(
    trades:          list[Trade],
    initial_balance: float = INITIAL_BALANCE,
    currency:        str   = "EUR",
) -> dict:
    """Computes weekly, monthly, and yearly performance breakdowns."""
    closed = [t for t in trades if t.outcome in ("WIN", "LOSS")]
    if not closed:
        return {"weekly": {}, "monthly": {}, "yearly": {}}

    rows = []
    for t in sorted(closed, key=lambda x: x.entry_bar):
        ts = pd.Timestamp(t.entry_time)
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        rows.append({
            "entry_time": ts,
            "pnl":        t.pnl,
            "outcome":    t.outcome,
        })

    df = pd.DataFrame(rows)
    df["week"]  = df["entry_time"].dt.to_period("W")
    df["month"] = df["entry_time"].dt.to_period("M")
    df["year"]  = df["entry_time"].dt.to_period("Y")

    def _period_stats(col: str) -> dict:
        result: dict = {}
        for period, grp in df.groupby(col):
            w    = (grp["outcome"] == "WIN").sum()
            tot  = len(grp)
            pnl  = round(grp["pnl"].sum(), 2)
            result[str(period)] = {
                "trades":     tot,
                "wins":       int(w),
                "losses":     int(tot - w),
                "win_rate":   round(w / tot * 100, 1) if tot else 0.0,
                "pnl":        pnl,
                "return_pct": round(pnl / initial_balance * 100, 2),
            }
        return result

    return {
        "weekly":  _period_stats("week"),
        "monthly": _period_stats("month"),
        "yearly":  _period_stats("year"),
        "currency": currency,
    }


def print_periodic_report(periodic: dict, currency: str = "EUR") -> None:
    """Prints weekly, monthly, and yearly performance tables."""
    cur   = currency
    sep   = "─" * 58
    cur_p = periodic.get("currency", cur)

    for label, key in [("SEMANA", "weekly"), ("MES", "monthly"), ("AÑO", "yearly")]:
        data = periodic.get(key, {})
        if not data:
            continue
        print(f"\n📅 RENDIMIENTO POR {label}")
        print(f"  {'Período':<18} {'Trades':>6} {'WR':>6} {'P&L':>12} {'Ret%':>7}")
        print(f"  {sep[:55]}")
        for period, d in sorted(data.items()):
            sign   = "+" if d["pnl"] >= 0 else ""
            color_win = "✓" if d["pnl"] >= 0 else "✗"
            print(
                f"  {color_win} {period:<16} {d['trades']:>6} "
                f"{d['win_rate']:>5.1f}% {sign}{d['pnl']:>9,.2f} {cur_p} "
                f"{sign}{d['return_pct']:>5.2f}%"
            )


def save_equity_plot(
    trades:          list[Trade],
    path:            str,
    symbol:          str,
    timeframe:       str,
    initial_balance: float = INITIAL_BALANCE,
    currency:        str   = "EUR",
) -> None:
    """Saves an equity curve chart as PNG. Requires matplotlib."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib no instalado — gráfica de equity no generada.")
        return

    if not trades:
        return

    equity = _build_equity_curve(trades, initial_balance)
    x      = list(range(len(equity)))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), gridspec_kw={"height_ratios": [3, 1]})
    fig.patch.set_facecolor("#1a1a2e")

    # ── Equity curve ──────────────────────────────────────────────────────
    ax1.set_facecolor("#16213e")
    ax1.plot(x, equity, color="#00C853", linewidth=1.5, label="Equity")
    ax1.axhline(
        initial_balance, color="#787B86", linewidth=0.8, linestyle="--",
        label=f"Inicio {initial_balance:,.0f} {currency}",
    )

    peak = initial_balance
    for xi, eq in enumerate(equity):
        peak = max(peak, eq)
        if eq < peak:
            ax1.fill_between([xi - 1, xi], [equity[xi - 1] if xi > 0 else eq, eq],
                             [peak], alpha=0.15, color="#D50000")

    for t in trades:
        if t.outcome == "WIN":
            ax1.scatter(t.exit_bar, t.balance_after, marker="^", color="#00C853", s=20, zorder=5, alpha=0.7)
        elif t.outcome == "LOSS":
            ax1.scatter(t.exit_bar, t.balance_after, marker="v", color="#D50000", s=20, zorder=5, alpha=0.7)

    closed  = [t for t in trades if t.outcome in ("WIN", "LOSS")]
    wins    = len([t for t in closed if t.outcome == "WIN"])
    wr      = wins / len(closed) * 100 if closed else 0
    net_pnl = (equity[-1] - initial_balance) if equity else 0

    ax1.set_title(
        f"SMC Equity — {symbol} {timeframe}  |  {len(closed)} trades  |  WR {wr:.1f}%  |  P&L {net_pnl:+.0f} {currency}",
        color="white", fontsize=12, pad=10,
    )
    ax1.set_ylabel(f"Balance ({currency})", color="white")
    ax1.tick_params(colors="white")
    ax1.spines[:].set_color("#333")
    ax1.legend(facecolor="#333", labelcolor="white", fontsize=9)

    # ── Score histogram ───────────────────────────────────────────────────
    ax2.set_facecolor("#16213e")
    score_counts = {}
    score_wins   = {}
    for t in closed:
        score_counts[t.score] = score_counts.get(t.score, 0) + 1
        if t.outcome == "WIN":
            score_wins[t.score] = score_wins.get(t.score, 0) + 1

    scores = sorted(score_counts)
    colors = ["#D50000" if score_wins.get(s, 0) / score_counts[s] < 0.5 else "#00C853" for s in scores]
    ax2.bar(scores, [score_counts[s] for s in scores], color=colors, alpha=0.8, width=0.6)
    ax2.set_xlabel("Score (condiciones activas)", color="white")
    ax2.set_ylabel("Trades", color="white")
    ax2.tick_params(colors="white")
    ax2.spines[:].set_color("#333")
    ax2.set_xticks(range(1, 8))

    plt.tight_layout()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    plt.savefig(path, dpi=150, facecolor=fig.get_facecolor())
    plt.close()
    print(f"Gráfica guardada: {path}")


# ── Private helpers ────────────────────────────────────────────────────────────

def _build_equity_curve(trades: list[Trade], initial: float) -> list[float]:
    curve = [initial]
    balance = initial
    for t in sorted(trades, key=lambda x: x.entry_bar):
        if t.outcome in ("WIN", "LOSS"):
            balance += t.pnl
            curve.append(round(balance, 2))
    return curve


def _max_drawdown(equity: list[float], initial: float) -> tuple[float, float]:
    peak = initial
    max_dd_eur = max_dd_pct = 0.0
    for eq in equity:
        peak = max(peak, eq)
        dd_eur = peak - eq
        dd_pct = dd_eur / peak * 100
        if dd_eur > max_dd_eur:
            max_dd_eur = dd_eur
            max_dd_pct = dd_pct
    return max_dd_pct, max_dd_eur


def _breakdown_by(closed: list[Trade], key_fn, keys) -> dict:
    result = {}
    for k in keys:
        subset = [t for t in closed if key_fn(t) == k]
        if not subset:
            continue
        wins = sum(1 for t in subset if t.outcome == "WIN")
        result[k] = {
            "total":    len(subset),
            "wins":     wins,
            "losses":   len(subset) - wins,
            "win_rate": round(wins / len(subset) * 100, 1),
        }
    return result


def _condition_stats(closed: list[Trade]) -> dict:
    cond_names = ["choch", "ob", "liq", "fvg", "pd", "bos", "sd"]
    wins = [t for t in closed if t.outcome == "WIN"]
    result = {}
    for name in cond_names:
        result[name] = {
            "in_wins":  sum(1 for t in wins  if t.conditions.get(name, False)),
            "in_total": sum(1 for t in closed if t.conditions.get(name, False)),
        }
    return result


def _count_blocked_days(trades: list[Trade]) -> int:
    # Heuristic: count unique days where a trade was rejected due to daily limit
    # We can't easily detect this from trade list alone; return 0 for now.
    # Full implementation would require tracking day-block events in the engine.
    return 0


def _empty_metrics() -> dict:
    return {
        "total_trades": 0, "wins": 0, "losses": 0, "open_trades": 0,
        "win_rate": 0.0, "net_pnl": 0.0, "return_pct": 0.0, "final_balance": INITIAL_BALANCE,
        "max_drawdown_pct": 0.0, "max_drawdown_eur": 0.0, "profit_factor": 0.0,
        "avg_win": 0.0, "avg_loss": 0.0, "expected_value": 0.0, "sharpe": 0.0,
        "days_blocked": 0, "by_score": {}, "by_direction": {}, "by_condition": {},
        "equity_curve": [],
    }


def _row(label: str, value: str) -> None:
    print(f"  {label:<28} {value}")


def _mini_bar(pct: float, width: int) -> str:
    filled = round(pct * width)
    return "▓" * filled + "░" * (width - filled)
