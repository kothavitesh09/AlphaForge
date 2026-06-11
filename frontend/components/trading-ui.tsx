"use client";
import { ArrowDownRight, ArrowUpRight, CheckCircle2, CircleDot, Minus, ShieldCheck } from "lucide-react";
import { Signal, Ticker } from "@/types";

export function formatInr(value?: number | null) {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  return `₹${value.toLocaleString("en-IN", { maximumFractionDigits: value > 100 ? 0 : 4 })}`;
}

export function normalizeSignal(value?: string) {
  const signal = String(value || "HOLD").toUpperCase();
  if (signal === "NO_TRADE" || signal === "SIDEWAYS") return "HOLD";
  return signal === "BUY" || signal === "SELL" ? signal : "HOLD";
}

export function riskLabel(value?: string) {
  const risk = String(value || "").replace("_RISK", "").replace("_", " ").toUpperCase();
  if (risk.includes("LOW")) return "LOW";
  if (risk.includes("HIGH")) return "HIGH";
  if (risk.includes("MEDIUM")) return "MEDIUM";
  return "MODERATE";
}

export function signalTone(signal?: string) {
  const value = normalizeSignal(signal);
  if (value === "BUY") return "text-buy";
  if (value === "SELL") return "text-sell";
  return "text-hold";
}

export function actionClasses(signal?: string) {
  const value = normalizeSignal(signal);
  if (value === "BUY") return "border-buy/30 bg-buy/10 text-buy";
  if (value === "SELL") return "border-sell/30 bg-sell/10 text-sell";
  return "border-hold/30 bg-hold/10 text-hold";
}

export function actionIcon(signal?: string) {
  const value = normalizeSignal(signal);
  if (value === "BUY") return ArrowUpRight;
  if (value === "SELL") return ArrowDownRight;
  return Minus;
}

export function percentFromSignal(signal: Signal) {
  const direct = signal.decision?.net_profit_percent;
  if (typeof direct === "number") return direct;
  const raw = String(signal.expected_move || "").match(/-?\d+(\.\d+)?/);
  return raw ? Number(raw[0]) : undefined;
}

export function targetFromSignal(signal: Signal, price?: number) {
  const move = percentFromSignal(signal);
  if (typeof price !== "number" || typeof move !== "number") return undefined;
  const direction = normalizeSignal(signal.signal);
  if (direction === "SELL") return price * (1 - Math.abs(move) / 100);
  if (direction === "BUY") return price * (1 + Math.abs(move) / 100);
  return price;
}

export function tradePlanScore(signal: Signal) {
  const confidence = Number(signal.confidence || 0);
  const move = Math.abs(percentFromSignal(signal) || 0);
  const riskPenalty = riskLabel(signal.risk) === "HIGH" ? 18 : riskLabel(signal.risk) === "MEDIUM" ? 8 : 0;
  return confidence + move * 3 - riskPenalty;
}

export function qualityGrade(confidence?: number) {
  const value = Number(confidence || 0);
  if (value >= 85) return "A+";
  if (value >= 75) return "A";
  if (value >= 65) return "B";
  if (value >= 55) return "C";
  return "D";
}

export function tickerMap(rows?: Ticker[] | null) {
  return new Map((rows || []).map((row) => [row.symbol, row]));
}

export function ActionPill({ signal }: { signal?: string }) {
  const Icon = actionIcon(signal);
  return (
    <span className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs font-semibold ${actionClasses(signal)}`}>
      <Icon size={14} />
      {normalizeSignal(signal)}
    </span>
  );
}

export function Panel({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <section className={`rounded-lg border border-line bg-panel shadow-card ${className}`}>{children}</section>;
}

export function Metric({ label, value, tone = "" }: { label: string; value: React.ReactNode; tone?: string }) {
  return (
    <Panel className="p-4 transition hover:border-slate-600 hover:bg-cardHover">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className={`mt-2 text-2xl font-semibold ${tone}`}>{value}</div>
    </Panel>
  );
}

export function ReasonList({ items }: { items?: string[] }) {
  const rows = (items || []).slice(0, 5);
  return (
    <div className="space-y-2">
      {rows.length === 0 && <div className="text-sm text-muted">No AI reasoning available</div>}
      {rows.map((item) => (
        <div key={item} className="flex items-start gap-2 text-sm text-slate-300">
          <CheckCircle2 size={15} className="mt-0.5 shrink-0 text-buy" />
          <span>{item}</span>
        </div>
      ))}
    </div>
  );
}

export function StatusLine({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-t border-line py-2 text-sm">
      <span className="text-muted">{label}</span>
      <span className="text-right font-medium text-slate-100">{value}</span>
    </div>
  );
}

export function ConfidenceBar({ value }: { value?: number }) {
  const confidence = Math.max(0, Math.min(100, Number(value || 0)));
  return (
    <div className="h-2 overflow-hidden rounded bg-ink">
      <div className="h-full rounded bg-primary" style={{ width: `${confidence}%` }} />
    </div>
  );
}

export function EmptyState({ label }: { label: string }) {
  return (
    <div className="flex min-h-24 items-center justify-center rounded-lg border border-dashed border-line bg-ink/40 text-sm text-muted">
      {label}
    </div>
  );
}

export function SectionTitle({ eyebrow, title, action }: { eyebrow?: string; title: string; action?: React.ReactNode }) {
  return (
    <div className="mb-4 flex items-end justify-between gap-4">
      <div>
        {eyebrow && <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-primary">{eyebrow}</div>}
        <h2 className="text-xl font-semibold text-slate-50">{title}</h2>
      </div>
      {action}
    </div>
  );
}

export function ConnectivityStatus() {
  return (
    <div className="flex items-center gap-2 text-xs text-muted">
      <CircleDot size={12} className="text-buy" />
      API Connected
      <ShieldCheck size={13} className="ml-auto text-primary" />
    </div>
  );
}
