"""MT5 connection and account data reader.

MT5 Python library is synchronous and Windows-only.
Wrap every call in asyncio.to_thread() to avoid blocking FastAPI's event loop.
"""

from datetime import datetime, timezone
from typing import Optional

import MetaTrader5 as mt5
from loguru import logger


class MT5Client:
    """Thin wrapper around the MetaTrader5 library."""

    def connect(
        self,
        login: int,
        password: str,
        server: str,
        path: str = "",
    ) -> bool:
        kwargs: dict = {"login": login, "password": password, "server": server}
        if path:
            kwargs["path"] = path

        if not mt5.initialize(**kwargs):
            logger.error("MT5 initialize() failed: {}", mt5.last_error())
            return False

        info = mt5.account_info()
        if info is None:
            logger.error("MT5 account_info() failed after connect: {}", mt5.last_error())
            mt5.shutdown()
            return False

        logger.info(
            "MT5 conectado | login={} name={} server={} currency={}",
            info.login, info.name, info.server, info.currency,
        )
        return True

    def disconnect(self) -> None:
        mt5.shutdown()
        logger.info("MT5 desconectado")

    def account_info(self) -> Optional[dict]:
        info = mt5.account_info()
        if info is None:
            logger.error("MT5 account_info() error: {}", mt5.last_error())
            return None
        return {
            "login":       info.login,
            "name":        info.name,
            "server":      info.server,
            "currency":    info.currency,
            "balance":     info.balance,
            "equity":      info.equity,
            "margin":      info.margin,
            "free_margin": info.margin_free,
            "profit":      info.profit,     # float P&L of open positions
            "leverage":    info.leverage,
        }

    def positions(self) -> list[dict]:
        """Returns all open positions as dicts."""
        raw = mt5.positions_get()
        if raw is None:
            return []
        result = []
        for p in raw:
            result.append({
                "ticket":     p.ticket,
                "symbol":     p.symbol,
                "type":       "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                "volume":     p.volume,
                "open_price": p.price_open,
                "current":    p.price_current,
                "sl":         p.sl,
                "tp":         p.tp,
                "profit":     p.profit,
                "swap":       p.swap,
                "comment":    p.comment,
            })
        return result

    def today_realized_pnl(self) -> float:
        """Realized P&L from deals closed today (server UTC day boundary)."""
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        deals = mt5.history_deals_get(day_start, now)
        if deals is None:
            return 0.0
        # DEAL_ENTRY_OUT = closed trade; skip deposits/withdrawals
        return sum(
            d.profit for d in deals
            if d.entry == mt5.DEAL_ENTRY_OUT
        )
