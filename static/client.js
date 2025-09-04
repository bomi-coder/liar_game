// ===== socket 연결 =====
const socket = io();

// ===== DOM =====
const $intro  = document.getElementById('intro');
const $lobby  = document.getElementById('lobby');
const $game   = document.getElementById('game');

const $joinForm   = document.getElementById('joinForm');
const $nameInput  = document.getElementById('nameInput');
const $joinBtn    = document.getElementById('joinBtn');

const $playerList = document.getElementById('playerList');

const $hostCodeInput = document.getElementById('hostCodeInput');
const $hostBtn       = document.getElementById('hostBtn');
const $startBtn      = document.getElementById('startBtn');

const $hostControls  = document.getElementById('hostControls');

const $roundInfo = document.getElementById('roundInfo');
const $roleInfo  = document.getElementById('roleInfo');

// 호스트 컨트롤 버튼들 (있으면 바인딩)
const $btnStartRound     = document.getElementById('btnStartRound');
const $btnNextSpeaker    = document.getElementById('btnNextSpeaker');
const $btnStartDiscussion= document.getElementById('btnStartDiscussion');
const $btnStartVote      = document.getElementById('btnStartVote');
const $btnEndVote        = document.getElementById('btnEndVote');
const $btnShowResults    = document.getElementById('btnShowResults');
const $btnResetGame      = document.getElementById('btnResetGame');

// ===== 상태 =====
let mySid = null;
let isHost = false;

// ===== 유틸 =====
function show(el){ if (el) el.style.display = ''; }
function hide(el){ if (el) el.style.display = 'none'; }
function inLobbyView(){ hide($intro); show($lobby); hide($game); }
function inGameView(){  hide($intro); hide($lobby); show($game); }

function ensureName(){
  const name = ($nameInput.value || '').trim();
  if (!name){
    alert("닉네임을 입력해 주세요.");
    $nameInput.focus();
    return null;
  }
  return name;
}

// ===== 이벤트 바인딩 =====

// (A) 폼 제출로 로비 입장
if ($joinForm){
  $joinForm.addEventListener('submit', (e)=>{
    e.preventDefault();
    const name = ensureName();
    if (!name) return;
    socket.emit('join', { name });
  });
}
// (B) 클릭으로도 동작 (모바일 보조)
if ($joinBtn){
  $joinBtn.addEventListener('click', ()=>{
    const name = ensureName();
    if (!name) return;
    socket.emit('join', { name });
  });
}

// 호스트 권한 얻기
if ($hostBtn){
  $hostBtn.addEventListener('click', ()=>{
    if (!mySid){
      // 서버에서 joined 안된 상태
      alert("먼저 이름을 입력하고 '게임 로비 입장'으로 접속해 주세요.");
      return;
    }
    const code = ($hostCodeInput.value || '').trim();
    if (!code){
      alert('호스트 코드를 입력해 주세요.');
      return;
    }
    socket.emit('become_host', { code });
  });
}

// 호스트만 보이는 컨트롤(서버 쪽 핸들러가 있는 것만 전송)
if ($btnStartRound){
  $btnStartRound.addEventListener('click', ()=> socket.emit('begin_round'));
}
if ($btnNextSpeaker){
  $btnNextSpeaker.addEventListener('click', ()=> socket.emit('next_speaker')); // 서버에 이 이벤트가 없으면 추가 필요
}
if ($btnStartDiscussion){
  $btnStartDiscussion.addEventListener('click', ()=> socket.emit('start_discussion')); // 서버에 추가 필요
}
if ($btnStartVote){
  $btnStartVote.addEventListener('click', ()=> socket.emit('start_vote')); // 서버에 추가 필요
}
if ($btnEndVote){
  $btnEndVote.addEventListener('click', ()=> socket.emit('end_vote')); // 서버에 추가 필요
}
if ($btnShowResults){
  $btnShowResults.addEventListener('click', ()=> socket.emit('start_vote_sum_reveal'));
}
if ($btnResetGame){
  $btnResetGame.addEventListener('click', ()=> socket.emit('reset_game')); // 서버에 추가 필요
}

// ===== 소켓 수신 =====

// 로비 입장 성공
socket.on('joined', (data)=>{
  mySid = data.sid;
  inLobbyView();
});

// 로비 플레이어 목록 갱신
socket.on('player_list', (list)=>{
  // 내가 호스트인지 정보를 못 받는다면 서버가 host_ok를 따로 보냄
  $playerList.innerHTML = '';
  (list || []).forEach(p=>{
    const li = document.createElement('li');
    li.textContent = `${p.name}${p.is_host ? ' (HOST)' : ''} — ${p.score ?? 0}점`;
    $playerList.appendChild(li);
    // 내 row 보고 호스트 여부 동기화(보조)
    if (mySid && p.sid === mySid){
      isHost = !!p.is_host;
    }
  });
  // 호스트 컨트롤 표시 여부
  if ($hostControls) (isHost ? show($hostControls) : hide($hostControls));
  if ($startBtn)      (isHost ? $startBtn.classList.remove('hide') : $startBtn.classList.add('hide'));
});

// 호스트 인증 결과
socket.on('host_ok', (data)=>{
  isHost = !!(data && data.ok);
  if (isHost){
    alert('호스트 권한이 부여되었습니다.');
  }else{
    alert('호스트 코드가 올바르지 않습니다.');
  }
  if ($hostControls) (isHost ? show($hostControls) : hide($hostControls));
  if ($startBtn)      (isHost ? $startBtn.classList.remove('hide') : $startBtn.classList.add('hide'));
});

// 게임 시작(서버 브로드캐스트)
socket.on('game_start', (payload)=>{
  inGameView();
  if ($roundInfo) $roundInfo.textContent = 'Round -';
  if ($roleInfo)  $roleInfo.textContent  = '내 역할/주제/제시어';
});

// 라운드 시작(서버 브로드캐스트)
socket.on('round_start', (data)=>{
  inGameView();
  if ($roundInfo){
    $roundInfo.textContent = `Round ${data.round} / ${data.total_rounds} — 주제: ${data.subject}`;
  }
});

// 개인별 역할/제시어 (유니캐스트)
socket.on('role_assignment', (data)=>{
  // data: {role, subject, keyword}
  if ($roleInfo){
    $roleInfo.textContent = `역할: ${data.role} | 주제: ${data.subject} | 제시어: ${data.keyword}`;
  }
});

// 에러 메시지
socket.on('error_msg', (data)=>{
  alert(data?.msg || '오류가 발생했어요.');
});
