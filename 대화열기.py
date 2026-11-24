"""라크의 명시적인 버튼 클릭만 맥 실행기로 전달한다."""
import time
import uuid
import 코덱스대화 as room

def database():
    c=room.db()
    c.execute("""CREATE TABLE IF NOT EXISTS open_requests(
        id TEXT PRIMARY KEY,thread TEXT NOT NULL,state TEXT NOT NULL,
        created REAL NOT NULL,token TEXT,updated REAL NOT NULL)""")
    c.commit()
    return c

def receive(data):
    from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTriggerResponse
    e=data.event
    actor=getattr(getattr(e,'operator',None),'open_id',None)
    context=getattr(e,'context',None)
    chat=getattr(context,'open_chat_id',None)
    mid=getattr(context,'open_message_id',None)
    value=getattr(getattr(e,'action',None),'value',None)
    response=lambda text:P2CardActionTriggerResponse({'toast':{'type':'info','content':text}})
    if actor!=room.OWNER or chat!=room.CHAT or not isinstance(value,dict):
        return response('이 대화 열기 요청을 확인할 수 없습니다.')
    key=value.get('report_key')
    target=value.get('thread')
    if not isinstance(key,str) or not isinstance(target,str):
        return response('대화 연결 정보가 없습니다.')
    with database() as c:
        c.execute('CREATE TABLE IF NOT EXISTS open_targets(key TEXT NOT NULL,thread TEXT NOT NULL,PRIMARY KEY(key,thread))')
        origin=c.execute("""SELECT o.thread FROM open_targets o JOIN report_push p ON o.key=p.key
            WHERE p.key=? AND p.message=? AND p.state='sent' AND o.thread=?""",
            (key,mid,target)).fetchone()
        if not origin:
            return response('원래 보고와 연결된 대화를 확인하지 못했습니다.')
        if value.get('action')=='submit_reply':
            return response('라크 답변 입력은 종료했습니다. 코덱스에서 확인해 주세요.')
        if value.get('action')=='reply_form':
            value['action']='open_codex'
        if value.get('action')!='open_codex':return response('지원하지 않는 요청입니다.')
        event_id=getattr(getattr(data,'header',None),'event_id',None) or getattr(e,'token',None) or str(int(time.time()/2))
        rid=str(uuid.uuid5(uuid.NAMESPACE_URL,str(event_id)+mid+target))
        now=time.time()
        c.execute('INSERT OR IGNORE INTO open_requests VALUES(?,?,?, ?,NULL,?)',
                  (rid,target,'pending',now,now))
    return response('맥에 대화 열기를 요청했습니다.')

def claim():
    with database() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute("UPDATE open_requests SET state='expired' WHERE state='pending' AND created<?",(time.time()-300,))
        # 수신 확인이 끊긴 열기 요청은 화면이 반복 전환되지 않도록 재실행하지 않는다.
        row=c.execute("SELECT * FROM open_requests WHERE state='pending' ORDER BY created LIMIT 1").fetchone()
        if not row:
            return None
        token=uuid.uuid4().hex
        c.execute("UPDATE open_requests SET state='opening',token=?,updated=? WHERE id=?",
                  (token,time.time(),row['id']))
        return {'kind':'open_thread','id':row['id'],'thread':row['thread'],'token':token}

def finish(payload):
    state='opened' if payload['opened'] else 'failed'
    with database() as c:
        changed=c.execute("UPDATE open_requests SET state=?,updated=? WHERE id=? AND token=? AND state='opening'",
                          (state,time.time(),payload['id'],payload['token'])).rowcount
        if not changed:
            raise RuntimeError('대화 열기 요청 소유권 불일치')
    return {'status':state}


def stream():
    """같은 SSH 연결에서 클릭 요청과 수신 확인을 이어받는다."""
    import json
    import sys
    import 답변연결
    connection=database()
    답변연결.setup(connection)
    connection.isolation_level=None
    try:
        while True:
            pending=connection.execute(
                "SELECT 1 FROM open_requests WHERE state='pending' UNION ALL SELECT 1 FROM reply_requests WHERE state IN ('pending','sending') LIMIT 1").fetchone()
            if not pending:
                time.sleep(0.05)
                continue
            request=답변연결.claim() or claim()
            if not request:
                continue
            sys.stdout.write(json.dumps(request)+'\n')
            sys.stdout.flush()
            line=sys.stdin.readline()
            if not line:
                return
            response=json.loads(line)
            if response.get('id')!=request['id'] or response.get('token')!=request['token']:
                raise RuntimeError('대화 열기 수신 확인 불일치')
            if request['kind']=='reply_thread':답변연결.finish(response)
            else:finish(response)
    finally:
        connection.close()


if __name__=='__main__':
    import os
    import sys
    os.umask(0o077)
    if sys.argv[1:]==['--stream']:
        stream()
