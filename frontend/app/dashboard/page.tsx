"use client";
import { Shell } from "@/components/Shell";
import { ErrorState, LoadingGrid } from "@/components/State";
import {
  ActionPill,
  ConfidenceBar,
  EmptyState,
  Metric,
  Panel,
  SectionTitle,
  StatusLine,
  formatInr,
  normalizeSignal,
  percentFromSignal,
  riskLabel,
  signalTone,
  targetFromSignal,
  tickerMap,
  tradePlanScore
} from "@/components/trading-ui";
import { useApi } from "@/hooks/useApi";
import { Signal, Ticker } from "@/types";

type Dashboard = {
  market_sentiment: { label: string; score: number };
  market_overview: Ticker[];
  market_trend: string;
  active_signals: number;
  portfolio_value: number;
  top_buy_signals: Signal[];
  top_sell_signals: Signal[];
  top_gainers: Ticker[];
  top_losers: Ticker[];
  recent_predictions: Record<string, string | number>[];
  recent_trades: Record<string, string | number>[];
  prediction_accuracy: { predictions: number; correct: number; accuracy: number };
};

export default function DashboardPage() {
  const { data, loading, error } = useApi<Dashboard>("/dashboard");
  const tickers = tickerMap(data?.market_overview);
  const plans = [...(data?.top_buy_signals || []), ...(data?.top_sell_signals || [])]
    .filter((signal) => normalizeSignal(signal.signal) !== "HOLD")
    .sort((a, b) => tradePlanScore(b) - tradePlanScore(a))
    .slice(0, 5);
  const forecastSymbols = Array.from(new Set([...(plans.map((plan) => plan.symbol)), ...(data?.recent_predictions || []).map((row) => String(row.symbol || ""))])).filter(Boolean).slice(0, 4);

  return (
    <Shell>
      <div className="mb-6 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-primary">AlphaForge Command Center</div>
          <h1 className="mt-1 text-[32px] font-semibold tracking-tight">What should I trade next?</h1>
        </div>
        <div className="text-sm text-muted">Live market data, AI predictions, and executable trade plans</div>
      </div>

      {loading && <LoadingGrid />}
      {error && <ErrorState message={error} />}
      {data && (
        <div className="space-y-6">
          <section>
            <SectionTitle eyebrow="Top trade plans" title="Highest quality opportunities" />
            <div className="grid gap-4 xl:grid-cols-5">
              {plans.length === 0 && <div className="xl:col-span-5"><EmptyState label="No active trade plans from live signals" /></div>}
              {plans.map((signal, index) => {
                const price = tickers.get(signal.symbol)?.last;
                const target = targetFromSignal(signal, price);
                const profit = percentFromSignal(signal);
                return (
                  <Panel key={signal.id || `${signal.symbol}-${index}`} className="p-4 transition hover:border-slate-600 hover:bg-cardHover">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-xs text-muted">Rank #{index + 1}</div>
                        <h2 className="mt-1 text-lg font-semibold">{signal.symbol.replace("_", "/")}</h2>
                      </div>
                      <ActionPill signal={signal.signal} />
                    </div>
                    <div className="mt-4 space-y-2">
                      <StatusLine label="Entry" value={formatInr(price)} />
                      <StatusLine label="Target" value={formatInr(target)} />
                      <StatusLine label="Profit" value={typeof profit === "number" ? `${profit > 0 ? "+" : ""}${profit}%` : signal.expected_move || "-"} />
                      <StatusLine label="Duration" value={signal.expected_window || "-"} />
                      <StatusLine label="Risk" value={riskLabel(signal.risk)} />
                    </div>
                    <div className="mt-4">
                      <div className="mb-2 flex justify-between text-xs text-muted"><span>AI confidence</span><span>{signal.confidence}%</span></div>
                      <ConfidenceBar value={signal.confidence} />
                    </div>
                    <div className="mt-3 flex items-center justify-between text-sm">
                      <span className="text-muted">Probability</span>
                      <span className="font-semibold">{signal.confidence}%</span>
                    </div>
                  </Panel>
                );
              })}
            </div>
          </section>

          <div className="grid gap-4 md:grid-cols-4">
            <Metric label="Market Sentiment" value={`${data.market_sentiment.label} ${data.market_sentiment.score}/100`} tone={data.market_trend === "Bullish" ? "text-buy" : data.market_trend === "Bearish" ? "text-sell" : "text-hold"} />
            <Metric label="Prediction Accuracy" value={`${data.prediction_accuracy.accuracy}%`} />
            <Metric label="Active Trade Signals" value={`${data.active_signals}`} />
            <Metric label="Portfolio Value" value={formatInr(data.portfolio_value)} />
          </div>

          <div className="grid gap-6 xl:grid-cols-[1.15fr_.85fr]">
            <Panel className="p-4">
              <SectionTitle eyebrow="AI forecast" title="Multi-source prediction consensus" />
              <div className="space-y-3">
                {forecastSymbols.length === 0 && <EmptyState label="No forecast rows available" />}
                {forecastSymbols.map((symbol) => {
                  const latest = plans.find((plan) => plan.symbol === symbol);
                  const prediction = latest ? normalizeSignal(latest.signal) : String((data.recent_predictions.find((row) => row.symbol === symbol) || {}).direction || "HOLD").toUpperCase();
                  return (
                    <div key={symbol} className="grid gap-3 rounded-lg border border-line bg-ink/40 p-3 text-sm md:grid-cols-[130px_1fr_110px] md:items-center">
                      <div className="font-semibold">{symbol.replace("_", "/")}</div>
                      <div className="grid grid-cols-2 gap-2 text-xs text-muted md:grid-cols-4">
                        {["15m", "1H", "4H", "1D"].map((tf) => <span key={tf} className="rounded border border-line bg-panel px-2 py-1">{tf} {prediction}</span>)}
                      </div>
                      <div className={`font-semibold md:text-right ${signalTone(prediction)}`}>{prediction === "BUY" ? "STRONG BUY" : prediction}</div>
                    </div>
                  );
                })}
              </div>
            </Panel>

            <Panel className="p-4">
              <SectionTitle eyebrow="Market intelligence" title="Regime snapshot" />
              <div className="mb-4 flex items-center justify-between rounded-lg border border-line bg-ink/40 p-4">
                <div>
                  <div className={`text-2xl font-semibold ${data.market_trend === "Bullish" ? "text-buy" : data.market_trend === "Bearish" ? "text-sell" : "text-hold"}`}>{data.market_sentiment.label}</div>
                  <div className="mt-1 text-sm text-muted">Fear & Greed style score</div>
                </div>
                <div className="text-4xl font-semibold">{data.market_sentiment.score}</div>
              </div>
              <StatusLine label="BTC Trend" value={data.market_overview.find((coin) => coin.symbol === "BTC_INR")?.trend || data.market_trend} />
              <StatusLine label="ETH Trend" value={data.market_overview.find((coin) => coin.symbol === "ETH_INR")?.trend || data.market_trend} />
              <StatusLine label="Market Momentum" value={data.market_trend} />
              <StatusLine label="Dominance Metrics" value="-" />
            </Panel>
          </div>

          <Panel className="p-4">
            <SectionTitle eyebrow="AlphaForge performance" title="Last measured intelligence" />
            <div className="grid gap-4 md:grid-cols-3">
              <Metric label="Predictions" value={data.prediction_accuracy.predictions} />
              <Metric label="Correct Predictions" value={data.prediction_accuracy.correct} />
              <Metric label="Accuracy" value={`${data.prediction_accuracy.accuracy}%`} />
            </div>
          </Panel>

          <div className="grid gap-6 xl:grid-cols-3">
            <MarketList title="Top Gainers" rows={data.top_gainers} positive />
            <MarketList title="Top Losers" rows={data.top_losers} />
            <Panel className="p-4">
              <SectionTitle title="Recent Paper Trades" />
              {data.recent_trades.length === 0 && <EmptyState label="No paper trades yet" />}
              {data.recent_trades.map((trade, index) => <div key={String(trade.id || index)} className="flex justify-between border-t border-line py-3 text-sm"><span>{String(trade.symbol || "")}</span><span>{String(trade.side || "")}</span></div>)}
            </Panel>
          </div>
        </div>
      )}
    </Shell>
  );
}

function MarketList({ title, rows, positive = false }: { title: string; rows: Ticker[]; positive?: boolean }) {
  return (
    <Panel className="p-4">
      <SectionTitle title={title} />
      <div className="space-y-3">
        {rows.map((ticker) => (
          <div key={ticker.symbol} className="flex items-center justify-between border-t border-line pt-3 text-sm">
            <div>
              <div className="font-medium">{ticker.symbol}</div>
              <div className="text-xs text-muted">{formatInr(ticker.last)}</div>
            </div>
            <span className={positive ? "text-buy" : "text-sell"}>{ticker.change_24h}%</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}
