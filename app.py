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

# Render 배포 호환: async_mode="eventlet"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

# ===== 주제/제시어 데이터 로드 =====
DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "topics.json")
with open(DATA_PATH, "r", encoding="utf-8") as f:
    TOPICS = json.load(f)

# ===== 상태 =====
players = {}  # sid -> {name, score, is_host}
order = []    # speaking order
game_state = {
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
    is_first = len(players) == 0
    players[sid] = {"name": name, "score": 0, "is_host": is_first}
    broadcast_player_list()
    emit("joined", {"sid": sid, "name": name, "is_host": is_first}, to=sid)
    # ✅ 로비 진입 신호
    emit("phase", {"phase": "lobby"}, to=sid)

# ===== 서버 실행 =====
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
