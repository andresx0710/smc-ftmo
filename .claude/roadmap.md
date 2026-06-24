---
name: roadmap
description: Roadmap del sistema SMC-FTMO — motor de análisis técnico como prioridad máxima
metadata:
  type: project
---

# Roadmap y Features

_Referenciado desde [[CLAUDE.md]]_
_Ver también: [[smc-concepts.md]] | [[ftmo-rules.md]] | [[target-users.md]]_

---

## Foco del MVP

**Motor de análisis técnico SMC** que detecta CHoCH, Order Blocks y FVGs en TradingView (Pine Script) con alertas en tiempo real, validado contra las reglas de riesgo FTMO para la cuenta de 10k EUR.

**El MVP NO incluye:** ejecución automática de órdenes, dashboard web, backtesting automatizado.

**Fecha objetivo de MVP:** Por definir

---

## FASE 1 — Motor de Análisis SMC (PRIORIDAD MÁXIMA)

> Núcleo del sistema. Sin esto, nada más tiene sentido.

### 1.1 Indicadores Pine Script (TradingView)
- [x] **Detector de estructura de mercado** — identificar HH, HL, LH, LL automáticamente → `pine/market_structure.pine`
- [x] **Detector de CHoCH / BOS** — señal visual en gráfico + alerta webhook → incluido en `pine/market_structure.pine`
- [x] **Detector de Order Blocks** (alcista y bajista) — con zona pintada y estado (activo/mitigado) → `pine/order_block.pine`
- [x] **Detector de Fair Value Gaps (FVG)** — visualización de zonas de imbalance → `pine/fvg_detector.pine`
- [x] **Detector de zonas Supply & Demand** — zonas de alta temporalidad → `pine/supply_demand.pine`
- [x] **Detector de liquidez** (BSL / SSL — equal highs/lows) → `pine/liquidity_detector.pine`
- [x] **Panel Premium/Discount** — indicador del 50% del rango actual → `pine/premium_discount.pine`

### 1.2 Sistema de confluencias
- [x] **Score de confluencia SMC** — 7 condiciones con pesos Alto/Medio, señal cuando score ≥ umbral → `pine/confluence_score.pine`
- [x] **Señal de entrada válida** — alerta cuando score ≥ i_minScore (default 3) para LONG y SHORT
- [x] **Análisis multi-timeframe integrado** — D1 sesgo (gate duro), H1 OB + CHoCH, TF actual BOS/FVG/Liq/OB → `pine/mtf_confluence_score.pine`

### 1.3 Webhooks y alertas
- [x] **TradingView → FastAPI webhook** — recepción de señales SMC en tiempo real → `backend/main.py`
- [x] **Alerta Telegram** — mensaje con score, condiciones, precio y checklist FTMO → `backend/telegram_bot.py`

---

## FASE 2 — Gestión de Riesgo FTMO Automatizada

> Dependiente de Fase 1. Protege la cuenta de fondeo.

- [x] **Panel de riesgo en tiempo real** (Pine Script) — P&L diario, drawdown total, riesgo abierto → `pine/risk_panel.pine`
- [x] **Calculadora de sizing automática** — calcula lotes según riesgo 1% y SL en pips → incluida en `pine/risk_panel.pine`
- [x] **Bloqueo automático de entradas** si se supera el 3% (300 EUR) de riesgo diario → lógica y alerta en `risk_panel.pine`
- [x] **Alerta crítica** cuando daily loss supera el 60% del límite del sistema (180 EUR) → 4 niveles: OK / Precaución / Bloqueado / Crítico
- [ ] **Motor de validación FTMO** (Python) — checklist pre-entrada automatizado (requiere MT5 — Phase 3)

---

## FASE 3 — Integración con MT5 (Ejecución semi-automática)

> Solo implementar una vez Fase 1 y 2 estén probadas manualmente.

- [x] **Conexión Python → MT5** — lectura de balance, equity y posiciones → `backend/mt5/client.py`
- [x] **Envío de órdenes desde Python** — market order con SL/TP auto → `backend/mt5/orders.py` + `POST /order`
- [x] **Monitor de posiciones abiertas** — loop asyncio, alertas por estado FTMO → `backend/mt5/monitor.py`
- [x] **Cierre automático de emergencia** — se activa cuando equity < 9.000 EUR → `close_all_positions()` en monitor

---

## FASE 4 — Backtesting y Optimización

- [x] **Descarga histórica OHLCV** — MT5 con caché CSV, fallback a CSV externo → `backtest/data.py`
- [x] **Backtester del motor SMC** — port completo de `confluence_score.pine` a Python → `backtest/detector.py` + `backtest/engine.py`
- [x] **Métricas de rendimiento** — win rate, R:R, profit factor, max drawdown, Sharpe, breakdown por score/dirección/condición → `backtest/metrics.py`
- [x] **CLI completo** — `python -m backtest.run --symbol EURUSD --tf H1 --min-score 4` → `backtest/run.py`
- [ ] **Optimización de parámetros** — grid search sobre min_score, sl_pips, ob_lookback (pendiente)

---

## Backlog (sin prioridad definida)

- Dashboard web para visualizar historial de señales y estadísticas
- Soporte para múltiples pares simultáneos (EURUSD, GBPUSD, XAUUSD, NAS100)
- Bot de Telegram interactivo para consultar estado de cuenta
- Notificaciones de noticias de alto impacto (integración con Forex Factory o Investing.com)
- Sistema de journaling automático (registrar cada operación con screenshot de TradingView)

---

## Descartado explícitamente

| Feature | Razón de descarte |
|---|---|
| Trading 100% autónomo sin supervisión | Riesgo demasiado alto para cuenta de fondeo; se prefiere asistencia con confirmación humana |
| Indicadores basados en medias móviles o RSI | El sistema es SMC puro — no mezclar con indicadores lagging tradicionales |
| Scalping en M1/M5 | Reglas FTMO son difíciles de gestionar en timeframes tan bajos; mínimo M15 |

---

## Métricas de éxito del MVP (Fase 1)

- El sistema detecta correctamente CHoCH en H4 con menos de 2 falsas señales por semana en EURUSD
- Las zonas de OB son visualmente correctas y se invalidan automáticamente tras mitigación
- El webhook llega a Telegram en menos de 5 segundos desde la alerta en TradingView
- El score de confluencia SMC correlaciona con win rate >60% en muestra de 50 señales

---

## Versiones

| Versión | Estado | Contenido |
|---|---|---|
| 0.1 | `[ ] En desarrollo` | Detectores Pine Script: CHoCH + OB + FVG |
| 0.2 | `[ ] Pendiente` | Score de confluencias + webhook + Telegram |
| 0.3 | `[ ] Pendiente` | Panel de riesgo FTMO + calculadora de sizing |
| 1.0 MVP | `[ ] Pendiente` | Fase 1 + Fase 2 completas y probadas en demo FTMO |
| 2.0 | `[ ] Pendiente` | Integración MT5 (Fase 3) |
