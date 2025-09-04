# -*- coding: utf-8 -*-
import os, random, time, json, eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

ADMIN_CODE = os.getenv("ADMIN_CODE", "BOM")
ROUND_COUNT = int(os.getenv("ROUND_COUNT", "5"))
HINT_SECONDS = int(os.getenv("HINT_SECONDS", "15"))
DISCUSS_SECONDS = int(os.getenv("DISCUSS_SECONDS", "120"))
TIE_SPEECH_SECONDS = int(os.getenv("TIE_SPEECH_SECONDS", "20"))
LIAR_GUESS_SECONDS = int(os.getenv("LIAR_GUESS_SECONDS", "30"))
VOTE_SECONDS = int(os.getenv("VOTE_SECONDS", "60"))

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "secret!liargame")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "topics.json")
with open(DATA_PATH, "r", encoding="utf-8") as f:
    TOPICS = json.load(f)

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
    "timer_token": 0,
}

def reset_round_state(full=False):
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
        "timer_token": 0,
    })
    if full:
        global order
        order = []

def broadcast_player_list():
    socketio.emit("player_list", [
        {"sid": sid, "name": p["name"], "score": p.get("score",0), "is_host": p.get("is_host", False)}
        for sid, p in players.items()
    ])

def choose_subject_and_keyword():
    subject = random.choice(list(TOPICS.keys()))
    keyword = random.choice(TOPICS[subject])
    return subject, keyword

def assign_roles():
    sids = list(players.keys())
    if not sids: return
    liar = random.choice(sids)
    spy = None
    if len(sids) >= 7:
        cand = [x for x in sids if x != liar]
        spy = random.choice(cand)
    game_state["liar_sid"] = liar
    game_state["spy_sid"] = spy
    for sid in sids:
        if sid == liar: game_state["roles"][sid] = "LIAR"
        elif spy and sid == spy: game_state["roles"][sid] = "SPY"
        else: game_state["roles"][sid] = "CITIZEN"

def countdown(seconds, tick_event, end_event):
    game_state["timer_token"] += 1
    token = game_state["timer_token"]
    socketio.emit("timer_reset", {"seconds": seconds})
    end_time = time.time() + seconds
    game_state["timer_end"] = end_time
    while True:
        if token != game_state["timer_token"]:
            return
        remaining = int(round(end_time - time.time()))
        if remaining < 0: remaining = 0
        socketio.emit(tick_event, {"remaining": remaining})
        if remaining <= 0: break
        socketio.sleep(1)
    socketio.emit(end_event, {})

def start_round():
    game_state["round"] += 1
    reset_round_state()
    subject, keyword = choose_subject_and_keyword()
    game_state["subject"] = subject
    game_state["keyword"] = keyword
    assign_roles()

    global order
    order = list(players.keys())
    random.shuffle(order)

    socketio.emit("round_start", {
        "round": game_state["round"], "total_rounds": ROUND_COUNT, "subject": game_state["subject"]
    })
    for sid in players.keys():
        role = game_state["roles"].get(sid, "CITIZEN")
        if role == "LIAR":
            socketio.emit("role_assignment", {"role":"라이어","subject":subject,"keyword":"???"}, to=sid)
        else:
            socketio.emit("role_assignment", {"role":"스파이" if role=="SPY" else "시민","subject":subject,"keyword":keyword}, to=sid)
    game_state["phase"] = "hints"
    socketio.emit("hints_ready", {"order":[{"sid":s, "name":players[s]["name"]} for s in order]})

def manual_next_speaker():
    if not order: return False
    next_idx = game_state.get("current_speaker_idx", -1) + 1
    if next_idx >= len(order): return False
    game_state["current_speaker_idx"] = next_idx
    sid = order[next_idx]
    if sid not in players: return False
    socketio.emit("pre_hint_notice", {"speaker_sid": sid, "speaker_name": players[sid]["name"]})
    socketio.sleep(1.5)
    socketio.emit("hint_turn", {
        "speaker_sid": sid, "speaker_name": players[sid]["name"],
        "order_index": next_idx, "total": len(order), "seconds": HINT_SECONDS
    })
    countdown(HINT_SECONDS, "timer_tick", "timer_done")
    socketio.sleep(0.2)
    return True

def start_discussion():
    game_state["phase"] = "discuss"
    socketio.emit("discussion_start", {"seconds": DISCUSS_SECONDS})
    countdown(DISCUSS_SECONDS, "timer_tick", "timer_done")
    socketio.sleep(0.2)

def start_vote(first=True, limited_to=None):
    game_state["phase"] = "vote1" if first else "vote2"
    game_state["votes"] = {}
    cand = limited_to if limited_to else list(players.keys())
    socketio.emit("vote_start", {
        "first": first, "round": 1 if first else 2,
        "candidates": [{"sid": s, "name": players[s]["name"]} for s in cand],
        "seconds": VOTE_SECONDS
    })
    socketio.start_background_task(run_vote_phase, first, cand)

def tally_votes(votes_dict, allowed=None):
    t = {}
    for voter, target in votes_dict.items():
        if not allowed or target in allowed:
            t[target] = t.get(target, 0) + 1
    return t

def run_vote_phase(first, cand):
    end_time = time.time() + VOTE_SECONDS
    while time.time() < end_time:
        if len(game_state["votes"]) >= len(players): break
        socketio.sleep(0.2)
    if first: game_state["votes1"] = dict(game_state["votes"])
    else: game_state["votes2"]  = dict(game_state["votes"])

    socketio.emit("vote_update", {"round": 1 if first else 2, "votes": game_state["votes"]})

    tally = tally_votes(game_state["votes"], allowed=cand)
    if not tally: return liar_spy_win("no_votes")
    maxv = max(tally.values())
    top = [sid for sid,c in tally.items() if c==maxv]
    if len(top) >= 2:
        game_state["tie_candidates"] = top
        socketio.emit("vote_tie", {"candidates":[{"sid":s,"name":players[s]["name"]} for s in top]})
        game_state["phase"] = "tie_speech"
        for s in top:
            socketio.emit("tie_speech_turn", {"sid":s,"name":players[s]["name"],"seconds":TIE_SPEECH_SECONDS})
            countdown(TIE_SPEECH_SECONDS, "timer_tick", "timer_done")
            socketio.sleep(0.2)
        return start_vote(first=False, limited_to=top)
    accused = top[0]
    if first: return  # 합산 공개는 별도
    if accused == game_state["liar_sid"]: start_liar_guess()
    else: liar_spy_win("wrong_accuse")

def start_liar_guess():
    game_state["phase"] = "liar_guess"
    liar_sid = game_state["liar_sid"]
    socketio.emit("liar_guess_start", {
        "liar_sid": liar_sid, "liar_name": players[liar_sid]["name"],
        "seconds": LIAR_GUESS_SECONDS, "subject": game_state["subject"]
    })
    socketio.emit("liar_input_enable", {}, to=liar_sid)
    socketio.start_background_task(run_liar_guess_timer, liar_sid)

def run_liar_guess_timer(liar_sid):
    countdown(LIAR_GUESS_SECONDS, "timer_tick", "timer_done")
    if game_state["phase"] == "liar_guess":
        citizens_win("timeout")

def normalize(s): return "".join(str(s).strip().split())

def citizens_win(reason=""):
    for sid, info in players.items():
        if game_state["roles"].get(sid,"CITIZEN") == "CITIZEN":
            info["score"] = info.get("score",0) + 1
    socketio.emit("round_result", {"winner":"시민","reason":reason,"keyword":game_state["keyword"]})
    emit_hide_vote(); end_or_next_round()

def liar_spy_win(reason=""):
    for sid, info in players.items():
        role = game_state["roles"].get(sid,"CITIZEN")
        if role=="LIAR": info["score"] = info.get("score",0) + 2
        elif role=="SPY": info["score"] = info.get("score",0) + 1
    socketio.emit("round_result", {"winner":"라이어/스파이","reason":reason,"keyword":game_state["keyword"]})
    emit_hide_vote(); end_or_next_round()

def emit_hide_vote(): socketio.emit("hide_vote_panel", {})

def end_or_next_round():
    if game_state["round"] >= ROUND_COUNT:
        game_state["phase"] = "game_end"
        board = [{"name":p["name"], "score":p.get("score",0)} for p in players.values()]
        board.sort(key=lambda x:x["score"], reverse=True)
        socketio.emit("game_over", {"scoreboard": board})
    else:
        game_state["phase"] = "round_end"
        socketio.emit("next_round_soon", {"next_round": game_state["round"]+1})
        socketio.sleep(2.0); start_round()

@app.route("/")
def index(): return render_template("index.html")

@socketio.on("connect")
def on_connect(): pass

@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    if sid in players:
        players.pop(sid, None)
        if sid in order:
            try: order.remove(sid)
            except ValueError: pass
        broadcast_player_list()

@socketio.on("join")
def on_join(data):
    name = (data.get("name","")).strip()
    if not name: emit("error_msg", {"msg":"이름을 입력해 주세요."}, to=request.sid); return
    sid = request.sid
    players[sid] = {"name": name, "score":0, "is_host":False}
    broadcast_player_list()
    emit("joined", {"sid": sid, "name": name}, to=sid)

@socketio.on("become_host")
def on_become_host(data):
    code = data.get("code",""); sid = request.sid
    if code==ADMIN_CODE and sid in players:
        players[sid]["is_host"] = True
        emit("host_ok", {"ok":True}, to=sid); broadcast_player_list()
    else: emit("host_ok", {"ok":False}, to=sid)

@socketio.on("start_game")
def on_start_game():
    sid = request.sid
    if not players.get(sid,{}).get("is_host"): emit("error_msg",{"msg":"권한이 없습니다."}, to=sid); return
    if len(players) < 3: emit("error_msg",{"msg":"최소 3명 이상이어야 시작할 수 있습니다."}, to=sid); return
    game_state["phase"] = "assign"; game_state["round"] = 0
    for p in players.values(): p["score"] = 0
    socketio.emit("game_start", {"rounds": ROUND_COUNT})
    start_round()

@socketio.on("vote")
def on_vote(data):
    sid = request.sid; target = (data or {}).get("target_sid")
    if game_state["phase"] not in ("vote1","vote2"): return
    if target not in players: return
    # 1인 1표: 덮어쓰기 (항상 마지막 표 1개만 유지)
    game_state["votes"][sid] = target
    emit("vote_ok", {"ok":True}, to=sid)

@socketio.on("liar_guess")
def on_liar_guess(data):
    sid = request.sid
    if sid != game_state.get("liar_sid"): return
    if game_state["phase"] != "liar_guess": return
    guess = (data.get("guess","")).strip()
    if not guess: return
    if normalize(guess) == normalize(game_state["keyword"]): liar_spy_win("liar_correct")
    else: citizens_win("liar_wrong")

# 수동 진행
@socketio.on("begin_round")
def on_begin_round():
    sid = request.sid
    if not players.get(sid,{}).get("is_host"): emit("error_msg",{"msg":"권한이 없습니다."}, to=sid); return
    start_round()

@socketio.on("next_speaker")
def on_next_speaker():
    sid = request.sid
    if not players.get(sid,{}).get("is_host"): emit("error_msg",{"msg":"권한이 없습니다."}, to=sid); return
    ok = manual_next_speaker()
    if not ok: emit("error_msg", {"msg":"더 이상 발언자가 없습니다."}, to=sid)

@socketio.on("start_discussion")
def on_start_discussion():
    sid = request.sid
    if not players.get(sid,{}).get("is_host"): emit("error_msg",{"msg":"권한이 없습니다."}, to=sid); return
    start_discussion()

@socketio.on("start_vote_manual")
def on_start_vote_manual(data=None):
    sid = request.sid
    if not players.get(sid,{}).get("is_host"): emit("error_msg",{"msg":"권한이 없습니다."}, to=sid); return
    first = True
    if data and isinstance(data, dict) and "first" in data: first = bool(data.get("first"))
    else: first = (len(game_state.get("votes1",{})) == 0)
    limited = None
    if not first: limited = game_state.get("tie_candidates") or list(players.keys())
    start_vote(first=first, limited_to=limited)

@socketio.on("start_vote_sum_reveal")
def on_start_vote_sum_reveal():
    sid = request.sid
    if not players.get(sid,{}).get("is_host"): emit("error_msg",{"msg":"권한이 없습니다."}, to=sid); return
    combined = {}
    for src in (game_state.get("votes1",{}), game_state.get("votes2",{})):
        for voter,target in src.items():
            if target not in players: continue
            combined[target] = combined.get(target,0) + 1
    if not combined: return liar_spy_win("no_votes")
    maxv = max(combined.values())
    top = [sid for sid,c in combined.items() if c==maxv]
    socketio.emit("combined_vote_result", {
        "tally": [{"sid": s, "name": players[s]["name"], "votes": combined[s]} for s in combined]
    })
    if len(top) >= 2:
        game_state["tie_candidates"] = top
        socketio.emit("vote_tie", {"candidates":[{"sid":s,"name":players[s]["name"]} for s in top]})
        game_state["phase"] = "tie_speech"
        for s in top:
            socketio.emit("tie_speech_turn", {"sid":s,"name":players[s]["name"],"seconds":TIE_SPEECH_SECONDS})
            countdown(TIE_SPEECH_SECONDS, "timer_tick", "timer_done")
            socketio.sleep(0.2)
        return start_vote(first=False, limited_to=top)
    accused = top[0]
    if accused == game_state["liar_sid"]: start_liar_guess()
    else: liar_spy_win("wrong_accuse")

@socketio.on("manual_next_phase")
def on_manual_next_phase(data):
    sid = request.sid
    if not players.get(sid,{}).get("is_host"): emit("error_msg",{"msg":"권한이 없습니다."}, to=sid); return
    phase = (data or {}).get("phase")
    if phase=="round_start": start_round(); emit_hide_vote()
    elif phase=="next_speaker":
        ok = manual_next_speaker(); emit_hide_vote()
        if not ok: emit("error_msg",{"msg":"더 이상 발언자가 없습니다."}, to=sid)
    elif phase=="discussion": start_discussion()
    elif phase=="vote": on_start_vote_manual({})
    elif phase=="results": on_start_vote_sum_reveal()

@socketio.on("hide_vote_panel")
def on_hide_vote_panel(): emit_hide_vote()

@socketio.on("reset_game")
def on_reset_game():
    for p in players.values():
        p["score"] = 0
        p["is_host"] = p.get("is_host", False)
    game_state["round"] = 0
    reset_round_state(full=True)
    game_state["phase"] = "lobby"
    socketio.emit("game_over", {"scoreboard": []})
    broadcast_player_list()

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.getenv("PORT","8000")))

# build_ts:1756943897
