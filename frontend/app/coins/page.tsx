"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { Shell } from "@/components/Shell";
import { ErrorState, LoadingGrid } from "@/components/State";
import { ActionPill, EmptyState, Panel, formatInr } from "@/components/trading-ui";
import { useApi } from "@/hooks/useApi";
import { Ticker } from "@/types";

export default function CoinsPage() {
  const { data, loading, error } = useApi<Ticker[]>("/coins");
  const [query, setQuery] = useState("");
  const [trend, setTrend] = useState("ALL");
  const [timeframe, setTimeframe] = useState("All Timeframes");
  const [exchange, setExchange] = useState("All Exchanges");
  const [category, setCategory] = useState("All Assets");
  const [sort, setSort] = useState<"volume" | "price" | "change" | "confidence">("volume");
  const rows = useMemo(() => {
    return (data || [])
      .filter((coin) => coin.symbol.toLowerCase().includes(query.toLowerCase()))
      .filter((coin) => trend === "ALL" || coin.trend === trend)
      .sort((a, b) => {
        if (sort === "price") return b.last - a.last;
        if (sort === "change") return b.change_24h - a.change_24h;
        if (sort === "confidence") return (b.confidence || 0) - (a.confidence || 0);
        return b.volume_24h - a.volume_24h;
      })
      .slice(0, 50);
  }, [data, query, sort, trend]);

  return (
    <Shell>
      <div className="mb-6 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-primary">Markets</div>
          <h1 className="mt-1 text-[32px] font-semibold tracking-tight">Raw market intelligence</h1>
        </div>
        <div className="text-sm text-muted">{rows.length} instruments visible</div>
      </div>

      <Panel className="sticky top-0 z-10 mb-6 p-3 backdrop-blur">
        <div className="grid gap-3 md:grid-cols-[1fr_repeat(5,auto)] md:items-center">
          <label className="relative">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search markets" className="w-full rounded-lg border border-line bg-ink py-2 pl-9 pr-3 text-sm text-white outline-none focus:border-primary" />
          </label>
          <select value={trend} onChange={(event) => setTrend(event.target.value)} className="rounded-lg border border-line bg-ink px-3 py-2 text-sm"><option>ALL</option><option>Bullish</option><option>Bearish</option><option>Neutral</option></select>
          <select value={timeframe} onChange={(event) => setTimeframe(event.target.value)} className="rounded-lg border border-line bg-ink px-3 py-2 text-sm"><option>All Timeframes</option><option>15m</option><option>1h</option><option>4h</option><option>1d</option></select>
          <select value={exchange} onChange={(event) => setExchange(event.target.value)} className="rounded-lg border border-line bg-ink px-3 py-2 text-sm"><option>All Exchanges</option><option>KoinBX</option><option>CoinDCX</option></select>
          <select value={category} onChange={(event) => setCategory(event.target.value)} className="rounded-lg border border-line bg-ink px-3 py-2 text-sm"><option>All Assets</option><option>Large Cap</option><option>Layer 1</option><option>DeFi</option></select>
          <select value={sort} onChange={(event) => setSort(event.target.value as typeof sort)} className="rounded-lg border border-line bg-ink px-3 py-2 text-sm"><option value="volume">Volume</option><option value="price">Price</option><option value="change">24h Change</option><option value="confidence">Confidence</option></select>
        </div>
      </Panel>

      {loading && <LoadingGrid />}
      {error && <ErrorState message={error} />}
      {!loading && rows.length === 0 && <EmptyState label="No markets match the selected filters" />}
      {rows.length > 0 && (
        <Panel className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[920px] text-left text-sm">
              <thead className="bg-secondary text-xs uppercase text-muted">
                <tr><th className="px-4 py-3 font-medium">Coin</th><th className="px-4 py-3 font-medium">Price</th><th className="px-4 py-3 font-medium">24h</th><th className="px-4 py-3 font-medium">Volume</th><th className="px-4 py-3 font-medium">Trend</th><th className="px-4 py-3 font-medium">RSI</th><th className="px-4 py-3 font-medium">Signal</th><th className="px-4 py-3 font-medium">Confidence</th></tr>
              </thead>
              <tbody>
                {rows.map((coin) => (
                  <tr key={coin.symbol} className="border-t border-line transition hover:bg-cardHover">
                    <td className="px-4 py-3"><Link href={`/coins/${coin.symbol}`} className="font-semibold text-white">{coin.symbol.replace("_", "/")}</Link></td>
                    <td className="px-4 py-3">{formatInr(coin.last)}</td>
                    <td className={`px-4 py-3 ${coin.change_24h >= 0 ? "text-buy" : "text-sell"}`}>{coin.change_24h}%</td>
                    <td className="px-4 py-3">{coin.volume_24h.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</td>
                    <td className="px-4 py-3">{coin.trend || "-"}</td>
                    <td className="px-4 py-3">{coin.rsi ?? "-"}</td>
                    <td className="px-4 py-3">{coin.signal && <ActionPill signal={coin.signal} />}</td>
                    <td className="px-4 py-3">{coin.confidence ?? 0}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </Shell>
  );
}
