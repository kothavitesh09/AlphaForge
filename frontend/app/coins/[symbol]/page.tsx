"use client";
import { use } from "react";
import { Shell } from "@/components/Shell";
import { MarketChart } from "@/components/MarketChart";
import { ErrorState, LoadingGrid } from "@/components/State";
import { ActionPill, Metric, Panel, SectionTitle, StatusLine, formatInr, normalizeSignal, signalTone } from "@/components/trading-ui";
import { useApi } from "@/hooks/useApi";
import { Candle, Ticker } from "@/types";

export default function CoinPage({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = use(params);
  const { data, loading, error } = useApi<{ ticker: Ticker; candles: Candle[] }>(`/coins/${symbol}`);
  const ticker = data?.ticker;
  const signal = normalizeSignal(ticker?.signal);

  return (
    <Shell>
      {loading && <LoadingGrid />}
      {error && <ErrorState message={error} />}
      {data && ticker && (
        <div className="space-y-6">
          <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wide text-primary">Market detail</div>
              <h1 className="mt-1 text-[32px] font-semibold tracking-tight">{ticker.symbol.replace("_", "/")}</h1>
              <p className="mt-1 text-muted">{formatInr(ticker.last)}</p>
            </div>
            <div className="flex items-center gap-3">
              <span className={`rounded-lg border border-line px-3 py-2 text-sm font-semibold ${ticker.change_24h >= 0 ? "text-buy" : "text-sell"}`}>{ticker.change_24h}% 24h</span>
              <span className={`rounded-lg border border-line px-3 py-2 text-sm font-semibold ${ticker.trend === "Bullish" ? "text-buy" : ticker.trend === "Bearish" ? "text-sell" : "text-hold"}`}>{ticker.trend || "Neutral"}</span>
            </div>
          </div>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,7fr)_minmax(320px,3fr)]">
            <Panel className="p-4">
              <SectionTitle title="Price Action" action={<span className="text-sm text-muted">{data.candles.length} candles</span>} />
              <MarketChart candles={data.candles} />
            </Panel>

            <Panel className="p-4">
              <SectionTitle eyebrow="AI intelligence" title="Trade Plan Snapshot" />
              <div className="mb-4 flex items-center justify-between rounded-lg border border-line bg-ink/40 p-4">
                <ActionPill signal={ticker.signal} />
                <div className={`text-2xl font-semibold ${signalTone(ticker.signal)}`}>{ticker.confidence ?? 0}%</div>
              </div>
              <StatusLine label="Risk" value={ticker.trend === "Bullish" || ticker.trend === "Bearish" ? "MODERATE" : "HIGH"} />
              <StatusLine label="Target" value="-" />
              <StatusLine label="Stop" value="-" />
              <StatusLine label="Expected Profit" value="-" />
              <StatusLine label="Expected Duration" value="-" />
              <StatusLine label="Signal Quality" value={ticker.confidence && ticker.confidence >= 75 ? "A" : ticker.confidence && ticker.confidence >= 60 ? "B" : "C"} />
            </Panel>
          </div>

          <div className="grid gap-4 md:grid-cols-4 xl:grid-cols-7">
            <Metric label="RSI" value={ticker.rsi ?? "-"} />
            <Metric label="MACD" value="-" />
            <Metric label="EMA" value={ticker.trend || "-"} />
            <Metric label="ATR" value="-" />
            <Metric label="Volume" value={ticker.volume_24h.toLocaleString("en-IN", { maximumFractionDigits: 2 })} />
            <Metric label="Bollinger" value="-" />
            <Metric label="Order Flow" value={signal} tone={signalTone(signal)} />
          </div>
        </div>
      )}
    </Shell>
  );
}
