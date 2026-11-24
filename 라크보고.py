"""기존 라크 대기열에 에이전트 상태와 한국시간 일일 보고를 기록한다."""
import fcntl
import json
import re
import sys
import time
import uuid
from datetime import datetime

import 코덱스대화 as room

STATES = {'running','waiting','completed','failed','review'}
HEX_ID = re.compile(r'[a-f0-9]{32}')
TITLE = re.compile(r'[가-힣a-zA-Z0-9_. -]{1,60}')
RETRY_SECONDS = 29 * 60


def ingest(events, *, source):
    tool = {'claude':'클로드 코드','codex':'코덱스'}[source]
    if not isinstance(events, list) or not 1 <= len(events) <= 50:
        raise ValueError('이벤트 묶음 범위 오류')
    for e in events:
        if not (HEX_ID.fullmatch(e['id']) and HEX_ID.fullmatch(e['task'])
                and e['status'] in STATES and TITLE.fullmatch(e['title'])
                and re.fullmatch(r'[a-f0-9]{8}',e['session'])
                and re.fullmatch(r'[가-힣a-zA-Z0-9 .,:!?()·~-]{0,220}',e['summary'])
                and re.fullmatch(r'[가-힣a-zA-Z0-9 .,:!?()·~-]{0,45}',e.get('label',''))
                and re.fullmatch(r'[가-힣a-zA-Z0-9_. ()·-]{0,60}',e.get('project',''))
                and re.fullmatch(r'[가-힣a-zA-Z0-9 .,:!?()·~-]{0,80}',e.get('action',''))
                and re.fullmatch(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}',e.get('thread','00000000-0000-0000-0000-000000000000'))):
            raise ValueError('클로드 작업 보고 형식 오류')
    with room.db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS report_origins(key TEXT PRIMARY KEY,thread TEXT NOT NULL,task_id TEXT NOT NULL)')
    import 답변연결
    with room.db() as c:답변연결.setup(c)
    received = []
    with room.db() as c:
        c.execute('BEGIN IMMEDIATE')
        for e in events:
            task_id = source + ':' + e['task']
            key = source + '-event:' + e['id']
            received.append(e['id'])
            if source == 'codex' and e.get('question_group'):
                답변연결.save(c,key,e['question_group'])
            elif source=='codex' and e['status']=='waiting' and e.get('turn'):
                turn=str(uuid.UUID(e['turn']))
                답변연결.save(c,key,{'id':e['id'],'questions':[{'id':'marker:'+turn,
                    'title':e.get('action') or e['summary'] or '원래 작업에 필요한 답변을 입력해 주세요.','options':[]}]})
            if source == 'codex' and e.get('thread'):
                c.execute('INSERT OR IGNORE INTO report_origins VALUES(?,?,?)',(key,e['thread'],task_id))
            if c.execute('SELECT 1 FROM report_push WHERE key=?',(key,)).fetchone():
                continue
            old = c.execute('SELECT title,status,current_mid FROM tracked_tasks WHERE id=?',(task_id,)).fetchone()
            status = e['status']
            if source == 'codex' and status == 'failed' and e.get('summary') in (
                '진행 중에 멈췄어요.', '작업 중단 신호 수신',
                '결과가 나오기 전에 대화가 닫혔어요.', '마지막 결과 기록 전에 대화 종료',
            ):
                status = 'review'
            if source == 'codex':
                title = e.get('label') or (old['title'] if old else e['title'])
                display = {
                    'running':'작업 중', 'waiting':'🟠 답변 필요',
                    'completed':'🟢 완료', 'failed':'🔴 중단',
                    'review':'상태 확인 중',
                }[status]
                project = e.get('project') if e.get('project') not in (None,'','프로젝트 미확인') else e['title']
                action = e.get('action') or {
                    'running':'작업을 진행하고 있어요.',
                    'waiting':'코덱스의 원래 대화에서 답해 주세요.',
                    'completed':'추가 작업 없음',
                    'failed':'코덱스의 원래 대화에서 중단 이유를 확인해 주세요.',
                    'review':'코덱스의 마지막 답변을 확인해 주세요.',
                }[status]
                lines=[f"[{project}]",f"안건: {title}",display]
                if e['summary']:
                    lines.extend(('', '처리 내용',e['summary']))
                if action and action not in ('추가 작업 없음','없음'):
                    lines.extend(('', '확인 요청' if status=='waiting' else '후속 조치',action))
                text='\n'.join(lines)

                notify = status in ('waiting','completed','failed') and (old is None or old['status'] != status)
                if status == 'waiting' and old and old['status'] == 'waiting':
                    previous = c.execute('SELECT text FROM report_push WHERE key=?',
                                         (source+'-event:'+old['current_mid'],)).fetchone()
                    notify = previous is None or previous['text'] != text
            else:
                base = f"{tool} · {e['title']} · 대화 {e['session']}"
                title = base + (' · '+e['summary'] if e['summary'] else '')
                notify = old is None or old['status'] != status and status != 'running'
                text = title + ' · ' + ('작업 접수' if old is None and status=='running' else room.STATUS_LABEL[status])
                if status == 'waiting':
                    text += f'\n원래 {tool} 대화에서 질문을 확인하고 답해 주세요.'
            c.execute("""INSERT INTO tracked_tasks VALUES(?,?,?,NULL,?,?)
                ON CONFLICT(id) DO UPDATE SET status=excluded.status,title=excluded.title,
                current_mid=excluded.current_mid,updated=excluded.updated""",
                (task_id,title,status,e['id'],time.time()))
            c.execute('INSERT INTO report_push(key,text,created,state) VALUES(?,?,?,?)',
                      (key,text,time.time(),'pending' if notify else 'recorded'))
    return {'accepted':received}


def daily(now, test=False):
    if not test and now.hour < 18:
        return
    key = ('daily-test:' if test else 'daily:') + now.date().isoformat()
    with room.db() as c:
        if c.execute('SELECT 1 FROM report_push WHERE key=?',(key,)).fetchone():
            return
    report = room.report('오늘 작업',now,include_codes=False)
    if test:
        report = '일일 자동 보고 시험\n' + report
    chunks = []
    chunk = ''
    for line in report.splitlines():
        if len((chunk+line).encode()) > 9000:
            chunks.append(chunk.rstrip())
            chunk = ''
        chunk += line+'\n'
    chunks.append(chunk.rstrip())
    with room.db() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM report_push WHERE key=?',(key,)).fetchone():
            return
        for index, text in enumerate(chunks):
            c.execute('INSERT INTO report_push(key,text,created) VALUES(?,?,?)',
                      (key if not index else f'{key}:{index}',text,time.time()))


def message_content(key,text):
    with room.db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS report_origins(key TEXT PRIMARY KEY,thread TEXT NOT NULL,task_id TEXT NOT NULL)')
        if key.startswith('daily'):
            origins=c.execute("""SELECT DISTINCT o.thread,t.title,o.key FROM report_origins o
                JOIN tracked_tasks t ON o.task_id=t.id
                WHERE o.key='codex-event:'||t.current_mid
                AND t.status NOT IN ('completed','resolved') ORDER BY t.updated DESC LIMIT 15""").fetchall()
        else:
            origins=c.execute('SELECT thread,? AS title,key FROM report_origins WHERE key=?',
                              ('맥에서 원래 대화 열기',key)).fetchall()
    if not origins:
        return 'text',{'text':text}
    lines=text.splitlines()
    heading=lines[0] if key.startswith('codex-event:') and len(lines)>=3 else None
    body='\n'.join(lines[1:]) if heading else text
    elements=[{'tag':'div','text':{'tag':'plain_text','content':body}}]
    for origin in origins:
        button_title=origin['title'][:60]
        if key.startswith('codex-event:') and len(lines)>=3 and lines[2]=='🟠 답변 필요':
            button_title='코덱스에서 답변하기'
        with room.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS open_targets(key TEXT NOT NULL,thread TEXT NOT NULL,PRIMARY KEY(key,thread))')
            c.execute('INSERT OR IGNORE INTO open_targets VALUES(?,?)',(key,origin['thread']))
        native_question=False
        if key.startswith('codex-event:') and len(lines)>=3 and lines[2]=='🟠 답변 필요':
            with room.db() as c:
                import 답변연결
                답변연결.setup(c)
                native_question=c.execute('SELECT 1 FROM report_questions WHERE key=?',(key,)).fetchone() is not None
            if native_question:button_title='라크에서 답변하기'
        elements.append({'tag':'action','actions':[{
            'tag':'button','text':{'tag':'plain_text','content':button_title},
            'type':'primary','value':{'action':'reply_form' if native_question else 'open_codex','thread':origin['thread'],'report_key':key},
        }]})
    card={'config':{'wide_screen_mode':True},'elements':elements}
    if heading:
        card['header']={'title':{'tag':'plain_text','content':heading}}
    return 'interactive',card


def send_pending():
    room.STATE.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (room.STATE/'report-send.lock').open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        with room.db() as c:
            c.execute("""UPDATE report_push SET state='uncertain'
                WHERE state='pending' AND attempted<?""",(time.time()-RETRY_SECONDS,))
            queue = c.execute("""SELECT key,text FROM report_push
                WHERE state='pending' ORDER BY created,rowid LIMIT 20""").fetchall()
        sent = 0
        for row in queue:
            with room.db() as c:
                c.execute('UPDATE report_push SET attempted=COALESCE(attempted,?) WHERE key=?',
                          (time.time(),row['key']))
            try:
                kind,content = message_content(row['key'],row['text'])
                result = room.api('POST','/open-apis/im/v1/messages?receive_id_type=chat_id',{
                    'receive_id':room.CHAT,'msg_type':kind,
                    'content':json.dumps(content,ensure_ascii=False),
                    'uuid':str(uuid.uuid5(uuid.NAMESPACE_URL,row['key']))})
                mid = result['message_id']
            except Exception as e:
                print('라크 보고 전송 재확인',type(e).__name__,file=sys.stderr)
                break
            with room.db() as c:
                c.execute("UPDATE report_push SET state='sent',message=? WHERE key=?",(mid,row['key']))
            sent += 1
        return sent


def tick(test=False):
    # 코덱스 실행기가 내려가 있어도 서버의 정기 실행이 만료와 보고를 처리한다.
    with room.db() as c:
        c.execute('BEGIN IMMEDIATE')
        room.expire_jobs(c)
        c.execute("""UPDATE tracked_tasks SET status='review',updated=?
            WHERE (id LIKE 'claude:%' OR id LIKE 'codex:%') AND status='running' AND updated<?""",
                  (time.time(),time.time()-4*3600))
    now = datetime.now(room.KOREA)
    daily(now,test)
    return {'sent':send_pending()}

if __name__ == '__main__':
    import os
    os.umask(0o077)
    tick(test='--시험' in sys.argv)
