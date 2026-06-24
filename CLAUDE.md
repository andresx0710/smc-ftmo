# CLAUDE.md — Hub Central del Proyecto

Este archivo es el punto de entrada para Claude en cada conversación.
Todo lo que Claude necesita saber sobre este proyecto está referenciado aquí.

---

## ¿Qué es este proyecto?

Sistema de trading algorítmico basado en **Smart Money Concepts (SMC)** diseñado para pasar y gestionar una cuenta de fondeo de **10.000 EUR en FTMO**. Automatiza el análisis de gráficos de TradingView para identificar Order Blocks, zonas de oferta/demanda, cambios de estructura (CHoCH) y tendencias institucionales, ejecutando operaciones bajo las reglas estrictas de riesgo de FTMO.

**Estado actual:** `[x] Ideación  [ ] MVP  [ ] Beta  [ ] Producción`

---

## Archivos de memoria del proyecto

| Archivo | Contenido |
|---|---|
| [Identidad de Marca](.claude/brand-identity.md) | Nombre, misión, valores del sistema |
| [Usuarios y Mercado](.claude/target-users.md) | Perfil del trader objetivo |
| [Stack Tecnológico](.claude/tech-stack.md) | Pine Script, Python, TradingView, MT5 |
| [Reglas y Convenciones](.claude/rules.md) | Coding style, commits, reglas para Claude |
| [Reglas FTMO + Gestión de Riesgo](.claude/ftmo-rules.md) | **CRÍTICO** — Límites de la cuenta 10k EUR |
| [Conceptos SMC](.claude/smc-concepts.md) | **CRÍTICO** — Glosario y reglas de detección SMC |
| [Historial de Decisiones](.claude/history.md) | Por qué elegimos X, pivots, aprendizajes |
| [Roadmap y Features](.claude/roadmap.md) | Prioridades, backlog, versiones |

---

## Instrucciones para Claude

- **SIEMPRE** leer [`ftmo-rules.md`](.claude/ftmo-rules.md) antes de proponer cualquier lógica de entrada/salida o gestión de riesgo.
- **SIEMPRE** leer [`smc-concepts.md`](.claude/smc-concepts.md) antes de implementar cualquier lógica de detección técnica.
- Antes de proponer una solución técnica, revisar [`tech-stack.md`](.claude/tech-stack.md) para no contradecir las decisiones tomadas.
- Todo código debe seguir las convenciones de [`rules.md`](.claude/rules.md).
- Si se toma una decisión importante (de producto, arquitectura o trading), registrarla en [`history.md`](.claude/history.md).
- **Nunca sugerir estrategias que violen las reglas FTMO** — ante la duda, la cuenta de fondeo tiene prioridad absoluta sobre el potencial de ganancia.
- No proponer features que contradigan el foco del MVP en [`roadmap.md`](.claude/roadmap.md).
