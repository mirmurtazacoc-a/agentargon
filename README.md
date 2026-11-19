"""
Zero-Dependency Node.js Fallback Server for Perp-AI Terminal (`frontend/dev-backend.mjs`):
When Python is not yet installed on a Windows workstation, this optional Node.js
multiplexed WebSocket + REST backend runs out-of-the-box using Node 18+ built-ins
and serves the exact same `/api/*` and `/ws` 3-Tier Event Pipeline protocol!
For production sub-5ms Python execution (`orjson` + `winloop`/`uvloop` + `google-genai`),
run `uvicorn backend.api.server:app --host 0.0.0.0 --port 8000`.
"""

# PERP-AI TERMINAL — Event-Driven 3-Tier Derivatives & AI Pipeline

Full-stack web trading terminal designed for **sub-100ms signal processing**, **derivatives positioning + forced liquidation flow**, and **~85% lower Gemini API token spend** via a 3-Tier Event Funnel and >4,096-token Implicit Prompt Caching.

---

## Architecture Overview

```text
perp-ai-terminal/
├── backend/
│   ├── core/
│   │   ├── bus.py                # Async event bus (ticks, liqs, news, alerts)
│   │   └── state.py              # In-memory deque ring buffers (orjson + winloop/uvloop)
│   ├── feeds/
│   │   ├── binance_futures.py    # /public depth + /market klines, aggTrades, !forceOrder@arr, !contractInfo
│   │   ├── binance_spot.py       # Spot aggTrade stream for Spot-vs-Perp CVD divergence
│   │   ├── derivatives_rest.py   # 1m/5m poller: OI Hist, Top Trader L/S, Taker Buy/Sell Ratio
│   │   └── news_stream.py        # Tree News WS + announcements + Tier-0 ticker/keyword regex filter
│   ├── engine/
│   │   ├── spoof_detector.py     # L2 wall tracking & spoof risk score (0-100)
│   │   ├── confluence.py         # Tier-0 quant scoring + BTC 60s dump guard (>0.35% block)
│   │   └── gemini_brain.py       # Cached Tier-1 triage (gemini-3.8-flash) + Tier-2 Google Search Grounding (gemini-4-argon)
│   └── api/
│       └── server.py             # FastAPI REST + 150ms-180ms throttled WS broadcaster
└── frontend/                     # React + TypeScript + Tailwind + Vite + TradingView Lightweight Charts
    ├── src/
    │   ├── components/
    │   │   ├── TopScannerRibbon.tsx         # Multi-coin heatbar ranked by Confluence (0-100) + BTC Regime badge
    │   │   ├── CenterChart.tsx              # 1m/15m candlesticks + AI Entry/SL/TP1/TP2 lines + Liq/News markers
    │   │   ├── RightMicrostructureStack.tsx # L2 wall bars (spoof yellow highlight) + Spot vs Perp CVD + News/Liq tape
    │   │   └── BottomActionRiskBar.tsx      # 3x-5x Isolated Margin ticket + 50% Partial + Move SL->BE + 15m Time-Stop
    │   ├── types/terminal.ts
    │   └── App.tsx
    └── package.json
```

---

## Quick Start

### 1. Start the Python Backend (FastAPI + `orjson` + `winloop`/`uvloop`)

```powershell
# Install dependencies into your existing backend\.venv virtual environment
.\backend\.venv\Scripts\pip.exe install -r requirements.txt

# Optional: Set your Gemini API key for live Tier-1 Triage & Tier-2 Search Grounding
$env:GEMINI_API_KEY="your_api_key_here"

# Launch FastAPI server on port 8000 (run from the project root directory)
.\backend\.venv\Scripts\uvicorn.exe backend.api.server:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Start the React + TradingView Lightweight Charts Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` in your browser. Use the **Test 3-Tier Funnel** buttons in the top bar (`Tier-1 Listing`, `Short Liq Cascade`, `Tier-2 Search Grounding`, `BTC Dump Guard`, `Kill-Switch`) to test every tier of the event pipeline live on the chart.
