import os
import random
from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from datetime import datetime
from data.topics import TOPICS

# ------------ App Setup ------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

HOST_CODE = os.environ.get("HOST_CODE", "9999")
ROOM = "main"

# ------------ In-Memory Game State (reset on server restart) ------------
class GameState:
    def __init__(self):
        self.reset_all()

    def reset_all(self):
        self.players = {}  # sid -> {'name': str, 'score': int, 'is_host': bool}
        self.sid_by_name = {}
        self.host_sid = None
        self.phase = "lobby"  # 'lobby','hint1','discussion','vote1','hint2','vote2','liar_guess','results','summary'
        self.round_num = 0
        self.max_rounds = 3
        self.category = None
        self.secret_word = None
        self.order = []  # speaking order
        self.roles = {}  # sid -> 'liar'|'spy'|'citizen'
        self.liar_sid = None
        self.spy_sid = None
        self.votes1 = {}  # voter_sid -> target_sid
        self.votes2 = {}  # voter_sid -> target_sid
        self.last_result = None  # dict summary of last round

    def game_started(self):
        return self.round_num > 0

GS = GameState()

# ------------ Helpers ------------
def get_players_public():
    arr = []
    for sid, info in GS.players.items():
        arr.append({
            "sid": sid,
            "name": info["name"],
            "score": info["score"],
            "is_host": info.get("is_host", False)
        })
    # stable sort by join order (approx by name mapping) then host first
    arr.sort(key=lambda x: (not x["is_host"], x["name"]))
    return arr

def broadcast_lobby_state():
    socketio.emit("lobby_state", {
        "players": get_players_public(),
        "host_sid": GS.host_sid,
        "host_name": GS.players.get(GS.host_sid, {}).get("name") if GS.host_sid else None,
        "phase": GS.phase
    }, to=ROOM)

def choose_roles_and_topic():
    sids = list(GS.players.keys())
    if len(sids) < 3:
        return False, "최소 3명 이상이 필요합니다."
    liar = random.choice(sids)
    spy = None
    if len(sids) >= 7:
        rest = [x for x in sids if x != liar]
        spy = random.choice(rest)
    GS.liar_sid = liar
    GS.spy_sid = spy
    GS.roles = {}
    for sid in sids:
        if sid == liar:
            GS.roles[sid] = "liar"
        elif spy and sid == spy:
            GS.roles[sid] = "spy"
        else:
            GS.roles[sid] = "citizen"

    category = random.choice(list(TOPICS.keys()))
    word = random.choice(TOPICS[category])
    GS.category = category
    GS.secret_word = word
    return True, None

def reset_round():
    GS.votes1 = {}
    GS.votes2 = {}
    GS.order = []
    GS.phase = "lobby"

def speaking_order():
    # random order among players
    order = list(GS.players.keys())
    random.shuffle(order)
    GS.order = order
    return order

def vote_tally(votes):
    tally = {}
    for voter, target in votes.items():
        tally[target] = tally.get(target, 0) + 1
    return tally

def top_candidates(tally):
    if not tally:
        return []
    maxv = max(tally.values())
    tops = [sid for sid, v in tally.items() if v == maxv]
    return tops, maxv

def apply_scores(result):
    # result dict keys: 'winner' 'liar_selected' 'liar_guessed_correct' etc.
    # Scoring rules:
    # 시민 승리: 최다득표로 라이어 정확 지목 & 라이어 정답 못맞힘 → 시민 전원 +1, 라이어/스파이 0
    # 라이어 승리(1): 최다득표로 라이어가 안 걸림 → 라이어 +2, 스파이 +1, 시민 0
    # 라이어 승리(2): 라이어가 걸렸지만 정답 맞힘 → 라이어 +2, 스파이 +1, 시민 0
    if result.get("winner") == "citizens":
        for sid, info in GS.players.items():
            if GS.roles.get(sid) == "citizen" or GS.roles.get(sid) == "spy":  # 시민 전원만 +1 (스파이는 0)
                pass
        for sid, info in GS.players.items():
            role = GS.roles.get(sid)
            if role == "citizen":
                info["score"] += 1
    else:
        # Liar/Spy win
        for sid, info in GS.players.items():
            role = GS.roles.get(sid)
            if role == "liar":
                info["score"] += 2
            elif role == "spy":
                info["score"] += 1

# ------------ Routes ------------
@app.route("/")
def index():
    name = session.get("name", "")
    return render_template("index.html", name=name)

@app.route("/join", methods=["POST"])
def join():
    name = request.form.get("name", "").strip()
    if not name:
        return redirect(url_for("index"))
    session["name"] = name
    return redirect(url_for("lobby"))

@app.route("/lobby")
def lobby():
    if not session.get("name"):
        return redirect(url_for("index"))
    return render_template("lobby.html", name=session["name"])

@app.route("/game")
def game():
    if not session.get("name"):
        return redirect(url_for("index"))
    return render_template("game.html", name=session["name"])

# ------------ Socket.IO ------------
@socketio.on("connect")
def on_connect():
    join_room(ROOM)
    emit("connected", {"message": "connected"})

@socketio.on("register")
def on_register(data):
    name = data.get("name", "").strip()
    sid = request.sid
    if not name:
        emit("error", {"message": "이름이 필요합니다."})
        return
    # If already exists with this sid, update name; else create
    GS.players[sid] = {"name": name, "score": 0, "is_host": (GS.host_sid == sid)}
    GS.sid_by_name[name] = sid
    broadcast_lobby_state()

@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    # If host leaves, drop host
    if sid == GS.host_sid:
        GS.host_sid = None
    if sid in GS.players:
        del GS.players[sid]
    # Clean roles if mid-game
    if sid in GS.roles:
        del GS.roles[sid]
    broadcast_lobby_state()

@socketio.on("claim_host")
def on_claim_host(data):
    code = str(data.get("code", "")).strip()
    sid = request.sid
    if code == HOST_CODE:
        GS.host_sid = sid
        # update host flags
        for s, info in GS.players.items():
            info["is_host"] = (s == GS.host_sid)
        emit("host_granted", {"ok": True, "host_sid": sid, "host_name": GS.players[sid]["name"]}, to=sid)
        broadcast_lobby_state()
    else:
        emit("host_granted", {"ok": False, "message": "호스트 코드가 올바르지 않습니다."}, to=sid)

@socketio.on("start_game")
def on_start_game():
    sid = request.sid
    if sid != GS.host_sid:
        emit("error", {"message": "호스트만 시작할 수 있습니다."}, to=sid)
        return
    ok, msg = choose_roles_and_topic()
    if not ok:
        emit("error", {"message": msg}, to=sid)
        return
    GS.round_num = 1
    GS.phase = "hint1"
    order = speaking_order()

    # send private role info
    for target_sid, info in GS.players.items():
        role = GS.roles.get(target_sid)
        if role == "liar":
            socketio.emit("role_info", {
                "role": "라이어",
                "topic": GS.category,
                "keyword": None
            }, to=target_sid)
        elif role == "spy":
            socketio.emit("role_info", {
                "role": "스파이",
                "topic": GS.category,
                "keyword": GS.secret_word
            }, to=target_sid)
        else:
            socketio.emit("role_info", {
                "role": "시민",
                "topic": GS.category,
                "keyword": GS.secret_word
            }, to=target_sid)

    # tell everyone to move to /game
    socketio.emit("game_started", {"round": GS.round_num})
    # initial hint order
    socketio.emit("hint_order", {
        "order": [{"sid": s, "name": GS.players[s]["name"]} for s in order],
        "phase": GS.phase,
        "round": GS.round_num
    }, to=ROOM)

@socketio.on("hint_next")
def on_hint_next(data):
    # host advances to next speaker index
    sid = request.sid
    if sid != GS.host_sid:
        return
    idx = int(data.get("index", 0))
    if not GS.order:
        return
    if idx < 0 or idx >= len(GS.order):
        return
    target_sid = GS.order[idx]
    socketio.emit("hint_turn", {
        "index": idx,
        "sid": target_sid,
        "name": GS.players.get(target_sid, {}).get("name"),
        "seconds": 15
    }, to=ROOM)

@socketio.on("start_discussion")
def on_start_discussion():
    if request.sid != GS.host_sid:
        return
    GS.phase = "discussion"
    socketio.emit("start_timer", {"label": "전체 자유토론", "seconds": 120}, to=ROOM)

@socketio.on("start_vote1")
def on_start_vote1():
    if request.sid != GS.host_sid:
        return
    GS.phase = "vote1"
    socketio.emit("open_vote", {
        "phase": "vote1",
        "players": [{"sid": s, "name": info["name"]} for s, info in GS.players.items()]
    }, to=ROOM)

@socketio.on("start_hint2")
def on_start_hint2():
    if request.sid != GS.host_sid:
        return
    GS.phase = "hint2"
    order = speaking_order()
    socketio.emit("hint_order", {
        "order": [{"sid": s, "name": GS.players[s]["name"]} for s in order],
        "phase": GS.phase,
        "round": GS.round_num
    }, to=ROOM)

@socketio.on("cast_vote")
def on_cast_vote(data):
    voter = request.sid
    target = data.get("target_sid")
    phase = GS.phase
    if phase not in ["vote1", "vote2"]:
        return
    if target not in GS.players:
        return
    if target == voter:
        emit("error", {"message": "자기 자신에게는 투표할 수 없습니다."}, to=voter)
        return
    if phase == "vote1":
        GS.votes1[voter] = target
        socketio.emit("vote_update", {"phase": "vote1", "voter": GS.players[voter]["name"], "target": GS.players[target]["name"]}, to=ROOM)
    else:
        GS.votes2[voter] = target
        socketio.emit("vote_update", {"phase": "vote2", "voter": GS.players[voter]["name"], "target": GS.players[target]["name"]}, to=ROOM)

@socketio.on("close_vote1")
def on_close_vote1():
    if request.sid != GS.host_sid:
        return
    tally = vote_tally(GS.votes1)
    tops, maxv = top_candidates(tally)
    socketio.emit("vote_closed", {
        "phase": "vote1",
        "tally": {GS.players[sid]["name"]: cnt for sid, cnt in tally.items()},
        "top": [GS.players[sid]["name"] for sid in tops],
        "max": maxv
    }, to=ROOM)

@socketio.on("start_vote2")
def on_start_vote2():
    if request.sid != GS.host_sid:
        return
    GS.phase = "vote2"
    socketio.emit("open_vote", {
        "phase": "vote2",
        "players": [{"sid": s, "name": info["name"]} for s, info in GS.players.items()]
    }, to=ROOM)

@socketio.on("close_vote2")
def on_close_vote2():
    if request.sid != GS.host_sid:
        return
    tally2 = vote_tally(GS.votes2)
    tops2, maxv2 = top_candidates(tally2)
    socketio.emit("vote_closed", {
        "phase": "vote2",
        "tally": {GS.players[sid]["name"]: cnt for sid, cnt in tally2.items()},
        "top": [GS.players[sid]["name"] for sid in tops2],
        "max": maxv2
    }, to=ROOM)

    # Decide accused: if tie persists, pick randomly among tops2
    if not tops2:
        accused_sid = None
    elif len(tops2) == 1:
        accused_sid = tops2[0]
    else:
        accused_sid = random.choice(tops2)

    if accused_sid and accused_sid == GS.liar_sid:
        # liar selected -> allow liar to guess
        GS.phase = "liar_guess"
        liar_name = GS.players[GS.liar_sid]["name"]
        socketio.emit("liar_selected", {
            "liar_name": liar_name,
            "seconds": 30,
            "category": GS.category
        }, to=ROOM)
    else:
        # liar not selected => liar team wins immediately
        result = {
            "winner": "liar_team",
            "liar_selected": False,
            "liar_guessed_correct": None,
            "secret_word": GS.secret_word,
            "category": GS.category,
            "accused": GS.players[accused_sid]["name"] if accused_sid else None
        }
        apply_scores(result)
        GS.last_result = result
        GS.phase = "results"
        socketio.emit("round_result", result, to=ROOM)

@socketio.on("liar_guess")
def on_liar_guess(data):
    # only liar can send this
    sid = request.sid
    if sid != GS.liar_sid:
        return
    guess = str(data.get("guess", "")).strip()
    correct = (guess == GS.secret_word)
    if correct:
        winner = "liar_team"
    else:
        winner = "citizens"
    result = {
        "winner": winner,
        "liar_selected": True,
        "liar_guessed_correct": correct,
        "secret_word": GS.secret_word,
        "category": GS.category,
        "accused": GS.players[GS.liar_sid]["name"]
    }
    apply_scores(result)
    GS.last_result = result
    GS.phase = "results"
    socketio.emit("round_result", result, to=ROOM)

@socketio.on("next_round")
def on_next_round():
    if request.sid != GS.host_sid:
        return
    if GS.round_num >= GS.max_rounds:
        # game over -> summary
        GS.phase = "summary"
        scoreboard = [{"name": info["name"], "score": info["score"]} for _, info in GS.players.items()]
        scoreboard.sort(key=lambda x: (-x["score"], x["name"]))
        socketio.emit("final_scores", {"scores": scoreboard}, to=ROOM)
        return

    # Start next round
    reset_round()
    GS.round_num += 1
    choose_roles_and_topic()
    GS.phase = "hint1"
    order = speaking_order()

    for target_sid, info in GS.players.items():
        role = GS.roles.get(target_sid)
        if role == "liar":
            socketio.emit("role_info", {
                "role": "라이어",
                "topic": GS.category,
                "keyword": None
            }, to=target_sid)
        elif role == "spy":
            socketio.emit("role_info", {
                "role": "스파이",
                "topic": GS.category,
                "keyword": GS.secret_word
            }, to=target_sid)
        else:
            socketio.emit("role_info", {
                "role": "시민",
                "topic": GS.category,
                "keyword": GS.secret_word
            }, to=target_sid)

    socketio.emit("game_started", {"round": GS.round_num})
    socketio.emit("hint_order", {
        "order": [{"sid": s, "name": GS.players[s]["name"]} for s in order],
        "phase": GS.phase,
        "round": GS.round_num
    }, to=ROOM)

# ------------ Main ------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Using eventlet web server for websockets on Render
    socketio.run(app, host="0.0.0.0", port=port)
