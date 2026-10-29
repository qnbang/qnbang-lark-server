# -*- coding: utf-8 -*-
"""보고방 수신·작업대기·답장. 실행 상태는 서버 로컬 SQLite에만 저장한다."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import uuid
import urllib.request

CHAT = 'oc_607080f94a47e6077d745ef1348b4379'
OWNER = 'ou_cb74778259f8960e7da101202235df4d'
SHEET = '1G4ply1-Lvy9w1_8rpXp6EnnxI6PKOOKL1H3xFCh6I6A'
STATE = Path(os.environ.get('SALES_CHAT_STATE', str(Path.home()/'.local/state/qnbang-sales-chat')))
ACK = re.compile(r'^(?:확인|확인했어|알겠어|알겠습니다|ㅇㅇ+|ㅇㅋ|오케이|고마워|감사합니다)[.!~\s]*$')
STOP = re.compile(r'^(?:잠깐\s*)?(?:전체\s*|조사\s*|작업\s*|다\s*)?(?:중단|정지|멈춰|멈춰줘|멈춰라|그만|그만해|일시정지)(?:해|해줘|해라|줘)?[.!\s]*$')

def db():
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.umask(0o077)
    c=sqlite3.connect(str(STATE/'queue.sqlite'), timeout=15)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.executescript('''
    CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY, role TEXT, body TEXT, parent TEXT, root TEXT, created REAL);
    CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, source TEXT UNIQUE, status TEXT, created REAL, updated REAL, token TEXT, result TEXT, error TEXT, reply TEXT, sheet_row INTEGER);
    CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY,value TEXT);
    CREATE TABLE IF NOT EXISTS outbox(key TEXT PRIMARY KEY,parent TEXT,body TEXT,state TEXT,message_id TEXT,updated REAL);
    ''')
    return c

def api(method,path,body=None):
    import lark
    token=lark.토큰받기(lark.설정읽기())
    req=urllib.request.Request('https://open.larksuite.com'+path,method=method,
        data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json; charset=utf-8'})
    with urllib.request.urlopen(req,timeout=25) as r: data=json.load(r)
    if data.get('code') != 0: raise RuntimeError('라크 응답 오류 '+str(data.get('code')))
    return data.get('data',{})

def reply(parent,body,key):
    """불명확한 전송은 자동 재발송하지 않는다. UUID로 서버 중복도 방지한다."""
    with contextlib.closing(db()) as c, c:
        old=c.execute('SELECT * FROM outbox WHERE key=?',(key,)).fetchone()
        if old:
            if old['state']=='sent': return old['message_id']
            raise RuntimeError('전송 확인 필요: '+key)
        c.execute('INSERT INTO outbox VALUES(?,?,?,?,?,?)',(key,parent,body,'sending','',time.time()))
    try:
        r=api('POST','/open-apis/im/v1/messages/'+parent+'/reply',{
            'msg_type':'text','content':json.dumps({'text':body},ensure_ascii=False),
            'uuid':str(uuid.uuid5(uuid.NAMESPACE_URL,key)), 'reply_in_thread':True})
        mid=r['message_id']
    except Exception:
        with contextlib.closing(db()) as c,c:
            c.execute("UPDATE outbox SET state='uncertain',updated=? WHERE key=?",(time.time(),key))
        raise
    with contextlib.closing(db()) as c,c:
        c.execute("UPDATE outbox SET state='sent',message_id=?,updated=? WHERE key=?",(mid,time.time(),key))
        p=c.execute('SELECT root FROM messages WHERE id=?',(parent,)).fetchone()
        root=(p['root'] if p else '') or parent
        c.execute('INSERT OR IGNORE INTO messages VALUES(?,?,?,?,?,?)',(mid,'assistant',body,parent,root,time.time()))
    return mid

def ingest(mid,sender,body,parent='',root='',created=None,chat=CHAT):
    if chat!=CHAT or sender!=OWNER or not mid or not body.strip(): return {'accepted':False}
    if len(body)>12000: body=body[:12000]+'\n[긴 메시지는 앞부분만 접수됨]'
    jid='LC-'+hashlib.sha256(mid.encode()).hexdigest()[:16]
    with contextlib.closing(db()) as c,c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM jobs WHERE source=?',(mid,)).fetchone(): return {'duplicate':True}
        c.execute('INSERT OR IGNORE INTO messages VALUES(?,?,?,?,?,?)',(mid,'user',body,parent or '',root or '',created or time.time()))
        if ACK.fullmatch(body.strip()):
            c.execute('INSERT INTO jobs(id,source,status,created,updated) VALUES(?,?,?,?,?)',(jid,mid,'acknowledged',time.time(),time.time()))
            return {'accepted':True,'status':'acknowledged','job_id':jid}
        stop=bool(STOP.fullmatch(body.strip()))
        if stop:
            c.execute("UPDATE jobs SET status=CASE WHEN status='running' THEN 'cancel_requested' ELSE 'cancelled' END,updated=? WHERE status IN ('pending','running')",(time.time(),))
        c.execute('INSERT INTO jobs(id,source,status,created,updated) VALUES(?,?,?,?,?)',(jid,mid,'cancelled' if stop else 'pending',time.time(),time.time()))
        hb=c.execute("SELECT value FROM kv WHERE key='worker_seen'").fetchone()
        online=bool(hb and time.time()-float(hb[0])<100)
        limit=c.execute("SELECT COUNT(*) FROM jobs WHERE token IS NOT NULL AND created>?",(time.time()-86400,)).fetchone()[0]>=20
    if stop:
        ack='이 대화에서 접수한 조사 작업을 멈출게. 이미 진행 중인 호출도 중단하도록 요청했어. 별도 정기 소싱 예약은 이 명령으로 바뀌지 않아.'
    elif limit:
        ack='요청은 저장했어. 최근 24시간의 자동 처리 한도 20건에 도달해서 지금은 대기 중이야. 한도가 풀리면 이어서 처리할게.'
    elif not online:
        ack='요청을 접수했어. 지금 조사 실행기가 연결돼 있지 않아 대기 중이야. 연결되면 앞선 대화부터 읽고 이어서 처리할게.'
    else:
        ack='접수했어. 앞선 보고와 연결해서 살펴볼게. 진행 중인 작업이 있으면 그다음 순서로 이어갈게.'
    try: reply(mid,ack,'ack:'+mid)
    except Exception: pass  # 대기열 접수는 유지. 불명확한 발송은 outbox에서 확인한다.
    return {'accepted':True,'job_id':jid,'status':'cancelled' if stop else 'pending'}

def receive(ev):
    msg=ev.message
    if msg.chat_id!=CHAT: return False
    if getattr(ev.sender,'sender_type','')!='user': return True
    sender=getattr(getattr(ev.sender,'sender_id',None),'open_id','')
    if sender!=OWNER: return True
    if getattr(msg,'message_type','')!='text':
        reply(msg.message_id,'지금은 글로 적은 요청을 처리할 수 있어. 확인할 내용을 텍스트로 적어줘.','unsupported:'+msg.message_id)
        return True
    body=json.loads(msg.content or '{}').get('text','')
    ingest(msg.message_id,sender,body,getattr(msg,'parent_id','') or '',getattr(msg,'root_id','') or '')
    return True

def sheet_session():
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
    credentials=service_account.Credentials.from_service_account_file(str(Path(__file__).with_name('google-key.json')),scopes=['https://www.googleapis.com/auth/spreadsheets'])
    return AuthorizedSession(credentials)

def sheet_read():
    from urllib.parse import urlencode
    ranges=['보고함!A1:N30','위탁검증!A1:L60','통합운영!A3:C11','실행관리!A20:S24']
    s=sheet_session()
    r=s.get('https://sheets.googleapis.com/v4/spreadsheets/'+SHEET+'/values:batchGet?'+urlencode([('ranges',v) for v in ranges]),timeout=20)
    if r.status_code!=200: return {'available':False,'reason':'원장 접근 불가 '+str(r.status_code)}
    return {'available':True,'ranges':r.json().get('valueRanges',[])}

def context(j):
    with contextlib.closing(db()) as c:
        m=dict(c.execute('SELECT * FROM messages WHERE id=?',(j['source'],)).fetchone())
        recent=[dict(x) for x in c.execute('SELECT role,body,id,parent,root FROM messages ORDER BY created DESC LIMIT 18')][::-1]
        target=m['parent'] or m['root']
        linked=c.execute('SELECT role,body,id FROM messages WHERE id=?',(target,)).fetchone() if target else None
    if target and not linked:
        try:
            data=api('GET','/open-apis/im/v1/messages/'+target)
            item=data.get('items',[{}])[0]
            if item.get('chat_id')==CHAT:
                linked={'role':'reported','body':json.loads(item.get('body',{}).get('content','{}')).get('text',''),'id':target}
        except Exception: pass
    try: sheet=sheet_read()
    except Exception: sheet={'available':False,'reason':'원장 조회 오류'}
    return {'request':m,'linked_report':dict(linked) if linked else None,'recent':recent,'sheet':sheet}

def claim():
    with contextlib.closing(db()) as old:
        stale=[dict(x) for x in old.execute("SELECT id,token FROM jobs WHERE status IN ('running','cancel_requested') AND updated<?",(time.time()-1000,))]
    for x in stale:
        finish(x['id'],x['token'],{'title':'실행 연결 끊김','answer':'조사 실행기의 응답이 끊겨 이번 작업을 완료하지 못했어. 요청은 보존했고 자동으로 중복 실행하지 않을게.','failed':True})
    with contextlib.closing(db()) as c,c:
        c.execute('BEGIN IMMEDIATE')
        c.execute("INSERT OR REPLACE INTO kv VALUES('worker_seen',?)",(str(time.time()),))
        if c.execute("SELECT 1 FROM jobs WHERE status IN ('running','cancel_requested')").fetchone(): return None
        # ponytail: 이 보고방은 한 번에 하나만 실행. 동시 요청은 순서대로 처리한다.
        if c.execute("SELECT COUNT(*) FROM jobs WHERE token IS NOT NULL AND created>?",(time.time()-86400,)).fetchone()[0]>=20: return None
        j=c.execute("SELECT * FROM jobs WHERE status='pending' ORDER BY created LIMIT 1").fetchone()
        if not j:return None
        j=dict(j);token=uuid.uuid4().hex
        c.execute("UPDATE jobs SET status='running',token=?,updated=? WHERE id=?",(token,time.time(),j['id']))
        j.update(token=token,status='running')
    j['context']=context(j)
    try:
        sheet_row=record_sheet(j,{'title':'라크 요청 확인 중','answer':j['context']['request']['body'],'running':True})
        with contextlib.closing(db()) as c,c:
            c.execute('UPDATE jobs SET sheet_row=? WHERE id=?',(sheet_row,j['id']))
    except Exception: pass
    try:
        started='앞선 보고를 읽고 요청한 내용을 확인하기 시작했어. 확인한 근거와 남은 문제를 묶어서 답할게.'
        with contextlib.closing(db()) as c:
            sent=c.execute("SELECT message_id FROM outbox WHERE key=? AND state='sent'",('ack:'+j['source'],)).fetchone()
        if sent:
            api('PUT','/open-apis/im/v1/messages/'+sent[0],{'msg_type':'text','content':json.dumps({'text':started},ensure_ascii=False)})
            with contextlib.closing(db()) as c,c:
                c.execute('UPDATE messages SET body=? WHERE id=?',(started,sent[0]))
                c.execute('UPDATE outbox SET body=? WHERE message_id=?',(started,sent[0]))
        else: reply(j['source'],started,'start:'+j['id'])
    except Exception: pass
    return j

def heartbeat(jid,token):
    with contextlib.closing(db()) as c,c:
        c.execute("INSERT OR REPLACE INTO kv VALUES('worker_seen',?)",(str(time.time()),))
        j=c.execute('SELECT status,token FROM jobs WHERE id=?',(jid,)).fetchone()
        if not j or j['token']!=token: return {'status':'lost'}
        c.execute('UPDATE jobs SET updated=? WHERE id=?',(time.time(),jid))
        return {'status':j['status']}

def record_sheet(j,result):
    """기존 보고함의 빈 행만 채운다. 다른 업무 데이터/승인/금액을 수정하지 않는다."""
    from urllib.parse import quote
    s=sheet_session();base='https://sheets.googleapis.com/v4/spreadsheets/'+SHEET
    r=s.get(base+'/values/'+quote('보고함!H4:H196'),timeout=20)
    if r.status_code!=200:return None
    values=r.json().get('values',[])
    existing=next((i+4 for i,x in enumerate(values) if x and x[0]==j['id']),None)
    # 끝에 추가만 하므로 예약 소싱의 기존 보고행을 덮지 않는다.
    kst=time.strftime('%Y-%m-%d %H:%M:%S',time.gmtime(time.time()+9*3600))
    title=result.get('title','라크 후속 요청 처리')[:100]
    body=(result.get('summary') or result['answer'].split('\n\n')[0])[:300]
    row=['진행중' if result.get('running') else ('보류' if result.get('failed') else '완료'),'실행 오류 확인' if result.get('failed') else '',title,body,next((u for u in result.get('sources',[]) if isinstance(u,str) and u.startswith('https://')),''),'오류' if result.get('failed') else '후속보고',kst,j['id'],j['id'],'라크 답장 준비','SYS-CHAT','',1,'라크 원문 '+j['source']+'; 원장 자동 승인 없음']
    if existing:
        r=s.put(base+'/values/'+quote('보고함!A'+str(existing)+':N'+str(existing))+'?valueInputOption=RAW',json={'values':[row]},timeout=20)
        r.raise_for_status()
        return existing
    r=s.post(base+'/values/'+quote('보고함!A3:N196')+':append?valueInputOption=RAW&insertDataOption=OVERWRITE',json={'values':[row]},timeout=20)
    r.raise_for_status(); rg=r.json()['updates']['updatedRange']
    match=re.search(r'!A(\d+):',rg)
    return int(match.group(1)) if match else None

def finish(jid,token,result):
    with contextlib.closing(db()) as c,c:
        j=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if not j or j['token']!=token: raise RuntimeError('실행 소유권 불일치')
        j=dict(j)
        if j['status'] in ('completed','failed','cancelled','sending','delivery_unknown'): return {'status':j['status']}
        if j['status']=='cancel_requested':
            c.execute("UPDATE jobs SET status='cancelled',updated=? WHERE id=?",(time.time(),jid))
            return {'status':'cancelled'}
        answer=str(result.get('answer','')).strip()
        if not answer:raise ValueError('빈 답변')
        c.execute("UPDATE jobs SET status='sending',result=?,updated=? WHERE id=?",(json.dumps(result,ensure_ascii=False),time.time(),jid))
    try: sheet_row=record_sheet(j,result)
    except Exception: sheet_row=None
    links=[u for u in result.get('sources',[]) if isinstance(u,str) and u.startswith('https://') and u not in answer]
    if links: answer+='\n\n확인한 출처\n'+'\n'.join(dict.fromkeys(links[:6]))
    if not sheet_row: answer+='\n\n시트 자동 기록은 아직 연결되지 않아 이번 결과는 이 대화에 남겼어.'
    try:
        mid=reply(j['source'],answer,'result:'+jid)
        status='failed' if result.get('failed') else 'completed'
    except Exception:
        mid='';status='delivery_unknown'
    with contextlib.closing(db()) as c,c:
        c.execute('UPDATE jobs SET status=?,reply=?,sheet_row=?,updated=? WHERE id=?',(status,mid,sheet_row,time.time(),jid))
    if sheet_row:
        try:
            from urllib.parse import quote
            ss=sheet_session(); base='https://sheets.googleapis.com/v4/spreadsheets/'+SHEET+'/values/'
            check=ss.get(base+quote('보고함!H'+str(sheet_row)),timeout=15).json().get('values',[])
            if check==[[jid]]:
                ss.put(base+quote('보고함!J'+str(sheet_row))+'?valueInputOption=RAW',json={'values':[['라크 발송 성공 / '+mid if mid else '라크 발송 확인 필요']]},timeout=15).raise_for_status()
        except Exception: pass
    return {'status':status,'message_id':mid,'sheet_row':sheet_row}

def seed(items):
    with contextlib.closing(db()) as c,c:
        for x in items:
            c.execute('INSERT OR IGNORE INTO messages VALUES(?,?,?,?,?,?)',(x['id'],x['role'],x['body'],x.get('parent',''),x.get('root',''),x.get('created',time.time())))
    return {'seeded':len(items)}

def rpc(r):
    action=r['action']
    if action=='claim': return claim()
    if action=='heartbeat':return heartbeat(r['id'],r['token'])
    if action=='finish':return finish(r['id'],r['token'],r['result'])
    if action=='seed':return seed(r['items'])
    if action=='ingest':return ingest(**r['message'])
    if action=='status':
        with contextlib.closing(db()) as c:
            return {'jobs':[dict(x) for x in c.execute('SELECT id,status,error,reply,sheet_row FROM jobs ORDER BY created DESC LIMIT 10')],
                    'outbox':[dict(x) for x in c.execute("SELECT key,state FROM outbox WHERE state!='sent'")]}
    raise ValueError('지원하지 않는 요청')

if __name__=='__main__':
    print(json.dumps(rpc(json.load(sys.stdin)),ensure_ascii=False))
