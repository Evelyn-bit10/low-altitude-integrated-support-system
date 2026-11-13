/* 临时自测：用最小 DOM 桩在 Node 里真跑一遍 App，验证渲染与核心逻辑。跑完即删。 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const DIR = __dirname;

/* ---------------- 最小 DOM 桩 ---------------- */
const registry = {};
function makeEl(tag) {
  const el = {
    tagName: String(tag || 'div').toUpperCase(),
    _html: '', _text: '',
    style: {}, dataset: {}, attrs: {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    children: [], parentNode: null, nextElementSibling: null, firstChild: null, childNodes: [],
    addEventListener() {}, removeEventListener() {},
    appendChild(c) { this.children.push(c); return c; },
    removeChild() {}, remove() {}, prepend() {},
    querySelector() { return null; }, querySelectorAll() { return []; },
    getBoundingClientRect() { return { width: 360, height: 288, left: 0, top: 0, right: 360, bottom: 288 }; },
    getContext() { return ctxStub; },
    setAttribute(k, v) { this.attrs[k] = v; },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    closest() { return null; }, focus() {}, click() {}, setPointerCapture() {}
  };
  Object.defineProperty(el, 'innerHTML', { get() { return this._html; }, set(v) { this._html = String(v); } });
  Object.defineProperty(el, 'textContent', { get() { return this._text; }, set(v) { this._text = String(v); } });
  return el;
}
const ctxStub = new Proxy({}, {
  get(t, k) {
    if (k === 'canvas') { return { width: 360, height: 288 }; }
    if (k in t) { return t[k]; }
    return function () { return ctxStub; };
  },
  set(t, k, v) { t[k] = v; return true; }
});

const documentStub = {
  readyState: 'complete',
  body: makeEl('body'),
  documentElement: makeEl('html'),
  createElement: (t) => makeEl(t),
  getElementById(id) { if (!registry[id]) { registry[id] = makeEl('div'); } return registry[id]; },
  querySelector(sel) {
    if (sel && sel[0] === '#') { const id = sel.slice(1); if (!registry[id]) { registry[id] = makeEl('div'); } return registry[id]; }
    return null;
  },
  querySelectorAll() { return []; },
  addEventListener() {}, removeEventListener() {}
};

/* ---------------- 上下文 ---------------- */
const ctx = {};
ctx.window = ctx; ctx.self = ctx;
ctx.document = documentStub;
ctx.location = { hash: '#/home', search: '', protocol: 'http:', hostname: '127.0.0.1', origin: 'http://127.0.0.1:5502', href: 'http://127.0.0.1:5502/index.html' };
ctx.navigator = { userAgent: 'node-selftest' };
ctx.localStorage = { getItem() { return null; }, setItem() {}, removeItem() {} };
ctx.fetch = function () { return Promise.reject(new Error('offline')); };
ctx.setTimeout = setTimeout; ctx.clearTimeout = clearTimeout;
ctx.setInterval = setInterval; ctx.clearInterval = clearInterval;
ctx.requestAnimationFrame = function () { return 1; };
ctx.cancelAnimationFrame = function () {};
ctx.console = console;
ctx.URLSearchParams = URLSearchParams;
ctx.AbortController = AbortController;
ctx.addEventListener = function () {};
ctx.removeEventListener = function () {};
ctx.dispatchEvent = function () {};
ctx.devicePixelRatio = 2;
ctx.innerWidth = 375;
ctx.innerHeight = 812;
ctx.getComputedStyle = function () { return { getPropertyValue() { return ''; } }; };
ctx.matchMedia = function () { return { matches: false, addListener() {}, removeListener() {} }; };
vm.createContext(ctx);

/* ---------------- 断言 ---------------- */
let failed = 0;
function check(name, cond, extra) {
  if (!cond) { failed++; }
  console.log((cond ? '  PASS  ' : '  FAIL  ') + name + (extra !== undefined ? '   [' + extra + ']' : ''));
}
function section(t) { console.log('\n== ' + t + ' =='); }

/* ---------------- 加载 ---------------- */
section('加载四个模块');
for (const f of ['mock.js', 'api.js', 'map.js', 'app.js']) {
  try {
    vm.runInContext(fs.readFileSync(path.join(DIR, f), 'utf8'), ctx, { filename: f });
    check('加载 ' + f, true);
  } catch (e) {
    check('加载 ' + f, false, e.message);
    process.exit(1);
  }
}

const App = ctx.FlyerApp;
const screen = () => documentStub.querySelector('#screen').innerHTML;

section('启动状态');
check('暴露调试入口 FlyerApp', !!App);
check('启动无异常，快照已就绪', !!(App && App.state.snapshot && App.state.snapshot.airport));
check('飞行器数量 = 5', App.state.snapshot.traffic.length === 5, App.state.snapshot.traffic.length);
check('起降点 = CQ-LX01', App.state.snapshot.airport.code === 'CQ-LX01', App.state.snapshot.airport.code);
check('我的飞行器已绑定', App.state.profile.fleet.length === 2, App.state.profile.fleet.length);

section('5 个 Tab 渲染');
function goTab(tab) { ctx.location.hash = '#/' + tab; App.state.tab = tab; App.render(); return screen(); }

const home = goTab('home');
check('首页：态势图画布', /id="situation-map"/.test(home));
check('首页：天气胶囊', /weather-chip/.test(home));
check('首页：我的飞行器卡片', /uav-card/.test(home));
check('首页：告警横幅', /alert-banner/.test(home));

const near = goTab('nearby');
check('周边：起降点卡片', /airfield-grid/.test(near));
check('周边：气象仪表盘', /gauge-ring/.test(near));
check('周边：机位网格', /stand-card/.test(near));
check('周边：障碍物列表', /row-ico obs/.test(near));

goTab('apply');
const applyBody = documentStub.querySelector('#apply-body').innerHTML;
check('申请：预判区已填充', /verdict/.test(applyBody));
check('申请：原因列表', /reason-list/.test(applyBody));
check('申请：许可占位区', /permit-slot/.test(screen()));

const msgs = goTab('messages');
check('消息：分组列表', /msg-item/.test(msgs));
check('消息：未读标记', /msg-dot/.test(msgs));

const me = goTab('me');
check('我的：资料卡', /profile-card/.test(me));
check('我的：设置表单', /set-api/.test(me) && /set-ground/.test(me));

section('自动决策预判');
const T = (id) => App.state.snapshot.traffic.find((t) => t.id === id);
const rEmerg = App.evaluate(T('UAV-CQ044'), 'landing');
check('紧急状态飞行器 → DENY', rEmerg.level === 'DENY', rEmerg.reasons[0] && rEmerg.reasons[0].text);
const rRid = App.evaluate(T('UAV-CQ052'), 'landing');
check('RID 丢失飞行器 → DENY', rRid.level === 'DENY', rRid.reasons[0] && rRid.reasons[0].text);
const rOk = App.evaluate(T('UAV-CQ009'), 'landing');
check('正常待命飞行器 → 非 DENY', rOk.level !== 'DENY', rOk.level + ' / ' + rOk.reasons.length + ' 条依据');
const rNo = App.evaluate(null, 'takeoff');
check('未选飞行器 → DENY', rNo.level === 'DENY', rNo.reasons[0].text);

section('恶劣气象 → 预判降级');
const meteoBak = JSON.parse(JSON.stringify(App.state.snapshot.meteo));
App.state.snapshot.meteo = Object.assign({}, meteoBak, { visibility: 900, cloud_base_agl: 80, wind_speed: 11.5 });
const rBad = App.evaluate(T('UAV-CQ009'), 'takeoff');
check('能见度/云底/风速超标 → DENY', rBad.level === 'DENY', rBad.reasons.map((r) => r.text).join(' ; '));
App.state.snapshot.meteo = meteoBak;

section('许可签发 + 60s 倒计时');
App.state.applyUav = 'UAV-CQ009';
App.state.applyAction = 'landing';
App.submitApply();
const p1 = App.state.permit;
check('生成许可编号 CLR-*', !!(p1 && /^CLR-/.test(p1.id)), p1 && p1.id);
check('状态为 approved', p1.status === 'approved', p1.status);
check('时间线 >= 3 条', p1.timeline.length >= 3, p1.timeline.length);
check('倒计时在 0~60 之间', App.permitRemain() !== null && App.permitRemain() <= 60, App.permitRemain());
check('有效期 = 60s', p1.validSeconds === 60, p1.validSeconds);

App.state.applyUav = 'UAV-CQ052';
App.submitApply();
const p2 = App.state.permit;
check('RID 丢失 → 许可 denied', p2.status === 'denied', p2.status);
check('denied 时无倒计时', App.permitRemain() === null);

section('数据回退（后端不可用）');
check('数据源标记为 mock', App.state.source.core === 'mock', App.state.source.core);

section('后端地址自动推导（手机真机能否连上的关键）');
function loadApiWithHost(host) {
  const c = {};
  c.window = c; c.self = c;
  c.location = { hash: '', search: '', protocol: 'http:', hostname: host, origin: 'http://' + host + ':5502' };
  c.URLSearchParams = URLSearchParams;
  c.AbortController = AbortController;
  c.fetch = function () { return Promise.reject(new Error('offline')); };
  c.setTimeout = setTimeout; c.clearTimeout = clearTimeout;
  c.console = { log() {}, warn() {}, error() {} };
  vm.createContext(c);
  vm.runInContext(fs.readFileSync(path.join(DIR, 'mock.js'), 'utf8'), c, { filename: 'mock.js' });
  vm.runInContext(fs.readFileSync(path.join(DIR, 'api.js'), 'utf8'), c, { filename: 'api.js' });
  return c.FlyerApi.config;
}
const cfgLocal = loadApiWithHost('127.0.0.1');
check('电脑访问 → 后端 127.0.0.1:8080', cfgLocal.baseUrl === 'http://127.0.0.1:8080', cfgLocal.baseUrl);
check('电脑访问 → 地面站 127.0.0.1:8090', cfgLocal.groundUrl === 'http://127.0.0.1:8090', cfgLocal.groundUrl);
const cfgLan = loadApiWithHost('192.168.1.20');
check('手机访问 → 后端自动指向电脑 IP:8080', cfgLan.baseUrl === 'http://192.168.1.20:8080', cfgLan.baseUrl);
check('手机访问 → 地面站自动指向电脑 IP:8090', cfgLan.groundUrl === 'http://192.168.1.20:8090', cfgLan.groundUrl);

console.log('\n' + (failed ? '❌ 失败 ' + failed + ' 项' : '✅ 全部通过'));
process.exit(failed ? 1 : 0);
