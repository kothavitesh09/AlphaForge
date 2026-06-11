"use client";
import { createChart, ColorType, UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { Candle } from "@/types";

export function MarketChart({ candles }: { candles: Candle[] }) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!ref.current || !candles.length) return;
    const chart = createChart(ref.current, {
      height: 360,
      layout: { background: { type: ColorType.Solid, color: "#10141b" }, textColor: "#a1a7b3" },
      grid: { vertLines: { color: "#1d2430" }, horzLines: { color: "#1d2430" } },
      rightPriceScale: { borderColor: "#242b36" },
      timeScale: { borderColor: "#242b36" }
    });
    const series = chart.addCandlestickSeries({ upColor: "#23d18b", downColor: "#ff5f68", borderVisible: false, wickUpColor: "#23d18b", wickDownColor: "#ff5f68" });
    series.setData(candles.map((c) => ({ time: Math.floor(new Date(c.timestamp).getTime() / 1000) as UTCTimestamp, open: c.open, high: c.high, low: c.low, close: c.close })));
    chart.timeScale().fitContent();
    const resize = () => chart.applyOptions({ width: ref.current?.clientWidth || 0 });
    resize();
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.remove(); };
  }, [candles]);
  return <div ref={ref} className="h-[360px] w-full rounded-lg border border-line bg-panel" />;
}
