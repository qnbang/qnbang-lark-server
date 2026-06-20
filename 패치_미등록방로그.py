# -*- coding: utf-8 -*-
# 실시간.py의 else(모르는 방) 분기에 chat_id 로그 한 줄 추가 — 과업방 chat_id 잡기용(임시).
s = open('실시간.py', encoding='utf-8').read()
old = '            return  # 우리가 쓰는 방이 아니면 무시'
new = '            print("미등록방chat:", chat_id, 본문[:20], flush=True)\n' + old
if '미등록방chat' in s:
    print('이미 적용됨')
elif old in s:
    open('실시간.py', 'w', encoding='utf-8').write(s.replace(old, new, 1))
    print('패치 적용 완료')
else:
    print('패턴 못 찾음 — 수동 확인 필요')
