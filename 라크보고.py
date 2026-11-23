"""기존 라크 대기열에 클로드 상태와 한국시간 일일 보고를 기록한다."""
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


def ingest(events):
    if not isinstance(events, list) or not 1 <= len(events) <= 50:
        raise ValueError('이벤트 묶음 범위 오류')
    for e in events:
        if not (HEX_ID.fullmatch(e['id']) and HEX_ID.fullmatch(e['task'])
                and e['status'] in STATES and TITLE.fullmatch(e['title'])
                and re.fullmatch(r'[a-f0-9]{8}',e['session'])
                and re.fullmatch(r'[가-힣a-zA-Z0-9 .,:!?()·-]{0,80}',e['summary'])):
            raise ValueError('클로드 작업 보고 형식 오류')
    received = []
    with room.db() as c:
        c.execute('BEGIN IMMEDIATE')
        for e in events:
            task_id = 'claude:' + e['task']
            key = 'claude-event:' + e['id']
            received.append(e['id'])
            if c.execute('SELECT 1 FROM report_push WHERE key=?',(key,)).fetchone():
                continue
            old = c.execute('SELECT title,status FROM tracked_tasks WHERE id=?',(task_id,)).fetchone()
            base = f"클로드 코드 · {e['title']} · 대화 {e['session']}"
            title = base + (' · '+e['summary'] if e['summary'] else '')
            status = e['status']
            c.execute("""INSERT INTO tracked_tasks VALUES(?,?,?,NULL,?,?)
                ON CONFLICT(id) DO UPDATE SET status=excluded.status,title=excluded.title,
                current_mid=excluded.current_mid,updated=excluded.updated""",
                (task_id,title,status,e['id'],time.time()))
            notify = old is None or old['status'] != status and status != 'running'
            text = title + ' · ' + ('작업 접수' if old is None and status=='running' else room.STATUS_LABEL[status])
            if status == 'waiting':
                text += '\n원래 클로드 코드 대화에서 질문을 확인하고 답해 주세요.'
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
    report = room.report('오늘 작업',now)
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
                result = room.api('POST','/open-apis/im/v1/messages?receive_id_type=chat_id',{
                    'receive_id':room.CHAT,'msg_type':'text',
                    'content':json.dumps({'text':row['text']},ensure_ascii=False),
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
            WHERE id LIKE 'claude:%' AND status='running' AND updated<?""",
                  (time.time(),time.time()-4*3600))
    now = datetime.now(room.KOREA)
    daily(now,test)
    return {'sent':send_pending()}

if __name__ == '__main__':
    import os
    os.umask(0o077)
    tick(test='--시험' in sys.argv)
