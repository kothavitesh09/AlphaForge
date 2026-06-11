"use client";
import { Shell } from "@/components/Shell";
import { MetricCard } from "@/components/MetricCard";
import { ErrorState, LoadingGrid } from "@/components/State";
import { useApi } from "@/hooks/useApi";
import { API } from "@/services/api";

type Analytics = {
  metrics: Record<string, number>;
  charts: {
    accuracy_trend: { date: string; accuracy: number; total: number; correct: number }[];
    signal_performance: { signal: string; total: number; wins: number; losses: number; average_return: number }[];
    profit_curve: { timestamp: string; equity: number }[];
    prediction_distribution: { direction: string; count: number }[];
  };
  tables: {
    best_symbols: SymbolRow[];
    worst_symbols: SymbolRow[];
    recent_predictions: Record<string, string | number | boolean>[];
    recent_results: Record<string, string | number | boolean>[];
  };
  backtests: Record<string, string | number>[];
};

type SymbolRow = { symbol: string; total: number; accuracy: number; average_return: number };

export default function AnalyticsPage() {
  const { data, loading, error } = useApi<Analytics>(API.analytics);
  return (
    <Shell>
      <div className="mb-6 flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">Analytics</h1>
        <div className="text-sm text-zinc-400">Measured intelligence</div>
      </div>
      {loading && <LoadingGrid />}
      {error && <ErrorState message={error} />}
      {data && (
        <div className="space-y-6">
          <div className="grid gap-4 md:grid-cols-4">
            <MetricCard label="Prediction Accuracy" value={`${data.metrics.prediction_accuracy ?? 0}%`} />
            <MetricCard label="Win Rate" value={`${data.metrics.win_rate ?? 0}%`} />
            <MetricCard label="Profit Factor" value={`${data.metrics.profit_factor ?? 0}`} />
            <MetricCard label="Sharpe Ratio" value={`${data.metrics.sharpe_ratio ?? 0}`} />
          </div>
          <div className="grid gap-6 xl:grid-cols-2">
            <ChartPanel title="Accuracy Trend" rows={data.charts.accuracy_trend.map((x) => ({ label: x.date, value: x.accuracy }))} suffix="%" />
            <ChartPanel title="Prediction Distribution" rows={data.charts.prediction_distribution.map((x) => ({ label: x.direction, value: x.count }))} />
            <ChartPanel title="Signal Performance" rows={data.charts.signal_performance.map((x) => ({ label: x.signal, value: x.average_return }))} suffix="%" />
            <ChartPanel title="Profit Curve" rows={data.charts.profit_curve.slice(-20).map((x, i) => ({ label: String(i + 1), value: x.equity }))} suffix="%" />
          </div>
          <div className="grid gap-6 xl:grid-cols-2">
            <SymbolTable title="Best Performing Symbols" rows={data.tables.best_symbols} />
            <SymbolTable title="Worst Performing Symbols" rows={data.tables.worst_symbols} />
          </div>
          <div className="grid gap-6 xl:grid-cols-2">
            <RecentTable title="Recent Predictions" rows={data.tables.recent_predictions} fields={["symbol", "timeframe", "direction", "confidence"]} />
            <RecentTable title="Recent Results" rows={data.tables.recent_results} fields={["symbol", "timeframe", "predicted", "actual", "correct"]} />
          </div>
          <RecentTable title="Backtesting Dashboard" rows={data.backtests} fields={["symbol", "win_rate", "profit_factor", "max_drawdown", "sharpe_ratio", "average_return"]} />
        </div>
      )}
    </Shell>
  );
}

function ChartPanel({ title, rows, suffix = "" }: { title: string; rows: { label: string; value: number }[]; suffix?: string }) {
  const max = Math.max(1, ...rows.map((row) => Math.abs(Number(row.value) || 0)));
  return (
    <section className="rounded-lg border border-line bg-panel p-4">
      <h2 className="mb-4 text-lg font-semibold">{title}</h2>
      <div className="space-y-3">
        {rows.length === 0 && <div className="text-sm text-zinc-500">No data</div>}
        {rows.slice(-12).map((row) => (
          <div key={`${title}-${row.label}`} className="grid grid-cols-[90px_1fr_72px] items-center gap-3 text-sm">
            <span className="truncate text-zinc-400">{row.label}</span>
            <div className="h-2 overflow-hidden rounded bg-ink"><div className="h-full bg-buy" style={{ width: `${Math.max(2, Math.abs(row.value) / max * 100)}%` }} /></div>
            <span className="text-right">{Number(row.value).toFixed(2)}{suffix}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function SymbolTable({ title, rows }: { title: string; rows: SymbolRow[] }) {
  return (
    <section className="rounded-lg border border-line bg-panel p-4">
      <h2 className="mb-4 text-lg font-semibold">{title}</h2>
      <div className="space-y-3 text-sm">
        {rows.length === 0 && <div className="text-zinc-500">No data</div>}
        {rows.map((row) => (
          <div key={`${title}-${row.symbol}`} className="grid grid-cols-4 gap-3 border-t border-line pt-3">
            <span>{row.symbol}</span><span>{row.total}</span><span>{row.accuracy}%</span><span className={row.average_return >= 0 ? "text-buy" : "text-sell"}>{row.average_return}%</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function RecentTable({ title, rows, fields }: { title: string; rows: Record<string, string | number | boolean>[]; fields: string[] }) {
  return (
    <section className="rounded-lg border border-line bg-panel p-4">
      <h2 className="mb-4 text-lg font-semibold">{title}</h2>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-left text-sm">
          <thead className="text-xs uppercase text-zinc-500"><tr>{fields.map((field) => <th key={field} className="pb-2 font-medium">{field.replace("_", " ")}</th>)}</tr></thead>
          <tbody>
            {rows.slice(0, 12).map((row, index) => (
              <tr key={`${title}-${index}`} className="border-t border-line">
                {fields.map((field) => <td key={field} className="py-2 pr-3">{String(row[field] ?? "")}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
