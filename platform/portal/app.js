(function () {
  'use strict';

  var Mock = window.LAVMock;
  var Api = window.LAVApi;
  var Visuals = window.LAVVisuals;
  var app = document.getElementById('app');
  var overlayRoot = document.getElementById('overlay-root');
  var toastRoot = document.getElementById('toast-root');
  var cleanup = [];
  var resizeTimer = 0;

  function clone(value) { return JSON.parse(JSON.stringify(value)); }
  function safeArray(value) { return Array.isArray(value) ? value : []; }
  function safeObject(value) { return value && typeof value === 'object' && !Array.isArray(value) ? value : {}; }
  function esc(value) { return String(value == null || value === '' ? '—' : value).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];}); }
  function number(value, digits) { var n=Number(value); return isFinite(n) ? n.toFixed(digits == null ? 0 : digits) : '—'; }
  function localTime(value) { if (!value) return '—'; var d=new Date(value); return isNaN(d.getTime()) ? String(value) : d.toLocaleString('zh-CN',{hour12:false}); }
  function nowTime() { return new Date().toLocaleTimeString('zh-CN',{hour12:false}); }
  function routeName(route) { return {home:'运行总览',situation:'实时态势',program:'飞行程序',decision:'AI 决策',ground:'地面站机位',dashboard:'数据看板',business:'业务管理',admin:'系统管理'}[route] || '运行总览'; }
  function parseRoute() { var value=location.hash.replace(/^#\/?/,'').split('?')[0]; return ['home','situation','program','decision','ground','dashboard','business','admin'].indexOf(value)>=0?value:'home'; }

  var state = {
    route: parseRoute(),
    snapshot: clone(Mock.snapshot),
    program: clone(Mock.program_analysis),
    ground: clone(Mock.ground),
    dedup: null,
    direction: 'S',
    plansLib: { arrival: [], departure: [] },
    planDirs: [],
    plansLoaded: false,
    push: null,
    dirTouched: false,
    source: { core:'mock', program:'mock', ground:'mock' },
    // 默认「演示数据」：门户完整展示内置演示数据（飞行程序必定显示、全页坐标统一）。
    // 统一接口全部保留，切到 live 即接入三个子系统；也可用 ?mode=live 或 LAV_CONFIG.dataMode 指定。
    dataMode: (function(){var cfg=(Api&&Api.config)||{};if(cfg.dataMode==='live')return 'live';if(/[?&]mode=live/.test(location.search))return 'live';return 'demo';})(),
    syncing: false,
    lastSync: null,
    selectedTraffic: 'UAV-CQ031',
    businessTab: 'plans',
    adverseWeather: false,
    actionBusy: false,
    // AI 决策页
    advice: null,
    adviceLoading: false,
    adviceError: null,
    adviceType: 'arrival',
    verdict: null,
    verdictBusy: false,
    verdictLoaded: false,
    // 系统管理页
    metrics: null,
    devices: null,
    routes: null,
    shadow: null,
    rl: null,
    adminLoaded: false,
    adminBusy: false
  };

  function normalizeSnapshot(raw) {
    raw=safeObject(raw);if(!raw.airport)return null;
    return {
      schema_version: raw.schema_version || '—', frame: raw.frame || 'WGS84', altitude_ref: raw.altitude_ref || 'MSL',
      generated_at: raw.generated_at || new Date().toISOString(), airport:safeObject(raw.airport),
      obstacles:safeArray(raw.obstacles), airspaces:safeArray(raw.airspaces), meteo:safeObject(raw.meteo),
      program:raw.program?safeObject(raw.program):null, traffic:safeArray(raw.traffic)
    };
  }

  function normalizeProgram(raw) {
    raw=safeObject(raw);
    return {
      // 航路必须取 canonical 快照里的经纬度航路：/api/program/current 的 program.waypoints 是 ENU(x/y/z)，画不出地图也填不了坐标表
      program: state.snapshot.program || clone(Mock.snapshot.program),
      risk: raw.risk || null,
      compliance: raw.compliance || null,
      simulate: raw.simulate || null,
      meteo: raw.meteo || state.snapshot.meteo,
      alarm: raw.alarm || '',
      last_event: raw.last_event || ''
    };
  }

  function normalizeGround(raw) {
    raw=safeObject(raw);
    return { stands:safeArray(raw.stands), rid_targets:safeArray(raw.rid_targets), sensor:safeObject(raw.sensor), dispatch:safeObject(raw.dispatch) };
  }

  function effectiveSnapshot() {
    var result=Object.assign({},state.snapshot);
    result.airport=safeObject(state.snapshot.airport);
    result.meteo=safeObject(state.snapshot.meteo);
    result.obstacles=safeArray(state.snapshot.obstacles);
    result.airspaces=safeArray(state.snapshot.airspaces);
    result.traffic=safeArray(state.snapshot.traffic);
    if (!result.traffic.length) result.traffic=clone(Mock.snapshot.traffic);
    result.program=state.snapshot.program || Mock.snapshot.program;
    return result;
  }

  function usesTrafficOverlay() { return state.source.core === 'live' && safeArray(state.snapshot.traffic).length === 0; }
  function riskScore() { var risk=state.program.risk;var value=typeof risk==='number'?risk:Number(risk&&risk.score);return isFinite(value)?Math.max(0,Math.min(100,value)):0; }
  function complianceChecks() { var c=state.program.compliance;if(Array.isArray(c))return c;return safeArray(c&&c.checks); }
  function compliancePassed() { var c=state.program.compliance;if(c&&typeof c.passed==='boolean')return c.passed;var checks=complianceChecks();return checks.length?checks.every(function(x){return x.pass!==false&&x.status!=='fail';}):false; }
  function simulationChecks() { var s=state.program.simulate;return safeArray(s&&s.checks); }
  function simulationPassed() { var s=state.program.simulate;return !!(s&&(s.passed===true||s.status==='pass')); }

  function sourceTag(source,label) { return '<span class="source-tag '+(source==='live'?'live':'mock')+'"><i></i>'+(label|| (source==='live'?'实时接口':'内置演示'))+'</span>'; }
  function badge(text,tone) { return '<span class="badge '+(tone||'')+'">'+esc(text)+'</span>'; }
  function icon(name) {
    var icons={radar:'⌁',route:'⌘',stand:'▦',chart:'◒',business:'◇',wind:'≋',alert:'!',link:'↗',shield:'◆',clock:'◷',plane:'✦'};
    return icons[name]||'·';
  }
  function breadcrumb(current) { return '<div class="breadcrumb"><a href="#/home" data-nav="home">挺中航空</a><span>›</span><b>'+esc(current)+'</b></div>'; }
  function pageHead(kicker,title,description,actions) { return '<div class="page-head"><div><div class="eyebrow">'+esc(kicker)+'</div><h1>'+esc(title)+'</h1><p>'+description+'</p></div><div class="page-actions">'+(actions||'')+'</div></div>'; }
  function panel(title,subtitle,tool,body,className) { return '<section class="panel '+(className||'')+'"><header class="panel-head"><div><h2>'+title+'</h2>'+(subtitle?'<p>'+subtitle+'</p>':'')+'</div>'+(tool||'')+'</header>'+body+'</section>'; }
  function kpi(label,value,unit,foot,ico,tone) { return '<article class="kpi panel '+(tone||'')+'"><div class="kpi-top"><span>'+label+'</span><i>'+icon(ico)+'</i></div><strong class="mono">'+value+'<small>'+unit+'</small></strong><footer>'+foot+'</footer></article>'; }
  function button(label,action,kind,extra) { return '<button type="button" class="button '+(kind||'')+'" data-action="'+action+'" '+(extra||'')+'>'+label+'</button>'; }
  function phaseLabel(value) { return {APPROACH:'进近',DEPARTURE:'离场',HOVER:'悬停',CRUISE:'巡航',STANDBY:'待机',LANDED:'已落地'}[value]||value; }
  function phaseTone(value) { return value==='HOVER'?'danger':value==='APPROACH'?'warning':value==='STANDBY'||value==='LANDED'?'success':'info'; }
  function decisionFor(traffic) {
    if(traffic.emergency)return{value:'DENY',tone:'danger',reason:'飞行器上报紧急状态，禁止进入起降航路。'};
    if(traffic.rid_lost)return{value:'HOLD',tone:'warning',reason:'RID 信号丢失，保持当前位置并等待身份复核。'};
    if(Number(traffic.battery_pct)<40)return{value:'HOLD',tone:'warning',reason:'电量低于演示阈值，等待地面站机位确认。'};
    if(Number(traffic.link_quality)<=2)return{value:'HOLD',tone:'warning',reason:'C2 链路质量不足，暂缓起降。'};
    return{value:'APPROVE',tone:'success',reason:'当前航迹、RID 与链路状态满足演示许可条件。'};
  }

  function renderHome() {
    var s=effectiveSnapshot(),g=state.ground,traffic=s.traffic,occupied=safeArray(g.stands).filter(function(x){return x.status!=='free';}).length;
    var alarms=traffic.filter(function(x){return x.emergency||x.rid_lost;}).length+Number(g.dispatch.deviation_alerts||0);
    return '<div class="page home-page">'+breadcrumb('运行总览')+
      '<section class="hero"><div class="hero-copy"><div class="eyebrow"><span class="eyebrow-line"></span>INTEGRATED SKYPORT OPERATIONS</div><h1>每一次起降<br><em>都有据可循</em></h1><p>贯通感知、通信、规划与业务的低空起降点统一运行门户。数据先于界面到达，决策在同一张图上闭环。</p><div class="hero-actions">'+button('进入实时态势&nbsp; ↗','go-situation','primary')+button('同步运行数据','sync','ghost')+'</div><div class="hero-caption">'+sourceTag(state.source.core)+(usesTrafficOverlay()?badge('态势采用演示目标','warning'):'')+'<span class="mono">'+esc(s.airport.code)+' · '+esc(s.frame)+' / '+esc(s.altitude_ref)+'</span></div></div>'+
      '<div class="hero-visual"><div class="orbital"><span class="orbit o1"></span><span class="orbit o2"></span><span class="orbit o3"></span><span class="orb-core"><i></i><b>'+esc(s.airport.code)+'</b><small>SKYPORT</small></span><span class="blip b1"></span><span class="blip b2"></span><span class="blip b3"></span></div><div class="hero-reading r1"><small>RUNWAY</small><b class="mono">'+number(s.airport.runway_heading,0)+'°</b></div><div class="hero-reading r2"><small>SAFE RADIUS</small><b class="mono">'+number(s.airport.safe_radius,0)+'m</b></div></div></section>'+
      '<div class="kpi-grid">'+kpi('在线飞行器',String(traffic.length),' 架','进近 '+traffic.filter(function(x){return x.phase==='APPROACH';}).length+' · 离场 '+traffic.filter(function(x){return x.phase==='DEPARTURE';}).length,'plane')+kpi('占用及预约机位',String(occupied),' / '+safeArray(g.stands).length,'地面站当前调度状态','stand')+kpi('开放告警',String(alarms),' 项','RID / 紧急 / 偏航','alert','warn')+kpi('今日运行架次','32',' 架次','较昨日 +14.2%','chart','cyan')+'</div>'+
      '<div class="section-title"><div><span>运行数据链</span><small>OPERATION PIPELINE</small></div><b>END-TO-END</b></div><section class="panel flowline">'+[
        ['ground','01','数据采集','传感器 · RID · 遥测'],['situation','02','通讯态势','识别 · C2 · 周边空域'],['program','03','规划决策','程序 · 风险 · 合规'],['business','04','业务管理','许可 · 飞手 · 审计']
      ].map(function(x,i){return '<a href="#/'+x[0]+'" data-nav="'+x[0]+'" class="flow-node"><span class="flow-index mono">'+x[1]+'</span><div><b>'+x[2]+'</b><small>'+x[3]+'</small></div>'+(i<3?'<i>→</i>':'')+'</a>';}).join('')+'</section></div>';
  }

  function trafficRow(t) { var d=decisionFor(t);return '<button type="button" class="traffic-row '+(state.selectedTraffic===t.id?'active':'')+'" data-entity="traffic" data-id="'+esc(t.id)+'"><span class="phase-dot '+phaseTone(t.phase)+'"></span><span><b>'+esc(t.callsign||t.id)+'</b>'+(t.merged?' <em class="merge-tag">双源</em>':'')+'<small>'+esc(phaseLabel(t.phase))+' · '+number(t.alt_msl,0)+' m MSL</small></span><span class="traffic-meta"><em class="mono">'+number(t.speed,1)+'</em><small>m/s</small></span>'+badge(d.value,d.tone)+'</button>'; }
  function renderSituation() {
    var s=effectiveSnapshot(),m=s.meteo,activeObstacles=s.obstacles.filter(function(x){return x.active!==false;}),alerts=s.traffic.filter(function(x){return x.emergency||x.rid_lost;});
    var dd=state.dedup||{input:s.traffic.length,unique_now:s.traffic.length,merged_now:0,tentative:0,enabled:false,node_id:'—',sources:[]};
    var mergedNow=Number(dd.merged_now||0),srcList=safeArray(dd.sources);
    return '<div class="page">'+breadcrumb('实时态势')+pageHead('COMMUNICATION · LIVE SITUATION','实时态势','起降点周边通信、识别与空域运行状态&nbsp; '+sourceTag(state.source.core),button('刷新快照','sync','ghost')+button('态势全屏','map-fullscreen','primary'))+
      '<section class="panel dedup-strip"><header><div><h2>多设备去重</h2><p>同一架无人机被多个设备看到时只保留一条&nbsp; '+(dd.enabled?'· 节点 '+esc(dd.node_id||'—'):'· 当前为演示数据')+'</p></div>'+(dd.enabled?badge('DEDUP ON','success'):badge('DEDUP OFF','warning'))+'</header>'+
      '<div class="dedup-flow"><div class="dedup-cell"><small>原始上报</small><b class="mono">'+number(dd.input,0)+'</b></div><i class="dedup-arrow">→</i>'+
      '<div class="dedup-cell accent"><small>去重后</small><b class="mono">'+number(dd.unique_now,0)+'</b></div>'+
      '<div class="dedup-cell"><small>多源融合</small><b class="mono">'+number(mergedNow,0)+'</b></div>'+
      '<div class="dedup-cell"><small>待确认</small><b class="mono">'+number(dd.tentative||0,0)+'</b></div>'+
      '<div class="dedup-sources">'+(srcList.length?srcList.map(function(x){return '<span>'+esc(x.source)+' <b class="mono">'+number(x.tracks,0)+'</b>'+(dd.source_sigmas&&dd.source_sigmas[x.source]?'<em class="sig">σ'+dd.source_sigmas[x.source]+'m</em>':'')+'</span>';}).join(''):'<span>暂无多源数据</span>')+(dd.clock_offsets&&Object.keys(dd.clock_offsets).length?'<span class="clk">时钟 '+Object.keys(dd.clock_offsets).map(function(k){var v=dd.clock_offsets[k];return esc(k)+' '+(v>0?'+':'')+v+'s';}).join(' · ')+'</span>':'')+'</div></div></section>'+
      '<div class="situation-grid"><section class="panel traffic-panel"><header class="panel-head"><div><h2>在线飞行器</h2><p>'+s.traffic.length+' targets · 点击查看 RID 详情</p></div>'+(usesTrafficOverlay()?badge('DEMO','warning'):badge('LIVE','success'))+'</header><div class="traffic-list">'+s.traffic.map(trafficRow).join('')+'</div></section>'+
      '<section class="panel map-panel"><header class="panel-head"><div><h2>'+esc(s.airport.code)+' 周边态势</h2><p>WGS84 · MSL · Canvas tactical view</p></div><div class="legend"><span><i class="aircraft"></i>飞行器</span><span><i class="obstacle"></i>障碍物</span><span><i class="airspace"></i>空域</span></div></header><div class="map-stage"><canvas id="situation-map" aria-label="起降点周边态势图"></canvas><div class="map-north mono">N<br>↑</div><div class="map-coordinate mono">'+number(s.airport.lat,5)+' N&nbsp;&nbsp;'+number(s.airport.lon,5)+' E</div></div></section>'+
      '<section class="panel feed-panel"><header class="panel-head"><div><h2>C2 / RID 报文</h2><p>演示消息流 · 滚动更新</p></div><span class="pulse-dot"></span></header><div class="message-feed">'+Mock.messages.map(function(msg){return '<article><header><time class="mono">'+esc(msg.timestamp)+'</time>'+badge(msg.type,msg.type==='RID'?'purple':msg.type==='ATC'?'success':'info')+'<span class="mono">'+esc(msg.target)+'</span></header><p>'+esc(msg.content)+'</p></article>';}).join('')+'</div></section></div>'+
      '<div class="situation-bottom">'+panel('实时气象','METEO · '+localTime(m.timestamp),badge('WIND '+number(m.wind_dir,0)+'°','info'),'<div class="weather-grid"><div><small>平均风速</small><b class="mono">'+number(m.wind_speed,1)+'<i>m/s</i></b></div><div><small>阵风</small><b class="mono">'+number(m.gust,1)+'<i>m/s</i></b></div><div><small>能见度</small><b class="mono">'+number(Number(m.visibility)/1000,1)+'<i>km</i></b></div><div><small>云底高 AGL</small><b class="mono">'+number(m.cloud_base_agl,0)+'<i>m</i></b></div><div><small>温度 / 露点</small><b class="mono">'+number(m.temperature,1)+'°<i>/ '+number(m.dew_point,1)+'°</i></b></div><div><small>气压</small><b class="mono">'+number(m.pressure,1)+'<i>hPa</i></b></div></div>','weather-panel')+
      panel('活动障碍物','OBSTACLES · '+activeObstacles.length+' active',badge('净空监视','warning'),'<div class="compact-list">'+activeObstacles.map(function(o){return '<article><span class="object-icon">△</span><div><b>'+esc(o.name)+'</b><small class="mono">'+esc(o.id)+' · TOP '+number(o.top_msl,0)+'m</small></div>'+badge(o.type==='dynamic'?'动态':'固定',o.type==='dynamic'?'warning':'info')+'</article>';}).join('')+'</div>')+
      panel('运行告警','ALARM · '+alerts.length+' flight',badge((alerts.length+Number(state.ground.dispatch.deviation_alerts||0))+' OPEN','danger'),'<div class="alert-list">'+(alerts.length?alerts.map(function(t){return '<article class="alert-item '+(t.emergency?'critical':'warning')+'"><i>!</i><div><b>'+esc(t.id)+'</b><p>'+(t.emergency?'飞行器上报紧急状态':'RID 识别信号丢失')+'</p></div></article>';}).join(''):'<div class="empty-state">当前无飞行器告警</div>')+'<article class="alert-item warning"><i>~</i><div><b>偏航监测</b><p>'+number(state.ground.dispatch.deviation_alerts,0)+' 个调度偏航告警</p></div></article></div>')+'</div></div>';
  }

  var DIR_CN = { N:'北', NE:'东北', E:'东', SE:'东南', S:'南', SW:'西南', W:'西', NW:'西北' };

  function dirName(){ return DIR_CN[state.direction] || state.direction; }

  function directionBar(){
    var dirs = state.planDirs.length ? state.planDirs : ['N','NE','E','SE','S','SW','W','NW'];
    return '<section class="panel dir-bar"><header><div><h2>进出场方向</h2><p>选择方向后，从方案库生成进近 / 离场程序</p></div>'+
      (state.direction?badge(state.direction+' '+dirName(),'info'):'')+'</header><div class="dir-buttons">'+
      dirs.map(function(d){
        var label = d.name || d;
        return '<button type="button" class="dir-btn '+(state.direction===label?'active':'')+'" data-action="dir" data-dir="'+esc(label)+'">'+
          '<b class="mono">'+esc(label)+'</b><small>'+esc(DIR_CN[label]||'')+'</small></button>';
      }).join('')+'</div></section>';
  }

  function planCards(type){
    if(state.dataMode!=='live') return '<div class="empty-state">切换顶栏到「实时数据」后可查询方案库</div>';
    if(!state.plansLoaded) return '<div class="empty-state">正在加载方案库…</div>';
    var list = safeArray((state.plansLib[type]||[])).filter(function(p){ return !p.direction || p.direction===state.direction; });
    if(!list.length) return '<div class="empty-state">该方向暂无方案</div>';
    return list.map(function(p){
      return '<article class="plan-card"><div><b class="mono">'+esc(p.std_name||('PLAN-'+p.id))+'</b>'+
        '<small>'+esc(p.plan_name||'')+' · '+number(p.length_m,0)+' m · 视距≥'+number(p.min_vis,0)+' m</small></div>'+
        '<button type="button" class="button ghost" data-action="gen-plan" data-type="'+esc(type)+'" data-dir="'+esc(p.direction||state.direction)+'">生成</button></article>';
    }).join('');
  }

  function plansPanel(){
    return panel('方案库', 'LIBRARY · '+(state.direction||'—'), badge((safeArray(state.plansLib.arrival).length+safeArray(state.plansLib.departure).length)+' 套','info'),
      '<div class="plan-group"><h4>进近 ARRIVAL</h4>'+planCards('arrival')+'</div>'+
      '<div class="plan-group"><h4>离场 DEPARTURE</h4>'+planCards('departure')+'</div>');
  }

  function loadPlans(){
    if(state.plansLoaded) return;
    Promise.all([Api.plans('arrival'),Api.plans('departure')]).then(function(res){
      var a=res[0],d=res[1];
      if(a.ok&&a.data){state.plansLib.arrival=safeArray(a.data.plans);state.planDirs=safeArray(a.data.directions);}
      if(d.ok&&d.data){state.plansLib.departure=safeArray(d.data.plans);}
      state.plansLoaded=!!(a.ok||d.ok);
      render();
    }).catch(function(){state.plansLoaded=true;render();});
  }

  function generateProgram(type, dir){
    if(state.actionBusy)return;
    if(state.dataMode!=='live'){toast('切换到「实时数据」后才能生成方案','warning');return;}
    state.actionBusy=true;state.direction=dir||state.direction;
    toast('正在生成'+(type==='departure'?'离场':'进近')+'程序…','info');
    Api.generate(type,state.direction,'template').then(function(r){
      state.actionBusy=false;
      if(!r.ok){toast('生成失败，请检查后端','warning');return;}
      var meta=r.data.meta||{};
      return Api.snapshot().then(function(snap){
        if(snap.ok){var n=normalizeSnapshot(snap.data);if(n){state.snapshot=n;state.source.core='live';}}
        state.program=normalizeProgram(r.data);state.source.program='live';
        render();
        if(meta.available===false){toast('该方向不可用：'+(meta.reason||'校验未通过'),'warning');}
        else if(meta.fallback){toast('模板不适用，已动态重规划（'+meta.reason+')','warning');}
        else{toast('已生成 '+(r.data.program&&r.data.program.std_name||type),'success');}
      });
    }).catch(function(){state.actionBusy=false;toast('生成失败','warning');});
  }

  function renderProgram() {
    var p=state.program.program||effectiveSnapshot().program||Mock.snapshot.program,score=riskScore(),checks=complianceChecks(),simChecks=simulationChecks(),risk=state.program.risk||{};
    var level=risk.level_name||risk.level||(score<=35?'低风险':score<=65?'中风险':'高风险');
    return '<div class="page">'+breadcrumb('飞行程序')+pageHead('FLYCONTROL · DYNAMIC PROCEDURE','动态飞行程序','规划、风险、合规与仿真的统一决策工作台&nbsp; '+sourceTag(state.source.program),button('切换障碍物','toggle-obstacle','ghost')+button(state.adverseWeather?'恢复标准气象':'注入恶劣气象','weather-scenario','ghost')+button('重规划进近','replan-arrival','primary')+button('重规划离场','replan-departure','primary'))+
      directionBar()+
      '<div class="program-grid"><div class="program-main">'+panel(esc(p.type==='departure'?'离场程序':'进近程序'),'PLAN · '+esc(p.plan_id),'<button class="text-button" data-entity="program" data-id="current">查看完整详情 ↗</button>','<div class="program-map-stage"><canvas id="program-map"></canvas><div class="program-legend"><span><i class="route-main"></i>主程序</span><span><i class="route-missed"></i>复飞路径</span></div></div><div class="program-meta"><div><small>版本</small><b class="mono">'+esc(p.version)+'</b></div><div><small>来源</small><b>'+esc(p.source)+'</b></div><div><small>主航路点</small><b class="mono">'+safeArray(p.waypoints).length+'</b></div><div><small>复飞点</small><b class="mono">'+safeArray(p.miss_approach).length+'</b></div></div>','route-panel')+
      panel('高度剖面','VERTICAL PROFILE · MSL',badge('PROFILE','info'),'<div class="profile-stage"><canvas id="profile-map"></canvas></div>')+'</div>'+
      '<aside class="program-side">'+plansPanel()+panel('风险评分','RISK ENGINE',badge(esc(risk.program_status||'VALID'),score>65?'danger':'success'),'<div class="risk-wrap"><div class="risk-gauge" style="--risk:'+score+'"><div><b class="mono">'+number(score,0)+'</b><small>/ 100</small></div></div><div class="risk-copy"><strong>'+esc(level)+'</strong><p>综合障碍物、气象、空域与实时交通因子。</p><small class="mono">MATCH '+esc(risk.matched_plan_id||p.plan_id)+'</small></div></div>')+
      panel('合规校验','COMPLIANCE',badge(compliancePassed()?'PASSED':'REVIEW',compliancePassed()?'success':'warning'),'<div class="check-list">'+(checks.length?checks.map(function(c){var pass=c.pass!==false&&c.status!=='fail';return '<article><i class="'+(pass?'pass':'fail')+'">'+(pass?'✓':'!')+'</i><div><b>'+esc(c.name)+'</b><p>'+esc(c.detail)+'</p></div><span class="mono">'+(c.margin!=null?number(c.margin,1):'—')+'</span></article>';}).join(''):'<div class="empty-state">暂无校验明细</div>')+'</div>')+
      panel('仿真验证','SIMULATION',badge(simulationPassed()?'PASSED':'PENDING',simulationPassed()?'success':'warning'),'<div class="simulation-result"><div class="simulation-seal">'+(simulationPassed()?'✓':'…')+'</div><div><b>'+(simulationPassed()?'轨迹仿真通过':'等待仿真结果')+'</b><p>'+esc(state.program.last_event||'暂无最近事件')+'</p></div></div><div class="sim-tags">'+simChecks.map(function(c){return badge(typeof c==='string'?c:(c.name||c.detail||'检查项'),'info');}).join('')+'</div>')+'</aside></div>'+
      '<div class="section-title"><div><span>航路点坐标</span><small>WAYPOINT MANIFEST</small></div>'+badge(esc(p.version),'info')+'</div><section class="panel table-panel"><div class="table-scroll"><table><thead><tr><th>序号</th><th>路径类型</th><th>纬度</th><th>经度</th><th>高度 MSL</th><th>速度</th></tr></thead><tbody>'+safeArray(p.waypoints).map(function(w,i){return '<tr><td class="mono">W'+String(i+1).padStart(2,'0')+'</td><td>'+badge('MAIN','success')+'</td><td class="mono">'+number(w.lat,6)+'</td><td class="mono">'+number(w.lon,6)+'</td><td class="mono">'+number(w.alt_msl,1)+' m</td><td class="mono">'+number(w.speed,1)+' m/s</td></tr>';}).join('')+safeArray(p.miss_approach).map(function(w,i){return '<tr><td class="mono">M'+String(i+1).padStart(2,'0')+'</td><td>'+badge('MISSED','warning')+'</td><td class="mono">'+number(w.lat,6)+'</td><td class="mono">'+number(w.lon,6)+'</td><td class="mono">'+number(w.alt_msl,1)+' m</td><td class="mono">'+number(w.speed,1)+' m/s</td></tr>';}).join('')+'</tbody></table></div></section></div>';
  }

  function standCard(s) { var tone=s.status==='free'?'success':s.status==='reserved'?'warning':'danger',label={free:'空闲',reserved:'已预约',occupied:'占用'}[s.status]||s.status;return '<button class="stand-card panel '+s.status+'" data-entity="stand" data-id="'+esc(s.id)+'"><header><span><b class="mono">'+esc(s.name)+'</b><small>'+esc(s.type==='indoor'?'室内机位':'室外机位')+'</small></span>'+badge(label,tone)+'</header><div class="stand-viz"><span class="stand-outline"><i></i></span><strong>'+esc(s.occupied_by||'READY')+'</strong></div><footer><span>充电 <b class="mono">'+number(s.charge_kw,0)+' kW</b></span><span>限宽 <b class="mono">'+number(s.max_size_m,1)+' m</b></span></footer></button>'; }
  function sensorCard(label,value,unit,ratio,ico) { var p=Math.max(0,Math.min(1,Number(ratio)||0));return '<article class="sensor-card"><div class="sensor-ring" style="--sensor:'+(p*100)+'"><span>'+icon(ico)+'</span></div><div><small>'+label+'</small><b class="mono">'+value+'<i>'+unit+'</i></b></div></article>'; }
  function renderGround() {
    var g=state.ground,s=g.sensor,d=g.dispatch,stands=safeArray(g.stands),rid=safeArray(g.rid_targets);
    return '<div class="page">'+breadcrumb('地面站机位')+pageHead('GROUNDSTATION · STAND & SENSOR','地面站机位','停靠调度、RID900 探测与 Modbus 传感器实时视图&nbsp; '+sourceTag(state.source.ground),button('刷新地面站数据','refresh-ground','ghost'))+
      '<div class="ground-summary">'+kpi('机位总数',String(stands.length),' 个','室内 '+stands.filter(function(x){return x.type==='indoor';}).length+' · 室外 '+stands.filter(function(x){return x.type==='outdoor';}).length,'stand')+kpi('当前占用',String(stands.filter(function(x){return x.status==='occupied';}).length),' 个','预约 '+stands.filter(function(x){return x.status==='reserved';}).length+' 个','plane')+kpi('等待区',number(d.waiting_count,0),' 架','等待停靠调度','clock','warn')+kpi('偏航告警',number(d.deviation_alerts,0),' 项','持续距离监测','alert','warn')+'</div>'+
      '<div class="section-title"><div><span>机位总览</span><small>STAND OCCUPANCY</small></div><b>点击机位查看详情</b></div><div class="stand-grid">'+stands.map(standCard).join('')+'</div>'+
      '<div class="ground-lower"><div class="ground-column">'+panel('停靠调度','DOCK DISPATCH',badge('SCHEDULER','info'),'<div class="dispatch-track"><article><span class="dispatch-icon">IN</span><div><small>进场任务</small><b>'+esc(d.inbound)+'</b></div><i class="success">运行中</i></article><article><span class="dispatch-icon out">OUT</span><div><small>离场任务</small><b>'+esc(d.outbound)+'</b></div><i class="warning">准备中</i></article><article><span class="dispatch-icon wait">Q</span><div><small>等待区队列</small><b class="mono">'+number(d.waiting_count,0)+' 架等待</b></div><i>动态排序</i></article></div>')+
      panel('RID900 探测目标','REMOTE ID TARGETS',badge(rid.length+' TARGETS','purple'),'<div class="table-scroll rid-table"><table><thead><tr><th>序列号</th><th>厂商 / 型号</th><th>位置</th><th>高度</th><th>速度</th><th>信号</th></tr></thead><tbody>'+rid.map(function(r){return '<tr data-entity="rid" data-id="'+esc(r.id)+'"><td class="mono">'+esc(r.id)+'</td><td>'+esc(r.vendor)+'<small>'+esc(r.model)+'</small></td><td class="mono">'+number(r.lat,5)+'<small>'+number(r.lon,5)+'</small></td><td class="mono">'+number(r.alt_msl,0)+'m</td><td class="mono">'+number(r.speed,1)+'m/s</td><td>'+badge('SNR '+number(r.snr,0),Number(r.snr)>=16?'success':'warning')+'</td></tr>';}).join('')+'</tbody></table></div>')+'</div>'+
      '<div class="ground-column">'+panel('环境传感器','MODBUS · '+nowTime(),badge('CONNECTED','success'),'<div class="sensor-grid">'+sensorCard('风速',number(s.wind_speed,1),' m/s',s.wind_speed/12,'wind')+sensorCard('温度',number(s.temperature,1),' ℃',s.temperature/45,'chart')+sensorCard('湿度',number(s.humidity,0),' %',s.humidity/100,'radar')+sensorCard('气压',number(s.pressure,1),' hPa',.72,'shield')+'</div><div class="sensor-secondary"><div><small>风向</small><b class="mono">'+number(s.wind_dir,0)+'°</b></div><div><small>光照</small><b class="mono">'+number(s.light,0)+' lux</b></div><div><small>雨量</small><b class="mono">'+number(s.rainfall,1)+' mm</b></div></div>')+
      panel('数据接入说明','GROUNDSTATION STATUS',badge(state.source.ground==='live'?'LIVE BRIDGE':'PENDING REST',state.source.ground==='live'?'success':'warning'),'<div class="integration-note"><span>i</span><p>'+(state.source.ground==='live'?'已接入地面站数据桥，机位 / RID900 / Modbus 传感器实时刷新。':'地面站数据源未就绪，当前使用内置演示数据。')+'</p></div>')+'</div></div></div>';
  }

  function chartPanel(id,title,subtitle,tool) { return '<section class="panel chart-panel"><header class="panel-head"><div><h2>'+title+'</h2><p>'+subtitle+'</p></div>'+tool+'</header><div id="'+id+'" class="chart-slot"><canvas></canvas></div></section>'; }
  function pushPanel(){
    return '<div id="push-panel">'+pushPanelInner()+'</div>';
  }

  function pushPanelInner(){
    var p=state.push;
    if(!p){
      return panel('数据推送','UOM / 地方平台',badge('未连接','warning'),
        '<div class="empty-state">切换到「实时数据」后显示推送状态</div>','push-panel');
    }
    var q=p.queue||{}, rate=(p.success_rate==null)?'—':Math.round(p.success_rate*100)+'%';
    return panel('数据推送','UOM / 地方平台 · '+esc(p.mode||'—'),
      badge(p.enabled?(p.running?'ONLINE':'IDLE'):'OFF', p.enabled?'success':'warning'),
      '<div class="push-grid">'+
        '<div class="push-cell"><small>发送成功</small><b class="mono">'+number(q.sent,0)+'</b></div>'+
        '<div class="push-cell"><small>待发送</small><b class="mono">'+number(q.pending,0)+'</b></div>'+
        '<div class="push-cell"><small>失败放弃</small><b class="mono">'+number(q.dead,0)+'</b></div>'+
        '<div class="push-cell"><small>成功率</small><b class="mono">'+rate+'</b></div>'+
        '<div class="push-cell"><small>平均延迟</small><b class="mono">'+(q.avg_latency_ms==null?'—':number(q.avg_latency_ms,0)+' ms')+'</b></div>'+
        '<div class="push-cell"><small>节点</small><b class="mono">'+esc(p.node_id||'—')+'</b></div>'+
      '</div>'+
      '<div class="push-foot"><span class="mono">'+esc(p.endpoint||'—')+'</span>'+
        button('立即推送','push-flush','ghost')+'</div>'+
      (p.last_error?'<div class="push-error">最近错误：'+esc(p.last_error)+'</div>':''),
      'push-panel');
  }

  function refreshPushPanel(){
    var el=document.getElementById('push-panel');
    if(el){el.outerHTML=pushPanel();}
  }

  function renderDashboard() {
    var a=Mock.analytics;
    return '<div class="page">'+breadcrumb('数据看板')+pageHead('ANALYTICS · OPERATION INSIGHT','运行数据看板','跨系统汇总指标、趋势和运行质量&nbsp; '+sourceTag(state.source.core),button('更新数据','sync','ghost'))+
      '<div class="kpi-grid">'+kpi('今日架次','32',' 架次','较昨日 +14.2%','plane','cyan')+kpi('平均周转时长','18.6',' min','目标 ≤ 22 min','clock')+kpi('机位占用率','66.7',' %','4 / 6 active','stand')+kpi('安全事件','0',' 起','连续 18 天无事故','shield','cyan')+'</div>'+
      '<div class="dashboard-grid">'+chartPanel('traffic-chart','在线架次趋势','过去 12 小时 · 在线 / 离场',badge('12H','info'))+chartPanel('alarm-chart','告警分布','按运行来源归类',badge('24 TOTAL','danger'))+chartPanel('weather-chart','气象走势','风速 / 温度 · 过去 8 小时',badge('METEO','info'))+
      panel('运行质量','QUALITY TARGET',badge('THIS WEEK','success'),'<div class="quality-list">'+[['程序准时发布率','98.4',98.4],['RID 识别覆盖率','96.8',96.8],['C2 链路可用率','99.9',99.9],['传感器在线率','100',100],['告警闭环率','94.1',94.1]].map(function(q){return '<article><header><span>'+q[0]+'</span><b class="mono">'+q[1]+'%</b></header><div><i style="width:'+q[2]+'%"></i></div></article>';}).join('')+'</div>','quality-panel')+'</div>'+runtimePanel()+pushPanel()+'</div>';
  }

  function businessTable() {
    var b=Mock.business;
    if(state.businessTab==='pilots')return '<table><thead><tr><th>登记编号</th><th>飞手 / 客户</th><th>实名登记</th><th>资质等级</th><th>有效期</th><th>状态</th></tr></thead><tbody>'+b.pilots.map(function(p){return '<tr data-entity="pilot" data-id="'+esc(p.id)+'"><td class="mono">'+esc(p.id)+'</td><td>'+esc(p.name)+'<small>'+esc(p.organization)+'</small></td><td>'+badge(p.real_name_verified?'已核验':'待复核',p.real_name_verified?'success':'warning')+'</td><td>'+esc(p.qualification)+'</td><td class="mono">'+esc(p.valid_until)+'</td><td>'+badge(p.status==='active'?'可运行':'限制运行',p.status==='active'?'success':'warning')+'</td></tr>';}).join('')+'</tbody></table>';
    if(state.businessTab==='audit')return '<table><thead><tr><th>时间</th><th>操作人</th><th>动作</th><th>对象</th><th>结果</th></tr></thead><tbody>'+b.audit.map(function(x){return '<tr><td class="mono">'+esc(x.timestamp)+'</td><td>'+esc(x.actor)+'</td><td>'+esc(x.action)+'</td><td class="mono">'+esc(x.target)+'</td><td>'+badge(x.result==='success'?'成功':'已记录',x.result==='success'?'success':'warning')+'</td></tr>';}).join('')+'</tbody></table>';
    return '<table><thead><tr><th>计划 ID</th><th>申请主体</th><th>运行类型</th><th>许可决策</th><th>指令有效期</th><th>状态</th></tr></thead><tbody>'+b.plans.map(function(p){return '<tr data-entity="plan" data-id="'+esc(p.plan_id)+'"><td class="mono">'+esc(p.plan_id)+'</td><td>'+esc(p.applicant)+'</td><td>'+esc(p.operation)+'</td><td>'+badge(p.decision,p.decision==='APPROVE'?'success':p.decision==='HOLD'?'warning':'danger')+'</td><td class="mono">'+esc(p.valid_until)+'</td><td>'+badge(p.status==='active'?'已生效':p.status==='review'?'待复核':'已驳回',p.status==='active'?'success':p.status==='review'?'warning':'danger')+'</td></tr>';}).join('')+'</tbody></table>';
  }
  function renderBusiness() {
    var tabs=[['plans','飞行计划 / 许可'],['pilots','飞手 / 客户'],['audit','审计日志']];
    return '<div class="page">'+breadcrumb('业务管理')+pageHead('BUSINESS · PERMIT & AUDIT','业务管理','许可指令、实名登记与全链路审计的演示业务层&nbsp; '+sourceTag('mock','BUSINESS MOCK'),button('新建登记','new-registration','primary'))+
      '<div class="kpi-grid">'+kpi('待审批计划','02',' 项','1 项需安全复核','clock','warn')+kpi('有效许可指令','18',' 条','当前运行窗口','shield','cyan')+kpi('实名登记主体','36',' 个','飞手 + 客户','business')+kpi('审计完整率','100',' %','链路操作已留痕','link','cyan')+'</div>'+
      '<section class="panel business-panel"><header class="business-toolbar"><div class="tabs">'+tabs.map(function(t){return '<button class="tab '+(state.businessTab===t[0]?'active':'')+'" data-tab="'+t[0]+'">'+t[1]+'</button>';}).join('')+'</div><div>'+badge('INTERNAL DEMO','info')+'</div></header><div class="table-scroll">'+businessTable()+'</div></section><div class="integration-note business-note"><span>i</span><p>业务管理实体尚未纳入当前 canonical REST 契约，本页仅展示需求中明确要求的许可状态、实名登记、指令有效期与审计信息，不向 flycontrol 接口写入这些字段。</p></div></div>';
  }

  // ---- AI 决策页（只读建议，不执行）与系统管理页 ----
  var DEMO_CANDIDATES = [
    {direction:'S',score:1.0,available:true,mode:'template',fallback:false,metrics:{distance_m:2490,eta_s:166,clearance_m:132,crosswind_ms:0},reasons:['逆风 5.0 m/s、侧风 0.0（最优）','航程 2.5 km']},
    {direction:'N',score:0.92,available:true,mode:'template',fallback:false,metrics:{distance_m:2560,eta_s:171,clearance_m:118,crosswind_ms:1.2},reasons:['顺风 5.0 m/s，能耗略低','超障余度 118 m']},
    {direction:'SW',score:0.81,available:true,mode:'dynamic',fallback:true,metrics:{distance_m:2980,eta_s:199,clearance_m:96,crosswind_ms:3.4},reasons:['模板不适用，已动态重规划','航程偏长']},
    {direction:'NE',score:0,available:false,mode:'dynamic',fallback:true,metrics:{},reasons:['合规校验未通过：穿越限飞区']}
  ];
  var DEMO_ADVICE = {
    advice:'（演示示例）数据来源和观测时间需要核验。候选结果仅用于展示，不能作为放行或运行依据。',
    model:'demo-advisory', requires_human_review:true, validated:false, executed:false,
    context:{captured_at:'—',data_freshness:'unknown',candidates:DEMO_CANDIDATES,
      limitations:['演示数据，非真实观测','未接入真实空域许可与机型参数','模型输出可能有误，需人工复核后使用']}
  };
  var DEMO_DEVICES = [
    {id:'D-A-RID',name:'A 站 RID 接收机',source_key:'A-RID',kind:'rid',sigma_m:8,status:'online'},
    {id:'D-B-RID',name:'B 站 RID 接收机',source_key:'B-RID',kind:'rid',sigma_m:22,status:'online'},
    {id:'D-RADAR-1',name:'场面雷达',source_key:'RADAR-1',kind:'radar',sigma_m:15,status:'offline'}
  ];
  var DEMO_ROUTES = [
    {id:'R-EAST',name:'东侧进场走廊',kind:'corridor',points:[[0,-300],[900,-200],[1500,0]],floor_agl:30,ceiling_agl:120},
    {id:'R-NOFY',name:'施工禁飞区',kind:'no_fly',points:[[300,300],[600,300],[600,500]],floor_agl:0,ceiling_agl:200}
  ];
  var DEMO_METRICS = {
    metrics:{uptime_sec:0,frames:0,avg_frame_ms:0,frame_ms:{p50:0,p90:0,p99:0,max:0},candidates:{p50:0,p99:0,max:0},unique_tracks:{now:0,p50:0,max:0},counters:{matched:0,created:0,duplicate:0}},
    kalman:{tracks:0,sigma_mean:0,sigma_max:0,sigma_scale:1}
  };
  var DEMO_VERDICT = {
    code:'AVAILABLE_CANDIDATES',label:'存在可用候选',refusal_reason:null,
    recommended:{direction:'S',score:1.0,mode:'template',fallback:false,reasons:['逆风 5.0 m/s、侧风 0.0（最优）','航程 2.5 km'],metrics:{length_m:2490,crosswind_mps:0,clearance_m:132}},
    available_count:3,total_count:4,no_current_program:false,hard_forbid:false,hard_forbid_reasons:[],
    constraints:{max_crosswind_ms:12,min_visibility_m:500,moc_approach_m:75}
  };

  function candidateTable(list) {
    if(!list.length) return '<div class="empty-state">暂无候选（未请求或后端未返回）</div>';
    return '<div class="table-scroll"><table><thead><tr><th>方向</th><th>可用</th><th>评分</th><th>模式</th><th>距离</th><th>超障</th><th>侧风</th><th>理由</th></tr></thead><tbody>'+
      list.map(function(c){var m=c.metrics||{};
        var distance=(m.distance_m!=null?m.distance_m:m.length_m);
        var crosswind=(m.crosswind_ms!=null?m.crosswind_ms:m.crosswind_mps);
        return '<tr><td class="mono">'+esc(c.direction||'—')+'</td>'+
        '<td>'+badge(c.available?'可用':'不可用',c.available?'success':'danger')+'</td>'+
        '<td class="mono">'+number(c.score,3)+'</td><td>'+esc(c.mode||'—')+(c.fallback?' <em>回退</em>':'')+'</td>'+
        '<td class="mono">'+(distance!=null?number(distance,0)+' m':'—')+'</td>'+
        '<td class="mono">'+(m.clearance_m!=null?number(m.clearance_m,0)+' m':'—')+'</td>'+
        '<td class="mono">'+(crosswind!=null?number(crosswind,1)+' m/s':'—')+'</td>'+
        '<td class="muted-cell">'+esc(safeArray(c.reasons).join('；')||'—')+'</td></tr>';}).join('')+'</tbody></table></div>';
  }

  function verdictPanel(v, demo) {
    var verdict=v||(demo?DEMO_VERDICT:null);
    if(!verdict) return '<div class="empty-state" role="status">'+(state.verdictLoaded?'未能加载引擎结果，请刷新上下文。':'正在加载引擎结果…')+'</div>';
    var rec=demo||verdict.demo_only?{}:(verdict.recommended||{}), cst=verdict.constraints||{};
    var codeTone=verdict.code==='AVAILABLE_CANDIDATES'?'success':(verdict.code==='NO_AVAILABLE_CANDIDATE'?'warning':'danger');
    var head='<div class="verdict-head"><span>结论码</span><b>'+badge(verdict.code+' · '+verdict.label,codeTone)+'</b></div>';
    var recHtml=rec.direction?
      '<div class="verdict-recommend"><span>推荐方向</span><b class="mono">'+esc(rec.direction)+'</b>'+
      '<span>评分 '+number(rec.score,3)+'</span><span>'+esc(rec.mode||'—')+(rec.fallback?' · 回退':'')+'</span>'+
      '<div class="verdict-reasons">'+safeArray(rec.reasons).map(function(r){return '<div>'+esc(r)+'</div>';}).join('')+'</div></div>':
      '<div class="verdict-recommend"><span>未提供推荐方向</span><p>'+esc(verdict.refusal_reason||(demo?'内置演示不提供运行建议。':'暂无推荐方向。'))+'</p></div>';
    var redline=verdict.code==='INSUFFICIENT_DATA'&&!verdict.hard_forbid
      ?'<div class="verdict-redline">数据不足，无法判定运行限制。</div>'
      :verdict.hard_forbid
      ?'<div class="verdict-redline"><b>限制条件命中</b><div>'+safeArray(verdict.hard_forbid_reasons).map(esc).join('</div><div>')+'</div></div>'
      :'<div class="verdict-redline ok">演示检查未发现列出的限制；不代表运行安全。</div>';
    var constraints='<div class="verdict-constraints">'+
      '<span>侧风上限 <b class="mono">'+number(cst.max_crosswind_ms,0)+' m/s</b></span>'+
      '<span>能见度下限 <b class="mono">'+number(cst.min_visibility_m,0)+' m</b></span>'+
      '<span>超障余度 <b class="mono">'+number(cst.moc_approach_m!=null?cst.moc_approach_m:cst.moc_departure_m,0)+' m</b></span></div>';
    return head+recHtml+redline+(verdict.code==='INSUFFICIENT_DATA'?'':constraints)+
      '<div class="form-note">'+(demo||verdict.demo_only?'仅供演示，不可用于运行。':'数据状态：'+esc(verdict.data_freshness||'未知')+'。')+' 模型输出未经验证，需人工独立复核。</div>';
  }

  function adviceDivergence(adv) {
    var items=[];
    if(adv&&adv.safety_guard&&adv.safety_guard.triggered){
      items=items.concat(safeArray(adv.safety_guard.reasons).map(function(x){return x;}));
    }
    var verdict=state.verdict;
    if(adv&&verdict&&verdict.hard_forbid){
      items.push('引擎命中硬红线，模型输出仍须以引擎结论为准，不得据此放行。');
    }
    if(!items.length) return '';
    return '<div class="divergence-banner"><b>检测到可能需要复核的措辞</b>'+items.map(function(x){return '<div>'+esc(x)+'</div>';}).join('')+'</div>';
  }

  function adviceBody(adv,demo) {
    if(state.adviceLoading) return '<div class="empty-state">正在请求大模型建议…（最长 45 秒）</div>';
    if(state.adviceError) return '<div class="advice-error"><b>请求失败</b><p>'+esc(state.adviceError)+'</p><p class="mono">检查 backend/.env.deepseek 或 DEEPSEEK_API_KEY 是否配置，以及后端 8080 是否可访问。</p></div>';
    var shown=adv||(demo?DEMO_ADVICE:null);
    if(!shown) return '<div class="empty-state">输入问题后点右上角「请求 AI 建议」。</div>';
    var divergence=adviceDivergence(shown);
    var refusal=shown.refusal?'<div class="refusal-banner"><b>确定性拒绝（未调用大模型）</b><div>'+esc(shown.refusal.reason||'')+'</div></div>':'';
    var fallback=shown.fallback?'<div class="fallback-banner"><b>模型不可用，已回落引擎结论</b><div>'+esc(shown.fallback.message||'')+'</div></div>':'';
    var adviceText=shown.advice?('<div class="advice-text">'+esc(shown.advice)+'</div>'):'<div class="empty-state">无模型陈述，请以左侧引擎结论为准。</div>';
    return divergence+refusal+fallback+adviceText+
      '<div class="advice-meta">'+badge('模型 '+(shown.model||'—'),'purple')+badge(shown.validated?'已校验':'未校验',shown.validated?'success':'warning')+badge(shown.executed?'已执行':'未执行','warning')+badge(shown.requires_human_review?'需人工复核':'—','warning')+'</div>'+
      (demo?'<div class="form-note">当前为内置演示示例，不可用于运行。</div>':'');
  }

  function renderDecision() {
    var demo=state.dataMode!=='live', adv=state.advice;
    var verdict=state.verdict||(demo?DEMO_VERDICT:null);
    var ctx=adv&&adv.context?adv.context:null;
    if(!ctx&&verdict&&(safeArray(verdict.candidates).length||safeArray(verdict.limitations).length)){ctx={candidates:verdict.candidates,limitations:verdict.limitations};}
    var candidates=safeArray(ctx&&ctx.candidates).length?safeArray(ctx.candidates):(demo?DEMO_CANDIDATES:[]);
    var limitations=safeArray(ctx&&ctx.limitations).length?safeArray(ctx.limitations):(demo?safeArray(DEMO_ADVICE.context.limitations):[]);
    var modeBadge=state.adviceLoading?badge('请求中','warning'):(adv?badge(adv.model||'LLM','purple'):(demo?badge('演示数据','warning'):badge('待请求','info')));
    var verdictBadge=verdict?badge('确定性引擎','success'):badge('待加载','info');
    return '<div class="page">'+breadcrumb('AI 决策')+
      pageHead('ADVISORY · LLM ASSISTED DECISION','AI 轨迹决策','数据须经独立核验；<b>只读建议，不执行、不下发</b>&nbsp; '+badge('READ ONLY','warning'),button('请求 AI 建议','ask-ai','primary')+button('刷新上下文','refresh-decision','ghost'))+
      panel('决策问题','QUESTION · 上下文由后端组装后发送',badge(state.adviceType==='departure'?'离场':'进近','info'),
        '<textarea id="ai-question" class="ai-question" rows="3" placeholder="例如：当前电量 68%、风速 8 m/s，应选择哪条进近航道？需要哪些放行条件？">'+esc(state.adviceQuestion||'当前电量与气象条件下，应安排哪条进近航道？请说明理由与风险。')+'</textarea>'+
        '<div class="ai-question-row"><label>程序类型 <select id="ai-program-type"><option value="arrival"'+(state.adviceType!=='departure'?' selected':'')+'>进近 arrival</option><option value="departure"'+(state.adviceType==='departure'?' selected':'')+'>离场 departure</option></select></label>'+
        '<span class="mono ai-hint">POST /api/ai/advice · 超时 45s</span></div>','decision-question')+
      '<div class="decision-grid">'+
        panel('引擎结论（确定性）','ENGINE VERDICT · 结论码模型不可改写',verdictBadge,verdictPanel(verdict,demo),'verdict-panel')+
        panel('AI 建议（模型陈述）','ADVISORY',modeBadge,adviceBody(adv,demo),'advice-panel')+
      '</div>'+
      panel(verdict&&verdict.demo_only||demo?'候选航道（仅供演示，不可用于运行）':'候选航道（只读评估）','CANDIDATES · '+candidates.length,badge(verdict&&verdict.demo_only||demo?'演示':'后端计算','warning'),candidateTable(candidates))+
      (limitations.length?panel('数据与使用限制','LIMITATIONS',badge('必须人工复核','warning'),'<ul class="limitation-list">'+limitations.map(function(x){return '<li>'+esc(x)+'</li>';}).join('')+'</ul>'):'')+
      '</div>';
  }

  function deviceTable(list,demo) {
    if(!list.length) return '<div class="empty-state">暂无设备</div>';
    return '<div class="table-scroll"><table><thead><tr><th>名称</th><th>source_key</th><th>类型</th><th>σ</th><th>状态</th><th></th></tr></thead><tbody>'+
      list.map(function(d){return '<tr><td>'+esc(d.name||d.id)+'</td><td class="mono">'+esc(d.source_key)+'</td><td>'+esc(d.kind)+'</td>'+
        '<td class="mono">'+number(d.sigma_m,0)+' m</td><td>'+badge(d.status||'—',d.status==='online'?'success':'warning')+'</td>'+
        '<td>'+(demo?'<span class="mono">演示</span>':'<button class="text-button danger" data-action="device-del" data-id="'+esc(d.id)+'">删除</button>')+'</td></tr>';}).join('')+'</tbody></table></div>';
  }
  function deviceForm(demo) {
    if(demo) return '<div class="form-note">演示数据模式：切换到「实时数据」后可新增/删除；写操作需要 admin 角色（AUTH_ENABLED=1 时）。</div>';
    return '<div class="inline-form"><input id="dev-name" class="form-input" placeholder="名称"><input id="dev-key" class="form-input" placeholder="source_key">'+
      '<select id="dev-kind" class="form-input"><option value="rid">rid</option><option value="adsb">adsb</option><option value="radar">radar</option><option value="camera">camera</option></select>'+
      '<input id="dev-sigma" class="form-input" placeholder="σ 米" value="15"><button class="button ghost" data-action="device-add">新增设备</button></div>';
  }
  function routeTable(list,demo) {
    if(!list.length) return '<div class="empty-state">暂无路线</div>';
    return '<div class="table-scroll"><table><thead><tr><th>名称</th><th>类型</th><th>点数</th><th>高度范围</th><th></th></tr></thead><tbody>'+
      list.map(function(r){return '<tr><td>'+esc(r.name||r.id)+'</td><td>'+badge(esc(r.kind),r.kind==='no_fly'?'danger':r.kind==='corridor'?'info':'success')+'</td>'+
        '<td class="mono">'+safeArray(r.points).length+'</td><td class="mono">'+number(r.floor_agl,0)+'–'+number(r.ceiling_agl,0)+' m AGL</td>'+
        '<td>'+(demo?'<span class="mono">演示</span>':'<button class="text-button danger" data-action="route-del" data-id="'+esc(r.id)+'">删除</button>')+'</td></tr>';}).join('')+'</tbody></table></div>';
  }
  function routeForm(demo) {
    if(demo) return '<div class="form-note">演示数据模式：路线台账写入需要 admin 角色。</div>';
    return '<div class="inline-form"><input id="route-name" class="form-input" placeholder="名称">'+
      '<select id="route-kind" class="form-input"><option value="corridor">corridor</option><option value="no_fly">no_fly</option><option value="route">route</option></select>'+
      '<input id="route-points" class="form-input" placeholder="点 x,y;x,y" value="0,-300;900,-200;1500,0">'+
      '<input id="route-floor" class="form-input" placeholder="下限 AGL" value="30"><input id="route-ceil" class="form-input" placeholder="上限 AGL" value="120">'+
      '<button class="button ghost" data-action="route-add">新增路线</button></div>';
  }
  function policyBody(shadow,rl) {
    var on=shadow&&shadow.enabled;
    return '<div class="policy-grid">'+
      '<div class="policy-item"><small>RL 影子模式</small><b>'+badge(on?'开启':'关闭',on?'success':'warning')+'</b><p>'+esc((shadow&&shadow.reason)||(on?'策略与规则并行记录':'未开启'))+'</p>'+
        (state.dataMode==='live'?'<button class="button ghost" data-action="shadow-toggle" data-on="'+(on?'0':'1')+'">'+(on?'关闭影子':'开启影子')+'</button>':'<span class="mono">演示模式</span>')+'</div>'+
      '<div class="policy-item"><small>RL 模型</small><b>'+badge(rl&&Object.keys(rl).length?'已加载':'未知',rl&&Object.keys(rl).length?'success':'warning')+'</b><p class="mono">GET /api/rl/health</p></div>'+
      '<div class="policy-item"><small>鉴权</small><b>'+badge('AUTH_ENABLED=false','warning')+'</b><p>演示默认关闭；写操作按 admin / operator / viewer 校验（见 docs/ADMIN.md）。</p></div>'+
      '<div class="policy-item"><small>外部调用</small><b>'+badge('LLM 计费','purple')+'</b><p>AI 建议调用会产生外部 API 请求与费用。</p></div>'+
      '</div>';
  }

  function renderAdmin() {
    var demo=state.dataMode!=='live';
    var m=(state.metrics&&state.metrics.metrics)||DEMO_METRICS.metrics;
    var k=(state.metrics&&state.metrics.kalman)||DEMO_METRICS.kalman;
    var fm=m.frame_ms||{},cand=m.candidates||{},uniq=m.unique_tracks||{};
    var devices=state.devices||DEMO_DEVICES, routes=state.routes||DEMO_ROUTES;
    var shadow=state.shadow||{enabled:false,reason:'未开启'}, rl=state.rl||{};
    return '<div class="page">'+breadcrumb('系统管理')+
      pageHead('SYSTEM · RUNTIME & LEDGER','系统管理','运行指标、设备台账、路线管理与策略开关&nbsp; '+sourceTag(demo?'mock':'live'),button('刷新','refresh-admin','ghost'))+
      '<div class="kpi-grid">'+kpi('运行时长',number(Number(m.uptime_sec||0)/3600,1),' h','frames '+number(m.frames,0),'clock')+
        kpi('帧耗时 p99',number(fm.p99,2),' ms','p50 '+number(fm.p50,2)+' ms','chart','cyan')+
        kpi('候选边 p99',number(cand.p99,0),' 条','max '+number(cand.max,0),'link')+
        kpi('唯一航迹',number(uniq.now,0),' 条','σ 均值 '+number(k.sigma_mean,1)+' m','radar','cyan')+'</div>'+
      '<div class="admin-grid">'+panel('设备台账','DEVICES · source_key 唯一',badge(devices.length+' 台','info'),deviceTable(devices,demo)+deviceForm(demo))+
        panel('路线台账','ROUTES · corridor / no_fly / route',badge(routes.length+' 条','info'),routeTable(routes,demo)+routeForm(demo))+'</div>'+
      panel('策略与权限','POLICY & RBAC',badge('演示默认关闭鉴权','warning'),policyBody(shadow,rl))+
      '</div>';
  }

  function loadAdmin(force) {
    if(state.adminBusy) return;
    if(state.adminLoaded&&!force) return;
    if(state.dataMode!=='live'){state.adminLoaded=true;return;}
    state.adminBusy=true;
    Promise.all([Api.metrics(),Api.devices(),Api.routes(),Api.shadow(),Api.rlHealth()]).then(function(r){
      if(r[0]&&r[0].ok)state.metrics=r[0].data;
      if(r[1]&&r[1].ok)state.devices=safeArray(r[1].data&&r[1].data.devices);
      if(r[2]&&r[2].ok)state.routes=safeArray(r[2].data&&r[2].data.routes);
      if(r[3]&&r[3].ok)state.shadow=r[3].data;
      if(r[4]&&r[4].ok)state.rl=r[4].data;
      state.adminBusy=false;state.adminLoaded=true;
      if(state.route==='admin')render();
    }).catch(function(){state.adminBusy=false;state.adminLoaded=true;if(state.route==='admin')render();});
  }

  var decisionGeneration = 0;
  var verdictGeneration = 0;

  function resetDecision() {
    decisionGeneration++; verdictGeneration++;
    state.advice=null;state.adviceLoading=false;state.adviceError=null;
    state.verdict=null;state.verdictBusy=false;state.verdictLoaded=false;
  }

  function loadVerdict(force) {
    if(state.dataMode!=='live'||state.verdictBusy||(state.verdictLoaded&&!force)) return;
    state.verdictBusy=true;
    var generation=++verdictGeneration;
    Api.verdict(state.adviceType).then(function(r){
      if(generation!==verdictGeneration) return;
      state.verdictBusy=false;
      state.verdictLoaded=true;
      state.verdict=r.ok?Object.assign({},r.data.engine_verdict,r.data,{engine_verdict:undefined}):null;
      if(state.route==='decision')render();
    });
  }

  function askAdvice() {
    if(state.adviceLoading) return;
    var q=document.getElementById('ai-question'), t=document.getElementById('ai-program-type');
    var message=((q&&q.value)||'').trim();
    if(!message){toast('请先输入决策问题','warning');return;}
    state.adviceQuestion=message;state.adviceType=(t&&t.value)||'arrival';
    if(state.dataMode!=='live'){toast('当前展示内置示例，不调用模型','info');return;}
    var generation=++decisionGeneration;
    state.advice=null;state.adviceLoading=true;state.adviceError=null;render();
    Api.advice(message,state.adviceType).then(function(r){
      if(generation!==decisionGeneration) return;
      state.adviceLoading=false;
      if(r.ok){
        state.advice=r.data;
        var ctx=r.data.context;
        if(ctx&&ctx.engine_verdict){
          verdictGeneration++;state.verdictBusy=false;state.verdictLoaded=true;
          state.verdict=Object.assign({},ctx.engine_verdict,ctx,{engine_verdict:undefined});
        }
      }else{state.adviceError=r.error==='TIMEOUT'?'请求超时，请刷新上下文后重试。':'建议请求未完成，请检查后端或调整问题。';}
      if(state.route==='decision')render();
    });
  }

  function runtimePanel() {
    var m=(state.metrics&&state.metrics.metrics)||DEMO_METRICS.metrics;
    var k=(state.metrics&&state.metrics.kalman)||DEMO_METRICS.kalman;
    var fm=m.frame_ms||{},cand=m.candidates||{},uniq=m.unique_tracks||{},ct=m.counters||{};
    var cells=[['帧数',number(m.frames,0)],['平均帧耗时',number(m.avg_frame_ms,2)+' ms'],['p50 / p99',number(fm.p50,2)+' / '+number(fm.p99,2)+' ms'],
      ['候选边 p50 / p99',number(cand.p50,0)+' / '+number(cand.p99,0)],['唯一航迹',number(uniq.now,0)],['匹配 / 新建 / 重复',number(ct.matched,0)+' / '+number(ct.created,0)+' / '+number(ct.duplicate,0)],
      ['σ 均值 / 上限',number(k.sigma_mean,1)+' / '+number(k.sigma_max,1)+' m'],['σ 标定尺度',number(k.sigma_scale,2)]];
    return panel('后端运行指标','RUNTIME METRICS · 环形缓冲 600 帧',badge(state.dataMode==='live'?'LIVE':'DEMO',state.dataMode==='live'?'success':'warning'),
      '<div class="metrics-grid">'+cells.map(function(c){return '<div class="metrics-cell"><small>'+esc(c[0])+'</small><b class="mono">'+esc(c[1])+'</b></div>';}).join('')+'</div>','metrics-panel');
  }

  // ---- 局部 DOM 更新：数据刷新时只改变化的部分，不重建整页（避免闪烁）----
  function morphChildren(current, next) {
    var cur = Array.prototype.slice.call(current.childNodes);
    var nxt = Array.prototype.slice.call(next.childNodes);
    var common = Math.min(cur.length, nxt.length), i;
    for (i = 0; i < common; i++) { morphNode(cur[i], nxt[i]); }
    for (i = cur.length - 1; i >= nxt.length; i--) { current.removeChild(cur[i]); }
    for (i = common; i < nxt.length; i++) { current.appendChild(nxt[i].cloneNode(true)); }
  }

  function morphNode(current, next) {
    if (current.nodeType !== next.nodeType) { current.parentNode.replaceChild(next.cloneNode(true), current); return; }
    if (current.nodeType === 3 || current.nodeType === 8) { if (current.nodeValue !== next.nodeValue) { current.nodeValue = next.nodeValue; } return; }
    if (current.nodeType !== 1) { return; }
    if (current.tagName !== next.tagName) { current.parentNode.replaceChild(next.cloneNode(true), current); return; }
    if (current.tagName === 'CANVAS') { return; }   // 保留画布内容，随后由 mountPage 重绘
    var i, attr;
    for (i = current.attributes.length - 1; i >= 0; i--) {
      attr = current.attributes[i];
      if (!next.hasAttribute(attr.name)) { current.removeAttribute(attr.name); }
    }
    for (i = 0; i < next.attributes.length; i++) {
      attr = next.attributes[i];
      if (current.getAttribute(attr.name) !== attr.value) { current.setAttribute(attr.name, attr.value); }
    }
    morphChildren(current, next);
  }

  function render() {
    cleanup.forEach(function(fn){try{fn();}catch(_){}});cleanup=[];Visuals.disposeCharts();
    var nextRoute=parseRoute(), routeChanged=(nextRoute!==state.route);
    state.route=nextRoute;
    document.querySelectorAll('[data-nav]').forEach(function(node){node.classList.toggle('active',node.getAttribute('data-nav')===state.route);});
    document.body.classList.remove('nav-open');
    var views={home:renderHome,situation:renderSituation,program:renderProgram,decision:renderDecision,ground:renderGround,dashboard:renderDashboard,business:renderBusiness,admin:renderAdmin};
    var html=(views[state.route]||renderHome)();
    if(routeChanged||!app.firstChild){app.innerHTML=html;}
    else{var tpl=document.createElement('template');tpl.innerHTML=html;morphChildren(app,tpl.content);}
    mountPage();updateConnection();
  }

  // 周期性数据刷新入口：图表页/业务页数据是静态的，只更新连接状态，避免图表重建闪烁
  function refreshView() {
    if(state.route==='dashboard'||state.route==='business'){updateConnection();}
    else{render();}
  }

  function mountPage() {
    var riskGauge=document.querySelector('.risk-gauge');
    if(riskGauge)riskGauge.style.background='conic-gradient(var(--cyan) '+riskScore()+'%, rgba(114,146,181,.11) 0)';
    document.querySelectorAll('.sensor-ring').forEach(function(ring){var value=parseFloat(ring.style.getPropertyValue('--sensor'))||0;ring.style.background='conic-gradient(var(--cyan) '+value+'%, rgba(100,139,179,.12) 0)';});
    if(state.route==='situation'){var canvas=document.getElementById('situation-map');if(canvas)cleanup.push(Visuals.situation(canvas,effectiveSnapshot(),state.selectedTraffic,function(id){state.selectedTraffic=id;openDrawer('traffic',id);}));}
    if(state.route==='program'){
      var curProg=state.snapshot.program||{};
      if(curProg.direction&&!state.dirTouched){state.direction=curProg.direction;}
      if(state.dataMode==='live'&&!state.plansLoaded)loadPlans();
      var p=state.program.program||effectiveSnapshot().program||Mock.snapshot.program;Visuals.program(document.getElementById('program-map'),effectiveSnapshot(),p);Visuals.profile(document.getElementById('profile-map'),p);}
    if(state.route==='dashboard'){cleanup.push(Visuals.dashboard(Mock.analytics));Visuals.loadECharts(function(ok){if(ok&&state.route==='dashboard'){Visuals.disposeCharts();cleanup.push(Visuals.dashboard(Mock.analytics));}});}
    if(state.route==='admin'){loadAdmin(false);}
    if(state.route==='decision'){loadVerdict(false);}
  }

  function updateConnection() {
    var pill=document.getElementById('connection-pill');if(!pill)return;
    var mode=state.dataMode, live=(mode==='live'&&state.source.core==='live');
    pill.className='connection-pill '+(live?'is-live':'is-mock')+(state.syncing?' is-syncing':'');
    pill.title='点击切换数据源：演示数据 / 实时数据（对接 flycontrol + communication + groundstation）';
    pill.innerHTML='<i></i><span>'+(mode==='demo'?'演示数据':(state.syncing?'同步中':(live?'实时数据':'实时不可用')))+'</span>';
  }

  function field(label,value) { return '<div class="drawer-field"><small>'+esc(label)+'</small><b class="mono">'+esc(value)+'</b></div>'; }
  function drawerShell(title,subtitle,body) { overlayRoot.innerHTML='<div class="drawer-backdrop" data-action="close-drawer"><aside class="drawer" role="dialog" aria-modal="true" aria-label="'+esc(title)+'"><header class="drawer-head"><div><div class="eyebrow">DETAIL / INSPECT</div><h2>'+esc(title)+'</h2><p>'+esc(subtitle)+'</p></div><button class="drawer-close" data-action="close-drawer" aria-label="关闭">×</button></header>'+body+'</aside></div>'; }
  function openDrawer(type,id) {
    if(type==='traffic'){var t=effectiveSnapshot().traffic.find(function(x){return String(x.id)===String(id);});if(!t)return;var d=decisionFor(t);drawerShell(t.id,(t.model||'')+' · '+(t.reg_no||''),'<div class="drawer-section"><div class="drawer-decision '+d.tone+'"><small>门户演示决策</small><b>'+d.value+'</b><p>'+d.reason+'</p></div></div><div class="drawer-grid">'+field('RID / UA ID',t.ua_id)+field('实名登记号',t.reg_no)+field('飞行相位',phaseLabel(t.phase))+field('经纬度',number(t.lat,6)+', '+number(t.lon,6))+field('高度',number(t.alt_msl,1)+' m MSL')+field('速度',number(t.speed,1)+' m/s')+field('航向',number(t.heading,0)+'°')+field('垂直速度',number(t.vertical_speed,1)+' m/s')+field('电量',number(t.battery_pct,0)+'%')+field('链路质量',number(t.link_quality,0)+' / 5')+field('紧急状态',t.emergency?'是':'否')+field('RID 丢失',t.rid_lost?'是':'否')+'</div><div class="drawer-section"><h3>计划航迹</h3><div class="timeline">'+safeArray(t.route).map(function(p,i){return '<article><i></i><div><b class="mono">P'+String(i+1).padStart(2,'0')+'</b><p class="mono">'+number(p.lat,6)+', '+number(p.lon,6)+' · '+number(p.alt_msl,1)+'m MSL</p></div></article>';}).join('')+'</div></div>');return;}
    if(type==='stand'){var s=safeArray(state.ground.stands).find(function(x){return String(x.id)===String(id);});if(!s)return;drawerShell('机位 '+s.name,s.id+' · '+(s.type==='indoor'?'室内':'室外'),'<div class="drawer-grid">'+field('当前状态',{free:'空闲',reserved:'已预约',occupied:'占用'}[s.status]||s.status)+field('占用者',s.occupied_by||'无')+field('充电功率',number(s.charge_kw,0)+' kW')+field('最大尺寸',number(s.max_size_m,1)+' m')+field('调度优先级','P'+s.priority)+field('数据来源','groundstation mock')+'</div><div class="drawer-section"><h3>演示状态时间线</h3><div class="timeline"><article><i></i><div><b>状态同步</b><p>'+nowTime()+' · '+({free:'机位就绪',reserved:'等待进场',occupied:'正在保障'}[s.status]||s.status)+'</p></div></article><article><i></i><div><b>充电桩心跳</b><p>'+number(s.charge_kw,0)+' kW capability ready</p></div></article><article><i></i><div><b>调度服务上线</b><p>优先级 P'+s.priority+'</p></div></article></div></div>');return;}
    if(type==='rid'){var r=safeArray(state.ground.rid_targets).find(function(x){return String(x.id)===String(id);});if(!r)return;drawerShell(r.id,r.vendor+' · '+r.model,'<div class="drawer-grid">'+field('纬度',number(r.lat,6))+field('经度',number(r.lon,6))+field('高度',number(r.alt_msl,1)+' m MSL')+field('航向',number(r.heading,0)+'°')+field('速度',number(r.speed,1)+' m/s')+field('垂直速度',number(r.vertical_speed,1)+' m/s')+field('RSSI',number(r.rssi,0)+' dBm')+field('SNR',number(r.snr,0)+' dB')+field('飞手纬度',number(r.pilot_lat,6))+field('飞手经度',number(r.pilot_lon,6))+'</div>');return;}
    if(type==='program'){var p=state.program.program||Mock.snapshot.program;drawerShell(p.version,p.plan_id+' · '+p.type,'<div class="drawer-grid">'+field('程序类型',p.type)+field('来源',p.source)+field('计划 ID',p.plan_id)+field('风险评分',number(riskScore(),0)+'/100')+field('合规结果',compliancePassed()?'通过':'需复核')+field('仿真结果',simulationPassed()?'通过':'待确认')+'</div><div class="drawer-section"><h3>全部航路点</h3><div class="drawer-table"><table><thead><tr><th>#</th><th>坐标</th><th>MSL</th><th>速度</th></tr></thead><tbody>'+safeArray(p.waypoints).map(function(w,i){return '<tr><td>W'+(i+1)+'</td><td class="mono">'+number(w.lat,6)+', '+number(w.lon,6)+'</td><td>'+number(w.alt_msl,1)+'m</td><td>'+number(w.speed,1)+'m/s</td></tr>';}).join('')+safeArray(p.miss_approach).map(function(w,i){return '<tr><td>M'+(i+1)+'</td><td class="mono">'+number(w.lat,6)+', '+number(w.lon,6)+'</td><td>'+number(w.alt_msl,1)+'m</td><td>'+number(w.speed,1)+'m/s</td></tr>';}).join('')+'</tbody></table></div></div>');return;}
    if(type==='plan'){var plan=Mock.business.plans.find(function(x){return x.plan_id===id;});if(!plan)return;drawerShell(plan.plan_id,plan.applicant,'<div class="drawer-decision '+(plan.decision==='APPROVE'?'success':plan.decision==='HOLD'?'warning':'danger')+'"><small>许可决策</small><b>'+plan.decision+'</b><p>许可指令有效期：'+plan.valid_until+'</p></div><div class="drawer-grid">'+field('申请主体',plan.applicant)+field('运行类型',plan.operation)+field('有效期',plan.valid_until)+field('状态',plan.status)+'</div>');return;}
    if(type==='pilot'){var pilot=Mock.business.pilots.find(function(x){return x.id===id;});if(!pilot)return;drawerShell(pilot.name,pilot.id+' · '+pilot.organization,'<div class="drawer-grid">'+field('登记编号',pilot.id)+field('组织',pilot.organization)+field('实名登记',pilot.real_name_verified?'已核验':'待复核')+field('资质等级',pilot.qualification)+field('资质有效期',pilot.valid_until)+field('运行状态',pilot.status)+'</div>');}
  }

  function closeDrawer() { overlayRoot.innerHTML=''; }
  function toast(message,tone) { var node=document.createElement('div');node.className='toast '+(tone||'');node.innerHTML='<i></i><span>'+esc(message)+'</span>';toastRoot.appendChild(node);setTimeout(function(){node.classList.add('leave');setTimeout(function(){node.remove();},250);},2800); }

  // 演示数据模式：直接展示内置完整演示数据，不依赖任何后端
  function applyDemoData() {
    state.snapshot=clone(Mock.snapshot);
    state.program=clone(Mock.program_analysis);
    state.ground=clone(Mock.ground);
    state.source={core:'mock',program:'mock',ground:'mock'};
  }

  function toggleDataMode() {
    state.dataMode = state.dataMode==='live' ? 'demo' : 'live';
    resetDecision();
    state.metrics=null;state.devices=null;state.routes=null;state.shadow=null;state.rl=null;state.adminLoaded=false;
    if(state.dataMode==='demo'){
      applyDemoData();render();
      toast('已切换到演示数据（内置完整演示数据）','info');
    }else{
      toast('已切换到实时数据，正在接入三个子系统…','info');
      if(state.route==='decision')render();
      syncData(true);
    }
  }

  function syncData(showToast,background) {
    if(state.dataMode!=='live'){ if(showToast)toast('当前为演示数据模式，点击顶栏状态胶囊可切换到实时数据','info'); return; }
    if(state.syncing)return;state.syncing=true;
    if(!background)updateConnection();   // 后台轮询不闪「同步中」，避免状态胶囊每 5 秒跳动
    Promise.all([Api.snapshot(),Api.program(),Api.ground(),Api.trafficStats(),Api.pushStatus()]).then(function(results){
      var snap=results[0],program=results[1],ground=results[2],stats=results[3],pushRes=results[4],normalized=snap.ok?normalizeSnapshot(snap.data):null;
      if(stats&&stats.ok){state.dedup=stats.data;}
      if(pushRes&&pushRes.ok){state.push=pushRes.data;refreshPushPanel();}
      if(normalized){state.snapshot=normalized;state.source.core='live';}else{state.source.core='mock';}
      if(program.ok){state.program=normalizeProgram(program.data);state.source.program='live';}else if(state.source.program!=='live'){state.program=clone(Mock.program_analysis);state.source.program='mock';}
      if(ground.ok){state.ground=normalizeGround(ground.data);state.source.ground='live';}else if(state.source.ground!=='live'){state.ground=clone(Mock.ground);state.source.ground='mock';}
      state.syncing=false;state.lastSync=new Date();refreshView();
      if(showToast){var anyLive=!!normalized||state.source.program==='live'||state.source.ground==='live';toast(anyLive?'已同步实时数据（态势 / 程序 / 地面站）':'后端不可用，继续使用内置演示数据',anyLive?'success':'warning');}
    }).catch(function(){state.syncing=false;state.source.core='mock';render();if(showToast)toast('同步失败，页面已保持在演示模式','warning');});
  }

  function refreshProgram(successMessage) { return Promise.all([Api.program(),Api.snapshot()]).then(function(results){var result=results[0],snap=results[1];if(snap.ok){var n=normalizeSnapshot(snap.data);if(n){state.snapshot=n;state.source.core='live';}}if(result.ok){state.program=normalizeProgram(result.data);state.source.program='live';}render();toast(result.ok?successMessage:'操作完成，但当前程序读取失败',result.ok?'success':'warning');}); }
  function localReplan(type){var p=clone(state.program.program||Mock.snapshot.program);p.type=type;p.version=(type==='arrival'?'ARR':'DEP')+'-DEMO-'+new Date().toTimeString().slice(0,8).replace(/:/g,'');state.program=clone(Mock.program_analysis);state.program.program=p;state.source.program='mock';render();}
  function replan(type) { if(state.actionBusy)return;state.actionBusy=true;if(state.dataMode!=='live'){state.actionBusy=false;localReplan(type);toast('演示模式：已执行本地演示重规划','info');return;}toast('正在请求'+(type==='arrival'?'进近':'离场')+'重规划…','info');Api.replan(type).then(function(result){state.actionBusy=false;if(result.ok)return refreshProgram((type==='arrival'?'进近':'离场')+'程序已重规划');localReplan(type);toast('后端不可用，已执行本地演示重规划','warning');}); }
  function applyWeatherLocally(next){state.snapshot.meteo=Object.assign({},state.snapshot.meteo,{wind_speed:next.wind_speed,wind_dir:next.wind_dir,gust:next.gust,visibility:next.visibility,cloud_base_agl:next.cloud_base,turbulence:next.turbulence,wind_shear:next.wind_shear,temperature:next.temperature,pressure:next.pressure});render();}
  function weatherScenario() { state.adverseWeather=!state.adverseWeather;var current=effectiveSnapshot().meteo;var next=state.adverseWeather?{wind_speed:11.8,wind_dir:112,gust:16.2,visibility:1800,cloud_base:140,turbulence:3,wind_shear:3,temperature:Number(current.temperature||27),pressure:Number(current.pressure||1008)}:{wind_speed:5.8,wind_dir:68,gust:8.2,visibility:9600,cloud_base:680,turbulence:2,wind_shear:1,temperature:27.4,pressure:1008.6};if(state.dataMode!=='live'){applyWeatherLocally(next);toast(state.adverseWeather?'已注入恶劣气象（演示）':'已恢复标准气象（演示）','info');return;}Api.setMeteo(next).then(function(result){if(result.ok){syncData(false);toast(state.adverseWeather?'恶劣气象已写入 flycontrol':'标准气象已恢复','success');}else{applyWeatherLocally(next);toast('后端不可用，气象场景仅在本页演示','warning');}}); }
  function toggleObstacle() { var list=safeArray(state.snapshot.obstacles),target=list.find(function(x){return x.type==='dynamic';})||list[0];if(!target){toast('当前没有可切换障碍物','warning');return;}var active=target.active===false;if(state.source.core!=='live'){target.active=active;render();toast(target.name+' 已切换为'+(active?'活动':'停用')+'（演示）','info');return;}Api.toggleObstacle(target.id,active).then(function(result){if(result.ok){syncData(false);toast(target.name+' 状态已更新','success');}else toast('障碍物切换失败：接口未接受该 ID','warning');}); }

  function handleAction(action,element,clickEvent) {
    if(action==='close-drawer'){if(element.classList.contains('drawer-backdrop')&&clickEvent.target!==element)return;closeDrawer();return;}
    if(action==='sync'){syncData(true);return;}
    if(action==='toggle-mode'){toggleDataMode();return;}
    if(action==='go-situation'){location.hash='#/situation';return;}
    if(action==='map-fullscreen'){var panel=document.querySelector('.map-panel');if(panel&&panel.requestFullscreen)panel.requestFullscreen().catch(function(){});return;}
    if(action==='push-flush'){Api.pushFlush().then(function(r){if(r.ok){state.push=r.data.status||state.push;syncData(false);toast('已推送 '+(r.data.sent||0)+' 条','success');}else toast('推送失败','warning');});return;}
    if(action==='dir'){state.dirTouched=true;state.direction=element.getAttribute('data-dir');render();return;}
    if(action==='gen-plan'){generateProgram(element.getAttribute('data-type'),element.getAttribute('data-dir'));return;}
    if(action==='replan-arrival'){replan('arrival');return;}
    if(action==='replan-departure'){replan('departure');return;}
    if(action==='toggle-obstacle'){toggleObstacle();return;}
    if(action==='weather-scenario'){weatherScenario();return;}
    if(action==='refresh-ground'){syncData(true);return;}
    if(action==='ask-ai'){askAdvice();return;}
    if(action==='refresh-decision'){resetDecision();render();return;}
    if(action==='refresh-admin'){loadAdmin(true);return;}
    if(action==='shadow-toggle'){var on=element.getAttribute('data-on')==='1';Api.setShadow(on).then(function(r){if(r.ok){toast('影子模式已'+(on?'开启':'关闭'),'success');loadAdmin(true);}else toast('切换失败：影子模式未加载','warning');});return;}
    if(action==='device-del'){var did=element.getAttribute('data-id');Api.deleteDevice(did).then(function(r){if(r.ok){toast('设备已删除','success');loadAdmin(true);}else toast('删除失败（需 admin 角色）','warning');});return;}
    if(action==='device-add'){var dn=document.getElementById('dev-name'),dk=document.getElementById('dev-key'),dkind=document.getElementById('dev-kind'),ds=document.getElementById('dev-sigma');
      var device={name:(dn&&dn.value)||'',source_key:(dk&&dk.value)||'',kind:(dkind&&dkind.value)||'rid',sigma_m:Number(ds&&ds.value)||15};
      if(!device.name||!device.source_key){toast('名称与 source_key 不能为空','warning');return;}
      Api.createDevice(device).then(function(r){if(r.ok){toast('设备已新增','success');loadAdmin(true);}else toast('新增失败：source_key 可能重复','warning');});return;}
    if(action==='route-del'){var rid=element.getAttribute('data-id');Api.deleteRoute(rid).then(function(r){if(r.ok){toast('路线已删除','success');loadAdmin(true);}else toast('删除失败（需 admin 角色）','warning');});return;}
    if(action==='route-add'){var rn=document.getElementById('route-name'),rk=document.getElementById('route-kind'),rp=document.getElementById('route-points'),rf=document.getElementById('route-floor'),rc=document.getElementById('route-ceil');
      var points=((rp&&rp.value)||'').split(';').map(function(pair){var xy=pair.split(',');var x=Number(xy[0]),y=Number(xy[1]);if(!isFinite(x)||!isFinite(y))return null;return {x:x,y:y};}).filter(function(p){return !!p;});
      var route={name:(rn&&rn.value)||'',kind:(rk&&rk.value)||'corridor',points:points,floor_agl:Number(rf&&rf.value)||0,ceiling_agl:Number(rc&&rc.value)||120};
      if(!route.name){toast('路线名称不能为空','warning');return;}
      Api.createRoute(route).then(function(r){if(r.ok){toast('路线已新增','success');loadAdmin(true);}else toast('新增失败（需 admin 角色）','warning');});return;}
    if(action==='new-registration'){toast('当前为业务演示数据，登记写入接口尚未提供','warning');}
  }

  document.addEventListener('click',function(event){var nav=event.target.closest('[data-nav]');if(nav){document.body.classList.remove('nav-open');return;}var tab=event.target.closest('[data-tab]');if(tab){state.businessTab=tab.getAttribute('data-tab');render();return;}var entity=event.target.closest('[data-entity]');if(entity){openDrawer(entity.getAttribute('data-entity'),entity.getAttribute('data-id'));return;}var action=event.target.closest('[data-action]');if(action){handleAction(action.getAttribute('data-action'),action,event);}});
  document.addEventListener('change',function(event){
    if(event.target.id!=='ai-program-type')return;
    var question=document.getElementById('ai-question');
    if(question)state.adviceQuestion=question.value;
    state.adviceType=event.target.value;
    resetDecision();render();
  });
  document.getElementById('nav-toggle').addEventListener('click',function(){document.body.classList.toggle('nav-open');});
  window.addEventListener('hashchange',render);
  window.addEventListener('resize',function(){clearTimeout(resizeTimer);resizeTimer=setTimeout(function(){if(state.route==='program'||state.route==='dashboard')render();},160);});
  document.addEventListener('keydown',function(event){if(event.key==='Escape')closeDrawer();});
  setInterval(function(){var clock=document.getElementById('system-clock');if(clock)clock.textContent=nowTime();},1000);

  render();
  if(state.dataMode==='live'){setTimeout(function(){syncData(false);},80);}
  setInterval(function(){if(state.dataMode==='live'&&!state.syncing)syncData(false,true);},5000);
}());
