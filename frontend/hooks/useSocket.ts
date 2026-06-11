"use client";
import { useEffect, useState } from "react";
import { API } from "@/services/api";

export function useSocket(path = "/ws") {
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    const url = API.websocket(path);
    const socket = new WebSocket(url);
    socket.onopen = () => setConnected(true);
    socket.onclose = () => setConnected(false);
    socket.onmessage = (event) => setLastEvent(JSON.parse(event.data));
    return () => socket.close();
  }, [path]);

  return { connected, lastEvent };
}
