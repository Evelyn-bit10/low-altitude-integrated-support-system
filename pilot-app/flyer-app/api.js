/* =========================================================================
 * 挺中航空 · 统一数据出口
 * -------------------------------------------------------------------------
 * 统一接口层：优先请求真实服务，失败/超时自动回退内置演示数据，
 * 页面在任何情况下都不会白屏。
 *
 * 预留接口（后期对接真实机场只需改下面 defaults 的地址）：
 *   flycontrol / 机场 UTM 服务   baseUrl   默认 http://127.0.0.1:8082
 *   groundstation 地面站服务     groundUrl 默认 http://127.0.0.1:8090
 *
 * 字段一律遵循统一契约 canonical（WGS84 经纬度 + 海拔 MSL + snake_case）。
 * ========================================================================= */
(function () {
  'use strict';

  var M = window.FlyerMock;

  // 后端地址默认按「当前页面所在主机」推导：
  //   电脑上访问             -> 127.0.0.1
  //   手机上访问 192.168.x.x -> 192.168.x.x（同一台电脑上的 flycontrol / 地面站桥）
  // 这样手机真机无需任何配置，就能连到与网页端完全相同的后端。
  var PAGE_HOST = (location.hostname && location.hostname !== 'localhost') ? location.hostname : '127.0.0.1';

  var defaults = {
    baseUrl: 'http://' + PAGE_HOST + ':8082',     // flycontrol / 真实机场 UTM
    groundUrl: 'http://' + PAGE_HOST + ':8090',   // 地面站数据服务
    timeoutMs: 2400
  };

  // 允许外部覆盖（URL 参数 ?api=... 或 window.FLYER_CONFIG）
  var config = Object.assign({}, defaults, window.FLYER_CONFIG || {});
  try {
    var q = new URLSearchParams(location.search);
    if (q.get('api')) { config.baseUrl = q.get('api'); }
    if (q.get('ground')) { config.groundUrl = q.get('ground'); }
  } catch (_) { /* 忽略 */ }

  function normalizeBase(url) { return String(url || '').replace(/\/$/, ''); }

  function requestUrl(url, options) {
    var controller = typeof AbortController === 'function' ? new AbortController() : null;
    var timer = controller ? setTimeout(function () { controller.abort(); }, config.timeoutMs) : null;
    var init = Object.assign({ method: 'GET', cache: 'no-store', headers: { Accept: 'application/json' } }, options || {});
    if (controller) { init.signal = controller.signal; }
    if (init.body) { init.headers = Object.assign({}, init.headers, { 'Content-Type': 'application/json' }); }

    return fetch(url, init)
      .then(function (res) {
        if (!res.ok) { throw new Error('HTTP_' + res.status); }
        return res.json();
      })
      .then(function (data) {
        if (timer) { clearTimeout(timer); }
        return { ok: true, data: data, source: 'live', error: null };
      })
      .catch(function (error) {
        if (timer) { clearTimeout(timer); }
        return { ok: false, data: null, source: 'mock', error: error && error.name === 'AbortError' ? 'TIMEOUT' : 'UNAVAILABLE' };
      });
  }

  function request(path, options) { return requestUrl(normalizeBase(config.baseUrl) + path, options); }

  /* ------------------------- 内置演示数据（mock） ------------------------- */
  function clone(v) { return JSON.parse(JSON.stringify(v)); }

  function mockSnapshot() {
    return {
      schema_version: '1.0', frame: 'WGS84', altitude_ref: 'MSL',
      generated_at: new Date().toISOString(),
      airport: clone(M.airport), obstacles: clone(M.obstacles), airspaces: clone(M.airspaces),
      meteo: clone(M.meteo), program: clone(M.program), traffic: clone(M.traffic)
    };
  }
  function mockProgram() {
    return {
      program: clone(M.program), risk: { score: 28, level: 1, level_name: '低风险', program_status: 'VALID' },
      compliance: { passed: true, checks: [
        { name: '障碍物净空', pass: true, detail: '航路保护区内无障碍物穿越', margin: 86 },
        { name: '气象窗口', pass: true, detail: '风速、阵风及能见度满足阈值', margin: 2.2 },
        { name: '空域边界', pass: true, detail: '未进入活动限制区', margin: 340 },
        { name: '复飞路径', pass: true, detail: '复飞航路连续且满足爬升要求', margin: 42 }
      ] },
      simulate: { passed: true, checks: ['航迹连续性通过', '碰撞检测通过', '速度包络通过', '终端点约束通过'] },
      meteo: clone(M.meteo), alarm: '', last_event: '程序 A03 已通过仿真与合规校验'
    };
  }
  function mockGround() {
    return {
      airport_code: M.airport.code, data_source: 'demo',
      generated_at: new Date().toISOString(),
      stands: clone(M.stands), rid_targets: clone(M.rid_targets),
      sensor: clone(M.sensor), dispatch: clone(M.dispatch)
    };
  }

  /* ------------------------------ 对外接口 ------------------------------ */
  window.FlyerApi = {
    config: config,

    health: function () { return request('/api/health'); },
    snapshot: function () { return request('/api/sync/snapshot'); },
    traffic: function () { return request('/api/traffic'); },
    program: function () { return request('/api/program/current'); },
    ground: function () { return requestUrl(normalizeBase(config.groundUrl) + '/api/ground'); },

    replan: function (programType) {
      return request('/api/program/replan', { method: 'POST', body: JSON.stringify({ program_type: programType }) });
    },
    setMeteo: function (meteo) {
      return request('/api/env/meteo', { method: 'POST', body: JSON.stringify(meteo) });
    },
    toggleObstacle: function (id, active) {
      return request('/api/env/obstacle/toggle', { method: 'POST', body: JSON.stringify({ id: id, active: active }) });
    },

    getMockSnapshot: function () { return { ok: true, data: mockSnapshot(), source: 'mock', error: null }; },
    getMockProgram: function () { return { ok: true, data: mockProgram(), source: 'mock', error: null }; },
    getMockGround: function () { return { ok: true, data: mockGround(), source: 'mock', error: null }; },

    setBackend: function (baseUrl, groundUrl) {
      if (baseUrl) { config.baseUrl = normalizeBase(baseUrl); }
      if (groundUrl) { config.groundUrl = normalizeBase(groundUrl); }
    }
  };
}());
