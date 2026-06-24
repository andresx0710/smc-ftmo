---
name: history
description: Registro cronológico de decisiones importantes del sistema SMC-FTMO
metadata:
  type: project
---

# Historial de Decisiones

_Referenciado desde [[CLAUDE.md]]_
_Registra el POR QUÉ, no el QUÉ. Las entradas van de más reciente a más antigua._

---

## Cómo añadir una entrada

```
### [YYYY-MM-DD] Título de la decisión
**Contexto:** Por qué surgió la necesidad de decidir esto.
**Opciones consideradas:** Qué alternativas se evaluaron.
**Decisión:** Qué se eligió.
**Por qué:** La razón real detrás de la elección.
**Consecuencias:** Qué implica esta decisión a futuro.
```

---

## Decisiones registradas

### [2026-06-24] Backtester: port directo de confluence_score.pine a Python

**Contexto:** Phase 4 — necesitamos validar la estrategia SMC con datos históricos antes de operar en real.
**Opciones consideradas:**
- Backtesting en Pine Script (TradingView): limitado — no permite exportar métricas ni automatizar grid search
- Backtrader / VectorBT: frameworks genéricos potentes pero requieren adaptar la lógica SMC a sus APIs
- Port manual a Python: elegido — control total, mismo detector que el sistema live
**Decisión:** Port completo de `confluence_score.pine` a Python en `backtest/detector.py`, con las MISMAS condiciones y parámetros por defecto para que los resultados del backtest sean comparables con las señales live de TradingView.
**Por qué:** Si usáramos un framework externo, el backtest podría divergir del comportamiento real. El port manual garantiza que lo que simulamos es exactamente lo que TradingView detecta.
**Consecuencias:** Si se cambia la lógica de detección en Pine Script, hay que actualizar también `detector.py`. Documentar cualquier divergencia conocida entre Pine Script y el port Python.

---

### [2026-06-24] Backtester: entrada al open de la barra siguiente (no al cierre de señal)

**Contexto:** Decidir en qué precio se simula la entrada tras una señal.
**Decisión:** La señal dispara en el cierre de bar[i]; la entrada se simula en el open de bar[i+1].
**Por qué:** Pine Script lanza `alert.freq_once_per_bar` al cierre de la barra. En tiempo real, la orden llegaría al mercado en la siguiente barra. Entrar al cierre de la barra de señal sería look-ahead bias.
**Consecuencias:** El backtest subestima ligeramente el rendimiento vs. la teoría (el spread y slippage del open añaden noise) pero es más realista. Importante para comparar backtest vs. resultados live.

---

### [2026-06-24] Backtester: FTMO daily limit aplicado al backtest (300 EUR/día)

**Contexto:** El backtest debe reflejar las condiciones reales de la cuenta FTMO, incluyendo el límite de pérdida diaria.
**Decisión:** El motor de backtest rastraea el P&L diario y bloquea nuevas entradas si la pérdida del día supera `ftmo_daily_limit` (default 300 EUR).
**Por qué:** Sin este filtro, el backtest simularía más operaciones de las que son posibles en real bajo las reglas FTMO. El win rate y drawdown serían optimistas (no reflejarían el comportamiento correcto del sistema).
**Consecuencias:** Los resultados del backtest con `ftmo_daily_limit=300` son conservadores. El parámetro es configurable vía `--daily-limit` en el CLI para explorar escenarios.

---

### [2026-06-24] MT5 Phase 3: semi-automático con validación FTMO pre-entrada

**Contexto:** Integración con MetaTrader5 para leer cuenta y colocar órdenes.
**Opciones consideradas:**
- Automático: webhook → MT5 sin intervención humana → descartado (roadmap.md: "Trading 100% autónomo — Riesgo demasiado alto para cuenta de fondeo")
- Semi-automático: webhook → Telegram → usuario aprueba → `POST /order` → MT5 → elegido
**Decisión:** La ejecución requiere que el usuario llame explícitamente a `POST /order`. El webhook solo notifica en Telegram.
**Por qué:** En una cuenta de fondeo FTMO, un error en la ejecución automática puede resultar en el fallo del challenge. La confirmación humana es el cortafuegos definitivo.
**Consecuencias:** El flujo completo es: TradingView signal → Telegram notification → usuario revisa → llama `/order` → MT5 → confirmación en Telegram.

---

### [2026-06-24] MT5: pip value calculado con trade_tick_value (no hardcodeado)

**Contexto:** EURUSD y XAUUSD tienen convenciones de pip muy distintas — hardcodear generaría errores.
**Decisión:** `calculate_lot_size()` usa `symbol_info.trade_tick_value` × pip_ticks para obtener el valor real del pip en EUR desde MT5.
**Por qué:** MT5 reporta el `trade_tick_value` en la moneda de la cuenta (EUR), ya ajustado por el tipo de cambio actual. Esto funciona correctamente para ambos pares y para cualquier otro que se añada en el futuro.
**Consecuencias:** `pip_ticks = 10` para pares de 5 decimales (EURUSD) y `100` para pares de 2 decimales (XAUUSD). La detección se basa en `symbol_info.digits`.

---

### [2026-06-24] Monitor MT5: máquina de estados para evitar spam en Telegram

**Contexto:** Si el monitor enviara un Telegram cada vez que comprueba la cuenta (cada 30s), el canal se llenaría de mensajes repetidos.
**Decisión:** El monitor mantiene `_state` en memoria y sólo envía alertas en TRANSICIONES de estado (OK→Warning, Warning→Blocked, etc.).
**Por qué:** El usuario necesita ser notificado UNA VEZ cuando algo cambia, no cada 30 segundos.
**Consecuencias:** El estado se pierde si el servidor se reinicia. Esto es aceptable para uso diario — el monitor no tiene memoria entre sesiones.

---

### [2026-06-24] Webhook: responder siempre 200 a TradingView independientemente del estado de Telegram

**Contexto:** TradingView desactiva automáticamente webhooks que reciben respuestas 4xx/5xx de forma consecutiva.
**Decisión:** `POST /webhook` siempre retorna HTTP 200. Los errores de Telegram se loguean pero no se propagan como error HTTP.
**Por qué:** Perder la conectividad de Telegram no debe dejar al indicador sin webhook. El log de Loguru registra el fallo para depuración posterior.
**Consecuencias:** Si Telegram falla silenciosamente, las señales se pierden sin aviso visual. En Phase 2 se añadirá un segundo canal de notificación (email o retry queue).

---

### [2026-06-24] Webhook autenticado con query param ?secret en lugar de header

**Contexto:** TradingView no permite configurar headers HTTP personalizados en los webhooks.
**Decisión:** El token de seguridad se pasa como query parameter: `POST /webhook?secret=XXX`.
**Por qué:** Es la única forma soportada por TradingView para autenticar el destino del webhook. Alternativa descartada: token en el payload JSON (añadiría campo extra al modelo de Pine Script).
**Consecuencias:** La URL del webhook debe mantenerse privada. En producción usar HTTPS para evitar que el secret sea interceptado en tránsito.

---

### [2026-06-24] Confluence score: detecciones inline ligeras en lugar de re-usar los indicadores existentes

**Contexto:** Pine Script no permite compartir datos entre indicadores en tiempo real. El score necesitaba detectar todas las condiciones por sí solo.
**Decisión:** Implementar versiones ligeras de cada condición directamente en `confluence_score.pine`, sin duplicar la lógica completa de cada indicador individual.
**Por qué:** Las versiones completas (order_block.pine, fvg_detector.pine, etc.) usan arrays de persistencia y gestión de estado compleja. Para el score, una detección más simple per-barra es suficiente y mucho más concisa.
**Consecuencias:** El score puede diferir ligeramente de lo que muestran los indicadores individuales (más permisivo). El usuario debe usar la tabla del score como guía rápida y confirmar con los indicadores completos antes de entrar.

---

### [2026-06-24] Pares objetivo definidos: EURUSD y XAUUSD como foco principal

**Contexto:** El usuario especificó que el sistema debe operar principalmente EURUSD y XAUUSD.
**Decisión:** Todos los parámetros de detección se calibran y documentan con valores por defecto óptimos para estos dos activos. El sistema sigue siendo compatible con otros pares.
**Consecuencias:**
- EURUSD H1: ATR ≈ 10-20 pips → tolerancias y umbrales ajustados a esa escala
- XAUUSD H1: ATR ≈ $5-15 → los mismos parámetros ATR-relativos funcionan correctamente
- Los tooltips de cada indicador documentan los valores recomendados por activo y timeframe
- Tests de validación deben hacerse sobre EURUSD H1 y XAUUSD H1 como casos primarios

---

### [2026-06-24] Detector de liquidez: wick para barredura, ATR para EQH/EQL

**Contexto:** Fase 1 — detector de BSL/SSL con identificación de Equal Highs/Equal Lows.
**Decisión:** La barredura (sweep) se detecta con el WICK (`high > nivel` / `low < nivel`), no con el cierre. Los Equal Highs/Lows usan tolerancia `N × ATR` para adaptarse a EURUSD y XAUUSD sin cambiar parámetros.
**Por qué:** En SMC los stop losses se activan cuando el precio toca el nivel (wick), no cuando cierra. Un cierre por encima sería un BOS, no una toma de liquidez. El ATR normaliza la tolerancia entre EURUSD (~0.0015 H1) y XAUUSD (~$10 H1) automáticamente.
**Consecuencias:** Las alertas de "liquidez barrida" son el pre-filtro más valioso del sistema: señalan que el mercado tomó stops y puede revertir. La confluencia `SSL swept + OB alcista` o `BSL swept + OB bajista` es la entrada de mayor probabilidad según smc-concepts.md.

---

### [2026-06-24] Detector de S&D implementado con detección ATR base+impulso

**Contexto:** Fase 1 — detector de zonas de Supply & Demand (smc-concepts.md: base + impulso fuerte).
**Decisión:** Detección mediante ATR: vela "base" si cuerpo < `i_baseThresh × ATR`; "impulso" si cuerpo > `i_impulseThresh × ATR`. La zona = rango [low, high] de las velas de base consecutivas.
**Por qué:** El ATR normaliza la detección entre distintos instrumentos (EURUSD, NAS100, XAUUSD) y timeframes sin cambiar los umbrales. Alternativa descartada: detección por BOS — requeriría pivots y añadiría latencia innecesaria; el patrón base+impulso es suficiente según smc-concepts.md.
**Consecuencias:** `i_maxBaseLen` (max velas en la base) actúa como guarda de formación en la comprobación de mitigación. Si el impulso es inmediatamente seguido de un retroceso, la guarda `bar_index > baseStart + i_maxBaseLen + 1` evita falsos positivos. Los parámetros por defecto (base 0.5×ATR, impulso 1.5×ATR) son un punto de partida — el usuario debe calibrar por par y timeframe.

---

### [2026-06-24] Detector de FVG implementado con guarda de formación

**Contexto:** Fase 1 — detector de Fair Value Gaps alcistas y bajistas con mitigación.
**Decisión:** Se añade guarda `bar_index > fvgBars[i] + 2` antes de comprobar mitigación, para evitar falsos positivos en la misma barra de detección (especialmente en FVG bajistas donde `close >= high[0]` puede ser verdadero).
**Por qué:** Sin la guarda, un FVG bajista podría marcarse como mitigado inmediatamente si el close de la vela 3 coincide con su propio high. Con la guarda, la comprobación empieza en la barra siguiente al patrón completo.
**Consecuencias:** El filtro `i_minTicks` usa `syminfo.mintick` para ser universal entre pares (EURUSD, XAUUSD, NAS100). El valor por defecto de 5 ticks equivale a ~0.5 pips en EURUSD y ~1.25 puntos en NAS100.

---

### [2026-06-24] Detector de Order Blocks implementado con gestión de mitigación por arrays

**Contexto:** Fase 1 del roadmap — detector de OB alcista y bajista con estado activo/mitigado.
**Decisión:** Se usan arrays paralelos (`obHighs`, `obLows`, `obBoxes`, `obActive`...) para gestionar múltiples OBs activos simultáneamente.
**Por qué:** Un único OB por tipo no es suficiente; en un gráfico real coexisten múltiples zonas relevantes de OB no mitigadas. El límite configurable `i_maxOBs` evita saturar el gráfico.
**Consecuencias:** La función `f_findOB` escanea `i_lookback` barras hacia atrás desde el BOS — si el lookback es demasiado largo puede capturar velas OB no relacionadas con el impulso. El usuario debe calibrar este parámetro según el par y timeframe.

---

### [2026-06-24] CHoCH y BOS integrados en el detector de estructura de mercado

**Contexto:** El roadmap listaba "detector de estructura de mercado" y "detector de CHoCH/BOS" como dos items separados.
**Decisión:** Se implementaron ambos en un único archivo `pine/market_structure.pine`.
**Por qué:** CHoCH y BOS son consecuencias directas de la clasificación HH/HL/LH/LL — comparten las mismas variables de pivots. Separarlos en dos indicadores obligaría a duplicar toda la lógica de detección de pivots.
**Consecuencias:** El roadmap marca ambos items como completados. Los próximos indicadores (OB, FVG, S&D) importarán el sesgo de mercado de este indicador vía alertas o parámetros.

---

### [2026-06-24] Definición del stack tecnológico principal

**Contexto:** El sistema necesita análisis visual en tiempo real + lógica de riesgo + ejecución en broker FTMO.
**Opciones consideradas:**
- Pure Python con datos de broker API: descartado por falta de visualización gráfica nativa
- n8n + webhooks genéricos: descartado por complejidad de mantenimiento y falta de control
- Pine Script (TradingView) + Python backend + MT5: elegido

**Decisión:** Pine Script para detección visual en TradingView, Python para lógica de negocio y riesgo, MT5 como broker.
**Por qué:** FTMO proporciona cuentas MT5. TradingView es el estándar para análisis SMC visual. Python tiene el mejor ecosistema para datos financieros.
**Consecuencias:** El backend Python debe correr en Windows (limitación de MT5 API). El análisis visual queda ligado a TradingView (requiere plan Pro+ para webhooks).

---

### [2026-06-24] Elección de Smart Money Concepts como metodología única

**Contexto:** Necesidad de definir qué estrategia de trading implementa el sistema.
**Opciones consideradas:**
- Indicadores técnicos clásicos (MA, RSI, MACD): descartado — indicadores lagging, baja precisión
- Price Action clásico (soporte/resistencia, patrones de velas): descartado — subjetivo, difícil de automatizar consistentemente
- SMC (Order Blocks, CHoCH, FVG, S&D): elegido

**Decisión:** El sistema implementa Smart Money Concepts de forma pura, sin mezclar con indicadores clásicos.
**Por qué:** SMC es objetivable y automatizable (reglas claras de detección). Alineado con cómo opera el dinero institucional, que mueve el mercado real.
**Consecuencias:** No se implementarán indicadores como RSI o medias móviles. Toda la lógica de detección debe seguir las reglas definidas en [[smc-concepts.md]].

---

### [2026-06-24] Análisis top-down H4 → H1 → M15 como flujo obligatorio

**Contexto:** Definir en qué timeframes opera el sistema y en qué orden.
**Decisión:** H4 define el sesgo, H1 identifica la zona de entrada (OB), M15 confirma con BOS antes de entrar.
**Por qué:** El análisis multi-timeframe reduce falsas señales. H4 filtra el ruido de timeframes bajos. M15 evita entrar antes de confirmación.
**Consecuencias:** No se generarán señales en M1, M5 o M30. Todos los detectores deben soportar configuración de timeframe.

---

### [2026-06-24] Riesgo por operación fijado en 1% (100 EUR) con tope diario de 3%

**Contexto:** Necesidad de definir la gestión de riesgo del sistema sobre la cuenta de 10k EUR FTMO.
**Opciones consideradas:**
- 2% por operación: demasiado agresivo para FTMO (5 pérdidas seguidas = daily loss limit tocado)
- 0.5% por operación: conservador pero permite poco progreso hacia el profit target
- 1% por operación con tope diario de 3%: balance entre protección y progreso

**Decisión:** 1% de riesgo por operación, máximo 3% de riesgo diario total.
**Por qué:** Con 1% por operación necesitamos 5 pérdidas consecutivas para acercarnos al daily loss limit de FTMO (5%). El tope de 3% deja un buffer de 2% antes del límite real.
**Consecuencias:** El sistema bloqueará nuevas entradas si el P&L diario supera -300 EUR. Ver [[ftmo-rules.md]] para el checklist completo.

---

### [2026-06-23] Creación de la estructura de memoria del proyecto

**Contexto:** Proyecto nuevo desde cero, necesidad de mantener contexto persistente entre sesiones de Claude Code.
**Decisión:** CLAUDE.md como hub central + archivos específicos en `.claude/` para cada dominio.
**Por qué:** Evitar reexplicar el proyecto en cada sesión. Claude lee CLAUDE.md automáticamente al iniciar.
**Consecuencias:** Toda decisión importante debe registrarse aquí. El stack va en [[tech-stack.md]], las reglas de trading en [[ftmo-rules.md]], los conceptos SMC en [[smc-concepts.md]].
