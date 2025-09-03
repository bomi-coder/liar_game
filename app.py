# -*- coding: utf-8 -*-
import os
import random
import time
import json
import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit

# 기본 설정
ADMIN_CODE = os.getenv("ADMIN_CODE", "BOM")  # 개발자 전용 시작 코드
ROUND_COUNT = int(os.getenv("ROUND_COUNT", "5"))
HINT_SECONDS = int(os.getenv("HINT_SECONDS", "15"))
DISCUSS_SECONDS = int(os.getenv("DISCUSS_SECONDS", "120"))
TIE_SPEECH_SECONDS = int(os.getenv("TIE_SPEECH_SECONDS", "20"))
LIAR_GUESS_SECONDS = int(os.getenv("LIAR_GUESS_SECONDS", "30"))
VOTE_SECONDS = int(os.getenv("VOTE_SECONDS", "60"))

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "secret!liargame")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

# 주제/제시어 데이터 로드 (외부 파일)
DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "topics.json")
with open(DATA_PATH, "r", encoding="utf-8") as f:
    TOPICS = json.load(f)

# ---- 상태 관리 ----
players = {}  # sid -> {name, score, is_host}
order = []    # speaking order (list of sid)
game_state = {

# 수동 진행 플래그
    "phase": "lobby",   # lobby, assign, hints, discuss, vote1, tie_speech, vote2, liar_guess, reveal, round_end, game_end
    "round": 0,
    "subject": None,
    "keyword": None,
    "roles": {},        # sid -> "LIAR"/"SPY"/"CITIZEN"
    "votes": {},        # sid -> target_sid
    "tie_candidates": [],
    "current_speaker_idx": -1,
    "liar_sid": None,
    "spy_sid": None,
    "timer_end": None
}

def reset_round_state():
    game_state.update({
        "phase": "assign",
        "subject": None,
        "keyword": None,
        "roles": {},
        "votes": {},
        "tie_candidates": [],
        "current_speaker_idx": -1,
        "liar_sid": None,
        "spy_sid": None,
        "timer_end": None
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

def start_round():
    game_state["round"] += 1
    reset_round_state()
    subject, keyword = choose_subject_and_keyword()
    game_state["subject"] = subject
    game_state["keyword"] = keyword
    assign_roles()

    # 발화 순서 섞기
    global order
    order = list(players.keys())
    random.shuffle(order)

    # ✅ 라운드 시작 브로드캐스트를 먼저 전송
    socketio.emit("round_start", {
        "round": game_state["round"],
        "total_rounds": ROUND_COUNT,
        "subject": game_state["subject"]
    })

    # 그 다음 개인 역할/제시어 발송 (유니캐스트: to=sid)
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

    # 힌트 단계로 이동(수동 진행)
    game_state["phase"] = "hints"
    global hint_initialized
    hint_initialized = True
    game_state["current_speaker_idx"] = -1
    socketio.emit("hints_ready", {"seconds": HINT_SECONDS, "order": [{"sid": s, "name": players[s]["name"]} for s in order]})

def countdown(seconds, tick_event, end_event):
    # 서버 기준 타이머 (초 단위 브로드캐스트)
    end_time = time.time() + seconds
    game_state["timer_end"] = end_time
    while True:
        remaining = int(round(end_time - time.time()))
        if remaining < 0:
            remaining = 0
        socketio.emit(tick_event, {"remaining": remaining})
        if remaining <= 0:
            break
        socketio.sleep(1)
    socketio.emit(end_event, {})

def run_hint_phase():
    # 순서대로 각자 15초 힌트
    for idx, sid in enumerate(order):
        if sid not in players:
            continue
        game_state["current_speaker_idx"] = idx
        socketio.emit("hint_turn", {
            "speaker_sid": sid,
            "speaker_name": players[sid]["name"],
            "order_index": idx,
            "total": len(order),
            "seconds": HINT_SECONDS
        })
        countdown(HINT_SECONDS, "timer_tick", "timer_done")
        socketio.sleep(0.2)
    # 토론 단계
    game_state["phase"] = "discuss"
    socketio.emit("discussion_start", {"seconds": DISCUSS_SECONDS})
    countdown(DISCUSS_SECONDS, "timer_tick", "timer_done")
    socketio.sleep(0.2)
    # 1차 투표
    start_vote(first=True)

def start_vote(first=True, limited_to=None):
    game_state["phase"] = "vote1" if first else "vote2"
    game_state["votes"] = {}
    candidates = limited_to if limited_to else list(players.keys())
    socketio.emit("vote_start", {
        "first": first,
        "candidates": [{"sid": sid, "name": players[sid]["name"]} for sid in candidates],
        "seconds": VOTE_SECONDS
    })
    socketio.start_background_task(run_vote_phase, first, candidates)

def run_vote_phase(first, candidates):
    # 투표 타이머
    end_time = time.time() + VOTE_SECONDS
    while time.time() < end_time:
        # 모든 플레이어가 투표를 완료하면 조기 종료
        if len(game_state["votes"]) >= len(players):
            break
        socketio.sleep(0.2)

    # 집계
    tally = {}
    for voter, target in game_state["votes"].items():
        if target in candidates:
            tally[target] = tally.get(target, 0) + 1

    if not tally:
        # 아무도 투표하지 않으면 무효 → 라이어/스파이 승
        liar_spy_win(reason="no_votes")
        return

    max_votes = max(tally.values())
    top = [sid for sid, cnt in tally.items() if cnt == max_votes]

        # 최다득표 결과 방송
    accused = top[0]
    role = game_state["roles"].get(accused, "CITIZEN")
    role_k = "라이어" if role=="LIAR" else ("스파이" if role=="SPY" else "시민")
    socketio.emit("vote_result", {"accused": {"sid": accused, "name": players.get(accused, {}).get("name", "?")}, "role": role_k, "tally": tally})

    if len(top) >= 2:
        # 동률자 발언
        game_state["tie_candidates"] = top
        socketio.emit("vote_tie", {
            "candidates": [{"sid": sid, "name": players[sid]["name"]} for sid in top]
        })
        # 동률자 각 20초 발언
        game_state["phase"] = "tie_speech"
        for sid in top:
            socketio.emit("tie_speech_turn", {
                "sid": sid, "name": players[sid]["name"], "seconds": TIE_SPEECH_SECONDS
            })
            countdown(TIE_SPEECH_SECONDS, "timer_tick", "timer_done")
            socketio.sleep(0.2)
        # 재투표
        start_vote(first=False, limited_to=top)
        return

    # 단일 최다득표자
    accused = top[0]
    liar_sid = game_state["liar_sid"]
    if accused == liar_sid:
        # 라이어 맞춤 기회
        start_liar_guess()
    else:
        # 라이어가 아닌 사람을 지목 → 라이어/스파이 승리
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
    # 라이어에게만 입력창 안내 (유니캐스트)
    socketio.emit("liar_input_enable", {}, to=liar_sid)
    socketio.start_background_task(run_liar_guess_timer, liar_sid)

def run_liar_guess_timer(liar_sid):
    # 30초 카운트다운
    countdown(LIAR_GUESS_SECONDS, "timer_tick", "timer_done")
    # 시간 만료 후에도 정답이 오지 않았다면 시민 승
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
        # 최종 스코어 보냄
        scoreboard = [{"name": p["name"], "score": p.get("score", 0)} for p in players.values()]
        scoreboard.sort(key=lambda x: x["score"], reverse=True)
        socketio.emit("game_over", {"scoreboard": scoreboard})
    else:
        # 잠깐 대기 후 다음 라운드
        game_state["phase"] = "round_end"
        socketio.emit("next_round_soon", {"next_round": game_state["round"] + 1})
        socketio.sleep(3)
        start_round()

@app.route("/")
def index():
    return render_template("index.html")

# ---- 소켓 이벤트 ----
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
    # 게임 시작
    game_state["phase"] = "assign"
    game_state["round"] = 0
    for p in players.values():
        p["score"] = 0
    socketio.emit("game_start", {"rounds": ROUND_COUNT})
    # 수동: 호스트가 라운드 시작 버튼을 눌러야 진행됨

@socketio.on("vote")
def on_vote(data):
    sid = request.sid
    target = data.get("target_sid")
    if game_state["phase"] not in ("vote1", "vote2"):
        return
    if target not in players:
        return
    game_state["votes"][sid] = target
    emit("vote_ok", {"ok": True}, to=sid)
    # 공개 투표 현황 방송
    voted = []
    for v, t in game_state["votes"].items():
        if v in players and t in players:
            voted.append({"from": players[v]["name"], "to": players[t]["name"]})
    socketio.emit("vote_update", {"voted": voted})

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
    # 판정
    if normalize(guess) == normalize(game_state["keyword"]):
        # 라이어/스파이 승
        liar_spy_win(reason="liar_correct")
    else:
        # 시민 승
        citizens_win(reason="liar_wrong")

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))

@socketio.on("begin_round")
def on_begin_round():
    sid = request.sid
    if not players.get(sid, {}).get("is_host"):
        emit("error_msg", {"msg": "권한이 없습니다."}, to=sid)
        return
    start_round()


@socketio.on("next_speaker")
def on_next_speaker():
    sid = request.sid
    if not players.get(sid, {}).get("is_host"):
        emit("error_msg", {"msg": "권한이 없습니다."}, to=sid)
        return
    if game_state.get("phase") != "hints":
        return
    # advance index
    if not order:
        return
    idx = game_state.get("current_speaker_idx", -1) + 1
    if idx >= len(order):
        # 모두 발언 완료
        socketio.emit("all_hints_done", {})
        return
    game_state["current_speaker_idx"] = idx
    spk_sid = order[idx]
    if spk_sid not in players:
        on_next_speaker()
        return
    socketio.emit("hint_turn", {
        "speaker_sid": spk_sid,
        "speaker_name": players[spk_sid]["name"],
        "order_index": idx,
        "total": len(order),
        "seconds": HINT_SECONDS
    })
    # 본인에게 팝업
    socketio.emit("your_turn_popup", {"name": players[spk_sid]["name"]}, to=spk_sid)
    countdown(HINT_SECONDS, "timer_tick", "timer_done")


@socketio.on("start_discussion")
def on_start_discussion():
    sid = request.sid
    if not players.get(sid, {}).get("is_host"):
        emit("error_msg", {"msg": "권한이 없습니다."}, to=sid)
        return
    if game_state.get("phase") not in ("hints", "discuss"):
        return
    game_state["phase"] = "discuss"
    socketio.emit("discussion_start", {"seconds": DISCUSS_SECONDS})
    countdown(DISCUSS_SECONDS, "timer_tick", "timer_done")


@socketio.on("start_vote_manual")
def on_start_vote_manual():
    sid = request.sid
    if not players.get(sid, {}).get("is_host"):
        emit("error_msg", {"msg": "권한이 없습니다."}, to=sid)
        return
    start_vote(first=True)


@socketio.on("start_tie_speech")
def on_start_tie_speech():
    sid = request.sid
    if not players.get(sid, {}).get("is_host"):
        emit("error_msg", {"msg": "권한이 없습니다."}, to=sid)
        return
    if not game_state.get("tie_candidates"):
        return
    game_state["phase"] = "tie_speech"
    for spk_sid in game_state["tie_candidates"]:
        if spk_sid in players:
            socketio.emit("tie_speech_turn", {
                "sid": spk_sid, "name": players[spk_sid]["name"], "seconds": TIE_SPEECH_SECONDS
            })
            countdown(TIE_SPEECH_SECONDS, "timer_tick", "timer_done")


@socketio.on("start_revote")
def on_start_revote():
    sid = request.sid
    if not players.get(sid, {}).get("is_host"):
        emit("error_msg", {"msg": "권한이 없습니다."}, to=sid)
        return
    if not game_state.get("tie_candidates"):
        return
    start_vote(first=False, limited_to=game_state["tie_candidates"])
