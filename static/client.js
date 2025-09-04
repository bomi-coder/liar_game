// 소켓 연결
const socket = io();

// 도우미 상태
let mySid = null;
let isHost = false;
let currentVoteRound = null; // 1 or 2
let voteSelections = {1: null, 2: null};
let voteLogs = {1: {}, 2: {}};

const $ = sel => document.querySelector(sel);
const $$ = sel => document.querySelectorAll(sel);

// 섹션 전환: 인라인 display까지 강제 (CSS/캐시 꼬임 방지)
function hardShowSection(id){
  const ids = ["intro","lobby","game"];
  ids.forEach(k=>{
    const el = document.getElementById(k);
    if(!el) return;
    el.style.display = (k===id) ? "" : "none";
    el.classList.toggle("show", k===id);
  });
}
function showSection(id){ hardShowSection(id); }

// “로비 입장” 버튼을 소켓 연결 시에만 활성화
const joinBtn = $("#joinBtn");
function setJoinEnabled(on){
  if(!joinBtn) return;
  joinBtn.disabled = !on;
  if(on) joinBtn.classList.remove("disabled"); else joinBtn.classList.add("disabled");
}
hardShowSection("intro");
setJoinEnabled(false);

socket.on("connect", ()=> setJoinEnabled(true));
socket.on("disconnect", ()=> setJoinEnabled(false));

// 인트로 → join
$("#joinBtn").onclick = () => {
  const name = $("#nameInput").value.trim();
  if(!name){ alert("이름을 입력하세요"); return; }
  if(!socket.connected){ alert("서버 연결을 확인해주세요."); return; }
  socket.emit("join", {name});
};

// 로비 & 호스트 권한
function updateHostControls(){
  // 로비 영역 버튼(게임 시작)은 호스트만
  const startBtn = $("#startBtn");
  if(startBtn){
    if(isHost) startBtn.classList.remove("hide");
    else startBtn.classList.add("hide");
  }
  // 게임 화면의 호스트 컨트롤바 + 리셋 버튼도 호스트만
  const hostControls = $("#hostControls");
  const btnResetGame = $("#btnResetGame");
  if(isHost){
    if(hostControls) hostControls.classList.remove("hide");
    if(btnResetGame) btnResetGame.classList.remove("hide");
  }else{
    if(hostControls) hostControls.classList.add("hide");
    if(btnResetGame) btnResetGame.classList.add("hide");
  }
}

socket.on("joined", d => { mySid = d.sid; showSection("lobby"); updateHostControls(); });

socket.on("player_list", list => {
  const ul = $("#playerList"); if(!ul) return;
  ul.innerHTML="";
  list.forEach(p=>{
    const li = document.createElement("li");
    li.className="pill";
    li.textContent = `${p.name} · 점수 ${p.score}${p.is_host ? " · HOST":""}`;
    ul.appendChild(li);
  });
});

$("#hostBtn").onclick = () => {
  socket.emit("become_host", {code: $("#hostCodeInput").value.trim()});
};
socket.on("host_ok", d => {
  if(d.ok){
    isHost = true;
    updateHostControls(); // 로비에서 노출
  }else{
    alert("호스트 코드가 틀렸습니다.");
  }
});

// 로비의 “게임 시작”
$("#startBtn")?.addEventListener("click", ()=> socket.emit("start_game"));

// 게임 시작
socket.on("game_start", () => {
  showSection("game");
  $("#winBanner").classList.add("hide");
  resetVotePanel();
  voteSelections={1:null,2:null}; voteLogs={1:{},2:{}};
  renderVoteStatus(1);
  updateHostControls(); // 게임 화면에서도 호스트 전용 컨트롤 노출
});

// 역할/라운드
socket.on("role_assignment", d => {
  $("#roleInfo").textContent = `내 역할: ${d.role} · 주제: ${d.subject} · 제시어: ${d.keyword}`;
});
socket.on("round_start", d => {
  $("#roundInfo").textContent = `Round ${d.round} / ${d.total_rounds} · 주제: ${d.subject}`;
});

// 발언 안내 + 팝업 + 모바일 진동
socket.on("pre_hint_notice", d => {
  $("#preHint").classList.remove("hide");
  $("#speakerPopup").classList.remove("hide");
  if(d.speaker_sid === mySid && navigator.vibrate) navigator.vibrate(200);
});
socket.on("hint_turn", d => {
  $("#preHint").classList.add("hide");
  $("#speakerName").textContent = d.speaker_name;
  $("#speakerPopup").classList.remove("hide");
  if(d.speaker_sid === mySid && navigator.vibrate) navigator.vibrate([100,70,100]);
  setTimeout(()=>$("#speakerPopup").classList.add("hide"), 1800);
});
$("#closePopup").onclick = ()=> $("#speakerPopup").classList.add("hide");

// 타이머
socket.on("timer_reset", d => { $("#timer").textContent = d.seconds; });
socket.on("timer_tick", d => { $("#timer").textContent = d.remaining; });
socket.on("timer_done", () => { $("#timer").textContent = "0"; });

// 투표 패널
function setTimerLabel(round){ $("#voteRoundTag").textContent = round ? `${round}차` : "-"; }
function resetVotePanel(){ $("#voteArea").innerHTML=""; setTimerLabel(null); }
socket.on("hide_vote_panel", ()=> resetVotePanel());

// 투표 시작
socket.on("vote_start", d => {
  currentVoteRound = d.first ? 1 : 2;
  setTimerLabel(currentVoteRound);
  renderVoteGrid(d.candidates);
});

// 1인 1표 UI + 서버 전송
function renderVoteGrid(cands){
  const area = $("#voteArea"); area.innerHTML="";
  cands.forEach(c=>{
    const btn = document.createElement("button");
    btn.className="btn vote";
    btn.textContent = c.name;
    btn.dataset.sid = c.sid;
    if(voteSelections[currentVoteRound] === c.sid) btn.classList.add("selected");
    btn.onclick = ()=>{
      $$("#voteArea .btn.vote").forEach(b=>b.classList.remove("selected"));
      btn.classList.add("selected");
      voteSelections[currentVoteRound] = c.sid;
      socket.emit("vote", {target_sid: c.sid});
    };
    area.appendChild(btn);
  });
}

// 공개 현황
socket.on("vote_update", d => {
  voteLogs[d.round] = d.votes||{};
  const active = $(".chip.active").id === "tabR2" ? 2 : 1;
  renderVoteStatus(active);
});
function renderVoteStatus(round){
  const box = $("#voteStatus"); box.innerHTML="";
  const logs = voteLogs[round] || {};
  if(!Object.keys(logs).length){ box.innerHTML="<div class='muted'>아직 투표가 없습니다.</div>"; return; }
  Object.entries(logs).forEach(([voterSid,targetSid])=>{
    const row = document.createElement("div");
    row.className="status-row";
    row.textContent = `${voterSid} → ${targetSid}`;
    box.appendChild(row);
  });
}

// 합산 결과
socket.on("combined_vote_result", d => {
  const box = $("#voteStatus"); const tally = d.tally||[];
  box.innerHTML = "<div class='muted'>합계 득표수</div>";
  tally.sort((a,b)=>b.votes-a.votes).forEach(item=>{
    const row = document.createElement("div");
    row.className="status-row strong";
    row.textContent = `${item.name} : ${item.votes}표`;
    box.appendChild(row);
  });
});

// 결과
socket.on("round_result", d => {
  $("#winText").textContent = `승리: ${d.winner}`;
  $("#winKeyword").textContent = `제시어: ${d.keyword}`;
  $("#winBanner").classList.remove("hide");
  resetVotePanel();
});
socket.on("game_over", d => {
  if((d.scoreboard||[]).length){
    const txt = d.scoreboard.map(x=>`${x.name} : ${x.score}`).join("\n");
    alert("게임 종료!\n\n"+txt);
  }
  $("#winBanner").classList.add("hide");
});

// 탭
$("#tabR1").onclick = ()=>{ $(".chip.active").classList.remove("active"); $("#tabR1").classList.add("active"); renderVoteStatus(1); };
$("#tabR2").onclick = ()=>{ $(".chip.active").classList.remove("active"); $("#tabR2").classList.add("active"); renderVoteStatus(2); };

// 🧑‍✈️ 호스트 컨트롤: 버튼 동작 이벤트 (서버에 이미 핸들러 있음)
$("#btnStartRound").onclick      = ()=>{ socket.emit("manual_next_phase", {phase:"round_start"}); socket.emit("hide_vote_panel"); };
$("#btnNextSpeaker").onclick     = ()=>{ socket.emit("manual_next_phase", {phase:"next_speaker"}); socket.emit("hide_vote_panel"); };
$("#btnStartDiscussion").onclick = ()=> socket.emit("manual_next_phase", {phase:"discussion"});
$("#btnStartVote").onclick       = ()=> socket.emit("manual_next_phase", {phase:"vote"});
$("#btnShowResults").onclick     = ()=> socket.emit("manual_next_phase", {phase:"results"});
$("#btnResetGame").onclick       = ()=> socket.emit("reset_game"); // 🔁 게임 리셋 (게임 화면 안)

