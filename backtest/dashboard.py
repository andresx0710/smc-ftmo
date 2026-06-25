"""Dashboard web en tiempo real para SMC-FTMO.

Expone en http://localhost:PORT/ un panel profesional con:
  - Balance / Equity / P&L diario / Posiciones
  - Equity curve chart (Chart.js)
  - P&L por operación (bar chart)
  - Stats de rendimiento (Win Rate, PF, etc.)
  - Panel de configuración interactivo (pausa, min_score)
  - Calculadora de riesgo en tiempo real

Uso:
    from backtest.dashboard import start_dashboard, update_state, get_controls
    start_dashboard(port=8765)
    update_state(balance=10000, ...)
    ctrl = get_controls()  # {"paused": False, "min_score_override": None}
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
    "status":          "iniciando",
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
    "conds_bull":      {"choch":False,"ob":False,"liq":False,"fvg":False,"pd":False,"bos":False,"sd":False},
    "conds_bear":      {"choch":False,"ob":False,"liq":False,"fvg":False,"pd":False,"bos":False,"sd":False},
    "tv_signal":       None,   # última señal recibida por webhook de TradingView
    "cycle":           0,
    "last_update":     None,
    "dry_run":         False,
    "log_lines":       [],
    "equity_history":  [],   # [{t:"HH:MM", v:float}] — máx 300 puntos
}
_lock = threading.Lock()

# ── Controles remotos ──────────────────────────────────────────────────────────

_controls: dict[str, Any] = {
    "paused":             False,   # pausa el bot sin detenerlo
    "min_score_override": None,    # int o None (usa default CLI)
}
_ctl_lock = threading.Lock()


def update_state(**kwargs: Any) -> None:
    """Actualiza campos del estado compartido desde el loop principal."""
    with _lock:
        _state.update(kwargs)
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        _state["last_update"] = ts + " UTC"
        if "equity" in kwargs:
            hist: list = _state["equity_history"]
            pt = {"t": ts, "v": round(float(kwargs["equity"]), 2)}
            if not hist or hist[-1]["v"] != pt["v"]:
                hist.append(pt)
                if len(hist) > 300:
                    hist.pop(0)


def get_state() -> dict:
    """Devuelve una copia del estado actual (thread-safe). Usado para cloud push."""
    with _lock:
        return dict(_state)


def push_log(line: str) -> None:
    """Añade una línea al log circular (máx 15 entradas)."""
    with _lock:
        lines: list = _state["log_lines"]
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        lines.append(f"{ts}  {line}")
        if len(lines) > 15:
            lines.pop(0)


def get_controls() -> dict:
    """Devuelve los controles remotos actuales. Llamar desde el loop del bot."""
    with _ctl_lock:
        return dict(_controls)


def set_controls(**kwargs: Any) -> None:
    """Actualiza controles remotos desde el dashboard."""
    with _ctl_lock:
        for k, v in kwargs.items():
            if k in _controls:
                _controls[k] = v


# ── HTML embebido ──────────────────────────────────────────────────────────────

_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SMC·FTMO</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#000;
  --c1:rgba(255,255,255,.055);
  --c2:rgba(255,255,255,.09);
  --br:rgba(255,255,255,.08);
  --br2:rgba(255,255,255,.14);
  --t1:#fff;--t2:rgba(255,255,255,.52);--t3:rgba(255,255,255,.24);--t4:rgba(255,255,255,.1);
  --gr:#30d158;--gr2:rgba(48,209,88,.18);--gr3:rgba(48,209,88,.07);
  --rd:#ff453a;--rd2:rgba(255,69,58,.18);--rd3:rgba(255,69,58,.07);
  --am:#ff9f0a;--am2:rgba(255,159,10,.18);--am3:rgba(255,159,10,.07);
  --bl:#0a84ff;--bl2:rgba(10,132,255,.18);--bl3:rgba(10,132,255,.07);
  --pu:#bf5af2;--pu2:rgba(191,90,242,.18);--pu3:rgba(191,90,242,.07);
  --font:-apple-system,'SF Pro Display',BlinkMacSystemFont,'Helvetica Neue','Segoe UI',sans-serif;
  --mono:'SF Mono','JetBrains Mono','Cascadia Code','Consolas',monospace;
  --r:18px;--r2:12px;--r3:8px;
  --sp:cubic-bezier(.34,1.56,.64,1);
  --ease:cubic-bezier(.4,0,.2,1);
  --fast:cubic-bezier(.25,.46,.45,.94);
}
html{scroll-behavior:smooth}
body{
  background:var(--bg);color:var(--t1);
  font-family:var(--font);font-size:.9375rem;line-height:1.47;
  min-height:100vh;overflow-x:hidden;
  -webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;
}
body::before{
  content:'';position:fixed;inset:0;pointer-events:none;z-index:0;
  background:
    radial-gradient(ellipse 900px 500px at -10% -5%,rgba(48,209,88,.04) 0%,transparent 70%),
    radial-gradient(ellipse 600px 400px at 110% 100%,rgba(10,132,255,.035) 0%,transparent 70%);
}
.app{position:relative;z-index:1;max-width:1380px;margin:0 auto;padding:0 1.5rem 5rem}

/* Offline */
.offline{display:none;background:var(--rd2);border-bottom:1px solid rgba(255,69,58,.3);
  color:var(--rd);font-size:.74rem;font-weight:600;text-align:center;padding:.55rem 1rem}

/* ── HEADER ── */
.hdr{
  position:sticky;top:0;z-index:200;
  background:rgba(0,0,0,.78);backdrop-filter:saturate(180%) blur(24px);
  -webkit-backdrop-filter:saturate(180%) blur(24px);
  border-bottom:1px solid var(--br);
  display:flex;align-items:center;justify-content:space-between;
  padding:.85rem 1.5rem;margin:0 -1.5rem 2rem;
}
.hdr-l{display:flex;align-items:center;gap:.9rem}
.logo{font-size:1rem;font-weight:700;letter-spacing:-.01em;
  background:linear-gradient(135deg,#fff 40%,rgba(255,255,255,.5));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.logo-dot{display:inline-block;width:7px;height:7px;border-radius:50%;
  background:var(--gr);margin:0 .12rem .06rem;box-shadow:0 0 8px var(--gr);
  -webkit-text-fill-color:initial;animation:dp 2s ease-in-out infinite}
@keyframes dp{0%,100%{transform:scale(1)}50%{transform:scale(1.35);opacity:.7}}
.vd{width:1px;height:1rem;background:var(--br2)}
.sym{background:var(--c1);border:1px solid var(--br);color:var(--t1);
  font-family:var(--mono);font-size:.72rem;font-weight:500;
  padding:.22rem .65rem;border-radius:var(--r3);letter-spacing:.06em}
.tf{font-size:.68rem;color:var(--t3);font-family:var(--mono)}
.dry{display:none;background:var(--am3);border:1px solid rgba(255,159,10,.3);
  color:var(--am);font-size:.64rem;font-weight:700;
  padding:.18rem .5rem;border-radius:6px;letter-spacing:.08em}
.hdr-r{display:flex;align-items:center;gap:.85rem}
.pill{display:flex;align-items:center;gap:.42rem;font-size:.71rem;font-weight:600;
  letter-spacing:.04em;padding:.3rem .9rem;border-radius:9999px;border:1px solid;
  transition:all .4s var(--ease)}
.dot{width:6px;height:6px;border-radius:50%;background:currentColor}
.p-live{color:var(--gr);border-color:rgba(48,209,88,.3);background:var(--gr3)}
.p-live .dot{animation:pd 1.5s ease-in-out infinite}
@keyframes pd{0%,100%{transform:scale(1);box-shadow:0 0 0 0 currentColor}
  50%{transform:scale(1.2);box-shadow:0 0 0 4px transparent}}
.p-block{color:var(--rd);border-color:rgba(255,69,58,.3);background:var(--rd3)}
.p-idle{color:var(--am);border-color:rgba(255,159,10,.3);background:var(--am3)}
.p-pause{color:var(--pu);border-color:rgba(191,90,242,.3);background:var(--pu3)}
.p-off{color:var(--t3);border-color:var(--br);background:var(--c1)}
.clk{font-family:var(--mono);font-size:.71rem;color:var(--t3);min-width:7.5rem;text-align:right}
/* settings btn */
.cfg-btn{
  display:flex;align-items:center;gap:.4rem;
  background:var(--c1);border:1px solid var(--br);color:var(--t2);
  font-size:.72rem;font-weight:500;padding:.28rem .8rem;border-radius:var(--r3);
  cursor:pointer;transition:all .3s var(--ease);
}
.cfg-btn:hover{background:var(--c2);color:var(--t1);border-color:var(--br2)}

/* ── KPI GRID ── */
.kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem;margin-bottom:1rem}
@media(max-width:900px){.kpi-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:500px){.kpi-grid{grid-template-columns:1fr}}
.kpi{
  position:relative;overflow:hidden;
  background:var(--c1);border:1px solid var(--br);border-radius:var(--r);
  padding:1.3rem 1.4rem 1.1rem;cursor:default;
  transition:transform .45s var(--sp),box-shadow .35s var(--ease),border-color .3s;
}
.kpi::after{content:'';position:absolute;top:0;left:0;right:0;height:1px;
  background:linear-gradient(90deg,transparent,rgba(255,255,255,.1),rgba(255,255,255,.18),rgba(255,255,255,.1),transparent)}
.kpi:hover{transform:translateY(-5px) scale(1.015);
  box-shadow:0 24px 64px rgba(0,0,0,.55),0 8px 20px rgba(0,0,0,.3);border-color:var(--br2)}
.ka{position:absolute;top:0;left:1.4rem;right:1.4rem;height:2px;border-radius:0 0 4px 4px;
  transition:background .5s var(--ease),box-shadow .5s var(--ease)}
.c-gr .ka{background:var(--gr);box-shadow:0 0 16px rgba(48,209,88,.5)}
.c-rd .ka{background:var(--rd);box-shadow:0 0 16px rgba(255,69,58,.5)}
.c-am .ka{background:var(--am);box-shadow:0 0 16px rgba(255,159,10,.5)}
.c-bl .ka{background:var(--bl);box-shadow:0 0 16px rgba(10,132,255,.5)}
.kpi-lbl{font-size:.65rem;color:var(--t3);text-transform:uppercase;
  letter-spacing:.12em;font-weight:500;margin-bottom:.55rem}
.kpi-val{font-size:1.85rem;font-weight:700;font-family:var(--mono);
  letter-spacing:-.04em;line-height:1;color:var(--t1);
  transition:color .4s var(--ease);margin-bottom:.55rem}
.kpi-sub{font-size:.71rem;color:var(--t2);display:flex;align-items:center;gap:.4rem;flex-wrap:wrap}
.badge{font-size:.64rem;font-weight:600;padding:.12rem .45rem;
  border-radius:var(--r3);font-family:var(--mono);transition:all .3s var(--ease)}
.b-pos{background:var(--gr2);color:var(--gr)}
.b-neg{background:var(--rd2);color:var(--rd)}
.b-neu{background:var(--c2);color:var(--t2)}

/* ── CHARTS ── */
.chart-row{display:grid;grid-template-columns:2fr 1fr;gap:1rem;margin-bottom:1rem}
@media(max-width:800px){.chart-row{grid-template-columns:1fr}}
.chart-card{
  background:var(--c1);border:1px solid var(--br);border-radius:var(--r);
  padding:1.1rem 1.4rem;
  transition:transform .4s var(--sp),box-shadow .3s var(--ease);
}
.chart-card:hover{transform:translateY(-3px);box-shadow:0 16px 48px rgba(0,0,0,.45)}
.chart-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem}
.chart-ttl{font-size:.68rem;color:var(--t3);text-transform:uppercase;letter-spacing:.12em;font-weight:500}
.chart-meta{font-size:.68rem;color:var(--t3);font-family:var(--mono)}
.chart-wrap{position:relative;height:160px}
.chart-wrap-sm{position:relative;height:160px}

/* ── STATS ROW ── */
.stats-row{display:grid;grid-template-columns:repeat(5,1fr);gap:.75rem;margin-bottom:1rem}
@media(max-width:900px){.stats-row{grid-template-columns:repeat(3,1fr)}}
@media(max-width:500px){.stats-row{grid-template-columns:repeat(2,1fr)}}
.stat{
  background:var(--c1);border:1px solid var(--br);border-radius:var(--r2);
  padding:.85rem 1rem;text-align:center;
  transition:transform .35s var(--sp),box-shadow .3s var(--ease);cursor:default;
}
.stat:hover{transform:translateY(-3px);box-shadow:0 12px 36px rgba(0,0,0,.4)}
.stat-lbl{font-size:.62rem;color:var(--t3);text-transform:uppercase;letter-spacing:.1em;margin-bottom:.4rem}
.stat-val{font-size:1.4rem;font-weight:700;font-family:var(--mono);letter-spacing:-.03em;color:var(--t1)}
.stat-sub{font-size:.62rem;color:var(--t3);margin-top:.2rem}

/* ── GAUGES ── */
.gauge-row{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem}
@media(max-width:700px){.gauge-row{grid-template-columns:1fr}}
.gauge{background:var(--c1);border:1px solid var(--br);border-radius:var(--r);
  padding:1.1rem 1.4rem;transition:transform .4s var(--sp),box-shadow .3s var(--ease)}
.gauge:hover{transform:translateY(-3px);box-shadow:0 16px 48px rgba(0,0,0,.45)}
.gauge-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:.8rem}
.gauge-lbl{font-size:.65rem;color:var(--t3);text-transform:uppercase;letter-spacing:.12em;font-weight:500}
.gauge-val{font-size:.75rem;color:var(--t1);font-family:var(--mono);font-weight:500}
.track{height:5px;background:rgba(255,255,255,.06);border-radius:9999px;position:relative;overflow:visible}
.fill{height:100%;border-radius:9999px;position:relative;
  transition:width .9s cubic-bezier(.16,1,.3,1),background .5s var(--ease)}
.fill::after{content:'';position:absolute;right:0;top:50%;transform:translateY(-50%);
  width:10px;height:10px;border-radius:50%;transition:background .5s,box-shadow .5s}
.f-g{background:linear-gradient(90deg,rgba(48,209,88,.25),var(--gr))}
.f-g::after{background:var(--gr);box-shadow:0 0 10px var(--gr),0 0 20px rgba(48,209,88,.4)}
.f-a{background:linear-gradient(90deg,rgba(255,159,10,.25),var(--am))}
.f-a::after{background:var(--am);box-shadow:0 0 10px var(--am),0 0 20px rgba(255,159,10,.4)}
.f-r{background:linear-gradient(90deg,rgba(255,69,58,.25),var(--rd))}
.f-r::after{background:var(--rd);box-shadow:0 0 10px var(--rd),0 0 20px rgba(255,69,58,.4)}
.gauge-ftr{display:flex;justify-content:space-between;margin-top:.55rem;
  font-size:.66rem;color:var(--t3);font-family:var(--mono)}

/* ── INFO CARDS ── */
.info-row{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem}
@media(max-width:700px){.info-row{grid-template-columns:1fr}}
.icard{background:var(--c1);border:1px solid var(--br);border-radius:var(--r);
  padding:1.1rem 1.4rem;display:flex;gap:1rem;align-items:center;
  transition:transform .4s var(--sp),box-shadow .3s var(--ease),border-color .3s}
.icard:hover{transform:translateY(-3px);box-shadow:0 16px 48px rgba(0,0,0,.45);border-color:var(--br2)}
.ind{width:44px;height:44px;border-radius:50%;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;font-size:1.15rem;
  border:1.5px solid var(--br);transition:all .5s var(--ease)}
.i-none{background:rgba(255,255,255,.03)}
.i-ok{background:rgba(48,209,88,.1);border-color:rgba(48,209,88,.3);box-shadow:0 0 20px rgba(48,209,88,.2)}
.i-warn{background:rgba(255,159,10,.1);border-color:rgba(255,159,10,.3);
  animation:ra .85s ease-in-out infinite}
.i-blk{background:rgba(255,69,58,.1);border-color:rgba(255,69,58,.3);
  animation:rr .65s ease-in-out infinite}
@keyframes ra{0%,100%{box-shadow:0 0 0 0 rgba(255,159,10,.4)}60%{box-shadow:0 0 0 9px rgba(255,159,10,0)}}
@keyframes rr{0%,100%{box-shadow:0 0 0 0 rgba(255,69,58,.5)}60%{box-shadow:0 0 0 11px rgba(255,69,58,0)}}
.itype{font-size:.63rem;color:var(--t3);text-transform:uppercase;letter-spacing:.12em;font-weight:500;margin-bottom:.3rem}
.imain{font-size:.875rem;font-weight:600;transition:color .4s}
.isub{font-size:.71rem;color:var(--t2);margin-top:.18rem}

/* ── PROBABILITY SECTION ── */
.prob-row{display:grid;grid-template-columns:1fr 1fr 1fr;gap:1rem;margin-bottom:1rem}
@media(max-width:900px){.prob-row{grid-template-columns:1fr 1fr}}
@media(max-width:560px){.prob-row{grid-template-columns:1fr}}
.prob-card{background:var(--c1);border:1px solid var(--br);border-radius:var(--r);
  padding:1.25rem 1.4rem;transition:transform .4s var(--sp),box-shadow .3s var(--ease),border-color .3s;cursor:default}
.prob-card:hover{transform:translateY(-4px);box-shadow:0 16px 48px rgba(0,0,0,.45);border-color:var(--br2)}
.prob-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem}
.prob-ttl{font-size:.65rem;color:var(--t3);text-transform:uppercase;letter-spacing:.12em;font-weight:500}
.prob-live{display:flex;align-items:center;gap:.35rem;font-size:.64rem;color:var(--t3);font-family:var(--mono)}
.pulse-dot{width:5px;height:5px;border-radius:50%;background:var(--gr);animation:pd 1.5s ease-in-out infinite}
/* Arc gauge */
.arc-wrap{display:flex;justify-content:center;align-items:center;margin-bottom:1rem;position:relative}
.arc-svg{overflow:visible}
.arc-bg{fill:none;stroke:rgba(255,255,255,.06);stroke-linecap:round}
.arc-fill-b{fill:none;stroke:var(--gr);stroke-linecap:round;
  transition:stroke-dashoffset 1s cubic-bezier(.16,1,.3,1),stroke .5s}
.arc-fill-s{fill:none;stroke:var(--rd);stroke-linecap:round;
  transition:stroke-dashoffset 1s cubic-bezier(.16,1,.3,1),stroke .5s}
.arc-center{position:absolute;text-align:center;pointer-events:none}
.arc-pct{font-size:2rem;font-weight:800;font-family:var(--mono);letter-spacing:-.05em;line-height:1}
.arc-lbl{font-size:.62rem;color:var(--t3);text-transform:uppercase;letter-spacing:.1em;margin-top:.2rem}
.arc-dir{font-size:.68rem;font-weight:700;letter-spacing:.08em;margin-top:.3rem}
.arc-bull{color:var(--gr)}.arc-bear{color:var(--rd)}.arc-neu{color:var(--t3)}
/* Condition breakdown */
.cond-grid{display:flex;flex-direction:column;gap:.45rem}
.cond-row{display:flex;align-items:center;justify-content:space-between;
  padding:.32rem .6rem;border-radius:var(--r3);
  transition:background .3s var(--ease),transform .25s var(--sp)}
.cond-row.on{background:rgba(48,209,88,.07)}
.cond-row.on-s{background:rgba(255,69,58,.07)}
.cond-row:hover{transform:translateX(2px)}
.cond-l{display:flex;align-items:center;gap:.55rem}
.cond-icon{font-size:.85rem;width:1.1rem;text-align:center;flex-shrink:0}
.cond-name{font-size:.8rem;font-weight:500}
.cond-name-sub{font-size:.64rem;color:var(--t3);margin-left:.3rem}
.cond-badge{font-size:.65rem;font-weight:700;padding:.1rem .42rem;
  border-radius:6px;font-family:var(--mono);transition:all .35s var(--ease)}
.cb-on-b{background:var(--gr2);color:var(--gr);box-shadow:0 0 8px rgba(48,209,88,.2)}
.cb-on-s{background:var(--rd2);color:var(--rd);box-shadow:0 0 8px rgba(255,69,58,.2)}
.cb-off{background:rgba(255,255,255,.04);color:var(--t4)}
.cond-weight{font-size:.6rem;color:var(--t4);text-transform:uppercase;letter-spacing:.08em}
/* Countdown */
.cdown-row{display:flex;align-items:center;gap:.6rem;
  padding:.55rem .6rem;border-radius:var(--r3);background:rgba(255,255,255,.03);margin-top:.5rem}
.cdown-lbl{font-size:.66rem;color:var(--t3)}
.cdown-val{font-size:.85rem;font-weight:700;font-family:var(--mono);
  color:var(--t1);min-width:3rem;transition:color .3s}
.cdown-bar{flex:1;height:3px;background:rgba(255,255,255,.06);border-radius:9999px;overflow:hidden}
.cdown-fill{height:100%;background:var(--bl);border-radius:9999px;
  transition:width .9s linear,background .3s}
/* TradingView */
.tv-card{background:var(--c1);border:1px solid var(--br);border-radius:var(--r);
  overflow:hidden;margin-bottom:1rem;
  transition:transform .4s var(--sp),box-shadow .3s var(--ease)}
.tv-card:hover{transform:translateY(-3px);box-shadow:0 16px 48px rgba(0,0,0,.45)}
.tv-hdr{display:flex;justify-content:space-between;align-items:center;
  padding:.85rem 1.4rem;border-bottom:1px solid var(--br)}
.tv-ttl{font-size:.65rem;color:var(--t3);text-transform:uppercase;letter-spacing:.12em;font-weight:500}
.tv-sym{font-family:var(--mono);font-size:.72rem;color:var(--t1);font-weight:600}
.tv-signal-banner{display:none;background:rgba(10,132,255,.1);border-bottom:1px solid rgba(10,132,255,.2);
  padding:.6rem 1.4rem;font-size:.75rem;color:var(--bl);font-weight:600}
.tv-signal-banner.show{display:flex;align-items:center;gap:.5rem}
/* ── SIGNAL PANEL ── */
.sig-card{background:var(--c1);border:1px solid var(--br);border-radius:var(--r);
  padding:1.3rem 1.5rem;margin-bottom:1rem;
  transition:transform .4s var(--sp),box-shadow .3s var(--ease),border-color .3s}
.sig-card:hover{transform:translateY(-3px);box-shadow:0 16px 48px rgba(0,0,0,.45);border-color:var(--br2)}
.sig-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:1.2rem}
.sig-title{font-size:.65rem;color:var(--t3);text-transform:uppercase;letter-spacing:.12em;font-weight:500}
.sig-badge{font-size:.71rem;font-weight:600;padding:.2rem .65rem;
  border-radius:var(--r3);border:1px solid;transition:all .35s var(--ease)}
.sl-long{color:var(--gr);border-color:rgba(48,209,88,.3);background:var(--gr3)}
.sl-short{color:var(--rd);border-color:rgba(255,69,58,.3);background:var(--rd3)}
.sl-none{color:var(--t3);border-color:var(--br);background:transparent}
.sig-body{display:flex;align-items:stretch}
.sig-side{flex:1;padding:.3rem 1.5rem}
.sig-side:first-child{padding-left:0}
.sig-side:last-child{padding-right:0}
.sig-sep{width:1px;background:var(--br);margin:.3rem 0}
.sig-dir{font-size:.68rem;font-weight:700;letter-spacing:.12em;margin-bottom:.7rem;display:block}
.sd-b{color:var(--gr)}.sd-s{color:var(--rd)}
.sig-row{display:flex;align-items:center;gap:1.1rem;margin-bottom:.7rem}
.sig-n{font-size:3.2rem;font-weight:700;font-family:var(--mono);
  line-height:1;letter-spacing:-.05em;min-width:2.8rem;transition:all .5s var(--sp)}
.sn-b{color:var(--gr)}.sn-s{color:var(--rd)}
.sn-off{opacity:.12}
.sn-b.on{text-shadow:0 0 32px rgba(48,209,88,.55),0 0 64px rgba(48,209,88,.2)}
.sn-s.on{text-shadow:0 0 32px rgba(255,69,58,.55),0 0 64px rgba(255,69,58,.2)}
.dots{display:flex;gap:7px;align-items:center;flex-wrap:wrap}
.d{width:11px;height:11px;border-radius:50%;background:rgba(255,255,255,.09);
  transition:all .45s var(--sp);flex-shrink:0}
.d.ob{background:var(--gr);box-shadow:0 0 8px rgba(48,209,88,.8),0 0 18px rgba(48,209,88,.3);transform:scale(1.25)}
.d.os{background:var(--rd);box-shadow:0 0 8px rgba(255,69,58,.8),0 0 18px rgba(255,69,58,.3);transform:scale(1.25)}
.sig-thr{font-size:.66rem;color:var(--t3);font-family:var(--mono)}

/* ── TABLES ── */
.tbl-card{background:var(--c1);border:1px solid var(--br);border-radius:var(--r);
  padding:1.1rem 1.4rem;margin-bottom:1rem;overflow-x:auto}
.tbl-hdr{display:flex;align-items:center;gap:.65rem;margin-bottom:.9rem}
.tbl-ttl{font-size:.68rem;color:var(--t3);text-transform:uppercase;letter-spacing:.12em;font-weight:500}
.tbl-n{background:var(--c2);color:var(--t2);font-size:.64rem;font-weight:600;
  padding:.11rem .48rem;border-radius:9999px;font-family:var(--mono)}
table{width:100%;border-collapse:collapse}
th{font-size:.63rem;color:var(--t3);text-transform:uppercase;letter-spacing:.12em;font-weight:500;
  text-align:left;padding:.28rem .7rem .55rem;border-bottom:1px solid var(--br)}
td{font-size:.79rem;padding:.52rem .7rem;border-bottom:1px solid rgba(255,255,255,.035);
  font-family:var(--mono);color:var(--t2);transition:background .2s var(--ease),color .2s var(--ease)}
tr:hover td{background:rgba(255,255,255,.035);color:var(--t1)}
tr:last-child td{border-bottom:none}
.empty td{color:var(--t3);text-align:center;padding:1.5rem;font-family:var(--font);font-size:.82rem}
.dl{color:var(--gr)!important;font-weight:600}.ds{color:var(--rd)!important;font-weight:600}
.pp{color:var(--gr)!important}.pn{color:var(--rd)!important}
.tk{background:rgba(255,255,255,.06);color:var(--t1);padding:.1rem .42rem;border-radius:6px;font-size:.71rem}

/* ── LOG ── */
.log-card{background:rgba(0,0,0,.7);border:1px solid var(--br);
  border-radius:var(--r);padding:1.1rem 1.4rem;margin-bottom:1rem}
.log-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:.85rem}
.log-ttl{font-size:.68rem;color:var(--t3);text-transform:uppercase;letter-spacing:.12em;font-weight:500;
  display:flex;align-items:center;gap:.55rem}
.log-live{width:7px;height:7px;border-radius:50%;background:var(--gr);
  box-shadow:0 0 8px var(--gr);animation:pd 1.5s ease-in-out infinite}
.log-ts{font-size:.66rem;color:var(--t3);font-family:var(--mono)}
.log-body{display:flex;flex-direction:column;gap:2px}
.ll{display:flex;gap:.9rem;padding:.26rem 0;
  border-bottom:1px solid rgba(255,255,255,.025);animation:up .28s var(--fast) both}
.ll:last-child{border-bottom:none}
@keyframes up{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:none}}
.lt{font-family:var(--mono);font-size:.67rem;color:var(--t3);flex-shrink:0;min-width:5.5rem}
.lm{font-family:var(--mono);font-size:.74rem;color:var(--t2)}
.ll:last-child .lm{color:var(--t1)}

/* ── FOOTER ── */
.footer{display:flex;justify-content:space-between;align-items:center;
  padding:.9rem 0 0;border-top:1px solid var(--br);
  font-size:.66rem;color:var(--t3);font-family:var(--mono)}

/* ── SETTINGS PANEL ── */
.overlay{
  position:fixed;inset:0;z-index:300;
  background:rgba(0,0,0,.5);backdrop-filter:blur(4px);
  opacity:0;pointer-events:none;transition:opacity .35s var(--ease);
}
.overlay.open{opacity:1;pointer-events:all}
.panel{
  position:fixed;top:0;right:0;bottom:0;z-index:301;
  width:380px;max-width:95vw;
  background:rgba(10,10,10,.96);backdrop-filter:blur(24px);
  border-left:1px solid var(--br2);
  transform:translateX(100%);
  transition:transform .45s var(--sp);
  overflow-y:auto;padding:1.5rem;display:flex;flex-direction:column;gap:1.5rem;
}
.panel.open{transform:translateX(0)}
.panel-hdr{display:flex;justify-content:space-between;align-items:center}
.panel-ttl{font-size:1rem;font-weight:700;letter-spacing:-.01em}
.panel-close{
  width:30px;height:30px;border-radius:50%;border:1px solid var(--br);
  background:var(--c1);color:var(--t2);cursor:pointer;font-size:1.1rem;
  display:flex;align-items:center;justify-content:center;
  transition:all .25s var(--ease);
}
.panel-close:hover{background:var(--c2);color:var(--t1);border-color:var(--br2)}
.psec{display:flex;flex-direction:column;gap:.85rem}
.psec-ttl{font-size:.65rem;color:var(--t3);text-transform:uppercase;
  letter-spacing:.12em;font-weight:500;padding-bottom:.6rem;border-bottom:1px solid var(--br)}
/* Toggle switch */
.toggle-row{display:flex;justify-content:space-between;align-items:center;gap:1rem}
.toggle-lbl{font-size:.85rem;font-weight:500}
.toggle-sub{font-size:.7rem;color:var(--t2);margin-top:.1rem}
.sw{position:relative;width:44px;height:26px;flex-shrink:0}
.sw input{opacity:0;width:0;height:0}
.sw-track{
  position:absolute;inset:0;border-radius:9999px;
  background:rgba(255,255,255,.1);border:1px solid var(--br);
  cursor:pointer;transition:all .3s var(--ease);
}
.sw-track::after{
  content:'';position:absolute;top:3px;left:3px;
  width:18px;height:18px;border-radius:50%;
  background:rgba(255,255,255,.5);transition:all .35s var(--sp);
}
.sw input:checked+.sw-track{background:var(--gr);border-color:var(--gr)}
.sw input:checked+.sw-track::after{transform:translateX(18px);background:#fff}
/* Slider */
.slider-row{display:flex;flex-direction:column;gap:.5rem}
.slider-header{display:flex;justify-content:space-between;align-items:baseline}
.slider-lbl{font-size:.85rem;font-weight:500}
.slider-val{font-size:1.2rem;font-weight:700;font-family:var(--mono);color:var(--gr)}
.slider-sub{font-size:.7rem;color:var(--t2)}
input[type=range]{
  width:100%;-webkit-appearance:none;appearance:none;
  height:5px;border-radius:9999px;
  background:rgba(255,255,255,.1);outline:none;cursor:pointer;
  transition:background .3s;
}
input[type=range]::-webkit-slider-thumb{
  -webkit-appearance:none;appearance:none;
  width:20px;height:20px;border-radius:50%;
  background:#fff;cursor:pointer;
  box-shadow:0 2px 8px rgba(0,0,0,.4);
  transition:transform .2s var(--sp),box-shadow .2s;
}
input[type=range]::-webkit-slider-thumb:hover{transform:scale(1.15);box-shadow:0 4px 16px rgba(0,0,0,.5)}
input[type=range]::-moz-range-thumb{
  width:20px;height:20px;border-radius:50%;border:none;
  background:#fff;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.4);
}
/* Calc */
.calc-grid{display:grid;grid-template-columns:1fr 1fr;gap:.75rem}
.calc-field{display:flex;flex-direction:column;gap:.4rem}
.calc-lbl{font-size:.67rem;color:var(--t3);text-transform:uppercase;letter-spacing:.1em}
.calc-input{
  background:var(--c2);border:1px solid var(--br);border-radius:var(--r3);
  color:var(--t1);font-family:var(--mono);font-size:.9rem;font-weight:600;
  padding:.55rem .75rem;outline:none;
  transition:border-color .25s var(--ease),box-shadow .25s;
  -webkit-appearance:none;appearance:none;
}
.calc-input:focus{border-color:rgba(255,255,255,.3);box-shadow:0 0 0 3px rgba(255,255,255,.06)}
.calc-result{
  grid-column:1/-1;background:rgba(48,209,88,.07);
  border:1px solid rgba(48,209,88,.2);border-radius:var(--r3);
  padding:.9rem 1rem;display:flex;flex-direction:column;gap:.3rem;
}
.calc-lot{font-size:1.8rem;font-weight:700;font-family:var(--mono);
  color:var(--gr);letter-spacing:-.04em}
.calc-lot-sub{font-size:.72rem;color:var(--t2)}
/* Info rows */
.info-kv{display:flex;justify-content:space-between;align-items:center;
  padding:.55rem 0;border-bottom:1px solid var(--br);font-size:.82rem}
.info-kv:last-child{border-bottom:none}
.info-k{color:var(--t2)}
.info-v{font-family:var(--mono);font-weight:600}
/* Apply button */
.apply-btn{
  width:100%;padding:.7rem;border-radius:var(--r3);border:none;
  background:var(--gr);color:#000;font-weight:700;font-size:.85rem;
  cursor:pointer;transition:all .3s var(--sp);letter-spacing:.02em;
}
.apply-btn:hover{transform:scale(1.02);box-shadow:0 8px 24px rgba(48,209,88,.35)}
.apply-btn:active{transform:scale(.98)}
.apply-btn.paused-apply{background:var(--rd)}
.status-msg{font-size:.72rem;color:var(--gr);text-align:center;
  min-height:1rem;transition:opacity .3s}
</style>
</head>
<body>
<div class="app">
<div class="offline" id="ban">⚠ Bot desconectado — sin datos recientes</div>

<!-- HEADER -->
<header class="hdr">
  <div class="hdr-l">
    <span class="logo">SMC<span class="logo-dot"></span>FTMO</span>
    <span class="vd"></span>
    <span class="sym" id="sym">—</span>
    <span class="tf" id="tf"></span>
    <span class="dry" id="dry">DRY RUN</span>
  </div>
  <div class="hdr-r">
    <button class="cfg-btn" onclick="openPanel()">⚙ Ajustes</button>
    <div class="pill p-off" id="pill"><span class="dot"></span><span id="pill-txt">Conectando</span></div>
    <span class="clk" id="clk">—</span>
  </div>
</header>

<!-- KPI GRID -->
<div class="kpi-grid">
  <div class="kpi c-bl" id="k-bal"><div class="ka"></div>
    <div class="kpi-lbl">Balance MT5</div>
    <div class="kpi-val" id="bal">—</div>
    <div class="kpi-sub">Referencia FTMO</div>
  </div>
  <div class="kpi c-gr" id="k-eq"><div class="ka"></div>
    <div class="kpi-lbl">Equity actual</div>
    <div class="kpi-val" id="eq">—</div>
    <div class="kpi-sub"><span class="badge b-neu" id="eq-d">—</span><span id="eq-s"></span></div>
  </div>
  <div class="kpi c-gr" id="k-pnl"><div class="ka"></div>
    <div class="kpi-lbl">P&amp;L hoy</div>
    <div class="kpi-val" id="pnl">—</div>
    <div class="kpi-sub">Límite: <span id="pnl-l">—</span></div>
  </div>
  <div class="kpi c-bl" id="k-pos"><div class="ka"></div>
    <div class="kpi-lbl">Posiciones abiertas</div>
    <div class="kpi-val" id="pos-n">0 / 1</div>
    <div class="kpi-sub">Ciclo <span class="badge b-neu" id="cyc">#0</span></div>
  </div>
</div>

<!-- CHARTS ROW -->
<div class="chart-row">
  <div class="chart-card">
    <div class="chart-hdr">
      <span class="chart-ttl">Curva de equity</span>
      <span class="chart-meta" id="eq-range">—</span>
    </div>
    <div class="chart-wrap"><canvas id="eq-chart"></canvas></div>
  </div>
  <div class="chart-card">
    <div class="chart-hdr">
      <span class="chart-ttl">P&amp;L por operación</span>
      <span class="chart-meta" id="pnl-meta">—</span>
    </div>
    <div class="chart-wrap-sm"><canvas id="pnl-chart"></canvas></div>
  </div>
</div>

<!-- STATS ROW -->
<div class="stats-row">
  <div class="stat"><div class="stat-lbl">Win Rate</div><div class="stat-val" id="st-wr">—</div><div class="stat-sub" id="st-wr-s">—</div></div>
  <div class="stat"><div class="stat-lbl">Profit Factor</div><div class="stat-val" id="st-pf">—</div><div class="stat-sub">bruto</div></div>
  <div class="stat"><div class="stat-lbl">Avg Win</div><div class="stat-val" id="st-aw" style="color:var(--gr)">—</div><div class="stat-sub">por operación</div></div>
  <div class="stat"><div class="stat-lbl">Avg Loss</div><div class="stat-val" id="st-al" style="color:var(--rd)">—</div><div class="stat-sub">por operación</div></div>
  <div class="stat"><div class="stat-lbl">Mejor / Peor</div><div class="stat-val" id="st-bw" style="font-size:1rem">— / —</div><div class="stat-sub">trades cerrados</div></div>
</div>

<!-- GAUGES -->
<div class="gauge-row">
  <div class="gauge">
    <div class="gauge-hdr">
      <span class="gauge-lbl">Suelo FTMO — DD máx. 10%</span>
      <span class="gauge-val" id="ftmo-v">—</span>
    </div>
    <div class="track"><div class="fill f-g" id="ftmo-f" style="width:100%"></div></div>
    <div class="gauge-ftr"><span id="ftmo-l">—</span><span id="ftmo-r">—</span></div>
  </div>
  <div class="gauge">
    <div class="gauge-hdr">
      <span class="gauge-lbl">Stop diario — Límite conservador</span>
      <span class="gauge-val" id="day-v">—</span>
    </div>
    <div class="track"><div class="fill f-g" id="day-f" style="width:0%"></div></div>
    <div class="gauge-ftr"><span id="day-l">—</span><span id="day-r">—</span></div>
  </div>
</div>

<!-- INFO ROW -->
<div class="info-row">
  <div class="icard">
    <div class="ind i-none" id="n-ind">📰</div>
    <div><div class="itype">Forex Factory</div>
      <div class="imain" id="n-main">—</div>
      <div class="isub" id="n-sub">—</div></div>
  </div>
  <div class="icard">
    <div class="ind i-none" id="s-ind">🕐</div>
    <div><div class="itype">Sesión de mercado</div>
      <div class="imain" id="s-main">—</div>
      <div class="isub">Londres 10:00–18:00 · NY 15:30–00:00 CEST</div></div>
  </div>
</div>

<!-- SIGNAL PANEL -->
<div class="sig-card">
  <div class="sig-hdr">
    <span class="sig-title">Análisis SMC — Confluencia de señales</span>
    <span class="sig-badge sl-none" id="sig-b">Sin señal</span>
  </div>
  <div class="sig-body">
    <div class="sig-side">
      <span class="sig-dir sd-b">▲ LONG</span>
      <div class="sig-row">
        <span class="sig-n sn-b sn-off" id="sc-b">0</span>
        <div class="dots" id="d-b"><span class="d"></span><span class="d"></span><span class="d"></span><span class="d"></span><span class="d"></span><span class="d"></span><span class="d"></span></div>
      </div>
      <span class="sig-thr" id="th-b">0 / 7 condiciones</span>
    </div>
    <div class="sig-sep"></div>
    <div class="sig-side">
      <span class="sig-dir sd-s">▼ SHORT</span>
      <div class="sig-row">
        <span class="sig-n sn-s sn-off" id="sc-s">0</span>
        <div class="dots" id="d-s"><span class="d"></span><span class="d"></span><span class="d"></span><span class="d"></span><span class="d"></span><span class="d"></span><span class="d"></span></div>
      </div>
      <span class="sig-thr" id="th-s">0 / 7 condiciones</span>
    </div>
  </div>
</div>

<!-- PROBABILITY + CONDITIONS + TV -->
<div class="prob-row">

  <!-- Bull probability arc -->
  <div class="prob-card">
    <div class="prob-hdr">
      <span class="prob-ttl">Prob. alcista ▲</span>
      <span class="prob-live"><span class="pulse-dot"></span>live</span>
    </div>
    <div class="arc-wrap" style="height:110px">
      <svg class="arc-svg" width="130" height="110" viewBox="-65 -65 130 90">
        <path class="arc-bg" d="M -50 0 A 50 50 0 0 1 50 0" stroke-width="7"/>
        <path class="arc-fill-b" id="arc-bull" d="M -50 0 A 50 50 0 0 1 50 0" stroke-width="7"
          stroke-dasharray="157" stroke-dashoffset="157"/>
      </svg>
      <div class="arc-center">
        <div class="arc-pct arc-bull" id="prob-bull-pct">0%</div>
        <div class="arc-lbl">LONG</div>
      </div>
    </div>
    <div class="cond-grid" id="conds-bull"></div>
  </div>

  <!-- Bear probability arc -->
  <div class="prob-card">
    <div class="prob-hdr">
      <span class="prob-ttl">Prob. bajista ▼</span>
      <span class="prob-live"><span class="pulse-dot" style="background:var(--rd)"></span>live</span>
    </div>
    <div class="arc-wrap" style="height:110px">
      <svg class="arc-svg" width="130" height="110" viewBox="-65 -65 130 90">
        <path class="arc-bg" d="M -50 0 A 50 50 0 0 1 50 0" stroke-width="7"/>
        <path class="arc-fill-s" id="arc-bear" d="M -50 0 A 50 50 0 0 1 50 0" stroke-width="7"
          stroke-dasharray="157" stroke-dashoffset="157"/>
      </svg>
      <div class="arc-center">
        <div class="arc-pct arc-bear" id="prob-bear-pct">0%</div>
        <div class="arc-lbl">SHORT</div>
      </div>
    </div>
    <div class="cond-grid" id="conds-bear"></div>
  </div>

  <!-- Countdown + TV signal -->
  <div class="prob-card" style="display:flex;flex-direction:column;gap:.75rem">
    <div class="prob-hdr">
      <span class="prob-ttl">Próxima vela M5</span>
    </div>
    <div style="text-align:center;padding:.5rem 0">
      <div style="font-size:2.8rem;font-weight:800;font-family:var(--mono);letter-spacing:-.04em;color:var(--t1)" id="cd-display">5:00</div>
      <div style="font-size:.66rem;color:var(--t3);margin-top:.3rem">hasta próxima señal</div>
    </div>
    <div class="cdown-bar"><div class="cdown-fill" id="cd-fill" style="width:0%"></div></div>
    <div style="border-top:1px solid var(--br);padding-top:.75rem">
      <div class="prob-ttl" style="margin-bottom:.5rem">TradingView</div>
      <div id="tv-signal-box" style="background:rgba(255,255,255,.03);border:1px solid var(--br);
        border-radius:var(--r3);padding:.6rem .8rem;font-size:.75rem;color:var(--t3);
        font-family:var(--mono);min-height:2.5rem;transition:all .4s var(--ease)">
        Sin señal recibida
      </div>
      <div style="font-size:.62rem;color:var(--t4);margin-top:.4rem">
        Webhook: <code style="color:var(--bl);font-size:.62rem">/webhook</code>
      </div>
    </div>
    <div style="border-top:1px solid var(--br);padding-top:.75rem">
      <div class="prob-ttl" style="margin-bottom:.4rem">Dirección dominante</div>
      <div id="dominant-dir" style="font-size:1.3rem;font-weight:800;font-family:var(--mono);
        text-align:center;padding:.5rem 0;transition:all .5s var(--sp)">—</div>
    </div>
  </div>
</div>

<!-- TRADINGVIEW WIDGET -->
<div class="tv-card">
  <div class="tv-hdr">
    <span class="tv-ttl">Gráfico en vivo — TradingView</span>
    <span class="tv-sym" id="tv-sym-lbl">EURUSD · M5</span>
  </div>
  <div id="tv-signal-banner" class="tv-signal-banner"></div>
  <div class="tradingview-widget-container" style="height:420px">
    <div id="tradingview_chart" style="height:100%"></div>
    <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
    <script type="text/javascript">
    (function(){
      if(typeof TradingView==='undefined')return;
      new TradingView.widget({
        autosize:true,
        symbol:"FX:EURUSD",
        interval:"5",
        timezone:"Europe/Madrid",
        theme:"dark",
        style:"1",
        locale:"es",
        toolbar_bg:"#000000",
        enable_publishing:false,
        hide_side_toolbar:false,
        allow_symbol_change:true,
        container_id:"tradingview_chart",
        backgroundColor:"rgba(0,0,0,1)",
        gridColor:"rgba(255,255,255,0.04)",
        studies:["STD;RSI","STD;MACD"],
        show_popup_button:true,
        popup_width:"1000",
        popup_height:"650",
        withdateranges:true,
        save_image:false,
      });
    })();
    </script>
  </div>
</div>

<!-- POSITIONS -->
<div class="tbl-card">
  <div class="tbl-hdr"><span class="tbl-ttl">Posiciones abiertas</span><span class="tbl-n" id="pos-c">0</span></div>
  <table>
    <thead><tr><th>Ticket</th><th>Par</th><th>Dir</th><th>Lote</th><th>Entrada</th><th>SL</th><th>TP</th><th>P&amp;L</th></tr></thead>
    <tbody id="pos-b"><tr class="empty"><td colspan="8">Sin posiciones abiertas</td></tr></tbody>
  </table>
</div>

<!-- TRADES -->
<div class="tbl-card">
  <div class="tbl-hdr"><span class="tbl-ttl">Historial de operaciones</span><span class="tbl-n" id="tr-c">0</span></div>
  <table>
    <thead><tr><th>Hora</th><th>Par</th><th>Dir</th><th>P&amp;L</th><th>Resultado</th></tr></thead>
    <tbody id="tr-b"><tr class="empty"><td colspan="5">Sin operaciones registradas</td></tr></tbody>
  </table>
</div>

<!-- LOG -->
<div class="log-card">
  <div class="log-hdr">
    <span class="log-ttl"><span class="log-live"></span>Log en tiempo real</span>
    <span class="log-ts" id="log-ts">—</span>
  </div>
  <div class="log-body" id="log-b">
    <div class="ll"><span class="lt">—</span><span class="lm">Esperando datos del bot…</span></div>
  </div>
</div>

<div class="footer">
  <span>SMC·FTMO Command Center · cada 3s</span>
  <span id="ft">—</span>
</div>
</div><!-- /.app -->

<!-- SETTINGS OVERLAY + PANEL -->
<div class="overlay" id="overlay" onclick="closePanel()"></div>
<div class="panel" id="panel">
  <div class="panel-hdr">
    <span class="panel-ttl">⚙ Ajustes del bot</span>
    <button class="panel-close" onclick="closePanel()">✕</button>
  </div>

  <!-- Bot controls -->
  <div class="psec">
    <div class="psec-ttl">Control del bot</div>
    <div class="toggle-row">
      <div><div class="toggle-lbl">Pausa del bot</div>
        <div class="toggle-sub">El bot sigue corriendo pero no opera</div></div>
      <label class="sw"><input type="checkbox" id="sw-pause" onchange="togglePause(this)">
        <div class="sw-track"></div></label>
    </div>
    <div class="slider-row">
      <div class="slider-header">
        <span class="slider-lbl">Score mínimo SMC</span>
        <span class="slider-val" id="sc-val">5</span>
      </div>
      <input type="range" id="sc-slider" min="1" max="7" value="5"
        oninput="document.getElementById('sc-val').textContent=this.value"
        onchange="applyScore(this.value)">
      <div class="slider-sub" id="sc-desc">5 de 7 condiciones requeridas — conservador</div>
    </div>
    <div class="status-msg" id="ctl-msg"></div>
  </div>

  <!-- Risk calculator -->
  <div class="psec">
    <div class="psec-ttl">Calculadora de riesgo</div>
    <div class="calc-grid">
      <div class="calc-field">
        <span class="calc-lbl">Balance (EUR)</span>
        <input class="calc-input" type="number" id="c-bal" value="10000" oninput="calcLot()">
      </div>
      <div class="calc-field">
        <span class="calc-lbl">Riesgo %</span>
        <input class="calc-input" type="number" id="c-risk" value="0.5" step="0.1" oninput="calcLot()">
      </div>
      <div class="calc-field">
        <span class="calc-lbl">SL en pips</span>
        <input class="calc-input" type="number" id="c-sl" value="20" oninput="calcLot()">
      </div>
      <div class="calc-field">
        <span class="calc-lbl">Pip value (EUR)</span>
        <input class="calc-input" type="number" id="c-pv" value="10" step="0.5" oninput="calcLot()">
      </div>
      <div class="calc-result">
        <span class="calc-lot" id="c-lot">0.25</span>
        <span class="calc-lot-sub">lotes recomendados · <span id="c-eur">50.00 EUR</span> en riesgo · TP: <span id="c-tp">150.00 EUR</span></span>
      </div>
    </div>
  </div>

  <!-- Info FTMO -->
  <div class="psec">
    <div class="psec-ttl">Estado FTMO</div>
    <div class="info-kv"><span class="info-k">Balance inicial</span><span class="info-v" id="i-init">—</span></div>
    <div class="info-kv"><span class="info-k">Suelo DD</span><span class="info-v" style="color:var(--rd)" id="i-floor">—</span></div>
    <div class="info-kv"><span class="info-k">Stop diario</span><span class="info-v" style="color:var(--am)" id="i-daily">—</span></div>
    <div class="info-kv"><span class="info-k">Margen disponible</span><span class="info-v" id="i-margin">—</span></div>
    <div class="info-kv"><span class="info-k">Símbolo activo</span><span class="info-v" id="i-sym">—</span></div>
    <div class="info-kv"><span class="info-k">Ciclos ejecutados</span><span class="info-v" id="i-cyc">—</span></div>
  </div>
</div>

<script>
"use strict";
const $=id=>document.getElementById(id);
const clamp=(v,lo,hi)=>Math.min(hi,Math.max(lo,v));
const fmtN=(n,d=2)=>n==null||isNaN(n)?'—':Number(n).toLocaleString('es-ES',{minimumFractionDigits:d,maximumFractionDigits:d});
const fmtE=(n,sign=false)=>{
  if(n==null||isNaN(n))return'—';
  const p=n<0?'-':(sign&&n>0?'+':'');
  return p+Math.abs(n).toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+' EUR';
};

// ── Animated number counter ────────────────────────────────────────────────────
const _v={};
function animN(id,target,render){
  const el=$(id);if(!el)return;
  const prev=_v[id]??target;_v[id]=target;
  if(prev===target){el.textContent=render(target);return;}
  const dur=700,s=performance.now(),from=prev,to=target;
  (function step(now){
    const t=clamp((now-s)/dur,0,1),e=t<.5?4*t*t*t:(1-Math.pow(-2*t+2,3)/2);
    el.textContent=render(from+(to-from)*e);
    t<1?requestAnimationFrame(step):el.textContent=render(to);
  })(performance.now());
}

// ── Clock ──────────────────────────────────────────────────────────────────────
const tick=()=>{
  const n=new Date(),p=x=>String(x).padStart(2,'0');
  $('clk').textContent=p(n.getUTCHours())+':'+p(n.getUTCMinutes())+':'+p(n.getUTCSeconds())+' UTC';
};
setInterval(tick,1000);tick();

// ── Panel ─────────────────────────────────────────────────────────────────────
function openPanel(){$('overlay').classList.add('open');$('panel').classList.add('open')}
function closePanel(){$('overlay').classList.remove('open');$('panel').classList.remove('open')}
document.addEventListener('keydown',e=>{if(e.key==='Escape')closePanel()});

// ── Bot controls ──────────────────────────────────────────────────────────────
async function postControl(data){
  try{
    const r=await fetch('/api/control',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    return r.ok;
  }catch{return false;}
}
async function togglePause(el){
  const paused=el.checked;
  const ok=await postControl({paused});
  const msg=$('ctl-msg');
  if(ok){msg.textContent=paused?'⏸ Bot en pausa — no ejecutará órdenes':'▶ Bot reanudado';
    msg.style.color=paused?'var(--am)':'var(--gr)';
    setTimeout(()=>msg.textContent='',3000);}
  else{el.checked=!paused;msg.textContent='Error al comunicar con el bot';msg.style.color='var(--rd)';}
}
const SC_LABELS=['','Muy permisivo','Permisivo','Moderado bajo','Moderado',
  'Conservador','Estricto','Muy estricto'];
async function applyScore(v){
  const n=parseInt(v);
  const ok=await postControl({min_score_override:n});
  const msg=$('ctl-msg');
  $('sc-desc').textContent=n+' de 7 condiciones — '+SC_LABELS[n];
  if(ok){msg.textContent='✓ Score actualizado a '+n+'/7';msg.style.color='var(--gr)';
    setTimeout(()=>msg.textContent='',3000);}
  else{msg.textContent='Sin conexión con el bot';msg.style.color='var(--am)';}
}

// ── Risk calculator ───────────────────────────────────────────────────────────
function calcLot(){
  const bal=parseFloat($('c-bal').value)||0;
  const risk=parseFloat($('c-risk').value)||0;
  const sl=parseFloat($('c-sl').value)||0;
  const pv=parseFloat($('c-pv').value)||10;
  const rr=3.0;
  if(!sl||!pv){$('c-lot').textContent='—';return;}
  const riskEur=(bal*risk/100);
  const lot=riskEur/(sl*pv);
  const tp=riskEur*rr;
  $('c-lot').textContent=lot.toFixed(2);
  $('c-eur').textContent=fmtN(riskEur)+' EUR';
  $('c-tp').textContent=fmtN(tp)+' EUR';
}
calcLot();

// ── Chart.js setup ────────────────────────────────────────────────────────────
Chart.defaults.color='rgba(255,255,255,.28)';
Chart.defaults.borderColor='rgba(255,255,255,.055)';
Chart.defaults.font.family="var(--mono)";
Chart.defaults.font.size=10;

// Equity curve chart
const eqCtx=$('eq-chart').getContext('2d');
const eqGrad=eqCtx.createLinearGradient(0,0,0,160);
eqGrad.addColorStop(0,'rgba(48,209,88,.22)');
eqGrad.addColorStop(1,'rgba(48,209,88,0)');
const eqChart=new Chart(eqCtx,{
  type:'line',
  data:{labels:[],datasets:[{
    data:[],borderColor:'#30d158',backgroundColor:eqGrad,
    borderWidth:1.5,fill:true,tension:.4,
    pointRadius:0,pointHoverRadius:5,
    pointHoverBackgroundColor:'#30d158',pointHoverBorderColor:'#fff',pointHoverBorderWidth:2,
  }]},
  options:{
    animation:{duration:400,easing:'easeOutQuart'},
    responsive:true,maintainAspectRatio:false,
    plugins:{
      legend:{display:false},
      tooltip:{
        backgroundColor:'rgba(0,0,0,.88)',borderColor:'rgba(255,255,255,.12)',borderWidth:1,
        titleColor:'rgba(255,255,255,.5)',bodyColor:'#fff',padding:10,
        callbacks:{label:c=>fmtN(c.parsed.y,2)+' EUR'}
      }
    },
    scales:{
      x:{grid:{color:'rgba(255,255,255,.04)'},ticks:{maxTicksLimit:6,color:'rgba(255,255,255,.25)'},border:{display:false}},
      y:{grid:{color:'rgba(255,255,255,.04)'},ticks:{color:'rgba(255,255,255,.25)',callback:v=>fmtN(v,0)+'€'},border:{display:false}},
    },
    interaction:{mode:'index',intersect:false},
  }
});

// P&L bar chart
const pnlCtx=$('pnl-chart').getContext('2d');
const pnlChart=new Chart(pnlCtx,{
  type:'bar',
  data:{labels:[],datasets:[{
    data:[],
    backgroundColor:ctx=>(ctx.parsed?.y??0)>=0?'rgba(48,209,88,.65)':'rgba(255,69,58,.65)',
    borderColor:ctx=>(ctx.parsed?.y??0)>=0?'#30d158':'#ff453a',
    borderWidth:1,borderRadius:4,borderSkipped:false,
  }]},
  options:{
    animation:{duration:500,easing:'easeOutQuart'},
    responsive:true,maintainAspectRatio:false,
    plugins:{
      legend:{display:false},
      tooltip:{
        backgroundColor:'rgba(0,0,0,.88)',borderColor:'rgba(255,255,255,.12)',borderWidth:1,
        bodyColor:'#fff',padding:10,
        callbacks:{label:c=>(c.parsed.y>=0?'+':'')+fmtN(c.parsed.y,2)+' EUR'}
      }
    },
    scales:{
      x:{grid:{display:false},ticks:{color:'rgba(255,255,255,.2)',maxRotation:0},border:{display:false}},
      y:{grid:{color:'rgba(255,255,255,.04)'},ticks:{color:'rgba(255,255,255,.25)',callback:v=>fmtN(v,0)+'€'},border:{display:false}},
    }
  }
});

// ── Countdown M5 ─────────────────────────────────────────────────────────────
(function cdLoop(){
  const now=new Date();
  const s=now.getUTCSeconds(),ms=now.getUTCMilliseconds();
  const elapsed=(now.getUTCMinutes()%5)*60+s+ms/1000;
  const total=300,rem=total-elapsed;
  const m=Math.floor(rem/60),sec=Math.floor(rem%60);
  const disp=$('cd-display');
  if(disp) disp.textContent=m+':'+(sec<10?'0':'')+sec;
  const fill=$('cd-fill');
  if(fill){
    const pct=(elapsed/total)*100;
    fill.style.width=pct+'%';
    fill.style.background=pct>80?'var(--rd)':pct>60?'var(--am)':'var(--bl)';
  }
  requestAnimationFrame(cdLoop);
})();

// ── Probability helpers ───────────────────────────────────────────────────────
// Weighted score: CHoCH/OB/Liq = 3pt each (HIGH), FVG/PD/BOS/SD = 1pt each (MEDIUM)
const COND_CFG=[
  {key:'choch',icon:'🔄',name:'CHoCH',sub:'Cambio de carácter',  weight:3,label:'ALTO'},
  {key:'ob',   icon:'📦',name:'OB',   sub:'Order Block',          weight:3,label:'ALTO'},
  {key:'liq',  icon:'💧',name:'Liq',  sub:'Barrido de liquidez',  weight:3,label:'ALTO'},
  {key:'fvg',  icon:'🕳',name:'FVG',  sub:'Fair Value Gap',       weight:1,label:'MED'},
  {key:'pd',   icon:'⚖️',name:'P/D',  sub:'Premium / Descuento',  weight:1,label:'MED'},
  {key:'bos',  icon:'💥',name:'BOS',  sub:'Break of Structure',   weight:1,label:'MED'},
  {key:'sd',   icon:'🏭',name:'S&D',  sub:'Supply & Demand',      weight:1,label:'MED'},
];
const MAX_W=COND_CFG.reduce((a,c)=>a+c.weight,0); // 13

function calcProb(conds){
  if(!conds)return 0;
  const w=COND_CFG.reduce((a,c)=>a+(conds[c.key]?c.weight:0),0);
  return Math.round((w/MAX_W)*100);
}

function setArc(id,pct,isB){
  const el=$(id);if(!el)return;
  const circ=157;
  const offset=circ-(circ*pct/100);
  el.style.strokeDashoffset=offset;
  el.style.stroke=isB?'var(--gr)':'var(--rd)';
}

function renderConds(containerId,conds,side){
  const el=$(containerId);if(!el||!conds)return;
  el.innerHTML=COND_CFG.map(c=>{
    const on=!!conds[c.key];
    const cls=on?(side==='bull'?'on':'on-s'):'';
    const bc=on?(side==='bull'?'cb-on-b':'cb-on-s'):'cb-off';
    return`<div class="cond-row ${cls}">
      <div class="cond-l">
        <span class="cond-icon">${c.icon}</span>
        <span class="cond-name">${c.name}<span class="cond-name-sub">${c.sub}</span></span>
      </div>
      <div style="display:flex;align-items:center;gap:.4rem">
        <span class="cond-weight">${c.label}</span>
        <span class="cond-badge ${bc}">${on?'✓':'—'}</span>
      </div>
    </div>`;
  }).join('');
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function setPill(cls,txt){$('pill').className='pill '+cls;$('pill-txt').textContent=txt;}
function setDots(id,score,cls){
  document.querySelectorAll('#'+id+' .d').forEach((d,i)=>{d.className='d'+(i<score?' '+cls:'');});
}

// ── Main refresh ──────────────────────────────────────────────────────────────
let _lastLogLines=[];

async function refresh(){
  let s;
  try{const r=await fetch('/api/state');if(!r.ok)throw 0;s=await r.json();}
  catch{setPill('p-off','DESCONECTADO');return;}

  // Stale banner
  const ban=$('ban');
  if(s.last_update){
    const[h,m,sec]=s.last_update.replace(' UTC','').split(':').map(Number);
    const ps=h*3600+m*60+sec,n=new Date(),ns=n.getUTCHours()*3600+n.getUTCMinutes()*60+n.getUTCSeconds();
    ban.style.display=((ns-ps+86400)%86400)>120?'block':'none';
  }else ban.style.display='none';

  // Header
  $('sym').textContent=s.symbol||'—';
  $('tf').textContent=s.tf_chain?'· '+s.tf_chain:'';
  $('dry').style.display=s.dry_run?'inline':'none';

  // Pill
  const paused=s.bot_paused;
  if(paused){setPill('p-pause','EN PAUSA');}
  else{
    const PM={operativo:['p-live','OPERATIVO'],bloqueado:['p-block','BLOQUEADO'],
      fuera_sesion:['p-idle','FUERA SESIÓN'],sin_señal:['p-idle','EN ESPERA'],iniciando:['p-idle','INICIANDO']};
    const[pc,pt]=PM[s.status]||['p-off',(s.status||'?').toUpperCase()];
    setPill(pc,pt);
  }
  // Sync pause toggle
  $('sw-pause').checked=!!paused;

  // Balance
  animN('bal',s.balance??0,v=>fmtN(v)+' EUR');

  // Equity
  const diff=(s.equity||0)-(s.initial_balance||10000);
  animN('eq',s.equity??0,v=>fmtN(v)+' EUR');
  $('eq').style.color=diff>=0?'var(--gr)':'var(--rd)';
  const ed=$('eq-d');ed.textContent=(diff>=0?'+':'')+fmtN(diff)+' EUR';
  ed.className='badge '+(diff>=0?'b-pos':'b-neg');
  $('k-eq').className='kpi '+(diff>=0?'c-gr':'c-rd');

  // P&L
  const pnl=s.daily_pnl||0,lim=s.daily_limit_eur||100;
  $('pnl').textContent=(pnl<0?'-':pnl>0?'+':'')+fmtN(Math.abs(pnl))+' EUR';
  $('pnl').style.color=pnl>=0?'var(--gr)':'var(--rd)';
  $('pnl-l').textContent='-'+fmtN(lim)+' EUR';
  $('k-pnl').className='kpi '+(pnl<-lim*.7?'c-rd':pnl<0?'c-am':'c-gr');

  // Positions count
  const np=(s.open_positions||[]).length;
  $('pos-n').textContent=np+' / 1';$('pos-n').style.color=np>0?'var(--gr)':'var(--t1)';
  $('cyc').textContent='#'+(s.cycle||0);$('pos-c').textContent=np;
  $('k-pos').className='kpi '+(np>0?'c-gr':'c-bl');

  // FTMO gauge
  const floor=s.ftmo_floor||9000,init=s.initial_balance||10000,eq=s.equity||0;
  const fp=clamp((1-Math.max(0,init-eq)/(init-floor))*100,0,100);
  const fb=$('ftmo-f');fb.style.width=fp+'%';
  fb.className='fill '+(fp>60?'f-g':fp>30?'f-a':'f-r');
  $('ftmo-v').textContent=fmtN(eq)+' / '+fmtN(init)+' EUR';
  $('ftmo-l').textContent='Margen: '+fmtN(eq-floor)+' EUR';
  $('ftmo-r').textContent='Suelo: '+fmtN(floor)+' EUR';

  // Daily gauge
  const loss=Math.max(0,-pnl);
  const dp=clamp((loss/lim)*100,0,100);
  const db=$('day-f');db.style.width=dp+'%';
  db.className='fill '+(dp<50?'f-g':dp<80?'f-a':'f-r');
  $('day-v').textContent=fmtN(loss)+' / '+fmtN(lim)+' EUR';
  $('day-l').textContent=dp<100?'Pérdida: '+fmtE(-loss):'⛔ Límite alcanzado';
  $('day-r').textContent=dp<100?'Restante: '+fmtE(lim-loss):'';

  // News
  const NS={
    none:  ['i-none','📰','Sin filtro activo','Activa --use-forex-factory'],
    ok:    ['i-ok','🟢','Libre para operar',s.next_news_title?'Próx: '+s.next_news_title+' ('+s.next_news_mins+'min)':'Sin noticias próximas'],
    warning:['i-warn','🟡','Precaución — '+(s.next_news_title||''),'En '+(s.next_news_mins||'?')+' min'],
    blocked:['i-blk','🔴','⛔ BLACKOUT — '+(s.next_news_title||'Noticia roja'),s.next_news_mins!=null?'Faltan '+s.next_news_mins+' min':'Bloqueado'],
  };
  const[nc,ne,nt,ns2]=NS[s.news_status]||NS.none;
  const ni=$('n-ind');ni.className='ind '+nc;ni.textContent=ne;
  $('n-main').textContent=nt;$('n-sub').textContent=ns2;

  // Session
  const si=$('s-ind'),sm=$('s-main');
  if(s.in_session){si.className='ind i-ok';si.textContent='🟢';sm.textContent=s.session||'Sesión activa';sm.style.color='var(--gr)';}
  else{si.className='ind i-none';si.textContent='🌙';sm.textContent=s.session||'Fuera de sesión';sm.style.color='var(--t2)';}

  // Signals
  const bull=s.score_bull||0,bear=s.score_bear||0,minSc=s.min_score||5;
  $('sc-b').textContent=bull;$('sc-s').textContent=bear;
  $('sc-b').className='sig-n sn-b '+(bull>=minSc?'on':'sn-off');
  $('sc-s').className='sig-n sn-s '+(bear>=minSc?'on':'sn-off');
  $('th-b').textContent=bull+' / 7 condiciones';$('th-s').textContent=bear+' / 7 condiciones';
  setDots('d-b',bull,'ob');setDots('d-s',bear,'os');
  const sb=$('sig-b');
  if(s.last_signal_dir==='LONG')      {sb.textContent='▲ LONG activa'; sb.className='sig-badge sl-long';}
  else if(s.last_signal_dir==='SHORT'){sb.textContent='▼ SHORT activa';sb.className='sig-badge sl-short';}
  else                                 {sb.textContent='Sin señal';     sb.className='sig-badge sl-none';}

  // ── Probabilities & conditions ──────────────────────────────────────────
  const cb=s.conds_bull||{},cs=s.conds_bear||{};
  const pb=calcProb(cb),ps=calcProb(cs);
  // Arc gauges
  setArc('arc-bull',pb,true);
  setArc('arc-bear',ps,false);
  // Percentage text with animation
  animN('prob-bull-pct',pb,v=>Math.round(v)+'%');
  animN('prob-bear-pct',ps,v=>Math.round(v)+'%');
  // Color pct label
  $('prob-bull-pct').style.color=pb>=70?'var(--gr)':pb>=40?'var(--am)':'var(--t3)';
  $('prob-bear-pct').style.color=ps>=70?'var(--rd)':ps>=40?'var(--am)':'var(--t3)';
  // Condition breakdown
  renderConds('conds-bull',cb,'bull');
  renderConds('conds-bear',cs,'bear');
  // Dominant direction
  const dd=$('dominant-dir');
  if(pb>ps&&pb>=50){dd.textContent='▲ LONG';dd.style.color='var(--gr)';}
  else if(ps>pb&&ps>=50){dd.textContent='▼ SHORT';dd.style.color='var(--rd)';}
  else{dd.textContent='NEUTRAL';dd.style.color='var(--t3)';}
  // TradingView signal banner
  const tvSig=s.tv_signal;
  const tvBox=$('tv-signal-box');
  if(tvSig&&tvBox){
    tvBox.textContent='📡 '+tvSig.dir+(tvSig.score?' (score: '+tvSig.score+')':'')+(tvSig.time?' · '+tvSig.time:'');
    tvBox.style.color=tvSig.dir==='LONG'?'var(--gr)':'var(--rd)';
    tvBox.style.background=tvSig.dir==='LONG'?'rgba(48,209,88,.07)':'rgba(255,69,58,.07)';
    tvBox.style.borderColor=tvSig.dir==='LONG'?'rgba(48,209,88,.2)':'rgba(255,69,58,.2)';
    const tvb=$('tv-signal-banner');
    if(tvb){tvb.textContent='📡 Señal TradingView: '+tvSig.dir+' recibida';tvb.classList.add('show');}
  }
  // Update TV widget symbol
  const tvsl=$('tv-sym-lbl');if(tvsl)tvsl.textContent=(s.symbol||'EURUSD')+' · M5';

  // Positions table
  const pos=s.open_positions||[];
  $('pos-b').innerHTML=pos.length===0
    ?'<tr class="empty"><td colspan="8">Sin posiciones abiertas</td></tr>'
    :pos.map(p=>`<tr>
      <td><span class="tk">#${p.ticket}</span></td><td>${p.symbol}</td>
      <td class="${p.dir==='LONG'?'dl':'ds'}">${p.dir==='LONG'?'▲ LONG':'▼ SHORT'}</td>
      <td>${fmtN(p.lot,2)}</td><td>${fmtN(p.entry,5)}</td>
      <td style="color:var(--rd)">${fmtN(p.sl,5)}</td>
      <td style="color:var(--gr)">${fmtN(p.tp,5)}</td>
      <td class="${(p.pnl||0)>=0?'pp':'pn'}">${fmtE(p.pnl,true)}</td>
    </tr>`).join('');

  // Trades table + stats
  const trs=[...(s.recent_trades||[])].reverse();
  $('tr-c').textContent=trs.length;
  $('tr-b').innerHTML=trs.length===0
    ?'<tr class="empty"><td colspan="5">Sin operaciones registradas</td></tr>'
    :trs.map(t=>`<tr>
      <td style="color:var(--t3)">${t.time||'—'}</td><td>${t.symbol||'—'}</td>
      <td class="${t.dir==='LONG'?'dl':'ds'}">${t.dir==='LONG'?'▲ LONG':'▼ SHORT'}</td>
      <td class="${(t.pnl||0)>=0?'pp':'pn'}">${fmtE(t.pnl,true)}</td>
      <td style="color:var(--t3);font-size:.71rem">${t.motivo||'—'}</td>
    </tr>`).join('');

  // Stats calculation
  const allTrades=s.recent_trades||[];
  if(allTrades.length>0){
    const wins=allTrades.filter(t=>t.pnl>0),losses=allTrades.filter(t=>t.pnl<0);
    const wr=wins.length/allTrades.length*100;
    const sumW=wins.reduce((a,t)=>a+t.pnl,0);
    const sumL=Math.abs(losses.reduce((a,t)=>a+t.pnl,0));
    const pf=sumL>0?sumW/sumL:sumW>0?Infinity:0;
    const avgW=wins.length?sumW/wins.length:0;
    const avgL=losses.length?-sumL/losses.length:0;
    const best=Math.max(...allTrades.map(t=>t.pnl));
    const worst=Math.min(...allTrades.map(t=>t.pnl));
    $('st-wr').textContent=wr.toFixed(0)+'%';
    $('st-wr').style.color=wr>=50?'var(--gr)':wr>=40?'var(--am)':'var(--rd)';
    $('st-wr-s').textContent=wins.length+'W · '+losses.length+'L';
    $('st-pf').textContent=pf===Infinity?'∞':pf.toFixed(2);
    $('st-pf').style.color=pf>=1.5?'var(--gr)':pf>=1?'var(--am)':'var(--rd)';
    $('st-aw').textContent=fmtN(avgW)+' €';
    $('st-al').textContent=fmtN(avgL)+' €';
    $('st-bw').textContent=fmtN(best)+' / '+fmtN(worst)+' €';
    // P&L chart update
    const labels=allTrades.map((_,i)=>'#'+(i+1));
    const data=allTrades.map(t=>t.pnl);
    pnlChart.data.labels=labels;
    pnlChart.data.datasets[0].data=data;
    pnlChart.update('active');
    $('pnl-meta').textContent=allTrades.length+' ops · '+fmtE(allTrades.reduce((a,t)=>a+t.pnl,0),true);
  }else{
    ['st-wr','st-pf','st-aw','st-al','st-bw'].forEach(id=>{$(id).textContent='—';$(id).style.color='';});
    $('st-wr-s').textContent='sin datos';
    pnlChart.data.labels=[];pnlChart.data.datasets[0].data=[];pnlChart.update();
    $('pnl-meta').textContent='sin operaciones';
  }

  // Equity chart
  const hist=s.equity_history||[];
  if(hist.length>1){
    eqChart.data.labels=hist.map(p=>p.t);
    eqChart.data.datasets[0].data=hist.map(p=>p.v);
    // Dynamic gradient based on trend
    const first=hist[0].v,last=hist[hist.length-1].v;
    const color=last>=first?'rgba(48,209,88,':'rgba(255,69,58,';
    const hex=last>=first?'#30d158':'#ff453a';
    const g=eqCtx.createLinearGradient(0,0,0,160);
    g.addColorStop(0,color+'.2)');g.addColorStop(1,color+'0)');
    eqChart.data.datasets[0].backgroundColor=g;
    eqChart.data.datasets[0].borderColor=hex;
    eqChart.update('active');
    $('eq-range').textContent=fmtN(Math.min(...hist.map(p=>p.v)),0)+' – '+fmtN(Math.max(...hist.map(p=>p.v)),0)+' EUR';
  }else{$('eq-range').textContent='acumulando datos…';}

  // Log
  const lines=s.log_lines||[];
  const linesKey=lines.join('|');
  if(linesKey!==_lastLogLines){
    _lastLogLines=linesKey;
    $('log-b').innerHTML=lines.length===0
      ?'<div class="ll"><span class="lt">—</span><span class="lm">Esperando datos…</span></div>'
      :lines.map(l=>{const ts=l.match(/^\d{2}:\d{2}/)?.[0]||'';const msg=ts?l.slice(ts.length).trim():l;
        return`<div class="ll"><span class="lt">${ts}</span><span class="lm">${msg}</span></div>`;}).join('');
  }
  $('log-ts').textContent=s.last_update||'—';
  $('ft').textContent=(s.last_update||'—')+'  ·  ciclo #'+(s.cycle||0);

  // Settings panel info
  $('c-bal').value=Math.round(s.balance||10000);
  calcLot();
  $('i-init').textContent=fmtN(s.initial_balance||10000)+' EUR';
  $('i-floor').textContent=fmtN(s.ftmo_floor||9000)+' EUR';
  $('i-daily').textContent='-'+fmtN(s.daily_limit_eur||100)+' EUR';
  $('i-margin').textContent=fmtN((s.equity||0)-(s.ftmo_floor||9000))+' EUR';
  $('i-sym').textContent=s.symbol||'—';
  $('i-cyc').textContent=s.cycle||0;
  // Sync slider with current min_score
  if(s.min_score){
    $('sc-slider').value=s.min_score;
    $('sc-val').textContent=s.min_score;
    $('sc-desc').textContent=s.min_score+' de 7 condiciones — '+SC_LABELS[s.min_score];
  }
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
        elif self.path == "/api/control":
            with _ctl_lock:
                data = json.dumps(_controls).encode("utf-8")
            self._serve_bytes(data, "application/json", cors=True)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        if self.path == "/api/control":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                data = json.loads(body)
                valid = {k: v for k, v in data.items() if k in _controls}
                set_controls(**valid)
                # Reflect min_score_override in displayed state
                if "min_score_override" in valid and valid["min_score_override"] is not None:
                    with _lock:
                        _state["min_score"] = int(valid["min_score_override"])
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
            except Exception:
                self.send_response(400)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
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
        pass


# ── Public API ─────────────────────────────────────────────────────────────────

def start_dashboard(port: int = 8765) -> HTTPServer:
    """Lanza el servidor HTTP en un hilo daemon. Devuelve la instancia del servidor."""
    server = HTTPServer(("0.0.0.0", port), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True, name="dashboard-http")
    t.start()
    return server
