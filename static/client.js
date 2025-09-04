const socket = io();
let mySid = null;
let isHost = false;
let currentVoteRound = null; // 1 or 2
let voteSelections = {1: null, 2: null};
let voteLogs = {1: {}, 2: {}};

const $ = sel => document.querySelector(sel);
const $$ = sel => document.querySelectorAll(sel);

function showSection(id){ $$(".section").forEach(s=>s.classList.remove("show")); $("#"+id).classList.add("show"); }
function show(el){ el.classList.remove("hide"); }
function hide(el){ el.classList.add("hide"); }
function setTimerLabel(round){ $("#voteRoundTag").textContent = round ? `${round}차` : "-"; }
function resetVotePanel(){ $("#voteArea").innerHTML=""; setTimerLabel(null); }

function updateHostControls(){
  if(isHost){ show($("#startBtn")); show($("#resetBtn")); show($("#hostControls")); }
  else{ hide($("#startBtn")); hide($("#resetBtn")); hide($("#hostControls")); }
}

// 인트로
$("#joinBtn").onclick = () => {
  const name = $("#nameInput").value.trim();
  if(!name){ alert("이름을 입력하세요"); return; }
  socket.emit("join", {name});
};

// 로비
socket.on("joined", d => { mySid = d.sid; showSection("lobby"); });
socket.on("player_list", list => {
  const ul = $("#playerList"); ul.innerHTML="";
  list.forEach(p=>{
    const li = document.createElement("li");
    li.className="pill";
    li.textContent = `${p.name} · 점수 ${p.score}${p.is_host ? " · HOST":""}`;
    ul.appendChild(li);
  });
});
$("#hostBtn").onclick = () => { socket.emit("become_host", {code: $("#hostCodeInput").value.trim()}); };
socket.on("host_ok", d => { if(d.ok){ isHost=true; updateHostControls(); } else alert("호스트 코드가 틀렸습니다."); });
$("#startBtn").onclick = () => socket.emit("start_game");
$("#resetBtn").onclick = () => socket.emit("reset_game");

// 게임
socket.on("game_start", () => {
  showSection("game");
  hide($("#winBanner"));
  resetVotePanel();
  voteSelections={1:null,2:null}; voteLogs={1:{},2:{}};
  renderVoteStatus(1);
});
socket.on("role_assignment", d => { $("#roleInfo").textContent = `내 역할: ${d.role} · 주제: ${d.subject} · 제시어: ${d.keyword}`; });
socket.on("round_start", d => { $("#roundInfo").textContent = `Round ${d.round} / ${d.total_rounds} · 주제: ${d.subject}`; });

// 발언 안내
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

// 투표
socket.on("vote_start", d => {
  currentVoteRound = d.first ? 1 : 2;
  setTimerLabel(currentVoteRound);
  renderVoteGrid(d.candidates);
});
function renderVoteGrid(cands){
  const area = $("#voteArea"); area.innerHTML="";
  cands.forEach(c=>{
    const btn = document.createElement("button");
    btn.className="btn vote";
    btn.textContent = c.name;
    btn.dataset.sid = c.sid;
    if(voteSelections[currentVoteRound] === c.sid) btn.classList.add("selected");
    btn.onclick = ()=>{
      // 1인 1표: UI 선택 토글 + 서버에 최종표 전송
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
  Object.entries(logs).forEach(([voter,target])=>{
    const row = document.createElement("div");
    row.className="status-row";
    row.textContent = `${voter} → ${target}`; // 간단 표기
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
    const txt = d.scoreboard.map(x=>`${x.name} : ${x.score}`).join("\\n");
    alert("게임 종료!\\n\\n"+txt);
  }
  hide($("#winBanner"));
});

// 호스트 컨트롤 → 서버
$("#btnStartRound").onclick = ()=>{ socket.emit("manual_next_phase", {phase:"round_start"}); socket.emit("hide_vote_panel"); };
$("#btnNextSpeaker").onclick = ()=>{ socket.emit("manual_next_phase", {phase:"next_speaker"}); socket.emit("hide_vote_panel"); };
$("#btnStartDiscussion").onclick = ()=> socket.emit("manual_next_phase", {phase:"discussion"});
$("#btnStartVote").onclick = ()=> socket.emit("manual_next_phase", {phase:"vote"});
$("#btnShowResults").onclick = ()=> socket.emit("manual_next_phase", {phase:"results"});

// 서버로부터 투표 패널 숨김
socket.on("hide_vote_panel", ()=> resetVotePanel());
// 탭
$("#tabR1").onclick = ()=>{ $(".chip.active").classList.remove("active"); $("#tabR1").classList.add("active"); renderVoteStatus(1); };
$("#tabR2").onclick = ()=>{ $(".chip.active").classList.remove("active"); $("#tabR2").classList.add("active"); renderVoteStatus(2); };

# build_ts:1756943897
