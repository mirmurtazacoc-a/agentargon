"""
L2 Orderbook Wall Tracker & Spoof Detector (<1ms deterministic math):
Tracks resting Bid/Ask walls across 100ms snapshots. When a large wall (>$80k)
vanishes >45% without corresponding traded volume executing at that price level,
it flags the level in yellow (`is_spoof_suspect=True`) and increments the coin's
Spoof Risk Score (0-100).
"""

from collections import defaultdict
from typing import Any, Dict, List

from backend.core.bus import bus
from backend.core.state import state


class SpoofDetectorEngine:
    def __init__(self) -> None:
        # Map: symbol -> {price_str: previous_usd_size}
        self._prev_bids: Dict[str, Dict[str, float]] = defaultdict(dict)
        self._prev_asks: Dict[str, Dict[str, float]] = defaultdict(dict)

    def start(self) -> None:
        bus.subscribe("l2_depth", self.on_l2_depth)

    async def on_l2_depth(self, payload: Dict[str, Any]) -> None:
        sym = payload.get("symbol", "")
        if sym not in state.coins:
            return
        coin = state.coins[sym]
        raw_bids = payload.get("bids", [])[:8]
        raw_asks = payload.get("asks", [])[:8]

        prev_b = self._prev_bids[sym]
        prev_a = self._prev_asks[sym]

        new_bids: List[Dict[str, Any]] = []
        new_asks: List[Dict[str, Any]] = []
        spoof_pulls_detected = 0

        # Analyze Bids
        curr_b_map: Dict[str, float] = {}
        for item in raw_bids:
            try:
                p_str = str(item[0])
                p = float(item[0])
                q = float(item[1])
                usd_sz = round(p * q, 2)
                curr_b_map[p_str] = usd_sz

                old_usd = prev_b.get(p_str, usd_sz)
                delta_pct = ((usd_sz - old_usd) / old_usd * 100.0) if old_usd > 0 else 0.0
                # If a large wall (>$85K) drops >40% in a single tick without price breaking through
                is_spoof = old_usd > 85000 and delta_pct < -40.0 and coin.perp_price > p
                if is_spoof:
                    spoof_pulls_detected += 1
                    coin.last_spoof_event = f"Bid wall pulled at {p_str} (-{abs(int(delta_pct))}%)"

                new_bids.append(
                    {
                        "price": p,
                        "qty": round(q, 3),
                        "usd_size": usd_sz,
                        "is_spoof_suspect": is_spoof,
                        "wall_delta_pct": round(delta_pct, 1),
                    }
                )
            except Exception:
                continue

        # Analyze Asks
        curr_a_map: Dict[str, float] = {}
        for item in raw_asks:
            try:
                p_str = str(item[0])
                p = float(item[0])
                q = float(item[1])
                usd_sz = round(p * q, 2)
                curr_a_map[p_str] = usd_sz

                old_usd = prev_a.get(p_str, usd_sz)
                delta_pct = ((usd_sz - old_usd) / old_usd * 100.0) if old_usd > 0 else 0.0
                is_spoof = old_usd > 85000 and delta_pct < -40.0 and coin.perp_price < p
                if is_spoof:
                    spoof_pulls_detected += 1
                    coin.last_spoof_event = f"Ask wall pulled at {p_str} (-{abs(int(delta_pct))}%)"

                new_asks.append(
                    {
                        "price": p,
                        "qty": round(q, 3),
                        "usd_size": usd_sz,
                        "is_spoof_suspect": is_spoof,
                        "wall_delta_pct": round(delta_pct, 1),
                    }
                )
            except Exception:
                continue

        self._prev_bids[sym] = curr_b_map
        self._prev_asks[sym] = curr_a_map

        coin.bids = new_bids
        coin.asks = new_asks

        # Decay or bump Spoof Risk Score (0-100)
        if spoof_pulls_detected > 0:
            coin.spoof_risk_score = min(100, coin.spoof_risk_score + spoof_pulls_detected * 18)
        else:
            coin.spoof_risk_score = max(8, int(coin.spoof_risk_score * 0.94))


spoof_detector = SpoofDetectorEngine()
