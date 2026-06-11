"use client";
import Link from "next/link";
import { useState } from "react";
import { Shell } from "@/components/Shell";
import { AuthRequired } from "@/components/AuthRequired";
import { ErrorState, LoadingGrid } from "@/components/State";
import { Panel, SectionTitle } from "@/components/trading-ui";
import { API, api } from "@/services/api";
import { useApi } from "@/hooks/useApi";

type Settings = { exchange_selection: string; refresh_interval: number; risk_profile: string; theme: string; auto_trading_enabled: boolean };

export default function SettingsPage() {
  return (
    <Shell>
      <div className="mb-6">
        <div className="text-xs font-semibold uppercase tracking-wide text-primary">Settings</div>
        <h1 className="mt-1 text-[32px] font-semibold tracking-tight">Workspace, risk, and AI performance</h1>
      </div>
      <AuthRequired><SettingsForm /></AuthRequired>
    </Shell>
  );
}

function SettingsForm() {
  const { data, loading, error } = useApi<Settings>(API.settings);
  const [message, setMessage] = useState("");
  const [draft, setDraft] = useState<Partial<Settings>>({});
  const settings = { ...data, ...draft } as Settings;
  async function save() {
    setMessage("");
    try {
      await api(API.settings, { method: "PUT", body: JSON.stringify(draft) });
      setMessage("Settings saved");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Settings failed to save");
    }
  }
  return (
    <div className="space-y-6">
      {loading && <LoadingGrid />}
      {error && <ErrorState message={error} />}
      {data && (
        <>
          <div className="grid gap-6 xl:grid-cols-2">
            <Panel className="p-5">
              <SectionTitle title="Profile" />
              <div className="grid gap-4 md:grid-cols-2">
                <Field label="Exchange APIs"><select value={settings.exchange_selection} onChange={(event) => setDraft({ ...draft, exchange_selection: event.target.value })} className="mt-1 w-full rounded-lg border border-line bg-ink p-3"><option>KoinBX</option><option>CoinDCX</option></select></Field>
                <Field label="Refresh Interval"><input type="number" value={settings.refresh_interval} onChange={(event) => setDraft({ ...draft, refresh_interval: Number(event.target.value) })} className="mt-1 w-full rounded-lg border border-line bg-ink p-3" /></Field>
              </div>
            </Panel>

            <Panel className="p-5">
              <SectionTitle title="Risk Settings" />
              <div className="grid gap-4 md:grid-cols-2">
                <Field label="Risk Profile"><select value={settings.risk_profile} onChange={(event) => setDraft({ ...draft, risk_profile: event.target.value })} className="mt-1 w-full rounded-lg border border-line bg-ink p-3"><option>Conservative</option><option>Balanced</option><option>Aggressive</option></select></Field>
                <Field label="Theme"><select value={settings.theme} onChange={(event) => setDraft({ ...draft, theme: event.target.value })} className="mt-1 w-full rounded-lg border border-line bg-ink p-3"><option>Dark</option><option>Light</option></select></Field>
              </div>
            </Panel>
          </div>

          <div className="grid gap-6 xl:grid-cols-2">
            <Panel className="p-5">
              <SectionTitle title="Security" />
              <div className="flex items-center justify-between rounded-lg border border-line bg-ink/40 p-4 text-sm">
                <span>Session</span>
                <button onClick={() => localStorage.removeItem("alphaforge_token")} className="rounded-lg border border-line px-4 py-2 text-muted hover:text-white">Clear</button>
              </div>
            </Panel>

            <Panel className="p-5">
              <SectionTitle title="Notifications" />
              <div className="flex items-center justify-between rounded-lg border border-line bg-ink/40 p-4 text-sm"><span>Auto Trading</span><span className="rounded-md bg-secondary px-2 py-1 text-xs text-muted">OFF</span></div>
            </Panel>
          </div>

          <Panel className="p-5">
            <SectionTitle title="AI Performance" />
            <div className="grid gap-3 md:grid-cols-3">
              <Link href="/analytics" className="rounded-lg border border-line bg-ink/40 p-4 transition hover:bg-cardHover"><div className="font-semibold">Analytics</div><div className="mt-1 text-sm text-muted">Accuracy, profit curve, backtests</div></Link>
              <Link href="/ml-analytics" className="rounded-lg border border-line bg-ink/40 p-4 transition hover:bg-cardHover"><div className="font-semibold">ML Analytics</div><div className="mt-1 text-sm text-muted">Models, confusion matrix, features</div></Link>
              <div className="rounded-lg border border-line bg-ink/40 p-4"><div className="font-semibold">Backend Diagnostics</div><div className="mt-1 text-sm text-muted">API connected</div></div>
            </div>
          </Panel>

          <div className="flex flex-wrap items-center gap-3">
            <button onClick={save} className="rounded-lg bg-buy px-5 py-3 font-semibold text-ink">Save</button>
            {message && <div className="text-sm text-buy">{message}</div>}
          </div>
        </>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block text-sm text-muted">{label}{children}</label>;
}
