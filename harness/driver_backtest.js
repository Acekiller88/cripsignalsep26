// Driver kanonik: backtest DATA-SEBENAR (klines Binance 2017-2025) — TIADA demo.
// Guna: node run.cjs <html> backtest [scope=10] [len=2000] ['{AB}'] [cap=0]
// AB: {"liqGate":bool,"adxGate":bool,"regime":"smart|all|trend","smc":bool,"minProb":n}
// Default AB kosong = default produk v8.2 (liq OFF, adx ON, smart, SMC, 70).
const FSB = require('fs');
const scope = +(process.argv[4] || 10);
const REALLEN = +(process.argv[5] || 2000);
const AB = JSON.parse(process.argv[6] || '{}');
const CAP = +(process.argv[7] || 0);
const JDIR = '/home/user/v8test/realdata/json/';
const cache = {};
function load1h(sym) {
  const s = sym.replace('USDT', '');
  if (cache[s]) return cache[s];
  try { cache[s] = JSON.parse(FSB.readFileSync(JDIR + s + '.json', 'utf8')); } catch (e) { cache[s] = null; }
  return cache[s];
}
function to4h(rows) {
  const out = []; let cur = null, key = -1;
  for (const r of rows) {
    const k = Math.floor(r[0] / 14400000);
    if (k !== key) { if (cur) out.push(cur); key = k; cur = { time: key * 14400000 + 14400000, open: r[1], high: r[2], low: r[3], close: r[4], volume: r[5] }; }
    else { cur.high = Math.max(cur.high, r[2]); cur.low = Math.min(cur.low, r[3]); cur.close = r[4]; cur.volume += r[5]; }
  }
  if (cur) out.push(cur); return out;
}
class CapArr extends Array {
  static get [Symbol.species]() { return Array; }
  slice(a, b) { const L = this.length; const B = (b === undefined) ? L : (b < 0 ? L + b : b); return super.slice(Math.max(0, B - this._cap), B); }
}
class HtfArr extends Array {
  static get [Symbol.species]() { return Array; }
  filter(fn) { let lo = 0, hi = this.length; while (lo < hi) { const m = (lo + hi) >>> 1; if (fn(this[m])) lo = m + 1; else hi = m; } return super.slice(Math.max(0, lo - 300), lo); }
}
const HTF_EXTRA = 600;
const meta = {};
fetchKlines = async function (symbol, interval, limit) {
  const rows = load1h(symbol);
  if (!rows || !rows.length) return [];
  const isHTF = (interval === '4h' || interval === '1d');
  if (isHTF) {
    const end = rows.length, start = Math.max(0, rows.length - (REALLEN || rows.length) - HTF_EXTRA);
    const h = to4h(rows.slice(start, end));
    return CAP > 0 ? HtfArr.from(h) : h;
  }
  const w = REALLEN > 0 ? rows.slice(-REALLEN) : rows.slice();
  meta[symbol] = { n: w.length, from: new Date(w[0][0]).toISOString().slice(0, 10), to: new Date(w[w.length - 1][0]).toISOString().slice(0, 10) };
  const arr = w.map(r => ({ time: r[0], open: r[1], high: r[2], low: r[3], close: r[4], volume: r[5] }));
  if (CAP > 0 && arr.length > CAP) { const c = CapArr.from(arr); c._cap = CAP; return c; }
  return arr;
};
document.getElementById('btScope').value = String(scope);
document.getElementById('btTF').value = '1h';
document.getElementById('btUseFilters').checked = true;
if (AB.regime) regimeFilter = AB.regime;
if (AB.smc === false) smcRequired = false;
if (AB.minProb) minProb = AB.minProb;
document.getElementById('btLiqGate').checked = AB.liqGate !== undefined ? AB.liqGate : false;
document.getElementById('btAdxGate').checked = AB.adxGate !== undefined ? AB.adxGate : true;
const T0 = process.hrtime.bigint();
await runBacktest();
const WALL = (Number(process.hrtime.bigint() - T0) / 1e9).toFixed(1);
const g = (id) => document.getElementById(id).textContent;
console.log('SCOPE=' + scope + ' TF=1h REALv82 len=' + (REALLEN || 'ALL') + ' cap=' + (CAP || 'off') + ' wall~' + WALL + 's');
console.log('META=' + JSON.stringify(meta));
console.log('N=' + g('btN') + ' | ' + document.getElementById('btNsub').textContent);
console.log('WR=' + g('btWR') + ' EXP=' + g('btExp') + ' PF=' + g('btPF'));
const strip = (s) => s.replace(/<[^>]+>/g, '|').replace(/\|+/g, ' | ').replace(/\s+/g, ' ');
console.log('BYGRADE: ' + strip(document.getElementById('btByGrade').innerHTML));
console.log('BYPAIR: ' + strip(document.getElementById('btByPair').innerHTML).slice(0, 1500));
console.log('FUNNEL: ' + strip(document.getElementById('btFunnel').innerHTML));
console.log('BYSESS: ' + strip(document.getElementById('btBySess').innerHTML));
console.log('BYREG: ' + strip(document.getElementById('btByReg').innerHTML));
