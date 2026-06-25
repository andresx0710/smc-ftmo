"""OHLCV data download and caching.

Sources:
  1. MT5 terminal (primary)  — requires MetaTrader5 installed and running
  2. CSV file  (fallback)    — any file with columns: time, o, h, l, c, vol

Timeframe strings:  M1 M5 M15 M30 H1 H4 D1
"""

import os
import time as _time
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

try:
    import MetaTrader5 as mt5
    _MT5_AVAILABLE = True
except ImportError:
    _MT5_AVAILABLE = False

# MT5 timeframe constants (resolved lazily to avoid import errors when MT5 absent)
_TF_MAP: dict = {}


def _get_tf_map() -> dict:
    global _TF_MAP
    if not _TF_MAP and _MT5_AVAILABLE:
        _TF_MAP = {
            "M1":  mt5.TIMEFRAME_M1,
            "M5":  mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1":  mt5.TIMEFRAME_H1,
            "H4":  mt5.TIMEFRAME_H4,
            "D1":  mt5.TIMEFRAME_D1,
        }
    return _TF_MAP


# ── MT5 download ───────────────────────────────────────────────────────────────

def download_from_mt5(
    symbol: str,
    timeframe: str,
    n_bars: int = 5000,
    login: int = 0,
    password: str = "",
    server: str = "",
    mt5_path: str = "",      # unified name (was 'path' — kept as mt5_path everywhere)
    retries: int = 3,
    retry_delay: float = 1.0,
) -> pd.DataFrame:
    """Downloads OHLCV data from MT5 terminal.

    Args:
        symbol:    MT5 symbol name, e.g. "EURUSD"
        timeframe: "M1", "M5", "M15", "M30", "H1", "H4", "D1"
        n_bars:    Number of bars to download (most recent)
        mt5_path:  Path to MT5 terminal .exe (optional)
        retries:   Times to retry if MT5 returns empty data
        retry_delay: Seconds between retries (MT5 may need time to sync)

    Returns:
        DataFrame with columns: time, o, h, l, c, vol
    """
    if not _MT5_AVAILABLE:
        raise ImportError("MetaTrader5 package not installed. Run: pip install MetaTrader5")

    # Connect if credentials provided
    if login and password and server:
        kwargs: dict = {"login": login, "password": password, "server": server}
        if mt5_path:
            kwargs["path"] = mt5_path
        if not mt5.initialize(**kwargs):
            raise ConnectionError(f"MT5 connect failed: {mt5.last_error()}")
    elif not mt5.initialize():
        raise ConnectionError(f"MT5 initialize() failed: {mt5.last_error()}")

    tf = _get_tf_map().get(timeframe.upper())
    if tf is None:
        raise ValueError(f"Unknown timeframe '{timeframe}'. Valid: {list(_get_tf_map())}")

    # Ensure the symbol is loaded in the terminal (critical for D1/H1 on new connections)
    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"MT5 no pudo seleccionar {symbol}: {mt5.last_error()}")

    # Retry loop — MT5 can return None/empty on first call if terminal is still syncing
    rates = None
    last_err = None
    for attempt in range(1, retries + 1):
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, n_bars)
        if rates is not None and len(rates) > 0:
            break
        last_err = mt5.last_error()
        if attempt < retries:
            _time.sleep(retry_delay)

    if rates is None or len(rates) == 0:
        raise RuntimeError(
            f"MT5: sin datos para {symbol} {timeframe} tras {retries} intentos. "
            f"Último error: {last_err}"
        )

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.rename(columns={
        "open": "o", "high": "h", "low": "l", "close": "c", "tick_volume": "vol",
    })
    df = df[["time", "o", "h", "l", "c", "vol"]].reset_index(drop=True)

    print(f"MT5: descargadas {len(df)} barras de {symbol} {timeframe} "
          f"({df['time'].iloc[0].date()} → {df['time'].iloc[-1].date()})")
    return df


# ── CSV handling ───────────────────────────────────────────────────────────────

def load_csv(path: str) -> pd.DataFrame:
    """Loads OHLCV from CSV. Accepts both raw MT5 exports and cached downloads.

    Expected columns (any order): time, o, h, l, c  (vol optional)
    """
    df = pd.read_csv(path)

    # Normalise column names
    rename = {
        "open": "o", "high": "h", "low": "l", "close": "c",
        "Open": "o", "High": "h", "Low": "l", "Close": "c",
        "tick_volume": "vol", "Volume": "vol",
        "Date": "time", "Datetime": "time", "date": "time",
        "<OPEN>": "o", "<HIGH>": "h", "<LOW>": "l", "<CLOSE>": "c",
        "<TICKVOL>": "vol", "<DATE>": "time",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    if "time" not in df.columns:
        raise ValueError(f"No 'time' column found in {path}. Columns: {list(df.columns)}")

    df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
    if df["time"].isna().all():
        df["time"] = pd.to_datetime(df["time"], utc=False, errors="coerce")

    if "vol" not in df.columns:
        df["vol"] = 0

    df = df[["time", "o", "h", "l", "c", "vol"]].dropna(subset=["time", "o", "h", "l", "c"])
    df = df.sort_values("time").reset_index(drop=True)

    print(f"CSV: cargadas {len(df)} barras desde {path} "
          f"({df['time'].iloc[0].date()} → {df['time'].iloc[-1].date()})")
    return df


def save_csv(df: pd.DataFrame, path: str) -> None:
    """Saves OHLCV DataFrame to CSV."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)
    print(f"CSV guardado: {path}")


# ── Smart loader ───────────────────────────────────────────────────────────────

TF_MINUTES: dict = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H4": 240, "D1": 1440,
}

_RESAMPLE_FREQ: dict = {
    "M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min",
    "H1": "1h",   "H4": "4h",   "D1":  "1D",
}


def resample_ohlcv(df: pd.DataFrame, target_tf: str) -> pd.DataFrame:
    """Resamples an OHLCV DataFrame to a higher timeframe."""
    freq = _RESAMPLE_FREQ.get(target_tf.upper())
    if freq is None:
        raise ValueError(f"Timeframe desconocido para resample: '{target_tf}'. "
                         f"Válidos: {list(_RESAMPLE_FREQ)}")

    d = df.copy()
    d["time"] = pd.to_datetime(d["time"], utc=True)
    d = d.set_index("time").sort_index()

    agg = d.resample(freq, label="left", closed="left").agg(
        o=("o", "first"),
        h=("h", "max"),
        l=("l", "min"),
        c=("c", "last"),
        vol=("vol", "sum"),
    ).dropna(subset=["o", "c"])

    result = agg.reset_index()
    return result[["time", "o", "h", "l", "c", "vol"]].reset_index(drop=True)


def download_multi_tf_chain(
    symbol:        str,
    tf_chain:      list,
    n_bars:        int       = 5000,
    cache_dir:     str       = "backtest/data",
    force_refresh: bool      = False,
    login:         int       = 0,
    password:      str       = "",
    server:        str       = "",
    mt5_path:      str       = "",
) -> dict:
    """Downloads (or derives) OHLCV data for every TF in a chain.

    Data resolution strategy (per TF):
      1. Cached CSV  → load immediately (if not force_refresh)
      2. MT5         → download and cache (with symbol_select + retry)
      3. Resample    → derive from entry TF if MT5 unavailable for higher TFs

    Returns:
        Dict keyed by TF string (uppercase): {"D1": df, "H1": df, "M15": df, "M5": df}
    """
    chain = [tf.upper() for tf in tf_chain]
    entry_tf    = chain[-1]
    entry_mins  = TF_MINUTES.get(entry_tf, 60)
    total_mins  = n_bars * entry_mins

    kwargs_mt5 = dict(login=login, password=password, server=server, mt5_path=mt5_path)

    n_bars_map: dict = {}
    for tf in chain:
        tf_mins        = TF_MINUTES.get(tf, 60)
        n_bars_map[tf] = max(200, int(total_mins / tf_mins) + 100)
    n_bars_map[entry_tf] = n_bars

    bar_info = " | ".join(f"{tf}({n_bars_map[tf]}b)" for tf in chain)
    print(f"Cargando {symbol}: {bar_info}...")

    result: dict = {}

    # ── Load entry TF first (needed for resampling fallback) ──────────────
    result[entry_tf] = get_ohlcv(
        symbol, entry_tf, n_bars, cache_dir=cache_dir,
        force_refresh=force_refresh, **kwargs_mt5,
    )
    entry_df = result[entry_tf]

    # ── Load / derive each higher TF ──────────────────────────────────────
    for tf in chain[:-1]:
        cached = os.path.join(cache_dir, f"{symbol}_{tf}.csv")

        # 1. Cached CSV (skip if force_refresh)
        if os.path.exists(cached) and not force_refresh:
            result[tf] = load_csv(cached)
            continue

        # 2. MT5 download (with retry + symbol_select)
        try:
            df_mt5 = download_from_mt5(
                symbol, tf, n_bars_map[tf],
                login=login, password=password, server=server, mt5_path=mt5_path,
            )
            save_csv(df_mt5, cached)
            result[tf] = df_mt5
            continue
        except Exception as exc:
            print(f"  MT5 falló para {tf} ({exc}) → intentando resample desde {entry_tf}...")

        # 3. Resample from entry TF (only if target is HIGHER timeframe)
        tf_mins     = TF_MINUTES.get(tf, 0)
        entry_mins_ = TF_MINUTES.get(entry_tf, 0)
        if tf_mins > entry_mins_:
            print(f"  Derivando {tf} desde {entry_tf} por resample "
                  f"(MT5 no disponible para este TF)...")
            resampled = resample_ohlcv(entry_df, tf)
            save_csv(resampled, cached)
            result[tf] = resampled
            continue

        raise RuntimeError(
            f"No se puede obtener {symbol} {tf}: sin caché, MT5 falló, "
            f"y {tf} ({tf_mins}min) es más fino que el entry TF {entry_tf} ({entry_mins_}min). "
            f"Proporciona un CSV con --input o conecta MT5."
        )

    # ── Clip HTF data: only remove future bars beyond entry TF end ────────
    # Keep ALL historical HTF context — the detector needs D1/H1 history
    # to find structure (CHoCH, BOS, Order Blocks). Only discard bars
    # that are ahead of the last M5 candle (would have incomplete OHLC).
    t_max = entry_df["time"].max()
    for tf in chain[:-1]:
        df = result[tf]
        result[tf] = df[df["time"] <= t_max].reset_index(drop=True)

    lengths = " | ".join(f"{tf}: {len(result[tf])}" for tf in chain)
    print(f"  {lengths}")
    return result


def download_multi_tf(
    symbol:    str,
    entry_tf:  str,
    n_bars:    int       = 5000,
    cache_dir: str       = "backtest/data",
    force_refresh: bool  = False,
    login:     int       = 0,
    password:  str       = "",
    server:    str       = "",
    mt5_path:  str       = "",
) -> dict:
    """Legacy wrapper. Use download_multi_tf_chain for new code."""
    chain_data = download_multi_tf_chain(
        symbol=symbol, tf_chain=["D1", "H1", entry_tf], n_bars=n_bars,
        cache_dir=cache_dir, force_refresh=force_refresh,
        login=login, password=password, server=server, mt5_path=mt5_path,
    )
    entry = entry_tf.upper()
    return {"entry": chain_data[entry], "h1": chain_data["H1"], "d1": chain_data["D1"]}


def get_ohlcv(
    symbol:        str,
    timeframe:     str,
    n_bars:        int        = 5000,
    cache_dir:     str        = "backtest/data",
    force_refresh: bool       = False,
    csv_path:      Optional[str] = None,
    login:         int        = 0,
    password:      str        = "",
    server:        str        = "",
    mt5_path:      str        = "",
) -> pd.DataFrame:
    """Returns OHLCV data, checking (in order):
    1. Explicit CSV path if provided
    2. Cached CSV in cache_dir (unless force_refresh)
    3. MT5 download → saved to cache
    """
    if csv_path:
        return load_csv(csv_path)

    cached = os.path.join(cache_dir, f"{symbol}_{timeframe}.csv")
    if os.path.exists(cached) and not force_refresh:
        return load_csv(cached)

    df = download_from_mt5(
        symbol, timeframe, n_bars,
        login=login, password=password, server=server, mt5_path=mt5_path,
    )
    save_csv(df, cached)
    return df
