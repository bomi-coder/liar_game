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
    "phase": "lobby",   # lobby, assign, hints, discuss, vote1, tie_speech, vote2, liar_guess, reveal, round_end, game_end
    "round": 0,
    "subject": None,
    "keyword": None,
    "roles": {},        # sid -> "LIAR"/"SPY"/"CITIZEN"
    "votes": {},        # 진행 중 투표 버퍼
    "votes1": {},       # 1차 투표 저장: voter_sid -> target_sid
    "votes2": {},       # 2차 투표 저장: voter_sid -> target_sid
    "tie_candidates": [],
    "current_speaker_idx": -1,
    "liar_sid": None,
    "spy_sid": None,
    "timer_end": None,
    "timer_token": 0
}

# ---- 유틸 ----
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
        "timer_token": 0,
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

# ---- 타이머 (리셋 지원: 토큰 방식) ----
def countdown(seconds, tick_event, end_event):
    game_state["timer_token"] = game_state.get("timer_token", 0) + 1
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

# ---- 라운드/단계 ----
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

    # 라운드 시작 브로드캐스트
    socketio.emit("round_start", {
        "round": game_state["round"],
        "total_rounds": ROUND_COUNT,
        "subject": game_state["subject"]
    })

    # 개인 역할/제시어 전달
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

    # 수동 진행을 위해 힌트 단계 준비만 표시
    game_state["phase"] = "hints"
    # 클라이언트에 순서 가이드(옵션)
    socketio.emit("hints_ready", {
        "order": [{"sid": s, "name": players[s]["name"]} for s in order]
    })

# 수동: 다음 발언자 1명 진행
def manual_next_speaker():
    if not order:
        return
    # 다음 인덱스 계산
    next_idx = game_state.get("current_speaker_idx", -1) + 1
    # 범위 체크
    if next_idx >= len(order):
        # 모두 발언 완료
        return False
    game_state["current_speaker_idx"] = next_idx
    sid = order[next_idx]
    if sid not in players:
        return False
    socketio.emit("hint_turn", {
        "speaker_sid": sid,
        "speaker_name": players[sid]["name"],
        "order_index": next_idx,
        "total": len(order),
        "seconds": HINT_SECONDS
    })
    countdown(HINT_SECONDS, "timer_tick", "timer_done")
    socketio.sleep(0.2)
    return True

# 자동 힌트 전체 진행(기존)
def run_hint_phase():
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

# 토론 시작(수동/자동 공용)
def start_discussion():
    game_state["phase"] = "discuss"
    socketio.emit("discussion_start", {"seconds": DISCUSS_SECONDS})
    countdown(DISCUSS_SECONDS, "timer_tick", "timer_done")
    socketio.sleep(0.2)

# 투표 공용 헬퍼
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
    socketio.start_background_task(run_vote_phase, first, candidates)

# 집계 헬퍼
def tally_votes(votes_dict, allowed_candidates=None):
    tally = {}
    for voter, target in votes_dict.items():
        if not allowed_candidates or target in allowed_candidates:
            tally[target] = tally.get(target, 0) + 1
    return tally

# 투표 단계 러너 (타이머 포함)
def run_vote_phase(first, candidates):
    end_time = time.time() + VOTE_SECONDS
    while time.time() < end_time:
        if len(game_state["votes"]) >= len(players):
            break
        socketio.sleep(0.2)

    # 최종 표 저장 (1차/2차)
    if first:
        game_state["votes1"] = dict(game_state["votes"])  # 복사 저장
    else:
        game_state["votes2"] = dict(game_state["votes"])  # 복사 저장

    # 실시간 현황 공유(선택): 누가 누구 찍었는지
    socketio.emit("vote_update", {
        "round": 1 if first else 2,
        "votes": game_state["votes"],  # {voter_sid: target_sid}
    })

    tally = tally_votes(game_state["votes"], allowed_candidates=candidates)

    if not tally:
        # 아무도 투표하지 않으면 무효 → 라이어/스파이 승
        liar_spy_win(reason="no_votes")
        return

    max_votes = max(tally.values())
    top = [sid for sid, cnt in tally.items() if cnt == max_votes]

    if len(top) >= 2:
        # 동률자 발언 후 재투표
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
        # 수동/자동 모두 여기서는 2차 투표로 유도
        start_vote(first=False, limited_to=top)
        return

    # 단일 최다득표자
    accused = top[0]
    if first:
        # 수동 플로우에서는 1차 종료만. (합산 공개는 별도 버튼)
        return
    else:
        # 2차에서 단일 최다 → 기존 규칙대로 처리
        liar_sid = game_state["liar_sid"]
        if accused == liar_sid:
            start_liar_guess()
        else:
            liar_spy_win(reason="wrong_accuse")

# 라이어 정답 기회
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

# 문자열 정규화
def normalize(s):
    return "".join(str(s).strip().split())

# 승패 처리
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
        socketio.sleep(3)
        start_round()

# ---- 라우트 ----
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
    game_state["phase"] = "assign"
    game_state["round"] = 0
    for p in players.values():
        p["score"] = 0
    socketio.emit("game_start", {"rounds": ROUND_COUNT})
    start_round()

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

# ---- 수동 진행용 이벤트 ----
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
    ok = manual_next_speaker()
    if not ok:
        emit("error_msg", {"msg": "더 이상 발언자가 없습니다."}, to=sid)

@socketio.on("start_discussion")
def on_start_discussion():
    sid = request.sid
    if not players.get(sid, {}).get("is_host"):
        emit("error_msg", {"msg": "권한이 없습니다."}, to=sid)
        return
    start_discussion()

@socketio.on("start_vote_manual")
def on_start_vote_manual(data=None):
    sid = request.sid
    if not players.get(sid, {}).get("is_host"):
        emit("error_msg", {"msg": "권한이 없습니다."}, to=sid)
        return
    # 기본: 1차가 비어있으면 1차, 있으면 2차
    first = True
    if data and isinstance(data, dict) and "first" in data:
        first = bool(data.get("first"))
    else:
        first = (len(game_state.get("votes1", {})) == 0)

    limited = None
    if not first:
        limited = game_state.get("tie_candidates") or list(players.keys())
    start_vote(first=first, limited_to=limited)

@socketio.on("start_vote_sum_reveal")
def on_start_vote_sum_reveal():
    """1차+2차 합산 결과 공개 및 규칙에 따른 분기 처리"""
    sid = request.sid
    if not players.get(sid, {}).get("is_host"):
        emit("error_msg", {"msg": "권한이 없습니다."}, to=sid)
        return

    # 합산 집계
    combined = {}
    for src in (game_state.get("votes1", {}), game_state.get("votes2", {})):
        for voter, target in src.items():
            if target not in players:
                continue
            combined[target] = combined.get(target, 0) + 1

    if not combined:
        # 표가 전혀 없으면 라/스 승
        liar_spy_win(reason="no_votes")
        return

    max_votes = max(combined.values())
    top = [sid for sid, cnt in combined.items() if cnt == max_votes]

    # 결과 화면용 브로드캐스트 (누가 몇 표 받았는지)
    socketio.emit("combined_vote_result", {
        "tally": [{"sid": sid, "name": players[sid]["name"], "votes": combined[sid]} for sid in combined]
    })

    if len(top) >= 2:
        # 합산도 동률이면 동률자 발언 후 재투표(2차)를 강제
        game_state["tie_candidates"] = top
        socketio.emit("vote_tie", {
            "candidates": [{"sid": sid, "name": players[sid]["name"]} for sid in top]
        })
        game_state["phase"] = "tie_speech"
        for sid2 in top:
            socketio.emit("tie_speech_turn", {
                "sid": sid2, "name": players[sid2]["name"], "seconds": TIE_SPEECH_SECONDS
            })
            countdown(TIE_SPEECH_SECONDS, "timer_tick", "timer_done")
            socketio.sleep(0.2)
        start_vote(first=False, limited_to=top)
        return

    # 단일 최다 득표자 확정
    accused = top[0]
    liar_sid = game_state["liar_sid"]
    if accused == liar_sid:
        start_liar_guess()
    else:
        liar_spy_win(reason="wrong_accuse")

# (옵션) 범용 수동 컨트롤: 클라이언트가 문자열로 지정
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
        ok = manual_next_speaker()
        if not ok:
            emit("error_msg", {"msg": "더 이상 발언자가 없습니다."}, to=sid)
    elif phase == "discussion":
        start_discussion()
    elif phase == "vote":
        on_start_vote_manual({})
    elif phase == "results":
        on_start_vote_sum_reveal()

# ---- 엔트리포인트 ----
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
