"""사용자가 전달한 카드와 발신자·제목·날짜가 일치하는 메일의 첨부만 읽는다."""
import email,hashlib,imaplib,json,os,re,unicodedata
from datetime import datetime,timedelta,timezone
from email.header import decode_header
from email.utils import parseaddr,parsedate_to_datetime
from pathlib import Path
MAX_BYTES=100*1024*1024

def decoded(value):
    return ''.join(x.decode(charset or 'utf-8',errors='replace') if isinstance(x,bytes) else x for x,charset in decode_header(value or ''))

def normalized(subject):
    return re.sub(r'\s+','',unicodedata.normalize('NFC',subject)).casefold()

def card_ref(item):
    try:c=json.loads(item.get('content','{}'))
    except (ValueError,TypeError):return None
    if 'client/mail/forward/card' not in json.dumps(c):return None
    texts=[]
    def walk(o):
        if isinstance(o,dict):
            if o.get('tag')=='text' and isinstance(o.get('text'),str):texts.append(o['text'])
            for v in o.values():walk(v)
        elif isinstance(o,list):
            for v in o:walk(v)
    walk(c)
    sender=''
    for i,t in enumerate(texts[:-1]):
        if any(k in t for k in ('发件人','寄件者','보낸사람','보낸 사람','From:')):
            cleaned=re.sub('[\u00ad\u200b\u200e\u200f]','',texts[i+1]);sender=parseaddr(cleaned)[1]
    dates=re.findall(r'(20\d{2})[年./-]\s*(\d{1,2})[月./-]\s*(\d{1,2})','\n'.join(texts))
    day='-'.join(dates[-1]) if dates else ''
    if not c.get('title') or not sender:return None
    return {'title':c['title'],'sender':sender,'day':day,'card_message_id':item['message_id']}

def select_matches(headers,ref):
    out=[]
    for uid,msg in headers:
        if parseaddr(decoded(msg.get('From')))[1].casefold()!=ref['sender'].casefold():continue
        if normalized(decoded(msg.get('Subject')))!=normalized(ref['title']):continue
        if ref['day']:
            try:
                expected=datetime.strptime(ref['day'],'%Y-%m-%d').date()
                actual=parsedate_to_datetime(msg.get('Date')).astimezone(timezone(timedelta(hours=9))).date()
                if actual!=expected:continue
            except (ValueError,TypeError,OverflowError):continue
        out.append(uid)
    return out

def save_parts(message,ref,uid,directory):
    files=[];issues=[]
    for i,part in enumerate(message.walk()):
        if part.is_multipart():continue
        typ=part.get_content_type();name=part.get_filename()
        is_image=typ.startswith('image/') and bool(part.get('Content-ID'))
        if not name and part.get_content_disposition()!='attachment' and not is_image:continue
        name=decoded(name) if name else ('메일이미지_'+str(i)+'.'+typ.split('/')[-1] if is_image else '메일첨부_'+str(i))
        name=Path(name.replace('\\','/')).name
        data=part.get_payload(decode=True) or b''
        if not data or len(data)>MAX_BYTES:
            issues.append({'name':name,'error':'빈 첨부 또는 100MB 처리 한도 초과'});continue
        aid=hashlib.sha256((str(ref['card_message_id'])+'\0'+str(uid)+'\0'+str(i)).encode()).hexdigest()
        suffix=Path(name).suffix.lower()
        if not re.fullmatch(r'\.[a-z0-9]{1,10}',suffix):suffix='.bin'
        target=directory/(aid+suffix)
        if not target.exists():
            tmp=target.with_suffix(target.suffix+'.part');tmp.write_bytes(data);os.chmod(tmp,0o600);tmp.replace(target)
        files.append({'id':aid,'name':name,'type':'image' if typ.startswith('image/') else 'file','message_id':ref['card_message_id'],'path':str(target),'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'source':'전달한 카드와 일치하는 회사 메일 원본'})
    return {'files':files,'issues':issues}

def prepare(context,config,directory):
    refs=[ref for x in context if (ref:=card_ref(x))]
    if not refs:return {'files':[],'issues':[]}
    if not config.get('메일첨부',{}).get('enabled',False):
        return {'files':[],'issues':[{'kind':'mail_card','message_ids':[r['card_message_id'] for r in refs],'error':'메일 카드 본문은 확보됨. 메일 첨부 원본의 계정 인증 복구 대기. 직접 전달된 파일과 구분해야 함.'}]}
    c=config.get('메일',{});client=None;files=[];issues=[]
    try:
        client=imaplib.IMAP4_SSL(c.get('imap_host','imap.daouoffice.com'),int(c.get('imap_port',993)),timeout=25)
        client.login(c['username'],c['password'])
        if client.select(c.get('folder','Inbox'),readonly=True)[0]!='OK':raise RuntimeError('읽기 전용 받은편지함 접근 실패')
        for ref in refs:
            day=datetime.strptime(ref['day'],'%Y-%m-%d') if ref['day'] else datetime.now()
            since=(day-timedelta(days=2)).strftime('%d-%b-%Y')
            sender=ref['sender']
            if not re.fullmatch(r'[A-Za-z0-9._+%-]+@[A-Za-z0-9.-]+',sender):raise ValueError('메일 발신자 형식 확인 필요')
            st,rows=client.uid('search',None,'FROM','"'+sender+'"','SINCE','"'+since+'"')
            if st!='OK':raise RuntimeError('메일 원본 검색 실패')
            headers=[]
            for uid in rows[0].split()[-100:]:
                st,parts=client.uid('fetch',uid,'(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)] RFC822.SIZE)')
                if st!='OK':continue
                for part in parts:
                    if isinstance(part,tuple):
                        match=re.search(rb'RFC822.SIZE (\d+)',part[0]);size=int(match[1]) if match else MAX_BYTES+1
                        if size>MAX_BYTES:continue
                        headers.append((uid,email.message_from_bytes(part[1])))
            matches=select_matches(headers,ref)
            if len(matches)!=1:
                issues.append({'name':ref['title'],'error':'메일 원본을 하나로 확정하지 못함: '+str(len(matches))+'건'});continue
            uid=matches[0];st,parts=client.uid('fetch',uid,'(BODY.PEEK[])')
            if st!='OK':raise RuntimeError('메일 원본 다운로드 실패')
            raw=next((p[1] for p in parts if isinstance(p,tuple)),b'')
            if len(raw)>MAX_BYTES:raise ValueError('원본 메일 100MB 처리 한도 초과')
            result=save_parts(email.message_from_bytes(raw),ref,uid,directory);files+=result['files'];issues+=result['issues']
    except Exception as e:
        issues.append({'kind':'mail_card','error':'메일 첨부 읽기 실패: '+type(e).__name__})
    finally:
        if client:
            try:client.logout()
            except Exception:pass
    return {'files':files,'issues':issues}
