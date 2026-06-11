import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import SUPPORTED_INTERVALS, SUPPORTED_SYMBOLS, get_settings


logger = logging.getLogger(__name__)

COINDCX_INTERVALS = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}


class CoinDCXClient:
    name = "coindcx"

    def __init__(self) -> None:
        settings = get_settings()
        self.candles_url = settings.coindcx_candles_url
        self.markets_url = settings.coindcx_markets_url
        self.tickers_url = settings.coindcx_tickers_url
        self.order_book_url = settings.coindcx_order_book_url
        self._pairs: dict[str, str] | None = None

    async def tickers(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(self.tickers_url)
            response.raise_for_status()
            payload = response.json()
        rows = payload if isinstance(payload, list) else payload.get("data", []) if isinstance(payload, dict) else []
        tickers = [self._normalize_ticker(row) for row in rows if isinstance(row, dict)]
        return [item for item in tickers if item["symbol"] in SUPPORTED_SYMBOLS and item["last"] > 0]

    async def ticker(self, symbol: str) -> dict:
        symbol = symbol.upper()
        for item in await self.tickers():
            if item["symbol"] == symbol:
                return item
        raise RuntimeError(f"CoinDCX ticker unavailable symbol={symbol}")

    async def candles(self, symbol: str, interval: str = "1h", limit: int = 240) -> list[dict]:
        symbol = symbol.upper()
        interval = _normalize_interval(interval)
        pair = await self._pair(symbol)
        if not pair:
            raise RuntimeError(f"CoinDCX pair unavailable symbol={symbol}")
        end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_ms = end_ms - (_interval_ms(interval) * max(limit + 5, 10))
        params = {
            "pair": pair,
            "interval": COINDCX_INTERVALS[interval],
            "startTime": start_ms,
            "endTime": end_ms,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(self.candles_url, params=params)
            response.raise_for_status()
            payload = response.json()
        rows = payload if isinstance(payload, list) else []
        candles = [_normalize_coindcx_candle(symbol, interval, row) for row in rows if isinstance(row, dict)]
        candles = [item for item in candles if _valid_candle(item)]
        candles.sort(key=lambda item: item["timestamp"])
        return candles[-limit:]

    async def order_book(self, symbol: str) -> dict:
        pair = await self._pair(symbol.upper())
        if not pair:
            return {"bids": [], "asks": []}
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get(self.order_book_url, params={"pair": pair})
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        bids = data.get("bids", []) if isinstance(data, dict) else []
        asks = data.get("asks", []) if isinstance(data, dict) else []
        return {"bids": _book_rows(bids), "asks": _book_rows(asks)}

    async def _pair(self, symbol: str) -> str | None:
        if self._pairs is None:
            self._pairs = await self._load_pairs()
        return self._pairs.get(symbol.upper())

    async def _load_pairs(self) -> dict[str, str]:
        pairs: dict[str, str] = {}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(self.markets_url)
                response.raise_for_status()
                markets = response.json()
            for market in markets if isinstance(markets, list) else []:
                base = str(market.get("base_currency_short_name", "")).upper()
                target = str(market.get("target_currency_short_name", "")).upper()
                candle_pair = str(market.get("pair") or market.get("coindcx_name") or "")
                if base == "INR" and target and candle_pair:
                    pairs[f"{target}_INR"] = candle_pair
        except httpx.HTTPError as exc:
            logger.warning("CoinDCX markets lookup failed error=%s", exc.__class__.__name__)
        for symbol in SUPPORTED_SYMBOLS:
            pairs.setdefault(symbol, f"I-{symbol}")
        return pairs

    def _normalize_ticker(self, item: dict) -> dict:
        symbol = _normalize_symbol(item.get("market") or item.get("symbol") or item.get("pair") or item.get("coindcx_name"))
        return {
            "symbol": symbol,
            "last": _float(item.get("last_price") or item.get("last") or item.get("close") or item.get("price")),
            "change_24h": _float(item.get("change_24_hour") or item.get("change_24h") or item.get("price_change_percent")),
            "volume_24h": _float(item.get("volume") or item.get("volume_24h") or item.get("base_volume") or item.get("quote_volume")),
            "high_24h": _float(item.get("high") or item.get("high_24h")),
            "low_24h": _float(item.get("low") or item.get("low_24h")),
            "timestamp": _utc_iso(datetime.now(timezone.utc)),
            "source": self.name,
        }


class KoinBXFallbackClient:
    name = "koinbx"

    def __init__(self) -> None:
        self.base_url = get_settings().koinbx_base_url.rstrip("/")

    async def tickers(self) -> list[dict]:
        payload = await self._get("/api/v2/tickers")
        raw = payload.get("data", payload) if isinstance(payload, dict) else payload
        if isinstance(raw, dict):
            raw = raw.get("tickers") or [{"symbol": key, **value} for key, value in raw.items() if isinstance(value, dict)]
        return [self._normalize_ticker(item) for item in raw if isinstance(item, dict)]

    async def ticker(self, symbol: str) -> dict:
        symbol = symbol.upper()
        for item in await self.tickers():
            if item["symbol"] == symbol:
                return item
        raise RuntimeError(f"KoinBX fallback ticker unavailable symbol={symbol}")

    async def candles(self, symbol: str, interval: str = "1h", limit: int = 240) -> list[dict]:
        payload = await self._get(
            "/api/v2/klines",
            {"symbol": symbol.upper(), "market": symbol.upper(), "market_pair": symbol.upper(), "interval": interval, "limit": limit},
        )
        raw = payload.get("data", payload) if isinstance(payload, dict) else payload
        if isinstance(raw, dict):
            raw = raw.get("candles") or raw.get("klines") or raw.get("result") or raw.get("items") or []
        candles = [_normalize_api_candle(symbol, interval, row, self.name) for row in raw if row]
        candles = [item for item in candles if _valid_candle(item)]
        candles.sort(key=lambda item: item["timestamp"])
        return candles[-limit:]

    async def order_book(self, symbol: str) -> dict:
        payload = await self._get("/api/v2/depth", {"market_pair": symbol.upper()})
        data = payload.get("data", payload) if isinstance(payload, dict) else {}
        return {"bids": data.get("bids", data.get("buy", [])), "asks": data.get("asks", data.get("sell", []))}

    async def _get(self, path: str, params: dict | None = None) -> Any:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get(f"{self.base_url}{path}", params=params)
            response.raise_for_status()
            return response.json()

    def _normalize_ticker(self, item: dict) -> dict:
        symbol = _normalize_symbol(item.get("symbol") or item.get("market") or item.get("pair") or item.get("trading_pairs"))
        return {
            "symbol": symbol,
            "last": _float(item.get("last") or item.get("last_price") or item.get("last_traded_price") or item.get("close") or item.get("price")),
            "change_24h": _float(item.get("change_24h") or item.get("price_change_percent") or item.get("price_change_percent_24h") or item.get("change")),
            "volume_24h": _float(item.get("volume") or item.get("volume_24h") or item.get("base_volume") or item.get("base_volume_24h") or item.get("quote_volume")),
            "high_24h": _float(item.get("high") or item.get("high_24h") or item.get("highest_price_24h")),
            "low_24h": _float(item.get("low") or item.get("low_24h") or item.get("lowest_price_24h")),
            "timestamp": _utc_iso(datetime.now(timezone.utc)),
            "source": self.name,
        }


class MarketDataClient:
    name = "coindcx"

    def __init__(self) -> None:
        settings = get_settings()
        self.primary = CoinDCXClient()
        self.fallback = KoinBXFallbackClient() if settings.koinbx_fallback_enabled else None
        self.active_provider = self.primary.name

    async def tickers(self) -> list[dict]:
        return await self._with_fallback("tickers")

    async def ticker(self, symbol: str) -> dict:
        return await self._with_fallback("ticker", symbol)

    async def candles(self, symbol: str, interval: str = "1h", limit: int = 240) -> list[dict]:
        return await self._with_fallback("candles", symbol, interval, limit)

    async def order_book(self, symbol: str) -> dict:
        try:
            return await self._with_fallback("order_book", symbol)
        except Exception:
            return {"bids": [], "asks": []}

    async def _with_fallback(self, method: str, *args):
        try:
            self.active_provider = self.primary.name
            return await getattr(self.primary, method)(*args)
        except Exception as exc:
            if not self.fallback:
                raise
            logger.warning("CoinDCX %s failed, using KoinBX fallback error=%s", method, exc)
            self.active_provider = self.fallback.name
            return await getattr(self.fallback, method)(*args)


KoinBXClient = KoinBXFallbackClient


def _normalize_coindcx_candle(symbol: str, interval: str, row: dict) -> dict:
    return {
        "symbol": symbol.upper(),
        "interval": _normalize_interval(interval),
        "timestamp": _parse_timestamp(row.get("time")),
        "open": _float(row.get("open")),
        "high": _float(row.get("high")),
        "low": _float(row.get("low")),
        "close": _float(row.get("close")),
        "volume": _float(row.get("volume")),
        "source": "coindcx",
    }


def _normalize_api_candle(symbol: str, interval: str, row: Any, source: str) -> dict:
    if isinstance(row, list):
        ts, open_, high, low, close, volume = (row + [None, None, None, None, None, None])[:6]
    else:
        ts = row.get("timestamp") or row.get("time") or row.get("date")
        open_, high, low, close, volume = row.get("open"), row.get("high"), row.get("low"), row.get("close"), row.get("volume")
    return {
        "symbol": symbol.upper(),
        "interval": _normalize_interval(interval),
        "timestamp": _parse_timestamp(ts),
        "open": _float(open_),
        "high": _float(high),
        "low": _float(low),
        "close": _float(close),
        "volume": _float(volume),
        "source": source,
    }


def _book_rows(value: Any) -> list:
    if isinstance(value, dict):
        return [[price, qty] for price, qty in value.items()]
    return value if isinstance(value, list) else []


def _normalize_symbol(value: Any) -> str:
    text = str(value or "").upper().replace("/", "_").replace("-", "_")
    if text.startswith("I-"):
        text = text[2:]
    if text.startswith("B-"):
        text = text[2:]
    if text.endswith("INR") and not text.endswith("_INR"):
        text = f"{text[:-3]}_INR"
    return text


def _normalize_interval(value: str) -> str:
    interval = str(value or "1h").lower()
    return interval if interval in SUPPORTED_INTERVALS else "1h"


def _interval_ms(interval: str) -> int:
    return {
        "1m": 60_000,
        "5m": 300_000,
        "15m": 900_000,
        "1h": 3_600_000,
        "4h": 14_400_000,
        "1d": 86_400_000,
    }[_normalize_interval(interval)]


def _parse_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)) or str(value).isdigit():
        numeric = float(value)
        dt = datetime.fromtimestamp(numeric / 1000 if numeric > 10_000_000_000 else numeric, timezone.utc)
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return _utc_iso(dt.replace(second=0, microsecond=0))


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _float(value: Any) -> float:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _valid_candle(candle: dict) -> bool:
    return bool(
        candle.get("symbol")
        and candle.get("interval") in SUPPORTED_INTERVALS
        and candle.get("timestamp")
        and float(candle.get("open") or 0) > 0
        and float(candle.get("high") or 0) > 0
        and float(candle.get("low") or 0) > 0
        and float(candle.get("close") or 0) > 0
    )
