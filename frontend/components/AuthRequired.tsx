"use client";
import Link from "next/link";
import { ReactNode, useEffect, useState } from "react";
import { token } from "@/services/api";

export function AuthRequired({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);

  useEffect(() => {
    setAuthenticated(Boolean(token()));
    setReady(true);
  }, []);

  if (!ready) {
    return <div className="skeleton h-36 rounded-lg" />;
  }

  if (!authenticated) {
    return (
      <div className="rounded-lg border border-line bg-panel p-5">
        <h2 className="text-lg font-semibold">Authentication required</h2>
        <p className="mt-2 text-sm text-zinc-400">Login or create an account to access portfolio and paper trading.</p>
        <div className="mt-4 flex gap-3">
          <Link href="/login" className="rounded bg-buy px-4 py-2 text-sm font-semibold text-black">Login</Link>
          <Link href="/register" className="rounded border border-line px-4 py-2 text-sm text-zinc-200">Register</Link>
        </div>
      </div>
    );
  }

  return children;
}
