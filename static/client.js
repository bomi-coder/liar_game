// =============================
// client.js
// =============================
const socket = io({transports: ["websocket"]});  // ✅ Render 배포 호환

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

// =============================
// 이벤트 바인딩
// =============================
if(joinBtn){
  joinBtn.onclick = ()=>{
    const name = $("#nameInput").value.trim();
    if(!name){ alert("이름을 입력하세요"); return; }
    socket.emit("join", {name});
  };
}

const startBtn = $("#startBtn");
if(startBtn){
  startBtn.onclick = ()=> socket.emit("start_game", {});
}

// =============================
// socket.io 이벤트
// =============================
socket.on("connect", ()=>{ mySid = socket.id; });

socket.on("player_list", list=>{
  const ul = document.createElement("ul");
  list.forEach(p=>{
    const li = document.createElement("li");
    li.textContent = p.name + (p.is_host ? " 👑":"");
    ul.appendChild(li);
    if(p.sid === mySid) isHost = p.is_host;
  });
  const wrap = $("#playerList");
  wrap.innerHTML = "";
  wrap.appendChild(ul);
  if(isHost) startBtn.style.display = ""; else startBtn.style.display = "none";
});

socket.on("phase", data=>{
  if(data.phase === "lobby"){ showSection("lobby"); }
  if(data.phase === "assign"){ showSection("game"); }
  if(data.phase === "game_end"){ alert("게임 종료!"); showSection("intro"); }
});

// ✅ 투표, 타이머 등 기존 로직 그대로 유지
socket.on("timer_update", sec=>{
  const el = $("#timer");
  if(el) el.textContent = sec;
});

socket.on("timer_done", ()=>{
  const el = $("#timer");
  if(el) el.textContent = "⏰";
});
