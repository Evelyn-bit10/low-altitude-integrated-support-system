/* =========================================================================
 * 低空起降点系统 · 统一数据接口 JS 适配层 (canonical v1.0)
 * -------------------------------------------------------------------------
 * 作用:两个项目(communication / flycontrol)之间的数据桥梁。
 *   - 提供 WGS84 经纬度 <-> 本地 ENU 的双向换算(与 flycontrol engines/geometry.py 一致);
 *   - 提供 communication 内部模型 <-> canonical 统一模型 的转换;
 *   - 挂载到 window.LAC,供 communication 前端直接 <script> 引入使用。
 *
 * 约定:跨项目传输一律 canonical(经纬度 + MSL + snake_case)。见 shared/contract.md。
 * ========================================================================= */
(function (root) {
  "use strict";

  var SCHEMA_VERSION = "1.1";
  var FRAME = "WGS84";
  var ALTITUDE_REF = "MSL";
  var M_PER_DEG_LAT = 111320.0;

  /* ----------------------------- 工具 ----------------------------- */
  function round(n, d) { var m = Math.pow(10, d); return Math.round(n * m) / m; }
  function metersPerDegLon(latDeg) { return M_PER_DEG_LAT * Math.cos(latDeg * Math.PI / 180); }

  /* ----------------------------- 坐标换算 ----------------------------- */
  // 参考点 = 起降点(机场)。setOrigin 后所有转换都相对该点。
  var geo = {
    refLat: null,
    refLon: null,
    refAlt: 0.0,
    ready: false,

    setOrigin: function (lat, lon, alt) {
      this.refLat = lat;
      this.refLon = lon;
      this.refAlt = (alt == null) ? 0.0 : alt;
      this.ready = (this.refLat != null && this.refLon != null);
      return this;
    },

    // 经纬度 + MSL -> ENU(x 东, y 北, z=AGL)
    toEnu: function (lat, lon, altMsl) {
      var mpdl = metersPerDegLon(this.refLat);
      return {
        x: (lon - this.refLon) * mpdl,
        y: (lat - this.refLat) * M_PER_DEG_LAT,
        z: (altMsl - this.refAlt),
      };
    },

    // ENU -> 经纬度 + MSL
    toLatLon: function (x, y, zAgl) {
      var mpdl = metersPerDegLon(this.refLat);
      return {
        lat: this.refLat + y / M_PER_DEG_LAT,
        lon: this.refLon + x / mpdl,
        alt: this.refAlt + (zAgl || 0),
      };
    },
  };

  /* --------------------- canonical 生成(输出统一模型) --------------------- */

  // communication 飞行器 -> canonical traffic(单条)
  function trafficFromCommunication(flight) {
    var ll = geo.toLatLon(flight.x, flight.y, flight.alt);
    return {
      id: flight.id,
      model: flight.model,
      reg_no: flight.regNo,
      ua_id: flight.uaId,
      phase: flight.phase,
      lat: round(ll.lat, 7),
      lon: round(ll.lon, 7),
      alt_msl: round(ll.alt, 1),
      speed: round(flight.speed, 1),
      heading: round(flight.heading, 1),
      vertical_speed: round(flight.vs, 1),
      battery_pct: Math.round(flight.battery),
      link_quality: flight.linkQuality,
      emergency: !!flight.emergency,
      rid_lost: !!flight.ridLost,
      route: (flight.route || []).map(function (r) {
        var p = geo.toLatLon(r.x, r.y, r.alt);
        return { lat: round(p.lat, 7), lon: round(p.lon, 7), alt_msl: round(p.alt, 1) };
      }),
    };
  }

  function trafficListFromCommunication(flights) {
    return (flights || []).map(trafficFromCommunication);
  }

  // communication 障碍物 -> canonical obstacle(需已 setOrigin)
  function obstacleFromCommunication(o, airportElevation) {
    var ll = geo.toLatLon(o.x, o.y, 0);
    return {
      id: String(o.id),
      name: o.name,
      type: "fixed",
      lat: round(ll.lat, 7),
      lon: round(ll.lon, 7),
      base_msl: round(airportElevation, 1),
      top_msl: round(airportElevation + (o.height || 0), 1),
      radius: o.radius,
      buffer: 60.0,
      active: true,
    };
  }

  // communication 围栏 -> canonical airspace
  function fenceFromCommunication(name, polygonXY, airportElevation, ceilingAgl) {
    return {
      id: "FENCE-01",
      name: name || "电子围栏(保护空域)",
      polygon: (polygonXY || []).map(function (pt) {
        var ll = geo.toLatLon(pt.x, pt.y, 0);
        return [round(ll.lat, 7), round(ll.lon, 7)];
      }),
      floor_msl: round(airportElevation, 1),
      ceiling_msl: round(airportElevation + (ceilingAgl || 500), 1),
      active: true,
    };
  }

  /* --------------------- canonical -> communication(反解析) --------------------- */
  // 输入 canonical snapshot,输出 communication 可直接使用的内部模型。
  // 副作用:调用 geo.setOrigin(机场经纬度+标高)。
  function snapshotToCommunication(snap) {
    var airport = snap.airport || {};
    var elevation = airport.elevation || 0;
    geo.setOrigin(airport.lat, airport.lon, elevation);

    var obstacles = (snap.obstacles || []).map(function (o) {
      var p = geo.toEnu(o.lat, o.lon, o.base_msl);
      return {
        id: String(o.id),
        name: o.name,
        x: round(p.x, 1),
        y: round(p.y, 1),
        // communication 内部用「顶高 AGL」;其冲突判定自带 60m 水平余量 ≈ flycontrol 的 buffer
        height: round(o.top_msl - elevation, 1),
        radius: o.radius,
        type: o.type === "dynamic" ? "tower" : "building",
      };
    });

    var airspaces = (snap.airspaces || []).map(function (a) {
      return {
        id: String(a.id),
        name: a.name,
        polygon: (a.polygon || []).map(function (ll) {
          var p = geo.toEnu(ll[0], ll[1], a.floor_msl);
          return { x: round(p.x, 1), y: round(p.y, 1) };
        }),
      };
    });

    var m = snap.meteo || {};
    var weather = {
      station: airport.code,
      timestamp: m.timestamp || new Date().toISOString(),
      windDir: m.wind_dir,
      wind: m.wind_speed,
      gust: m.gust,
      ceiling: m.cloud_base_agl,
      visibility: m.visibility,
      temp: m.temperature,
      dewPoint: m.dew_point,
      qnh: m.pressure,
      phenomenon: null, // 由 communication 按能见度自行判定
    };

    var program = null;
    if (snap.program && snap.program.waypoints && snap.program.waypoints.length) {
      program = {
        type: snap.program.type,
        version: snap.program.version,
        source: snap.program.source,
        waypoints: snap.program.waypoints.map(function (w) {
          var p = geo.toEnu(w.lat, w.lon, w.alt_msl);
          return { x: round(p.x, 1), y: round(p.y, 1), alt: round(p.z, 1) };
        }),
      };
    }

    return {
      airport: {
        code: airport.code,
        name: airport.name,
        lat: airport.lat,
        lon: airport.lon,
        elevation: elevation,
        safe_radius: airport.safe_radius,
        runway_heading: airport.runway_heading,
      },
      obstacles: obstacles,
      airspaces: airspaces,
      weather: weather,
      program: program,
    };
  }

  root.LAC = {
    SCHEMA_VERSION: SCHEMA_VERSION,
    FRAME: FRAME,
    ALTITUDE_REF: ALTITUDE_REF,
    M_PER_DEG_LAT: M_PER_DEG_LAT,
    geo: geo,
    round: round,
    trafficFromCommunication: trafficFromCommunication,
    trafficListFromCommunication: trafficListFromCommunication,
    obstacleFromCommunication: obstacleFromCommunication,
    fenceFromCommunication: fenceFromCommunication,
    snapshotToCommunication: snapshotToCommunication,
  };
})(typeof window !== "undefined" ? window : this);
