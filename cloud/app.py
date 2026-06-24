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
from fastapi.responses import HTMLResponse, JSONResponse

# ── Configuración ──────────────────────────────────────────────────────────────

PUSH_TOKEN   = os.environ.get("PUSH_TOKEN",   "change-me-push-token")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN", "")   # vacío = sin auth en dashboard

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


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    """Sirve el panel. La auth se realiza en el cliente vía ?key=..."""
    return HTMLResponse(_HTML)


# ── HTML embebido ──────────────────────────────────────────────────────────────

_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SMC-FTMO</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
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

<!-- Access denied overlay (shown if key is wrong) -->
<div id="access-overlay" style="display:none">
  <h1>🔒 Acceso restringido</h1>
  <p>Introduce la clave de acceso o usa el enlace completo que te compartieron.</p>
  <input type="password" id="key-input" placeholder="Clave de acceso..." autocomplete="off">
  <button onclick="tryKey()">Acceder</button>
  <p id="key-error" style="color:var(--red);display:none">Clave incorrecta</p>
</div>

<!-- Bot offline banner -->
<div id="offline-banner">⚠ Bot desconectado o sin datos recientes — última actualización hace más de 2 minutos</div>

<!-- Header -->
<div class="header">
  <div class="header-left">
    <span class="logo">SMC-FTMO</span>
    <span class="symbol-tag" id="symbol-tag">—</span>
    <span class="dry-badge" id="dry-badge">DRY RUN</span>
  </div>
  <div class="header-right">
    <span class="status-pill espera" id="status-pill">
      <span class="dot"></span><span id="status-text">Conectando…</span>
    </span>
    <span id="clock">—</span>
  </div>
</div>

<!-- Metric cards -->
<div class="cards">
  <div class="card">
    <div class="card-label">Balance MT5</div>
    <div class="card-value pos-muted" id="balance">—</div>
    <div class="card-sub">Referencia FTMO</div>
  </div>
  <div class="card">
    <div class="card-label">Equity actual</div>
    <div class="card-value" id="equity">—</div>
    <div class="card-sub" id="equity-sub">—</div>
  </div>
  <div class="card">
    <div class="card-label">P&amp;L hoy</div>
    <div class="card-value" id="daily-pnl">—</div>
    <div class="card-sub" id="daily-pnl-sub">Límite: —</div>
  </div>
  <div class="card">
    <div class="card-label">Posiciones</div>
    <div class="card-value" id="pos-count">0/1</div>
    <div class="card-sub" id="cycle-sub">Ciclo #0</div>
  </div>
</div>

<!-- Gauges -->
<div class="gauges">
  <div class="gauge-card">
    <div class="gauge-header">
      <span class="gauge-title">Suelo FTMO (10% DD)</span>
      <span class="gauge-nums" id="ftmo-nums">—</span>
    </div>
    <div class="bar-track"><div class="bar-fill bar-green" id="ftmo-bar" style="width:100%"></div></div>
    <div class="gauge-sub" id="ftmo-sub">—</div>
  </div>
  <div class="gauge-card">
    <div class="gauge-header">
      <span class="gauge-title">Límite diario — 100 EUR</span>
      <span class="gauge-nums" id="daily-nums">—</span>
    </div>
    <div class="bar-track"><div class="bar-fill bar-green" id="daily-bar" style="width:0%"></div></div>
    <div class="gauge-sub" id="daily-sub">—</div>
  </div>
</div>

<!-- News + Session -->
<div class="info-row">
  <div class="info-card">
    <div class="traffic-light light-none" id="news-light">📰</div>
    <div class="info-text-block">
      <div class="info-title">Noticias Forex Factory</div>
      <div class="info-main" id="news-main">—</div>
      <div class="info-sub"  id="news-sub">—</div>
    </div>
  </div>
  <div class="info-card">
    <div class="traffic-light light-none" id="session-light">🕐</div>
    <div class="info-text-block">
      <div class="info-title">Sesión de mercado</div>
      <div class="info-main" id="session-main">—</div>
      <div class="info-sub">Londres 10:00–18:00 | NY 15:30–00:00 CEST</div>
    </div>
  </div>
</div>

<!-- Signals -->
<div class="signals-card">
  <span class="sig-label">Señales SMC</span>
  <div class="sig-pair">
    <span style="font-size:var(--sm);color:var(--muted)">LONG</span>
    <span class="sig-score bull" id="score-bull">0</span>
  </div>
  <div class="sig-divider"></div>
  <div class="sig-pair">
    <span style="font-size:var(--sm);color:var(--muted)">SHORT</span>
    <span class="sig-score bear" id="score-bear">0</span>
  </div>
  <div class="sig-divider"></div>
  <span style="font-size:var(--sm);color:var(--muted)" id="sig-threshold">umbral: 5/7</span>
  <div style="flex:1"></div>
  <span style="font-size:.8rem;color:var(--muted)" id="last-signal-dir">—</span>
</div>

<!-- Open positions -->
<div class="table-card">
  <div class="table-title">Posiciones abiertas</div>
  <table>
    <thead><tr><th>Ticket</th><th>Símbolo</th><th>Dir</th><th>Lote</th><th>Entrada</th><th>SL</th><th>TP</th><th>P&amp;L</th></tr></thead>
    <tbody id="pos-tbody"><tr class="empty-row"><td colspan="8">Sin posiciones abiertas</td></tr></tbody>
  </table>
</div>

<!-- Recent trades -->
<div class="table-card">
  <div class="table-title">Últimas operaciones</div>
  <table>
    <thead><tr><th>Hora</th><th>Símbolo</th><th>Dir</th><th>P&amp;L</th><th>Motivo</th></tr></thead>
    <tbody id="trades-tbody"><tr class="empty-row"><td colspan="5">Sin operaciones registradas</td></tr></tbody>
  </table>
</div>

<!-- Log -->
<div class="log-card">
  <div class="log-title">Log en tiempo real</div>
  <ul class="log-lines" id="log-lines"><li>Esperando datos del bot…</li></ul>
</div>

<div class="footer">SMC-FTMO · Actualiza cada 5s · <span id="last-update">—</span></div>

<script>
"use strict";

// ── Auth: leer key desde URL (?key=...) ───────────────────────────────────────
let _key = new URLSearchParams(window.location.search).get('key') || '';

function tryKey() {
  const input = document.getElementById('key-input').value.trim();
  if (input) {
    const url = new URL(window.location.href);
    url.searchParams.set('key', input);
    window.location.href = url.toString();
  }
}
document.getElementById('key-input')
  .addEventListener('keydown', e => { if (e.key === 'Enter') tryKey(); });

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmt(n, d=2) {
  if (n===null||n===undefined||isNaN(n)) return '—';
  return Number(n).toLocaleString('es-ES',{minimumFractionDigits:d,maximumFractionDigits:d});
}
function fmtEur(n, sign=false) {
  if (n===null||n===undefined||isNaN(n)) return '—';
  const abs=Math.abs(n);
  const pre=n<0?'-':(sign&&n>0?'+':'');
  return pre+abs.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+' EUR';
}
function clamp(v,lo,hi){return Math.min(hi,Math.max(lo,v));}

// ── Live clock ────────────────────────────────────────────────────────────────
function updateClock(){
  const n=new Date(),p=x=>String(x).padStart(2,'0');
  document.getElementById('clock').textContent=p(n.getUTCHours())+':'+p(n.getUTCMinutes())+':'+p(n.getUTCSeconds())+' UTC';
}
setInterval(updateClock,1000); updateClock();

// ── Main refresh ──────────────────────────────────────────────────────────────
let _firstFetch = true;

async function refresh() {
  let s, resp;
  try {
    resp = await fetch('/api/state?key='+encodeURIComponent(_key));
    if (resp.status === 401) {
      document.getElementById('access-overlay').style.display='flex';
      if (!_firstFetch) document.getElementById('key-error').style.display='block';
      return;
    }
    s = await resp.json();
    _firstFetch = false;
    document.getElementById('access-overlay').style.display='none';
  } catch(e) {
    setPill('espera','SIN CONEXIÓN');
    return;
  }

  // Stale data warning (last_push > 2 min)
  const banner = document.getElementById('offline-banner');
  if (s.last_push) {
    const lastPushStr = s.last_push; // "HH:MM:SS UTC"
    const now = new Date();
    // parse HH:MM:SS UTC
    const parts = lastPushStr.replace(' UTC','').split(':');
    const pushSecs = parseInt(parts[0])*3600+parseInt(parts[1])*60+parseInt(parts[2]);
    const nowSecs  = now.getUTCHours()*3600+now.getUTCMinutes()*60+now.getUTCSeconds();
    const diffSecs = (nowSecs - pushSecs + 86400) % 86400;
    banner.style.display = diffSecs > 120 ? 'block' : 'none';
  } else {
    banner.style.display = s.status==='bot_offline' ? 'block' : 'none';
  }

  // ── Symbol + dry run
  document.getElementById('symbol-tag').textContent = (s.symbol||'—')+' '+( s.tf_chain||'');
  document.getElementById('dry-badge').style.display = s.dry_run ? 'inline' : 'none';

  // ── Status pill
  const smap = {
    operativo:   ['operativo','OPERATIVO'],
    bloqueado:   ['bloqueado','BLOQUEADO'],
    fuera_sesion:['fuera','FUERA DE SESIÓN'],
    sin_señal:   ['espera','EN ESPERA'],
    iniciando:   ['espera','INICIANDO'],
    bot_offline: ['bloqueado','BOT OFFLINE'],
  };
  const [cls,txt]=smap[s.status]||['espera',(s.status||'—').toUpperCase()];
  setPill(cls,txt);

  function setPill(c,t){
    const p=document.getElementById('status-pill');
    p.className='status-pill '+c;
    document.getElementById('status-text').textContent=t;
  }

  // ── Cards
  document.getElementById('balance').textContent = fmt(s.balance)+' EUR';

  const diff=(s.equity||0)-(s.initial_balance||10000);
  const eqEl=document.getElementById('equity');
  eqEl.textContent=fmt(s.equity)+' EUR';
  eqEl.className='card-value '+(diff>=0?'pos-green':'pos-red');
  document.getElementById('equity-sub').textContent=(diff>=0?'+':'')+fmt(diff)+' EUR vs inicio';

  const pnl=s.daily_pnl||0;
  const pnlEl=document.getElementById('daily-pnl');
  pnlEl.textContent=fmtEur(pnl,true);
  pnlEl.className='card-value '+(pnl>=0?'pos-green':'pos-red');
  document.getElementById('daily-pnl-sub').textContent='Límite: -'+fmt(s.daily_limit_eur||100)+' EUR';

  const nPos=(s.open_positions||[]).length;
  const posEl=document.getElementById('pos-count');
  posEl.textContent=nPos+'/1';
  posEl.className='card-value '+(nPos>0?'pos-green':'pos-muted');
  document.getElementById('cycle-sub').textContent='Ciclo #'+(s.cycle||0);

  // ── FTMO gauge
  const floor=s.ftmo_floor||9000,init=s.initial_balance||10000,eq=s.equity||0;
  const ftmoPct=clamp((1-Math.max(0,init-eq)/(init-floor))*100,0,100);
  const fb=document.getElementById('ftmo-bar');
  fb.style.width=ftmoPct+'%';
  fb.className='bar-fill '+(ftmoPct>60?'bar-green':ftmoPct>30?'bar-yellow':'bar-red');
  document.getElementById('ftmo-nums').textContent=fmt(eq)+' / '+fmt(init)+' EUR';
  document.getElementById('ftmo-sub').textContent='Margen hasta suelo: '+fmt(eq-floor)+' EUR  (suelo: '+fmt(floor)+' EUR)';

  // ── Daily gauge
  const lossToday=Math.max(0,-pnl),limitEur=s.daily_limit_eur||100;
  const dailyPct=clamp((lossToday/limitEur)*100,0,100);
  const db=document.getElementById('daily-bar');
  db.style.width=dailyPct+'%';
  db.className='bar-fill '+(dailyPct<50?'bar-green':dailyPct<80?'bar-yellow':'bar-red');
  document.getElementById('daily-nums').textContent=fmt(lossToday)+' / '+fmt(limitEur)+' EUR';
  document.getElementById('daily-sub').textContent=
    dailyPct<100?'Pérdida hoy: '+fmtEur(-lossToday)+'  —  Restante: '+fmtEur(limitEur-lossToday)
               :'⛔ LÍMITE DIARIO ALCANZADO — reanuda mañana';

  // ── News
  const nl=document.getElementById('news-light'),nm=document.getElementById('news-main'),ns=document.getElementById('news-sub');
  if(s.news_status==='none'){
    nl.className='traffic-light light-none'; nl.textContent='📰';
    nm.textContent='Sin filtro activo'; ns.textContent='Bot sin --use-forex-factory';
  } else if(s.news_status==='blocked'){
    nl.className='traffic-light light-blocked'; nl.textContent='🔴';
    nm.textContent='⛔ BLACKOUT — '+(s.next_news_title||'Noticia roja');
    ns.textContent=s.next_news_mins!==null?'Minutos: '+s.next_news_mins:'Ejecución bloqueada';
  } else if(s.news_status==='warning'){
    nl.className='traffic-light light-warning'; nl.textContent='🟡';
    nm.textContent='⚠ PRECAUCIÓN — '+(s.next_news_title||'');
    ns.textContent='En '+(s.next_news_mins||'?')+' min';
  } else {
    nl.className='traffic-light light-ok'; nl.textContent='🟢';
    nm.textContent='Libre para operar';
    ns.textContent=s.next_news_title?'Próxima: '+s.next_news_title+' (en '+s.next_news_mins+' min)':'Sin noticias próximas';
  }

  // ── Session
  const sl=document.getElementById('session-light'),sm=document.getElementById('session-main');
  if(s.in_session){
    sl.className='traffic-light light-ok'; sl.textContent='🟢';
    sm.textContent=s.session||'Sesión activa'; sm.style.color='var(--accent)';
  } else {
    sl.className='traffic-light light-none'; sl.textContent='🌙';
    sm.textContent=s.session||'Fuera de sesión'; sm.style.color='var(--muted)';
  }

  // ── Signals
  const sb=s.score_bull||0,sr=s.score_bear||0,minSc=s.min_score||5;
  const sbEl=document.getElementById('score-bull'),srEl=document.getElementById('score-bear');
  sbEl.textContent=sb; srEl.textContent=sr;
  sbEl.style.opacity=sb>=minSc?'1':'0.35'; srEl.style.opacity=sr>=minSc?'1':'0.35';
  document.getElementById('sig-threshold').textContent='umbral: '+minSc+'/7';
  const dirEl=document.getElementById('last-signal-dir');
  if(s.last_signal_dir==='LONG'){dirEl.textContent='▲ Señal LONG'; dirEl.style.color='var(--accent)';}
  else if(s.last_signal_dir==='SHORT'){dirEl.textContent='▼ Señal SHORT'; dirEl.style.color='var(--red)';}
  else{dirEl.textContent='Sin señal'; dirEl.style.color='var(--muted)';}

  // ── Positions
  const posTb=document.getElementById('pos-tbody'),positions=s.open_positions||[];
  posTb.innerHTML=positions.length===0
    ?'<tr class="empty-row"><td colspan="8">Sin posiciones abiertas</td></tr>'
    :positions.map(p=>`<tr>
      <td>${p.ticket}</td><td>${p.symbol}</td>
      <td class="${p.dir==='LONG'?'dir-long':'dir-short'}">${p.dir}</td>
      <td>${fmt(p.lot,2)}</td><td>${fmt(p.entry,5)}</td>
      <td>${fmt(p.sl,5)}</td><td>${fmt(p.tp,5)}</td>
      <td class="${(p.pnl||0)>=0?'pnl-pos':'pnl-neg'}">${fmtEur(p.pnl,true)}</td>
    </tr>`).join('');

  // ── Trades
  const tradeTb=document.getElementById('trades-tbody'),trades=s.recent_trades||[];
  tradeTb.innerHTML=trades.length===0
    ?'<tr class="empty-row"><td colspan="5">Sin operaciones registradas</td></tr>'
    :[...trades].reverse().map(t=>`<tr>
      <td>${t.time||'—'}</td><td>${t.symbol||'—'}</td>
      <td class="${t.dir==='LONG'?'dir-long':'dir-short'}">${t.dir||'—'}</td>
      <td class="${(t.pnl||0)>=0?'pnl-pos':'pnl-neg'}">${fmtEur(t.pnl,true)}</td>
      <td>${t.motivo||'—'}</td>
    </tr>`).join('');

  // ── Log
  const logUl=document.getElementById('log-lines'),lines=s.log_lines||[];
  logUl.innerHTML=lines.length===0
    ?'<li>Esperando datos…</li>'
    :lines.map(l=>`<li>${l}</li>`).join('');

  document.getElementById('last-update').textContent=
    'Última push: '+(s.last_push||'—')+'  ·  Ciclo #'+(s.cycle||0);
}

setInterval(refresh, 5000);
refresh();
</script>
</body>
</html>"""
