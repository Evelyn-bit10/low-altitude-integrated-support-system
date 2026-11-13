/* =========================================================================
 * 低空起降点—飞行器实时通讯与态势系统（网页演示）
 * -------------------------------------------------------------------------
 * 设计参考（仅演示思路，不替代官方标准）：
 * 1) 《无人驾驶航空器飞行管理暂行条例》(2024-01-01 施行)
 *    - 实名登记、唯一产品识别码、飞行活动申请、隔离飞行等要求；
 * 2) CCAR-92 部《民用无人驾驶航空器运行安全管理规则》
 *    - 运行分类、运营合格证、远程识别(RID)、C2 链路余度等；
 * 3) 《民用无人驾驶航空器空中交通管理信息服务系统数据接口规范》
 *    (MH/T 系列) 风格的消息封装：消息头 + 载荷的 JSON 结构；
 * 4) RID 广播数据字段参考 ASTM F3411 思路：Basic ID / 位置 / 高度 /
 *    速度矢量 / 航向 / 操作者位置 / 时间戳 / 紧急状态；
 * 5) 起降点障碍物限制面与最低气象标准为演示阈值，可配置。
 * ========================================================================= */
(function () {
  "use strict";

  /* ----------------------------- 可调参数 ----------------------------- */
  const CONFIG = {
    vertiportId: "ZBTJ-VP-01",                 // 起降点编号（天津示例）
    c2RangeM: 6000,                            // C2 链路覆盖半径（米）
    ridIntervalMs: 1000,                       // RID 广播周期（要求 ≤1s）
    heartbeatIntervalMs: 3000,                 // 飞行器心跳周期
    posReportIntervalMs: 2000,                 // 位置报告周期
    metIntervalMs: 5000,                       // 气象更新周期（演示加速）
    trailMax: 40,                              // 航迹点数
    // 起降最低气象标准（演示阈值，可配置）
    metMin: { visibilityM: 1600, ceilingM: 120, windMs: 8.0 },
    // 冲突判定余量
    obstacleMarginM: 60,
    obstacleAltMarginM: 40,
  };

  // 与 flycontrol 的双向同步配置(可覆盖 baseUrl)
  const SYNC = {
    enabled: true,
    baseUrl: (typeof window !== "undefined" && window.LAC_SYNC_BASE) || "http://127.0.0.1:8080",
    snapshotIntervalMs: 3000,   // 周期拉取统一快照(环境/气象/程序)
    pushIntervalMs: 1000,       // 周期回传飞行器态势
    timeoutMs: 2000,
  };

  /* ----------------------------- 工具函数 ----------------------------- */
  const $ = (id) => document.getElementById(id);
  const now = () => new Date();
  const pad = (n, l = 2) => String(n).padStart(l, "0");
  const fmtTime = (d = new Date()) =>
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  const fmtClock = (d = new Date()) =>
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${fmtTime(d)}`;
  const rnd = (a, b) => a + Math.random() * (b - a);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const deg2rad = (d) => (d * Math.PI) / 180;
  const dist2d = (x1, y1, x2, y2) => Math.hypot(x2 - x1, y2 - y1);
  const fmtM = (m) => (m >= 1000 ? (m / 1000).toFixed(2) + " km" : Math.round(m) + " m");

  function makeMsgId() {
    return "MSG-" + Date.now().toString(36).toUpperCase() + "-" +
      Math.random().toString(36).slice(2, 6).toUpperCase();
  }

  /* ----------------------------- 初始数据 ----------------------------- */
  // 起降点位于坐标原点，x 向东(米)，y 向北(米)
  const obstacles = [
    { id: "OBS-01", name: "北侧高层建筑", x: 0,    y: 820,  height: 150, radius: 60,  type: "building" },
    { id: "OBS-02", name: "东北通讯铁塔", x: 850,  y: 850,  height: 220, radius: 30,  type: "tower" },
    { id: "OBS-03", name: "东侧山体",     x: 2790, y: 240,  height: 410, radius: 400, type: "mountain" },
    { id: "OBS-04", name: "东南电线杆群", x: 350,  y: -350, height: 35,  radius: 15,  type: "poles" },
    { id: "OBS-05", name: "西南水塔",     x: -500, y: -500, height: 55,  radius: 25,  type: "tower" },
    { id: "OBS-06", name: "西侧建筑群",   x: -1480,y: -180, height: 120, radius: 120, type: "building" },
  ];

  // 电子围栏多边形（起降场保护区，相对坐标）
  const fencePoly = [
    { x: -260, y: -520 }, { x: 260, y: -520 }, { x: 320, y: 0 },
    { x: 260, y: 520 }, { x: -260, y: 520 }, { x: -320, y: 0 },
  ];

  const uasTemplates = [
    {
      id: "UAS-2024-0001", model: "EH216-S 物流型", regNo: "UA-12H7K9Q3",
      uaId: "1581F3A7C2D94B6E", phase: "APPROACH", alt: 100, speed: 16, heading: 135,
      x: -420, y: 380, vs: -2.5, battery: 72, route: [
        { x: -420, y: 380, alt: 100 }, { x: -200, y: 180, alt: 70 },
        { x: -40, y: 40, alt: 30 },
        { x: 0, y: 0, alt: 0 },
      ],
    },
    {
      id: "UAS-2024-0002", model: "DJI M350 RTK 巡检", regNo: "UA-33B8T2F6",
      uaId: "1581F9E1A0C74D2B", phase: "HOVER", alt: 120, speed: 4, heading: 0,
      x: 620, y: 90, vs: 0, battery: 81, route: [
        { x: 620, y: 90, alt: 120 }, { x: 640, y: 120, alt: 121 },
        { x: 600, y: 140, alt: 119 }, { x: 570, y: 100, alt: 120 },
        { x: 590, y: 70, alt: 121 },
      ],
    },
    {
      id: "UAS-2024-0003", model: "复合翼 FX-3", regNo: "UA-56C4P8A1",
      uaId: "1581F6B2D8E04C9A", phase: "DEPARTURE", alt: 65, speed: 18, heading: 225,
      x: -230, y: -190, vs: 3.5, battery: 92, route: [
        { x: -230, y: -190, alt: 65 }, { x: -420, y: -410, alt: 110 },
        { x: -640, y: -640, alt: 160 }, { x: -900, y: -900, alt: 220 },
        { x: -1200, y: -1180, alt: 280 }, { x: -1500, y: -1480, alt: 350 },
      ],
    },
    {
      id: "UAS-2024-0004", model: "FP-981C 物流", regNo: "UA-77A1M5X8",
      uaId: "1581F4C0B6A24E7D", phase: "CRUISE", alt: 300, speed: 26, heading: 60,
      x: 3800, y: -2500, vs: 0, battery: 55, route: [
        { x: 3800, y: -2500, alt: 300 }, { x: 2600, y: -1700, alt: 280 },
        { x: 1600, y: -1000, alt: 240 }, { x: 800, y: -450, alt: 180 },
        { x: 320, y: -160, alt: 100 }, { x: 120, y: -60, alt: 70 },
      ],
    },
    {
      id: "UAS-2024-0005", model: "CW-15 测绘", regNo: "UA-91D3R6W2",
      uaId: "1581F8A5E3B04C1F", phase: "STANDBY", alt: 0, speed: 0, heading: 0,
      x: 150, y: 210, vs: 0, battery: 100, route: [
        { x: 150, y: 210, alt: 0 }, { x: 150, y: 210, alt: 0 },
      ],
    },
  ];

  /* ----------------------------- 状态 ----------------------------- */
  const state = {
    flights: [],
    weather: null,
    weatherHist: [],
    messages: [],          // 通讯面板消息
    logs: [],              // 系统事件
    alerts: [],            // 活动告警
    selectedUasId: null,
    occupied: false,
      degraded: { rid: false, met: false, c2: false },
      link: { rssi: -62, latencyMs: 42, lossPct: 0.4, msgCount: 0 },
    simTime: 0,            // 演示秒
    ridLostUntil: {},      // id -> 恢复时间（模拟 RID 丢失）
    scripted: {},          // 已执行的脚本 id
    external: false,       // 是否已连接 flycontrol（双向同步）
    externalAirport: null,
    externalAirspaces: [], // 来自 flycontrol 的空域（ENU）
    externalProgram: null, // 来自 flycontrol 的飞行程序（ENU）
  };

  /* ----------------------------- 气象模拟 ----------------------------- */
  function generateWeather(t) {
    // 构造一段能见度变差再恢复的过程，用于演示气象告警
    let vis = 9000 - 3200 * Math.sin(t / 55) - 900 * Math.sin(t / 13);
    if (t > 42 && t < 78) vis = Math.min(vis, 1500 - 260 * Math.abs(Math.sin((t - 42) / 6)));
    vis = Math.max(700, Math.round(vis / 50) * 50);

    const windDir = Math.round(120 + 40 * Math.sin(t / 30));
    let wind = clamp(2.8 + 2.6 * Math.sin(t / 17) + rnd(-0.6, 0.6), 0.5, 14);
      if (t > 42 && t < 78) wind = Math.max(wind, 7.6 + 2.4 * Math.abs(Math.sin((t - 42) / 5)));
    const gust = wind + rnd(1.5, 3.2);
    let ceiling = Math.max(60, Math.round((2000 - 620 * Math.sin(t / 40)) / 10) * 10);
      if (t > 50 && t < 66) ceiling = 90;
    const temp = 26 + 4 * Math.sin(t / 90);
    const dew = temp - rnd(4, 7);
    return {
      station: CONFIG.vertiportId,
      timestamp: new Date().toISOString(),
      windDir, wind, gust, ceiling,
      visibility: vis,
      temp: Math.round(temp * 10) / 10,
      dewPoint: Math.round(dew * 10) / 10,
      qnh: Math.round(1011 + 4 * Math.sin(t / 60)),
      phenomenon: vis < 1600 ? "BR（轻雾）" : vis < 5000 ? "HZ（霾）" : "CAVOK",
    };
  }

  function metBelowStandard(w) {
    const below = [];
    if (w.visibility < CONFIG.metMin.visibilityM) below.push("能见度");
    if (w.ceiling < CONFIG.metMin.ceilingM) below.push("云底高");
    if (w.wind > CONFIG.metMin.windMs) below.push("风速");
    return below;
  }

  /* ----------------------------- RID 报文 ----------------------------- */
  function buildRidMessage(uas) {
    return {
      protocol: "CAAC-RID-BROADCAST/1.0",
      messageHeader: {
        messageType: "RID_BROADCAST",
        messageId: makeMsgId(),
        sender: uas.id,
        receiver: "BROADCAST",
        timestamp: new Date().toISOString(),
      },
      payload: {
        basicId: { uaId: uas.uaId, regNo: uas.regNo, type: "CAA_Registration" },
        position: { x_m: Math.round(uas.x), y_m: Math.round(uas.y), alt_m: Math.round(uas.alt) },
        velocity: {
          groundSpeed_ms: +uas.speed.toFixed(1),
          heading_deg: Math.round(uas.heading),
          verticalSpeed_ms: +uas.vs.toFixed(1),
        },
        operator: { lat: 39.125 + uas.x / 111000, lon: 117.346 + uas.y / 96000, distance_m: Math.round(Math.hypot(uas.x, uas.y)) },
        flightPhase: uas.phase,
        emergencyStatus: uas.emergency ? "EMERGENCY" : "NONE",
        batteryPct: Math.round(uas.battery),
        linkQuality: uas.linkQuality,
        timestamp: new Date().toISOString(),
      },
    };
  }

  /* ----------------------------- 起降点报文 ----------------------------- */
  function buildAtcMessage(type, targetId, payload) {
    return {
      protocol: "CAAC-UTM-C2/1.0",
      messageHeader: {
        messageType: type,
        messageId: makeMsgId(),
        sender: CONFIG.vertiportId,
        receiver: targetId,
        timestamp: new Date().toISOString(),
      },
      payload: payload || {},
    };
  }

  function buildUasMessage(type, payload) {
    return {
      protocol: "CAAC-UTM-C2/1.0",
      messageHeader: {
        messageType: type,
        messageId: makeMsgId(),
        sender: null, // 由调用方填
        receiver: CONFIG.vertiportId,
        timestamp: new Date().toISOString(),
      },
      payload: payload || {},
    };
  }

  /* ----------------------------- 通讯引擎 ----------------------------- */
  function addMessage(cls, type, from, to, text, detail) {
    state.messages.push({ cls, type, from, to, text, detail, time: fmtTime() });
    if (state.messages.length > 120) state.messages.splice(0, state.messages.length - 120);
    state.link.msgCount++;
    renderMessages();
  }

  function addLog(cls, text) {
    state.logs.unshift({ cls, text, time: fmtTime() });
    if (state.logs.length > 40) state.logs.pop();
    renderLogs();
  }

  function addAlert(id, text, level) {
    if (state.alerts.some((a) => a.id === id)) return;
    state.alerts.push({ id, text, level, time: fmtTime() });
    addLog(level === "bad" ? "bad" : "warn", "告警：" + text);
    renderAlerts();
  }

  function clearAlert(id) {
    const before = state.alerts.length;
    state.alerts = state.alerts.filter((a) => a.id !== id);
    if (state.alerts.length !== before) {
      addLog("ok", "告警解除：" + id);
      renderAlerts();
    }
  }

  function atcSend(type, targetId, payload) {
    const t = state.flights.find((f) => f.id === targetId);
    const isDirective = type.startsWith("ATC_CLEARANCE") || type === "HOLD_INSTRUCTION" || type === "GO_AROUND";
    if (isDirective && payload && typeof payload === "object") {
      payload.validUntil = new Date(Date.now() + 60 * 1000).toISOString(); // 指令有效期 60s，超时自动失效
      payload.revalidate = true;
    }
    const msg = buildAtcMessage(type, targetId, payload);
    addMessage("from-atc", type, CONFIG.vertiportId, targetId, type, JSON.stringify(msg.payload));
    if (t) {
      if (type === "GO_AROUND" && t.phase !== "LANDED") {
        t.routeDir = -1;          // 复飞：调转航线方向，飞离起降点
        t.vs = Math.abs(t.vs) + 1;
        addLog("warn", `${t.id} 收到复飞指令，调整航向等待天气好转。`);
      }
      if (type === "ATC_CLEARANCE_LAND" && t.routeDir === -1) {
        t.routeDir = 1;           // 重新许可后调头进近
      }
      scheduleUasAck(t, type);
    }
    return msg;
  }

  function uasSend(uas, type, payload, cls) {
    const msg = buildUasMessage(type, payload);
    msg.messageHeader.sender = uas.id;
    addMessage(cls || "from-uas", type, uas.id, CONFIG.vertiportId, type, JSON.stringify(msg.payload));
    return msg;
  }

  // 飞行器收到指令后的自动应答
  function scheduleUasAck(uas, cmdType) {
    setTimeout(() => {
      if (!state.flights.find((f) => f.id === uas.id)) return;
      uasSend(uas, "C2_ACK", { ackFor: cmdType, accepted: true, note: "收到，按指令执行。" });
    }, 900 + rnd(200, 600));
  }

  /* ----------------------------- 飞行器初始化 ----------------------------- */
  function initFlights() {
    state.flights = uasTemplates.map((tpl) => {
      const p0 = tpl.route[0];
      return {
        id: tpl.id, model: tpl.model, regNo: tpl.regNo, uaId: tpl.uaId,
        phase: tpl.phase, x: tpl.x, y: tpl.y, alt: tpl.alt,
        speed: tpl.speed, baseSpeed: tpl.speed,
        heading: tpl.heading, vs: tpl.vs, battery: tpl.battery,
        route: tpl.route.slice(), routeIdx: 0, routeDir: 1,
        emergency: false, linkQuality: 4 + Math.round(Math.random()),
        trail: [], lastRidAt: 0, lastHbAt: 0, lastPosAt: 0,
      };
    });
  }

  /* ----------------------------- 飞行器运动 ----------------------------- */
  function updateFlightMotion(f, dtSec) {
    if (f.phase === "STANDBY" || f.phase === "LANDED") return;
    const route = f.route;
    if (!route.length) return;
    f.routeIdx = clamp(f.routeIdx, 0, route.length - 1);
    const target = route[f.routeIdx];
    const dx = target.x - f.x;
    const dy = target.y - f.y;
    const dAlt = target.alt - f.alt;
    const dh = Math.hypot(dx, dy);
    const step = f.baseSpeed * dtSec;
    const vStep = Math.max(1.5, Math.abs(f.vs) * dtSec + 1);

    // 水平、垂直均到达航路点容差内 → 切到下一航路点
    if (dh <= step + 0.5 && Math.abs(dAlt) <= vStep + 0.5) {
      f.x = target.x; f.y = target.y; f.alt = target.alt;
      if (f.id === "UAS-2024-0001" && Math.hypot(f.x, f.y) < 1 && f.alt < 1) {
        f.phase = "LANDED"; f.speed = 0; f.vs = 0;
        addLog("ok", `${f.id} 已降落到位，C2 链路保持。`);
        return;
      }
      // 航线反转（ping-pong），保持航迹连续
      if (f.routeDir === 1 && f.routeIdx === route.length - 1) {
        f.routeDir = -1;
        f.routeIdx = Math.max(0, route.length - 2);
      } else if (f.routeDir === -1 && f.routeIdx === 0) {
        f.routeDir = 1;
        f.routeIdx = Math.min(route.length - 1, 1);
      } else {
        f.routeIdx += f.routeDir;
      }
    } else {
      // 水平接近但高度差还大 → 只修高度，避免水平震荡
      if (dh <= step + 0.5) {
        f.alt += Math.sign(dAlt) * Math.max(1.5, Math.abs(f.vs) * dtSec);
      } else {
        f.x += (dx / dh) * step;
        f.y += (dy / dh) * step;
        f.heading = (Math.atan2(dx, dy) * 180) / Math.PI; // 北为0，顺时针
        if (f.heading < 0) f.heading += 360;
      }
      if (Math.abs(dAlt) <= vStep + 0.5) {
        f.alt = target.alt;
      } else {
        f.alt += Math.sign(dAlt) * Math.max(1.5, Math.abs(f.vs) * dtSec);
      }
      f.speed = f.baseSpeed;
    }
    f.alt = clamp(f.alt, 0, 500);
  }

  function updateFlightPhase(f) {
    if (f.id === "UAS-2024-0001" && f.phase !== "LANDED") f.phase = "APPROACH";
    if (f.id === "UAS-2024-0003") f.phase = f.alt > 200 ? "CRUISE" : "DEPARTURE";
    if (f.id === "UAS-2024-0004") f.phase = f.alt < 120 ? "APPROACH" : "CRUISE";
    if (f.id === "UAS-2024-0002") f.phase = "HOVER";
    if (f.phase === "LANDED") { f.speed = 0; f.vs = 0; f.alt = 0; }
  }

  /* ----------------------------- 冲突与告警 ----------------------------- */
  function runConflictDetection() {
    const w = state.weather;
    // 气象告警
    if (w) {
      const below = metBelowStandard(w);
      if (below.length) {
        addAlert("MET-BELOW-STD", `气象低于起降标准：${below.join("、")}（${w.visibility}m / ${w.ceiling}m / ${w.wind.toFixed(1)}m/s）`, "bad");
        if (!state.scripted["met-warn-msg"]) {
          state.scripted["met-warn-msg"] = true;
          atcSend("WEATHER_BROADCAST", "ALL", { ...w, warning: true, minima: CONFIG.metMin });
          addMessage("alert", "MET-ALERT", CONFIG.vertiportId, "ALL", "气象告警", "能见度/云底高/风速低于起降标准，暂停起降，等待天气好转。");
        }
      } else {
        clearAlert("MET-BELOW-STD");
      }
    }

    // 障碍物冲突
    for (const f of state.flights) {
      if (f.phase === "LANDED" || f.phase === "STANDBY") continue;
      let anyConflict = false;
      for (const o of obstacles) {
        const d = dist2d(f.x, f.y, o.x, o.y);
        const conflict = d < o.radius + CONFIG.obstacleMarginM &&
                         f.alt < o.height + CONFIG.obstacleAltMarginM;
        if (conflict) {
          anyConflict = true;
          const id = `OBS-CONFLICT-${f.id}-${o.id}`;
          addAlert(id, `${f.id} 与障碍物「${o.name}」水平距离 ${Math.round(d)}m、高度 ${Math.round(f.alt)}m，低于障碍高度 ${o.height}m，存在冲突风险！`, "bad");
          if (!state.scripted[id]) {
            state.scripted[id] = true;
            atcSend("OBSTACLE_ALERT", f.id, { obstacle: o.name, distance_m: Math.round(d), uasAlt_m: Math.round(f.alt), obstacleAlt_m: o.height, action: "立即拉升或改航避让" });
          }
        } else {
          clearAlert(`OBS-CONFLICT-${f.id}-${o.id}`);
        }
      }
      f.emergency = anyConflict;
    }

    // RID 丢失告警（在 RID 接收逻辑中处理）
  }

  /* ----------------------------- RID 接收模拟 ----------------------------- */
  function receiveRid(f) {
    const nowMs = Date.now();
    // 模拟偶发 RID 丢失：0.2% 概率丢失 3~6 秒
    if (!state.ridLostUntil[f.id] && Math.random() < 0.002) {
      state.ridLostUntil[f.id] = nowMs + rnd(3000, 6000);
      addLog("warn", `${f.id} RID 广播丢失，进入告警观察（要求广播间隔 ≤1s）。`);
    }
    if (state.ridLostUntil[f.id] && nowMs < state.ridLostUntil[f.id]) {
      f.ridLost = true;
      addAlert(`RID-LOST-${f.id}`, `${f.id} 超过 3 个广播周期未收到 RID 报文！`, "warn");
      return;
    }
    if (state.ridLostUntil[f.id] && nowMs >= state.ridLostUntil[f.id]) {
      state.ridLostUntil[f.id] = null;
      f.ridLost = false;
      clearAlert(`RID-LOST-${f.id}`);
      addLog("ok", `${f.id} RID 广播恢复。`);
    }
    f.lastRidAt = nowMs;
    // 更新链路质量
    f.linkQuality = clamp(3 + Math.round(rnd(0, 2) + (f.ridLost ? -2 : 0)), 1, 5);
  }

  /* ----------------------------- 自动通讯脚本 ----------------------------- */
  function runScriptedComms(t) {
    if (t === 5 && !state.scripted["script-0003-takeoff"]) {
      state.scripted["script-0003-takeoff"] = true;
      const f = getFlight("UAS-2024-0003");
      uasSend(f, "TAKEOFF_REQUEST", { alt_m: 200, heading_deg: 225, reason: "执行巡检任务，申请起飞。" });
      setTimeout(() => atcSend("ATC_CLEARANCE_TAKEOFF", f.id, { approved: true, runway: "VP-01-A", altLimit_m: 300 }), 2000);
    }
    if (t === 10 && !state.scripted["script-0001-land"]) {
      state.scripted["script-0001-land"] = true;
      const f = getFlight("UAS-2024-0001");
      uasSend(f, "LANDING_REQUEST", { alt_m: 180, distance_m: Math.round(Math.hypot(f.x, f.y)), eta_s: 32 });
      setTimeout(() => atcSend("ATC_CLEARANCE_LAND", f.id, { approved: true, pad: "PAD-01", wind: state.weather ? `${state.weather.wind.toFixed(1)} m/s @ ${state.weather.windDir}°` : "-" }), 2500);
    }
    if (t === 16 && !state.scripted["script-0002-hover"]) {
      state.scripted["script-0002-hover"] = true;
      const f = getFlight("UAS-2024-0002");
      uasSend(f, "POSITION_REPORT", { alt_m: 120, hover: true, mission: "起降点周边巡检悬停" });
    }
    if (t === 22 && !state.scripted["script-0005-hold"]) {
      state.scripted["script-0005-hold"] = true;
      const f = getFlight("UAS-2024-0005");
      uasSend(f, "TAKEOFF_REQUEST", { alt_m: 150, heading_deg: 0, reason: "测绘任务申请起飞。" });
      setTimeout(() => atcSend("HOLD_INSTRUCTION", f.id, { reason: "空域占用，原地等待 60 秒后重新申请。" }), 1800);
    }
    if (t === 32 && !state.scripted["script-0005-clear"]) {
      state.scripted["script-0005-clear"] = true;
      const f = getFlight("UAS-2024-0005");
      atcSend("ATC_CLEARANCE_TAKEOFF", f.id, { approved: true, runway: "VP-01-A", altLimit_m: 200 });
      f.phase = "DEPARTURE";
      f.baseSpeed = 10; f.speed = 10; f.vs = 2.5;
      f.route = [
        { x: 150, y: 210, alt: 0 }, { x: 200, y: 320, alt: 60 },
        { x: 300, y: 520, alt: 120 }, { x: 480, y: 820, alt: 180 },
      ];
      f.routeIdx = 0;
    }
    if (t === 58 && !state.scripted["script-rid-lost"]) {
      state.scripted["script-rid-lost"] = true;
      state.ridLostUntil["UAS-2024-0002"] = Date.now() + 4000;
      addLog("warn", "注入演示事件：UAS-2024-0002 RID 广播丢失 4 秒（模拟遮挡/干扰）。");
    }
    if (t === 50 && !state.scripted["script-0004-in"]) {
      state.scripted["script-0004-in"] = true;
      const f = getFlight("UAS-2024-0004");
      uasSend(f, "POSITION_REPORT", { alt_m: 300, distance_m: Math.round(Math.hypot(f.x, f.y)), eta_s: 95, note: "申请进入起降点空域。" });
    }
    if (t === 68 && !state.scripted["script-0004-land"]) {
      state.scripted["script-0004-land"] = true;
      const f = getFlight("UAS-2024-0004");
      uasSend(f, "LANDING_REQUEST", { alt_m: 200, distance_m: Math.round(Math.hypot(f.x, f.y)), eta_s: 30 });
      setTimeout(() => atcSend("GO_AROUND", f.id, { reason: "能见度低于标准，终止进近，复飞等待。" }), 2000);
    }
    if (t === 82 && !state.scripted["script-0004-land2"]) {
      state.scripted["script-0004-land2"] = true;
      const f = getFlight("UAS-2024-0004");
      uasSend(f, "LANDING_REQUEST", { alt_m: 240, distance_m: Math.round(Math.hypot(f.x, f.y)), eta_s: 35, note: "天气好转，重新申请降落。" });
      setTimeout(() => atcSend("ATC_CLEARANCE_LAND", f.id, { approved: true, pad: "PAD-02" }), 2400);
    }
  }

  function getFlight(id) {
    return state.flights.find((f) => f.id === id);
  }

    /* 起降许可自动决策引擎（简化演示：输入 RID 合法性 / 气象 / 障碍物 / 占用状态） */
    function autoDecision(f) {
      if (!f || f.ridLost) return { result: "DENY", reason: "RID 远程识别不可用，禁止接入" };
      const w = state.weather;
      if (state.degraded.met) return { result: "DENY", reason: "气象源失效，切人工值守，禁止自动许可" };
      const below = w ? metBelowStandard(w) : ["气象源失效"];
      if (below.length) return { result: "DENY", reason: `气象低于起降标准（${below.join("、")}）` };
      const inConflict = state.alerts.some((a) => a.id.startsWith(`OBS-CONFLICT-${f.id}-`));
      if (inConflict) return { result: "DENY", reason: "进近存在障碍物冲突" };
      if (state.occupied && f.id !== "UAS-2024-0001") return { result: "DENY", reason: "起降点占用" };
      if (w && (w.visibility < 5000 || w.wind > 6)) return { result: "ADVISE_HOLD", reason: "气象条件受限，建议等待" };
      return { result: "APPROVE", reason: "满足起降条件" };
    }

  /* ----------------------------- 渲染：列表 ----------------------------- */
  function renderUasList() {
    const box = $("uas-list");
    const frag = document.createDocumentFragment();
    for (const f of state.flights) {
      const card = document.createElement("div");
      card.className = "uas-card" + (f.id === state.selectedUasId ? " active" : "") + (f.ridLost ? " lost" : "");
      card.onclick = () => { selectUas(f.id); };
      const phaseTxt = { APPROACH: "进近", DEPARTURE: "离场", HOVER: "悬停", CRUISE: "巡航", STANDBY: "待命", LANDED: "已降落" }[f.phase] || f.phase;
      const phaseCls = f.phase === "HOVER" ? "hover" : f.phase === "APPROACH" ? "approach" : f.phase === "EMERGENCY" ? "emergency" : "";
      const batt = Math.round(f.battery);
      card.innerHTML =
        `<div class="r1"><span class="callsign">${f.id}</span><span class="phase ${phaseCls}">${phaseTxt}</span></div>
         <div class="r2"><span>${f.model}</span><span>${Math.round(f.alt)} m</span></div>
         <div class="r2"><span>${fmtM(Math.hypot(f.x, f.y))} · ${f.speed.toFixed(1)} m/s</span><span>🔋 ${batt}%</span></div>
         <div class="bar"><i style="width:${batt}%"></i></div>`;
      frag.appendChild(card);
    }
    box.innerHTML = "";
    box.appendChild(frag);
    $("uas-count").textContent = state.flights.filter((f) => !f.ridLost).length + " 架在线";
  }

  function renderUasDetail() {
    const box = $("uas-detail");
    const f = getFlight(state.selectedUasId);
    if (!f) { box.textContent = "尚未选中"; return; }
    const rid = buildRidMessage(f);
      const dec = autoDecision(f);
      const decBadge = dec.result === "APPROVE" ? "🟢 APPROVE 许可" : dec.result === "ADVISE_HOLD" ? "🟡 HOLD 建议等待" : "🔴 " + dec.result + " 拒绝/告警";
    box.innerHTML =
      `<div style="color:#eaf3ff">${f.id}（${f.model}）</div>
       <div>登记号：${f.regNo}</div>
       <div>唯一识别码：${f.uaId}</div>
       <div>位置：X ${Math.round(f.x)} m / Y ${Math.round(f.y)} m / H ${Math.round(f.alt)} m</div>
       <div>速度：${f.speed.toFixed(1)} m/s · 航向 ${Math.round(f.heading)}° · 升降 ${f.vs.toFixed(1)} m/s</div>
       <div>距起降点：${fmtM(Math.hypot(f.x, f.y))} · 电池 ${Math.round(f.battery)}%</div>
       <div>链路质量：${"▮".repeat(f.linkQuality)}${"▯".repeat(5 - f.linkQuality)} · 紧急：${f.emergency ? "是" : "否"}</div>
       <div style="margin-top:4px;color:#eaf3ff">自动决策：${decBadge}${dec.reason ? " · " + dec.reason : ""}</div>
         <div style="color:#7f9bc4">RID 最后报文：${f.ridLost ? "丢失" : "正常"} · ${fmtTime()}</div>`;
  }

  /* ----------------------------- 渲染：消息/日志 ----------------------------- */
  function renderMessages() {
    const box = $("msg-stream");
    const frag = document.createDocumentFragment();
    for (const m of state.messages.slice(-60)) {
      const div = document.createElement("div");
      div.className = "msg " + m.cls;
      div.innerHTML = `<div class="mh"><span>${m.time}</span><span>${m.from} → ${m.to}</span></div>
        <div class="mt">${m.type}</div>
        <div class="mp">${escapeHtml(m.detail || "")}</div>`;
      frag.appendChild(div);
    }
    box.innerHTML = "";
    box.appendChild(frag);
    box.scrollTop = box.scrollHeight;
  }

  function renderLogs() {
    const box = $("log-list");
    box.innerHTML = state.logs.map((l) =>
      `<div class="log-item ${l.cls}">[${l.time}] ${escapeHtml(l.text)}</div>`).join("");
  }

  function renderAlerts() {
    const el = $("st-alert");
    const n = state.alerts.length;
    el.textContent = "告警 " + n;
    el.className = "status-item " + (n > 0 ? "bad" : "warn");
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  /* ----------------------------- 渲染：气象/障碍物 ----------------------------- */
  function renderWeather() {
    const w = state.weather;
    if (!w) return;
    $("met-time").textContent = "更新 " + fmtTime() + " · " + w.station;
    $("met-wind").textContent = w.windDir + "°";
    $("met-speed").textContent = w.wind.toFixed(1) + " m/s";
    $("met-gust").textContent = w.gust.toFixed(1) + " m/s";
    $("met-vis").textContent = w.visibility + " m";
    $("met-ceil").textContent = w.ceiling + " m";
    $("met-temp").textContent = w.temp + " / " + w.dewPoint + " ℃";
    $("met-press").textContent = w.qnh + " hPa";
    const below = metBelowStandard(w);
    const stdEl = $("met-std");
    stdEl.textContent = below.length ? "低于标准" : "达标";
    stdEl.parentElement.className = "met-cell " + (below.length ? "bad" : "ok");
    document.querySelectorAll(".met-cell").forEach((c) => c.classList.remove("warn"));
    if (w.visibility < 3000) $("met-vis").parentElement.classList.add("warn");
    if (w.wind > 6) $("met-speed").parentElement.classList.add("warn");
  }

  function renderObstacles() {
    const box = $("obs-list");
    box.innerHTML = obstacles.map((o) => {
      const d = fmtM(Math.hypot(o.x, o.y));
      const conflict = state.alerts.some((a) => a.id.startsWith("OBS-CONFLICT-") && a.id.endsWith("-" + o.id));
      return `<div class="obs-item ${conflict ? "conflict" : ""}">
        <span class="nm">${o.name}</span><span class="ds">${d} · H ${o.height}m</span></div>`;
    }).join("");
  }

  /* ----------------------------- 态势图 ----------------------------- */
  const canvas = $("map");
  const ctx = canvas.getContext("2d");
  let zoomRange = 6000;

  function canvasToWorld(px, py, scale) {
    const w = canvas.width, h = canvas.height;
    return { x: (px - w / 2) * scale, y: (h / 2 - py) * scale };
  }

  function worldToCanvas(x, y, scale) {
    return { px: canvas.width / 2 + x / scale, py: canvas.height / 2 - y / scale };
  }

  function drawMap() {
    const w = canvas.width, h = canvas.height;
    const scale = zoomRange / (w / 2);   // 米/像素
    ctx.clearRect(0, 0, w, h);

    // 背景
    const bg = ctx.createRadialGradient(w / 2, h / 2, 60, w / 2, h / 2, w / 2);
    bg.addColorStop(0, "#0c1a30"); bg.addColorStop(1, "#070f1d");
    ctx.fillStyle = bg; ctx.fillRect(0, 0, w, h);

    // 网格
    ctx.strokeStyle = "rgba(47,155,255,0.07)";
    ctx.lineWidth = 1;
    const gridStep = zoomRange / 8;
    for (let i = -8; i <= 8; i++) {
      const p = worldToCanvas(i * gridStep, 0, scale);
      ctx.beginPath(); ctx.moveTo(p.px, 0); ctx.lineTo(p.px, h); ctx.stroke();
      const p2 = worldToCanvas(0, i * gridStep, scale);
      ctx.beginPath(); ctx.moveTo(0, p2.py); ctx.lineTo(w, p2.py); ctx.stroke();
    }

    // C2 覆盖圈
    if ($("chk-range").checked) {
      ctx.setLineDash([6, 6]);
      ctx.strokeStyle = "rgba(47,155,255,0.55)";
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.arc(w / 2, h / 2, CONFIG.c2RangeM / scale, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "rgba(47,155,255,0.5)";
      ctx.font = "11px Consolas";
      ctx.fillText("C2 覆盖半径 6 km", w / 2 + 8, h / 2 - CONFIG.c2RangeM / scale + 10);
    }

    // 电子围栏（本地演示模式）
    if ($("chk-fence").checked && !state.external) {
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = "rgba(255,77,94,0.85)";
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      fencePoly.forEach((pt, i) => {
        const p = worldToCanvas(pt.x, pt.y, scale);
        i === 0 ? ctx.moveTo(p.px, p.py) : ctx.lineTo(p.px, p.py);
      });
      ctx.closePath();
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "rgba(255,77,94,0.75)";
      ctx.font = "10px Consolas";
      const fp = worldToCanvas(fencePoly[0].x, fencePoly[0].y, scale);
      ctx.fillText("电子围栏（保护空域）", fp.px + 4, fp.py - 4);
    }

    // 空域 / 限飞区（来自 flycontrol）
    if ($("chk-fence").checked && state.external) {
      for (const a of state.externalAirspaces) {
        if (!a.polygon || !a.polygon.length) continue;
        ctx.setLineDash([4, 4]);
        ctx.strokeStyle = "rgba(251,191,36,0.85)";
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        a.polygon.forEach((pt, i) => {
          const p = worldToCanvas(pt.x, pt.y, scale);
          i === 0 ? ctx.moveTo(p.px, p.py) : ctx.lineTo(p.px, p.py);
        });
        ctx.closePath();
        ctx.stroke();
        ctx.setLineDash([]);
        const pc = worldToCanvas(a.polygon[0].x, a.polygon[0].y, scale);
        ctx.fillStyle = "rgba(251,191,36,0.8)";
        ctx.font = "10px 'Microsoft YaHei'";
        ctx.fillText(a.name || "限飞区", pc.px + 4, pc.py - 4);
      }
    }

    // 跑道 / 起降点
    const vp = worldToCanvas(0, 0, scale);
    ctx.fillStyle = "rgba(47,155,255,0.12)";
    ctx.fillRect(vp.px - 26, vp.py - 3, 52, 6);
    ctx.strokeStyle = "#2f9bff"; ctx.lineWidth = 2;
    ctx.strokeRect(vp.px - 26, vp.py - 3, 52, 6);
    ctx.beginPath();
    ctx.arc(vp.px, vp.py, 7, 0, Math.PI * 2);
    ctx.fillStyle = "#2f9bff"; ctx.fill();
    ctx.fillStyle = "#eaf3ff"; ctx.font = "bold 11px Consolas"; ctx.textAlign = "center";
    ctx.fillText("H", vp.px, vp.py + 4);
    ctx.fillStyle = "rgba(214,230,255,0.9)"; ctx.font = "11px 'Microsoft YaHei'";
    ctx.fillText(CONFIG.vertiportId, vp.px, vp.py - 14);
    ctx.textAlign = "left";

    // 障碍物
    if ($("chk-obstacle").checked) {
      for (const o of obstacles) {
        const p = worldToCanvas(o.x, o.y, scale);
        const conflict = state.alerts.some((a) => a.id.startsWith("OBS-CONFLICT-") && a.id.endsWith("-" + o.id));
        ctx.fillStyle = conflict ? "rgba(255,77,94,0.25)" : "rgba(255,176,32,0.16)";
        ctx.beginPath();
        ctx.arc(p.px, p.py, Math.max(5, o.radius / scale), 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = conflict ? "#ff4d5e" : "#ffb020";
        ctx.lineWidth = conflict ? 1.8 : 1;
        ctx.stroke();
        if (o.type === "tower" || o.type === "poles") {
          ctx.beginPath();
          ctx.moveTo(p.px - 4, p.py); ctx.lineTo(p.px, p.py - 14); ctx.lineTo(p.px + 4, p.py);
          ctx.strokeStyle = conflict ? "#ff4d5e" : "#ffb020";
          ctx.stroke();
        }
        ctx.fillStyle = conflict ? "#ff4d5e" : "#ffb020";
        ctx.font = "10px Consolas";
        ctx.fillText(`${o.name} ${o.height}m`, p.px + 6, p.py - 4);
      }
    }

    // 飞行程序航路（来自 flycontrol 的进近/离场程序）
    if (state.externalProgram && state.externalProgram.waypoints && state.externalProgram.waypoints.length) {
      const wps = state.externalProgram.waypoints;
      ctx.setLineDash([8, 5]);
      ctx.strokeStyle = "rgba(52,211,153,0.85)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      wps.forEach((w, i) => {
        const p = worldToCanvas(w.x, w.y, scale);
        i === 0 ? ctx.moveTo(p.px, p.py) : ctx.lineTo(p.px, p.py);
      });
      ctx.stroke();
      ctx.setLineDash([]);
      const p0 = worldToCanvas(wps[0].x, wps[0].y, scale);
      ctx.fillStyle = "rgba(52,211,153,0.95)";
      ctx.font = "10px 'Microsoft YaHei'";
      ctx.fillText("飞行程序·" + (state.externalProgram.type || "") + " " + (state.externalProgram.version || ""), p0.px + 6, p0.py - 4);
    }

    // 飞行器航迹
    for (const f of state.flights) {
      if (f.trail.length > 1 && $("chk-trail").checked) {
        ctx.setLineDash([2, 3]);
        ctx.strokeStyle = f.id === state.selectedUasId ? "rgba(39,224,216,0.7)" : "rgba(37,208,125,0.4)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        f.trail.forEach((pt, i) => {
          const p = worldToCanvas(pt.x, pt.y, scale);
          i === 0 ? ctx.moveTo(p.px, p.py) : ctx.lineTo(p.px, p.py);
        });
        ctx.stroke();
        ctx.setLineDash([]);
      }
      // 飞行器
      const p = worldToCanvas(f.x, f.y, scale);
      const color = f.emergency ? "#ff4d5e" : f.ridLost ? "#ffb020" : f.id === state.selectedUasId ? "#27e0d8" : "#25d07d";
      const rad = deg2rad(f.heading);
      ctx.save();
      ctx.translate(p.px, p.py);
      ctx.rotate(rad); // 航向0=北=向上；canvas 正角为顺时针，直接用航向弧度
      ctx.beginPath();
      ctx.moveTo(0, -9); ctx.lineTo(6, 7); ctx.lineTo(0, 3); ctx.lineTo(-6, 7);
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.fill();
      ctx.restore();
      ctx.fillStyle = color;
      ctx.font = "10px Consolas";
      ctx.fillText(`${f.id} ${Math.round(f.alt)}m`, p.px + 9, p.py - 5);
    }

    // 比例尺
    const barM = zoomRange / 8;
    ctx.fillStyle = "rgba(214,230,255,0.55)";
    ctx.fillRect(w - 100, h - 18, 80, 2);
    ctx.fillRect(w - 100, h - 20, 2, 6);
    ctx.fillRect(w - 20, h - 20, 2, 6);
    ctx.font = "10px Consolas";
    ctx.fillText(fmtM(barM), w - 96, h - 6);
  }

  function selectUas(id) {
    state.selectedUasId = id;
    renderUasList();
    renderUasDetail();
    renderSelectedInfo();
  }

  function renderSelectedInfo() {
    const el = $("selected-info");
    const f = getFlight(state.selectedUasId);
    if (!f) { el.textContent = "点击飞行器查看 RID 详情"; return; }
    el.innerHTML = `已选中 ${f.id}<br>${f.model}<br>${Math.round(f.alt)}m · ${f.speed.toFixed(1)}m/s · ${fmtM(Math.hypot(f.x, f.y))}`;
  }

  canvas.addEventListener("click", (e) => {
    const rect = canvas.getBoundingClientRect();
    const px = (e.clientX - rect.left) * (canvas.width / rect.width);
    const py = (e.clientY - rect.top) * (canvas.height / rect.height);
    const scale = zoomRange / (canvas.width / 2);
    let best = null, bestD = 24;
    for (const f of state.flights) {
      const p = worldToCanvas(f.x, f.y, scale);
      const d = Math.hypot(p.px - px, p.py - py);
      if (d < bestD) { best = f; bestD = d; }
    }
    if (best) selectUas(best.id);
  });

  /* ----------------------------- UI 事件 ----------------------------- */
  function fillCmdTargets() {
    const sel = $("cmd-target");
    sel.innerHTML = '<option value="ALL">ALL（广播）</option>' +
      state.flights.map((f) => `<option value="${f.id}">${f.id}</option>`).join("");
  }

  $("btn-send").addEventListener("click", () => {
    const target = $("cmd-target").value;
    const type = $("cmd-type").value;
    const f = getFlight(target);
    if (target === "ALL") {
      atcSend(type, "ALL", { note: "广播指令", text: $("cmd-type").selectedOptions[0].textContent });
      for (const u of state.flights) if (u.phase !== "LANDED" && u.phase !== "STANDBY") scheduleUasAck(u, type);
    } else if (f) {
      atcSend(type, target, { note: $("cmd-type").selectedOptions[0].textContent });
    }
  });

  $("btn-free").addEventListener("click", () => {
    const text = $("msg-free").value.trim();
    if (!text) return;
    const target = $("cmd-target").value;
    const msg = buildAtcMessage("C2_FREE_TEXT", target, { text });
    addMessage("from-atc", "C2_FREE_TEXT", CONFIG.vertiportId, target, "C2_FREE_TEXT", JSON.stringify(msg.payload));
    $("msg-free").value = "";
    if (target !== "ALL") {
      const f = getFlight(target);
      if (f) setTimeout(() => uasSend(f, "C2_ACK", { ackFor: "C2_FREE_TEXT", accepted: true, note: "已收到自由报文。" }), 800);
    }
  });

  $("zoom-level").addEventListener("change", (e) => { zoomRange = +e.target.value; });
  ["chk-obstacle", "chk-fence", "chk-range", "chk-trail"].forEach((id) => {
    $(id).addEventListener("change", () => {});
  });

  /* ----------------------------- 双向同步（flycontrol） ----------------------------- */
  function syncSetStatus(text, cls) {
    const el = $("st-sync");
    if (el) { el.textContent = text; el.className = "status-item " + (cls || ""); }
  }

  function applySnapshot(snap) {
    if (!snap || !snap.airport || typeof window.LAC === "undefined") return false;
    const mapped = window.LAC.snapshotToCommunication(snap);
    if (!mapped) return false;

    // 1) 起降点身份与坐标原点对齐 flycontrol
    CONFIG.vertiportId = mapped.airport.code;
    window.LAC.geo.setOrigin(mapped.airport.lat, mapped.airport.lon, mapped.airport.elevation);

    // 2) 以 flycontrol 为权威数据源：替换障碍物 / 空域 / 气象
    obstacles.length = 0;
    obstacles.push(...mapped.obstacles);
    state.externalAirspaces = mapped.airspaces || [];
    state.externalProgram = mapped.program || null;

    if (mapped.weather) {
      state.weather = mapped.weather;
      state.weather.phenomenon =
        mapped.weather.visibility < 1600 ? "BR（轻雾）"
        : mapped.weather.visibility < 5000 ? "HZ（霾）" : "CAVOK";
      renderWeather();
    }

    state.external = true;
    state.externalAirport = mapped.airport;
    return true;
  }

  async function syncPullSnapshot() {
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), SYNC.timeoutMs);
      const r = await fetch(SYNC.baseUrl + "/api/sync/snapshot", { cache: "no-store", signal: ctrl.signal });
      clearTimeout(timer);
      if (!r.ok) throw new Error("HTTP " + r.status);
      const snap = await r.json();
      if (applySnapshot(snap)) {
        syncSetStatus("已连接 flycontrol", "ok");
        return true;
      }
    } catch (e) {
      // flycontrol 未启动 / 网络不可达 → 保持本地演示
    }
    syncSetStatus("本地演示", "warn");
    return false;
  }

  async function pushTraffic() {
    if (!state.external || typeof window.LAC === "undefined") return;
    const payload = window.LAC.trafficListFromCommunication(state.flights);
    if (!payload.length) return;
    try {
      await fetch(SYNC.baseUrl + "/api/traffic/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch (e) { /* 单次推送失败忽略，下个周期重试 */ }
  }

  /* ----------------------------- 主循环 ----------------------------- */
  let lastTick = Date.now();
  let lastSyncPull = 0;
  let lastTrafficPush = 0;

  function tick() {
    const nowMs = Date.now();
    const dtSec = Math.min(0.5, (nowMs - lastTick) / 1000);
    lastTick = nowMs;
    state.simTime += dtSec;
    const t = state.simTime;

    // 1) 飞行器运动
    for (const f of state.flights) {
      updateFlightMotion(f, dtSec);
      updateFlightPhase(f);
      // 航迹
      if (f.phase !== "LANDED" && f.phase !== "STANDBY") {
        f.trail.push({ x: f.x, y: f.y });
        if (f.trail.length > CONFIG.trailMax) f.trail.shift();
      }
    }

    // 2) RID 接收（1s 周期）
    if (Math.floor(nowMs / CONFIG.ridIntervalMs) !== Math.floor((nowMs - dtSec * 1000) / CONFIG.ridIntervalMs) || !state.ridTickDone) {
      state.ridTickDone = true;
      for (const f of state.flights) {
        if (f.phase === "LANDED" || f.phase === "STANDBY") {
          f.lastRidAt = nowMs; // 地面待命/已降落仍广播 RID
        }
        receiveRid(f);
      }
    }

    // 3) 飞行器自动报文（心跳 / 位置报告，轮询避免刷屏）
    for (const f of state.flights) {
      if (f.phase === "LANDED") continue;
      if (nowMs - f.lastHbAt > CONFIG.heartbeatIntervalMs) {
        f.lastHbAt = nowMs;
        if (Math.random() < 0.5) {
          uasSend(f, "HEARTBEAT", { c2Status: "ONLINE", batteryPct: Math.round(f.battery), linkQuality: f.linkQuality, mode: f.phase });
        }
      }
      if (nowMs - f.lastPosAt > CONFIG.posReportIntervalMs) {
        f.lastPosAt = nowMs;
        if (Math.random() < 0.4) {
          uasSend(f, "POSITION_REPORT", { x_m: Math.round(f.x), y_m: Math.round(f.y), alt_m: Math.round(f.alt), heading_deg: Math.round(f.heading), groundSpeed_ms: +f.speed.toFixed(1) });
        }
      }
    }

    // 4) 气象更新（5s 周期；连接 flycontrol 后以快照气象为准，不再本地模拟）
    if (!state.external && nowMs - (state.lastMetAt || 0) > CONFIG.metIntervalMs) {
      state.lastMetAt = nowMs;
      state.weather = generateWeather(t);
      renderWeather();
      const below = metBelowStandard(state.weather);
      if (!below.length) addLog("ok", `气象更新：${state.weather.visibility}m / 风 ${state.weather.wind.toFixed(1)}m/s / 云底 ${state.weather.ceiling}m，起降标准达标。`);
      else addLog("warn", `气象更新：${below.join("、")}低于起降标准（${state.weather.visibility}m / 风 ${state.weather.wind.toFixed(1)}m/s / 云底 ${state.weather.ceiling}m）。`);
    }

    // 5) 自动通讯脚本
    runScriptedComms(Math.floor(t));

    // 6) 冲突检测
    runConflictDetection();
      state.occupied = state.flights.some((f) =>
        (f.phase === "APPROACH" || f.phase === "DEPARTURE" || f.phase === "HOVER") &&
        Math.hypot(f.x, f.y) < 500);

    // 7) 链路指标
    state.link.latencyMs = Math.round(clamp(38 + 18 * Math.sin(t / 7) + rnd(-6, 6), 18, 180));
    state.link.lossPct = +clamp(0.15 + 0.35 * Math.sin(t / 13) + rnd(-0.1, 0.1), 0, 2.5).toFixed(2);
    state.link.rssi = Math.round(clamp(-66 + 6 * Math.sin(t / 9) + rnd(-2, 2), -90, -45));
    $("lm-latency").textContent = state.link.latencyMs + " ms";
    $("lm-loss").textContent = state.link.lossPct + " %";
    $("lm-rssi").textContent = state.link.rssi + " dBm";
    $("lm-msg").textContent = state.link.msgCount + " 条";
    const delayOk = state.link.latencyMs <= 500;
    $("comp-delay").textContent = delayOk ? "✔ 符合" : "✘ 超时";
    $("comp-delay").className = delayOk ? "ok" : "bad";
    $("st-link").className = "status-item " + (state.link.lossPct < 5 && delayOk ? "ok" : "bad");
    $("st-link").textContent = `C2链路 ${delayOk && state.link.lossPct < 5 ? "正常" : "劣化"}`;
      state.degraded.c2 = !(delayOk && state.link.lossPct < 5);
      state.degraded.rid = state.flights.some((f) => f.ridLost);
      state.degraded.met = false; // 演示中气象源在线；生产环境气象源失效应切人工值守并禁止自动许可

    // 8) 时钟与通用渲染
    $("st-clock").textContent = fmtClock();
    renderUasList();
    renderUasDetail();
    renderObstacles();
    drawMap();

    // 9) RID 状态
    const anyLost = state.flights.some((f) => f.ridLost);
    $("st-rid").className = "status-item " + (anyLost ? "bad" : "ok");
    $("st-rid").textContent = anyLost ? "RID 丢失" : "RID 正常";
    const belowStd = state.weather && metBelowStandard(state.weather).length > 0;
    $("st-met").className = "status-item " + (belowStd ? "bad" : "ok");
    $("st-met").textContent = belowStd ? "气象低于标准" : "气象 正常";

    // 10) 与 flycontrol 双向同步（拉快照 / 推态势）
    if (SYNC.enabled && typeof window.LAC !== "undefined") {
      const syncNow = Date.now();
      if (syncNow - lastTrafficPush > SYNC.pushIntervalMs) {
        lastTrafficPush = syncNow;
        pushTraffic();
      }
      if (syncNow - lastSyncPull > SYNC.snapshotIntervalMs) {
        lastSyncPull = syncNow;
        syncPullSnapshot();
      }
    }
  }

  /* ----------------------------- 启动 ----------------------------- */
  initFlights();
  state.weather = generateWeather(0);
  state.lastMetAt = Date.now();
  fillCmdTargets();
  renderWeather();
  renderObstacles();
  renderAlerts();
  addLog("ok", "系统启动：起降点 C2 / RID / MET / 障碍物态势融合在线。");
  addLog("ok", `RID 广播周期 ${CONFIG.ridIntervalMs / 1000}s，C2 覆盖 ${CONFIG.c2RangeM / 1000}km，气象更新 ${CONFIG.metIntervalMs / 1000}s（演示加速）。`);
  addLog("warn", "演示数据为模拟生成，仅用于说明通讯软件系统思路，不构成运行标准。");
  addMessage("sys", "SYS", CONFIG.vertiportId, "ALL", "系统就绪", "起降点通讯软件系统已启动，开始接收 RID 广播与飞行器 C2 报文。");

  // 尝试连接 flycontrol，建立双向同步（失败则保持本地演示）
  if (SYNC.enabled && typeof window.LAC !== "undefined") {
    syncSetStatus("连接中…", "warn");
    syncPullSnapshot().then((ok) => {
      if (ok) addLog("ok", "已连接 flycontrol 后端，双向同步建立：环境/气象/飞行程序来自 flycontrol，飞行器态势回传 flycontrol。");
    });
  } else {
    syncSetStatus("本地演示", "warn");
  }

  // 初始选中 1 号机
  selectUas("UAS-2024-0001");

  setInterval(tick, 250);
  tick();
})();
