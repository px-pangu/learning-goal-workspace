#!/usr/bin/env node
/* 数据归属安全性校验：证明「这份页面只会读写它自己被配置的那几张表」。
 *
 * 关心的问题：
 *   1) 页面里没配表 ID（默认占位符）时，即便运行在资料库环境里，会不会拿占位符去请求、
 *      或者连到作者的表上？—— 不应该有任何一次 SDK 调用。
 *   2) 使用者在「我的 → 数据表绑定」里填了自己的表 ID 后，请求打到的确实是那些 ID。
 *   3) 配置前后，页面都不会去碰任何「别人」的表 ID。
 *
 * 做法：桩掉 window.__SMART_PAGE__.database，记录每一次 SDK 调用的 databaseId，
 *      然后分别以「未配置」和「已配置」两种状态启动页面，检查调用记录。
 *
 * 用法：
 *   node tools/binding_check.js [--html ../index.html]
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
if (!m) throw new Error('没找到内联脚本');
const js = m[1];

let pass = 0, fail = 0;
const log = [];
function ck(label, cond, extra) {
  cond ? pass++ : fail++;
  log.push((cond ? '  PASS  ' : '  FAIL  ') + label + (extra ? '   [' + extra + ']' : ''));
}

/* ---------------- 桩 ---------------- */
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
function makeDom() {
  const els = {};
  const mainEl = makeEl('main');
  const nav = ['today', 'board', 'weekly', 'mine'].map(t => {
    const b = makeEl('nav-' + t); b.dataset.tab = t; return b;
  });
  return {
    els, mainEl, nav,
    document: {
      getElementById(id) { return (els[id] = els[id] || makeEl(id)); },
      createElement(t) { return makeEl('c-' + t); },
      querySelector(s) { return s === 'main' ? mainEl : null; },
      querySelectorAll(s) { return s === '.nav button' ? nav : []; },
      addEventListener() {}, activeElement: null,
      body: makeEl('body'), documentElement: makeEl('html')
    }
  };
}
/* 记录所有 SDK 调用的 databaseId */
function makeSdk() {
  const calls = [];
  const rec = name => p => { calls.push({ m: name, id: p && p.databaseId }); return Promise.resolve({ results: [], hasMore: false, id: 'rec1' }); };
  return {
    calls,
    query: rec('query'), getSchema: rec('getSchema'),
    addRecord: rec('addRecord'), updateRecord: rec('updateRecord'), deleteRecord: rec('deleteRecord'),
    onUpdated() {}, aggregate: () => Promise.resolve({})
  };
}

function boot({ sdk, store }) {
  const dom = makeDom();
  const mem = Object.assign({}, store || {});
  const localStorage = {
    getItem: k => (k in mem ? mem[k] : null),
    setItem: (k, v) => { mem[k] = String(v); },
    removeItem: k => { delete mem[k]; }
  };
  const window = {
    addEventListener() {}, removeEventListener() {},
    matchMedia() { return { matches: false, addEventListener() {}, addListener() {} }; },
    setTimeout, clearTimeout, Date, JSON, Math,
    navigator: { userAgent: 'node', clipboard: null }
  };
  if (sdk) window.__SMART_PAGE__ = { database: sdk };
  new Function('window', 'document', 'localStorage', 'console', 'setTimeout', 'clearTimeout',
    js)(window, dom.document, localStorage, console, setTimeout, clearTimeout);
  return { dom, mem };
}
const wait = ms => new Promise(r => setTimeout(r, ms));

(async function () {
  /* 页面是否已内置配置（跑过 tools/configure.py 就是已配置） */
  const builtin = {};
  ['DB_GOALS', 'DB_LOGS', 'DB_NOTES'].forEach(k => {
    const mm = html.match(new RegExp('var\\s+' + k + "\\s*=\\s*'([^']*)'"));
    builtin[k] = mm ? mm[1] : null;
  });
  const builtinConfigured = Object.values(builtin).every(v => v && !/^YOUR_/.test(v));

  /* 「允许出现的表 ID」= 页面内置配置 + 使用者填写的。
     真正要保证的性质是：任何一次请求都落在这个集合里，
     即「只读写被配置给它的表」。（单看位数分不出「他人」还是「自己配的」。） */
  const allowedIds = (extra) => {
    const s = new Set();
    Object.values(builtin).forEach(v => { if (v && !/^YOUR_/.test(v)) s.add(v); });
    (extra || []).forEach(v => v && s.add(v));
    return s;
  };
  const onlyConfigured = (ids, extra) => {
    const s = allowedIds(extra);
    return ids.every(v => s.has(v));
  };

  /* === 场景 1：资料库环境 + 页面自带配置状态 === */
  log.push(builtinConfigured
    ? '=== 场景 1：页面已内置配置（跑过 configure.py）==='
    : '=== 场景 1：运行在资料库环境，但页面还没配表 ID ===');
  const sdk1 = makeSdk();
  const env1 = boot({ sdk: sdk1 });
  await wait(60);

  if (builtinConfigured) {
    const ids1 = [...new Set(sdk1.calls.map(c => c.id).filter(Boolean))];
    ck('启动即读取内置配置的表', sdk1.calls.length > 0, '调用次数 ' + sdk1.calls.length);
    ck('请求打到内置配置的三个 ID',
      Object.values(builtin).every(v => ids1.includes(v)), ids1.join(','));
    ck('不出现占位符', !ids1.some(v => /^YOUR_/.test(v)), ids1.join(','));
    ck('请求不落在配置之外的任何表上', onlyConfigured(ids1), ids1.join(','));
  } else {
    ck('一次 SDK 调用都没有（不会拿占位符去请求）', sdk1.calls.length === 0,
      '调用次数 ' + sdk1.calls.length);
    ck('不会连到任何硬编码的他人表 ID',
      !sdk1.calls.some(c => c.id && /^[A-Za-z0-9]{22}$/.test(c.id)),
      sdk1.calls.map(c => c.id).join(',') || '无调用');
  }
  if (!builtinConfigured) {
    ck('界面明确提示「未绑定数据表」',
      /未绑定|尚未绑定/.test(env1.dom.document.getElementById('netText').textContent +
        env1.dom.document.getElementById('mineSyncHint').textContent +
        env1.dom.document.getElementById('heroSync').innerHTML),
      env1.dom.document.getElementById('netText').textContent.slice(0, 40));
    ck('未配置时仍能正常建目标（数据留在本机）', (function () {
      env1.dom.document.getElementById('btnSideAdd').fire('click');
      env1.dom.document.getElementById('fName').value = '未配置也能建';
      env1.dom.document.getElementById('fTotal').value = '50';
      env1.dom.document.getElementById('fDeadline').value =
        new Date(Date.now() + 20 * 86400000).toISOString().slice(0, 10);
      env1.dom.document.getElementById('modalSave').fire('click');
      return /未配置也能建/.test(env1.dom.document.getElementById('boardGrid').innerHTML);
    })());
    ck('本机新建不会尝试写云端', sdk1.calls.length === 0, '调用次数 ' + sdk1.calls.length);
  }

  /* === 场景 2：「我的」页手填自己的表 ID === */
  log.push('');
  log.push('=== 场景 2：在「我的 → 数据表绑定」填入自己的三张表 ===');
  const MINE = {
    goals: 'MyGoalsTableId0001',
    logs: 'MyLogsTableId00001',
    notes: 'MyNotesTableId0001'
  };
  const sdk2 = makeSdk();
  const env2 = boot({ sdk: sdk2 });
  await wait(40);
  env2.dom.document.getElementById('bindGoals').value = MINE.goals;
  env2.dom.document.getElementById('bindLogs').value = MINE.logs;
  env2.dom.document.getElementById('bindNotes').value = MINE.notes;
  env2.dom.document.getElementById('btnBindSave').fire('click');
  await wait(80);

  ck('保存后立刻开始读取配置的表', sdk2.calls.length > 0, '调用次数 ' + sdk2.calls.length);
  const usedIds = [...new Set(sdk2.calls.map(c => c.id).filter(Boolean))];
  ck('请求打到的正是填写的三个 ID',
    [MINE.goals, MINE.logs, MINE.notes].every(v => usedIds.includes(v)),
    '实际请求: ' + usedIds.join(','));
  ck('不出现占位符', !usedIds.some(v => /^YOUR_/.test(v)), usedIds.join(','));
  ck('请求不落在配置之外的任何表上', onlyConfigured(usedIds, Object.values(MINE)), usedIds.join(','));
  ck('绑定状态区显示已绑定的表',
    /MyGoalsTableId0001/.test(env2.dom.document.getElementById('bindStatus').innerHTML));

  /* === 场景 3：重开后本机绑定仍然生效 === */
  log.push('');
  log.push('=== 场景 3：关掉重开，绑定还在 ===');
  const sdk3 = makeSdk();
  boot({ sdk: sdk3, store: { goal_workspace_v2_binding: JSON.stringify(MINE) } });
  await wait(80);
  const ids3 = [...new Set(sdk3.calls.map(c => c.id).filter(Boolean))];
  ck('重开后仍读取自己的表', ids3.includes(MINE.logs), ids3.join(','));
  ck('重开后仍只读写配置的表', onlyConfigured(ids3, Object.values(MINE)), ids3.join(','));

  console.log(log.join('\n'));
  console.log('\n结果：' + pass + ' 通过 / ' + fail + ' 失败');
  process.exit(fail ? 1 : 0);
})();
