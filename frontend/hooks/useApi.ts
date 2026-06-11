"use client";
import { useEffect, useState } from "react";
import { api } from "@/services/api";

export function useApi<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    api<T>(path)
      .then((value) => active && setData(value))
      .catch((err) => active && setError(err.message))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [path]);

  return { data, loading, error };
}
