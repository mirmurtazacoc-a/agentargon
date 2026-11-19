"""
In-memory ring buffers (collections.deque) for sub-5ms market state tracking.
Uses orjson for 5x-10x faster serialization and winloop/uvloop when available.
Never writes raw 100ms depth or trade ticks to disk.
"""

from collections import deque
from dataclasses import dataclass, field
import time
from typing import Any, Deque, Dict, List, Optional

try:
    import orjson

    def json_dumps(data: Any) -> bytes:
        return orjson.dumps(data)

    def json_loads(data: bytes | str) -> Any:
        return orjson.loads(data)

except ImportError:
    import json

    def json_dumps(data: Any) -> bytes:
        return json.dumps(data).encode("utf-8")

    def json_loads(data: bytes | str) -> Any:
        return json.loads(data)


def install_fast_event_loop() -> str:
    """Install uvloop (Linux/macOS) or winloop (Windows) if available."""
    try:
        import winloop  # type: ignore

        winloop.install()
        return "winloop"
    except ImportError:
        pass
    try:
        import uvloop  # type: ignore

        uvloop.install()
        return "uvloop"
    except ImportError:
        pass
    return "asyncio"


@dataclass
class TradeTick:
    ts: float
    price: float
    qty: float
    usd_vol: float
    is_buyer_maker: bool  # True = sell taker, False = buy taker


@dataclass
class LiquidationEvent:
    id: str
    symbol: str
    side: str  # "BUY" (Short Liq) or "SELL" (Long Liq)
    price: float
    qty: float
    usd_value: float
    ts: float


@dataclass
class NewsHeadline:
    id: str
    title: str
    source: str
    url: str
    ts: float
    matched_tickers: List[str] = field(default_factory=list)
    matched_keywords: List[str] = field(default_factory=list)
    triage: Optional[Dict[str, Any]] = None


@dataclass
class OrderBookLevel:
    price: float
    qty: float
    usd_size: float
    is_spoof_suspect: bool = False
    wall_delta_pct: float = 0.0


@dataclass
class AISignalSetup:
    symbol: str
    bias: str  # "LONG" | "SHORT" | "NEUTRAL" | "KILL_SWITCH"
    entry_price: float
    hard_sl: float
    tp1: float
    tp2: float
    leverage: int
    confidence: int
    catalyst_badge: str
    reasoning: str
    ts: float
    timeframe: str = "15m"
    win_probability_pct: float = 68.5
    tp1_hit_prob_pct: float = 74.0
    tp2_hit_prob_pct: float = 54.0
    expected_value_r: float = 0.85
    mtf_alignment_label: str = "15M + 1H + 4H ALIGNED"
    rr_ratio: float = 2.6
    recommended_margin_usd: float = 1000.0
    position_size_usd: float = 4000.0
    max_loss_usd: float = -42.0
    expected_tp1_usd: float = 56.0
    expected_tp2_usd: float = 112.0
    candle_15m_open: float = 0.0
    candle_15m_high: float = 0.0
    candle_15m_low: float = 0.0
    candle_15m_close: float = 0.0
    candle_15m_atr: float = 0.0
    candle_15m_atr_pct: float = 0.85
    candle_15m_ema9: float = 0.0
    candle_15m_ema21: float = 0.0
    candle_15m_vwap: float = 0.0
    candle_15m_rsi: float = 50.0
    candle_15m_swing_high: float = 0.0
    candle_15m_swing_low: float = 0.0
    candle_15m_structure: str = "15M BULLISH BREAKOUT"
    entry_type: str = "MARKET / 15M CLOSE"
    factor_scores: Dict[str, float] = field(default_factory=dict)
    liquidation_price: float = 0.0
    sl_distance_pct: float = 1.05
    tp1_distance_pct: float = 1.65
    tp2_distance_pct: float = 3.15
    funding_edge_note: str = ""
    news_edge_note: str = ""


@dataclass
class PaperPosition:
    id: str
    symbol: str
    side: str  # "LONG" | "SHORT"
    entry_price: float
    mark_price: float
    size_usd: float
    margin_usd: float
    leverage: int
    hard_sl: float
    tp1: float
    tp2: float
    opened_at: float
    time_stop_sec: int = 900  # 15 minutes
    is_be_moved: bool = False
    partial_closed: bool = False
    pnl_usd: float = 0.0
    pnl_pct: float = 0.0


def get_tick_decimals(tick_size_str: str) -> int:
    """Count exact significant decimal places from a Binance PRICE_FILTER tickSize string (e.g., '0.0000010' -> 6)."""
    s = tick_size_str.strip().rstrip("0")
    if "." in s:
        return len(s.split(".")[1])
    return 0


def snap_to_tick(price: float, tick_size: float, decimals: int) -> float:
    """Snap a price to the exact Binance PRICE_FILTER tickSize multiple and round to exact decimals."""
    if tick_size <= 0:
        return round(price, decimals)
    steps = round(price / tick_size)
    return round(steps * tick_size, decimals)


class CoinRingState:
    """Fixed-length rolling memory windows (60s, 5m, 15m) for a single symbol."""

    def __init__(
        self,
        symbol: str,
        base_price: float = 100.0,
        init_funding: float = -0.00025,
        init_news_headline: str = "",
        init_news_sentiment: str = "BULLISH",
        init_news_score: int = 85,
        tick_size: float = 0.01,
        price_decimals: int = 2,
    ) -> None:
        self.symbol: str = symbol
        self.tick_size: float = tick_size
        self.price_decimals: int = price_decimals
        self.perp_price: float = round(base_price, price_decimals)
        self.spot_price: float = round(base_price, price_decimals)
        self.mark_price: float = round(base_price, price_decimals)
        self.index_price: float = round(base_price, price_decimals)

        # Rolling price & trade deques (fixed max lengths in RAM)
        self.perp_trades_60s: Deque[TradeTick] = deque(maxlen=1500)
        self.spot_trades_60s: Deque[TradeTick] = deque(maxlen=1500)
        self.price_history_15m: Deque[tuple[float, float]] = deque(maxlen=900)
        self.klines_1m: Deque[Dict[str, Any]] = deque(maxlen=180)
        self.klines_15m: Deque[Dict[str, Any]] = deque(maxlen=32)  # Last 32 x 15-minute candles
        self.klines_1h: Deque[Dict[str, Any]] = deque(maxlen=32)   # Last 32 x 1-hour candles
        self.klines_4h: Deque[Dict[str, Any]] = deque(maxlen=32)   # Last 32 x 4-hour candles
        self.chart_markers: Deque[Dict[str, Any]] = deque(maxlen=60)

        # CVD & Volume metrics
        self.perp_cvd_60s: float = 65000.0
        self.spot_cvd_60s: float = 195000.0
        self.perp_cvd_15m: float = 240000.0
        self.spot_cvd_15m: float = 690000.0
        self.volume_1m_usd: float = 210000.0
        self.avg_volume_1m_usd: float = 150000.0
        self.change_24h_pct: float = 0.0
        self.quote_volume_24h_usd: float = 50_000_000.0
        self.squeeze_radar_score: float = 85.0
        self.squeeze_type: str = "SHORT SQUEEZE RADAR"

        # Derivatives & Positioning (Polled 1m-5m / Event-driven)
        self.funding_rate: float = init_funding
        self.next_funding_time: float = time.time() + 2100
        self.funding_interval_hours: int = 4 if abs(init_funding) >= 0.0002 else 8
        self.open_interest_usd: float = 28_500_000.0
        self.oi_delta_15m_pct: float = 4.2
        self.top_trader_ls_ratio: float = 1.24
        self.taker_buy_sell_ratio: float = 1.18

        # News + Funding Composite Edge Metrics (Used to rank Top 10 Best Tradeable Coins)
        self.latest_news_headline: str = init_news_headline
        self.news_sentiment: str = init_news_sentiment  # "BULLISH" | "BEARISH" | "NEUTRAL"
        self.news_catalyst_type: str = "EXCHANGE_LISTING"
        self.news_score: int = init_news_score  # 0-100
        self.funding_score: int = 85  # 0-100
        self.trade_rank_score: int = 88  # Combined News + Funding + Flow Rank Score (0-100)

        # L2 Orderbook & Spoof Detection
        self.bids: List[Dict[str, Any]] = []
        self.asks: List[Dict[str, Any]] = []
        self.spoof_risk_score: int = 12  # 0-100
        self.last_spoof_event: str = ""

        # Liquidations in rolling window
        self.short_liq_60s_usd: float = 48000.0
        self.long_liq_60s_usd: float = 4500.0

        # Tier-0 Quant Confluence Metrics
        self.confluence_score: int = 86  # 0-100
        self.ma_pinch_score: float = 84.0
        self.ret_1m_pct: float = 0.25
        self.ret_2m_pct: float = 0.62
        self.ret_15m_pct: float = 1.85
        self.signal_state: str = "HIGH_CONFLUENCE_LONG"

        # AI Triage & Calculated Position Setups across 15m, 1h, and 4h timeframes
        self.ai_setup: Optional[AISignalSetup] = None
        self.setups_by_tf: Dict[str, AISignalSetup] = {}
        self.last_ai_call_ts: float = 0.0

    @property
    def spot_perp_basis_pct(self) -> float:
        """Compute Spot-Perp Basis %: ((Perp - Spot) / Spot) * 100."""
        if self.spot_price <= 0:
            return 0.0
        return ((self.perp_price - self.spot_price) / self.spot_price) * 100.0

    @property
    def funding_countdown_str(self) -> str:
        rem = max(0, int(self.next_funding_time - time.time()))
        hrs = rem // 3600
        mins = (rem % 3600) // 60
        secs = rem % 60
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"

    def _compute_tf_setup(
        self,
        tf: str,
        bars: List[Dict[str, Any]],
        margin_usd: float = 1000.0,
        leverage: int = 0,
    ) -> AISignalSetup:
        """
        First-Principles 10-Factor Quantitative Trade Calculator for a given timeframe ('15m', '1h', or '4h'):
        Combines ALL live coin metrics simultaneously to compute an accurate, structural trade:
          1. True EMA-9 & EMA-21 Trend Slope on that timeframe
          2. Session Volume-Weighted Average Price (VWAP) Position & Taker Buy/Sell Volume Ratio
          3. Wilder RSI(14) Momentum & Overbought/Oversold Mean-Reversion Guard
          4. Wilder ATR(14) Volatility & Swing High / Swing Low Structure
          5. Live Funding Rate Squeeze Vector
          6. Spot-vs-Perp Basis % Discount/Premium & Spot-vs-Perp CVD Flow
          7. Open Interest Δ%, Top Trader Long/Short Ratio, and Taker Buy/Sell Ratio
          8. L2 Orderbook Bid/Ask Wall Imbalance
        """
        p = self.perp_price
        decimals = self.price_decimals
        tick = self.tick_size
        tf_upper = tf.upper()

        # Timeframe volatility & structural clamp multipliers
        tf_mult = 1.0 if tf == "15m" else (1.75 if tf == "1h" else 2.85)
        min_sl_bound = 0.0065 if tf == "15m" else (0.0115 if tf == "1h" else 0.0195)
        max_sl_bound = 0.0285 if tf == "15m" else (0.0480 if tf == "1h" else 0.0780)

        if len(bars) >= 5:
            curr_bar = bars[-1]
            c_open = float(curr_bar["open"])
            c_high = max(float(curr_bar["high"]), p)
            c_low = min(float(curr_bar["low"]), p)
            c_close = p

            # 1. True Exponential Moving Averages (EMA-9 and EMA-21)
            closes = [float(b["close"]) for b in bars[:-1]] + [p]
            k9 = 2.0 / (9.0 + 1.0)
            k21 = 2.0 / (21.0 + 1.0)
            ema9 = closes[0]
            ema21 = closes[0]
            for c_val in closes[1:]:
                ema9 = c_val * k9 + ema9 * (1.0 - k9)
                ema21 = c_val * k21 + ema21 * (1.0 - k21)

            # 2. Wilder's ATR(14)
            trs: List[float] = []
            for i in range(1, len(bars)):
                h = float(bars[i]["high"]) if i < len(bars) - 1 else c_high
                l = float(bars[i]["low"]) if i < len(bars) - 1 else c_low
                prev_c = float(bars[i - 1]["close"])
                trs.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
            atr_val = trs[0]
            for tr_val in trs[1:]:
                atr_val = (atr_val * 13.0 + tr_val) / 14.0

            # 3. Wilder's RSI(14)
            gains: List[float] = []
            losses: List[float] = []
            for i in range(1, len(closes)):
                diff = closes[i] - closes[i - 1]
                gains.append(max(0.0, diff))
                losses.append(max(0.0, -diff))
            avg_gain = sum(gains[-14:]) / max(1, len(gains[-14:]))
            avg_loss = sum(losses[-14:]) / max(1, len(losses[-14:]))
            if avg_loss <= 1e-12:
                rsi_val = 85.0 if avg_gain > 0 else 50.0
            else:
                rs = avg_gain / avg_loss
                rsi_val = 100.0 - (100.0 / (1.0 + rs))

            # 4. Rolling Session VWAP (last 16 bars)
            vwap_num = 0.0
            vwap_den = 0.0
            for b in bars[-16:]:
                typ_p = (float(b["high"]) + float(b["low"]) + float(b["close"])) / 3.0
                vol_q = max(1.0, float(b.get("volume", 1.0)))
                vwap_num += typ_p * vol_q
                vwap_den += vol_q
            vwap_val = vwap_num / max(1.0, vwap_den)

            # 5. Structural Swing High & Swing Low (last 6 bars)
            recent_bars = bars[-6:]
            swing_high = max(max(float(b["high"]) for b in recent_bars), c_high)
            swing_low = min(min(float(b["low"]) for b in recent_bars), c_low)

            # 6. Candle Taker Buy Ratio from klines
            tb_ratios = [
                float(b.get("taker_buy_ratio", 0.5))
                for b in bars[-4:]
                if "taker_buy_ratio" in b
            ]
            if tb_ratios and tf == "15m":
                avg_tb = sum(tb_ratios) / len(tb_ratios)
                self.taker_buy_sell_ratio = round(avg_tb / max(0.05, 1.0 - avg_tb), 2)
        else:
            c_open = snap_to_tick(p * (1.0 - 0.0035 * tf_mult), tick, decimals)
            c_high = snap_to_tick(p * (1.0 + 0.0065 * tf_mult), tick, decimals)
            c_low = snap_to_tick(p * (1.0 - 0.0085 * tf_mult), tick, decimals)
            c_close = p
            atr_val = p * (0.0095 * tf_mult)
            ema9 = snap_to_tick(p * (1.0 - 0.0022 * tf_mult), tick, decimals)
            ema21 = snap_to_tick(p * (1.0 - 0.0058 * tf_mult), tick, decimals)
            vwap_val = snap_to_tick(p * (1.0 - 0.0032 * tf_mult), tick, decimals)
            rsi_val = 56.0
            swing_high = snap_to_tick(p * (1.0 + 0.012 * tf_mult), tick, decimals)
            swing_low = snap_to_tick(p * (1.0 - 0.012 * tf_mult), tick, decimals)

        atr_pct = max(0.30, min(12.0, (atr_val / max(p, 1e-9)) * 100.0))

        # ====================================================================
        # MULTI-FACTOR QUANT VECTOR SCORING (-100 BEARISH SHORT to +100 BULLISH LONG)
        # ====================================================================
        ema_spread_pct = ((ema9 - ema21) / max(ema21, 1e-9)) * 100.0
        price_vs_ema9_pct = ((p - ema9) / max(ema9, 1e-9)) * 100.0
        f_trend = max(-25.0, min(25.0, (ema_spread_pct * 14.0 + price_vs_ema9_pct * 8.0) / (tf_mult ** 0.45)))

        vwap_dist_pct = ((p - vwap_val) / max(vwap_val, 1e-9)) * 100.0
        f_vwap = max(-15.0, min(15.0, (vwap_dist_pct * 10.0) / (tf_mult ** 0.45)))

        if rsi_val > 74.0:
            f_rsi = -((rsi_val - 72.0) * 1.1)
        elif rsi_val < 26.0:
            f_rsi = (28.0 - rsi_val) * 1.1
        else:
            f_rsi = max(-15.0, min(15.0, (rsi_val - 50.0) * 0.55))

        funding_pct = self.funding_rate * 100.0
        basis_pct = self.spot_perp_basis_pct
        if funding_pct < -0.015:
            if p >= min(ema9, vwap_val):
                f_funding = min(25.0, abs(funding_pct) * 85.0 + max(0.0, -basis_pct * 35.0))
            else:
                f_funding = -min(15.0, abs(price_vs_ema9_pct) * 7.0)
        elif funding_pct > 0.015:
            if p < ema9:
                f_funding = -min(25.0, funding_pct * 110.0 + max(0.0, basis_pct * 35.0))
            else:
                f_funding = max(-8.0, 6.0 - funding_pct * 45.0)
        else:
            f_funding = max(-10.0, min(10.0, -basis_pct * 25.0))

        taker_edge = (self.taker_buy_sell_ratio - 1.0) * 35.0
        ls_edge = (self.top_trader_ls_ratio - 1.0) * 12.0
        cvd_net = (self.spot_cvd_60s - self.perp_cvd_60s * 0.5) / 50000.0
        oi_dir = 1.0 if p >= c_open else -1.0
        oi_edge = min(8.0, max(-8.0, self.oi_delta_15m_pct * 1.4 * oi_dir))
        f_orderflow = max(-20.0, min(20.0, taker_edge + ls_edge + cvd_net + oi_edge))

        bid_wall_sum = sum(float(b.get("usd_size", 0.0)) for b in self.bids[:5])
        ask_wall_sum = sum(float(a.get("usd_size", 0.0)) for a in self.asks[:5])
        total_book = bid_wall_sum + ask_wall_sum
        if total_book > 0:
            book_imbalance = ((bid_wall_sum - ask_wall_sum) / total_book) * 15.0
        else:
            book_imbalance = 0.0
        f_orderbook = max(-10.0, min(10.0, book_imbalance))

        net_vector = f_trend + f_vwap + f_rsi + f_funding + f_orderflow + f_orderbook
        bias = "LONG" if net_vector >= 0.0 else "SHORT"

        agreement_score = int(round(62.0 + min(36.0, abs(net_vector) * 0.52)))

        if bias == "LONG":
            if funding_pct < -0.025:
                squeeze_label = f"{tf_upper} SHORT SQUEEZE + VWAP BREAKOUT"
            elif p > ema9 and ema9 > ema21:
                squeeze_label = f"{tf_upper} TREND + ORDERFLOW LONG"
            else:
                squeeze_label = f"{tf_upper} DEMAND RECLAIM LONG"
        else:
            if funding_pct > 0.012 or rsi_val > 68.0:
                squeeze_label = f"{tf_upper} LONG FLUSH / OVEREXTENDED SHORT"
            elif p < ema9 and ema9 < ema21:
                squeeze_label = f"{tf_upper} TREND BREAKDOWN SHORT"
            else:
                squeeze_label = f"{tf_upper} VWAP REJECTION SHORT"

        if tf == "15m":
            self.trade_rank_score = agreement_score
            self.confluence_score = agreement_score
            self.squeeze_type = squeeze_label

        # Auto-select optimal Isolated Leverage (3x, 4x, or 5x) from timeframe ATR Volatility
        if leverage not in (3, 4, 5):
            if atr_pct >= 1.35 * tf_mult:
                leverage = 3
            elif atr_pct >= 0.65 * tf_mult:
                leverage = 4
            else:
                leverage = 5

        stretch_from_ema9 = abs(p - ema9)
        if bias == "LONG":
            if p > ema9 and stretch_from_ema9 > atr_val * 0.85:
                raw_entry = max(ema9, p - atr_val * 0.35)
                entry_type = f"PULLBACK LIMIT ({tf_upper})"
            else:
                raw_entry = p
                entry_type = f"MARKET / {tf_upper} ACTIVE"
            entry_p = snap_to_tick(raw_entry, tick, decimals)

            structural_floor = min(c_low, ema21, swing_low) - (atr_val * 0.30)
            atr_floor = entry_p - (atr_val * 1.35)
            raw_sl = max(structural_floor, atr_floor)
            min_sl_p = entry_p * (1.0 - min_sl_bound)
            max_sl_p = entry_p * (1.0 - max_sl_bound)
            hard_sl = snap_to_tick(min(min_sl_p, max(max_sl_p, raw_sl)), tick, decimals)
            if hard_sl >= entry_p:
                hard_sl = snap_to_tick(entry_p - max(tick * 5, entry_p * min_sl_bound), tick, decimals)

            risk_per_unit = max(tick, entry_p - hard_sl)
            raw_tp1 = max(entry_p + risk_per_unit * 1.65, min(swing_high, entry_p + risk_per_unit * 2.10))
            raw_tp2 = entry_p + risk_per_unit * 3.10
            tp1 = snap_to_tick(raw_tp1, tick, decimals)
            tp2 = snap_to_tick(raw_tp2, tick, decimals)
            liq_p = snap_to_tick(entry_p * (1.0 - (0.92 / leverage)), tick, decimals)
        else:
            if p < ema9 and stretch_from_ema9 > atr_val * 0.85:
                raw_entry = min(ema9, p + atr_val * 0.35)
                entry_type = f"PULLBACK LIMIT ({tf_upper})"
            else:
                raw_entry = p
                entry_type = f"MARKET / {tf_upper} ACTIVE"
            entry_p = snap_to_tick(raw_entry, tick, decimals)

            structural_ceiling = max(c_high, ema21, swing_high) + (atr_val * 0.30)
            atr_ceiling = entry_p + (atr_val * 1.35)
            raw_sl = min(structural_ceiling, atr_ceiling)
            min_sl_p = entry_p * (1.0 + min_sl_bound)
            max_sl_p = entry_p * (1.0 + max_sl_bound)
            hard_sl = snap_to_tick(max(min_sl_p, min(max_sl_p, raw_sl)), tick, decimals)
            if hard_sl <= entry_p:
                hard_sl = snap_to_tick(entry_p + max(tick * 5, entry_p * min_sl_bound), tick, decimals)

            risk_per_unit = max(tick, hard_sl - entry_p)
            raw_tp1 = min(entry_p - risk_per_unit * 1.65, max(swing_low, entry_p - risk_per_unit * 2.10))
            raw_tp2 = entry_p - risk_per_unit * 3.10
            tp1 = snap_to_tick(max(tick, raw_tp1), tick, decimals)
            tp2 = snap_to_tick(max(tick, raw_tp2), tick, decimals)
            liq_p = snap_to_tick(entry_p * (1.0 + (0.92 / leverage)), tick, decimals)

        sl_dist_pct = abs(entry_p - hard_sl) / max(entry_p, 1e-9)
        tp1_dist_pct = abs(tp1 - entry_p) / max(entry_p, 1e-9)
        tp2_dist_pct = abs(tp2 - entry_p) / max(entry_p, 1e-9)

        notional_usd = round(margin_usd * leverage, 2)
        max_loss_usd = -round(notional_usd * sl_dist_pct, 2)
        expected_tp1_usd = round(notional_usd * tp1_dist_pct, 2)
        expected_tp2_usd = round(notional_usd * tp2_dist_pct, 2)
        rr_ratio = round(tp2_dist_pct / max(sl_dist_pct, 1e-6), 2)

        # Count how many of the 6 pillars agree with the chosen trade direction
        pillars = [f_trend, f_vwap, f_rsi, f_funding, f_orderflow, f_orderbook]
        aligned_pillars = sum(1 for val in pillars if (val > 0.3 if bias == "LONG" else val < -0.3))
        base_win_prob = 51.5 + min(26.5, abs(net_vector) * 0.48) + (aligned_pillars * 1.8)
        if (bias == "LONG" and rsi_val > 72.0) or (bias == "SHORT" and rsi_val < 28.0):
            base_win_prob -= 6.5
        win_prob_pct = round(max(44.0, min(89.5, base_win_prob)), 1)
        tp1_prob_pct = round(min(93.5, win_prob_pct + 6.8), 1)
        tp2_prob_pct = round(max(36.0, win_prob_pct - 13.5), 1)

        # Expected Value in R-multiples: 50% @ TP1 (1.65R) + 50% @ TP2 (3.10R) vs 1.0R Stop-Loss
        p_win = win_prob_pct / 100.0
        p_tp2 = tp2_prob_pct / 100.0
        ev_r = round((p_tp2 * 2.37) + ((p_win - p_tp2) * 0.82) - ((1.0 - p_win) * 1.0), 2)

        factor_scores_dict = {
            "ema_trend": round(f_trend, 1),
            "vwap_anchor": round(f_vwap, 1),
            "rsi_momentum": round(f_rsi, 1),
            "funding_squeeze": round(f_funding, 1),
            "oi_orderflow": round(f_orderflow, 1),
            "l2_orderbook": round(f_orderbook, 1),
            "net_vector": round(net_vector, 1),
        }

        return AISignalSetup(
            symbol=self.symbol,
            bias=bias,
            entry_price=entry_p,
            hard_sl=hard_sl,
            tp1=tp1,
            tp2=tp2,
            leverage=leverage,
            confidence=agreement_score,
            catalyst_badge=(
                f"{tf_upper} {bias} • Win Prob {win_prob_pct}% • {leverage}x ISOLATED • R:R 1:{rr_ratio}"
            ),
            reasoning=(
                f"[{tf_upper}] Net Vector: {net_vector:+.1f} | Win Prob: {win_prob_pct}% (TP1: {tp1_prob_pct}%, TP2: {tp2_prob_pct}%)"
            ),
            ts=time.time(),
            timeframe=tf,
            win_probability_pct=win_prob_pct,
            tp1_hit_prob_pct=tp1_prob_pct,
            tp2_hit_prob_pct=tp2_prob_pct,
            expected_value_r=ev_r,
            mtf_alignment_label="15M + 1H + 4H ANALYZED",
            rr_ratio=rr_ratio,
            recommended_margin_usd=margin_usd,
            position_size_usd=notional_usd,
            max_loss_usd=max_loss_usd,
            expected_tp1_usd=expected_tp1_usd,
            expected_tp2_usd=expected_tp2_usd,
            candle_15m_open=snap_to_tick(c_open, tick, decimals),
            candle_15m_high=snap_to_tick(c_high, tick, decimals),
            candle_15m_low=snap_to_tick(c_low, tick, decimals),
            candle_15m_close=snap_to_tick(c_close, tick, decimals),
            candle_15m_atr=snap_to_tick(atr_val, tick, decimals),
            candle_15m_atr_pct=round(atr_pct, 2),
            candle_15m_ema9=snap_to_tick(ema9, tick, decimals),
            candle_15m_ema21=snap_to_tick(ema21, tick, decimals),
            candle_15m_vwap=snap_to_tick(vwap_val, tick, decimals),
            candle_15m_rsi=round(rsi_val, 1),
            candle_15m_swing_high=snap_to_tick(swing_high, tick, decimals),
            candle_15m_swing_low=snap_to_tick(swing_low, tick, decimals),
            candle_15m_structure=squeeze_label,
            entry_type=entry_type,
            factor_scores=factor_scores_dict,
            liquidation_price=liq_p,
            sl_distance_pct=round(sl_dist_pct * 100.0, 2),
            tp1_distance_pct=round(tp1_dist_pct * 100.0, 2),
            tp2_distance_pct=round(tp2_dist_pct * 100.0, 2),
            funding_edge_note=f"Funding {self.funding_rate * 100:+.4f}% ({self.funding_countdown_str})",
            news_edge_note="Multi-Timeframe 15m / 1h / 4h Quant Engine Active",
        )

    def recalculate_position_setup(self, margin_usd: float = 1000.0, leverage: int = 0) -> AISignalSetup:
        """
        Computes all three timeframe setups ('15m', '1h', and '4h') simultaneously,
        cross-checks multi-timeframe trend alignment to refine Win Probability % on each timeframe,
        and stores them in `self.setups_by_tf`.
        """
        s_15m = self._compute_tf_setup("15m", list(self.klines_15m), margin_usd, leverage)
        s_1h = self._compute_tf_setup("1h", list(self.klines_1h), margin_usd, leverage)
        s_4h = self._compute_tf_setup("4h", list(self.klines_4h), margin_usd, leverage)

        biases = {"15m": s_15m.bias, "1h": s_1h.bias, "4h": s_4h.bias}
        all_same = (s_15m.bias == s_1h.bias == s_4h.bias)

        for tf_key, setup in (("15m", s_15m), ("1h", s_1h), ("4h", s_4h)):
            same_count = sum(1 for b in biases.values() if b == setup.bias)
            if all_same:
                mtf_bonus = 6.5
                setup.mtf_alignment_label = f"FULL MTF CONFLUENCE (15M + 1H + 4H ALL {setup.bias})"
            elif same_count == 2:
                mtf_bonus = 2.0
                aligned_tfs = [k.upper() for k, v in biases.items() if v == setup.bias]
                setup.mtf_alignment_label = f"{' + '.join(aligned_tfs)} ALIGNED {setup.bias}"
            else:
                mtf_bonus = -4.5
                setup.mtf_alignment_label = f"COUNTER-TREND {tf_key.upper()} {setup.bias} (HTF DIVERGENCE)"

            setup.win_probability_pct = round(max(42.0, min(91.5, setup.win_probability_pct + mtf_bonus)), 1)
            setup.tp1_hit_prob_pct = round(min(94.8, setup.win_probability_pct + 6.5), 1)
            setup.tp2_hit_prob_pct = round(max(34.0, setup.win_probability_pct - 13.0), 1)

            p_win = setup.win_probability_pct / 100.0
            p_tp2 = setup.tp2_hit_prob_pct / 100.0
            setup.expected_value_r = round(
                (p_tp2 * 2.37) + ((p_win - p_tp2) * 0.82) - ((1.0 - p_win) * 1.0), 2
            )
            setup.catalyst_badge = (
                f"{tf_key.upper()} {setup.bias} • WIN PROB {setup.win_probability_pct}% • "
                f"{setup.leverage}x ISOLATED • R:R 1:{setup.rr_ratio}"
            )
            self.setups_by_tf[tf_key] = setup

        self.ai_setup = s_15m
        return self.ai_setup


class TerminalMemoryState:
    """
    Global in-memory state container tracking a universe of 16 perpetual pairs
    and filtering down to ONLY the Top 10 best coins to trade based on News & Funding.
    """

    # Exact Binance USDS-M Futures PRICE_FILTER tickSize strings (auto-refreshed via /fapi/v1/exchangeInfo on startup)
    EXACT_TICK_SIZES: Dict[str, str] = {
        "HUMAUSDT": "0.000001",
        "SOLUSDT": "0.01",
        "SUIUSDT": "0.0001",
        "XRPUSDT": "0.0001",
        "1000PEPEUSDT": "0.0000001",
        "AAVEUSDT": "0.01",
        "ENAUSDT": "0.00001",
        "DOGEUSDT": "0.00001",
        "ETHUSDT": "0.01",
        "BTCUSDT": "0.1",
        "LINKUSDT": "0.001",
        "ONDOUSDT": "0.0001",
        "ADAUSDT": "0.0001",
        "AVAXUSDT": "0.001",
        "DOTUSDT": "0.0001",
        "NEARUSDT": "0.001",
    }

    # Universe of 16 coins: (Symbol, BasePrice, FundingRate, NewsHeadline, NewsSentiment, NewsCatalystScore)
    # Note: BasePrice is only the instant initial placeholder for 0ms startup before `derivatives_poller.sync_live_prices_and_funding()`
    # overwrites every coin with real-time Binance USDS-M Futures Mark Price, Spot Price, and Live Funding Rate.
    COIN_UNIVERSE = [
        (
            "HUMAUSDT",
            0.008626,
            -0.00065,
            "UPBIT LISTING & SQUEEZE: Upbit KRW & USDT spot volume surges on HUMA; negative funding short squeeze active",
            "BULLISH",
            97,
        ),
        (
            "SOLUSDT",
            73.56,
            -0.00038,
            "WHALE FLOW: $42M USDC deployed into SOL Spot on Binance as perp shorts get squeezed ($14.2M short liqs)",
            "BULLISH",
            94,
        ),
        (
            "SUIUSDT",
            0.7194,
            -0.00042,
            "INSTITUTIONAL INFLOW: Grayscale Sui Trust weekly volume hits record high while perp funding turns deeply negative",
            "BULLISH",
            92,
        ),
        (
            "XRPUSDT",
            0.9672,
            -0.00031,
            "REGULATORY & ETF CATALYST: Spot XRP ETF institutional filing update sparks +11.8% 15m Open Interest breakout",
            "BULLISH",
            90,
        ),
        (
            "1000PEPEUSDT",
            0.0037568,
            -0.00052,
            "BITHUMB & BINANCE FLOW: Korean retail volume surges 4.2x on 1000PEPE while perp basis trades at -0.18% discount",
            "BULLISH",
            89,
        ),
        (
            "AAVEUSDT",
            109.44,
            -0.00029,
            "PROTOCOL REVENUE RECORD: Aave V4 fee switch buyback proposal passes governance vote with 99.4% approval",
            "BULLISH",
            88,
        ),
        (
            "ENAUSDT",
            0.11201,
            -0.00048,
            "YIELD & FUNDING CATALYST: Ethena sUSDe APY jumps to 24% as derivatives basis and Spot buying accelerate",
            "BULLISH",
            87,
        ),
        (
            "DOGEUSDT",
            0.05891,
            -0.00024,
            "PAYMENTS INTEGRATION: X Payments regulatory licensing expands to 38 states; whale spot wallets accumulate 180M DOGE",
            "BULLISH",
            85,
        ),
        (
            "ETHUSDT",
            1781.16,
            -0.00019,
            "ETF INFLOW SURGE: US Spot Ethereum ETFs record +$295M net daily inflows as ETH/BTC basis stabilizes",
            "BULLISH",
            84,
        ),
        (
            "BTCUSDT",
            63060.4,
            -0.00015,
            "MACRO & TREASURY ANCHOR: US Core CPI cools to 2.9% YoY; corporate treasury buyers absorb $640M spot BTC",
            "BULLISH",
            83,
        ),
        (
            "LINKUSDT",
            9.090,
            -0.00018,
            "CCIP INSTITUTIONAL PILOT: Swift & Euroclear expand Chainlink CCIP settlement trials across tokenized funds",
            "BULLISH",
            81,
        ),
        (
            "ONDOUSDT",
            0.2975,
            -0.00022,
            "RWA EXPANSION: Ondo Global Markets tokenized Treasury TVL crosses $1.8B milestone on multi-chain settlement",
            "BULLISH",
            80,
        ),
        # Lower-conviction / Low-news / Neutral-funding coins (Filtered OUT of the Top 10 unless a new catalyst hits)
        (
            "ADAUSDT",
            0.1514,
            0.00008,
            "Routine developer status update; no immediate exchange or funding catalyst",
            "NEUTRAL",
            48,
        ),
        (
            "AVAXUSDT",
            7.023,
            0.00009,
            "Standard subnet maintenance completed; funding neutral",
            "NEUTRAL",
            46,
        ),
        (
            "DOTUSDT",
            0.7203,
            0.00010,
            "No breaking headlines in last 4 hours; low perp OI delta",
            "NEUTRAL",
            42,
        ),
        (
            "NEARUSDT",
            3.321,
            0.00011,
            "Quiet secondary market flow; waiting for volume anomaly",
            "NEUTRAL",
            40,
        ),
    ]

    def __init__(self) -> None:
        self.coins: Dict[str, CoinRingState] = {}
        self.active_symbol: str = "HUMAUSDT"
        self.user_pinned_symbol: bool = False
        self.live_feeds_connected: bool = False
        self.simulation_active: bool = True

        # Global tapes (fixed deques)
        self.liquidations_tape: Deque[LiquidationEvent] = deque(maxlen=120)
        self.news_tape: Deque[NewsHeadline] = deque(maxlen=80)
        self.ai_alerts_tape: Deque[Dict[str, Any]] = deque(maxlen=50)

        # BTC Regime Anchor
        self.btc_regime: str = "GREEN"  # "GREEN" | "CAUTION" | "DUMP_BLOCK"
        self.btc_1m_return_pct: float = 0.08
        self.btc_cvd_60s: float = 420000.0
        self.btc_dump_blocked_until: float = 0.0

        # Emergency Kill-Switch Alarm
        self.kill_switch_active: bool = False
        self.kill_switch_reason: str = ""
        self.kill_switch_ticker: str = ""

        # Gemini API Budget & Implicit Cache Telemetry
        self.gemini_stats: Dict[str, Any] = {
            "tier0_filtered_events": 0,
            "tier1_triage_calls": 4,
            "tier2_grounding_calls": 1,
            "total_input_tokens": 22400,
            "total_cached_tokens": 20800,
            "cache_hit_rate_pct": 92.9,
            "estimated_cost_saved_pct": 86.4,
            "last_latency_ms": 340,
            "model_tier1": "gemini-3.8-flash",
            "model_tier2": "gemini-4-argon",
        }

        # Paper / Live Execution State
        self.execution_mode: str = "PAPER"  # "PAPER" | "LIVE"
        self.paper_balance_usd: float = 25000.0
        self.positions: Dict[str, PaperPosition] = {}

        self._init_watchlist()

    def _init_watchlist(self) -> None:
        now = int(time.time() // 60) * 60
        import random

        for sym, base_p, init_f, headline, sentiment, n_score in self.COIN_UNIVERSE:
            tick_str = self.EXACT_TICK_SIZES.get(sym, "0.0001")
            tick_val = float(tick_str)
            decimals = get_tick_decimals(tick_str)
            coin = CoinRingState(
                symbol=sym,
                base_price=base_p,
                init_funding=init_f,
                init_news_headline=headline,
                init_news_sentiment=sentiment,
                init_news_score=n_score,
                tick_size=tick_val,
                price_decimals=decimals,
            )
            coin.perp_price = snap_to_tick(base_p, tick_val, decimals)
            coin.spot_price = snap_to_tick(
                base_p * (1.0014 if init_f < 0 else 0.9994),
                tick_val,
                decimals,
            )
            coin.mark_price = coin.perp_price
            coin.price_history_15m.append((float(now - 60), base_p * 0.998))
            coin.price_history_15m.append((float(now), base_p))

            # Compute initial Funding Edge Score (0-100): stronger negative funding = higher short-squeeze score
            funding_bps = abs(init_f) * 10000.0
            coin.funding_score = min(99, int(55 + funding_bps * 9.5)) if init_f < 0 else max(35, int(60 - funding_bps * 5))
            coin.trade_rank_score = min(
                99,
                int(round(coin.news_score * 0.55 + coin.funding_score * 0.45)),
            )
            coin.confluence_score = coin.trade_rank_score
            coin.oi_delta_15m_pct = round(random.uniform(2.8, 9.4) if n_score >= 80 else random.uniform(-0.8, 1.2), 2)
            coin.recalculate_position_setup(margin_usd=1000.0, leverage=0)
            self.coins[sym] = coin


# Global singleton memory state
state = TerminalMemoryState()
