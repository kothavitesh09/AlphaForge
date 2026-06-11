from datetime import datetime, timezone
from typing import Any
import logging
import httpx
import pandas as pd
from app.core.config import get_settings


logger = logging.getLogger(__name__)


class KoinBXClient:
    def __init__(self) -> None:
        self.base_url = get_settings().koinbx_base_url.rstrip("/")

    async def _get_first(self, paths: list[str], params: dict | None = None) -> Any:
        async with httpx.AsyncClient(timeout=12) as client:
            errors: list[str] = []
            for path in paths:
                try:
                    response = await client.get(f"{self.base_url}{path}", params=params)
                    if response.status_code < 400:
                        logger.info("KoinBX API response path=%s status=%s", path, response.status_code)
                        return response.json()
                    errors.append(f"{path}:{response.status_code}")
                except httpx.HTTPError as exc:
                    errors.append(f"{path}:{exc.__class__.__name__}")
        raise RuntimeError(f"KoinBX market data unavailable ({', '.join(errors)})")

    async def tickers(self) -> list[dict]:
        payload = await self._get_first(["/ticker", "/api/v2/tickers", "/api/v1/tickers", "/tickers"])
        raw = payload.get("data", payload) if isinstance(payload, dict) else payload
        if isinstance(raw, dict) and "tickers" in raw:
            raw = raw["tickers"]
        if isinstance(raw, dict):
            raw = [{"symbol": key, **value} if isinstance(value, dict) else {"symbol": key, "last": value} for key, value in raw.items()]
        return [self._normalize_ticker(item) for item in raw if isinstance(item, dict)]

    async def ticker(self, symbol: str) -> dict:
        symbol = symbol.upper()
        for item in await self.tickers():
            if item["symbol"].upper().replace("/", "").replace("_", "") == symbol.replace("/", "").replace("_", ""):
                return item
        payload = await self._get_first([f"/ticker/{symbol}", f"/api/v2/tickers/{symbol}", f"/api/v1/tickers/{symbol}"])
        return self._normalize_ticker(payload.get("data", payload) if isinstance(payload, dict) else payload)

    async def candles(self, symbol: str, interval: str = "1h", limit: int = 240) -> list[dict]:
        try:
            payload = await self._get_first(
                ["/api/v2/klines", "/api/v2/candles", "/api/v1/klines", "/api/v1/candles"],
                {"symbol": symbol.upper(), "market": symbol.upper(), "market_pair": symbol.upper(), "interval": interval, "limit": limit},
            )
            raw = payload.get("data", payload) if isinstance(payload, dict) else payload
            if isinstance(raw, dict):
                raw = raw.get("candles") or raw.get("klines") or raw.get("result") or raw.get("items") or []
            candles = [self._normalize_candle(item) for item in raw if item]
            return [item for item in candles if item["close"] > 0]
        except RuntimeError:
            return await self.trade_candles(symbol, interval, limit)

    async def discover_historical_endpoints(self, symbol: str, interval: str) -> list[dict]:
        endpoints = ["/api/v2/klines", "/api/v2/candles", "/api/v1/klines", "/api/v1/candles"]
        results: list[dict] = []
        async with httpx.AsyncClient(timeout=12) as client:
            for path in endpoints:
                params = {"symbol": symbol.upper(), "market": symbol.upper(), "market_pair": symbol.upper(), "interval": interval, "limit": 1000}
                try:
                    response = await client.get(f"{self.base_url}{path}", params=params)
                    count = 0
                    if response.status_code < 400:
                        payload = response.json()
                        raw = payload.get("data", payload) if isinstance(payload, dict) else payload
                        if isinstance(raw, dict):
                            raw = raw.get("candles") or raw.get("klines") or raw.get("result") or raw.get("items") or []
                        count = len(raw) if isinstance(raw, list) else 0
                    results.append({"path": path, "status_code": response.status_code, "available": response.status_code < 400, "sample_count": count})
                except httpx.HTTPError as exc:
                    results.append({"path": path, "status_code": None, "available": False, "error": exc.__class__.__name__})
        return results

    async def order_book(self, symbol: str) -> dict:
        payload = await self._get_first(
            ["/orderbook", "/api/v2/depth", "/api/v2/order_book", "/api/v1/depth", "/api/v1/order_book"],
            {"market_pair": symbol.upper()},
        )
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        return {"bids": data.get("bids", data.get("buy", [])), "asks": data.get("asks", data.get("sell", []))}

    async def trade_candles(self, symbol: str, interval: str, limit: int) -> list[dict]:
        payload = await self._get_first(["/trades"], {"market_pair": symbol.upper()})
        raw = payload.get("data", payload) if isinstance(payload, dict) else payload
        if isinstance(raw, dict):
            raw = raw.get("trades") or raw.get("result") or raw.get("items") or []
        trades = [self._normalize_trade(item) for item in raw if isinstance(item, dict)]
        if not trades:
            return []
        df = pd.DataFrame(trades)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp").sort_index()
        rule = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h", "1d": "1D"}.get(interval, "1h")
        candles = df.resample(rule).agg(open=("price", "first"), high=("price", "max"), low=("price", "min"), close=("price", "last"), volume=("quantity", "sum")).dropna()
        return [
            {"timestamp": index.to_pydatetime().isoformat(), "open": float(row.open), "high": float(row.high), "low": float(row.low), "close": float(row.close), "volume": float(row.volume)}
            for index, row in candles.tail(limit).iterrows()
        ]

    def _normalize_ticker(self, item: dict) -> dict:
        symbol = str(item.get("symbol") or item.get("market") or item.get("pair") or item.get("trading_pairs") or "").upper()
        return {
            "symbol": symbol,
            "last": self._float(item.get("last") or item.get("last_price") or item.get("last_traded_price") or item.get("close") or item.get("price")),
            "change_24h": self._float(item.get("change_24h") or item.get("price_change_percent") or item.get("price_change_percent_24h") or item.get("change")),
            "volume_24h": self._float(item.get("volume") or item.get("volume_24h") or item.get("base_volume") or item.get("base_volume_24h") or item.get("quote_volume")),
            "high_24h": self._float(item.get("high") or item.get("high_24h") or item.get("highest_price_24h")),
            "low_24h": self._float(item.get("low") or item.get("low_24h") or item.get("lowest_price_24h")),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _normalize_candle(self, item: Any) -> dict:
        if isinstance(item, list):
            ts, open_, high, low, close, volume = (item + [0, 0, 0, 0, 0, 0])[:6]
        else:
            ts = item.get("timestamp") or item.get("time") or item.get("date")
            open_, high, low, close, volume = item.get("open"), item.get("high"), item.get("low"), item.get("close"), item.get("volume")
        return {
            "timestamp": datetime.fromtimestamp(float(ts) / 1000 if float(ts or 0) > 10_000_000_000 else float(ts or 0), timezone.utc).isoformat() if ts else datetime.now(timezone.utc).isoformat(),
            "open": float(open_ or 0),
            "high": float(high or 0),
            "low": float(low or 0),
            "close": float(close or 0),
            "volume": float(volume or 0),
        }

    def _normalize_trade(self, item: dict) -> dict:
        timestamp = item.get("timestamp") or item.get("trade_timestamp") or item.get("created_at") or datetime.now(timezone.utc).isoformat()
        if isinstance(timestamp, (int, float)) or str(timestamp).isdigit():
            numeric = float(timestamp)
            timestamp = datetime.fromtimestamp(numeric / 1000 if numeric > 10_000_000_000 else numeric, timezone.utc).isoformat()
        return {
            "timestamp": timestamp,
            "price": self._float(item.get("price") or item.get("trade_price")),
            "quantity": self._float(item.get("quantity") or item.get("amount") or item.get("base_volume")),
        }

    def _float(self, value: Any) -> float:
        try:
            return float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            return 0.0
