"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, BarChart3, BrainCircuit, Coins, LayoutDashboard, Radar, Settings, Target, TrendingUp, Wallet } from "lucide-react";
import { ConnectivityStatus } from "@/components/trading-ui";

const items = [
  { href: "/dashboard", label: "Command", icon: LayoutDashboard },
  { href: "/signals", label: "Trade Plans", icon: Target },
  { href: "/forecasts", label: "Forecasts", icon: TrendingUp },
  { href: "/intelligence", label: "Intel", icon: Radar },
  { href: "/coins", label: "Markets", icon: Coins },
  { href: "/portfolio", label: "Portfolio", icon: Wallet },
  { href: "/paper-trading", label: "Backtesting", icon: BarChart3 },
  { href: "/analytics", label: "Analytics", icon: Activity },
  { href: "/ml-analytics", label: "ML", icon: BrainCircuit },
  { href: "/settings", label: "Settings", icon: Settings }
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="min-h-screen bg-ink text-slate-100">
      <aside className="fixed bottom-0 z-20 grid w-full grid-cols-10 border-t border-line bg-secondary/95 shadow-card backdrop-blur md:left-0 md:top-0 md:h-screen md:w-[260px] md:grid-cols-1 md:grid-rows-[auto_1fr_auto] md:border-r md:border-t-0">
        <div className="hidden border-b border-line px-6 py-6 md:block">
          <div className="text-xl font-semibold tracking-tight">AlphaForge</div>
          <div className="mt-1 text-xs text-muted">AI trade intelligence</div>
        </div>
        <nav className="contents md:block md:px-3 md:py-4">
          {items.map((item) => {
            const Icon = item.icon;
            const active = pathname.startsWith(item.href);
            return (
              <Link key={item.href} href={item.href} className={`flex min-h-16 flex-col items-center justify-center gap-1 text-xs transition md:mb-1 md:min-h-0 md:flex-row md:justify-start md:rounded-lg md:px-3 md:py-3 md:text-sm ${active ? "bg-primary/10 text-primary" : "text-muted hover:bg-white/5 hover:text-white"}`}>
                <Icon size={18} />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="hidden border-t border-line p-4 md:block">
          <div className="mb-3 rounded-lg border border-line bg-ink/50 p-3">
            <div className="text-sm font-medium">Trader Workspace</div>
            <div className="mt-1 text-xs text-muted">Pro plan active</div>
          </div>
          <ConnectivityStatus />
        </div>
      </aside>
      <main className="pb-24 md:ml-[260px] md:pb-0">
        <div className="mx-auto max-w-7xl px-4 py-5 sm:px-6 lg:px-8">{children}</div>
      </main>
    </div>
  );
}
