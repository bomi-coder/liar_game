import os
import random
import time
from threading import Timer, Lock
from flask import Flask, render_template, request, session, redirect, url_for
from flask_socketio import SocketIO, emit, join_room, leave_room

# -------------------- 기본 설정 --------------------
HOST_CODE = os.environ.get("HOST_CODE", "BOM")  # 개발자 전용 시작 코드
ROOM = "main"  # 단일 방 운영 (필요시 멀티룸으로 확장 가능)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "secret-key")
socketio = SocketIO(app, cors_allowed_origins="*")

# -------------------- 게임 데이터 --------------------
lock = Lock()
players = {}           # sid -> {"name": str, "score": int, "is_host": bool}
order = []             # 발언 순서 (sid 리스트)
roles = {}             # sid -> "liar" | "spy" | "citizen"
current_round = 0      # 1..5
phase = "lobby"        # "lobby" | "clue_turns" | "discussion" | "vote" | "tiebreak" | "revote" | "guess" | "result" | "gameover"
turn_index = 0         # 발언 순서 인덱스
timer_deadline = 0     # 서버 기준 카운트다운 종료 시각 (epoch)
topic = None           # 현재 라운드 주제
word = None            # 현재 라운드 제시어
votes = {}             # voter_sid -> target_sid
tied_targets = []      # 동률 대상 sid 리스트

# 주제/제시어 예시 (원하는 만큼 확장 가능)
TOPICS = {
    "과일": ["딸기", "바나나", "사과", "포도", "복숭아", "수박", "참외", "자두", "귤", "레몬", "라임", "오렌지", "파인애플", "망고", "석류", "체리", "블루베리",
           "블랙베리", "라즈베리", "크랜베리", "멜론", "키위", "코코넛", "두리안", "용과", "스타프루트", "리치", "구아바", "패션프루트", "살구", "곶감", "감",
           "무화과", "대추", "올리브", "밤", "호두", "잣", "피스타치오", "아보카도", "카람볼라", "카카오", "산딸기", "앵두", "복분자", "홍시", "망고스틴", "자몽",
           "유자", "머루", "청포도"],
    "채소": ["당근", "오이", "양파", "고구마", "브로콜리", "배추", "양배추", "상추", "치커리", "케일", "시금치", "부추", "대파", "쪽파", "마늘", "생강", "고추",
           "피망", "파프리카", "가지", "애호박", "호박", "옥수수", "감자", "연근", "우엉", "샐러리", "아스파라거스", "버섯", "표고버섯", "팽이버섯", "양송이버섯",
           "느타리버섯", "콩나물", "숙주나물", "도라지", "더덕", "무", "열무", "갓", "청경채", "브뤼셀스프라우트", "콜리플라워", "순무", "비트", "쑥갓", "겨자잎",
           "라디치오", "에다마메", "강낭콩", "완두콩"],
    "동물": ["호랑이", "사자", "펭귄", "기린", "코끼리", "고양이", "강아지", "늑대", "여우", "곰", "판다", "하마", "코뿔소", "캥거루", "코알라", "다람쥐", "토끼",
           "말", "당나귀", "소", "돼지", "양", "염소", "닭", "오리", "거위", "칠면조", "독수리", "매", "부엉이", "올빼미", "비둘기", "참새", "까치", "갈매기",
           "상어", "고래", "돌고래", "문어", "오징어", "게", "새우", "해파리", "사슴", "고라니", "표범", "치타", "재규어", "하이에나", "바다사자"],
    "스포츠": ["축구", "야구", "농구", "배드민턴", "수영", "탁구", "테니스", "골프", "배구", "하키",
            "럭비", "핸드볼", "볼링", "스쿼시", "복싱", "레슬링", "유도", "태권도", "검도", "씨름",
            "펜싱", "승마", "체조", "리듬체조", "역도", "사격", "양궁", "철인3종", "마라톤", "달리기",
            "스피드스케이팅", "피겨스케이팅", "스키", "스노보드", "컬링", "서핑", "요트", "카누", "패러글라이딩", "클라이밍"],
    "직업": ["의사", "경찰", "선생님", "요리사", "소방관", "간호사", "약사", "판사", "변호사", "군인", "프로그래머", "웹디자이너", "그래픽디자이너", "기자", "작가",
           "화가", "사진작가", "배우", "가수", "댄서", "운동선수", "과학자", "연구원", "정치인", "외교관", "은행원", "회계사", "파일럿", "항해사", "농부"],
    "교통수단": ["자동차", "비행기", "자전거", "지하철", "버스", "기차", "트럭", "택시", "전동킥보드", "스쿠터", "오토바이", "요트", "배", "페리", "잠수함", "헬리콥터",
             "열기구", "케이블카", "트램", "전철", "고속버스", "우주선", "로켓", "마차", "세그웨이", "트롤리버스", "빙상썰매", "스노우모빌", "전동휠체어", "군용탱크"],
    "가전제품": ["냉장고", "세탁기", "청소기", "에어컨", "텔레비전", "전자레인지", "밥솥", "토스터", "전기포트", "커피머신", "믹서기", "블렌더", "헤어드라이어", "다리미",
             "선풍기", "가습기", "제습기", "청정기", "온풍기", "전기히터", "식기세척기", "전기레인지", "오븐", "빔프로젝터", "스피커", "CD플레이어", "라디오", "모니터",
             "프린터", "게임콘솔"],
    "음식": ["피자", "햄버거", "초밥", "비빔밥", "치킨", "파스타", "타코", "라멘", "딤섬", "쌀국수", "쌈밥", "부리토", "케밥", "카레", "스테이크",
           "보쌈", "김치찌개", "된장찌개", "샤브샤브", "쭈꾸미볶음", "탕수육", "짜장면", "짬뽕", "칼국수", "순대국밥", "삼계탕", "갈비찜", "불고기",
           "닭강정", "찜닭", "비프웰링턴", "라자냐", "그릭요거트", "바클라바", "빠에야", "소바", "규동", "오코노미야키", "타파스", "코코넛카레", "바비큐립",
           "와플", "팬케이크", "샌드위치", "포케", "크로와상", "샤와르마", "후무스", "브리또볼", "롤케이크"],
    "음료": ["커피", "우유", "맥주", "주스", "차", "아메리카노", "카푸치노", "에스프레소", "카페라떼", "콜라", "사이다", "환타", "핫초코", "녹차", "홍차",
           "허브티", "밀크티", "마테차", "레몬에이드", "오렌지주스", "포도주스", "망고주스", "수박주스", "코코넛워터", "아이스티", "스무디", "쉐이크", "바나나우유",
           "초코우유", "딸기우유", "보리차", "옥수수수염차", "헛개차", "알로에주스", "청포도에이드", "모히또", "피나콜라다", "맥콜", "칵테일", "샴페인", "막걸리",
           "소주", "와인", "사케", "하이볼", "아이리쉬커피", "아이스초코", "자몽에이드", "귤주스", "민트티"],
    "악기": ["피아노", "바이올린", "기타", "드럼", "트럼펫", "플루트", "클라리넷", "오보에", "첼로", "하프", "트롬본", "튜바", "콘트라베이스", "신디사이저", "오르간",
           "하모니카", "만돌린", "리코더", "카혼", "탬버린", "캐스터네츠", "심벌즈", "팀파니", "마림바", "비올라", "일렉기타", "베이스기타", "우쿨렐레", "장구", "가야금",
           "거문고", "대금", "해금", "피리", "태평소", "징", "북", "아코디언", "사운드믹서", "전자드럼", "샘플러", "신시사이저 키보드", "글로켄슈필", "비브라폰",
           "트라이앵글", "봉고", "콩가", "멜로디언", "에르후", "산시엔"],
    "나라": ["한국", "미국", "일본", "중국", "프랑스", "영국", "독일", "이탈리아", "스페인", "포르투갈", "네덜란드", "벨기에", "스웨덴", "노르웨이", "덴마크", "핀란드",
           "오스트리아", "스위스", "러시아", "터키", "사우디아라비아", "이란", "이라크", "이스라엘", "이집트", "남아프리카공화국", "나이지리아", "케냐", "인도", "파키스탄",
           "네팔", "방글라데시", "태국", "베트남", "말레이시아", "인도네시아", "필리핀", "호주", "뉴질랜드", "캐나다", "멕시코", "브라질", "아르헨티나", "칠레",
           "콜롬비아", "페루", "쿠바", "자메이카", "그리스", "폴란드"],
    "도시": ["서울", "뉴욕", "도쿄", "베를린", "파리", "런던", "로마", "바르셀로나", "리스본", "암스테르담", "브뤼셀", "스톡홀름", "오슬로", "코펜하겐", "헬싱키", "빈",
           "취리히", "제네바", "모스크바", "상트페테르부르크", "이스탄불", "두바이", "리야드", "카이로", "케이프타운", "요하네스버그", "나이로비", "뭄바이", "델리", "카라치",
           "카트만두", "다카", "방콕", "하노이", "호찌민", "쿠알라룸푸르", "자카르타", "마닐라", "시드니", "멜버른", "오클랜드", "토론토", "밴쿠버", "몬트리올",
           "멕시코시티", "리우데자네이루", "부에노스아이레스", "산티아고", "보고타", "리마"],
    "의류": ["셔츠", "청바지", "모자", "치마", "운동화", "티셔츠", "후드티", "니트", "블라우스", "원피스", "정장", "재킷", "코트", "패딩", "점퍼", "바지", "반바지",
           "카디건", "슬랙스", "조거팬츠", "드레스", "한복", "한복저고리", "치파오", "사리", "키모노", "양복", "베스트", "조끼", "야상", "트렌치코트", "롱코트",
           "숏패딩", "롱패딩", "야구잠바", "점프수트", "레깅스", "스커트", "플리츠스커트", "맥시드레스", "블레이저", "와이셔츠", "폴로셔츠", "스웨터", "크롭티", "탱크톱",
           "브라탑", "샌들", "부츠"],
    "전자기기": ["스마트폰", "노트북", "태블릿", "스마트워치", "카메라"],
    "자연": ["바다", "산", "강", "사막", "숲"],
    "계절": ["봄", "여름", "가을", "겨울", "장마"],
    "취미": ["독서", "그림", "등산", "게임", "춤"],
    "가구": ["의자", "책상", "침대", "소파", "옷장"],
    "날씨": ["맑음", "비", "눈", "바람", "안개"],
    "행성": ["지구", "화성", "금성", "목성", "토성"],
    "KWDI": ["할머니", "본부장", "재무팀", "인사팀", "예산팀", "행정직", "연구직", "수딘", "도은", "미나", "여니미니", "두농", "김서정수","빛나","공동의장","본관","식당","413호",
             "원장님","체력단련실","체육관"],
    "영화": ["기생충", "괴물", "올드보이", "신세계", "범죄와의 전쟁", "명량", "극한직업", "7번방의 선물", "살인의 추억", "해운대", "도가니", "부산행",
           "내부자들", "아가씨", "암살", "관상", "국제시장", "택시운전사", "밀정", "곡성", "한공주", "변호인", "소원", "마더", "추격자", "친절한 금자씨",
           "박쥐", "설국열차", "베테랑", "신과함께-죄와 벌", "신과함께-인과 연", "클래식", "엽기적인 그녀", "건축학개론", "엽문", "전우치", "웰컴 투 동막골",
           "태극기 휘날리며", "실미도", "쉬리", "공동경비구역 JSA", "혈의 누", "장화, 홍련", "범죄도시", "범죄도시2", "범죄도시3", "검사외전", "럭키", "청년경찰",
           "은밀하게 위대하게", "말아톤", "우리들의 행복한 시간", "완득이", "과속스캔들", "써니", "건축학개론", "늑대소년"],
    "장소": ["학교", "병원", "공원", "도서관", "카페", "식당", "영화관", "놀이공원", "동물원", "수족관",
            "미술관", "박물관", "시장", "백화점", "마트", "편의점", "공항", "기차역", "버스터미널", "지하철역",
            "체육관", "수영장", "헬스장", "노래방", "PC방", "볼링장", "경기장", "극장", "교회", "사찰",
            "해수욕장", "산", "강", "호수", "섬", "사막", "동굴", "성", "궁전", "호텔",
            "캠핑장", "놀이동산", "스키장", "온천", "시장골목", "옥상", "지하실", "주차장", "버스정류장", "광장"]
}

# -------------------- 유틸 --------------------
def broadcast_state():
    with lock:
        payload = {
            "phase": phase,
            "current_round": current_round,
            "timer_remaining": max(0, int(timer_deadline - time.time())) if timer_deadline else 0,
            "players": [{"sid": sid, "name": p["name"], "score": p["score"]} for sid, p in players.items()],
            "order": order,
        }
    socketio.emit("state", payload, to=ROOM)

def set_timer(seconds):
    global timer_deadline
    timer_deadline = time.time() + seconds
    socketio.emit("timer_start", {"seconds": seconds}, to=ROOM)

def next_phase(new_phase):
    global phase
    phase = new_phase
    broadcast_state()

def choose_topic_word():
    global topic, word
    topic = random.choice(list(TOPICS.keys()))
    word = random.choice(TOPICS[topic])

def assign_roles():
    global roles
    sids = list(players.keys())
    random.shuffle(sids)
    n = len(sids)
    liar_sid = sids[0]
    roles = {sid: "citizen" for sid in sids}
    roles[liar_sid] = "liar"
    if n >= 7:
        # 스파이 1명
        for sid in sids[1:]:
            roles[sid] = roles.get(sid, "citizen")
        spy_sid = sids[1]
        roles[spy_sid] = "spy"

def deal_personal_cards():
    """개인별 역할/제시어 안내"""
    for sid in players.keys():
        r = roles.get(sid, "citizen")
        if r == "liar":
            socketio.emit("personal", {"role": r, "topic": topic, "word": None}, to=sid)
        else:
            socketio.emit("personal", {"role": r, "topic": topic, "word": word}, to=sid)

def compute_vote_result(targets):
    # targets: dict voter_sid -> target_sid
    tally = {}
    for t in targets.values():
        tally[t] = tally.get(t, 0) + 1
    if not tally:
        return None, []  # no votes
    max_votes = max(tally.values())
    winners = [sid for sid, cnt in tally.items() if cnt == max_votes]
    if len(winners) == 1:
        return winners[0], []
    return None, winners

def award_scores(liar_sid, spy_sid, citizens_sids, liar_caught: bool, liar_guessed_correct: bool):
    # 시민 승리: liar_caught True and liar_guessed_correct False
    # 라이어 승리(1): liar_caught False
    # 라이어 승리(2): liar_caught True and liar_guessed_correct True
    if liar_caught and not liar_guessed_correct:
        # 시민 전원 +1
        for sid in citizens_sids:
            players[sid]["score"] += 1
        # liar, spy 0
    elif not liar_caught:
        # liar +2, spy +1
        players[liar_sid]["score"] += 2
        if spy_sid:
            players[spy_sid]["score"] += 1
    else:  # liar_caught and liar_guessed_correct
        players[liar_sid]["score"] += 2
        if spy_sid:
            players[spy_sid]["score"] += 1

# -------------------- 라우트 --------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/lobby")
def lobby():
    name = session.get("name")
    if not name:
        return redirect(url_for("index"))
    return render_template("lobby.html", is_host=session.get("is_host", False))

@app.route("/game")
def game():
    name = session.get("name")
    if not name:
        return redirect(url_for("index"))
    return render_template("game.html", is_host=session.get("is_host", False))

# -------------------- 소켓 이벤트 --------------------
@socketio.on("connect")
def on_connect():
    join_room(ROOM)
    emit("hello", {"msg": "connected"})
    broadcast_state()

@socketio.on("disconnect")
def on_disconnect():
    with lock:
        sid = request.sid
        if sid in players:
            del players[sid]
            if sid in order:
                order.remove(sid)
            if sid in roles:
                del roles[sid]
    broadcast_state()

@socketio.on("join")
def on_join(data):
    """data: {"name": "...", "host_code": "...."}"""
    name = data.get("name", "").strip()
    host_code = data.get("host_code", "")
    if not name:
        emit("error", {"msg": "이름을 입력하세요."})
        return

    with lock:
        sid = request.sid
        is_host = (host_code == HOST_CODE)
        players[sid] = {"name": name, "score": 0, "is_host": is_host}
        if sid not in order:
            order.append(sid)
        # 세션 대용으로 클라이언트가 is_host 상태를 기억하도록 회신
        emit("join_ok", {"is_host": is_host})
    broadcast_state()

@socketio.on("start_game")
def on_start_game():
    # 호스트만 가능
    sid = request.sid
    with lock:
        if not players.get(sid, {}).get("is_host"):
            emit("error", {"msg": "호스트만 시작할 수 있습니다."})
            return
        # 초기화
        global current_round, phase, turn_index, votes, tied_targets
        current_round = 1
        phase = "lobby"
        turn_index = 0
        votes = {}
        tied_targets = []

        # 라운드 시작
        _start_round()

def _start_round():
    global phase, turn_index, votes, tied_targets
    with lock:
        assign_roles()
        choose_topic_word()
        deal_personal_cards()
        turn_index = 0
        votes = {}
        tied_targets = []
        phase = "clue_turns"
        set_timer(30)
        current_speaker_sid = order[turn_index] if order else None
    socketio.emit("speak_turn", {"sid": current_speaker_sid}, to=ROOM)
    broadcast_state()

@socketio.on("next_turn")
def on_next_turn():
    """호스트가 수동으로 다음 화자/다음 단계 진행 가능 (네트워크 지연 대비)"""
    sid = request.sid
    with lock:
        if not players.get(sid, {}).get("is_host"):
            emit("error", {"msg": "호스트만 진행할 수 있습니다."})
            return
        _advance_turn_locked()

def _advance_turn_locked():
    global turn_index, phase
    if phase != "clue_turns":
        return
    turn_index += 1
    if turn_index < len(order):
        set_timer(30)
        socketio.emit("speak_turn", {"sid": order[turn_index]}, to=ROOM)
    else:
        # 모든 인원이 발언 완료 -> 토론
        phase = "discussion"
        set_timer(180)
        broadcast_state()

@socketio.on("timer_expired")
def on_timer_expired():
    """클라이언트 타이머 종료 신호 -> 서버 상태 진행"""
    with lock:
        if phase == "clue_turns":
            _advance_turn_locked()
        elif phase == "discussion":
            # 투표 단계로
            global votes
            votes = {}
            next_phase("vote")
        elif phase == "tiebreak":
            # 동률자 발언 완료 -> 재투표
            next_phase("revote")
        elif phase == "guess":
            # 라이어 정답 시도 종료 -> 결과 계산
            _finalize_round(liar_guess=None)  # None은 시간초과로 오답 처리

@socketio.on("cast_vote")
def on_cast_vote(data):
    """data: {"target_sid": "..."}"""
    target_sid = data.get("target_sid")
    voter_sid = request.sid
    with lock:
        if phase not in ("vote", "revote"):
            return
        if voter_sid == target_sid:
            return  # 자기 자신 투표 방지 (원하면 허용 가능)
        votes[voter_sid] = target_sid
        # 모두 투표하면 즉시 집계
        if len(votes) >= len(players):
            _tally_votes_locked()

def _tally_votes_locked():
    global phase, tied_targets
    target, ties = compute_vote_result(votes)
    if target:
        # 최다득표자 확정
        liar_sid = next((sid for sid, r in roles.items() if r == "liar"), None)
        if target == liar_sid:
            # 라이어가 걸림 -> 정답 시도
            phase = "guess"
            set_timer(30)
            socketio.emit("ask_guess", {}, to=liar_sid)
        else:
            # 라이어 아님 -> 라이어/스파이 승리
            _finalize_round(liar_guess="WRONG_TARGET")
    else:
        # 동률 -> 동률자 30초씩 발언
        tied_targets = ties
        phase = "tiebreak"
        set_timer(30 * len(tied_targets))
    broadcast_state()

@socketio.on("submit_guess")
def on_submit_guess(data):
    """라이어가 제시어 추측 제출. data: {"guess": "..." }"""
    guess = (data.get("guess") or "").strip()
    _finalize_round(liar_guess=guess)

def _finalize_round(liar_guess):
    global current_round, phase
    with lock:
        liar_sid = next((sid for sid, r in roles.items() if r == "liar"), None)
        spy_sid = next((sid for sid, r in roles.items() if r == "spy"), None)
        citizen_sids = [sid for sid, r in roles.items() if r == "citizen"]

        liar_caught = False
        liar_guessed_correct = False

        if liar_guess == "WRONG_TARGET":
            # 라이어가 아닌 사람을 최다 득표 -> 라이어 승리(1)
            liar_caught = False
            liar_guessed_correct = False
        elif liar_guess is None:
            # 시간초과 -> 라이어가 걸렸지만 오답 처리 -> 시민 승리
            liar_caught = True
            liar_guessed_correct = False
        else:
            # 라이어가 걸려서 단어 추측
            liar_caught = True
            liar_guessed_correct = (liar_guess == word)

        award_scores(liar_sid, spy_sid, citizen_sids, liar_caught, liar_guessed_correct)

        # 라운드 결과 브로드캐스트
        socketio.emit("round_result", {
            "liar_sid": liar_sid,
            "spy_sid": spy_sid,
            "topic": topic,
            "word": word,
            "liar_caught": liar_caught,
            "liar_guessed_correct": liar_guessed_correct,
            "scores": {sid: p["score"] for sid, p in players.items()}
        }, to=ROOM)

        # 다음 라운드로 이동 or 게임 종료
        if current_round >= 5:
            phase = "gameover"
            broadcast_state()
        else:
            current_round += 1
            _start_round()

# -------------------- 페이지 제출 이벤트 --------------------
@app.route("/join", methods=["POST"])
def http_join():
    name = request.form.get("name", "").strip()
    host_code = request.form.get("host_code", "").strip()
    if not name:
        return redirect(url_for("index"))
    session["name"] = name
    session["is_host"] = (host_code == HOST_CODE)
    return redirect(url_for("lobby"))

if __name__ == "__main__":
    # Replit에서는 host='0.0.0.0' 권장
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))