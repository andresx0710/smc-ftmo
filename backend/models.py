from pydantic import BaseModel, Field
from typing import Literal


class SMCSignal(BaseModel):
    """Payload JSON enviado por Pine Script vía alert() de TradingView."""

    action: Literal["LONG", "SHORT"]
    symbol: str                        # e.g. "EURUSD", "XAUUSD"
    tf: str                            # timeframe de TradingView: "60"=H1, "240"=H4
    score: int = Field(ge=0, le=7)    # número de condiciones activas (0-7)
    price: float                       # precio de cierre en el momento de la señal

    # Condiciones individuales (smc-concepts.md)
    choch: bool   # CHoCH confirmado [Alto]
    ob: bool      # Order Block en zona [Alto]
    liq: bool     # Liquidez barrida [Alto]
    fvg: bool     # Fair Value Gap reciente [Medio]
    pd: bool      # Precio en zona correcta (Discount/Premium) [Medio]
    bos: bool     # BOS de confirmación [Medio]
    sd: bool      # Zona S&D alineada [Medio]

    @property
    def active_conditions(self) -> list[str]:
        """Retorna los nombres de las condiciones activas para el mensaje de Telegram."""
        labels = {
            "choch": ("CHoCH", "Alto"),
            "ob":    ("OB en zona", "Alto"),
            "liq":   ("Liq. barrida", "Alto"),
            "fvg":   ("FVG", "Medio"),
            "pd":    ("Precio P/D", "Medio"),
            "bos":   ("BOS confirmación", "Medio"),
            "sd":    ("S&D alineada", "Medio"),
        }
        result = []
        for key, (name, weight) in labels.items():
            value = getattr(self, key)
            result.append((name, weight, value))
        return result

    @property
    def timeframe_label(self) -> str:
        """Convierte el timeframe de TradingView a una etiqueta legible."""
        _map = {
            "1": "M1", "3": "M3", "5": "M5", "15": "M15", "30": "M30",
            "60": "H1", "120": "H2", "240": "H4", "480": "H8",
            "720": "H12", "1D": "D1", "D": "D1", "1W": "W1", "W": "W1",
        }
        return _map.get(self.tf, self.tf)

    @property
    def score_bar(self) -> str:
        """Genera barra visual: '●●●●○○○' para score=4."""
        return "●" * self.score + "○" * (7 - self.score)


class OrderRequest(BaseModel):
    """Payload para POST /order — coloca una orden en MT5 (Phase 3).

    El tamaño de posición (lotes) se calcula automáticamente en main.py
    usando el balance actual y el presupuesto diario restante (1% del balance,
    capado por el límite FTMO — ftmo-rules.md).
    """

    symbol:  str                         # "EURUSD", "XAUUSD", etc.
    action:  Literal["BUY", "SELL"]
    sl_pips: float = Field(gt=0, description="SL en pips (EURUSD) o dólares (XAUUSD)")
    rr:      float = Field(default=2.0, ge=1.0, description="R:R ratio — mínimo 1:2 (ftmo-rules.md)")
    comment: str   = "SMC"
