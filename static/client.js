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

// --- 호스트 컨트롤 ---
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

if(btnBeginRound){ btnBeginRound.onclick = ()=> socket.emit("begin_round"); }
if(btnNextSpeaker){ btnNextSpeaker.onclick = ()=> socket.emit("next_speaker"); }
if(btnStartDiscussion){ btnStartDiscussion.onclick = ()=> socket.emit("start_discussion"); }
if(btnStartVote){ btnStartVote.onclick = ()=> socket.emit("start_vote_manual"); }
if(btnStartSumReveal){ btnStartSumReveal.onclick = ()=> socket.emit("start_vote_sum_reveal"); }


// 초기가리기
lobbySection.style.display = "none";
gameSection.style.display = "none";

// 이름 입력 후 로비 버튼 노출
nameInput.addEventListener("input", () => {
  if (nameInput.value.trim().length > 0) {
    lobbyBtn.disabled = false;
  } else {
    lobbyBtn.disabled = true;
  }
});

// 로비 입장
lobbyBtn.addEventListener("click", (e) => {
  e.preventDefault();
  myName = nameInput.value.trim();
  socket.emit("join", {name: myName});
  $("#intro").style.display = "none";
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

// 투표
function sendVote(targetSid){
  socket.emit("vote", {target_sid: targetSid});
}

// 라이어 정답 제출
guessBtn.addEventListener("click", () => {
  const val = guessInput.value.trim();
  if(!val) return;
  socket.emit("liar_guess", {guess: val});
  guessInput.value = "";
});

// 타이머 표시
function setTimer(sec){
  timerBox.textContent = sec + "초";
}

// scoreboard CSV 다운로드
csvBtn.addEventListener("click", () => {
  let rows = [["이름","점수"]];
  $all("#scoreboard-list li").forEach(li => {
    const name = li.getAttribute("data-name");
    const score = li.getAttribute("data-score");
    rows.push([name, score]);
  });
  const csv = rows.map(r => r.join(",")).join("\n");
  const blob = new Blob([csv], {type: "text/csv;charset=utf-8;"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "liar_game_scoreboard.csv";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
});

// ---- 소켓 이벤트 처리 ----
socket.on("joined", (data) => {
  mySid = data.sid;
  myName = data.name;
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
  if(res.ok){
    alert("호스트 권한이 부여되었습니다.");
  } else {
    alert("코드가 올바르지 않습니다.");
  }
});

socket.on("error_msg", (data) => {
  alert(data.msg);
});

socket.on("game_start", (data) => {
  lobbySection.style.display = "none";
  gameSection.style.display = "block";
  scoreboardBox.style.display = "none";
  phaseTitle.textContent = "게임 시작! 라운드 준비 중...";
  roleBox.textContent = "";
  subjectBox.textContent = "";
  keywordBox.textContent = "";
  orderBox.innerHTML = "";
  voteBox.style.display = "none";
  guessBox.style.display = "none";
  setTimer("");
});

socket.on("round_start", (data) => {
  phaseTitle.textContent = `라운드 ${data.round}/${data.total_rounds} 시작!`;
  subjectBox.textContent = `주제: ${data.subject}`;
  // keywordBox는 여기서 건드리지 않음! (role_assignment에서 최종 세팅)
  voteBox.style.display = "none";
  guessBox.style.display = "none";
  orderBox.innerHTML = "";
});

socket.on("role_assignment", (data) => {
  roleBox.textContent = `내 역할: ${data.role}`;
  subjectBox.textContent = `주제: ${data.subject}`;
  keywordBox.textContent = `제시어: ${data.keyword}`;
});

socket.on("hint_turn", (data) => {
  phaseTitle.textContent = "힌트 발언 단계";
  orderBox.innerHTML = `발언자: ${data.speaker_name} (${data.order_index+1}/${data.total})`;
});

socket.on("discussion_start", (data) => {
  phaseTitle.textContent = "자유 토론";
});

socket.on("vote_start", (data) => {
  phaseTitle.textContent = data.first ? "1차 공개 투표" : "재투표";
  voteBox.style.display = "block";
  voteList.innerHTML = "";
  data.candidates.forEach(c => {
    const btn = document.createElement("button");
    btn.className = "pill";
    btn.textContent = c.name;
    btn.onclick = () => sendVote(c.sid);
    const li = document.createElement("li");
    li.appendChild(btn);
    voteList.appendChild(li);
  });
});

socket.on("vote_tie", (data) => {
  alert("동률입니다. 동률자 발언을 진행합니다.");
});

socket.on("tie_speech_turn", (data) => {
  phaseTitle.textContent = `동률자 발언: ${data.name}`;
});

socket.on("liar_guess_start", (data) => {
  phaseTitle.textContent = `라이어 정답 기회 (지목됨: ${data.liar_name})`;
  guessBox.style.display = "none"; // 기본은 숨김, 라이어에게만 enable 이벤트
});

socket.on("liar_input_enable", () => {
  // 라이어에게만 입력창 표시
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

socket.on("timer_tick", (data) => {
  setTimer(data.remaining);
});

socket.on("timer_done", () => {
  // no-op
});
const btnStartSumReveal = $("#btn-start-sum-reveal");
if(btnStartSumReveal){ btnStartSumReveal.onclick = ()=> socket.emit("start_vote_sum_reveal"); }

socket.on("timer_reset", (data)=>{
  if(timerBox){
    timerBox.classList.remove("timer-flash");
    void timerBox.offsetWidth;
    timerBox.classList.add("timer-flash");
    timerBox.textContent = `남은 시간: ${data.seconds}초`;
  }
});

socket.on("vote_result_sum", (data)=>{
  if(voteSumResultBox && voteSumResultText){
    voteSumResultText.textContent = `최다 득표: ${data.accused.name} (역할: ${data.role})`;
    voteSumResultBox.style.display = "block";
  }
});

socket.on("vote_ok", (data)=>{
  // 투표 확정 시 버튼 강조
  $all("#vote-box button.vote-selected").forEach(b=>{
    b.classList.add("vote-confirmed");
  });
});
