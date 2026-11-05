import asyncio
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/agent'))
from preflight import StablePreflight


class PreflightTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.events = []
        self.hints = StablePreflight(self.events.append, delay=.02, min_chars=2)

    async def asyncTearDown(self):
        self.hints.close()
        await asyncio.sleep(0)

    async def test_changed_interim_cancels_stale_candidate(self):
        self.hints.update('旧句', 'old')
        self.hints.update('新句', 'new')
        await asyncio.sleep(.04)
        self.assertEqual(self.events, ['new'])

    async def test_repeated_interim_does_not_postpone_hint(self):
        for _ in range(6):
            self.hints.update('相同', 'same')
            await asyncio.sleep(.01)
        self.assertEqual(self.events, ['same'])

    async def test_final_and_close_prevent_late_hints(self):
        self.hints.update('结束', 'final')
        self.hints.final()
        await asyncio.sleep(.04)
        self.hints.update('关闭', 'close')
        self.hints.close()
        self.hints.update('关闭以后', 'late')
        await asyncio.sleep(.04)
        self.assertEqual(self.events, [])

    async def test_candidate_budget_resets_only_on_final(self):
        for text in ['一', '第一', '第二', '第三']:
            self.hints.update(text, text)
            await asyncio.sleep(.04)
        self.assertEqual(self.events, ['第一', '第二'])
        self.hints.final()
        self.hints.update('下一句', 'next')
        await asyncio.sleep(.04)
        self.assertEqual(self.events, ['第一', '第二', 'next'])

    async def test_optional_hint_failure_is_contained(self):
        def fail(value):
            raise RuntimeError('private provider payload')
        self.hints.emit = fail
        self.hints.update('出错', 'private')
        await asyncio.sleep(.04)
        self.assertIsNone(self.hints.task.exception())


if __name__ == '__main__':
    unittest.main()
