(function () {
  'use strict';

  // 主机名自适应：本机 / 手机 / 局域网演示都指向同一后端（换端口时用 window.LAV_CONFIG 覆盖）
  var HOST = (typeof location !== 'undefined' && location.hostname) || '127.0.0.1';
  var defaults = {
    baseUrl: 'http://' + HOST + ':8080',    // flycontrol API
    groundUrl: 'http://' + HOST + ':8090',  // groundstation 数据桥
    timeoutMs: 2200
  };
  var config = Object.assign({}, defaults, window.LAV_CONFIG || {});

  function requestUrl(url, options) {
    var opts = options || {};
    var timeoutMs = opts.timeoutMs || config.timeoutMs;   // AI 调用需要比普通轮询更长的超时
    var controller = typeof AbortController === 'function' ? new AbortController() : null;
    var timeout = controller ? setTimeout(function () { controller.abort(); }, timeoutMs) : null;
    var init = Object.assign({ method: 'GET', cache: 'no-store', headers: { 'Accept': 'application/json' } }, opts);
    delete init.timeoutMs;
    if (controller) init.signal = controller.signal;
    if (init.body) init.headers = Object.assign({}, init.headers, { 'Content-Type': 'application/json' });

    return fetch(url, init)
      .then(function (response) {
        if (!response.ok) throw new Error('HTTP_' + response.status);
        return response.json();
      })
      .then(function (data) {
        if (timeout) clearTimeout(timeout);
        return { ok: true, data: data, source: 'live', error: null };
      })
      .catch(function (error) {
        if (timeout) clearTimeout(timeout);
        return { ok: false, data: null, source: 'mock', error: error && error.name === 'AbortError' ? 'TIMEOUT' : 'UNAVAILABLE' };
      });
  }

  function request(path, options) { return requestUrl(config.baseUrl.replace(/\/$/, '') + path, options); }

  window.LAVApi = {
    config: config,
    health: function () { return request('/api/health'); },
    snapshot: function () { return request('/api/sync/snapshot'); },
    traffic: function () { return request('/api/traffic'); },
    trafficStats: function () { return request('/api/traffic/stats'); },
    program: function () { return request('/api/program/current'); },
    ground: function () { return requestUrl(config.groundUrl.replace(/\/$/, '') + '/api/ground'); },
    plans: function (programType, direction) {
      var q = '/api/plans?program_type=' + encodeURIComponent(programType || 'arrival');
      if (direction) q += '&direction=' + encodeURIComponent(direction);
      return request(q);
    },
    generate: function (programType, direction, mode) {
      return request('/api/program/generate', { method:'POST',
        body: JSON.stringify({ program_type: programType, direction: direction, mode: mode || 'template' }) });
    },
    pushStatus: function () { return request('/api/push/status'); },
    pushFlush: function () { return request('/api/push/flush', { method:'POST' }); },
    replan: function (programType) { return request('/api/program/replan', { method:'POST', body:JSON.stringify({ program_type:programType }) }); },
    setMeteo: function (meteo) { return request('/api/env/meteo', { method:'POST', body:JSON.stringify(meteo) }); },
    toggleObstacle: function (id, active) { return request('/api/env/obstacle/toggle', { method:'POST', body:JSON.stringify({ id:id, active:active }) }); },

    // ---- AI 调度建议（只读，不执行）----
    advice: function (message, programType) {
      return request('/api/ai/advice', { method:'POST', timeoutMs: 45000,
        body: JSON.stringify({ message: message, program_type: programType || 'arrival' }) });
    },
    verdict: function (programType) {
      return request('/api/ai/verdict?program_type=' + encodeURIComponent(programType || 'arrival'), {timeoutMs: 45000});
    },

    // ---- 运维 / 台账 / 指标 ----
    metrics: function () { return request('/api/metrics'); },
    devices: function () { return request('/api/devices'); },
    createDevice: function (body) { return request('/api/devices', { method:'POST', body:JSON.stringify(body) }); },
    deleteDevice: function (id) { return request('/api/devices/' + encodeURIComponent(id), { method:'DELETE' }); },
    routes: function () { return request('/api/routes'); },
    createRoute: function (body) { return request('/api/routes', { method:'POST', body:JSON.stringify(body) }); },
    deleteRoute: function (id) { return request('/api/routes/' + encodeURIComponent(id), { method:'DELETE' }); },
    shadow: function () { return request('/api/traffic/shadow'); },
    setShadow: function (enabled) { return request('/api/traffic/shadow', { method:'POST', body:JSON.stringify({ enabled: !!enabled }) }); },
    rlHealth: function () { return request('/api/rl/health'); },

    setBaseUrl: function (value) { config.baseUrl = String(value || defaults.baseUrl).replace(/\/$/, ''); }
  };
}());
