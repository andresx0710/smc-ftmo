"""SMC-FTMO Cloud Dashboard — FastAPI.

Variables de entorno requeridas (configurar en Render/Railway):
  PUSH_TOKEN    — token secreto que usa el bot para hacer POST /push
  ACCESS_TOKEN  — clave para ver el dashboard (?key=... en la URL)
                  dejar vacío = dashboard público (no recomendado)

Deploy en Render.com:
  Build:  pip install -r cloud/requirements.txt
  Start:  uvicorn cloud.app:app --host 0.0.0.0 --port $PORT

Deploy en Railway:
  Igual que Render. Configura las env vars en el panel.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from cloud.db import (
    load_config, save_config, config_exists,
    backend_name, encryption_active,
)

# ── Configuración ──────────────────────────────────────────────────────────────

PUSH_TOKEN   = os.environ.get("PUSH_TOKEN",   "change-me-push-token")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN", "")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

_state: dict[str, Any] = {
    "status":          "bot_offline",
    "symbol":          "—",
    "tf_chain":        "—",
    "balance":         0.0,
    "equity":          0.0,
    "daily_pnl":       0.0,
    "daily_limit_eur": 100.0,
    "daily_start_eq":  0.0,
    "ftmo_floor":      9000.0,
    "initial_balance": 10000.0,
    "open_positions":  [],
    "recent_trades":   [],
    "session":         "—",
    "in_session":      False,
    "news_status":     "none",
    "next_news_title": "",
    "next_news_mins":  None,
    "score_bull":      0,
    "score_bear":      0,
    "min_score":       5,
    "last_signal_dir": None,
    "cycle":           0,
    "last_update":     None,
    "last_push":       None,   # cuándo recibimos el último POST /push
    "dry_run":         False,
    "log_lines":       [],
}


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"ok": True})


@app.post("/push")
async def push_state(request: Request) -> JSONResponse:
    """El bot local envía su estado aquí en cada ciclo."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != PUSH_TOKEN:
        raise HTTPException(status_code=401, detail="Token inválido")
    global _state
    try:
        body = await request.json()
        _state = body
    except Exception:
        raise HTTPException(status_code=400, detail="JSON inválido")
    _state["last_push"] = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    return JSONResponse({"ok": True, "ts": _state["last_push"]})


@app.get("/api/state")
async def get_state(key: str = Query(default="")) -> JSONResponse:
    """Estado JSON consumido por el dashboard JS."""
    if ACCESS_TOKEN and key != ACCESS_TOKEN:
        raise HTTPException(status_code=401, detail="Acceso denegado")
    return JSONResponse(_state)


@app.get("/config")
async def get_config(request: Request) -> JSONResponse:
    """El bot local llama aquí al arrancar para obtener su configuración completa."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != PUSH_TOKEN:
        raise HTTPException(status_code=401, detail="Token inválido")
    cfg = load_config()
    if cfg is None:
        raise HTTPException(status_code=404, detail="Configuración no encontrada — usa /setup")
    return JSONResponse(cfg)


@app.get("/setup", response_class=HTMLResponse)
async def setup_form(key: str = Query(default="")) -> HTMLResponse:
    """Formulario de configuración del bot (protegido por ACCESS_TOKEN)."""
    if ACCESS_TOKEN and key != ACCESS_TOKEN:
        return HTMLResponse(_ACCESS_DENIED, status_code=401)
    cfg  = load_config() or {}
    warn = "" if encryption_active() else (
        "<div class='warn'>⚠ SECRET_KEY no configurado — las credenciales se guardan sin cifrar. "
        "Genera una clave y añádela como variable de entorno.</div>"
    )
    db_info = f"Base de datos: <strong>{backend_name()}</strong>"
    return HTMLResponse(_setup_html(cfg, warn, db_info, key))


@app.post("/setup")
async def save_setup(request: Request, key: str = Query(default="")) -> HTMLResponse:
    """Guarda la configuración enviada por el formulario."""
    if ACCESS_TOKEN and key != ACCESS_TOKEN:
        raise HTTPException(status_code=401, detail="Acceso denegado")

    form = await request.form()
    existing = load_config() or {}

    def _fval(name: str, default: Any = "") -> Any:
        return form.get(name, existing.get(name, default))

    # Campos de contraseña: si el usuario los dejó en blanco, conservar el valor anterior
    def _secret(name: str) -> str:
        v = form.get(name, "").strip()
        return v if v else existing.get(name, "")

    cfg = {
        "mt5_login":        _fval("mt5_login", ""),
        "mt5_password":     _secret("mt5_password"),
        "mt5_server":       _fval("mt5_server", ""),
        "mt5_path":         _fval("mt5_path", ""),
        "tg_token":         _secret("tg_token"),
        "tg_chat_id":       _fval("tg_chat_id", ""),
        "symbol":           _fval("symbol", "EURUSD"),
        "tf_chain":         _fval("tf_chain", "D1,H1,M15,M5"),
        "min_score":        int(_fval("min_score", 5)),
        "sl_pips":          float(_fval("sl_pips", 20.0)),
        "rr":               float(_fval("rr", 3.0)),
        "risk_pct":         float(_fval("risk_pct", 0.5)),
        "daily_limit_eur":  float(_fval("daily_limit_eur", 100.0)),
        "balance":          float(_fval("balance", 10000.0)),
        "currency":         _fval("currency", "EUR"),
        "use_ff":           1 if form.get("use_ff") else 0,
        "news_buffer_mins": int(_fval("news_buffer_mins", 60)),
        "only_short":       1 if form.get("only_short") else 0,
        "only_long":        1 if form.get("only_long")  else 0,
    }

    try:
        save_config(cfg)
    except Exception as e:
        return HTMLResponse(
            _setup_html(cfg, f"<div class='err'>❌ Error guardando: {e}</div>",
                        f"Base de datos: {backend_name()}", key)
        )

    return HTMLResponse(
        _setup_html(cfg, "<div class='ok'>✅ Configuración guardada correctamente.</div>",
                    f"Base de datos: {backend_name()}", key)
    )


@app.get("/", response_class=HTMLResponse)
async def dashboard(key: str = Query(default="")) -> HTMLResponse:
    """Panel principal. Redirige a /setup si no hay configuración."""
    if not config_exists():
        return RedirectResponse(url=f"/setup?key={key}")
    return HTMLResponse(_HTML)


# ── HTML: Access Denied ───────────────────────────────────────────────────────

_ACCESS_DENIED = """<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>SMC-FTMO</title>
<style>body{background:#0a0e1a;color:#f9fafb;font-family:system-ui,sans-serif;
display:flex;align-items:center;justify-content:center;min-height:100vh;flex-direction:column;gap:1rem;}
h1{color:#ef4444;}p{color:#6b7280;max-width:360px;text-align:center;}
input{background:#111827;border:1px solid #1f2937;color:#f9fafb;padding:.6rem 1rem;
border-radius:8px;font-size:.875rem;width:280px;outline:none;}
button{background:#10b981;color:#fff;border:none;border-radius:8px;padding:.6rem 1.5rem;
cursor:pointer;font-weight:600;}</style></head>
<body><h1>🔒 Acceso restringido</h1>
<p>Introduce la clave de acceso o usa el enlace completo.</p>
<input type="password" id="k" placeholder="ACCESS_TOKEN..." onkeydown="if(event.key==='Enter')go()">
<button onclick="go()">Acceder</button>
<script>function go(){const k=document.getElementById('k').value.trim();
if(k)window.location.href='/setup?key='+encodeURIComponent(k);}</script>
</body></html>"""


# ── HTML: Setup form (generado dinámicamente) ─────────────────────────────────

def _setup_html(cfg: dict, banner: str, db_info: str, key: str) -> str:
    tf = cfg.get("tf_chain", "D1,H1,M15,M5")
    if isinstance(tf, list):
        tf = ",".join(tf)

    def _v(k: str, default: str = "") -> str:
        return str(cfg.get(k, default)).replace('"', "&quot;")

    def _checked(k: str) -> str:
        return "checked" if cfg.get(k) else ""

    symbols = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "NAS100", "BTCUSD"]
    sym_opts = "".join(
        f'<option value="{s}" {"selected" if _v("symbol","EURUSD")==s else ""}>{s}</option>'
        for s in symbols
    )

    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SMC-FTMO — Configuración</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{--bg:#0a0e1a;--card:#111827;--border:#1f2937;--accent:#10b981;
--red:#ef4444;--yellow:#f59e0b;--text:#f9fafb;--muted:#6b7280}}
body{{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;
font-size:.875rem;min-height:100vh;padding:1.5rem 1rem 3rem}}
.wrap{{max-width:680px;margin:0 auto}}
.logo{{font-size:1.25rem;font-weight:700;color:var(--accent);letter-spacing:.05em}}
.subtitle{{color:var(--muted);font-size:.8rem;margin-top:.25rem;margin-bottom:1.5rem}}
.db-tag{{background:var(--border);color:var(--muted);font-size:.7rem;padding:.2rem .5rem;
border-radius:4px;margin-left:.5rem}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:10px;
padding:1.25rem 1.5rem;margin-bottom:1rem}}
.card-title{{font-size:.7rem;text-transform:uppercase;letter-spacing:.08em;
color:var(--muted);margin-bottom:1rem;border-bottom:1px solid var(--border);padding-bottom:.5rem}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:.75rem}}
@media(max-width:500px){{.grid{{grid-template-columns:1fr}}}}
.field{{display:flex;flex-direction:column;gap:.35rem}}
.field label{{font-size:.75rem;color:var(--muted)}}
.field input,.field select{{background:#0d1420;border:1px solid var(--border);color:var(--text);
padding:.55rem .8rem;border-radius:8px;font-size:.875rem;outline:none;transition:border .2s}}
.field input:focus,.field select:focus{{border-color:var(--accent)}}
.field .hint{{font-size:.68rem;color:var(--muted)}}
.toggle-row{{display:flex;align-items:center;gap:.6rem;padding:.3rem 0}}
.toggle-row label{{font-size:.8rem;color:var(--text);cursor:pointer}}
input[type=checkbox]{{width:16px;height:16px;accent-color:var(--accent);cursor:pointer}}
.btn{{background:var(--accent);color:#fff;border:none;border-radius:8px;
padding:.7rem 2rem;font-size:.9rem;font-weight:600;cursor:pointer;width:100%;
margin-top:1rem;transition:opacity .2s}}
.btn:hover{{opacity:.85}}
.btn-dash{{background:var(--border);color:var(--text);border:none;border-radius:8px;
padding:.5rem 1.2rem;font-size:.8rem;cursor:pointer;margin-top:.5rem;width:100%}}
.ok{{background:#064e3b;color:#6ee7b7;border:1px solid #10b981;border-radius:8px;
padding:.75rem 1rem;margin-bottom:1rem;font-size:.85rem}}
.warn{{background:#78350f;color:#fcd34d;border:1px solid #f59e0b;border-radius:8px;
padding:.75rem 1rem;margin-bottom:1rem;font-size:.85rem}}
.err{{background:#7f1d1d;color:#fca5a5;border:1px solid #ef4444;border-radius:8px;
padding:.75rem 1rem;margin-bottom:1rem;font-size:.85rem}}
</style></head>
<body><div class="wrap">

<div class="logo">SMC-FTMO <span class="db-tag">{db_info}</span></div>
<div class="subtitle">Panel de configuración · <a href="/?key={key}" style="color:var(--accent)">Ver dashboard →</a></div>

{banner}

<form method="POST" action="/setup?key={key}">

<div class="card">
<div class="card-title">🖥 MetaTrader 5 — Credenciales de cuenta FTMO</div>
<div class="grid">
  <div class="field">
    <label>Login MT5</label>
    <input name="mt5_login" value="{_v('mt5_login')}" placeholder="531307202" required>
  </div>
  <div class="field">
    <label>Contraseña MT5</label>
    <input type="password" name="mt5_password" placeholder="•••• (dejar vacío = no cambiar)">
    <span class="hint">Solo rellena si quieres cambiarla</span>
  </div>
  <div class="field">
    <label>Servidor MT5</label>
    <input name="mt5_server" value="{_v('mt5_server')}" placeholder="FTMO-Server3" required>
  </div>
  <div class="field">
    <label>Ruta ejecutable MT5 (opcional)</label>
    <input name="mt5_path" value="{_v('mt5_path')}" placeholder="C:\\Program Files\\...\\terminal64.exe">
  </div>
</div>
</div>

<div class="card">
<div class="card-title">📱 Telegram — Notificaciones en tiempo real</div>
<div class="grid">
  <div class="field">
    <label>Bot Token</label>
    <input type="password" name="tg_token" placeholder="•••• (dejar vacío = no cambiar)">
    <span class="hint">Obtener en @BotFather → /newbot</span>
  </div>
  <div class="field">
    <label>Chat ID</label>
    <input name="tg_chat_id" value="{_v('tg_chat_id')}" placeholder="8259161831">
    <span class="hint">Obtener con @userinfobot</span>
  </div>
</div>
</div>

<div class="card">
<div class="card-title">📊 Configuración de trading</div>
<div class="grid">
  <div class="field">
    <label>Símbolo</label>
    <select name="symbol">{sym_opts}</select>
  </div>
  <div class="field">
    <label>Cadena de temporalidades (separado por comas)</label>
    <input name="tf_chain" value="{tf}" placeholder="D1,H1,M15,M5">
  </div>
  <div class="field">
    <label>Score mínimo SMC (1–7)</label>
    <input type="number" name="min_score" value="{_v('min_score','5')}" min="1" max="7">
  </div>
  <div class="field">
    <label>Stop Loss (pips)</label>
    <input type="number" name="sl_pips" value="{_v('sl_pips','20.0')}" step="0.5" min="5">
  </div>
  <div class="field">
    <label>Ratio RR (mínimo recomendado: 3.0)</label>
    <input type="number" name="rr" value="{_v('rr','3.0')}" step="0.5" min="1">
  </div>
  <div class="field">
    <label>Dirección</label>
    <div class="toggle-row"><input type="checkbox" name="only_short" {_checked('only_short')}><label>Solo SHORT</label></div>
    <div class="toggle-row"><input type="checkbox" name="only_long"  {_checked('only_long')} ><label>Solo LONG</label></div>
  </div>
</div>
</div>

<div class="card">
<div class="card-title">🛡 Gestión de riesgo FTMO</div>
<div class="grid">
  <div class="field">
    <label>Balance inicial FTMO (siempre 10 000)</label>
    <input type="number" name="balance" value="{_v('balance','10000')}" step="100">
    <span class="hint">Nunca cambiarlo — es la referencia para calcular el suelo 9 000 EUR</span>
  </div>
  <div class="field">
    <label>Riesgo por operación (%)</label>
    <input type="number" name="risk_pct" value="{_v('risk_pct','0.5')}" step="0.1" min="0.1" max="3">
  </div>
  <div class="field">
    <label>Stop diario propio (EUR)</label>
    <input type="number" name="daily_limit_eur" value="{_v('daily_limit_eur','100')}" step="10" min="10">
    <span class="hint">El bot se bloquea al alcanzar esta pérdida. Límite FTMO real: 300 EUR</span>
  </div>
  <div class="field">
    <label>Divisa de la cuenta</label>
    <input name="currency" value="{_v('currency','EUR')}" placeholder="EUR">
  </div>
</div>
</div>

<div class="card">
<div class="card-title">📰 Forex Factory — Filtro de noticias</div>
<div class="toggle-row" style="margin-bottom:.75rem">
  <input type="checkbox" name="use_ff" {_checked('use_ff')}>
  <label>Activar filtro de noticias de alto impacto</label>
</div>
<div class="field" style="max-width:280px">
  <label>Buffer antes/después de la noticia (minutos)</label>
  <input type="number" name="news_buffer_mins" value="{_v('news_buffer_mins','60')}" min="5" max="120">
</div>
</div>

<button type="submit" class="btn">💾 Guardar configuración</button>
<a href="/?key={key}"><button type="button" class="btn-dash">← Volver al dashboard</button></a>
</form>

</div></body></html>"""


# ── HTML embebido ──────────────────────────────────────────────────────────────

_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SMC·FTMO — Command Center</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#06090f;--s1:#0d1117;--s2:#161b22;--s3:#1c2128;
  --b1:#21262d;--b2:#30363d;
  --t1:#e6edf3;--t2:#8b949e;--t3:#484f58;
  --green:#3fb950;--gd:rgba(63,185,80,.14);
  --red:#f85149;--rd:rgba(248,81,73,.14);
  --amber:#d29922;--ad:rgba(210,153,34,.14);
  --blue:#58a6ff;--bd:rgba(88,166,255,.12);
  --r:8px;
  --font:'Inter',system-ui,-apple-system,sans-serif;
  --mono:'JetBrains Mono','Cascadia Code','Consolas',monospace;
}
html{font-size:14px;scroll-behavior:smooth}
body{background:var(--bg);color:var(--t1);font-family:var(--font);min-height:100vh;overflow-x:hidden}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:var(--s1)}
::-webkit-scrollbar-thumb{background:var(--b2);border-radius:3px}

/* ── Layout ── */
.app{max-width:1380px;margin:0 auto;padding:.875rem 1.25rem 3rem}

/* ── Header ── */
.hdr{
  display:flex;align-items:center;justify-content:space-between;
  padding:.75rem 0;margin-bottom:1.25rem;
  border-bottom:1px solid var(--b1);
  position:sticky;top:0;z-index:100;
  background:rgba(6,9,15,.92);backdrop-filter:blur(16px);
}
.hdr-l{display:flex;align-items:center;gap:.75rem}
.logo{font-size:.9rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--t1)}
.logo em{color:var(--green);font-style:normal}
.vd{width:1px;height:14px;background:var(--b2)}
.sym-badge{
  font-family:var(--mono);font-size:.72rem;font-weight:500;
  color:var(--blue);background:var(--bd);
  padding:.2rem .6rem;border-radius:4px;letter-spacing:.04em
}
.tf-tag{font-family:var(--mono);font-size:.68rem;color:var(--t3);letter-spacing:.02em}
.dry-badge{
  font-size:.6rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;
  color:var(--amber);background:var(--ad);
  padding:.15rem .5rem;border-radius:4px;display:none
}
.hdr-r{display:flex;align-items:center;gap:.875rem}
.setup-btn{
  font-size:.68rem;color:var(--t3);text-decoration:none;
  padding:.25rem .65rem;border:1px solid var(--b1);border-radius:5px;
  transition:all .2s
}
.setup-btn:hover{color:var(--t2);border-color:var(--b2);background:var(--s2)}
.pill{
  display:flex;align-items:center;gap:.35rem;
  font-size:.65rem;font-weight:600;letter-spacing:.09em;text-transform:uppercase;
  padding:.28rem .72rem;border-radius:9999px;border:1px solid currentColor;
  transition:all .3s
}
.dot{width:6px;height:6px;border-radius:50%;background:currentColor}
.p-live{color:var(--green)} .p-live .dot{animation:pg 2s infinite}
.p-block{color:var(--red)}  .p-block .dot{animation:pr 1s infinite}
.p-idle{color:var(--amber)}
.p-off{color:var(--t3)}
@keyframes pg{0%,100%{opacity:1;box-shadow:0 0 0 0 rgba(63,185,80,.4)}50%{opacity:.7;box-shadow:0 0 0 5px rgba(63,185,80,0)}}
@keyframes pr{0%,100%{opacity:1}50%{opacity:.3}}
.clk{font-family:var(--mono);font-size:.72rem;color:var(--t2);letter-spacing:.05em}

/* ── Offline banner ── */
.offline{
  display:none;background:var(--rd);border:1px solid rgba(248,81,73,.3);
  color:var(--red);padding:.55rem 1rem;border-radius:var(--r);
  font-size:.77rem;font-weight:500;margin-bottom:.875rem;text-align:center;
  animation:fi .3s ease
}

/* ── KPI grid ── */
.kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:.75rem;margin-bottom:.75rem}
@media(max-width:780px){.kpi-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:420px){.kpi-grid{grid-template-columns:1fr}}

.kpi{
  background:var(--s1);border:1px solid var(--b1);border-radius:var(--r);
  padding:.95rem 1.1rem;position:relative;overflow:hidden;
  transition:border-color .2s,transform .2s;cursor:default
}
.kpi::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--kl,transparent);transition:background .4s}
.kpi:hover{border-color:var(--b2);transform:translateY(-1px)}
.kpi.c-green{--kl:var(--green)} .kpi.c-red{--kl:var(--red)}
.kpi.c-blue{--kl:var(--blue)}   .kpi.c-amber{--kl:var(--amber)}
.kpi-lbl{font-size:.6rem;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--t2);margin-bottom:.45rem}
.kpi-val{font-family:var(--mono);font-size:1.5rem;font-weight:500;line-height:1;color:var(--t1);margin-bottom:.3rem;transition:color .3s}
.kpi-sub{font-size:.68rem;color:var(--t2);display:flex;align-items:center;gap:.35rem}
.badge{font-family:var(--mono);font-size:.67rem;font-weight:500;padding:.1rem .35rem;border-radius:3px}
.b-pos{color:var(--green);background:var(--gd)}
.b-neg{color:var(--red);background:var(--rd)}
.b-neu{color:var(--t2);background:var(--s2)}

/* ── Gauges ── */
.gauge-row{display:grid;grid-template-columns:1fr 1fr;gap:.75rem;margin-bottom:.75rem}
@media(max-width:600px){.gauge-row{grid-template-columns:1fr}}
.gauge{
  background:var(--s1);border:1px solid var(--b1);border-radius:var(--r);
  padding:.95rem 1.1rem;transition:border-color .2s
}
.gauge:hover{border-color:var(--b2)}
.gauge-hdr{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:.65rem}
.gauge-lbl{font-size:.6rem;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--t2)}
.gauge-val{font-family:var(--mono);font-size:.78rem;font-weight:500;color:var(--t1)}
.track{width:100%;height:5px;background:var(--s2);border-radius:9999px;overflow:hidden;margin-bottom:.5rem}
.fill{height:100%;border-radius:9999px;transition:width .9s cubic-bezier(.4,0,.2,1),background .5s}
.f-g{background:linear-gradient(90deg,rgba(63,185,80,.4),var(--green));box-shadow:0 0 10px rgba(63,185,80,.25)}
.f-a{background:linear-gradient(90deg,rgba(210,153,34,.4),var(--amber));box-shadow:0 0 10px rgba(210,153,34,.25)}
.f-r{background:linear-gradient(90deg,rgba(248,81,73,.4),var(--red));box-shadow:0 0 10px rgba(248,81,73,.25)}
.gauge-ftr{display:flex;justify-content:space-between;font-size:.68rem;color:var(--t2)}

/* ── Info row ── */
.info-row{display:grid;grid-template-columns:1fr 1fr;gap:.75rem;margin-bottom:.75rem}
@media(max-width:600px){.info-row{grid-template-columns:1fr}}
.icard{
  background:var(--s1);border:1px solid var(--b1);border-radius:var(--r);
  padding:.875rem 1.1rem;display:flex;align-items:center;gap:.875rem;
  transition:border-color .2s
}
.icard:hover{border-color:var(--b2)}
.indicator{
  width:38px;height:38px;border-radius:50%;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;font-size:1rem;
  border:1px solid transparent;transition:all .4s
}
.i-none{background:var(--s2);border-color:var(--b1)}
.i-ok{background:var(--gd);border-color:var(--green)}
.i-warn{background:var(--ad);border-color:var(--amber);animation:pam 2s infinite}
.i-block{background:var(--rd);border-color:var(--red);animation:par 1s infinite}
@keyframes pam{0%,100%{box-shadow:0 0 0 0 rgba(210,153,34,.3)}50%{box-shadow:0 0 0 6px rgba(210,153,34,0)}}
@keyframes par{0%,100%{box-shadow:0 0 0 0 rgba(248,81,73,.4)}50%{box-shadow:0 0 0 6px rgba(248,81,73,0)}}
.icontent{flex:1;min-width:0}
.itype{font-size:.58rem;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--t3);margin-bottom:.28rem}
.imain{font-size:.82rem;font-weight:600;color:var(--t1);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:color .3s}
.isub{font-size:.68rem;color:var(--t2);margin-top:.12rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* ── Signal panel ── */
.sig-card{
  background:var(--s1);border:1px solid var(--b1);border-radius:var(--r);
  padding:.95rem 1.2rem;margin-bottom:.75rem;transition:border-color .2s
}
.sig-card:hover{border-color:var(--b2)}
.sig-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:.85rem}
.sig-title{font-size:.6rem;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--t2)}
.sig-last{font-size:.68rem;font-weight:600;padding:.18rem .55rem;border-radius:4px;letter-spacing:.04em}
.sl-long{color:var(--green);background:var(--gd)}
.sl-short{color:var(--red);background:var(--rd)}
.sl-none{color:var(--t3);background:var(--s2)}
.sig-grid{display:grid;grid-template-columns:1fr 1px 1fr;gap:1.25rem;align-items:center}
.sig-divider{background:var(--b1);height:3rem;justify-self:center;width:1px}
.sig-side{display:flex;flex-direction:column;gap:.45rem}
.sig-dir{font-size:.62rem;font-weight:600;letter-spacing:.1em;text-transform:uppercase}
.sd-bull{color:var(--green)} .sd-bear{color:var(--red)}
.sig-row{display:flex;align-items:center;gap:.75rem;flex-wrap:wrap}
.sig-num{font-family:var(--mono);font-size:1.8rem;font-weight:500;line-height:1;min-width:2.2rem;transition:color .3s}
.sn-bull.on{color:var(--green)} .sn-bear.on{color:var(--red)} .sn-off{color:var(--t3)}
.dots{display:flex;gap:4px;align-items:center}
.d{width:8px;height:8px;border-radius:50%;background:var(--s2);border:1px solid var(--b2);transition:all .35s}
.d.on-bull{background:var(--green);border-color:var(--green);box-shadow:0 0 5px rgba(63,185,80,.6)}
.d.on-bear{background:var(--red);border-color:var(--red);box-shadow:0 0 5px rgba(248,81,73,.6)}
.sig-thr{font-size:.63rem;color:var(--t3)}

/* ── Tables ── */
.tbl-card{background:var(--s1);border:1px solid var(--b1);border-radius:var(--r);margin-bottom:.75rem;overflow:hidden}
.tbl-hdr{display:flex;justify-content:space-between;align-items:center;padding:.8rem 1.1rem .65rem;border-bottom:1px solid var(--b1)}
.tbl-title{font-size:.6rem;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--t2)}
.tbl-cnt{font-family:var(--mono);font-size:.63rem;color:var(--t3);background:var(--s2);padding:.12rem .45rem;border-radius:9999px}
table{width:100%;border-collapse:collapse}
thead th{
  padding:.5rem 1.1rem;text-align:left;
  font-size:.6rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;
  color:var(--t3);border-bottom:1px solid var(--b1);background:var(--s1);white-space:nowrap
}
tbody tr{transition:background .15s;border-bottom:1px solid rgba(33,38,45,.7)}
tbody tr:last-child{border-bottom:none}
tbody tr:hover{background:var(--s2)}
tbody td{padding:.6rem 1.1rem;font-size:.78rem;color:var(--t1);white-space:nowrap;font-variant-numeric:tabular-nums}
.empty td{text-align:center;color:var(--t3);padding:1.5rem;font-size:.78rem}
.mono{font-family:var(--mono);font-size:.72rem}
.dl{color:var(--green);font-weight:600} .ds{color:var(--red);font-weight:600}
.pp{font-family:var(--mono);font-size:.73rem;color:var(--green)}
.pn{font-family:var(--mono);font-size:.73rem;color:var(--red)}
.p0{font-family:var(--mono);font-size:.73rem;color:var(--t2)}
.tk{font-family:var(--mono);font-size:.68rem;color:var(--blue);background:var(--bd);padding:.08rem .35rem;border-radius:3px}

/* ── Log ── */
.log-card{background:#080b12;border:1px solid var(--b1);border-radius:var(--r);overflow:hidden}
.log-hdr{display:flex;justify-content:space-between;align-items:center;padding:.7rem 1.1rem;border-bottom:1px solid var(--b1);background:var(--s1)}
.log-title{font-size:.6rem;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--t2);display:flex;align-items:center;gap:.45rem}
.log-dot{width:6px;height:6px;border-radius:50%;background:var(--green);animation:bl 1.5s infinite}
@keyframes bl{0%,100%{opacity:1}50%{opacity:.15}}
.log-ts{font-family:var(--mono);font-size:.62rem;color:var(--t3)}
.log-body{padding:.65rem 1.1rem;display:flex;flex-direction:column;gap:.18rem;min-height:5.5rem}
.ll{
  font-family:var(--mono);font-size:.68rem;color:var(--t3);
  padding:.12rem 0;border-bottom:1px solid rgba(33,38,45,.4);
  display:flex;gap:.65rem;animation:fi .3s ease
}
.ll:last-child{color:var(--t2);border-bottom:none}
.ll:nth-last-child(2){color:#596270}
.lt{color:var(--t3);flex-shrink:0}
@keyframes fi{from{opacity:0;transform:translateY(3px)}to{opacity:1;transform:none}}

/* ── Footer ── */
.footer{
  margin-top:1.5rem;padding-top:.875rem;border-top:1px solid var(--b1);
  display:flex;justify-content:space-between;align-items:center;
  font-size:.62rem;color:var(--t3)
}

/* ── Access overlay ── */
#aov{
  position:fixed;inset:0;background:var(--bg);
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  z-index:9999;gap:.875rem
}
#aov h1{font-size:1rem;font-weight:600;color:var(--red)}
#aov p{font-size:.78rem;color:var(--t2);max-width:300px;text-align:center;line-height:1.5}
#aov input{
  background:var(--s1);border:1px solid var(--b2);color:var(--t1);
  padding:.6rem 1rem;border-radius:var(--r);font-size:.875rem;
  width:280px;outline:none;font-family:var(--mono);transition:border-color .2s
}
#aov input:focus{border-color:var(--green)}
#aov button{
  background:var(--green);color:#fff;border:none;border-radius:var(--r);
  padding:.6rem 1.5rem;cursor:pointer;font-size:.875rem;font-weight:600;font-family:var(--font);transition:opacity .2s
}
#aov button:hover{opacity:.85}

@media(max-width:600px){
  .sig-grid{grid-template-columns:1fr 1px 1fr;gap:.75rem}
  .sig-num{font-size:1.4rem}
  .kpi-val{font-size:1.25rem}
}
</style>
</head>
<body>
    --bg: #0a0e1a; --card: #111827; --border: #1f2937;
    --accent: #10b981; --red: #ef4444; --yellow: #f59e0b;
    --text: #f9fafb; --muted: #6b7280;
    --sm: 0.75rem; --base: 0.875rem; --lg: 1rem; --xl: 1.25rem; --2xl: 1.5rem;
  }
  body { background:var(--bg); color:var(--text);
    font-family:'Segoe UI',system-ui,sans-serif; font-size:var(--base);
    min-height:100vh; padding:1rem 1.25rem 2rem; }

  /* ── Access denied overlay ── */
  #access-overlay {
    position:fixed; inset:0; background:#0a0e1a;
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    z-index:9999; gap:1rem;
  }
  #access-overlay h1 { color:var(--red); font-size:var(--xl); }
  #access-overlay p  { color:var(--muted); font-size:var(--sm); text-align:center; max-width:360px; }
  #access-overlay input {
    background:var(--card); border:1px solid var(--border); color:var(--text);
    padding:.6rem 1rem; border-radius:8px; font-size:var(--base); width:280px;
    outline:none;
  }
  #access-overlay input:focus { border-color:var(--accent); }
  #access-overlay button {
    background:var(--accent); color:#fff; border:none; border-radius:8px;
    padding:.6rem 1.5rem; cursor:pointer; font-size:var(--base); font-weight:600;
  }

  /* ── Offline banner ── */
  #offline-banner {
    display:none; background:#7f1d1d; color:#fca5a5;
    padding:.5rem 1rem; border-radius:8px; font-size:var(--sm);
    margin-bottom:.75rem; text-align:center;
  }

  /* ── Header ── */
  .header { display:flex; align-items:center; justify-content:space-between;
    margin-bottom:1.25rem; padding-bottom:.75rem; border-bottom:1px solid var(--border); }
  .header-left { display:flex; align-items:center; gap:.75rem; }
  .logo { font-size:var(--xl); font-weight:700; letter-spacing:.05em; color:var(--accent); }
  .symbol-tag { background:var(--border); font-size:var(--sm); font-weight:600;
    padding:.25rem .6rem; border-radius:6px; letter-spacing:.04em; }
  .dry-badge { background:#92400e; color:#fcd34d; font-size:.65rem; font-weight:700;
    padding:.2rem .5rem; border-radius:4px; display:none; }
  .header-right { display:flex; align-items:center; gap:1rem; }
  .status-pill { display:flex; align-items:center; gap:.35rem; font-size:var(--sm);
    font-weight:600; padding:.3rem .8rem; border-radius:9999px; border:1px solid currentColor; }
  .dot { width:7px; height:7px; border-radius:50%; background:currentColor; }
  .status-pill.operativo { color:var(--accent); }
  .status-pill.bloqueado { color:var(--red); }
  .status-pill.fuera     { color:var(--yellow); }
  .status-pill.espera    { color:var(--muted); }
  #clock { font-size:var(--sm); color:var(--muted); font-variant-numeric:tabular-nums; }

  /* ── Cards ── */
  .cards { display:grid; grid-template-columns:repeat(4,1fr); gap:.75rem; margin-bottom:.75rem; }
  @media(max-width:700px){ .cards { grid-template-columns:repeat(2,1fr); } }
  .card { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:1rem 1.1rem; }
  .card-label { font-size:var(--sm); color:var(--muted); text-transform:uppercase;
    letter-spacing:.07em; margin-bottom:.35rem; }
  .card-value { font-size:var(--2xl); font-weight:700; font-variant-numeric:tabular-nums; }
  .card-sub   { font-size:var(--sm); color:var(--muted); margin-top:.2rem; }
  .pos-green { color:var(--accent); } .pos-red { color:var(--red); } .pos-muted { color:var(--muted); }

  /* ── Gauges ── */
  .gauges { display:grid; grid-template-columns:1fr 1fr; gap:.75rem; margin-bottom:.75rem; }
  @media(max-width:700px){ .gauges { grid-template-columns:1fr; } }
  .gauge-card { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:.9rem 1.1rem; }
  .gauge-header { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:.6rem; }
  .gauge-title { font-size:var(--sm); color:var(--muted); text-transform:uppercase; letter-spacing:.07em; }
  .gauge-nums  { font-size:var(--sm); font-variant-numeric:tabular-nums; }
  .bar-track   { width:100%; height:10px; background:var(--border); border-radius:9999px; overflow:hidden; }
  .bar-fill    { height:100%; border-radius:9999px; transition:width .5s ease, background .5s ease; }
  .bar-green   { background:linear-gradient(90deg,#064e3b,var(--accent)); }
  .bar-yellow  { background:linear-gradient(90deg,#78350f,var(--yellow)); }
  .bar-red     { background:linear-gradient(90deg,#7f1d1d,var(--red)); }
  .gauge-sub   { margin-top:.45rem; font-size:var(--sm); color:var(--muted); }

  /* ── Info row ── */
  .info-row { display:grid; grid-template-columns:1fr 1fr; gap:.75rem; margin-bottom:.75rem; }
  @media(max-width:700px){ .info-row { grid-template-columns:1fr; } }
  .info-card { background:var(--card); border:1px solid var(--border); border-radius:10px;
    padding:.9rem 1.1rem; display:flex; gap:1rem; align-items:center; }
  .traffic-light { width:42px; height:42px; border-radius:50%; border:2px solid var(--border);
    display:flex; align-items:center; justify-content:center; font-size:1.2rem; flex-shrink:0;
    transition:background .4s; }
  .light-none    { background:#1f2937; }
  .light-ok      { background:#064e3b; border-color:var(--accent); }
  .light-warning { background:#78350f; border-color:var(--yellow); }
  .light-blocked { background:#7f1d1d; border-color:var(--red); animation:pulse 1s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.6} }
  .info-text-block { flex:1; }
  .info-title { font-size:var(--sm); color:var(--muted); text-transform:uppercase; letter-spacing:.07em; margin-bottom:.3rem; }
  .info-main  { font-size:var(--base); font-weight:600; }
  .info-sub   { font-size:var(--sm); color:var(--muted); margin-top:.1rem; }

  /* ── Signals ── */
  .signals-card { background:var(--card); border:1px solid var(--border); border-radius:10px;
    padding:.85rem 1.1rem; display:flex; align-items:center; gap:1.5rem; margin-bottom:.75rem; }
  .sig-label  { font-size:var(--sm); color:var(--muted); text-transform:uppercase; letter-spacing:.06em; }
  .sig-pair   { display:flex; align-items:center; gap:.5rem; }
  .sig-score  { font-size:var(--xl); font-weight:700; font-variant-numeric:tabular-nums; }
  .sig-score.bull { color:var(--accent); } .sig-score.bear { color:var(--red); }
  .sig-divider{ width:1px; height:2rem; background:var(--border); }

  /* ── Tables ── */
  .table-card { background:var(--card); border:1px solid var(--border); border-radius:10px;
    padding:.9rem 1.1rem; margin-bottom:.75rem; overflow-x:auto; }
  .table-title { font-size:var(--sm); color:var(--muted); text-transform:uppercase;
    letter-spacing:.07em; margin-bottom:.75rem; }
  table { width:100%; border-collapse:collapse; min-width:400px; }
  th { font-size:.7rem; color:var(--muted); text-transform:uppercase; letter-spacing:.07em;
    text-align:left; padding:0 .5rem .5rem; border-bottom:1px solid var(--border); }
  td { font-size:var(--sm); padding:.45rem .5rem; border-bottom:1px solid #1a2235;
    font-variant-numeric:tabular-nums; }
  tr:last-child td { border-bottom:none; }
  .empty-row td { color:var(--muted); text-align:center; padding:1rem; }
  .dir-long  { color:var(--accent); font-weight:600; }
  .dir-short { color:var(--red);    font-weight:600; }
  .pnl-pos   { color:var(--accent); } .pnl-neg { color:var(--red); }

  /* ── Log ── */
  .log-card { background:#080c18; border:1px solid var(--border); border-radius:10px;
    padding:.85rem 1.1rem; }
  .log-title { font-size:var(--sm); color:var(--muted); text-transform:uppercase;
    letter-spacing:.07em; margin-bottom:.6rem; }
  .log-lines { list-style:none; }
  .log-lines li { font-size:.72rem; font-family:'Cascadia Code','Consolas',monospace;
    color:#64748b; padding:.12rem 0; border-bottom:1px solid #0f1623; }
  .log-lines li:last-child  { border-bottom:none; color:#94a3b8; }
  .log-lines li:nth-last-child(2) { color:#6b7280; }

  .footer { margin-top:1.5rem; text-align:center; font-size:.7rem; color:#374151; }
</style>
</head>
<body>

<!-- Access overlay -->
<div id="aov" style="display:none">
  <h1>🔒 Acceso restringido</h1>
  <p>Introduce tu clave de acceso para continuar.</p>
  <input type="password" id="aov-key" placeholder="ACCESS_TOKEN…" autocomplete="off">
  <button onclick="tryKey()">Acceder</button>
  <p id="aov-err" style="color:var(--red);font-size:.7rem;display:none">Clave incorrecta</p>
</div>

<div class="app">
  <!-- Offline banner -->
  <div class="offline" id="banner">⚠ Bot desconectado — sin datos en los últimos 2 minutos</div>

  <!-- Header -->
  <header class="hdr">
    <div class="hdr-l">
      <span class="logo">SMC·<em>FTMO</em></span>
      <span class="vd"></span>
      <span class="sym-badge" id="sym">—</span>
      <span class="tf-tag" id="tf-tag"></span>
      <span class="dry-badge" id="dry">DRY RUN</span>
    </div>
    <div class="hdr-r">
      <a class="setup-btn" id="setup-lnk" href="/setup">⚙ Config</a>
      <div class="pill p-off" id="pill"><span class="dot"></span><span id="pill-txt">Conectando</span></div>
      <span class="clk" id="clk">—</span>
    </div>
  </header>

  <!-- KPI cards -->
  <div class="kpi-grid">
    <div class="kpi c-blue">
      <div class="kpi-lbl">Balance MT5</div>
      <div class="kpi-val" id="bal">—</div>
      <div class="kpi-sub">Referencia FTMO</div>
    </div>
    <div class="kpi" id="eq-card">
      <div class="kpi-lbl">Equity actual</div>
      <div class="kpi-val" id="eq">—</div>
      <div class="kpi-sub"><span id="eq-delta" class="badge b-neu">—</span><span id="eq-sub"></span></div>
    </div>
    <div class="kpi" id="pnl-card">
      <div class="kpi-lbl">P&amp;L hoy</div>
      <div class="kpi-val" id="pnl">—</div>
      <div class="kpi-sub">Límite: <span id="pnl-lim">—</span></div>
    </div>
    <div class="kpi" id="pos-card">
      <div class="kpi-lbl">Posiciones abiertas</div>
      <div class="kpi-val" id="pos-n">0 / 1</div>
      <div class="kpi-sub">Ciclo <span class="badge b-neu" id="cyc">#0</span></div>
    </div>
  </div>

  <!-- Gauges -->
  <div class="gauge-row">
    <div class="gauge">
      <div class="gauge-hdr">
        <span class="gauge-lbl">Suelo FTMO — Drawdown máx. 10%</span>
        <span class="gauge-val" id="ftmo-val">—</span>
      </div>
      <div class="track"><div class="fill f-g" id="ftmo-bar" style="width:100%"></div></div>
      <div class="gauge-ftr"><span id="ftmo-l">—</span><span id="ftmo-r">—</span></div>
    </div>
    <div class="gauge">
      <div class="gauge-hdr">
        <span class="gauge-lbl">Stop diario — Límite conservador</span>
        <span class="gauge-val" id="day-val">—</span>
      </div>
      <div class="track"><div class="fill f-g" id="day-bar" style="width:0%"></div></div>
      <div class="gauge-ftr"><span id="day-l">—</span><span id="day-r">—</span></div>
    </div>
  </div>

  <!-- News + Session -->
  <div class="info-row">
    <div class="icard">
      <div class="indicator i-none" id="news-ind">📰</div>
      <div class="icontent">
        <div class="itype">Forex Factory</div>
        <div class="imain" id="news-main">—</div>
        <div class="isub"  id="news-sub">—</div>
      </div>
    </div>
    <div class="icard">
      <div class="indicator i-none" id="sess-ind">🕐</div>
      <div class="icontent">
        <div class="itype">Sesión de mercado</div>
        <div class="imain" id="sess-main">—</div>
        <div class="isub">Londres 10:00–18:00 · NY 15:30–00:00 CEST</div>
      </div>
    </div>
  </div>

  <!-- Signal panel -->
  <div class="sig-card">
    <div class="sig-hdr">
      <span class="sig-title">Análisis SMC — Confluencia de señales</span>
      <span class="sig-last sl-none" id="sig-last">Sin señal</span>
    </div>
    <div class="sig-grid">
      <div class="sig-side">
        <span class="sig-dir sd-bull">▲ LONG</span>
        <div class="sig-row">
          <span class="sig-num sn-bull sn-off" id="sc-bull">0</span>
          <div class="dots" id="dots-bull">
            <span class="d"></span><span class="d"></span><span class="d"></span><span class="d"></span>
            <span class="d"></span><span class="d"></span><span class="d"></span>
          </div>
        </div>
        <span class="sig-thr" id="thr-bull">0 / 7 condiciones</span>
      </div>
      <div class="sig-divider"></div>
      <div class="sig-side">
        <span class="sig-dir sd-bear">▼ SHORT</span>
        <div class="sig-row">
          <span class="sig-num sn-bear sn-off" id="sc-bear">0</span>
          <div class="dots" id="dots-bear">
            <span class="d"></span><span class="d"></span><span class="d"></span><span class="d"></span>
            <span class="d"></span><span class="d"></span><span class="d"></span>
          </div>
        </div>
        <span class="sig-thr" id="thr-bear">0 / 7 condiciones</span>
      </div>
    </div>
  </div>

  <!-- Positions table -->
  <div class="tbl-card">
    <div class="tbl-hdr">
      <span class="tbl-title">Posiciones abiertas</span>
      <span class="tbl-cnt" id="pos-cnt">0</span>
    </div>
    <table>
      <thead><tr><th>Ticket</th><th>Par</th><th>Dir</th><th>Lote</th><th>Entrada</th><th>SL</th><th>TP</th><th>P&amp;L</th></tr></thead>
      <tbody id="pos-tbody"><tr class="empty"><td colspan="8">Sin posiciones abiertas</td></tr></tbody>
    </table>
  </div>

  <!-- Trades table -->
  <div class="tbl-card">
    <div class="tbl-hdr">
      <span class="tbl-title">Historial de operaciones</span>
      <span class="tbl-cnt" id="trade-cnt">0</span>
    </div>
    <table>
      <thead><tr><th>Hora</th><th>Par</th><th>Dir</th><th>P&amp;L</th><th>Resultado</th></tr></thead>
      <tbody id="trade-tbody"><tr class="empty"><td colspan="5">Sin operaciones registradas</td></tr></tbody>
    </table>
  </div>

  <!-- Log -->
  <div class="log-card">
    <div class="log-hdr">
      <span class="log-title"><span class="log-dot"></span>Log en tiempo real</span>
      <span class="log-ts" id="log-ts">—</span>
    </div>
    <div class="log-body" id="log-body">
      <div class="ll"><span class="lt">—</span><span>Esperando datos del bot…</span></div>
    </div>
  </div>

  <!-- Footer -->
  <div class="footer">
    <span>SMC·FTMO Command Center · Actualiza cada 5s</span>
    <span id="ft-upd">—</span>
  </div>
</div>

<script>
"use strict";
const _key = new URLSearchParams(location.search).get('key') || '';

// Setup link with key
const sl = document.getElementById('setup-lnk');
if (sl) sl.href = '/setup?key=' + encodeURIComponent(_key);

// Access overlay
function tryKey() {
  const v = document.getElementById('aov-key').value.trim();
  if (!v) return;
  const u = new URL(location.href);
  u.searchParams.set('key', v);
  location.href = u.toString();
}
const ki = document.getElementById('aov-key');
if (ki) ki.addEventListener('keydown', e => { if (e.key === 'Enter') tryKey(); });

// Helpers
const $ = id => document.getElementById(id);
const fmt = (n, d=2) => n==null||isNaN(n) ? '—'
  : Number(n).toLocaleString('es-ES', {minimumFractionDigits:d, maximumFractionDigits:d});
const fmtE = (n, sign=false) => {
  if (n==null||isNaN(n)) return '—';
  const pre = n<0 ? '-' : (sign&&n>0 ? '+' : '');
  return pre + Math.abs(n).toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2}) + ' €';
};
const clamp = (v,lo,hi) => Math.min(hi, Math.max(lo, v));

// Clock
const clkEl = $('clk');
const tick = () => {
  const n=new Date(), p=x=>String(x).padStart(2,'0');
  clkEl.textContent = p(n.getUTCHours())+':'+p(n.getUTCMinutes())+':'+p(n.getUTCSeconds())+' UTC';
};
setInterval(tick, 1000); tick();

// Pill helper
function setPill(type, txt) {
  const el = $('pill');
  el.className = 'pill ' + type;
  $('pill-txt').textContent = txt;
}

// Dots helper
function setDots(id, score, type) {
  const dots = document.querySelectorAll('#'+id+' .d');
  dots.forEach((d, i) => {
    d.className = 'd' + (i < score ? ' on-'+type : '');
  });
}

let _first = true;

async function refresh() {
  let s;
  try {
    const r = await fetch('/api/state?key=' + encodeURIComponent(_key));
    if (r.status === 401) {
      $('aov').style.display = 'flex';
      if (!_first) { const e=$('aov-err'); if(e) e.style.display='block'; }
      return;
    }
    s = await r.json();
    _first = false;
    $('aov').style.display = 'none';
  } catch(e) {
    setPill('p-off', 'Sin conexión');
    return;
  }

  // Offline banner
  const banner = $('banner');
  if (s.last_push) {
    const parts = s.last_push.replace(' UTC','').split(':');
    const ps = parseInt(parts[0])*3600+parseInt(parts[1])*60+parseInt(parts[2]);
    const n  = new Date();
    const ns = n.getUTCHours()*3600+n.getUTCMinutes()*60+n.getUTCSeconds();
    banner.style.display = ((ns-ps+86400)%86400) > 120 ? 'block' : 'none';
  } else {
    banner.style.display = s.status==='bot_offline' ? 'block' : 'none';
  }

  // Header
  $('sym').textContent   = s.symbol || '—';
  $('tf-tag').textContent = s.tf_chain ? '· ' + s.tf_chain : '';
  $('dry').style.display  = s.dry_run ? 'inline' : 'none';

  // Status pill
  const PM = {
    operativo:    ['p-live',  'OPERATIVO'],
    bloqueado:    ['p-block', 'BLOQUEADO'],
    fuera_sesion: ['p-idle',  'FUERA SESIÓN'],
    sin_señal:    ['p-idle',  'EN ESPERA'],
    iniciando:    ['p-idle',  'INICIANDO'],
    bot_offline:  ['p-off',   'OFFLINE'],
  };
  const [pc, pt] = PM[s.status] || ['p-off', (s.status||'?').toUpperCase()];
  setPill(pc, pt);

  // KPI — Balance
  $('bal').textContent = fmt(s.balance) + ' €';

  // KPI — Equity
  const diff = (s.equity||0) - (s.initial_balance||10000);
  $('eq').textContent = fmt(s.equity) + ' €';
  $('eq').style.color = diff >= 0 ? 'var(--green)' : 'var(--red)';
  const ed = $('eq-delta');
  ed.textContent = (diff>=0?'+':'')+fmt(diff)+' €';
  ed.className   = 'badge ' + (diff>=0?'b-pos':'b-neg');
  $('eq-card').className = 'kpi ' + (diff>=0?'c-green':'c-red');

  // KPI — P&L
  const pnl = s.daily_pnl || 0;
  $('pnl').textContent = fmtE(pnl, true);
  $('pnl').style.color = pnl >= 0 ? 'var(--green)' : 'var(--red)';
  $('pnl-lim').textContent = '-' + fmt(s.daily_limit_eur||100) + ' €';
  $('pnl-card').className = 'kpi ' + (pnl < -(s.daily_limit_eur||100)*0.7 ? 'c-red' : pnl < 0 ? 'c-amber' : 'c-green');

  // KPI — Positions
  const np = (s.open_positions||[]).length;
  $('pos-n').textContent = np + ' / 1';
  $('pos-n').style.color = np > 0 ? 'var(--green)' : 'var(--t1)';
  $('cyc').textContent   = '#' + (s.cycle||0);
  $('pos-cnt').textContent = np;
  $('pos-card').className = 'kpi ' + (np > 0 ? 'c-green' : 'c-blue');

  // FTMO Gauge
  const floor=s.ftmo_floor||9000, init=s.initial_balance||10000, eq=s.equity||0;
  const fp = clamp((1 - Math.max(0,init-eq)/(init-floor))*100, 0, 100);
  const fb = $('ftmo-bar');
  fb.style.width = fp + '%';
  fb.className   = 'fill ' + (fp>60?'f-g':fp>30?'f-a':'f-r');
  $('ftmo-val').textContent = fmt(eq) + ' / ' + fmt(init) + ' €';
  $('ftmo-l').textContent   = 'Margen: ' + fmt(eq-floor) + ' €';
  $('ftmo-r').textContent   = 'Suelo: ' + fmt(floor) + ' €';

  // Daily Gauge
  const loss = Math.max(0, -pnl), lim = s.daily_limit_eur||100;
  const dp = clamp((loss/lim)*100, 0, 100);
  const db = $('day-bar');
  db.style.width = dp + '%';
  db.className   = 'fill ' + (dp<50?'f-g':dp<80?'f-a':'f-r');
  $('day-val').textContent = fmt(loss) + ' / ' + fmt(lim) + ' €';
  $('day-l').textContent   = dp < 100 ? 'Pérdida: ' + fmtE(-loss) : '⛔ Límite alcanzado — reanuda mañana';
  $('day-r').textContent   = dp < 100 ? 'Restante: ' + fmtE(lim-loss) : '';

  // News
  const ni=$('news-ind'), nm=$('news-main'), ns=$('news-sub');
  const NS = {
    none:    ['i-none','📰','Sin filtro activo','--use-forex-factory desactivado'],
    ok:      ['i-ok',  '🟢','Libre para operar', s.next_news_title ? 'Próx: '+s.next_news_title+' ('+s.next_news_mins+'min)' : 'Sin noticias próximas'],
    warning: ['i-warn','🟡','Precaución — '+(s.next_news_title||''), 'En '+(s.next_news_mins||'?')+' min'],
    blocked: ['i-block','🔴','⛔ BLACKOUT — '+(s.next_news_title||'Noticia roja'), s.next_news_mins!=null?'Faltan '+s.next_news_mins+' min':'Ejecución bloqueada'],
  };
  const [nc,ne,nt,nst] = NS[s.news_status] || NS.none;
  ni.className='indicator '+nc; ni.textContent=ne;
  nm.textContent=nt; ns.textContent=nst;

  // Session
  const si=$('sess-ind'), sm=$('sess-main');
  if (s.in_session) {
    si.className='indicator i-ok'; si.textContent='🟢';
    sm.textContent=s.session||'Sesión activa'; sm.style.color='var(--green)';
  } else {
    si.className='indicator i-none'; si.textContent='🌙';
    sm.textContent=s.session||'Fuera de sesión'; sm.style.color='var(--t2)';
  }

  // Signals
  const bull=s.score_bull||0, bear=s.score_bear||0, minSc=s.min_score||5;
  $('sc-bull').textContent = bull;
  $('sc-bear').textContent = bear;
  $('sc-bull').className = 'sig-num sn-bull ' + (bull>=minSc?'on':'sn-off');
  $('sc-bear').className = 'sig-num sn-bear ' + (bear>=minSc?'on':'sn-off');
  $('thr-bull').textContent = bull + ' / 7 condiciones';
  $('thr-bear').textContent = bear + ' / 7 condiciones';
  setDots('dots-bull', bull, 'bull');
  setDots('dots-bear', bear, 'bear');
  const sl2=$('sig-last');
  if (s.last_signal_dir==='LONG')       { sl2.textContent='▲ Señal LONG';  sl2.className='sig-last sl-long'; }
  else if (s.last_signal_dir==='SHORT') { sl2.textContent='▼ Señal SHORT'; sl2.className='sig-last sl-short'; }
  else                                  { sl2.textContent='Sin señal';      sl2.className='sig-last sl-none'; }

  // Positions table
  const pos = s.open_positions || [];
  $('pos-tbody').innerHTML = pos.length === 0
    ? '<tr class="empty"><td colspan="8">Sin posiciones abiertas</td></tr>'
    : pos.map(p => `<tr>
        <td><span class="tk">#${p.ticket}</span></td>
        <td class="mono">${p.symbol}</td>
        <td class="${p.dir==='LONG'?'dl':'ds'}">${p.dir==='LONG'?'▲ LONG':'▼ SHORT'}</td>
        <td class="mono">${fmt(p.lot,2)}</td>
        <td class="mono">${fmt(p.entry,5)}</td>
        <td class="mono" style="color:var(--red)">${fmt(p.sl,5)}</td>
        <td class="mono" style="color:var(--green)">${fmt(p.tp,5)}</td>
        <td class="${(p.pnl||0)>=0?'pp':'pn'}">${fmtE(p.pnl,true)}</td>
      </tr>`).join('');

  // Trades table
  const trades = [...(s.recent_trades||[])].reverse();
  $('trade-cnt').textContent = trades.length;
  $('trade-tbody').innerHTML = trades.length === 0
    ? '<tr class="empty"><td colspan="5">Sin operaciones registradas</td></tr>'
    : trades.map(t => `<tr>
        <td class="mono" style="color:var(--t2)">${t.time||'—'}</td>
        <td class="mono">${t.symbol||'—'}</td>
        <td class="${t.dir==='LONG'?'dl':'ds'}">${t.dir==='LONG'?'▲ LONG':'▼ SHORT'}</td>
        <td class="${(t.pnl||0)>=0?'pp':'pn'}">${fmtE(t.pnl,true)}</td>
        <td style="color:var(--t2);font-size:.73rem">${t.motivo||'—'}</td>
      </tr>`).join('');

  // Log
  const lines = s.log_lines || [];
  $('log-body').innerHTML = lines.length === 0
    ? '<div class="ll"><span class="lt">—</span><span>Esperando datos…</span></div>'
    : lines.map(l => {
        const ts = l.match(/^\d{2}:\d{2}/)?.[0] || '';
        const msg = ts ? l.slice(ts.length).trim() : l;
        return `<div class="ll"><span class="lt">${ts}</span><span>${msg}</span></div>`;
      }).join('');
  $('log-ts').textContent = s.last_push || '—';

  // Footer
  $('ft-upd').textContent = 'Push: ' + (s.last_push||'—') + '  ·  Ciclo #' + (s.cycle||0);
}

setInterval(refresh, 5000);
refresh();
</script>
</body>
</html>"""
