import logging
from pymongo.uri_parser import parse_uri
from pymongo.errors import OperationFailure
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import get_settings


logger = logging.getLogger(__name__)
client: AsyncIOMotorClient | None = None
database_name: str | None = None

EXPECTED_COLLECTIONS = (
    "market_data",
    "indicator_data",
    "signals",
    "predictions",
    "prediction_results",
    "paper_trades",
    "portfolio",
    "portfolios",
    "accuracy_stats",
    "analytics_stats",
    "backfill_status",
    "backfill_runs",
    "backtest_results",
    "market_sentiment",
    "ml_datasets",
    "ml_features",
    "ml_labels",
    "ml_model_results",
    "ml_model_versions",
    "ml_predictions",
    "ensemble_predictions",
    "signal_validations",
    "settings",
    "users",
    "forecasts",
    "alpha_scores",
    "market_regimes",
    "opportunities",
    "ml_monitoring",
    "system_health",
    "job_runs",
)


async def connect_mongo() -> None:
    global client, database_name
    settings = get_settings()
    client = AsyncIOMotorClient(
        settings.mongodb_uri,
        uuidRepresentation="standard",
        serverSelectionTimeoutMS=5000,
        appname="AlphaForge",
    )
    database_name = _database_name(settings.mongodb_uri, settings.mongodb_database)
    await client.admin.command("ping")
    db = get_database()
    await ensure_collections(db)
    await ensure_indexes(db)
    logger.info("MongoDB Connected database=%s", db.name)


async def close_mongo() -> None:
    global client
    if client:
        client.close()
        client = None


def get_database() -> AsyncIOMotorDatabase:
    if client is None:
        raise RuntimeError("MongoDB is not connected")
    if database_name:
        return client[database_name]
    return client.get_default_database()


def _database_name(uri: str, fallback: str) -> str:
    try:
        default_db = parse_uri(uri).get("database")
        return default_db or fallback
    except Exception:
        return fallback


async def ensure_collections(db: AsyncIOMotorDatabase) -> None:
    existing = set(await db.list_collection_names())
    for name in EXPECTED_COLLECTIONS:
        if name not in existing:
            await db.create_collection(name)
            logger.info("MongoDB collection created collection=%s", name)


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    await _drop_legacy_market_data_index(db)
    await _ensure_index(db.users, [("email", 1)], unique=True)
    await _ensure_index(db.coins, [("symbol", 1)], unique=True)
    await _ensure_index(db.market_data, [("symbol", 1), ("interval", 1), ("timestamp", -1)], unique=True, name="market_data_symbol_interval_timestamp")
    await _ensure_index(db.market_data, [("interval", 1), ("timestamp", -1)], name="market_data_interval_timestamp")
    await _ensure_index(db.price_history, [("symbol", 1), ("timestamp", -1)])
    await _ensure_index(db.signals, [("symbol", 1), ("created_at", -1)], name="signals_symbol_created_at")
    await _ensure_index(db.signals, [("signal", 1), ("confidence", -1), ("created_at", -1)], name="signals_action_confidence_created_at")
    await _ensure_index(db.predictions, [("symbol", 1), ("created_at", -1)], name="predictions_symbol_created_at")
    await _ensure_index(db.predictions, [("timeframe", 1), ("created_at", -1)], name="predictions_timeframe_created_at")
    await _ensure_index(db.paper_trades, [("user_id", 1), ("created_at", -1)])
    await _ensure_index(db.paper_trades, [("symbol", 1), ("created_at", -1)], name="paper_trades_symbol_created_at")
    await _ensure_index(db.portfolios, [("user_id", 1)], unique=True)
    await _ensure_index(db.portfolio, [("user_id", 1)], unique=True)
    await _ensure_index(db.market_sentiment, [("created_at", 1)])
    await _ensure_index(db.social_sentiment, [("symbol", 1), ("created_at", -1)])
    await _ensure_index(db.prediction_results, [("symbol", 1), ("resolved_at", -1)])
    await _ensure_index(db.accuracy_stats, [("timeframe", 1), ("created_at", -1)])
    await _ensure_index(db.indicator_data, [("symbol", 1), ("interval", 1), ("timestamp", -1)], unique=True, name="indicator_symbol_interval_timestamp")
    await _ensure_index(db.indicator_data, [("symbol", 1), ("timeframe", 1), ("timestamp", -1)])
    await _ensure_index(db.backtest_results, [("symbol", 1), ("created_at", -1)])
    await _ensure_index(db.backfill_status, [("symbol", 1), ("interval", 1)], unique=True, name="backfill_symbol_interval")
    await _ensure_index(db.accuracy_stats, [("symbol", 1), ("timeframe", 1), ("created_at", -1)], name="accuracy_symbol_timeframe_created_at")
    await _ensure_index(db.analytics_stats, [("scope", 1), ("created_at", -1)], name="analytics_scope_created_at")
    await _ensure_index(db.market_sentiment, [("created_at", -1)], name="market_sentiment_created_at")
    await _ensure_index(db.ml_datasets, [("symbol", 1), ("timeframe", 1), ("created_at", -1)], name="ml_dataset_symbol_timeframe_created_at")
    await _ensure_index(db.ml_features, [("symbol", 1), ("timeframe", 1), ("timestamp", -1)], unique=True, name="ml_features_symbol_timeframe_timestamp")
    await _ensure_index(db.ml_labels, [("symbol", 1), ("timeframe", 1), ("timestamp", -1)], unique=True, name="ml_labels_symbol_timeframe_timestamp")
    await _ensure_index(db.ml_model_results, [("model", 1), ("timeframe", 1), ("created_at", -1)], name="ml_model_results_model_timeframe_created_at")
    await _ensure_index(db.ml_model_versions, [("model", 1), ("timeframe", 1), ("created_at", -1)], name="ml_model_versions_model_timeframe_created_at")
    await _ensure_index(db.ml_predictions, [("symbol", 1), ("timeframe", 1), ("timestamp", -1), ("model", 1)], name="ml_predictions_symbol_timeframe_timestamp_model")
    await _ensure_index(db.ensemble_predictions, [("symbol", 1), ("timeframe", 1), ("timestamp", -1)], unique=True, name="ensemble_symbol_timeframe_timestamp")
    await _ensure_index(db.signal_validations, [("signal_id", 1)], unique=True, name="signal_validation_signal_id")
    await _ensure_index(db.signal_validations, [("symbol", 1), ("created_at", -1)], name="signal_validation_symbol_created_at")
    await _ensure_index(db.settings, [("user_id", 1)], unique=True)
    await _ensure_index(db.forecasts, [("symbol", 1)], unique=True)
    await _ensure_index(db.forecasts, [("alpha_score", -1), ("confidence", -1)], name="forecasts_alpha_confidence")
    await _ensure_index(db.alpha_scores, [("symbol", 1)], unique=True)
    await _ensure_index(db.alpha_scores, [("rank", 1), ("alpha_score", -1)], name="alpha_scores_rank_score")
    await _ensure_index(db.market_regimes, [("symbol", 1)], unique=True)
    await _ensure_index(db.market_regimes, [("regime", 1), ("confidence", -1)], name="market_regimes_regime_confidence")
    await _ensure_index(db.opportunities, [("symbol", 1)], unique=True)
    await _ensure_index(db.opportunities, [("rank", 1), ("alpha_score", -1)], name="opportunities_rank_score")
    await _ensure_index(db.ml_monitoring, [("symbol", 1)], unique=True)
    await _ensure_index(db.system_health, [("component", 1)], unique=True)
    await _ensure_index(db.job_runs, [("job", 1), ("started_at", -1)], name="job_runs_job_started")
    logger.info("MongoDB indexes ensured")


async def _ensure_index(collection, keys: list[tuple[str, int]], **kwargs) -> None:
    indexes = await collection.index_information()
    if any(spec.get("key") == keys for spec in indexes.values()):
        return
    await collection.create_index(keys, **kwargs)


async def _drop_legacy_market_data_index(db: AsyncIOMotorDatabase) -> None:
    indexes = await db.market_data.index_information()
    for name, spec in indexes.items():
        keys = spec.get("key", [])
        if keys == [("symbol", 1), ("timeframe", 1), ("timestamp", -1)]:
            try:
                await db.market_data.drop_index(name)
                logger.info("Dropped legacy market_data index index=%s", name)
            except OperationFailure as exc:
                logger.warning("Could not drop legacy market_data index index=%s error=%s", name, exc)
