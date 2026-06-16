"use client";
import { useMemo, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { Shell } from "@/components/Shell";
import { ErrorState, LoadingGrid } from "@/components/State";
import { ActionPill, EmptyState, Panel, SectionTitle, StatusLine, formatInr } from "@/components/trading-ui";
import { useApi } from "@/hooks/useApi";
import {
  CORE_TIMEFRAMES,
  CoreTimeframe,
  OpportunityRow,
  buildTerminalOpportunities,
  confidenceLabel,
  displayTimeframe,
  firstNumber,
  formatDate,
  signed
} from "@/lib/intelligence";
import { API } from "@/services/api";
import { Prediction, Signal, Ticker } from "@/types";

type Forecast = {
  symbol: string;
  current_price: number;
  forecast_24h?: number;
  forecast_48h?: number;
  forecast_7d?: number;
  confidence: number;
  alpha_score?: number;
  market_regime?: string;
  expected_return?: number;
};

type Analytics = {
  tables?: {
    best_symbols?: { symbol: string; accuracy: number; total: number }[];
    worst_symbols?: { symbol: string; accuracy: number; total: number }[];
  };
};

export default function IntelligencePage() {
  const predictions = useApi<Prediction[]>(API.predictions);
  const signals = useApi<Signal[]>(API.signals);
  const markets = useApi<Ticker[]>(API.markets);
  const forecasts = useApi<Forecast[]>(API.forecasts);
  const analytics = useApi<Analytics>(API.analytics);
  const loading = predictions.loading || signals.loading || markets.loading || forecasts.loading || analytics.loading;
  const error = predictions.error || signals.error || markets.error || forecasts.error || analytics.error;
  const accuracyBySymbol = useMemo(() => {
    const rows = [...(analytics.data?.tables?.best_symbols || []), ...(analytics.data?.tables?.worst_symbols || [])];
    return new Map(rows.map((row) => [row.symbol, row]));
  }, [analytics.data]);
  const opportunities = buildTerminalOpportunities({
    predictions: predictions.data,
    signals: signals.data,
    tickers: markets.data,
    forecasts: forecasts.data
  });

  return (
    <Shell>
      <header className="mb-5 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-primary">Opportunities</div>
          <h1 className="mt-1 text-[28px] font-semibold tracking-tight">Ranked trade intelligence</h1>
        </div>
        <div className="text-sm text-muted">{opportunities.length} coins ranked by opportunity score</div>
      </header>

      {loading && <LoadingGrid />}
      {error && <ErrorState message={error} />}
      {!loading && !error && opportunities.length === 0 && (
        <EmptyState label="No high-confidence opportunities currently exist. AlphaForge continues monitoring markets and will surface opportunities when sufficient evidence is detected." />
      )}

      <div className="space-y-4">
        {opportunities.map((opportunity, index) => (
          <OpportunityCard key={opportunity.symbol} opportunity={opportunity} rank={index + 1} historicalAccuracy={accuracyBySymbol.get(opportunity.symbol)} />
        ))}
      </div>
    </Shell>
  );
}

function OpportunityCard({ opportunity, rank, historicalAccuracy }: { opportunity: OpportunityRow; rank: number; historicalAccuracy?: { accuracy: number; total: number } }) {
  const [expanded, setExpanded] = useState(false);
  const [timeframe, setTimeframe] = useState<CoreTimeframe>(opportunity.timeframe);
  const selected = useMemo(() => selectedOpportunity(opportunity, timeframe), [opportunity, timeframe]);
  const signal = selected.signal?.signal || (selected.expectedReturn >= 0 ? "BUY" : "SELL");

  return (
    <Panel className="overflow-hidden">
      <div className="grid gap-0 xl:grid-cols-[220px_1fr]">
        <div className="border-b border-line bg-ink/30 p-4 xl:border-b-0 xl:border-r">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-xs text-muted">Rank #{rank}</div>
              <h2 className="mt-1 text-2xl font-semibold">{opportunity.symbol.replace("_", "/")}</h2>
            </div>
            <ActionPill signal={signal} />
          </div>
          <div className="mt-4 text-xs uppercase text-muted">Opportunity Score</div>
          <div className="text-4xl font-semibold text-primary">{Math.round(selected.score)}</div>
          <div className="mt-2 text-sm text-slate-300">{confidenceLabel(selected.confidence)} ({Math.round(selected.confidence)}%)</div>
        </div>

        <div className="p-4">
          <div className="mb-4 flex flex-wrap gap-2">
            {CORE_TIMEFRAMES.map((item) => {
              const row = selectedOpportunity(opportunity, item);
              const active = timeframe === item;
              const best = opportunity.timeframe === item;
              return (
                <button
                  key={item}
                  onClick={() => setTimeframe(item)}
                  className={`rounded-md border px-3 py-2 text-xs font-semibold transition ${active ? "border-primary bg-primary/15 text-primary" : "border-line bg-ink/40 text-muted hover:border-slate-600 hover:text-white"}`}
                >
                  {displayTimeframe(item)}
                  {best && <span className="ml-2 rounded bg-buy/15 px-1.5 py-0.5 text-[10px] text-buy">BEST OPPORTUNITY</span>}
                  <span className="ml-2 text-[10px] text-muted">{Math.round(row.score)}</span>
                </button>
              );
            })}
          </div>

          <div className="grid gap-3 md:grid-cols-4 xl:grid-cols-8">
            <Cell label="Current Price" value={formatInr(selected.currentPrice)} />
            <Cell label="Expected Price" value={formatInr(selected.expectedPrice)} />
            <Cell label="Expected Return" value={signed(selected.expectedReturn)} tone={selected.expectedReturn >= 0 ? "text-buy" : "text-sell"} />
            <Cell label="Expected Date" value={formatDate(selected.expectedDate)} />
            <Cell label="Confidence" value={`${Math.round(selected.confidence)}%`} />
            <Cell label="Risk Level" value={selected.riskLevel} />
            <Cell label="Historical Accuracy" value={historicalAccuracy ? `${historicalAccuracy.accuracy}% (${historicalAccuracy.total})` : `${selected.prediction?.validation_accuracy ?? 0}%`} />
            <Cell label="Regime" value={selected.forecast?.market_regime || selected.ticker?.trend || "-"} />
          </div>

          <button onClick={() => setExpanded((value) => !value)} className="mt-4 flex w-full items-center justify-center gap-2 rounded-md border border-line px-4 py-2 text-sm font-semibold text-slate-100 transition hover:bg-white/5">
            {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            {expanded ? "Hide Detail" : "Expand Detail"}
          </button>

          {expanded && <ExpandedOpportunity opportunity={selected} />}
        </div>
      </div>
    </Panel>
  );
}

function ExpandedOpportunity({ opportunity }: { opportunity: OpportunityRow }) {
  const signal = opportunity.signal;
  const prediction = opportunity.prediction;
  const target1 = firstNumber(prediction?.take_profit_1, signal?.target, signal?.decision?.take_profit_1, opportunity.expectedPrice);
  const target2 = firstNumber(prediction?.take_profit_2, signal?.decision?.take_profit_2);
  const target3 = firstNumber(prediction?.take_profit_3, signal?.decision?.take_profit_3);
  return (
    <div className="mt-4 grid gap-4 border-t border-line pt-4 lg:grid-cols-2">
      <Panel className="p-4">
        <SectionTitle title="Execution" />
        <StatusLine label="Entry" value={formatInr(firstNumber(signal?.entry, signal?.decision?.entry_price, opportunity.currentPrice))} />
        <StatusLine label="Stop Loss" value={formatInr(firstNumber(prediction?.stop_loss, signal?.stop_loss, signal?.decision?.stop_loss))} />
        <StatusLine label="Target 1" value={formatInr(target1)} />
        <StatusLine label="Target 2" value={formatInr(target2)} />
        <StatusLine label="Target 3" value={formatInr(target3)} />
        <StatusLine label="Risk/Reward" value={prediction?.risk_reward_ratio || signal?.risk_reward || signal?.decision?.risk_reward_ratio || "-"} />
      </Panel>
      <Panel className="p-4">
        <SectionTitle title="Peak & Holding" />
        <StatusLine label="Expected Peak Price" value={formatInr(opportunity.expectedPrice)} />
        <StatusLine label="Expected Peak Time" value={formatDate(opportunity.expectedDate)} />
        <StatusLine label="Expected Holding Duration" value={signal?.expected_window || signal?.decision?.estimated_duration || displayTimeframe(opportunity.timeframe)} />
        <StatusLine label="ML View" value={prediction?.direction || signal?.signal || "-"} />
        <StatusLine label="Risk Factors" value={signal?.risk || opportunity.riskLevel} />
      </Panel>
      <Panel className="p-4 lg:col-span-2">
        <SectionTitle title="Why This Opportunity Exists" />
        <div className="grid gap-3 md:grid-cols-3">
          <Reason label="Trend" value={opportunity.ticker?.trend || opportunity.forecast?.market_regime || "Trend evidence is limited"} />
          <Reason label="Momentum" value={signed(opportunity.expectedReturn)} tone={opportunity.expectedReturn >= 0 ? "text-buy" : "text-sell"} />
          <Reason label="Volume" value={opportunity.ticker?.volume_24h ? opportunity.ticker.volume_24h.toLocaleString("en-IN", { maximumFractionDigits: 0 }) : "Volume detail unavailable"} />
          <Reason label="Market Structure" value={prediction?.expected_move || opportunity.forecast?.market_regime || "-"} />
          <Reason label="ML View" value={prediction?.probabilities ? probabilityText(prediction.probabilities) : prediction?.direction || "-"} />
          <Reason label="Risk Factors" value={signal?.explanation?.slice(0, 2).join(" ") || signal?.decision?.reason || opportunity.riskLevel} />
        </div>
      </Panel>
    </div>
  );
}

function selectedOpportunity(opportunity: OpportunityRow, timeframe: CoreTimeframe) {
  const prediction = opportunity.predictions[timeframe] || opportunity.prediction;
  return {
    ...opportunity,
    prediction,
    timeframe,
    expectedPrice: firstNumber(prediction?.predicted_price, opportunity.expectedPrice),
    expectedReturn: firstNumber(prediction?.predicted_change_pct, opportunity.expectedReturn) || 0,
    expectedDate: prediction?.target_timestamp || opportunity.expectedDate,
    confidence: firstNumber(prediction?.confidence, opportunity.confidence) || 0,
    score: firstNumber(prediction?.opportunity_score, opportunity.score) || opportunity.score
  };
}

function Cell({ label, value, tone = "" }: { label: string; value: React.ReactNode; tone?: string }) {
  return (
    <div className="min-h-[78px] rounded-md border border-line bg-ink/40 p-3">
      <div className="text-[11px] uppercase text-muted">{label}</div>
      <div className={`mt-2 text-sm font-semibold leading-tight ${tone}`}>{value}</div>
    </div>
  );
}

function Reason({ label, value, tone = "" }: { label: string; value: React.ReactNode; tone?: string }) {
  return (
    <div className="rounded-md border border-line bg-ink/40 p-3">
      <div className="text-xs uppercase text-muted">{label}</div>
      <div className={`mt-2 text-sm text-slate-100 ${tone}`}>{value}</div>
    </div>
  );
}

function probabilityText(probabilities: Record<string, number>) {
  return Object.entries(probabilities)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 3)
    .map(([key, value]) => `${key.toUpperCase()} ${Math.round(Number(value))}%`)
    .join(" / ");
}
