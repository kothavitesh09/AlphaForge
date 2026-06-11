"use client";
import { useEffect, useState } from "react";

export function useSocket(path = "/ws") {
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    const api = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";
    const url = api.replace(/^http/, "ws").replace(/\/api$/, path);
    const socket = new WebSocket(url);
    socket.onopen = () => setConnected(true);
    socket.onclose = () => setConnected(false);
    socket.onmessage = (event) => setLastEvent(JSON.parse(event.data));
    return () => socket.close();
  }, [path]);

  return { connected, lastEvent };
}
