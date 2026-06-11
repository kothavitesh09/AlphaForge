export function LoadingGrid() {
  return <div className="grid gap-4 md:grid-cols-3">{Array.from({ length: 6 }).map((_, i) => <div key={i} className="skeleton h-28 rounded-lg" />)}</div>;
}

export function ErrorState({ message }: { message: string }) {
  return <div className="rounded-lg border border-sell/40 bg-sell/10 p-4 text-sm text-sell">{message}</div>;
}
