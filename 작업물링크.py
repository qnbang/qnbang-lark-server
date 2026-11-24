"""최종 답변에 실제로 전달한 작업 문서의 링크만 보고 카드용으로 정리한다."""
import re
import unicodedata
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode


def clean(link):
    if not isinstance(link,dict) or not isinstance(link.get('url'),str):return None
    try:
        u=urlsplit(link['url'].strip().rstrip(').,;!'))
        if u.scheme!='https' or u.username or u.password or u.port not in (None,443):return None
        host=(u.hostname or '').lower()
        query=dict(parse_qsl(u.query))
        if any(re.search(r'token|secret|signature|resourcekey|password|credential|api_key|access_key',k,re.I) for k in query):return None
        path=u.path;params={};fragment=''
        if host=='docs.google.com':
            m=re.match(r'^/(document|spreadsheets|presentation)/d/([A-Za-z0-9_-]{8,})(?:/|$)',path)
            if not m:return None
            kind={'document':'구글 문서 보기','spreadsheets':'구글 시트 보기','presentation':'구글 슬라이드 보기'}[m[1]]
            path='/'+m[1]+'/d/'+m[2]+'/edit'
            if re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',query.get('tab','')):params['tab']=query['tab']
            if re.fullmatch(r'gid=\d+',u.fragment):fragment=u.fragment
        elif host=='drive.google.com':
            m=re.match(r'^/drive/(?:u/\d+/)?folders/([A-Za-z0-9_-]{8,})(?:/|$)',path)
            if m:path='/drive/folders/'+m[1];kind='드라이브 폴더 보기'
            else:
                m=re.match(r'^/file/d/([A-Za-z0-9_-]{8,})(?:/|$)',path)
                if not m:return None
                path='/file/d/'+m[1]+'/view';kind='파일 보기'
        elif host in ('figma.com','www.figma.com'):
            m=re.match(r'^/(design|file|proto|board|slides)/([A-Za-z0-9_-]{8,})(?:/|$)',path)
            if not m:return None
            host='www.figma.com';path='/'+m[1]+'/'+m[2];kind='피그마 보기'
            for k in ('node-id','page-id'):
                if re.fullmatch(r'[0-9:-]{1,60}',query.get(k,'')):params[k]=query[k]
        else:return None
        title=unicodedata.normalize('NFC',str(link.get('title') or kind))
        title=re.sub(r'[^가-힣A-Za-z0-9 _.,()·~-]','',title).strip()[:45] or kind
        return {'title':title,'url':urlunsplit(('https',host,path,urlencode(params),fragment)),'button':kind}
    except (ValueError,TypeError):return None


def normalize(links):
    if not isinstance(links,list):return []
    result=[];seen=set()
    for link in links[:30]:
        item=clean(link)
        if not item:continue
        u=urlsplit(item['url']);key=u.netloc+u.path
        if key in seen:continue
        seen.add(key);result.append(item)
        if len(result)==3:break
    return result


def extract(text):
    if not isinstance(text,str):return []
    links=[{'title':m[1],'url':m[2]} for m in re.finditer(r'\[([^\]\n]{1,160})\]\((https://[^\s)]+)\)',text)]
    links.extend({'url':m[0]} for m in re.finditer(r'https://[^\s<>"\]]+',text))
    return normalize(links)
