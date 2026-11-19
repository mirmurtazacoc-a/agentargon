export interface ScannerCard {
  symbol: string;
  perp_price: number;
  spot_price: number;
  price_decimals: number;
  spot_perp_basis_pct: number;
  funding_rate_pct: number;
  funding_countdown: string;
  oi_delta_15m_pct: number;
  confluence_score: number;
  spoof_risk_score: number;
  spot_cvd_60s: number;
  perp_cvd_60s: number;
  ret_1m_pct: number;
  ret_15m_pct: number;
  change_24h_pct: number;
  quote_volume_24h_usd: number;
  squeeze_type: string;
  signal_state: string;
  // 15-Minute Candle Trade Position Fields
  bias: 'LONG' | 'SHORT' | 'NEUTRAL' | 'KILL_SWITCH';
  entry_price: number;
  hard_sl: number;
  tp1: number;
  tp2: number;
  leverage: number;
  rr_ratio: number;
  liquidation_price: number;
  sl_distance_pct: number;
  tp1_distance_pct: number;
  tp2_distance_pct: number;
  candle_15m_atr_pct: number;
  candle_15m_structure: string;
  win_probability_pct?: number;
}

export interface OrderBookLevel {
  price: number;
  qty: number;
  usd_size: number;
  is_spoof_suspect: boolean;
  wall_delta_pct: number;
}

export interface KlineBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface ChartMarkerItem {
  time: number;
  position: 'aboveBar' | 'belowBar' | 'inBar';
  color: string;
  shape: 'circle' | 'square' | 'arrowUp' | 'arrowDown';
  text: string;
}

export interface AISignalSetup {
  symbol: string;
  bias: 'LONG' | 'SHORT' | 'NEUTRAL' | 'KILL_SWITCH';
  entry_price: number;
  hard_sl: number;
  tp1: number;
  tp2: number;
  leverage: number;
  confidence: number;
  catalyst_badge: string;
  reasoning: string;
  ts: number;
  timeframe: string;
  win_probability_pct: number;
  tp1_hit_prob_pct: number;
  tp2_hit_prob_pct: number;
  expected_value_r: number;
  mtf_alignment_label: string;
  rr_ratio: number;
  recommended_margin_usd: number;
  position_size_usd: number;
  max_loss_usd: number;
  expected_tp1_usd: number;
  expected_tp2_usd: number;
  candle_15m_open: number;
  candle_15m_high: number;
  candle_15m_low: number;
  candle_15m_close: number;
  candle_15m_atr: number;
  candle_15m_atr_pct: number;
  candle_15m_ema9: number;
  candle_15m_ema21: number;
  candle_15m_vwap: number;
  candle_15m_rsi: number;
  candle_15m_swing_high: number;
  candle_15m_swing_low: number;
  candle_15m_structure: string;
  entry_type: string;
  factor_scores?: {
    ema_trend: number;
    vwap_anchor: number;
    rsi_momentum: number;
    funding_squeeze: number;
    oi_orderflow: number;
    l2_orderbook: number;
    net_vector: number;
  };
  liquidation_price: number;
  sl_distance_pct: number;
  tp1_distance_pct: number;
  tp2_distance_pct: number;
  funding_edge_note: string;
  news_edge_note: string;
}

export interface ActiveDetail {
  symbol: string;
  perp_price: number;
  spot_price: number;
  mark_price: number;
  price_decimals: number;
  spot_perp_basis_pct: number;
  funding_rate_pct: number;
  funding_countdown: string;
  open_interest_usd: number;
  oi_delta_15m_pct: number;
  top_trader_ls_ratio: number;
  taker_buy_sell_ratio: number;
  spot_cvd_60s: number;
  perp_cvd_60s: number;
  short_liq_60s_usd: number;
  long_liq_60s_usd: number;
  spoof_risk_score: number;
  last_spoof_event: string;
  confluence_score: number;
  change_24h_pct: number;
  quote_volume_24h_usd: number;
  squeeze_type: string;
  ma_pinch_score: number;
  bids: OrderBookLevel[];
  asks: OrderBookLevel[];
  klines_1m: KlineBar[];
  chart_markers: ChartMarkerItem[];
  ai_setup: AISignalSetup | null;
  setups_by_tf?: Record<'15m' | '1h' | '4h', AISignalSetup>;
}

export interface PaperPosition {
  id: string;
  symbol: string;
  side: 'LONG' | 'SHORT';
  entry_price: number;
  mark_price: number;
  size_usd: number;
  margin_usd: number;
  leverage: number;
  hard_sl: number;
  tp1: number;
  tp2: number;
  opened_at: number;
  time_stop_sec: number;
  is_be_moved: boolean;
  partial_closed: boolean;
  pnl_usd: number;
  pnl_pct: number;
  remaining_sec: number;
  countdown_str: string;
}

export interface LiquidationEvent {
  id: string;
  symbol: string;
  side: 'BUY' | 'SELL';
  price: number;
  qty: number;
  usd_value: number;
  ts: number;
}

export interface NewsHeadline {
  id: string;
  title: string;
  source: string;
  url: string;
  ts: number;
  matched_tickers: string[];
  matched_keywords: string[];
}

export interface AIAlertItem {
  id: string;
  tier: string;
  symbol: string;
  catalyst: string;
  sentiment: string;
  urgency: number;
  action: string;
  summary: string;
  latency_ms: number;
  ts: number;
}

export interface TerminalSnapshot {
  type: string;
  ts: number;
  engine_meta: {
    event_loop: string;
    serializer: string;
    live_feeds_connected: boolean;
    events_processed: number;
    execution_mode: string;
    paper_balance_usd: number;
  };
  btc_anchor: {
    regime: 'GREEN' | 'CAUTION' | 'DUMP_BLOCK';
    ret_1m_pct: number;
    cvd_60s: number;
  };
  kill_switch: {
    active: boolean;
    ticker: string;
    reason: string;
  };
  gemini_stats: {
    tier0_filtered_events: number;
    tier1_triage_calls: number;
    tier2_grounding_calls: number;
    total_input_tokens: number;
    total_cached_tokens: number;
    cache_hit_rate_pct: number;
    estimated_cost_saved_pct: number;
    last_latency_ms: number;
    model_tier1: string;
    model_tier2: string;
  };
  active_symbol: string;
  scanner_ribbon: ScannerCard[];
  active_detail: ActiveDetail;
  active_position: PaperPosition | null;
  all_positions: PaperPosition[];
  liquidations_tape: LiquidationEvent[];
  news_tape: NewsHeadline[];
  ai_alerts_tape: AIAlertItem[];
}
