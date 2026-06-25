"""Dashboard web en tiempo real para SMC-FTMO.

Expone en http://localhost:PORT/ un panel profesional con:
  - Balance / Equity / P&L diario / Posiciones
  - Barra de proximidad al suelo FTMO
  - Barra de límite diario personalizable
  - Semáforo de noticias Forex Factory (verde/amarillo/rojo)
  - Tabla de posiciones abiertas y últimas operaciones
  - Log de señales SMC en tiempo real

Uso:
    from backtest.dashboard import start_dashboard, update_state
    start_dashboard(port=8765)          # lanza hilo daemon
    update_state(balance=10000, ...)    # actualiza desde el loop principal
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

# ── Estado compartido ──────────────────────────────────────────────────────────

_state: dict[str, Any] = {
    "symbol":          "—",
    "tf_chain":        "—",
    "status":          "iniciando",   # operativo | bloqueado | fuera_sesion | sin_señal
    "balance":         0.0,
    "equity":          0.0,
    "daily_pnl":       0.0,
    "daily_limit_eur": 100.0,
    "daily_start_eq":  0.0,
    "ftmo_floor":      9000.0,
    "initial_balance": 10000.0,
    "open_positions":  [],            # [{ticket, symbol, dir, lot, entry, sl, tp, pnl}]
    "recent_trades":   [],            # [{time, symbol, dir, pnl, motivo}] (últimas 10)
    "session":         "—",
    "in_session":      False,
    "news_status":     "none",        # none | ok | warning | blocked
    "next_news_title": "",
    "next_news_mins":  None,
    "score_bull":      0,
    "score_bear":      0,
    "min_score":       5,
    "last_signal_dir": None,
    "cycle":           0,
    "last_update":     None,
    "dry_run":         False,
    "log_lines":       [],            # últimas 12 líneas del log
}
_lock = threading.Lock()


def update_state(**kwargs: Any) -> None:
    """Actualiza campos del estado compartido desde el loop principal."""
    with _lock:
        _state.update(kwargs)
        _state["last_update"] = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")


def get_state() -> dict:
    """Devuelve una copia del estado actual (thread-safe). Usado para cloud push."""
    with _lock:
        return dict(_state)


def push_log(line: str) -> None:
    """Añade una línea al log circular (máx 12 entradas)."""
    with _lock:
        lines: list = _state["log_lines"]
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        lines.append(f"{ts}  {line}")
        if len(lines) > 12:
            lines.pop(0)


# ── HTML embebido ──────────────────────────────────────────────────────────────

_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SMC·FTMO — Command Center</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
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
  --font:'Inter',system-ui,-apple-system,sans-serif;
  --mono:'JetBrains Mono','Cascadia Code','Consolas',monospace;
}
body{background:var(--bg);color:var(--t1);font-family:var(--font);font-size:.875rem;line-height:1.5;min-height:100vh}
.app{max-width:1280px;margin:0 auto;padding:0 1.25rem 3rem}
.mono{font-family:var(--mono)}

/* offline banner */
.offline{display:none;background:var(--rd);border:1px solid var(--red);color:var(--red);
  font-size:.75rem;font-weight:600;text-align:center;padding:.5rem 1rem;letter-spacing:.04em}

/* header */
.hdr{position:sticky;top:0;z-index:50;background:rgba(6,9,15,.85);
  backdrop-filter:blur(16px);border-bottom:1px solid var(--b1);
  display:flex;align-items:center;justify-content:space-between;
  padding:.75rem 1.25rem;margin:0 -1.25rem 1.5rem}
.hdr-l{display:flex;align-items:center;gap:.75rem}
.logo{font-size:1.1rem;font-weight:700;letter-spacing:.08em;color:var(--t1)}
.logo em{font-style:normal;color:var(--green)}
.vd{width:1px;height:1.2rem;background:var(--b2)}
.sym-badge{background:var(--s2);border:1px solid var(--b1);color:var(--t1);
  font-family:var(--mono);font-size:.75rem;font-weight:500;
  padding:.2rem .6rem;border-radius:6px;letter-spacing:.04em}
.tf-tag{font-size:.7rem;color:var(--t3);font-family:var(--mono)}
.dry-badge{display:none;background:var(--ad);border:1px solid var(--amber);
  color:var(--amber);font-size:.65rem;font-weight:700;
  padding:.2rem .5rem;border-radius:4px;letter-spacing:.08em}
.hdr-r{display:flex;align-items:center;gap:.75rem}
.pill{display:flex;align-items:center;gap:.4rem;font-size:.72rem;font-weight:600;
  padding:.28rem .8rem;border-radius:9999px;border:1px solid;letter-spacing:.04em;
  transition:all .3s}
.pill .dot{width:6px;height:6px;border-radius:50%;background:currentColor}
.p-live{color:var(--green);border-color:rgba(63,185,80,.4);background:var(--gd)}
.p-live .dot{animation:blink 1.4s ease-in-out infinite}
.p-block{color:var(--red);border-color:rgba(248,81,73,.4);background:var(--rd)}
.p-idle{color:var(--amber);border-color:rgba(210,153,34,.4);background:var(--ad)}
.p-off{color:var(--t3);border-color:var(--b2);background:var(--s2)}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.35}}
.clk{font-family:var(--mono);font-size:.72rem;color:var(--t3);min-width:7rem;text-align:right}

/* KPI grid */
.kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:.75rem;margin-bottom:.75rem}
@media(max-width:900px){.kpi-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:500px){.kpi-grid{grid-template-columns:1fr}}
.kpi{background:var(--s1);border:1px solid var(--b1);border-top:2px solid var(--b2);
  border-radius:10px;padding:1rem 1.1rem;
  transition:border-top-color .4s,transform .15s,box-shadow .15s;cursor:default}
.kpi:hover{transform:translateY(-2px);box-shadow:0 8px 24px rgba(0,0,0,.4)}
.c-green{border-top-color:var(--green)}
.c-red  {border-top-color:var(--red)}
.c-amber{border-top-color:var(--amber)}
.c-blue {border-top-color:var(--blue)}
.kpi-lbl{font-size:.68rem;color:var(--t3);text-transform:uppercase;letter-spacing:.08em;margin-bottom:.4rem}
.kpi-val{font-size:1.5rem;font-weight:700;font-family:var(--mono);color:var(--t1);
  transition:color .4s;line-height:1.1;margin-bottom:.35rem}
.kpi-sub{font-size:.72rem;color:var(--t2);display:flex;align-items:center;gap:.35rem;flex-wrap:wrap}
.badge{font-size:.65rem;font-weight:600;padding:.1rem .4rem;border-radius:4px;font-family:var(--mono)}
.b-pos{background:var(--gd);color:var(--green)}
.b-neg{background:var(--rd);color:var(--red)}
.b-neu{background:var(--s3);color:var(--t2)}

/* Gauges */
.gauge-row{display:grid;grid-template-columns:1fr 1fr;gap:.75rem;margin-bottom:.75rem}
@media(max-width:700px){.gauge-row{grid-template-columns:1fr}}
.gauge{background:var(--s1);border:1px solid var(--b1);border-radius:10px;padding:.9rem 1.1rem}
.gauge-hdr{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:.6rem}
.gauge-lbl{font-size:.68rem;color:var(--t3);text-transform:uppercase;letter-spacing:.08em}
.gauge-val{font-size:.75rem;color:var(--t2);font-family:var(--mono)}
.track{height:8px;background:var(--s3);border-radius:9999px;overflow:hidden}
.fill{height:100%;border-radius:9999px;transition:width .6s cubic-bezier(.4,0,.2,1),background .5s}
.f-g{background:linear-gradient(90deg,#033a1b,var(--green));box-shadow:0 0 8px rgba(63,185,80,.3)}
.f-a{background:linear-gradient(90deg,#4d3800,var(--amber));box-shadow:0 0 8px rgba(210,153,34,.3)}
.f-r{background:linear-gradient(90deg,#4d0f0c,var(--red));box-shadow:0 0 8px rgba(248,81,73,.3)}
.gauge-ftr{display:flex;justify-content:space-between;margin-top:.4rem;
  font-size:.67rem;color:var(--t3);font-family:var(--mono)}

/* Info cards (news + session) */
.info-row{display:grid;grid-template-columns:1fr 1fr;gap:.75rem;margin-bottom:.75rem}
@media(max-width:700px){.info-row{grid-template-columns:1fr}}
.icard{background:var(--s1);border:1px solid var(--b1);border-radius:10px;
  padding:.9rem 1.1rem;display:flex;gap:1rem;align-items:center}
.indicator{width:40px;height:40px;border-radius:50%;border:1.5px solid var(--b2);
  display:flex;align-items:center;justify-content:center;
  font-size:1.1rem;flex-shrink:0;transition:all .4s}
.i-none {background:var(--s2);border-color:var(--b1)}
.i-ok   {background:rgba(63,185,80,.1);border-color:rgba(63,185,80,.5)}
.i-warn {background:rgba(210,153,34,.1);border-color:rgba(210,153,34,.5);animation:pulse-a .9s infinite}
.i-block{background:rgba(248,81,73,.1);border-color:rgba(248,81,73,.5);animation:pulse-r .7s infinite}
@keyframes pulse-a{0%,100%{box-shadow:0 0 0 0 rgba(210,153,34,.4)}50%{box-shadow:0 0 0 6px rgba(210,153,34,0)}}
@keyframes pulse-r{0%,100%{box-shadow:0 0 0 0 rgba(248,81,73,.5)}50%{box-shadow:0 0 0 8px rgba(248,81,73,0)}}
.icontent{flex:1}
.itype{font-size:.67rem;color:var(--t3);text-transform:uppercase;letter-spacing:.08em;margin-bottom:.25rem}
.imain{font-size:.875rem;font-weight:600;color:var(--t1);transition:color .4s}
.isub {font-size:.7rem;color:var(--t2);margin-top:.15rem}

/* Signal panel */
.sig-card{background:var(--s1);border:1px solid var(--b1);border-radius:10px;
  padding:1rem 1.25rem;margin-bottom:.75rem}
.sig-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:.9rem}
.sig-title{font-size:.75rem;color:var(--t3);text-transform:uppercase;letter-spacing:.08em}
.sig-last{font-size:.72rem;font-weight:600;padding:.18rem .55rem;border-radius:6px}
.sl-long {background:var(--gd);color:var(--green)}
.sl-short{background:var(--rd);color:var(--red)}
.sl-none {background:var(--s3);color:var(--t3)}
.sig-grid{display:flex;gap:0;align-items:stretch}
.sig-side{flex:1;display:flex;flex-direction:column;gap:.5rem;padding:.25rem 1rem}
.sig-side:first-child{padding-left:0}
.sig-divider{width:1px;background:var(--b1);margin:.25rem 0}
.sig-dir{font-size:.7rem;font-weight:700;letter-spacing:.1em;color:var(--t2)}
.sd-bull{color:var(--green)}
.sd-bear{color:var(--red)}
.sig-row{display:flex;align-items:center;gap:.75rem}
.sig-num{font-size:2.2rem;font-weight:700;font-family:var(--mono);line-height:1;
  transition:all .4s;min-width:2rem}
.sn-bull{color:var(--green)}
.sn-bear{color:var(--red)}
.sn-off{opacity:.2}
.sn-bull.on{text-shadow:0 0 16px rgba(63,185,80,.6)}
.sn-bear.on{text-shadow:0 0 16px rgba(248,81,73,.6)}
.dots{display:flex;gap:5px;align-items:center}
.d{width:10px;height:10px;border-radius:50%;background:var(--b2);
  transition:all .35s cubic-bezier(.4,0,.2,1);flex-shrink:0}
.d.on-bull{background:var(--green);box-shadow:0 0 6px rgba(63,185,80,.7)}
.d.on-bear{background:var(--red);box-shadow:0 0 6px rgba(248,81,73,.7)}
.sig-thr{font-size:.67rem;color:var(--t3);font-family:var(--mono)}

/* Tables */
.tbl-card{background:var(--s1);border:1px solid var(--b1);border-radius:10px;
  padding:.9rem 1.1rem;margin-bottom:.75rem;overflow-x:auto}
.tbl-hdr{display:flex;align-items:center;gap:.6rem;margin-bottom:.75rem}
.tbl-title{font-size:.75rem;color:var(--t3);text-transform:uppercase;letter-spacing:.08em}
.tbl-cnt{background:var(--s3);color:var(--t2);font-size:.65rem;font-weight:600;
  padding:.1rem .45rem;border-radius:9999px;font-family:var(--mono)}
table{width:100%;border-collapse:collapse}
th{font-size:.65rem;color:var(--t3);text-transform:uppercase;letter-spacing:.08em;
  text-align:left;padding:.3rem .6rem .5rem;border-bottom:1px solid var(--b1)}
td{font-size:.78rem;padding:.45rem .6rem;border-bottom:1px solid var(--s2);
  font-family:var(--mono);color:var(--t2);transition:background .2s}
tr:hover td{background:var(--s2)}
tr:last-child td{border-bottom:none}
.empty td{color:var(--t3);text-align:center;padding:1.2rem;font-family:var(--font)}
.dl{color:var(--green);font-weight:600}
.ds{color:var(--red);font-weight:600}
.pp{color:var(--green)}
.pn{color:var(--red)}
.tk{background:var(--s3);color:var(--t2);padding:.1rem .35rem;border-radius:4px;font-size:.72rem}

/* Log */
.log-card{background:#030508;border:1px solid var(--b1);border-radius:10px;
  padding:.9rem 1.1rem;margin-bottom:.75rem}
.log-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:.7rem}
.log-title{font-size:.75rem;color:var(--t3);text-transform:uppercase;letter-spacing:.08em;
  display:flex;align-items:center;gap:.5rem}
.log-dot{width:6px;height:6px;border-radius:50%;background:var(--green);
  animation:blink 1.4s ease-in-out infinite}
.log-ts{font-size:.67rem;color:var(--t3);font-family:var(--mono)}
.log-body{display:flex;flex-direction:column;gap:1px}
.ll{display:flex;gap:.75rem;padding:.22rem 0;border-bottom:1px solid rgba(255,255,255,.03);
  animation:fade-in .3s ease}
.ll:last-child{border-bottom:none}
@keyframes fade-in{from{opacity:0;transform:translateY(3px)}to{opacity:1;transform:none}}
.lt{font-family:var(--mono);font-size:.68rem;color:var(--t3);flex-shrink:0;min-width:5rem}
.ll span:last-child{font-family:var(--mono);font-size:.72rem;color:var(--t2)}
.ll:last-child span:last-child{color:var(--t1)}

/* Footer */
.footer{display:flex;justify-content:space-between;font-size:.67rem;color:var(--t3);
  padding:.75rem 0 0;border-top:1px solid var(--b1);font-family:var(--mono)}
</style>
</head>
<body>
<div class="app">

<div class="offline" id="banner">⚠ Bot desconectado — sin datos en los últimos 2 minutos</div>

<header class="hdr">
  <div class="hdr-l">
    <span class="logo">SMC·<em>FTMO</em></span>
    <span class="vd"></span>
    <span class="sym-badge" id="sym">—</span>
    <span class="tf-tag" id="tf-tag"></span>
    <span class="dry-badge" id="dry">DRY RUN</span>
  </div>
  <div class="hdr-r">
    <div class="pill p-off" id="pill"><span class="dot"></span><span id="pill-txt">Conectando</span></div>
    <span class="clk" id="clk">—</span>
  </div>
</header>

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

<div class="log-card">
  <div class="log-hdr">
    <span class="log-title"><span class="log-dot"></span>Log en tiempo real</span>
    <span class="log-ts" id="log-ts">—</span>
  </div>
  <div class="log-body" id="log-body">
    <div class="ll"><span class="lt">—</span><span>Esperando datos del bot…</span></div>
  </div>
</div>

<div class="footer">
  <span>SMC·FTMO Command Center · Actualiza cada 3s</span>
  <span id="ft-upd">—</span>
</div>

</div>

<script>
"use strict";
const $ = id => document.getElementById(id);
const fmt = (n,d=2) => n==null||isNaN(n) ? '—'
  : Number(n).toLocaleString('es-ES',{minimumFractionDigits:d,maximumFractionDigits:d});
const fmtE = (n,sign=false) => {
  if (n==null||isNaN(n)) return '—';
  const pre = n<0?'-':(sign&&n>0?'+':'');
  return pre+Math.abs(n).toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+' EUR';
};
const clamp = (v,lo,hi) => Math.min(hi,Math.max(lo,v));

// Clock
const tick = () => {
  const n=new Date(),p=x=>String(x).padStart(2,'0');
  $('clk').textContent=p(n.getUTCHours())+':'+p(n.getUTCMinutes())+':'+p(n.getUTCSeconds())+' UTC';
};
setInterval(tick,1000); tick();

function setPill(type,txt){
  $('pill').className='pill '+type;
  $('pill-txt').textContent=txt;
}

function setDots(id,score,type){
  document.querySelectorAll('#'+id+' .d').forEach((d,i)=>{
    d.className='d'+(i<score?' on-'+type:'');
  });
}

async function refresh(){
  let s;
  try{
    const r=await fetch('/api/state');
    if(!r.ok) throw 0;
    s=await r.json();
  }catch{
    setPill('p-off','DESCONECTADO');
    return;
  }

  // Offline banner
  const banner=$('banner');
  if(s.last_update){
    const parts=s.last_update.replace(' UTC','').split(':');
    const ps=parseInt(parts[0])*3600+parseInt(parts[1])*60+parseInt(parts[2]);
    const n=new Date(),ns=n.getUTCHours()*3600+n.getUTCMinutes()*60+n.getUTCSeconds();
    banner.style.display=((ns-ps+86400)%86400)>120?'block':'none';
  }else{
    banner.style.display='none';
  }

  // Header
  $('sym').textContent=s.symbol||'—';
  $('tf-tag').textContent=s.tf_chain?'· '+s.tf_chain:'';
  $('dry').style.display=s.dry_run?'inline':'none';

  // Pill
  const PM={
    operativo:   ['p-live','OPERATIVO'],
    bloqueado:   ['p-block','BLOQUEADO'],
    fuera_sesion:['p-idle','FUERA SESIÓN'],
    sin_señal:   ['p-idle','EN ESPERA'],
    iniciando:   ['p-idle','INICIANDO'],
  };
  const[pc,pt]=PM[s.status]||['p-off',(s.status||'?').toUpperCase()];
  setPill(pc,pt);

  // Balance
  $('bal').textContent=fmt(s.balance)+' EUR';

  // Equity
  const diff=(s.equity||0)-(s.initial_balance||10000);
  $('eq').textContent=fmt(s.equity)+' EUR';
  $('eq').style.color=diff>=0?'var(--green)':'var(--red)';
  const ed=$('eq-delta');
  ed.textContent=(diff>=0?'+':'')+fmt(diff)+' EUR';
  ed.className='badge '+(diff>=0?'b-pos':'b-neg');
  $('eq-card').className='kpi '+(diff>=0?'c-green':'c-red');

  // P&L
  const pnl=s.daily_pnl||0;
  $('pnl').textContent=fmtE(pnl,true);
  $('pnl').style.color=pnl>=0?'var(--green)':'var(--red)';
  $('pnl-lim').textContent='-'+fmt(s.daily_limit_eur||100)+' EUR';
  $('pnl-card').className='kpi '+(pnl<-(s.daily_limit_eur||100)*.7?'c-red':pnl<0?'c-amber':'c-green');

  // Positions count
  const np=(s.open_positions||[]).length;
  $('pos-n').textContent=np+' / 1';
  $('pos-n').style.color=np>0?'var(--green)':'var(--t1)';
  $('cyc').textContent='#'+(s.cycle||0);
  $('pos-cnt').textContent=np;
  $('pos-card').className='kpi '+(np>0?'c-green':'c-blue');

  // FTMO gauge
  const floor=s.ftmo_floor||9000,init=s.initial_balance||10000,eq=s.equity||0;
  const fp=clamp((1-Math.max(0,init-eq)/(init-floor))*100,0,100);
  const fb=$('ftmo-bar');
  fb.style.width=fp+'%';
  fb.className='fill '+(fp>60?'f-g':fp>30?'f-a':'f-r');
  $('ftmo-val').textContent=fmt(eq)+' / '+fmt(init)+' EUR';
  $('ftmo-l').textContent='Margen: '+fmt(eq-floor)+' EUR';
  $('ftmo-r').textContent='Suelo: '+fmt(floor)+' EUR';

  // Daily gauge
  const loss=Math.max(0,-pnl),lim=s.daily_limit_eur||100;
  const dp=clamp((loss/lim)*100,0,100);
  const db=$('day-bar');
  db.style.width=dp+'%';
  db.className='fill '+(dp<50?'f-g':dp<80?'f-a':'f-r');
  $('day-val').textContent=fmt(loss)+' / '+fmt(lim)+' EUR';
  $('day-l').textContent=dp<100?'Pérdida: '+fmtE(-loss):'⛔ Límite alcanzado';
  $('day-r').textContent=dp<100?'Restante: '+fmtE(lim-loss):'';

  // News
  const ni=$('news-ind'),nm=$('news-main'),ns=$('news-sub');
  const NS={
    none:   ['i-none','📰','Sin filtro activo','Activa --use-forex-factory'],
    ok:     ['i-ok','🟢','Libre para operar',s.next_news_title?'Próx: '+s.next_news_title+' ('+s.next_news_mins+'min)':'Sin noticias próximas'],
    warning:['i-warn','🟡','Precaución — '+(s.next_news_title||''),'En '+(s.next_news_mins||'?')+' min'],
    blocked:['i-block','🔴','⛔ BLACKOUT — '+(s.next_news_title||'Noticia roja'),s.next_news_mins!=null?'Faltan '+s.next_news_mins+' min':'Bloqueado'],
  };
  const[nc,ne,nt,nst]=NS[s.news_status]||NS.none;
  ni.className='indicator '+nc; ni.textContent=ne;
  nm.textContent=nt; ns.textContent=nst;

  // Session
  const si=$('sess-ind'),sm=$('sess-main');
  if(s.in_session){
    si.className='indicator i-ok'; si.textContent='🟢';
    sm.textContent=s.session||'Sesión activa'; sm.style.color='var(--green)';
  }else{
    si.className='indicator i-none'; si.textContent='🌙';
    sm.textContent=s.session||'Fuera de sesión'; sm.style.color='var(--t2)';
  }

  // Signals
  const bull=s.score_bull||0,bear=s.score_bear||0,minSc=s.min_score||5;
  $('sc-bull').textContent=bull;
  $('sc-bear').textContent=bear;
  $('sc-bull').className='sig-num sn-bull '+(bull>=minSc?'on':'sn-off');
  $('sc-bear').className='sig-num sn-bear '+(bear>=minSc?'on':'sn-off');
  $('thr-bull').textContent=bull+' / 7 condiciones';
  $('thr-bear').textContent=bear+' / 7 condiciones';
  setDots('dots-bull',bull,'bull');
  setDots('dots-bear',bear,'bear');
  const sl=$('sig-last');
  if(s.last_signal_dir==='LONG')      {sl.textContent='▲ Señal LONG'; sl.className='sig-last sl-long';}
  else if(s.last_signal_dir==='SHORT'){sl.textContent='▼ Señal SHORT';sl.className='sig-last sl-short';}
  else                                 {sl.textContent='Sin señal';    sl.className='sig-last sl-none';}

  // Positions table
  const pos=s.open_positions||[];
  $('pos-tbody').innerHTML=pos.length===0
    ?'<tr class="empty"><td colspan="8">Sin posiciones abiertas</td></tr>'
    :pos.map(p=>`<tr>
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
  const trades=[...(s.recent_trades||[])].reverse();
  $('trade-cnt').textContent=trades.length;
  $('trade-tbody').innerHTML=trades.length===0
    ?'<tr class="empty"><td colspan="5">Sin operaciones registradas</td></tr>'
    :trades.map(t=>`<tr>
      <td class="mono" style="color:var(--t2)">${t.time||'—'}</td>
      <td class="mono">${t.symbol||'—'}</td>
      <td class="${t.dir==='LONG'?'dl':'ds'}">${t.dir==='LONG'?'▲ LONG':'▼ SHORT'}</td>
      <td class="${(t.pnl||0)>=0?'pp':'pn'}">${fmtE(t.pnl,true)}</td>
      <td style="color:var(--t2);font-size:.72rem">${t.motivo||'—'}</td>
    </tr>`).join('');

  // Log
  const lines=s.log_lines||[];
  $('log-body').innerHTML=lines.length===0
    ?'<div class="ll"><span class="lt">—</span><span>Esperando datos…</span></div>'
    :lines.map(l=>{
      const ts=l.match(/^\d{2}:\d{2}/)?.[0]||'';
      const msg=ts?l.slice(ts.length).trim():l;
      return `<div class="ll"><span class="lt">${ts}</span><span>${msg}</span></div>`;
    }).join('');
  $('log-ts').textContent=s.last_update||'—';

  $('ft-upd').textContent='Última actualización: '+(s.last_update||'—')+'  ·  Ciclo #'+(s.cycle||0);
}

setInterval(refresh,3000);
refresh();
</script>
</body>
</html>"""


# ── HTTP Handler ───────────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._serve_bytes(_HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            with _lock:
                data = json.dumps(_state, default=str).encode("utf-8")
            self._serve_bytes(data, "application/json", cors=True)
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_bytes(self, body: bytes, ctype: str, cors: bool = False) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if cors:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: Any) -> None:
        pass   # silencia el access log en consola


# ── Public API ─────────────────────────────────────────────────────────────────

def start_dashboard(port: int = 8765) -> HTTPServer:
    """Lanza el servidor HTTP en un hilo daemon. Devuelve la instancia del servidor."""
    server = HTTPServer(("0.0.0.0", port), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True, name="dashboard-http")
    t.start()
    return server
