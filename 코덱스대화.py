"""라크 작업방 시험 연결. 방과 실행 상태는 서버 로컬에 보관한다."""
import json, os, re, sqlite3, sys, time, uuid
from pathlib import Path
import urllib.request
from datetime import datetime, timezone, timedelta
CHAT='oc_06c4cbf7604d17f82f38a2dd9670f06b'
OWNER='ou_cb74778259f8960e7da101202235df4d'
STATE=Path(os.environ.get('LARK_CODEX_STATE',str(Path.home()/'.local/state/qnbang-codex-chat')))

def db():
    STATE.mkdir(parents=True,exist_ok=True,mode=0o700)
    c=sqlite3.connect(STATE/'queue.sqlite',timeout=20);c.row_factory=sqlite3.Row
    c.executescript('''CREATE TABLE IF NOT EXISTS rooms(chat TEXT PRIMARY KEY,session TEXT);
    CREATE TABLE IF NOT EXISTS jobs(mid TEXT PRIMARY KEY,chat TEXT,body TEXT,status TEXT,created REAL,token TEXT,updated REAL,result TEXT);
    CREATE TABLE IF NOT EXISTS outbox(key TEXT PRIMARY KEY,state TEXT,message TEXT);
    CREATE TABLE IF NOT EXISTS tracked_tasks(
        id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL,
        session TEXT, current_mid TEXT NOT NULL, updated REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS tracked_turns(
        mid TEXT PRIMARY KEY, task_id TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS tracked_turns_task ON tracked_turns(task_id);
    CREATE TABLE IF NOT EXISTS report_push(
        key TEXT PRIMARY KEY, text TEXT NOT NULL, created REAL NOT NULL,
        attempted REAL, state TEXT NOT NULL DEFAULT 'pending', message TEXT);
    CREATE INDEX IF NOT EXISTS report_push_pending ON report_push(state,created);''')
    return c

def api(method,path,body=None):
    import lark
    token=lark.토큰받기(lark.설정읽기())
    req=urllib.request.Request('https://open.larksuite.com'+path,method=method,data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=25) as r:out=json.load(r)
    if out.get('code')!=0:raise RuntimeError('라크 응답 오류 '+str(out.get('code')))
    return out.get('data',{})

def reply(mid,text,key,on_sent=None):
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
    with db() as c:
        c.execute("UPDATE outbox SET state='sent',message=? WHERE key=?",(r['message_id'],key))
        if on_sent:
            on_sent(c)
    return r['message_id']

TASK_PREFIX = '새 작업 '
TASK_RULES = """
이번 요청은 단독으로 관리하는 작업이다. 앞선 다른 작업을 참조하지 않는다.
다음 사용자 입력이 있어야 작업을 마칠 수 있으면 최종 응답의 첫 줄에 [답변 필요]를 쓰고,
그 아래에 완료한 범위와 사용자가 답할 질문 하나를 적는다.
요청한 결과를 끝냈을 때만 첫 줄을 [완료]로 쓴다. 실패나 접근 제한으로 멈췄을 때는
첫 줄을 [중단]으로 쓰고 확인한 결과와 남은 일을 적는다.
사용자에게 권한 우회나 라크에서의 민감한 승인·인증값 입력을 요구하지 않는다.
"""
REPORTS = {'오늘 작업', '오늘 작업 보고', '내 답 기다리는 거 뭐 있어?', '답변 대기'}
KOREA = timezone(timedelta(hours=9))
STATUS_LABEL = {
    'pending': '실행 대기', 'running': '실행 중', 'waiting': '답변 필요',
    'completed': '완료', 'failed': '중단', 'delivery_unknown': '보고 확인 필요',
    'review': '상태 확인 필요', 'resolved': '해결',
}


def expire_jobs(c):
    cutoff = time.time() - 1200
    c.execute("""UPDATE tracked_tasks SET status='delivery_unknown',updated=?
                 WHERE current_mid IN (SELECT mid FROM jobs WHERE status='sending' AND updated<?)""",
              (time.time(), cutoff))
    c.execute("UPDATE jobs SET status='delivery_unknown' WHERE status='sending' AND updated<?", (cutoff,))
    c.execute("""UPDATE tracked_tasks SET status='failed',updated=? WHERE status='running'
                 AND current_mid IN (SELECT mid FROM jobs
                 WHERE status IN ('running','cancel_requested') AND updated<?)""",
              (time.time(), cutoff))
    c.execute("""UPDATE jobs SET status='failed',result='실행 응답 끊김: 자동 재실행하지 않음'
                 WHERE status IN ('running','cancel_requested') AND updated<?""", (cutoff,))


def report(body, now=None):
    now = now or datetime.now(KOREA)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        expire_jobs(c)
        if body in ('답변 대기', '내 답 기다리는 거 뭐 있어?'):
            rows = c.execute("SELECT * FROM tracked_tasks WHERE status='waiting' ORDER BY updated").fetchall()
        else:
            rows = c.execute("""SELECT * FROM tracked_tasks
                WHERE status NOT IN ('completed','resolved')
                OR updated>=? ORDER BY updated DESC""", (start,)).fetchall()
        if body not in ('답변 대기', '내 답 기다리는 거 뭐 있어?'):
            uncertain = c.execute("SELECT COUNT(*) FROM report_push WHERE state='uncertain'").fetchone()[0]
        else:
            uncertain = 0
    title = '답변 대기' if body in ('답변 대기', '내 답 기다리는 거 뭐 있어?') else now.strftime('%m월 %d일 작업 보고')
    lines = [title]
    for row in rows:
        suffix = f" · 번호 {task_code(row['id'])}" if row['status'] not in ('completed','resolved') else ''
        lines.append(f"• {row['title']} · {STATUS_LABEL[row['status']]}{suffix}")
    if not rows:
        lines.append('해당하는 작업이 없어요.')
    if uncertain:
        lines.append(f'전송 여부를 확인해야 하는 이전 보고 {uncertain}건이 있어요.')
    return '\n'.join(lines)

def task_code(task_id):
    return uuid.uuid5(uuid.NAMESPACE_URL, task_id).hex[:10]

def resolve(code):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        rows = [r for r in c.execute(
            "SELECT id,title FROM tracked_tasks WHERE status IN ('waiting','failed','review','delivery_unknown')")
            if task_code(r['id']) == code]
        if len(rows) != 1:
            return '해결할 수 있는 작업 번호를 찾지 못했어요. 오늘 작업에서 번호를 확인해 주세요.'
        c.execute("UPDATE tracked_tasks SET status='resolved',updated=? WHERE id=?",
                  (time.time(),rows[0]['id']))
    return f"{rows[0]['title']} · 해결로 표시했어요."



def tracked_input(mid, parent, root, body):
    is_new = not (parent or root) and (body.startswith(TASK_PREFIX) or body == TASK_PREFIX.strip())
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM jobs WHERE mid=?',(mid,)).fetchone():
            return None
        task = None
        if not is_new:
            task = c.execute("""SELECT t.*,o.message AS question FROM tracked_tasks t
                LEFT JOIN outbox o ON o.key='result:'||t.current_mid AND o.state='sent'
                WHERE t.id=(SELECT a.task_id FROM tracked_turns a
                    LEFT JOIN outbox b ON b.key='result:'||a.mid AND b.state='sent'
                    WHERE a.mid IN (?,?) OR b.message IN (?,?)
                    ORDER BY CASE WHEN b.message=? OR a.mid=? THEN 0 ELSE 1 END LIMIT 1)""",
                (parent,root,parent,root,parent,parent)).fetchone()
            if not task:
                return False
            if task['status'] != 'waiting' or parent != task['question']:
                return '이 작업에 열린 질문이 없거나 이전 보고에 답장했어요. 가장 최근의 답변 필요 메시지를 확인해 주세요.'
        now = time.time()
        if is_new:
            title, _, details = body[len(TASK_PREFIX):].strip().partition('\n')
            if not title.strip():
                return '첫 줄에 새 작업과 이름을 적고, 다음 줄에 요청을 적어 주세요.'
            title = title.strip()[:70]
            task_id = mid
            body = details.strip() or title
            c.execute('INSERT INTO tracked_tasks VALUES(?,?,?,?,?,?)',
                (task_id,title,'pending',None,mid,now))
        else:
            task_id = task['id']
            title = task['title']
            c.execute("UPDATE tracked_tasks SET status='pending',current_mid=?,updated=? WHERE id=?",
                (mid,now,task_id))
        c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,NULL,?,NULL)',(mid,CHAT,body,'pending',now,now))
        c.execute('INSERT INTO tracked_turns VALUES(?,?)',(mid,task_id))
        return f'{title} · ' + ('작업 접수' if is_new else '답변 접수')


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
    if body in REPORTS and not (getattr(msg,'parent_id',None) or getattr(msg,'root_id',None)):
        try:reply(mid,report(body),'daily:'+mid)
        except RuntimeError as e:
            if str(e) != '전송 확인 필요':raise
        return True
    parent, root = getattr(msg,'parent_id',None), getattr(msg,'root_id',None)
    resolve_request = re.fullmatch(r'해결 ([a-f0-9]{10})',body)
    if resolve_request and not (parent or root):
        try:reply(mid,resolve(resolve_request[1]),'resolve:'+mid)
        except RuntimeError as e:
            if str(e) != '전송 확인 필요':raise
        return True
    if parent or root:
        with db() as c:
            external = c.execute(
                "SELECT 1 FROM report_push WHERE key LIKE 'claude-event:%' AND message IN (?,?)",
                (parent,root)).fetchone()
        if external:
            try:reply(mid,'이 작업의 답은 시작한 클로드 코드 대화에 입력해 주세요.','claude-reply:'+mid)
            except RuntimeError as e:
                if str(e) != '전송 확인 필요':raise
            return True
    tracked = tracked_input(mid,parent,root,body)
    if tracked is not False:
        if tracked:
            try:reply(mid,tracked,'ack:'+mid)
            except Exception as e:print('작업 접수 답장 오류',type(e).__name__,flush=True)
        return True
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM jobs WHERE mid=?',(mid,)).fetchone():return True
        c.execute('INSERT OR IGNORE INTO rooms VALUES(?,NULL)',(CHAT,))
        stop=body.strip() in ('중단','멈춰','작업 중단')
        if stop:c.execute("UPDATE jobs SET status=CASE WHEN status='running' THEN 'cancel_requested' ELSE 'cancelled' END WHERE chat=? AND status IN ('pending','running') AND mid NOT IN (SELECT mid FROM tracked_turns)",(CHAT,))
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
    if action in ('claude_events','report_tick'):
        import 라크보고
        if action == 'claude_events':
            return 라크보고.ingest(r['events'])
        return 라크보고.tick(test=r.get('test',False))
    with db() as c:
        if action=='claim':
            c.execute('BEGIN IMMEDIATE')
            expire_jobs(c)
            if c.execute("SELECT 1 FROM jobs WHERE status IN ('running','cancel_requested')").fetchone():return None
            row=c.execute("SELECT * FROM jobs WHERE status='pending' ORDER BY created LIMIT 1").fetchone()
            if not row:return None
            j=dict(row);j['token']=uuid.uuid4().hex
            c.execute("UPDATE jobs SET status='running',token=?,updated=? WHERE mid=?",(j['token'],time.time(),j['mid']))
            tracked=c.execute("""SELECT t.* FROM tracked_tasks t JOIN tracked_turns a
                              ON a.task_id=t.id WHERE a.mid=?""",(j['mid'],)).fetchone()
            if tracked:
                c.execute("UPDATE tracked_tasks SET status='running',updated=? WHERE id=?",
                          (time.time(),tracked['id']))
                j['session']=tracked['session']
                j['body']=TASK_RULES+'\n작업 이름: '+tracked['title']+'\n사용자 요청:\n'+j['body']
            else:
                j['session']=c.execute('SELECT session FROM rooms WHERE chat=?',(j['chat'],)).fetchone()[0]
        if action=='attachments':
            job=c.execute('SELECT * FROM jobs WHERE mid=? AND token=?',(r['mid'],r['token'])).fetchone()
            if not job or job['status']!='running':raise RuntimeError('첨부 조회 실행 소유권 불일치')
            if c.execute('SELECT 1 FROM tracked_turns WHERE mid=?',(job['mid'],)).fetchone():
                return {'files':[],'issues':[]}
            import 라크첨부,lark
            return 라크첨부.prepare(room_context(job['mid']),lark.설정읽기(),STATE)
        if action in ('heartbeat','finish'):
            c.execute('BEGIN IMMEDIATE')
            j=c.execute('SELECT * FROM jobs WHERE mid=? AND token=?',(r['mid'],r['token'])).fetchone()
            if not j:raise RuntimeError('실행 소유권 불일치')
            if action=='heartbeat':
                c.execute('UPDATE jobs SET updated=? WHERE mid=?',(time.time(),r['mid']));return {'status':j['status']}
            if j['status'] in ('completed','failed','waiting','sending','delivery_unknown','cancelled'):return {'status':j['status']}
            tracked=c.execute("""SELECT t.* FROM tracked_tasks t JOIN tracked_turns a
                              ON a.task_id=t.id WHERE a.mid=?""",(j['mid'],)).fetchone()
            answer=r['answer'];session=r.get('session')
            tracked_status = None
            if j['status']=='cancel_requested':answer='작업을 중단했어.'
            if tracked:
                first, _, detail = answer.strip().partition('\n')
                if r.get('failed') or first == '[중단]':
                    tracked_status = 'failed'
                elif first == '[답변 필요]' and session and detail.strip():
                    tracked_status = 'waiting'
                elif first == '[완료]' and detail.strip():
                    tracked_status = 'completed'
                else:
                    tracked_status = 'failed'
                    answer = '작업 결과의 상태나 이어갈 대화를 확인하지 못했어요.\n'+answer
                if first in ('[중단]','[답변 필요]','[완료]') and detail.strip() and not r.get('failed'):
                    answer = detail.strip()
                c.execute('UPDATE tracked_tasks SET session=COALESCE(?,session) WHERE id=?',(session,tracked['id']))
            elif session:c.execute('UPDATE rooms SET session=? WHERE chat=?',(session,j['chat']))
            c.execute("UPDATE jobs SET status='sending',result=?,updated=? WHERE mid=?",(answer,time.time(),j['mid']))
        elif action=='status':
            return {'tracked':[dict(x) for x in c.execute('SELECT title,status,session,current_mid FROM tracked_tasks ORDER BY updated DESC LIMIT 12')],'jobs':[dict(x) for x in c.execute('SELECT mid,status,updated FROM jobs ORDER BY created DESC LIMIT 10')],'rooms':[dict(x) for x in c.execute('SELECT * FROM rooms')]}
        elif action!='claim':raise ValueError('알 수 없는 요청')
    if action=='claim':
        if not tracked:
            try:j['room_context']=room_context(j['mid'])
            except Exception as e:j['context_error']=str(e)
        return j
    import 라크파일전송
    files=r.get('files',[])
    if files:
        import lark
        try:
            delivered=라크파일전송.deliver(r['mid'],files,db,api,lark.설정읽기(),STATE,CHAT)
            answer='요청한 파일 '+str(len(delivered))+'개를 이 방에 첨부했어.\n'+'\n'.join(x['name'] for x in delivered)
        except Exception as e:
            answer='파일은 준비했지만 이 방에 첨부하지 못했어. '+str(e)
            r['failed']=True
    else:
        if ':codex-file-citation{' in answer:
            answer='결과 파일 표시가 있었지만 전송할 파일을 확보하지 못해 첨부하지 못했어.'
            r['failed']=True
        answer=라크파일전송.clean_answer(answer)
    status = tracked_status or ('failed' if r.get('failed') else 'completed')
    if r.get('failed'):
        status = 'failed'
    if tracked:
        answer = f"{tracked['title']} · {STATUS_LABEL[status]}\n{answer}"
        if status == 'waiting':
            answer += '\n이 메시지에 직접 답장해 주세요.'
    def persist(c,state):
        c.execute('UPDATE jobs SET status=?,updated=? WHERE mid=?',(state,time.time(),r['mid']))
        if tracked:
            c.execute('UPDATE tracked_tasks SET status=?,updated=? WHERE id=? AND current_mid=?',
                      (state,time.time(),tracked['id'],r['mid']))

    try:
        reply(r['mid'],answer,'result:'+r['mid'],lambda c: persist(c,status))
    except Exception:
        status='delivery_unknown'
        with db() as c:
            persist(c,status)
    return {'status':status}

if __name__=='__main__':
    os.umask(0o077)
    print(json.dumps(rpc(json.load(sys.stdin)),ensure_ascii=False))
