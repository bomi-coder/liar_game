# -*- coding: utf-8 -*-
import os
import random
import time
import json
import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

# ===== 기본 설정 =====
ADMIN_CODE = os.getenv("ADMIN_CODE", "BOM")  # 개발자 전용 시작 코드
ROUND_COUNT = int(os.getenv("ROUND_COUNT", "5"))
HINT_SECONDS = int(os.getenv("HINT_SECONDS", "15"))
DISCUSS_SECONDS = int(os.getenv("DISCUSS_SECONDS", "120"))
TIE_SPEECH_SECONDS = int(os.getenv("TIE_SPEECH_SECONDS", "20"))
LIAR_GUESS_SECONDS = int(os.getenv("LIAR_GUESS_SECONDS", "30"))
VOTE_SECONDS = int(os.getenv("VOTE_SECONDS", "60"))

# 정적/템플릿 경로 명시 (정적 0바이트/경로 꼬임 방지)
app = Flask(__name__, static_folder="static", template_folder="templates")
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "secret!liargame")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

# ===== 주제/제시어 데이터 로드 =====
DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "topics.json")
with open(DATA_PATH, "r", encoding="utf-8") as f:
    TOPICS = json.load(f)

# ===== 상태 =====
players = {}  # sid -> {name, score, is_host}
order = []    # speaking order (list of sid)
game_state = {
    "phase": "lobby",   # lobby, assign, hints, discuss, vote1, tie_speech, vote2, liar_guess, reveal, round_end, game_end
    "round": 0,
    "subject": None,
    "keyword": None,
    "roles": {},        # sid -> "LIAR"/"SPY"/"CITIZEN"
    "votes": {},        # 현재 라운드(1차/2차 어떤 쪽이든) 수집 버퍼
    "votes1": {},       # 1차 투표 결과(공개 현황 용)
    "votes2": {},       # 2차 투표 결과(공개 현황 용)
    "tie_candidates": [],
    "current_speaker_idx": -1,
    "liar_sid": None,
    "spy_sid": None,
    "timer_end": None,
    "timer_token": 0    # 타이머 리셋 토큰
}

def reset_round_state():
    game_state.update({
        "phase": "assign",
        "subject": None,
        "keyword": None,
        "roles": {},
        "votes": {},
        "votes1": {},
        "votes2": {},
        "tie_candidates": [],
        "current_speaker_idx": -1,
        "liar_sid": None,
        "spy_sid": None,
        "timer_end": None,
        "timer_token": 0
    })

def broadcast_player_list():
    socketio.emit("player_list", [
        {"sid": sid, "name": p["name"], "score": p.get("score", 0), "is_host": p.get("is_host", False)}
        for sid, p in players.items()
    ])

def choose_subject_and_keyword():
    subject = random.choice(list(TOPICS.keys()))
    keyword = random.choice(TOPICS[subject])
    return subject, keyword

def assign_roles():
    sids = list(players.keys())
    if len(sids) == 0:
        return
    liar = random.choice(sids)
    spy = None
    if len(sids) >= 7:
        candidates = [x for x in sids if x != liar]
        spy = random.choice(candidates)
    game_state["liar_sid"] = liar
    game_state["spy_sid"] = spy

    for sid in sids:
        if sid == liar:
            game_state["roles"][sid] = "LIAR"
        elif spy and sid == spy:
            game_state["roles"][sid] = "SPY"
        else:
            game_state["roles"][sid] = "CITIZEN"

def countdown(seconds, tick_event, end_event):
    # 토큰 기반 타이머 (리셋 지원)
    game_state["timer_token"] = game_state.get("timer_token", 0) + 1
    my_token = game_state["timer_token"]
    # 초기화 알림
    socketio.emit("timer_reset", {"seconds": seconds})
    end_time = time.time() + seconds
    game_state["timer_end"] = end_time
    while True:
        if my_token != game_state.get("timer_token"):
            # 새로운 타이머 시작됨 → 중단
            return
        remaining = int(round(end_time - time.time()))
        if remaining < 0:
            remaining = 0
        socketio.emit(tick_event, {"remaining": remaining})
        if remaining <= 0:
            break
        socketio.sleep(1)
    socketio.emit(end_event, {})

# ===== 라운드 시작 (수동 진행을 위해 자동 단계진행 제거) =====
def start_round():
    game_state["round"] += 1
    # round 올리기 전에 reset을 하면 round 0 됨 → 순서 바꾸지 마!
    # 다음 라운드를 위해 일부 상태만 초기화
    game_state.update({
        "phase": "assign",
        "subject": None,
        "keyword": None,
        "roles": {},
        "votes": {},
        "votes1": {},
        "votes2": {},
        "tie_candidates": [],
        "current_speaker_idx": -1,
        "liar_sid": None,
        "spy_sid": None,
        "timer_end": None,
        "timer_token": 0
    })

    subject, keyword = choose_subject_and_keyword()
    game_state["subject"] = subject
    game_state["keyword"] = keyword
    assign_roles()

    # 발화 순서 섞기
    global order
    order = list(players.keys())
    random.shuffle(order)

    # 라운드 정보 브로드캐스트
    socketio.emit("round_start", {
        "round": game_state["round"],
        "total_rounds": ROUND_COUNT,
        "subject": game_state["subject"]
    })

    # 개인 역할/제시어 발송 (유니캐스트)
    for sid in players.keys():
        role = game_state["roles"].get(sid, "CITIZEN")
        if role == "LIAR":
            socketio.emit("role_assignment", {
                "role": "라이어",
                "subject": game_state["subject"],
                "keyword": "???"
            }, to=sid)
        else:
            socketio.emit("role_assignment", {
                "role": "스파이" if role == "SPY" else "시민",
                "subject": game_state["subject"],
                "keyword": game_state["keyword"]
            }, to=sid)

    # 이제 수동 단계로 넘어감
    game_state["phase"] = "hints"
    game_state["current_speaker_idx"] = -1  # 아직 첫 발언자 전

def step_next_speaker():
    """호스트 버튼으로 1명씩 발언턴 진행"""
    if game_state["phase"] not in ("hints", "assign"):
        return
    # 다음 인덱스
    next_idx = game_state.get("current_speaker_idx", -1) + 1
    if next_idx >= len(order):
        # 모두 발언 끝 → 토론으로 넘길 수 있도록 상태만 설정
        game_state["phase"] = "discuss"
        return

    game_state["current_speaker_idx"] = next_idx
    sid = order[next_idx]
    name = players.get(sid, {}).get("name", "알수없음")

    # 사전 안내 → 팝업
    socketio.emit("pre_hint_notice", {
        "speaker_sid": sid,
        "speaker_name": name
    })
    socketio.sleep(0.4)

    # 발언 턴 시작 + 타이머
    socketio.emit("hint_turn", {
        "speaker_sid": sid,
        "speaker_name": name,
        "order_index": next_idx,
        "total": len(order),
        "seconds": HINT_SECONDS
    })
    socketio.start_background_task(countdown, HINT_SECONDS, "timer_tick", "timer_done")

def start_discussion():
    game_state["phase"] = "discuss"
    socketio.emit("discussion_start", {"seconds": DISCUSS_SECONDS})
    socketio.start_background_task(countdown, DISCUSS_SECONDS, "timer_tick", "timer_done")

def start_vote(first=True, limited_to=None):
    game_state["phase"] = "vote1" if first else "vote2"
    game_state["votes"] = {}
    candidates = limited_to if limited_to else list(players.keys())
    socketio.emit("vote_start", {
        "first": first,
        "round": 1 if first else 2,
        "candidates": [{"sid": sid, "name": players[sid]["name"]} for sid in candidates],
        "seconds": VOTE_SECONDS
    })
    # 투표 타이머도 동작(요청사항 60초 타이머)
    socketio.start_background_task(countdown, VOTE_SECONDS, "timer_tick", "timer_done")
    # 별도의 자동 집계는 하지 않고, '합계 공개' 버튼/기존 로직으로 처리 가능

def combined_vote_and_reveal_then_judge():
    """1차+2차 합산을 공개하고, 기존 규칙으로 판정 이어가기"""
    # 합산용 tally
    tally = {}
    for d in (game_state["votes1"], game_state["votes2"]):
        for voter, target in d.items():
            if target in players:
                tally[target] = tally.get(target, 0) + 1

    # 공개용 데이터 (이름과 득표수)
    name_map = {sid: players[sid]["name"] for sid in players}
    combo_list = [{"sid": sid, "name": name_map.get(sid, sid), "votes": v} for sid, v in tally.items()]
    socketio.emit("combined_vote_result", {"tally": combo_list})

    if not tally:
        liar_spy_win(reason="no_votes")
        return

    max_votes = max(tally.values())
    top = [sid for sid, cnt in tally.items() if cnt == max_votes]

    if len(top) >= 2:
        # 동률자 발언 → 20초씩
        game_state["tie_candidates"] = top
        socketio.emit("vote_tie", {
            "candidates": [{"sid": sid, "name": players[sid]["name"]} for sid in top]
        })
        game_state["phase"] = "tie_speech"
        for sid in top:
            socketio.emit("tie_speech_turn", {
                "sid": sid, "name": players[sid]["name"], "seconds": TIE_SPEECH_SECONDS
            })
            countdown(TIE_SPEECH_SECONDS, "timer_tick", "timer_done")
            socketio.sleep(0.2)
        # 재투표(2차로 제한 투표)
        start_vote(first=False, limited_to=top)
        return

    # 단일 최다득표자
    accused = top[0]
    liar_sid = game_state["liar_sid"]
    if accused == liar_sid:
        start_liar_guess()
    else:
        liar_spy_win(reason="wrong_accuse")

def start_liar_guess():
    game_state["phase"] = "liar_guess"
    liar_sid = game_state["liar_sid"]
    socketio.emit("liar_guess_start", {
        "liar_sid": liar_sid,
        "liar_name": players[liar_sid]["name"],
        "seconds": LIAR_GUESS_SECONDS,
        "subject": game_state["subject"]
    })
    socketio.emit("liar_input_enable", {}, to=liar_sid)
    socketio.start_background_task(run_liar_guess_timer, liar_sid)

def run_liar_guess_timer(liar_sid):
    countdown(LIAR_GUESS_SECONDS, "timer_tick", "timer_done")
    if game_state["phase"] == "liar_guess":
        citizens_win(reason="timeout")

def normalize(s):
    return "".join(str(s).strip().split())

def citizens_win(reason=""):
    # 점수: 시민 전원 +1 (라이어가 걸렸고 정답 못맞힘)
    for sid, info in players.items():
        role = game_state["roles"].get(sid, "CITIZEN")
        if role == "CITIZEN":
            info["score"] = info.get("score", 0) + 1
    socketio.emit("round_result", {"winner": "시민", "reason": reason, "keyword": game_state["keyword"]})
    end_or_next_round()

def liar_spy_win(reason=""):
    # 점수: 라이어 +2, 스파이 +1 (스파이가 존재할 때만)
    for sid, info in players.items():
        role = game_state["roles"].get(sid, "CITIZEN")
        if role == "LIAR":
            info["score"] = info.get("score", 0) + 2
        elif role == "SPY":
            info["score"] = info.get("score", 0) + 1
    socketio.emit("round_result", {"winner": "라이어/스파이", "reason": reason, "keyword": game_state["keyword"]})
    end_or_next_round()

def end_or_next_round():
    if game_state["round"] >= ROUND_COUNT:
        game_state["phase"] = "game_end"
        scoreboard = [{"name": p["name"], "score": p.get("score", 0)} for p in players.values()]
        scoreboard.sort(key=lambda x: x["score"], reverse=True)
        socketio.emit("game_over", {"scoreboard": scoreboard})
    else:
        game_state["phase"] = "round_end"
        socketio.emit("next_round_soon", {"next_round": game_state["round"] + 1})
        socketio.sleep(2.5)
        # 다음 라운드도 수동 버튼으로 시작할 수 있도록 여기서는 자동 호출하지 않음
        # (호스트가 '라운드 시작' 버튼을 눌러야 start_round() 실행)

# ===== 라우팅 =====
@app.route("/")
def index():
    return render_template("index.html")

# ===== 소켓 이벤트 =====
@socketio.on("connect")
def on_connect():
    pass

@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    if sid in players:
        players.pop(sid, None)
        if sid in order:
            try:
                order.remove(sid)
            except ValueError:
                pass
        broadcast_player_list()

@socketio.on("join")
def on_join(data):
    name = data.get("name", "").strip()
    if not name:
        emit("error_msg", {"msg": "이름을 입력해 주세요."}, to=request.sid)
        return
    sid = request.sid
    players[sid] = {"name": name, "score": 0, "is_host": False}
    broadcast_player_list()
    emit("joined", {"sid": sid, "name": name}, to=sid)

@socketio.on("become_host")
def on_become_host(data):
    code = data.get("code", "")
    sid = request.sid
    if code == ADMIN_CODE and sid in players:
        players[sid]["is_host"] = True
        emit("host_ok", {"ok": True}, to=sid)
        broadcast_player_list()
    else:
        emit("host_ok", {"ok": False}, to=sid)

@socketio.on("start_game")
def on_start_game():
    sid = request.sid
    if not players.get(sid, {}).get("is_host"):
        emit("error_msg", {"msg": "권한이 없습니다."}, to=sid)
        return
    if len(players) < 3:
        emit("error_msg", {"msg": "최소 3명 이상이어야 시작할 수 있습니다."}, to=sid)
        return
    # 게임 전체 초기화
    game_state["phase"] = "assign"
    game_state["round"] = 0
    for p in players.values():
        p["score"] = 0
    socketio.emit("game_start", {"rounds": ROUND_COUNT})
    # 라운드 시작은 수동 버튼(라운드 시작)으로 진행

# === 수동 컨트롤: 호스트만 ===
@socketio.on("manual_next_phase")
def on_manual_next_phase(data):
    sid = request.sid
    if not players.get(sid, {}).get("is_host"):
        emit("error_msg", {"msg": "권한이 없습니다."}, to=sid)
        return

    phase = (data or {}).get("phase")
    if phase == "round_start":
        start_round()
    elif phase == "next_speaker":
        step_next_speaker()
    elif phase == "discussion":
        start_discussion()
    elif phase == "vote":
        # 1차를 먼저, 그 다음 2차
        first = (game_state["phase"] != "vote2") and (len(game_state["votes1"]) == 0)
        start_vote(first=first)
    elif phase == "results":
        combined_vote_and_reveal_then_judge()

@socketio.on("hide_vote_panel")
def on_hide_vote_panel():
    # 클라이언트가 패널 숨김을 UI용으로만 쓰므로 서버에선 별도 상태 없음
    pass

@socketio.on("reset_game")
def on_reset_game():
    sid = request.sid
    if not players.get(sid, {}).get("is_host"):
        emit("error_msg", {"msg": "권한이 없습니다."}, to=sid)
        return
    # 전부 초기화
    for p in players.values():
        p["score"] = 0
    game_state.update({
        "phase": "lobby",
        "round": 0,
        "subject": None,
        "keyword": None,
        "roles": {},
        "votes": {},
        "votes1": {},
        "votes2": {},
        "tie_candidates": [],
        "current_speaker_idx": -1,
        "liar_sid": None,
        "spy_sid": None,
        "timer_end": None,
        "timer_token": 0
    })
    socketio.emit("game_over", {"scoreboard": []})  # UI 초기화 유도용(빈 보드)

@socketio.on("vote")
def on_vote(data):
    sid = request.sid
    target = data.get("target_sid")
    if game_state["phase"] not in ("vote1", "vote2"):
        return
    if target not in players:
        return

    # 1인 1표(마지막 선택으로 갱신)
    game_state["votes"][sid] = target
    # 공개 현황용 별도 저장 + 브로드캐스트
    if game_state["phase"] == "vote1":
        game_state["votes1"][sid] = target
        socketio.emit("vote_update", {"round": 1, "votes": game_state["votes1"]})
    else:
        game_state["votes2"][sid] = target
        socketio.emit("vote_update", {"round": 2, "votes": game_state["votes2"]})

    emit("vote_ok", {"ok": True}, to=sid)

@socketio.on("liar_guess")
def on_liar_guess(data):
    sid = request.sid
    if sid != game_state.get("liar_sid"):
        return
    if game_state["phase"] != "liar_guess":
        return
    guess = data.get("guess", "").strip()
    if not guess:
        return
    if normalize(guess) == normalize(game_state["keyword"]):
        liar_spy_win(reason="liar_correct")
    else:
        citizens_win(reason="liar_wrong")

# ---- 선택: 예전 호환용(필요시) ----
@socketio.on("begin_round")
def on_begin_round():
    sid = request.sid
    if not players.get(sid, {}).get("is_host"):
        emit("error_msg", {"msg": "권한이 없습니다."}, to=sid)
        return
    start_round()

@socketio.on("start_vote_sum_reveal")
def on_start_vote_sum_reveal():
    sid = request.sid
    if not players.get(sid, {}).get("is_host"):
        emit("error_msg", {"msg": "권한이 없습니다."}, to=sid)
        return
    combined_vote_and_reveal_then_judge()

# ===== 엔트리 포인트 =====
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
