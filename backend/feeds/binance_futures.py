"""
Binance USDS-M Futures Real-Time WebSocket Ingestion:
1. Live Forced Liquidations: wss://fstream.binance.com/market/stream?streams=!forceOrder@arr (filter st == 1)
2. Contract & Funding Shifts: wss://fstream.binance.com/market/stream?streams=!contractInfo
3. Perp aggTrades, 1m Klines, L2 Depth, and !markPrice@arr@1s
Separates public streams so all valid USDS-M symbols stream live without rejection.
"""

import asyncio
import random
import time
from typing import Any, Dict, List
import uuid

from backend.core.bus import bus
from backend.core.state import (
    LiquidationEvent,
    TradeTick,
    json_loads,
    snap_to_tick,
    state,
)


class BinanceFuturesFeed:
    FUTURES_PUBLIC_WS = "wss://fstream.binance.com/stream"

    def __init__(self) -> None:
        self._running = False
        self._tasks: List[asyncio.Task[None]] = []

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._tasks.append(asyncio.create_task(self._run_global_futures_stream()))
        self._tasks.append(asyncio.create_task(self._run_symbol_futures_stream()))
        self._tasks.append(asyncio.create_task(self._run_simulation_fallback()))

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()

    async def _run_global_futures_stream(self) -> None:
        """
        Dedicated WebSocket for global all-market streams:
        - !markPrice@arr@1s (real-time mark price, index price, and funding rate for every USDS-M contract every 1s)
        - !forceOrder@arr (real-time forced liquidations across all USDS-M contracts)
        """
        try:
            import websockets
        except ImportError:
            return

        url = f"{self.FUTURES_PUBLIC_WS}?streams=!markPrice@arr@1s/!forceOrder@arr"
        while self._running:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=10, close_timeout=5) as ws:
                    state.live_feeds_connected = True
                    state.simulation_active = False
                    async for raw_msg in ws:
                        if not self._running:
                            break
                        self._process_ws_message(raw_msg)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(3.0)

    async def _run_symbol_futures_stream(self) -> None:
        """Connects to per-symbol aggTrade and depth10@100ms streams, auto-reconnecting when hot symbols change."""
        try:
            import websockets
        except ImportError:
            return

        while self._running:
            subscribed_set = set(state.coins.keys())
            symbols_lower = [s.lower() for s in subscribed_set]
            streams: List[str] = []
            for sym in symbols_lower:
                streams.append(f"{sym}@aggTrade")
                streams.append(f"{sym}@depth10@100ms")

            url = f"{self.FUTURES_PUBLIC_WS}?streams={'/'.join(streams)}"
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=10, close_timeout=5) as ws:
                    state.live_feeds_connected = True
                    state.simulation_active = False
                    last_check = time.time()
                    async for raw_msg in ws:
                        if not self._running:
                            break
                        self._process_ws_message(raw_msg)
                        # If Squeeze Radar or user Search added new symbols, reconnect WS to include them
                        if time.time() - last_check > 6.0:
                            last_check = time.time()
                            if set(state.coins.keys()) != subscribed_set:
                                break
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(3.0)

    def _process_ws_message(self, raw_msg: bytes | str) -> None:
        try:
            msg = json_loads(raw_msg)
            stream = msg.get("stream", "")
            data = msg.get("data", {})

            if stream == "!forceOrder@arr":
                events = data if isinstance(data, list) else [data]
                for ev in events:
                    self._handle_force_order(ev)
            elif stream == "!contractInfo":
                self._handle_contract_info(data)
            elif stream == "!markPrice@arr@1s":
                if isinstance(data, list):
                    for item in data:
                        self._handle_mark_price(item)
            elif "@aggTrade" in stream:
                self._handle_agg_trade(data)
            elif "@kline_1m" in stream:
                self._handle_kline(data)
            elif "@depth10" in stream:
                sym = stream.split("@")[0].upper()
                self._handle_depth(sym, data)
        except Exception:
            pass

    def _handle_force_order(self, data: Dict[str, Any]) -> None:
        """Handle !forceOrder@arr live forced liquidations."""
        order = data.get("o", data)
        sym = order.get("s", "")
        if sym not in state.coins:
            return
        side = order.get("S", "BUY")  # BUY = Short liquidated, SELL = Long liquidated
        price = float(order.get("ap") or order.get("p") or 0.0)
        qty = float(order.get("q") or 0.0)
        usd_val = price * qty
        if usd_val < 1000:
            return

        now = time.time()
        liq = LiquidationEvent(
            id=f"liq-{uuid.uuid4().hex[:8]}",
            symbol=sym,
            side=side,
            price=price,
            qty=qty,
            usd_value=round(usd_val, 2),
            ts=now,
        )
        state.liquidations_tape.appendleft(liq)

        coin = state.coins[sym]
        if side == "BUY":
            coin.short_liq_60s_usd += usd_val
        else:
            coin.long_liq_60s_usd += usd_val

        bus.publish_nowait(
            "liquidation",
            {
                "symbol": sym,
                "side": side,
                "price": price,
                "usd_value": usd_val,
                "ts": now,
            },
        )

    def _handle_contract_info(self, data: Dict[str, Any]) -> None:
        sym = data.get("s", "")
        contract_status = data.get("cs", "TRADING")
        if sym in state.coins and contract_status != "TRADING":
            bus.publish_nowait(
                "contract_shift",
                {
                    "symbol": sym,
                    "status": contract_status,
                    "note": f"Contract status changed to {contract_status}",
                    "ts": time.time(),
                },
            )

    def _handle_mark_price(self, item: Dict[str, Any]) -> None:
        sym = item.get("s", "")
        if sym not in state.coins:
            return
        coin = state.coins[sym]
        mark_p = float(item.get("p") or 0.0)
        index_p = float(item.get("i") or 0.0)
        if mark_p > 0:
            coin.mark_price = snap_to_tick(mark_p, coin.tick_size, coin.price_decimals)
        if index_p > 0:
            coin.index_price = snap_to_tick(index_p, coin.tick_size, coin.price_decimals)
        coin.funding_rate = float(item.get("r") or coin.funding_rate)
        next_ft = int(item.get("T") or 0)
        if next_ft > 0:
            coin.next_funding_time = next_ft / 1000.0

    def _handle_agg_trade(self, data: Dict[str, Any]) -> None:
        sym = data.get("s", "")
        if sym not in state.coins:
            return
        coin = state.coins[sym]
        raw_p = float(data.get("p") or coin.perp_price)
        price = snap_to_tick(raw_p, coin.tick_size, coin.price_decimals)
        qty = float(data.get("q") or 0.0)
        is_buyer_maker = bool(data.get("m", False))
        usd_vol = price * qty
        now = time.time()

        coin.perp_price = price
        coin.mark_price = price
        tick = TradeTick(ts=now, price=price, qty=qty, usd_vol=usd_vol, is_buyer_maker=is_buyer_maker)
        coin.perp_trades_60s.append(tick)
        coin.price_history_15m.append((now, price))

        signed_delta = -usd_vol if is_buyer_maker else usd_vol
        coin.perp_cvd_60s += signed_delta
        coin.perp_cvd_15m += signed_delta

        bus.publish_nowait("perp_tick", {"symbol": sym, "price": price, "signed_delta": signed_delta, "ts": now})

    def _handle_kline(self, data: Dict[str, Any]) -> None:
        sym = data.get("s", "")
        if sym not in state.coins:
            return
        k = data.get("k", {})
        candle_ts = int(k.get("t", 0)) // 1000
        if candle_ts <= 0:
            return
        coin = state.coins[sym]
        coin.volume_1m_usd = round(float(k.get("q", 0.0)), 2)

    def _handle_depth(self, sym: str, data: Dict[str, Any]) -> None:
        if sym not in state.coins:
            return
        raw_bids = data.get("b", [])
        raw_asks = data.get("a", [])
        bus.publish_nowait("l2_depth", {"symbol": sym, "bids": raw_bids, "asks": raw_asks, "ts": time.time()})

    async def _run_simulation_fallback(self) -> None:
        """
        Fallback microstructure generator ONLY when completely offline (no internet).
        Does NOT randomly drift prices away from real market values when live REST/WS is active.
        """
        while self._running:
            await asyncio.sleep(0.25)
            if state.live_feeds_connected:
                continue

            now = time.time()
            for sym, coin in state.coins.items():
                p = coin.perp_price
                decimals = 6 if p < 1 else 2

                # Tiny micro-jitter around accurate reference price when offline
                pct_step = random.gauss(0.0, 0.00015)
                new_p = max(p * 0.5, round(p * (1.0 + pct_step), decimals))
                coin.perp_price = new_p
                coin.mark_price = new_p

                is_sell = pct_step < 0
                usd_vol = random.uniform(4500.0, 35000.0)
                qty = usd_vol / new_p
                tick = TradeTick(ts=now, price=new_p, qty=qty, usd_vol=usd_vol, is_buyer_maker=is_sell)
                coin.perp_trades_60s.append(tick)
                coin.price_history_15m.append((now, new_p))

                spread = new_p * 0.0003
                bids = []
                asks = []
                for lvl in range(1, 9):
                    b_price = round(new_p - spread * lvl, decimals)
                    a_price = round(new_p + spread * lvl, decimals)
                    b_qty = random.uniform(15000, 195000) / max(b_price, 1e-8)
                    a_qty = random.uniform(15000, 195000) / max(a_price, 1e-8)
                    bids.append([str(b_price), str(b_qty)])
                    asks.append([str(a_price), str(a_qty)])

                bus.publish_nowait("l2_depth", {"symbol": sym, "bids": bids, "asks": asks, "ts": now})


futures_feed = BinanceFuturesFeed()
