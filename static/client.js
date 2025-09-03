const socket = io();
let mySid = null;
let isHost = false;

// 섹션 토글
function showSection(id) {
  document.querySelectorAll(".section").forEach(sec => sec.style.display = "none");
  document.getElementById(id).style.display = "block";
}

// 호스트 컨트롤 표시/숨김
function updateHostControls() {
  document.getElementById("hostControls").style.display = isHost ? "block" : "none";
}

// --- 인트로 ---
document.getElementById("joinBtn").onclick = () => {
  const name = document.getElementById("nameInput").value.trim();
  if (!name) return alert("이름을 입력하세요");
  socket.emit("join", { name });
};

// --- 로비 ---
socket.on("joined", data => {
  mySid = data.sid;
  showSection("lobby");
});

socket.on("player_list", list => {
  const ul = document.getElementById("playerList");
  ul.innerHTML = "";
  list.forEach(p => {
    const li = document.createElement("li");
    li.textContent = `${p.name} (점수:${p.score}) ${p.is_host ? "[HOST]" : ""}`;
    ul.appendChild(li);
  });
});

document.getElementById("hostBtn").onclick = () => {
  const code = document.getElementById("hostCodeInput").value.trim();
  socket.emit("become_host", { code });
};

socket.on("host_ok", data => {
  if (data.ok) {
    isHost = true;
    document.getElementById("startBtn").style.display = "inline-block";
    updateHostControls();
  } else {
    alert("호스트 코드가 틀렸습니다.");
  }
});

document.getElementById("startBtn").onclick = () => {
  socket.emit("start_game");
};

// --- 게임 ---
socket.on("game_start", data => {
  showSection("game");
});

socket.on("role_assignment", data => {
  document.getElementById("roleInfo").innerText =
    `내 역할: ${data.role}, 주제: ${data.subject}, 제시어: ${data.keyword}`;
});

socket.on("round_start", data => {
  document.getElementById("roundInfo").innerText =
    `Round ${data.round} / ${data.total_rounds} (주제: ${data.subject})`;
});

// 발언 차례
socket.on("hint_turn", data => {
  const popup = document.getElementById("speakerPopup");
  const nameBadge = document.getElementById("speakerName");
  nameBadge.textContent = data.speaker_name;
  popup.style.display = "flex";
  if (data.speaker_sid === mySid && navigator.vibrate) {
    navigator.vibrate(300);
  }
  setTimeout(() => { popup.style.display = "none"; }, 2000);
});

// 타이머
socket.on("timer_tick", d => {
  document.getElementById("timer").innerText = `남은 시간: ${d.remaining}s`;
});
socket.on("timer_done", () => {
  document.getElementById("timer").innerText = "";
});

// 투표
socket.on("vote_start", d => {
  const area = document.getElementById("voteArea");
  area.innerHTML = "";
  d.candidates.forEach(c => {
    const btn = document.createElement("button");
    btn.textContent = c.name;
    btn.onclick = () => {
      socket.emit("vote", { target_sid: c.sid });
      btn.style.backgroundColor = "#3b82f6";
    };
    area.appendChild(btn);
  });
});

socket.on("round_result", d => {
  document.getElementById("voteResults").innerText =
    `승리: ${d.winner}, 제시어: ${d.keyword}`;
});

socket.on("game_over", d => {
  const results = d.scoreboard.map(s => `${s.name} : ${s.score}`).join("\n");
  document.getElementById("finalResults").innerText = results;
});

// --- 호스트 컨트롤 ---
document.getElementById("btnStartRound").onclick = () => socket.emit("manual_next_phase", { phase: "round_start" });
document.getElementById("btnNextSpeaker").onclick = () => socket.emit("manual_next_phase", { phase: "next_speaker" });
document.getElementById("btnStartDiscussion").onclick = () => socket.emit("manual_next_phase", { phase: "discussion" });
document.getElementById("btnStartVote").onclick = () => socket.emit("manual_next_phase", { phase: "vote" });
document.getElementById("btnShowResults").onclick = () => socket.emit("manual_next_phase", { phase: "results" });
