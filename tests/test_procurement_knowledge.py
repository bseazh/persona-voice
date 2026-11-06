import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'services/agent'))
from procurement_knowledge import ProcurementKnowledge, normalize

SCOPE = 'viking://resources/procurement_demo'

class EvidenceTest(unittest.TestCase):
    def test_rejects_outside_scope_and_abstract_only(self):
        result = normalize({'status':'ok','result':{'resources':[
            {'uri':SCOPE+'-private/file','content':'secret'},
            {'uri':SCOPE+'/../private/file','content':'secret'},
            {'uri':SCOPE+'/summary','abstract':'not source evidence'},
            {'uri':SCOPE+'/manual','content':'verified excerpt'},
        ]}}, SCOPE)
        self.assertEqual(len(result['results']),1)
        self.assertEqual(result['results'][0]['content'],'verified excerpt')

    def test_failed_provider_not_treated_as_evidence(self):
        with self.assertRaises(ValueError):
            normalize({'status':'error','result':{}},SCOPE)

class MissingConfigTest(unittest.IsolatedAsyncioTestCase):
    async def test_no_implicit_local_fallback(self):
        with patch.dict(os.environ, {'OPENVIKING_API_KEY':'','OPENVIKING_PROCUREMENT_URI':''}):
            events=[]
            client=ProcurementKnowledge(lambda kind,payload:events.append((kind,payload)))
            result=await client.search('电机型号')
        self.assertEqual(result['status'],'not_configured')
        self.assertEqual(result['results'],[])
        self.assertEqual(events[-1][0],'knowledge.completed')

if __name__=='__main__':
    unittest.main()
