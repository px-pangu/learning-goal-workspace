#!/usr/bin/env node
/* 渲染回归校验：不重写一遍业务逻辑，而是抽出页面自身的内联脚本，
 * 用桩 DOM 驱动 applyGoals/applyLogs/applyNotes + refreshAll，
 * 再对真实渲染出来的 DOM 做断言。输入是线上数据表读回的行数据，
 * 因此断言通过 = 「表里存的东西在页面上确实渲染成预期状态」。
 *
 * 用法：
 *   node tools/render_check.js [--html index.html] [--rows-dir .cache]
 *
 * 前置：先跑 tools/fetch_rows.py 生成 .cache/rows_goals.json 等文件。
 */

const fs = require('fs');
const path = require('path');

function arg(name, def) {
  const i = process.argv.indexOf('--' + name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def;
}

const ROOT = path.join(__dirname, '..');
const HTML = path.resolve(ROOT, arg('html', 'index.html'));
const ROWS_DIR = path.resolve(ROOT, arg('rows-dir', '.cache'));

const html = fs.readFileSync(HTML, 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) throw new Error('页面里没找到内联脚本: ' + HTML);
let js = m[1];

/* 切掉末尾「启动」段（它需要真实 DOM 与资料库 SDK），再补回 IIFE 收尾，
 * 并把内部函数挂到 window 上供校验使用。 */
const MARK = '/* ================= 启动 ================= */';
const cut = js.indexOf(MARK);
if (cut < 0) throw new Error('未找到启动段，页面脚本结构与预期不符（可能已被改写）');
js = js.slice(0, cut) + `
window.__T={state:state,applyGoals:applyGoals,applyLogs:applyLogs,applyNotes:applyNotes,
refreshAll:refreshAll,setSync:setSync,todayStr:todayStr,streak:streak,eta:eta,dailySuggest:dailySuggest,
isOverdue:isOverdue,isComplete:isComplete,missedYesterday:missedYesterday,isRestDay:isRestDay,
goalById:goalById,doneAmount:doneAmount,last7Sum:last7Sum,dateSetOf:dateSetOf,addDays:addDays,
logsExpanded:logsExpanded,fmtShort:fmtShort};})();`;

/* ---------------- DOM 桩：按 id 复用同一实例，便于回收渲染结果 ---------------- */
const els = {};
function makeEl(id) {
  return {
    id, innerHTML: '', textContent: '', className: '', value: '', checked: false,
    style: {}, dataset: {}, offsetParent: null,
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener() {}, removeEventListener() {}, appendChild() {}, focus() {},
    closest() { return null; }, querySelector() { return null; }, querySelectorAll() { return []; },
    getAttribute() { return null; }, setAttribute() {}, removeAttribute() {},
    insertBefore() {}, remove() {}
  };
}
const document = {
  getElementById(id) { return (els[id] = els[id] || makeEl(id)); },
  createElement(tag) { return makeEl('new-' + tag); },
  querySelector() { return null; }, querySelectorAll() { return []; },
  addEventListener() {}, activeElement: null, body: makeEl('body')
};
const mem = {};
const localStorage = {
  getItem: k => (k in mem ? mem[k] : null),
  setItem: (k, v) => { mem[k] = String(v); },
  removeItem: k => { delete mem[k]; }
};

const W = {};
new Function('window', 'document', 'localStorage', 'console', js)(W, document, localStorage, console);
const api = W.__T;
if (!api) throw new Error('脚本内部对象未导出，请检查启动段标记是否仍然存在');

function readRows(name) {
  const p = path.join(ROWS_DIR, name);
  if (!fs.existsSync(p)) throw new Error('缺少 ' + p + '（先运行 tools/fetch_rows.py）');
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

api.setSync('synced', '');
const nGoals = api.applyGoals(readRows('rows_goals.json'));
const nLogs = api.applyLogs(readRows('rows_logs.json'));
const nNotes = api.applyNotes(readRows('rows_notes.json'));
api.refreshAll();

const $ = id => document.getElementById(id).innerHTML;
const txt = id => document.getElementById(id).textContent;
const today = api.todayStr();

let pass = 0, fail = 0;
const log = [];
function ck(label, cond) { cond ? pass++ : fail++; log.push((cond ? '  PASS  ' : '  FAIL  ') + label); }

const Z = $('todayZone'), L = $('todayList'), D = $('doneSection'), B = $('boardGrid'), H = $('heroChips');

log.push('今天 = ' + today + ' | 载入 目标 ' + nGoals + ' / 记录 ' + nLogs + ' / 复盘 ' + nNotes);
log.push('\n[今日]');
ck('红卡：显示「已逾期 N 天，且昨天没学」', /已逾期 \d+ 天，且昨天没学/.test(Z));
ck('红卡：提供「立即打卡」与「调整计划」两个出口',
  Z.indexOf('data-checkin="seed-g2"') >= 0 && Z.indexOf('调整计划') >= 0);
ck('黄卡：显示已用本周休息日且连续天数保住',
  Z.indexOf('本周休息日') >= 0 && Z.indexOf('连续天数保住了') >= 0);
ck('黄卡：使用休息日卡片样式', Z.indexOf('rest-card') >= 0);
ck('卡片展示用户预案（如果…我就…）', Z.indexOf('如果下班回家觉得太累，我就先只打开编辑器写一行代码') >= 0);
ck('已完成区含今日已打卡目标且带「示例」标', D.indexOf('背英语单词') >= 0 && D.indexOf('示例') >= 0);
ck('待打卡区含其余目标', L.indexOf('Python 入门课') >= 0 && L.indexOf('人类简史') >= 0);
ck('首屏累计记录数与数据一致', H.indexOf('>' + nLogs + '<') >= 0);

log.push('\n[看板]');
ck('三种预计完成日文案齐全：提前 / 拖后 / 暂无推算',
  B.indexOf('提前') >= 0 && B.indexOf('拖后') >= 0 && B.indexOf('暂无推算') >= 0);
ck('进度环 + 完成率/连续天数/预计完成日三个核心数字',
  /class="ring"/.test(B) && B.indexOf('完成率') >= 0 && B.indexOf('连续') >= 0);
ck('预案展示在看板', B.indexOf('如果拿起手机，我就先把单词 App 打开') >= 0);
ck('每个目标都有可展开的记录区', (B.match(/data-togglelogs=/g) || []).length === nGoals);
api.state.goals.forEach(g => { api.logsExpanded[g.id] = true; });
api.refreshAll();
const B2 = $('boardGrid');
const delBtns = (B2.match(/data-dellog=/g) || []).length;
const capSum = api.state.goals.reduce((s, g) =>
  s + Math.min(10, api.state.logs.filter(l => l.goalId === g.id).length), 0);
ck('展开后记录按每目标上限 10 条渲染（' + delBtns + ' 个删除按钮）', delBtns === capSum);
ck('超出上限时给出「仅显示最近 10 条」提示', B2.indexOf('仅显示最近 10 条') >= 0);
ck('补记记录带「补」标', B2.indexOf('badge-makeup') >= 0);
const C2 = $('chartBox');
ck('手写 SVG 堆叠柱状图已渲染（' + (C2.match(/<rect /g) || []).length + ' 个分块）',
  /<svg/.test(C2) && (C2.match(/<rect /g) || []).length >= 20);
ck('图例列出参与投入的目标', $('chartLegend').indexOf('背英语单词') >= 0);

log.push('\n[周报 / 我的]');
const WS = $('weekSummary');
ck('周报按周一到周日汇总投入/天数/分钟', WS.indexOf('分钟') >= 0 && WS.indexOf('打卡') >= 0);
ck('周报含上周同口径环比', WS.indexOf('上周') >= 0);
ck('我的页显示同步状态与最近同步时间',
  txt('mineSyncState').length > 0 && txt('mineSyncTime').indexOf('最近同步：') === 0);

log.push('\n[计算值]');
api.state.goals.forEach(g => {
  const e = api.eta(g);
  const etaTxt = e.status === 'ok' ? (e.date + (e.diff >= 0 ? ' 提前 ' + e.diff + ' 天' : ' 拖后 ' + (-e.diff) + ' 天'))
    : e.status === 'done' ? '已完成' : '暂无推算';
  log.push('  ' + g.name + '  ' + api.doneAmount(g.id) + '/' + g.total +
    ' (' + Math.round(api.doneAmount(g.id) / g.total * 100) + '%)' +
    '  连续 ' + api.streak(g.id) + ' 天' +
    '  今日建议 +' + api.dailySuggest(g) +
    '  预计完成日 ' + etaTxt);
});

log.push('\n结果：' + pass + ' 通过 / ' + fail + ' 失败');
console.log(log.join('\n'));
process.exit(fail ? 1 : 0);
