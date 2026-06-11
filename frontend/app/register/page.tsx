"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { API, auth } from "@/services/api";

export default function RegisterPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try { await auth(API.register, { name, email, password }); router.push("/dashboard"); } catch (err) { setError(err instanceof Error ? err.message : "Registration failed"); }
  }
  return <main className="grid min-h-screen place-items-center bg-ink p-4"><form onSubmit={submit} className="w-full max-w-md rounded-lg border border-line bg-panel p-6"><h1 className="mb-5 text-2xl font-semibold">Register</h1><input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} className="mb-3 w-full rounded border border-line bg-ink p-3" /><input placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} className="mb-3 w-full rounded border border-line bg-ink p-3" /><input placeholder="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="mb-4 w-full rounded border border-line bg-ink p-3" /><button className="w-full rounded bg-buy p-3 font-semibold text-black">Register</button>{error && <div className="mt-3 text-sm text-sell">{error}</div>}<div className="mt-4 text-sm text-zinc-400"><Link href="/login" className="text-buy">Login</Link></div></form></main>;
}
