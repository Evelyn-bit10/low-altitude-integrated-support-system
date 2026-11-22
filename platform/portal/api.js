(function () {
  'use strict';

  // 主机名自适应：本机 / 手机 / 局域网演示都指向同一后端（换端口时用 window.LAV_CONFIG 覆盖）
  var HOST = (typeof location !== 'undefined' && location.hostname) || '127.0.0.1';
  var defaults = {
    baseUrl: 'http://' + HOST + ':8082',    // flycontrol API
    groundUrl: 'http://' + HOST + ':8090',  // groundstation 数据桥
    timeoutMs: 5000
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

    if (new Headers(init.headers).has('X-Token') && new Headers(init.headers).get('X-Token')) {
      var target = new URL(url, location.href);
      if (target.protocol !== 'https:' && !(target.protocol === 'http:' && ['localhost','127.0.0.1','[::1]'].includes(target.hostname))) {
        if (timeout) clearTimeout(timeout);
        return Promise.resolve({ok:false, error:'INSECURE_CONNECTION'});
      }
      init.redirect = 'error';
    }
    return fetch(url, init)
      .then(async function (response) {
        var isJson = /\bapplication\/json\b/i.test(response.headers.get('Content-Type') || '');
        if (!isJson) return {ok:false, data:null, error:'WRONG_SERVICE', httpStatus:response.status};
        var data = await response.json();
        if (response.ok) return {ok:true, data:data, source:'live', error:null};
        var status = response.status;
        var error = {400:'BAD_REQUEST', 401:'UNAUTHORIZED', 403:'FORBIDDEN', 404:'NOT_FOUND',
          422:'BAD_REQUEST', 429:'RATE_LIMITED', 503:'SERVICE_UNAVAILABLE'}[status] || 'UNAVAILABLE';
        return {ok:false, data:null, error:error, httpStatus:status,
          detail:typeof (data && data.detail)==='string' ? data.detail : null};
      })
      .catch(function (error) {
        return {ok:false, data:null, source:'mock', error:error && error.name==='AbortError'?'TIMEOUT':'UNAVAILABLE'};
      })
      .finally(function () { if (timeout) clearTimeout(timeout); });
  }

  function request(path, options) { return requestUrl(config.baseUrl.replace(/\/$/, '') + path, options); }

  function weatherRequest(path, options) {
    var base = config.weatherUrl || (location.protocol === 'https:' ? location.origin : config.baseUrl);
    var target = new URL(base.replace(/\/$/, '') + path, location.href);
    var loopback = ['localhost', '127.0.0.1', '[::1]'].includes(target.hostname);
    if (options && target.protocol !== 'https:' && !(target.protocol === 'http:' && loopback)) {
      return Promise.resolve({ok: false, error: 'INSECURE_CONNECTION'});
    }
    return requestUrl(target.href, options);
  }

  window.LAVApi = {
    config: config,
    health: function () { return request('/api/health'); },
    snapshot: function () { return request('/api/sync/snapshot'); },
    traffic: function () { return request('/api/traffic'); },
    weatherReference: function () { return weatherRequest('/api/weather/reference'); },
    deviceWeather: function (latitude, longitude) {
      return weatherRequest('/api/weather/device', {
        method: 'POST', timeoutMs: 27000, redirect: 'error',
        body: JSON.stringify({ latitude: latitude, longitude: longitude })
      });
    },
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

    taskDraft: function (draft, token) {
      return request('/api/task-drafts/check', {method:'POST', headers:token?{'X-Token':token}:{}, body:JSON.stringify(draft)});
    },
    // ---- AI 调度建议（只读，不执行）----
    advice: function (message, programType, token, scenario) {
      return request('/api/ai/advice', { method:'POST', timeoutMs:90000,
        headers:token ? {'X-Token':token} : {},
        body: JSON.stringify({ message: message, program_type: programType || 'arrival', scenario: scenario || 'live' }) });
    },
    verdict: function (programType, token) {
      return request('/api/ai/verdict?program_type=' + encodeURIComponent(programType || 'arrival'),
        {timeoutMs:45000, headers:token ? {'X-Token':token} : {}});
    },

    followUp: function (assessmentId, answers, token) {
      return request('/api/ai/follow-up', {method:'POST', headers:{'X-Token':token},
        body:JSON.stringify({assessment_id:assessmentId, answers:answers})});
    },
    replay: function (assessmentId, token) {
      return request('/api/ai/assessments/' + encodeURIComponent(assessmentId), {headers:{'X-Token':token}});
    },
    review: function (assessmentId, decision, token) {
      return request('/api/ai/reviews', {method:'POST', headers:{'X-Token':token},
        body:JSON.stringify({assessment_id:assessmentId, decision:decision})});
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
