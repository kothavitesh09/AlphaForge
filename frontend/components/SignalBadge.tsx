import { Signal } from "@/types";

export function SignalBadge({ signal }: { signal: Signal["signal"] }) {
  const cls = signal === "BUY" ? "bg-buy/15 text-buy" : signal === "SELL" ? "bg-sell/15 text-sell" : signal === "NO_TRADE" ? "bg-zinc-600/20 text-zinc-300" : "bg-hold/15 text-hold";
  return <span className={`rounded px-2 py-1 text-xs font-semibold ${cls}`}>{signal}</span>;
}
