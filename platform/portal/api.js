(function () {
  'use strict';

  var defaults = {
    baseUrl: 'http://127.0.0.1:8080',    // flycontrol API
    groundUrl: 'http://127.0.0.1:8090',  // groundstation 数据桥
    timeoutMs: 2200
  };
  var config = Object.assign({}, defaults, window.LAV_CONFIG || {});

  function requestUrl(url, options) {
    var controller = typeof AbortController === 'function' ? new AbortController() : null;
    var timeout = controller ? setTimeout(function () { controller.abort(); }, config.timeoutMs) : null;
    var init = Object.assign({ method: 'GET', cache: 'no-store', headers: { 'Accept': 'application/json' } }, options || {});
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
    setBaseUrl: function (value) { config.baseUrl = String(value || defaults.baseUrl).replace(/\/$/, ''); }
  };
}());
