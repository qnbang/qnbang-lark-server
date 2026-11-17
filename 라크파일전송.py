"""코덱스가 만든 결과 파일을 지정 작업방에 실제 파일 메시지로 보낸다."""
import hashlib,json,mimetypes,re,time,urllib.request,uuid
from pathlib import Path
ALLOWED={'.pdf','.png','.jpg','.jpeg','.webp','.hwp','.hwpx','.docx','.xlsx','.csv','.zip','.txt','.md','.pptx'}
MAX_BYTES=100*1024*1024

def output_paths(answer,root):
    paths=re.findall(r':codex-file-citation\{([^}]+)\}',answer)
    found=[]
    for attrs in paths:
        if not re.search(r'purpose\s*=\s*["\']output["\']',attrs):continue
        match=re.search(r'path\s*=\s*["\']([^"\']+)["\']',attrs)
        if match:found.append(match[1])
    found+=re.findall(r'\]\((?:<)?(/[^\n)>]+)(?:>)?\)',answer)
    result=[];seen=set();root=Path(root).resolve()
    for name in found:
        p=Path(name).resolve()
        try:p.relative_to(root)
        except ValueError:continue
        if p in seen or not p.is_file() or p.suffix.lower() not in ALLOWED or p.name.startswith('.'):continue
        if not 0<p.stat().st_size<=MAX_BYTES:continue
        seen.add(p);result.append(p)
    return result

def clean_answer(answer):
    answer=re.sub(r':codex-file-citation\{[^}]+\}','',answer)
    answer=re.sub(r'\[([^\]]+)\]\((?:<)?/[^\n)>]+(?:>)?\)',r'\1',answer)
    return re.sub(r'\n{3,}','\n\n',answer).strip()

def upload(path,name,config):
    import lark
    token=lark.토큰받기(config)
    boundary='QnbangFile'+uuid.uuid4().hex
    safe_name=Path(name.replace('\\','/')).name.replace('"','_').replace('\r','').replace('\n','')
    data=Path(path).read_bytes()
    if not 0<len(data)<=MAX_BYTES:raise ValueError('결과 파일 크기 확인 필요')
    fields=[]
    for key,value in [('file_type','stream'),('file_name',safe_name)]:
        fields.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+key+'"\r\n\r\n'+value+'\r\n').encode())
    fields.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="file"; filename="'+safe_name+'"\r\nContent-Type: '+(mimetypes.guess_type(safe_name)[0] or 'application/octet-stream')+'\r\n\r\n').encode()+data+b'\r\n')
    body=b''.join(fields)+('--'+boundary+'--\r\n').encode()
    request=urllib.request.Request('https://open.larksuite.com/open-apis/im/v1/files',data=body,headers={'Authorization':'Bearer '+token,'Content-Type':'multipart/form-data; boundary='+boundary},method='POST')
    try:
        with urllib.request.urlopen(request,timeout=90) as response:r=json.load(response)
    except urllib.error.HTTPError as e:
        try:r=json.load(e)
        except Exception:raise RuntimeError('라크 파일 업로드 HTTP 오류')
    if r.get('code')!=0:
        msg=str(r.get('msg',''))
        if r.get('code')==99991672 or 'im:resource' in msg:raise RuntimeError('라크 봇 파일 업로드 권한 필요: im:resource:upload 또는 im:resource')
        raise RuntimeError('라크 파일 업로드 오류 '+str(r.get('code')))
    return r['data']['file_key']

def deliver(mid,items,db,api,config,state,chat):
    results=[];base=(Path(state)/'outgoing').resolve()
    for item in items:
        p=Path(item['path']).resolve()
        try:p.relative_to(base)
        except ValueError:raise ValueError('승인된 결과 파일 경로가 아님')
        if not p.is_file() or p.suffix.lower() not in ALLOWED:raise ValueError('보낼 파일 형식 확인 필요')
        data=p.read_bytes();digest=hashlib.sha256(data).hexdigest()
        if digest!=item['sha256']:raise ValueError('전송 파일 무결성 불일치')
        key='file:'+mid+':'+digest
        with db() as c:
            old=c.execute('SELECT state,message FROM outbox WHERE key=?',(key,)).fetchone()
        if old:
            if old['state']=='sent':results.append({'name':item['name'],'message_id':old['message']});continue
            raise RuntimeError('파일 전송 결과 확인 필요: 자동 중복 전송하지 않음')
        # 업로드 실패는 방에 메시지를 만들지 않는다. 권한 복구 후 명시 재전송 가능.
        file_key=upload(p,item['name'],config)
        with db() as c:c.execute('INSERT INTO outbox VALUES(?,?,?)',(key,'sending',''))
        try:
            sent=api('POST','/open-apis/im/v1/messages?receive_id_type=chat_id',{'receive_id':chat,'msg_type':'file','content':json.dumps({'file_key':file_key}), 'uuid':str(uuid.uuid5(uuid.NAMESPACE_URL,key))})
        except Exception:
            with db() as c:c.execute("UPDATE outbox SET state='uncertain' WHERE key=?",(key,))
            raise
        with db() as c:c.execute("UPDATE outbox SET state='sent',message=? WHERE key=?",(sent['message_id'],key))
        results.append({'name':item['name'],'message_id':sent['message_id']})
    return results
