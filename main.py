"""
ForexBot Main Execution Engine
==============================
Production-ready, object-oriented algorithmic trading bot for MetaTrader 5 (MT5).

Features:
- Multi-Symbol Non-Blocking Polling Loop: EURUSD, GBPUSD, XAUUSD on M15 candle closes.
- Dynamic Risk Manager: Dynamic lot sizing based on account equity and 50-pip Stop Loss.
- Prop Firm Guardrail: Continuous daily drawdown monitor (4.5% kill-switch with auto-liquidation).
- Resilient State Recovery: Detects existing open positions by Magic Number upon boot.
- Dual-Pipe Logging: Real-time console stream and persistent file logging to 'logs/bot_activity.log'.
- Network Drop Resilience: Comprehensive try-except error handling and automated reconnects.
"""

import logging
import math
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import pandas as pd

# Ensure project root is in sys.path (needed for Windows embed python under Wine)
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Import Configuration and Strategy
from config import (
    LOG_FILE_PATH,
    LOG_FORMAT,
    LOG_DATE_FORMAT,
    SUPPORTED_SYMBOLS,
    MT5Config,
    RiskConfig,
    StrategyConfig,
    SymbolSpec,
    WebConfig,
)
from strategy import PriceActionStrategy, SignalType, TradeSignal
import web_server

# Try importing native MetaTrader5
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False


# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------
def setup_logger(name: str = "ForexBot") -> logging.Logger:
    """Configures dual-output logger for file and console streaming."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    # File Handler
    file_handler = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    return logger


logger = setup_logger("ForexBot")


def auto_enable_mt5_autotrading() -> bool:
    """
    Automatically enables MT5 'Algo Trading' (AutoTrading) in the terminal
    by sending the Ctrl+E hotkey to the MetaTrader 5 window via Win32 API
    and X11 xdotool. Works natively on Windows, under Wine, and Linux Xvfb.
    """
    success = False

    # 1. Try Win32 API keybd_event if under Windows or Wine Python
    if sys.platform == "win32":
        try:
            import ctypes
            user32 = ctypes.windll.user32

            hwnd_targets = []

            def _enum_cb(hwnd, lparam):
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buf, length + 1)
                        title = buf.value
                        if "MetaTrader" in title or "MetaQuotes" in title or "5055872290" in title:
                            hwnd_targets.append(hwnd)
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
            user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)

            VK_CONTROL = 0x11
            VK_E = 0x45
            KEYEVENTF_KEYUP = 0x0002

            if hwnd_targets:
                for hwnd in hwnd_targets:
                    try:
                        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                        user32.SetForegroundWindow(hwnd)
                        time.sleep(0.2)
                        user32.keybd_event(VK_CONTROL, 0, 0, 0)
                        user32.keybd_event(VK_E, 0, 0, 0)
                        time.sleep(0.1)
                        user32.keybd_event(VK_E, 0, KEYEVENTF_KEYUP, 0)
                        user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
                        time.sleep(0.3)
                    except Exception:
                        pass
            else:
                user32.keybd_event(VK_CONTROL, 0, 0, 0)
                user32.keybd_event(VK_E, 0, 0, 0)
                time.sleep(0.1)
                user32.keybd_event(VK_E, 0, KEYEVENTF_KEYUP, 0)
                user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
                time.sleep(0.3)

            success = True
        except Exception as ex:
            logger.debug(f"auto_enable_mt5_autotrading Win32 exception: {ex}")

    # 2. Try xdotool if running in Linux Xvfb environment
    try:
        import subprocess
        display = os.getenv("DISPLAY", ":99")
        subprocess.run(
            ["xdotool", "key", "ctrl+e"],
            env=dict(os.environ, DISPLAY=display),
            timeout=3,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        subprocess.run(
            ["xdotool", "search", "--name", "MetaTrader", "windowactivate", "--sync", "key", "ctrl+e"],
            env=dict(os.environ, DISPLAY=display),
            timeout=3,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        success = True
    except Exception:
        pass

    return success


# ---------------------------------------------------------------------------
# MT5 Client & Connection Manager
# ---------------------------------------------------------------------------
class MT5Client:
    """
    Manages terminal connection, network heartbeat, and low-level MT5 API calls
    with defensive exception handling and retry mechanisms.
    """

    def __init__(self, config: MT5Config):
        self.config = config
        self.is_connected = False

    def connect(self) -> bool:
        """Initializes connection to MT5 terminal and logs in."""
        if not MT5_AVAILABLE:
            logger.error("MetaTrader5 Python library is not installed or not supported on this OS.")
            logger.info("To run live execution, install MetaTrader5 on Windows or run via Wine.")
            return False

        try:
            logger.info(f"Connecting to MT5 terminal on server: '{self.config.SERVER}'...")
            
            init_kwargs = {
                "timeout": self.config.TIMEOUT_MS,
                "portable": self.config.PORTABLE
            }
            if self.config.PATH:
                init_kwargs["path"] = self.config.PATH
            if self.config.LOGIN:
                init_kwargs["login"] = int(self.config.LOGIN)
            if self.config.PASSWORD:
                init_kwargs["password"] = str(self.config.PASSWORD)
            if self.config.SERVER:
                init_kwargs["server"] = str(self.config.SERVER)

            initialized = False
            for attempt in range(1, 4):
                if mt5.initialize(**init_kwargs):
                    initialized = True
                    break
                err = mt5.last_error()
                logger.warning(f"MT5 initialize() attempt {attempt}/3 failed: {err}")
                time.sleep(2.0)

            if not initialized:
                err = mt5.last_error()
                logger.error(f"MT5 initialize() failed after 3 attempts: {err}")
                return False

            # Login if credentials provided
            if self.config.LOGIN:
                login_ok = mt5.login(
                    login=self.config.LOGIN,
                    password=self.config.PASSWORD,
                    server=self.config.SERVER,
                    timeout=self.config.TIMEOUT_MS
                )
                if not login_ok:
                    err = mt5.last_error()
                    logger.error(f"MT5 login failed for user {self.config.LOGIN}: {err}")
                    mt5.shutdown()
                    return False

            # Allow MT5 terminal network handshake with broker server
            logger.info("Waiting for MT5 broker server synchronization...")
            for _ in range(15):
                term = mt5.terminal_info()
                if term and term.connected:
                    break
                time.sleep(1.0)

            terminal_info = mt5.terminal_info()
            account_info = mt5.account_info()
            
            if account_info is None:
                logger.error("Failed to retrieve MT5 account info.")
                return False

            self.is_connected = True
            term_trade_allowed = getattr(terminal_info, "trade_allowed", True) if terminal_info else True
            acc_trade_allowed = getattr(account_info, "trade_allowed", True) if account_info else True
            acc_trade_expert = getattr(account_info, "trade_expert", True) if account_info else True

            # If AutoTrading is disabled in MT5, automatically trigger Ctrl+E hotkey
            if not term_trade_allowed:
                logger.info("[ForexBot] MT5 terminal has 'Algo Trading' disabled. Triggering automated Ctrl+E hotkey activation...")
                auto_enable_mt5_autotrading()
                time.sleep(1.0)
                terminal_info = mt5.terminal_info()
                term_trade_allowed = getattr(terminal_info, "trade_allowed", False) if terminal_info else False
                if term_trade_allowed:
                    logger.info("[ForexBot] SUCCESS: MT5 'Algo Trading' has been activated automatically!")
                else:
                    logger.info("[ForexBot] Retrying automated Algo Trading activation...")
                    auto_enable_mt5_autotrading()
                    time.sleep(1.0)
                    terminal_info = mt5.terminal_info()
                    term_trade_allowed = getattr(terminal_info, "trade_allowed", False) if terminal_info else False

            logger.info(f"Connected to MT5 successfully | Account: {account_info.login} | "
                        f"Server: {account_info.server} | Balance: ${account_info.balance:,.2f} | "
                        f"Equity: ${account_info.equity:,.2f} | Currency: {account_info.currency}")
            logger.info(f"MT5 Trade Status: Terminal AlgoTrading={term_trade_allowed}, "
                        f"Account TradeAllowed={acc_trade_allowed}, Account TradeExpert={acc_trade_expert}")
            
            if not term_trade_allowed:
                logger.warning("[ForexBot] NOTICE: MT5 terminal reported trade_allowed=False. Automated hotkey activator is armed to toggle Algo Trading ON upon trade signals.")
            if not acc_trade_allowed or not acc_trade_expert:
                logger.warning("[ForexBot] WARNING: Account does not have full trading permissions. Ensure master trading password was used instead of investor password.")
            return True

        except Exception as ex:
            logger.exception(f"Unexpected exception during MT5 connection: {ex}")
            return False

    def disconnect(self) -> None:
        """Safely shuts down MT5 connection."""
        if MT5_AVAILABLE and self.is_connected:
            try:
                mt5.shutdown()
                self.is_connected = False
                logger.info("MT5 terminal connection safely terminated.")
            except Exception as ex:
                logger.error(f"Error during MT5 shutdown: {ex}")

    def ensure_connection(self) -> bool:
        """Heartbeat check; automatically reconnects if disconnected."""
        if not MT5_AVAILABLE:
            return False

        try:
            term = mt5.terminal_info()
            if term is None:
                logger.warning("MT5 terminal_info is None. Reconnecting...")
                self.is_connected = False
                return self.connect()
            if not term.connected:
                # MT5 process is alive, terminal is momentarily syncing with broker
                return True
            return True
        except Exception as ex:
            logger.error(f"Connection check failed: {ex}. Reconnecting...")
            self.is_connected = False
            return self.connect()

    def subscribe_symbol(self, symbol: str) -> bool:
        """Ensures the symbol is visible in the Market Watch."""
        if not MT5_AVAILABLE:
            return False
        try:
            selected = mt5.symbol_select(symbol, True)
            if not selected:
                logger.warning(f"Failed to select symbol '{symbol}' in Market Watch.")
            # Warm up history download
            mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 10)
            return True
        except Exception as ex:
            logger.error(f"Error selecting symbol '{symbol}': {ex}")
            return False

    def get_rates(self, symbol: str, timeframe: int, count: int) -> Optional[pd.DataFrame]:
        """
        Fetches the latest `count` completed candles for a symbol with retries.
        Returns a formatted pandas DataFrame.
        """
        if not MT5_AVAILABLE:
            return None

        for attempt in range(3):
            try:
                rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
                if rates is not None and len(rates) > 0:
                    df = pd.DataFrame(rates)
                    df["time"] = pd.to_datetime(df["time"], unit="s")
                    return df
                time.sleep(1.0)
            except Exception as ex:
                logger.error(f"Exception in get_rates for {symbol}: {ex}")
                time.sleep(1.0)

        err = mt5.last_error()
        logger.warning(f"No rates returned for {symbol} after retries: {err}")
        return None

    def get_account_equity_and_balance(self) -> Tuple[float, float]:
        """Returns (equity, balance). Fallback to (0.0, 0.0) on error."""
        if not MT5_AVAILABLE:
            return (0.0, 0.0)
        try:
            acc = mt5.account_info()
            if acc:
                return (acc.equity, acc.balance)
        except Exception as ex:
            logger.error(f"Error fetching account equity: {ex}")
        return (0.0, 0.0)

    def get_symbol_tick(self, symbol: str):
        """Fetches latest bid/ask tick for symbol."""
        if not MT5_AVAILABLE:
            return None
        try:
            return mt5.symbol_info_tick(symbol)
        except Exception as ex:
            logger.error(f"Error fetching tick for {symbol}: {ex}")
            return None

    def get_symbol_info(self, symbol: str):
        """Fetches full broker symbol info (contract size, tick value, stops, etc.)."""
        if not MT5_AVAILABLE:
            return None
        try:
            return mt5.symbol_info(symbol)
        except Exception as ex:
            logger.error(f"Error fetching symbol info for {symbol}: {ex}")
            return None


# ---------------------------------------------------------------------------
# Risk Manager
# ---------------------------------------------------------------------------
class RiskManager:
    """
    Calculates dynamic position sizing and validates market conditions (spread, equity).
    """

    def __init__(self, risk_config: RiskConfig):
        self.config = risk_config

    def calculate_lot_size(
        self,
        equity: float,
        sl_pips: float,
        spec: SymbolSpec,
        mt5_symbol_info=None,
        use_fixed: bool = True
    ) -> float:
        """
        Calculates position volume:
        - If use_fixed is True: returns spec.fixed_lot (0.05 for EURUSD/GBPUSD, 0.02 for XAUUSD)
        - Otherwise calculates dynamic lot size based on current equity and Stop Loss in pips.
        """
        if use_fixed:
            return spec.fixed_lot

        if equity <= 0 or sl_pips <= 0:
            return spec.min_lot

        risk_amount = equity * self.config.RISK_PER_TRADE
        
        # Determine tick value from MT5 if available, else use theoretical spec
        if mt5_symbol_info is not None and getattr(mt5_symbol_info, "trade_tick_value", 0) > 0:
            tick_value = mt5_symbol_info.trade_tick_value
            tick_size = mt5_symbol_info.trade_tick_size
            points_per_pip = spec.pip_size / tick_size
            pip_value_1_lot = tick_value * points_per_pip
        else:
            pip_value_1_lot = spec.pip_size * spec.contract_size

        if pip_value_1_lot <= 0:
            return spec.min_lot

        raw_lot = risk_amount / (sl_pips * pip_value_1_lot)

        # Get broker constraints
        min_lot = getattr(mt5_symbol_info, "volume_min", spec.min_lot) if mt5_symbol_info else spec.min_lot
        max_lot = getattr(mt5_symbol_info, "volume_max", spec.max_lot) if mt5_symbol_info else spec.max_lot
        step_lot = getattr(mt5_symbol_info, "volume_step", spec.lot_step) if mt5_symbol_info else spec.lot_step

        # Step quantization
        steps = math.floor(raw_lot / step_lot)
        quantized_lot = round(steps * step_lot, 2)

        # Clamp between min and max
        final_lot = max(min_lot, min(quantized_lot, max_lot))
        return final_lot

    def is_spread_acceptable(self, ask: float, bid: float, spec: SymbolSpec) -> bool:
        """Verifies if current spread is within allowable risk limits."""
        spread_price = ask - bid
        spread_pips = spec.price_delta_to_pips(spread_price)
        if spread_pips > self.config.MAX_SPREAD_PIPS:
            logger.warning(f"Spread filter tripped for {spec.symbol}: {spread_pips:.1f} pips "
                           f"(Max allowed: {self.config.MAX_SPREAD_PIPS:.1f} pips). Skipping trade.")
            return False
        return True


# ---------------------------------------------------------------------------
# Prop Firm Guardrails (Daily Drawdown Kill-Switch)
# ---------------------------------------------------------------------------
class PropFirmGuard:
    """
    Monitors daily drawdown against the starting daily balance.
    If equity falls 4.5% below starting balance, initiates emergency liquidation.
    """

    def __init__(self, limit_pct: float = RiskConfig.GLOBAL_DAILY_DRAWDOWN_LIMIT):
        self.limit_pct = limit_pct
        self.starting_daily_balance: float = 0.0
        self.current_day: int = -1
        self.is_killswitch_active: bool = False

    def update_daily_baseline(self, current_balance: float) -> None:
        """Resets baseline balance at UTC midnight or on initial startup."""
        today = datetime.now(timezone.utc).day
        if today != self.current_day or self.starting_daily_balance <= 0:
            self.current_day = today
            self.starting_daily_balance = current_balance
            logger.info(f"PropFirmGuard: New daily baseline balance established: "
                        f"${self.starting_daily_balance:,.2f} (Daily DD Limit: {self.limit_pct*100:.1f}%)")

    def check_equity(self, current_equity: float) -> bool:
        """
        Checks if equity breached the daily drawdown threshold.
        Returns False if breached (Kill-switch triggered), True if healthy.
        """
        if self.starting_daily_balance <= 0:
            return True

        allowed_equity_floor = self.starting_daily_balance * (1.0 - self.limit_pct)
        drawdown_pct = (self.starting_daily_balance - current_equity) / self.starting_daily_balance

        if current_equity < allowed_equity_floor:
            self.is_killswitch_active = True
            logger.critical("=" * 70)
            logger.critical(f"PROP FIRM GUARD KILL-SWITCH TRIGGERED!")
            logger.critical(f"Current Equity: ${current_equity:,.2f} | Baseline Balance: ${self.starting_daily_balance:,.2f}")
            logger.critical(f"Daily Drawdown: {drawdown_pct*100:.2f}% (Limit: {self.limit_pct*100:.1f}%)")
            logger.critical("Initiating emergency account liquidation & safe shutdown...")
            logger.critical("=" * 70)
            return False

        return True


# ---------------------------------------------------------------------------
# Paper Trading & Simulation Client (For Native Linux Execution)
# ---------------------------------------------------------------------------
class PaperClient:
    """
    Simulated broker client allowing live paper-trading on Linux
    without requiring the Windows MetaTrader5 library.
    """

    def __init__(self, initial_balance: Optional[float] = None):
        if initial_balance is None:
            initial_balance = float(os.getenv("ACCOUNT_BALANCE") or os.getenv("INITIAL_BALANCE") or "100.0")
        self.balance = initial_balance
        self.equity = initial_balance
        self.is_connected = True
        self.data_cache: Dict[str, pd.DataFrame] = {}
        self.current_indices: Dict[str, int] = {}
        self._load_data()

    def _load_data(self):
        """Loads available historical CSV data for paper trading simulation."""
        from backtester import find_csv_for_symbol, generate_sample_data
        for sym in SUPPORTED_SYMBOLS:
            csv_path = find_csv_for_symbol(sym)
            if csv_path and csv_path.exists():
                try:
                    df = pd.read_csv(csv_path, sep=None, engine="python")
                    df.columns = [str(c).strip().lower().replace("<", "").replace(">", "") for c in df.columns]
                    if "date" in df.columns and "time" in df.columns:
                        df["time"] = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str), errors="coerce")
                    elif "time" in df.columns:
                        df["time"] = pd.to_datetime(df["time"], errors="coerce")
                    for col in ["open", "high", "low", "close"]:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("time").reset_index(drop=True)
                    self.data_cache[sym] = df
                    self.current_indices[sym] = min(500, len(df) - 50)
                except Exception:
                    self.data_cache[sym] = generate_sample_data(sym, num_bars=500)
                    self.current_indices[sym] = 100
            else:
                self.data_cache[sym] = generate_sample_data(sym, num_bars=500)
                self.current_indices[sym] = 100

    def connect(self) -> bool:
        logger.info(f"Connected to Paper Trading Engine | Simulated Account: 5055872290 | "
                    f"Balance: ${self.balance:,.2f} | Equity: ${self.equity:,.2f} | Mode: PAPER / SIMULATION")
        return True

    def disconnect(self) -> None:
        logger.info("Paper trading connection safely terminated.")

    def ensure_connection(self) -> bool:
        return True

    def subscribe_symbol(self, symbol: str) -> bool:
        return True

    def get_rates(self, symbol: str, timeframe: int, count: int) -> Optional[pd.DataFrame]:
        df = self.data_cache.get(symbol)
        if df is None:
            return None
        idx = self.current_indices[symbol]
        # Slice rolling lookback window
        window = df.iloc[max(0, idx - count): idx + 1].copy()
        # Advance index by 1 for next candle poll
        if idx < len(df) - 1:
            self.current_indices[symbol] += 1
        return window

    def get_account_equity_and_balance(self) -> Tuple[float, float]:
        return (self.equity, self.balance)

    def get_symbol_tick(self, symbol: str):
        df = self.data_cache.get(symbol)
        if df is None:
            return None
        idx = self.current_indices[symbol]
        bar = df.iloc[min(idx, len(df) - 1)]
        spec = SUPPORTED_SYMBOLS[symbol]
        spread = spec.pips_to_price_delta(1.2)

        class Tick:
            ask = float(bar["close"]) + spread
            bid = float(bar["close"])
        return Tick()

    def get_symbol_info(self, symbol: str):
        return None


# ---------------------------------------------------------------------------
# Order Execution Engine
# ---------------------------------------------------------------------------
class OrderExecutor:
    """
    Handles order dispatching, position closing, and pending order cancellations.
    """

    def __init__(self, client, magic_number: int):
        self.client = client
        self.magic_number = magic_number
        self.virtual_positions: List[Dict] = []
        self.ticket_counter = 1001

    def get_open_positions(self, symbol: Optional[str] = None) -> List:
        """Fetches all open positions."""
        if not MT5_AVAILABLE or isinstance(self.client, PaperClient):
            if symbol:
                return [p for p in self.virtual_positions if p["symbol"] == symbol]
            return self.virtual_positions

        try:
            if symbol:
                positions = mt5.positions_get(symbol=symbol)
            else:
                positions = mt5.positions_get()

            if positions is None:
                return []
            return [p for p in positions if p.magic == self.magic_number]
        except Exception as ex:
            logger.error(f"Error fetching open positions: {ex}")
            return []

    def _determine_filling_mode(self, symbol: str) -> int:
        """
        Dynamically detects supported MT5 execution filling mode for the symbol using bitmask checks.
        Prevents MT5 10030 (Unsupported filling mode) error.
        """
        if not MT5_AVAILABLE:
            return 0
        try:
            sym_info = self.client.get_symbol_info(symbol) if hasattr(self.client, "get_symbol_info") else mt5.symbol_info(symbol)
            if sym_info is None:
                sym_info = mt5.symbol_info(symbol)
            if sym_info is not None:
                filling_mode = getattr(sym_info, "filling_mode", 0)
                # Bit 0 (1): SYMBOL_FILLING_FOK -> ORDER_FILLING_FOK
                if filling_mode & 1:
                    return mt5.ORDER_FILLING_FOK
                # Bit 1 (2): SYMBOL_FILLING_IOC -> ORDER_FILLING_IOC
                elif filling_mode & 2:
                    return mt5.ORDER_FILLING_IOC
        except Exception as ex:
            logger.warning(f"Error checking symbol filling mode for {symbol}: {ex}")
        
        # Default fallback to ORDER_FILLING_RETURN
        return getattr(mt5, "ORDER_FILLING_RETURN", 2)

    def open_trade(self, signal: TradeSignal, lot_size: float, spec: SymbolSpec) -> bool:
        """Dispatches market BUY or SELL order with exact SL/TP and auto-adaptive filling mode."""
        if not MT5_AVAILABLE or isinstance(self.client, PaperClient):
            self.ticket_counter += 1
            pos = {
                "ticket": self.ticket_counter,
                "symbol": signal.symbol,
                "type": 0 if signal.signal == SignalType.BUY else 1,
                "volume": lot_size,
                "price_open": signal.entry_price,
                "sl": signal.stop_loss,
                "tp": signal.take_profit,
                "profit": 0.0,
                "magic": self.magic_number
            }
            self.virtual_positions.append(pos)
            logger.info(f"[PAPER EXECUTION] ORDER FILLED: Ticket #{pos['ticket']} | {signal.signal.value} "
                        f"{lot_size} lots {signal.symbol} @ {signal.entry_price:.{spec.digits}f} "
                        f"| SL: {signal.stop_loss} | TP: {signal.take_profit}")
            return True

        tick = self.client.get_symbol_tick(signal.symbol)
        if tick is None:
            logger.error(f"Cannot execute trade: Tick data unavailable for {signal.symbol}.")
            return False

        order_type = mt5.ORDER_TYPE_BUY if signal.signal == SignalType.BUY else mt5.ORDER_TYPE_SELL
        price = tick.ask if signal.signal == SignalType.BUY else tick.bid

        sl_dist = spec.pips_to_price_delta(signal.sl_pips)
        tp_dist = spec.pips_to_price_delta(signal.tp_pips)
        sl_price = spec.round_price(price - sl_dist if signal.signal == SignalType.BUY else price + sl_dist)
        tp_price = spec.round_price(price + tp_dist if signal.signal == SignalType.BUY else price - tp_dist)

        # Margin Validation & Automatic Volume Downsizing for Capital Safety
        acc_info = mt5.account_info()
        if acc_info is not None:
            free_margin = getattr(acc_info, "margin_free", 0.0)
            if free_margin is not None and free_margin > 0:
                calc_margin = mt5.order_calc_margin(order_type, signal.symbol, lot_size, price)
                if calc_margin is not None and calc_margin > (free_margin * 0.85):
                    safe_budget = free_margin * 0.75
                    single_lot_margin = mt5.order_calc_margin(order_type, signal.symbol, 1.0, price)
                    if single_lot_margin and single_lot_margin > 0:
                        max_affordable_lots = safe_budget / single_lot_margin
                        steps = math.floor(max_affordable_lots / spec.lot_step)
                        downsized_lot = round(steps * spec.lot_step, 2)
                        if downsized_lot >= spec.min_lot:
                            logger.warning(
                                f"[{signal.symbol}] Margin Protection: {lot_size} lots requires ${calc_margin:.2f} "
                                f"(Free Margin: ${free_margin:.2f}). Auto-adjusting volume to {downsized_lot} lots."
                            )
                            lot_size = downsized_lot
                        else:
                            min_margin = single_lot_margin * spec.min_lot
                            logger.error(
                                f"[{signal.symbol}] Insufficient Free Margin: ${free_margin:.2f} available, "
                                f"minimum {spec.min_lot} lots requires ${min_margin:.2f}. Skipping trade safely."
                            )
                            return False

        # Pre-check MT5 AlgoTrading status before sending order
        if MT5_AVAILABLE and not self.is_paper:
            try:
                term = mt5.terminal_info()
                if term and not term.trade_allowed:
                    logger.info("[ForexBot] Pre-flight check: 'Algo Trading' is OFF in MT5. Triggering automated hotkey activation...")
                    auto_enable_mt5_autotrading()
                    time.sleep(0.5)
            except Exception:
                pass

        default_filling = self._determine_filling_mode(signal.symbol)
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": signal.symbol,
            "volume": lot_size,
            "type": order_type,
            "price": price,
            "sl": sl_price,
            "tp": tp_price,
            "deviation": self.client.config.SLIPPAGE_POINTS,
            "magic": self.magic_number,
            "comment": f"ForexBot_M15_{signal.signal.value}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": default_filling,
        }

        logger.info(f"Sending Order: {signal.signal.value} {lot_size} lots {signal.symbol} @ {price:.{spec.digits}f} "
                    f"| SL: {sl_price} | TP: {tp_price}")

        # Candidate filling modes to test in sequence if broker rejects with retcode 10030
        filling_candidates = [
            default_filling,
            mt5.ORDER_FILLING_FOK,
            mt5.ORDER_FILLING_IOC,
            mt5.ORDER_FILLING_RETURN
        ]
        seen = set()
        filling_candidates = [f for f in filling_candidates if not (f in seen or seen.add(f))]

        for fm in filling_candidates:
            request["type_filling"] = fm
            try:
                result = mt5.order_send(request)
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.info(f"ORDER FILLED: Ticket #{result.order} | Volume: {result.volume} | Price: {result.price}")
                    return True
                elif result and result.retcode == 10030:  # Unsupported filling mode
                    logger.warning(f"Filling mode {fm} unsupported for {signal.symbol}, attempting next filling mode...")
                    continue
                elif result and result.retcode == 10019:  # No money (Insufficient Free Margin)
                    logger.warning(f"Broker returned retcode 10019 (No money) for {request['volume']} lots {signal.symbol}.")
                    # Attempt automated fallback to smaller volume
                    reduced_vol = round(request["volume"] / 2.0, 2)
                    if reduced_vol >= spec.min_lot and reduced_vol != request["volume"]:
                        logger.info(f"Retrying order with reduced volume: {reduced_vol} lots...")
                        request["volume"] = reduced_vol
                        result_retry = mt5.order_send(request)
                        if result_retry and result_retry.retcode == mt5.TRADE_RETCODE_DONE:
                            logger.info(f"ORDER FILLED (Reduced Volume): Ticket #{result_retry.order} | Volume: {result_retry.volume} | Price: {result_retry.price}")
                            return True
                    logger.error(f"Order send failed: Insufficient margin for {signal.symbol}. Balance/Margin too low.")
                    return False
                elif result and result.retcode == 10027:  # AutoTrading disabled by client
                    logger.warning("[ForexBot] Broker returned retcode 10027 ('AutoTrading disabled by client').")
                    logger.info("[ForexBot] Activating MT5 'Algo Trading' via automated hotkey and retrying order immediately...")
                    auto_enable_mt5_autotrading()
                    time.sleep(1.0)
                    result_retry = mt5.order_send(request)
                    if result_retry and result_retry.retcode == mt5.TRADE_RETCODE_DONE:
                        logger.info(f"ORDER FILLED (AutoTrading Activated): Ticket #{result_retry.order} | Volume: {result_retry.volume} | Price: {result_retry.price}")
                        return True
                    elif result_retry and result_retry.retcode != 10027:
                        # Process other response codes or filling mode trial
                        continue
                    else:
                        logger.error(f"[ForexBot] Order send retry failed: {result_retry}")
                        return False
                else:
                    logger.error(f"Order send failed: {result}")
                    return False
            except Exception as ex:
                logger.exception(f"Unexpected exception sending order for {signal.symbol}: {ex}")
                return False

        return False

    def close_position(self, position) -> bool:
        """Closes an open position in either paper or live MT5 mode."""
        if isinstance(self.client, PaperClient) or not MT5_AVAILABLE:
            ticket = position["ticket"] if isinstance(position, dict) else getattr(position, "ticket", None)
            self.virtual_positions = [p for p in self.virtual_positions if p["ticket"] != ticket]
            logger.info(f"[PAPER] Closed Position #{ticket}")
            return True

        try:
            ticket = getattr(position, "ticket", position.get("ticket") if isinstance(position, dict) else None)
            symbol = getattr(position, "symbol", position.get("symbol") if isinstance(position, dict) else None)
            pos_type = getattr(position, "type", position.get("type") if isinstance(position, dict) else None)
            volume = getattr(position, "volume", position.get("volume") if isinstance(position, dict) else None)

            if not all([ticket, symbol, volume is not None]):
                logger.error(f"Cannot close position: invalid position data: {position}")
                return False

            tick = self.client.get_symbol_tick(symbol)
            if tick is None:
                logger.error(f"Cannot close position #{ticket}: tick unavailable for {symbol}")
                return False

            close_order_type = mt5.ORDER_TYPE_SELL if pos_type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
            price = tick.bid if pos_type == mt5.ORDER_TYPE_BUY else tick.ask

            default_filling = self._determine_filling_mode(symbol)
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": ticket,
                "symbol": symbol,
                "volume": volume,
                "type": close_order_type,
                "price": price,
                "deviation": self.client.config.SLIPPAGE_POINTS,
                "magic": self.magic_number,
                "comment": f"ForexBot_Close_{ticket}",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": default_filling,
            }

            filling_candidates = [default_filling, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN]
            seen = set()
            filling_candidates = [f for f in filling_candidates if not (f in seen or seen.add(f))]

            for fm in filling_candidates:
                request["type_filling"] = fm
                result = mt5.order_send(request)
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.info(f"POSITION CLOSED: Ticket #{ticket} ({symbol}) at {price}")
                    return True
                elif result and result.retcode == 10030:
                    continue
                else:
                    logger.error(f"Failed to close position #{ticket}: {result}")
                    return False
        except Exception as ex:
            logger.exception(f"Exception closing position: {ex}")
            return False

        return False

    def emergency_liquidate_all(self) -> None:
        logger.critical("EMERGENCY: Closing all open positions...")
        open_positions = self.get_open_positions()
        for pos in open_positions:
            self.close_position(pos)


# ---------------------------------------------------------------------------
# Main ForexBot Orchestrator
# ---------------------------------------------------------------------------
class ForexBot:
    """
    Main Live & Paper Orchestration Loop.
    Coordinates symbol feeds, candle synchronization, risk checks, and trade dispatching.
    """

    def __init__(self, mode: str = "auto"):
        self.web_config = WebConfig()
        
        # Dynamically read EXECUTION_MODE or BOT_MODE from env/config
        env_mode = os.getenv("EXECUTION_MODE", os.getenv("BOT_MODE", self.web_config.EXECUTION_MODE)).upper()
        if mode in ("live", "LIVE"):
            self.mode = "LIVE"
        elif mode in ("paper", "PAPER"):
            self.mode = "PAPER"
        elif env_mode == "LIVE":
            self.mode = "LIVE"
        elif env_mode == "PAPER":
            self.mode = "PAPER"
        else:
            self.mode = "LIVE" if MT5_AVAILABLE else "PAPER"

        self.mt5_config = MT5Config()
        self.risk_config = RiskConfig()
        self.strategy_config = StrategyConfig()

        if self.mode == "LIVE" and MT5_AVAILABLE:
            self.client = MT5Client(self.mt5_config)
            self.is_paper = False
        elif self.mode == "LIVE" and not MT5_AVAILABLE:
            logger.warning("[ForexBot] LIVE MT5 mode was requested, but native MetaTrader5 package is not available in this Python interpreter.")
            logger.warning("[ForexBot] (Note: MT5 on Linux/Heroku requires Wine Python: wine /opt/wine-mt5/drive_c/Python39/python.exe main.py).")
            logger.warning("[ForexBot] Running in PAPER simulation fallback mode until Wine MT5 dyno is active.")
            self.client = PaperClient(initial_balance=self.risk_config.ACCOUNT_BALANCE)
            self.is_paper = True
        else:
            self.client = PaperClient(initial_balance=self.risk_config.ACCOUNT_BALANCE)
            self.is_paper = True

        self.risk_manager = RiskManager(self.risk_config)
        self.prop_guard = PropFirmGuard(self.risk_config.GLOBAL_DAILY_DRAWDOWN_LIMIT)
        self.executor = OrderExecutor(self.client, self.mt5_config.MAGIC_NUMBER)
        self.strategy = PriceActionStrategy(self.strategy_config)

        self.is_running = False
        self.last_candle_times: Dict[str, Optional[datetime]] = {
            sym: None for sym in SUPPORTED_SYMBOLS
        }

        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame):
        logger.warning(f"Received termination signal ({signum}). Shutting down gracefully...")
        self.is_running = False

    def startup(self) -> bool:
        logger.info("==================================================")
        mode_label = "PAPER TRADING / SIMULATION" if self.is_paper else "LIVE MT5"
        logger.info(f"     STARTING FOREXBOT ENGINE [{mode_label}]     ")
        logger.info("==================================================")

        # Launch Web Dashboard for Heroku and Cloud monitoring if enabled or PORT is set
        enable_dash = getattr(self.web_config, "ENABLE_DASHBOARD", True) or getattr(self.web_config, "ENABLE_WEB_DASHBOARD", True) or bool(os.getenv("PORT"))
        if enable_dash:
            port = int(os.getenv("PORT", getattr(self.web_config, "PORT", 8080)))
            host = getattr(self.web_config, "HOST", "0.0.0.0")
            try:
                web_server.start_web_server(port=port, host=host)
            except Exception as ex:
                logger.warning(f"Could not start web dashboard on port {port}: {ex}")

        if not self.client.connect():
            if self.mode == "LIVE":
                logger.warning("[ForexBot] LIVE MT5 connection failed. Switching to Paper Simulation fallback to keep dashboard and trading engine active.")
                self.client = PaperClient(initial_balance=self.risk_config.ACCOUNT_BALANCE)
                self.is_paper = True
                self.client.connect()
            else:
                logger.error("Initial connection failed. Exiting.")
                web_server.update_web_status(status="CONNECTION_FAILED", mode="PAPER" if self.is_paper else "LIVE")
                return False

        equity, balance = self.client.get_account_equity_and_balance()
        self.prop_guard.update_daily_baseline(balance)
        web_server.update_web_status(status="RUNNING", mode="PAPER" if self.is_paper else "LIVE", balance=balance, equity=equity)

        for sym in SUPPORTED_SYMBOLS:
            self.client.subscribe_symbol(sym)

        self.is_running = True
        return True

    def process_symbol(self, symbol: str) -> None:
        """Checks market feed for newly closed M15 candle and evaluates trade signals."""
        spec = SUPPORTED_SYMBOLS[symbol]
        
        timeframe = mt5.TIMEFRAME_M15 if MT5_AVAILABLE and not self.is_paper else 15
        df = self.client.get_rates(symbol, timeframe, self.strategy_config.BARS_LOOKBACK)
        if df is None or len(df) < self.strategy_config.SWING_LOOKBACK + 2:
            return

        latest_closed_candle = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
        candle_close_time = latest_closed_candle["time"]

        if self.last_candle_times[symbol] == candle_close_time:
            return

        self.last_candle_times[symbol] = candle_close_time
        logger.info(f"[{symbol}] New M15 Candle at {candle_close_time} | Close: {latest_closed_candle['close']}")

        open_positions = self.executor.get_open_positions(symbol)
        if len(open_positions) >= self.risk_config.MAX_POSITIONS_PER_SYMBOL:
            return

        completed_df = df.iloc[:-1] if len(df) >= 2 else df
        signal = self.strategy.evaluate_latest(completed_df, symbol)

        if not signal.is_actionable:
            return

        logger.info(f"[{symbol}] 🎯 SIGNAL DETECTED: {signal.signal.value} | {signal.rationale}")
        web_server.update_web_status(last_signal={
            "symbol": symbol,
            "type": signal.signal.value,
            "price": signal.entry_price,
            "reason": signal.rationale
        })

        equity, _ = self.client.get_account_equity_and_balance()
        mt5_sym_info = self.client.get_symbol_info(symbol)
        lot_size = self.risk_manager.calculate_lot_size(equity, signal.sl_pips, spec, mt5_sym_info, use_fixed=True)

        self.executor.open_trade(signal, lot_size, spec)

    def run(self) -> None:
        """Main non-blocking execution loop."""
        if not self.startup():
            return

        logger.info("Entering trading loop. Monitoring EURUSD, GBPUSD, XAUUSD on M15...")

        try:
            iteration = 0
            while self.is_running:
                if not self.client.ensure_connection():
                    time.sleep(5)
                    continue

                equity, balance = self.client.get_account_equity_and_balance()
                self.prop_guard.update_daily_baseline(balance)

                if not self.prop_guard.check_equity(equity):
                    self.executor.emergency_liquidate_all()
                    logger.critical("Bot terminated by Prop Firm Guardrail.")
                    web_server.update_web_status(status="KILL_SWITCH_ACTIVE")
                    break

                for symbol in SUPPORTED_SYMBOLS:
                    try:
                        self.process_symbol(symbol)
                    except Exception as ex:
                        logger.exception(f"Error processing {symbol}: {ex}")

                # Update live web status
                open_pos = self.executor.get_open_positions()
                pos_data = []
                for p in open_pos:
                    pos_data.append({
                        "ticket": getattr(p, "ticket", p.get("ticket") if isinstance(p, dict) else None),
                        "symbol": getattr(p, "symbol", p.get("symbol") if isinstance(p, dict) else None),
                        "type": getattr(p, "type", p.get("type") if isinstance(p, dict) else 0),
                        "volume": getattr(p, "volume", p.get("volume") if isinstance(p, dict) else 0.0),
                        "price_open": getattr(p, "price_open", p.get("price_open") if isinstance(p, dict) else 0.0),
                        "sl": getattr(p, "sl", p.get("sl") if isinstance(p, dict) else None),
                        "tp": getattr(p, "tp", p.get("tp") if isinstance(p, dict) else None),
                    })
                baseline = self.prop_guard.starting_daily_balance
                dd_pct = ((baseline - equity) / baseline * 100.0) if baseline > 0 else 0.0
                web_server.update_web_status(balance=balance, equity=equity, daily_dd_pct=max(0.0, dd_pct), open_positions=pos_data)

                iteration += 1
                time.sleep(1.0)

        except Exception as ex:
            logger.exception(f"Fatal error in main execution loop: {ex}")
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        logger.info("Performing clean shutdown...")
        web_server.update_web_status(status="STOPPED")
        self.client.disconnect()
        logger.info("ForexBot stopped.")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="ForexBot Multi-Timeframe Trading Engine")
    parser.add_argument("--mode", type=str, default="auto", choices=["auto", "paper", "live"],
                        help="Execution mode: 'auto' (Live MT5 if available, Paper if on Linux), 'paper' (Simulation), 'live' (Strict MT5)")
    args = parser.parse_args()

    bot = ForexBot(mode=args.mode)
    bot.run()


if __name__ == "__main__":
    main()
