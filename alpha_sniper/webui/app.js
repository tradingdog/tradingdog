const $ = (id) => document.getElementById(id);

function money(n) {
  if (n == null || Number.isNaN(n)) return "—";
  const abs = Math.abs(n);
  const s = abs >= 1000 ? abs.toLocaleString("en-US", { maximumFractionDigits: 1 }) : abs.toFixed(2);
  return (n < 0 ? "−" : "") + s;
}

function pct(n) {
  if (n == null) return "—";
  return `${(n * 100).toFixed(1)}%`;
}

function clsRet(n) {
  if (n > 0.002) return "up";
  if (n < -0.002) return "down";
  return "";
}

function when(s, day, ts) {
  if (s && s.clock_mode === "unix" && ts && ts > 1e9) {
    return new Date(ts * 1000).toLocaleString("zh-CN", {
      hour12: false,
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }
  if (day == null) return "—";
  return `D${Number(day).toFixed(2)}`;
}

function render(s) {
  window.__SNAP = s;
  const pill = $("statePill");
  pill.textContent = s.state_zh;
  pill.className = "pill " + ({ SQUAT: "squat", ARMED: "armed", IN_THESIS: "fire" }[s.state] || "squat");
  if (s.clock_mode === "unix" && s.now > 1e9) {
    $("clock").textContent = new Date(s.now * 1000).toLocaleString("zh-CN", { hour12: false });
  } else {
    $("clock").textContent = `回放第 ${s.day.toFixed(2)} 天 / ${s.horizon_days} 天`;
  }
  $("narration").textContent = s.boot_error || s.narration || "等待行情";
  if (s.mode === "binance_sim") {
    $("modePill").textContent = s.allow_new ? "真实行情 · 模拟资金 · 允许开仓" : "真实行情 · 模拟资金 · 已暂停开仓";
  } else {
    $("modePill").textContent = s.finished ? "本地回放 · 已结束" : s.running ? "本地回放 · 进行中" : "本地回放 · 已暂停";
  }
  const feed = s.feed || {};
  const fp = $("feedPill");
  if (fp) {
    fp.textContent = feed.ok ? `币安已连接 ${feed.latency_ms || 0}ms` : (s.ready === false ? "正在拉行情" : "行情断开");
    fp.className = "pill " + (feed.ok ? "squat" : "quiet");
  }
  const fl = $("feedline");
  if (fl) {
    const pollAt = (s.last_poll || feed.last_poll)
      ? ` · 上次刷新 ${new Date((s.last_poll || feed.last_poll) * 1000).toLocaleTimeString("zh-CN", { hour12: false })}`
      : "";
    fl.innerHTML = s.mode === "binance_sim"
      ? `监控 ${feed.symbols || 0} 个 USDT 交易对 · Alpha ${feed.alpha || 0} 个 · ${feed.key_note || ""}${pollAt}${feed.last_error ? " · " + feed.last_error : ""}`
      : "当前是本地回放数据，不是币安实时行情。";
  }
  const mv = $("movers");
  if (mv) {
    const quotes = (s.quotes || []).slice(0, 8);
    mv.innerHTML = quotes.length
      ? quotes.map((q) => `<div class="mover"><div class="sym">${q.symbol}${q.is_alpha ? " · Alpha" : ""}</div><div class="chg ret ${clsRet(q.change24h)}">${pct(q.change24h)}</div></div>`).join("")
      : "";
  }

  document.querySelectorAll("#speeds button").forEach((b) => {
    b.classList.toggle("on", Number(b.dataset.speed) === s.speed);
  });

  const a = s.account;
  $("metrics").innerHTML = [
    metric("权益", money(a.equity), `起始 ${money(a.starting)} · ${a.multiple.toFixed(2)}x`, clsRet(a.equity - a.starting)),
    metric("可用资金", money(a.cash), "模拟账户里还能开仓的钱"),
    metric("锁定利润", money(a.vault), "翻倍后锁住，不再拿去开新仓"),
    metric("浮动盈亏", money(a.unrealized), "未平仓的模拟盈亏", clsRet(a.unrealized)),
    metric("距 100 倍", pct(a.progress_log), `线性 ${pct(a.progress_linear)} · 目标 ${money(a.target)}`),
  ].join("");

  $("stones").innerHTML = a.stepping_stones
    .map((st) => `<span class="stone ${st.hit ? "hit" : ""}">${st.label}</span>`)
    .join("<span class='stone'>→</span>");

  $("theses").innerHTML = s.theses.length
    ? s.theses.map(thesisCard).join("")
    : `<div class="empty"><strong>◎ 空仓</strong>现在没有模拟持仓，这是正常的。<br/>下面列表里出现横盘缩量、再凑齐三类信号，才会开仓。</div>`;

  $("gates").innerHTML = s.risk.gates
    .map(
      (g) => `<div class="gate"><span><i class="dot ${g.ok ? "ok" : "bad"}"></i>${g.label}</span><span class="mute">${g.detail}</span></div>`
    )
    .join("");
  $("skips").innerHTML = s.skips.length
    ? "<div>最近没开仓的原因</div>" + s.skips.map((x) => `<div>${x.why_zh} · ${x.count} 次</div>`).join("")
    : "<div>还没有过滤记录。安静说明没乱开仓。</div>";

  $("hunt").innerHTML = s.hunt
    .map((r) => {
      const lamps = r.family_lamps
        .map((l) => `<span class="lamp ${l.on ? "on" : ""}" title="${l.zh}">${l.zh.slice(0, 1)}</span>`)
        .join("");
      const q = (s.quotes || []).find((x) => x.symbol === r.symbol);
      const chg = q ? q.change24h : r.moved;
      return `<tr>
        <td><strong>${r.symbol}</strong><div class="mute">${r.is_alpha ? "Alpha" : r.tier} · ${r.venue_zh}</div></td>
        <td class="mono ret ${clsRet(chg || 0)}">${chg == null ? "—" : pct(chg)}</td>
        <td class="mono">${r.mark == null ? "—" : Number(r.mark).toPrecision(6)}</td>
        <td class="mono">${r.coiled.toFixed(2)}${r.armed ? " · 已盯" : ""}</td>
        <td class="mono">${r.silence.toFixed(2)}</td>
        <td><div class="lamps">${lamps}</div></td>
        <td>
          <div class="bars">
            <div class="bar" title="可能性"><i style="width:${pct(r.possibility)}"></i></div>
            <div class="bar crowd" title="拥挤"><i style="width:${pct(r.crowding)}"></i></div>
            <div class="bar exit" title="退出"><i style="width:${pct(r.exit_liquidity)}"></i></div>
          </div>
        </td>
        <td>${r.wait}</td>
        <td><button type="button" class="tiny" data-block="${r.symbol}">${(s.blocked || []).includes(r.symbol) ? "取消拉黑" : "拉黑"}</button></td>
      </tr>`;
    })
    .join("");

  $("script").innerHTML = s.script
    .map(
      (ev) => `<li class="${ev.status}"><span class="d">${ev.symbol || "公告"}</span><div><strong>${ev.title}</strong><div class="mute">${ev.hint || ""}</div></div></li>`
    )
    .join("");

  const journal = [...s.journal].reverse();
  $("journal").innerHTML = journal.length
    ? journal
        .map((e) => `<li><span class="kind">${e.kind_zh}</span><span class="mono">${when(s, e.day, e.ts)}</span> ${e.symbol}<div class="mute">${e.detail}</div></li>`)
        .join("")
    : "<li class='mute'>还没有开平仓。空仓时这里本来就该安静。</li>";

  const misses = [...s.near_misses].reverse();
  $("misses").innerHTML = misses.length
    ? misses
        .map((m) => `<li><span class="mono">${when(s, m.day, m.ts)}</span> ${m.symbol} ${m.side_zh}<div class="mute">${(m.families_zh || []).join(" · ")} — ${m.reason}</div></li>`)
        .join("")
    : "<li class='mute'>还没有被挡下的信号。说明真正齐套的机会很少。</li>";

  $("closed").innerHTML = s.closed.length
    ? s.closed
        .slice()
        .reverse()
        .map(
          (t) => `<div class="closed-row">
            <strong>${t.symbol}</strong>
            <span class="tag ${t.side}">${t.side_zh}</span>
            <span class="mono ret ${clsRet(t.ret)}">${pct(t.ret)}</span>
            <span>${t.exit_reason || "—"} · ${(t.families_zh || []).join("、")}</span>
            <span class="mono">${money(t.pnl)}</span>
          </div>`
        )
        .join("")
    : `<div class="empty">还没有平过仓。</div>`;

  drawEquity(s.equity_curve, a.starting, a.target);
}

function metric(k, v, hint, extra) {
  return `<article class="metric"><div class="k">${k}</div><div class="v ${extra || ""}">${v}</div><div class="hint">${hint}</div></article>`;
}

function thesisCard(t) {
  return `<article class="card">
    <div class="row">
      <h3>${t.symbol} <span class="tag ${t.side}">${t.side_zh}</span> <span class="tag">${t.venue_zh}</span></h3>
      <div class="mono ret ${clsRet(t.ret)}">${pct(t.ret)} · ${money(t.pnl)}</div>
    </div>
    <p class="plain">${t.plain}</p>
    <div class="mute" style="margin-top:10px">
      入场 ${t.entry.toPrecision(4)} · 现价 ${Number(t.mark).toPrecision(4)} · 止损 ${t.invalidation.toPrecision(4)}
      · 剩余仓 ${(t.remaining_frac * 100).toFixed(0)}%
      · 还剩 ${t.hours_left.toFixed(1)} 小时
      ${t.scaled_40 ? " · 已减 40%" : ""}
      ${t.scaled_100 ? " · 已减 100% 档" : ""}
    </div>
    <div class="actions">
      <button type="button" class="tiny danger" data-close="${t.id}">平掉这一笔</button>
    </div>
  </article>`;
}

function drawEquity(curve, start, target) {
  const c = $("equity");
  const ctx = c.getContext("2d");
  const w = c.width;
  const h = c.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#16140f";
  ctx.fillRect(0, 0, w, h);
  if (!curve.length) return;
  const xs = curve.map((p) => p.t);
  const ys = curve.map((p) => p.e);
  const minX = xs[0];
  const maxX = Math.max(xs[xs.length - 1], minX + 0.2);
  const minY = Math.min(start * 0.85, ...ys);
  const maxY = Math.max(start * 1.15, ...ys);
  const x = (t) => ((t - minX) / (maxX - minX)) * (w - 24) + 12;
  const y = (e) => h - 16 - ((e - minY) / (maxY - minY)) * (h - 32);

  ctx.strokeStyle = "#322e26";
  ctx.beginPath();
  ctx.moveTo(12, y(start));
  ctx.lineTo(w - 12, y(start));
  ctx.stroke();

  ctx.strokeStyle = "#d4a05a";
  ctx.lineWidth = 1.6;
  ctx.beginPath();
  curve.forEach((p, i) => {
    const X = x(p.t);
    const Y = y(p.e);
    if (i === 0) ctx.moveTo(X, Y);
    else ctx.lineTo(X, Y);
  });
  ctx.stroke();
  ctx.fillStyle = "#9a927f";
  ctx.font = "12px IBM Plex Mono";
  ctx.fillText(`起始 ${start}`, 14, y(start) - 6);
}

const replay = {
  frames: [],
  i: 0,
  running: false,
  speed: 8,
  timer: null,
};

function hydrate(frame, i) {
  const curve = replay.frames.slice(0, i + 1).map((f) => f.eq || { t: f.day, e: f.account.equity });
  return {
    ...frame,
    running: replay.running,
    finished: i >= replay.frames.length - 1,
    speed: replay.speed,
    equity_curve: curve,
    pulses: frame.pulses || [],
  };
}

function showReplay(i) {
  replay.i = Math.max(0, Math.min(replay.frames.length - 1, i));
  const frame = replay.frames[replay.i];
  if (!frame) return;
  render(hydrate(frame, replay.i));
  $("modePill").textContent = replay.running
    ? "浏览器重放 · 进行中（无需本机服务）"
    : replay.i >= replay.frames.length - 1
      ? "浏览器重放 · 已跑完"
      : "浏览器重放 · 任意浏览器可打开";
}

function replayTick() {
  if (!replay.running) return;
  const step = replay.speed >= 32 ? 2 : 1;
  if (replay.i >= replay.frames.length - 1) {
    replay.running = false;
    showReplay(replay.i);
    return;
  }
  showReplay(replay.i + step);
}

function replayNextShot() {
  for (let i = replay.i + 1; i < replay.frames.length; i += 1) {
    const prev = replay.frames[i - 1];
    const cur = replay.frames[i];
    const prevN = (prev.journal || []).length;
    const curN = (cur.journal || []).length;
    const fired = (cur.theses || []).length > (prev.theses || []).length;
    const closed = (cur.closed || []).length > (prev.closed || []).length;
    if (fired || closed || curN > prevN) {
      replay.running = false;
      showReplay(i);
      return;
    }
  }
  replay.running = false;
  showReplay(replay.frames.length - 1);
}

function replayControl(action, extra) {
  if (action === "start") replay.running = true;
  if (action === "pause") replay.running = false;
  if (action === "reset") {
    replay.running = false;
    showReplay(0);
    return;
  }
  if (action === "next") {
    replayNextShot();
    return;
  }
  if (action === "speed") replay.speed = extra.speed;
  showReplay(replay.i);
}

async function send(action, extra) {
  if (action === "flatten" && !window.confirm("确认把所有模拟持仓按现价平掉？资金仍是模拟的。")) return;
  if (action === "reset" && !window.confirm("确认把模拟资金重置回 1000，并重新拉币安行情？")) return;
  if (action === "close" && !window.confirm("确认平掉这一笔模拟持仓？")) return;
  if (replay.frames.length) {
    replayControl(action, extra || {});
    return;
  }
  const res = await fetch("/api/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, ...extra }),
  });
  if (!res.ok) return;
  render(await res.json());
}

$("controls").addEventListener("click", (ev) => {
  const btn = ev.target.closest("button");
  if (!btn) return;
  if (btn.dataset.act) send(btn.dataset.act);
  if (btn.dataset.speed) send("speed", { speed: Number(btn.dataset.speed) });
});
document.body.addEventListener("click", (ev) => {
  const closeBtn = ev.target.closest("button[data-close]");
  if (closeBtn) {
    send("close", { thesis_id: closeBtn.dataset.close });
    return;
  }
  const btn = ev.target.closest("button[data-block]");
  if (!btn) return;
  const symbol = btn.dataset.block;
  const blocked = (window.__SNAP && window.__SNAP.blocked) || [];
  send(blocked.includes(symbol) ? "unblock" : "block", { symbol });
});

function connectLive() {
  if (window.EventSource) {
    const es = new EventSource("/api/stream");
    es.onmessage = (ev) => {
      try {
        render(JSON.parse(ev.data));
      } catch (_) {}
    };
    es.onerror = () => {
      es.close();
      setTimeout(poll, 800);
    };
    return;
  }
  poll();
}

async function poll() {
  try {
    const res = await fetch("/api/state");
    if (res.ok) render(await res.json());
  } catch (_) {}
  setTimeout(poll, 700);
}

function loadEmbeddedReplay() {
  const node = document.getElementById("replay-data");
  if (!node || !node.textContent.trim()) return null;
  try {
    return JSON.parse(node.textContent);
  } catch (_) {
    return null;
  }
}

async function startReplay() {
  let data = loadEmbeddedReplay();
  if (!data) {
    const base = document.querySelector('meta[name="asset-base"]');
    const prefix = base ? base.getAttribute("content") : "";
    const res = await fetch(`${prefix}replay.json`, { cache: "no-store" });
    if (!res.ok) {
      $("narration").textContent = "打不开观察台数据。请用最新的预览链接，不要打开 jsDelivr 或 127.0.0.1。";
      return;
    }
    data = await res.json();
  }
  replay.frames = data.frames || [];
  showReplay(0);
  if (replay.timer) clearInterval(replay.timer);
  replay.timer = setInterval(replayTick, 420);
}

async function boot() {
  try {
    const res = await fetch("/api/state", { cache: "no-store" });
    const type = res.headers.get("content-type") || "";
    if (res.ok && type.includes("json")) {
      render(await res.json());
      connectLive();
      return;
    }
  } catch (_) {}
  await startReplay();
}

boot();
