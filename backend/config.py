from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Telegram (requerido para señales SMC)
    telegram_bot_token: str
    telegram_chat_id: str
    webhook_secret: str = ""

    # MT5 (opcional — sólo en Windows con MetaTrader5 instalado en el mismo PC)
    # Si no se configura, el servidor funciona únicamente como webhook + Telegram.
    mt5_login:            Optional[int] = None
    mt5_password:         Optional[str] = None
    mt5_server:           Optional[str] = None
    mt5_path:             str = ""   # ruta a terminal64.exe (vacío = ruta por defecto)
    mt5_monitor_interval: int = 30   # segundos entre comprobaciones de la cuenta

    @property
    def mt5_configured(self) -> bool:
        return (
            self.mt5_login is not None
            and bool(self.mt5_password)
            and bool(self.mt5_server)
        )


settings = Settings()
