"""
ForexBot Configuration Module
=============================
Handles MT5 credentials, risk parameters, symbol pip/point specifications,
session filtering, fixed/dynamic lot sizing, and SLK/CRT multi-timeframe settings.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple
import os


# ---------------------------------------------------------------------------
# Base Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# MetaTrader 5 Connection & Terminal Config
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MT5Config:
    """Account credentials and MT5 terminal settings."""
    LOGIN: int = int(os.getenv("MT5_ACCOUNT") or os.getenv("MT5_LOGIN", "5055872290"))
    PASSWORD: str = os.getenv("MT5_PASSWORD", "RhPwCr*0")
    SERVER: str = os.getenv("MT5_SERVER", "MetaQuotes-Demo")
    
    PATH: str = os.getenv("MT5_PATH", "")
    MAGIC_NUMBER: int = 101202           # Unique ID to identify bot trades
    SLIPPAGE_POINTS: int = 20            # Allowed slippage in points (2 pips on FX)
    TIMEOUT_MS: int = 60000              # MT5 API timeout in ms
    PORTABLE: bool = False


# ---------------------------------------------------------------------------
# Cloud & Web Dashboard Configuration
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class WebConfig:
    """Settings for Cloud/Heroku web dashboard and health monitoring."""
    PORT: int = int(os.getenv("PORT", "8080"))
    HOST: str = os.getenv("HOST", "0.0.0.0")
    EXECUTION_MODE: str = "PAPER" if (os.getenv("EXECUTION_MODE", "").upper() == "PAPER" or os.getenv("BOT_MODE", "").upper() == "PAPER") else "LIVE"
    BOT_MODE: str = EXECUTION_MODE



# ---------------------------------------------------------------------------
# Global Risk Management Configuration
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RiskConfig:
    """
    Risk parameters enforced across live trading and backtesting.
    Adheres strictly to Prop Firm and capital preservation guidelines.
    """
    # Fractional Risk per trade when dynamic sizing is enabled
    RISK_PER_TRADE: float = 0.01
    
    # Maximum allowed daily drawdown from starting daily balance (0.045 = 4.5%)
    GLOBAL_DAILY_DRAWDOWN_LIMIT: float = 0.045
    
    # Maximum open positions across all symbols concurrently
    MAX_OPEN_POSITIONS: int = 3
    
    # Maximum open positions allowed per individual symbol
    MAX_POSITIONS_PER_SYMBOL: int = 1
    
    # Spread guard: Max allowable spread in pips before skipping a trade signal
    MAX_SPREAD_PIPS: float = 3.5

    # Default fixed lot sizing as requested by strategy spec
    DEFAULT_FIXED_LOTS: Dict[str, float] = field(default_factory=lambda: {
        "EURUSD": 0.10,
        "GBPUSD": 0.10,
        "XAUUSD": 0.02,
    })


# ---------------------------------------------------------------------------
# Symbol Specifications (FX vs Commodities)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SymbolSpec:
    """
    Detailed physical and mathematical specifications for each symbol.
    Differentiates 5-digit FX pairs from 2/3-digit Gold (XAUUSD) contracts.
    """
    symbol: str
    digits: int              # Number of decimal places (5 for EURUSD/GBPUSD, 2 for XAUUSD)
    pip_size: float          # Standard 1 pip price move (0.00010 for FX, 0.10 for Gold)
    point_size: float        # Minimum broker price change (0.00001 for 5-digit FX, 0.01 for Gold)
    contract_size: float     # Units per 1.0 standard lot (100,000 for FX, 100 oz for Gold)
    min_lot: float = 0.01    # Broker minimum volume
    max_lot: float = 100.0   # Broker maximum volume
    lot_step: float = 0.01   # Volume increment step
    fixed_lot: float = 0.10  # Default fixed lot size for user strategy
    default_sl_pips: float = 10.0   # Tight Stop Loss in pips (e.g. 10 pips = $10 on 0.10 lots)
    default_tp_pips: float = 30.0   # 1:3 RR Take Profit (30 pips = $30 on 0.10 lots)
    default_tp2_pips: float = 50.0  # 1:5 RR Runner (50 pips = $50 on 0.10 lots)
    
    @property
    def points_per_pip(self) -> float:
        """Returns the number of points in 1 standard pip."""
        return self.pip_size / self.point_size

    def pips_to_price_delta(self, pips: float) -> float:
        """Convert a pip quantity into absolute price movement."""
        return pips * self.pip_size

    def price_delta_to_pips(self, price_delta: float) -> float:
        """Convert an absolute price difference into pips."""
        return abs(price_delta) / self.pip_size

    def round_price(self, price: float) -> float:
        """Round price to valid broker decimal places."""
        return round(price, self.digits)


# Active Trading Symbols Configuration
SUPPORTED_SYMBOLS: Dict[str, SymbolSpec] = {
    "EURUSD": SymbolSpec(
        symbol="EURUSD",
        digits=5,
        pip_size=0.00010,
        point_size=0.00001,
        contract_size=100000.0,
        min_lot=0.01,
        max_lot=100.0,
        lot_step=0.01,
        fixed_lot=0.05,             # 0.05 lots ($5.00 risk on 10p SL, ~$57 margin required)
        default_sl_pips=10.0,       # 10 pips * 0.05 lot = $5.00 Risk
        default_tp_pips=30.0,       # 30 pips * 0.05 lot = $15.00 Reward (1:3 RR)
        default_tp2_pips=50.0       # 50 pips * 0.05 lot = $25.00 Reward (1:5 RR)
    ),
    "GBPUSD": SymbolSpec(
        symbol="GBPUSD",
        digits=5,
        pip_size=0.00010,
        point_size=0.00001,
        contract_size=100000.0,
        min_lot=0.01,
        max_lot=100.0,
        lot_step=0.01,
        fixed_lot=0.05,             # 0.05 lots ($5.00 risk on 10p SL, ~$66 margin required)
        default_sl_pips=10.0,       # 10 pips * 0.05 lot = $5.00 Risk
        default_tp_pips=30.0,       # 30 pips * 0.05 lot = $15.00 Reward (1:3 RR)
        default_tp2_pips=50.0       # 50 pips * 0.05 lot = $25.00 Reward (1:5 RR)
    ),
    "XAUUSD": SymbolSpec(
        symbol="XAUUSD",
        digits=2,            # 2 decimals (e.g. 2350.50)
        pip_size=0.10,       # 1 pip in gold = $0.10 per ounce
        point_size=0.01,     # 1 point = $0.01
        contract_size=100.0, # 1 standard lot = 100 troy ounces
        min_lot=0.01,
        max_lot=50.0,
        lot_step=0.01,
        fixed_lot=0.01,             # 0.01 lots ($5.00 risk on 50p SL, ~$43 margin required)
        default_sl_pips=50.0,       # 50 pips * 0.01 lot = $5.00 Risk
        default_tp_pips=150.0,      # 150 pips * 0.01 lot = $15.00 Reward (1:3 RR)
        default_tp2_pips=250.0      # 250 pips * 0.01 lot = $25.00 Reward (1:5 RR)
    ),
}


# ---------------------------------------------------------------------------
# Session & Trading Hours Configuration (UTC)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SessionConfig:
    """
    Session time filtering in UTC.
    Trading allowed strictly in London and New York sessions.
    """
    LONDON_START_HOUR: int = 7       # 07:00 UTC (London Open / Pre-London)
    LONDON_END_HOUR: int = 12        # 12:00 UTC
    NEWYORK_START_HOUR: int = 12     # 12:00 UTC (NY Open / London-NY Overlap)
    NEWYORK_END_HOUR: int = 20       # 20:00 UTC (NY Session Close)
    
    def is_session_active(self, dt) -> Tuple[bool, str]:
        """
        Validates if datetime falls within London or New York sessions.
        Returns (is_active, session_name).
        """
        hour = dt.hour
        weekday = dt.weekday()  # 0=Monday, 6=Sunday
        
        # Exclude weekend
        if weekday >= 5:
            return (False, "WEEKEND")
            
        if self.LONDON_START_HOUR <= hour < self.LONDON_END_HOUR:
            return (True, "LONDON")
        elif self.NEWYORK_START_HOUR <= hour < self.NEWYORK_END_HOUR:
            return (True, "NEW_YORK")
        else:
            return (False, "OFF_SESSION")


# ---------------------------------------------------------------------------
# Strategy Configuration (SLK + CRT + ABC/XYZ Multi-Timeframe Engine)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class StrategyConfig:
    """
    Mathematical rules for SLK (Structure, Liquidity, Key Level),
    CRT (Candle Range Theory), and ABC -> XYZ Multi-Timeframe execution.
    """
    TIMEFRAME_NAME: str = "M15"
    TIMEFRAME_MINUTES: int = 15

    # Global Risk-to-Reward Fallbacks
    STOP_LOSS_PIPS: float = 50.0       # Fallback Stop Loss in pips
    TAKE_PROFIT_PIPS: float = 150.0    # Fallback Take Profit (1:3 RR)
    TAKE_PROFIT_2_PIPS: float = 250.0  # Fallback Take Profit 2 (1:5 RR)
    
    # Sizing Mode
    USE_FIXED_LOT_SIZING: bool = True  # If True: EURUSD/GBPUSD=0.10, XAUUSD=0.02

    # Historical Bars Lookback
    BARS_LOOKBACK: int = 100

    # Timeframe Hierarchy
    HTF_TIMEFRAMES: List[str] = field(default_factory=lambda: ["1W", "1D", "4h", "2h"])
    LTF_TIMEFRAMES: List[str] = field(default_factory=lambda: ["2h", "1h", "15m"])
    BASE_TIMEFRAME: str = "15m"

    # Structure & Swing Lookback
    SWING_LOOKBACK: int = 10           # Lookback to identify A/V shape swing pivots
    MIN_KEY_LEVEL_TOUCHES: int = 2     # Minimum touches/rejections sponsoring a key level
    
    # Fair Value Gap / Imbalance Threshold (in pips)
    MIN_FVG_PIPS: float = 2.0
    
    # Momentum Expansion Threshold (Body / Range ratio)
    MOMENTUM_BODY_RATIO: float = 0.55
    
    # CRT (Candle Range Theory) Parameters
    CRT_SWEEP_TOLERANCE_RATIO: float = 0.05 # Minimum sweep beyond previous candle extreme

    def get_sl_pips(self, symbol: str) -> float:
        """Returns symbol-specific Stop Loss in pips (10 pips FX, 50 pips Gold)."""
        if symbol in SUPPORTED_SYMBOLS:
            return SUPPORTED_SYMBOLS[symbol].default_sl_pips
        return self.STOP_LOSS_PIPS

    def get_tp_pips(self, symbol: str) -> float:
        """Returns symbol-specific Take Profit in pips (30 pips FX, 150 pips Gold)."""
        if symbol in SUPPORTED_SYMBOLS:
            return SUPPORTED_SYMBOLS[symbol].default_tp_pips
        return self.TAKE_PROFIT_PIPS

    def get_tp2_pips(self, symbol: str) -> float:
        """Returns symbol-specific extended Take Profit 2 in pips."""
        if symbol in SUPPORTED_SYMBOLS:
            return SUPPORTED_SYMBOLS[symbol].default_tp2_pips
        return self.TAKE_PROFIT_2_PIPS



# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------
LOG_FILE_PATH = str(LOGS_DIR / "bot_activity.log")
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | [%(name)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

