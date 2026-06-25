"""Capa de acceso a datos para la configuración del bot SMC-FTMO.

Backends (auto-detectados por orden de prioridad):
  1. Supabase  — si SUPABASE_URL + SUPABASE_KEY están definidos (recomendado en Render free)
  2. SQLite    — /data/config.db (Render con disco persistente) o ./config.db (dev local)

Cifrado de campos sensibles:
  Generar clave: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  Guardar como SECRET_KEY en las variables de entorno de Render.
  Sin SECRET_KEY: los datos se guardan en texto plano (solo para desarrollo local).
"""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

# ── Cifrado Fernet (opcional) ──────────────────────────────────────────────────

_fernet = None
try:
    from cryptography.fernet import Fernet, InvalidToken
    _sk = os.environ.get("SECRET_KEY", "").strip()
    if _sk:
        _fernet = Fernet(_sk.encode())
except Exception:
    # ImportError si cryptography no está, ValueError/binascii.Error si la clave es inválida
    _fernet = None   # cryptography no instalado → sin cifrado

_SENSITIVE = {"mt5_password", "tg_token"}


def _enc(v: str) -> str:
    return _fernet.encrypt(v.encode()).decode() if (_fernet and v) else v


def _dec(v: str) -> str:
    if not (_fernet and v):
        return v
    try:
        return _fernet.decrypt(v.encode()).decode()
    except Exception:
        return v   # ya en texto plano o corrompido


# ── Esquema SQL compartido ─────────────────────────────────────────────────────

_COLUMNS = [
    "mt5_login", "mt5_password", "mt5_server", "mt5_path",
    "tg_token", "tg_chat_id",
    "symbol", "tf_chain",
    "min_score", "sl_pips", "rr", "risk_pct",
    "daily_limit_eur", "balance", "currency",
    "use_ff", "news_buffer_mins",
    "only_short", "only_long",
    "updated_at",
]

_DEFAULTS: dict[str, Any] = {
    "mt5_login": "", "mt5_password": "", "mt5_server": "", "mt5_path": "",
    "tg_token": "", "tg_chat_id": "",
    "symbol": "EURUSD", "tf_chain": "D1,H1,M15,M5",
    "min_score": 5, "sl_pips": 20.0, "rr": 3.0, "risk_pct": 0.5,
    "daily_limit_eur": 100.0, "balance": 10000.0, "currency": "EUR",
    "use_ff": 1, "news_buffer_mins": 60,
    "only_short": 0, "only_long": 0,
    "updated_at": "",
}


def _row_to_dict(row: dict) -> dict:
    """Descifra campos sensibles y convierte tf_chain a lista."""
    d = dict(row)
    for f in _SENSITIVE:
        if d.get(f):
            d[f] = _dec(str(d[f]))
    tf = d.get("tf_chain", "D1,H1,M15,M5")
    d["tf_chain"] = tf.split(",") if isinstance(tf, str) else tf
    d["use_ff"]      = bool(int(d.get("use_ff", 1)))
    d["only_short"]  = bool(int(d.get("only_short", 0)))
    d["only_long"]   = bool(int(d.get("only_long", 0)))
    return d


def _dict_to_row(cfg: dict) -> dict:
    """Cifra campos sensibles y convierte tf_chain a string para almacenamiento."""
    d = {**_DEFAULTS, **cfg}
    for f in _SENSITIVE:
        if d.get(f):
            d[f] = _enc(str(d[f]))
    if isinstance(d.get("tf_chain"), list):
        d["tf_chain"] = ",".join(d["tf_chain"])
    d["use_ff"]     = 1 if d.get("use_ff")     else 0
    d["only_short"] = 1 if d.get("only_short") else 0
    d["only_long"]  = 1 if d.get("only_long")  else 0
    d["updated_at"] = datetime.now(timezone.utc).isoformat()
    return d


# ── Backend SQLite ─────────────────────────────────────────────────────────────

_DB_PATH = os.environ.get("DB_PATH", "config.db")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS bot_config (
    id              INTEGER PRIMARY KEY,
    mt5_login       TEXT DEFAULT '',
    mt5_password    TEXT DEFAULT '',
    mt5_server      TEXT DEFAULT '',
    mt5_path        TEXT DEFAULT '',
    tg_token        TEXT DEFAULT '',
    tg_chat_id      TEXT DEFAULT '',
    symbol          TEXT DEFAULT 'EURUSD',
    tf_chain        TEXT DEFAULT 'D1,H1,M15,M5',
    min_score       INTEGER DEFAULT 5,
    sl_pips         REAL DEFAULT 20.0,
    rr              REAL DEFAULT 3.0,
    risk_pct        REAL DEFAULT 0.5,
    daily_limit_eur REAL DEFAULT 100.0,
    balance         REAL DEFAULT 10000.0,
    currency        TEXT DEFAULT 'EUR',
    use_ff          INTEGER DEFAULT 1,
    news_buffer_mins INTEGER DEFAULT 60,
    only_short      INTEGER DEFAULT 0,
    only_long       INTEGER DEFAULT 0,
    updated_at      TEXT DEFAULT ''
);
"""


def _sqlite_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(_CREATE_TABLE)
    conn.commit()
    return conn


def _sqlite_load() -> dict | None:
    with _sqlite_conn() as conn:
        row = conn.execute("SELECT * FROM bot_config WHERE id=1").fetchone()
    return _row_to_dict(dict(row)) if row else None


def _sqlite_save(cfg: dict) -> None:
    row = _dict_to_row(cfg)
    cols = _COLUMNS
    with _sqlite_conn() as conn:
        existing = conn.execute("SELECT id FROM bot_config WHERE id=1").fetchone()
        if existing:
            sets = ", ".join(f"{c}=?" for c in cols)
            vals = [row.get(c, _DEFAULTS.get(c, "")) for c in cols] + [1]
            conn.execute(f"UPDATE bot_config SET {sets} WHERE id=?", vals)
        else:
            all_cols = ["id"] + cols
            ph = ",".join("?" * len(all_cols))
            vals = [1] + [row.get(c, _DEFAULTS.get(c, "")) for c in cols]
            conn.execute(f"INSERT INTO bot_config ({','.join(all_cols)}) VALUES ({ph})", vals)
        conn.commit()


def _sqlite_exists() -> bool:
    with _sqlite_conn() as conn:
        row = conn.execute("SELECT id FROM bot_config WHERE id=1").fetchone()
    return row is not None


# ── Backend Supabase (REST API sin dependencias extra) ─────────────────────────

_SB_URL   = os.environ.get("SUPABASE_URL",  "").rstrip("/")
_SB_KEY   = os.environ.get("SUPABASE_KEY",  "")
_SB_TABLE = "bot_config"
_USE_SB   = bool(_SB_URL and _SB_KEY)


def _sb_headers() -> dict:
    return {
        "apikey":        _SB_KEY,
        "Authorization": f"Bearer {_SB_KEY}",
        "Content-Type":  "application/json",
    }


def _sb_request(method: str, path: str, body: dict | None = None) -> Any:
    url  = f"{_SB_URL}/rest/v1/{path}"
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(url, data=data, headers=_sb_headers(), method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def _sb_load() -> dict | None:
    try:
        rows = _sb_request("GET", f"{_SB_TABLE}?select=*&limit=1")
        return _row_to_dict(rows[0]) if rows else None
    except Exception:
        return None


def _sb_save(cfg: dict) -> None:
    row = _dict_to_row(cfg)
    row["id"] = 1
    # upsert via POST with Prefer: resolution=merge-duplicates
    url  = f"{_SB_URL}/rest/v1/{_SB_TABLE}"
    data = json.dumps(row).encode()
    hdrs = {**_sb_headers(), "Prefer": "resolution=merge-duplicates,return=minimal"}
    req  = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    with urllib.request.urlopen(req, timeout=10):
        pass


def _sb_exists() -> bool:
    try:
        rows = _sb_request("GET", f"{_SB_TABLE}?select=id&limit=1")
        return bool(rows)
    except Exception:
        return False


# ── API pública ────────────────────────────────────────────────────────────────

def load_config() -> dict | None:
    """Carga la configuración del bot. None si aún no se ha configurado."""
    return _sb_load() if _USE_SB else _sqlite_load()


def save_config(cfg: dict) -> None:
    """Guarda (upsert) la configuración del bot."""
    if _USE_SB:
        _sb_save(cfg)
    else:
        _sqlite_save(cfg)


def config_exists() -> bool:
    """True si ya existe una configuración guardada."""
    return _sb_exists() if _USE_SB else _sqlite_exists()


def backend_name() -> str:
    return "Supabase" if _USE_SB else f"SQLite ({_DB_PATH})"


def encryption_active() -> bool:
    return _fernet is not None
