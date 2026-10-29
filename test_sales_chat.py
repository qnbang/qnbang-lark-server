import contextlib
import importlib
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ['SALES_CHAT_STATE']=tempfile.mkdtemp(prefix='sales-chat-test-')
a=importlib.import_module('판매왕대화')

class Flow(unittest.TestCase):
    def test_full_flow(self):
        with patch.object(a,'api',return_value={'message_id':'bot-result'}), patch.object(a,'sheet_read',return_value={'available':False}), patch.object(a,'record_sheet',return_value=None):
            self.assertEqual(a.ingest('ack-only',a.OWNER,'확인')['status'],'acknowledged')
            self.assertIsNone(a.claim())
            self.assertFalse(a.ingest('bad','stranger','찾아줘')['accepted'])
            self.assertFalse(a.ingest('bad',a.OWNER,'찾아줘',chat='other')['accepted'])
            r=a.ingest('msg-1',a.OWNER,'미확정이면 더 확인해줘')
            self.assertTrue(r['accepted'])
            self.assertTrue(a.ingest('msg-1',a.OWNER,'다시')['duplicate'])
            j=a.claim(); self.assertEqual(j['source'],'msg-1'); self.assertIsNone(a.claim())
            self.assertEqual(a.heartbeat(j['id'],'wrong')['status'],'lost')
            result={'title':'재조사','answer':'공식 안내에서 세금 조건을 확인했어.'}
            self.assertEqual(a.finish(j['id'],j['token'],result)['status'],'completed')
            self.assertEqual(a.finish(j['id'],j['token'],result)['status'],'completed')
            r=a.ingest('msg-2',a.OWNER,'한 번 더 알아봐');j=a.claim()
            a.ingest('msg-stop',a.OWNER,'멈춰')
            self.assertEqual(a.heartbeat(j['id'],j['token'])['status'],'cancel_requested')
            self.assertEqual(a.finish(j['id'],j['token'],result)['status'],'cancelled')
            self.assertIsNone(a.claim())
            a.ingest('msg-3',a.OWNER,'아까 보고에 답변',parent='msg-1');j=a.claim()
            self.assertEqual(j['context']['linked_report']['id'],'msg-1')
            self.assertEqual(a.finish(j['id'],j['token'],{'title':'오류','answer':'실행 실패','failed':True})['status'],'failed')
    def test_uncertain_send_not_retried(self):
        with patch.object(a,'api',side_effect=TimeoutError) as api:
            with self.assertRaises(TimeoutError):a.reply('p','test','unique-fail')
            with self.assertRaises(RuntimeError):a.reply('p','test','unique-fail')
            self.assertEqual(api.call_count,1)

if __name__=='__main__':unittest.main()
