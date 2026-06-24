---
name: target-users
description: Perfil del trader objetivo — usuario del sistema SMC-FTMO
metadata:
  type: project
---

# Usuarios y Mercado

_Referenciado desde [[CLAUDE.md]]_

---

## Fase actual: herramienta personal

El sistema es en primera instancia una **herramienta para uso propio** del desarrollador — pasar y gestionar la cuenta FTMO de 10k EUR. Una vez validado, puede evolucionar a SaaS para traders con fondeo.

---

## Usuario principal (fase actual)

**Perfil:** Trader individual con cuenta de fondeo FTMO activa o en proceso de Challenge.

**Conocimientos previos:**
- Conoce y opera con Smart Money Concepts (OB, CHoCH, S&D, FVG, liquidez)
- Familiarizado con TradingView y sus herramientas de análisis
- Entiende las reglas de FTMO (daily loss, drawdown, profit target)
- Puede no tener experiencia avanzada en programación

**Problema principal que resuelve el sistema:**
1. El análisis manual de múltiples timeframes es lento y propenso a errores emocionales
2. Identificar confluencias SMC consistentemente requiere disciplina que la emoción del mercado sabotea
3. Cumplir las reglas FTMO bajo presión (especialmente el daily loss limit) es difícil manualmente

**Jobs to be done:**
1. Recibir señales de entrada validadas por SMC sin tener que analizar el gráfico desde cero
2. Saber en todo momento cuánto riesgo lleva acumulado y si puede abrir nuevas operaciones
3. Pasar el Challenge FTMO en los tiempos establecidos sin violar ninguna regla

**Pares objetivo principales:** EURUSD y XAUUSD (Gold)
- EURUSD: par más líquido del mundo, spreads bajos, comportamiento SMC muy limpio
- XAUUSD: alta volatilidad intradía, movimientos SMC amplios, ideal para objetivos de 1:3+

---

## Usuario futuro (SaaS — fase post-MVP validado)

**Perfil:** Traders con cuentas de fondeo (FTMO, MyForexFunds, The Funded Trader) que operan con SMC.

**Segmento:** B2C — traders retail con capital de fondeo entre 10k y 100k EUR/USD.

**Canal de adquisición probable:** YouTube (tutoriales SMC), comunidades de Discord/Telegram de trading, TikTok de finanzas.

---

## Lo que el usuario NO es

- No es un trader algorítmico puro sin conocimiento de SMC — el sistema asume que el usuario entiende las señales que recibe
- No es un inversor pasivo (hold) — es un trader activo intradía/swingtrading
- No busca un bot 100% autónomo sin supervisión humana — el sistema es **asistencia y automatización de análisis**, no trading autónomo

---

## Métricas de éxito del usuario

- Pasar el Challenge FTMO de 10k EUR (10% profit target, sin violar daily loss ni max drawdown)
- Pasar la Verification FTMO (5% profit target, mismas restricciones)
- Consistencia: mínimo 4 días de trading por fase
- Tasa de señales válidas: >60% de las señales detectadas resultan en movimientos confirmados
