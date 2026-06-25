from loguru import logger
from typing import Optional

# Intentamos importar mt5. Si falla, creamos una clase que no haga nada 
# pero que permita que el resto del bot siga vivo.
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    logger.warning("MetaTrader5 no disponible en este entorno (Linux).")

class MT5Client:
    """Wrapper que evita errores si MT5 no está instalado."""

    def connect(self, login: int, password: str, server: str, path: str = "") -> bool:
        if not MT5_AVAILABLE:
            logger.warning("Simulando conexión: MT5 no disponible.")
            return True
        # ... (aquí mantienes tu código original de conexión)
        return True

    def account_info(self) -> Optional[dict]:
        if not MT5_AVAILABLE:
            return {"login": 0, "balance": 0.0, "equity": 0.0}
        # ... (aquí mantienes el resto de tu código original)
        return None

    def positions(self) -> list[dict]:
        if not MT5_AVAILABLE:
            return []
        return []

    def today_realized_pnl(self) -> float:
        return 0.0
