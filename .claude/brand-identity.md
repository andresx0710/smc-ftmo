---
name: brand-identity
description: Identidad del sistema de trading SMC-FTMO — nombre, misión y valores
metadata:
  type: project
---

# Identidad del Sistema

_Referenciado desde [[CLAUDE.md]]_

---

## Nombre del proyecto

**Nombre de trabajo:** `SMC Engine` _(provisional — pendiente de definir nombre final)_
**Tagline:** `"Análisis institucional. Disciplina de máquina. Cuenta de fondeo protegida."`

---

## Misión

Automatizar el análisis técnico basado en Smart Money Concepts para que un trader individual pueda pasar y gestionar una cuenta de fondeo FTMO de 10.000 EUR sin depender de decisiones emocionales, operando con la precisión y disciplina de un sistema institucional.

---

## Valores del sistema

1. **Disciplina sobre ganancia** — Respetar las reglas FTMO es no-negociable, aunque eso signifique perderse una entrada.
2. **Precisión institucional** — Solo operamos donde el dinero inteligente opera (OB, S&D, CHoCH).
3. **Riesgo controlado primero** — El sistema calcula el riesgo antes que el beneficio potencial.
4. **Transparencia del análisis** — Cada señal debe ser trazable: qué se detectó, por qué y en qué timeframe.

---

## Tono del sistema (logs, alertas, dashboards)

| Atributo | Estilo elegido |
|---|---|
| Formalidad | Técnico y preciso |
| Mensajes de alerta | Cortos, directos, sin adornos |
| Mensajes de error | Explícitos sobre la causa, nunca vagos |
| Nomenclatura | Inglés para conceptos SMC (OB, CHoCH, FVG), español para UI |

**Ejemplos de mensajes que SÍ representan el sistema:**
- `"OB bajista detectado en H4 — zona: 1.0842-1.0851 — confluencia con FVG"`
- `"CHoCH alcista confirmado en H1 — BOS previo en 1.0820"`
- `"Riesgo diario al 80% — entrada bloqueada"`

**Mensajes que NO representan el sistema:**
- `"¡Gran oportunidad de compra!"`
- `"Señal fuerte 🚀"`
- Cualquier mensaje que sugiera certeza absoluta en el mercado

---

## Competidores / referencias

| Referencia | Lo que hacen bien | Nuestro diferenciador |
|---|---|---|
| Indicadores SMC genéricos de TradingView | Detección básica de OB y CHoCH | Integración completa con reglas FTMO y gestión de riesgo automática |
| Bots de trading genéricos | Automatización de órdenes | Análisis estructural SMC multiframe, no solo cruces de medias |
| LuxAlgo / SMC Library | Indicadores visuales potentes | Sistema end-to-end: análisis + validación FTMO + alertas de entrada |
