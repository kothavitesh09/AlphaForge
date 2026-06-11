"use client";
import { Shell } from "@/components/Shell";
import { AuthRequired } from "@/components/AuthRequired";
import { ErrorState, LoadingGrid } from "@/components/State";
import { EmptyState, Metric, Panel, SectionTitle, formatInr } from "@/components/trading-ui";
import { useApi } from "@/hooks/useApi";
import { API } from "@/services/api";

type Portfolio = {
  cash_balance: number;
  equity: number;
  portfolio_value: number;
  available_cash: number;
  open_positions: number;
  closed_positions: number;
  unrealized_pnl: number;
  realized_pnl: number;
  win_rate: number;
  positions: Record<string, { symbol: string; side: string; quantity: number; market_value: number; unrealized_pnl: number; current_price: number; entry_price: number; target: number; stop_loss: number; duration: string }>;
};

export default function PortfolioPage() {
  return (
    <Shell>
      <div className="mb-6">
        <div className="text-xs font-semibold uppercase tracking-wide text-primary">Portfolio Intelligence</div>
        <h1 className="mt-1 text-[32px] font-semibold tracking-tight">Paper portfolio and position risk</h1>
      </div>
      <AuthRequired>
        <PortfolioContent />
      </AuthRequired>
    </Shell>
  );
}

function PortfolioContent() {
  const { data, loading, error } = useApi<Portfolio>(API.portfolio);
  const positions = Object.entries(data?.positions || {});
  return (
    <>
      {loading && <LoadingGrid />}
      {error && <ErrorState message={error} />}
      {data && <div className="space-y-6">
        <div className="grid gap-4 md:grid-cols-4">
          <Metric label="Portfolio Value" value={formatInr(data.portfolio_value)} />
          <Metric label="Cash Available" value={formatInr(data.available_cash)} />
          <Metric label="Open Positions" value={data.open_positions} />
          <Metric label="Total Return" value={formatInr(data.realized_pnl + data.unrealized_pnl)} tone={data.realized_pnl + data.unrealized_pnl >= 0 ? "text-buy" : "text-sell"} />
        </div>

        <div className="grid gap-6 xl:grid-cols-[1fr_360px]">
          <Panel className="p-4">
            <SectionTitle title="Open Positions" />
            {positions.length === 0 && <EmptyState label="No open positions" />}
            {positions.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[920px] text-left text-sm">
                  <thead className="text-xs uppercase text-muted"><tr><th className="pb-3">Symbol</th><th className="pb-3">Side</th><th className="pb-3">Qty</th><th className="pb-3">Entry</th><th className="pb-3">Current</th><th className="pb-3">Target</th><th className="pb-3">Stop</th><th className="pb-3">PnL</th><th className="pb-3">Duration</th></tr></thead>
                  <tbody>
                    {positions.map(([id, p]) => (
                      <tr key={id} className="border-t border-line">
                        <td className="py-3 font-medium">{p.symbol}</td>
                        <td className={p.side?.toUpperCase() === "BUY" ? "text-buy" : "text-sell"}>{p.side}</td>
                        <td>{p.quantity}</td>
                        <td>{formatInr(p.entry_price)}</td>
                        <td>{formatInr(p.current_price)}</td>
                        <td>{formatInr(p.target)}</td>
                        <td>{formatInr(p.stop_loss)}</td>
                        <td className={p.unrealized_pnl >= 0 ? "text-buy" : "text-sell"}>{formatInr(p.unrealized_pnl)}</td>
                        <td>{p.duration}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          <Panel className="p-4">
            <SectionTitle title="Allocation" />
            <div className="space-y-3">
              {positions.length === 0 && <EmptyState label="No allocation yet" />}
              {positions.map(([id, p]) => {
                const width = data.portfolio_value > 0 ? Math.max(2, Math.min(100, p.market_value / data.portfolio_value * 100)) : 0;
                return (
                  <div key={id} className="text-sm">
                    <div className="mb-1 flex justify-between"><span>{p.symbol}</span><span>{width.toFixed(1)}%</span></div>
                    <div className="h-2 rounded bg-ink"><div className="h-full rounded bg-primary" style={{ width: `${width}%` }} /></div>
                  </div>
                );
              })}
            </div>
            <div className="mt-6 grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-lg border border-line bg-ink/40 p-3"><div className="text-xs text-muted">Closed</div><div className="mt-1 font-semibold">{data.closed_positions}</div></div>
              <div className="rounded-lg border border-line bg-ink/40 p-3"><div className="text-xs text-muted">Win Rate</div><div className="mt-1 font-semibold">{data.win_rate}%</div></div>
              <div className="rounded-lg border border-line bg-ink/40 p-3"><div className="text-xs text-muted">Unrealized</div><div className={`mt-1 font-semibold ${data.unrealized_pnl >= 0 ? "text-buy" : "text-sell"}`}>{formatInr(data.unrealized_pnl)}</div></div>
              <div className="rounded-lg border border-line bg-ink/40 p-3"><div className="text-xs text-muted">Realized</div><div className={`mt-1 font-semibold ${data.realized_pnl >= 0 ? "text-buy" : "text-sell"}`}>{formatInr(data.realized_pnl)}</div></div>
            </div>
          </Panel>
        </div>
      </div>}
    </>
  );
}
