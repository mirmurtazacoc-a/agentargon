import React, { useEffect, useRef, useState } from 'react';
import {
  AlertOctagon,
  Radar,
  Search,
  ShieldAlert,
  ShieldCheck,
  Wifi,
  WifiOff,
  X,
} from 'lucide-react';
import { TerminalSnapshot } from '../types/terminal';

interface TopScannerRibbonProps {
  snapshot: TerminalSnapshot;
  allSymbols: string[];
  isSearching: boolean;
  wsConnected: boolean;
  onSearchCoin: (query: string) => void;
  onResetKillSwitch: () => void;
}

export const TopScannerRibbon: React.FC<TopScannerRibbonProps> = ({
  snapshot,
  allSymbols,
  isSearching,
  wsConnected,
  onSearchCoin,
  onResetKillSwitch,
}) => {
  const { btc_anchor, kill_switch } = snapshot;

  const [searchQuery, setSearchQuery] = useState<string>('');
  const [showDropdown, setShowDropdown] = useState<boolean>(false);
  const searchWrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (searchWrapRef.current && !searchWrapRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const filteredMatches = searchQuery.trim()
    ? allSymbols
        .filter((s) => s.includes(searchQuery.trim().toUpperCase()))
        .slice(0, 10)
    : [];

  const handleSubmitSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    onSearchCoin(searchQuery.trim());
    setShowDropdown(false);
  };

  const handlePickSuggestion = (sym: string) => {
    setSearchQuery(sym);
    setShowDropdown(false);
    onSearchCoin(sym);
  };

  return (
    <header className="w-full bg-[#090d16] border-b border-slate-800/90 flex flex-col select-none sticky top-0 z-40">
      {/* Emergency Kill-Switch Red Alarm Banner */}
      {kill_switch.active && (
        <div className="bg-red-600/95 text-white px-3 py-1.5 flex items-center justify-between text-xs font-mono font-bold border-b border-red-400 animate-pulse">
          <div className="flex items-center gap-2 truncate">
            <AlertOctagon className="w-4 h-4 shrink-0" />
            <span className="truncate">{kill_switch.reason}</span>
          </div>
          <button
            onClick={onResetKillSwitch}
            className="px-2 py-0.5 bg-black/40 hover:bg-black/60 rounded border border-white/30 text-[10px] shrink-0"
          >
            RESET
          </button>
        </div>
      )}

      {/* Brand + BTC Regime + Global Binance Coin Search Bar */}
      <div className="px-3.5 py-2.5 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2.5 font-mono">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 font-bold text-cyan-400 tracking-wider text-xs sm:text-sm">
            <Radar
              className="w-4 h-4 text-cyan-400 animate-spin shrink-0"
              style={{ animationDuration: '6s' }}
            />
            <span>X-QUANT 15M • 1H • 4H</span>
          </div>

          <div className="flex items-center gap-1.5">
            {btc_anchor.regime === 'DUMP_BLOCK' ? (
              <span className="flex items-center gap-1 px-2 py-0.5 rounded bg-red-500/20 border border-red-500 text-red-300 text-[10px] font-bold animate-pulse">
                <ShieldAlert className="w-3 h-3 text-red-400" />
                BTC DUMP ({btc_anchor.ret_1m_pct.toFixed(2)}%)
              </span>
            ) : (
              <span className="flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 text-[10px] font-semibold">
                <ShieldCheck className="w-3 h-3 text-emerald-400" />
                BTC {btc_anchor.ret_1m_pct >= 0 ? '+' : ''}
                {btc_anchor.ret_1m_pct.toFixed(2)}%
              </span>
            )}

            <span
              className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] border ${
                wsConnected
                  ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                  : 'bg-rose-500/15 border-rose-500/30 text-rose-400'
              }`}
            >
              {wsConnected ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
              <span>{wsConnected ? 'LIVE' : 'SYNC'}</span>
            </span>
          </div>
        </div>

        {/* Search Any Coin on Binance Input */}
        <div ref={searchWrapRef} className="relative w-full sm:w-80 md:w-96">
          <form onSubmit={handleSubmitSearch} className="flex items-center gap-1.5">
            <div className="relative flex-1">
              <Search className="w-3.5 h-3.5 text-cyan-400 absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                type="text"
                value={searchQuery}
                onFocus={() => setShowDropdown(true)}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setShowDropdown(true);
                }}
                placeholder="Search any coin (DOGE, BTC, SOL, PEPE)..."
                className="w-full pl-8 pr-7 py-1.5 rounded-md bg-[#0c1322] border border-cyan-500/40 focus:border-cyan-400 focus:outline-none text-xs text-white placeholder-slate-500 font-mono"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => {
                    setSearchQuery('');
                    setShowDropdown(false);
                  }}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
            <button
              type="submit"
              disabled={isSearching}
              className="px-3 py-1.5 rounded-md bg-cyan-500 hover:bg-cyan-400 active:scale-95 text-slate-950 font-bold text-xs transition shrink-0"
            >
              {isSearching ? '...' : 'SEARCH'}
            </button>
          </form>

          {/* Autocomplete Dropdown */}
          {showDropdown && filteredMatches.length > 0 && (
            <div className="absolute left-0 right-0 mt-1 bg-[#0b111e] border border-cyan-500/50 rounded-md shadow-2xl max-h-60 overflow-y-auto divide-y divide-slate-800/70 z-50">
              {filteredMatches.map((sym) => (
                <button
                  key={sym}
                  type="button"
                  onClick={() => handlePickSuggestion(sym)}
                  className="w-full px-3 py-2.5 text-left text-xs font-mono text-slate-200 hover:bg-cyan-500/20 flex items-center justify-between transition"
                >
                  <span className="font-bold text-white">
                    {sym.replace('USDT', '')}
                    <span className="text-slate-500 text-[10px] ml-0.5">USDT</span>
                  </span>
                  <span className="text-[10px] text-cyan-400">Calculate Trade →</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </header>
  );
};
