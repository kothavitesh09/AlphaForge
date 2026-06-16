"use client";
import { Shell } from "@/components/Shell";
import { ErrorState, LoadingGrid } from "@/components/State";
import { ActionPill, EmptyState, Metric, Panel, SectionTitle, StatusLine, formatInr } from "@/components/trading-ui";
import { useApi } from "@/hooks/useApi";
import { buildTerminalOpportunities, confidenceLabel, formatDate, signed } from "@/lib/intelligence";
import { API } from "@/services/api";
import { Prediction, Signal, Ticker } from "@/types";

type Dashboard = {
  market_sentiment: { label: string; score: number };
  market_trend: string;
  prediction_accuracy: { predictions: number; correct: number; accuracy: number };
};

type Accuracy = {
  source_type: string;
  total_predictions: number;
  accuracy_percent: number;
  win_rate?: number;
  mae?: number;
  mape?: number;
  rmse?: number;
};

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

export default function DashboardPage() {
  const dashboard = useApi<Dashboard>(API.dashboard);
  const predictions = useApi<Prediction[]>(API.predictions);
  const signals = useApi<Signal[]>(API.signals);
  const markets = useApi<Ticker[]>(API.markets);
  const forecasts = useApi<Forecast[]>(API.forecasts);
  const accuracy = useApi<Accuracy>(API.accuracy);

  const loading = dashboard.loading || predictions.loading || signals.loading || markets.loading || forecasts.loading || accuracy.loading;
  const error = dashboard.error || predictions.error || signals.error || markets.error || forecasts.error || accuracy.error;
  const opportunities = buildTerminalOpportunities({
    predictions: predictions.data,
    signals: signals.data,
    tickers: markets.data,
    forecasts: forecasts.data
  });
  const top = opportunities[0];

  return (
    <Shell>
      <header className="mb-5 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-primary">Mission Control</div>
          <h1 className="mt-1 text-[28px] font-semibold tracking-tight">Best trade right now</h1>
        </div>
        <div className="text-sm text-muted">Live validation only: {accuracy.data?.total_predictions ?? 0} samples</div>
      </header>

      {loading && <LoadingGrid />}
      {error && <ErrorState message={error} />}
      {!loading && !error && !top && (
        <EmptyState label="No high-confidence opportunities currently exist. AlphaForge continues monitoring markets and will surface opportunities when sufficient evidence is detected." />
      )}

      {top && (
        <div className="space-y-5">
          <Panel className="overflow-hidden">
            <div className="grid gap-0 lg:grid-cols-[1.1fr_.9fr]">
              <div className="border-b border-line p-5 lg:border-b-0 lg:border-r">
                <div className="mb-4 flex items-start justify-between gap-4">
                  <div>
                    <div className="text-sm text-muted">Top Opportunity</div>
                    <h2 className="mt-1 text-4xl font-semibold tracking-tight">{top.symbol.replace("_", "/")}</h2>
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <ActionPill signal={top.signal?.signal || (top.expectedReturn >= 0 ? "BUY" : "SELL")} />
                      <span className="rounded-md border border-line bg-ink/50 px-2.5 py-1 text-xs font-semibold text-primary">{top.timeframe.toUpperCase()} best opportunity</span>
                      <span className="rounded-md border border-line bg-ink/50 px-2.5 py-1 text-xs text-slate-300">{top.riskLevel} risk</span>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-xs uppercase text-muted">Opportunity Score</div>
                    <div className="mt-1 text-4xl font-semibold text-primary">{Math.round(top.score)}</div>
                  </div>
                </div>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <Metric label="Expected Return" value={signed(top.expectedReturn)} tone={top.expectedReturn >= 0 ? "text-buy" : "text-sell"} />
                  <Metric label="Expected Price" value={formatInr(top.expectedPrice)} />
                  <Metric label="Expected Target Date" value={formatDate(top.expectedDate)} />
                  <Metric label="Confidence" value={`${Math.round(top.confidence)}%`} />
                </div>
              </div>

              <div className="p-5">
                <SectionTitle title="Trust Snapshot" />
                <StatusLine label="Recent Live Accuracy" value={`${accuracy.data?.accuracy_percent ?? 0}%`} />
                <StatusLine label="Recent Win Rate" value={`${accuracy.data?.win_rate ?? accuracy.data?.accuracy_percent ?? 0}%`} />
                <StatusLine label="Sample Size" value={accuracy.data?.total_predictions ?? 0} />
                <StatusLine label="Confidence Label" value={`${confidenceLabel(top.confidence)} (${Math.round(top.confidence)}%)`} />
                <StatusLine label="Market Regime" value={top.forecast?.market_regime || dashboard.data?.market_trend || dashboard.data?.market_sentiment?.label || "-"} />
              </div>
            </div>
          </Panel>

          <section>
            <SectionTitle title="Top 5 Opportunities" />
            <div className="grid gap-3 xl:grid-cols-5">
              {opportunities.slice(0, 5).map((row, index) => (
                <Panel key={row.symbol} className="p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-xs text-muted">Rank #{index + 1}</div>
                      <div className="mt-1 text-lg font-semibold">{row.symbol.replace("_", "/")}</div>
                    </div>
                    <ActionPill signal={row.signal?.signal || (row.expectedReturn >= 0 ? "BUY" : "SELL")} />
                  </div>
                  <div className="mt-4 space-y-1">
                    <StatusLine label="Return" value={<span className={row.expectedReturn >= 0 ? "text-buy" : "text-sell"}>{signed(row.expectedReturn)}</span>} />
                    <StatusLine label="Price" value={formatInr(row.expectedPrice)} />
                    <StatusLine label="By" value={formatDate(row.expectedDate)} />
                    <StatusLine label="Confidence" value={`${Math.round(row.confidence)}%`} />
                  </div>
                </Panel>
              ))}
            </div>
          </section>
        </div>
      )}
    </Shell>
  );
}
