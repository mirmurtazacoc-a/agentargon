import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Activity, Clock, Flame, Trophy } from 'lucide-react';
import { CenterChart } from './components/CenterChart';
import { TopScannerRibbon } from './components/TopScannerRibbon';
import { ScannerCard, TerminalSnapshot } from './types/terminal';

export default function App() {
  const [snapshot, setSnapshot] = useState<TerminalSnapshot | null>(null);
  const [allSymbols, setAllSymbols] = useState<string[]>([]);
  const [isSearching, setIsSearching] = useState<boolean>(false);
  const [wsConnected, setWsConnected] = useState<boolean>(false);
  const [toastMsg, setToastMsg] = useState<string>('');
  const wsRef = useRef<WebSocket | null>(null);

  const showToast = (msg: string) => {
    setToastMsg(msg);
    setTimeout(() => {
      setToastMsg((prev) => (prev === msg ? '' : prev));
    }, 3000);
  };

  useEffect(() => {
    let isMounted = true;
    let reconnectTimer: number | undefined;

    const connectWs = () => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.host}/ws`;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        if (isMounted) setWsConnected(true);
      };

      ws.onmessage = (event) => {
        if (!isMounted) return;
        try {
          const data: TerminalSnapshot = JSON.parse(event.data);
          if (data && data.type === 'TERMINAL_SNAPSHOT') {
            setSnapshot(data);
          }
        } catch {
          // ignore malformed packet
        }
      };

      ws.onclose = () => {
        if (!isMounted) return;
        setWsConnected(false);
        reconnectTimer = window.setTimeout(connectWs, 1500);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    fetch('/api/snapshot')
      .then((res) => res.json())
      .then((data: TerminalSnapshot) => {
        if (isMounted && data?.type === 'TERMINAL_SNAPSHOT') {
          setSnapshot(data);
        }
      })
      .catch(() => {});

    fetch('/api/symbols')
      .then((res) => res.json())
      .then((data: { symbols?: string[] }) => {
        if (isMounted && Array.isArray(data?.symbols)) {
          setAllSymbols(data.symbols);
        }
      })
      .catch(() => {});

    connectWs();

    return () => {
      isMounted = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (wsRef.current) wsRef.current.close();
    };
  }, []);

  const handleSelectSymbol = useCallback(async (sym: string) => {
    setIsSearching(true);
    try {
      const res = await fetch(`/api/active-symbol/${encodeURIComponent(sym)}`, {
        method: 'POST',
      });
      const data = await res.json();
      if (data?.active_symbol) {
        showToast(`Loaded trade calculation for ${data.active_symbol}`);
      }
    } catch {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(`SELECT:${sym}`);
      }
    } finally {
      setIsSearching(false);
    }
  }, []);

  const handleSearchCoin = useCallback(async (query: string) => {
    setIsSearching(true);
    try {
      const res = await fetch(`/api/search-coin/${encodeURIComponent(query)}`, {
        method: 'POST',
      });
      const data = await res.json();
      if (data.error) {
        showToast(data.error);
      } else if (data.symbol) {
        showToast(`Loaded trade calculation for ${data.symbol}`);
      }
    } catch {
      showToast(`Could not load coin '${query}'`);
    } finally {
      setIsSearching(false);
    }
  }, []);

  const handleResetKillSwitch = useCallback(async () => {
    await fetch('/api/kill-switch/reset', { method: 'POST' });
    showToast('Emergency Kill-Switch Alarm Reset');
  }, []);

  if (!snapshot) {
    return (
      <div className="min-h-screen w-full bg-[#06090f] text-slate-200 flex flex-col items-center justify-center font-mono gap-3 p-4">
        <Activity className="w-8 h-8 text-cyan-400 animate-spin" />
        <div className="text-sm font-bold tracking-wider text-center">
          LOADING X-QUANT 15M SQUEEZE RADAR...
        </div>
      </div>
    );
  }

  const { scanner_ribbon, active_symbol } = snapshot;

  return (
    <div className="min-h-screen lg:h-screen w-full flex flex-col bg-[#06090f] text-slate-100 overflow-x-hidden lg:overflow-hidden">
      {/* Toast Notification */}
      {toastMsg && (
        <div className="fixed bottom-5 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-lg bg-cyan-500 text-slate-950 font-mono font-bold text-xs shadow-xl border border-cyan-300">
          {toastMsg}
        </div>
      )}

      {/* TOP HEADER BAR: Brand + Search Any Coin */}
      <TopScannerRibbon
        snapshot={snapshot}
        allSymbols={allSymbols}
        isSearching={isSearching}
        wsConnected={wsConnected}
        onSearchCoin={handleSearchCoin}
        onResetKillSwitch={handleResetKillSwitch}
      />

      {/* MAIN WORKSPACE: LEFT SIDEBAR (Top 10 Coins to Invest/Watch — No Trades Shown) + RIGHT MAIN VIEW (Single Calculated Trade) */}
      <div className="flex-1 flex flex-col lg:flex-row min-h-0 overflow-hidden">
        {/* LEFT SIDEBAR: Top 10 Hot Coins List (Coin Info Only — Click to Calculate Trade on Right) */}
        <aside className="w-full lg:w-[300px] xl:w-[320px] bg-[#090d16] border-b lg:border-b-0 lg:border-r border-slate-800/90 flex flex-col shrink-0 select-none">
          <div className="px-3.5 py-2.5 border-b border-slate-800/80 flex items-center justify-between bg-[#0b101b] font-mono">
            <div className="flex items-center gap-1.5 text-xs font-bold text-amber-300">
              <Trophy className="w-3.5 h-3.5 text-amber-400" />
              <span>TOP 10 HOT COINS</span>
            </div>
            <span className="text-[10px] font-mono text-slate-400">Tap coin to view trade</span>
          </div>

          {/* Mobile: Horizontal swipeable cards | Desktop: Vertical Left Sidebar List */}
          <div className="flex lg:flex-col gap-2 p-2.5 overflow-x-auto lg:overflow-y-auto lg:flex-1 font-mono">
            {scanner_ribbon.slice(0, 10).map((card: ScannerCard, index: number) => {
              const isSelected = card.symbol === active_symbol;
              const dec = card.price_decimals ?? 4;
              const chg = card.change_24h_pct ?? 0;
              const volM = ((card.quote_volume_24h_usd || 0) / 1_000_000).toFixed(0);

              return (
                <button
                  key={card.symbol}
                  onClick={() => handleSelectSymbol(card.symbol)}
                  className={`text-left p-3 rounded-lg border transition-all shrink-0 w-[210px] lg:w-full flex flex-col gap-1.5 ${
                    isSelected
                      ? 'bg-cyan-500/15 border-cyan-400 shadow-[0_0_15px_rgba(34,211,238,0.2)]'
                      : 'bg-[#0c121e] border-slate-800/90 hover:border-slate-600 hover:bg-slate-800/40'
                  }`}
                >
                  {/* Row 1: Rank # + Coin Symbol + Live Price */}
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          isSelected
                            ? 'bg-cyan-400 text-slate-950'
                            : 'bg-slate-800 text-cyan-400'
                        }`}
                      >
                        #{index + 1}
                      </span>
                      <span className="font-bold text-sm text-white">
                        {card.symbol.replace('USDT', '')}
                      </span>
                    </div>
                    <span className="text-xs font-bold text-slate-100">
                      ${card.perp_price.toFixed(dec)}
                    </span>
                  </div>

                  {/* Row 2: 24h Change % + Hot Squeeze Score */}
                  <div className="flex items-center justify-between text-[11px]">
                    <span
                      className={`font-bold ${
                        chg >= 0 ? 'text-emerald-400' : 'text-rose-400'
                      }`}
                    >
                      24h: {chg >= 0 ? '+' : ''}
                      {chg.toFixed(1)}%
                    </span>
                    <span className="px-1.5 py-0.2 rounded bg-amber-500/15 text-amber-300 border border-amber-500/30 text-[10px] font-bold flex items-center gap-1">
                      <Flame className="w-2.5 h-2.5 text-amber-400" />
                      Score {card.confluence_score}
                    </span>
                  </div>

                  {/* Row 3: Funding Rate + 24h Volume (No Trade Levels Here!) */}
                  <div className="flex items-center justify-between text-[10px] text-slate-400 pt-1 border-t border-slate-800/80">
                    <span>
                      Fund:{' '}
                      <strong
                        className={
                          card.funding_rate_pct < 0 ? 'text-emerald-400' : 'text-amber-300'
                        }
                      >
                        {card.funding_rate_pct >= 0 ? '+' : ''}
                        {card.funding_rate_pct.toFixed(3)}%
                      </strong>
                    </span>
                    <span className="flex items-center gap-1 text-slate-400">
                      Vol ${volM}M
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </aside>

        {/* RIGHT / CENTER MAIN PANEL: Shows ONLY the Calculated Trade for the Clicked/Searched Coin */}
        <main className="flex-1 min-w-0 overflow-y-auto bg-[#070b12]">
          <CenterChart detail={snapshot.active_detail} onRefreshCoin={handleSelectSymbol} />
        </main>
      </div>
    </div>
  );
}
