/* global io */
const socket = io();

let mySid = null;
let myName = null;
let isHost = false;

function $(sel){ return document.querySelector(sel); }
function $all(sel){ return document.querySelectorAll(sel); }

// 페이지 요소
const joinForm = $("#join-form");
const nameInput = $("#name-input");
const lobbyBtn = $("#lobby-btn");
const introSection = $("#intro");
const lobbySection = $("#lobby");
const playerList = $("#player-list");
const startBtn = $("#start-btn");
const hostCodeBtn = $("#host-code-btn");
const hostCodeInput = $("#host-code-input");
const gameSection = $("#game");
const phaseTitle = $("#phase-title");
const roleBox = $("#role-box");
const subjectBox = $("#subject-box");
const keywordBox = $("#keyword-box");
const orderBox = $("#order-box");
const timerBox = $("#timer-box");
const voteBox = $("#vote-box");
const voteList = $("#vote-list");
const guessBox = $("#guess-box");
const guessInput = $("#guess-input");
const guessBtn = $("#guess-btn");
const scoreboardBox = $("#scoreboard-box");
const scoreboardList = $("#scoreboard-list");
const csvBtn = $("#csv-btn");

// 호스트 컨트롤
const hostControls = $("#host-controls");
const btnBeginRound = $("#btn-begin-round");
const btnNextSpeaker = $("#btn-next-speaker");
const btnStartDiscussion = $("#btn-start-discussion");
const btnStartVote = $("#btn-start-vote");
const btnStartSumReveal = $("#btn-start-sum-reveal");

function updateHostControls(){
  if(!hostControls) return;
  hostControls.style.display = isHost ? "block" : "none";
}

// 발언자 팝업
const speakerPopup = $("#speaker-popup");
const speakerBadge = document.querySelector(".speaker-name-badge");

// 이름 입력 후 로비 버튼 노출
nameInput.addEventListener("input", () => {
  lobbyBtn.disabled = nameInput.value.trim().length <= 0;
});

// 로비 입장
lobbyBtn.addEventListener("click", (e) => {
  e.preventDefault();
  myName = nameInput.value.trim();
  if(!myName) return;
  socket.emit("join", {name: myName});
  introSection.style.display = "none";
  lobbySection.style.display = "block";
});

// 호스트 코드 제출
hostCodeBtn.addEventListener("click", () => {
  const code = hostCodeInput.value.trim();
  if (!code) return;
  socket.emit("become_host", {code});
});

// 게임 시작 (호스트 전용)
startBtn.addEventListener("click", () => {
  socket.emit("start_game");
});

// 버튼 바인딩
if(btnBeginRound){ btnBeginRound.onclick = ()=> socket.emit("begin_round"); }
if(btnNextSpeaker){ btnNextSpeaker.onclick = ()=> socket.emit("next_speaker"); }
if(btnStartDiscussion){ btnStartDiscussion.onclick = ()=> socket.emit("start_discussion"); }
if(btnStartVote){ btnStartVote.onclick = ()=> socket.emit("start_vote_manual"); }
if(btnStartSumReveal){ btnStartSumReveal.onclick = ()=> socket.emit("start_vote_sum_reveal"); }

// 투표
function sendVote(targetSid){
  socket.emit("vote", {target_sid: targetSid});
}

// 라이어 정답 제출
if(guessBtn){
  guessBtn.addEventListener("click", () => {
    const val = guessInput.value.trim();
    if(!val) return;
    socket.emit("liar_guess", {guess: val});
    guessInput.value = "";
  });
}

// 타이머 표시
function setTimer(sec){
  timerBox.textContent = sec ? `남은 시간: ${sec}초` : "";
}

// ---- 소켓 이벤트 처리 ----
socket.on("joined", (data) => {
  mySid = data.sid;
  myName = data.name;
  updateHostControls();
});

socket.on("player_list", (list) => {
  playerList.innerHTML = "";
  list.forEach(p => {
    const li = document.createElement("li");
    li.textContent = `${p.name} (${p.score}점)` + (p.is_host ? " 👑" : "");
    playerList.appendChild(li);
    if (p.sid === mySid) {
      isHost = p.is_host;
    }
  });
  startBtn.style.display = isHost ? "inline-flex" : "none";
  updateHostControls();
});

socket.on("host_ok", (res) => {
  alert(res.ok ? "호스트 권한이 부여되었습니다." : "코드가 올바르지 않습니다.");
  if(res.ok){ isHost = true; updateHostControls(); }
});

socket.on("error_msg", (data) => {
  alert(data.msg);
});

socket.on("game_start", () => {
  lobbySection.style.display = "none";
  gameSection.style.display = "block";
  scoreboardBox.style.display = "none";
  phaseTitle.textContent = "게임 시작! 라운드 준비 중...";
  roleBox.textContent = "내 역할: -";
  subjectBox.textContent = "주제: -";
  keywordBox.textContent = "제시어: -";
  orderBox.innerHTML = "-";
  voteBox.style.display = "none";
  guessBox.style.display = "none";
  setTimer("");
  updateHostControls();
});

socket.on("round_start", (data) => {
  phaseTitle.textContent = `라운드 ${data.round}/${data.total_rounds} 시작!`;
  subjectBox.textContent = `주제: ${data.subject}`;
  voteBox.style.display = "none";
  guessBox.style.display = "none";
  orderBox.innerHTML = "";
  setTimer("");
});

socket.on("role_assignment", (data) => {
  roleBox.textContent = `내 역할: ${data.role}`;
  subjectBox.textContent = `주제: ${data.subject}`;
  keywordBox.textContent = `제시어: ${data.keyword}`;
});

socket.on("hints_ready", (data)=>{
  phaseTitle.textContent = "힌트 발언 단계 (준비됨)";
  // 발언 순서 리스트 표시
  if(Array.isArray(data.order)){
    orderBox.innerHTML = data.order.map((o,i)=> `${i+1}. ${o.name}`).join("<br>");
  }
});

socket.on("hint_turn", (data) => {
  phaseTitle.innerHTML = `<span class="speaker-highlight">${data.speaker_name}</span> <span class="small">(${data.order_index+1}/${data.total})</span>`;

  // 발언자에게만 팝업 + 진동
  if(mySid === data.speaker_sid){
    if(speakerBadge){ speakerBadge.textContent = data.speaker_name; }
    if(speakerPopup){ speakerPopup.style.display = "flex"; }
    if(navigator.vibrate){ navigator.vibrate(300); }
    setTimeout(()=>{ if(speakerPopup) speakerPopup.style.display = "none"; }, 4000);
  }
});

socket.on("discussion_start", () => {
  phaseTitle.textContent = "자유 토론";
});

socket.on("vote_start", (data) => {
  phaseTitle.textContent = data.first ? "1차 공개 투표" : (data.round===2 ? "2차 공개 투표" : "공개 투표");
  voteBox.style.display = "block";
  voteList.innerHTML = "";
  data.candidates.forEach(c => {
    const btn = document.createElement("button");
    btn.className = "pill";
    btn.textContent = c.name;
    btn.onclick = () => {
      // UI 피드백
      $all("#vote-list .pill").forEach(b=> b.classList.remove("vote-selected","vote-confirmed"));
      btn.classList.add("vote-selected");
      // 전송
      socket.emit("vote", {target_sid: c.sid});
    };
    const li = document.createElement("li");
    li.appendChild(btn);
    voteList.appendChild(li);
  });
});

socket.on("vote_ok", () => {
  // 확정 피드백
  $all("#vote-list .pill.vote-selected").forEach(b=> b.classList.add("vote-confirmed"));
});

socket.on("vote_update", (data) => {
  // 필요 시 공개 현황 UI 갱신(1차/2차 분리 UI가 있으면 라운드에 맞게 표시)
});

socket.on("vote_tie", () => {
  alert("동률입니다. 동률자 발언을 진행합니다.");
});

socket.on("tie_speech_turn", (data) => {
  phaseTitle.textContent = `동률자 발언: ${data.name}`;
});

socket.on("liar_guess_start", (data) => {
  phaseTitle.textContent = `라이어 정답 기회 (지목됨: ${data.liar_name})`;
  guessBox.style.display = "none";
});

socket.on("liar_input_enable", () => {
  guessBox.style.display = "block";
});

socket.on("round_result", (data) => {
  phaseTitle.textContent = `라운드 결과: ${data.winner} 승`;
  keywordBox.textContent = `정답 제시어: ${data.keyword}`;
  voteBox.style.display = "none";
  guessBox.style.display = "none";
});

socket.on("next_round_soon", (data) => {
  phaseTitle.textContent = `잠시 후 라운드 ${data.next_round} 시작`;
  setTimer("");
});

socket.on("game_over", (data) => {
  phaseTitle.textContent = "게임 종료! 최종 점수";
  scoreboardList.innerHTML = "";
  data.scoreboard.forEach(s => {
    const li = document.createElement("li");
    li.textContent = `${s.name}: ${s.score}점`;
    li.setAttribute("data-name", s.name);
    li.setAttribute("data-score", s.score);
    scoreboardList.appendChild(li);
  });
  scoreboardBox.style.display = "block";
});

socket.on("timer_reset", (data)=> setTimer(data.seconds));
socket.on("timer_tick", (data) => setTimer(data.remaining));
socket.on("timer_done", () => {});
