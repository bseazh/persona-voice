"""Bounded speculative hints; never convert an interim transcript to a final one."""
import asyncio
import logging
import os
import time

logger = logging.getLogger(__name__)

def preflight_enabled():
    value = os.getenv('VOICE_PREFLIGHT', 'on')
    if value not in ('on', 'off'):
        raise ValueError('VOICE_PREFLIGHT must be on or off')
    return value == 'on'


class StablePreflight:
    def __init__(self, emit, *, delay=.15, min_chars=6, max_candidates=1):
        self.emit, self.delay, self.min_chars = emit, delay, min_chars
        self.max_candidates = max_candidates
        self.task = None
        self.latest = ''
        self.sent = set()
        self.closed = False
        self.speaking = None
        self.eligible = False
        self.value = None
        self.updated_at = 0.0

    def set_speaking(self, speaking):
        if self.closed or self.speaking == speaking:
            return
        previous = self.speaking
        self.speaking = speaking
        self._cancel()
        self.eligible = previous is True and speaking is False
        if self.eligible:
            self._schedule()

    def update(self, text, value):
        if self.closed or text == self.latest:
            return
        self._cancel()
        self.latest = text
        self.value = value
        self.updated_at = time.monotonic()
        self._schedule()

    def _schedule(self):
        text, value = self.latest, self.value
        if self.closed or not self.eligible or self.speaking is not False:
            return
        if len(text) < self.min_chars or text in self.sent or len(self.sent) >= self.max_candidates:
            return
        async def wait_stable():
            await asyncio.sleep(max(0, self.delay - (time.monotonic() - self.updated_at)))
            if self.latest == text and self.eligible and self.speaking is False:
                self.sent.add(text)
                try:
                    self.emit(value)
                except Exception as error:
                    # A speculative hint is optional; never leak payloads or fail ASR.
                    logger.warning('preflight hint skipped (%s)', type(error).__name__)
        self.task = asyncio.create_task(wait_stable())

    def _cancel(self):
        if self.task is not None:
            self.task.cancel()
            self.task = None

    def final(self):
        self._cancel()
        self.latest = ''
        self.value = None
        self.eligible = False
        self.sent.clear()

    def close(self):
        self.closed = True
        self.final()
