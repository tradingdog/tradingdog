const $ = (id) => document.getElementById(id);

function feedErrorText(feed) {
  const raw = (feed && feed.last_error) || "";
  if (!raw) return "";
  if (String(raw).includes("451") && feed.ok) return "";
  if (String(raw).includes("451")) {
    return "币安主站 451（地区限制）。公开行情应走 data-api.binance.vision，不影响模拟盘";
  }
  return raw;
}

function hostShort(host) {
  if (!host) return "";
  return String(host).replace(/^https?:\/\//, "");
}

function feedLine(s, feed, pollAt) {
  const h = s.health || {};
  const scan = h.scan || {};
  const watch = h.watch || feed.watch || 0;
  const bits = [
    `盯盘 ${watch} 个币（横盘缩量为主）`,
    feed.host ? `公开行情 ${hostShort(feed.host)}` : "",
    `Alpha ${feed.alpha || 0}`,
    feed.key_note || "",
    scan.opens != null ? `开仓 ${scan.opens}` : "",
    scan.blocked_chase ? `追涨拦截 ${scan.blocked_chase}` : "",
    h.persist || h.saved_at ? "状态已落盘" : "",
    h.restored ? "已从上次接着跑" : "",
    h.note || "",
    pollAt,
    feedErrorText(feed),
    s.loop_error || h.loop_error || "",
  ].filter(Boolean);
  return bits.join(" · ");
}

function fmtWall(ts, withSec) {
  if (ts == null || Number(ts) < 1e9) return "—";
  const opt = {
    hour12: false,
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  };
  if (withSec) opt.second = "2-digit";
  return new Date(Number(ts) * 1000).toLocaleString("zh-CN", opt);
}

function fmtDur(sec) {
  if (sec == null || Number.isNaN(Number(sec))) return "—";
  const n = Math.max(0, Math.floor(Number(sec)));
  const d = Math.floor(n / 86400);
  const h = Math.floor((n % 86400) / 3600);
  const m = Math.floor((n % 3600) / 60);
  const s = n % 60;
  if (d) return `${d} 天 ${h} 小时 ${m} 分`;
  if (h) return `${h} 小时 ${m} 分`;
  if (m) return `${m} 分 ${s} 秒`;
  return `${s} 秒`;
}

function rtCard(k, v, hint) {
  return `<article class="rt"><div class="k">${k}</div><div class="v">${v}</div>${hint ? `<div class="hint">${hint}</div>` : ""}</article>`;
}

function renderRuntime(s) {
  const el = $("runtime");
  if (!el) return;
  const rt = s.runtime || {};
  if (s.mode !== "binance_sim") {
    el.innerHTML = [
      rtCard("本进程启动", fmtWall(rt.process_started_at, true), `已运行 ${fmtDur(rt.uptime_sec)}`),
      rtCard("模式", "本地纸上回放", "不是币安真实行情"),
    ].join("");
    return;
  }
  const barSec = rt.bar_seconds || 3600;
  const barOpen = rt.last_closed_bar_at;
  const barClose = barOpen ? barOpen + barSec : 0;
  const nextHint = rt.next_bar_eta_sec != null
    ? `下一根约 ${fmtDur(rt.next_bar_eta_sec)} 后收盘`
    : "还没吃到已收盘的 1 小时 K";
  el.innerHTML = [
    rtCard("本进程启动", fmtWall(rt.process_started_at, true), `已运行 ${fmtDur(rt.uptime_sec)}`),
    rtCard("行情就绪", fmtWall(rt.ready_at, true), rt.ready_at ? `就绪后已盯 ${fmtDur(rt.ready_sec)}` : "仍在拉 K 线"),
    rtCard("上次刷新公开行情", fmtWall(rt.last_poll_at, true), rt.last_poll_ago_sec != null ? `${fmtDur(rt.last_poll_ago_sec)} 前` : "尚未刷新"),
    rtCard("最近 1 小时 K（北京时间）", barOpen ? `${fmtWall(barOpen)} → ${fmtWall(barClose)}` : "—", nextHint),
    rtCard("盯盘池上次重选", fmtWall(rt.universe_at, true), "大约每 6 小时按横盘缩量重挑一次"),
    rtCard("模拟账户落盘", fmtWall(rt.saved_at, true), rt.restored ? "本进程从上次状态接着跑" : (rt.saved_at ? "已写入本机状态文件" : "尚未落盘")),
  ].join("");
}

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
      timeZone: "Asia/Shanghai",
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
  const rt = s.runtime || {};
  const pill = $("statePill");
  pill.textContent = s.state_zh;
  pill.className = "pill " + ({ SQUAT: "squat", ARMED: "armed", IN_THESIS: "fire" }[s.state] || "squat");
  if (s.mode === "binance_sim") {
    const wall = rt.wall_now || Date.now() / 1000;
    $("clock").textContent = `${fmtWall(wall, true)} 北京时间`;
    const up = $("uptimePill");
    if (up) up.textContent = `已运行 ${fmtDur(rt.uptime_sec)}`;
  } else if (s.clock_mode === "unix" && s.now > 1e9) {
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
      ? `上次刷新 ${fmtWall(s.last_poll || feed.last_poll, true)}`
      : "";
    fl.innerHTML = s.mode === "binance_sim"
      ? feedLine(s, feed, pollAt)
      : "当前是本地回放数据，不是币安实时行情。";
  }
  renderRuntime(s);
  document.querySelectorAll("#controls [data-act]").forEach((b) => {
    const act = b.dataset.act;
    if (act === "start") b.classList.toggle("on", !!s.allow_new);
    if (act === "pause") b.classList.toggle("on", !s.allow_new);
  });

  const a = s.account;
  const p = s.performance || {};
  $("metrics").innerHTML = [
    metric("模拟权益", money(a.equity), `起始 ${money(a.starting)} · ${a.multiple.toFixed(2)}x`, clsRet(a.equity - a.starting)),
    metric("可用资金", money(a.cash), "还能用来开新仓的模拟资金"),
    metric("总收益率", pct(p.total_ret != null ? p.total_ret : (a.equity - a.starting) / a.starting), `已实现 ${money(p.realized_pnl || 0)} · 浮动 ${money(a.unrealized)}`, clsRet(a.equity - a.starting)),
    metric("胜率", p.trades ? pct(p.win_rate) : "—", p.trades ? `${p.wins} 赢 / ${p.losses} 亏 · 共 ${p.trades} 笔` : "还没有平过仓"),
    metric("今日盈亏", money(a.daily_pnl), `本周 ${money(a.weekly_pnl)} · 锁定利润 ${money(a.vault)}`, clsRet(a.daily_pnl)),
  ].join("");

  const disc = $("discoveries");
  if (disc) {
    bindDiscScroll(disc);
    const html = renderDiscoveries(s);
    const skel = discoverySkeleton(s);
    const y = disc.scrollTop;
    if (disc.dataset.skel !== skel) {
      disc.innerHTML = html;
      disc.dataset.skel = skel;
      restoreDiscScroll(disc, y);
    } else {
      patchDiscoveryLive(disc, s);
    }
  }

  $("theses").innerHTML = s.theses.length
    ? s.theses.map(thesisCard).join("")
    : `<div class="empty"><strong>现在空仓</strong>没有模拟持仓是正常的。抓的是少而精的妖币：1 小时图上先有横盘箱体，再出现突破大实体和消息/板块导火线，才会开仓。</div>`;

  const rules = $("rules");
  if (rules) {
    rules.innerHTML = (s.rules || [])
      .map((r) => `<div class="rule"><strong>${r.title}</strong><div>${r.text}</div></div>`)
      .join("");
  }
  $("gates").innerHTML = s.risk.gates
    .map(
      (g) => `<div class="gate"><span><i class="dot ${g.ok ? "ok" : "bad"}"></i>${g.label}</span><span class="mute">${g.detail}</span></div>`
    )
    .join("");
  $("skips").innerHTML = s.skips.length
    ? "<div>最近没开仓的原因</div>" + s.skips.map((x) => `<div>${x.why_zh} · ${x.count} 次</div>`).join("")
    : "<div>还没有过滤记录。安静说明没乱开仓。</div>";

  const sc = $("scorecard");
  if (sc) sc.innerHTML = renderScorecard(p);

  const journal = [...s.journal].reverse();
  $("journal").innerHTML = journal.length
    ? journal
        .map((e) => `<li><span class="kind">${e.kind_zh}</span><span class="mono">${when(s, e.day, e.ts)}</span> ${e.symbol}<div class="mute">${e.detail}</div></li>`)
        .join("")
    : "<li class='mute'>还没有开平仓。空仓时这里本来就该安静。</li>";

  const misses = [...s.near_misses].reverse();
  $("misses").innerHTML = misses.length
    ? misses
        .map((m) => `<li><span class="kind">${m.origin_zh || "记下"}</span><span class="mono">${when(s, m.day, m.ts)}</span> ${m.symbol} ${m.side_zh}<div class="mute">${(m.families_zh || []).join(" · ")} — ${m.reason}</div></li>`)
        .join("")
    : "<li class='mute'>还没有被挡下的信号。说明真正齐套的机会很少。</li>";

  $("closed").innerHTML = s.closed.length
    ? s.closed
        .slice()
        .reverse()
        .map(
          (t) => `<div class="closed-row">
            <div><strong>${t.symbol}</strong> <a class="ext" href="${t.binance_url || "#"}" target="_blank" rel="noreferrer">币安</a></div>
            <span class="tag ${t.side}">${t.side_zh}</span>
            <span class="mono">${money(t.notional)} U</span>
            <span class="mono">入 ${Number(t.entry).toPrecision(6)} → 出 ${Number(t.exit_price || t.mark).toPrecision(6)}</span>
            <span>${t.exit_reason_zh || t.exit_reason || "—"}</span>
            <span class="mono ret ${clsRet(t.ret)}">${pct(t.ret)} · ${money(t.pnl)}</span>
          </div>`
        )
        .join("")
    : `<div class="empty">还没有平过仓。有了第一笔，这里会写出场价、盈亏和收益率。</div>`;

  drawEquity(s.equity_curve, a.starting, a.target);
}

function metric(k, v, hint, extra) {
  return `<article class="metric"><div class="k">${k}</div><div class="v ${extra || ""}">${v}</div><div class="hint">${hint}</div></article>`;
}

function bindDiscScroll(el) {
  if (!el || el.dataset.scrollBound) return;
  el.dataset.scrollBound = "1";
  el.addEventListener("scroll", () => { window.__DISC_Y = el.scrollTop; }, { passive: true });
}

function restoreDiscScroll(el, y) {
  if (!el) return;
  const apply = () => {
    el.scrollTop = y;
    window.__DISC_Y = el.scrollTop;
  };
  apply();
  requestAnimationFrame(() => {
    apply();
    requestAnimationFrame(apply);
  });
}

function discoverySkeleton(s) {
  const rows = s.discoveries || s.hunt || [];
  if (!rows.length) return "empty";
  window.__OPEN = window.__OPEN || new Set();
  const blocked = s.blocked || [];
  return rows.map((r) => `${r.symbol}:${window.__OPEN.has(r.symbol) ? 1 : 0}:${r.armed ? 1 : 0}:${blocked.includes(r.symbol) ? 1 : 0}`).join("|");
}

function renderDiscoveries(s) {
  const rows = s.discoveries || s.hunt || [];
  if (!rows.length) {
    return `<div class="empty">还没有盯上任何币。系统在扫币安现货里波动还能走大的 USDT 交易对。</div>`;
  }
  window.__OPEN = window.__OPEN || new Set();
  return rows.map((r) => discoveryRow(r, s)).join("");
}

function patchDiscoveryLive(root, s) {
  const rows = s.discoveries || s.hunt || [];
  for (const r of rows) {
    const item = root.querySelector(`[data-sym="${r.symbol}"]`);
    if (!item) continue;
    const chg = r.change24h != null ? r.change24h : r.moved;
    const chgEl = item.querySelector("[data-f=chg]");
    if (chgEl) {
      chgEl.textContent = chg == null ? "—" : pct(chg);
      chgEl.className = `mono ret ${clsRet(chg || 0)}`;
    }
    const priceEl = item.querySelector("[data-f=price]");
    if (priceEl) priceEl.textContent = r.price != null ? Number(r.price).toPrecision(6) : "—";
    const planEl = item.querySelector("[data-f=plan]");
    if (planEl) planEl.textContent = money(r.planned_usdt);
    const stopEl = item.querySelector("[data-f=stop]");
    if (stopEl) stopEl.textContent = r.stop ? Number(r.stop).toPrecision(6) : "—";
    item.querySelectorAll("[data-f=status]").forEach((n) => {
      n.textContent = r.status || r.wait || (n.closest(".disc-body") ? "—" : "");
    });
  }
}

function discoveryRow(r, s) {
  const chg = r.change24h != null ? r.change24h : r.moved;
  const open = window.__OPEN.has(r.symbol);
  const how = (r.how_found || []).map((x) => `<li>${x}</li>`).join("");
  const vol = r.quote_volume != null ? `${money(r.quote_volume)} USDT` : "—";
  return `<article class="disc-item ${r.armed ? "hot" : ""} ${open ? "open" : ""}" data-sym="${r.symbol}">
    <button type="button" class="disc-head" data-toggle="${r.symbol}" aria-expanded="${open ? "true" : "false"}">
      <div class="disc-top">
        <span class="disc-name"><strong>${r.symbol}</strong>
          <span class="tag ${r.side}">${r.side_zh || ""}</span>
          ${r.armed ? '<span class="tag">已盯上</span>' : ""}
        </span>
        <span class="mono ret ${clsRet(chg || 0)}" data-f="chg">${chg == null ? "—" : pct(chg)}</span>
      </div>
      <div class="disc-sub">
        <span>现价 <b class="mono" data-f="price">${r.price != null ? Number(r.price).toPrecision(6) : "—"}</b></span>
        <span>计划 <b class="mono" data-f="plan">${money(r.planned_usdt)}</b> U</span>
        <span>止损 <b class="mono" data-f="stop">${r.stop ? Number(r.stop).toPrecision(6) : "—"}</b></span>
        <span class="disc-status" data-f="status">${r.status || r.wait || ""}</span>
      </div>
    </button>
    ${open ? `<div class="disc-body">
      <p>${r.why_side || ""}</p>
      <p><strong>怎么发现的</strong></p>
      <ul class="how">${how || "<li>还在扫描</li>"}</ul>
      <p><strong>现在卡在哪：</strong><span data-f="status">${r.status || r.wait || "—"}</span></p>
      <p class="plan">24h成交额 ${vol} · 止盈1 ${r.tp1 ? Number(r.tp1).toPrecision(6) : "—"}（40% 减 25%） · 止盈2 ${r.tp2 ? Number(r.tp2).toPrecision(6) : "—"}（100% 再减 25%） · ${r.time_stop_hours || 72} 小时没走出 20% 就平</p>
      <div class="actions">
        <a class="ext" href="${r.binance_url || "#"}" target="_blank" rel="noreferrer">去币安核对</a>
        <button type="button" class="tiny" data-block="${r.symbol}">${(s.blocked || []).includes(r.symbol) ? "取消拉黑" : "拉黑"}</button>
      </div>
    </div>` : ""}
  </article>`;
}

function renderScorecard(p) {
  if (!p) return "";
  return `<div class="score">
    <div><span class="k">已平仓笔数</span><b>${p.trades || 0}</b></div>
    <div><span class="k">胜率</span><b>${p.trades ? pct(p.win_rate) : "—"}</b></div>
    <div><span class="k">已实现盈亏</span><b class="ret ${clsRet(p.realized_pnl || 0)}">${money(p.realized_pnl || 0)}</b></div>
    <div><span class="k">平均盈利 / 亏损</span><b>${money(p.avg_win || 0)} / ${money(p.avg_loss || 0)}</b></div>
    <div><span class="k">最好一笔</span><b>${p.best_symbol || "—"} ${p.best_symbol ? money(p.best_pnl) : ""}</b></div>
    <div><span class="k">最差一笔</span><b>${p.worst_symbol || "—"} ${p.worst_symbol ? money(p.worst_pnl) : ""}</b></div>
  </div>`;
}

function thesisCard(t) {
  return `<article class="card">
    <div class="row">
      <h3>${t.symbol} <span class="tag ${t.side}">${t.side_zh}</span> <span class="tag">${t.venue_zh}</span></h3>
      <div class="mono ret ${clsRet(t.ret)}">${pct(t.ret)} · ${money(t.pnl)} U</div>
    </div>
    <p class="plain">${t.why_side || ""}</p>
    <p class="plain">${t.plain}</p>
    <div class="nums">
      <div><span class="k">仓位</span><span class="mono">${money(t.notional)} U（${pct(t.size_pct || 0)} 权益）</span></div>
      <div><span class="k">入场</span><span class="mono">${Number(t.entry).toPrecision(6)}</span></div>
      <div><span class="k">现价</span><span class="mono">${Number(t.mark).toPrecision(6)}</span></div>
      <div><span class="k">止损</span><span class="mono">${Number(t.invalidation).toPrecision(6)}（${pct(t.stop_pct || 0)}）</span></div>
      <div><span class="k">止盈1 / 2</span><span class="mono">${Number(t.tp1).toPrecision(6)} / ${Number(t.tp2).toPrecision(6)}</span></div>
      <div><span class="k">剩余时间</span><span class="mono">${t.hours_left.toFixed(1)} / ${t.hold_hours ? t.hold_hours.toFixed(0) : "—"} 小时</span></div>
    </div>
    <div class="actions">
      <a class="ext" href="${t.binance_url || "#"}" target="_blank" rel="noreferrer">去币安核对</a>
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
  if (action === "flatten") {
    const n = ((window.__SNAP && window.__SNAP.theses) || []).length;
    if (!n) return;
    if (!window.confirm("确认把所有模拟持仓按现价平掉？资金仍是模拟的。")) return;
  }
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
  const toggle = ev.target.closest("[data-toggle]");
  if (toggle && !ev.target.closest("a, button[data-block], button[data-close]")) {
    ev.preventDefault();
    window.__OPEN = window.__OPEN || new Set();
    const symbol = toggle.dataset.toggle;
    if (window.__OPEN.has(symbol)) window.__OPEN.delete(symbol);
    else window.__OPEN.add(symbol);
    const wrap = $("discoveries");
    const y = wrap ? wrap.scrollTop : (window.__DISC_Y || 0);
    if (window.__SNAP) render(window.__SNAP);
    restoreDiscScroll($("discoveries"), y);
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
