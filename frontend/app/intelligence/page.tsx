"use client";
import { Shell } from "@/components/Shell";
import { ErrorState, LoadingGrid } from "@/components/State";
import { EmptyState, Metric, Panel, SectionTitle, StatusLine, formatInr } from "@/components/trading-ui";
import { useApi } from "@/hooks/useApi";
import { API } from "@/services/api";

type Opportunity = {
  symbol: string;
  alpha_score: number;
  expected_return: number;
  confidence: number;
  risk_score: number;
  rank: number;
  market_regime?: string;
};

type Forecast = {
  symbol: string;
  current_price: number;
  forecast_48h: number;
  confidence: number;
  expected_return: number;
};

type Intelligence = {
  top_opportunity?: Opportunity | null;
  top_opportunities: Opportunity[];
  market_regime_overview: { symbol: string; regime: string; confidence: number }[];
  highest_confidence_forecast?: Forecast | null;
  highest_expected_return?: Forecast | null;
  most_accurate_model?: { model: string; timeframe: string; metrics?: { accuracy?: number; f1?: number } } | null;
  best_performing_coin?: { symbol: string; accuracy: number; average_return: number } | null;
  worst_performing_coin?: { symbol: string; accuracy: number; average_return: number } | null;
  live_alpha_rankings: Opportunity[];
};

export default function IntelligencePage() {
  const { data, loading, error } = useApi<Intelligence>(API.intelligence);
  const top = data?.top_opportunity;

  return (
    <Shell>
      <div className="mb-6 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-primary">AlphaForge Intelligence</div>
          <h1 className="mt-1 text-[32px] font-semibold tracking-tight">Forecasts, regimes, and alpha rankings</h1>
        </div>
        <div className="text-sm text-muted">Ensemble intelligence layer</div>
      </div>

      {loading && <LoadingGrid />}
      {error && <ErrorState message={error} />}
      {!loading && !error && !data && <EmptyState label="No intelligence snapshot available" />}

      {data && (
        <div className="space-y-6">
          <div className="grid gap-4 md:grid-cols-4">
            <Metric label="Top Opportunity" value={top?.symbol || "-"} />
            <Metric label="Alpha Score" value={top?.alpha_score ?? 0} />
            <Metric label="Expected Return" value={`${signed(top?.expected_return)}%`} tone={(top?.expected_return || 0) >= 0 ? "text-buy" : "text-sell"} />
            <Metric label="Risk Score" value={top?.risk_score ?? 0} />
          </div>

          <div className="grid gap-6 xl:grid-cols-[1.1fr_.9fr]">
            <Panel className="p-4">
              <SectionTitle eyebrow="Scanner" title="Top 5 Opportunities" />
              {data.top_opportunities.length === 0 && <EmptyState label="No ranked opportunities" />}
              <div className="space-y-3">
                {data.top_opportunities.map((row) => <OpportunityRow key={row.symbol} row={row} />)}
              </div>
            </Panel>

            <Panel className="p-4">
              <SectionTitle eyebrow="Regime" title="Market Regime Overview" />
              {data.market_regime_overview.length === 0 && <EmptyState label="No regime data" />}
              <div className="grid gap-2 sm:grid-cols-2">
                {data.market_regime_overview.slice(0, 10).map((row) => (
                  <div key={row.symbol} className="rounded-lg border border-line bg-ink/40 p-3 text-sm">
                    <div className="flex justify-between gap-3"><span className="font-semibold">{row.symbol}</span><span>{row.regime}</span></div>
                    <div className="mt-1 text-xs text-muted">Confidence {row.confidence}%</div>
                  </div>
                ))}
              </div>
            </Panel>
          </div>

          <div className="grid gap-6 xl:grid-cols-3">
            <Panel className="p-4">
              <SectionTitle title="Highest Confidence Forecast" />
              <ForecastBlock forecast={data.highest_confidence_forecast} />
            </Panel>
            <Panel className="p-4">
              <SectionTitle title="Highest Expected Return" />
              <ForecastBlock forecast={data.highest_expected_return} />
            </Panel>
            <Panel className="p-4">
              <SectionTitle title="Model & Coin Quality" />
              <StatusLine label="Most Accurate Model" value={data.most_accurate_model ? `${data.most_accurate_model.model} ${data.most_accurate_model.timeframe}` : "-"} />
              <StatusLine label="Model Accuracy" value={`${data.most_accurate_model?.metrics?.accuracy ?? 0}%`} />
              <StatusLine label="Best Coin" value={data.best_performing_coin?.symbol || "-"} />
              <StatusLine label="Worst Coin" value={data.worst_performing_coin?.symbol || "-"} />
            </Panel>
          </div>

          <Panel className="p-4">
            <SectionTitle title="Live Alpha Rankings" />
            {data.live_alpha_rankings.length === 0 && <EmptyState label="No alpha rankings" />}
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-left text-sm">
                <thead className="text-xs uppercase text-muted"><tr><th className="pb-3">Rank</th><th>Coin</th><th>Alpha</th><th>Return</th><th>Confidence</th><th>Risk</th><th>Regime</th></tr></thead>
                <tbody>
                  {data.live_alpha_rankings.map((row) => (
                    <tr key={row.symbol} className="border-t border-line">
                      <td className="py-3">#{row.rank}</td>
                      <td className="font-semibold">{row.symbol}</td>
                      <td>{row.alpha_score}</td>
                      <td className={row.expected_return >= 0 ? "text-buy" : "text-sell"}>{signed(row.expected_return)}%</td>
                      <td>{row.confidence}%</td>
                      <td>{row.risk_score}</td>
                      <td>{row.market_regime || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>
      )}
    </Shell>
  );
}

function OpportunityRow({ row }: { row: Opportunity }) {
  return (
    <div className="grid gap-3 rounded-lg border border-line bg-ink/40 p-3 text-sm md:grid-cols-[64px_1fr_repeat(4,92px)] md:items-center">
      <div className="font-semibold text-primary">#{row.rank}</div>
      <div className="font-semibold">{row.symbol}</div>
      <div>{row.alpha_score}</div>
      <div className={row.expected_return >= 0 ? "text-buy" : "text-sell"}>{signed(row.expected_return)}%</div>
      <div>{row.confidence}%</div>
      <div>{row.market_regime || "-"}</div>
    </div>
  );
}

function ForecastBlock({ forecast }: { forecast?: Forecast | null }) {
  if (!forecast) return <EmptyState label="No forecast" />;
  return (
    <>
      <StatusLine label="Coin" value={forecast.symbol} />
      <StatusLine label="Current" value={formatInr(forecast.current_price)} />
      <StatusLine label="48H Forecast" value={formatInr(forecast.forecast_48h)} />
      <StatusLine label="Expected Return" value={`${signed(forecast.expected_return)}%`} />
      <StatusLine label="Confidence" value={`${forecast.confidence}%`} />
    </>
  );
}

function signed(value?: number) {
  const number = Number(value || 0);
  return `${number > 0 ? "+" : ""}${number.toFixed(2)}`;
}
