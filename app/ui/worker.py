"""
Background worker for long-running tasks.
"""

from __future__ import annotations

import logging
import traceback
from typing import Callable, Any

from PySide6.QtCore import QRunnable, QObject, Signal, Slot

logger = logging.getLogger(__name__)


class WorkerSignals(QObject):
    """Worker sinyalleri."""
    started = Signal()
    finished = Signal()
    error = Signal(str)
    result = Signal(object)
    progress = Signal(int, str)  # value, message


class Worker(QRunnable):
    """
    Background worker thread.

    Usage:
        def do_work(progress_callback):
            progress_callback(50, "Halfway there...")
            return result

        worker = Worker(do_work)
        worker.signals.result.connect(on_complete)
        worker.signals.error.connect(on_error)
        thread_pool.start(worker)
    """

    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        """Execute the worker function."""
        logger.debug("Worker: started")
        self.signals.started.emit()

        try:
            # Progress callback ekle
            result = self.fn(
                self._progress_callback,
                *self.args,
                **self.kwargs,
            )
            logger.debug("Worker: emitting result signal")
            self.signals.result.emit(result)
            logger.debug("Worker: result signal emitted")
        except Exception as e:
            logger.exception(f"Worker error: {e}")
            traceback.print_exc()
            self.signals.error.emit(str(e))
        finally:
            logger.debug("Worker: emitting finished signal")
            self.signals.finished.emit()

    def _progress_callback(self, value: int, message: str = ""):
        """Progress callback for worker function."""
        self.signals.progress.emit(value, message)
