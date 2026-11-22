'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
const nodes = new Map();
function element() {
  return { innerHTML: '', textContent: '', className: '', value: '', checked: true,
    selectedOptions: [{ textContent: '演示指令' }], children: [], events: {}, style: {},
    addEventListener(name, fn) { this.events[name] = fn; },
    appendChild(child) { this.children.push(child); },
    getContext() { return {}; },
    getBoundingClientRect() { return { width: 500, height: 500, left: 0, top: 0 }; } };
}
const document = {
  getElementById(id) { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); },
  createElement: element, createDocumentFragment: element
};
let timers = 0;
const math = Object.create(Math);
math.random = () => 0.5;
const sandbox = { document, console, AbortController, fetch: () => Promise.reject(new Error('offline')),
  setTimeout() { timers++; return 1; }, clearTimeout() {}, setInterval() {}, Date, Math: math };
sandbox.window = sandbox;
vm.createContext(sandbox);
function load(file) { vm.runInContext(fs.readFileSync(path.join(root, file), 'utf8'), sandbox, { filename: file }); }
load('shared/interface.js');
load('pilot-app/flyer-app/decision.js');
let app = fs.readFileSync(path.join(__dirname, 'app.js'), 'utf8');
const marker = '  /* ----------------------------- 启动 ----------------------------- */';
assert.ok(app.includes(marker));
app = app.slice(0, app.indexOf(marker)) + '\nwindow.testApp = { state, runConflictDetection, autoDecision, receiveRid };\n})();';
vm.runInContext(app, sandbox, { filename: 'communication/app.js' });
const { state, runConflictDetection, autoDecision, receiveRid } = sandbox.testApp;
sandbox.LAC.geo.setOrigin(0, 0, 0);
state.externalSnapshot = { airport: { code: 'A' }, airspaces: [], obstacles: [
  { id: 'O1', name: '塔', active: true, lat: 0, lon: 0, radius: 10, buffer: 5, top_msl: 100 }
] };
const f = { id: 'F1', x: 0, y: 0, alt: 100, phase: 'APPROACH', emergency: false,
  ridLost: false, regNo: 'R', uaId: 'U', battery: 60, linkQuality: 4 };
state.flights = [f];
f.ridLost = undefined;
receiveRid(f);
assert.equal(f.ridLost, false);
state.weather = { visibility: 5000, ceiling: 500, wind: 5, gust: 8 };
state.ground = { airport_code: 'A', data_source: 'demo', generated_at: new Date().toISOString(), stands: [{ status: 'free' }] };
runConflictDetection();
assert.equal(state.alerts.some(a => a.id === 'OBS-CONFLICT-F1-O1'), true);
assert.equal(f.emergency, false);
assert.equal(autoDecision(f).result, 'DENY');
state.externalSnapshot = null;
runConflictDetection();
assert.equal(state.alerts.some(a => a.id === 'OBS-CONFLICT-F1-O1'), true);
assert.equal(state.alerts.some(a => a.id === 'OBS-DATA-UNAVAILABLE'), true);
state.externalSnapshot = { airport: { code: 'A' }, airspaces: [], obstacles: [] };
runConflictDetection();
assert.equal(state.alerts.some(a => a.id === 'OBS-CONFLICT-F1-O1'), false);
assert.equal(state.alerts.some(a => a.id === 'OBS-DATA-UNAVAILABLE'), false);
assert.equal(autoDecision(f).result, 'HOLD');
assert.match(autoDecision(f).reason, /可用机位 1 个/);
state.ground.airport_code = 'B';
assert.match(autoDecision(f).reason, /不属于同一起降点/);
state.ground.airport_code = 'A';
state.degraded.rid = true;
assert.equal(autoDecision(f).result, 'HOLD');
assert.doesNotMatch(autoDecision(f).reason, /识别信号丢失/);
document.getElementById('cmd-target').value = 'ALL';
document.getElementById('cmd-type').value = 'GO_AROUND';
document.getElementById('btn-send').events.click();
assert.equal(timers, 0);
assert.equal(f.emergency, false);
console.log('通讯态势告警和指令拦截自测通过');
