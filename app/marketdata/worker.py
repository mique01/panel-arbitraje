from __future__ import annotations

import signal
import time

from app.runtime import get_runtime
from app.marketdata.engine import MarketDataEngine
from app.utils.logging import get_logger


def run_worker() -> None:
    runtime = get_runtime()
    settings = runtime["settings"]
    repository = runtime["repository"]
    logger = get_logger("worker")
    engine = MarketDataEngine(settings, repository)
    running = True

    def _stop(*_args):
        nonlocal running
        logger.info("Worker shutdown requested")
        running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    repository.heartbeat("worker", "STARTING", "Worker boot")
    engine.start()
    last_heartbeat = 0.0
    try:
        while running:
            engine.process_next(timeout=settings.worker_poll_interval)
            now = time.time()
            if now - last_heartbeat >= settings.worker_heartbeat_seconds:
                repository.heartbeat("worker", "RUNNING", "Market data engine alive")
                last_heartbeat = now
    finally:
        engine.stop()
        repository.heartbeat("worker", "STOPPED", "Worker stopped")


if __name__ == "__main__":
    run_worker()
