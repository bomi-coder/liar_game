import os, random, time, threading
from collections import defaultdict, Counter
from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from dotenv import load_dotenv

load_dotenv()
HOST_CODE = os.getenv("HOST_CODE", "BOM")

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "dev-secret")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

# ---- In-memory state (단일 로비/단일 게임) ----
PLAYERS = {}  # sid -> {id, name, is_host, score, role, word, alive, spoke}
PLAYER_SEQ = []  # 고정 순서
ROUND = 0
MAX_ROUND = 5

PHASE = "LOBBY"   # LOBBY -> HINT -> DEBATE -> VOTE -> TIE_SPEECH -> REVOTE -> LIAR_GUESS -> SCORE -> NEXT(or END)
PHASE_END_TS = 0  # phase 종료 시각(epoch)
TURN_INDEX = 0    # HINT 단계에서 말할 사람 인덱스
VOTES = {}        # sid -> target_sid
TOPIC = ""
WORD = ""
WORDS_DB = {
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

LOCK = threading.Lock()

def now():
    return int(time.time())

def broadcast_state():
    emit('state', {
        "players": [{"id": sid, "name": p["name"], "is_host": p.get("is_host", False)} for sid,p in PLAYERS.items()],
        "round": ROUND
    }, broadcast=True)

def phase_seconds_left():
    return max(0, PHASE_END_TS - now())

def phase_label():
    return {
        "HINT": "힌트 발언",
        "DEBATE": "자유토론",
        "VOTE": "공개 투표",
        "TIE_SPEECH": "동률자 추가 발언",
        "REVOTE": "재투표",
        "LIAR_GUESS": "라이어 최종 정답",
        "SCORE": "점수집계"
    }.get(PHASE, "대기중")

def push_game_info(to=None):
    def pack_me(sid):
        p = PLAYERS[sid]
        return {
            "role": p.get("role"),
            "word": p.get("word")
        }
    data = {
        "phase": PHASE,
        "phase_label": phase_label(),
        "seconds_left": phase_seconds_left(),
        "round": ROUND,
        "topic": TOPIC,
        "players": [{
            "id": sid,
            "name": p["name"],
            "is_dead": not p.get("alive", True),
            "speaked": p.get("spoke", False)
        } for sid,p in PLAYERS.items()]
    }
    if to:
        me = pack_me(to)
        data["me"] = me
        data["my_vote"] = VOTES.get(to)
        socketio.emit('game_info', data, to=to)
        socketio.emit('me', {"id": to}, to=to)
    else:
        for sid in PLAYERS:
            d = dict(data)
            d["me"] = pack_me(sid)
            d["my_vote"] = VOTES.get(sid)
            socketio.emit('game_info', d, to=sid)

def set_phase(name, duration_sec):
    global PHASE, PHASE_END_TS
    PHASE = name
    PHASE_END_TS = now() + duration_sec
    push_game_info()
    socketio.start_background_task(ticker)

def assign_roles_and_words():
    global TOPIC, WORD
    # 역할 배정
    sids = list(PLAYERS.keys())
    random.shuffle(sids)
    for sid in sids:
        PLAYERS[sid].update({"role":"CITIZEN","word":None,"alive":True,"spoke":False})
    n = len(sids)
    liar_sid = random.choice(sids)
    PLAYERS[liar_sid]["role"] = "LIAR"

    spy_sid = None
    if n >= 7:
        remain = [x for x in sids if x != liar_sid]
        spy_sid = random.choice(remain)
        PLAYERS[spy_sid]["role"] = "SPY"

    # 제시어
    TOPIC = random.choice(list(WORDS_DB.keys()))
    WORD = random.choice(WORDS_DB[TOPIC])

    # 시민/스파이에게만 단어 제공
    for sid,p in PLAYERS.items():
        if p["role"] in ("CITIZEN","SPY"):
            p["word"] = WORD
        else:
            p["word"] = None

def next_round_or_finish():
    global ROUND, TURN_INDEX, VOTES
    ROUND += 1
    TURN_INDEX = 0
    VOTES = {}
    for p in PLAYERS.values():
        p["spoke"] = False
    if ROUND > MAX_ROUND:
        # 끝
        socketio.emit('move_results', broadcast=True)
        return False
    assign_roles_and_words()
    set_phase("HINT", 30)  # 첫 발언 30초
    return True

def finish_hint_or_next_speaker():
    global TURN_INDEX
    alive_order = [sid for sid in PLAYER_SEQ if PLAYERS[sid].get("alive",True)]
    if TURN_INDEX < len(alive_order)-1:
        TURN_INDEX += 1
        set_phase("HINT", 30)
    else:
        # 모두 발언 완료 -> 3분 토론
        set_phase("DEBATE", 180)

def resolve_vote(tie_targets=None):
    """투표 결과 집계. tie_targets 가 있으면 그 후보만 허용한 재투표 단계에서 사용."""
    counts = Counter(VOTES.values())
    # 후보 제한
    if tie_targets:
        for k in list(counts.keys()):
            if k not in tie_targets:
                del counts[k]
    if not counts:
        return None, []  # 아무도 안뽑음
    maxc = max(counts.values())
    winners = [k for k,v in counts.items() if v==maxc]
    if len(winners)==1:
        return winners[0], winners
    return None, winners  # 동률

def scoring(liar_caught, liar_guessed_correct):
    # 시민 승리: 라이어 지목+정답 못맞힘 → 시민 +1, 라이어/스파이 0
    # 라이어 승1: 라이어 안 걸림 → 라이어 +2, 스파이 +1, 시민 0
    # 라이어 승2: 라이어 걸렸지만 정답 맞힘 → 라이어 +2, 스파이 +1, 시민 0
    if liar_caught and not liar_guessed_correct:
        for p in PLAYERS.values():
            if p["role"]=="CITIZEN": p["score"] += 1
    else:
        for p in PLAYERS.values():
            if p["role"]=="LIAR": p["score"] += 2
            if p["role"]=="SPY": p["score"] += 1

def ticker():
    # 초단위 카운트다운 브로드캐스트
    while phase_seconds_left() > 0:
        socketio.emit('tick', phase_seconds_left(), broadcast=True)
        socketio.sleep(1)
    # 시간 만료 시 자동 진행
    with LOCK:
        auto_advance()

def auto_advance():
    global TURN_INDEX, VOTES
    if PHASE == "HINT":
        # 현재 화자 spoke 표시
        alive_order = [sid for sid in PLAYER_SEQ if PLAYERS[sid].get("alive",True)]
        if alive_order:
            curr = alive_order[min(TURN_INDEX, len(alive_order)-1)]
            PLAYERS[curr]["spoke"] = True
        finish_hint_or_next_speaker()

    elif PHASE == "DEBATE":
        set_phase("VOTE", 60)  # 투표 60초

    elif PHASE == "VOTE":
        target, ties = resolve_vote()
        if target:
            # 최다 득표 확정
            liar_sid = next((sid for sid,p in PLAYERS.items() if p["role"]=="LIAR"), None)
            if target == liar_sid:
                # 라이어 지목됨 → 라이어 정답 맞히기
                set_phase("LIAR_GUESS", 30)
            else:
                # 라이어 아님 → 즉시 라이어/스파이 승 & 라운드 종료
                scoring(liar_caught=False, liar_guessed_correct=False)
                set_phase("SCORE", 5)
        else:
            # 동률 → 동률자 추가발언 30초 후 재투표
            socketio.server.manager.emit('tie_info', {'ties': ties}, broadcast=True)
            set_phase("TIE_SPEECH", 30)

    elif PHASE == "TIE_SPEECH":
        # 재투표 45초
        set_phase("REVOTE", 45)

    elif PHASE == "REVOTE":
        # 직전 tie 후보만 유효
        # (간단하게 VOTES에 남은 대상들 중 상위 동률자 집합 추적 없이, 서버 메모리에 저장해둘 수도 있음.
        # 여기서는 전체 재집계 후 동일 로직으로 처리)
        target, ties = resolve_vote()
        liar_sid = next((sid for sid,p in PLAYERS.items() if p["role"]=="LIAR"), None)
        if target and target == liar_sid:
            set_phase("LIAR_GUESS", 30)
        else:
            # 라이어 안걸림(또는 target 없음) → 라이어/스파이 승
            scoring(liar_caught=False, liar_guessed_correct=False)
            set_phase("SCORE", 5)

    elif PHASE == "LIAR_GUESS":
        # 시간이 끝나면 실패로 간주
        scoring(liar_caught=True, liar_guessed_correct=False)
        set_phase("SCORE", 5)

    elif PHASE == "SCORE":
        # 다음 라운드로
        if not next_round_or_finish():
            pass  # 결과 페이지로 이동됨

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", title="라이어 게임")

@app.route("/enter", methods=["POST"])
def enter():
    name = request.form.get("name","").strip()
    if not name: return redirect(url_for('index'))
    session['name'] = name
    # 개발자만 호스트 권한 얻도록 쿼리스트링 보호도 가능. 여기선 HOST_CODE를 세션에 심을 수 있도록 옵션:
    session['host_code'] = request.args.get('code','')
    return redirect(url_for('lobby'))

@app.route("/lobby")
def lobby():
    is_host = (session.get('host_code','') == HOST_CODE)
    return render_template("lobby.html", is_host=is_host, host_code=session.get('host_code',''))

@app.route("/game")
def game():
    return render_template("game.html")

@app.route("/results")
def results():
    return render_template("results.html")

@socketio.on('join')
def on_join(data):
    name = (data or {}).get('name') or session.get('name')
    if not name:
        emit('error_msg', {"msg":"이름이 필요해요!"})
        return
    sid = request.sid
    is_host = ((data or {}).get('host_code','') == HOST_CODE)
    with LOCK:
        if sid not in PLAYERS:
            PLAYERS[sid] = {
                "id": sid, "name": name, "is_host": is_host, "score": 0,
                "role": None, "word": None, "alive": True, "spoke": False
            }
            if sid not in PLAYER_SEQ:
                PLAYER_SEQ.append(sid)
    emit('join_ok', {"is_host": is_host})
    broadcast_state()

@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    with LOCK:
        if sid in PLAYERS:
            del PLAYERS[sid]
            if sid in PLAYER_SEQ: PLAYER_SEQ.remove(sid)
    broadcast_state()

@socketio.on('start_game')
def start_game():
    sid = request.sid
    if not PLAYERS.get(sid,{}).get('is_host'):
        emit('error_msg', {"msg":"개발자만 시작할 수 있어요."})
        return
    global ROUND
    with LOCK:
        if len(PLAYERS) < 3:
            emit('error_msg', {"msg":"최소 3명 이상이어야 시작할 수 있어요."})
            return
        ROUND = 0
        for p in PLAYERS.values():
            p["score"] = 0
        ok = next_round_or_finish()
        if ok:
            socketio.emit('move_game', broadcast=True)

@socketio.on('sync_game')
def sync_game():
    sid = request.sid
    push_game_info(to=sid)

@socketio.on('submit_vote')
def submit_vote(data):
    if PHASE not in ("VOTE","REVOTE"):
        emit('error_msg', {"msg":"지금은 투표 시간이 아니에요."})
        return
    target = (data or {}).get('target_id')
    sid = request.sid
    with LOCK:
        if target not in PLAYERS:
            emit('error_msg', {"msg":"잘못된 대상이에요."})
            return
        if not PLAYERS[sid].get("alive",True):
            emit('error_msg', {"msg":"탈락자는 투표할 수 없어요."})
            return
        VOTES[sid] = target
    push_game_info(to=sid)

@socketio.on('liar_guess')
def liar_guess(data):
    if PHASE != "LIAR_GUESS":
        emit('error_msg', {"msg":"지금은 정답 제출 단계가 아니에요."})
        return
    sid = request.sid
    if PLAYERS.get(sid,{}).get("role") != "LIAR":
        emit('error_msg', {"msg":"라이어만 제출할 수 있어요."})
        return
    guess = (data or {}).get('guess','').strip()
    correct = (guess == WORD)
    scoring(liar_caught=True, liar_guessed_correct=correct)
    set_phase("SCORE", 5)

@socketio.on('get_scores')
def get_scores():
    emit('scores', {"players":[{"name":p["name"],"score":p["score"]} for p in PLAYERS.values()]})
