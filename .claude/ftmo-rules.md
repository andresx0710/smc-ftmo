---
name: ftmo-rules
description: Reglas de la cuenta FTMO 10k EUR — límites de riesgo, targets y restricciones operativas CRÍTICAS
metadata:
  type: project
---

# Reglas FTMO — Cuenta 10.000 EUR

_Referenciado desde [[CLAUDE.md]]_
_Este archivo es CRÍTICO. Toda lógica de riesgo del sistema debe validarse contra estas reglas._

---

## Parámetros de la cuenta

| Parámetro | Valor |
|---|---|
| Balance inicial | 10.000 EUR |
| Firma de fondeo | FTMO |
| Modalidad | Normal (no Aggressive) |

---

## Reglas de pérdida — ABSOLUTAS (violarlas = cuenta eliminada)

| Regla | Límite | Valor en EUR | Acción del sistema |
|---|---|---|---|
| **Max Daily Loss** | 5% del balance inicial | **500 EUR/día** | Bloquear nuevas entradas si P&L diario ≤ -500 EUR |
| **Max Overall Loss** | 10% del balance inicial | **1.000 EUR total** | Bloquear sistema si equity ≤ 9.000 EUR |

> **Importante:** El Daily Loss se calcula desde el balance al inicio del día (EOD balance), no desde el balance inicial de la cuenta.

---

## Targets de beneficio por fase

| Fase | Target | Valor en EUR | Días mínimos | Días máximos |
|---|---|---|---|---|
| **Phase 1 — Challenge** | 10% | 1.000 EUR | 4 días | 30 días |
| **Phase 2 — Verification** | 5% | 500 EUR | 4 días | 60 días |
| **Funded Account** | Sin target fijo | — | Sin mínimo | Sin máximo |

---

## Reglas de gestión de riesgo del SISTEMA

Estas reglas son más conservadoras que los límites FTMO para añadir margen de seguridad:

| Parámetro | Regla del sistema | Por qué |
|---|---|---|
| **Riesgo por operación** | Máx 1% = 100 EUR | Permite 5 operaciones perdedoras antes de tocar el daily loss |
| **Riesgo máximo diario del sistema** | 3% = 300 EUR | Buffer de 200 EUR antes del límite FTMO de 500 EUR |
| **Riesgo máximo total abierto** | 2% = 200 EUR | Máx 2 posiciones abiertas simultáneas al 1% |
| **R:R mínimo** | 1:2 | Solo entrar si el beneficio potencial es al menos el doble del riesgo |
| **Posiciones simultáneas máx** | 2 | Evitar sobreexposición |

---

## Cálculo de tamaño de posición

```
Riesgo en EUR  = balance_actual × 0.01          (1%)
Tamaño (lotes) = riesgo_eur / (sl_pips × pip_value)

Ejemplo para EURUSD, SL de 20 pips:
  Riesgo = 10.000 × 0.01 = 100 EUR
  pip_value (lote estándar EURUSD) = 10 EUR/pip
  Tamaño = 100 / (20 × 10) = 0.5 lotes
```

---

## Restricciones operativas

| Restricción | Regla |
|---|---|
| **Noticias de alto impacto** | No abrir posiciones 15 min antes / después de noticias NFP, CPI, decisiones de tipos |
| **Fin de semana** | No mantener posiciones abiertas el viernes después de las 21:00 UTC |
| **Rollover nocturno** | Revisar swap antes de mantener posiciones overnight (especialmente en pares con diferencial alto) |
| **Días sin operar** | Permitido — no hay penalización por días de inactividad en la Funded Account |

---

## Checklist pre-entrada (el sistema DEBE validar todo antes de enviar orden)

- [ ] P&L diario actual > -300 EUR (margen de seguridad)
- [ ] Equity total > 9.200 EUR (margen de seguridad sobre el límite de 9.000 EUR)
- [ ] Riesgo abierto actual < 2% (< 200 EUR en posiciones abiertas)
- [ ] R:R de la operación ≥ 1:2
- [ ] No hay noticia de alto impacto en los próximos 15 minutos
- [ ] SL definido ANTES de calcular el tamaño

---

## Estado de la cuenta (actualizar manualmente)

**Fase actual:** `[ ] Challenge  [ ] Verification  [ ] Funded`
**Balance actual:** `10.000 EUR`
**P&L acumulado:** `0 EUR`
**Días operados:** `0`
