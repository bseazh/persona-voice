import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/agent'))
from realtime_control import ResponseRouter, explicit_end


def created(value):return {'type':'response.created','response':{'id':value}}
def done(value):return {'type':'response.done','response':{'id':value,'status':'cancelled'}}


class RoutingTests(unittest.TestCase):
    def test_superseded_response_closes_before_new_stream_and_late_done_is_ignored(self):
        r=ResponseRouter()
        r.feed(created('old'))
        out=r.feed(created('new'))
        self.assertEqual([e['type'] for e in out],['response.done','response.created'])
        self.assertEqual(out[0]['response']['id'],'old')
        self.assertEqual(r.feed(done('old')),[])
        self.assertEqual(r.active,'new')
        self.assertEqual(r.feed({'type':'response.audio.delta','response_id':'old','delta':'AA=='}),[])

    def test_cancel_blocks_audio_without_losing_completion(self):
        r=ResponseRouter();r.feed(created('a'))
        self.assertTrue(r.cancel());self.assertFalse(r.cancel())
        self.assertEqual(r.feed({'type':'response.audio.delta','response_id':'a'}),[])
        self.assertEqual(r.feed(done('a')),[done('a')])
        self.assertFalse(r.cancel())
        r.feed(created('b'))
        event={'type':'response.audio.delta','response_id':'b'}
        self.assertEqual(r.feed(event),[event])

    def test_unannounced_done_has_no_livekit_channel_to_close(self):
        r=ResponseRouter();r.feed(created('a'))
        e={'type':'response.output_item.done','response_id':'a','item':{'id':'i','type':'message'}}
        self.assertEqual(r.feed(e),[])
        r.feed({**e,'type':'response.output_item.added'})
        self.assertEqual(r.feed(e),[e])

    def test_muting_ends_existing_generation_but_never_opens_another(self):
        r=ResponseRouter();r.feed(created('a'));r.muted=True
        out=r.feed(created('b'))
        self.assertEqual(len(out),1)
        self.assertEqual(out[0]['type'],'response.done')
        self.assertIsNone(r.active)
        self.assertEqual(r.feed(created('c')),[])

    def test_stale_tool_cannot_be_executed_in_new_response(self):
        r=ResponseRouter();r.feed(created('a'));r.feed(done('a'));r.feed(created('b'))
        self.assertEqual(r.feed({'type':'response.output_item.done','response_id':'a',
            'item':{'id':'x','type':'function_call','name':'finish_consultation'}}),[])


class EndCommandTests(unittest.TestCase):
    def test_explicit_commands(self):
        for text in ('再见。','请挂断电话。','今天就聊到这里吧',
                     '好的，那今天就聊到这里吧','今天就聊到这里吧，再见，请挂断电话。','现在不方便'):
            with self.subTest(text=text):self.assertTrue(explicit_end(text))

    def test_mentions_and_negations_do_not_end_calls(self):
        for text in ('不要挂断电话','还没说完，再见只是举例','如果我说再见会怎样',
                     '“再见”是什么意思','请不要说再见','再见面的时候聊','今天就聊到这里吧可以这么说吗'):
            with self.subTest(text=text):self.assertFalse(explicit_end(text))


if __name__=='__main__':unittest.main()
