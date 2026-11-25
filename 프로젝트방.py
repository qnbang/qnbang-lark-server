"""기존 회사 봇으로 프로젝트 폴더와 비공개 방을 한 번만 연결한다."""
import fcntl,json,re,time,unicodedata
from pathlib import PurePosixPath
import 코덱스대화 as room


def setup(c):
    c.execute('''CREATE TABLE IF NOT EXISTS project_rooms(
        project_key TEXT PRIMARY KEY,name TEXT NOT NULL,local_path TEXT NOT NULL,
        drive_url TEXT NOT NULL,report_name TEXT NOT NULL,chat TEXT UNIQUE,
        state TEXT NOT NULL,updated REAL NOT NULL,notice TEXT)''')


def lookup(chat):
    with room.db() as c:
        setup(c)
        row=c.execute("SELECT * FROM project_rooms WHERE chat=? AND state='active'",(chat,)).fetchone()
    return dict(row) if row else None


def validate(r):
    r={k:unicodedata.normalize('NFC',str(r.get(k,''))) for k in
       ('project_key','name','local_path','drive_url','report_name')}
    parts=PurePosixPath(r['project_key']).parts
    if len(parts)!=2 or parts[0] not in ('01_프로젝트','02_자체브랜드','03_실험') or parts[1] in ('.','..'):
        raise ValueError('메인 프로젝트 폴더만 연결할 수 있습니다.')
    if parts[1]!=r['name'] or not 1<=len(r['name'])<=60 or any(ord(x)<32 for x in r['name']):
        raise ValueError('프로젝트 폴더명 확인 필요')
    suffix='/큐앤뱅 뉴 대시보드/'+r['project_key']
    if not r['local_path'].startswith('/Users/charlie/') or not r['local_path'].endswith(suffix) or '..' in PurePosixPath(r['local_path']).parts:
        raise ValueError('프로젝트 실행 경로 확인 필요')
    if not re.fullmatch(r'https://drive\.google\.com/drive/folders/[A-Za-z0-9_-]+',r['drive_url']):
        raise ValueError('확인된 드라이브 폴더 주소가 필요합니다.')
    if not re.fullmatch(r'[가-힣a-zA-Z0-9_. ()·-]{1,60}',r['report_name']):
        raise ValueError('보고 프로젝트명 확인 필요')
    return r


def verify(chat,r):
    data=room.api('GET','/open-apis/im/v1/chats/'+chat+'?user_id_type=open_id')
    if data.get('name')!=r['name'] or data.get('owner_id')!=room.OWNER or data.get('external') is not False or data.get('chat_type')!='private':
        raise RuntimeError('방 이름·소유자·비공개 조직 소속 확인 필요')
    members=room.api('GET','/open-apis/im/v1/chats/'+chat+'/members?member_id_type=open_id&page_size=100')
    if room.OWNER not in [x.get('member_id') for x in members.get('items',[])]:
        raise RuntimeError('사용자의 방 참여 확인 필요')


def ensure(request):
    r=validate(request)
    room.STATE.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (room.STATE/'project-room.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        with room.db() as c:
            setup(c)
            old=c.execute('SELECT * FROM project_rooms WHERE project_key=?',(r['project_key'],)).fetchone()
        if old:
            if any(old[k]!=r[k] for k in r):
                raise RuntimeError('기존 연결 정보와 달라 자동 변경하지 않았습니다.')
            if old['state']!='active':
                raise RuntimeError('이전 방 생성 결과 대조가 필요합니다. 중복 생성하지 않았습니다.')
            verify(old['chat'],r)
            return {'state':'active','chat':old['chat'],'created':False}
        # 조회 자체가 실패하면 방 생성 시도나 생성 중 기록을 만들지 않는다.
        room.api('GET','/open-apis/im/v1/chats/'+room.CHAT)
        with room.db() as c:
            c.execute('INSERT INTO project_rooms VALUES(?,?,?,?,?,NULL,?,?,NULL)',
                      (*[r[k] for k in ('project_key','name','local_path','drive_url','report_name')],'creating',time.time()))
        try:
            made=room.api('POST','/open-apis/im/v1/chats?user_id_type=open_id&set_bot_manager=true',{
                'name':r['name'],'description':'프로젝트 자료와 작업기록: '+r['drive_url'],
                'owner_id':room.OWNER,'user_id_list':[room.OWNER],
                'chat_mode':'group','chat_type':'private','external':False})
            chat=made['chat_id']
            if not re.fullmatch(r'oc_[a-f0-9]{32}',chat):raise RuntimeError('방 식별자 확인 필요')
            with room.db() as c:
                c.execute("UPDATE project_rooms SET chat=?,state='verifying',updated=? WHERE project_key=?",(chat,time.time(),r['project_key']))
            verify(chat,r)
            with room.db() as c:
                c.execute("UPDATE project_rooms SET state='active',updated=? WHERE project_key=?",(time.time(),r['project_key']))
                c.execute('INSERT OR IGNORE INTO rooms VALUES(?,NULL)',(chat,))
            # 설명에 폴더 링크가 있으므로 알림 발송에 실패해도 방을 새로 만들지 않는다.
            notice=room.api('POST','/open-apis/im/v1/messages?receive_id_type=chat_id',{
                'receive_id':chat,'msg_type':'text','content':json.dumps({'text':r['name']+'\n프로젝트 폴더: '+r['drive_url']+'\n이 방의 요청은 연결된 폴더의 기존 작업기록을 확인하고 이어서 처리합니다.'},ensure_ascii=False)})
            with room.db() as c:c.execute('UPDATE project_rooms SET notice=? WHERE project_key=?',(notice['message_id'],r['project_key']))
            return {'state':'active','chat':chat,'created':True}
        except Exception:
            # 생성 성공 여부가 불명확하면 확인 전 재생성을 막는다.
            with room.db() as c:c.execute("UPDATE project_rooms SET state=CASE WHEN state='active' THEN state ELSE 'review' END,updated=? WHERE project_key=?",(time.time(),r['project_key']))
            raise


def report_target(project):
    with room.db() as c:
        setup(c)
        rows=c.execute("SELECT chat FROM project_rooms WHERE state='active' AND report_name=?",(project,)).fetchall()
    return rows[0]['chat'] if len(rows)==1 else room.CHAT
