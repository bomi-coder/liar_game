(function(){
  const socket = io();

  // util
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));
  const meName = (window.APP && window.APP.name) || "";

  let isHost = false;
  let roundNum = 0;
  let currentPhase = "-";
  let order = [];
  let hintIndex = -1;

  // register
  socket.on("connect", ()=>{
    if(meName){
      socket.emit("register", {name: meName});
    }
  });

  // index: nothing else

  // LOBBY
  const claimBtn = $("#claim-host-btn");
  if(claimBtn){
    const modal = $("#host-modal");
    const codeInput = $("#host-code");
    const cancelBtn = $("#host-cancel");
    const submitBtn = $("#host-submit");
    const startBtn = $("#start-btn");
    const hostInfo = $("#host-info");
    const playerList = $("#player-list");

    claimBtn.addEventListener("click", ()=>{
      modal.classList.remove("hidden");
      codeInput.value = "";
      codeInput.focus();
    });
    cancelBtn.addEventListener("click", ()=> modal.classList.add("hidden"));
    submitBtn.addEventListener("click", ()=> {
      socket.emit("claim_host", {code: codeInput.value});
    });

    startBtn.addEventListener("click", ()=> socket.emit("start_game"));

    socket.on("host_granted", (resp)=>{
      if(resp.ok){
        isHost = true;
        document.body.classList.add("host-enabled");
        modal.classList.add("hidden");
        hostInfo.innerText = "호스트: " + (resp.host_name || "나");
        startBtn.disabled = false;
        toast("🎉 호스트가 되었습니다!");
      }else{
        toast("❌ " + (resp.message || "호스트 실패"));
      }
    });

    socket.on("lobby_state", (state)=>{
      playerList.innerHTML = "";
      (state.players || []).forEach(p=>{
        const li = document.createElement("li");
        li.textContent = p.name + (p.is_host ? " 👑" : "");
        playerList.appendChild(li);
        if(p.name === meName && p.is_host){
          isHost = true;
          document.body.classList.add("host-enabled");
          startBtn.disabled = false;
        }
      });
      hostInfo.innerText = "호스트: " + (state.host_name || "대기중…");
    });

    socket.on("game_started", ()=>{
      window.location.href = "/game";
    });
  }

  // GAME
  const roleEl = $("#role");
  const topicEl = $("#topic");
  const keyEl = $("#keyword");
  const roundEl = $("#round");
  const phaseEl = $("#phase");
  const orderList = $("#order-list");
  const currentSpeaker = $("#current-speaker strong");
  const timerEl = $("#timer");
  const voteGrid = $("#vote-grid");
  const voteLog = $("#vote-log");
  const pop = $("#pop");

  const btnHint1 = $("#btn-hint1");
  const btnDiscuss = $("#btn-discuss");
  const btnVote1 = $("#btn-vote1");
  const btnHint2 = $("#btn-hint2");
  const btnVote2 = $("#btn-vote2");
  const btnClose1 = $("#btn-close1");
  const btnClose2 = $("#btn-close2");
  const btnNextTurn = $("#btn-next-turn");
  const btnNextRound = $("#btn-next-round");
  const scoreboard = $("#scoreboard");
  let timerId=null, remain=0;

  function setTimer(sec){
    clearInterval(timerId);
    remain = sec;
    renderTimer();
    timerId = setInterval(()=>{
      remain -= 1;
      renderTimer();
      if(remain <= 0){
        clearInterval(timerId);
        if(isHost && currentPhase.startsWith("hint")){
          // auto next speaker
          socket.emit("hint_next", {index: ++hintIndex});
        }
      }
    }, 1000);
  }
  function renderTimer(){
    const m = String(Math.floor(Math.max(remain,0)/60)).padStart(2,"0");
    const s = String(Math.max(remain,0)%60).padStart(2,"0");
    if(timerEl) timerEl.textContent = `${m}:${s}`;
  }
  function toast(msg){
    if(!pop) return;
    pop.innerText = msg;
    pop.classList.remove("hidden");
    setTimeout(()=>pop.classList.add("hidden"), 1600);
  }

  socket.on("role_info", (info)=>{
    if(roleEl) roleEl.textContent = info.role;
    if(topicEl) topicEl.textContent = info.topic || "-";
    if(keyEl) keyEl.textContent = info.keyword || "???";
  });

  socket.on("game_started", (g)=>{
    roundNum = g.round;
    if(roundEl) roundEl.textContent = String(roundNum);
  });

  socket.on("hint_order", (data)=>{
    currentPhase = data.phase;
    if(phaseEl) phaseEl.textContent = phaseKo(currentPhase);
    order = data.order || [];
    orderList.innerHTML = "";
    order.forEach((p, idx)=>{
      const li = document.createElement("li");
      li.textContent = `${idx+1}. ${p.name}`;
      orderList.appendChild(li);
    });
    hintIndex = -1;
    if(isHost){
      // start first speaker immediately
      socket.emit("hint_next", {index: 0});
    }
  });

  socket.on("hint_turn", (d)=>{
    currentPhase = currentPhase; // unchanged
    hintIndex = d.index;
    if(currentSpeaker) currentSpeaker.textContent = d.name || "-";
    setTimer(d.seconds || 15);
  });

  socket.on("start_timer", (d)=>{
    currentPhase = "discussion";
    if(phaseEl) phaseEl.textContent = phaseKo(currentPhase) + ` (${d.label || ""})`;
    setTimer(d.seconds || 120);
  });

  socket.on("open_vote", (d)=>{
    currentPhase = d.phase;
    if(phaseEl) phaseEl.textContent = phaseKo(currentPhase);
    voteGrid.innerHTML = "";
    voteLog.innerHTML = "";
    (d.players || []).forEach(p=>{
      if(p.name === meName) return; // 자기 자신 투표 방지
      const btn = document.createElement("button");
      btn.className = "vote-btn";
      btn.textContent = `🗳️ ${p.name}`;
      btn.addEventListener("click", ()=>{
        // disable after vote
        $$(".vote-btn").forEach(b=>b.disabled=true);
        btn.classList.add("voted");
        socket.emit("cast_vote", {target_sid: p.sid});
      });
      voteGrid.appendChild(btn);
    });
  });

  socket.on("vote_update", (d)=>{
    const li = document.createElement("li");
    li.textContent = `${d.voter} ➜ ${d.target}`;
    voteLog.appendChild(li);
  });

  socket.on("vote_closed", (d)=>{
    const li = document.createElement("li");
    li.textContent = `✅ ${d.phase} 마감 (최다: ${d.top.join(", ") || "없음"} / 표수: ${d.max || 0})`;
    voteLog.appendChild(li);
  });

  socket.on("liar_selected", (d)=>{
    toast(`😈 라이어(${d.liar_name})가 지목됐어요! 30초 안에 정답을 맞추세요.`);
    if(roleEl && roleEl.textContent === "라이어"){
      const guess = prompt(`주제: ${d.category}\n정답(제시어)을 입력하세요 (30초 제한):`);
      if(guess){
        socket.emit("liar_guess", {guess});
      }
    }
  });

  socket.on("round_result", (res)=>{
    const li = document.createElement("li");
    const w = (res.winner === "citizens") ? "🎉 시민 승리!" : "😎 라이어팀 승리!";
    li.textContent = `${w} (정답: ${res.secret_word} / 주제: ${res.category})`;
    scoreboard.appendChild(li);
    toast("라운드 종료! 점수가 반영되었어요.");
  });

  socket.on("final_scores", (data)=>{
    scoreboard.innerHTML = "";
    data.scores.forEach((s, idx)=>{
      const li = document.createElement("li");
      li.textContent = `#${idx+1} ${s.name} — ${s.score}점`;
      scoreboard.appendChild(li);
    });
    toast("🏁 게임 종료! 최종 점수 공개");
  });

  // Host-only buttons
  if(btnHint1){ btnHint1.addEventListener("click", ()=> socket.emit("start_game")); }
  if(btnDiscuss){ btnDiscuss.addEventListener("click", ()=> socket.emit("start_discussion")); }
  if(btnVote1){ btnVote1.addEventListener("click", ()=> socket.emit("start_vote1")); }
  if(btnHint2){ btnHint2.addEventListener("click", ()=> socket.emit("start_hint2")); }
  if(btnVote2){ btnVote2.addEventListener("click", ()=> socket.emit("start_vote2")); }
  if(btnClose1){ btnClose1.addEventListener("click", ()=> socket.emit("close_vote1")); }
  if(btnClose2){ btnClose2.addEventListener("click", ()=> socket.emit("close_vote2")); }
  if(btnNextTurn){ btnNextTurn.addEventListener("click", ()=> socket.emit("hint_next", {index: (hintIndex<0?0:hintIndex+1)})); }
  if(btnNextRound){ btnNextRound.addEventListener("click", ()=> socket.emit("next_round")); }

  function phaseKo(p){
    switch(p){
      case "hint1": return "1차 힌트";
      case "discussion": return "전체 토론";
      case "vote1": return "1차 투표";
      case "hint2": return "2차 힌트";
      case "vote2": return "2차 투표";
      case "liar_guess": return "라이어 정답 맞추기";
      case "results": return "라운드 결과";
      case "summary": return "최종 결과";
      default: return p || "-";
    }
  }
})();
