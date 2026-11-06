import os
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'services/agent'))
from procurement_knowledge import ProcurementKnowledge, normalize, retrieval_query

SCOPE = 'viking://resources/procurement_demo'

class EvidenceTest(unittest.TestCase):
    def test_compact_evidence_keeps_each_requested_model_and_skips_title(self):
        resources=[{'uri':SCOPE+'/TDS825/title','content':'TDS 825'},
            {'uri':SCOPE+'/procurement-expansion/tds820/spec','content':'TDS 820 '+('2000 mm '*40)},
            {'uri':SCOPE+'/procurement-expansion/tds825/spec','content':'TDS 825 '+('2500 mm '*40)}]
        single=normalize({'status':'ok','result':{'resources':resources}},SCOPE,'TDS 825 轴长')
        self.assertEqual(len(single['results']),1)
        self.assertIn('2500',single['results'][0]['content'])
        comparison=normalize({'status':'ok','result':{'resources':resources}},SCOPE,'TDS 820 与825')
        self.assertEqual(len(comparison['results']),2)
    def test_fragmented_model_and_equipment_are_search_candidates(self):
        for query in ('phone next 1600 长宽高', 'P H O E N I X 1600 筛筒直径', '1600 筛筒长和直径'):
            result = retrieval_query(query)
            self.assertTrue(result.startswith(query))
            self.assertIn('候选型号：Phoenix 1600', result)
            self.assertIn('需核对原意', result)

    def test_numbers_alone_and_other_models_are_not_rewritten(self):
        for query in ('1600', '输送带宽1600毫米', 'TDS 825 轴长', '筛筒16000毫米'):
            self.assertEqual(retrieval_query(query), query)

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
    async def test_tool_audits_exact_input_and_return_value(self):
        events=[]
        client=ProcurementKnowledge(lambda kind,payload:events.append((kind,payload)))
        client.search=AsyncMock(return_value={'status':'ok','request_id':'retrieval-1',
            'results':[{'uri':SCOPE+'/manual','content':'直径 1.54 m','content_sha256':'internal'}]})
        output=await client.invoke_tool(' Phoenix 1600 直径 ')
        self.assertEqual(events[0][1]['input'], {'query':' Phoenix 1600 直径 '})
        self.assertEqual(events[1][1]['output'], output)
        self.assertEqual(events[0][1]['tool_id'],events[1][1]['tool_id'])
        self.assertEqual(events[1][1]['request_id'],'retrieval-1')
        self.assertEqual(events[1][1]['output_sha256'],hashlib.sha256(output.encode()).hexdigest())
        self.assertNotIn('content_sha256',json.loads(output)['results'][0])

    async def test_cancelled_tool_has_no_success_output(self):
        events=[]
        client=ProcurementKnowledge(lambda kind,payload:events.append((kind,payload)))
        client.search=AsyncMock(side_effect=asyncio.CancelledError)
        with self.assertRaises(asyncio.CancelledError):await client.invoke_tool('参数')
        self.assertEqual([e[0] for e in events],['knowledge.tool_input','knowledge.tool_cancelled'])

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
