"use client";
import { Shell } from "@/components/Shell";
import { MetricCard } from "@/components/MetricCard";
import { ErrorState, LoadingGrid } from "@/components/State";
import { useApi } from "@/hooks/useApi";

type ModelResult = {
  model: string;
  timeframe: string;
  status: string;
  reason?: string;
  metrics?: { accuracy: number; win_rate: number; precision: number; recall: number; f1: number; profit_factor: number; sharpe_ratio: number; confusion_matrix: number[][] };
  feature_importance?: { feature: string; importance: number }[];
  samples?: { total: number; train: number; validation: number; test: number };
};

type MLAnalytics = {
  models: ModelResult[];
  best_model?: ModelResult | null;
  top_features: { feature: string; importance: number }[];
  prediction_distribution: { prediction: string; count: number }[];
  ensemble_predictions: { symbol: string; timeframe: string; action: string; confidence: number }[];
  recent_ml_predictions: { symbol: string; timeframe: string; model: string; prediction: string; probability: number }[];
};

export default function MLAnalyticsPage() {
  const { data, loading, error } = useApi<MLAnalytics>("/ml/analytics");
  const best = data?.best_model;
  return (
    <Shell>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">ML Analytics</h1>
        <div className="text-sm text-zinc-400">Parallel model benchmark</div>
      </div>
      {loading && <LoadingGrid />}
      {error && <ErrorState message={error} />}
      {data && (
        <div className="space-y-6">
          <div className="grid gap-4 md:grid-cols-4">
            <MetricCard label="Best Model" value={best ? `${best.model} ${best.timeframe}` : "None"} />
            <MetricCard label="Model Accuracy" value={`${best?.metrics?.accuracy ?? 0}%`} />
            <MetricCard label="Model Win Rate" value={`${best?.metrics?.win_rate ?? 0}%`} />
            <MetricCard label="F1 Score" value={`${best?.metrics?.f1 ?? 0}`} />
          </div>
          <div className="grid gap-6 xl:grid-cols-2">
            <ModelTable rows={data.models} />
            <FeaturePanel rows={data.top_features} />
            <Distribution rows={data.prediction_distribution} />
            <ConfusionMatrix matrix={best?.metrics?.confusion_matrix || []} />
          </div>
          <RecentTable title="Ensemble Predictions" rows={data.ensemble_predictions} fields={["symbol", "timeframe", "action", "confidence"]} />
          <RecentTable title="Recent ML Predictions" rows={data.recent_ml_predictions} fields={["symbol", "timeframe", "model", "prediction", "probability"]} />
        </div>
      )}
    </Shell>
  );
}

function ModelTable({ rows }: { rows: ModelResult[] }) {
  return (
    <section className="rounded-lg border border-line bg-panel p-4">
      <h2 className="mb-4 text-lg font-semibold">Model Comparison</h2>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="text-xs uppercase text-zinc-500"><tr><th>Model</th><th>TF</th><th>Status</th><th>Acc</th><th>F1</th><th>PF</th><th>Sharpe</th></tr></thead>
          <tbody>{rows.map((row, i) => <tr key={`${row.model}-${row.timeframe}-${i}`} className="border-t border-line"><td className="py-2">{row.model}</td><td>{row.timeframe}</td><td>{row.status}</td><td>{row.metrics?.accuracy ?? row.reason ?? ""}</td><td>{row.metrics?.f1 ?? ""}</td><td>{row.metrics?.profit_factor ?? ""}</td><td>{row.metrics?.sharpe_ratio ?? ""}</td></tr>)}</tbody>
        </table>
      </div>
    </section>
  );
}

function FeaturePanel({ rows }: { rows: { feature: string; importance: number }[] }) {
  const max = Math.max(1, ...rows.map((row) => row.importance));
  return <section className="rounded-lg border border-line bg-panel p-4"><h2 className="mb-4 text-lg font-semibold">Top Features</h2><div className="space-y-3">{rows.slice(0, 20).map((row) => <div key={row.feature} className="grid grid-cols-[150px_1fr_70px] items-center gap-3 text-sm"><span>{row.feature}</span><div className="h-2 rounded bg-ink"><div className="h-full rounded bg-buy" style={{ width: `${row.importance / max * 100}%` }} /></div><span className="text-right">{row.importance}</span></div>)}</div></section>;
}

function Distribution({ rows }: { rows: { prediction: string; count: number }[] }) {
  return <section className="rounded-lg border border-line bg-panel p-4"><h2 className="mb-4 text-lg font-semibold">Prediction Distribution</h2><div className="space-y-3">{rows.map((row) => <div key={row.prediction} className="flex justify-between border-t border-line pt-3 text-sm"><span>{row.prediction}</span><span>{row.count}</span></div>)}</div></section>;
}

function ConfusionMatrix({ matrix }: { matrix: number[][] }) {
  return <section className="rounded-lg border border-line bg-panel p-4"><h2 className="mb-4 text-lg font-semibold">Confusion Matrix</h2><div className="grid grid-cols-3 gap-2 text-center text-sm">{matrix.flat().map((value, index) => <div key={index} className="rounded bg-ink p-3">{value}</div>)}</div></section>;
}

function RecentTable({ title, rows, fields }: { title: string; rows: Record<string, string | number>[]; fields: string[] }) {
  return <section className="rounded-lg border border-line bg-panel p-4"><h2 className="mb-4 text-lg font-semibold">{title}</h2><div className="overflow-x-auto"><table className="w-full min-w-[560px] text-left text-sm"><thead className="text-xs uppercase text-zinc-500"><tr>{fields.map((field) => <th key={field}>{field}</th>)}</tr></thead><tbody>{rows.slice(0, 16).map((row, index) => <tr key={index} className="border-t border-line">{fields.map((field) => <td key={field} className="py-2">{String(row[field] ?? "")}</td>)}</tr>)}</tbody></table></div></section>;
}
