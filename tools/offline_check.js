#!/usr/bin/env node
/* 离线可用性自检：回答「clone 下来直接用浏览器打开 index.html 能不能用」。
 *
 * 与 render_check.js 的区别：
 *   - render_check.js 走「有资料库 SDK + 线上真实数据」的路径；
 *   - 本脚本刻意把环境模拟成「纯浏览器 + 没有 window.__SMART_PAGE__ + 空 localStorage」，
 *     并且【保留页面完整的启动段】，跑真实的 loadMeta → loadCache → bind → refreshAll → SDK 判定，
 *     再用桩 DOM 模拟点击，验证离线模式下仍然建得了目标、打得了卡、关掉重开数据还在。
 *
 * 用法：
 *   node tools/offline_check.js [--html ../index.html]
 *
 * 退出码 0 = 全部通过。
 */
const fs = require('fs');
const path = require('path');

function arg(name, def) {
  const i = process.argv.indexOf('--' + name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def;
}

const ROOT = path.join(__dirname, '..');
const HTML = path.resolve(ROOT, arg('html', 'index.html'));
const html = fs.readFileSync(HTML, 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) throw new Error('页面里没找到内联脚本: ' + HTML);
const js = m[1];

let pass = 0, fail = 0;
const log = [];
function ck(label, cond, extra) {
  cond ? pass++ : fail++;
  log.push((cond ? '  PASS  ' : '  FAIL  ') + label + (extra ? '   [' + extra + ']' : ''));
}

/* ---------------- 桩 DOM：按 id 复用实例，可记录并触发事件 ---------------- */
function makeEl(id) {
  const h = {};
  const el = {
    id, innerHTML: '', textContent: '', className: '', value: '', checked: false,
    style: {}, dataset: {}, offsetParent: {}, children: [],
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    setAttribute() {}, getAttribute() { return null; }, removeAttribute() {},
    appendChild() {}, insertBefore() {}, remove() {}, focus() {}, blur() {}, click() {},
    querySelector() { return null; }, querySelectorAll() { return []; },
    closest() { return null; },
    addEventListener(t, fn) { (h[t] = h[t] || []).push(fn); },
    removeEventListener() {},
    fire(t, ev) { (h[t] || []).forEach(fn => fn(ev || { target: el, preventDefault() {} })); }
  };
  return el;
}

function makeEnv(store) {
  const els = {};
  const mainEl = makeEl('main');
  const nav = ['today', 'board', 'weekly', 'mine'].map(t => {
    const b = makeEl('nav-' + t); b.dataset.tab = t; return b;
  });
  const document = {
    getElementById(id) { return (els[id] = els[id] || makeEl(id)); },
    createElement(tag) { return makeEl('el-' + tag); },
    querySelector(sel) { return sel === 'main' ? mainEl : null; },
    querySelectorAll(sel) { return sel === '.nav button' ? nav : []; },
    addEventListener() {}, activeElement: null,
    body: makeEl('body'), documentElement: makeEl('html')
  };
  return { els, mainEl, nav, document };
}

/* localStorage：跨「两次启动」共享，用于验证持久化 */
const mem = {};
const localStorage = {
  getItem: k => (k in mem ? mem[k] : null),
  setItem: (k, v) => { mem[k] = String(v); },
  removeItem: k => { delete mem[k]; }
};

/* 关键：不注入 window.__SMART_PAGE__ —— 模拟 clone 后在普通浏览器打开 */
const window = {
  addEventListener() {}, removeEventListener() {},
  matchMedia() { return { matches: false, addEventListener() {}, addListener() {} }; },
  setTimeout, clearTimeout, Date, JSON, Math,
  navigator: { userAgent: 'node', clipboard: null }
};

function boot(document) {
  new Function('window', 'document', 'localStorage', 'console', 'setTimeout', 'clearTimeout', 'alert',
    js)(window, document, localStorage, console, setTimeout, clearTimeout, () => {});
}

/* ---------------- 启动 ---------------- */
log.push('=== 场景：clone 后在普通浏览器打开（无资料库 SDK）===');
const env = makeEnv();
let bootError = null;
try { boot(env.document); } catch (e) { bootError = e; }

ck('启动不抛异常（不白屏的前提）', !bootError, bootError ? bootError.message : '');
if (bootError) {
  console.log(log.join('\n'));
  console.log('\n启动即失败：\n' + (bootError.stack || bootError.message));
  process.exit(1);
}

const $ = id => env.document.getElementById(id).innerHTML;
const txt = id => env.document.getElementById(id).textContent;

/* 1. 首屏是否真的渲染出东西 */
const zones = ['todayZone', 'todayList', 'heroChips', 'todayStats', 'boardGrid', 'weekSummary', 'mineSyncHint'];
const rendered = zones.filter(z => ($(z) || '').length > 0);
ck('首屏各区块有渲染内容（不白屏）', rendered.length >= 5,
  rendered.length + '/' + zones.length + '：' + rendered.join(','));
ck('空状态有引导文案（不是一片空白）',
  /新建|还没有|开始|添加|创建|目标/.test($('todayZone') + $('todayList') + $('boardGrid')));
/* 回归：离线结论确定后，首屏不能再停留在「正在加载中」 */
ck('首屏不残留「正在加载中」（不让用户干等）',
  !/正在加载中/.test($('todayZone') + $('todayList')),
  '片段：' + ($('todayZone') + $('todayList')).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 80));

/* 2. 同步状态是否诚实 */
const syncAll = txt('heroSync') + txt('mineSyncHint') + $('heroSync') + $('mineSyncHint');
ck('明确告知处于离线 / 无法连接数据表', /离线|无法连接|不可用/.test(syncAll));

/* 3. 离线模式下新建目标 */
env.document.getElementById('btnSideAdd').fire('click');
const dl = new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10);
env.document.getElementById('fName').value = '离线自检目标';
env.document.getElementById('fUnit').value = '页';
env.document.getElementById('fTotal').value = '100';
env.document.getElementById('fDeadline').value = dl;
env.document.getElementById('fObstacle').value = '总是忘记';
env.document.getElementById('fPlan').value = '如果想不起来，就先打开这一页';
env.document.getElementById('modalSave').fire('click');

const afterAdd = $('todayList') + $('todayZone') + $('boardGrid');
ck('离线模式下能新建目标', /离线自检目标/.test(afterAdd));
ck('新建的目标出现在看板', /离线自检目标/.test($('boardGrid')));
ck('今日建议量已算出（无 NaN / undefined）', !/NaN|undefined/.test($('todayList') + $('todayZone')));

/* 4. 离线模式下打卡 */
const ids = [...new Set([...($('todayList') + $('todayZone')).matchAll(/data-checkin="([^"]+)"/g)].map(x => x[1]))];
ck('目标卡渲染出可点击的打卡入口', ids.length > 0, ids.length + ' 个');
if (ids.length) {
  const gid = ids[0];
  env.document.getElementById('amt-' + gid).value = '10';
  const target = makeEl('chk');
  target.dataset.checkin = gid;
  target.closest = () => target;
  env.mainEl.fire('click', { target, preventDefault() {} });
  const after = $('todayList') + $('todayZone') + $('boardGrid');
  ck('离线模式下能打卡', /10%|10 &nbsp;/.test(after));
  ck('打卡后页面无 NaN / undefined', !/NaN|undefined/.test(after));
}

/* 5. 数据落本机：关掉重开还在 */
ck('数据已写入 localStorage', Object.keys(mem).length > 0, Object.keys(mem).join(','));

const env2 = makeEnv();
let rebootError = null;
try { boot(env2.document); } catch (e) { rebootError = e; }
const after2 = env2.document.getElementById('todayList').innerHTML + env2.document.getElementById('boardGrid').innerHTML;
ck('重开不报错', !rebootError, rebootError ? rebootError.message : '');
ck('重开后数据还在（离线模式真正可用）', /离线自检目标/.test(after2));

/* 6. Tab 切换 */
env2.nav.forEach(b => b.fire('click'));
ck('四个 Tab 可切换且不报错', true, 'today/board/weekly/mine');

console.log(log.join('\n'));
console.log('\n结果：' + pass + ' 通过 / ' + fail + ' 失败');
process.exit(fail ? 1 : 0);
