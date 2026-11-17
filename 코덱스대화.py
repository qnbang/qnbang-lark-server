"""라크 작업방 시험 연결. 방과 실행 상태는 서버 로컬에 보관한다."""
import json, os, sqlite3, sys, time, uuid
from pathlib import Path
import urllib.request
CHAT='oc_06c4cbf7604d17f82f38a2dd9670f06b'
OWNER='ou_cb74778259f8960e7da101202235df4d'
STATE=Path(os.environ.get('LARK_CODEX_STATE',str(Path.home()/'.local/state/qnbang-codex-chat')))

def db():
    STATE.mkdir(parents=True,exist_ok=True,mode=0o700)
    c=sqlite3.connect(STATE/'queue.sqlite',timeout=20);c.row_factory=sqlite3.Row
    c.executescript('''CREATE TABLE IF NOT EXISTS rooms(chat TEXT PRIMARY KEY,session TEXT);
    CREATE TABLE IF NOT EXISTS jobs(mid TEXT PRIMARY KEY,chat TEXT,body TEXT,status TEXT,created REAL,token TEXT,updated REAL,result TEXT);
    CREATE TABLE IF NOT EXISTS outbox(key TEXT PRIMARY KEY,state TEXT,message TEXT);''')
    return c

def api(method,path,body=None):
    import lark
    token=lark.토큰받기(lark.설정읽기())
    req=urllib.request.Request('https://open.larksuite.com'+path,method=method,data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=25) as r:out=json.load(r)
    if out.get('code')!=0:raise RuntimeError('라크 응답 오류 '+str(out.get('code')))
    return out.get('data',{})

def reply(mid,text,key):
    with db() as c:
        old=c.execute('SELECT state,message FROM outbox WHERE key=?',(key,)).fetchone()
        if old:
            if old['state']=='sent':return old['message']
            raise RuntimeError('전송 확인 필요')
        c.execute('INSERT INTO outbox VALUES(?,?,?)',(key,'sending',''))
    try:
        r=api('POST','/open-apis/im/v1/messages/'+mid+'/reply',{'msg_type':'text','content':json.dumps({'text':text},ensure_ascii=False),'uuid':str(uuid.uuid5(uuid.NAMESPACE_URL,key)),'reply_in_thread':False})
    except Exception:
        with db() as c:c.execute("UPDATE outbox SET state='uncertain' WHERE key=?",(key,))
        raise
    with db() as c:c.execute("UPDATE outbox SET state='sent',message=? WHERE key=?",(r['message_id'],key))
    return r['message_id']

def receive(ev):
    msg=ev.message
    if msg.chat_id!=CHAT:return False
    sender=getattr(getattr(ev.sender,'sender_id',None),'open_id','')
    if getattr(ev.sender,'sender_type','')!='user' or sender!=OWNER:return True
    mid=msg.message_id
    if getattr(msg,'message_type','')=='interactive':
        reply(mid,'전달한 메일 카드를 받았어. 이 방에서 원하는 작업을 말하면 메일 본문과 함께 읽고 처리할게.','mail-card:'+mid)
        return True
    if getattr(msg,'message_type','') in ('file','image'):
        reply(mid,'첨부 자료를 받았어. 다음 작업 지시를 처리할 때 파일 원본도 함께 읽을게.','attachment:'+mid)
        return True
    if getattr(msg,'message_type','') not in ('text','post'):
        reply(mid,'이 메시지 형식은 아직 직접 읽지 못했어. 메일 카드·파일·이미지 또는 글로 보낸 자료를 처리할 수 있어.','unsupported:'+mid);return True
    content=json.loads(msg.content or '{}')
    def texts(o):
        if isinstance(o,dict):
            if isinstance(o.get('text'),str):yield o['text']
            for k,v in o.items():
                if k!='text':yield from texts(v)
        elif isinstance(o,list):
            for v in o:yield from texts(v)
    body='\n'.join(texts(content)).strip()
    if not body:return True
    if len(body)>24000:
        reply(mid,'한 번에 처리할 본문이 너무 길어. 메일 하나씩 나눠 보내줘.','long:'+mid);return True
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM jobs WHERE mid=?',(mid,)).fetchone():return True
        c.execute('INSERT OR IGNORE INTO rooms VALUES(?,NULL)',(CHAT,))
        stop=body.strip() in ('중단','멈춰','작업 중단')
        if stop:c.execute("UPDATE jobs SET status=CASE WHEN status='running' THEN 'cancel_requested' ELSE 'cancelled' END WHERE chat=? AND status IN ('pending','running')",(CHAT,))
        c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,NULL,?,NULL)',(mid,CHAT,body,'cancelled' if stop else 'pending',time.time(),time.time()))
    try:reply(mid,'중단 요청했어.' if stop else '접수했어. 이 방의 앞선 대화를 이어서 처리할게.','ack:'+mid)
    except Exception as e:print('접수 답장 오류',type(e).__name__,flush=True)
    return True

def room_context(mid):
    """사람의 지시 때만 방 기록을 한 번 조회한다. 봇 알림도 자료로 읽는다."""
    from urllib.parse import urlencode
    import lark
    own_app=lark.설정읽기()['app_id']
    query=urlencode({'container_id_type':'chat','container_id':CHAT,'sort_type':'ByCreateTimeDesc','page_size':50})
    items=api('GET','/open-apis/im/v1/messages?'+query).get('items',[])
    current=next((i for i,x in enumerate(items) if x.get('message_id')==mid),None)
    if current is None:raise RuntimeError('현재 요청이 최근 기록 범위를 벗어나 맥락 확인 필요')
    out=[];remaining=45000
    for x in reversed(items[current+1:]):
        sender=x.get('sender',{})
        if x.get('msg_type')=='system' or sender.get('id')==own_app:continue
        raw=x.get('body',{}).get('content','')
        if not raw:continue
        if len(raw)>remaining:raw=raw[:remaining]+' [내용 일부 생략]'
        out.append({'message_id':x.get('message_id'),'message_type':x.get('msg_type'),'sender_type':sender.get('sender_type'),'content':raw})
        remaining-=len(raw)
        if remaining<=0:break
    return out

def rpc(r):
    action=r['action']
    with db() as c:
        if action=='claim':
            c.execute('BEGIN IMMEDIATE')
            c.execute("UPDATE jobs SET status='failed',result='실행 응답 끊김: 자동 재실행하지 않음' WHERE status IN ('running','cancel_requested') AND updated<?",(time.time()-1200,))
            if c.execute("SELECT 1 FROM jobs WHERE status IN ('running','cancel_requested')").fetchone():return None
            row=c.execute("SELECT * FROM jobs WHERE status='pending' ORDER BY created LIMIT 1").fetchone()
            if not row:return None
            j=dict(row);j['token']=uuid.uuid4().hex
            c.execute("UPDATE jobs SET status='running',token=?,updated=? WHERE mid=?",(j['token'],time.time(),j['mid']))
            j['session']=c.execute('SELECT session FROM rooms WHERE chat=?',(j['chat'],)).fetchone()[0]
            try:j['room_context']=room_context(j['mid'])
            except Exception as e:j['context_error']=str(e)
            return j
        if action=='attachments':
            job=c.execute('SELECT * FROM jobs WHERE mid=? AND token=?',(r['mid'],r['token'])).fetchone()
            if not job or job['status']!='running':raise RuntimeError('첨부 조회 실행 소유권 불일치')
            import 라크첨부,lark
            return 라크첨부.prepare(room_context(job['mid']),lark.설정읽기(),STATE)
        if action in ('heartbeat','finish'):
            j=c.execute('SELECT * FROM jobs WHERE mid=? AND token=?',(r['mid'],r['token'])).fetchone()
            if not j:raise RuntimeError('실행 소유권 불일치')
            if action=='heartbeat':
                c.execute('UPDATE jobs SET updated=? WHERE mid=?',(time.time(),r['mid']));return {'status':j['status']}
            if j['status'] in ('completed','failed','sending','delivery_unknown','cancelled'):return {'status':j['status']}
            answer=r['answer'];session=r.get('session')
            if j['status']=='cancel_requested':answer='작업을 중단했어.'
            if session:c.execute('UPDATE rooms SET session=? WHERE chat=?',(session,j['chat']))
            c.execute("UPDATE jobs SET status='sending',result=?,updated=? WHERE mid=?",(answer,time.time(),j['mid']))
        elif action=='status':
            return {'jobs':[dict(x) for x in c.execute('SELECT mid,status,updated FROM jobs ORDER BY created DESC LIMIT 10')],'rooms':[dict(x) for x in c.execute('SELECT * FROM rooms')]}
        else:raise ValueError('알 수 없는 요청')
    try:reply(r['mid'],answer,'result:'+r['mid']);status='failed' if r.get('failed') else 'completed'
    except Exception:status='delivery_unknown'
    with db() as c:c.execute('UPDATE jobs SET status=?,updated=? WHERE mid=?',(status,time.time(),r['mid']))
    return {'status':status}

if __name__=='__main__':
    os.umask(0o077)
    print(json.dumps(rpc(json.load(sys.stdin)),ensure_ascii=False))
