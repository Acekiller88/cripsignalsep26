// Tune Lab e2e: mod rawak (seed+bajet) + mod LLM (fetch stub) atas data real.
// Guna: node run.cjs <html> tune
const FST = require('fs');
const LENT = 600;
const JDIRT = '/home/user/v8test/realdata/json/';
const cacheT = {};
function load1hT(sym) {
  const s = sym.replace('USDT', '');
  if (cacheT[s]) return cacheT[s];
  try { cacheT[s] = JSON.parse(FST.readFileSync(JDIRT + s + '.json', 'utf8')); } catch (e) { cacheT[s] = null; }
  return cacheT[s];
}
function to4hT(rows) {
  const out = []; let cur = null, key = -1;
  for (const r of rows) {
    const k = Math.floor(r[0] / 14400000);
    if (k !== key) { if (cur) out.push(cur); key = k; cur = { time: key * 14400000 + 14400000, open: r[1], high: r[2], low: r[3], close: r[4], volume: r[5] }; }
    else { cur.high = Math.max(cur.high, r[2]); cur.low = Math.min(cur.low, r[3]); cur.close = r[4]; cur.volume += r[5]; }
  }
  if (cur) out.push(cur); return out;
}
fetchKlines = async function (symbol, interval, limit) {
  const rows = load1hT(symbol);
  if (!rows || !rows.length) return [];
  if (interval === '4h' || interval === '1d') {
    const start = Math.max(0, rows.length - LENT - 600);
    return to4hT(rows.slice(start, rows.length));
  }
  return rows.slice(-LENT).map(r => ({ time: r[0], open: r[1], high: r[2], low: r[3], close: r[4], volume: r[5] }));
};
const stripT = (s) => s.replace(/<[^>]+>/g, '|').replace(/\|+/g, ' | ').replace(/\s+/g, ' ');
// FASA 1: rawak
document.getElementById('tuneHypo').value = 'ujian ejen: prob75 lawan baseline';
document.getElementById('tuneScope').value = '10';
document.getElementById('tuneBudget').value = '4';
document.getElementById('tuneSeed').value = '7';
document.getElementById('tuneMode').value = 'rawak';
await runTuneLab();
console.log('TUNE-RAWAK: ' + stripT(document.getElementById('tuneOut').innerHTML));
console.log('ROWS: ' + stripT(document.getElementById('tuneRows').innerHTML).slice(0, 700));
// FASA 2: LLM stub (2 sah + 1 rosak -> preflight + top-up rawak)
globalThis.fetch = async (url, opts) => ({
  ok: true,
  json: async () => ({ message: { content: '{"candidates":[{"minProb":75,"regime":"smart","smc":true},{"minProb":65,"regime":"all","smc":false},{"minProb":99,"regime":"xxx","smc":"ya"}]}' } })
});
document.getElementById('tuneHypo').value = 'ujian llm stub';
document.getElementById('tuneMode').value = 'llm';
document.getElementById('tuneBudget').value = '4';
await runTuneLab();
console.log('TUNE-LLM: ' + stripT(document.getElementById('tuneOut').innerHTML));
const JJ = JSON.parse(localStorage.getItem('gsv83_tune_journal_v1'));
console.log('JOURNAL runs=' + JJ.runs.length);
JJ.runs.forEach((r, i) => console.log(' run' + i + ' mode=' + r.mode + ' trials=' + r.trials.length + ' verdict=' + r.verdict));
