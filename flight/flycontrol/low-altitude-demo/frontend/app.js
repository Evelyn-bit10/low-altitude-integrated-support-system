/* 低空动态起降飞行程序实时调整系统 Demo —— 前端逻辑(纯 Canvas, 无外部依赖) */
"use strict";

const PLAN = document.getElementById("plan");
const PROFILE = document.getElementById("profile");
const planCtx = PLAN.getContext("2d");
const profCtx = PROFILE.getContext("2d");

const WORLD = 2200;            // 平面视图半跨度(米)
let state = { obstacles: [], airspaces: [], airport: null, current: null };
let crane = null;              // 动态障碍物(id, active)

async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json();
}

async function refresh() {
  try {
    const [cur, obs, air, ap] = await Promise.all([
      getJSON("/api/program/current"),
      getJSON("/api/obstacles"),
      getJSON("/api/airspaces"),
      getJSON("/api/airport"),
    ]);
    state.obstacles = obs.filter(o => o.active);
    state.airspaces = air;
    state.airport = ap;
    state.current = cur;
    crane = obs.find(o => o.obs_type === 2) || crane;
    setPill(true);
    drawPlan();
    drawProfile();
    updatePanel();
  } catch (e) {
    setPill(false);
    console.error(e);
  }
}

function setPill(ok) {
  const el = document.getElementById("status-pill");
  el.textContent = ok ? "已连接 · 闭环运行中" : "连接失败";
  el.className = "status-pill " + (ok ? "ok" : "err");
}

/* ---------------- 平面视图 ---------------- */
function toScreen(x, y) {
  const s = PLAN.width / (2 * WORLD);
  return { px: PLAN.width / 2 + x * s, py: PLAN.height / 2 - y * s, s };
}

function drawPlan() {
  const ctx = planCtx;
  ctx.clearRect(0, 0, PLAN.width, PLAN.height);

  // 网格
  ctx.strokeStyle = "#16213c";
  ctx.lineWidth = 1;
  const step = 500;
  for (let g = -WORLD; g <= WORLD; g += step) {
    const a = toScreen(g, -WORLD), b = toScreen(g, WORLD);
    const c = toScreen(-WORLD, g), d = toScreen(WORLD, g);
    ctx.beginPath(); ctx.moveTo(a.px, a.py); ctx.lineTo(b.px, b.py); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(c.px, c.py); ctx.lineTo(d.px, d.py); ctx.stroke();
  }

  // 限飞区
  for (const a of state.airspaces) {
    ctx.beginPath();
    a.polygon.forEach(([x, y], i) => {
      const p = toScreen(x, y);
      i ? ctx.lineTo(p.px, p.py) : ctx.moveTo(p.px, p.py);
    });
    ctx.closePath();
    ctx.fillStyle = "rgba(251,191,36,0.10)";
    ctx.strokeStyle = "rgba(251,191,36,0.6)";
    ctx.fill(); ctx.stroke();
    const c = a.polygon.reduce((s, p) => [s[0] + p[0], s[1] + p[1]], [0, 0]);
    const pc = toScreen(c[0] / a.polygon.length, c[1] / a.polygon.length);
    ctx.fillStyle = "#fbbf24"; ctx.font = "12px sans-serif";
    ctx.fillText(a.name, pc.px, pc.py);
  }

  // 障碍物(外圈=保护区, 内圈=实体)
  for (const o of state.obstacles) {
    const p = toScreen(o.x, o.y);
    ctx.beginPath(); ctx.arc(p.px, p.py, (o.radius + o.buffer) * p.s, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(248,113,113,0.15)"; ctx.fill();
    ctx.strokeStyle = "rgba(248,113,113,0.7)"; ctx.stroke();
    ctx.beginPath(); ctx.arc(p.px, p.py, o.radius * p.s, 0, Math.PI * 2);
    ctx.fillStyle = o.obs_type === 2 ? "#f87171" : "#b45309"; ctx.fill();
    ctx.fillStyle = "#fff"; ctx.font = "11px sans-serif";
    ctx.fillText(`${o.name} (${o.top_agl}m)`, p.px + o.radius * p.s + 4, p.py);
  }

  // 起降点
  const ap = toScreen(0, 0);
  ctx.beginPath(); ctx.arc(ap.px, ap.py, 8, 0, Math.PI * 2);
  ctx.fillStyle = "#38bdf8"; ctx.fill();
  ctx.fillStyle = "#dbe4ff"; ctx.font = "12px sans-serif";
  ctx.fillText(state.airport ? state.airport.code : "起降点", ap.px + 12, ap.py + 4);
  // 跑道方向
  if (state.airport) {
    const h = state.airport.runway_heading * Math.PI / 180;
    const e = toScreen(Math.sin(h) * 160, Math.cos(h) * 160);
    ctx.strokeStyle = "#38bdf8"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(ap.px, ap.py); ctx.lineTo(e.px, e.py); ctx.stroke();
  }

  // 当前程序航迹
  const prog = state.current && state.current.program;
  if (prog) {
    drawPath(ctx, prog.waypoints, "#34d399", 3);
    if (prog.miss_approach && prog.miss_approach.length) {
      drawPath(ctx, prog.miss_approach, "#fbbf24", 1.5, [6, 4]);
    }
  }
}

function drawPath(ctx, wps, color, width, dash) {
  ctx.strokeStyle = color; ctx.lineWidth = width;
  ctx.setLineDash(dash || []);
  ctx.beginPath();
  wps.forEach((w, i) => {
    const p = toScreen(w.x, w.y);
    i ? ctx.lineTo(p.px, p.py) : ctx.moveTo(p.px, p.py);
  });
  ctx.stroke();
  ctx.setLineDash([]);
  // 起点/终点
  if (wps.length) {
    const s = toScreen(wps[0].x, wps[0].y);
    const e = toScreen(wps[wps.length - 1].x, wps[wps.length - 1].y);
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.arc(s.px, s.py, 4, 0, Math.PI * 2); ctx.fill();
    ctx.beginPath(); ctx.arc(e.px, e.py, 4, 0, Math.PI * 2); ctx.fill();
  }
}

/* ---------------- 高度剖面 ---------------- */
function drawProfile() {
  const ctx = profCtx;
  ctx.clearRect(0, 0, PROFILE.width, PROFILE.height);
  const prog = state.current && state.current.program;
  if (!prog || !prog.waypoints.length) return;

  const wps = prog.waypoints;
  let cum = [0];
  for (let i = 1; i < wps.length; i++) {
    cum.push(cum[i - 1] + Math.hypot(wps[i].x - wps[i - 1].x, wps[i].y - wps[i - 1].y));
  }
  const maxD = Math.max(cum[cum.length - 1], 1);
  const maxZ = Math.max(500, ...wps.map(w => w.z));
  const pad = 24;
  const sx = d => pad + (d / maxD) * (PROFILE.width - pad * 2);
  const sy = z => PROFILE.height - pad - (z / maxZ) * (PROFILE.height - pad * 2);

  // 网格
  ctx.strokeStyle = "#16213c"; ctx.lineWidth = 1;
  for (let z = 0; z <= maxZ; z += 100) {
    ctx.beginPath(); ctx.moveTo(pad, sy(z)); ctx.lineTo(PROFILE.width - pad, sy(z)); ctx.stroke();
    ctx.fillStyle = "#7d8bb0"; ctx.font = "10px sans-serif";
    ctx.fillText(z + "m", 2, sy(z) + 3);
  }
  // 障碍物高度参考线(标注最高障碍物)
  const top = Math.max(0, ...state.obstacles.map(o => o.top_agl));
  if (top > 0) {
    ctx.strokeStyle = "rgba(248,113,113,0.5)"; ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(pad, sy(top)); ctx.lineTo(PROFILE.width - pad, sy(top)); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#f87171"; ctx.fillText("障碍物顶 " + top + "m", PROFILE.width - 110, sy(top) - 4);
  }
  // 剖面线
  ctx.strokeStyle = "#34d399"; ctx.lineWidth = 2.5;
  ctx.beginPath();
  wps.forEach((w, i) => { i ? ctx.lineTo(sx(cum[i]), sy(w.z)) : ctx.moveTo(sx(0), sy(w.z)); });
  ctx.stroke();
  // 起终点
  ctx.fillStyle = "#34d399";
  ctx.beginPath(); ctx.arc(sx(0), sy(wps[0].z), 4, 0, Math.PI * 2); ctx.fill();
  ctx.beginPath(); ctx.arc(sx(cum[cum.length - 1]), sy(wps[wps.length - 1].z), 4, 0, Math.PI * 2); ctx.fill();
}

/* ---------------- 控制面板 ---------------- */
function updatePanel() {
  const cur = state.current || {};
  const risk = cur.risk;
  const el = document.getElementById("risk-score");
  const lv = document.getElementById("risk-level");
  if (risk) {
    el.textContent = risk.score;
    lv.textContent = `${risk.level_name} · ${risk.program_status}`;
    lv.className = "risk-level l" + risk.level;
    document.getElementById("f-obs").textContent = risk.factors.obstacle;
    document.getElementById("f-met").textContent = risk.factors.meteo;
    document.getElementById("f-air").textContent = risk.factors.airspace;
  }
  const prog = cur.program;
  if (prog) {
    document.getElementById("p-ver").textContent = prog.version;
    document.getElementById("p-type").textContent = prog.type;
    document.getElementById("p-src").textContent = prog.source;
    document.getElementById("p-wp").textContent = prog.waypoints.length;
  }
  const alarm = document.getElementById("alarm");
  if (cur.alarm) { alarm.hidden = false; alarm.textContent = "⚠ " + cur.alarm; }
  else alarm.hidden = true;

  const event = document.getElementById("event");
  if (cur.last_event) { event.hidden = false; event.textContent = "↻ " + cur.last_event; }
  else event.hidden = true;

  // 校验结果
  const checksEl = document.getElementById("checks");
  checksEl.innerHTML = "";
  const checks = [];
  if (cur.compliance) checks.push(...cur.compliance.checks);
  if (cur.simulate) checks.push(...cur.simulate.checks);
  for (const c of checks) {
    const div = document.createElement("div");
    div.className = "check " + (c.pass ? "pass" : "fail");
    div.innerHTML = `<span class="dot"></span><div><div>${c.name}</div><div class="detail">${c.detail}</div></div>`;
    checksEl.appendChild(div);
  }

  if (crane) {
    const btn = document.getElementById("btn-crane");
    btn.textContent = crane.active ? "关闭动态塔吊" : "激活动态塔吊";
  }
}

/* ---------------- 事件 ---------------- */
document.getElementById("btn-crane").addEventListener("click", async () => {
  if (!crane) return;
  await getJSON("/api/env/obstacle/toggle", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: crane.id, active: !crane.active }),
  });
  crane.active = !crane.active;
  refresh();
});

async function replan(type) {
  await getJSON("/api/program/replan", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ program_type: type }),
  });
  refresh();
}
document.getElementById("btn-replan-arr").addEventListener("click", () => replan("arrival"));
document.getElementById("btn-replan-dep").addEventListener("click", () => replan("departure"));

function readMeteo() {
  return {
    wind_speed: +document.getElementById("in-wind").value,
    visibility: +document.getElementById("in-vis").value,
    turbulence: +document.getElementById("in-turb").value,
    wind_shear: +document.getElementById("in-shear").value,
  };
}
document.getElementById("in-wind").addEventListener("input", e => {
  document.getElementById("v-wind").textContent = e.target.value;
});
document.getElementById("in-vis").addEventListener("input", e => {
  document.getElementById("v-vis").textContent = e.target.value;
});
document.getElementById("btn-meteo").addEventListener("click", async () => {
  await getJSON("/api/env/meteo", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(readMeteo()),
  });
  refresh();
});
document.getElementById("btn-meteo-bad").addEventListener("click", async () => {
  await getJSON("/api/env/meteo", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ wind_speed: 20, visibility: 500, turbulence: 4, wind_shear: 3 }),
  });
  document.getElementById("in-wind").value = 20;
  document.getElementById("in-vis").value = 500;
  document.getElementById("in-turb").value = 4;
  document.getElementById("in-shear").value = 3;
  document.getElementById("v-wind").textContent = 20;
  document.getElementById("v-vis").textContent = 500;
  refresh();
});

refresh();
setInterval(refresh, 1500);
