"""
FastAPI REST + 150ms Throttled Multiplexed WebSocket Broadcaster (`server.py`):
- Installs winloop (Windows) or uvloop (Linux) for sub-5ms async loop efficiency.
- Uses orjson for compact JSON serialization.
- Broadcasts aggregated terminal snapshots to React + Vite at ~5-6 FPS (180ms interval),
  preventing browser UI freezes while maintaining sub-100ms backend hot-path ingestion.
- Exposes interactive simulation & paper-trading triggers so the user can test
  Tier-1 Exchange Listings, Emergency Exploit Kill-Switches, Tier-2 Search Grounding
  anomalies, BTC Dump Block guards, and 3x-5x Isolated Margin Paper Orders.
"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
import time
from typing import Any, Dict, List, Set
import uuid

from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.core.bus import bus
from backend.core.state import (
    PaperPosition,
    install_fast_event_loop,
    json_dumps,
    state,
)
from backend.engine.confluence import confluence_engine
from backend.engine.gemini_brain import gemini_brain
from backend.engine.spoof_detector import spoof_detector
from backend.feeds.binance_futures import futures_feed
from backend.feeds.binance_spot import spot_feed
from backend.feeds.derivatives_rest import derivatives_poller
from backend.feeds.news_stream import news_stream


ACTIVE_LOOP_POLICY = install_fast_event_loop()


class OrderRequest(BaseModel):
    symbol: str
    side: str = "LONG"  # "LONG" | "SHORT"
    leverage: int = 4  # Locked 3x-5x Isolated Margin
    margin_usd: float = 1000.0


class SimulateEventRequest(BaseModel):
    scenario: str  # "UPBIT_LISTING" | "EXPLOIT_KILL_SWITCH" | "ANOMALY_SEARCH" | "BTC_DUMP_BLOCK" | "SHORT_SQUEEZE"
    symbol: str = "HUMAUSDT"


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active_connections.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.active_connections.discard(ws)

    async def broadcast_bytes(self, payload_bytes: bytes) -> None:
        if not self.active_connections:
            return
        text_payload = payload_bytes.decode("utf-8")
        stale: List[WebSocket] = []
        for ws in list(self.active_connections):
            try:
                await ws.send_text(text_payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)


ws_manager = ConnectionManager()


def build_terminal_snapshot() -> Dict[str, Any]:
    """Assemble compact multiplexed state diff for the 4-panel React terminal."""
    now = time.time()
    active_sym = state.active_symbol
    if active_sym not in state.coins:
        active_sym = "SOLUSDT"
    active_coin = state.coins[active_sym]

    # Top 10 Best Coins to Trade (background AI + funding ranked, with pre-calculated 15m position setups)
    scanner_cards = []
    for sym, c in state.coins.items():
        if c.ai_setup is None:
            c.recalculate_position_setup()
        setup = c.ai_setup
        scanner_cards.append(
            {
                "symbol": sym,
                "perp_price": c.perp_price,
                "spot_price": c.spot_price,
                "price_decimals": c.price_decimals,
                "spot_perp_basis_pct": round(c.spot_perp_basis_pct, 3),
                "funding_rate_pct": round(c.funding_rate * 100.0, 4),
                "funding_countdown": c.funding_countdown_str,
                "oi_delta_15m_pct": c.oi_delta_15m_pct,
                "confluence_score": c.trade_rank_score,
                "spoof_risk_score": c.spoof_risk_score,
                "spot_cvd_60s": round(c.spot_cvd_60s, 0),
                "perp_cvd_60s": round(c.perp_cvd_60s, 0),
                "ret_1m_pct": c.ret_1m_pct,
                "ret_15m_pct": c.ret_15m_pct,
                "change_24h_pct": c.change_24h_pct,
                "quote_volume_24h_usd": round(c.quote_volume_24h_usd, 0),
                "squeeze_type": c.squeeze_type,
                "signal_state": c.signal_state,
                # 15-Minute Candle Trade Position Fields for every Top 10 coin:
                "bias": setup.bias if setup else "LONG",
                "entry_price": setup.entry_price if setup else c.perp_price,
                "hard_sl": setup.hard_sl if setup else c.perp_price,
                "tp1": setup.tp1 if setup else c.perp_price,
                "tp2": setup.tp2 if setup else c.perp_price,
                "leverage": setup.leverage if setup else 4,
                "rr_ratio": setup.rr_ratio if setup else 2.5,
                "liquidation_price": setup.liquidation_price if setup else 0.0,
                "sl_distance_pct": setup.sl_distance_pct if setup else 1.0,
                "tp1_distance_pct": setup.tp1_distance_pct if setup else 1.6,
                "tp2_distance_pct": setup.tp2_distance_pct if setup else 3.0,
                "candle_15m_atr_pct": setup.candle_15m_atr_pct if setup else 0.85,
                "candle_15m_structure": setup.candle_15m_structure if setup else "15M BULLISH BREAKOUT",
                "win_probability_pct": setup.win_probability_pct if setup else 68.5,
            }
        )
    scanner_cards.sort(key=lambda x: x["confluence_score"], reverse=True)
    scanner_cards = scanner_cards[:10]

    # Active symbol position & 15-minute time-stop countdown
    active_pos = state.positions.get(active_sym)
    pos_dict = None
    if active_pos:
        rem_sec = max(0, int(active_pos.time_stop_sec - (now - active_pos.opened_at)))
        pos_dict = {
            **asdict(active_pos),
            "remaining_sec": rem_sec,
            "countdown_str": f"{rem_sec // 60:02d}:{rem_sec % 60:02d}",
        }

    all_positions = []
    for p in state.positions.values():
        rem_s = max(0, int(p.time_stop_sec - (now - p.opened_at)))
        all_positions.append(
            {
                **asdict(p),
                "remaining_sec": rem_s,
                "countdown_str": f"{rem_s // 60:02d}:{rem_s % 60:02d}",
            }
        )

    return {
        "type": "TERMINAL_SNAPSHOT",
        "ts": now,
        "engine_meta": {
            "event_loop": ACTIVE_LOOP_POLICY,
            "serializer": "orjson",
            "live_feeds_connected": state.live_feeds_connected,
            "events_processed": bus.events_processed,
            "execution_mode": state.execution_mode,
            "paper_balance_usd": state.paper_balance_usd,
        },
        "btc_anchor": {
            "regime": state.btc_regime,
            "ret_1m_pct": state.btc_1m_return_pct,
            "cvd_60s": round(state.btc_cvd_60s, 0),
        },
        "kill_switch": {
            "active": state.kill_switch_active,
            "ticker": state.kill_switch_ticker,
            "reason": state.kill_switch_reason,
        },
        "gemini_stats": state.gemini_stats,
        "active_symbol": active_sym,
        "scanner_ribbon": scanner_cards,
        "active_detail": {
            "symbol": active_sym,
            "perp_price": active_coin.perp_price,
            "spot_price": active_coin.spot_price,
            "mark_price": active_coin.mark_price,
            "price_decimals": active_coin.price_decimals,
            "spot_perp_basis_pct": round(active_coin.spot_perp_basis_pct, 4),
            "funding_rate_pct": round(active_coin.funding_rate * 100.0, 4),
            "funding_countdown": active_coin.funding_countdown_str,
            "open_interest_usd": active_coin.open_interest_usd,
            "oi_delta_15m_pct": active_coin.oi_delta_15m_pct,
            "top_trader_ls_ratio": active_coin.top_trader_ls_ratio,
            "taker_buy_sell_ratio": active_coin.taker_buy_sell_ratio,
            "spot_cvd_60s": round(active_coin.spot_cvd_60s, 0),
            "perp_cvd_60s": round(active_coin.perp_cvd_60s, 0),
            "short_liq_60s_usd": round(active_coin.short_liq_60s_usd, 0),
            "long_liq_60s_usd": round(active_coin.long_liq_60s_usd, 0),
            "spoof_risk_score": active_coin.spoof_risk_score,
            "last_spoof_event": active_coin.last_spoof_event,
            "confluence_score": active_coin.trade_rank_score,
            "change_24h_pct": active_coin.change_24h_pct,
            "quote_volume_24h_usd": round(active_coin.quote_volume_24h_usd, 0),
            "squeeze_type": active_coin.squeeze_type,
            "news_score": active_coin.news_score,
            "funding_score": active_coin.funding_score,
            "latest_news_headline": active_coin.latest_news_headline,
            "news_sentiment": active_coin.news_sentiment,
            "ma_pinch_score": active_coin.ma_pinch_score,
            "bids": active_coin.bids,
            "asks": active_coin.asks,
            "klines_1m": list(active_coin.klines_1m)[-90:],
            "chart_markers": list(active_coin.chart_markers)[-25:],
            "ai_setup": asdict(active_coin.ai_setup) if active_coin.ai_setup else None,
            "setups_by_tf": {
                tf: asdict(s) for tf, s in active_coin.setups_by_tf.items()
            },
        },
        "active_position": pos_dict,
        "all_positions": all_positions,
        "liquidations_tape": [asdict(x) for x in list(state.liquidations_tape)[:30]],
        "news_tape": [asdict(x) for x in list(state.news_tape)[:25]],
        "ai_alerts_tape": list(state.ai_alerts_tape)[:20],
    }


async def _multiplexed_broadcaster_loop() -> None:
    """Broadcasts compact JSON diffs every 180ms (~5.5 FPS) to connected React clients."""
    while True:
        try:
            if ws_manager.active_connections:
                snap = build_terminal_snapshot()
                payload_bytes = json_dumps(snap)
                await ws_manager.broadcast_bytes(payload_bytes)
        except asyncio.CancelledError:
            break
        except Exception:
            pass
        await asyncio.sleep(0.18)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await bus.start()
    spoof_detector.start()
    gemini_brain.start()
    await derivatives_poller.start()
    await futures_feed.start()
    await spot_feed.start()
    await news_stream.start()
    await confluence_engine.start()
    broadcaster_task = asyncio.create_task(_multiplexed_broadcaster_loop())
    yield
    broadcaster_task.cancel()
    await confluence_engine.stop()
    await news_stream.stop()
    await derivatives_poller.stop()
    await spot_feed.stop()
    await futures_feed.stop()
    await bus.stop()


app = FastAPI(title="Perp AI Terminal — 3-Tier Event Engine", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/snapshot")
async def get_snapshot() -> Response:
    snap = build_terminal_snapshot()
    return Response(content=json_dumps(snap), media_type="application/json")


@app.get("/api/symbols")
async def get_all_symbols() -> Dict[str, Any]:
    """Return all 300+ active Binance USDS-M Perpetual USDT symbols for search autocomplete."""
    return {"symbols": derivatives_poller.get_all_supported_symbols()}


@app.post("/api/search-coin/{query}")
async def search_and_select_coin(query: str) -> Dict[str, Any]:
    """On-demand search for any Binance USDS-M Perpetual contract; fetches live 15m klines & computes position setup."""
    res = await derivatives_poller.lookup_and_activate_coin(query)
    return res


@app.post("/api/active-symbol/{symbol}")
async def set_active_symbol(symbol: str) -> Dict[str, Any]:
    sym = symbol.upper()
    res = await derivatives_poller.lookup_and_activate_coin(sym)
    return {"active_symbol": state.active_symbol, **res}


@app.post("/api/kill-switch/reset")
async def reset_kill_switch() -> Dict[str, Any]:
    state.kill_switch_active = False
    state.kill_switch_reason = ""
    state.kill_switch_ticker = ""
    return {"status": "ok", "kill_switch_active": False}


@app.post("/api/order/open")
async def open_paper_order(req: OrderRequest) -> Dict[str, Any]:
    sym = req.symbol.upper()
    if sym not in state.coins:
        return {"error": f"Unknown symbol {sym}"}

    # Block altcoin longs if BTC Regime Anchor is in DUMP_BLOCK
    if req.side.upper() == "LONG" and sym != "BTCUSDT" and state.btc_regime == "DUMP_BLOCK":
        return {
            "error": "BLOCKED BY BTC REGIME ANCHOR: BTC dumped >0.35% in 60s. Altcoin longs auto-blocked."
        }

    coin = state.coins[sym]
    # Lock leverage strictly to 3x - 5x Isolated Margin
    lev = max(3, min(5, req.leverage))
    margin = min(req.margin_usd, state.paper_balance_usd)
    size_usd = round(margin * lev, 2)
    entry_p = coin.perp_price
    decimals = 6 if entry_p < 1 else 2

    if req.side.upper() == "LONG":
        sl = coin.ai_setup.hard_sl if coin.ai_setup else round(entry_p * 0.989, decimals)
        tp1 = coin.ai_setup.tp1 if coin.ai_setup else round(entry_p * 1.013, decimals)
        tp2 = coin.ai_setup.tp2 if coin.ai_setup else round(entry_p * 1.026, decimals)
    else:
        sl = round(entry_p * 1.011, decimals)
        tp1 = round(entry_p * 0.987, decimals)
        tp2 = round(entry_p * 0.974, decimals)

    pos = PaperPosition(
        id=f"pos-{uuid.uuid4().hex[:6]}",
        symbol=sym,
        side=req.side.upper(),
        entry_price=entry_p,
        mark_price=entry_p,
        size_usd=size_usd,
        margin_usd=margin,
        leverage=lev,
        hard_sl=sl,
        tp1=tp1,
        tp2=tp2,
        opened_at=time.time(),
        time_stop_sec=900,
    )
    state.positions[sym] = pos
    return {"status": "opened", "position": asdict(pos)}


@app.post("/api/order/partial-close/{symbol}")
async def partial_close_50(symbol: str) -> Dict[str, Any]:
    sym = symbol.upper()
    pos = state.positions.get(sym)
    if not pos:
        return {"error": "No open position"}
    realized = round(pos.pnl_usd * 0.5, 2)
    state.paper_balance_usd = round(state.paper_balance_usd + realized, 2)
    pos.size_usd = round(pos.size_usd * 0.5, 2)
    pos.margin_usd = round(pos.margin_usd * 0.5, 2)
    pos.pnl_usd = round(pos.pnl_usd * 0.5, 2)
    pos.partial_closed = True
    return {"status": "partial_closed_50", "realized_usd": realized, "position": asdict(pos)}


@app.post("/api/order/move-sl-be/{symbol}")
async def move_sl_to_breakeven(symbol: str) -> Dict[str, Any]:
    sym = symbol.upper()
    pos = state.positions.get(sym)
    if not pos:
        return {"error": "No open position"}
    pos.hard_sl = pos.entry_price
    pos.is_be_moved = True
    coin = state.coins.get(sym)
    if coin and coin.ai_setup:
        coin.ai_setup.hard_sl = pos.entry_price
    return {"status": "moved_to_be", "new_sl": pos.hard_sl}


@app.post("/api/order/close/{symbol}")
async def close_position(symbol: str) -> Dict[str, Any]:
    sym = symbol.upper()
    pos = state.positions.pop(sym, None)
    if not pos:
        return {"error": "No open position"}
    state.paper_balance_usd = round(state.paper_balance_usd + pos.pnl_usd, 2)
    return {"status": "closed", "realized_usd": pos.pnl_usd}


@app.post("/api/simulate-event")
async def simulate_pipeline_event(req: SimulateEventRequest) -> Dict[str, Any]:
    """
    Interactive test harness to trigger any stage of the 3-tier pipeline on demand:
    - UPBIT_LISTING: Tier-0 regex match -> Tier-1 Gemini Triage -> ALERT_LONG + chart marker
    - EXPLOIT_KILL_SWITCH: Tier-1 Exploit detection (Urgency >= 85) -> Red Emergency Kill-Switch Alarm
    - ANOMALY_SEARCH: >1.8% 2m price jump with 0 news -> Tier-2 Gemini Google Search Grounding badge
    - BTC_DUMP_BLOCK: BTC drops -0.48% in 60s -> Auto-blocks altcoin longs
    - SHORT_SQUEEZE: $180K forced short liquidation cascade + Spot CVD burst -> Confluence >= 88
    """
    sym = req.symbol.upper() if req.symbol.upper() in state.coins else state.active_symbol
    coin = state.coins[sym]
    base_ticker = sym.replace("USDT", "")
    scenario = req.scenario.upper()

    if scenario == "UPBIT_LISTING":
        coin.spot_cvd_60s += 320000
        coin.oi_delta_15m_pct = round(max(coin.oi_delta_15m_pct, 8.4), 2)
        coin.confluence_score = 91
        await news_stream.ingest_headline(
            f"BREAKING: Upbit announces KRW spot market listing for {base_ticker} ({sym}) — trading begins in 30 minutes",
            source="TreeNews WS / Upbit",
            trigger_ai=True,
        )
        return {"status": "triggered", "scenario": scenario, "symbol": sym}

    if scenario == "EXPLOIT_KILL_SWITCH":
        await news_stream.ingest_headline(
            f"URGENT SECURITY ALERT: {base_ticker} bridge smart contract exploited for $28M; abnormal token minting & exchange deposits halted",
            source="TreeNews Security / PeckShield",
            trigger_ai=True,
        )
        return {"status": "triggered", "scenario": scenario, "symbol": sym}

    if scenario == "ANOMALY_SEARCH":
        decimals = 6 if coin.perp_price < 1 else 2
        coin.perp_price = round(coin.perp_price * 1.024, decimals)
        coin.mark_price = coin.perp_price
        coin.ret_2m_pct = 2.42
        coin.volume_1m_usd = coin.avg_volume_1m_usd * 4.8
        await bus.publish(
            "tier2_anomaly_trigger",
            {
                "symbol": sym,
                "ret_2m_pct": 2.42,
                "vol_spike_ratio": 4.8,
                "oi_delta_15m_pct": coin.oi_delta_15m_pct,
                "ts": time.time(),
            },
        )
        return {"status": "triggered", "scenario": scenario, "symbol": sym}

    if scenario == "BTC_DUMP_BLOCK":
        btc = state.coins["BTCUSDT"]
        now = time.time()
        btc.perp_price = round(btc.perp_price * 0.9945, 2)
        btc.price_history_15m.append((now, btc.perp_price))
        btc.ret_1m_pct = -0.52
        state.btc_regime = "DUMP_BLOCK"
        state.btc_1m_return_pct = -0.52
        state.btc_dump_blocked_until = now + 90.0
        return {"status": "triggered", "scenario": scenario, "btc_regime": "DUMP_BLOCK"}

    if scenario == "SHORT_SQUEEZE":
        decimals = 6 if coin.perp_price < 1 else 2
        coin.perp_price = round(coin.perp_price * 1.015, decimals)
        coin.spot_price = round(coin.perp_price * 1.0018, decimals)
        coin.spot_cvd_60s += 285000
        coin.perp_cvd_60s += 95000
        coin.oi_delta_15m_pct = 6.8
        futures_feed._handle_force_order(
            {
                "s": sym,
                "S": "BUY",
                "ap": str(coin.perp_price),
                "q": str(165000.0 / coin.perp_price),
            }
        )
        return {"status": "triggered", "scenario": scenario, "symbol": sym}

    return {"error": f"Unknown scenario {scenario}"}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws_manager.connect(ws)
    try:
        # Send immediate initial snapshot on connect
        snap = build_terminal_snapshot()
        await ws.send_text(json_dumps(snap).decode("utf-8"))
        while True:
            msg = await ws.receive_text()
            if msg.startswith("SELECT:"):
                sym = msg.split(":", 1)[1].strip().upper()
                await derivatives_poller.lookup_and_activate_coin(sym)
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
    except Exception:
        ws_manager.disconnect(ws)


# ---------------------------------------------------------------------------
# Production Single-Host SPA Static Serving (Render / Docker)
# ---------------------------------------------------------------------------
frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

if frontend_dist.exists() and (frontend_dist / "index.html").exists():
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api/") or full_path == "api" or full_path.startswith("ws"):
            return Response(status_code=404)
        file_path = frontend_dist / full_path
        if full_path and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(frontend_dist / "index.html")

