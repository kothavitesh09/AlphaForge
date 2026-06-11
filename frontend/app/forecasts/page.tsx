"use client";
import { Shell } from "@/components/Shell";
import { ErrorState, LoadingGrid } from "@/components/State";
import { ConfidenceBar, EmptyState, Metric, Panel, SectionTitle, StatusLine, formatInr } from "@/components/trading-ui";
import { useApi } from "@/hooks/useApi";
import { API } from "@/services/api";

type Forecast = {
  symbol: string;
  current_price: number;
  forecast_24h: number;
  forecast_48h: number;
  forecast_7d: number;
  bull_case: number;
  base_case: number;
  bear_case: number;
  confidence: number;
  alpha_score: number;
  market_regime: string;
  expected_return: number;
  rank?: number;
};

export default function ForecastsPage() {
  const { data, loading, error } = useApi<Forecast[]>(API.forecasts);
  const rows = [...(data || [])].sort((a, b) => Number(b.alpha_score || 0) - Number(a.alpha_score || 0));
  const top = rows[0];

  return (
    <Shell>
      <div className="mb-6 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-primary">Forecast Engine</div>
          <h1 className="mt-1 text-[32px] font-semibold tracking-tight">Institutional market forecasts</h1>
        </div>
        <div className="text-sm text-muted">{rows.length} live forecasts</div>
      </div>

      {loading && <LoadingGrid />}
      {error && <ErrorState message={error} />}
      {!loading && !error && rows.length === 0 && <EmptyState label="No forecasts generated yet" />}

      {top && (
        <div className="mb-6 grid gap-4 md:grid-cols-4">
          <Metric label="Top Alpha" value={top.symbol} />
          <Metric label="Alpha Score" value={top.alpha_score} />
          <Metric label="Expected Return" value={`${signed(top.expected_return)}%`} tone={top.expected_return >= 0 ? "text-buy" : "text-sell"} />
          <Metric label="Regime" value={top.market_regime} />
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        {rows.map((row, index) => (
          <Panel key={row.symbol} className="p-4 transition hover:border-slate-600 hover:bg-cardHover">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div>
                <div className="text-xs text-muted">Rank #{row.rank || index + 1}</div>
                <h2 className="mt-1 text-2xl font-semibold">{row.symbol.replace("_", "/")}</h2>
                <div className="mt-1 text-sm text-muted">Current {formatInr(row.current_price)}</div>
              </div>
              <div className="text-right">
                <div className="text-xs text-muted">Alpha Score</div>
                <div className="text-3xl font-semibold text-primary">{Math.round(row.alpha_score || 0)}</div>
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-3">
              <ForecastCell label="24H" value={row.forecast_24h} current={row.current_price} />
              <ForecastCell label="48H" value={row.forecast_48h} current={row.current_price} />
              <ForecastCell label="7D" value={row.forecast_7d} current={row.current_price} />
            </div>

            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <Panel className="p-3">
                <SectionTitle title="Scenarios" />
                <StatusLine label="Bull Case" value={formatInr(row.bull_case)} />
                <StatusLine label="Base Case" value={formatInr(row.base_case)} />
                <StatusLine label="Bear Case" value={formatInr(row.bear_case)} />
              </Panel>
              <Panel className="p-3">
                <SectionTitle title="Conviction" />
                <StatusLine label="Confidence" value={`${row.confidence}%`} />
                <StatusLine label="Regime" value={row.market_regime} />
                <StatusLine label="Expected Return" value={`${signed(row.expected_return)}%`} />
                <div className="mt-3"><ConfidenceBar value={row.confidence} /></div>
              </Panel>
            </div>
          </Panel>
        ))}
      </div>
    </Shell>
  );
}

function ForecastCell({ label, value, current }: { label: string; value: number; current: number }) {
  const change = current > 0 ? (value / current - 1) * 100 : 0;
  return (
    <div className="rounded-lg border border-line bg-ink/40 p-3">
      <div className="text-xs text-muted">{label} Forecast</div>
      <div className="mt-2 text-lg font-semibold">{formatInr(value)}</div>
      <div className={`mt-1 text-xs ${change >= 0 ? "text-buy" : "text-sell"}`}>{signed(change)}%</div>
    </div>
  );
}

function signed(value?: number) {
  const number = Number(value || 0);
  return `${number > 0 ? "+" : ""}${number.toFixed(2)}`;
}
