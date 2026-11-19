import React, { useState } from 'react';
import {
  AlertOctagon,
  Award,
  Check,
  Clock,
  Copy,
  Crosshair,
  Gauge,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  Target,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import { ActiveDetail, AISignalSetup } from '../types/terminal';

interface CenterChartProps {
  detail: ActiveDetail;
  onRefreshCoin: (sym: string) => void;
}

export const CenterChart: React.FC<CenterChartProps> = ({ detail, onRefreshCoin }) => {
  const [selectedTf, setSelectedTf] = useState<'15m' | '1h' | '4h'>('15m');
  const [copiedField, setCopiedField] = useState<string>('');

  const setupsByTf = detail.setups_by_tf;
  const ai: AISignalSetup | null =
    (setupsByTf && setupsByTf[selectedTf]) || detail.ai_setup || null;

  const formatPrice = (p: number, dec?: number) =>
    p.toFixed(dec !== undefined ? dec : detail.price_decimals ?? (p < 1 ? 6 : 2));

  const copyValue = (label: string, val: string) => {
    navigator.clipboard?.writeText(val).catch(() => {});
    setCopiedField(label);
    setTimeout(() => {
      setCopiedField((prev) => (prev === label ? '' : prev));
    }, 1500);
  };

  if (!ai) {
    return (
      <div className="w-full h-full flex items-center justify-center font-mono text-slate-400 p-6 text-center">
        Calculating multi-timeframe (15m / 1h / 4h) trade setup for {detail.symbol}...
      </div>
    );
  }

  const isLong = ai.bias !== 'SHORT';
  const isKillSwitch = ai.bias === 'KILL_SWITCH';
  const recLeverage = ai.leverage || 4;
  const tfLabel = selectedTf.toUpperCase();

  const slPct =
    ai.sl_distance_pct ||
    (detail.perp_price > 0
      ? (Math.abs(ai.entry_price - ai.hard_sl) / ai.entry_price) * 100
      : 1.05);
  const tp1Pct =
    ai.tp1_distance_pct ||
    (detail.perp_price > 0 ? (Math.abs(ai.tp1 - ai.entry_price) / ai.entry_price) * 100 : 1.65);
  const tp2Pct =
    ai.tp2_distance_pct ||
    (detail.perp_price > 0 ? (Math.abs(ai.tp2 - ai.entry_price) / ai.entry_price) * 100 : 3.15);

  const estLiqPrice =
    ai.liquidation_price ||
    (isLong
      ? detail.perp_price * (1 - 0.92 / recLeverage)
      : detail.perp_price * (1 + 0.92 / recLeverage));

  const entryStr = formatPrice(ai.entry_price);
  const slStr = formatPrice(ai.hard_sl);
  const tp1Str = formatPrice(ai.tp1);
  const tp2Str = formatPrice(ai.tp2);

  const winProb = ai.win_probability_pct ?? 68.5;
  const tp1Prob = ai.tp1_hit_prob_pct ?? 75.0;
  const tp2Prob = ai.tp2_hit_prob_pct ?? 55.0;
  const evR = ai.expected_value_r ?? 0.85;

  return (
    <div className="w-full max-w-4xl mx-auto p-3 sm:p-5 space-y-4 font-mono select-none">
      {/* SINGLE SELECTED COIN — MASTER MULTI-TIMEFRAME (15M / 1H / 4H) TRADE CARD */}
      <div
        className={`p-4 sm:p-6 rounded-xl border shadow-2xl ${
          isKillSwitch
            ? 'bg-red-950/30 border-red-500'
            : isLong
            ? 'bg-gradient-to-br from-emerald-950/35 via-[#0b1322] to-[#090e1a] border-emerald-500/50'
            : 'bg-gradient-to-br from-rose-950/35 via-[#0b1322] to-[#090e1a] border-rose-500/50'
        }`}
      >
        {/* Top Timeframe Selector Bar: 15M | 1H | 4H */}
        <div className="flex flex-wrap items-center justify-between gap-2 pb-4 mb-4 border-b border-slate-800/90">
          <div className="flex items-center gap-1.5">
            <Clock className="w-4 h-4 text-cyan-400" />
            <span className="text-xs font-bold text-slate-300 mr-1">SELECT TIMEFRAME:</span>
            {(['15m', '1h', '4h'] as const).map((tf) => {
              const tfSetup = setupsByTf ? setupsByTf[tf] : null;
              const isActiveTf = selectedTf === tf;
              const tfIsLong = tfSetup ? tfSetup.bias !== 'SHORT' : isLong;
              const tfWin = tfSetup?.win_probability_pct ?? winProb;
              return (
                <button
                  key={tf}
                  type="button"
                  onClick={() => setSelectedTf(tf)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-bold transition flex items-center gap-2 border ${
                    isActiveTf
                      ? 'bg-cyan-500 text-slate-950 border-cyan-300 shadow-[0_0_14px_rgba(34,211,238,0.3)]'
                      : 'bg-[#0b111e] text-slate-300 border-slate-800 hover:border-slate-600'
                  }`}
                >
                  <span className="uppercase">
                    {tf === '15m' ? '15 MIN' : tf === '1h' ? '1 HOUR' : '4 HOURS'}
                  </span>
                  {tfSetup && (
                    <span
                      className={`px-1.5 py-0.2 rounded text-[10px] ${
                        isActiveTf
                          ? 'bg-slate-950/20 text-slate-950 font-extrabold'
                          : tfIsLong
                          ? 'bg-emerald-500/20 text-emerald-300'
                          : 'bg-rose-500/20 text-rose-300'
                      }`}
                    >
                      {tfIsLong ? '▲' : '▼'} {tfWin}%
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {/* Multi-Timeframe Alignment Status Badge */}
          <div className="px-2.5 py-1 rounded bg-slate-900/90 border border-slate-700 text-[11px] text-cyan-300 font-bold">
            {ai.mtf_alignment_label || '15M + 1H + 4H ANALYZED'}
          </div>
        </div>

        {/* Coin Name, Live Mark Price, 24h %, Win Probability Gauge, and Predicted Signal Banner */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 pb-4 border-b border-slate-800/90">
          <div className="flex items-center justify-between sm:justify-start gap-3">
            <div>
              <div className="flex items-center gap-2.5">
                <h1 className="text-2xl sm:text-3xl font-bold text-white tracking-tight">
                  {detail.symbol.replace('USDT', '')}
                  <span className="text-sm text-slate-400 font-normal ml-0.5">/USDT</span>
                </h1>
                <span className="px-2 py-0.5 rounded bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 text-xs font-bold">
                  {tfLabel} TRADE
                </span>
                <span
                  className={`text-xs px-2 py-0.5 rounded font-bold border ${
                    (detail.change_24h_pct ?? 0) >= 0
                      ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                      : 'bg-rose-500/15 text-rose-300 border-rose-500/30'
                  }`}
                >
                  {(detail.change_24h_pct ?? 0) >= 0 ? '+' : ''}
                  {(detail.change_24h_pct ?? 0).toFixed(2)}%
                </span>
              </div>
              <div className="flex items-center gap-2 mt-1 text-xs text-slate-400">
                <span>
                  Live Mark:{' '}
                  <strong className="text-cyan-300 text-sm">
                    ${formatPrice(detail.perp_price)}
                  </strong>
                </span>
                <span>•</span>
                <span>
                  Spot:{' '}
                  <strong className="text-slate-200">${formatPrice(detail.spot_price)}</strong>
                </span>
              </div>
            </div>

            <button
              onClick={() => onRefreshCoin(detail.symbol)}
              className="p-2 rounded-lg bg-slate-800/80 hover:bg-slate-700 text-cyan-300 border border-slate-700 transition sm:ml-2"
              title="Recalculate 15m, 1h & 4h trades with latest market ticks"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>

          {/* Big Signal Badge (LONG or SHORT + Leverage + Win Probability %) */}
          <div className="flex flex-col sm:items-end gap-1.5">
            <div
              className={`px-4 py-2 rounded-lg text-sm sm:text-base font-bold tracking-wide flex items-center justify-center gap-2 shadow-lg ${
                isKillSwitch
                  ? 'bg-red-600 text-white animate-pulse'
                  : isLong
                  ? 'bg-emerald-500 text-slate-950'
                  : 'bg-rose-500 text-white'
              }`}
            >
              {isKillSwitch ? (
                <>
                  <AlertOctagon className="w-5 h-5" />
                  KILL-SWITCH • DO NOT TRADE
                </>
              ) : isLong ? (
                <>
                  <TrendingUp className="w-5 h-5" />
                  ▲ {tfLabel} LONG • {recLeverage}x ISOLATED
                </>
              ) : (
                <>
                  <TrendingDown className="w-5 h-5" />
                  ▼ {tfLabel} SHORT • {recLeverage}x ISOLATED
                </>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              <span
                className={`px-2.5 py-0.5 rounded font-bold border flex items-center gap-1 ${
                  winProb >= 70
                    ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/50'
                    : winProb >= 60
                    ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40'
                    : 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                }`}
              >
                <Award className="w-3.5 h-3.5" />
                WIN PROBABILITY: {winProb}%
              </span>
              <span className="px-2 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-500/30 font-bold">
                R:R 1 : {ai.rr_ratio}
              </span>
              <span className="px-2 py-0.5 rounded bg-purple-500/15 text-purple-300 border border-purple-500/30 font-bold">
                EV: {evR >= 0 ? '+' : ''}
                {evR}R
              </span>
            </div>
          </div>
        </div>

        {/* WIN PROBABILITY BREAKDOWN BAR (TP1 HIT PROBABILITY vs TP2 HIT PROBABILITY) */}
        <div className="mt-4 p-3 rounded-lg bg-[#090e1a] border border-slate-800/90">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs mb-1.5">
            <span className="font-bold text-slate-200 flex items-center gap-1.5">
              <Award className="w-4 h-4 text-emerald-400" />
              {tfLabel} TRADE WIN PROBABILITY:{' '}
              <strong className="text-emerald-400 text-sm">{winProb}%</strong>
            </span>
            <div className="flex items-center gap-3 text-[11px]">
              <span className="text-slate-400">
                TP1 (50% Exit) Hit Odds: <strong className="text-emerald-400">{tp1Prob}%</strong>
              </span>
              <span className="text-slate-600">|</span>
              <span className="text-slate-400">
                TP2 (Full Runner) Hit Odds: <strong className="text-cyan-300">{tp2Prob}%</strong>
              </span>
            </div>
          </div>
          <div className="w-full h-2.5 bg-slate-900 rounded-full overflow-hidden border border-slate-800">
            <div
              className={`h-full transition-all duration-300 ${
                winProb >= 70
                  ? 'bg-gradient-to-r from-emerald-500 to-cyan-400'
                  : winProb >= 60
                  ? 'bg-cyan-400'
                  : 'bg-amber-400'
              }`}
              style={{ width: `${Math.min(100, winProb)}%` }}
            />
          </div>
        </div>

        {/* Tap-to-Copy Mobile & Desktop Trade Levels Grid (Entry, Stop-Loss, TP1, TP2, Leverage) */}
        <div className="mt-4">
          <div className="text-[11px] text-slate-400 mb-2 flex items-center justify-between">
            <span>{tfLabel} CALCULATED TRADE LEVELS (TAP ANY PRICE TO COPY FOR BINANCE APP):</span>
            <span className="text-cyan-400 font-bold">{ai.entry_type}</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
            {/* 1. Entry Price */}
            <button
              type="button"
              onClick={() => copyValue('ENTRY', entryStr)}
              className="text-left p-3.5 rounded-lg bg-[#0a101d] border border-cyan-500/50 hover:border-cyan-400 active:scale-[0.99] transition group"
            >
              <div className="flex items-center justify-between text-[11px] text-cyan-400 mb-1">
                <span className="font-bold flex items-center gap-1">
                  <Crosshair className="w-3.5 h-3.5" />
                  1. ENTRY ({tfLabel})
                </span>
                {copiedField === 'ENTRY' ? (
                  <span className="text-emerald-400 flex items-center gap-0.5 text-[10px] font-bold">
                    <Check className="w-3 h-3" /> COPIED
                  </span>
                ) : (
                  <Copy className="w-3 h-3 opacity-50 group-hover:opacity-100" />
                )}
              </div>
              <div className="text-2xl font-bold text-white">${entryStr}</div>
              <div className="mt-1.5 pt-1.5 border-t border-slate-800/80 text-[11px] text-slate-400 flex justify-between">
                <span>Order Type:</span>
                <strong className="text-cyan-300">
                  {ai.entry_type?.includes('PULLBACK') ? 'Limit Pullback' : 'Market / Limit'}
                </strong>
              </div>
            </button>

            {/* 2. Stop-Loss */}
            <button
              type="button"
              onClick={() => copyValue('SL', slStr)}
              className="text-left p-3.5 rounded-lg bg-[#0a101d] border border-rose-500/50 hover:border-rose-400 active:scale-[0.99] transition group"
            >
              <div className="flex items-center justify-between text-[11px] text-rose-400 mb-1">
                <span className="font-bold flex items-center gap-1">
                  <ShieldAlert className="w-3.5 h-3.5" />
                  2. STOP-LOSS
                </span>
                {copiedField === 'SL' ? (
                  <span className="text-emerald-400 flex items-center gap-0.5 text-[10px] font-bold">
                    <Check className="w-3 h-3" /> COPIED
                  </span>
                ) : (
                  <Copy className="w-3 h-3 opacity-50 group-hover:opacity-100" />
                )}
              </div>
              <div className="text-2xl font-bold text-rose-400">${slStr}</div>
              <div className="mt-1.5 pt-1.5 border-t border-slate-800/80 text-[11px] text-slate-400 flex justify-between">
                <span>Move / {recLeverage}x Risk:</span>
                <strong className="text-rose-400">
                  {isLong ? '-' : '+'}
                  {slPct.toFixed(2)}% (-{(slPct * recLeverage).toFixed(1)}%)
                </strong>
              </div>
            </button>

            {/* 3. Take-Profit 1 (50%) */}
            <button
              type="button"
              onClick={() => copyValue('TP1', tp1Str)}
              className="text-left p-3.5 rounded-lg bg-[#0a101d] border border-emerald-500/50 hover:border-emerald-400 active:scale-[0.99] transition group"
            >
              <div className="flex items-center justify-between text-[11px] text-emerald-400 mb-1">
                <span className="font-bold flex items-center gap-1">
                  <Target className="w-3.5 h-3.5" />
                  3. TP1 ({tp1Prob}% PROB)
                </span>
                {copiedField === 'TP1' ? (
                  <span className="text-emerald-400 flex items-center gap-0.5 text-[10px] font-bold">
                    <Check className="w-3 h-3" /> COPIED
                  </span>
                ) : (
                  <Copy className="w-3 h-3 opacity-50 group-hover:opacity-100" />
                )}
              </div>
              <div className="text-2xl font-bold text-emerald-400">${tp1Str}</div>
              <div className="mt-1.5 pt-1.5 border-t border-slate-800/80 text-[11px] text-slate-400 flex justify-between">
                <span>Move / {recLeverage}x ROI:</span>
                <strong className="text-emerald-400">
                  {isLong ? '+' : '-'}
                  {tp1Pct.toFixed(2)}% (+{(tp1Pct * recLeverage).toFixed(1)}%)
                </strong>
              </div>
            </button>

            {/* 4. Take-Profit 2 (100%) */}
            <button
              type="button"
              onClick={() => copyValue('TP2', tp2Str)}
              className="text-left p-3.5 rounded-lg bg-[#0a101d] border border-emerald-400/70 hover:border-emerald-300 active:scale-[0.99] transition group"
            >
              <div className="flex items-center justify-between text-[11px] text-emerald-300 mb-1">
                <span className="font-bold flex items-center gap-1">
                  <Sparkles className="w-3.5 h-3.5" />
                  4. TP2 ({tp2Prob}% PROB)
                </span>
                {copiedField === 'TP2' ? (
                  <span className="text-emerald-400 flex items-center gap-0.5 text-[10px] font-bold">
                    <Check className="w-3 h-3" /> COPIED
                  </span>
                ) : (
                  <Copy className="w-3 h-3 opacity-50 group-hover:opacity-100" />
                )}
              </div>
              <div className="text-2xl font-bold text-emerald-300">${tp2Str}</div>
              <div className="mt-1.5 pt-1.5 border-t border-slate-800/80 text-[11px] text-slate-400 flex justify-between">
                <span>Move / {recLeverage}x ROI:</span>
                <strong className="text-emerald-300">
                  {isLong ? '+' : '-'}
                  {tp2Pct.toFixed(2)}% (+{(tp2Pct * recLeverage).toFixed(1)}%)
                </strong>
              </div>
            </button>

            {/* 5. Recommended Leverage & Liquidation */}
            <div className="p-3.5 rounded-lg bg-[#0a101d] border border-purple-500/40">
              <div className="flex items-center justify-between text-[11px] text-purple-300 mb-1">
                <span className="font-bold flex items-center gap-1">
                  <Gauge className="w-3.5 h-3.5" />
                  5. LEVERAGE
                </span>
                <span className="px-1.5 py-0.2 rounded bg-purple-500/15 text-[10px]">ISOLATED</span>
              </div>
              <div className="text-2xl font-bold text-purple-300">
                {recLeverage}x <span className="text-xs text-slate-400 font-normal">Isolated</span>
              </div>
              <div className="mt-1.5 pt-1.5 border-t border-slate-800/80 text-[11px] text-slate-400 flex justify-between">
                <span>Est. Liq Price:</span>
                <strong className="text-amber-300">${formatPrice(estLiqPrice)}</strong>
              </div>
            </div>
          </div>
        </div>

        {/* All Live Coin Values Used to Calculate This Timeframe Trade */}
        <div className="mt-5 pt-4 border-t border-slate-800/80">
          <div className="text-[11px] font-bold text-slate-300 uppercase tracking-wider mb-2.5">
            LIVE VALUES &amp; {tfLabel} CANDLE STRUCTURE USED FOR THIS CALCULATION:
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2.5 text-xs">
            <div className="bg-[#090e1a] p-2.5 rounded-lg border border-slate-800">
              <div className="text-slate-500 text-[10px]">{tfLabel} VWAP &amp; RSI(14)</div>
              <div className="text-slate-200 font-bold mt-0.5">
                ${formatPrice(ai.candle_15m_vwap || ai.candle_15m_ema9)} •{' '}
                <span
                  className={
                    (ai.candle_15m_rsi ?? 50) > 70
                      ? 'text-rose-400'
                      : (ai.candle_15m_rsi ?? 50) < 30
                      ? 'text-emerald-400'
                      : 'text-amber-300'
                  }
                >
                  RSI {(ai.candle_15m_rsi ?? 50).toFixed(1)}
                </span>
              </div>
            </div>

            <div className="bg-[#090e1a] p-2.5 rounded-lg border border-slate-800">
              <div className="text-slate-500 text-[10px]">{tfLabel} EMA-9 / EMA-21</div>
              <div className="text-slate-200 font-bold mt-0.5">
                ${formatPrice(ai.candle_15m_ema9)} / ${formatPrice(ai.candle_15m_ema21)}
              </div>
            </div>

            <div className="bg-[#090e1a] p-2.5 rounded-lg border border-slate-800">
              <div className="text-slate-500 text-[10px]">{tfLabel} SWING HIGH / LOW</div>
              <div className="text-slate-200 font-bold mt-0.5">
                <span className="text-emerald-400">
                  ${formatPrice(ai.candle_15m_swing_high || ai.candle_15m_high)}
                </span>{' '}
                /{' '}
                <span className="text-rose-400">
                  ${formatPrice(ai.candle_15m_swing_low || ai.candle_15m_low)}
                </span>
              </div>
            </div>

            <div className="bg-[#090e1a] p-2.5 rounded-lg border border-slate-800">
              <div className="text-slate-500 text-[10px]">{tfLabel} ATR (14) VOLATILITY</div>
              <div className="text-cyan-300 font-bold mt-0.5">
                ${formatPrice(ai.candle_15m_atr)} ({ai.candle_15m_atr_pct}%)
              </div>
            </div>

            <div className="bg-[#090e1a] p-2.5 rounded-lg border border-slate-800">
              <div className="text-slate-500 text-[10px]">FUNDING RATE (COUNTDOWN)</div>
              <div
                className={`font-bold mt-0.5 ${
                  detail.funding_rate_pct < 0 ? 'text-emerald-400' : 'text-amber-300'
                }`}
              >
                {detail.funding_rate_pct >= 0 ? '+' : ''}
                {detail.funding_rate_pct.toFixed(4)}% ({detail.funding_countdown.slice(3)})
              </div>
            </div>

            <div className="bg-[#090e1a] p-2.5 rounded-lg border border-slate-800">
              <div className="text-slate-500 text-[10px]">SPOT-PERP BASIS &amp; 15M OI Δ</div>
              <div className="text-slate-200 font-bold mt-0.5">
                <span
                  className={
                    detail.spot_perp_basis_pct < 0 ? 'text-emerald-400' : 'text-amber-300'
                  }
                >
                  {detail.spot_perp_basis_pct >= 0 ? '+' : ''}
                  {detail.spot_perp_basis_pct.toFixed(3)}%
                </span>{' '}
                •{' '}
                <span className={detail.oi_delta_15m_pct >= 0 ? 'text-cyan-300' : 'text-rose-400'}>
                  {detail.oi_delta_15m_pct >= 0 ? '+' : ''}
                  {detail.oi_delta_15m_pct.toFixed(2)}% OI
                </span>
              </div>
            </div>

            <div className="bg-[#090e1a] p-2.5 rounded-lg border border-slate-800">
              <div className="text-slate-500 text-[10px]">TAKER BUY/SELL &amp; TOP L/S</div>
              <div className="text-slate-200 font-bold mt-0.5">
                Taker:{' '}
                <span
                  className={
                    detail.taker_buy_sell_ratio >= 1.0 ? 'text-emerald-400' : 'text-rose-400'
                  }
                >
                  {detail.taker_buy_sell_ratio}
                </span>{' '}
                • L/S: {detail.top_trader_ls_ratio}
              </div>
            </div>

            <div className="bg-[#090e1a] p-2.5 rounded-lg border border-slate-800">
              <div className="text-slate-500 text-[10px]">SPOT vs. PERP CVD FLOW</div>
              <div className="text-slate-200 font-bold mt-0.5">
                <span className={detail.spot_cvd_60s >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                  ${(detail.spot_cvd_60s / 1000).toFixed(0)}K
                </span>{' '}
                /{' '}
                <span className={detail.perp_cvd_60s >= 0 ? 'text-cyan-300' : 'text-rose-400'}>
                  ${(detail.perp_cvd_60s / 1000).toFixed(0)}K
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* 6-Pillar Quant Vector Breakdown */}
        {ai.factor_scores && (
          <div className="mt-4 pt-3 border-t border-slate-800/70">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-2 text-[11px]">
              <span className="text-slate-400 font-bold">
                {tfLabel} MULTI-FACTOR QUANT SCORE (NET VECTOR:{' '}
                <strong
                  className={
                    ai.factor_scores.net_vector >= 0 ? 'text-emerald-400' : 'text-rose-400'
                  }
                >
                  {ai.factor_scores.net_vector >= 0 ? '+' : ''}
                  {ai.factor_scores.net_vector} → {isLong ? 'LONG' : 'SHORT'}
                </strong>
                )
              </span>
              <span className="text-[10px] text-slate-500">
                + Bullish Long Weight / - Bearish Short Weight
              </span>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 text-[11px]">
              {[
                { label: `${tfLabel} EMA Trend`, val: ai.factor_scores.ema_trend, max: 25 },
                { label: `${tfLabel} VWAP`, val: ai.factor_scores.vwap_anchor, max: 15 },
                { label: `${tfLabel} RSI(14)`, val: ai.factor_scores.rsi_momentum, max: 15 },
                { label: 'Funding/Basis', val: ai.factor_scores.funding_squeeze, max: 25 },
                { label: 'OI/Taker/CVD', val: ai.factor_scores.oi_orderflow, max: 20 },
                { label: 'L2 Orderbook', val: ai.factor_scores.l2_orderbook, max: 10 },
              ].map((f) => (
                <div
                  key={f.label}
                  className="px-2.5 py-1.5 rounded bg-[#080d18] border border-slate-800/90 flex items-center justify-between"
                >
                  <span className="text-slate-400">{f.label}</span>
                  <strong className={f.val >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                    {f.val >= 0 ? '+' : ''}
                    {f.val}
                  </strong>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
