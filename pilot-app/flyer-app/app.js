/* =========================================================================
 * 挺中航空 · C 端应用逻辑
 * -------------------------------------------------------------------------
 * 5 个 Tab：首页/态势 · 周边信息 · 起降申请 · 消息 · 我的
 * 核心交互：① 自动决策预判（APPROVE / HOLD / DENY + 原因）
 *          ② 预检状态时间线 + 指令有效期 60s 倒计时
 * 数据：FlyerApi（真实接口 + mock 回退），字段遵循 canonical 契约。
 * ========================================================================= */
(function () {
  'use strict';

  var Mock = window.FlyerMock;
  var Api = window.FlyerApi;
  var MapLib = window.FlyerMap;

  /* ============================ 工具 ============================ */
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function clone(v) { return JSON.parse(JSON.stringify(v)); }
  function arr(v) { return Array.isArray(v) ? v : []; }
  function obj(v) { return v && typeof v === 'object' && !Array.isArray(v) ? v : {}; }
  function esc(v) {
    return String(v == null || v === '' ? '—' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function num(v, d) { var n = Number(v); return isFinite(n) ? n.toFixed(d == null ? 0 : d) : '—'; }
  function pct(a, b) { var n = Number(a) / Number(b); return isFinite(n) ? Math.max(0, Math.min(1, n)) : 0; }
  function clockText(d) {
    d = d || new Date();
    return [d.getHours(), d.getMinutes(), d.getSeconds()].map(function (n) { return String(n).padStart(2, '0'); }).join(':');
  }
  function stamp(offsetSec) {
    var d = new Date(Date.now() + (offsetSec || 0) * 1000);
    return clockText(d);
  }
  function phaseLabel(p) {
    return { APPROACH: '进近', DEPARTURE: '离场', HOVER: '悬停', CRUISE: '巡航', STANDBY: '待命', LANDED: '已落地' }[p] || p || '—';
  }
  function phaseTone(p) {
    return p === 'HOVER' ? 'danger' : p === 'APPROACH' ? 'warn' : (p === 'STANDBY' || p === 'LANDED') ? 'ok' : 'info';
  }
  function haversine(lat1, lon1, lat2, lon2) {
    var R = 6371000, dLat = (lat2 - lat1) * Math.PI / 180, dLon = (lon2 - lon1) * Math.PI / 180;
    var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(a)));
  }
  function fmtDist(m) { return m >= 1000 ? (m / 1000).toFixed(2) + ' km' : Math.round(m) + ' m'; }
  function toast(msg, tone) {
    var root = document.getElementById('toast-root');
    var el = document.createElement('div');
    el.className = 'toast ' + (tone || '');
    el.innerHTML = '<i></i><span>' + esc(msg) + '</span>';
    root.appendChild(el);
    setTimeout(function () { el.classList.add('out'); setTimeout(function () { el.remove(); }, 260); }, 2400);
  }

  /* ============================ 状态 ============================ */
  var TABS = ['home', 'nearby', 'apply', 'messages', 'me'];

  var state = {
    tab: parseTab(),
    snapshot: null,
    program: null,
    ground: null,
    profile: clone(Mock.profile),
    messages: clone(Mock.messages),
    source: { core: 'mock', program: 'mock', ground: 'mock' },
    selectedUav: null,
    selectedTraffic: null,
    applyUav: null,
    applyAction: 'takeoff',
    permit: null,
    lastTick: Date.now(),
    refreshing: false,
    syncTried: false,
    settings: loadSettings()
  };

  function parseTab() {
    var v = location.hash.replace(/^#\/?/, '').split('?')[0];
    return TABS.indexOf(v) >= 0 ? v : 'home';
  }
  function loadSettings() {
    try { return JSON.parse(localStorage.getItem('flyer.settings') || '{}'); } catch (_) { return {}; }
  }
  function saveSettings() {
    try { localStorage.setItem('flyer.settings', JSON.stringify(state.settings)); } catch (_) { }
  }

  /* ============================ 数据 ============================ */
  function normalizeSnapshot(raw) {
    raw = obj(raw);
    if (!raw.airport && !arr(raw.traffic).length) { return null; }
    return {
      schema_version: raw.schema_version || '1.0',
      frame: raw.frame || 'WGS84',
      altitude_ref: raw.altitude_ref || 'MSL',
      generated_at: raw.generated_at || new Date().toISOString(),
      airport: obj(raw.airport),
      obstacles: Array.isArray(raw.obstacles) ? raw.obstacles : null,
      airspaces: Array.isArray(raw.airspaces) ? raw.airspaces : null,
      meteo: obj(raw.meteo),
      program: raw.program ? obj(raw.program) : null,
      traffic: arr(raw.traffic)
    };
  }
  function normalizeGround(raw) {
    raw = obj(raw);
    return { airport_code: raw.airport_code, data_source: raw.data_source, generated_at: raw.generated_at,
      stands: Array.isArray(raw.stands) ? raw.stands : null, rid_targets: arr(raw.rid_targets), sensor: obj(raw.sensor), dispatch: obj(raw.dispatch) };
  }

  function bootstrap() {
    // 先用内置演示数据立即渲染，再后台尝试接入真实服务
    state.snapshot = normalizeSnapshot(Api.getMockSnapshot().data);
    state.program = Api.getMockProgram().data;
    state.ground = normalizeGround(Api.getMockGround().data);
    state.applyUav = state.profile.fleet[0] ? state.profile.fleet[0].id : null;
    render();
    syncAll(false);
  }

  function syncAll(showToast) {
    if (state.refreshing) { return Promise.resolve(); }
    state.refreshing = true;
    setSyncBadge('syncing');

    return Promise.all([Api.snapshot(), Api.program(), Api.ground()]).then(function (res) {
      var snap = res[0], prog = res[1], ground = res[2];
      var liveBefore = state.source.core === 'live';

      var n = snap.ok ? normalizeSnapshot(snap.data) : null;
      state.snapshot = n || normalizeSnapshot(Api.getMockSnapshot().data);
      state.source.core = n ? 'live' : 'mock';

      state.program = prog.ok ? prog.data : Api.getMockProgram().data;
      state.source.program = prog.ok ? 'live' : 'mock';

      if (ground.ok && Array.isArray(obj(ground.data).stands)) {
        state.ground = normalizeGround(ground.data);
        state.source.ground = ground.data.data_source === 'demo' ? 'mock' : 'live';
      } else {
        state.ground = normalizeGround(Api.getMockGround().data); state.source.ground = 'mock';
      }

      state.refreshing = false;
      state.syncTried = true;
      setSyncBadge();
      updateLiveNodes();
      if (liveBefore !== (state.source.core === 'live')) { render(); }
      else if (state.tab === 'apply') { renderApplyBody(); }
      if (showToast) {
        var live = state.source.core === 'live';
        toast(live ? '已同步起降点实时数据' : '未连接到后端，使用内置演示数据', live ? 'ok' : 'warn');
      }
    }).catch(function () {
      state.refreshing = false;
      state.syncTried = true;
      setSyncBadge();
      if (showToast) { toast('同步失败，已回退演示数据', 'warn'); }
    });
  }

  // 测试设置页里填写的后端地址是否可达（打包成 App / 手机真机时最常用）
  function testConnection() {
    var api = ($('#set-api') || {}).value || '';
    var ground = ($('#set-ground') || {}).value || '';
    if (api || ground) { Api.setBackend(api, ground); }
    toast('正在测试连接…', 'info');
    Promise.all([Api.health(), Api.ground()]).then(function (r) {
      var apiOk = r[0].ok, groundOk = r[1].ok;
      if (apiOk && groundOk) { toast('连接正常：后端与地面站服务均可访问', 'ok'); }
      else if (apiOk || groundOk) { toast((apiOk ? '后端 OK' : '后端不通') + ' · ' + (groundOk ? '地面站 OK' : '地面站不通'), 'warn'); }
      else { toast('都连不上：检查地址、服务是否启动、手机与电脑是否同一 Wi-Fi', 'danger'); }
    });
  }

  function setSyncBadge(force) {
    var el = $('#sync-badge');
    if (!el) { return; }
    var live = state.source.core === 'live';
    el.className = 'sync-badge ' + (force === 'syncing' ? 'syncing' : live ? 'live' : 'mock');
    el.textContent = force === 'syncing' ? '同步中' : live ? '实时' : '演示';
  }

  /* --------------------- 演示模式：飞行器缓慢移动 --------------------- */
  function stepTraffic(dtSec) {
    var s = state.snapshot;
    if (!s || state.source.core === 'live') { return; }   // 实时数据不模拟
    var a = s.airport || {};
    s.traffic.forEach(function (t) {
      if (t.phase === 'STANDBY' || t.phase === 'LANDED') { return; }
      var speed = Number(t.speed) || 0;
      if (speed <= 0.2) { return; }

      var d = speed * dtSec;
      var rad = (Number(t.heading) || 0) * Math.PI / 180;
      t.lat += (d * Math.cos(rad)) / 111320;
      t.lon += (d * Math.sin(rad)) / (111320 * Math.cos(t.lat * Math.PI / 180));
      t.alt_msl = Math.max(a.elevation || 0, (Number(t.alt_msl) || 0) + (Number(t.vertical_speed) || 0) * dtSec);

      // 飞出 4 km 折返，保持画面内有目标
      if (haversine(a.lat, a.lon, t.lat, t.lon) > 4000) {
        t.heading = (Number(t.heading) + 180) % 360;
        t.vertical_speed = -Math.abs(Number(t.vertical_speed) || 0.5);
      }
    });
  }

  /* ========================= 自动决策预判 ========================= */
  function evaluate(uav, action) {
    var s = state.snapshot || {};
    var m = obj(s.meteo);
    var shared = window.DemoDecision.evaluate(uav, m);
    var reasons = shared.reasons.slice();
    var level = shared.level;
    function hold(text) { if (level !== 'DENY') { level = 'HOLD'; } reasons.push({ tone: 'warn', text: text }); }

    if (!uav) { return shared; }
    var environment = window.DemoDecision.environment(uav, s);
    if (environment.level === 'DENY') level = 'DENY';
    else if (environment.level === 'HOLD' && level === 'APPROVE') level = 'HOLD';
    reasons = reasons.concat(environment.reasons);
    if (action === 'landing' && state.source.core !== state.source.ground) {
      hold('飞行器与机位数据来源不同，需人工核对');
    }

    if (action === 'landing') {
      var standResult = window.DemoDecision.stands(obj(s.airport).code, state.ground);
      if (standResult.level === 'HOLD' && level !== 'DENY') level = 'HOLD';
      reasons = reasons.concat(standResult.reasons);
    }

    return { level: level, reasons: reasons };
  }

  function verdictMeta(level) {
    if (level === 'APPROVE') { return { label: 'APPROVE 演示预检通过', tone: 'ok', desc: '演示阈值内，仍需人工确认' }; }
    if (level === 'HOLD') { return { label: 'HOLD 建议等待', tone: 'warn', desc: '存在受限项，需确认后执行' }; }
    return { label: 'DENY 暂不可行', tone: 'danger', desc: '存在硬性限制，请处理后重新申请' };
  }

  /* ============================ 许可 ============================ */
  var PERMIT_VALID_SECONDS = 60;

  function submitApply() {
    var uav = trafficById(state.applyUav);
    if (!uav) { toast('请先选择飞行器', 'warn'); return; }
    var ev = evaluate(uav, state.applyAction);
    var now = Date.now();

    state.permit = {
      id: 'CLR-' + now.toString(36).toUpperCase().slice(-6),
      uav_id: uav.id,
      action: state.applyAction,
      level: ev.level,
      reasons: ev.reasons,
      issuedAt: now,
      validSeconds: PERMIT_VALID_SECONDS,
      status: ev.level === 'APPROVE' ? 'approved' : ev.level === 'HOLD' ? 'hold' : 'denied',
      timeline: [
        { ts: clockText(new Date(now)), text: '提交' + (state.applyAction === 'takeoff' ? '起飞' : '降落') + '申请 · ' + uav.id, tone: 'info' },
        { ts: clockText(new Date(now + 300)), text: '自动决策预检完成 · ' + ev.level, tone: ev.level === 'APPROVE' ? 'ok' : ev.level === 'HOLD' ? 'warn' : 'danger' },
        ev.level === 'APPROVE'
          ? { ts: clockText(new Date(now + 700)), text: '演示预检通过 · ' + 'CLR-' + now.toString(36).toUpperCase().slice(-6) + '，有效期 ' + PERMIT_VALID_SECONDS + ' s', tone: 'ok' }
          : { ts: clockText(new Date(now + 700)), text: ev.level === 'HOLD' ? '待人工确认' : '演示预检存在限制，请处理限制项后重新提交', tone: ev.level === 'HOLD' ? 'warn' : 'danger' }
      ]
    };

    if (state.permit.status === 'approved') { startCountdown(); }
    renderApplyBody();
    toast(ev.level === 'APPROVE' ? '演示预检已通过，有效期 60 秒' : ev.level === 'HOLD' ? '待人工确认' : '演示预检存在限制', ev.level === 'APPROVE' ? 'ok' : ev.level === 'HOLD' ? 'warn' : 'danger');
  }

  var countdownTimer = null;
  function startCountdown() {
    stopCountdown();
    countdownTimer = setInterval(tickCountdown, 250);
  }
  function stopCountdown() {
    if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = null; }
  }
  function permitRemain() {
    var p = state.permit;
    if (!p || p.status !== 'approved') { return null; }
    return Math.max(0, p.validSeconds - Math.floor((Date.now() - p.issuedAt) / 1000));
  }
  function tickCountdown() {
    var p = state.permit;
    if (!p) { stopCountdown(); return; }
    var remain = permitRemain();
    if (remain === null) { stopCountdown(); return; }

    var ring = $('#permit-ring');
    var secEl = $('#permit-sec');
    if (ring) {
      var ratio = remain / p.validSeconds;
      ring.style.background = 'conic-gradient(' + (remain <= 10 ? 'var(--red)' : 'var(--cyan)') + ' ' + (ratio * 360) + 'deg, rgba(114,146,181,.14) 0)';
    }
    if (secEl) { secEl.textContent = remain; }

    if (remain <= 0) {
      p.status = 'expired';
      p.timeline.push({ ts: clockText(), text: '预检结果有效期届满（60 s），请重新检查', tone: 'danger' });
      stopCountdown();
      renderApplyBody();
      toast('预检结果已过期，请重新申请', 'warn');
    }
  }

  /* ============================ 渲染 ============================ */
  var mapCtl = null;

  function render() {
    state.tab = parseTab();
    document.body.dataset.tab = state.tab;

    $$('.tabbar a').forEach(function (a) {
      a.classList.toggle('active', a.getAttribute('data-tab') === state.tab);
    });

    var screen = $('#screen');
    var views = { home: renderHome, nearby: renderNearby, apply: renderApply, messages: renderMessages, me: renderMe };
    screen.innerHTML = (views[state.tab] || renderHome)();
    screen.scrollTop = 0;
    afterRender();
  }

  function afterRender() {
    destroyMap();
    if (state.tab === 'home') { mountMap(); }
    if (state.tab === 'apply') { renderApplyBody(); }   // 申请页需要填充预判与许可区
    updateLiveNodes();
    setSyncBadge();
  }

  function destroyMap() {
    if (mapCtl) { try { mapCtl.destroy(); } catch (_) { } mapCtl = null; }
  }

  function mountMap() {
    var canvas = $('#situation-map');
    if (!canvas || !MapLib) { return; }
    mapCtl = MapLib.create(canvas, {
      onPick: function (t) {
        state.selectedTraffic = t.id;
        updateLiveNodes();
        openUavSheet(t.id);
      }
    });
    var a = state.snapshot.airport || {};
    mapCtl.focusOn(a.lat, a.lon, 14);
    pushMapData();
  }

  function pushMapData() {
    if (!mapCtl) { return; }
    mapCtl.setData(state.snapshot, myIds(), state.selectedTraffic);
  }

  function myIds() { return state.profile.fleet.map(function (f) { return f.id; }); }
  function trafficById(id) { return arr((state.snapshot || {}).traffic).find(function (t) { return t.id === id; }); }

  /* ---------------------------- Tab 1 首页 ---------------------------- */
  function renderHome() {
    var s = state.snapshot || {};
    var a = obj(s.airport), m = obj(s.meteo);
    var alerts = homeAlerts();

    return '' +
      connectHint() +
      '<section class="hero-card">' +
        '<div class="hero-top">' +
          '<div><div class="hero-kicker">SKYPORT · ' + esc(a.code) + '</div>' +
          '<h1>' + esc(a.name || '起降点') + '</h1></div>' +
          '<div class="hero-runway"><small>跑道</small><b>' + num(a.runway_heading, 0) + '°</b></div>' +
        '</div>' +
        '<div class="weather-strip">' +
          weatherChip('风速', num(m.wind_speed, 1), 'm/s', 'wind') +
          weatherChip('能见度', num(Number(m.visibility) / 1000, 1), 'km', 'eye') +
          weatherChip('云底高', num(m.cloud_base_agl, 0), 'm', 'cloud') +
          weatherChip('温度', num(m.temperature, 1), '℃', 'temp') +
        '</div>' +
      '</section>' +

      (alerts.length ? '<div class="alert-banner ' + alerts[0].tone + '">' +
        '<span class="alert-pulse"></span>' +
        '<div><b>' + esc(alerts[0].title) + '</b><p>' + esc(alerts[0].body) + '</p></div>' +
        '<span class="alert-count">' + alerts.length + '</span></div>' : '') +

      '<section class="panel map-panel">' +
        '<header class="panel-head"><div><h2>起降点周边态势</h2><p>双指缩放 · 拖动平移 · 点击飞行器查看</p></div>' +
        '<div class="map-actions">' +
          '<button class="icon-btn" data-act="map-in" aria-label="放大">＋</button>' +
          '<button class="icon-btn" data-act="map-out" aria-label="缩小">－</button>' +
          '<button class="icon-btn" data-act="map-reset" aria-label="回到起降点">◎</button>' +
        '</div></header>' +
        '<div class="map-stage"><canvas id="situation-map"></canvas>' +
          '<div class="map-legend"><span><i class="dot mine"></i>我的</span><span><i class="dot other"></i>其他</span><span><i class="sq obs"></i>障碍物</span><span><i class="ln zone"></i>限飞区</span></div>' +
        '</div>' +
      '</section>' +

      '<section class="panel">' +
        '<header class="panel-head"><div><h2>我的飞行器</h2><p>' + state.profile.fleet.length + ' 架 · 左右滑动</p></div>' +
        '<button class="link-btn" data-act="go-apply">申请起降 ↗</button></header>' +
        '<div class="hscroll">' + state.profile.fleet.map(fleetCard).join('') + '</div>' +
      '</section>' +

      '<section class="panel">' +
        '<header class="panel-head"><div><h2>空域动态</h2><p>' + arr(s.airspaces).filter(activeZone).length + ' 个活动区域</p></div></header>' +
        '<div class="list">' + (arr(s.airspaces).length ? arr(s.airspaces).map(zoneRow).join('') : emptyRow('暂无空域数据')) + '</div>' +
      '</section>';
  }

  // 未连上后端时的引导条：打包成 App 后无法自动识别后端地址，需手动填电脑 IP
  function connectHint() {
    if (!state.syncTried || state.source.core === 'live') { return ''; }
    return '<button class="connect-hint" data-act="go-settings">' +
      '<i>!</i><div><b>未连接到起降点服务</b>' +
      '<p>当前为内置演示数据 · 点此填写电脑 / 服务器地址</p></div>' +
      '<span>去设置 ↗</span></button>';
  }

  function weatherChip(label, value, unit, ico) {
    return '<div class="weather-chip"><i class="wc-ico ' + ico + '">' + wIcon(ico) + '</i>' +
      '<div><small>' + label + '</small><b>' + value + '<em>' + unit + '</em></b></div></div>';
  }
  function wIcon(k) { return { wind: '≋', eye: '◉', cloud: '☁', temp: '🌡' }[k] || '·'; }

  function homeAlerts() {
    var out = [];
    arr((state.snapshot || {}).traffic).forEach(function (t) {
      if (t.emergency) { out.push({ tone: 'danger', title: t.id + ' 紧急状态', body: '电量 ' + num(t.battery_pct, 0) + '% · 悬停等待地面确认' }); }
      else if (t.rid_lost) { out.push({ tone: 'warn', title: t.id + ' RID 信号丢失', body: '已进入观察清单，限制进入安全半径' }); }
    });
    return out;
  }

  function fleetCard(f) {
    var t = trafficById(f.id) || {};
    var batt = Number(t.battery_pct) || 0;
    var tone = batt > 50 ? 'ok' : batt > 20 ? 'warn' : 'danger';
    return '<button class="uav-card panel" data-act="open-uav" data-id="' + esc(f.id) + '">' +
      '<header><div><b>' + esc(f.alias) + '</b><small>' + esc(f.model) + ' · ' + esc(f.role) + '</small></div>' +
      '<span class="tag ' + phaseTone(t.phase) + '">' + esc(phaseLabel(t.phase)) + '</span></header>' +
      '<div class="uav-metrics">' +
        '<div><small>高度</small><b data-live="alt-' + esc(f.id) + '">' + num(t.alt_msl, 0) + '<em>m</em></b></div>' +
        '<div><small>速度</small><b data-live="spd-' + esc(f.id) + '">' + num(t.speed, 1) + '<em>m/s</em></b></div>' +
        '<div><small>链路</small><b data-live="lnk-' + esc(f.id) + '">' + num(t.link_quality, 0) + '<em>/5</em></b></div>' +
      '</div>' +
      '<div class="battery"><div class="battery-bar"><i class="' + tone + '" data-live="bat-' + esc(f.id) + '" style="width:' + batt + '%"></i></div>' +
      '<span class="mono">' + num(batt, 0) + '%</span></div>' +
      '<footer><span class="mono">' + esc(f.id) + '</span><span class="go">详情 ↗</span></footer>' +
    '</button>';
  }

  function activeZone(a) { return a && a.active !== false; }
  function zoneRow(a) {
    return '<article class="list-row"><span class="row-ico zone">⬡</span>' +
      '<div><b>' + esc(a.name) + '</b><small>' + num(a.floor_msl, 0) + '–' + num(a.ceiling_msl, 0) + ' m MSL · ' + esc(a.id) + '</small></div>' +
      '<span class="tag ' + (activeZone(a) ? 'warn' : '') + '">' + (activeZone(a) ? '生效' : '停用') + '</span></article>';
  }
  function emptyRow(text) { return '<div class="empty-row">' + esc(text) + '</div>'; }

  /* ---------------------------- Tab 2 周边信息 ---------------------------- */
  function renderNearby() {
    var s = state.snapshot || {};
    var a = obj(s.airport), m = obj(s.meteo), g = obj(state.ground);
    var freeStands = arr(g.stands).filter(function (x) { return x.status === 'free'; });

    return '' +
      '<section class="panel airfield">' +
        '<header class="panel-head"><div><h2>' + esc(a.code) + ' · ' + esc(a.name) + '</h2><p>WGS84 · 海拔基准 MSL</p></div>' +
        '<span class="tag info">起降点</span></header>' +
        '<div class="airfield-grid">' +
          '<div><small>基准标高</small><b>' + num(a.elevation, 0) + '<em>m</em></b></div>' +
          '<div><small>跑道方向</small><b>' + num(a.runway_heading, 0) + '<em>°</em></b></div>' +
          '<div><small>安全半径</small><b>' + num(Number(a.safe_radius) / 1000, 1) + '<em>km</em></b></div>' +
          '<div><small>经纬度</small><b class="sm">' + num(a.lat, 5) + '<br>' + num(a.lon, 5) + '</b></div>' +
        '</div>' +
      '</section>' +

      '<section class="panel">' +
        '<header class="panel-head"><div><h2>气象详情</h2><p>实时观测 · ' + esc(m.turbulence != null ? '湍流 ' + m.turbulence + '/4' : '') + '</p></div>' +
        '<span class="tag ' + (meteoOk(m) ? 'ok' : 'danger') + '">' + (meteoOk(m) ? '达标' : '低于标准') + '</span></header>' +
        '<div class="gauge-row">' +
          gauge('风速', num(m.wind_speed, 1), 'm/s', pct(m.wind_speed, 12), m.wind_speed > 8 ? 'danger' : m.wind_speed > 6 ? 'warn' : 'ok') +
          gauge('能见度', num(Number(m.visibility) / 1000, 1), 'km', pct(m.visibility, 10000), Number(m.visibility) < 1600 ? 'danger' : 'ok') +
          gauge('云底高', num(m.cloud_base_agl, 0), 'm', pct(m.cloud_base_agl, 1200), Number(m.cloud_base_agl) < 120 ? 'danger' : 'ok') +
          gauge('阵风', num(m.gust, 1), 'm/s', pct(m.gust, 18), Number(m.gust) > 12 ? 'warn' : 'ok') +
        '</div>' +
        '<div class="metric-grid">' +
          metric('风向', num(m.wind_dir, 0) + '°') + metric('气压', num(m.pressure, 1) + ' hPa') +
          metric('温度', num(m.temperature, 1) + ' ℃') + metric('露点', num(m.dew_point, 1) + ' ℃') +
          metric('风切变', num(m.wind_shear, 0) + ' / 4') + metric('湍流', num(m.turbulence, 0) + ' / 4') +
        '</div>' +
      '</section>' +

      '<section class="panel">' +
        '<header class="panel-head"><div><h2>空域 / 限飞区</h2><p>' + arr(s.airspaces).length + ' 个区域</p></div></header>' +
        '<div class="list">' + (arr(s.airspaces).length ? arr(s.airspaces).map(zoneRow).join('') : emptyRow('暂无空域数据')) + '</div>' +
      '</section>' +

      '<section class="panel">' +
        '<header class="panel-head"><div><h2>周边障碍物</h2><p>' + arr(s.obstacles).filter(activeZone).length + ' 个生效</p></div></header>' +
        '<div class="list">' + arr(s.obstacles).map(function (o) {
          var a0 = obj(s.airport);
          var d = haversine(a0.lat, a0.lon, o.lat, o.lon);
          return '<article class="list-row"><span class="row-ico obs">△</span>' +
            '<div><b>' + esc(o.name) + '</b><small>' + fmtDist(d) + ' · 顶高 ' + num(o.top_msl, 0) + ' m · 半径 ' + num(o.radius, 0) + ' m</small></div>' +
            '<span class="tag ' + (o.active !== false ? (o.type === 'dynamic' ? 'warn' : 'info') : '') + '">' + (o.active === false ? '停用' : o.type === 'dynamic' ? '动态' : '固定') + '</span></article>';
        }).join('') + '</div>' +
      '</section>' +

      '<section class="panel">' +
        '<header class="panel-head"><div><h2>可用机位</h2><p>' + freeStands.length + ' / ' + arr(g.stands).length + ' 空闲</p></div>' +
        '<span class="tag ' + (state.source.ground === 'live' ? 'ok' : '') + '">' + (state.source.ground === 'live' ? '实时' : '演示') + '</span></header>' +
        '<div class="stand-grid">' + arr(g.stands).map(function (st) {
          var tone = st.status === 'free' ? 'ok' : st.status === 'reserved' ? 'warn' : 'danger';
          var label = { free: '空闲', reserved: '已预约', occupied: '占用' }[st.status] || st.status;
          return '<article class="stand-card ' + st.status + '">' +
            '<header><b>' + esc(st.name) + '</b><span class="tag ' + tone + '">' + label + '</span></header>' +
            '<small>' + (st.type === 'indoor' ? '室内机库' : '室外机坪') + ' · ' + num(st.charge_kw, 0) + ' kW</small>' +
            '<div class="stand-occupant">' + esc(st.occupied_by || '待分配') + '</div>' +
          '</article>';
        }).join('') + '</div>' +
      '</section>';
  }

  function meteoOk(m) {
    return Number(m.visibility) >= 1600 && Number(m.cloud_base_agl) >= 120 && Number(m.wind_speed) <= 8;
  }
  function gauge(label, value, unit, ratio, tone) {
    var deg = Math.round(ratio * 360);
    return '<div class="gauge ' + tone + '">' +
      '<div class="gauge-ring" style="background:conic-gradient(currentColor ' + deg + 'deg, rgba(114,146,181,.13) 0)">' +
      '<span></span></div>' +
      '<b>' + value + '<em>' + unit + '</em></b><small>' + label + '</small></div>';
  }
  function metric(label, value) {
    return '<div class="metric"><small>' + label + '</small><b>' + esc(value) + '</b></div>';
  }

  /* ---------------------------- Tab 3 起降申请 ---------------------------- */
  function renderApply() {
    return '<section class="panel">' +
        '<header class="panel-head"><div><h2>起降申请</h2><p>选择飞行器与动作，系统实时预判</p></div>' +
        '<span class="tag info">C 端申请</span></header>' +
        '<div id="apply-body"></div>' +
      '</section>' +
      '<div id="permit-slot"></div>';
  }

  function renderApplyBody() {
    var slot = $('#apply-body');
    if (!slot) { return; }
    var uav = trafficById(state.applyUav);
    var ev = evaluate(uav, state.applyAction);
    var vm = verdictMeta(ev.level);

    slot.innerHTML = '' +
      '<div class="field-block"><label>① 选择飞行器</label>' +
        '<div class="chip-row">' + state.profile.fleet.map(function (f) {
          var on = f.id === state.applyUav;
          return '<button class="chip ' + (on ? 'on' : '') + '" data-act="pick-uav" data-id="' + esc(f.id) + '">' +
            '<b>' + esc(f.alias) + '</b><small>' + esc(f.model) + '</small></button>';
        }).join('') + '</div>' +
      '</div>' +

      '<div class="field-block"><label>② 选择动作</label>' +
        '<div class="segment">' +
          '<button class="' + (state.applyAction === 'takeoff' ? 'on' : '') + '" data-act="pick-action" data-id="takeoff">🛫 申请起飞</button>' +
          '<button class="' + (state.applyAction === 'landing' ? 'on' : '') + '" data-act="pick-action" data-id="landing">🛬 申请降落</button>' +
        '</div>' +
      '</div>' +

      '<div class="field-block"><label>③ 自动决策预判</label>' +
        '<div class="verdict ' + vm.tone + '">' +
          '<div class="verdict-head"><span class="verdict-badge">' + esc(vm.label) + '</span><small>' + esc(vm.desc) + '</small></div>' +
          '<ul class="reason-list">' + ev.reasons.map(function (r) {
            return '<li class="' + r.tone + '"><i>' + (r.tone === 'ok' ? '✓' : r.tone === 'warn' ? '!' : '✕') + '</i><span>' + esc(r.text) + '</span></li>';
          }).join('') + '</ul>' +
        '</div>' +
      '</div>' +

      '<div class="field-block"><label>④ 提交申请</label>' +
        '<button class="primary-btn" data-act="submit-apply">提交起降申请</button>' +
        '<p class="hint">提交后仅在本机生成演示预检记录，不发送起降申请。</p>' +
      '</div>';

    renderPermitSlot();
  }

  function renderPermitSlot() {
    var slot = $('#permit-slot');
    if (!slot) { return; }
    var p = state.permit;
    if (!p) {
      slot.innerHTML = '<section class="panel permit-empty"><div class="empty-row">尚未提交申请，提交后将在此显示预检状态与有效期倒计时</div></section>';
      return;
    }

    var remain = permitRemain();
    var statusText = { approved: '演示预检已通过', hold: '待人工确认', denied: '演示预检存在限制', expired: '预检结果已过期' }[p.status] || p.status;
    var statusTone = p.status === 'approved' ? 'ok' : p.status === 'hold' ? 'warn' : 'danger';

    slot.innerHTML = '<section class="panel permit-panel">' +
      '<header class="panel-head"><div><h2>预检状态</h2><p class="mono">' + esc(p.id) + ' · ' + esc(p.uav_id) + '</p></div>' +
      '<span class="tag ' + statusTone + '">' + esc(statusText) + '</span></header>' +

      (p.status === 'approved' || p.status === 'expired' ?
        '<div class="countdown">' +
          '<div id="permit-ring" class="count-ring" style="background:conic-gradient(var(--cyan) 360deg, rgba(114,146,181,.14) 0)">' +
            '<div class="count-core"><b id="permit-sec">' + (remain == null ? 0 : remain) + '</b><small>秒</small></div>' +
          '</div>' +
          '<div class="count-copy"><b>' + (p.status === 'expired' ? '预检已过期' : '预检倒计时') + '</b>' +
          '<p>预检有效期内仅供演示参考；实际起降须经人工确认及相应授权。</p>' +
          '<small class="mono">ISSUED ' + stamp(0) + '</small></div>' +
        '</div>' : '') +

      '<div class="timeline">' + p.timeline.map(function (t) {
        return '<article class="' + t.tone + '"><i></i><div><b class="mono">' + esc(t.ts) + '</b><p>' + esc(t.text) + '</p></div></article>';
      }).join('') + '</div>' +
    '</section>';
  }

  /* ---------------------------- Tab 4 消息 ---------------------------- */
  function renderMessages() {
    var groups = [
      ['ATC', '起降许可'], ['C2', 'C2 指令'], ['RID', '远程识别'],
      ['METEO', '气象'], ['ALERT', '系统告警'], ['SYS', '系统通知']
    ];
    var unread = state.messages.filter(function (m) { return !m.read; }).length;

    return '<section class="panel">' +
        '<header class="panel-head"><div><h2>消息与告警</h2><p>' + unread + ' 条未读 · 共 ' + state.messages.length + ' 条</p></div>' +
        '<button class="link-btn" data-act="read-all">全部已读</button></header>' +
        '<div class="msg-list">' + groups.map(function (g) {
          var list = state.messages.filter(function (m) { return m.type === g[0]; });
          if (!list.length) { return ''; }
          return '<div class="msg-group"><div class="group-title">' + g[1] + '<span>' + list.length + '</span></div>' +
            list.map(function (m) {
              return '<button class="msg-item ' + (m.read ? 'read' : '') + ' ' + m.level + '" data-act="read-msg" data-id="' + esc(m.id) + '">' +
                '<span class="msg-dot"></span>' +
                '<div><div class="msg-top"><b>' + esc(m.title) + '</b><time class="mono">' + esc(m.ts) + '</time></div>' +
                '<p>' + esc(m.body) + '</p></div></button>';
            }).join('') + '</div>';
        }).join('') + '</div>' +
      '</section>';
  }

  /* ---------------------------- Tab 5 我的 ---------------------------- */
  function renderMe() {
    var p = state.profile;
    return '<section class="panel profile-card">' +
        '<div class="avatar">' + esc(String(p.name || '飞').slice(0, 1)) + '</div>' +
        '<div class="profile-main"><h2>' + esc(p.name) + '</h2><p>' + esc(p.org) + ' · ' + esc(p.phone) + '</p>' +
        '<div class="profile-tags"><span class="tag ' + (p.real_name_verified ? 'ok' : 'warn') + '">' + (p.real_name_verified ? '实名已核验' : '待核验') + '</span>' +
        '<span class="tag info">' + esc(p.qualification) + '</span></div></div>' +
      '</section>' +

      '<section class="panel">' +
        '<header class="panel-head"><div><h2>虚拟注册资料</h2><p>用于演示预检</p></div></header>' +
        '<div class="kv-list">' +
          kv('飞手编号', p.pilot_id) + kv('实名登记号', p.license_no) +
          kv('唯一产品识别码', p.ua_id) + kv('资质有效期', p.valid_until) +
          kv('常驻起降点', p.home_airport) +
        '</div>' +
      '</section>' +

      '<section class="panel">' +
        '<header class="panel-head"><div><h2>我的飞行器</h2><p>' + p.fleet.length + ' 架已绑定</p></div>' +
        '<button class="link-btn" data-act="add-uav">＋ 绑定</button></header>' +
        '<div class="list">' + p.fleet.map(function (f) {
          var t = trafficById(f.id) || {};
          return '<article class="list-row"><span class="row-ico uav">✦</span>' +
            '<div><b>' + esc(f.alias) + '</b><small>' + esc(f.model) + ' · ' + esc(f.id) + ' · ' + esc(phaseLabel(t.phase)) + '</small></div>' +
            '<button class="icon-btn danger" data-act="unbind" data-id="' + esc(f.id) + '" aria-label="解绑">✕</button></article>';
        }).join('') + '</div>' +
      '</section>' +

      '<section class="panel">' +
        '<header class="panel-head"><div><h2>设置</h2><p>后端地址可配，留空则用内置演示数据</p></div></header>' +
        '<div class="form-row"><label>机场 / UTM 服务</label>' +
          '<input id="set-api" type="url" inputmode="url" placeholder="http://127.0.0.1:8082" value="' + esc(state.settings.baseUrl || Api.config.baseUrl) + '" /></div>' +
        '<div class="form-row"><label>地面站服务</label>' +
          '<input id="set-ground" type="url" inputmode="url" placeholder="http://127.0.0.1:8090" value="' + esc(state.settings.groundUrl || Api.config.groundUrl) + '" /></div>' +
        '<div class="btn-row">' +
          '<button class="ghost-btn" data-act="test-conn">测试连接</button>' +
          '<button class="primary-btn" data-act="save-settings">保存并同步</button>' +
        '</div>' +
        '<p class="hint">填电脑（或机场服务器）的局域网地址，例如 <b class="mono">http://192.168.1.20:8082</b>。<br>' +
        '装成 App 后无法自动识别后端，需在此填写一次（地址会记住）。</p>' +
      '</section>' +

      '<section class="panel">' +
        '<header class="panel-head"><div><h2>关于</h2></div></header>' +
        '<div class="kv-list">' + kv('应用', '挺中航空 · C 端') + kv('版本', 'v1.0.0') +
        kv('数据源', state.source.core === 'live' ? '实时接口' : '内置演示') +
        kv('运行容器', window.Capacitor ? 'Android App' : location.protocol === 'file:' ? '本地文件' : '浏览器') +
        kv('后端地址', Api.config.baseUrl) + '</div>' +
      '</section>';
  }

  function kv(k, v) { return '<div class="kv"><small>' + esc(k) + '</small><b>' + esc(v) + '</b></div>'; }

  /* ------------------------ 局部刷新（不重建 DOM） ------------------------ */
  function updateLiveNodes() {
    var s = state.snapshot || {};
    var m = obj(s.meteo);

    var chips = $$('.weather-chip b');
    if (chips[0]) { chips[0].innerHTML = num(m.wind_speed, 1) + '<em>m/s</em>'; }
    if (chips[1]) { chips[1].innerHTML = num(Number(m.visibility) / 1000, 1) + '<em>km</em>'; }
    if (chips[2]) { chips[2].innerHTML = num(m.cloud_base_agl, 0) + '<em>m</em>'; }
    if (chips[3]) { chips[3].innerHTML = num(m.temperature, 1) + '<em>℃</em>'; }

    state.profile.fleet.forEach(function (f) {
      var t = trafficById(f.id) || {};
      setLive('alt-' + f.id, num(t.alt_msl, 0) + '<em>m</em>');
      setLive('spd-' + f.id, num(t.speed, 1) + '<em>m/s</em>');
      setLive('lnk-' + f.id, num(t.link_quality, 0) + '<em>/5</em>');
      var bar = $('[data-live="bat-' + f.id + '"]');
      if (bar) {
        var b = Number(t.battery_pct) || 0;
        bar.style.width = b + '%';
        bar.className = b > 50 ? 'ok' : b > 20 ? 'warn' : 'danger';
        var label = bar.parentNode && bar.parentNode.nextElementSibling;
        if (label) { label.textContent = num(b, 0) + '%'; }
      }
    });

    pushMapData();
  }
  function setLive(key, html) {
    var el = $('[data-live="' + key + '"]');
    if (el) { el.innerHTML = html; }
  }

  /* ============================ 弹层 ============================ */
  function openUavSheet(id) {
    var t = trafficById(id);
    if (!t) { return; }
    var f = state.profile.fleet.find(function (x) { return x.id === id; });
    var ev = evaluate(t, 'landing');
    var vm = verdictMeta(ev.level);

    var a = obj((state.snapshot || {}).airport);
    var dist = haversine(a.lat, a.lon, t.lat, t.lon);

    sheet(
      (f ? f.alias + ' · ' : '') + t.id,
      t.model + ' · ' + t.reg_no,
      '<div class="sheet-verdict ' + vm.tone + '"><b>' + esc(vm.label) + '</b><small>' + esc(vm.desc) + '</small></div>' +
      '<div class="kv-grid">' +
        kv('飞行相位', phaseLabel(t.phase)) + kv('距起降点', fmtDist(dist)) +
        kv('高度', num(t.alt_msl, 0) + ' m MSL') + kv('地速', num(t.speed, 1) + ' m/s') +
        kv('航向', num(t.heading, 0) + '°') + kv('垂直速度', num(t.vertical_speed, 1) + ' m/s') +
        kv('电量', num(t.battery_pct, 0) + ' %') + kv('链路质量', num(t.link_quality, 0) + ' / 5') +
        kv('RID / UA ID', t.ua_id) + kv('紧急状态', t.emergency ? '是' : '否') +
      '</div>' +
      '<div class="sheet-actions">' +
        '<button class="ghost-btn" data-act="focus-uav" data-id="' + esc(t.id) + '">在图上定位</button>' +
        '<button class="primary-btn" data-act="apply-for" data-id="' + esc(t.id) + '">为它申请起降</button>' +
      '</div>'
    );
  }

  function sheet(title, sub, body) {
    var root = document.getElementById('sheet-root');
    root.innerHTML = '<div class="sheet-backdrop" data-act="close-sheet">' +
      '<div class="sheet" role="dialog" aria-modal="true">' +
        '<div class="sheet-grip"></div>' +
        '<header class="sheet-head"><div><h2>' + esc(title) + '</h2><p>' + esc(sub) + '</p></div>' +
        '<button class="icon-btn" data-act="close-sheet" aria-label="关闭">✕</button></header>' +
        '<div class="sheet-body">' + body + '</div>' +
      '</div></div>';
    root.classList.add('show');
  }
  function closeSheet() {
    var root = document.getElementById('sheet-root');
    root.classList.remove('show');
    setTimeout(function () { if (!root.classList.contains('show')) { root.innerHTML = ''; } }, 220);
  }

  /* ============================ 事件 ============================ */
  document.addEventListener('click', function (e) {
    var tab = e.target.closest('.tabbar a');
    if (tab) { return; }                                   // 交给 hashchange

    var el = e.target.closest('[data-act]');
    if (!el) { return; }
    var act = el.getAttribute('data-act');
    var id = el.getAttribute('data-id');

    switch (act) {
      case 'close-sheet': if (e.target.classList.contains('sheet-backdrop') || e.target.closest('.icon-btn')) { closeSheet(); } break;
      case 'map-in': if (mapCtl) { mapCtl.zoom(0.75); } break;
      case 'map-out': if (mapCtl) { mapCtl.zoom(1.35); } break;
      case 'map-reset': if (mapCtl) { mapCtl.resetView(state.snapshot); } break;
      case 'go-apply': location.hash = '#/apply'; break;
      case 'open-uav': openUavSheet(id); break;
      case 'focus-uav': closeSheet(); if (mapCtl) { var t = trafficById(id); if (t) { mapCtl.focusOn(t.lat, t.lon, 9); } } break;
      case 'apply-for': closeSheet(); state.applyUav = id; location.hash = '#/apply'; setTimeout(renderApplyBody, 0); break;
      case 'pick-uav': state.applyUav = id; renderApplyBody(); break;
      case 'pick-action': state.applyAction = id; renderApplyBody(); break;
      case 'submit-apply': submitApply(); break;
      case 'read-msg': {
        var msg = state.messages.find(function (m) { return m.id === id; });
        if (msg) { msg.read = true; render(); }
        break;
      }
      case 'read-all': state.messages.forEach(function (m) { m.read = true; }); render(); toast('已全部标记为已读', 'ok'); break;
      case 'unbind': {
        state.profile.fleet = state.profile.fleet.filter(function (f) { return f.id !== id; });
        toast('已解绑 ' + id, 'warn'); render(); break;
      }
      case 'add-uav': toast('演示模式：绑定入口将在接入真实账户服务后开放', 'warn'); break;
      case 'go-settings': location.hash = '#/me'; break;
      case 'test-conn': testConnection(); break;
      case 'save-settings': {
        state.settings.baseUrl = ($('#set-api') || {}).value || '';
        state.settings.groundUrl = ($('#set-ground') || {}).value || '';
        saveSettings();
        Api.setBackend(state.settings.baseUrl, state.settings.groundUrl);
        toast('已保存，正在重新同步…', 'ok');
        syncAll(true);
        break;
      }
    }
  });

  window.addEventListener('hashchange', function () {
    if (parseTab() !== state.tab) { render(); } else { state.tab = parseTab(); }
  });

  /* ---------------------------- 下拉刷新 ---------------------------- */
  (function pullToRefresh() {
    var screen = document.getElementById('screen');
    var startY = 0, pulling = false, indicator = null;

    screen.addEventListener('touchstart', function (e) {
      if (screen.scrollTop <= 0 && e.touches.length === 1) { startY = e.touches[0].clientY; pulling = true; }
      else { pulling = false; }
    }, { passive: true });

    screen.addEventListener('touchmove', function (e) {
      if (!pulling) { return; }
      var dy = e.touches[0].clientY - startY;
      if (dy > 60) {
        if (!indicator) { indicator = document.createElement('div'); indicator.className = 'pull-hint'; indicator.textContent = '松手刷新'; screen.prepend(indicator); }
      }
    }, { passive: true });

    screen.addEventListener('touchend', function (e) {
      if (indicator) { indicator.remove(); indicator = null; toast('正在刷新…', 'info'); syncAll(true); }
      pulling = false;
    });
  }());

  /* ============================ 主循环 ============================ */
  var tickCount = 0;
  function tick() {
    var now = Date.now();
    var dt = Math.min(0.5, (now - state.lastTick) / 1000);
    state.lastTick = now;

    stepTraffic(dt);
    pushMapData();                        // 250ms 推进一次，飞行器移动更顺滑

    tickCount++;
    if (tickCount % 4 === 0) {            // 文本类每秒刷新一次，避免频繁重排
      updateLiveNodes();
      var c = $('#hud-clock');
      if (c) { c.textContent = clockText(); }
    }
  }

  /* ============================ 启动 ============================ */
  function boot() {
    bootstrap();
    setInterval(tick, 250);
    setInterval(function () { syncAll(false); }, 15000);   // 15s 轮询真实接口
  }

  /* 调试 / 自动化入口（只读引用，不影响正常运行） */
  window.FlyerApp = {
    state: state, evaluate: evaluate, verdictMeta: verdictMeta,
    render: render, bootstrap: bootstrap, submitApply: submitApply,
    permitRemain: permitRemain, syncAll: syncAll
  };

  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', boot); }
  else { boot(); }

  /* Service Worker（http/https 下启用离线缓存） */
  if ('serviceWorker' in navigator && location.protocol.indexOf('http') === 0) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('sw.js').catch(function () { });
    });
  }
}());
