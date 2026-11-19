import React, { useState } from 'react';
import {
  ArrowRightLeft,
  CheckCircle2,
  Clock,
  Crosshair,
  DollarSign,
  Lock,
  Scissors,
  Shield,
  XCircle,
} from 'lucide-react';
import { ActiveDetail, PaperPosition } from '../types/terminal';

interface BottomActionRiskBarProps {
  detail: ActiveDetail;
  activePosition: PaperPosition | null;
  paperBalanceUsd: number;
  btcRegime: 'GREEN' | 'CAUTION' | 'DUMP_BLOCK';
  onOpenOrder: (side: 'LONG' | 'SHORT', leverage: number, marginUsd: number) => void;
  onPartialClose50: (symbol: string) => void;
  onMoveSlToBe: (symbol: string) => void;
  onClosePosition: (symbol: string) => void;
}

export const BottomActionRiskBar: React.FC<BottomActionRiskBarProps> = ({
  detail,
  activePosition,
  paperBalanceUsd,
  btcRegime,
  onOpenOrder,
  onPartialClose50,
  onMoveSlToBe,
  onClosePosition,
}) => {
  // Locked strictly to 3x - 5x Isolated Margin per system rules
  const [leverage, setLeverage] = useState<number>(4);
  const [marginUsd, setMarginUsd] = useState<number>(1000);

  const isAltLongBlocked = detail.symbol !== 'BTCUSDT' && btcRegime === 'DUMP_BLOCK';
  const ai = detail.ai_setup;

  return (
    <footer className="w-full bg-[#090d16] border-t border-slate-800/90 px-3 py-2 flex flex-wrap items-center justify-between gap-3 select-none font-mono text-xs">
      {/* Left: One-Click Paper / Live Execution Ticket Locked to 3x-5x Isolated Margin */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1.5 bg-slate-900/90 px-2.5 py-1.5 rounded border border-slate-800">
          <Lock className="w-3.5 h-3.5 text-cyan-400" />
          <span className="text-slate-400 text-[11px]">ISOLATED MARGIN:</span>
          {([3, 4, 5] as const).map((lev) => (
            <button
              key={lev}
              onClick={() => setLeverage(lev)}
              className={`px-2 py-0.5 rounded text-[11px] font-bold transition ${
                leverage === lev
                  ? 'bg-cyan-500 text-slate-950'
                  : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
              }`}
            >
              {lev}x
            </button>
          ))}
        </div>

        {/* Margin Collateral Selector */}
        <div className="flex items-center gap-1.5 bg-slate-900/90 px-2.5 py-1.5 rounded border border-slate-800">
          <DollarSign className="w-3.5 h-3.5 text-emerald-400" />
          <span className="text-slate-400 text-[11px]">MARGIN:</span>
          {[500, 1000, 2500].map((amt) => (
            <button
              key={amt}
              onClick={() => setMarginUsd(amt)}
              className={`px-2 py-0.5 rounded text-[11px] font-bold transition ${
                marginUsd === amt
                  ? 'bg-emerald-500/25 text-emerald-300 border border-emerald-500/50'
                  : 'bg-slate-800 text-slate-400 hover:text-slate-200'
              }`}
            >
              ${amt}
            </button>
          ))}
          <span className="text-slate-500 text-[10px] ml-1">
            (Notional: ${(marginUsd * leverage).toLocaleString()})
          </span>
        </div>

        {/* One-Click Long / Short Execution Buttons */}
        <div className="flex items-center gap-2">
          <button
            disabled={isAltLongBlocked}
            onClick={() => onOpenOrder('LONG', leverage, marginUsd)}
            className={`px-3.5 py-1.5 rounded font-bold text-xs flex items-center gap-1.5 transition ${
              isAltLongBlocked
                ? 'bg-slate-800 text-slate-500 border border-slate-700 cursor-not-allowed'
                : 'bg-emerald-500 hover:bg-emerald-400 text-slate-950 shadow-[0_0_15px_rgba(16,185,129,0.25)]'
            }`}
          >
            <Crosshair className="w-3.5 h-3.5" />
            {isAltLongBlocked
              ? 'LONG BLOCKED (BTC DUMP)'
              : `1-CLICK LONG ${detail.symbol.replace('USDT', '')} (${leverage}x)`}
          </button>

          <button
            onClick={() => onOpenOrder('SHORT', leverage, marginUsd)}
            className="px-3 py-1.5 rounded font-bold text-xs bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-500/40 transition"
          >
            1-CLICK SHORT ({leverage}x)
          </button>
        </div>
      </div>

      {/* Center: AI Computed Entry / Hard SL / TP1 / TP2 Summary */}
      {ai && (
        <div className="hidden 2xl:flex items-center gap-3 bg-[#0c121e] px-3 py-1.5 rounded border border-slate-800 text-[11px]">
          <span className="text-cyan-400 font-bold">AI LEVELS:</span>
          <span>
            Entry:{' '}
            <strong className="text-white">
              ${ai.entry_price.toFixed(detail.price_decimals ?? 4)}
            </strong>
          </span>
          <span>
            Hard SL:{' '}
            <strong className="text-rose-400">
              ${ai.hard_sl.toFixed(detail.price_decimals ?? 4)}
            </strong>
          </span>
          <span>
            TP1:{' '}
            <strong className="text-emerald-400">
              ${ai.tp1.toFixed(detail.price_decimals ?? 4)}
            </strong>
          </span>
          <span>
            TP2:{' '}
            <strong className="text-emerald-300">
              ${ai.tp2.toFixed(detail.price_decimals ?? 4)}
            </strong>
          </span>
        </div>
      )}

      {/* Right: Active Position Controls (50% Partial Close, Move SL to BE, 15m Time-Stop Countdown) */}
      <div className="flex items-center gap-2.5">
        {activePosition ? (
          <div className="flex items-center gap-2 bg-slate-900/95 px-3 py-1 rounded border border-cyan-500/40">
            <div className="flex items-center gap-1.5 pr-2 border-r border-slate-800">
              <span
                className={`px-1.5 py-0.2 rounded text-[10px] font-bold ${
                  activePosition.side === 'LONG'
                    ? 'bg-emerald-500/20 text-emerald-300'
                    : 'bg-rose-500/20 text-rose-300'
                }`}
              >
                {activePosition.side} {activePosition.leverage}x
              </span>
              <span className="font-bold text-white">{activePosition.symbol}</span>
              <span
                className={`font-bold ${
                  activePosition.pnl_usd >= 0 ? 'text-emerald-400' : 'text-rose-400'
                }`}
              >
                {activePosition.pnl_usd >= 0 ? '+' : ''}${activePosition.pnl_usd.toFixed(2)} (
                {activePosition.pnl_pct >= 0 ? '+' : ''}
                {activePosition.pnl_pct.toFixed(2)}%)
              </span>
            </div>

            {/* Visual 15-Minute Time-Stop Countdown */}
            <div
              className="flex items-center gap-1 px-2 py-0.5 rounded bg-amber-500/15 border border-amber-500/40 text-amber-300 text-[11px]"
              title="15-Minute Time-Stop Countdown: Auto-exits stagnant trades if TP1 is not reached"
            >
              <Clock className="w-3.5 h-3.5 text-amber-400" />
              <span>15m Time-Stop:</span>
              <strong className="font-bold">{activePosition.countdown_str}</strong>
            </div>

            {/* 50% Partial Close Button */}
            <button
              onClick={() => onPartialClose50(activePosition.symbol)}
              className="px-2.5 py-1 rounded bg-cyan-500/15 hover:bg-cyan-500/25 border border-cyan-500/40 text-cyan-300 text-[11px] font-bold flex items-center gap-1 transition"
            >
              <Scissors className="w-3 h-3" />
              50% Partial Close
            </button>

            {/* Move SL to Break-Even Button */}
            <button
              onClick={() => onMoveSlToBe(activePosition.symbol)}
              className={`px-2.5 py-1 rounded border text-[11px] font-bold flex items-center gap-1 transition ${
                activePosition.is_be_moved
                  ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-300'
                  : 'bg-purple-500/15 hover:bg-purple-500/25 border-purple-500/40 text-purple-300'
              }`}
            >
              <Shield className="w-3 h-3" />
              {activePosition.is_be_moved ? 'SL @ Break-Even ✓' : 'Move SL → BE'}
            </button>

            {/* Full Market Close */}
            <button
              onClick={() => onClosePosition(activePosition.symbol)}
              className="px-2 py-1 rounded bg-rose-500/20 hover:bg-rose-500/35 border border-rose-500/50 text-rose-300 text-[11px] font-bold flex items-center gap-1 transition"
            >
              <XCircle className="w-3 h-3" />
              Exit
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-3 text-slate-400 text-[11px] bg-slate-900/70 px-3 py-1.5 rounded border border-slate-800">
            <span>No active position on {detail.symbol}</span>
            <span className="text-slate-600">|</span>
            <span>
              Paper Equity:{' '}
              <strong className="text-emerald-400 font-bold">
                ${paperBalanceUsd.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </strong>
            </span>
          </div>
        )}
      </div>
    </footer>
  );
};
