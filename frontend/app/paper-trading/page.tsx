"use client";
import { useState } from "react";
import { PlayCircle } from "lucide-react";
import { Shell } from "@/components/Shell";
import { AuthRequired } from "@/components/AuthRequired";
import { Panel, SectionTitle } from "@/components/trading-ui";
import { api } from "@/services/api";

export default function PaperTradingPage() {
  const [symbol, setSymbol] = useState("BTC_INR");
  const [quantity, setQuantity] = useState("0.01");
  const [message, setMessage] = useState("");
  async function trade(side: "buy" | "sell") {
    setMessage("");
    try {
      await api(`/paper-trade/${side}`, { method: "POST", body: JSON.stringify({ symbol, quantity: Number(quantity) }) });
      setMessage(`${side.toUpperCase()} order filled`);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Trade failed");
    }
  }
  return (
    <Shell>
      <div className="mb-6 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-primary">Backtesting and execution lab</div>
          <h1 className="mt-1 text-[32px] font-semibold tracking-tight">Validate, simulate, execute</h1>
        </div>
        {message && <div className="rounded-lg border border-line bg-panel px-3 py-2 text-sm text-slate-300">{message}</div>}
      </div>
      <AuthRequired>
        <div className="grid gap-6 xl:grid-cols-[420px_1fr]">
          <Panel className="p-5">
            <SectionTitle title="Manual Paper Trade" action={<PlayCircle size={18} className="text-primary" />} />
            <label className="mb-3 block text-sm text-muted">Symbol<input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} className="mt-1 w-full rounded-lg border border-line bg-ink p-3 text-white outline-none focus:border-primary" /></label>
            <label className="mb-4 block text-sm text-muted">Quantity<input value={quantity} onChange={(e) => setQuantity(e.target.value)} type="number" step="0.0001" className="mt-1 w-full rounded-lg border border-line bg-ink p-3 text-white outline-none focus:border-primary" /></label>
            <div className="grid grid-cols-2 gap-3"><button onClick={() => trade("buy")} className="rounded-lg bg-buy px-4 py-3 font-semibold text-ink">Buy</button><button onClick={() => trade("sell")} className="rounded-lg bg-sell px-4 py-3 font-semibold text-white">Sell</button></div>
          </Panel>

          <Panel className="p-5">
            <SectionTitle title="Backtest Summary" />
            <div className="grid gap-3 md:grid-cols-5">
              {["Win Rate", "Profit Factor", "Max Drawdown", "Sharpe Ratio", "Average Return"].map((label) => (
                <div key={label} className="rounded-lg border border-line bg-ink/40 p-3">
                  <div className="text-xs text-muted">{label}</div>
                  <div className="mt-2 text-sm font-semibold">-</div>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </AuthRequired>
    </Shell>
  );
}
