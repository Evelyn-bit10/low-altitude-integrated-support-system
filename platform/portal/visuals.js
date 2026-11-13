(function () {
  'use strict';

  var chartInstances = [];
  var echartsLoading = false;
  var echartsCallbacks = [];

  function fit(canvas) {
    if (!canvas) return null;
    var rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    var ratio = Math.min(window.devicePixelRatio || 1, 2);
    var width = Math.round(rect.width * ratio);
    var height = Math.round(rect.height * ratio);
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width; canvas.height = height;
    }
    var ctx = canvas.getContext('2d');
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    return { ctx:ctx, width:rect.width, height:rect.height, ratio:ratio };
  }

  function safeArray(value) { return Array.isArray(value) ? value : []; }
  function colorAlpha(hex, alpha) {
    var clean = String(hex).replace('#', '');
    var value = parseInt(clean, 16);
    return 'rgba(' + ((value >> 16) & 255) + ',' + ((value >> 8) & 255) + ',' + (value & 255) + ',' + alpha + ')';
  }

  function bounds(snapshot) {
    var airport = snapshot.airport || { lat:0, lon:0 };
    var points = [[airport.lat, airport.lon]];
    safeArray(snapshot.airspaces).forEach(function (a) { safeArray(a.polygon).forEach(function (p) { if (p && p.length >= 2) points.push([Number(p[0]), Number(p[1])]); }); });
    safeArray(snapshot.obstacles).forEach(function (o) { points.push([Number(o.lat), Number(o.lon)]); });
    safeArray(snapshot.traffic).forEach(function (t) { points.push([Number(t.lat), Number(t.lon)]); safeArray(t.route).forEach(function (p) { points.push([Number(p.lat), Number(p.lon)]); }); });
    points = points.filter(function (p) { return isFinite(p[0]) && isFinite(p[1]); });
    var lats = points.map(function (p) { return p[0]; });
    var lons = points.map(function (p) { return p[1]; });
    var minLat = Math.min.apply(null, lats), maxLat = Math.max.apply(null, lats);
    var minLon = Math.min.apply(null, lons), maxLon = Math.max.apply(null, lons);
    var latPad = Math.max((maxLat - minLat) * .16, .005);
    var lonPad = Math.max((maxLon - minLon) * .16, .006);
    return { minLat:minLat-latPad, maxLat:maxLat+latPad, minLon:minLon-lonPad, maxLon:maxLon+lonPad };
  }

  function projector(box, width, height, pad) {
    pad = pad || 26;
    return function (lat, lon) {
      var x = pad + ((Number(lon) - box.minLon) / Math.max(.000001, box.maxLon - box.minLon)) * (width - pad * 2);
      var y = height - pad - ((Number(lat) - box.minLat) / Math.max(.000001, box.maxLat - box.minLat)) * (height - pad * 2);
      return { x:x, y:y };
    };
  }

  function drawGrid(ctx, width, height) {
    var gradient = ctx.createRadialGradient(width * .52, height * .48, 0, width * .52, height * .48, Math.max(width, height) * .65);
    gradient.addColorStop(0, '#102940'); gradient.addColorStop(.48, '#091b2d'); gradient.addColorStop(1, '#06111f');
    ctx.fillStyle = gradient; ctx.fillRect(0, 0, width, height);
    ctx.lineWidth = 1; ctx.strokeStyle = 'rgba(89,160,219,.09)';
    for (var x = 0; x <= width; x += 40) { ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,height); ctx.stroke(); }
    for (var y = 0; y <= height; y += 40) { ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(width,y); ctx.stroke(); }
    ctx.strokeStyle = 'rgba(72,139,197,.08)';
    for (var d = -height; d < width; d += 100) { ctx.beginPath(); ctx.moveTo(d,0); ctx.lineTo(d+height,height); ctx.stroke(); }
  }

  function mountSituation(canvas, snapshot, selectedId, onPick) {
    var stopped = false, frame = 0, hits = [];
    var colors = { APPROACH:'#ffb35c', DEPARTURE:'#27e0d8', HOVER:'#ff647b', CRUISE:'#7c5cff', STANDBY:'#49e3ae', LANDED:'#8798b2' };

    function draw(timestamp) {
      if (stopped || !document.body.contains(canvas)) return;
      var size = fit(canvas);
      if (!size) { frame = requestAnimationFrame(draw); return; }
      var ctx = size.ctx, width = size.width, height = size.height;
      var box = bounds(snapshot), project = projector(box, width, height, 30);
      hits = [];
      ctx.clearRect(0, 0, width, height); drawGrid(ctx, width, height);

      safeArray(snapshot.airspaces).forEach(function (airspace) {
        var polygon = safeArray(airspace.polygon); if (polygon.length < 3) return;
        ctx.beginPath(); polygon.forEach(function (p, index) { var q = project(p[0],p[1]); index ? ctx.lineTo(q.x,q.y) : ctx.moveTo(q.x,q.y); }); ctx.closePath();
        ctx.fillStyle = 'rgba(124,92,255,.11)'; ctx.fill();
        ctx.strokeStyle = 'rgba(151,127,255,.64)'; ctx.lineWidth = 1; ctx.setLineDash([7,6]); ctx.stroke(); ctx.setLineDash([]);
        var label = project(polygon[0][0], polygon[0][1]); ctx.fillStyle = '#a998ff'; ctx.font = '10px Consolas, monospace'; ctx.fillText(airspace.id || 'AIRSPACE', label.x + 5, label.y - 6);
      });

      var airport = snapshot.airport || {};
      var center = project(airport.lat, airport.lon);
      [58,116,174,232].forEach(function (radius, index) { ctx.beginPath(); ctx.arc(center.x,center.y,radius,0,Math.PI*2); ctx.strokeStyle = index === 3 ? 'rgba(39,224,216,.28)' : 'rgba(64,154,225,.18)'; ctx.setLineDash(index === 3 ? [8,7] : []); ctx.stroke(); }); ctx.setLineDash([]);
      var sweepAngle = ((timestamp || 0) / 3600) % (Math.PI * 2);
      var sweep = ctx.createLinearGradient(center.x,center.y,center.x+Math.cos(sweepAngle)*220,center.y+Math.sin(sweepAngle)*220);
      sweep.addColorStop(0,'rgba(39,224,216,.65)'); sweep.addColorStop(1,'rgba(39,224,216,0)');
      ctx.beginPath(); ctx.moveTo(center.x,center.y); ctx.lineTo(center.x+Math.cos(sweepAngle)*230,center.y+Math.sin(sweepAngle)*230); ctx.strokeStyle=sweep; ctx.lineWidth=2; ctx.stroke();

      safeArray(snapshot.obstacles).forEach(function (obstacle) {
        var q = project(obstacle.lat, obstacle.lon); var active = obstacle.active !== false;
        ctx.beginPath(); ctx.arc(q.x,q.y,Math.max(7,Number(obstacle.radius || 30)/12),0,Math.PI*2); ctx.fillStyle = active ? 'rgba(255,179,92,.12)' : 'rgba(131,151,181,.07)'; ctx.fill();
        ctx.strokeStyle = active ? 'rgba(255,179,92,.72)' : 'rgba(131,151,181,.32)'; ctx.stroke();
        ctx.fillStyle = active ? '#ffb35c' : '#617792'; ctx.fillRect(q.x-3,q.y-3,6,6);
      });

      safeArray(snapshot.traffic).forEach(function (traffic) {
        var route = safeArray(traffic.route); if (route.length < 2) return;
        ctx.beginPath(); route.forEach(function (p,index) { var q=project(p.lat,p.lon); index?ctx.lineTo(q.x,q.y):ctx.moveTo(q.x,q.y); });
        ctx.strokeStyle = traffic.id === selectedId ? 'rgba(39,224,216,.82)' : 'rgba(47,155,255,.28)'; ctx.lineWidth = traffic.id === selectedId ? 2 : 1; ctx.setLineDash([6,5]); ctx.stroke(); ctx.setLineDash([]);
      });

      safeArray(snapshot.traffic).forEach(function (traffic) {
        var q = project(traffic.lat,traffic.lon); var color = colors[traffic.phase] || '#2f9bff'; var selected = traffic.id === selectedId;
        if (selected) { ctx.beginPath(); ctx.arc(q.x,q.y,18 + Math.sin((timestamp||0)/220)*2,0,Math.PI*2); ctx.strokeStyle=colorAlpha(color,.32); ctx.lineWidth=5; ctx.stroke(); }
        ctx.beginPath(); ctx.arc(q.x,q.y,selected?11:9,0,Math.PI*2); ctx.fillStyle=colorAlpha(color,.18); ctx.fill(); ctx.strokeStyle=color; ctx.lineWidth=selected?2:1; ctx.stroke();
        ctx.save(); ctx.translate(q.x,q.y); ctx.rotate((Number(traffic.heading||0)-90)*Math.PI/180); ctx.beginPath(); ctx.moveTo(11,0);ctx.lineTo(-7,5);ctx.lineTo(-3,0);ctx.lineTo(-7,-5);ctx.closePath();ctx.fillStyle=color;ctx.fill();ctx.restore();
        ctx.font='10px Consolas, monospace';ctx.fillStyle='#d7ebff';ctx.fillText(String(traffic.id||'').replace('UAV-',''),q.x+14,q.y+4);
        hits.push({ id:traffic.id, x:q.x, y:q.y });
      });

      var heading = (Number(airport.runway_heading || 0)-90)*Math.PI/180;
      ctx.save();ctx.translate(center.x,center.y);ctx.rotate(heading);ctx.strokeStyle='#dffeff';ctx.lineWidth=5;ctx.beginPath();ctx.moveTo(-20,0);ctx.lineTo(20,0);ctx.stroke();ctx.strokeStyle='#27e0d8';ctx.lineWidth=1;ctx.strokeRect(-25,-7,50,14);ctx.restore();
      ctx.fillStyle='#bfe8ff';ctx.font='11px system-ui';ctx.fillText(airport.code || 'SKYPORT',center.x+15,center.y-13);
      frame = requestAnimationFrame(draw);
    }

    canvas.onclick = function (event) {
      var rect=canvas.getBoundingClientRect(),x=event.clientX-rect.left,y=event.clientY-rect.top,best=null,distance=Infinity;
      hits.forEach(function (hit) { var d=Math.hypot(hit.x-x,hit.y-y);if(d<distance){distance=d;best=hit;} });
      if (best && distance < 30 && typeof onPick === 'function') onPick(best.id);
    };
    frame = requestAnimationFrame(draw);
    return function () { stopped=true; cancelAnimationFrame(frame); canvas.onclick=null; };
  }

  function drawProgram(canvas, snapshot, program) {
    var size=fit(canvas);if(!size)return;var ctx=size.ctx,width=size.width,height=size.height;ctx.clearRect(0,0,width,height);drawGrid(ctx,width,height);
    var local={airport:snapshot.airport,airspaces:snapshot.airspaces,obstacles:snapshot.obstacles,traffic:[],program:program};
    var points=safeArray(program.waypoints).concat(safeArray(program.miss_approach));
    local.traffic=[{lat:snapshot.airport.lat,lon:snapshot.airport.lon,route:points}];
    var box=bounds(local),project=projector(box,width,height,38);
    safeArray(snapshot.airspaces).forEach(function(a){var polygon=safeArray(a.polygon);if(polygon.length<3)return;ctx.beginPath();polygon.forEach(function(p,i){var q=project(p[0],p[1]);i?ctx.lineTo(q.x,q.y):ctx.moveTo(q.x,q.y);});ctx.closePath();ctx.fillStyle='rgba(124,92,255,.08)';ctx.fill();ctx.strokeStyle='rgba(124,92,255,.38)';ctx.setLineDash([5,5]);ctx.stroke();ctx.setLineDash([]);});
    function route(list,color,dash,prefix){list=safeArray(list);if(!list.length)return;ctx.beginPath();list.forEach(function(p,i){var q=project(p.lat,p.lon);i?ctx.lineTo(q.x,q.y):ctx.moveTo(q.x,q.y);});ctx.strokeStyle=color;ctx.lineWidth=2;ctx.setLineDash(dash||[]);ctx.stroke();ctx.setLineDash([]);list.forEach(function(p,i){var q=project(p.lat,p.lon);ctx.beginPath();ctx.arc(q.x,q.y,5,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();ctx.fillStyle='#cfe8fa';ctx.font='10px Consolas';ctx.fillText(prefix+String(i+1).padStart(2,'0'),q.x+9,q.y-7);});}
    route(program.waypoints,'#27e0d8',[],'W');route(program.miss_approach,'#ffb35c',[7,5],'M');
  }

  function drawProfile(canvas, program) {
    var size=fit(canvas);if(!size)return;var ctx=size.ctx,width=size.width,height=size.height,points=safeArray(program.waypoints);ctx.clearRect(0,0,width,height);ctx.fillStyle='#071322';ctx.fillRect(0,0,width,height);if(!points.length)return;
    var values=points.map(function(p){return Number(p.alt_msl)||0;}),max=Math.max.apply(null,values.concat([1])),min=Math.min.apply(null,values.concat([0]));var range=Math.max(1,max-min);var pad={l:48,r:22,t:22,b:31};
    ctx.font='10px Consolas';ctx.strokeStyle='rgba(92,154,208,.13)';ctx.fillStyle='#6684a6';for(var i=0;i<4;i++){var value=min+range*i/3,y=height-pad.b-(value-min)/range*(height-pad.t-pad.b);ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(width-pad.r,y);ctx.stroke();ctx.fillText(Math.round(value)+'m',8,y+3);}
    var plotted=points.map(function(p,i){return{x:pad.l+i*(width-pad.l-pad.r)/Math.max(1,points.length-1),y:height-pad.b-(Number(p.alt_msl)-min)/range*(height-pad.t-pad.b)};});
    var gradient=ctx.createLinearGradient(0,pad.t,0,height-pad.b);gradient.addColorStop(0,'rgba(39,224,216,.28)');gradient.addColorStop(1,'rgba(39,224,216,.02)');ctx.beginPath();plotted.forEach(function(p,i){i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y);});ctx.lineTo(plotted[plotted.length-1].x,height-pad.b);ctx.lineTo(plotted[0].x,height-pad.b);ctx.closePath();ctx.fillStyle=gradient;ctx.fill();
    ctx.beginPath();plotted.forEach(function(p,i){i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y);});ctx.strokeStyle='#27e0d8';ctx.lineWidth=2;ctx.stroke();plotted.forEach(function(p,i){ctx.beginPath();ctx.arc(p.x,p.y,4,0,Math.PI*2);ctx.fillStyle='#e5ffff';ctx.fill();ctx.fillStyle='#7699bb';ctx.fillText('W'+(i+1),p.x-7,height-10);});
  }

  function lineFallback(canvas, series, labels) {
    var size=fit(canvas);if(!size)return;var ctx=size.ctx,w=size.width,h=size.height,p={l:38,r:18,t:20,b:30};ctx.clearRect(0,0,w,h);ctx.fillStyle='#091523';ctx.fillRect(0,0,w,h);
    var all=[];series.forEach(function(s){all=all.concat(s.data);});var max=Math.max.apply(null,all.concat([1])),min=Math.min.apply(null,all.concat([0])),range=Math.max(1,max-min);ctx.strokeStyle='rgba(100,158,211,.12)';for(var g=0;g<5;g++){var y=p.t+g*(h-p.t-p.b)/4;ctx.beginPath();ctx.moveTo(p.l,y);ctx.lineTo(w-p.r,y);ctx.stroke();}
    series.forEach(function(s){ctx.beginPath();s.data.forEach(function(v,i){var x=p.l+i*(w-p.l-p.r)/Math.max(1,s.data.length-1),y=h-p.b-(v-min)/range*(h-p.t-p.b);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.strokeStyle=s.color;ctx.lineWidth=2;ctx.stroke();});
    ctx.font='10px Consolas';ctx.fillStyle='#637f9f';labels.forEach(function(label,i){if(i%Math.max(1,Math.ceil(labels.length/6))!==0&&i!==labels.length-1)return;var x=p.l+i*(w-p.l-p.r)/Math.max(1,labels.length-1);ctx.fillText(label,x-6,h-10);});
  }

  function donutFallback(canvas, values, colors) {
    var size=fit(canvas);if(!size)return;var ctx=size.ctx,w=size.width,h=size.height,total=values.reduce(function(a,b){return a+b;},0)||1,cx=w/2,cy=h/2,r=Math.min(w,h)*.31,start=-Math.PI/2;ctx.clearRect(0,0,w,h);values.forEach(function(v,i){var end=start+v/total*Math.PI*2;ctx.beginPath();ctx.arc(cx,cy,r,start,end);ctx.strokeStyle=colors[i];ctx.lineWidth=17;ctx.stroke();start=end;});ctx.textAlign='center';ctx.fillStyle='#e9f7ff';ctx.font='600 22px Consolas';ctx.fillText(total,cx,cy+2);ctx.fillStyle='#7791af';ctx.font='11px system-ui';ctx.fillText('告警总数',cx,cy+21);ctx.textAlign='left';
  }

  function disposeCharts() { chartInstances.forEach(function(instance){try{instance.dispose();}catch(_){}});chartInstances=[]; }

  function mountDashboard(analytics) {
    disposeCharts();
    var traffic=document.querySelector('#traffic-chart canvas'),weather=document.querySelector('#weather-chart canvas'),alarm=document.querySelector('#alarm-chart canvas');
    if (!window.echarts) {
      lineFallback(traffic,[{data:analytics.online,color:'#27e0d8'},{data:analytics.departures,color:'#7c5cff'}],analytics.hours);
      lineFallback(weather,[{data:analytics.wind,color:'#2f9bff'},{data:analytics.temperature,color:'#ffb35c'}],['08','09','10','11','12','13','14','15']);
      donutFallback(alarm,analytics.alarm_values,['#27e0d8','#2f9bff','#7c5cff','#ffb35c']);
      return disposeCharts;
    }
    [['traffic-chart',{labels:analytics.hours,series:[{name:'在线架次',data:analytics.online,color:'#27e0d8'},{name:'离场',data:analytics.departures,color:'#7c5cff'}]}],['weather-chart',{labels:['08','09','10','11','12','13','14','15'],series:[{name:'风速',data:analytics.wind,color:'#2f9bff'},{name:'温度',data:analytics.temperature,color:'#ffb35c'}]}]].forEach(function(item){var el=document.getElementById(item[0]);el.innerHTML='';var chart=window.echarts.init(el);var cfg=item[1];chart.setOption({animationDuration:500,grid:{left:42,right:18,top:34,bottom:28},tooltip:{trigger:'axis',backgroundColor:'#0b1728',borderColor:'#29496c',textStyle:{color:'#dceeff'}},legend:{top:0,right:0,textStyle:{color:'#7991ad',fontSize:10}},xAxis:{type:'category',data:cfg.labels,boundaryGap:false,axisLine:{lineStyle:{color:'#263b57'}},axisLabel:{color:'#6e87a5',fontSize:10}},yAxis:{type:'value',axisLine:{show:false},axisLabel:{color:'#6e87a5',fontSize:10},splitLine:{lineStyle:{color:'rgba(100,158,211,.1)'}}},series:cfg.series.map(function(s){return{name:s.name,type:'line',data:s.data,smooth:true,showSymbol:false,lineStyle:{color:s.color,width:2},areaStyle:{color:colorAlpha(s.color,.07)}};})});chartInstances.push(chart);});
    var alarmEl=document.getElementById('alarm-chart');alarmEl.innerHTML='';var donut=window.echarts.init(alarmEl);donut.setOption({tooltip:{trigger:'item'},series:[{type:'pie',radius:['58%','78%'],center:['50%','50%'],label:{show:false},data:analytics.alarm_values.map(function(v,i){return{name:analytics.alarm_labels[i],value:v,itemStyle:{color:['#27e0d8','#2f9bff','#7c5cff','#ffb35c'][i]}};})}],graphic:[{type:'text',left:'center',top:'42%',style:{text:String(analytics.alarm_values.reduce(function(a,b){return a+b;},0)),fill:'#e9f7ff',font:'600 22px Consolas'}},{type:'text',left:'center',top:'56%',style:{text:'告警总数',fill:'#7791af',font:'11px system-ui'}}]});chartInstances.push(donut);
    return disposeCharts;
  }

  function loadECharts(callback) {
    if (window.echarts) { callback(true); return; }
    echartsCallbacks.push(callback); if (echartsLoading) return; echartsLoading=true;
    var script=document.createElement('script');script.async=true;script.src='https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js';
    var done=false;function finish(ok){if(done)return;done=true;echartsLoading=false;var callbacks=echartsCallbacks.splice(0);callbacks.forEach(function(cb){try{cb(ok);}catch(_){}});}
    script.onload=function(){finish(!!window.echarts);};script.onerror=function(){finish(false);};document.head.appendChild(script);setTimeout(function(){finish(!!window.echarts);},3500);
  }

  window.LAVVisuals = {
    situation: mountSituation,
    program: drawProgram,
    profile: drawProfile,
    dashboard: mountDashboard,
    loadECharts: loadECharts,
    disposeCharts: disposeCharts
  };
}());
