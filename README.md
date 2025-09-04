# 라이어 게임 (Flask + Socket.IO)

모바일 브라우저로 접속해 실시간으로 즐기는 라이어 게임입니다. UI는 귀엽고(이모지 팍팍🥳), Render에 배포하기 편하게 구성했습니다.

## 빠른 시작 (로컬)
```bash
python -m venv .venv && source .venv/bin/activate  # Windows는 .venv\Scripts\activate
pip install -r requirements.txt
export HOST_CODE=9999  # 호스트 코드 (원하면 바꿔도 됨)
python app.py
# http://localhost:10000 접속
```

## 배포 (Render)
1. GitHub 새 저장소 생성 후 본 폴더 내용을 커밋/푸시
2. Render 대시보드에서 "New +" → "Web Service" → GitHub repo 연결
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `gunicorn -k eventlet -w 1 app:app`
5. (선택) `render.yaml` 사용 시 Infrastructure as Code로 같은 설정 유지 가능
6. 환경변수:
   - `HOST_CODE` : 호스트 권한 코드 (기본 9999)
   - `SECRET_KEY`: Flask 세션 키 (자동 생성 또는 직접 지정)

## 게임 규칙 및 흐름
- 접속 → 로비 → (호스트 권한 획득) → 게임 시작
- 7인 이상: 라이어 1 / 스파이 1 / 나머지 시민, 7인 이하: 라이어 1 / 나머지 시민
- 라이어: **주제만** 제공, 스파이/시민: **주제+제시어** 제공
- 진행(라운드 1~3 반복):  
  1) **1차 힌트**(랜덤 순서, 15초/인) →  
  2) **전체 토론**(2분) →  
  3) **1차 투표** →  
  4) **2차 힌트**(15초/인) →  
  5) **2차 투표** →  
  6) **라운드 결과** / (라이어 지목 시 30초 정답 기회)

- 점수
  - 시민 승리: 라이어 지목 & 라이어 정답 실패 → 시민 +1
  - 라이어 승리(1): 라이어 미지목 → 라이어 +2, 스파이 +1
  - 라이어 승리(2): 라이어 지목됐지만 정답 맞춤 → 라이어 +2, 스파이 +1

## 주제/제시어
- `data/topics.py` 파일에서 관리(서버 재시작 없이 코드만 수정하면 반영).

## 자주 묻는 점
- **/socket.io/socket.io.js 400**: 클라이언트는 CDN(`cdn.socket.io`)으로 불러옵니다.
- Render 프리 플랜은 연결이 유휴 시 슬립될 수 있어요. 다시 접속하면 깨워집니다.
