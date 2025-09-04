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
    "phase": "lobby",   # lobby, assign, hints, discuss, vote1, vote2, tie_speech, liar_guess, round_end, game_end
    "round": 0,
    "subject": None,
    "keyword": None,
    "roles": {},        # sid -> "LIAR"/"SPY"/"CITIZEN"
    "votes": {},        # 진행중 투표 버퍼
    "votes1": {},       # 1차 공개용
    "votes2": {},       # 2차 공개용
    "tie_candidates": [],
    "current_speaker_idx": -1,
    "liar_sid": None,
    "spy_sid": None,
    "timer_end": None,
    "timer_token": 0
}

# ===== 유틸 =====
def stop_timer():
    game_state["timer_token"] += 1
    game_state["timer_end"] = None
    socketio.emit("timer_done", {})

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
    game_state["timer_token"] += 1
    my_token = game_state["timer_token"]
    socketio.emit("timer_reset", {"seconds": seconds})
    end_time = time.time() + seconds
    game_state["timer_end"] = end_time
    while True:
        if my_token != game_state.get("timer_token"):
            return
        remaining = int(round(end_time - time.time()))
        if remaining < 0:
            remaining = 0
        socketio.emit(tick_event, {"remaining": remaining})
        if remaining <= 0:
            break
        socketio.sleep(1)
    socketio.emit(end_event, {})

# ===== 라운드/단계 =====
def start_round():
    game_state["round"] += 1
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

    # 라운드 정보 & 개인 역할 노출
    socketio.emit("round_start", {
        "round": game_state["round"],
        "total_rounds": ROUND_COUNT,
        "subject": game_state["subject"]
    })
    for sid in players.keys():
        role = game_state["roles"].get(sid, "CITIZEN")
        if role == "LIAR":
            socketio.emit("role_assignment", {"role": "라이어","subject": game_state["subject"],"keyword": "???"}, to=sid)
        else:
            socketio.emit("role_assignment", {"role": "스파이" if role=="SPY" else "시민","subject": game_state["subject"],"keyword": game_state["keyword"]}, to=sid)

    game_state["phase"] = "hints"
    game_state["current_speaker_idx"] = -1

def step_next_speaker():
    if game_state["phase"] not in ("hints", "assign"):
        return
    next_idx = game_state.get("current_speaker_idx", -1) + 1
    if next_idx >= len(order):
        # 모두 발언 완료 → 토론으로 넘어갈 수 있게 상태만
        game_state["phase"] = "discuss"
        return
    game_state["current_speaker_idx"] = next_idx
    sid = order[next_idx]
    name = players.get(sid, {}).get("name", "알수없음")

    socketio.emit("pre_hint_notice", {"speaker_sid": sid, "speaker_name": name})
    socketio.sleep(0.4)
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

def _broadcast_vote_update(roundno):
    details = []
    votes = game_state["votes1"] if roundno == 1 else game_state["votes2"]
    for voter, target in votes.items():
        details.append({
            "voter_sid": voter,
            "voter_name": players.get(voter, {}).get("name", voter),
            "target_sid": target,
            "target_name": players.get(target, {}).get("name", target),
        })
    socketio.emit("vote_update", {"round": roundno, "details": details})

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
    socketio.start_background_task(countdown, VOTE_SECONDS, "timer_tick", "timer_done")

def end_vote():
    """호스트가 '투표 종료'를 누르면 타이머 정지 + 패널 숨김.
       1차 투표였다면 다음 사이클(다시 힌트)로 갈 수 있도록 phase 유연화."""
    stop_timer()
    socketio.emit("hide_vote_panel")
    if game_state["phase"] == "vote1":
        # 다시 힌트 단계로 돌아가서 전원 발언 2회차 진행 가능
        game_state["phase"] = "hints"
        game_state["current_speaker_idx"] = -1

def combined_vote_and_reveal_then_judge():
    tally = {}
    for d in (game_state["votes1"], game_state["votes2"]):
        for voter, target in d.items():
            if target in players:
                tally[target] = tally.get(target, 0) + 1
    name_map = {sid: players[sid]["name"] for sid in players}
    combo_list = [{"sid": sid, "name": name_map.get(sid, sid), "votes": v} for sid, v in tally.items()]
    socketio.emit("combined_vote_result", {"tally": combo_list})

    if not tally:
        liar_spy_win(reason="no_votes"); return
    max_votes = max(tally.values())
    top = [sid for sid, cnt in tally.items() if cnt == max_votes]
    if len(top) >= 2:
        game_state["tie_candidates"] = top
        socketio.emit("vote_tie", {"candidates": [{"sid": sid, "name": players[sid]["name"]} for sid in top]})
        game_state["phase"] = "tie_speech"
        for sid in top:
            socketio.emit("tie_speech_turn", {"sid": sid, "name": players[sid]["name"], "seconds": TIE_SPEECH_SECONDS})
            countdown(TIE_SPEECH_SECONDS, "timer_tick", "timer_done")
            socketio.sleep(0.2)
        start_vote(first=False, limited_to=top)
        return
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
    for sid, info in players.items():
        role = game_state["roles"].get(sid, "CITIZEN")
        if role == "CITIZEN":
            info["score"] = info.get("score", 0) + 1
    socketio.emit("round_result", {"winner": "시민", "reason": reason, "keyword": game_state["keyword"]})
    end_or_next_round()

def liar_spy_win(reason=""):
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
        socketio.sleep(2.0)
        # 다음 라운드는 호스트가 '라운드 시작'으로 진행

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
    code = (data.get("code", "") or "").strip()
    sid = request.sid
    # 대소문자 무시 비교
    if sid in players and code and code.lower() == ADMIN_CODE.lower():
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
    game_state["phase"] = "assign"
    game_state["round"] = 0
    for p in players.values():
        p["score"] = 0
    socketio.emit("game_start", {"rounds": ROUND_COUNT})
    # 라운드 시작은 수동 버튼

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
        # 1차가 비어 있으면 1차, 아니면 2차
        first = (len(game_state["votes1"]) == 0)
        start_vote(first=first)
    elif phase == "results":
        combined_vote_and_reveal_then_judge()

@socketio.on("end_vote")
def on_end_vote():
    sid = request.sid
    if not players.get(sid, {}).get("is_host"):
        emit("error_msg", {"msg": "권한이 없습니다."}, to=sid)
        return
    end_vote()

@socketio.on("hide_vote_panel")
def on_hide_vote_panel():
    # 클라 UI용 훅
    pass

@socketio.on("reset_game")
def on_reset_game():
    sid = request.sid
    if not players.get(sid, {}).get("is_host"):
        emit("error_msg", {"msg": "권한이 없습니다."}, to=sid)
        return
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
    socketio.emit("game_over", {"scoreboard": []})

@socketio.on("vote")
def on_vote(data):
    sid = request.sid
    target = data.get("target_sid")
    if game_state["phase"] not in ("vote1", "vote2"):
        return
    if target not in players:
        return
    # 1인 1표(마지막 선택으로 덮어쓰기)
    game_state["votes"][sid] = target
    if game_state["phase"] == "vote1":
        game_state["votes1"][sid] = target
        _broadcast_vote_update(1)
    else:
        game_state["votes2"][sid] = target
        _broadcast_vote_update(2)
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

# 호환용
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

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
