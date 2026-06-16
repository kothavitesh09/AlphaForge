"use client";
import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { Shell } from "@/components/Shell";
import { ErrorState, LoadingGrid } from "@/components/State";
import { ActionPill, EmptyState, Panel, formatInr } from "@/components/trading-ui";
import { useApi } from "@/hooks/useApi";
import { API } from "@/services/api";
import { Ticker } from "@/types";

type Regime = { symbol: string; regime: string; confidence: number };
type Opportunity = { symbol: string; rank: number; alpha_score: number; confidence: number; expected_return: number; risk_score?: number };

export default function CoinsPage() {
  const markets = useApi<Ticker[]>(API.markets);
  const regimes = useApi<Regime[]>(API.marketRegimes);
  const opportunities = useApi<Opportunity[]>(API.opportunities);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"rank" | "change" | "volume" | "confidence">("rank");
  const regimeMap = useMemo(() => new Map((regimes.data || []).map((row) => [row.symbol, row])), [regimes.data]);
  const opportunityMap = useMemo(() => new Map((opportunities.data || []).map((row) => [row.symbol, row])), [opportunities.data]);
  const rows = useMemo(() => {
    return (markets.data || [])
      .filter((row) => row.symbol.toLowerCase().includes(query.toLowerCase()))
      .sort((a, b) => {
        const ao = opportunityMap.get(a.symbol);
        const bo = opportunityMap.get(b.symbol);
        if (sort === "change") return b.change_24h - a.change_24h;
        if (sort === "volume") return b.volume_24h - a.volume_24h;
        if (sort === "confidence") return (bo?.confidence || b.confidence || 0) - (ao?.confidence || a.confidence || 0);
        return (ao?.rank || 999) - (bo?.rank || 999);
      });
  }, [markets.data, opportunityMap, query, sort]);
  const loading = markets.loading || regimes.loading || opportunities.loading;
  const error = markets.error || regimes.error || opportunities.error;

  return (
    <Shell>
      <header className="mb-5 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-primary">Market Intelligence</div>
          <h1 className="mt-1 text-[28px] font-semibold tracking-tight">Scan the market</h1>
        </div>
        <div className="text-sm text-muted">{rows.length} assets</div>
      </header>

      <Panel className="sticky top-0 z-10 mb-5 p-3 backdrop-blur">
        <div className="grid gap-3 md:grid-cols-[1fr_auto]">
          <label className="relative">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search asset" className="w-full rounded-md border border-line bg-ink py-2 pl-9 pr-3 text-sm text-white outline-none focus:border-primary" />
          </label>
          <select value={sort} onChange={(event) => setSort(event.target.value as typeof sort)} className="rounded-md border border-line bg-ink px-3 py-2 text-sm">
            <option value="rank">Opportunity Rank</option>
            <option value="confidence">Confidence</option>
            <option value="change">24H Change</option>
            <option value="volume">Volume</option>
          </select>
        </div>
      </Panel>

      {loading && <LoadingGrid />}
      {error && <ErrorState message={error} />}
      {!loading && !error && rows.length === 0 && <EmptyState label="No market rows match the current scan. AlphaForge continues monitoring active assets." />}

      {rows.length > 0 && (
        <Panel className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1040px] text-left text-sm">
              <thead className="bg-secondary text-xs uppercase text-muted">
                <tr>
                  <th className="px-4 py-3 font-medium">Asset</th>
                  <th className="px-4 py-3 font-medium">Current Price</th>
                  <th className="px-4 py-3 font-medium">24H Change</th>
                  <th className="px-4 py-3 font-medium">Trend</th>
                  <th className="px-4 py-3 font-medium">Market Regime</th>
                  <th className="px-4 py-3 font-medium">Volume Strength</th>
                  <th className="px-4 py-3 font-medium">Signal</th>
                  <th className="px-4 py-3 font-medium">Confidence</th>
                  <th className="px-4 py-3 font-medium">Opportunity Rank</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((coin) => {
                  const regime = regimeMap.get(coin.symbol);
                  const opportunity = opportunityMap.get(coin.symbol);
                  return (
                    <tr key={coin.symbol} className="border-t border-line transition hover:bg-cardHover">
                      <td className="px-4 py-3 font-semibold">{coin.symbol.replace("_", "/")}</td>
                      <td className="px-4 py-3">{formatInr(coin.last)}</td>
                      <td className={`px-4 py-3 ${coin.change_24h >= 0 ? "text-buy" : "text-sell"}`}>{coin.change_24h}%</td>
                      <td className="px-4 py-3">{coin.trend || "-"}</td>
                      <td className="px-4 py-3">{regime ? `${regime.regime} (${Math.round(regime.confidence)}%)` : "-"}</td>
                      <td className="px-4 py-3">{volumeStrength(coin.volume_24h)}</td>
                      <td className="px-4 py-3"><ActionPill signal={coin.signal || ((opportunity?.expected_return || 0) >= 0 ? "BUY" : "SELL")} /></td>
                      <td className="px-4 py-3">{Math.round(opportunity?.confidence || coin.confidence || 0)}%</td>
                      <td className="px-4 py-3">{opportunity ? `#${opportunity.rank}` : "-"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </Shell>
  );
}

function volumeStrength(volume: number) {
  if (volume >= 100000000) return "Very High";
  if (volume >= 10000000) return "High";
  if (volume > 0) return "Normal";
  return "-";
}
