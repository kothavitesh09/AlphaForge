import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.database.mongo import get_database
from app.services.analytics_engine import AnalyticsEngine, MarketSentimentEngine, SignalValidationService
from app.services.market_collector import MarketDataCollector, collector_state
from app.services.market_data import MarketDataClient
from app.services.intelligence import IntelligenceService
from app.services.ml_engine import MLTrainingService
from app.services.notifications import TelegramNotifier
from app.services.prediction_pipeline import PredictionPipelineService
from app.services.sentiment import SentimentService
from app.services.signals import SignalService


logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()
collector_task: asyncio.Task | None = None
collector_stop_event: asyncio.Event | None = None


async def collect_market_data() -> None:
    db = get_database()
    logger.info("Collector Started")
    inserted = await MarketDataCollector(db).collect_once()
    logger.info("Market Collector Finished inserted=%s", inserted)


async def collect_and_signal() -> None:
    db = get_database()
    market = MarketDataClient()
    sentiment_service = SentimentService()
    signal_service = SignalService(db)
    notifier = TelegramNotifier()
    tickers = await market.tickers()
    for ticker in tickers[:20]:
        symbol = ticker["symbol"]
        try:
            candles = await market.candles(symbol)
            order_book = await market.order_book(symbol)
            sentiment = await sentiment_service.symbol_sentiment(symbol)
            signal = await signal_service.generate(symbol, candles, order_book, sentiment)
            await notifier.send_signal(signal)
        except Exception as exc:
            logger.warning("Signal generation failed for %s: %s", symbol, exc)


async def generate_predictions_and_accuracy() -> None:
    db = get_database()
    pipeline = PredictionPipelineService(db)
    await pipeline.generate_predictions()
    await pipeline.evaluate_predictions()
    await SignalValidationService(db).validate_all()
    await MarketSentimentEngine(db).update()
    await AnalyticsEngine(db).update()


async def refresh_intelligence_layer() -> None:
    await IntelligenceService(get_database()).refresh_all()


async def retrain_ml_models() -> None:
    await MLTrainingService(get_database()).run()


def start_scheduler() -> None:
    start_market_collector()
    if scheduler.running:
        return
    scheduler.add_job(collect_and_signal, "interval", minutes=30, id="signal_generation", replace_existing=True, next_run_time=None)
    scheduler.add_job(generate_predictions_and_accuracy, "interval", minutes=15, id="prediction_generation", replace_existing=True, next_run_time=None)
    scheduler.add_job(refresh_intelligence_layer, "interval", minutes=30, id="forecast_intelligence", replace_existing=True, next_run_time=None)
    scheduler.add_job(retrain_ml_models, "cron", hour=2, id="daily_ml_retraining", replace_existing=True, next_run_time=None)
    scheduler.add_job(retrain_ml_models, "cron", day_of_week="sun", hour=3, id="weekly_ml_retraining", replace_existing=True, next_run_time=None)
    scheduler.start()


def stop_scheduler() -> None:
    stop_market_collector()
    if scheduler.running:
        scheduler.shutdown(wait=False)


def start_market_collector() -> None:
    global collector_task, collector_stop_event
    if collector_task and not collector_task.done():
        return
    collector_stop_event = asyncio.Event()
    collector_task = asyncio.create_task(MarketDataCollector(get_database()).run_forever(collector_stop_event))
    collector_task.add_done_callback(_collector_done)


def stop_market_collector() -> None:
    if collector_stop_event:
        collector_stop_event.set()
    collector_state.running = False


def is_market_collector_running() -> bool:
    return bool(collector_task and not collector_task.done() and collector_state.running)


def _collector_done(task: asyncio.Task) -> None:
    collector_state.running = False
    if task.cancelled():
        logger.info("Market collector task cancelled")
        return
    exc = task.exception()
    if exc:
        collector_state.last_error = str(exc)
        logger.error("Collector Exception error=%s", exc, exc_info=exc)
