"use client";
import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronUp, TrendingDown, TrendingUp } from "lucide-react";
import { Shell } from "@/components/Shell";
import { ErrorState, LoadingGrid } from "@/components/State";
import { EmptyState, Panel, SectionTitle, StatusLine, formatInr, normalizeSignal, riskLabel, tickerMap } from "@/components/trading-ui";
import { useApi } from "@/hooks/useApi";
import { API, api } from "@/services/api";
import { Prediction, Signal, Ticker } from "@/types";

const TIMEFRAMES = ["15m", "1h", "4h", "1d"];
const NOT_AVAILABLE = "Not Available";

type Opportunity = {
  symbol: string;
  signal?: Signal;
  predictions: Record<string, Prediction>;
  bestTimeframe: string;
  best: Prediction;
  score: number;
  expectedReturn: number;
  confidence: number;
};

export default function SignalsPage() {
  const { data: predictions, loading: predictionsLoading, error: predictionsError } = useApi<Prediction[]>(API.predictions);
  const { data: signals, loading: signalsLoading, error: signalsError } = useApi<Signal[]>(API.signals);
  const { data: tickers } = useApi<Ticker[]>(API.markets);
  const [message, setMessage] = useState("");
  const prices = tickerMap(tickers);

  const opportunities = useMemo(() => {
    return buildOpportunities(predictions || [], signals || [], prices);
  }, [predictions, signals, prices]);

  async function takeTrade(signal?: Signal) {
    if (!signal?.id) {
      setMessage("No executable signal available for this opportunity");
      return;
    }
    setMessage("");
    try {
      await api(API.executeSignal, { method: "POST", body: JSON.stringify({ signal_id: signal.id, risk_fraction: 0.1 }) });
      setMessage(`${signal.symbol} trade plan executed`);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Trade failed");
    }
  }

  const loading = predictionsLoading || signalsLoading;
  const error = predictionsError || signalsError;

  return (
    <Shell>
      <div className="mb-6 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-primary">Trade Plans</div>
          <h1 className="mt-1 text-[32px] font-semibold tracking-tight">Highest expected opportunities</h1>
        </div>
        {message && <div className="rounded-lg border border-line bg-panel px-3 py-2 text-sm text-slate-300">{message}</div>}
      </div>

      {loading && <LoadingGrid />}
      {error && <ErrorState message={error} />}
      {!loading && !error && opportunities.length === 0 && <EmptyState label="No timeframe predictions returned by the backend" />}

      <div className="grid gap-4 xl:grid-cols-2">
        {opportunities.map((opportunity) => (
          <OpportunityCard key={opportunity.symbol} opportunity={opportunity} onTakeTrade={takeTrade} />
        ))}
      </div>
    </Shell>
  );
}

function OpportunityCard({ opportunity, onTakeTrade }: { opportunity: Opportunity; onTakeTrade: (signal?: Signal) => void }) {
  const [selectedTimeframe, setSelectedTimeframe] = useState(opportunity.bestTimeframe);
  const [expanded, setExpanded] = useState(false);
  const selected = opportunity.predictions[selectedTimeframe] || opportunity.predictions[opportunity.bestTimeframe] || opportunity.best;
  const selectedScore = opportunityScore(selected, opportunity.signal);
  const direction = directionLabel(selected);
  const DirectionIcon = direction === "BEARISH" ? TrendingDown : TrendingUp;
  const isBestSelected = selectedTimeframe === opportunity.bestTimeframe;

  useEffect(() => {
    if (opportunity.predictions[selectedTimeframe]) return;
    const fallback = opportunity.bestTimeframe || Object.keys(opportunity.predictions)[0] || "1h";
    setSelectedTimeframe(fallback);
  }, [opportunity.bestTimeframe, opportunity.predictions, selectedTimeframe]);

  useEffect(() => {
    console.log("[TradePlans] selected timeframe", {
      symbol: opportunity.symbol,
      selectedTimeframe,
      availableTimeframes: Object.keys(opportunity.predictions),
      predictionTimeframe: selected?.timeframe,
      predicted_price: selected?.predicted_price,
      predicted_change_pct: selected?.predicted_change_pct,
      target_timestamp: selected?.target_timestamp,
      confidence: selected?.confidence,
      entry_zone: selected?.entry_zone,
      stop_loss: selected?.stop_loss,
      targets: selected?.targets,
      reasoning: selected?.reasoning
    });
  }, [opportunity.symbol, opportunity.predictions, selected, selectedTimeframe]);

  function selectTimeframe(timeframe: string) {
    const normalized = normalizeTimeframe(timeframe);
    const row = opportunity.predictions[normalized];
    console.log("[TradePlans] tab click", {
      symbol: opportunity.symbol,
      requestedTimeframe: timeframe,
      selectedTimeframe: normalized,
      found: Boolean(row)
    });
    if (row) setSelectedTimeframe(normalized);
  }

  return (
    <Panel className="overflow-hidden transition hover:border-slate-600 hover:bg-cardHover">
      <div className="border-b border-line bg-ink/30 p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight">{formatSymbol(opportunity.symbol)}</h2>
            <div className={`mt-2 inline-flex items-center gap-1 text-sm font-semibold ${directionTone(selected)}`}>
              <DirectionIcon size={16} />
              {direction} {direction === "BEARISH" ? "↓" : "↑"}
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-muted">Opportunity Score</div>
            <div className="text-3xl font-semibold text-primary">{formatScore(selectedScore)}</div>
            <div className="mt-1 text-xs text-muted">Confidence: <span className="font-semibold text-slate-100">{formatPercent(selected.confidence)}</span></div>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <PriorityMetric label="Expected Profit" value={formatSignedPercent(predictedChange(selected))} tone={returnTone(selected)} />
          <PriorityMetric label="Expected Price" value={formatPrice(predictedPrice(selected))} />
          <PriorityMetric label="Expected Time" value={formatDateTime(targetTimestamp(selected))} />
          <PriorityMetric label="Best Timeframe" value={displayTimeframe(opportunity.bestTimeframe)} badge={isBestSelected ? "BEST OPPORTUNITY" : undefined} />
        </div>
      </div>

      <div className="p-4">
        <div className="mb-4 flex flex-wrap gap-2">
          {TIMEFRAMES.map((timeframe) => {
            const row = opportunity.predictions[timeframe];
            const selectedTab = selectedTimeframe === timeframe;
            const bestTab = opportunity.bestTimeframe === timeframe;
            return (
              <button
                key={timeframe}
                onClick={() => selectTimeframe(timeframe)}
                disabled={!row}
                className={`rounded-md border px-3 py-2 text-xs font-semibold transition duration-200 ${
                  selectedTab ? "border-primary bg-primary/15 text-primary" : "border-line bg-ink/40 text-muted hover:border-slate-600 hover:text-white"
                } ${!row ? "cursor-not-allowed opacity-40" : ""}`}
              >
                {displayTimeframe(timeframe)}
                {bestTab && <span className="ml-2 rounded bg-buy/15 px-1.5 py-0.5 text-[10px] text-buy">BEST</span>}
              </button>
            );
          })}
        </div>

        <div className="grid gap-3 transition duration-200 md:grid-cols-3">
          <PlanMetric label="Current Price" value={formatPrice(currentPrice(selected))} />
          <PlanMetric label="Expected Price" value={formatPrice(predictedPrice(selected))} tone={returnTone(selected)} />
          <PlanMetric label="Expected Gain/Loss" value={formatSignedPercent(predictedChange(selected))} tone={returnTone(selected)} />
          <PlanMetric label="Timeframe" value={displayTimeframe(selectedTimeframe)} />
          <PlanMetric label="Expected By" value={formatDateTime(targetTimestamp(selected))} />
          <PlanMetric label="Confidence" value={formatPercent(selected.confidence)} />
        </div>

        <button
          onClick={() => setExpanded((value) => !value)}
          className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg border border-line px-4 py-2 text-sm font-semibold text-slate-100 transition hover:bg-white/5"
        >
          {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          {expanded ? "Hide Details" : "Expand Details"}
        </button>

        {expanded && <OpportunityDetails prediction={selected} signal={opportunity.signal} onTakeTrade={() => onTakeTrade(opportunity.signal)} />}
      </div>
    </Panel>
  );
}

function PriorityMetric({ label, value, tone = "", badge }: { label: string; value: React.ReactNode; tone?: string; badge?: string }) {
  return (
    <div className="min-h-[92px] rounded-lg border border-line bg-panel/80 p-3">
      <div className="text-xs text-muted">{label}</div>
      <div className={`mt-2 text-lg font-semibold leading-tight ${tone}`}>{value}</div>
      {badge && <div className="mt-2 inline-flex rounded bg-buy/15 px-2 py-1 text-[10px] font-semibold text-buy">{badge}</div>}
    </div>
  );
}

function PlanMetric({ label, value, tone = "" }: { label: string; value: React.ReactNode; tone?: string }) {
  return (
    <div className="rounded-lg border border-line bg-ink/40 p-3">
      <div className="text-xs text-muted">{label}</div>
      <div className={`mt-1 text-sm font-semibold ${tone}`}>{value}</div>
    </div>
  );
}

function OpportunityDetails({ prediction, signal, onTakeTrade }: { prediction: Prediction; signal?: Signal; onTakeTrade: () => void }) {
  const targets = targetLevels(prediction, signal);
  const executable = normalizeSignal(signal?.signal) === "BUY" || normalizeSignal(signal?.signal) === "SELL";
  return (
    <div className="mt-4 grid gap-4 border-t border-line pt-4 lg:grid-cols-2">
      <Panel className="p-4">
        <SectionTitle title="Execution Details" />
        <StatusLine label="Entry Zone" value={entryZone(prediction, signal)} />
        <StatusLine label="Stop Loss" value={formatPrice(firstNumber(prediction.stop_loss, signal?.stop_loss, signal?.decision?.stop_loss))} />
        <StatusLine label="Target 1" value={formatPrice(targets[0])} />
        <StatusLine label="Target 2" value={formatPrice(targets[1])} />
        <StatusLine label="Target 3" value={formatPrice(targets[2])} />
        <StatusLine label="Risk/Reward" value={prediction.risk_reward_ratio || signal?.risk_reward || signal?.decision?.risk_reward_ratio || NOT_AVAILABLE} />
        {executable && <button onClick={onTakeTrade} className="mt-4 w-full rounded-lg bg-buy px-4 py-3 text-sm font-semibold text-ink">Take Trade</button>}
      </Panel>

      <Panel className="p-4">
        <SectionTitle title="Strategy" />
        <StatusLine label="Exit Strategy" value={prediction.exit_strategy || exitStrategy(targets)} />
        <StatusLine label="Re-entry Strategy" value={prediction.reentry_strategy || reentryStrategy(signal)} />
        <StatusLine label="Risk" value={signal ? riskLabel(signal.risk) : NOT_AVAILABLE} />
        <StatusLine label="Validation" value={formatPercent(prediction.validation_accuracy)} />
      </Panel>

      <Panel className="p-4 lg:col-span-2">
        <SectionTitle title="AI Reasoning" />
        <div className="grid gap-2 md:grid-cols-2">
          {reasoningRows(prediction, signal).map((row) => (
            <div key={row.label} className="rounded-lg border border-line bg-ink/40 p-3">
              <div className="text-xs text-muted">{row.label}</div>
              <div className="mt-1 text-sm font-medium text-slate-100">{row.value}</div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}

function buildOpportunities(predictions: Prediction[], signals: Signal[], prices: Map<string, Ticker>): Opportunity[] {
  const latestSignal = new Map<string, Signal>();
  for (const signal of signals) {
    if (!latestSignal.has(signal.symbol)) latestSignal.set(signal.symbol, signal);
  }

  const grouped = new Map<string, Record<string, Prediction>>();
  for (const prediction of predictions) {
    const timeframe = normalizeTimeframe(prediction.timeframe);
    if (!isSupportedTimeframe(timeframe)) continue;
    const normalizedPrediction = { ...prediction, timeframe };
    const existing = grouped.get(prediction.symbol) || {};
    const current = existing[timeframe];
    if (!current || timestampValue(normalizedPrediction.updated_at || normalizedPrediction.created_at || normalizedPrediction.source_timestamp) > timestampValue(current.updated_at || current.created_at || current.source_timestamp)) {
      existing[timeframe] = withTickerPrice(normalizedPrediction, prices.get(prediction.symbol)?.last);
      grouped.set(prediction.symbol, existing);
    }
  }

  return Array.from(grouped.entries()).flatMap(([symbol, rows]) => {
    const signal = latestSignal.get(symbol);
    const scoped = Object.values(rows);
    if (scoped.length === 0) return [];
    const best = [...scoped].sort((a, b) => sortPredictions(a, b, signal))[0];
    return [{
      symbol,
      signal,
      predictions: rows,
      bestTimeframe: normalizeTimeframe(best.timeframe),
      best,
      score: opportunityScore(best, signal),
      expectedReturn: Math.abs(predictedChange(best) || 0),
      confidence: Number(best.confidence || 0)
    }];
  }).sort((a, b) => b.score - a.score || b.expectedReturn - a.expectedReturn || b.confidence - a.confidence);
}

function withTickerPrice(prediction: Prediction, tickerPrice?: number): Prediction {
  if (prediction.current_price || prediction.source_close || typeof tickerPrice !== "number") return prediction;
  return { ...prediction, current_price: tickerPrice };
}

function sortPredictions(a: Prediction, b: Prediction, signal?: Signal) {
  return opportunityScore(b, signal) - opportunityScore(a, signal)
    || Math.abs(predictedChange(b) || 0) - Math.abs(predictedChange(a) || 0)
    || Number(b.confidence || 0) - Number(a.confidence || 0);
}

function opportunityScore(prediction: Prediction, signal?: Signal) {
  const backendScore = firstNumber(prediction.opportunity_score);
  const confidence = Number(prediction.confidence || 0);
  const change = Math.abs(predictedChange(prediction) || 0);
  const base = typeof backendScore === "number" ? backendScore : change * 12 + confidence * 0.55;
  const riskPenalty = signal ? { LOW: 0, MEDIUM: 6, HIGH: 14, MODERATE: 8 }[riskLabel(signal.risk)] || 8 : 0;
  return clamp(base - riskPenalty, 0, 100);
}

function directionLabel(prediction: Prediction) {
  const direction = String(prediction.direction || "").toUpperCase();
  if (direction === "DOWN" || direction === "SELL" || (predictedChange(prediction) || 0) < 0) return "BEARISH";
  return "BULLISH";
}

function directionTone(prediction: Prediction) {
  return directionLabel(prediction) === "BEARISH" ? "text-sell" : "text-buy";
}

function returnTone(prediction: Prediction) {
  const change = predictedChange(prediction);
  if (typeof change !== "number") return "";
  return change < 0 ? "text-sell" : "text-buy";
}

function currentPrice(prediction: Prediction) {
  return firstNumber(prediction.current_price, prediction.source_close);
}

function predictedPrice(prediction: Prediction) {
  const explicit = firstNumber(prediction.predicted_price);
  if (typeof explicit === "number") return explicit;
  const current = currentPrice(prediction);
  const change = predictedChange(prediction);
  if (typeof current === "number" && typeof change === "number") return current * (1 + change / 100);
  return undefined;
}

function predictedChange(prediction: Prediction) {
  const explicit = firstNumber(prediction.predicted_change_pct);
  if (typeof explicit === "number") return explicit;
  const current = currentPrice(prediction);
  const target = firstNumber(prediction.predicted_price);
  if (typeof current === "number" && current > 0 && typeof target === "number") return ((target / current) - 1) * 100;
  return undefined;
}

function targetTimestamp(prediction: Prediction) {
  return prediction.target_timestamp || "";
}

function targetLevels(prediction: Prediction, signal?: Signal) {
  const explicit = Array.isArray(prediction.targets) ? prediction.targets.filter((value) => typeof value === "number") : [];
  return [
    explicit[0] ?? firstNumber(prediction.take_profit_1, signal?.target, signal?.decision?.take_profit_1, prediction.predicted_price),
    explicit[1] ?? firstNumber(prediction.take_profit_2, signal?.decision?.take_profit_2),
    explicit[2] ?? firstNumber(prediction.take_profit_3, signal?.decision?.take_profit_3)
  ];
}

function entryZone(prediction: Prediction, signal?: Signal) {
  const zone = zoneValue(prediction.entry_zone) || zoneValue(signal?.entry_zone);
  if (zone) return zone;
  const entry = firstNumber(signal?.entry, signal?.decision?.entry_price, prediction.current_price, prediction.source_close);
  return formatPrice(entry);
}

function exitStrategy(targets: Array<number | undefined>) {
  if (!targets.some((target) => typeof target === "number")) return NOT_AVAILABLE;
  return "TP1 sell 30%, TP2 sell 30%, TP3 sell remaining 40%";
}

function reentryStrategy(signal?: Signal) {
  const zone = zoneValue(signal?.re_entry_zone);
  if (!zone && !signal?.re_entry_window) return NOT_AVAILABLE;
  return [zone, signal?.re_entry_window].filter(Boolean).join(" | ");
}

function reasoningRows(prediction: Prediction, signal?: Signal) {
  const probabilities = prediction.probabilities || {};
  const confidenceDrivers = Object.entries(probabilities)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .map(([key, value]) => `${key.toUpperCase()} ${formatPercent(Number(value))}`)
    .slice(0, 3)
    .join(" / ");
  const signalReasons = (signal?.explanation || []).slice(0, 2).join(" ");
  const modelReasoning = (prediction.reasoning || []).filter(Boolean).slice(0, 2).join(" ");
  return [
    { label: "Trend Direction", value: `${directionLabel(prediction)} on ${displayTimeframe(prediction.timeframe)} timeframe` },
    { label: "Momentum", value: formatSignedPercent(predictedChange(prediction)) },
    { label: "Model Reasoning", value: modelReasoning || "Model reasoning not available for this timeframe" },
    { label: "Volume Analysis", value: signalReasons || "Volume detail not available in this prediction" },
    { label: "Market Structure", value: prediction.expected_move ? `Model range ${prediction.expected_move}` : "Market structure detail not available" },
    { label: "Confidence Drivers", value: confidenceDrivers || `Model confidence ${formatPercent(prediction.confidence)}` }
  ];
}

function zoneValue(value: unknown) {
  if (typeof value === "string" && value.trim()) return value;
  if (Array.isArray(value) && value.length >= 2) {
    const low = firstNumber(value[0]);
    const high = firstNumber(value[1]);
    if (typeof low === "number" && typeof high === "number") return `${formatPrice(low)} - ${formatPrice(high)}`;
  }
  if (!value || typeof value !== "object") return undefined;
  const record = value as Record<string, unknown>;
  const low = firstNumber(record.low, record.min, record.from);
  const high = firstNumber(record.high, record.max, record.to);
  if (typeof low === "number" && typeof high === "number") return `${formatPrice(low)} - ${formatPrice(high)}`;
  return undefined;
}

function firstNumber(...values: unknown[]) {
  for (const value of values) {
    const number = typeof value === "number" ? value : Number(value);
    if (Number.isFinite(number)) return number;
  }
  return undefined;
}

function formatSymbol(symbol: string) {
  return symbol.replace("_", "");
}

function displayTimeframe(timeframe: string) {
  const value = normalizeTimeframe(timeframe);
  return value === "15m" ? "15m" : value.toUpperCase();
}

function normalizeTimeframe(timeframe?: string) {
  return String(timeframe || "1h").toLowerCase();
}

function isSupportedTimeframe(timeframe?: string) {
  return TIMEFRAMES.includes(normalizeTimeframe(timeframe));
}

function formatPrice(value?: number) {
  return typeof value === "number" ? formatInr(value) : NOT_AVAILABLE;
}

function formatPercent(value?: number) {
  return typeof value === "number" ? `${round(value)}%` : NOT_AVAILABLE;
}

function formatSignedPercent(value?: number) {
  return typeof value === "number" ? `${value > 0 ? "+" : ""}${round(value)}%` : NOT_AVAILABLE;
}

function formatScore(value?: number) {
  return typeof value === "number" ? `${Math.round(value)}` : NOT_AVAILABLE;
}

function formatDateTime(value?: string) {
  if (!value) return NOT_AVAILABLE;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
    timeZoneName: "short"
  }).format(date);
}

function timestampValue(value?: string) {
  if (!value) return 0;
  const time = new Date(value).getTime();
  return Number.isFinite(time) ? time : 0;
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function round(value: number) {
  return Number(value.toFixed(2));
}
