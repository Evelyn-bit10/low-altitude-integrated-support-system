/* 演示阈值，仅用于展示，不构成运行许可。 */
(function (root) {
  'use strict';
  function number(v) {
    if (v === null || v === undefined || v === '' || typeof v === 'boolean') return null;
    var n = Number(v);
    return isFinite(n) ? n : null;
  }
  function evaluate(uav, meteo) {
    var level = 'APPROVE', reasons = [];
    function add(next, text) {
      if (next === 'DENY' || (next === 'HOLD' && level === 'APPROVE')) level = next;
      reasons.push({ tone: next === 'DENY' ? 'danger' : 'warn', text: text });
    }
    if (!uav) return { level: 'DENY', reasons: [{ tone: 'danger', text: '请先选择一架飞行器' }] };
    if (uav.rid_lost === true) add('DENY', 'RID 远程识别信号丢失');
    else if (uav.rid_lost !== false) add('HOLD', 'RID 远程识别状态未知');
    if (uav.emergency === true) add('DENY', '飞行器处于紧急状态');
    else if (uav.emergency !== false) add('HOLD', '飞行器紧急状态未知');
    if (!uav.reg_no || !uav.ua_id) add('DENY', '缺少实名登记号或唯一产品识别码');
    var battery = number(uav.battery_pct), link = number(uav.link_quality);
    if (battery === null || battery < 0 || battery > 100) add('HOLD', '电量数据不可用');
    else if (battery < 25) add('DENY', '电量低于演示阈值 25%');
    else if (battery < 45) add('HOLD', '电量低于演示阈值 45%');
    if (link === null || link < 1 || link > 5) add('HOLD', 'C2 链路质量不可用');
    else if (link <= 2) add('DENY', 'C2 链路质量低于演示阈值');
    else if (link <= 3) add('HOLD', 'C2 链路质量受限');
    var m = meteo || {};
    var visibility = number(m.visibility), cloud = number(m.cloud_base_agl);
    var wind = number(m.wind_speed), gust = number(m.gust);
    if (visibility === null || cloud === null || wind === null || gust === null ||
        visibility < 0 || cloud < 0 || wind < 0 || gust < 0) {
      add('HOLD', '气象数据不完整或无效');
    }
    if ((visibility !== null && visibility >= 0 && visibility < 1600) ||
        (cloud !== null && cloud >= 0 && cloud < 120) ||
        (wind !== null && wind > 8)) add('DENY', '气象超出演示阈值');
    else if ((wind !== null && wind > 6) || (gust !== null && gust > 10)) add('HOLD', '风速或阵风接近演示阈值');
    if (!reasons.length) reasons.push({ tone: 'ok', text: '识别、电量、链路与气象满足演示阈值' });
    return { level: level, reasons: reasons };
  }
  function position(lat, lon) {
    return lat !== null && lon !== null && Math.abs(lat) <= 90 && Math.abs(lon) <= 180;
  }
  function inside(lat, lon, polygon) {
    var hit = false;
    for (var i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
      var a = polygon[i], b = polygon[j];
      var cross = (lon - a[1]) * (b[0] - a[0]) - (lat - a[0]) * (b[1] - a[1]);
      if (Math.abs(cross) < 1e-12 && lat >= Math.min(a[0], b[0]) && lat <= Math.max(a[0], b[0]) && lon >= Math.min(a[1], b[1]) && lon <= Math.max(a[1], b[1])) return true;
      if ((a[0] > lat) !== (b[0] > lat) && lon < (b[1] - a[1]) * (lat - a[0]) / (b[0] - a[0]) + a[1]) hit = !hit;
    }
    return hit;
  }
  function environment(uav, snapshot) {
    var level = 'APPROVE', reasons = [], obstacleHits = [];
    var lat = number(uav && uav.lat), lon = number(uav && uav.lon), alt = number(uav && uav.alt_msl);
    function add(next, text) {
      if (next === 'DENY' || level === 'APPROVE') level = next;
      reasons.push({ tone: next === 'DENY' ? 'danger' : 'warn', text: text });
    }
    if (!position(lat, lon) || alt === null) add('HOLD', '飞行器位置或高度不可用');
    var s = snapshot || {};
    if (!Array.isArray(s.airspaces)) add('HOLD', '空域数据不可用');
    else s.airspaces.forEach(function (a) {
      if (!a || (a.active !== true && a.active !== false)) { add('HOLD', '空域状态不可用'); return; }
      if (!a.active) return;
      var floor = number(a.floor_msl), ceiling = number(a.ceiling_msl);
      var poly = Array.isArray(a.polygon) ? a.polygon.map(function (p) { return Array.isArray(p) ? [number(p[0]), number(p[1])] : [null, null]; }) : [];
      if (floor === null || ceiling === null || floor > ceiling || poly.length < 3 || poly.some(function (p) { return !position(p[0], p[1]); })) { add('HOLD', '空域数据不完整'); return; }
      if (position(lat, lon) && alt !== null && alt >= floor && alt <= ceiling && inside(lat, lon, poly)) add('DENY', '位于限制空域「' + (a.name || a.id || '未命名') + '」内');
    });
    if (!Array.isArray(s.obstacles)) add('HOLD', '障碍物数据不可用');
    else s.obstacles.forEach(function (o) {
      if (!o || (o.active !== true && o.active !== false)) { add('HOLD', '障碍物状态不可用'); return; }
      if (!o.active) return;
      var olat = number(o.lat), olon = number(o.lon), top = number(o.top_msl), radius = number(o.radius), buffer = number(o.buffer);
      if (o.id === undefined || o.id === null || String(o.id).trim() === '' || !position(olat, olon) || top === null || radius === null || buffer === null || radius < 0 || buffer < 0) { add('HOLD', '障碍物数据不完整'); return; }
      if (!position(lat, lon) || alt === null) return;
      var rad = Math.PI / 180, dlat = (olat - lat) * rad, dlon = (olon - lon) * rad;
      var h = Math.sin(dlat / 2) ** 2 + Math.cos(lat * rad) * Math.cos(olat * rad) * Math.sin(dlon / 2) ** 2;
      var distance = 12742000 * Math.asin(Math.sqrt(Math.min(1, h)));
      if (distance <= radius + buffer && alt <= top) {
        var name = o.name || o.id || '未命名';
        obstacleHits.push({ id: String(o.id), name: name, distance_m: distance });
        add('DENY', '与障碍物「' + name + '」存在演示冲突');
      }
    });
    return { level: level, reasons: reasons, obstacleHits: obstacleHits };
  }
  function stands(airportCode, ground, now) {
    function hold(text) { return { level: 'HOLD', reasons: [{ tone: 'warn', text: text }] }; }
    if (typeof airportCode !== 'string' || !airportCode.trim() || !ground ||
        typeof ground.airport_code !== 'string' || !ground.airport_code.trim()) return hold('缺少起降点标识，机位待核对');
    if (airportCode.trim() !== ground.airport_code.trim()) return hold('机位与飞行态势不属于同一起降点');
    if (typeof ground.data_source !== 'string' || !ground.data_source.trim()) return hold('机位数据来源未声明');
    if (!Array.isArray(ground.stands)) return hold('机位数据不可用');
    var timestamp = typeof ground.generated_at === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/i.test(ground.generated_at) ? Date.parse(ground.generated_at) : NaN;
    var current = now === undefined ? Date.now() : now;
    if (!isFinite(timestamp) || !isFinite(current) || timestamp > current + 30000 || current - timestamp > 60000) return hold('机位数据时间无效或已过期');
    if (ground.stands.some(function (s) { return !s || ['free', 'occupied', 'reserved'].indexOf(s.status) < 0; })) return hold('机位状态不完整');
    var free = ground.stands.filter(function (s) { return s.status === 'free'; }).length;
    if (!free) return hold('当前无空闲机位，需人工确认');
    return { level: 'APPROVE', reasons: [{ tone: 'ok', text: '可用机位 ' + free + ' 个（演示预检）' }] };
  }
  var api = { evaluate: evaluate, environment: environment, stands: stands };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.DemoDecision = api;
}(typeof window !== 'undefined' ? window : globalThis));
