---
name: smc-concepts
description: Glosario de Smart Money Concepts (SMC) y reglas de detección para el motor de análisis
metadata:
  type: project
---

# Smart Money Concepts — Glosario y Reglas de Detección

_Referenciado desde [[CLAUDE.md]]_
_Este archivo define exactamente qué es cada concepto SMC y cómo debe detectarlo el sistema._

---

## Estructura de mercado

### Higher High (HH) / Higher Low (HL) — Tendencia alcista
- **Definición:** Precio hace máximos y mínimos ascendentes
- **Detección:** `high[i] > high[i-1]` y `low[i] > low[i-1]` consecutivos

### Lower High (LH) / Lower Low (LL) — Tendencia bajista
- **Definición:** Precio hace máximos y mínimos descendentes
- **Detección:** `high[i] < high[i-1]` y `low[i] < low[i-1]` consecutivos

---

## CHoCH — Change of Character

**Definición:** Ruptura de la estructura de mercado en sentido contrario a la tendencia previa. Es la primera señal de un posible cambio de tendencia.

**Reglas de detección:**
- En tendencia alcista: precio rompe el último HL → CHoCH bajista
- En tendencia bajista: precio rompe el último LH → CHoCH alcista
- **La vela que rompe debe CERRAR por encima/debajo del nivel**, no solo tocarlo

**Diferencia con BOS:**
- CHoCH = cambio de carácter (posible reversión)
- BOS = Break of Structure (continuación de tendencia confirmada)

**Timeframes de relevancia:** H4 (CHoCH de alta confluencia), H1 (CHoCH de entrada)

---

## BOS — Break of Structure

**Definición:** Precio rompe el último HH (en tendencia alcista) o LL (en tendencia bajista). Confirma que la tendencia continúa.

**Reglas de detección:**
- En tendencia alcista: precio cierra por encima del último HH → BOS alcista
- En tendencia bajista: precio cierra por debajo del último LL → BOS bajista

**Uso en el sistema:** El BOS después de un CHoCH confirma la nueva tendencia. El BOS dentro de una tendencia es señal de continuación.

---

## Order Block (OB)

**Definición:** Última vela bajista antes de un movimiento alcista fuerte (OB alcista), o última vela alcista antes de un movimiento bajista fuerte (OB bajista). Representa una zona donde el dinero institucional colocó órdenes.

**Reglas de detección:**
- **OB alcista:** Última vela roja (close < open) inmediatamente antes de un impulso alcista que rompe estructura. La zona válida es el rango `[low, high]` de esa vela.
- **OB bajista:** Última vela verde (close > open) inmediatamente antes de un impulso bajista que rompe estructura. La zona válida es el rango `[low, high]` de esa vela.

**Validación de un OB:**
1. El impulso posterior debe romper al menos el swing anterior (BOS)
2. El OB no debe haber sido mitigado (precio ya tocó y cerró dentro del rango)
3. Mayor confluencia si el OB coincide con FVG o zona S&D

**Mitigación:** Un OB se considera "usado" (mitigado) cuando el precio cierra dentro de su rango. Después de la primera mitigación, el OB pierde validez como zona de entrada.

---

## Fair Value Gap (FVG) / Imbalance

**Definición:** Desequilibrio entre oferta y demanda visible como un "hueco" en el precio que tiende a rellenarse. Se forma en una secuencia de 3 velas donde la mecha de la vela 1 y la mecha de la vela 3 no se solapan.

**Reglas de detección:**
- **FVG alcista:** `low[2] > high[0]` (hueco entre mecha inferior de vela 3 y mecha superior de vela 1)
- **FVG bajista:** `high[2] < low[0]` (hueco entre mecha superior de vela 3 y mecha inferior de vela 1)
- La zona del FVG es `[high[0], low[2]]` (alcista) o `[high[2], low[0]]` (bajista)

**Uso:** El precio tiende a volver a rellenar el FVG. Se usa como zona de reentrada o confluencia con OB.

---

## Supply & Demand Zones (S&D)

**Definición:**
- **Zona de Demanda:** Área donde la demanda superó a la oferta, generando un impulso alcista fuerte. Similar al OB pero de mayor dimensión temporal.
- **Zona de Oferta:** Área donde la oferta superó a la demanda, generando un impulso bajista fuerte.

**Reglas de detección:**
- Identificar base (consolidación lateral) seguida de un movimiento fuerte (impulso)
- La zona es el rango de la base (consolidación)
- Cuanto más fuerte y largo el impulso posterior, más válida la zona

**Diferencia con OB:**
- OB: zona de 1 vela, más precisa
- S&D: zona más amplia que puede incluir varias velas de consolidación

---

## Liquidez

**Definición:** Concentración de stop losses de retail traders que el mercado (institucional) busca para ejecutar sus propias órdenes.

**Tipos:**
- **BSL (Buy-Side Liquidity):** Stop losses de posiciones cortas acumulados por encima de máximos anteriores (equal highs, swing highs)
- **SSL (Sell-Side Liquidity):** Stop losses de posiciones largas acumulados por debajo de mínimos anteriores (equal lows, swing lows)

**Uso en el sistema:** El precio suele moverse hacia zonas de liquidez antes de revertir. Una entrada en OB con confirmación de que el precio ya tomó liquidez tiene mayor probabilidad.

---

## Premium & Discount

**Definición:** División del rango entre el último swing high y swing low.
- **Premium (>50%):** Zona cara — buscar ventas / OB bajistas
- **Discount (<50%):** Zona barata — buscar compras / OB alcistas
- **Equilibrium (50%):** Zona neutral

**Regla del sistema:** Solo comprar en Discount, solo vender en Premium (respecto al rango del HTF).

---

## Confluencia SMC (mínimo requerido para señal válida)

Para que el sistema genere una señal de entrada, deben confluir al menos **3 de los siguientes elementos:**

| Factor | Peso |
|---|---|
| CHoCH en HTF (H4) confirmado | Alto |
| OB en la zona de entrada | Alto |
| FVG dentro o cerca del OB | Medio |
| Precio en zona de Discount/Premium correcta | Medio |
| Liquidez barrida antes de la entrada | Alto |
| BOS de confirmación en LTF (M15) | Medio |
| Zona S&D alineada con el OB | Medio |

**Señal inválida si:** El OB ya fue mitigado, no hay CHoCH previo en H4, o el precio está en zona neutral (equilibrium) sin dirección clara.

---

## Análisis Top-Down (flujo obligatorio del sistema)

```
H4 → Determinar tendencia principal (HH/HL o LH/LL)
   → Identificar CHoCH si hay reversión posible
   → Marcar zonas S&D y OB de alta temporalidad

H1 → Confirmar estructura alineada con H4
   → Identificar OB de entrada
   → Verificar FVG y liquidez

M15 → Esperar BOS de confirmación en la dirección de H4/H1
    → Afinar entrada en el OB de M15 o H1
    → Calcular SL por debajo/encima del OB
    → Calcular TP en la siguiente zona de liquidez o S&D opuesta
```
