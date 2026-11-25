"""기존 메인 프로젝트 폴더를 회사 라크 봇의 비공개 방과 연결한다."""
import argparse,ast,json,subprocess,sys,unicodedata
from pathlib import Path
ROOT=Path('/Users/charlie/Library/CloudStorage/GoogleDrive-chairlie92.biz@gmail.com/내 드라이브/큐앤뱅 뉴 대시보드')
HERE=Path(__file__).resolve().parent

def payload(folder,url,report_name=None):
    actual=Path(folder).resolve(strict=True)
    if not actual.is_dir():raise ValueError('실제 프로젝트 폴더가 필요합니다.')
    # 맥의 한글 파일명 정규화 차이는 비교에만 반영한다.
    root=unicodedata.normalize('NFC',str(ROOT.resolve()))
    normalized=unicodedata.normalize('NFC',str(actual))
    rel=Path(normalized).relative_to(root)
    if len(rel.parts)!=2 or rel.parts[0] not in ('01_프로젝트','02_자체브랜드','03_실험'):
        raise ValueError('자료·제작 하위 폴더 대신 메인 프로젝트 폴더를 지정해 주세요.')
    return {'action':'project_room_ensure','project_key':rel.as_posix(),'name':rel.name,
            'local_path':normalized,'drive_url':url,'report_name':report_name or rel.name}

def connect(data):
    tree=ast.parse((HERE/'코덱스실행기.py').read_text())
    cmd=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
             and any(isinstance(x,ast.Name) and x.id=='COMMAND' for x in n.targets))
    cmd.remove('-t')
    # 기존 서버 인증 경로를 그대로 사용하며, 비밀 설정을 읽거나 복사하지 않는다.
    remote='''import json,sys,urllib.error
import 코덱스대화 as room
try:
 print(json.dumps(room.rpc(json.load(sys.stdin)),ensure_ascii=False))
except urllib.error.HTTPError as exc:
 try: detail=json.load(exc)
 except (ValueError,TypeError): detail={}
 code=detail.get('code')
 message='월 API 한도 초과로 실제 방 연결을 보류했습니다.' if code==99991403 else '라크 API 권한 또는 응답을 확인해야 합니다.'
 print(json.dumps({'state':'pending','code':code,'message':message},ensure_ascii=False))
except Exception as exc:
 print(json.dumps({'state':'pending','message':str(exc)[:180]},ensure_ascii=False))
'''
    import shlex
    cmd[-1]='cd /home/charlie/lark-calendar && ./venv/bin/python -c '+shlex.quote(remote)
    result=subprocess.run(cmd,input=json.dumps(data,ensure_ascii=False),text=True,capture_output=True,timeout=55)
    if result.returncode:raise RuntimeError('기존 라크 서버에 연결하지 못했습니다.')
    return json.loads(result.stdout.strip().splitlines()[-1])

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--folder',required=True);p.add_argument('--drive-url',required=True)
    p.add_argument('--report-name');p.add_argument('--check',action='store_true',help='외부 요청 없이 입력만 검증')
    args=p.parse_args();data=payload(args.folder,args.drive_url,args.report_name)
    result={'state':'input_validated','project':data['name']} if args.check else connect(data)
    print(json.dumps(result,ensure_ascii=False));return 0 if result['state'] in ('active','input_validated') else 2
if __name__=='__main__':
    try:sys.exit(main())
    except (ValueError,OSError,RuntimeError,subprocess.TimeoutExpired) as e:
        print(json.dumps({'state':'pending','message':str(e)[:180]},ensure_ascii=False));sys.exit(2)
