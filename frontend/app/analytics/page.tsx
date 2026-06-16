"use client";
import { Shell } from "@/components/Shell";
import { ErrorState, LoadingGrid } from "@/components/State";
import { EmptyState, Panel, SectionTitle, StatusLine } from "@/components/trading-ui";
import { useApi } from "@/hooks/useApi";
import { API } from "@/services/api";

type Accuracy = {
  source_type: string;
  total_predictions: number;
  correct_predictions: number;
  incorrect_predictions: number;
  accuracy_percent: number;
  win_rate?: number;
  mae: number;
  mape: number;
  rmse: number;
  by_asset?: { symbol: string; total: number; correct: number; accuracy: number }[];
  by_timeframe?: { timeframe: string; total: number; correct: number; accuracy: number }[];
  over_time?: { date: string; total: number; correct: number; accuracy: number }[];
};

type Analytics = {
  metrics: {
    profit_factor?: number;
    sharpe_ratio?: number;
  };
};

type Performance = {
  live_performance?: {
    prediction_metrics?: { sample_size: number; accuracy: number; mae: number; mape: number; rmse: number };
    trade_metrics?: { sample_size: number; win_rate: number; loss_rate: number; profit_factor: number; expectancy: number; sharpe_ratio: number; maximum_drawdown: number; recovery_factor: number };
  } | null;
  opportunity_score_validation: { bucket: string; sample_size: number; win_rate: number; profit_factor: number; expectancy?: number }[];
  confidence_calibration: { bucket: string; sample_size: number; expected_confidence: number; actual_success_rate: number; calibration_error: number; confidence_reliability: number }[];
  model_tournament: { model: string; timeframe: string; accuracy: number; mae: number; mape: number; rmse: number; profit_factor: number; sharpe: number; win_rate: number; is_best?: boolean; is_worst?: boolean }[];
  allocation: { allocations?: { symbol: string; allocation_percent: number }[] }[];
};

export default function AnalyticsPage() {
  const accuracy = useApi<Accuracy>(API.accuracy);
  const analytics = useApi<Analytics>(API.analytics);
  const performance = useApi<Performance>(API.performance);
  const loading = accuracy.loading || analytics.loading || performance.loading;
  const error = accuracy.error || analytics.error || performance.error;
  const data = accuracy.data;
  const tradeMetrics = performance.data?.live_performance?.trade_metrics;

  return (
    <Shell>
      <header className="mb-5 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-primary">Accuracy Center</div>
          <h1 className="mt-1 text-[28px] font-semibold tracking-tight">Live prediction trust metrics</h1>
        </div>
        <div className="text-sm text-muted">Sample size: {data?.total_predictions ?? 0}</div>
      </header>

      {loading && <LoadingGrid />}
      {error && <ErrorState message={error} />}
      {!loading && !error && !data && <EmptyState label="No live accuracy data is available yet. AlphaForge will report trust metrics after predictions resolve." />}

      {data && (
        <div className="space-y-5">
          <Panel className="border-primary/30 p-4">
            <div className="grid gap-4 md:grid-cols-4 xl:grid-cols-8">
              <Stat label="Live Predictions" value={data.total_predictions} />
              <Stat label="Live Accuracy" value={`${data.accuracy_percent}%`} />
              <Stat label="Win Rate" value={`${tradeMetrics?.win_rate ?? data.win_rate ?? data.accuracy_percent}%`} />
              <Stat label="MAE" value={data.mae.toFixed(4)} />
              <Stat label="MAPE" value={`${data.mape.toFixed(4)}%`} />
              <Stat label="RMSE" value={data.rmse.toFixed(4)} />
              <Stat label="Profit Factor" value={tradeMetrics?.profit_factor ?? analytics.data?.metrics?.profit_factor ?? 0} />
              <Stat label="Sharpe Ratio" value={tradeMetrics?.sharpe_ratio ?? analytics.data?.metrics?.sharpe_ratio ?? 0} />
            </div>
            <div className="mt-4 rounded-md border border-line bg-ink/40 p-3 text-sm text-muted">
              Live sample size is shown prominently because small samples can be misleading. Bootstrap results are excluded from this page.
            </div>
          </Panel>

          <div className="grid gap-5 xl:grid-cols-2">
            <Breakdown title="Accuracy By Asset" rows={data.by_asset || []} keyName="symbol" />
            <Breakdown title="Accuracy By Timeframe" rows={data.by_timeframe || []} keyName="timeframe" />
          </div>

          <Panel className="p-4">
            <SectionTitle title="Accuracy Over Time" />
            {(data.over_time || []).length === 0 && <EmptyState label="No resolved live predictions over time yet." />}
            <div className="space-y-3">
              {(data.over_time || []).map((row) => (
                <div key={row.date} className="grid grid-cols-[110px_1fr_96px] items-center gap-3 text-sm">
                  <span className="text-muted">{row.date}</span>
                  <div className="h-2 rounded bg-ink"><div className="h-full rounded bg-primary" style={{ width: `${Math.max(2, row.accuracy)}%` }} /></div>
                  <span className="text-right">{row.accuracy}% ({row.total})</span>
                </div>
              ))}
            </div>
          </Panel>

          <div className="grid gap-5 xl:grid-cols-2">
            <Panel className="p-4">
              <SectionTitle title="Opportunity Score Validation" />
              {(performance.data?.opportunity_score_validation || []).slice(0, 5).map((row) => (
                <StatusLine key={`${row.bucket}-${row.sample_size}`} label={row.bucket} value={`${row.win_rate}% win | PF ${row.profit_factor} | n=${row.sample_size}`} />
              ))}
              {(performance.data?.opportunity_score_validation || []).length === 0 && <EmptyState label="No completed live trades exist yet for opportunity score validation." />}
            </Panel>
            <Panel className="p-4">
              <SectionTitle title="Confidence Calibration" />
              {(performance.data?.confidence_calibration || []).slice(0, 5).map((row) => (
                <StatusLine key={`${row.bucket}-${row.sample_size}`} label={row.bucket} value={`Expected ${row.expected_confidence}% | Actual ${row.actual_success_rate}% | Error ${row.calibration_error}%`} />
              ))}
              {(performance.data?.confidence_calibration || []).length === 0 && <EmptyState label="No live calibration data exists yet." />}
            </Panel>
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <Panel className="p-4">
              <SectionTitle title="Model Tournament" />
              {(performance.data?.model_tournament || []).slice(0, 8).map((row) => (
                <StatusLine key={`${row.model}-${row.timeframe}`} label={`${row.model} ${row.timeframe}${row.is_best ? " BEST" : row.is_worst ? " WORST" : ""}`} value={`${row.accuracy}% acc | PF ${row.profit_factor} | Sharpe ${row.sharpe}`} />
              ))}
              {(performance.data?.model_tournament || []).length === 0 && <EmptyState label="No model tournament measurements exist yet." />}
            </Panel>
            <Panel className="p-4">
              <SectionTitle title="Allocation Recommendation" />
              {(performance.data?.allocation?.[0]?.allocations || []).map((row) => (
                <StatusLine key={row.symbol} label={row.symbol} value={`${row.allocation_percent}%`} />
              ))}
              {(performance.data?.allocation?.[0]?.allocations || []).length === 0 && <EmptyState label="No allocation recommendation exists yet." />}
            </Panel>
          </div>
        </div>
      )}
    </Shell>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-md border border-line bg-ink/40 p-3">
      <div className="text-[11px] uppercase text-muted">{label}</div>
      <div className="mt-2 text-xl font-semibold">{value}</div>
    </div>
  );
}

function Breakdown({ title, rows, keyName }: { title: string; rows: Array<Record<string, string | number>>; keyName: string }) {
  return (
    <Panel className="p-4">
      <SectionTitle title={title} />
      {rows.length === 0 && <EmptyState label="No live breakdown is available yet." />}
      {rows.map((row) => (
        <div key={String(row[keyName])} className="border-t border-line py-2">
          <StatusLine label={String(row[keyName])} value={`${row.accuracy}% (${row.correct}/${row.total})`} />
        </div>
      ))}
    </Panel>
  );
}
