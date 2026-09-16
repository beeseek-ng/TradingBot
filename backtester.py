"""
ForexBot Backtesting & Performance Analytics Engine
===================================================
Simulates historical trade execution on exported MT5 CSV candlestick data
using the SLK (Structure, Liquidity, Key Level), CRT, and ABC/XYZ multi-timeframe
strategy engine.

Outputs comprehensive quantitative metrics:
- Win Rate, Profit Factor, Expected Value (Expectancy)
- Maximum Drawdown ($ and %), Sharpe Ratio
- Session Breakdown (London vs New York)
- Detailed Trade-by-Trade logs with SLK/CRT rationale
"""

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import numpy as np
import pandas as pd

try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

from config import (
    DATA_DIR,
    SUPPORTED_SYMBOLS,
    RiskConfig,
    StrategyConfig,
    SessionConfig,
    SymbolSpec,
)
from strategy import PriceActionStrategy, SignalType, TradeSignal


@dataclass
class TradeRecord:
    """Detailed record of an individual simulated trade."""
    trade_id: int
    symbol: str
    order_type: str
    entry_time: str
    entry_price: float
    exit_time: str
    exit_price: float
    stop_loss: float
    take_profit: float
    lot_size: float
    risk_usd: float
    pnl_usd: float
    pnl_pips: float
    exit_reason: str          # 'TP', 'SL', or 'END_OF_DATA'
    balance_after: float
    equity_after: float
    bars_held: int
    session: str = "LONDON"
    rationale: str = ""


@dataclass
class BacktestResult:
    """Comprehensive performance metrics for a backtest run."""
    symbol: str
    initial_balance: float
    final_balance: float
    total_net_profit: float
    total_return_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    profit_factor: float
    expected_payoff: float
    max_drawdown_usd: float
    max_drawdown_pct: float
    sharpe_ratio: float
    london_trades: int = 0
    ny_trades: int = 0
    trades: List[TradeRecord] = field(default_factory=list)
    equity_series: List[float] = field(default_factory=list)


class MultiTimeframeResampler:
    """
    Resamples base OHLCV candlestick data into higher timeframes
    (1H, 2H, 4H, 1D, 1W) without lookahead bias.
    """

    @staticmethod
    def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
        """
        Resamples a DataFrame indexed by datetime to the target rule ('1h', '2h', '4h', '1D', '1W').
        """
        if "time" not in df.columns:
            raise ValueError("DataFrame must contain 'time' column for resampling.")

        temp = df.copy()
        temp["time"] = pd.to_datetime(temp["time"])
        temp = temp.set_index("time").sort_index()

        agg_dict = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last"
        }
        if "tick_volume" in temp.columns:
            agg_dict["tick_volume"] = "sum"
        elif "vol" in temp.columns:
            agg_dict["vol"] = "sum"

        resampled = temp.resample(rule, closed="left", label="left").agg(agg_dict).dropna().reset_index()
        return resampled


class Backtester:
    """
    Event-driven Historical Backtesting Engine for SLK & CRT Strategy.
    """

    def __init__(
        self,
        initial_balance: float = 10000.0,
        risk_per_trade: float = RiskConfig.RISK_PER_TRADE,
        spread_pips: float = 1.2,
        slippage_pips: float = 0.5,
        use_fixed_lot: bool = True,
        tp_pips: float = 150.0,
        sl_pips: float = 50.0,
    ):
        self.initial_balance = initial_balance
        self.risk_per_trade = risk_per_trade
        self.spread_pips = spread_pips
        self.slippage_pips = slippage_pips
        self.use_fixed_lot = use_fixed_lot
        
        self.strategy_config = StrategyConfig(
            STOP_LOSS_PIPS=sl_pips,
            TAKE_PROFIT_PIPS=tp_pips,
            USE_FIXED_LOT_SIZING=use_fixed_lot
        )
        self.session_config = SessionConfig()
        self.strategy = PriceActionStrategy(self.strategy_config, self.session_config)

    def load_csv_data(self, filepath: Path) -> pd.DataFrame:
        """
        Loads and cleans MT5 exported CSV data.
        Handles tab-delimited, comma-delimited, and datetime headers.
        """
        if not filepath.exists():
            raise FileNotFoundError(f"Data file not found at: {filepath}")

        try:
            df = pd.read_csv(filepath, sep=None, engine="python")
        except Exception:
            df = pd.read_csv(filepath, sep="\t")

        # Standardize column headers
        df.columns = [str(c).strip().lower().replace("<", "").replace(">", "") for c in df.columns]

        # Handle MT5 standard column names: date, time, open, high, low, close, vol/tickvol
        if "date" in df.columns and "time" in df.columns and "datetime" not in df.columns:
            df["time"] = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str), errors="coerce")
        elif "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"], errors="coerce")
        elif "datetime" in df.columns:
            df["time"] = pd.to_datetime(df["datetime"], errors="coerce")
        elif "timestamp" in df.columns:
            df["time"] = pd.to_datetime(df["timestamp"], errors="coerce")
        else:
            df["time"] = pd.date_range(start="2022-01-01", periods=len(df), freq="15min")

        for col in ["open", "high", "low", "close"]:
            if col not in df.columns:
                raise ValueError(f"CSV file is missing mandatory column: '{col}'")
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("time").reset_index(drop=True)
        return df

    def calculate_lot_size(
        self,
        current_equity: float,
        sl_pips: float,
        symbol_spec: SymbolSpec,
    ) -> float:
        """
        Calculates position volume:
        - If use_fixed_lot is True: uses spec.fixed_lot (EURUSD/GBPUSD=0.05, XAUUSD=0.02)
        - Otherwise calculates dynamic lot size risking exactly risk_per_trade.
        """
        if self.use_fixed_lot:
            return symbol_spec.fixed_lot

        risk_amount = current_equity * self.risk_per_trade
        pip_value_per_lot = symbol_spec.pip_size * symbol_spec.contract_size
        
        if sl_pips <= 0 or pip_value_per_lot <= 0:
            return symbol_spec.min_lot

        raw_lot = risk_amount / (sl_pips * pip_value_per_lot)
        steps = round(raw_lot / symbol_spec.lot_step)
        normalized_lot = round(steps * symbol_spec.lot_step, 2)
        clamped_lot = max(symbol_spec.min_lot, min(normalized_lot, symbol_spec.max_lot))
        return clamped_lot

    def run(self, symbol: str, df: pd.DataFrame) -> BacktestResult:
        """
        Executes historical multi-timeframe backtest on the provided DataFrame for the symbol.
        """
        if symbol not in SUPPORTED_SYMBOLS:
            raise KeyError(f"Symbol '{symbol}' not found in SUPPORTED_SYMBOLS.")

        spec: SymbolSpec = SUPPORTED_SYMBOLS[symbol]
        balance = self.initial_balance
        equity = balance
        peak_balance = balance
        max_dd_usd = 0.0
        max_dd_pct = 0.0

        trades: List[TradeRecord] = []
        equity_curve: List[float] = [balance]

        active_trade: Optional[Dict] = None
        trade_counter = 0

        lookback = self.strategy.config.SWING_LOOKBACK
        sl_pips = self.strategy.config.get_sl_pips(symbol)
        tp_pips = self.strategy.config.get_tp_pips(symbol)
        sl_dist = spec.pips_to_price_delta(sl_pips)
        tp_dist = spec.pips_to_price_delta(tp_pips)
        spread_delta = spec.pips_to_price_delta(self.spread_pips)
        slippage_delta = spec.pips_to_price_delta(self.slippage_pips)

        # Pre-build Multi-Timeframe Series (4H, Daily, Weekly) for HTF ABC context
        print(f"[*] Resampling {symbol} data into 4H, Daily, and Weekly timeframes for HTF ABC bias...")
        try:
            h4_df = MultiTimeframeResampler.resample(df, "4h")
            d1_df = MultiTimeframeResampler.resample(df, "1D")
            w1_df = MultiTimeframeResampler.resample(df, "1W")
        except Exception as e:
            print(f"[!] Resampling notice: {e}. Fallback to single-stream data.")
            h4_df = None
            d1_df = None
            w1_df = None

        print(f"[*] Simulating {len(df):,} candles with SLK & CRT rules (Fixed SL: {sl_pips}p, TP: {tp_pips}p, Lot: {spec.fixed_lot})...")

        # Step through candles sequentially
        for i in range(lookback + 5, len(df)):
            current_bar = df.iloc[i]
            prev_bar = df.iloc[i - 1]
            
            bar_time = current_bar["time"]
            bar_time_str = str(bar_time)
            bar_open = float(current_bar["open"])
            bar_high = float(current_bar["high"])
            bar_low = float(current_bar["low"])
            bar_close = float(current_bar["close"])

            # ---------------------------------------------------------------
            # 1. Manage Active Position (Check for SL or TP on current bar)
            # ---------------------------------------------------------------
            if active_trade is not None:
                active_trade["bars_held"] += 1
                pos_type = active_trade["order_type"]
                entry_p = active_trade["entry_price"]
                sl_p = active_trade["stop_loss"]
                tp_p = active_trade["take_profit"]
                lots = active_trade["lot_size"]

                exit_triggered = False
                exit_price = 0.0
                exit_reason = ""

                if pos_type == "BUY":
                    if bar_low <= sl_p:
                        exit_price = sl_p - slippage_delta
                        exit_reason = "SL"
                        exit_triggered = True
                    elif bar_high >= tp_p:
                        exit_price = tp_p - slippage_delta
                        exit_reason = "TP"
                        exit_triggered = True

                    if exit_triggered:
                        pnl_pips = (exit_price - entry_p) / spec.pip_size
                        pnl_usd = pnl_pips * spec.pip_size * spec.contract_size * lots
                        balance += pnl_usd
                        equity = balance

                        record = TradeRecord(
                            trade_id=active_trade["trade_id"],
                            symbol=symbol,
                            order_type=pos_type,
                            entry_time=active_trade["entry_time"],
                            entry_price=entry_p,
                            exit_time=bar_time_str,
                            exit_price=spec.round_price(exit_price),
                            stop_loss=sl_p,
                            take_profit=tp_p,
                            lot_size=lots,
                            risk_usd=active_trade["risk_usd"],
                            pnl_usd=round(pnl_usd, 2),
                            pnl_pips=round(pnl_pips, 1),
                            exit_reason=exit_reason,
                            balance_after=round(balance, 2),
                            equity_after=round(equity, 2),
                            bars_held=active_trade["bars_held"],
                            session=active_trade.get("session", "LONDON"),
                            rationale=active_trade.get("rationale", "")
                        )
                        trades.append(record)
                        active_trade = None

                elif pos_type == "SELL":
                    if bar_high >= sl_p:
                        exit_price = sl_p + slippage_delta
                        exit_reason = "SL"
                        exit_triggered = True
                    elif bar_low <= tp_p:
                        exit_price = tp_p + slippage_delta
                        exit_reason = "TP"
                        exit_triggered = True

                    if exit_triggered:
                        pnl_pips = (entry_p - exit_price) / spec.pip_size
                        pnl_usd = pnl_pips * spec.pip_size * spec.contract_size * lots
                        balance += pnl_usd
                        equity = balance

                        record = TradeRecord(
                            trade_id=active_trade["trade_id"],
                            symbol=symbol,
                            order_type=pos_type,
                            entry_time=active_trade["entry_time"],
                            entry_price=entry_p,
                            exit_time=bar_time_str,
                            exit_price=spec.round_price(exit_price),
                            stop_loss=sl_p,
                            take_profit=tp_p,
                            lot_size=lots,
                            risk_usd=active_trade["risk_usd"],
                            pnl_usd=round(pnl_usd, 2),
                            pnl_pips=round(pnl_pips, 1),
                            exit_reason=exit_reason,
                            balance_after=round(balance, 2),
                            equity_after=round(equity, 2),
                            bars_held=active_trade["bars_held"],
                            session=active_trade.get("session", "LONDON"),
                            rationale=active_trade.get("rationale", "")
                        )
                        trades.append(record)
                        active_trade = None

            # Track Drawdown
            if balance > peak_balance:
                peak_balance = balance
            dd_usd = peak_balance - balance
            dd_pct = (dd_usd / peak_balance) * 100.0 if peak_balance > 0 else 0.0
            if dd_usd > max_dd_usd:
                max_dd_usd = dd_usd
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

            equity_curve.append(balance)

            # ---------------------------------------------------------------
            # 2. Evaluate Multi-Timeframe Strategy on Completed Bars
            # ---------------------------------------------------------------
            if active_trade is None:
                window_ltf = df.iloc[:i]  # Slice up to completed bar (i-1)
                
                # Fetch completed HTF bars up to current time (no lookahead)
                curr_dt = pd.to_datetime(bar_time)
                window_htf = d1_df[d1_df["time"] < curr_dt] if d1_df is not None else None
                window_w1 = w1_df[w1_df["time"] < curr_dt] if w1_df is not None else None

                signal = self.strategy.evaluate_multi_timeframe(
                    symbol=symbol,
                    ltf_df=window_ltf,
                    htf_df=window_htf,
                    weekly_df=window_w1
                )

                if signal.is_actionable:
                    trade_counter += 1
                    lot_size = self.calculate_lot_size(balance, signal.sl_pips, spec)
                    risk_usd = balance * self.risk_per_trade
                    session_label = signal.metadata.get("session", "LONDON")

                    if signal.signal == SignalType.BUY:
                        exec_entry = spec.round_price(bar_open + spread_delta + slippage_delta)
                        exec_sl = spec.round_price(exec_entry - sl_dist)
                        exec_tp = spec.round_price(exec_entry + tp_dist)
                        
                        active_trade = {
                            "trade_id": trade_counter,
                            "order_type": "BUY",
                            "entry_time": bar_time_str,
                            "entry_price": exec_entry,
                            "stop_loss": exec_sl,
                            "take_profit": exec_tp,
                            "lot_size": lot_size,
                            "risk_usd": risk_usd,
                            "bars_held": 0,
                            "session": session_label,
                            "rationale": signal.rationale
                        }
                    elif signal.signal == SignalType.SELL:
                        exec_entry = spec.round_price(bar_open - slippage_delta)
                        exec_sl = spec.round_price(exec_entry + sl_dist)
                        exec_tp = spec.round_price(exec_entry - tp_dist)
                        
                        active_trade = {
                            "trade_id": trade_counter,
                            "order_type": "SELL",
                            "entry_time": bar_time_str,
                            "entry_price": exec_entry,
                            "stop_loss": exec_sl,
                            "take_profit": exec_tp,
                            "lot_size": lot_size,
                            "risk_usd": risk_usd,
                            "bars_held": 0,
                            "session": session_label,
                            "rationale": signal.rationale
                        }

        # Close any active trade at end of data
        if active_trade is not None:
            last_bar = df.iloc[-1]
            last_close = float(last_bar["close"])
            pos_type = active_trade["order_type"]
            entry_p = active_trade["entry_price"]
            lots = active_trade["lot_size"]

            if pos_type == "BUY":
                pnl_pips = (last_close - entry_p) / spec.pip_size
            else:
                pnl_pips = (entry_p - last_close) / spec.pip_size
            pnl_usd = pnl_pips * spec.pip_size * spec.contract_size * lots
            balance += pnl_usd

            record = TradeRecord(
                trade_id=active_trade["trade_id"],
                symbol=symbol,
                order_type=pos_type,
                entry_time=active_trade["entry_time"],
                entry_price=entry_p,
                exit_time=str(last_bar["time"]),
                exit_price=spec.round_price(last_close),
                stop_loss=active_trade["stop_loss"],
                take_profit=active_trade["take_profit"],
                lot_size=lots,
                risk_usd=active_trade["risk_usd"],
                pnl_usd=round(pnl_usd, 2),
                pnl_pips=round(pnl_pips, 1),
                exit_reason="END_OF_DATA",
                balance_after=round(balance, 2),
                equity_after=round(balance, 2),
                bars_held=active_trade["bars_held"],
                session=active_trade.get("session", "LONDON"),
                rationale=active_trade.get("rationale", "")
            )
            trades.append(record)

        # -------------------------------------------------------------------
        # Metrics Compilation
        # -------------------------------------------------------------------
        total_trades = len(trades)
        wins = [t for t in trades if t.pnl_usd > 0]
        losses = [t for t in trades if t.pnl_usd <= 0]
        winning_trades = len(wins)
        losing_trades = len(losses)
        win_rate_pct = (winning_trades / total_trades * 100.0) if total_trades > 0 else 0.0

        london_trades = len([t for t in trades if t.session == "LONDON"])
        ny_trades = len([t for t in trades if t.session == "NEW_YORK"])

        gross_profit = sum(t.pnl_usd for t in wins)
        gross_loss = abs(sum(t.pnl_usd for t in losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
        
        net_profit = balance - self.initial_balance
        total_return_pct = (net_profit / self.initial_balance) * 100.0
        expected_payoff = (net_profit / total_trades) if total_trades > 0 else 0.0

        if len(trades) > 1:
            pnl_series = pd.Series([t.pnl_usd for t in trades])
            std = pnl_series.std()
            sharpe_ratio = (pnl_series.mean() / std * np.sqrt(252)) if std > 0 else 0.0
        else:
            sharpe_ratio = 0.0

        return BacktestResult(
            symbol=symbol,
            initial_balance=round(self.initial_balance, 2),
            final_balance=round(balance, 2),
            total_net_profit=round(net_profit, 2),
            total_return_pct=round(total_return_pct, 2),
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate_pct=round(win_rate_pct, 2),
            profit_factor=round(profit_factor, 2),
            expected_payoff=round(expected_payoff, 2),
            max_drawdown_usd=round(max_dd_usd, 2),
            max_drawdown_pct=round(max_dd_pct, 2),
            sharpe_ratio=round(sharpe_ratio, 2),
            london_trades=london_trades,
            ny_trades=ny_trades,
            trades=trades,
            equity_series=equity_curve,
        )

    def print_summary(self, result: BacktestResult) -> None:
        """Prints a clean, formatted performance report to the console."""
        spec = SUPPORTED_SYMBOLS[result.symbol]
        lot_desc = f"{spec.fixed_lot} lots (Fixed)" if self.use_fixed_lot else "Dynamic (1.0% Equity Risk)"
        
        metrics = [
            ["Symbol", result.symbol],
            ["Strategy Framework", "SLK + CRT + ABC/XYZ Multi-Timeframe"],
            ["Lot Sizing", lot_desc],
            ["Initial Balance", f"${result.initial_balance:,.2f}"],
            ["Final Balance", f"${result.final_balance:,.2f}"],
            ["Total Net Profit", f"${result.total_net_profit:,.2f} ({result.total_return_pct:+.2f}%)"],
            ["Total Trades Executed", result.total_trades],
            ["Win Rate", f"{result.win_rate_pct:.2f}% ({result.winning_trades}W / {result.losing_trades}L)"],
            ["Profit Factor", f"{result.profit_factor:.2f}"],
            ["Expected Payoff / Trade", f"${result.expected_payoff:,.2f}"],
            ["Max Drawdown ($)", f"${result.max_drawdown_usd:,.2f}"],
            ["Max Drawdown (%)", f"{result.max_drawdown_pct:.2f}%"],
            ["Sharpe Ratio", f"{result.sharpe_ratio:.2f}"],
            ["Session Distribution", f"London: {result.london_trades} | New York: {result.ny_trades}"],
            ["Stop Loss / Take Profit", f"{self.strategy.config.get_sl_pips(result.symbol)} pips / {self.strategy.config.get_tp_pips(result.symbol)} pips (1:3 RR)"],
        ]

        print("\n" + "=" * 65)
        print(f"       SLK & CRT HISTORICAL BACKTEST REPORT: {result.symbol}")
        print("=" * 65)
        
        if HAS_TABULATE:
            print(tabulate(metrics, headers=["Metric", "Value"], tablefmt="fancy_grid"))
        else:
            for row in metrics:
                print(f"  {row[0]:<26} : {row[1]}")
        print("=" * 65 + "\n")

        # Print sample trade executions
        if result.trades:
            print(f"[*] Recent Executed Trades Sample (Total: {len(result.trades)}):")
            sample_trades = result.trades[-5:]
            sample_rows = [
                [t.trade_id, t.order_type, t.lot_size, t.entry_time[:16], t.entry_price, t.exit_time[:16], t.exit_price, t.exit_reason, f"{t.pnl_pips:+.1f}p", f"${t.pnl_usd:+,.2f}", t.session]
                for t in sample_trades
            ]
            headers = ["ID", "Type", "Lot", "Entry Time", "Entry", "Exit Time", "Exit", "Reason", "Pips", "PnL ($)", "Session"]
            if HAS_TABULATE:
                print(tabulate(sample_rows, headers=headers, tablefmt="simple"))
            else:
                for r in sample_rows:
                    print(" | ".join(map(str, r)))
            print()


def find_csv_for_symbol(symbol: str) -> Optional[Path]:
    """Finds the most appropriate CSV file for a given symbol in the data directory."""
    files = list(DATA_DIR.glob(f"*{symbol}*.csv"))
    if not files:
        return None
    # Sort by file size or name to pick the most comprehensive dataset
    files.sort(key=lambda f: f.stat().st_size, reverse=True)
    return files[0]


def generate_sample_data(symbol: str, num_bars: int = 1500) -> pd.DataFrame:
    """Generates realistic synthetic 15-minute candlestick data for testing."""
    np.random.seed(42 if symbol == "EURUSD" else (43 if symbol == "GBPUSD" else 44))
    
    spec = SUPPORTED_SYMBOLS[symbol]
    start_prices = {"EURUSD": 1.08500, "GBPUSD": 1.26500, "XAUUSD": 2350.00}
    volatilities = {"EURUSD": 0.00030, "GBPUSD": 0.00045, "XAUUSD": 1.50}

    base_price = start_prices.get(symbol, 1.0)
    vol = volatilities.get(symbol, 0.001)

    timestamps = pd.date_range(end=pd.Timestamp.now(), periods=num_bars, freq="15min")
    
    returns = np.random.normal(0.00005, 1.0, num_bars)
    for burst in range(5, num_bars, 80):
        direction = 1 if np.random.rand() > 0.45 else -1
        returns[burst:burst + 10] += direction * 1.8

    price_series = base_price + np.cumsum(returns * vol)
    opens = price_series[:-1]
    closes = price_series[1:]
    highs = np.maximum(opens, closes) + np.abs(np.random.normal(0, vol * 0.7, num_bars - 1))
    lows = np.minimum(opens, closes) - np.abs(np.random.normal(0, vol * 0.7, num_bars - 1))
    volumes = np.random.randint(50, 1500, num_bars - 1)

    df = pd.DataFrame({
        "time": timestamps[1:],
        "open": np.round(opens, spec.digits),
        "high": np.round(highs, spec.digits),
        "low": np.round(lows, spec.digits),
        "close": np.round(closes, spec.digits),
        "tick_volume": volumes
    })
    return df


def main():
    """Main CLI execution for running backtests."""
    parser = argparse.ArgumentParser(description="SLK & CRT Multi-Timeframe Backtesting Engine")
    parser.add_argument("--symbol", type=str, default="ALL", choices=["EURUSD", "GBPUSD", "XAUUSD", "ALL"],
                        help="Symbol to backtest (or 'ALL' to test all supported symbols)")
    parser.add_argument("--balance", type=float, default=10000.0, help="Initial backtest balance")
    parser.add_argument("--tp", type=float, default=150.0, help="Take profit in pips (e.g. 150.0 or 250.0)")
    parser.add_argument("--sl", type=float, default=50.0, help="Stop loss in pips (default 50.0)")
    parser.add_argument("--lotsize", type=str, default="fixed", choices=["fixed", "dynamic"],
                        help="Lot sizing mode: 'fixed' (0.05 for FX, 0.02 for Gold) or 'dynamic' (1% equity risk)")
    parser.add_argument("--csv", type=str, default="", help="Optional explicit path to CSV data file")
    args = parser.parse_args()

    symbols_to_test = list(SUPPORTED_SYMBOLS.keys()) if args.symbol == "ALL" else [args.symbol]
    use_fixed_lot = (args.lotsize == "fixed")

    backtester = Backtester(
        initial_balance=args.balance,
        use_fixed_lot=use_fixed_lot,
        tp_pips=args.tp,
        sl_pips=args.sl
    )

    for sym in symbols_to_test:
        if args.csv and Path(args.csv).exists():
            csv_file = Path(args.csv)
        else:
            csv_file = find_csv_for_symbol(sym)
        
        if csv_file is None or not csv_file.exists():
            print(f"[*] No CSV found for {sym} in data/. Generating sample dataset...")
            sample_df = generate_sample_data(sym, num_bars=2000)
            target_path = DATA_DIR / f"{sym}_M15.csv"
            sample_df.to_csv(target_path, index=False)
            df = sample_df
        else:
            print(f"[*] Ingesting historical CSV for {sym} from: {csv_file.name}")
            df = backtester.load_csv_data(csv_file)

        print(f"[*] Starting SLK & CRT multi-timeframe backtest on {sym} ({len(df):,} bars)...")
        result = backtester.run(sym, df)
        backtester.print_summary(result)


if __name__ == "__main__":
    main()
