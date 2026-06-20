# -*- coding: utf-8 -*-
# 실시간.py에 과업방 라우팅 연결: import 과업해석 + elif(과업방 chat_id → 과업메시지처리)
s = open('실시간.py', encoding='utf-8').read()
ch = False
if 'import 과업해석' not in s:
    s = s.replace('import 처리\n', 'import 처리\nimport 과업해석\n', 1); ch = True
elif_block = ('        elif chat_id == "oc_9c6524739c743cfb0f5d6b60ae8430d3":\n'
              '            과업해석.과업메시지처리(본문)\n')
anchor = '        else:\n            print("미등록방chat:'
if '과업해석.과업메시지처리' not in s and anchor in s:
    s = s.replace(anchor, elif_block + anchor, 1); ch = True
open('실시간.py', 'w', encoding='utf-8').write(s)
print('패치됨' if ch else '이미 적용됐거나 앵커 못 찾음')
