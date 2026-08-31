"""Thread lifecycle ownership for the background trading scheduler."""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


class SchedulerLifecycleMixin:
    """Serialize worker generations and report actual worker liveness."""

    _lifecycle_lock: threading.Lock
    _initialized: threading.Event
    _running: threading.Event
    _stop_requested: threading.Event
    _stopping: bool
    _thread: threading.Thread | None
    _completed_iterations: int

    def scheduler_stop_timeout_seconds(self) -> float:
        raise NotImplementedError

    def _run_loop(self) -> None:
        raise NotImplementedError

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._stopping or (self._thread is not None and self._thread.is_alive()):
                return
            self._stop_requested.clear()
            self._initialized.clear()
            self._completed_iterations = 0
            self._running.set()
            thread = threading.Thread(
                target=self._thread_main,
                name="karkinos-trading-scheduler",
                daemon=True,
            )
            self._thread = thread
            try:
                thread.start()
            except Exception:
                self._thread = None
                self._running.clear()
                self._stop_requested.set()
                raise
        logger.info("TradingScheduler started")

    def stop(self) -> None:
        with self._lifecycle_lock:
            if self._stopping:
                return
            self._stopping = True
            self._stop_requested.set()
            self._running.clear()
            self._initialized.clear()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=self.scheduler_stop_timeout_seconds())
        worker_alive = thread is not None and thread.is_alive()
        with self._lifecycle_lock:
            if not worker_alive and self._thread is thread:
                self._thread = None
            self._stopping = False
        if worker_alive:
            logger.warning(
                "TradingScheduler stop timed out; restart remains blocked until "
                "the existing worker exits"
            )
            return
        logger.info("TradingScheduler stopped")

    @property
    def is_running(self) -> bool:
        with self._lifecycle_lock:
            return self._thread is not None and self._thread.is_alive()

    @property
    def is_initialized(self) -> bool:
        return self._initialized.is_set()

    def mark_scheduler_initialized(self) -> None:
        self._initialized.set()

    def mark_scheduler_uninitialized(self) -> None:
        self._initialized.clear()

    def mark_scheduler_iteration_completed(self) -> None:
        with self._lifecycle_lock:
            self._completed_iterations += 1

    @property
    def completed_iterations(self) -> int:
        with self._lifecycle_lock:
            return self._completed_iterations

    def _thread_main(self) -> None:
        try:
            self._run_loop()
        except Exception:
            logger.exception("TradingScheduler worker terminated unexpectedly")
        finally:
            self._running.clear()
            self._initialized.clear()
            with self._lifecycle_lock:
                if self._thread is threading.current_thread():
                    self._thread = None
