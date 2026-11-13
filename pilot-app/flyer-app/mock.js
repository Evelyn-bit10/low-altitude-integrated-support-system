/* =========================================================================
 * 挺中航空 · 内置演示数据 (mock)
 * -------------------------------------------------------------------------
 * 字段遵循统一数据契约 canonical（WGS84 经纬度 + 海拔 MSL + snake_case）：
 *   airport / obstacles / airspaces / meteo / traffic / program
 * 另含地面站与业务演示数据（stands / rid_targets / sensor / dispatch / messages）。
 * 本文件自包含，App 不依赖根目录门户的 mock。
 * ========================================================================= */
(function () {
  'use strict';

  /* ---------------- 起降点 ---------------- */
  var airport = {
    code: 'CQ-LX01', name: '龙兴低空起降点', lat: 29.71860, lon: 106.63450,
    elevation: 327, safe_radius: 3000, runway_heading: 42
  };

  /* ---------------- 障碍物 ---------------- */
  var obstacles = [
    { id: 'OBS-001', name: '北侧通信塔', type: 'fixed', lat: 29.72820, lon: 106.63850, base_msl: 330, top_msl: 462, radius: 32, buffer: 80, active: true },
    { id: 'OBS-002', name: '滨江吊塔', type: 'dynamic', lat: 29.70940, lon: 106.62940, base_msl: 330, top_msl: 388, radius: 44, buffer: 120, active: true },
    { id: 'OBS-003', name: '西侧厂房', type: 'fixed', lat: 29.71450, lon: 106.61540, base_msl: 327, top_msl: 372, radius: 95, buffer: 60, active: false },
    { id: 'OBS-004', name: '东南临时吊装区', type: 'dynamic', lat: 29.70400, lon: 106.64900, base_msl: 326, top_msl: 405, radius: 72, buffer: 110, active: true }
  ];

  /* ---------------- 空域 / 限飞区 ---------------- */
  var airspaces = [
    { id: 'ASP-101', name: '东侧临时限制区', polygon: [[29.7350, 106.6420], [29.7350, 106.6570], [29.7210, 106.6650], [29.7140, 106.6500], [29.7210, 106.6380]], floor_msl: 450, ceiling_msl: 900, active: true },
    { id: 'ASP-203', name: '滨江训练空域', polygon: [[29.7030, 106.6050], [29.7160, 106.6020], [29.7110, 106.6200], [29.6970, 106.6210]], floor_msl: 380, ceiling_msl: 760, active: true }
  ];

  /* ---------------- 气象 ---------------- */
  var meteo = {
    timestamp: '2026-09-09T14:28:00.000Z', wind_speed: 5.8, wind_dir: 68,
    gust: 8.2, visibility: 9600, cloud_base_agl: 680, turbulence: 2,
    wind_shear: 1, temperature: 27.4, dew_point: 21.6, pressure: 1008.6
  };

  /* ---------------- 飞行器态势 ---------------- */
  var traffic = [
    {
      id: 'UAV-CQ031', model: 'EH216-S', reg_no: 'B-EC31', ua_id: 'RID-CQ031', phase: 'APPROACH',
      lat: 29.72720, lon: 106.62440, alt_msl: 515, speed: 18.4, heading: 124, vertical_speed: -1.8,
      battery_pct: 72, link_quality: 5, emergency: false, rid_lost: false,
      route: [{ lat: 29.7400, lon: 106.6100, alt_msl: 620 }, { lat: 29.7272, lon: 106.6244, alt_msl: 515 }, { lat: 29.7186, lon: 106.6345, alt_msl: 327 }]
    },
    {
      id: 'UAV-CQ018', model: 'VoloCity', reg_no: 'B-EV18', ua_id: 'RID-CQ018', phase: 'DEPARTURE',
      lat: 29.71030, lon: 106.64240, alt_msl: 438, speed: 21.7, heading: 318, vertical_speed: 3.5,
      battery_pct: 88, link_quality: 4, emergency: false, rid_lost: false,
      route: [{ lat: 29.7186, lon: 106.6345, alt_msl: 327 }, { lat: 29.7103, lon: 106.6424, alt_msl: 438 }, { lat: 29.7050, lon: 106.6540, alt_msl: 560 }]
    },
    {
      id: 'UAV-CQ044', model: '物流六旋翼', reg_no: 'B-DR44', ua_id: 'RID-CQ044', phase: 'HOVER',
      lat: 29.72180, lon: 106.64820, alt_msl: 404, speed: 0.9, heading: 260, vertical_speed: 0.1,
      battery_pct: 39, link_quality: 3, emergency: true, rid_lost: false,
      route: [{ lat: 29.7190, lon: 106.6390, alt_msl: 395 }, { lat: 29.7218, lon: 106.6482, alt_msl: 404 }]
    },
    {
      id: 'UAV-CQ052', model: 'DJI M350', reg_no: 'B-M352', ua_id: 'RID-CQ052', phase: 'CRUISE',
      lat: 29.70150, lon: 106.63140, alt_msl: 686, speed: 24.8, heading: 72, vertical_speed: 0.4,
      battery_pct: 64, link_quality: 4, emergency: false, rid_lost: true,
      route: [{ lat: 29.6860, lon: 106.6120, alt_msl: 690 }, { lat: 29.7015, lon: 106.6314, alt_msl: 686 }, { lat: 29.7160, lon: 106.6620, alt_msl: 660 }]
    },
    {
      id: 'UAV-CQ009', model: 'Alpha 800', reg_no: 'B-AL09', ua_id: 'RID-CQ009', phase: 'STANDBY',
      lat: 29.71690, lon: 106.63190, alt_msl: 332, speed: 0, heading: 40, vertical_speed: 0,
      battery_pct: 96, link_quality: 5, emergency: false, rid_lost: false, route: []
    }
  ];

  /* ---------------- 当前程序 ---------------- */
  var program = {
    type: 'arrival', version: 'ARR-2026.09.09-A03', source: 'dynamic', plan_id: 'PLAN-CQ-260909-018',
    waypoints: [
      { lat: 29.7480, lon: 106.6040, alt_msl: 720, speed: 22 },
      { lat: 29.7390, lon: 106.6160, alt_msl: 650, speed: 20 },
      { lat: 29.7270, lon: 106.6240, alt_msl: 515, speed: 18 },
      { lat: 29.7186, lon: 106.6345, alt_msl: 327, speed: 8 }
    ],
    miss_approach: [
      { lat: 29.7270, lon: 106.6240, alt_msl: 515, speed: 18 },
      { lat: 29.7350, lon: 106.6420, alt_msl: 580, speed: 20 },
      { lat: 29.7470, lon: 106.6510, alt_msl: 650, speed: 22 }
    ]
  };

  /* ---------------- 机位（地面站） ---------------- */
  var stands = [
    { id: 'S-01', name: 'A01', type: 'indoor', status: 'occupied', occupied_by: 'UAV-CQ009', charge_kw: 30, max_size_m: 3.2, priority: 1 },
    { id: 'S-02', name: 'A02', type: 'indoor', status: 'reserved', occupied_by: 'UAV-CQ018', charge_kw: 60, max_size_m: 4.5, priority: 2 },
    { id: 'S-03', name: 'A03', type: 'indoor', status: 'free', occupied_by: null, charge_kw: 30, max_size_m: 3.2, priority: 3 },
    { id: 'S-04', name: 'B01', type: 'outdoor', status: 'occupied', occupied_by: 'UAV-CQ031', charge_kw: 22, max_size_m: 5.5, priority: 1 },
    { id: 'S-05', name: 'B02', type: 'outdoor', status: 'free', occupied_by: null, charge_kw: 22, max_size_m: 5.5, priority: 4 },
    { id: 'S-06', name: 'B03', type: 'outdoor', status: 'free', occupied_by: null, charge_kw: 11, max_size_m: 4.0, priority: 5 }
  ];

  /* ---------------- RID900 探测目标 ---------------- */
  var rid_targets = [
    { id: 'RID900-7A21', vendor: '星网智控', model: 'RID900', lat: 29.72310, lon: 106.64650, alt_msl: 416, heading: 258, speed: 6.4, vertical_speed: -0.4, rssi: -58, snr: 21, pilot_lat: 29.71780, pilot_lon: 106.63390 },
    { id: 'RID900-7A26', vendor: '星网智控', model: 'RID900', lat: 29.70640, lon: 106.62340, alt_msl: 572, heading: 84, speed: 13.2, vertical_speed: 1.1, rssi: -71, snr: 14, pilot_lat: 29.69510, pilot_lon: 106.61620 },
    { id: 'RID900-7A31', vendor: '天域感知', model: 'RID900', lat: 29.73050, lon: 106.61720, alt_msl: 488, heading: 190, speed: 4.6, vertical_speed: 0, rssi: -64, snr: 17, pilot_lat: 29.72540, pilot_lon: 106.62040 }
  ];

  /* ---------------- 环境传感器 ---------------- */
  var sensor = { wind_speed: 5.8, wind_dir: 68, temperature: 27.4, humidity: 66, pressure: 1008.6, light: 4820, rainfall: 0.4 };

  /* ---------------- 停靠调度 ---------------- */
  var dispatch = { waiting_count: 3, inbound: 'UAV-CQ044 / 待确认', outbound: 'UAV-CQ018 / 准备离场', deviation_alerts: 2 };

  /* ---------------- C 端：当前飞手（虚拟注册客户） ---------------- */
  var profile = {
    pilot_id: 'PILOT-CQ-018',
    name: '张启明',
    org: '重庆云行科技',
    phone: '138****6018',
    real_name_verified: true,
    qualification: 'eVTOL / V2',
    license_no: 'UA-12H7K9Q3',          // 实名登记号
    ua_id: '1581F3A7C2D94B6E',          // 唯一产品识别码
    valid_until: '2027-04-18',
    fleet: [                            // 我的飞行器（引用 traffic.id）
      { id: 'UAV-CQ031', alias: '云行 01 号', model: 'EH216-S', role: '载人试飞' },
      { id: 'UAV-CQ009', alias: '云行 待命机', model: 'Alpha 800', role: '备用运力' }
    ],
    home_airport: 'CQ-LX01'
  };

  /* ---------------- 消息 / 告警 ---------------- */
  var messages = [
    { id: 'M-1006', ts: '14:28:31', type: 'ATC', level: 'info', title: '起降许可已发布', body: 'UAV-CQ031 · APPROVE · 许可窗口 18 分钟', read: false },
    { id: 'M-1005', ts: '14:28:24', type: 'RID', level: 'warn', title: 'RID 信号超时', body: 'UAV-CQ052 连续 3 个广播周期未收到报文', read: false },
    { id: 'M-1004', ts: '14:28:17', type: 'METEO', level: 'info', title: '气象更新', body: '东北风 5.8 m/s，阵风 8.2 m/s，能见度 9.6 km', read: false },
    { id: 'M-1003', ts: '14:27:52', type: 'C2', level: 'info', title: 'C2 指令已确认', body: 'UAV-CQ031 进近航向确认，执行 ARR-2026.09.09-A03', read: true },
    { id: 'M-1002', ts: '14:26:40', type: 'ALERT', level: 'danger', title: '飞行器紧急状态', body: 'UAV-CQ044 电量 39%，悬停等待地面确认', read: false },
    { id: 'M-1001', ts: '14:24:08', type: 'SYS', level: 'info', title: '空域限制生效', body: '东侧临时限制区 ASP-101 生效，450-900 m MSL', read: true }
  ];

  window.FlyerMock = {
    airport: airport,
    obstacles: obstacles,
    airspaces: airspaces,
    meteo: meteo,
    traffic: traffic,
    program: program,
    stands: stands,
    rid_targets: rid_targets,
    sensor: sensor,
    dispatch: dispatch,
    profile: profile,
    messages: messages
  };
}());
