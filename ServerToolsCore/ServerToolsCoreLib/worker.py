"""Off-UI-thread execution so a slow tool call never freezes Slicer.

Hard constraint: never touch the MRML scene from a secondary thread. BackgroundJob
runs `target` on a worker thread; the outcome (or exception) is pushed onto a
queue.Queue and drained by a qt.QTimer on the main thread, which then invokes
on_success/on_error/on_progress. Everything touching slicer.* therefore stays
on the main thread.
"""

import logging
import queue
import threading

import qt

logger = logging.getLogger("ServerToolsCore.worker")

_POLL_INTERVAL_MS = 100


class BackgroundJob:
    """Runs `target(progress_cb)` on a worker thread; delivers the outcome on the main thread."""

    def __init__(self, target, on_success=None, on_error=None, on_progress=None,
                 on_event=None):
        self._target = target
        self._on_success = on_success
        self._on_error = on_error
        self._on_progress = on_progress
        # A second channel beside `progress`, for a tool reporting STRUCTURED
        # events as it works (see client._consume_stream). Same rule as every
        # other callback here: emitted on the worker thread, delivered on the
        # main one, so a handler may touch the scene.
        self._on_event = on_event
        self._queue = queue.Queue()
        self._timer = qt.QTimer()
        self._timer.setInterval(_POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._drain)
        self._thread = None
        self._cancelled = False

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._timer.start()

    def cancel(self) -> None:
        """Best-effort: the in-flight HTTP request cannot be interrupted, but its
        result is discarded and the UI is released immediately (see ARCHITECTURE.md
        limitations — no true server-side cancel)."""
        self._cancelled = True
        self._timer.stop()

    def _run(self) -> None:
        try:
            def progress_cb(message):
                self._queue.put(("progress", message))

            def event_cb(event):
                self._queue.put(("event", event))

            result = (
                self._target(progress_cb, event_cb)
                if self._on_event is not None
                else self._target(progress_cb)
            )
            self._queue.put(("success", result))
        except Exception as exc:
            logger.exception("Background job failed")
            self._queue.put(("error", exc))

    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if self._cancelled:
                    continue
                if kind == "progress" and self._on_progress:
                    self._on_progress(payload)
                elif kind == "event" and self._on_event:
                    self._on_event(payload)
                elif kind == "success":
                    self._timer.stop()
                    if self._on_success:
                        self._on_success(payload)
                elif kind == "error":
                    self._timer.stop()
                    if self._on_error:
                        self._on_error(payload)
        except queue.Empty:
            pass
