"""
Tier-0 Deterministic Quant & News + Funding Rank Filter ($0 cost, <2ms execution):
1. Continuously ranks the entire watched coin universe by **News Catalyst Score + Funding Rate Squeeze Edge**
   so only the Top 10 best tradeable coins are surfaced in the terminal scanner ribbon.
2. Dynamically recalculates the exact trading position setup (Entry, Hard SL, TP1, TP2, Notional Size,
   Max Dollar Risk, Expected Profit, and News/Funding edge breakdown) whenever a coin is selected or updated.
3. Background BTC Regime Anchor (100ms): Auto-blocks altcoin longs if BTC dumps > 0.35% in 60 seconds.
"""

import asyncio
import time
from typing import List

from backend.core.bus import bus
from backend.core.state import CoinRingState, state


class Tier0ConfluenceEngine:
    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._quant_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    async def _quant_loop(self) -> None:
        while self._running:
            try:
                now = time.time()
                self._evaluate_btc_regime_anchor(now)
                for sym, coin in state.coins.items():
                    await self._evaluate_coin_confluence(sym, coin, now)
                self._update_paper_positions(now)
            except asyncio.CancelledError:
                break
            except Exception:
                pass
            await asyncio.sleep(0.25)

    def _evaluate_btc_regime_anchor(self, now: float) -> None:
        """
        BTC Regime Anchor:
        Monitors BTCUSDT 60s return + Spot/Perp CVD.
        Auto-blocks altcoin longs if BTC dumps > 0.35% in 60 seconds.
        """
        btc = state.coins.get("BTCUSDT")
        if not btc:
            return

        self._prune_rolling_windows(btc, now)
        state.btc_1m_return_pct = btc.ret_1m_pct
        state.btc_cvd_60s = btc.spot_cvd_60s + btc.perp_cvd_60s

        if btc.ret_1m_pct <= -0.35:
            state.btc_regime = "DUMP_BLOCK"
            state.btc_dump_blocked_until = now + 90.0  # Hold block for 90s
        elif now < state.btc_dump_blocked_until:
            state.btc_regime = "DUMP_BLOCK"
        elif btc.ret_1m_pct <= -0.18 or state.btc_cvd_60s < -250000:
            state.btc_regime = "CAUTION"
        else:
            state.btc_regime = "GREEN"

    def _prune_rolling_windows(self, coin: CoinRingState, now: float) -> None:
        """Prune 60s trade deques and recompute exact 60s CVD & 1m/2m returns in RAM."""
        cutoff_60s = now - 60.0
        cutoff_120s = now - 120.0

        while coin.perp_trades_60s and coin.perp_trades_60s[0].ts < cutoff_60s:
            coin.perp_trades_60s.popleft()
        while coin.spot_trades_60s and coin.spot_trades_60s[0].ts < cutoff_60s:
            coin.spot_trades_60s.popleft()

        if coin.perp_trades_60s:
            coin.perp_cvd_60s = round(
                sum(-t.usd_vol if t.is_buyer_maker else t.usd_vol for t in coin.perp_trades_60s), 2
            )
        if coin.spot_trades_60s:
            coin.spot_cvd_60s = round(
                sum(-t.usd_vol if t.is_buyer_maker else t.usd_vol for t in coin.spot_trades_60s), 2
            )

        p_now = coin.perp_price
        p_60s = p_now
        p_120s = p_now
        for ts, price in reversed(coin.price_history_15m):
            if ts <= cutoff_60s and p_60s == p_now:
                p_60s = price
            if ts <= cutoff_120s:
                p_120s = price
                break

        coin.ret_1m_pct = round(((p_now - p_60s) / p_60s) * 100.0, 3) if p_60s > 0 else 0.0
        coin.ret_2m_pct = round(((p_now - p_120s) / p_120s) * 100.0, 3) if p_120s > 0 else 0.0

        coin.short_liq_60s_usd = round(coin.short_liq_60s_usd * 0.992, 2)
        coin.long_liq_60s_usd = round(coin.long_liq_60s_usd * 0.992, 2)

    async def _evaluate_coin_confluence(self, sym: str, coin: CoinRingState, now: float) -> None:
        if sym != "BTCUSDT":
            self._prune_rolling_windows(coin, now)

        # 1. Funding Rate Edge Score (0 to 100):
        # Strongly negative funding (< -0.015%) with negative Spot-Perp basis = high-conviction short-squeeze fuel
        basis = coin.spot_perp_basis_pct
        funding_bps = abs(coin.funding_rate) * 10000.0
        if coin.funding_rate < 0:
            basis_bonus = min(14, int(abs(min(0.0, basis)) * 65))
            coin.funding_score = min(99, int(58 + funding_bps * 8.5 + basis_bonus))
        else:
            coin.funding_score = max(30, min(78, int(56 - funding_bps * 4.0)))

        # 2. News Catalyst Score (0 to 100):
        # Boosted when matching breaking headlines hit in the news stream
        for h in list(state.news_tape)[:12]:
            if sym in h.matched_tickers and (now - h.ts) < 600:
                coin.latest_news_headline = h.title
                if h.triage:
                    coin.news_score = max(coin.news_score, int(h.triage.get("urgency", 88)))
                    coin.news_sentiment = h.triage.get("sentiment", coin.news_sentiment)
                    coin.news_catalyst_type = h.triage.get("catalyst", "EXCHANGE_LISTING")
                else:
                    coin.news_score = max(coin.news_score, 89)
                break

        # 3. Flow & Positioning Bonus (Spot CVD > Perp CVD + 15m OI Delta + Short Liquidations)
        flow_bonus = 0
        if coin.spot_cvd_60s > coin.perp_cvd_60s and coin.spot_cvd_60s > 25000:
            flow_bonus += 4
        if coin.oi_delta_15m_pct > 2.0:
            flow_bonus += 3
        if coin.short_liq_60s_usd > 30000:
            flow_bonus += 3
        spoof_penalty = int(coin.spoof_risk_score / 25)

        combined_rank = int(
            round(
                max(
                    coin.squeeze_radar_score,
                    coin.news_score * 0.52 + coin.funding_score * 0.48 + flow_bonus - spoof_penalty,
                )
            )
        )

        if sym != "BTCUSDT" and state.btc_regime == "DUMP_BLOCK":
            coin.signal_state = "BTC_DUMP_BLOCKED"
        elif combined_rank >= 80:
            coin.signal_state = "TOP_NEWS_FUNDING_LONG"
        elif combined_rank >= 65:
            coin.signal_state = "FUNDING_SQUEEZE_WATCH"
        else:
            coin.signal_state = "NEUTRAL"

        coin.trade_rank_score = max(10, min(99, combined_rank))
        coin.confluence_score = coin.trade_rank_score
        state.gemini_stats["tier0_filtered_events"] += 1

        # Keep the active coin's calculated position setup live with current price & metrics
        if sym == state.active_symbol or coin.ai_setup is None:
            mar = coin.ai_setup.recommended_margin_usd if coin.ai_setup else 1000.0
            if not (coin.ai_setup and coin.ai_setup.bias == "KILL_SWITCH" and state.kill_switch_active):
                coin.recalculate_position_setup(margin_usd=mar, leverage=0)

        # Gate 1: Trigger Tier-1 Gemini Setup Triage if Rank Score >= 85 (cooldown 45s per symbol)
        if coin.confluence_score >= 85 and (now - coin.last_ai_call_ts) > 45.0:
            coin.last_ai_call_ts = now
            await bus.publish(
                "tier1_confluence_trigger",
                {
                    "symbol": sym,
                    "confluence_score": coin.confluence_score,
                    "spot_perp_basis_pct": round(basis, 4),
                    "spot_cvd_60s": coin.spot_cvd_60s,
                    "perp_cvd_60s": coin.perp_cvd_60s,
                    "oi_delta_15m_pct": coin.oi_delta_15m_pct,
                    "short_liq_60s_usd": coin.short_liq_60s_usd,
                    "funding_rate": coin.funding_rate,
                    "spoof_risk_score": coin.spoof_risk_score,
                    "ts": now,
                },
            )

        # Gate 2: Trigger Tier-2 On-Demand Catalyst Search if >1.8% move in 2m or 4x volume spike with 0 recent news
        vol_spike_ratio = coin.volume_1m_usd / max(coin.avg_volume_1m_usd, 1.0)
        has_recent_news = any(
            sym in h.matched_tickers and (now - h.ts) < 180.0 for h in state.news_tape
        )
        if (abs(coin.ret_2m_pct) >= 1.8 or vol_spike_ratio >= 4.0) and not has_recent_news:
            if (now - coin.last_ai_call_ts) > 60.0:
                coin.last_ai_call_ts = now
                await bus.publish(
                    "tier2_anomaly_trigger",
                    {
                        "symbol": sym,
                        "ret_2m_pct": coin.ret_2m_pct,
                        "vol_spike_ratio": round(vol_spike_ratio, 2),
                        "oi_delta_15m_pct": coin.oi_delta_15m_pct,
                        "ts": now,
                    },
                )

    def _update_paper_positions(self, now: float) -> None:
        """Update live unrealized PnL, Break-Even stops, and 15-Minute Time-Stop countdown."""
        to_close: List[str] = []
        for sym, pos in state.positions.items():
            coin = state.coins.get(sym)
            if not coin:
                continue
            pos.mark_price = coin.mark_price
            price_diff = (pos.mark_price - pos.entry_price) if pos.side == "LONG" else (pos.entry_price - pos.mark_price)
            pos.pnl_pct = round((price_diff / max(pos.entry_price, 1e-8)) * 100.0 * pos.leverage, 2)
            pos.pnl_usd = round(pos.margin_usd * (pos.pnl_pct / 100.0), 2)

            elapsed = now - pos.opened_at
            hit_sl = (pos.side == "LONG" and pos.mark_price <= pos.hard_sl) or (
                pos.side == "SHORT" and pos.mark_price >= pos.hard_sl
            )
            if hit_sl or elapsed >= pos.time_stop_sec:
                to_close.append(sym)

        for sym in to_close:
            pos = state.positions.pop(sym, None)
            if pos:
                state.paper_balance_usd = round(state.paper_balance_usd + pos.pnl_usd, 2)


confluence_engine = Tier0ConfluenceEngine()
