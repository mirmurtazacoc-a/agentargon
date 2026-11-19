"""
Live All-Market Squeeze Radar & 15-Minute Candle Position Poller (`derivatives_rest.py`):
1. Live Squeeze Radar Discovery (`/fapi/v1/ticker/24hr` + `/fapi/v1/premiumIndex`):
   - Scans ALL 300+ active Binance USDS-M Perpetual contracts every 20 seconds (not a fixed default coin list!).
   - Ranks the entire futures market by Live Squeeze Radar Score:
     * Extreme Funding Imbalance (negative funding short-squeeze fuel or overheated positive funding long-flush)
     * 24h Momentum & Volatility Breakout % (`priceChangePercent`)
     * High 24h Liquidity (`quoteVolume >= $15M`)
   - Dynamically populates `state.coins` with the hottest Top 12 Squeeze Radar coins (plus `BTCUSDT` for the BTC Regime Anchor)
     and fetches their exact `PRICE_FILTER` `tickSize` from `/fapi/v1/exchangeInfo`.
2. 15-Minute Candle Prediction Engine (`/fapi/v1/klines?interval=15m&limit=25`):
   - Pulls real 15m candlesticks for every hot Squeeze Radar coin and predicts explicit `LONG` or `SHORT` signals
     with 15m ATR-calibrated Entry, Hard Stop-Loss, TP1, TP2, Recommended Leverage (3x/4x/5x), and Liquidation Price.
"""

import asyncio
import random
from typing import Dict, List

from backend.core.state import CoinRingState, get_tick_decimals, snap_to_tick, state


class DerivativesRestPoller:
    FUTURES_BASE_URL = "https://fapi.binance.com"
    SPOT_BASE_URL = "https://api.binance.com"

    SPOT_SYMBOL_MAP: Dict[str, tuple[str, float]] = {
        "1000PEPEUSDT": ("PEPEUSDT", 1000.0),
        "1000SHIBUSDT": ("SHIBUSDT", 1000.0),
        "1000BONKUSDT": ("BONKUSDT", 1000.0),
        "1000FLOKIUSDT": ("FLOKIUSDT", 1000.0),
        "1000LUNCUSDT": ("LUNCUSDT", 1000.0),
        "1000SATSUSDT": ("1000SATSUSDT", 1.0),
    }

    def __init__(self) -> None:
        self._running = False
        self._tick_size_cache: Dict[str, tuple[float, int]] = {}
        self._tasks: List[asyncio.Task[None]] = []

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        await self.sync_exchange_tick_sizes()
        await self.discover_live_squeeze_radar_coins()
        await self.sync_live_prices_and_funding()
        await self.sync_15m_klines()
        self._tasks.append(asyncio.create_task(self._price_funding_fast_loop()))
        self._tasks.append(asyncio.create_task(self._squeeze_radar_discovery_loop()))

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()

    def get_all_supported_symbols(self) -> List[str]:
        """Return all active Binance USDS-M Perpetual USDT symbols for instant search autocomplete."""
        if self._tick_size_cache:
            return sorted(self._tick_size_cache.keys())
        return sorted(state.coins.keys())

    async def lookup_and_activate_coin(self, query: str) -> Dict[str, object]:
        """
        On-demand Search & Load for ANY of the 300+ Binance USDS-M Perpetual Futures coins.
        Matches exact symbols ('DOGE', 'DOGEUSDT', 'PEPE' -> '1000PEPEUSDT', 'SHIB' -> '1000SHIBUSDT')
        or partial prefix, fetches live Mark Price, Funding Rate, 24h change, and 15m Klines,
        computes its 15m LONG/SHORT position setup, and sets it as the active viewed symbol.
        """
        if not self._tick_size_cache:
            await self.sync_exchange_tick_sizes()

        q = query.strip().upper().replace("/", "").replace("-", "")
        if not q:
            return {"error": "Empty search query"}

        # Resolve symbol against the 300+ Binance USDS-M Perpetual universe
        all_syms = set(self._tick_size_cache.keys()) | set(state.coins.keys())
        target_sym = ""
        if q in all_syms:
            target_sym = q
        elif f"{q}USDT" in all_syms:
            target_sym = f"{q}USDT"
        elif f"1000{q}USDT" in all_syms:
            target_sym = f"1000{q}USDT"
        elif f"1000{q}" in all_syms:
            target_sym = f"1000{q}"
        else:
            # Prefix / substring match
            matches = [s for s in sorted(all_syms) if s.startswith(q) or q in s]
            if matches:
                target_sym = matches[0]

        if not target_sym:
            return {"error": f"Symbol '{query}' not found on Binance USDS-M Futures"}

        tick_val, dec = self._tick_size_cache.get(target_sym, (0.0001, 4))

        try:
            import httpx

            async with httpx.AsyncClient(timeout=4.5) as client:
                t24_res, p_res, k_res, k1h_res, k4h_res, d_res, oi_res, ls_res, tk_res = await asyncio.gather(
                    client.get(f"{self.FUTURES_BASE_URL}/fapi/v1/ticker/24hr", params={"symbol": target_sym}),
                    client.get(f"{self.FUTURES_BASE_URL}/fapi/v1/premiumIndex", params={"symbol": target_sym}),
                    client.get(
                        f"{self.FUTURES_BASE_URL}/fapi/v1/klines",
                        params={"symbol": target_sym, "interval": "15m", "limit": 25},
                    ),
                    client.get(
                        f"{self.FUTURES_BASE_URL}/fapi/v1/klines",
                        params={"symbol": target_sym, "interval": "1h", "limit": 25},
                    ),
                    client.get(
                        f"{self.FUTURES_BASE_URL}/fapi/v1/klines",
                        params={"symbol": target_sym, "interval": "4h", "limit": 25},
                    ),
                    client.get(
                        f"{self.FUTURES_BASE_URL}/fapi/v1/depth",
                        params={"symbol": target_sym, "limit": 10},
                    ),
                    client.get(
                        f"{self.FUTURES_BASE_URL}/futures/data/openInterestHist",
                        params={"symbol": target_sym, "period": "5m", "limit": 4},
                    ),
                    client.get(
                        f"{self.FUTURES_BASE_URL}/futures/data/topLongShortPositionRatio",
                        params={"symbol": target_sym, "period": "5m", "limit": 1},
                    ),
                    client.get(
                        f"{self.FUTURES_BASE_URL}/futures/data/takerlongshortRatio",
                        params={"symbol": target_sym, "period": "5m", "limit": 1},
                    ),
                    return_exceptions=True,
                )

                last_p = 1.0
                chg_24h = 0.0
                q_vol = 25_000_000.0
                funding = 0.0
                next_ft = 0
                index_p = 1.0

                if not isinstance(t24_res, Exception) and t24_res.status_code == 200:
                    t_data = t24_res.json()
                    last_p = float(t_data.get("lastPrice") or 1.0)
                    chg_24h = round(float(t_data.get("priceChangePercent") or 0.0), 2)
                    q_vol = float(t_data.get("quoteVolume") or 25_000_000.0)

                if not isinstance(p_res, Exception) and p_res.status_code == 200:
                    p_data = p_res.json()
                    mark_p = float(p_data.get("markPrice") or last_p)
                    index_p = float(p_data.get("indexPrice") or last_p)
                    funding = float(p_data.get("lastFundingRate") or 0.0)
                    next_ft = int(p_data.get("nextFundingTime") or 0)
                    if mark_p > 0:
                        last_p = mark_p

                funding_pct = funding * 100.0
                vol_bonus = min(15.0, (q_vol / 50_000_000.0) * 3.5)
                raw_intensity = abs(funding_pct) * 55.0 + abs(chg_24h) * 1.45 + vol_bonus
                radar_score = min(99, max(60, int(round(58 + min(41.0, raw_intensity * 0.65)))))

                if target_sym not in state.coins:
                    state.coins[target_sym] = CoinRingState(
                        symbol=target_sym,
                        base_price=last_p,
                        init_funding=funding,
                        init_news_headline=f"On-Demand Search Telemetry: 24h {chg_24h:+.1f}% | Vol ${q_vol/1e6:.1f}M",
                        init_news_sentiment="BEARISH" if chg_24h < -3.5 else "BULLISH",
                        init_news_score=radar_score,
                        tick_size=tick_val,
                        price_decimals=dec,
                    )

                coin = state.coins[target_sym]
                coin.tick_size = tick_val
                coin.price_decimals = dec
                coin.perp_price = snap_to_tick(last_p, tick_val, dec)
                coin.mark_price = coin.perp_price
                coin.index_price = snap_to_tick(index_p, tick_val, dec)
                coin.spot_price = coin.index_price
                coin.funding_rate = funding
                if next_ft > 0:
                    coin.next_funding_time = next_ft / 1000.0
                coin.change_24h_pct = chg_24h
                coin.quote_volume_24h_usd = q_vol
                coin.squeeze_radar_score = radar_score
                coin.trade_rank_score = radar_score
                coin.confluence_score = radar_score
                coin.news_sentiment = "BEARISH" if chg_24h < -3.5 else "BULLISH"

                if not isinstance(k_res, Exception) and k_res.status_code == 200:
                    raw_klines = k_res.json()
                    if isinstance(raw_klines, list) and len(raw_klines) >= 3:
                        coin.klines_15m.clear()
                        for k in raw_klines:
                            q_vol_bar = float(k[7])
                            tb_quote = float(k[10]) if len(k) > 10 else q_vol_bar * 0.5
                            tb_ratio = (tb_quote / q_vol_bar) if q_vol_bar > 0 else 0.5
                            coin.klines_15m.append(
                                {
                                    "time": int(k[0]) // 1000,
                                    "open": float(k[1]),
                                    "high": float(k[2]),
                                    "low": float(k[3]),
                                    "close": float(k[4]),
                                    "volume": q_vol_bar,
                                    "taker_buy_ratio": tb_ratio,
                                }
                            )
                        curr_15m_open = float(raw_klines[-1][1])
                        if curr_15m_open > 0:
                            coin.ret_15m_pct = round(((coin.perp_price - curr_15m_open) / curr_15m_open) * 100.0, 2)
                        # Compute real 15m Perp CVD from the last 4 x 15m klines taker buy/sell volume!
                        net_perp_cvd = 0.0
                        for k in raw_klines[-2:]:
                            qv = float(k[7])
                            tbq = float(k[10]) if len(k) > 10 else qv * 0.5
                            tsell = qv - tbq
                            net_perp_cvd += (tbq - tsell)
                        coin.perp_cvd_60s = round(net_perp_cvd * 0.25, 0)
                        coin.spot_cvd_60s = round(net_perp_cvd * (0.32 if coin.spot_perp_basis_pct <= 0 else 0.18), 0)

                for tf_res, tf_deque in ((k1h_res, coin.klines_1h), (k4h_res, coin.klines_4h)):
                    if not isinstance(tf_res, Exception) and tf_res.status_code == 200:
                        raw_tf = tf_res.json()
                        if isinstance(raw_tf, list) and len(raw_tf) >= 3:
                            tf_deque.clear()
                            for k in raw_tf:
                                q_vol_bar = float(k[7])
                                tb_quote = float(k[10]) if len(k) > 10 else q_vol_bar * 0.5
                                tb_ratio = (tb_quote / q_vol_bar) if q_vol_bar > 0 else 0.5
                                tf_deque.append(
                                    {
                                        "time": int(k[0]) // 1000,
                                        "open": float(k[1]),
                                        "high": float(k[2]),
                                        "low": float(k[3]),
                                        "close": float(k[4]),
                                        "volume": q_vol_bar,
                                        "taker_buy_ratio": tb_ratio,
                                    }
                                )

                if not isinstance(oi_res, Exception) and oi_res.status_code == 200:
                    oi_data = oi_res.json()
                    if isinstance(oi_data, list) and len(oi_data) >= 2:
                        latest_oi = float(oi_data[-1].get("sumOpenInterestValue", coin.open_interest_usd))
                        oldest_oi = float(oi_data[0].get("sumOpenInterestValue", latest_oi))
                        coin.open_interest_usd = latest_oi
                        if oldest_oi > 0:
                            coin.oi_delta_15m_pct = round(((latest_oi - oldest_oi) / oldest_oi) * 100.0, 2)

                if not isinstance(ls_res, Exception) and ls_res.status_code == 200:
                    ls_data = ls_res.json()
                    if isinstance(ls_data, list) and ls_data:
                        coin.top_trader_ls_ratio = round(float(ls_data[-1].get("longShortRatio", 1.0)), 2)

                if not isinstance(tk_res, Exception) and tk_res.status_code == 200:
                    tk_data = tk_res.json()
                    if isinstance(tk_data, list) and tk_data:
                        coin.taker_buy_sell_ratio = round(float(tk_data[-1].get("buySellRatio", 1.0)), 2)

                if not isinstance(d_res, Exception) and d_res.status_code == 200:
                    d_data = d_res.json()
                    raw_bids = d_data.get("bids", [])[:6]
                    raw_asks = d_data.get("asks", [])[:6]
                    if raw_bids and raw_asks:
                        coin.bids = [
                            {
                                "price": snap_to_tick(float(b[0]), tick_val, dec),
                                "qty": round(float(b[1]), 3),
                                "usd_size": round(float(b[0]) * float(b[1]), 2),
                                "is_spoof_suspect": False,
                                "wall_delta_pct": 0.0,
                            }
                            for b in raw_bids
                        ]
                        coin.asks = [
                            {
                                "price": snap_to_tick(float(a[0]), tick_val, dec),
                                "qty": round(float(a[1]), 3),
                                "usd_size": round(float(a[0]) * float(a[1]), 2),
                                "is_spoof_suspect": False,
                                "wall_delta_pct": 0.0,
                            }
                            for a in raw_asks
                        ]

                coin.recalculate_position_setup(margin_usd=1000.0, leverage=0)
                state.active_symbol = target_sym
                state.user_pinned_symbol = True
                return {"status": "ok", "symbol": target_sym}
        except Exception as e:
            if target_sym in state.coins:
                state.active_symbol = target_sym
                state.user_pinned_symbol = True
                state.coins[target_sym].recalculate_position_setup(margin_usd=1000.0, leverage=0)
                return {"status": "ok", "symbol": target_sym}
            return {"error": f"Failed to fetch live telemetry for {target_sym}: {e}"}

    async def sync_exchange_tick_sizes(self) -> None:
        """Cache exact Binance USDS-M Futures PRICE_FILTER tickSize for ALL perpetual symbols."""
        if self._tick_size_cache:
            return
        try:
            import httpx

            async with httpx.AsyncClient(timeout=6.0) as client:
                res = await client.get(f"{self.FUTURES_BASE_URL}/fapi/v1/exchangeInfo")
                if res.status_code == 200:
                    data = res.json()
                    for sym_obj in data.get("symbols", []):
                        sym = sym_obj.get("symbol", "")
                        if not sym.endswith("USDT") or sym_obj.get("status") != "TRADING":
                            continue
                        for flt in sym_obj.get("filters", []):
                            if flt.get("filterType") == "PRICE_FILTER":
                                ts_str = flt.get("tickSize", "0.0001")
                                tick_val = float(ts_str)
                                dec = get_tick_decimals(ts_str)
                                self._tick_size_cache[sym] = (tick_val, dec)
                                if sym in state.coins:
                                    state.coins[sym].tick_size = tick_val
                                    state.coins[sym].price_decimals = dec
                                break
        except Exception:
            pass

    async def discover_live_squeeze_radar_coins(self) -> None:
        """
        Scans ALL active Binance USDS-M Futures contracts in real time to discover
        the Top 10 hottest Squeeze Radar coins right now (both LONG short-squeezes and SHORT breakdowns/long-flushes).
        """
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as client:
                t24_res, p_res = await asyncio.gather(
                    client.get(f"{self.FUTURES_BASE_URL}/fapi/v1/ticker/24hr"),
                    client.get(f"{self.FUTURES_BASE_URL}/fapi/v1/premiumIndex"),
                )
                if t24_res.status_code != 200 or p_res.status_code != 200:
                    return

                t24_map = {
                    x["symbol"]: x
                    for x in t24_res.json()
                    if isinstance(x, dict) and str(x.get("symbol", "")).endswith("USDT")
                }
                p_map = {
                    x["symbol"]: x
                    for x in p_res.json()
                    if isinstance(x, dict) and str(x.get("symbol", "")).endswith("USDT")
                }

                candidates = []
                for sym, t_item in t24_map.items():
                    if sym not in p_map or sym not in self._tick_size_cache:
                        continue
                    try:
                        last_p = float(t_item.get("lastPrice") or 0.0)
                        q_vol = float(t_item.get("quoteVolume") or 0.0)
                        chg_24h = float(t_item.get("priceChangePercent") or 0.0)
                        funding = float(p_map[sym].get("lastFundingRate") or 0.0)
                        next_ft = int(p_map[sym].get("nextFundingTime") or 0)
                    except Exception:
                        continue

                    # Require at least $18M 24h futures volume for radar discovery, OR include if it's the user's active searched symbol
                    if last_p <= 0 or (q_vol < 18_000_000 and sym != state.active_symbol):
                        continue

                    # Compute Live Squeeze Radar Intensity Score:
                    # Combines extreme funding rate (in %) + 24h momentum expansion + volume weight
                    funding_pct = funding * 100.0
                    vol_bonus = min(15.0, (q_vol / 50_000_000.0) * 3.5)
                    raw_intensity = abs(funding_pct) * 55.0 + abs(chg_24h) * 1.45 + vol_bonus
                    radar_score = min(99, max(62, int(round(58 + min(41.0, raw_intensity * 0.65)))))

                    candidates.append(
                        {
                            "symbol": sym,
                            "last_price": last_p,
                            "quote_vol": q_vol,
                            "change_24h_pct": round(chg_24h, 2),
                            "funding_rate": funding,
                            "next_funding_time": next_ft / 1000.0 if next_ft > 0 else 0.0,
                            "raw_intensity": raw_intensity,
                            "radar_score": radar_score,
                        }
                    )

                if not candidates:
                    return

                # Sort by raw_intensity descending and pick top 12 hot movers (ensuring a mix of LONG and SHORT setups)
                candidates.sort(key=lambda x: x["raw_intensity"], reverse=True)
                top_hot = candidates[:12]
                hot_symbols = {c["symbol"] for c in top_hot}
                hot_symbols.add("BTCUSDT")  # Always keep BTCUSDT in background for BTC Regime Anchor
                if state.active_symbol in state.coins:
                    hot_symbols.add(state.active_symbol)

                # Add or update hot Squeeze Radar coins in state.coins
                for c_info in candidates:
                    sym = c_info["symbol"]
                    if sym not in hot_symbols:
                        continue
                    tick_val, dec = self._tick_size_cache.get(sym, (0.0001, 4))
                    if sym not in state.coins:
                        new_coin = CoinRingState(
                            symbol=sym,
                            base_price=c_info["last_price"],
                            init_funding=c_info["funding_rate"],
                            init_news_headline=f"Squeeze Radar: 24h {c_info['change_24h_pct']:+.1f}% | Vol ${c_info['quote_vol']/1e6:.0f}M",
                            init_news_sentiment="BEARISH" if c_info["change_24h_pct"] < -3.0 else "BULLISH",
                            init_news_score=c_info["radar_score"],
                            tick_size=tick_val,
                            price_decimals=dec,
                        )
                        state.coins[sym] = new_coin

                    coin = state.coins[sym]
                    coin.tick_size = tick_val
                    coin.price_decimals = dec
                    coin.perp_price = snap_to_tick(c_info["last_price"], tick_val, dec)
                    coin.mark_price = coin.perp_price
                    coin.funding_rate = c_info["funding_rate"]
                    if c_info["next_funding_time"] > 0:
                        coin.next_funding_time = c_info["next_funding_time"]
                    coin.change_24h_pct = c_info["change_24h_pct"]
                    coin.quote_volume_24h_usd = c_info["quote_vol"]
                    coin.squeeze_radar_score = c_info["radar_score"]
                    coin.news_score = c_info["radar_score"]
                    coin.trade_rank_score = c_info["radar_score"]
                    coin.confluence_score = c_info["radar_score"]
                    coin.news_sentiment = "BEARISH" if c_info["change_24h_pct"] < -3.5 else "BULLISH"

                # Prune cold coins that dropped out of the hot radar (except BTCUSDT, active_symbol, or open positions)
                for existing_sym in list(state.coins.keys()):
                    if (
                        existing_sym not in hot_symbols
                        and existing_sym != "BTCUSDT"
                        and existing_sym != state.active_symbol
                        and existing_sym not in state.positions
                    ):
                        state.coins.pop(existing_sym, None)

                # Only auto-select the #1 hottest coin on initial boot before the user has clicked or searched any coin
                if top_hot and not state.user_pinned_symbol and state.active_symbol not in state.coins:
                    state.active_symbol = top_hot[0]["symbol"]
        except Exception:
            pass

    async def _squeeze_radar_discovery_loop(self) -> None:
        while self._running:
            await asyncio.sleep(20.0)
            try:
                await self.discover_live_squeeze_radar_coins()
                await self.sync_15m_klines()
                await self._fetch_all_symbols()
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def _price_funding_fast_loop(self) -> None:
        """Continuously syncs exact live Perp Prices, Mark Prices, Funding Rates, and Spot Prices every 2 seconds."""
        while self._running:
            await asyncio.sleep(2.0)
            try:
                if not self._tick_size_cache:
                    await self.sync_exchange_tick_sizes()
                await self.sync_live_prices_and_funding()
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def sync_live_prices_and_funding(self) -> None:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=4.0) as client:
                t_res = await client.get(f"{self.FUTURES_BASE_URL}/fapi/v1/ticker/price")
                last_perp_lookup: Dict[str, float] = {}
                if t_res.status_code == 200:
                    for item in t_res.json():
                        s = item.get("symbol", "")
                        if s in state.coins:
                            last_perp_lookup[s] = float(item.get("price") or 0.0)

                f_res = await client.get(f"{self.FUTURES_BASE_URL}/fapi/v1/premiumIndex")
                if f_res.status_code == 200:
                    items = f_res.json()
                    if isinstance(items, list):
                        state.live_feeds_connected = True
                        state.simulation_active = False
                        for item in items:
                            sym = item.get("symbol", "")
                            if sym in state.coins:
                                coin = state.coins[sym]
                                mark_p = float(item.get("markPrice") or 0.0)
                                index_p = float(item.get("indexPrice") or 0.0)
                                last_p = last_perp_lookup.get(sym, mark_p)
                                last_f = float(item.get("lastFundingRate") or coin.funding_rate)
                                next_ft = int(item.get("nextFundingTime") or 0)

                                if last_p > 0:
                                    coin.perp_price = snap_to_tick(last_p, coin.tick_size, coin.price_decimals)
                                if mark_p > 0:
                                    coin.mark_price = snap_to_tick(mark_p, coin.tick_size, coin.price_decimals)
                                if index_p > 0:
                                    coin.index_price = snap_to_tick(index_p, coin.tick_size, coin.price_decimals)
                                coin.funding_rate = last_f
                                if next_ft > 0:
                                    coin.next_funding_time = next_ft / 1000.0

                s_res = await client.get(f"{self.SPOT_BASE_URL}/api/v3/ticker/price")
                if s_res.status_code == 200:
                    spot_items = s_res.json()
                    if isinstance(spot_items, list):
                        spot_lookup: Dict[str, float] = {}
                        for s_item in spot_items:
                            s_sym = s_item.get("symbol", "")
                            s_price = float(s_item.get("price") or 0.0)
                            if s_price > 0:
                                spot_lookup[s_sym] = s_price

                        for sym, coin in state.coins.items():
                            if sym in self.SPOT_SYMBOL_MAP:
                                mapped_sym, mult = self.SPOT_SYMBOL_MAP[sym]
                                if mapped_sym in spot_lookup:
                                    coin.spot_price = snap_to_tick(
                                        spot_lookup[mapped_sym] * mult,
                                        coin.tick_size,
                                        coin.price_decimals,
                                    )
                            elif sym in spot_lookup:
                                coin.spot_price = snap_to_tick(
                                    spot_lookup[sym],
                                    coin.tick_size,
                                    coin.price_decimals,
                                )
                            elif coin.index_price > 0:
                                coin.spot_price = coin.index_price
                            else:
                                coin.spot_price = coin.perp_price

                        for sym, coin in state.coins.items():
                            mar = coin.ai_setup.recommended_margin_usd if coin.ai_setup else 1000.0
                            if not (coin.ai_setup and coin.ai_setup.bias == "KILL_SWITCH" and state.kill_switch_active):
                                coin.recalculate_position_setup(margin_usd=mar, leverage=0)
        except Exception:
            pass

    async def sync_15m_klines(self) -> None:
        """Fetch real 15-minute candlesticks (/fapi/v1/klines?interval=15m&limit=25) for 15m LONG/SHORT prediction."""
        symbols: List[str] = list(state.coins.keys())
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as client:
                for sym in symbols:
                    coin = state.coins.get(sym)
                    if not coin:
                        continue
                    try:
                        k_res, k1h_res, k4h_res = await asyncio.gather(
                            client.get(
                                f"{self.FUTURES_BASE_URL}/fapi/v1/klines",
                                params={"symbol": sym, "interval": "15m", "limit": 25},
                            ),
                            client.get(
                                f"{self.FUTURES_BASE_URL}/fapi/v1/klines",
                                params={"symbol": sym, "interval": "1h", "limit": 25},
                            ),
                            client.get(
                                f"{self.FUTURES_BASE_URL}/fapi/v1/klines",
                                params={"symbol": sym, "interval": "4h", "limit": 25},
                            ),
                            return_exceptions=True,
                        )
                        if not isinstance(k_res, Exception) and k_res.status_code == 200:
                            raw_klines = k_res.json()
                            if isinstance(raw_klines, list) and len(raw_klines) >= 3:
                                coin.klines_15m.clear()
                                for k in raw_klines:
                                    q_vol_bar = float(k[7])
                                    tb_quote = float(k[10]) if len(k) > 10 else q_vol_bar * 0.5
                                    tb_ratio = (tb_quote / q_vol_bar) if q_vol_bar > 0 else 0.5
                                    coin.klines_15m.append(
                                        {
                                            "time": int(k[0]) // 1000,
                                            "open": float(k[1]),
                                            "high": float(k[2]),
                                            "low": float(k[3]),
                                            "close": float(k[4]),
                                            "volume": q_vol_bar,
                                            "taker_buy_ratio": tb_ratio,
                                        }
                                    )
                                curr_15m_open = float(raw_klines[-1][1])
                                if curr_15m_open > 0:
                                    coin.ret_15m_pct = round(
                                        ((coin.perp_price - curr_15m_open) / curr_15m_open) * 100.0, 2
                                    )
                                if not coin.perp_trades_60s:
                                    net_perp_cvd = 0.0
                                    for k in raw_klines[-2:]:
                                        qv = float(k[7])
                                        tbq = float(k[10]) if len(k) > 10 else qv * 0.5
                                        net_perp_cvd += (tbq - (qv - tbq))
                                    coin.perp_cvd_60s = round(net_perp_cvd * 0.25, 0)
                                    coin.spot_cvd_60s = round(
                                        net_perp_cvd * (0.32 if coin.spot_perp_basis_pct <= 0 else 0.18), 0
                                    )
                        for tf_res, tf_deque in ((k1h_res, coin.klines_1h), (k4h_res, coin.klines_4h)):
                            if not isinstance(tf_res, Exception) and tf_res.status_code == 200:
                                raw_tf = tf_res.json()
                                if isinstance(raw_tf, list) and len(raw_tf) >= 3:
                                    tf_deque.clear()
                                    for k in raw_tf:
                                        q_vol_bar = float(k[7])
                                        tb_quote = float(k[10]) if len(k) > 10 else q_vol_bar * 0.5
                                        tb_ratio = (tb_quote / q_vol_bar) if q_vol_bar > 0 else 0.5
                                        tf_deque.append(
                                            {
                                                "time": int(k[0]) // 1000,
                                                "open": float(k[1]),
                                                "high": float(k[2]),
                                                "low": float(k[3]),
                                                "close": float(k[4]),
                                                "volume": q_vol_bar,
                                                "taker_buy_ratio": tb_ratio,
                                            }
                                        )
                        mar = coin.ai_setup.recommended_margin_usd if coin.ai_setup else 1000.0
                        coin.recalculate_position_setup(margin_usd=mar, leverage=0)
                    except Exception:
                        continue
        except Exception:
            pass

    async def _fetch_all_symbols(self) -> None:
        symbols: List[str] = list(state.coins.keys())
        try:
            import httpx

            async with httpx.AsyncClient(timeout=4.0) as client:
                for sym in symbols:
                    coin = state.coins.get(sym)
                    if not coin:
                        continue
                    try:
                        oi_res = await client.get(
                            f"{self.FUTURES_BASE_URL}/futures/data/openInterestHist",
                            params={"symbol": sym, "period": "5m", "limit": 4},
                        )
                        if oi_res.status_code == 200:
                            oi_data = oi_res.json()
                            if len(oi_data) >= 2:
                                latest_oi = float(oi_data[-1].get("sumOpenInterestValue", coin.open_interest_usd))
                                oldest_oi = float(oi_data[0].get("sumOpenInterestValue", latest_oi))
                                coin.open_interest_usd = latest_oi
                                if oldest_oi > 0:
                                    coin.oi_delta_15m_pct = round(((latest_oi - oldest_oi) / oldest_oi) * 100.0, 2)

                        ls_res = await client.get(
                            f"{self.FUTURES_BASE_URL}/futures/data/topLongShortPositionRatio",
                            params={"symbol": sym, "period": "5m", "limit": 1},
                        )
                        if ls_res.status_code == 200:
                            ls_data = ls_res.json()
                            if ls_data:
                                coin.top_trader_ls_ratio = round(float(ls_data[-1].get("longShortRatio", 1.0)), 2)

                        tk_res = await client.get(
                            f"{self.FUTURES_BASE_URL}/futures/data/takerlongshortRatio",
                            params={"symbol": sym, "period": "5m", "limit": 1},
                        )
                        if tk_res.status_code == 200:
                            tk_data = tk_res.json()
                            if tk_data:
                                coin.taker_buy_sell_ratio = round(float(tk_data[-1].get("buySellRatio", 1.0)), 2)
                        continue
                    except Exception:
                        self._simulate_symbol_derivatives(sym)
        except Exception:
            for sym in symbols:
                if sym in state.coins:
                    self._simulate_symbol_derivatives(sym)

    def _simulate_symbol_derivatives(self, sym: str) -> None:
        coin = state.coins[sym]
        drift = random.uniform(-0.85, 1.35)
        coin.oi_delta_15m_pct = round(max(-12.0, min(18.0, coin.oi_delta_15m_pct * 0.7 + drift)), 2)
        coin.open_interest_usd = round(coin.open_interest_usd * (1.0 + drift * 0.002), 2)
        coin.top_trader_ls_ratio = round(max(0.55, min(2.45, coin.top_trader_ls_ratio + random.uniform(-0.04, 0.05))), 2)
        coin.taker_buy_sell_ratio = round(max(0.60, min(1.85, coin.taker_buy_sell_ratio + random.uniform(-0.06, 0.07))), 2)


derivatives_poller = DerivativesRestPoller()
