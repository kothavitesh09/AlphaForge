"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { auth } from "@/services/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try { await auth("/auth/login", { email, password }); router.push("/dashboard"); } catch (err) { setError(err instanceof Error ? err.message : "Login failed"); }
  }
  return <AuthFrame title="Login" error={error} submit={submit} email={email} setEmail={setEmail} password={password} setPassword={setPassword} footer={<Link href="/register" className="text-buy">Create account</Link>} />;
}

function AuthFrame(props: { title: string; error: string; submit: (e: React.FormEvent) => void; email: string; setEmail: (v: string) => void; password: string; setPassword: (v: string) => void; footer: React.ReactNode }) {
  return <main className="grid min-h-screen place-items-center bg-ink p-4"><form onSubmit={props.submit} className="w-full max-w-md rounded-lg border border-line bg-panel p-6"><h1 className="mb-5 text-2xl font-semibold">{props.title}</h1><input placeholder="Email" value={props.email} onChange={(e) => props.setEmail(e.target.value)} className="mb-3 w-full rounded border border-line bg-ink p-3" /><input placeholder="Password" type="password" value={props.password} onChange={(e) => props.setPassword(e.target.value)} className="mb-4 w-full rounded border border-line bg-ink p-3" /><button className="w-full rounded bg-buy p-3 font-semibold text-black">{props.title}</button>{props.error && <div className="mt-3 text-sm text-sell">{props.error}</div>}<div className="mt-4 text-sm text-zinc-400">{props.footer}</div></form></main>;
}
