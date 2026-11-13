/* =========================================================================
 * 挺中航空 · 态势图 (Canvas 自绘)
 * -------------------------------------------------------------------------
 * 纯 Canvas 绘制的起降点周边态势：网格 / 安全半径 / 限飞区 / 障碍物 /
 * 飞行器（含航迹、航向、我的飞行器高亮）。支持：
 *   - 单指拖动平移、双指捏合缩放、滚轮缩放
 *   - 松手惯性滑动
 *   - 点击飞行器选中
 * 坐标：WGS84 经纬度 -> 本地等距平面（与契约一致的 111320 m/deg 近似）
 * ========================================================================= */
(function () {
  'use strict';

  var M_PER_DEG_LAT = 111320;

  function cosLat(lat) { return Math.cos(lat * Math.PI / 180); }

  function create(canvas, opts) {
    opts = opts || {};
    var ctx = canvas.getContext('2d');
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var W = 0, H = 0;

    var view = { lat: 29.7186, lon: 106.6345, mpp: 14 };  // mpp = 米/像素
    var data = { snapshot: null, myIds: [], selectedId: null };
    var pointers = new Map();
    var pinchStart = null;
    var dragStart = null;
    var vx = 0, vy = 0;
    var tapCandidate = null;
    var stopped = false;
    var raf = 0;
    var time = 0;

    /* ----------------------------- 尺寸 ----------------------------- */
    function resize() {
      var rect = canvas.getBoundingClientRect();
      W = Math.max(1, Math.round(rect.width));
      H = Math.max(1, Math.round(rect.height));
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    /* --------------------------- 投影 --------------------------- */
    function project(lat, lon) {
      var kx = M_PER_DEG_LAT * cosLat(view.lat);
      return {
        x: W / 2 + ((lon - view.lon) * kx) / view.mpp,
        y: H / 2 - ((lat - view.lat) * M_PER_DEG_LAT) / view.mpp
      };
    }
    function unproject(x, y) {
      var kx = M_PER_DEG_LAT * cosLat(view.lat);
      return {
        lat: view.lat + ((H / 2 - y) * view.mpp) / M_PER_DEG_LAT,
        lon: view.lon + ((x - W / 2) * view.mpp) / kx
      };
    }
    function panByPixels(dx, dy) {
      var kx = M_PER_DEG_LAT * cosLat(view.lat);
      view.lon -= (dx * view.mpp) / kx;
      view.lat += (dy * view.mpp) / M_PER_DEG_LAT;
    }

    /* ---------------------------- 绘制 ---------------------------- */
    function draw() {
      if (stopped) { return; }
      time += 1 / 60;
      var s = data.snapshot || {};

      // 惯性
      if (!pointerActive() && (Math.abs(vx) > 0.05 || Math.abs(vy) > 0.05)) {
        panByPixels(vx, vy);
        vx *= 0.92; vy *= 0.92;
      }

      ctx.clearRect(0, 0, W, H);

      // 背景
      var bg = ctx.createRadialGradient(W / 2, H / 2, 20, W / 2, H / 2, Math.max(W, H) * 0.75);
      bg.addColorStop(0, '#0a1729');
      bg.addColorStop(1, '#050b16');
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, W, H);

      drawGrid();
      if (s.airport) { drawSafeRadius(s.airport); }
      safeArray(s.airspaces).forEach(drawAirspace);
      safeArray(s.obstacles).forEach(drawObstacle);
      safeArray(s.traffic).forEach(drawTrafficRoute);
      safeArray(s.traffic).forEach(drawTraffic);
      if (s.airport) { drawAirport(s.airport); }
      drawChrome();

      raf = requestAnimationFrame(draw);
    }

    function drawGrid() {
      var step = gridStepMeters();
      var halfM = Math.max(W, H) / 2 * view.mpp;
      var center = unproject(W / 2, H / 2);
      var kx = M_PER_DEG_LAT * cosLat(center.lat);

      ctx.lineWidth = 1;
      ctx.strokeStyle = 'rgba(84,142,204,.12)';

      var lonSpan = halfM / kx;
      var latSpan = halfM / M_PER_DEG_LAT;
      var lonStart = Math.floor((center.lon - lonSpan) / (step / kx)) * (step / kx);
      var latStart = Math.floor((center.lat - latSpan) / (step / M_PER_DEG_LAT)) * (step / M_PER_DEG_LAT);

      ctx.beginPath();
      for (var lon = lonStart; lon < center.lon + lonSpan; lon += step / kx) {
        var p = project(center.lat, lon);
        ctx.moveTo(p.x, 0); ctx.lineTo(p.x, H);
      }
      for (var lat = latStart; lat < center.lat + latSpan; lat += step / M_PER_DEG_LAT) {
        var q = project(lat, center.lon);
        ctx.moveTo(0, q.y); ctx.lineTo(W, q.y);
      }
      ctx.stroke();
    }

    function gridStepMeters() {
      var want = view.mpp * 70;                 // 目标格子像素
      var steps = [50, 100, 200, 500, 1000, 2000, 5000, 10000];
      for (var i = 0; i < steps.length; i++) { if (steps[i] >= want) { return steps[i]; } }
      return 20000;
    }

    function drawSafeRadius(a) {
      var c = project(a.lat, a.lon);
      var r = (a.safe_radius || 0) / view.mpp;
      if (r < 4) { return; }
      ctx.save();
      ctx.setLineDash([9, 8]);
      ctx.strokeStyle = 'rgba(39,224,216,.42)';
      ctx.lineWidth = 1.4;
      ctx.beginPath(); ctx.arc(c.x, c.y, r, 0, Math.PI * 2); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = 'rgba(39,224,216,.55)';
      ctx.font = '10px ' + mono();
      ctx.fillText('安全半径 ' + Math.round(a.safe_radius / 1000) + ' km', c.x + 6, c.y - r - 6);
      ctx.restore();
    }

    function drawAirspace(a) {
      if (!a.active || !a.polygon || a.polygon.length < 3) { return; }
      ctx.beginPath();
      a.polygon.forEach(function (pt, i) {
        var p = project(pt[0], pt[1]);
        i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y);
      });
      ctx.closePath();
      ctx.fillStyle = 'rgba(124,92,255,.13)';
      ctx.fill();
      ctx.setLineDash([6, 5]);
      ctx.strokeStyle = 'rgba(124,92,255,.62)';
      ctx.lineWidth = 1.4;
      ctx.stroke();
      ctx.setLineDash([]);

      // 名称
      var cLat = 0, cLon = 0;
      a.polygon.forEach(function (pt) { cLat += pt[0]; cLon += pt[1]; });
      cLat /= a.polygon.length; cLon /= a.polygon.length;
      var c = project(cLat, cLon);
      ctx.fillStyle = 'rgba(196,180,255,.86)';
      ctx.font = '10px ' + sans();
      ctx.textAlign = 'center';
      ctx.fillText(a.name, c.x, c.y);
      ctx.textAlign = 'left';
    }

    function drawObstacle(o) {
      var p = project(o.lat, o.lon);
      var r = Math.max(3, o.radius / view.mpp);
      var buffer = Math.max(r, (o.radius + (o.buffer || 0)) / view.mpp);
      var on = o.active !== false;

      ctx.beginPath(); ctx.arc(p.x, p.y, buffer, 0, Math.PI * 2);
      ctx.fillStyle = on ? 'rgba(255,179,92,.07)' : 'rgba(120,140,170,.05)';
      ctx.fill();

      ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
      ctx.fillStyle = on ? 'rgba(255,179,92,.28)' : 'rgba(120,140,170,.18)';
      ctx.fill();
      ctx.strokeStyle = on ? '#ffb35c' : 'rgba(120,140,170,.5)';
      ctx.lineWidth = 1.4;
      ctx.stroke();

      if (view.mpp < 30) {
        ctx.fillStyle = on ? 'rgba(255,205,150,.9)' : 'rgba(150,168,190,.7)';
        ctx.font = '9px ' + sans();
        ctx.fillText(o.name, p.x + r + 4, p.y + 3);
      }
    }

    function drawTrafficRoute(t) {
      var route = safeArray(t.route);
      if (route.length < 2) { return; }
      var mine = isMine(t.id);
      ctx.beginPath();
      route.forEach(function (pt, i) {
        var p = project(pt.lat, pt.lon);
        i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y);
      });
      ctx.setLineDash([5, 5]);
      ctx.lineWidth = data.selectedId === t.id ? 2 : 1;
      ctx.strokeStyle = data.selectedId === t.id ? 'rgba(39,224,216,.8)'
        : mine ? 'rgba(39,224,216,.42)' : 'rgba(47,155,255,.24)';
      ctx.stroke();
      ctx.setLineDash([]);
    }

    function drawTraffic(t) {
      var p = project(t.lat, t.lon);
      var selected = data.selectedId === t.id;
      var mine = isMine(t.id);
      var color = t.emergency ? '#ff6279' : t.rid_lost ? '#ffb35c'
        : t.phase === 'APPROACH' ? '#ffb35c' : t.phase === 'DEPARTURE' ? '#27e0d8'
        : t.phase === 'CRUISE' ? '#7c5cff' : t.phase === 'STANDBY' ? '#49e3ae' : '#2f9bff';

      // 我的飞行器：脉冲光环
      if (mine) {
        var pulse = 14 + Math.sin(time * 2.2) * 5;
        ctx.beginPath(); ctx.arc(p.x, p.y, pulse, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(39,224,216,' + (0.30 - Math.sin(time * 2.2) * 0.1) + ')';
        ctx.lineWidth = 1.6; ctx.stroke();
      }

      // 选中光环
      if (selected) {
        ctx.beginPath(); ctx.arc(p.x, p.y, 17, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(39,224,216,.55)';
        ctx.lineWidth = 1.4; ctx.stroke();
      }

      // 机体
      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(((Number(t.heading) || 0) - 90) * Math.PI / 180);
      ctx.beginPath();
      ctx.moveTo(11, 0); ctx.lineTo(-7, 6); ctx.lineTo(-3.5, 0); ctx.lineTo(-7, -6);
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.shadowColor = color;
      ctx.shadowBlur = selected || mine ? 12 : 6;
      ctx.fill();
      ctx.restore();

      // 标签
      if (view.mpp < 40) {
        ctx.fillStyle = mine ? '#d9fdff' : '#bcd6ee';
        ctx.font = '9px ' + mono();
        ctx.fillText(t.id.replace('UAV-', ''), p.x + 13, p.y - 9);
        if (view.mpp < 18) {
          ctx.fillStyle = 'rgba(140,170,200,.85)';
          ctx.fillText(Math.round(t.alt_msl) + 'm', p.x + 13, p.y + 2);
        }
      }
    }

    function drawAirport(a) {
      var c = project(a.lat, a.lon);
      // 跑道方向
      var h = (Number(a.runway_heading) || 0) * Math.PI / 180;
      ctx.save();
      ctx.translate(c.x, c.y);
      ctx.rotate(h);
      ctx.fillStyle = 'rgba(47,155,255,.35)';
      ctx.fillRect(-24, -3, 48, 6);
      ctx.strokeStyle = '#2f9bff';
      ctx.lineWidth = 1.6;
      ctx.strokeRect(-24, -3, 48, 6);
      ctx.restore();

      ctx.beginPath(); ctx.arc(c.x, c.y, 8, 0, Math.PI * 2);
      ctx.fillStyle = '#d8faff'; ctx.fill();
      ctx.strokeStyle = '#27e0d8'; ctx.lineWidth = 3; ctx.stroke();

      ctx.fillStyle = '#cfe9ff';
      ctx.font = '10px ' + mono();
      ctx.fillText(a.code || 'SKYPORT', c.x + 14, c.y + 4);
    }

    function drawChrome() {
      // 比例尺
      var m = 1000;
      var widths = [100, 200, 500, 1000, 2000, 5000];
      for (var i = 0; i < widths.length; i++) {
        if (widths[i] / view.mpp > 48) { m = widths[i]; break; }
      }
      var px = m / view.mpp;
      var x0 = 14, y0 = H - 16;
      ctx.strokeStyle = 'rgba(190,220,245,.6)';
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.moveTo(x0, y0); ctx.lineTo(x0 + px, y0);
      ctx.moveTo(x0, y0 - 4); ctx.lineTo(x0, y0 + 4);
      ctx.moveTo(x0 + px, y0 - 4); ctx.lineTo(x0 + px, y0 + 4);
      ctx.stroke();
      ctx.fillStyle = 'rgba(170,200,228,.85)';
      ctx.font = '9px ' + mono();
      ctx.fillText(m >= 1000 ? (m / 1000) + ' km' : m + ' m', x0 + 4, y0 - 7);

      // 指北针
      var nx = W - 22, ny = 22;
      ctx.strokeStyle = 'rgba(190,220,245,.5)';
      ctx.beginPath(); ctx.arc(nx, ny, 11, 0, Math.PI * 2); ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(nx, ny - 7); ctx.lineTo(nx + 3.5, ny + 5); ctx.lineTo(nx, ny + 2); ctx.lineTo(nx - 3.5, ny + 5);
      ctx.closePath();
      ctx.fillStyle = '#27e0d8'; ctx.fill();
      ctx.fillStyle = 'rgba(170,200,228,.85)';
      ctx.font = '8px ' + mono();
      ctx.textAlign = 'center';
      ctx.fillText('N', nx, ny + 19);
      ctx.textAlign = 'left';
    }

    /* --------------------------- 工具 --------------------------- */
    function safeArray(v) { return Array.isArray(v) ? v : []; }
    function mono() { return '"Cascadia Code",Consolas,monospace'; }
    function sans() { return 'Inter,"Microsoft YaHei",system-ui,sans-serif'; }
    function isMine(id) { return data.myIds.indexOf(id) >= 0; }
    function pointerActive() { return pointers.size > 0; }

    /* --------------------------- 交互 --------------------------- */
    function pointerPos(e) {
      var r = canvas.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    }

    function onDown(e) {
      canvas.setPointerCapture && canvas.setPointerCapture(e.pointerId);
      var p = pointerPos(e);
      pointers.set(e.pointerId, p);
      vx = vy = 0;

      if (pointers.size === 1) {
        dragStart = { x: p.x, y: p.y, time: Date.now(), moved: 0 };
        tapCandidate = { x: p.x, y: p.y, time: Date.now() };
      } else if (pointers.size === 2) {
        var pts = Array.from(pointers.values());
        pinchStart = {
          dist: Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y),
          mpp: view.mpp,
          mid: { x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2 }
        };
        dragStart = null;
        tapCandidate = null;
      }
    }

    function onMove(e) {
      if (!pointers.has(e.pointerId)) { return; }
      var p = pointerPos(e);
      var prev = pointers.get(e.pointerId);
      pointers.set(e.pointerId, p);

      if (pointers.size === 1 && dragStart) {
        var dx = p.x - prev.x, dy = p.y - prev.y;
        panByPixels(dx, dy);
        vx = dx * 0.85; vy = dy * 0.85;
        dragStart.moved += Math.hypot(dx, dy);
        if (dragStart.moved > 8) { tapCandidate = null; }
      } else if (pointers.size === 2 && pinchStart) {
        var pts = Array.from(pointers.values());
        var dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
        if (dist > 0 && pinchStart.dist > 0) {
          var ratio = pinchStart.dist / dist;
          var next = clamp(pinchStart.mpp * ratio, 2, 500);
          // 以捏合中心为锚点缩放
          var mid = { x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2 };
          var anchor = unproject(mid.x, mid.y);
          view.mpp = next;
          var after = project(anchor.lat, anchor.lon);
          panByPixels(after.x - mid.x, after.y - mid.y);
        }
      }
    }

    function onUp(e) {
      var wasTap = tapCandidate;
      pointers.delete(e.pointerId);
      if (pointers.size < 2) { pinchStart = null; }
      if (pointers.size === 0) { dragStart = null; }

      if (wasTap && Date.now() - wasTap.time < 400) {
        var hit = hitTest(wasTap.x, wasTap.y);
        if (hit && typeof opts.onPick === 'function') { opts.onPick(hit); }
        else if (!hit && typeof opts.onPickEmpty === 'function') { opts.onPickEmpty(); }
      }
      tapCandidate = null;
    }

    function hitTest(x, y) {
      var list = safeArray((data.snapshot || {}).traffic);
      var best = null, bestD = 30;
      list.forEach(function (t) {
        var p = project(t.lat, t.lon);
        var d = Math.hypot(p.x - x, p.y - y);
        if (d < bestD) { bestD = d; best = t; }
      });
      return best;
    }

    function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }

    function onWheel(e) {
      e.preventDefault();
      var p = pointerPos(e);
      var anchor = unproject(p.x, p.y);
      view.mpp = clamp(view.mpp * (e.deltaY > 0 ? 1.14 : 0.88), 2, 500);
      var after = project(anchor.lat, anchor.lon);
      panByPixels(after.x - p.x, after.y - p.y);
    }

    /* --------------------------- 生命周期 --------------------------- */
    resize();
    canvas.addEventListener('pointerdown', onDown);
    canvas.addEventListener('pointermove', onMove);
    canvas.addEventListener('pointerup', onUp);
    canvas.addEventListener('pointercancel', onUp);
    canvas.addEventListener('wheel', onWheel, { passive: false });
    canvas.addEventListener('dblclick', function (e) {
      e.preventDefault();
      view.mpp = clamp(view.mpp / 1.6, 2, 500);
    });
    window.addEventListener('resize', resize);
    raf = requestAnimationFrame(draw);

    return {
      setData: function (snapshot, myIds, selectedId) {
        data.snapshot = snapshot;
        data.myIds = Array.isArray(myIds) ? myIds : [];
        data.selectedId = selectedId || null;
      },
      focusOn: function (lat, lon, mpp) {
        if (!isFinite(lat) || !isFinite(lon)) { return; }
        view.lat = lat; view.lon = lon;
        if (mpp) { view.mpp = clamp(mpp, 2, 500); }
      },
      resetView: function (snapshot) {
        var a = (snapshot || data.snapshot || {}).airport;
        if (a) { view.lat = a.lat; view.lon = a.lon; }
        view.mpp = 14;
        vx = vy = 0;
      },
      zoom: function (factor) {
        view.mpp = clamp(view.mpp * factor, 2, 500);
      },
      destroy: function () {
        stopped = true;
        cancelAnimationFrame(raf);
        window.removeEventListener('resize', resize);
        canvas.removeEventListener('pointerdown', onDown);
        canvas.removeEventListener('pointermove', onMove);
        canvas.removeEventListener('pointerup', onUp);
        canvas.removeEventListener('pointercancel', onUp);
        canvas.removeEventListener('wheel', onWheel);
      }
    };
  }

  window.FlyerMap = { create: create };
}());
