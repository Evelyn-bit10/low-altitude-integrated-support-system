(function () {
  'use strict';

  var snapshot = {
    schema_version: '1.0',
    frame: 'WGS84',
    altitude_ref: 'MSL',
    generated_at: '2026-09-09T14:28:30.000Z',
    airport: {
      code: 'CQ-LX01', name: '龙兴低空起降点', lat: 29.71860, lon: 106.63450,
      elevation: 327, safe_radius: 3000, runway_heading: 42
    },
    obstacles: [
      { id: 'OBS-001', name: '北侧通信塔', type: 'fixed', lat: 29.72820, lon: 106.63850, base_msl: 330, top_msl: 462, radius: 32, buffer: 80, active: true },
      { id: 'OBS-002', name: '滨江吊塔', type: 'dynamic', lat: 29.70940, lon: 106.62940, base_msl: 330, top_msl: 388, radius: 44, buffer: 120, active: true },
      { id: 'OBS-003', name: '西侧厂房', type: 'fixed', lat: 29.71450, lon: 106.61540, base_msl: 327, top_msl: 372, radius: 95, buffer: 60, active: false },
      { id: 'OBS-004', name: '东南临时吊装区', type: 'dynamic', lat: 29.70400, lon: 106.64900, base_msl: 326, top_msl: 405, radius: 72, buffer: 110, active: true }
    ],
    airspaces: [
      { id: 'ASP-101', name: '东侧临时限制区', polygon: [[29.7350,106.6420],[29.7350,106.6570],[29.7210,106.6650],[29.7140,106.6500],[29.7210,106.6380]], floor_msl: 450, ceiling_msl: 900, active: true },
      { id: 'ASP-203', name: '滨江训练空域', polygon: [[29.7030,106.6050],[29.7160,106.6020],[29.7110,106.6200],[29.6970,106.6210]], floor_msl: 380, ceiling_msl: 760, active: true }
    ],
    meteo: {
      timestamp: '2026-09-09T14:28:00.000Z', wind_speed: 5.8, wind_dir: 68,
      gust: 8.2, visibility: 9600, cloud_base_agl: 680, turbulence: 2,
      wind_shear: 1, temperature: 27.4, dew_point: 21.6, pressure: 1008.6
    },
    traffic: [
      { id: 'UAV-CQ031', model: 'EH216-S', reg_no: 'B-EC31', ua_id: 'RID-CQ031', phase: 'APPROACH', lat: 29.72720, lon: 106.62440, alt_msl: 515, speed: 18.4, heading: 124, vertical_speed: -1.8, battery_pct: 72, link_quality: 5, emergency: false, rid_lost: false, route: [{lat:29.7400,lon:106.6100,alt_msl:620},{lat:29.7272,lon:106.6244,alt_msl:515},{lat:29.7186,lon:106.6345,alt_msl:327}] },
      { id: 'UAV-CQ018', model: 'VoloCity', reg_no: 'B-EV18', ua_id: 'RID-CQ018', phase: 'DEPARTURE', lat: 29.71030, lon: 106.64240, alt_msl: 438, speed: 21.7, heading: 318, vertical_speed: 3.5, battery_pct: 88, link_quality: 4, emergency: false, rid_lost: false, route: [{lat:29.7186,lon:106.6345,alt_msl:327},{lat:29.7103,lon:106.6424,alt_msl:438},{lat:29.7050,lon:106.6540,alt_msl:560}] },
      { id: 'UAV-CQ044', model: '物流六旋翼', reg_no: 'B-DR44', ua_id: 'RID-CQ044', phase: 'HOVER', lat: 29.72180, lon: 106.64820, alt_msl: 404, speed: 0.9, heading: 260, vertical_speed: 0.1, battery_pct: 39, link_quality: 3, emergency: true, rid_lost: false, route: [{lat:29.7190,lon:106.6390,alt_msl:395},{lat:29.7218,lon:106.6482,alt_msl:404}] },
      { id: 'UAV-CQ052', model: 'DJI M350', reg_no: 'B-M352', ua_id: 'RID-CQ052', phase: 'CRUISE', lat: 29.70150, lon: 106.63140, alt_msl: 686, speed: 24.8, heading: 72, vertical_speed: 0.4, battery_pct: 64, link_quality: 4, emergency: false, rid_lost: true, route: [{lat:29.6860,lon:106.6120,alt_msl:690},{lat:29.7015,lon:106.6314,alt_msl:686},{lat:29.7160,lon:106.6620,alt_msl:660}] },
      { id: 'UAV-CQ009', model: 'Alpha 800', reg_no: 'B-AL09', ua_id: 'RID-CQ009', phase: 'STANDBY', lat: 29.71690, lon: 106.63190, alt_msl: 332, speed: 0, heading: 40, vertical_speed: 0, battery_pct: 96, link_quality: 5, emergency: false, rid_lost: false, route: [] }
    ],
    program: {
      type: 'arrival', version: 'ARR-2026.09.09-A03', source: 'dynamic', plan_id: 'PLAN-CQ-260909-018',
      waypoints: [
        {lat:29.7480,lon:106.6040,alt_msl:720,speed:22},
        {lat:29.7390,lon:106.6160,alt_msl:650,speed:20},
        {lat:29.7270,lon:106.6240,alt_msl:515,speed:18},
        {lat:29.7186,lon:106.6345,alt_msl:327,speed:8}
      ],
      miss_approach: [
        {lat:29.7270,lon:106.6240,alt_msl:515,speed:18},
        {lat:29.7350,lon:106.6420,alt_msl:580,speed:20},
        {lat:29.7470,lon:106.6510,alt_msl:650,speed:22}
      ]
    }
  };

  var programAnalysis = {
    program: snapshot.program,
    risk: {
      score: 28, level: 'LOW', level_name: '低风险', program_status: 'VALID',
      matched_plan_id: snapshot.program.plan_id,
      factors: { obstacle: 8, meteo: 9, airspace: 5, traffic: 6 }
    },
    compliance: {
      passed: true,
      checks: [
        { name: '障碍物净空', pass: true, detail: '航路保护区内无障碍物穿越', margin: 86 },
        { name: '气象窗口', pass: true, detail: '风速、阵风及能见度满足阈值', margin: 2.2 },
        { name: '空域边界', pass: true, detail: '未进入活动限制区', margin: 340 },
        { name: '复飞路径', pass: true, detail: '复飞航路连续且满足爬升要求', margin: 42 }
      ]
    },
    simulate: { passed: true, checks: ['航迹连续性通过', '碰撞检测通过', '速度包络通过', '终端点约束通过'] },
    meteo: snapshot.meteo,
    alarm: '',
    last_event: '程序 A03 已通过仿真与合规校验'
  };

  var ground = {
    stands: [
      {id:'S-01',name:'A01',type:'indoor',status:'occupied',occupied_by:'UAV-CQ009',charge_kw:30,max_size_m:3.2,priority:1},
      {id:'S-02',name:'A02',type:'indoor',status:'reserved',occupied_by:'UAV-CQ018',charge_kw:60,max_size_m:4.5,priority:2},
      {id:'S-03',name:'A03',type:'indoor',status:'free',occupied_by:null,charge_kw:30,max_size_m:3.2,priority:3},
      {id:'S-04',name:'B01',type:'outdoor',status:'occupied',occupied_by:'UAV-CQ031',charge_kw:22,max_size_m:5.5,priority:1},
      {id:'S-05',name:'B02',type:'outdoor',status:'free',occupied_by:null,charge_kw:22,max_size_m:5.5,priority:4},
      {id:'S-06',name:'B03',type:'outdoor',status:'free',occupied_by:null,charge_kw:11,max_size_m:4.0,priority:5}
    ],
    rid_targets: [
      {id:'RID900-7A21',vendor:'星网智控',model:'RID900',lat:29.72310,lon:106.64650,alt_msl:416,heading:258,speed:6.4,vertical_speed:-0.4,rssi:-58,snr:21,pilot_lat:29.71780,pilot_lon:106.63390},
      {id:'RID900-7A26',vendor:'星网智控',model:'RID900',lat:29.70640,lon:106.62340,alt_msl:572,heading:84,speed:13.2,vertical_speed:1.1,rssi:-71,snr:14,pilot_lat:29.69510,pilot_lon:106.61620},
      {id:'RID900-7A31',vendor:'天域感知',model:'RID900',lat:29.73050,lon:106.61720,alt_msl:488,heading:190,speed:4.6,vertical_speed:0,rssi:-64,snr:17,pilot_lat:29.72540,pilot_lon:106.62040}
    ],
    sensor: { wind_speed:5.8, wind_dir:68, temperature:27.4, humidity:66, pressure:1008.6, light:4820, rainfall:0.4 },
    dispatch: { waiting_count:3, inbound:'UAV-CQ044 / 待确认', outbound:'UAV-CQ018 / 准备离场', deviation_alerts:2 }
  };

  var messages = [
    { timestamp:'14:28:31', type:'C2', target:'UAV-CQ031', content:'进近航向确认，执行程序 ARR-2026.09.09-A03' },
    { timestamp:'14:28:29', type:'RID', target:'UAV-CQ044', content:'远程识别更新，链路质量 3 / 5' },
    { timestamp:'14:28:24', type:'ATC', target:'UAV-CQ031', content:'APPROVE · 许可窗口剩余 00:18:00' },
    { timestamp:'14:28:17', type:'METEO', target:'ALL', content:'东北风 5.8 m/s，阵风 8.2 m/s，能见度 9.6 km' },
    { timestamp:'14:28:08', type:'SYS', target:'OBS-001', content:'北侧通信塔净空校验通过' },
    { timestamp:'14:27:56', type:'RID', target:'UAV-CQ052', content:'RID 信号超时，已进入观察清单' }
  ];

  var business = {
    plans: [
      { plan_id:'PLAN-CQ-260909-018', applicant:'重庆云行科技', operation:'arrival / eVTOL', decision:'APPROVE', valid_until:'2026-09-09 15:00', status:'active' },
      { plan_id:'PLAN-CQ-260909-021', applicant:'西部物流试验场', operation:'departure / UAV', decision:'HOLD', valid_until:'2026-09-09 16:30', status:'review' },
      { plan_id:'PLAN-CQ-260909-024', applicant:'龙兴巡检中心', operation:'cruise / UAV', decision:'DENY', valid_until:'—', status:'denied' }
    ],
    pilots: [
      { id:'PILOT-CQ-018', name:'张启明', organization:'重庆云行科技', real_name_verified:true, qualification:'eVTOL / V2', valid_until:'2027-04-18', status:'active' },
      { id:'PILOT-CQ-024', name:'李若川', organization:'西部物流试验场', real_name_verified:true, qualification:'UAV / V3', valid_until:'2026-11-02', status:'active' },
      { id:'PILOT-CQ-031', name:'王思远', organization:'龙兴巡检中心', real_name_verified:false, qualification:'UAV / V2', valid_until:'2026-09-30', status:'review' }
    ],
    audit: [
      { timestamp:'14:28:24', actor:'系统引擎', action:'发布起降许可', target:'PLAN-CQ-260909-018', result:'success' },
      { timestamp:'14:26:18', actor:'陈默 / 调度员', action:'确认动态程序', target:'ARR-2026.09.09-A03', result:'success' },
      { timestamp:'14:12:43', actor:'赵宁 / 安全员', action:'切换障碍物状态', target:'OBS-003', result:'success' },
      { timestamp:'13:48:21', actor:'系统引擎', action:'记录 RID 丢失告警', target:'UAV-CQ052', result:'recorded' }
    ]
  };

  var analytics = {
    hours: ['04','05','06','07','08','09','10','11','12','13','14','15'],
    online: [2,3,2,4,5,6,5,7,8,6,9,8],
    arrivals: [1,1,0,2,2,3,2,4,3,2,4,3],
    departures: [1,2,2,2,3,3,3,3,5,4,5,5],
    occupancy: [32,38,34,47,55,63,58,72,67,61,70,67],
    wind: [2.8,3.1,3.8,4.5,5.2,5.7,6.1,5.8],
    temperature: [22.4,23.2,24.0,25.1,26.3,27.0,27.6,27.4],
    alarm_labels: ['通讯链路','气象环境','空域程序','机位调度'],
    alarm_values: [12,7,3,2]
  };

  window.LAVMock = {
    snapshot: snapshot,
    program_analysis: programAnalysis,
    ground: ground,
    messages: messages,
    business: business,
    analytics: analytics
  };
}());
