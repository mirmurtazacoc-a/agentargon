"""
Binance Spot aggTrade Stream for Spot-vs-Perp CVD Divergence:
wss://stream.binance.com:9443/stream?streams={sym}@aggTrade
Separates real spot-led rallies from fragile perp-only leverage pumps that snap back.
Automatically maps 1000PEPEUSDT (Futures) <-> PEPEUSDT (Spot) with 1000x price scaling.
"""

import asyncio
import random
import time
from typing import Any, Dict, List

from backend.core.bus import bus
from backend.core.state import TradeTick, json_loads, state


class BinanceSpotFeed:
    SPOT_WS = "wss://stream.binance.com:9443/stream"

    # Spot symbol -> (State Symbol, Price Multiplier)
    SPOT_TO_STATE_MAP: Dict[str, tuple[str, float]] = {
        "PEPEUSDT": ("1000PEPEUSDT", 1000.0),
    }

    def __init__(self) -> None:
        self._running = False
        self._tasks: List[asyncio.Task[None]] = []

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._tasks.append(asyncio.create_task(self._run_spot_stream()))
        self._tasks.append(asyncio.create_task(self._run_spot_simulation()))

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()

    async def _run_spot_stream(self) -> None:
        try:
            import websockets
        except ImportError:
            return

        spot_streams: List[str] = []
        for s in state.coins.keys():
            if s == "1000PEPEUSDT":
                spot_streams.append("pepeusdt@aggTrade")
            else:
                spot_streams.append(f"{s.lower()}@aggTrade")

        url = f"{self.SPOT_WS}?streams={'/'.join(spot_streams)}"

        while self._running:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=10, close_timeout=5) as ws:
                    async for raw_msg in ws:
                        if not self._running:
                            break
                        msg = json_loads(raw_msg)
                        data = msg.get("data", {})
                        self._handle_spot_agg_trade(data)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(5.0)

    def _handle_spot_agg_trade(self, data: Dict[str, Any]) -> None:
        raw_sym = data.get("s", "")
        mult = 1.0
        if raw_sym in self.SPOT_TO_STATE_MAP:
            sym, mult = self.SPOT_TO_STATE_MAP[raw_sym]
        else:
            sym = raw_sym

        if sym not in state.coins:
            return
        coin = state.coins[sym]
        raw_price = float(data.get("p") or 0.0)
        if raw_price <= 0:
            return
        price = raw_price * mult
        qty = float(data.get("q") or 0.0) / mult
        is_buyer_maker = bool(data.get("m", False))
        usd_vol = price * qty
        now = time.time()

        coin.spot_price = price
        tick = TradeTick(ts=now, price=price, qty=qty, usd_vol=usd_vol, is_buyer_maker=is_buyer_maker)
        coin.spot_trades_60s.append(tick)

        signed_delta = -usd_vol if is_buyer_maker else usd_vol
        coin.spot_cvd_60s += signed_delta
        coin.spot_cvd_15m += signed_delta

        bus.publish_nowait("spot_tick", {"symbol": sym, "price": price, "signed_delta": signed_delta, "ts": now})

    async def _run_spot_simulation(self) -> None:
        """Simulate realistic Spot vs Perp basis and Spot CVD flow ONLY when offline/sandboxed."""
        while self._running:
            await asyncio.sleep(0.25)
            if state.live_feeds_connected:
                continue

            now = time.time()
            for sym, coin in state.coins.items():
                decimals = 6 if coin.perp_price < 1 else 2
                basis_shift = random.gauss(0.0001, 0.0004)
                spot_p = round(coin.perp_price * (1.0 + basis_shift), decimals)
                coin.spot_price = spot_p

                usd_vol = random.uniform(6000.0, 45000.0)
                is_sell = random.random() < (0.38 if spot_p > coin.perp_price else 0.52)
                tick = TradeTick(
                    ts=now,
                    price=spot_p,
                    qty=usd_vol / max(spot_p, 1e-6),
                    usd_vol=usd_vol,
                    is_buyer_maker=is_sell,
                )
                coin.spot_trades_60s.append(tick)


spot_feed = BinanceSpotFeed()
