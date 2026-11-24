"""보고 카드에서 받은 답을 원래 코덱스 대화에 연결한다."""
import json
import time
import uuid
import 코덱스대화 as room


def setup(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS report_questions(
        key TEXT PRIMARY KEY,group_id TEXT NOT NULL,questions TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS reply_requests(
        id TEXT PRIMARY KEY,key TEXT NOT NULL UNIQUE,thread TEXT NOT NULL,
        questions TEXT NOT NULL,answers TEXT NOT NULL,state TEXT NOT NULL,
        created REAL NOT NULL,updated REAL NOT NULL,token TEXT,error TEXT);''')


def save(c,key,group):
    if not isinstance(group,dict):raise ValueError('질문 묶음 오류')
    gid=uuid.UUID(hex=group['id']).hex
    questions=group['questions']
    if not isinstance(questions,list) or not 1<=len(questions)<=3:raise ValueError('질문 개수 오류')
    for q in questions:
        if q['id'].startswith('marker:'):
            uuid.UUID(q['id'].split(':',1)[1])
        else:
            ident=json.loads(q['id'])
            if not (len(ident)==3 and ident[0]=='request_user_input_async' and isinstance(ident[1],str)
                    and isinstance(ident[2],int)):raise ValueError('원본 질문 식별자 오류')
        if not isinstance(q['title'],str) or not 1<=len(q['title'])<=220:raise ValueError('원본 질문 제목 오류')
    c.execute('INSERT OR IGNORE INTO report_questions VALUES(?,?,?)',
              (key,gid,json.dumps(questions,ensure_ascii=False)))


def response(text,card=None):
    from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTriggerResponse
    body={'toast':{'type':'info','content':text}}
    if card:body['card']={'type':'raw','data':card}
    return P2CardActionTriggerResponse(body)


def receive(e,key,target):
    action=e.action
    with room.db() as c:
        setup(c)
        row=c.execute('''SELECT q.*,p.text,t.status,t.current_mid FROM report_questions q
          JOIN report_push p ON p.key=q.key JOIN report_origins o ON o.key=q.key
          JOIN tracked_tasks t ON t.id=o.task_id WHERE q.key=? AND o.thread=?''',(key,target)).fetchone()
        if not row or row['status']!='waiting' or key!='codex-event:'+row['current_mid']:
            return response('이미 답했거나 지난 질문입니다. 최신 보고를 확인해 주세요.')
        old=c.execute('SELECT state FROM reply_requests WHERE key=?',(key,)).fetchone()
        if old:return response('이 답변은 이미 접수됐습니다. 중복 전달하지 않습니다.')
        questions=json.loads(row['questions'])
        if action.value['action']=='reply_form':
            import 라크보고
            kind,card=라크보고.message_content(key,row['text'])
            card['elements']=[x for x in card['elements'] if x['tag']!='action']
            elements=[]
            for i,q in enumerate(questions):
                label=q['title']
                if q.get('options'):label+=' (선택 예: '+', '.join(q['options'])+')'
                elements.append({'tag':'input','name':'answer_'+str(i),'label':{'tag':'plain_text','content':label},
                    'placeholder':{'tag':'plain_text','content':'답변을 입력해 주세요. 비밀번호·인증번호는 입력하지 마세요.'},
                    'required':True,'max_length':1000,'label_position':'top'})
            elements.append({'tag':'button','name':'submit_reply','action_type':'form_submit',
                'text':{'tag':'plain_text','content':'원래 코덱스 작업에 답변 보내기'},'type':'primary',
                'value':{'action':'submit_reply','report_key':key,'thread':target}})
            card['elements'].append({'tag':'form','name':'codex_reply','elements':elements})
            return response('이 카드 안에서 답변을 입력해 주세요.',card)
        values=getattr(action,'form_value',None)
        if not isinstance(values,dict):return response('입력한 답변을 확인하지 못했습니다.')
        answers={str(i):values.get('answer_'+str(i),'') for i in range(len(questions))}
        if any(not isinstance(v,str) or not v.strip() or len(v)>1000 for v in answers.values()):
            return response('모든 질문에 답변을 입력해 주세요. 답변은 각각 1,000자까지 보낼 수 있습니다.')
        rid=str(uuid.uuid5(uuid.NAMESPACE_URL,'lark-reply:'+key))
        c.execute('INSERT OR IGNORE INTO reply_requests VALUES(?,?,?,?,?,?,?,?,NULL,NULL)',
            (rid,key,target,row['questions'],json.dumps(answers,ensure_ascii=False),'pending',time.time(),time.time()))
    return response('답변을 접수했습니다. 원래 코덱스 대화로 전달하겠습니다.')


def claim():
    with room.db() as c:
        setup(c)
        c.execute('BEGIN IMMEDIATE')
        # 답변은 공식 대기열의 고정 식별자로 중복을 막으므로 수신 확인이 끊겨도 재전달할 수 있다.
        c.execute("UPDATE reply_requests SET state='pending' WHERE state='sending' AND updated<?",(time.time()-90,))
        row=c.execute("SELECT * FROM reply_requests WHERE state='pending' ORDER BY created LIMIT 1").fetchone()
        if not row:return None
        token=uuid.uuid4().hex
        c.execute("UPDATE reply_requests SET state='sending',token=?,updated=? WHERE id=?",(token,time.time(),row['id']))
        return {'kind':'reply_thread','id':row['id'],'thread':row['thread'],'token':token,
                'questions':json.loads(row['questions']),'answers':json.loads(row['answers'])}


def finish(payload):
    delivered=payload.get('delivered') is True
    with room.db() as c:
        row=c.execute("SELECT * FROM reply_requests WHERE id=? AND token=? AND state='sending'",(payload['id'],payload['token'])).fetchone()
        if not row:raise RuntimeError('답변 수신 확인 소유권 불일치')
        c.execute('UPDATE reply_requests SET state=?,updated=?,error=?,answers=? WHERE id=?',
            ('queued' if delivered else 'failed',time.time(),None if delivered else '원래 대화 전달 실패',
             '{}' if delivered else row['answers'],row['id']))
        p=c.execute('SELECT message,text FROM report_push WHERE key=?',(row['key'],)).fetchone()
    # 대기열 전달 성공과 실제 업무 완료를 구분한다. 대기 상태는 원래 대화가 답을 읽은 뒤 감시기가 갱신한다.
    import 라크보고
    kind,card=라크보고.message_content(row['key'],p['text'])
    card['elements']=[x for x in card['elements'] if x['tag']!='action']
    text='답변을 원래 코덱스 대화의 대기열에 전달했습니다.' if delivered else '답변을 전달하지 못했습니다. 원래 코덱스 대화에서 확인해 주세요.'
    card['elements'].append({'tag':'div','text':{'tag':'plain_text','content':text}})
    card['elements'].append({'tag':'action','actions':[{'tag':'button','type':'default',
        'text':{'tag':'plain_text','content':'맥에서 원래 대화 열기'},
        'value':{'action':'open_codex','thread':row['thread'],'report_key':row['key']}}]})
    try:room.api('PATCH','/open-apis/im/v1/messages/'+p['message'],{'content':json.dumps(card,ensure_ascii=False)})
    except Exception:pass
    return {'status':'queued' if delivered else 'failed'}
