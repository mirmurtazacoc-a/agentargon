import React, { useState } from 'react';
import {
  AlertTriangle,
  Flame,
  Layers,
  Scale,
} from 'lucide-react';
import {
  ActiveDetail,
  LiquidationEvent,
  OrderBookLevel,
} from '../types/terminal';

interface RightMicrostructureStackProps {
  detail: ActiveDetail;
  liquidations: LiquidationEvent[];
}

export const RightMicrostructureStack: React.FC<RightMicrostructureStackProps> = ({
  detail,
  liquidations,
}) => {
  const [filterActiveSymbolOnly, setFilterActiveSymbolOnly] = useState<boolean>(false);

  const maxWallUsd = Math.max(
    100000,
    ...detail.bids.map((b) => b.usd_size),
    ...detail.asks.map((a) => a.usd_size)
  );

  const formatUsdCompact = (val: number) => {
    const abs = Math.abs(val);
    const sign = val < 0 ? '-' : '+';
    if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
    if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(0)}K`;
    return `${sign}$${abs.toFixed(0)}`;
  };

  const cvdDelta = detail.spot_cvd_60s - detail.perp_cvd_60s;
  const isSpotLed = detail.spot_cvd_60s > 0 && cvdDelta > 0;
  const maxCvdBar = Math.max(250000, Math.abs(detail.spot_cvd_60s), Math.abs(detail.perp_cvd_60s));
  const spotWidthPct = Math.min(100, (Math.abs(detail.spot_cvd_60s) / maxCvdBar) * 100);
  const perpWidthPct = Math.min(100, (Math.abs(detail.perp_cvd_60s) / maxCvdBar) * 100);

  const filteredLiqs = filterActiveSymbolOnly
    ? liquidations.filter((l) => l.symbol === detail.symbol || l.symbol === 'BTCUSDT')
    : liquidations;

  return (
    <aside className="w-full lg:w-[370px] xl:w-[400px] bg-[#090d16] border-l border-slate-800/90 flex flex-col h-full overflow-hidden select-none">
      {/* 1. Spot vs. Perp CVD Flow & Derivatives Positioning */}
      <div className="p-3 border-b border-slate-800/80 space-y-2.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-xs font-mono font-bold text-slate-200">
            <Scale className="w-3.5 h-3.5 text-cyan-400" />
            <span>SPOT vs. PERP CVD &amp; POSITIONING</span>
          </div>
          <span
            className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold ${
              isSpotLed
                ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                : detail.perp_cvd_60s > detail.spot_cvd_60s && detail.perp_cvd_60s > 20000
                ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                : 'bg-slate-800 text-slate-400'
            }`}
          >
            {isSpotLed
              ? 'SPOT-LED BUYING'
              : detail.perp_cvd_60s > detail.spot_cvd_60s
              ? 'PERP LEVERAGE'
              : 'BALANCED FLOW'}
          </span>
        </div>

        <div className="space-y-1.5 font-mono text-[11px]">
          <div>
            <div className="flex justify-between mb-0.5">
              <span className="text-slate-400">Spot CVD (Real Buying)</span>
              <span
                className={
                  detail.spot_cvd_60s >= 0 ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold'
                }
              >
                {formatUsdCompact(detail.spot_cvd_60s)}
              </span>
            </div>
            <div className="w-full h-2 bg-slate-900 rounded overflow-hidden border border-slate-800">
              <div
                className={`h-full transition-all duration-200 ${
                  detail.spot_cvd_60s >= 0 ? 'bg-emerald-500' : 'bg-rose-500'
                }`}
                style={{ width: `${spotWidthPct}%` }}
              />
            </div>
          </div>

          <div>
            <div className="flex justify-between mb-0.5">
              <span className="text-slate-400">Perp CVD (Futures Flow)</span>
              <span
                className={
                  detail.perp_cvd_60s >= 0 ? 'text-cyan-300 font-bold' : 'text-rose-400 font-bold'
                }
              >
                {formatUsdCompact(detail.perp_cvd_60s)}
              </span>
            </div>
            <div className="w-full h-2 bg-slate-900 rounded overflow-hidden border border-slate-800">
              <div
                className={`h-full transition-all duration-200 ${
                  detail.perp_cvd_60s >= 0 ? 'bg-cyan-400' : 'bg-rose-500'
                }`}
                style={{ width: `${perpWidthPct}%` }}
              />
            </div>
          </div>
        </div>

        {/* Positioning Mini Grid: Top Trader L/S, Taker Ratio, 60s Liquidations */}
        <div className="grid grid-cols-3 gap-1.5 pt-1 text-[10px] font-mono">
          <div className="bg-[#0d1422] p-1.5 rounded border border-slate-800/80">
            <div className="text-slate-500">Top Trader L/S</div>
            <div className="text-slate-200 font-bold text-xs">{detail.top_trader_ls_ratio}</div>
          </div>
          <div className="bg-[#0d1422] p-1.5 rounded border border-slate-800/80">
            <div className="text-slate-500">Taker Buy/Sell</div>
            <div
              className={`font-bold text-xs ${
                detail.taker_buy_sell_ratio >= 1.0 ? 'text-emerald-400' : 'text-rose-400'
              }`}
            >
              {detail.taker_buy_sell_ratio}
            </div>
          </div>
          <div className="bg-[#0d1422] p-1.5 rounded border border-slate-800/80">
            <div className="text-slate-500">60s Short Liqs</div>
            <div className="text-emerald-400 font-bold text-xs">
              ${(detail.short_liq_60s_usd / 1000).toFixed(0)}K
            </div>
          </div>
        </div>
      </div>

      {/* 2. Live L2 Bid/Ask Orderbook Walls & Spoof Risk */}
      <div className="p-3 border-b border-slate-800/80">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-1.5 text-xs font-mono font-bold text-slate-200">
            <Layers className="w-3.5 h-3.5 text-purple-400" />
            <span>L2 ORDERBOOK WALLS</span>
          </div>
          <div
            className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-bold ${
              detail.spoof_risk_score >= 50
                ? 'bg-yellow-500/25 text-yellow-300 border border-yellow-400 animate-pulse'
                : 'bg-slate-800 text-slate-300'
            }`}
          >
            <AlertTriangle className="w-3 h-3 text-yellow-400" />
            Spoof Risk: {detail.spoof_risk_score}/100
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2 font-mono text-[10px]">
          <div className="space-y-1">
            <div className="flex justify-between text-slate-500 text-[9px] pb-0.5 border-b border-slate-800">
              <span>BID PRICE</span>
              <span>SIZE (USD)</span>
            </div>
            {detail.bids.slice(0, 6).map((b: OrderBookLevel, idx: number) => {
              const widthPct = Math.min(100, (b.usd_size / maxWallUsd) * 100);
              return (
                <div
                  key={idx}
                  className={`relative flex items-center justify-between px-1.5 py-0.5 rounded overflow-hidden ${
                    b.is_spoof_suspect
                      ? 'bg-yellow-500/25 border border-yellow-400 text-yellow-200 font-bold'
                      : 'bg-slate-900/70'
                  }`}
                >
                  <div
                    className={`absolute right-0 top-0 bottom-0 opacity-25 ${
                      b.is_spoof_suspect ? 'bg-yellow-400' : 'bg-emerald-500'
                    }`}
                    style={{ width: `${widthPct}%` }}
                  />
                  <span className="relative z-10 text-emerald-400">
                    {b.price.toFixed(detail.price_decimals ?? 4)}
                  </span>
                  <span className="relative z-10 text-slate-200">
                    ${(b.usd_size / 1000).toFixed(0)}K
                    {b.is_spoof_suspect && ' ⚠️'}
                  </span>
                </div>
              );
            })}
          </div>

          <div className="space-y-1">
            <div className="flex justify-between text-slate-500 text-[9px] pb-0.5 border-b border-slate-800">
              <span>ASK PRICE</span>
              <span>SIZE (USD)</span>
            </div>
            {detail.asks.slice(0, 6).map((a: OrderBookLevel, idx: number) => {
              const widthPct = Math.min(100, (a.usd_size / maxWallUsd) * 100);
              return (
                <div
                  key={idx}
                  className={`relative flex items-center justify-between px-1.5 py-0.5 rounded overflow-hidden ${
                    a.is_spoof_suspect
                      ? 'bg-yellow-500/25 border border-yellow-400 text-yellow-200 font-bold'
                      : 'bg-slate-900/70'
                  }`}
                >
                  <div
                    className={`absolute left-0 top-0 bottom-0 opacity-25 ${
                      a.is_spoof_suspect ? 'bg-yellow-400' : 'bg-rose-500'
                    }`}
                    style={{ width: `${widthPct}%` }}
                  />
                  <span className="relative z-10 text-rose-400">
                    {a.price.toFixed(detail.price_decimals ?? 4)}
                  </span>
                  <span className="relative z-10 text-slate-200">
                    ${(a.usd_size / 1000).toFixed(0)}K
                    {a.is_spoof_suspect && ' ⚠️'}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* 3. Live Forced Liquidations Stream (!forceOrder@arr) */}
      <div className="flex-1 flex flex-col min-h-0">
        <div className="px-3 py-1.5 border-b border-slate-800/80 flex items-center justify-between bg-[#0b101b]">
          <span className="text-[10px] font-mono font-bold text-slate-300 flex items-center gap-1">
            <Flame className="w-3 h-3 text-amber-400" />
            LIVE FORCED LIQUIDATIONS
          </span>
          <label className="flex items-center gap-1 text-[10px] font-mono text-slate-400 cursor-pointer">
            <input
              type="checkbox"
              checked={filterActiveSymbolOnly}
              onChange={(e) => setFilterActiveSymbolOnly(e.target.checked)}
              className="rounded border-slate-700 bg-slate-900 text-cyan-500"
            />
            <span>{detail.symbol.replace('USDT', '')} only</span>
          </label>
        </div>

        <div className="flex-1 overflow-y-auto p-2.5 space-y-1.5 font-mono text-[11px]">
          {filteredLiqs.slice(0, 16).map((liq) => {
            const isShortLiq = liq.side === 'BUY';
            return (
              <div
                key={liq.id}
                className={`px-2.5 py-1.5 rounded border flex items-center justify-between ${
                  isShortLiq
                    ? 'bg-emerald-950/20 border-emerald-500/30 text-emerald-300'
                    : 'bg-rose-950/20 border-rose-500/30 text-rose-300'
                }`}
              >
                <div className="flex items-center gap-1.5">
                  <Flame className="w-3.5 h-3.5 shrink-0" />
                  <span className="font-bold">{liq.symbol.replace('USDT', '')}</span>
                  <span className="text-[10px] opacity-85">
                    {isShortLiq ? 'SHORT LIQ' : 'LONG LIQ'}
                  </span>
                </div>
                <div className="text-right">
                  <span className="font-bold">${(liq.usd_value / 1000).toFixed(1)}K</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </aside>
  );
};
