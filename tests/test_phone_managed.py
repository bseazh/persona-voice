import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/phone-console'))
import managed_calls as calls

class ManagedCallTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=patch.object(calls,'DB',Path(self.temp.name)/'calls.sqlite3');self.db.start()
        self.id='00000000-0000-4000-8000-000000000001'
        self.ready=lambda:{'busy':False,'gateway_online':True}
    def tearDown(self):self.db.stop();self.temp.cleanup()
    def test_retry_after_unknown_result_never_redials(self):
        with patch.object(calls,'ami_originate',side_effect=TimeoutError) as originate:
            self.assertEqual(calls.dial('13660199577',self.id,['13660199577'],self.ready)[0],202)
            self.assertEqual(calls.dial('13660199577',self.id,['13660199577'],self.ready)[1]['state'],'uncertain')
            originate.assert_called_once()
    def test_other_request_blocked_by_persistent_call(self):
        with patch.object(calls,'ami_originate') as originate:
            calls.dial('13660199577',self.id,['13660199577'],self.ready)
            self.assertEqual(calls.dial('13660199577',self.id[:-1]+'2',['13660199577'],self.ready)[0],409)
            originate.assert_called_once()
    def test_bad_number_never_reaches_ami(self):
        with patch.object(calls,'ami_originate') as originate:
            self.assertEqual(calls.dial('13660199577\r\nAction: Command',self.id,['13660199577'],self.ready)[0],400)
            originate.assert_not_called()
    def test_hangup_is_scoped_to_request(self):
        with patch.object(calls,'ami_originate'):calls.dial('13660199577',self.id,['13660199577'],self.ready)
        with patch.object(calls,'channels',return_value={self.id:[('Local/13660199577@console-outbound-00000001;1',True)],'other':[('other',True)]}),patch.object(calls,'cli',create=True) as cli:
            self.assertEqual(calls.hangup(self.id,cli)[0],200)
            cli.assert_called_once_with('channel request hangup Local/13660199577@console-outbound-00000001;1')
    def test_restart_reconciliation_and_ended_event(self):
        with patch.object(calls,'ami_originate'):calls.dial('13660199577',self.id,['13660199577'],self.ready)
        with patch.object(calls,'channels',return_value={self.id:[('channel',True)]}):calls.monitor_once(None)
        self.assertEqual(calls.get(self.id)['state'],'connected')
        with patch.object(calls,'channels',return_value={}):calls.monitor_once(None)
        self.assertEqual(calls.get(self.id)['state'],'ended')
        self.assertFalse(calls.active())
    def test_cli_failure_does_not_mark_call_ended(self):
        with patch.object(calls,'ami_originate'):calls.dial('13660199577',self.id,['13660199577'],self.ready)
        with patch.object(calls,'channels',side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):calls.monitor_once(None)
        self.assertTrue(calls.active())

if __name__=='__main__':unittest.main()
