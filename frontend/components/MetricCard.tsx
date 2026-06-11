export function MetricCard({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="rounded-lg border border-line bg-panel p-4">
      <div className="text-xs uppercase tracking-wider text-zinc-500">{label}</div>
      <div className={`mt-2 text-2xl font-semibold ${accent || "text-white"}`}>{value}</div>
    </div>
  );
}
