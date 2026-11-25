"""실제 API 호출 없이 방 생성 중복 방지와 프로젝트 격리를 확인한다."""
import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import patch
import 코덱스대화 as room,프로젝트방 as pr

class Rooms(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=room.STATE;room.STATE=Path(self.tmp.name)
  self.req={'project_key':'01_프로젝트/099_연결검증','name':'099_연결검증','local_path':'/Users/charlie/Library/CloudStorage/GoogleDrive-chairlie92.biz@gmail.com/내 드라이브/큐앤뱅 뉴 대시보드/01_프로젝트/099_연결검증','drive_url':'https://drive.google.com/drive/folders/test_id','report_name':'099_연결검증'}
  self.chat='oc_'+'1'*32;self.calls=[]
 def tearDown(self):room.STATE=self.old;self.tmp.cleanup()
 def api(self,m,p,b=None):
  self.calls.append((m,p,b))
  if m=='POST' and p.startswith('/open-apis/im/v1/chats?'):return {'chat_id':self.chat}
  if '/members?' in p:return {'items':[{'member_id':room.OWNER}]}
  if m=='GET' and self.chat in p:return {'name':self.req['name'],'owner_id':room.OWNER,'external':False,'chat_type':'private'}
  if m=='POST':return {'message_id':'om_test'}
  return {}
 def bind(self):
  with patch.object(room,'api',side_effect=self.api):return pr.ensure(self.req)
 def test_create_reuse_private_and_exact_owner(self):
  self.assertTrue(self.bind()['created'])
  with patch.object(room,'api',side_effect=self.api):self.assertFalse(pr.ensure(self.req)['created'])
  made=[b for m,p,b in self.calls if m=='POST' and '/chats?' in p]
  self.assertEqual(len(made),1);self.assertEqual(made[0]['user_id_list'],[room.OWNER]);self.assertFalse(made[0]['external'])
  self.assertEqual(pr.report_target(self.req['report_name']),self.chat)
  self.assertEqual(pr.report_target('다른 프로젝트'),room.CHAT)
 def test_preflight_failure_creates_nothing(self):
  with patch.object(room,'api',side_effect=RuntimeError('한도 초과')):
   with self.assertRaises(RuntimeError):pr.ensure(self.req)
  with room.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM project_rooms').fetchone()[0],0)
 def test_uncertain_create_never_duplicates(self):
  def fail(m,p,b=None):
   if m=='POST':raise TimeoutError()
   return {}
  with patch.object(room,'api',side_effect=fail):
   with self.assertRaises(TimeoutError):pr.ensure(self.req)
  with patch.object(room,'api',side_effect=self.api):
   with self.assertRaisesRegex(RuntimeError,'중복'):pr.ensure(self.req)
  self.assertEqual(self.calls,[])
 def test_reject_bad_path_and_url(self):
  for k,v in [('project_key','01_프로젝트/../다른곳'),('local_path','/tmp/위조'),('drive_url','https://evil.example/folder')]:
   with self.assertRaises(ValueError):pr.validate(dict(self.req,**{k:v}))
 def event(self,chat,owner,mid='om_job'):
  return S(message=S(chat_id=chat,message_id=mid,message_type='text',content=json.dumps({'text':'자료 정리'})),sender=S(sender_id=S(open_id=owner),sender_type='user'))
 def test_registered_rooms_owner_and_claim_context(self):
  self.bind()
  with patch.object(room,'reply',return_value='ok'):
   self.assertFalse(room.receive(self.event('oc_'+'2'*32,room.OWNER)))
   self.assertTrue(room.receive(self.event(self.chat,'other')))
   self.assertTrue(room.receive(self.event(self.chat,room.OWNER)))
   self.assertTrue(room.receive(self.event(self.chat,room.OWNER)))
  with room.db() as c:
   self.assertEqual(c.execute('SELECT count(*) FROM jobs').fetchone()[0],1)
   self.assertEqual(c.execute('SELECT chat FROM jobs').fetchone()[0],self.chat)
  with patch.object(room,'room_context',return_value=[]) as context:
   j=room.rpc({'action':'claim'})
   context.assert_called_once_with('om_job',self.chat)
  self.assertEqual(j['project']['project_key'],self.req['project_key'])
 def test_verification_failure_not_active(self):
  def wrong(m,p,b=None):
   result=self.api(m,p,b)
   if self.chat in p and '/members?' not in p:result['owner_id']='other'
   return result
  with patch.object(room,'api',side_effect=wrong):
   with self.assertRaises(RuntimeError):pr.ensure(self.req)
  self.assertIsNone(pr.lookup(self.chat))

if __name__=='__main__':unittest.main()
