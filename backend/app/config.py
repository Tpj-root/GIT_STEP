"""Configuration: env-backed settings plus the two per-mode trading configs."""
from __future__ import annotations
from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BrokerKind(str, Enum):
    paper = "paper"
    mt5 = "mt5"
    deriv = "deriv"


class Mode(str, Enum):
    manual = "manual"
    auto = "auto"


class Settings(BaseSettings):
    """Process-level settings. Credentials live here and nowhere else."""
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    deriv_app_id: str = "1089"
    deriv_ws_url: str = "wss://ws.derivws.com/websockets/v3"

    # Deriv API token (Settings > API token on deriv.com). Needs the `read` and
    # `trade` scopes. A token is bound to ONE account, so a demo (VRTC) token
    # can only ever touch the demo account -- that is the safety property to
    # rely on, not a config flag.
    deriv_api_token: Optional[str] = None
    deriv_contract_type: str = "MULT"     # MULT | TURBOS
    deriv_multiplier: int = 100

    broker: BrokerKind = BrokerKind.paper
    mt5_login: Optional[int] = None
    mt5_password: Optional[str] = None
    mt5_server: Optional[str] = None

    db_path: str = "trading.db"

    # hard caps the UI can never exceed -- enforced server-side
    hard_max_lots: float = 1.0
    hard_max_daily_loss: float = 1000.0
    stale_tick_seconds: float = 10.0
    counter_reset_utc_hour: int = Field(0, ge=0, le=23)

    @property
    def ws_url(self) -> str:
        return f"{self.deriv_ws_url}?app_id={self.deriv_app_id}"


SignalAction = Literal["reverse", "open-only", "close-only"]


class ModeConfig(BaseModel):
    """Per-mode trading parameters. Auto and manual are kept separate on purpose:
    sharing them lets a manual experiment silently rearm automated execution."""
    lots: float = Field(0.01, gt=0)
    stop_loss_points: Optional[float] = Field(50, gt=0)
    take_profit_points: Optional[float] = Field(100)
    max_concurrent_positions: int = Field(1, ge=1, le=5)
    max_daily_loss: Optional[float] = Field(50, gt=0)
    max_trades_per_day: Optional[int] = Field(20, gt=0)
    signal_action: SignalAction = "reverse"
    close_and_reverse_on_opposite: bool = True

    @field_validator("take_profit_points")
    @classmethod
    def _tp(cls, v):
        if v is not None and v <= 0:
            raise ValueError("take_profit_points must be > 0 or null (disabled)")
        return v


class AutoModeConfig(ModeConfig):
    """Auto mode makes the optional guards mandatory. A bot with no loss limit,
    no trade cap and no stop is not a strategy, it is an open tap."""
    @model_validator(mode="after")
    def _require_guards(self):
        missing = [n for n in ("stop_loss_points", "max_daily_loss", "max_trades_per_day")
                   if getattr(self, n) is None]
        if missing:
            raise ValueError(f"auto mode requires: {', '.join(missing)}")
        return self


class ConfigBundle(BaseModel):
    manual: ModeConfig = ModeConfig()
    auto: AutoModeConfig = AutoModeConfig()


settings = Settings()
