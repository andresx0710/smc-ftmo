---
name: rules
description: Reglas de código, convenciones de commits y comportamiento de Claude en el proyecto SMC-FTMO
metadata:
  type: project
---

# Reglas y Convenciones

_Referenciado desde [[CLAUDE.md]]_
_Ver también: [[tech-stack.md]] | [[ftmo-rules.md]] para reglas de trading_

---

## Reglas para Claude

- **NUNCA proponer lógica de entrada sin validar contra [[ftmo-rules.md]]** — las reglas FTMO tienen prioridad absoluta.
- **NUNCA sugerir modificar el SL una vez la operación está abierta** — mover SL a pérdida mayor está prohibido en este sistema.
- No agregar features fuera del scope del MVP — revisar [[roadmap.md]] primero.
- No cambiar decisiones del [[tech-stack.md]] sin registrar el motivo en [[history.md]].
- No escribir comentarios que expliquen QUÉ hace el código — solo el POR QUÉ cuando no sea obvio.
- Respuestas cortas y directas. Sin resúmenes al final de cada respuesta.
- Si la lógica de detección SMC es ambigua, preguntar antes de implementar — una detección incorrecta de OB o CHoCH puede generar señales falsas.
- Ante cualquier duda sobre riesgo: **errar del lado conservador**.

---

## Convenciones de código — Python

**Lenguaje de los identificadores:** Inglés (nombres de variables, funciones, clases)
**Comentarios y docstrings:** Español

**Nombrado:**
- Variables y funciones: `snake_case`
- Clases: `PascalCase`
- Constantes: `UPPER_SNAKE_CASE`
- Archivos: `snake_case.py`

**Formato:**
- Indentación: 4 espacios
- Comillas: dobles `"`
- Largo máx de línea: 100 caracteres
- Formatter: **Black**
- Linter: **Ruff**
- Type hints: obligatorios en funciones públicas

**Ejemplo de función correcta:**
```python
def calculate_position_size(account_balance: float, risk_pct: float, sl_pips: float) -> float:
    """Calcula el tamaño de posición en lotes respetando el riesgo FTMO."""
    risk_amount = account_balance * (risk_pct / 100)
    return risk_amount / sl_pips
```

---

## Convenciones de código — Pine Script

**Versión:** Pine Script v5 siempre (`//@version=5`)
**Nombrado:**
- Variables: `camelCase`
- Funciones: `camelCase`
- Constantes: `UPPER_SNAKE_CASE`

**Estructura obligatoria de cada indicador:**
```pine
//@version=5
indicator("Nombre del indicador", overlay=true, max_bars_back=500)

// --- INPUTS ---
// --- FUNCIONES ---
// --- LÓGICA PRINCIPAL ---
// --- PLOTS ---
// --- ALERTAS ---
```

---

## Convenciones de Git

**Rama principal:** `main`

**Estrategia de ramas:**
- Features: `feature/nombre-corto`
- Bugs: `fix/descripcion`
- Indicadores Pine Script: `indicator/nombre-indicador`

**Formato de commits:**
```
tipo(scope): descripción en imperativo

feat(pine)     → nuevo indicador o señal
feat(engine)   → nueva lógica del motor Python
feat(risk)     → nueva regla de gestión de riesgo
fix(pine)      → corrección en indicador
fix(risk)      → corrección en cálculo de riesgo
refactor       → sin cambio de funcionalidad
test           → tests del motor de análisis
chore          → mantenimiento, dependencias
```

---

## Estructura de carpetas

```
/
├── pine/                    # Indicadores Pine Script
│   ├── choch_detector.pine
│   ├── order_block.pine
│   ├── supply_demand.pine
│   ├── fvg_detector.pine
│   └── risk_panel.pine
├── engine/                  # Motor Python
│   ├── detectors/           # Módulos de detección SMC
│   ├── risk/                # Gestión de riesgo FTMO
│   ├── broker/              # Integración MT5
│   ├── alerts/              # Telegram, webhooks
│   └── api/                 # FastAPI (recepción webhooks)
├── data/                    # OHLCV histórico para backtesting
├── tests/                   # Tests del motor
└── CLAUDE.md
```

---

## Lo que está prohibido

- Nunca usar `time.sleep()` en el motor de webhooks — usar async/await
- Nunca hardcodear el balance de la cuenta — leerlo siempre desde MT5 API en tiempo real
- Nunca enviar una orden sin pasar primero por el módulo de validación FTMO
- Nunca modificar el SL de una operación abierta para aumentar la pérdida máxima
- Nunca operar en viernes después de las 20:00 UTC (riesgo de gaps de fin de semana)
