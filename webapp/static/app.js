/* 2026 世界杯预测中心 — 前端逻辑（纯原生 JS） */

const FLAGS = {
  "Mexico": "🇲🇽", "South Africa": "🇿🇦", "South Korea": "🇰🇷", "Czech Republic": "🇨🇿",
  "Canada": "🇨🇦", "Bosnia and Herzegovina": "🇧🇦", "Qatar": "🇶🇦", "Switzerland": "🇨🇭",
  "Brazil": "🇧🇷", "Morocco": "🇲🇦", "Haiti": "🇭🇹", "Scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
  "United States": "🇺🇸", "Paraguay": "🇵🇾", "Australia": "🇦🇺", "Turkey": "🇹🇷",
  "Germany": "🇩🇪", "Ecuador": "🇪🇨", "Curaçao": "🇨🇼", "Curacao": "🇨🇼",
  "Ivory Coast": "🇨🇮", "Netherlands": "🇳🇱", "Japan": "🇯🇵", "Tunisia": "🇹🇳",
  "New Zealand": "🇳🇿", "Belgium": "🇧🇪", "Egypt": "🇪🇬", "Iran": "🇮🇷",
  "Panama": "🇵🇦", "Spain": "🇪🇸", "Uruguay": "🇺🇾", "Cape Verde": "🇨🇻",
  "Saudi Arabia": "🇸🇦", "France": "🇫🇷", "Senegal": "🇸🇳", "Norway": "🇳🇴",
  "DR Congo": "🇨🇩", "Argentina": "🇦🇷", "Jordan": "🇯🇴", "Algeria": "🇩🇿",
  "Uzbekistan": "🇺🇿", "Portugal": "🇵🇹", "Colombia": "🇨🇴", "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
  "Croatia": "🇭🇷", "Iraq": "🇮🇶", "Ghana": "🇬🇭", "Austria": "🇦🇹", "Sweden": "🇸🇪",
};

const ZH = {
  "Mexico": "墨西哥", "South Africa": "南非", "South Korea": "韩国", "Czech Republic": "捷克",
  "Canada": "加拿大", "Bosnia and Herzegovina": "波黑", "Qatar": "卡塔尔", "Switzerland": "瑞士",
  "Brazil": "巴西", "Morocco": "摩洛哥", "Haiti": "海地", "Scotland": "苏格兰",
  "United States": "美国", "Paraguay": "巴拉圭", "Australia": "澳大利亚", "Turkey": "土耳其",
  "Germany": "德国", "Ecuador": "厄瓜多尔", "Curaçao": "库拉索", "Curacao": "库拉索",
  "Ivory Coast": "科特迪瓦", "Netherlands": "荷兰", "Japan": "日本", "Tunisia": "突尼斯",
  "New Zealand": "新西兰", "Belgium": "比利时", "Egypt": "埃及", "Iran": "伊朗",
  "Panama": "巴拿马", "Spain": "西班牙", "Uruguay": "乌拉圭", "Cape Verde": "佛得角",
  "Saudi Arabia": "沙特", "France": "法国", "Senegal": "塞内加尔", "Norway": "挪威",
  "DR Congo": "民主刚果", "Argentina": "阿根廷", "Jordan": "约旦", "Algeria": "阿尔及利亚",
  "Uzbekistan": "乌兹别克斯坦", "Portugal": "葡萄牙", "Colombia": "哥伦比亚", "England": "英格兰",
  "Croatia": "克罗地亚", "Iraq": "伊拉克", "Ghana": "加纳", "Austria": "奥地利", "Sweden": "瑞典",
};

const STAGES = [
  ["round_of_32", "进 32 强"], ["round_of_16", "进 16 强"], ["quarter_final", "进 8 强"],
  ["semi_final", "进 4 强"], ["final", "进决赛"], ["champion", "夺冠"],
];
const KO_STAGE_ZH = {
  "Round of 32": "32 强赛", "Round of 16": "16 强赛", "Quarter-final": "1/4 决赛",
  "Semi-final": "半决赛", "Play-off for third place": "季军赛", "Final": "决赛",
};

const S = { meta: null, forecast: null, stage: "champion" };

const $ = (sel) => document.querySelector(sel);
const flag = (t) => FLAGS[t] || "⚽";
const zh = (t) => ZH[t] || t;
const pct = (x, d = 1) => (x * 100).toFixed(d) + "%";
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function fmtDate(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "short" });
}
function fmtTime(iso) {
  return new Date(iso).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

/* ---------- 启动轮询 ---------- */

async function pollUntilReady() {
  while (true) {
    try {
      const st = await (await fetch("/api/status")).json();
      $("#loading-phase").textContent = st.error ? "❌ " + st.error : st.phase + "…";
      if (st.total > 0) {
        $("#loading-bar").style.width = (st.progress / st.total * 100) + "%";
        $("#loading-phase").textContent = `${st.phase}：${st.progress.toLocaleString()} / ${st.total.toLocaleString()} 届`;
      }
      if (st.error) return;
      if (st.ready && !st.running) break;
    } catch (e) { /* 服务还没起来，继续等 */ }
    await new Promise((r) => setTimeout(r, 400));
  }
  [S.meta, S.forecast] = await Promise.all([
    (await fetch("/api/meta")).json(),
    (await fetch("/api/forecast")).json(),
  ]);
  $("#loading").classList.add("hidden");
  renderAll();
}

function renderAll() {
  renderHero();
  renderDashboard();
  renderGroups();
  renderMatches();
  renderBracket();
  renderLab();
}

/* ---------- 头部信息条 ---------- */

function renderHero() {
  const fav = topByStage("champion")[0];
  const days = Math.ceil((new Date(S.meta.kickoff) - Date.now()) / 86400000);
  const countdown = days > 0 ? `距开幕 <b>${days}</b> 天` : "🎉 比赛进行中";
  $("#hero-chips").innerHTML = `
    <span class="chip">${countdown}</span>
    <span class="chip">头号热门 ${flag(fav[0])} <b>${zh(fav[0])} ${pct(fav[1])}</b></span>
    <span class="chip">蒙特卡洛 <b>${S.forecast.n_sims.toLocaleString()}</b> 届</span>
    <span class="chip">更新于 <b>${S.forecast.finished_at}</b></span>`;
}

/* ---------- 总览 ---------- */

function topByStage(stage) {
  return Object.entries(S.forecast.team_probs)
    .map(([t, p]) => [t, p[stage]])
    .sort((a, b) => b[1] - a[1]);
}

function renderDashboard() {
  $("#stage-chips").innerHTML = STAGES.map(([k, label]) =>
    `<button class="stage-chip ${k === S.stage ? "active" : ""}" data-stage="${k}">${label}</button>`
  ).join("");
  document.querySelectorAll(".stage-chip").forEach((b) =>
    b.addEventListener("click", () => { S.stage = b.dataset.stage; renderDashboard(); })
  );

  const rows = topByStage(S.stage).slice(0, 16);
  const max = rows[0][1] || 1;
  $("#champ-chart").innerHTML = rows.map(([t, p]) => `
    <div class="bar-row" data-team="${esc(t)}">
      <div class="bar-team"><span class="flag">${flag(t)}</span>${zh(t)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${(p / max * 100).toFixed(1)}%"></div></div>
      <div class="bar-val">${pct(p)}</div>
    </div>`).join("");
  bindTeamClicks($("#champ-chart"));

  const [favT, favP] = topByStage("champion")[0];
  $("#card-favorite").innerHTML = `
    <h3>👑 头号热门</h3>
    <div class="big-stat">
      <span class="flag">${flag(favT)}</span>
      <div><div class="name">${zh(favT)}</div><div class="muted">Elo ${eloOf(favT)}</div></div>
      <div class="pct" style="margin-left:auto">${pct(favP)}</div>
    </div>`;

  $("#card-hosts").innerHTML = `<h3>🏠 东道主行情（夺冠概率）</h3>` +
    S.meta.hosts.map((h) => {
      const p = S.forecast.team_probs[h];
      return `<div class="host-row"><span>${flag(h)} ${zh(h)}</span><b>${pct(p.champion)}</b></div>`;
    }).join("");

  const opener = S.meta.matches.find((m) => m.stage === "First Stage");
  $("#card-opener").innerHTML = `
    <h3>🎬 揭幕战</h3>
    <div class="match-info">${fmtDate(opener.date)} ${fmtTime(opener.date)} · ${esc(opener.stadium)}</div>
    <div style="display:flex;justify-content:space-between;font-weight:600;margin:8px 0 6px">
      <span>${flag(opener.home)} ${zh(opener.home)}</span><span>${zh(opener.away)} ${flag(opener.away)}</span>
    </div>
    ${wdlBar(opener)}
    <div class="match-pcts"><span>主胜 ${pct(opener.p_home)}</span><span>平 ${pct(opener.p_draw)}</span><span>客胜 ${pct(opener.p_away)}</span></div>`;
}

function eloOf(t) { return Math.round(S.meta.teams.find((x) => x.name === t).elo); }

function wdlBar(m) {
  return `<div class="wdl">
    <div class="w" style="width:${m.p_home * 100}%"></div>
    <div class="d" style="width:${m.p_draw * 100}%"></div>
    <div class="l" style="width:${m.p_away * 100}%"></div>
  </div>`;
}

/* ---------- 小组赛 ---------- */

function renderGroups() {
  const groups = {};
  S.meta.teams.forEach((t) => (groups[t.group] = groups[t.group] || []).push(t));
  $("#groups-grid").innerHTML = Object.keys(groups).sort().map((g) => `
    <div class="card group-card">
      <h4>⚽ ${g} 组</h4>
      ${groups[g].map((t) => {
        const adv = S.forecast.team_probs[t.name].round_of_32;
        return `<div class="group-team" data-team="${esc(t.name)}">
          <div class="t"><span class="flag">${flag(t.name)}</span>${zh(t.name)}${t.host ? ' <span class="host-badge">东道主</span>' : ""}</div>
          <div class="elo">${Math.round(t.elo)}</div>
          <div class="adv-mini"><div class="adv-track"><div class="adv-fill" style="width:${adv * 100}%"></div></div><span class="adv-pct">${Math.round(adv * 100)}%</span></div>
        </div>`;
      }).join("")}
      <div class="muted" style="margin-top:8px;font-size:11px">出线率 = 进入 32 强概率</div>
    </div>`).join("");
  bindTeamClicks($("#groups-grid"));
}

/* ---------- 赛程 ---------- */

function renderMatches() {
  const sel = $("#filter-group");
  if (sel.options.length === 1) {
    [...new Set(S.meta.matches.filter((m) => m.group).map((m) => m.group))].sort()
      .forEach((g) => sel.add(new Option(g + " 组", g)));
    sel.addEventListener("change", renderMatchList);
    $("#filter-team").addEventListener("input", renderMatchList);
  }
  renderMatchList();
}

function renderMatchList() {
  const g = $("#filter-group").value;
  const q = $("#filter-team").value.trim().toLowerCase();
  const list = S.meta.matches.filter((m) => m.group)
    .filter((m) => !g || m.group === g)
    .filter((m) => !q || [m.home, m.away, zh(m.home), zh(m.away)].some((x) => x.toLowerCase().includes(q)));

  $("#match-count").textContent = `共 ${list.length} 场`;

  let html = "", lastDate = "";
  for (const m of list) {
    const d = fmtDate(m.date);
    if (d !== lastDate) { html += `<div class="date-head">📅 ${d}</div>`; lastDate = d; }
    const favSide = m.p_home > Math.max(m.p_draw, m.p_away) ? "home" : m.p_away > Math.max(m.p_draw, m.p_home) ? "away" : "";
    html += `<div class="match-card">
      <div class="match-side ${favSide === "home" ? "fav" : ""}"><span class="flag">${flag(m.home)}</span>${zh(m.home)}</div>
      <div class="match-mid">
        <div class="match-info">${m.group} 组 · ${fmtTime(m.date)} · ${esc(m.stadium || "")}${m.city ? " · " + esc(m.city) : ""}</div>
        ${wdlBar(m)}
        <div class="match-pcts"><span>胜 ${pct(m.p_home)}</span><span>平 ${pct(m.p_draw)}</span><span>胜 ${pct(m.p_away)}</span></div>
      </div>
      <div class="match-side right ${favSide === "away" ? "fav" : ""}">${zh(m.away)}<span class="flag">${flag(m.away)}</span></div>
    </div>`;
  }
  $("#match-list").innerHTML = html || '<p class="muted">没有符合条件的比赛</p>';
}

/* ---------- 对阵图 ---------- */

function phZh(ph) {
  if (!ph) return "";
  if (ph.startsWith("W")) return `第 ${ph.slice(1)} 场胜者`;
  if (ph.startsWith("RU")) return `第 ${ph.slice(2)} 场负者`;
  if (ph.startsWith("1")) return `${ph[1]} 组第一`;
  if (ph.startsWith("2")) return `${ph[1]} 组第二`;
  if (ph.startsWith("3")) return `小组第三·${ph.slice(1)}`;
  return ph;
}

function renderBracket() {
  const kos = S.meta.matches.filter((m) => !m.group);
  const order = ["Round of 32", "Round of 16", "Quarter-final", "Semi-final", "Final", "Play-off for third place"];
  const cols = order.filter((st) => kos.some((m) => m.stage === st));

  $("#bracket").innerHTML = cols.map((st) => {
    const ms = kos.filter((m) => m.stage === st);
    return `<div class="bracket-col"><h4>${KO_STAGE_ZH[st]}</h4><div class="bracket-col-body">${ms.map((m) => koCard(m, st)).join("")}</div></div>`;
  }).join("");
  bindTeamClicks($("#bracket"));
}

function koCard(m, st) {
  const ks = S.forecast.ko_stats[m.num] || {};
  const side = (dist, ph) => {
    const top = (dist || [])[0];
    return `<div class="ko-side">
      <div class="t">${top ? `<span class="flag">${flag(top[0])}</span><span data-team="${esc(top[0])}" style="cursor:pointer">${zh(top[0])}</span>` : ""}<span class="ko-ph">${phZh(ph)}</span></div>
      <span class="p">${top ? pct(top[1], 0) : ""}</span>
    </div>`;
  };
  const w = (ks.winner || [])[0];
  return `<div class="ko-card ${st === "Final" ? "final-card" : ""}">
    <div class="ko-meta"><span>M${m.num}</span><span>${fmtDate(m.date)} · ${esc(m.city || "")}</span></div>
    ${side(ks.side_a, m.ph_a)}
    ${side(ks.side_b, m.ph_b)}
    ${w ? `<div class="ko-winner"><span>最可能晋级：${flag(w[0])} ${zh(w[0])}</span><span>${pct(w[1], 0)}</span></div>` : ""}
  </div>`;
}

/* ---------- 实验室 ---------- */

function renderLab() {
  const mi = S.meta.model;
  $("#model-info").innerHTML = `
    <div class="kv"><span>进球模型</span><code>λ(d) = exp(${mi.a} + ${mi.b}·d)</code></div>
    <div class="kv"><span>校准样本</span><b>${mi.n_samples.toLocaleString()} 条</b></div>
    <div class="kv"><span>本轮模拟</span><b>${S.forecast.n_sims.toLocaleString()} 届 / ${S.forecast.elapsed}s</b></div>
    <div class="kv"><span>随机种子</span><b>${S.forecast.seed ?? "随机"}</b></div>
    <div class="kv"><span>赛程来源</span><a href="${S.meta.sources.fixtures}" target="_blank">FIFA 官方 API</a></div>
    <div class="kv"><span>历史赛果</span><a href="${S.meta.sources.history}" target="_blank">martj42 数据集</a></div>`;

  const ranked = [...S.meta.teams].sort((a, b) => b.elo - a.elo);
  $("#elo-list").innerHTML = ranked.map((t, i) => `
    <div class="elo-row" data-team="${esc(t.name)}">
      <span class="rank">${i + 1}</span>
      <span>${flag(t.name)} ${zh(t.name)} <span class="muted">${t.group} 组</span></span>
      <span class="v">${Math.round(t.elo)}</span>
    </div>`).join("");
  bindTeamClicks($("#elo-list"));
}

async function runSimulation() {
  const btn = $("#sim-run");
  btn.disabled = true;
  const resp = await fetch("/api/simulate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sims: +$("#sim-count").value, seed: $("#sim-seed").value || null }),
  });
  if (!resp.ok) {
    toast("❌ " + ((await resp.json()).error || "启动失败"));
    btn.disabled = false;
    return;
  }
  $("#sim-progress").classList.remove("hidden");
  while (true) {
    await new Promise((r) => setTimeout(r, 350));
    const st = await (await fetch("/api/status")).json();
    if (st.total > 0) {
      $("#sim-bar").style.width = (st.progress / st.total * 100) + "%";
      $("#sim-progress-text").textContent = `${st.progress.toLocaleString()} / ${st.total.toLocaleString()} 届`;
    }
    if (!st.running) break;
  }
  S.forecast = await (await fetch("/api/forecast")).json();
  $("#sim-progress").classList.add("hidden");
  $("#sim-bar").style.width = "0%";
  btn.disabled = false;
  renderAll();
  toast(`✅ 完成 ${S.forecast.n_sims.toLocaleString()} 届模拟，用时 ${S.forecast.elapsed}s`);
}

/* ---------- 球队弹窗 ---------- */

function bindTeamClicks(root) {
  root.querySelectorAll("[data-team]").forEach((el) =>
    el.addEventListener("click", (e) => { e.stopPropagation(); showTeam(el.dataset.team); })
  );
}

function showTeam(name) {
  const t = S.meta.teams.find((x) => x.name === name);
  const p = S.forecast.team_probs[name];
  if (!t || !p) return;
  const games = S.meta.matches.filter((m) => m.home === name || m.away === name).filter((m) => m.group);
  $("#modal-card").innerHTML = `
    <button class="modal-close" id="modal-close">✕</button>
    <div class="modal-head">
      <span class="flag">${flag(name)}</span>
      <div>
        <h2>${zh(name)} <span class="muted" style="font-size:14px">${esc(name)}</span></h2>
        <div class="sub">${t.group} 组 · Elo ${Math.round(t.elo)}${t.host ? " · 🏠 东道主（享主场优势）" : ""}</div>
      </div>
    </div>
    ${STAGES.map(([k, label]) => `
      <div class="funnel-row">
        <span class="lbl">${label}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${p[k] * 100}%"></div></div>
        <span class="bar-val">${pct(p[k])}</span>
      </div>`).join("")}
    <h4>小组赛赛程</h4>
    ${games.map((m) => {
      const isHome = m.home === name;
      const opp = isHome ? m.away : m.home;
      const win = isHome ? m.p_home : m.p_away;
      return `<div class="mini-match">
        <span>${fmtDate(m.date)} · vs ${flag(opp)} ${zh(opp)}</span>
        <span class="bar-val">胜率 ${pct(win)}</span>
      </div>`;
    }).join("")}`;
  $("#modal").classList.remove("hidden");
  $("#modal-close").addEventListener("click", closeModal);
}

function closeModal() { $("#modal").classList.add("hidden"); }

/* ---------- 其他 ---------- */

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.add("hidden"), 3500);
}

document.querySelectorAll(".tab").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === b));
    document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + b.dataset.tab));
  })
);
$("#modal").querySelector(".modal-backdrop").addEventListener("click", closeModal);
$("#sim-run").addEventListener("click", runSimulation);

pollUntilReady();
