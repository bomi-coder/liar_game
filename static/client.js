const socket = io();

let mySid = null;
let isHost = false;
let currentVoteRound = null; // 1 or 2
let voteSelections = {1: null, 2: null};
let voteLogs = {1: [], 2: []}; // ✅ [{voter_name,target_name}, ...]

const $ = sel => document.querySelector(sel);
const $$ = sel => document.querySelectorAll(sel);

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

$("#joinBtn").onclick = () => {
  const name = $("#nameInput").value.trim();
  if(!name){ alert("이름을 입력하세요"); return; }
  if(!socket.connected){ alert("서버 연결을 확인해주세요."); return; }
  socket.emit("join", {name});
};

function updateHostControls(){
  const startBtn = $("#startBtn");
  if(startBtn){
    if(isHost) startBtn.classList.remove("hide"); else startBtn.classList.add("hide");
  }
  const hostControls = $("#hostControls");
  const btnResetGame = $("#btnResetGame");
  if(isHost){
    hostControls?.classList.remove("hide");
    btnResetGame?.classList.remove("hide");
  }else{
    hostControls?.classList.add("hide");
    btnResetGame?.classList.add("hide");
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

socket.on("host_ok", d => {
  if (d.ok) {
    window.isHost = true;
    if (typeof updateHostControls === "function") {
      updateHostControls();  // 호스트 컨트롤바 보이기/활성화
    }
    alert("호스트 권한이 부여되었습니다.");
  } else {
    alert("호스트 코드가 틀렸습니다.");
  }
});


// 호스트 버튼 클릭
$("#hostBtn").onclick = () => {
  if (!window.mySid) {
    alert("먼저 이름을 입력하고 '게임 로비 입장'으로 접속해 주세요.");
    return;
  }
  const raw = $("#hostCodeInput").value || "";
  const code = raw.trim(); // 앞뒤 공백 제거
  if (!code) {
    alert("호스트 코드를 입력해 주세요.");
    return;
  }
  socket.emit("become_host", { code });
};

$("#startBtn")?.addEventListener("click", ()=> socket.emit("start_game"));

socket.on("game_start", () => {
  showSection("game");
  $("#winBanner").classList.add("hide");
  resetVotePanel();
  voteSelections={1:null,2:null}; voteLogs={1:[],2:[]};
  renderVoteStatus(1);
  updateHostControls();
});

// 역할/라운드
socket.on("role_assignment", d => {
  $("#roleInfo").textContent = `내 역할: ${d.role} · 주제: ${d.subject} · 제시어: ${d.keyword}`;
});
socket.on("round_start", d => {
  $("#roundInfo").textContent = `Round ${d.round} / ${d.total_rounds} · 주제: ${d.subject}`;
});

// 발언 안내 + 팝업 + 진동
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

// 1인 1표 UI
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

// ✅ 공개 현황(닉네임 → 닉네임)
socket.on("vote_update", d => {
  voteLogs[d.round] = d.details || [];
  const active = $(".chip.active").id === "tabR2" ? 2 : 1;
  renderVoteStatus(active);
});

function renderVoteStatus(round){
  const box = $("#voteStatus"); box.innerHTML="";
  const logs = voteLogs[round] || [];
  if(logs.length === 0){ box.innerHTML="<div class='muted'>아직 투표가 없습니다.</div>"; return; }
  logs.forEach(it=>{
    const row = document.createElement("div");
    row.className="status-row";
    row.textContent = `${it.voter_name} → ${it.target_name}`;
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

// 🧑‍✈️ 호스트 컨트롤
$("#btnStartRound").onclick      = ()=>{ socket.emit("manual_next_phase", {phase:"round_start"}); socket.emit("hide_vote_panel"); };
$("#btnNextSpeaker").onclick     = ()=>{ socket.emit("manual_next_phase", {phase:"next_speaker"}); socket.emit("hide_vote_panel"); };
$("#btnStartDiscussion").onclick = ()=> socket.emit("manual_next_phase", {phase:"discussion"});
$("#btnStartVote").onclick       = ()=> socket.emit("manual_next_phase", {phase:"vote"});
$("#btnEndVote").onclick         = ()=> socket.emit("end_vote");          // ✅ 추가: 투표 종료
$("#btnShowResults").onclick     = ()=> socket.emit("manual_next_phase", {phase:"results"});
$("#btnResetGame").onclick       = ()=> socket.emit("reset_game");
