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
<title>SMC-FTMO Dashboard</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg:        #0a0e1a;
    --card:      #111827;
    --border:    #1f2937;
    --accent:    #10b981;
    --red:       #ef4444;
    --yellow:    #f59e0b;
    --blue:      #3b82f6;
    --purple:    #8b5cf6;
    --text:      #f9fafb;
    --muted:     #6b7280;
    --sm:        0.75rem;
    --base:      0.875rem;
    --lg:        1rem;
    --xl:        1.25rem;
    --2xl:       1.5rem;
    --3xl:       1.875rem;
  }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    font-size: var(--base);
    min-height: 100vh;
    padding: 1rem 1.25rem 2rem;
  }

  /* ── Header ── */
  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1.25rem;
    padding-bottom: 0.75rem;
    border-bottom: 1px solid var(--border);
  }
  .header-left { display: flex; align-items: center; gap: 0.75rem; }
  .logo {
    font-size: var(--xl);
    font-weight: 700;
    letter-spacing: 0.05em;
    color: var(--accent);
  }
  .symbol-tag {
    background: var(--border);
    color: var(--text);
    font-size: var(--sm);
    font-weight: 600;
    padding: 0.25rem 0.6rem;
    border-radius: 6px;
    letter-spacing: 0.04em;
  }
  .dry-badge {
    background: #92400e;
    color: #fcd34d;
    font-size: 0.65rem;
    font-weight: 700;
    padding: 0.2rem 0.5rem;
    border-radius: 4px;
    letter-spacing: 0.08em;
    display: none;
  }
  .header-right { display: flex; align-items: center; gap: 1rem; }
  .status-pill {
    display: flex; align-items: center; gap: 0.35rem;
    font-size: var(--sm); font-weight: 600;
    padding: 0.3rem 0.8rem;
    border-radius: 9999px;
    border: 1px solid currentColor;
  }
  .dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
  .status-pill.operativo { color: var(--accent); }
  .status-pill.bloqueado { color: var(--red); }
  .status-pill.fuera     { color: var(--yellow); }
  .status-pill.espera    { color: var(--muted); }
  #clock { font-size: var(--sm); color: var(--muted); font-variant-numeric: tabular-nums; }

  /* ── Cards row ── */
  .cards {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 0.75rem;
    margin-bottom: 0.75rem;
  }
  @media (max-width: 800px) { .cards { grid-template-columns: repeat(2, 1fr); } }
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1rem 1.1rem;
  }
  .card-label { font-size: var(--sm); color: var(--muted); text-transform: uppercase;
                letter-spacing: 0.07em; margin-bottom: 0.35rem; }
  .card-value { font-size: var(--2xl); font-weight: 700; font-variant-numeric: tabular-nums; }
  .card-sub   { font-size: var(--sm); color: var(--muted); margin-top: 0.2rem; }
  .pos-green { color: var(--accent); }
  .pos-red   { color: var(--red); }
  .pos-muted { color: var(--muted); }

  /* ── Gauge bars ── */
  .gauges {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.75rem;
    margin-bottom: 0.75rem;
  }
  @media (max-width: 800px) { .gauges { grid-template-columns: 1fr; } }
  .gauge-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 0.9rem 1.1rem;
  }
  .gauge-header {
    display: flex; justify-content: space-between; align-items: baseline;
    margin-bottom: 0.6rem;
  }
  .gauge-title { font-size: var(--sm); color: var(--muted); text-transform: uppercase;
                 letter-spacing: 0.07em; }
  .gauge-nums  { font-size: var(--sm); color: var(--text); font-variant-numeric: tabular-nums; }
  .bar-track {
    width: 100%; height: 10px; background: var(--border); border-radius: 9999px;
    overflow: hidden;
  }
  .bar-fill {
    height: 100%; border-radius: 9999px;
    transition: width 0.5s ease, background 0.5s ease;
  }
  .bar-green  { background: linear-gradient(90deg, #064e3b, var(--accent)); }
  .bar-yellow { background: linear-gradient(90deg, #78350f, var(--yellow)); }
  .bar-red    { background: linear-gradient(90deg, #7f1d1d, var(--red)); }
  .gauge-sub { margin-top: 0.45rem; font-size: var(--sm); color: var(--muted); }

  /* ── Info row (news + session) ── */
  .info-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.75rem;
    margin-bottom: 0.75rem;
  }
  @media (max-width: 800px) { .info-row { grid-template-columns: 1fr; } }
  .info-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 0.9rem 1.1rem;
    display: flex; gap: 1rem; align-items: center;
  }
  .traffic-light {
    width: 42px; height: 42px; border-radius: 50%;
    border: 2px solid var(--border);
    display: flex; align-items: center; justify-content: center;
    font-size: 1.2rem; flex-shrink: 0;
    transition: background 0.4s;
  }
  .light-none    { background: #1f2937; }
  .light-ok      { background: #064e3b; border-color: var(--accent); }
  .light-warning { background: #78350f; border-color: var(--yellow); }
  .light-blocked { background: #7f1d1d; border-color: var(--red); animation: pulse 1s infinite; }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0.6; }
  }
  .info-text-block { flex: 1; }
  .info-title { font-size: var(--sm); color: var(--muted); text-transform: uppercase;
                letter-spacing: 0.07em; margin-bottom: 0.3rem; }
  .info-main  { font-size: var(--base); font-weight: 600; }
  .info-sub   { font-size: var(--sm); color: var(--muted); margin-top: 0.1rem; }

  /* ── Signals bar ── */
  .signals-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 0.85rem 1.1rem;
    display: flex; align-items: center; gap: 1.5rem;
    margin-bottom: 0.75rem;
  }
  .sig-label { font-size: var(--sm); color: var(--muted); text-transform: uppercase;
               letter-spacing: 0.06em; }
  .sig-pair  { display: flex; align-items: center; gap: 0.5rem; }
  .sig-name  { font-size: var(--sm); color: var(--muted); }
  .sig-score { font-size: var(--xl); font-weight: 700; font-variant-numeric: tabular-nums; }
  .sig-score.bull { color: var(--accent); }
  .sig-score.bear { color: var(--red); }
  .sig-threshold { font-size: var(--sm); color: var(--muted); }
  .sig-divider { width: 1px; height: 2rem; background: var(--border); }

  /* ── Tables ── */
  .table-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 0.9rem 1.1rem;
    margin-bottom: 0.75rem;
  }
  .table-title { font-size: var(--sm); color: var(--muted); text-transform: uppercase;
                 letter-spacing: 0.07em; margin-bottom: 0.75rem; }
  table { width: 100%; border-collapse: collapse; }
  th {
    font-size: 0.7rem; color: var(--muted); text-transform: uppercase;
    letter-spacing: 0.07em; text-align: left; padding: 0 0.5rem 0.5rem;
    border-bottom: 1px solid var(--border);
  }
  td {
    font-size: var(--sm); padding: 0.45rem 0.5rem;
    border-bottom: 1px solid #1a2235; font-variant-numeric: tabular-nums;
  }
  tr:last-child td { border-bottom: none; }
  .empty-row td { color: var(--muted); text-align: center; padding: 1rem; }
  .dir-long  { color: var(--accent); font-weight: 600; }
  .dir-short { color: var(--red);    font-weight: 600; }
  .pnl-pos   { color: var(--accent); }
  .pnl-neg   { color: var(--red); }

  /* ── Log ── */
  .log-card {
    background: #080c18;
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 0.85rem 1.1rem;
  }
  .log-title { font-size: var(--sm); color: var(--muted); text-transform: uppercase;
               letter-spacing: 0.07em; margin-bottom: 0.6rem; }
  .log-lines { list-style: none; }
  .log-lines li {
    font-size: 0.72rem; font-family: 'Cascadia Code', 'Consolas', monospace;
    color: #64748b; padding: 0.12rem 0;
    border-bottom: 1px solid #0f1623;
  }
  .log-lines li:last-child { border-bottom: none; color: #94a3b8; }
  .log-lines li:nth-last-child(2) { color: #6b7280; }

  /* ── Footer ── */
  .footer {
    margin-top: 1.5rem;
    text-align: center;
    font-size: 0.7rem;
    color: #374151;
  }
</style>
</head>
<body>

<!-- ── HEADER ── -->
<div class="header">
  <div class="header-left">
    <span class="logo">SMC-FTMO</span>
    <span class="symbol-tag" id="symbol-tag">—</span>
    <span class="dry-badge" id="dry-badge">DRY RUN</span>
  </div>
  <div class="header-right">
    <span class="status-pill espera" id="status-pill">
      <span class="dot"></span>
      <span id="status-text">Iniciando…</span>
    </span>
    <span id="clock">—</span>
  </div>
</div>

<!-- ── METRIC CARDS ── -->
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

<!-- ── GAUGES ── -->
<div class="gauges">
  <div class="gauge-card">
    <div class="gauge-header">
      <span class="gauge-title">Suelo FTMO (10% DD)</span>
      <span class="gauge-nums" id="ftmo-nums">—</span>
    </div>
    <div class="bar-track">
      <div class="bar-fill bar-green" id="ftmo-bar" style="width:100%"></div>
    </div>
    <div class="gauge-sub" id="ftmo-sub">Margen disponible: —</div>
  </div>
  <div class="gauge-card">
    <div class="gauge-header">
      <span class="gauge-title">Límite diario</span>
      <span class="gauge-nums" id="daily-nums">—</span>
    </div>
    <div class="bar-track">
      <div class="bar-fill bar-green" id="daily-bar" style="width:0%"></div>
    </div>
    <div class="gauge-sub" id="daily-sub">Pérdida: —</div>
  </div>
</div>

<!-- ── NEWS + SESSION ── -->
<div class="info-row">
  <div class="info-card">
    <div class="traffic-light light-none" id="news-light">📰</div>
    <div class="info-text-block">
      <div class="info-title">Noticias Forex Factory</div>
      <div class="info-main" id="news-main">No configurado</div>
      <div class="info-sub"  id="news-sub">Activa --use-forex-factory</div>
    </div>
  </div>
  <div class="info-card">
    <div class="traffic-light light-none" id="session-light">🕐</div>
    <div class="info-text-block">
      <div class="info-title">Sesión de mercado</div>
      <div class="info-main" id="session-main">—</div>
      <div class="info-sub"  id="session-sub">Londres 10:00–18:00 | NY 15:30–00:00 CEST</div>
    </div>
  </div>
</div>

<!-- ── SIGNALS ── -->
<div class="signals-card">
  <span class="sig-label">Señales SMC</span>
  <div class="sig-pair">
    <span class="sig-name">LONG</span>
    <span class="sig-score bull" id="score-bull">0</span>
  </div>
  <div class="sig-divider"></div>
  <div class="sig-pair">
    <span class="sig-name">SHORT</span>
    <span class="sig-score bear" id="score-bear">0</span>
  </div>
  <div class="sig-divider"></div>
  <span class="sig-threshold" id="sig-threshold">umbral: 5/7</span>
  <div style="flex:1"></div>
  <span class="sig-label" id="last-signal-dir" style="font-size:0.8rem">—</span>
</div>

<!-- ── OPEN POSITIONS ── -->
<div class="table-card">
  <div class="table-title">Posiciones abiertas</div>
  <table>
    <thead>
      <tr>
        <th>Ticket</th><th>Símbolo</th><th>Dir</th>
        <th>Lote</th><th>Entrada</th><th>SL</th><th>TP</th><th>P&amp;L</th>
      </tr>
    </thead>
    <tbody id="pos-tbody">
      <tr class="empty-row"><td colspan="8">Sin posiciones abiertas</td></tr>
    </tbody>
  </table>
</div>

<!-- ── RECENT TRADES ── -->
<div class="table-card">
  <div class="table-title">Últimas operaciones</div>
  <table>
    <thead>
      <tr>
        <th>Hora</th><th>Símbolo</th><th>Dir</th><th>P&amp;L</th><th>Motivo</th>
      </tr>
    </thead>
    <tbody id="trades-tbody">
      <tr class="empty-row"><td colspan="5">Sin operaciones registradas</td></tr>
    </tbody>
  </table>
</div>

<!-- ── LOG ── -->
<div class="log-card">
  <div class="log-title">Log en tiempo real</div>
  <ul class="log-lines" id="log-lines">
    <li>Esperando datos del bot…</li>
  </ul>
</div>

<div class="footer">SMC-FTMO Dashboard · Actualiza cada 3s · <span id="last-update">—</span></div>

<!-- ── JAVASCRIPT ── -->
<script>
"use strict";

function fmt(n, d=2) {
  if (n === null || n === undefined || isNaN(n)) return '—';
  return Number(n).toLocaleString('es-ES', {minimumFractionDigits: d, maximumFractionDigits: d});
}
function fmtEur(n, sign=false) {
  if (n === null || n === undefined || isNaN(n)) return '—';
  const abs = Math.abs(n);
  const prefix = n < 0 ? '-' : (sign && n > 0 ? '+' : '');
  return prefix + abs.toLocaleString('es-ES', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + ' EUR';
}
function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }

// Live clock
function updateClock() {
  const now = new Date();
  const pad = n => String(n).padStart(2,'0');
  document.getElementById('clock').textContent =
    pad(now.getUTCHours()) + ':' + pad(now.getUTCMinutes()) + ':' + pad(now.getUTCSeconds()) + ' UTC';
}
setInterval(updateClock, 1000);
updateClock();

async function refresh() {
  let s;
  try {
    const r = await fetch('/api/state');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    s = await r.json();
  } catch(e) {
    const pill = document.getElementById('status-pill');
    pill.className = 'status-pill bloqueado';
    document.getElementById('status-text').textContent = 'DESCONECTADO';
    return;
  }

  // ── Symbol & dry run
  document.getElementById('symbol-tag').textContent = s.symbol + '  ' + s.tf_chain;
  const dryBadge = document.getElementById('dry-badge');
  dryBadge.style.display = s.dry_run ? 'inline' : 'none';

  // ── Status pill
  const pill = document.getElementById('status-pill');
  const statusMap = {
    operativo:    ['operativo', 'OPERATIVO'],
    bloqueado:    ['bloqueado', 'BLOQUEADO'],
    fuera_sesion: ['fuera',     'FUERA DE SESIÓN'],
    sin_señal:    ['espera',    'EN ESPERA'],
    iniciando:    ['espera',    'INICIANDO'],
  };
  const [cls, txt] = statusMap[s.status] || ['espera', s.status.toUpperCase()];
  pill.className = 'status-pill ' + cls;
  document.getElementById('status-text').textContent = txt;

  // ── Metric cards
  document.getElementById('balance').textContent = fmt(s.balance) + ' EUR';

  const eqEl = document.getElementById('equity');
  eqEl.textContent = fmt(s.equity) + ' EUR';
  const diff = (s.equity || 0) - (s.initial_balance || 10000);
  eqEl.className = 'card-value ' + (diff >= 0 ? 'pos-green' : 'pos-red');
  document.getElementById('equity-sub').textContent =
    (diff >= 0 ? '+' : '') + fmt(diff) + ' EUR vs inicio';

  const pnl = s.daily_pnl || 0;
  const pnlEl = document.getElementById('daily-pnl');
  pnlEl.textContent = fmtEur(pnl, true);
  pnlEl.className   = 'card-value ' + (pnl >= 0 ? 'pos-green' : 'pos-red');
  document.getElementById('daily-pnl-sub').textContent =
    'Límite: -' + fmt(s.daily_limit_eur) + ' EUR';

  const nPos = (s.open_positions || []).length;
  const posEl = document.getElementById('pos-count');
  posEl.textContent = nPos + '/1';
  posEl.className   = 'card-value ' + (nPos > 0 ? 'pos-green' : 'pos-muted');
  document.getElementById('cycle-sub').textContent = 'Ciclo #' + (s.cycle || 0);

  // ── FTMO gauge
  const floor  = s.ftmo_floor || 9000;
  const init   = s.initial_balance || 10000;
  const eq     = s.equity || 0;
  const ftmoRange  = init - floor;              // 1000 EUR de margen total
  const ftmoUsed   = Math.max(0, init - eq);   // cuánto se ha perdido
  const ftmoPct    = clamp((1 - ftmoUsed / ftmoRange) * 100, 0, 100);
  const ftmoBar    = document.getElementById('ftmo-bar');
  ftmoBar.style.width = ftmoPct + '%';
  ftmoBar.className    = 'bar-fill ' +
    (ftmoPct > 60 ? 'bar-green' : ftmoPct > 30 ? 'bar-yellow' : 'bar-red');
  document.getElementById('ftmo-nums').textContent =
    fmt(eq) + ' / ' + fmt(init) + ' EUR';
  document.getElementById('ftmo-sub').textContent =
    'Margen hasta suelo: ' + fmt(eq - floor) + ' EUR  (suelo: ' + fmt(floor) + ' EUR)';

  // ── Daily limit gauge
  const lossToday = Math.max(0, -(pnl));          // pérdida positiva
  const limitEur  = s.daily_limit_eur || 100;
  const dailyPct  = clamp((lossToday / limitEur) * 100, 0, 100);
  const dailyBar  = document.getElementById('daily-bar');
  dailyBar.style.width = dailyPct + '%';
  dailyBar.className   = 'bar-fill ' +
    (dailyPct < 50 ? 'bar-green' : dailyPct < 80 ? 'bar-yellow' : 'bar-red');
  document.getElementById('daily-nums').textContent =
    fmt(lossToday) + ' / ' + fmt(limitEur) + ' EUR';
  document.getElementById('daily-sub').textContent =
    dailyPct < 100
      ? 'Pérdida hoy: ' + fmtEur(-lossToday) + '  —  Restante: ' + fmtEur(limitEur - lossToday)
      : '⛔ LÍMITE DIARIO ALCANZADO — reanuda mañana';

  // ── News traffic light
  const nl  = document.getElementById('news-light');
  const nm  = document.getElementById('news-main');
  const ns2 = document.getElementById('news-sub');
  if (s.news_status === 'none') {
    nl.className = 'traffic-light light-none'; nl.textContent = '📰';
    nm.textContent = 'Sin filtro activo';
    ns2.textContent = 'Activa --use-forex-factory';
  } else if (s.news_status === 'blocked') {
    nl.className = 'traffic-light light-blocked'; nl.textContent = '🔴';
    nm.textContent = '⛔ BLACKOUT — ' + (s.next_news_title || 'Noticia roja');
    ns2.textContent = s.next_news_mins !== null
      ? 'Minutos: ' + s.next_news_mins
      : 'Ejecución bloqueada';
  } else if (s.news_status === 'warning') {
    nl.className = 'traffic-light light-warning'; nl.textContent = '🟡';
    nm.textContent = '⚠ PRECAUCIÓN — ' + (s.next_news_title || '');
    ns2.textContent = 'En ' + (s.next_news_mins || '?') + ' min — prepárate';
  } else {
    nl.className = 'traffic-light light-ok'; nl.textContent = '🟢';
    nm.textContent = 'Libre para operar';
    ns2.textContent = s.next_news_title
      ? 'Próxima: ' + s.next_news_title + ' (en ' + s.next_news_mins + ' min)'
      : 'Sin noticias próximas detectadas';
  }

  // ── Session
  const sl2  = document.getElementById('session-light');
  const sm2  = document.getElementById('session-main');
  if (s.in_session) {
    sl2.className = 'traffic-light light-ok'; sl2.textContent = '🟢';
    sm2.textContent = s.session || 'Sesión activa';
    sm2.style.color = 'var(--accent)';
  } else {
    sl2.className = 'traffic-light light-none'; sl2.textContent = '🌙';
    sm2.textContent = s.session || 'Fuera de sesión';
    sm2.style.color = 'var(--muted)';
  }

  // ── Signals
  const sb = s.score_bull || 0;
  const sr = s.score_bear || 0;
  const minSc = s.min_score || 5;
  const sbEl = document.getElementById('score-bull');
  const srEl = document.getElementById('score-bear');
  sbEl.textContent = sb;
  srEl.textContent = sr;
  sbEl.style.opacity = sb >= minSc ? '1' : '0.4';
  srEl.style.opacity = sr >= minSc ? '1' : '0.4';
  document.getElementById('sig-threshold').textContent = 'umbral: ' + minSc + '/7';
  const dirEl = document.getElementById('last-signal-dir');
  if (s.last_signal_dir === 'LONG')  { dirEl.textContent = '▲ Señal LONG activa';  dirEl.style.color = 'var(--accent)'; }
  else if (s.last_signal_dir === 'SHORT') { dirEl.textContent = '▼ Señal SHORT activa'; dirEl.style.color = 'var(--red)'; }
  else { dirEl.textContent = 'Sin señal'; dirEl.style.color = 'var(--muted)'; }

  // ── Open positions
  const posTbody = document.getElementById('pos-tbody');
  const positions = s.open_positions || [];
  if (positions.length === 0) {
    posTbody.innerHTML = '<tr class="empty-row"><td colspan="8">Sin posiciones abiertas</td></tr>';
  } else {
    posTbody.innerHTML = positions.map(p => {
      const pnlCls = (p.pnl || 0) >= 0 ? 'pnl-pos' : 'pnl-neg';
      const dirCls = p.dir === 'LONG' ? 'dir-long' : 'dir-short';
      return `<tr>
        <td>${p.ticket}</td>
        <td>${p.symbol}</td>
        <td class="${dirCls}">${p.dir}</td>
        <td>${fmt(p.lot,2)}</td>
        <td>${fmt(p.entry,5)}</td>
        <td>${fmt(p.sl,5)}</td>
        <td>${fmt(p.tp,5)}</td>
        <td class="${pnlCls}">${fmtEur(p.pnl,true)}</td>
      </tr>`;
    }).join('');
  }

  // ── Recent trades
  const tradesTbody = document.getElementById('trades-tbody');
  const trades = s.recent_trades || [];
  if (trades.length === 0) {
    tradesTbody.innerHTML = '<tr class="empty-row"><td colspan="5">Sin operaciones registradas</td></tr>';
  } else {
    tradesTbody.innerHTML = [...trades].reverse().map(t => {
      const pnlCls = (t.pnl || 0) >= 0 ? 'pnl-pos' : 'pnl-neg';
      const dirCls = t.dir === 'LONG' ? 'dir-long' : 'dir-short';
      return `<tr>
        <td>${t.time || '—'}</td>
        <td>${t.symbol || '—'}</td>
        <td class="${dirCls}">${t.dir || '—'}</td>
        <td class="${pnlCls}">${fmtEur(t.pnl,true)}</td>
        <td>${t.motivo || '—'}</td>
      </tr>`;
    }).join('');
  }

  // ── Log
  const logUl = document.getElementById('log-lines');
  const lines  = s.log_lines || [];
  if (lines.length === 0) {
    logUl.innerHTML = '<li>Esperando datos del bot…</li>';
  } else {
    logUl.innerHTML = lines.map(l => `<li>${l}</li>`).join('');
  }

  document.getElementById('last-update').textContent =
    'Última actualización: ' + (s.last_update || '—');
}

setInterval(refresh, 3000);
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
