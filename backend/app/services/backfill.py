import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import httpx
from pymongo import UpdateOne
from pymongo.errors import BulkWriteError
from app.core.config import SUPPORTED_INTERVALS, SUPPORTED_SYMBOLS
from app.services.advanced_indicators import persist_latest_indicators


logger = logging.getLogger(__name__)

INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}

COINDCX_INTERVALS = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}

COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "TRX": "tron",
    "DOT": "polkadot",
    "AVAX": "avalanche-2",
    "ATOM": "cosmos",
    "BDX": "beldex",
    "ADA": "cardano",
    "LINK": "chainlink",
    "MATIC": "matic-network",
}


@dataclass(frozen=True)
class SourceResult:
    source: str
    status: str
    earliest: str | None
    latest: str | None
    candles: list[dict]
    message: str | None = None


class HistoricalProvider:
    name = "provider"

    async def probe(self, symbol: str, interval: str) -> SourceResult:
        raise NotImplementedError

    async def pages(self, symbol: str, interval: str, resume_before: str | None = None):
        raise NotImplementedError


class KoinBXHistoricalProvider(HistoricalProvider):
    name = "koinbx"

    def __init__(self) -> None:
        self.base_url = os.getenv("KOINBX_BASE_URL", "https://api.koinbx.com").rstrip("/")
        self.paths = ("/api/v2/klines", "/api/v2/candles", "/api/v1/klines", "/api/v1/candles")

    async def probe(self, symbol: str, interval: str) -> SourceResult:
        async with httpx.AsyncClient(timeout=20) as client:
            errors = []
            for path in self.paths:
                params = {"symbol": symbol, "market": symbol, "market_pair": symbol, "interval": interval, "limit": 1000}
                try:
                    response = await client.get(f"{self.base_url}{path}", params=params)
                    if response.status_code >= 400:
                        errors.append(f"{path}:{response.status_code}")
                        continue
                    candles = [_normalize_api_candle(symbol, interval, item, self.name) for item in _extract_rows(response.json())]
                    candles = [item for item in candles if _valid_candle(item)]
                    return _source_result(self.name, candles, "available" if candles else "empty", ",".join(errors) or None)
                except Exception as exc:
                    errors.append(f"{path}:{exc.__class__.__name__}")
        return SourceResult(self.name, "unavailable", None, None, [], ",".join(errors))

    async def pages(self, symbol: str, interval: str, resume_before: str | None = None):
        result = await self.probe(symbol, interval)
        if result.candles:
            yield result.candles


class CoinDCXHistoricalProvider(HistoricalProvider):
    name = "coindcx"

    def __init__(self) -> None:
        self.candles_url = "https://public.coindcx.com/market_data/candles"
        self.markets_url = "https://api.coindcx.com/exchange/v1/markets_details"
        self._pairs: dict[str, str] | None = None
        self.page_size = int(os.getenv("BACKFILL_PAGE_SIZE", "500"))

    async def probe(self, symbol: str, interval: str) -> SourceResult:
        pair = await self._pair(symbol)
        if not pair:
            return SourceResult(self.name, "unavailable", None, None, [], "pair_not_listed")
        candles = await self._fetch(pair, interval, None, None)
        normalized = [_normalize_coindcx(symbol, interval, row) for row in candles]
        normalized = [item for item in normalized if _valid_candle(item)]
        return _source_result(self.name, normalized, "available" if normalized else "empty", None)

    async def pages(self, symbol: str, interval: str, resume_before: str | None = None):
        pair = await self._pair(symbol)
        if not pair:
            return
        end_ms = _to_ms(resume_before) - INTERVAL_MS[interval] if resume_before else int(datetime.now(timezone.utc).timestamp() * 1000)
        empty_pages = 0
        while end_ms > 0:
            start_ms = max(0, end_ms - (INTERVAL_MS[interval] * self.page_size))
            rows = await self._fetch(pair, interval, start_ms, end_ms)
            normalized = [_normalize_coindcx(symbol, interval, row) for row in rows]
            normalized = [item for item in normalized if _valid_candle(item)]
            if not normalized:
                empty_pages += 1
                if empty_pages >= 2:
                    break
                end_ms = start_ms - INTERVAL_MS[interval]
                continue
            empty_pages = 0
            normalized.sort(key=lambda item: item["timestamp"])
            yield normalized
            oldest_ms = min(_to_ms(item["timestamp"]) for item in normalized)
            next_end = oldest_ms - INTERVAL_MS[interval]
            if next_end >= end_ms:
                break
            end_ms = next_end
            await asyncio.sleep(0.08)

    async def _fetch(self, pair: str, interval: str, start_ms: int | None, end_ms: int | None) -> list[dict]:
        params: dict[str, Any] = {"pair": pair, "interval": COINDCX_INTERVALS[interval]}
        if start_ms is not None:
            params["startTime"] = start_ms
        if end_ms is not None:
            params["endTime"] = end_ms
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(self.candles_url, params=params)
            response.raise_for_status()
            payload = response.json()
        return payload if isinstance(payload, list) else []

    async def _pair(self, symbol: str) -> str | None:
        if self._pairs is None:
            self._pairs = await self._load_pairs()
        return self._pairs.get(symbol)

    async def _load_pairs(self) -> dict[str, str]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(self.markets_url)
            response.raise_for_status()
            markets = response.json()
        pairs = {}
        for market in markets:
            base = str(market.get("base_currency_short_name", "")).upper()
            target = str(market.get("target_currency_short_name", "")).upper()
            candle_pair = str(market.get("pair") or market.get("coindcx_name") or "")
            if base == "INR" and target:
                pairs[f"{target}_INR"] = candle_pair
        for symbol in SUPPORTED_SYMBOLS:
            pairs.setdefault(symbol, f"I-{symbol}")
        return pairs


class CoinGeckoHistoricalProvider(HistoricalProvider):
    name = "coingecko"

    async def probe(self, symbol: str, interval: str) -> SourceResult:
        if interval not in {"1d"}:
            return SourceResult(self.name, "unavailable", None, None, [], "coingecko_public_range_is_not_ohlcv_for_intraday")
        if not os.getenv("COINGECKO_API_KEY"):
            return SourceResult(self.name, "auth_required", None, None, [], "COINGECKO_API_KEY not configured")
        return SourceResult(self.name, "auth_required", None, None, [], "configured client not enabled for storage without OHLCV endpoint verification")

    async def pages(self, symbol: str, interval: str, resume_before: str | None = None):
        return
        yield


class CryptoCompareHistoricalProvider(HistoricalProvider):
    name = "cryptocompare"

    async def probe(self, symbol: str, interval: str) -> SourceResult:
        if not os.getenv("CRYPTOCOMPARE_API_KEY"):
            return SourceResult(self.name, "auth_required", None, None, [], "CRYPTOCOMPARE_API_KEY not configured")
        return SourceResult(self.name, "auth_required", None, None, [], "API key configured, paginated client not selected because CoinDCX INR source is available")

    async def pages(self, symbol: str, interval: str, resume_before: str | None = None):
        return
        yield


class BackfillService:
    def __init__(self, db, providers: list[HistoricalProvider] | None = None) -> None:
        self.db = db
        self.providers = providers or [
            CoinDCXHistoricalProvider(),
            KoinBXHistoricalProvider(),
            CoinGeckoHistoricalProvider(),
            CryptoCompareHistoricalProvider(),
        ]

    async def run(
        self,
        symbols: list[str] | None = None,
        intervals: list[str] | None = None,
        max_pages_per_pair: int | None = None,
    ) -> dict:
        symbols = [s.upper() for s in (symbols or list(SUPPORTED_SYMBOLS)) if s.upper() in SUPPORTED_SYMBOLS]
        intervals = [i for i in (intervals or list(SUPPORTED_INTERVALS)) if i in SUPPORTED_INTERVALS]
        started_at = _utc_now()
        run = {
            "status": "running",
            "started_at": started_at,
            "symbols": symbols,
            "intervals": intervals,
            "records_downloaded": 0,
            "symbols_completed": 0,
            "created_at": started_at,
            "updated_at": started_at,
        }
        await self.db.backfill_runs.insert_one(run)
        summary = {"started_at": started_at.isoformat(), "records_downloaded": 0, "inserted": 0, "updated": 0, "failed": 0, "pairs": []}
        completed_symbols = set()
        for symbol in symbols:
            symbol_ok = True
            for interval in intervals:
                pair_result = await self.backfill_pair(symbol, interval, max_pages_per_pair=max_pages_per_pair)
                summary["records_downloaded"] += pair_result.get("records_downloaded", 0)
                summary["inserted"] += pair_result.get("inserted", 0)
                summary["updated"] += pair_result.get("updated", 0)
                summary["failed"] += 1 if pair_result.get("status") == "failed" else 0
                summary["pairs"].append(pair_result)
                symbol_ok = symbol_ok and pair_result.get("status") in {"completed", "unavailable"}
                await self.db.backfill_runs.update_one({"started_at": started_at}, {"$set": {**summary, "updated_at": _utc_now()}})
            if symbol_ok:
                completed_symbols.add(symbol)
        summary["symbols_completed"] = len(completed_symbols)
        summary["finished_at"] = _utc_now().isoformat()
        await self.db.backfill_runs.update_one(
            {"started_at": started_at},
            {"$set": {"status": "completed", **summary, "updated_at": _utc_now()}},
            upsert=True,
        )
        return summary

    async def backfill_pair(self, symbol: str, interval: str, max_pages_per_pair: int | None = None) -> dict:
        status_key = {"symbol": symbol.upper(), "interval": interval}
        now = _utc_now()
        existing_status = await self.db.backfill_status.find_one(status_key)
        resume_before = existing_status.get("oldest_downloaded") if existing_status else None
        await self.db.backfill_status.update_one(
            status_key,
            {
                "$set": {"status": "running", "updated_at": now},
                "$setOnInsert": {"records_downloaded": 0, "created_at": now, "started_at": now},
            },
            upsert=True,
        )
        probes = []
        for provider in self.providers:
            result = await provider.probe(symbol, interval)
            probes.append(result)
            if result.candles:
                break
        selected = self._select_source(probes)
        if not selected:
            result = {
                **status_key,
                "status": "unavailable",
                "source": None,
                "records_downloaded": 0,
                "inserted": 0,
                "updated": 0,
                "oldest_downloaded": resume_before,
                "newest_downloaded": existing_status.get("newest_downloaded") if existing_status else None,
                "source_discovery": [_result_dict(item) for item in probes],
                "error": "No source returned historical OHLCV candles",
                "updated_at": _utc_now(),
            }
            await self.db.backfill_status.update_one(status_key, {"$set": result}, upsert=True)
            return _serializable(result)

        provider = next(provider for provider in self.providers if provider.name == selected.source)
        inserted = 0
        updated = 0
        downloaded = 0
        rejected = 0
        oldest = resume_before
        newest = existing_status.get("newest_downloaded") if existing_status else None
        pages = 0
        try:
            async for page in provider.pages(symbol, interval, resume_before=resume_before):
                pages += 1
                valid, invalid = self._validate_page(page)
                rejected += len(invalid)
                for record in invalid:
                    logger.warning("Rejected historical candle symbol=%s interval=%s source=%s reason=%s record=%s", symbol, interval, selected.source, record["reason"], record["record"])
                write_result = await self._bulk_upsert(valid)
                inserted += write_result["inserted"]
                updated += write_result["updated"]
                downloaded += len(valid)
                if valid:
                    page_oldest = min(item["timestamp"] for item in valid)
                    page_newest = max(item["timestamp"] for item in valid)
                    oldest = min([value for value in [oldest, page_oldest] if value])
                    newest = max([value for value in [newest, page_newest] if value])
                    await persist_latest_indicators(self.db, symbol, interval, valid)
                await self.db.backfill_status.update_one(
                    status_key,
                    {
                        "$inc": {"records_downloaded": len(valid), "rejected_records": len(invalid)},
                        "$set": {
                            "status": "running",
                            "source": selected.source,
                            "oldest_downloaded": oldest,
                            "newest_downloaded": newest,
                            "inserted": inserted,
                            "updated": updated,
                            "pages_downloaded": pages,
                            "updated_at": _utc_now(),
                        },
                    },
                    upsert=True,
                )
                if max_pages_per_pair and pages >= max_pages_per_pair:
                    break
            final_status = "partial" if max_pages_per_pair and pages >= max_pages_per_pair else "completed"
            result = {
                **status_key,
                "status": final_status,
                "source": selected.source,
                "records_downloaded": downloaded,
                "inserted": inserted,
                "updated": updated,
                "rejected_records": rejected,
                "oldest_downloaded": oldest,
                "newest_downloaded": newest,
                "oldest_available_reached": final_status == "completed",
                "pages_downloaded": pages,
                "source_discovery": [_result_dict(item) for item in probes],
                "updated_at": _utc_now(),
                "finished_at": _utc_now(),
                "error": None,
            }
            await self.db.backfill_status.update_one(status_key, {"$set": result}, upsert=True)
            return _serializable(result)
        except Exception as exc:
            logger.exception("Backfill failed symbol=%s interval=%s source=%s error=%s", symbol, interval, selected.source, exc)
            result = {
                **status_key,
                "status": "failed",
                "source": selected.source,
                "records_downloaded": downloaded,
                "inserted": inserted,
                "updated": updated,
                "oldest_downloaded": oldest,
                "newest_downloaded": newest,
                "source_discovery": [_result_dict(item) for item in probes],
                "error": str(exc),
                "updated_at": _utc_now(),
            }
            await self.db.backfill_status.update_one(status_key, {"$set": result}, upsert=True)
            return _serializable(result)

    async def status(self) -> dict:
        rows = [_serializable(row) async for row in self.db.backfill_status.find({}).sort([("symbol", 1), ("interval", 1)])]
        running = len([row for row in rows if row.get("status") == "running"])
        records = sum(int(row.get("records_downloaded", 0)) for row in rows)
        symbols_completed = len({row["symbol"] for row in rows if row.get("status") == "completed"})
        oldest = min([row.get("oldest_downloaded") for row in rows if row.get("oldest_downloaded")] or [None])
        newest = max([row.get("newest_downloaded") for row in rows if row.get("newest_downloaded")] or [None])
        return {
            "running": running > 0,
            "running_pairs": running,
            "records_downloaded": records,
            "symbols_completed": symbols_completed,
            "oldest_timestamp": oldest,
            "newest_timestamp": newest,
            "pairs": rows,
        }

    def _select_source(self, probes: list[SourceResult]) -> SourceResult | None:
        available = [item for item in probes if item.candles]
        if not available:
            return None
        return min(available, key=lambda item: item.earliest or "9999")

    def _validate_page(self, candles: list[dict]) -> tuple[list[dict], list[dict]]:
        valid = []
        invalid = []
        seen = set()
        for candle in candles:
            reason = _invalid_reason(candle)
            key = (candle.get("symbol"), candle.get("interval"), candle.get("timestamp"))
            if not reason and key in seen:
                reason = "duplicate_in_page"
            if reason:
                invalid.append({"reason": reason, "record": candle})
                continue
            seen.add(key)
            valid.append(candle)
        return valid, invalid

    async def _bulk_upsert(self, candles: list[dict]) -> dict:
        if not candles:
            return {"inserted": 0, "updated": 0}
        now = _utc_now()
        operations = [
            UpdateOne(
                {"symbol": item["symbol"], "interval": item["interval"], "timestamp": item["timestamp"]},
                {"$set": {**item, "updated_at": now}, "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
            for item in candles
        ]
        try:
            result = await self.db.market_data.bulk_write(operations, ordered=False)
        except BulkWriteError as exc:
            logger.warning("Backfill bulk write completed with duplicate conflicts: %s", exc.details)
            details = exc.details
            return {"inserted": int(details.get("nUpserted", 0)), "updated": int(details.get("nModified", 0))}
        return {"inserted": int(result.upserted_count), "updated": int(result.modified_count)}


class BackfillTaskManager:
    def __init__(self) -> None:
        self.task: asyncio.Task | None = None
        self.last_result: dict | None = None
        self.last_error: str | None = None

    def start(self, db, payload: dict | None = None) -> dict:
        if self.task and not self.task.done():
            return {"status": "already_running"}
        payload = payload or {}
        self.task = asyncio.create_task(self._run(db, payload))
        return {"status": "started"}

    async def _run(self, db, payload: dict) -> None:
        try:
            self.last_result = await BackfillService(db).run(
                symbols=payload.get("symbols"),
                intervals=payload.get("intervals"),
                max_pages_per_pair=payload.get("max_pages_per_pair"),
            )
            self.last_error = None
        except Exception as exc:
            self.last_error = str(exc)
            logger.exception("Backfill task failed: %s", exc)

    def running(self) -> bool:
        return bool(self.task and not self.task.done())


backfill_manager = BackfillTaskManager()


def _normalize_coindcx(symbol: str, interval: str, row: dict) -> dict:
    return {
        "symbol": symbol.upper(),
        "interval": interval,
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
        values = (row + [None, None, None, None, None, None])[:6]
        ts, open_, high, low, close, volume = values
    else:
        ts = row.get("timestamp") or row.get("time") or row.get("date")
        open_, high, low, close, volume = row.get("open"), row.get("high"), row.get("low"), row.get("close"), row.get("volume")
    return {
        "symbol": symbol.upper(),
        "interval": interval,
        "timestamp": _parse_timestamp(ts),
        "open": _float(open_),
        "high": _float(high),
        "low": _float(low),
        "close": _float(close),
        "volume": _float(volume),
        "source": source,
    }


def _extract_rows(payload: Any) -> list:
    raw = payload.get("data", payload) if isinstance(payload, dict) else payload
    if isinstance(raw, dict):
        raw = raw.get("candles") or raw.get("klines") or raw.get("result") or raw.get("items") or []
    return raw if isinstance(raw, list) else []


def _source_result(source: str, candles: list[dict], status: str, message: str | None) -> SourceResult:
    oldest = min((item["timestamp"] for item in candles), default=None)
    latest = max((item["timestamp"] for item in candles), default=None)
    return SourceResult(source, status, oldest, latest, candles, message)


def _invalid_reason(candle: dict) -> str | None:
    if not candle.get("timestamp"):
        return "missing_timestamp"
    values = [candle.get("open"), candle.get("high"), candle.get("low"), candle.get("close")]
    if any(value is None or float(value) <= 0 for value in values):
        return "invalid_ohlc"
    if float(candle["high"]) < max(float(candle["open"]), float(candle["close"]), float(candle["low"])):
        return "invalid_high"
    if float(candle["low"]) > min(float(candle["open"]), float(candle["close"]), float(candle["high"])):
        return "invalid_low"
    if float(candle.get("volume", 0)) < 0:
        return "negative_volume"
    return None


def _valid_candle(candle: dict) -> bool:
    return _invalid_reason(candle) is None


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
    return dt.astimezone(timezone.utc).replace(second=0, microsecond=0).isoformat().replace("+00:00", "Z")


def _to_ms(value: str | None) -> int:
    if not value:
        return int(datetime.now(timezone.utc).timestamp() * 1000)
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def _float(value: Any) -> float:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _result_dict(result: SourceResult) -> dict:
    return {
        "source": result.source,
        "status": result.status,
        "earliest": result.earliest,
        "latest": result.latest,
        "sample_count": len(result.candles),
        "message": result.message,
    }


def _serializable(document: dict) -> dict:
    item = dict(document)
    item.pop("_id", None)
    for key, value in list(item.items()):
        if isinstance(value, datetime):
            item[key] = value.isoformat().replace("+00:00", "Z")
    return item
