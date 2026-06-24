---
name: tech-stack
description: Stack tecnológico del sistema de trading SMC-FTMO — Pine Script, Python, TradingView, MT5
metadata:
  type: project
---

# Stack Tecnológico

_Referenciado desde [[CLAUDE.md]]_
_Ver también: [[rules.md]] para convenciones | [[smc-concepts.md]] para lógica de detección_

---

## Capa de análisis técnico — TradingView / Pine Script

| Componente | Tecnología | Por qué |
|---|---|---|
| Indicadores de detección | **Pine Script v5** | Nativo en TradingView, acceso directo a OHLCV, visualización en tiempo real |
| Alertas de señales | **TradingView Webhooks** | Envío automático a backend cuando se cumplen condiciones SMC |
| Timeframes de análisis | H4 (tendencia), H1 (estructura), M15 (entrada) | Top-down analysis: HTF define sesgo, LTF afina entrada |

**Indicadores Pine Script a desarrollar:**
- Detector de CHoCH / BOS
- Detector de Order Blocks (bullish / bearish)
- Detector de Fair Value Gaps (FVG)
- Detector de zonas de Supply & Demand
- Detector de liquidez (equal highs/lows, BSL/SSL)
- Panel de gestión de riesgo FTMO (drawdown en tiempo real)

---

## Capa de backend — Motor de análisis

| Componente | Tecnología | Alternativa descartada | Por qué |
|---|---|---|---|
| Lenguaje principal | **Python 3.11+** | JavaScript | Ecosistema de datos financieros (pandas, numpy, TA-Lib) |
| Procesamiento de datos OHLCV | **pandas + numpy** | — | Estándar de facto para análisis de series temporales |
| Servidor de webhooks | **FastAPI** | Flask | Async nativo, tipado, performance |
| Indicadores técnicos adicionales | **pandas-ta** | TA-Lib | Instalación más simple, activamente mantenido |

---

## Capa de ejecución — Broker

| Componente | Tecnología | Por qué |
|---|---|---|
| Broker compatible FTMO | **MetaTrader 5 (MT5)** | FTMO proporciona cuentas MT5; API Python oficial (`MetaTrader5`) |
| Librería Python-MT5 | **MetaTrader5** (pip) | Conexión directa a terminal MT5 para envío de órdenes y gestión de posiciones |
| Gestión de órdenes | Módulo propio sobre MT5 API | Control total del sizing, SL/TP calculados con reglas FTMO |

---

## Base de datos

| Tipo | Tecnología | Propósito |
|---|---|---|
| Principal | **PostgreSQL** | Almacenar operaciones, señales detectadas, P&L histórico |
| Caché / tiempo real | **Redis** | Estado de cuenta (drawdown actual, riesgo abierto) |

---

## Infraestructura

| Componente | Servicio |
|---|---|
| Ejecución del backend | Local (mismo PC con MT5) durante desarrollo; VPS Windows para producción |
| VPS recomendado | Windows Server con MT5 instalado (requerimiento de MT5 Python API) |
| Alertas al trader | Telegram Bot API |
| Logs | Loguru (Python) + archivos locales |

---

## Flujo de datos del sistema

```
TradingView (Pine Script)
    │ Webhook al detectar señal SMC
    ▼
FastAPI Backend (Python)
    │ Valida señal + calcula riesgo
    │ Consulta estado de cuenta en MT5
    ▼
Motor de Riesgo FTMO
    │ ¿Daily loss OK? ¿Max drawdown OK? ¿Sizing correcto?
    ▼
MT5 API → Orden enviada al broker
    │
    ▼
Telegram → Notificación al trader
    │
    ▼
PostgreSQL → Registro histórico
```

---

## Decisiones arquitectónicas fijas

> Estas decisiones NO deben cuestionarse sin actualizar [[history.md]]

- **Pine Script como capa de detección visual** — La lógica de detección SMC vive en TradingView para aprovechar los gráficos en tiempo real y las alertas nativas.
- **Python como backend** — Todo lo que requiera lógica de negocio compleja (gestión de riesgo, cálculo de sizing, validación FTMO) vive en Python.
- **MT5 como broker** — FTMO opera principalmente sobre MT5; no usar cuentas MT4 para este proyecto.
- **Análisis top-down**: H4 → H1 → M15. No operar en timeframes inferiores a M15.

---

## Deuda técnica conocida

- La API de Python para MT5 solo funciona en Windows — considerar alternativas si se necesita portabilidad Linux
- TradingView webhooks requieren plan Pro+ o superior para activarse en tiempo real
