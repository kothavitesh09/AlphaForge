import { Prediction, Signal, Ticker } from "@/types";

export const CORE_TIMEFRAMES = ["1h", "4h", "1d"] as const;
export type CoreTimeframe = (typeof CORE_TIMEFRAMES)[number];

export type ForecastRow = {
  symbol: string;
  current_price: number;
  forecast_24h?: number;
  forecast_48h?: number;
  forecast_7d?: number;
  confidence: number;
  alpha_score?: number;
  market_regime?: string;
  expected_return?: number;
  rank?: number;
};

export type OpportunityRow = {
  symbol: string;
  prediction?: Prediction;
  predictions: Partial<Record<CoreTimeframe, Prediction>>;
  signal?: Signal;
  ticker?: Ticker;
  forecast?: ForecastRow;
  timeframe: CoreTimeframe;
  score: number;
  currentPrice?: number;
  expectedPrice?: number;
  expectedReturn: number;
  expectedDate?: string;
  confidence: number;
  riskLevel: string;
  trendStrength: number;
  volumeStrength: number;
};

export function buildTerminalOpportunities(input: {
  predictions?: Prediction[] | null;
  signals?: Signal[] | null;
  tickers?: Ticker[] | null;
  forecasts?: ForecastRow[] | null;
}) {
  const latestSignals = new Map<string, Signal>();
  for (const signal of input.signals || []) {
    if (!latestSignals.has(signal.symbol)) latestSignals.set(signal.symbol, signal);
  }
  const tickerMap = new Map((input.tickers || []).map((ticker) => [ticker.symbol, ticker]));
  const forecastMap = new Map((input.forecasts || []).map((forecast) => [forecast.symbol, forecast]));
  const grouped = new Map<string, Partial<Record<CoreTimeframe, Prediction>>>();

  for (const prediction of input.predictions || []) {
    const timeframe = normalizeTimeframe(prediction.timeframe);
    if (!isCoreTimeframe(timeframe)) continue;
    const existing = grouped.get(prediction.symbol) || {};
    const current = existing[timeframe];
    if (!current || timestampValue(prediction.prediction_timestamp || prediction.updated_at || prediction.created_at || prediction.source_timestamp) > timestampValue(current.prediction_timestamp || current.updated_at || current.created_at || current.source_timestamp)) {
      existing[timeframe] = prediction;
      grouped.set(prediction.symbol, existing);
    }
  }

  const symbols = new Set([...grouped.keys(), ...forecastMap.keys()]);
  return Array.from(symbols).flatMap((symbol) => {
    const predictions = grouped.get(symbol) || {};
    const signal = latestSignals.get(symbol);
    const ticker = tickerMap.get(symbol);
    const forecast = forecastMap.get(symbol);
    const candidates = CORE_TIMEFRAMES.map((timeframe) => {
      const prediction = predictions[timeframe];
      return opportunityFrom(symbol, timeframe, prediction, signal, ticker, forecast, predictions);
    }).filter(Boolean) as OpportunityRow[];
    if (candidates.length === 0 && forecast) {
      candidates.push(opportunityFrom(symbol, "1d", undefined, signal, ticker, forecast, predictions) as OpportunityRow);
    }
    if (candidates.length === 0) return [];
    return [candidates.sort((a, b) => b.score - a.score)[0]];
  }).sort((a, b) => b.score - a.score);
}

export function opportunityFrom(
  symbol: string,
  timeframe: CoreTimeframe,
  prediction: Prediction | undefined,
  signal: Signal | undefined,
  ticker: Ticker | undefined,
  forecast: ForecastRow | undefined,
  predictions: Partial<Record<CoreTimeframe, Prediction>>
) {
  const currentPrice = firstNumber(prediction?.current_price, prediction?.source_close, forecast?.current_price, ticker?.last);
  const expectedPrice = expectedPriceFor(timeframe, prediction, forecast, currentPrice);
  const expectedReturn = expectedReturnFor(prediction, currentPrice, expectedPrice, forecast);
  const confidence = firstNumber(prediction?.confidence_score, prediction?.confidence, forecast?.confidence, signal?.confidence, ticker?.confidence) || 0;
  const riskLevel = riskLabel(signal?.risk);
  const trendStrength = Math.abs(firstNumber(ticker?.trend_score, signal?.score, 0) || 0);
  const volumeStrength = firstNumber(ticker?.volume_24h ? 50 : 0, 0) || 0;
  const riskReward = riskRewardScore(signal);
  const score = clamp(
    firstNumber(prediction?.overall_opportunity_score, prediction?.opportunity_score_v2) ??
    Math.abs(expectedReturn) * 12
      + confidence * 0.45
      + riskReward * 0.12
      + Math.min(100, trendStrength) * 0.12
      + Math.min(100, Math.abs(volumeStrength)) * 0.09
      - riskPenalty(riskLevel),
    0,
    100
  );
  if (!prediction && !forecast && !ticker && !signal) return null;
  return {
    symbol,
    prediction,
    predictions,
    signal,
    ticker,
    forecast,
    timeframe,
    score,
    currentPrice,
    expectedPrice,
    expectedReturn,
    expectedDate: prediction?.expected_peak_time || prediction?.target_timestamp || targetDateFor(timeframe),
    confidence,
    riskLevel,
    trendStrength,
    volumeStrength
  };
}

export function confidenceLabel(value?: number) {
  const confidence = Number(value || 0);
  if (confidence >= 90) return "Very High Confidence";
  if (confidence >= 75) return "High Confidence";
  if (confidence >= 60) return "Moderate Confidence";
  return "Speculative";
}

export function normalizeTimeframe(value?: string) {
  return String(value || "1h").toLowerCase();
}

export function isCoreTimeframe(value?: string): value is CoreTimeframe {
  return CORE_TIMEFRAMES.includes(normalizeTimeframe(value) as CoreTimeframe);
}

export function displayTimeframe(value?: string) {
  const timeframe = normalizeTimeframe(value);
  return timeframe === "1h" ? "1H" : timeframe === "4h" ? "4H" : timeframe === "1d" ? "1D" : timeframe.toUpperCase();
}

export function formatDate(value?: string) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" }).format(date);
}

export function signed(value?: number) {
  const number = Number(value || 0);
  return `${number > 0 ? "+" : ""}${number.toFixed(2)}%`;
}

export function firstNumber(...values: unknown[]) {
  for (const value of values) {
    const number = typeof value === "number" ? value : Number(value);
    if (Number.isFinite(number)) return number;
  }
  return undefined;
}

export function riskLabel(value?: string) {
  const risk = String(value || "").replace("_RISK", "").replace("_", " ").toUpperCase();
  if (risk.includes("LOW")) return "Low";
  if (risk.includes("HIGH")) return "High";
  if (risk.includes("MEDIUM")) return "Medium";
  if (risk.includes("NO")) return "No Trade";
  return "Moderate";
}

function expectedPriceFor(timeframe: CoreTimeframe, prediction?: Prediction, forecast?: ForecastRow, currentPrice?: number) {
  const explicit = firstNumber(prediction?.expected_peak_price, prediction?.predicted_price);
  if (explicit) return explicit;
  const forecastPrice = timeframe === "1h" ? forecast?.forecast_24h : timeframe === "4h" ? forecast?.forecast_48h : forecast?.forecast_7d;
  if (typeof forecastPrice === "number") return forecastPrice;
  const change = firstNumber(prediction?.predicted_change_pct, forecast?.expected_return);
  if (typeof currentPrice === "number" && typeof change === "number") return currentPrice * (1 + change / 100);
  return undefined;
}

function expectedReturnFor(prediction?: Prediction, currentPrice?: number, expectedPrice?: number, forecast?: ForecastRow) {
  const explicit = firstNumber(prediction?.expected_peak_return_pct, prediction?.predicted_return_pct, prediction?.predicted_change_pct, forecast?.expected_return);
  if (typeof explicit === "number") return explicit;
  if (typeof currentPrice === "number" && currentPrice > 0 && typeof expectedPrice === "number") return (expectedPrice / currentPrice - 1) * 100;
  return 0;
}

function targetDateFor(timeframe: CoreTimeframe) {
  const date = new Date();
  if (timeframe === "1h") date.setUTCHours(date.getUTCHours() + 1);
  if (timeframe === "4h") date.setUTCHours(date.getUTCHours() + 4);
  if (timeframe === "1d") date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString();
}

function riskRewardScore(signal?: Signal) {
  const raw = String(signal?.risk_reward || signal?.decision?.risk_reward_ratio || "");
  const number = Number(raw.replace("1:", ""));
  return Number.isFinite(number) ? Math.min(100, number * 25) : 50;
}

function riskPenalty(risk: string) {
  if (risk === "High") return 14;
  if (risk === "Medium") return 7;
  return 0;
}

function timestampValue(value?: string) {
  if (!value) return 0;
  const timestamp = new Date(value).getTime();
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}
