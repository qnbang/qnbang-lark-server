"""지정 작업방 자료의 파일·이미지만 내려받는다. 임의 외부 주소는 열지 않는다."""
import hashlib,json,os,re,urllib.parse,urllib.request
from pathlib import Path
MAX_BYTES=100*1024*1024

def references(context):
    found=[];seen=set()
    for item in context:
        try:body=json.loads(item.get('content','{}'))
        except (ValueError,TypeError):continue
        mid=item['message_id'];kind=item.get('message_type')
        def walk(obj):
            if isinstance(obj,dict):
                key=obj.get('file_key') or obj.get('image_key') or (obj.get('img_key') if obj.get('tag')=='img' else None)
                if key and isinstance(key,str):
                    typ='image' if obj.get('image_key') or obj.get('img_key') or kind=='image' else 'file'
                    identity=(mid,key)
                    if identity not in seen:
                        seen.add(identity);found.append({'message_id':mid,'key':key,'type':typ,'name':obj.get('file_name') or ('첨부이미지.png' if typ=='image' else '첨부파일')})
                for value in obj.values():walk(value)
            elif isinstance(obj,list):
                for value in obj:walk(value)
        walk(body)
    return found

def prepare(context,config,state):
    import lark
    token=lark.토큰받기(config)
    directory=Path(state)/'attachments';directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    manifest=[];issues=[]
    for ref in references(context):
        aid=hashlib.sha256((ref['message_id']+'\0'+ref['key']).encode()).hexdigest()
        suffix=Path(str(ref['name'])).suffix.lower()
        if not re.fullmatch(r'\.[a-z0-9]{1,10}',suffix):suffix='.png' if ref['type']=='image' else '.bin'
        target=directory/(aid+suffix)
        try:
            if not target.exists():
                path='/open-apis/im/v1/messages/'+urllib.parse.quote(ref['message_id'],safe='')+'/resources/'+urllib.parse.quote(ref['key'],safe='')+'?type='+ref['type']
                req=urllib.request.Request('https://open.larksuite.com'+path,headers={'Authorization':'Bearer '+token})
                partial=target.with_suffix(target.suffix+'.part')
                try:
                    with urllib.request.urlopen(req,timeout=35) as response,partial.open('wb') as out:
                        if int(response.headers.get('Content-Length','0') or 0)>MAX_BYTES:raise ValueError('첨부 100MB 처리 한도 초과')
                        size=0
                        while True:
                            chunk=response.read(1024*1024)
                            if not chunk:break
                            size+=len(chunk)
                            if size>MAX_BYTES:raise ValueError('첨부 100MB 처리 한도 초과')
                            out.write(chunk)
                        if not size:raise ValueError('빈 첨부')
                    os.chmod(partial,0o600);partial.replace(target)
                finally:
                    if partial.exists():partial.unlink()
            digest=hashlib.sha256(target.read_bytes()).hexdigest()
            manifest.append({'id':aid,'name':Path(str(ref['name']).replace('\\','/')).name,'type':ref['type'],'message_id':ref['message_id'],'path':str(target),'size':target.stat().st_size,'sha256':digest})
        except Exception as e:issues.append({'name':ref['name'],'message_id':ref['message_id'],'error':str(e)[:250]})
    import 메일첨부
    mail=메일첨부.prepare(context,config,directory)
    manifest+=mail['files'];issues+=mail['issues']
    return {'files':manifest,'issues':issues}
