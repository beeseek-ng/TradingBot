"""
Unit Tests for ForexBot Suite
=============================
Tests math accuracy, risk management calculations, SLK (Structure, Liquidity, Key Level),
CRT (Candle Range Theory), session timing, and multi-timeframe backtester simulation.
"""

import math
import pytest
import pandas as pd
import numpy as np

from config import (
    SUPPORTED_SYMBOLS,
    RiskConfig,
    StrategyConfig,
    SessionConfig,
    SymbolSpec,
)
from strategy import (
    PriceActionStrategy,
    SignalType,
    TradeSignal,
    MarketEnvironmentClassifier,
    MarketEnvironment,
    MarketPhase,
    KeyLevelDetector,
    CandleRangeTheoryEngine,
)
from backtester import Backtester, MultiTimeframeResampler, generate_sample_data
from main import RiskManager, PropFirmGuard


# ---------------------------------------------------------------------------
# 1. Symbol Configuration & Pip Math Tests
# ---------------------------------------------------------------------------
def test_symbol_pip_math():
    """Verify pip-to-price and price-to-pip conversions for FX vs Gold."""
    eurusd = SUPPORTED_SYMBOLS["EURUSD"]
    gbpusd = SUPPORTED_SYMBOLS["GBPUSD"]
    xauusd = SUPPORTED_SYMBOLS["XAUUSD"]

    # EURUSD 50 pips = 0.00500 price move
    assert math.isclose(eurusd.pips_to_price_delta(50.0), 0.00500, rel_tol=1e-5)
    assert math.isclose(eurusd.price_delta_to_pips(0.00500), 50.0, rel_tol=1e-5)

    # GBPUSD 150 pips = 0.01500 price move
    assert math.isclose(gbpusd.pips_to_price_delta(150.0), 0.01500, rel_tol=1e-5)
    assert math.isclose(gbpusd.price_delta_to_pips(0.01500), 150.0, rel_tol=1e-5)

    # XAUUSD 50 pips = $5.00 price move (0.10 * 50 = $5.00)
    assert math.isclose(xauusd.pips_to_price_delta(50.0), 5.0, rel_tol=1e-5)
    assert math.isclose(xauusd.price_delta_to_pips(5.0), 50.0, rel_tol=1e-5)

    # XAUUSD 150 pips = $15.00 price move
    assert math.isclose(xauusd.pips_to_price_delta(150.0), 15.0, rel_tol=1e-5)
    assert math.isclose(xauusd.price_delta_to_pips(15.0), 150.0, rel_tol=1e-5)


# ---------------------------------------------------------------------------
# 2. Risk Manager & Lot Sizing Tests (Fixed & Dynamic)
# ---------------------------------------------------------------------------
def test_risk_manager_lot_sizing():
    """Verify fixed lot sizing and dynamic lot sizing modes."""
    risk_config = RiskConfig(RISK_PER_TRADE=0.01)
    risk_mgr = RiskManager(risk_config)
    eurusd = SUPPORTED_SYMBOLS["EURUSD"]
    gbpusd = SUPPORTED_SYMBOLS["GBPUSD"]
    xauusd = SUPPORTED_SYMBOLS["XAUUSD"]

    # Fixed lot sizing as requested
    assert risk_mgr.calculate_lot_size(10000.0, 50.0, eurusd, use_fixed=True) == 0.05
    assert risk_mgr.calculate_lot_size(10000.0, 50.0, gbpusd, use_fixed=True) == 0.05
    assert risk_mgr.calculate_lot_size(10000.0, 50.0, xauusd, use_fixed=True) == 0.02

    # Dynamic lot sizing mode (1% equity risk on 50 pips)
    lot_eur_dyn = risk_mgr.calculate_lot_size(10000.0, 50.0, eurusd, use_fixed=False)
    assert lot_eur_dyn == 0.20


# ---------------------------------------------------------------------------
# 3. Session Timing Filter Tests
# ---------------------------------------------------------------------------
def test_session_timing_filter():
    """Verify London (07-12 UTC) and NY (12-20 UTC) session filtering."""
    session_mgr = SessionConfig()

    # Wednesday 09:00 UTC -> London
    dt_london = pd.Timestamp("2026-09-09 09:00:00")
    active_ldn, name_ldn = session_mgr.is_session_active(dt_london)
    assert active_ldn is True
    assert name_ldn == "LONDON"

    # Wednesday 14:30 UTC -> New York
    dt_ny = pd.Timestamp("2026-09-09 14:30:00")
    active_ny, name_ny = session_mgr.is_session_active(dt_ny)
    assert active_ny is True
    assert name_ny == "NEW_YORK"

    # Wednesday 02:00 UTC -> Off session (Asian)
    dt_off = pd.Timestamp("2026-09-09 02:00:00")
    active_off, name_off = session_mgr.is_session_active(dt_off)
    assert active_off is False
    assert name_off == "OFF_SESSION"

    # Saturday -> Weekend
    dt_weekend = pd.Timestamp("2026-09-12 10:00:00")
    active_wk, name_wk = session_mgr.is_session_active(dt_weekend)
    assert active_wk is False
    assert name_wk == "WEEKEND"


# ---------------------------------------------------------------------------
# 4. Market Environment & Phase Classifier Tests
# ---------------------------------------------------------------------------
def test_market_environment_classifier():
    """Verify environment detection (Uptrend / Downtrend / Range / Chop)."""
    # Create synthetic uptrend series
    dates = pd.date_range("2026-01-01", periods=50, freq="15min")
    prices = np.linspace(1.1000, 1.1200, 50)
    df_uptrend = pd.DataFrame({
        "time": dates,
        "open": prices,
        "high": prices + 0.0005,
        "low": prices - 0.0002,
        "close": prices + 0.0004
    })
    env, phase = MarketEnvironmentClassifier.classify(df_uptrend)
    assert env in (MarketEnvironment.UPTREND, MarketEnvironment.RANGING)


# ---------------------------------------------------------------------------
# 5. Key Level & FVG Detector Tests
# ---------------------------------------------------------------------------
def test_key_level_and_fvg_detection():
    """Verify detection of Fair Value Gaps and key levels."""
    spec = SUPPORTED_SYMBOLS["EURUSD"]
    # Construct 3 candles with bullish FVG (low[2] > high[0])
    df_fvg = pd.DataFrame({
        "time": pd.date_range("2026-01-01", periods=5, freq="15min"),
        "open": [1.1000, 1.1020, 1.1050, 1.1060, 1.1070],
        "high": [1.1010, 1.1045, 1.1080, 1.1075, 1.1085],
        "low":  [1.0995, 1.1015, 1.1040, 1.1050, 1.1060],
        "close":[1.1005, 1.1040, 1.1075, 1.1065, 1.1080]
    })
    fvgs = KeyLevelDetector.find_fair_value_gaps(df_fvg, min_pips=1.0, spec=spec)
    assert len(fvgs) > 0


# ---------------------------------------------------------------------------
# 6. CRT Sweep Detection Tests
# ---------------------------------------------------------------------------
def test_crt_sweep_detection():
    """Verify Candle Range Theory sweep recognition."""
    # Bullish CRT: Candle 2 sweeps candle 1 low and closes back inside range
    df_crt = pd.DataFrame({
        "time": [pd.Timestamp("2026-01-01 09:00:00"), pd.Timestamp("2026-01-01 09:15:00")],
        "open": [1.1050, 1.1030],
        "high": [1.1080, 1.1070],
        "low":  [1.1020, 1.1005],  # Low swept (1.1005 < 1.1020)
        "close":[1.1040, 1.1060]   # Closed back above (1.1060 > 1.1020)
    })
    sweep = CandleRangeTheoryEngine.evaluate_crt(df_crt)
    assert sweep is not None
    assert sweep.is_bullish_sweep is True
    assert sweep.swept_level == 1.1020


# ---------------------------------------------------------------------------
# 7. Backtester Multi-Timeframe Resampling & Simulation
# ---------------------------------------------------------------------------
def test_backtester_multi_timeframe_simulation():
    """Verify end-to-end backtester execution with resampling and SLK metrics."""
    backtester = Backtester(initial_balance=10000.0, use_fixed_lot=True)
    df = generate_sample_data("EURUSD", num_bars=500)

    # Test resampling
    h4_df = MultiTimeframeResampler.resample(df, "4h")
    assert len(h4_df) > 0
    assert "open" in h4_df.columns and "close" in h4_df.columns

    # Test run
    result = backtester.run("EURUSD", df)
    assert result.symbol == "EURUSD"
    assert result.initial_balance == 10000.0
    assert result.final_balance > 0
    assert 0.0 <= result.win_rate_pct <= 100.0
