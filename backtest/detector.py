"""SMC signal detector — Python port of pine/confluence_score.pine.

Implements the same 7 conditions with identical default parameters so backtest
results are comparable to live TradingView signals.

Conditions (same weights as confluence_score.pine):
  1. CHoCH  — Change of Character              [Alto]
  2. OB     — Order Block (price in zone)      [Alto]
  3. Liq    — Liquidity swept (SSL/BSL)        [Alto]
  4. FVG    — Fair Value Gap detected          [Medio]
  5. P/D    — Price in Premium/Discount zone   [Medio]
  6. BOS    — Break of Structure               [Medio]
  7. S&D    — Supply & Demand impulse          [Medio]
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ── Default parameters (matches confluence_score.pine inputs) ─────────────────
DEFAULT_PARAMS: dict = {
    # Pivot detection (ta.pivothigh / ta.pivotlow)
    "left_bars":      5,
    "right_bars":     3,
    # ATR
    "atr_len":        14,
    # Window: bars a condition stays "active" after firing
    "window":         10,
    # Order Block
    "ob_lookback":    10,    # bars to scan for OB
    "atr_mult":       0.8,   # min impulse body as multiple of ATR
    # Premium / Discount range
    "pd_lookback":    50,    # rolling bars for range detection
    # FVG
    "min_fvg_ticks":  3,     # minimum gap in ticks
    "mintick":        0.00001,  # override per symbol (EURUSD=0.00001, XAUUSD=0.01)
    # S&D
    "base_mult":      0.5,   # max body of base candle (× ATR)
    "impulse_mult":   1.5,   # min body of impulse candle (× ATR)
}

MINTICKS: dict = {
    "EURUSD": 0.00001, "GBPUSD": 0.00001, "USDJPY": 0.001,
    "EURGBP": 0.00001, "EURJPY": 0.001,
    "XAUUSD": 0.01,    "GOLD":   0.01,
    "NAS100": 0.01,    "US100":  0.01,
    "BTCUSD": 0.01,
}

# MTF-specific defaults: window for HTF conditions (in HTF bars)
DEFAULT_MTF_PARAMS: dict = {
    **DEFAULT_PARAMS,
    "h1_window":  10,   # bars in H1 time that a CHoCH/BOS stays active
    "d1_window":  5,    # bars in D1 time
}


# ── Public API ─────────────────────────────────────────────────────────────────

def detect_signals(df: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    """Runs all 7 SMC conditions and returns per-bar scores.

    Args:
        df:     OHLCV DataFrame with columns o, h, l, c, time
        params: Override any DEFAULT_PARAMS key (all others keep defaults)

    Returns:
        DataFrame (same index as df) with columns:
          score_bull, score_bear  (0-7)
          choch_bull, ob_bull, liq_bull, fvg_bull, pd_bull, bos_bull, sd_bull  (bool)
          choch_bear, ob_bear, liq_bear, fvg_bear, pd_bear, bos_bear, sd_bear  (bool)
          atr, sh1, sh2, sl1, sl2, bull_struct, bear_struct
    """
    p = {**DEFAULT_PARAMS, **(params or {})}

    highs  = df["h"].values.astype(float)
    lows   = df["l"].values.astype(float)
    opens  = df["o"].values.astype(float)
    closes = df["c"].values.astype(float)
    n      = len(df)

    # Pre-compute ATR and rolling Premium/Discount range
    atr_vals = _calc_atr(highs, lows, closes, p["atr_len"])
    pd_highs = df["h"].rolling(p["pd_lookback"], min_periods=1).max().values
    pd_lows  = df["l"].rolling(p["pd_lookback"], min_periods=1).min().values
    equil    = (pd_highs + pd_lows) / 2.0

    # State variables (mirrors Pine Script `var` declarations)
    sh1 = sh2 = sl1 = sl2 = np.nan

    win = p["window"]
    never = -(win + 1)
    last_choch_bull = last_choch_bear = never
    last_liq_bull   = last_liq_bear   = never
    last_fvg_bull   = last_fvg_bear   = never
    last_bos_bull   = last_bos_bear   = never
    last_sd_bull    = last_sd_bear    = never

    left   = p["left_bars"]
    right  = p["right_bars"]
    mintick = p["mintick"]
    min_gap = p["min_fvg_ticks"] * mintick

    rows: list[dict] = []

    for i in range(n):
        # ── Update swing high/low (with right_bars delay, mirrors ta.pivothigh) ──
        check = i - right
        if check >= left:
            if _is_pivot_high(highs, check, left, right):
                sh2 = sh1
                sh1 = highs[check]
            if _is_pivot_low(lows, check, left, right):
                sl2 = sl1
                sl1 = lows[check]

        atr = atr_vals[i]
        if np.isnan(atr) or i == 0:
            rows.append(_empty_row(sh1, sh2, sl1, sl2))
            continue

        c_prev = closes[i - 1]
        c_curr = closes[i]

        # Market structure
        bull_struct = (
            not np.isnan(sh1) and not np.isnan(sh2) and sh1 > sh2 and
            not np.isnan(sl1) and not np.isnan(sl2) and sl1 > sl2
        )
        bear_struct = (
            not np.isnan(sh1) and not np.isnan(sh2) and sh1 < sh2 and
            not np.isnan(sl1) and not np.isnan(sl2) and sl1 < sl2
        )

        # ── 1. CHoCH ──────────────────────────────────────────────────────────
        if not np.isnan(sh1) and bear_struct and c_prev < sh1 and c_curr > sh1:
            last_choch_bull = i
        if not np.isnan(sl1) and bull_struct and c_prev > sl1 and c_curr < sl1:
            last_choch_bear = i
        cond_choch_bull = (i - last_choch_bull) <= win
        cond_choch_bear = (i - last_choch_bear) <= win

        # ── 2. OB ─────────────────────────────────────────────────────────────
        ob_bh, ob_bl = _find_ob(opens, highs, lows, closes, i, "bull", p["ob_lookback"], atr, p["atr_mult"])
        ob_sh, ob_sl = _find_ob(opens, highs, lows, closes, i, "bear", p["ob_lookback"], atr, p["atr_mult"])
        cond_ob_bull = not np.isnan(ob_bh) and ob_bl <= c_curr <= ob_bh
        cond_ob_bear = not np.isnan(ob_sh) and ob_sl <= c_curr <= ob_sh

        # ── 3. Liquidity Sweep ────────────────────────────────────────────────
        if not np.isnan(sl1) and lows[i] < sl1:
            last_liq_bull = i
        if not np.isnan(sh1) and highs[i] > sh1:
            last_liq_bear = i
        cond_liq_bull = (i - last_liq_bull) <= win
        cond_liq_bear = (i - last_liq_bear) <= win

        # ── 4. FVG ────────────────────────────────────────────────────────────
        if i >= 2:
            if lows[i] > highs[i - 2] and (lows[i] - highs[i - 2]) >= min_gap:
                last_fvg_bull = i
            if highs[i] < lows[i - 2] and (lows[i - 2] - highs[i]) >= min_gap:
                last_fvg_bear = i
        cond_fvg_bull = (i - last_fvg_bull) <= win
        cond_fvg_bear = (i - last_fvg_bear) <= win

        # ── 5. Premium / Discount ─────────────────────────────────────────────
        cond_pd_bull = c_curr < equil[i]   # discount  → bullish
        cond_pd_bear = c_curr > equil[i]   # premium   → bearish

        # ── 6. BOS ────────────────────────────────────────────────────────────
        if not np.isnan(sh1) and c_prev < sh1 and c_curr > sh1:
            last_bos_bull = i
        if not np.isnan(sl1) and c_prev > sl1 and c_curr < sl1:
            last_bos_bear = i
        cond_bos_bull = (i - last_bos_bull) <= win
        cond_bos_bear = (i - last_bos_bear) <= win

        # ── 7. S&D ────────────────────────────────────────────────────────────
        body_prev = abs(closes[i - 1] - opens[i - 1])
        body_curr = abs(closes[i] - opens[i])
        is_base   = body_prev < atr * p["base_mult"]
        if is_base and closes[i] > opens[i] and body_curr > atr * p["impulse_mult"]:
            last_sd_bull = i
        if is_base and closes[i] < opens[i] and body_curr > atr * p["impulse_mult"]:
            last_sd_bear = i
        cond_sd_bull = (i - last_sd_bull) <= win
        cond_sd_bear = (i - last_sd_bear) <= win

        # ── Score ──────────────────────────────────────────────────────────────
        score_bull = (int(cond_choch_bull) + int(cond_ob_bull) + int(cond_liq_bull) +
                      int(cond_fvg_bull)  + int(cond_pd_bull)  + int(cond_bos_bull) + int(cond_sd_bull))
        score_bear = (int(cond_choch_bear) + int(cond_ob_bear) + int(cond_liq_bear) +
                      int(cond_fvg_bear)  + int(cond_pd_bear)  + int(cond_bos_bear) + int(cond_sd_bear))

        rows.append({
            "score_bull":  score_bull,  "score_bear":  score_bear,
            "choch_bull":  cond_choch_bull, "ob_bull":  cond_ob_bull,  "liq_bull": cond_liq_bull,
            "fvg_bull":    cond_fvg_bull,   "pd_bull":  cond_pd_bull,  "bos_bull": cond_bos_bull,
            "sd_bull":     cond_sd_bull,
            "choch_bear":  cond_choch_bear, "ob_bear":  cond_ob_bear,  "liq_bear": cond_liq_bear,
            "fvg_bear":    cond_fvg_bear,   "pd_bear":  cond_pd_bear,  "bos_bear": cond_bos_bear,
            "sd_bear":     cond_sd_bear,
            "atr":         atr,
            "sh1": sh1, "sh2": sh2, "sl1": sl1, "sl2": sl2,
            "bull_struct": bull_struct, "bear_struct": bear_struct,
        })

    return pd.DataFrame(rows, index=df.index)


# ── Private helpers ────────────────────────────────────────────────────────────

def _calc_atr(highs, lows, closes, period: int) -> np.ndarray:
    h  = pd.Series(highs)
    l  = pd.Series(lows)
    c  = pd.Series(closes)
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean().values


def _is_pivot_high(highs: np.ndarray, i: int, left: int, right: int) -> bool:
    """True if highs[i] is strictly the maximum in [i-left … i+right]."""
    if i < left or i + right >= len(highs):
        return False
    pivot = highs[i]
    return pivot > highs[i - left:i].max() and pivot > highs[i + 1:i + right + 1].max()


def _is_pivot_low(lows: np.ndarray, i: int, left: int, right: int) -> bool:
    if i < left or i + right >= len(lows):
        return False
    pivot = lows[i]
    return pivot < lows[i - left:i].min() and pivot < lows[i + 1:i + right + 1].min()


def _find_ob(
    opens, highs, lows, closes,
    i: int, direction: str, lookback: int, atr: float, atr_mult: float,
) -> tuple[float, float]:
    """Finds the most recent Order Block up to `lookback` bars back.

    Bullish OB: last BEARISH candle immediately before a bullish impulse.
    Bearish OB: last BULLISH candle immediately before a bearish impulse.
    """
    for j in range(i - 1, max(i - lookback - 1, 0), -1):
        if j + 1 >= i:
            continue
        if direction == "bull":
            impulse  = closes[j + 1] > opens[j + 1] and (closes[j + 1] - opens[j + 1]) > atr * atr_mult
            is_ob    = closes[j] < opens[j]   # bearish candle is the OB
        else:
            impulse  = closes[j + 1] < opens[j + 1] and (opens[j + 1] - closes[j + 1]) > atr * atr_mult
            is_ob    = closes[j] > opens[j]   # bullish candle is the OB
        if is_ob and impulse:
            return highs[j], lows[j]
    return np.nan, np.nan


def detect_signals_chain(
    entry_df: pd.DataFrame,
    htf_dfs: list,
    params: dict | None = None,
) -> pd.DataFrame:
    """Generic multi-TF chain detection. Replaces the hardcoded D1+H1 logic.

    Architecture (same 7-condition score, generalized to any number of TFs):
      htf_dfs[0]  = macro TF (highest)  → C1: market structure gate
      htf_dfs[1]  = first confirm TF    → C2: OB zone, C3: CHoCH
      htf_dfs[2+] = extra confirm TFs   → AND filter applied to C2 and C3
      entry_df    = entry TF (lowest)   → C4: BOS, C5: FVG, C6: Liq, C7: OB/SD

    If htf_dfs is empty: gate=True, C2=C3=False → only entry TF conditions count (4 pts max).
    If only one HTF: gate only, no confirmation layer.
    """
    p = {**DEFAULT_MTF_PARAMS, **(params or {})}

    primary_sig = detect_signals(entry_df, p)
    closes      = entry_df["c"].values
    n           = len(entry_df)

    # ── C1: Macro gate (highest HTF structure) ────────────────────────────
    gate_bull = np.ones(n, dtype=bool)
    gate_bear = np.ones(n, dtype=bool)

    if htf_dfs:
        macro_df  = htf_dfs[0]
        macro_sig = detect_signals(macro_df, p)
        src = macro_df[["time"]].copy()
        src["bull"] = macro_sig["bull_struct"].values
        src["bear"] = macro_sig["bear_struct"].values
        src = src.sort_values("time")
        al = pd.merge_asof(
            entry_df[["time"]].sort_values("time"),
            src, on="time", direction="backward",
        ).set_index(entry_df.sort_values("time").index)
        gate_bull = al["bull"].fillna(False).values.astype(bool)
        gate_bear = al["bear"].fillna(False).values.astype(bool)

    # ── C2+C3: Confirmation TFs (htf_dfs[1:], ANDed together) ───────────
    c2_bull = np.zeros(n, dtype=bool)
    c2_bear = np.zeros(n, dtype=bool)
    c3_bull = np.zeros(n, dtype=bool)
    c3_bear = np.zeros(n, dtype=bool)

    for idx, confirm_df in enumerate(htf_dfs[1:]):
        if confirm_df is None or len(confirm_df) == 0:
            continue
        confirm_sig = detect_signals(confirm_df, p)
        ob_zones    = _extract_ob_zones(confirm_df, confirm_sig, p)
        choch_s     = _build_choch_series(confirm_sig, p.get("h1_window", 10))

        src = confirm_df[["time"]].copy()
        src["ob_bull_h"]  = ob_zones["ob_bull_h"].values
        src["ob_bull_l"]  = ob_zones["ob_bull_l"].values
        src["ob_bear_h"]  = ob_zones["ob_bear_h"].values
        src["ob_bear_l"]  = ob_zones["ob_bear_l"].values
        src["choch_bull"] = choch_s["choch_bull"].values
        src["choch_bear"] = choch_s["choch_bear"].values
        src = src.sort_values("time")

        al = pd.merge_asof(
            entry_df[["time"]].sort_values("time"),
            src, on="time", direction="backward",
        ).set_index(entry_df.sort_values("time").index)

        ob_bh = al["ob_bull_h"].values
        ob_bl = al["ob_bull_l"].values
        ob_sh = al["ob_bear_h"].values
        ob_sl = al["ob_bear_l"].values

        this_c2_bull = np.array([
            not np.isnan(ob_bh[i]) and ob_bl[i] <= closes[i] <= ob_bh[i]
            for i in range(n)
        ])
        this_c2_bear = np.array([
            not np.isnan(ob_sh[i]) and ob_sl[i] <= closes[i] <= ob_sh[i]
            for i in range(n)
        ])
        this_c3_bull = al["choch_bull"].fillna(False).values.astype(bool)
        this_c3_bear = al["choch_bear"].fillna(False).values.astype(bool)

        if idx == 0:
            c2_bull, c2_bear = this_c2_bull, this_c2_bear
            c3_bull, c3_bear = this_c3_bull, this_c3_bear
        else:
            c2_bull &= this_c2_bull
            c2_bear &= this_c2_bear
            c3_bull &= this_c3_bull
            c3_bear &= this_c3_bear

    # ── C4-C7: Entry TF conditions ────────────────────────────────────────
    c4_bull = primary_sig["bos_bull"].values.astype(bool)
    c4_bear = primary_sig["bos_bear"].values.astype(bool)
    c5_bull = primary_sig["fvg_bull"].values.astype(bool)
    c5_bear = primary_sig["fvg_bear"].values.astype(bool)
    c6_bull = primary_sig["liq_bull"].values.astype(bool)
    c6_bear = primary_sig["liq_bear"].values.astype(bool)
    c7_bull = primary_sig["ob_bull"].values.astype(bool) | primary_sig["sd_bull"].values.astype(bool)
    c7_bear = primary_sig["ob_bear"].values.astype(bool) | primary_sig["sd_bear"].values.astype(bool)

    score_bull = (gate_bull.astype(int) + c2_bull.astype(int) + c3_bull.astype(int) +
                  c4_bull.astype(int)  + c5_bull.astype(int)  + c6_bull.astype(int) + c7_bull.astype(int))
    score_bear = (gate_bear.astype(int) + c2_bear.astype(int) + c3_bear.astype(int) +
                  c4_bear.astype(int)   + c5_bear.astype(int)  + c6_bear.astype(int) + c7_bear.astype(int))

    return pd.DataFrame({
        "mtf_score_bull": score_bull,  "mtf_score_bear": score_bear,
        "score_bull":     score_bull,  "score_bear":     score_bear,
        "d1_bull":        gate_bull,   "d1_bear":        gate_bear,
        "h1_ob_bull":     c2_bull,     "h1_ob_bear":     c2_bear,
        "h1_choch_bull":  c3_bull,     "h1_choch_bear":  c3_bear,
        "bos_bull":       c4_bull,     "bos_bear":       c4_bear,
        "fvg_bull":       c5_bull,     "fvg_bear":       c5_bear,
        "liq_bull":       c6_bull,     "liq_bear":       c6_bear,
        "entry_bull":     c7_bull,     "entry_bear":     c7_bear,
        "gate_bull":      gate_bull,   "gate_bear":      gate_bear,
        "choch_bull": primary_sig["choch_bull"].values,
        "choch_bear": primary_sig["choch_bear"].values,
        "ob_bull":    c7_bull,         "ob_bear":    c7_bear,
        "pd_bull":    primary_sig["pd_bull"].values,
        "pd_bear":    primary_sig["pd_bear"].values,
        "sd_bull":    primary_sig["sd_bull"].values,
        "sd_bear":    primary_sig["sd_bear"].values,
        "atr":        primary_sig["atr"].values,
    }, index=entry_df.index)


def detect_signals_mtf(
    primary_df: pd.DataFrame,
    h1_df: pd.DataFrame | None = None,
    d1_df: pd.DataFrame | None = None,
    params: dict | None = None,
) -> pd.DataFrame:
    """Legacy wrapper — kept for backward compatibility. Calls detect_signals_chain."""
    htf_dfs = []
    if d1_df is not None:
        htf_dfs.append(d1_df)
    if h1_df is not None:
        htf_dfs.append(h1_df)
    return detect_signals_chain(primary_df, htf_dfs, params)


def _extract_ob_zones(df: pd.DataFrame, sig: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Returns per-H1-bar the most recent OB zone (h, l) for bull and bear."""
    highs  = df["h"].values.astype(float)
    lows   = df["l"].values.astype(float)
    opens  = df["o"].values.astype(float)
    closes = df["c"].values.astype(float)
    atr_v  = sig["atr"].values
    n = len(df)

    ob_bull_h = np.full(n, np.nan)
    ob_bull_l = np.full(n, np.nan)
    ob_bear_h = np.full(n, np.nan)
    ob_bear_l = np.full(n, np.nan)

    for i in range(n):
        atr = atr_v[i]
        if np.isnan(atr):
            continue
        bh, bl = _find_ob(opens, highs, lows, closes, i, "bull", p["ob_lookback"], atr, p["atr_mult"])
        sh, sl = _find_ob(opens, highs, lows, closes, i, "bear", p["ob_lookback"], atr, p["atr_mult"])
        ob_bull_h[i] = bh; ob_bull_l[i] = bl
        ob_bear_h[i] = sh; ob_bear_l[i] = sl

    return pd.DataFrame({"ob_bull_h": ob_bull_h, "ob_bull_l": ob_bull_l,
                          "ob_bear_h": ob_bear_h, "ob_bear_l": ob_bear_l})


def _build_choch_series(sig: pd.DataFrame, window: int) -> pd.DataFrame:
    """Converts instantaneous CHoCH flags into windowed active states."""
    n = len(sig)
    choch_bull = np.zeros(n, dtype=bool)
    choch_bear = np.zeros(n, dtype=bool)
    last_cb = last_cs = -(window + 1)
    for i in range(n):
        if sig["choch_bull"].iloc[i]:
            last_cb = i
        if sig["choch_bear"].iloc[i]:
            last_cs = i
        choch_bull[i] = (i - last_cb) <= window
        choch_bear[i] = (i - last_cs) <= window
    return pd.DataFrame({"choch_bull": choch_bull, "choch_bear": choch_bear})


def _empty_row(sh1, sh2, sl1, sl2) -> dict:
    return {
        "score_bull": 0, "score_bear": 0,
        "choch_bull": False, "ob_bull": False, "liq_bull": False,
        "fvg_bull":   False, "pd_bull": False, "bos_bull": False, "sd_bull": False,
        "choch_bear": False, "ob_bear": False, "liq_bear": False,
        "fvg_bear":   False, "pd_bear": False, "bos_bear": False, "sd_bear": False,
        "atr": np.nan,
        "sh1": sh1, "sh2": sh2, "sl1": sl1, "sl2": sl2,
        "bull_struct": False, "bear_struct": False,
    }
