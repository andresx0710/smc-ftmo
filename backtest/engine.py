"""Backtesting engine — simulates FTMO-aware trade execution.

Entry logic (mirrors live system):
  - Signal fires at bar[i] CLOSE  (same as Pine Script alert.freq_once_per_bar)
  - Entry at bar[i+1] OPEN        (realistic: can't fill at signal bar's close)
  - Exit when wick hits SL or TP  (bars are scanned forward until outcome)

FTMO rules applied:
  - Daily P&L is tracked; trading stops if daily loss > ftmo_daily_limit
  - Open risk capped at max_open_risk (2 simultaneous positions max)
  - Lot size calculated from 1% risk per trade (configurable)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd



# Default pip sizes per symbol (price distance of 1 pip)
PIP_SIZES: dict = {
    "EURUSD": 0.0001,  "GBPUSD": 0.0001,  "AUDUSD": 0.0001,  "NZDUSD": 0.0001,
    "EURGBP": 0.0001,  "USDJPY": 0.01,    "EURJPY": 0.01,
    "XAUUSD": 1.0,     "GOLD":   1.0,
    "NAS100": 1.0,     "US100":  1.0,
    "BTCUSD": 1.0,
}

# FTMO default limits — percentages of balance (ftmo-rules.md)
FTMO_DAILY_LIMIT_PCT  = 0.03   # 3% system limit (conservative; FTMO hard limit is 5%)
FTMO_MAX_LOSS_PCT     = 0.10   # 10% total drawdown — FTMO hard rule
MAX_OPEN_RISK_PCT     = 0.02   # 2% max simultaneous open risk
INITIAL_BALANCE       = 10_000.0


@dataclass
class Trade:
    entry_bar:   int
    entry_time:  object         # datetime
    direction:   str            # "LONG" | "SHORT"
    entry:       float
    sl:          float
    tp:          float
    score:       int
    risk_eur:    float          # account currency units at risk for this trade
    conditions:  dict = field(default_factory=dict)
    # Filled on exit
    exit_bar:    Optional[int]   = None
    exit_time:   Optional[object] = None
    exit_price:  float           = 0.0
    outcome:     str             = "OPEN"   # "WIN" | "LOSS" | "OPEN"
    pnl:         float           = 0.0
    balance_after: float         = 0.0
    daily_pnl_before: float      = 0.0


@dataclass
class EngineParams:
    symbol:           str            = "EURUSD"
    min_score:        int            = 3
    sl_pips:          float          = 20.0
    rr:               float          = 2.0
    risk_pct:         float          = 1.0
    initial_balance:  float          = INITIAL_BALANCE
    currency:         str            = "EUR"
    # None → auto-compute proportionally from initial_balance
    ftmo_daily_limit: Optional[float] = None   # default: 3% of balance
    ftmo_max_loss:    Optional[float] = None   # default: 10% drawdown floor
    max_open_risk:    Optional[float] = None   # default: 2% of balance
    pip_size:         Optional[float] = None   # auto-detect from symbol if None
    allow_simultaneous: bool          = False

    def __post_init__(self) -> None:
        if self.ftmo_daily_limit is None:
            self.ftmo_daily_limit = round(self.initial_balance * FTMO_DAILY_LIMIT_PCT, 2)
        if self.ftmo_max_loss is None:
            self.ftmo_max_loss = round(self.initial_balance * (1 - FTMO_MAX_LOSS_PCT), 2)
        if self.max_open_risk is None:
            self.max_open_risk = round(self.initial_balance * MAX_OPEN_RISK_PCT, 2)


def run_backtest(
    df: pd.DataFrame,
    signals_df: pd.DataFrame,
    params: Optional[EngineParams] = None,
) -> list[Trade]:
    """Simulates all LONG and SHORT signals and returns a list of Trade objects.

    Args:
        df:          OHLCV DataFrame (same index as signals_df)
        signals_df:  Output of detector.detect_signals()
        params:      Engine configuration

    Returns:
        List of Trade objects with filled outcome, pnl, and balance_after.
    """
    p = params or EngineParams()

    pip = p.pip_size or PIP_SIZES.get(p.symbol.upper(), 0.0001)
    sl_dist  = p.sl_pips * pip
    tp_dist  = sl_dist * p.rr

    balance  = p.initial_balance
    trades: list[Trade] = []

    # FTMO daily tracking
    current_day: Optional[date] = None
    daily_pnl   = 0.0
    day_blocked = False

    # Open position tracking (ticket → Trade)
    open_trade: Optional[Trade] = None   # single-position mode (default)

    highs  = df["h"].values
    lows   = df["l"].values
    opens  = df["o"].values
    times  = df["time"].values if "time" in df.columns else np.arange(len(df))

    n = len(df)
    overall_blocked = False

    for i in range(n - 1):   # n-1: need at least i+1 for entry bar
        if overall_blocked:
            break

        bar_time = pd.Timestamp(times[i])
        bar_date = bar_time.date() if hasattr(bar_time, "date") else bar_time

        # ── Daily reset ────────────────────────────────────────────────────
        if bar_date != current_day:
            current_day = bar_date
            daily_pnl   = 0.0
            day_blocked = False

        # ── Close open position if SL/TP hit ──────────────────────────────
        if open_trade is not None:
            hit, exit_price = _check_exit(open_trade, highs[i], lows[i])
            if hit:
                pnl = open_trade.risk_eur * p.rr if hit == "WIN" else -open_trade.risk_eur
                open_trade.exit_bar   = i
                open_trade.exit_time  = times[i]
                open_trade.exit_price = exit_price
                open_trade.outcome    = hit
                open_trade.pnl        = pnl
                balance              += pnl
                daily_pnl            += pnl
                open_trade.balance_after = balance
                trades.append(open_trade)
                open_trade = None

                if daily_pnl <= -p.ftmo_daily_limit:
                    day_blocked = True
                if balance <= p.ftmo_max_loss:
                    overall_blocked = True
                    break

        # ── Entry gate ────────────────────────────────────────────────────
        if day_blocked:
            continue
        if open_trade is not None and not p.allow_simultaneous:
            continue

        # ── Signal detection at bar[i] ────────────────────────────────────
        row    = signals_df.iloc[i]
        signal = None

        # Avoid entering opposing direction if we already have a position
        if row["score_bull"] >= p.min_score and open_trade is None:
            signal = "LONG"
        elif row["score_bear"] >= p.min_score and open_trade is None:
            signal = "SHORT"

        if signal is None:
            continue

        # ── Calculate risk ─────────────────────────────────────────────────
        risk_eur = balance * p.risk_pct / 100.0
        # Cap risk to remaining daily budget
        budget_left = max(0.0, p.ftmo_daily_limit + daily_pnl)  # daily_pnl is negative if losses
        risk_eur    = min(risk_eur, budget_left)
        if risk_eur <= 0.0:
            day_blocked = True
            continue

        # ── Open trade at next bar open ────────────────────────────────────
        entry = opens[i + 1]
        if signal == "LONG":
            sl = entry - sl_dist
            tp = entry + tp_dist
        else:
            sl = entry + sl_dist
            tp = entry - tp_dist

        score = row["score_bull"] if signal == "LONG" else row["score_bear"]
        conditions = {
            "choch": bool(row[f"choch_{'bull' if signal == 'LONG' else 'bear'}"]),
            "ob":    bool(row[f"ob_{'bull' if signal == 'LONG' else 'bear'}"]),
            "liq":   bool(row[f"liq_{'bull' if signal == 'LONG' else 'bear'}"]),
            "fvg":   bool(row[f"fvg_{'bull' if signal == 'LONG' else 'bear'}"]),
            "pd":    bool(row[f"pd_{'bull' if signal == 'LONG' else 'bear'}"]),
            "bos":   bool(row[f"bos_{'bull' if signal == 'LONG' else 'bear'}"]),
            "sd":    bool(row[f"sd_{'bull' if signal == 'LONG' else 'bear'}"]),
        }

        open_trade = Trade(
            entry_bar=i + 1,
            entry_time=times[i + 1],
            direction=signal,
            entry=entry,
            sl=sl,
            tp=tp,
            score=score,
            risk_eur=risk_eur,
            conditions=conditions,
            daily_pnl_before=daily_pnl,
        )

    # ── Close any open trade at end of data ───────────────────────────────
    if open_trade is not None:
        last_close = df["c"].iloc[-1]
        pnl = (last_close - open_trade.entry) * (1 if open_trade.direction == "LONG" else -1)
        # Convert to EUR (rough: proportional to risk)
        pnl_scaled = open_trade.risk_eur * (pnl / (open_trade.tp - open_trade.entry))
        open_trade.exit_bar   = n - 1
        open_trade.exit_time  = times[-1]
        open_trade.exit_price = last_close
        open_trade.outcome    = "OPEN"
        open_trade.pnl        = round(pnl_scaled, 2)
        open_trade.balance_after = balance + pnl_scaled
        trades.append(open_trade)

    return trades


# ── Private helpers ────────────────────────────────────────────────────────────

def _check_exit(trade: Trade, bar_high: float, bar_low: float) -> tuple[str, float]:
    """Returns ("WIN"/"LOSS"/None, exit_price) based on current bar's wicks."""
    if trade.direction == "LONG":
        if bar_low <= trade.sl:
            return "LOSS", trade.sl
        if bar_high >= trade.tp:
            return "WIN", trade.tp
    else:
        if bar_high >= trade.sl:
            return "LOSS", trade.sl
        if bar_low <= trade.tp:
            return "WIN", trade.tp
    return None, 0.0
