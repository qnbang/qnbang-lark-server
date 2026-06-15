#!/bin/bash
# 서버 본체(코드 + tasks.json)를 깃허브에 자동 백업한다.
# - 변경이 있을 때만 커밋한다.
# - 푸시가 실패하면 커밋은 로컬에 남고, 다음 주기에 밀린 커밋까지 다시 푸시한다.
# - 결과는 cron이 자동백업로그.txt 에 시각과 함께 남긴다.
# 주의: bash 변수명은 영문만 가능(한글 변수명 쓰면 깨짐). 로그 문구만 한글.
set -u
cd /home/charlie/lark-calendar || exit 1
now="$(date '+%F %T')"

git add -A

# 새 변경이 있으면 커밋
if ! git diff --cached --quiet; then
  files="$(git diff --cached --name-only | tr '\n' ' ')"
  git -c user.name='신종호' -c user.email='ceo@qnbang.com' \
      commit -q -m "자동백업 ${now}: ${files}"
fi

# 로컬이 원격보다 앞서 있으면(이번 커밋 또는 지난번 실패분) 푸시
if [ -n "$(git log origin/main..main 2>/dev/null)" ]; then
  if git push -q origin main 2>/dev/null; then
    echo "${now} 백업·푸시 완료"
  else
    echo "${now} !! 푸시 실패 — 다음 주기 재시도(커밋은 로컬 보관됨)"
  fi
else
  echo "${now} 변경 없음 — 건너뜀"
fi
