# SMC-FTMO — Bot de Trading Algorítmico

Sistema de trading basado en **Smart Money Concepts (SMC)** diseñado para gestionar una cuenta de fondeo FTMO de 10 000 EUR. Detecta Order Blocks, CHoCH, FVG y zonas institucionales en tiempo real usando MetaTrader 5, con filtro de noticias de Forex Factory y notificaciones push en Telegram.

## Índice

1. [Arquitectura](#arquitectura)
2. [Requisitos](#requisitos)
3. [Guía de despliegue paso a paso](#guía-de-despliegue)
4. [Referencia de parámetros](#referencia-de-parámetros)
5. [Gestión de riesgo FTMO](#gestión-de-riesgo-ftmo)
6. [Dashboard](#dashboard)
7. [Forex Factory](#forex-factory)
8. [Seguridad](#seguridad)
9. [Solución de problemas](#solución-de-problemas)

---

## Arquitectura

```
┌─────────────────────────────────────────────────────────────┐
│  Tu PC Windows (MetaTrader 5 instalado)                     │
│                                                             │
│  python -m backtest.run_live                                │
│    │                                                        │
│    ├── GET /config ──────────────────────────────────────►  │
│    │         ▲  credenciales MT5, Telegram, riesgo         │
│    │         │                                             │
│    └── POST /push (cada 60s) ───────────────────────────►  │
│                                                             │
└───────────────────────── Internet ──────────────────────────┘
                                │
                     ┌──────────▼──────────┐
                     │  Render / Railway   │
                     │  cloud/app.py       │
                     │  FastAPI + SQLite   │
                     │                     │
                     │  /setup ← configuras│
                     │  /      ← dashboard │
                     └─────────────────────┘
```

**El bot siempre corre en tu PC** (MetaTrader 5 es Windows-only). La nube guarda la configuración y sirve el dashboard.

---

## Requisitos

| Componente | Descripción |
|---|---|
| Windows 10/11 | Para ejecutar MetaTrader 5 y el bot |
| Python 3.10+ | `python --version` |
| MetaTrader 5 | Descarga desde [metatrader5.com](https://www.metatrader5.com) |
| Cuenta FTMO | Fase 1 (10 000 EUR) o cualquier cuenta MT5 |
| Bot de Telegram | Creado con [@BotFather](https://t.me/BotFather) |
| Cuenta Render | [render.com](https://render.com) |

---

## Guía de despliegue

### Paso 1 — Fork del repositorio

1. Abre [github.com/andresx0710/smc-ftmo](https://github.com/andresx0710/smc-ftmo)
2. Pulsa **Fork** (esquina superior derecha)
3. Clona tu fork:
   ```bash
   git clone https://github.com/TU_USUARIO/smc-ftmo.git
   cd smc-ftmo
   ```

---

### Paso 2 — Desplegar en Render

#### Opción A — Automático con render.yaml (recomendado)

1. Ve a [dashboard.render.com](https://dashboard.render.com) → **New** → **Blueprint**
2. Conecta tu repositorio de GitHub
3. Render detecta `render.yaml` y crea el servicio automáticamente
4. Espera ~3 minutos al build
5. Anota tu URL: `https://smc-ftmo-XXXXX.onrender.com`

#### Opción B — Configuración manual

1. **New** → **Web Service** → conecta tu repo
2. Rellena:
   - **Build Command:** `pip install -r cloud/requirements.txt`
   - **Start Command:** `uvicorn cloud.app:app --host 0.0.0.0 --port $PORT`
   - **Plan:** Starter ($7/mes, sin sleep) o Free
3. Añade estas variables de entorno:

| Variable | Cómo generarla |
|---|---|
| `PUSH_TOKEN` | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ACCESS_TOKEN` | `python -c "import secrets; print(secrets.token_hex(16))"` |
| `SECRET_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |

> **Plan Free de Render:** El servicio duerme tras 15 min sin peticiones. Como el bot hace POST cada 60 s, **no dormirá mientras el bot esté corriendo**. El plan Free es suficiente durante las horas de trading.

#### Opción C — Supabase como BD (plan Free sin disco)

Si usas el plan Free de Render (sin disco persistente), usa Supabase para persistir la configuración:

1. Crea cuenta en [supabase.com](https://supabase.com) (gratis)
2. Nuevo proyecto → **SQL Editor** → ejecuta:
   ```sql
   CREATE TABLE bot_config (
     id              SERIAL PRIMARY KEY,
     mt5_login       TEXT DEFAULT '',
     mt5_password    TEXT DEFAULT '',
     mt5_server      TEXT DEFAULT '',
     mt5_path        TEXT DEFAULT '',
     tg_token        TEXT DEFAULT '',
     tg_chat_id      TEXT DEFAULT '',
     symbol          TEXT DEFAULT 'EURUSD',
     tf_chain        TEXT DEFAULT 'D1,H1,M15,M5',
     min_score       INTEGER DEFAULT 5,
     sl_pips         REAL DEFAULT 20.0,
     rr              REAL DEFAULT 3.0,
     risk_pct        REAL DEFAULT 0.5,
     daily_limit_eur REAL DEFAULT 100.0,
     balance         REAL DEFAULT 10000.0,
     currency        TEXT DEFAULT 'EUR',
     use_ff          INTEGER DEFAULT 1,
     news_buffer_mins INTEGER DEFAULT 60,
     only_short      INTEGER DEFAULT 0,
     only_long       INTEGER DEFAULT 0,
     updated_at      TEXT DEFAULT ''
   );
   ```
3. **Project Settings** → **API** → copia `Project URL` y `anon public key`
4. En Render añade: `SUPABASE_URL` y `SUPABASE_KEY`

---

### Paso 3 — Configurar credenciales

1. Abre en el navegador:
   ```
   https://smc-ftmo-XXXXX.onrender.com/?key=TU_ACCESS_TOKEN
   ```
2. Serás redirigido a `/setup` automáticamente
3. Rellena el formulario:

   **MetaTrader 5**
   - Login: tu número de cuenta FTMO
   - Contraseña: tu contraseña de MT5
   - Servidor: `FTMO-Server3` (el que indique FTMO)

   **Telegram**
   - Bot Token: en [@BotFather](https://t.me/BotFather) → `/newbot`
   - Chat ID: en [@userinfobot](https://t.me/userinfobot)

   **Parámetros de riesgo:** los valores por defecto son conservadores y válidos para FTMO

4. Pulsa **Guardar configuración** → ✅

---

### Paso 4 — Ejecutar el bot localmente

#### Instalación

```bash
python -m venv .venv
.venv\Scripts\activate

pip install MetaTrader5 pandas matplotlib cryptography
```

#### Configuración local mínima

Crea `.env` en la raíz del proyecto con solo dos líneas:

```env
CLOUD_URL=https://smc-ftmo-XXXXX.onrender.com
CLOUD_TOKEN=TU_PUSH_TOKEN
```

El bot carga el resto (MT5, Telegram, riesgo) desde el cloud automáticamente.

#### Arrancar

```bash
python -m backtest.run_live
```

Con opciones adicionales que sobrescriben la config del cloud:

```bash
python -m backtest.run_live \
  --symbol EURUSD \
  --only-short \
  --use-forex-factory \
  --news-buffer-mins 60 \
  --dashboard-port 8765
```

---

## Referencia de parámetros

| Parámetro CLI | Default | Descripción |
|---|---|---|
| `--symbol` | `EURUSD` | Par operado |
| `--tf-chain` | `D1 H1 M15 M5` | Temporalidades SMC (mayor → menor) |
| `--min-score` | `5` | Score mínimo para abrir (1–7) |
| `--sl-pips` | `20` | Stop Loss en pips |
| `--rr` | `3.0` | Ratio Riesgo/Beneficio |
| `--risk-pct` | `0.5` | Riesgo por op (% balance) |
| `--daily-limit-eur` | `100` | Stop diario propio en EUR |
| `--balance` | `10000` | Balance inicial FTMO (no cambiar) |
| `--only-short` | — | Solo posiciones SHORT |
| `--only-long` | — | Solo posiciones LONG |
| `--use-forex-factory` | — | Filtro de noticias FF |
| `--news-buffer-mins` | `60` | Buffer ±min alrededor de noticia |
| `--dashboard-port` | `8765` | Puerto dashboard local |
| `--dry-run` | — | Simular sin órdenes reales |
| `--cloud-url` | `.env` | URL del servicio Render |
| `--cloud-token` | `.env` | PUSH_TOKEN del servicio |

---

## Gestión de riesgo FTMO

### Dos capas de protección

**Capa 1 — Stop diario propio (100 EUR)**
- El bot para automáticamente si pierdes 100 EUR en el día
- Se reactiva solo al día siguiente
- Mantiene una distancia segura del límite real de FTMO (300 EUR)

**Capa 2 — Suelo FTMO (9 000 EUR)**
- Si la equity cae por debajo de 9 000 EUR, bloqueo permanente
- Corresponde al 10% de drawdown máximo permitido por FTMO

### Reglas FTMO Fase 1 (10 000 EUR)

| Límite | FTMO real | Nuestro sistema |
|---|---|---|
| Pérdida diaria máx. | -300 EUR (3%) | **-100 EUR (stop propio)** |
| Drawdown máx. total | -1 000 EUR (10%) | Suelo 9 000 EUR |
| Objetivo beneficio | +1 000 EUR (10%) | — |

### Fase 2 (10 000 EUR verificado)

| Límite | Valor |
|---|---|
| Pérdida diaria máx. | -200 EUR (2%) |
| Drawdown máx. total | -500 EUR (5%) |
| Objetivo beneficio | +500 EUR (5%) |

---

## Dashboard

### Local
`http://localhost:8765/` — disponible mientras el bot corre en tu PC.

### Cloud (cualquier dispositivo)
```
https://TU-APP.onrender.com/?key=TU_ACCESS_TOKEN
```

Comparte esta URL por WhatsApp para ver el estado desde el móvil.

**El panel muestra:**
- Balance · Equity · P&L del día
- Barra FTMO (proximidad a 9 000 EUR)
- Barra límite diario (proximidad a -100 EUR)
- Semáforo noticias FF 🟢🟡🔴
- Sesión activa (Londres / Nueva York)
- Score SMC (LONG/SHORT vs umbral)
- Posiciones abiertas y últimas 10 operaciones
- Log del loop en tiempo real

---

## Forex Factory

Descarga el calendario de [Forex Factory](https://forexfactory.com) diariamente y bloquea nuevas entradas durante una ventana alrededor de cada noticia roja (alto impacto) de las divisas del par operado.

**Divisas monitorizadas por par:**
- `EURUSD` → EUR + USD
- `GBPUSD` → GBP + USD
- `XAUUSD` → USD
- `USDJPY` → USD + JPY

**Buffer recomendado:** 60 minutos para NFP, PCE, FOMC, PIB, IPC.

**Semáforo:**
- 🟢 Libre para operar
- 🟡 Noticia en 30–60 min (precaución)
- 🔴 Blackout activo (ejecución bloqueada)

---

## Seguridad

| Dato | Riesgo si se filtra |
|---|---|
| `PUSH_TOKEN` | Falsificación del estado del dashboard |
| `ACCESS_TOKEN` | Alguien ve tu P&L y posiciones |
| `SECRET_KEY` | Descifrado de credenciales en BD |
| `mt5_password` | Acceso a tu cuenta de trading |

**Reglas:**
- `.env` local está en `.gitignore` — **nunca lo subas a GitHub**
- Las contraseñas se cifran con AES-128 (Fernet) en la BD
- Rota `ACCESS_TOKEN` si dejas de compartir la URL con alguien

---

## Solución de problemas

### El bot detecta score = 0 siempre

El gate D1 necesita varios meses de historial para activarse. Con solo 2 días de datos M5 (resampleados a D1) el gate bloquea todas las señales. En producción, cuando MT5 tenga historial acumulado, esto se resuelve solo.

Prueba provisional sin gate:
```bash
python -m backtest.run_live --min-score 3 --tf-chain M5
```

### `MT5 no disponible para D1 → derivando desde M5`

Normal cuando el broker no tiene barras D1 disponibles en la sesión actual. El bot resamplea automáticamente. La calidad mejora con historial acumulado.

### Telegram 401 Unauthorized

El token tiene un formato incorrecto (espacios, caracteres extra). Formato correcto:
```
1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ
```
Configúralo desde `/setup` en lugar de escribirlo a mano.

### `BLOQUEADO: Límite diario alcanzado`

El bot se reactiva automáticamente al día siguiente (medianoche UTC). Para forzar la reanudación:
```bash
python -m backtest.run_live --daily-limit-eur 200
```

### Render: datos de config perdidos tras redeploy

En el plan Free no hay disco persistente. Usa Supabase (Opción C) o actualiza al plan Starter con disco.

### `ForexFactory 429 Too Many Requests`

El bot reintenta con backoff automático. Si el error persiste al arrancar, espera 5 minutos y vuelve a iniciar.

---

## Créditos

Desarrollado con [Claude Code](https://claude.ai/code).

**Stack:** Python 3.11 · MetaTrader5 · FastAPI · SQLite/Supabase · Telegram Bot API · Fernet (AES-128)
