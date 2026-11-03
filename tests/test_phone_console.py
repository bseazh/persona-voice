import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ['PHONE_ALLOWED_NUMBERS'] = '15820242347'
spec = importlib.util.spec_from_file_location('phone_console', Path(__file__).resolve().parents[1] / 'services/phone-console/server.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PhoneConsoleTests(unittest.TestCase):
    def setUp(self):
        module.PENDING_UNTIL = 0

    def test_rejects_unapproved_or_injected_numbers_without_command(self):
        with patch.object(module, 'cli') as cli:
            for number in ('13660199577', '15820242347;hangup all', '+8615820242347'):
                self.assertEqual(module.dial(number)[0], 400)
            cli.assert_not_called()

    def test_rejects_busy_and_offline(self):
        for state in ({'busy': True, 'gateway_online': True}, {'busy': False, 'gateway_online': False}):
            with patch.object(module, 'snapshot', return_value=state), patch.object(module, 'cli') as cli:
                self.assertEqual(module.dial('15820242347')[0], 409)
                cli.assert_not_called()

    def test_duplicate_submission_blocked(self):
        with patch.object(module, 'cli', side_effect=lambda cmd: 'Contact: k60-test/sip:test Avail 10' if cmd == 'pjsip show contacts' else '') as cli:
            self.assertEqual(module.dial('15820242347')[0], 202)
            self.assertEqual(module.dial('15820242347')[0], 409)
            self.assertEqual(sum('channel originate' in call.args[0] for call in cli.call_args_list), 1)

    def test_hangup_only_console_owned_channels(self):
        owned = 'Local/15820242347@console-outbound-00000001;1'
        channels = owned + '!Up\nPJSIP/k60-test-00000001!Up\nLocal/15820242347@sim-ai-outbound-00000002;1!Up'
        with patch.object(module, 'cli', side_effect=lambda cmd: channels if cmd == 'core show channels concise' else '') as cli:
            self.assertEqual(module.hangup()[0], 200)
            commands = [call.args[0] for call in cli.call_args_list if call.args[0].startswith('channel request')]
            self.assertEqual(commands, ['channel request hangup ' + owned])


if __name__ == '__main__':
    unittest.main()
