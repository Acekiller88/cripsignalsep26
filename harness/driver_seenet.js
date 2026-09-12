// Analisis fee-vs-edge: selesaikan setiap trade (v8 exits), banding gross vs net-of-fees + varian penapis feeR.
// Guna: node run.cjs <html> seenet [scope=10] [len=6000]
// Default produk v8.1 (liqGate OFF, minProb 70, smart, SMC) — tidak di-override.
const FSR4 = require('fs');
const scopeN = +(process.argv[4] || 10);
const LENN = +(process.argv[5] || 6000);
const JDIRN = '/home/user/v8test/realdata/json/';
const cacheN = {};
function load1hN(sym) {
  const s = sym.replace('USDT', '');
  if (cacheN[s]) return cacheN[s];
  try { cacheN[s] = JSON.parse(FSR4.readFileSync(JDIRN + s + '.json', 'utf8')); } catch (e) { cacheN[s] = null; }
  return cacheN[s];
}
function to4hN(rows) {
  const out = []; let cur = null, key = -1;
  for (const r of rows) {
    const k = Math.floor(r[0] / 14400000);
    if (k !== key) { if (cur) out.push(cur); key = k; cur = { time: key * 14400000 + 14400000, open: r[1], high: r[2], low: r[3], close: r[4], volume: r[5] }; }
    else { cur.high = Math.max(cur.high, r[2]); cur.low = Math.min(cur.low, r[3]); cur.close = r[4]; cur.volume += r[5]; }
  }
  if (cur) out.push(cur); return out;
}
fetchKlines = async function (symbol, interval, limit) {
  const rows = load1hN(symbol);
  if (!rows || !rows.length) return [];
  if (interval === '4h' || interval === '1d') {
    const start = Math.max(0, rows.length - LENN - 600);
    return to4hN(rows.slice(start, rows.length));
  }
  return rows.slice(-LENN).map(r => ({ time: r[0], open: r[1], high: r[2], low: r[3], close: r[4], volume: r[5] }));
};
const pairsN = PAIRS.slice(0, scopeN);
const TR = []; let nOpen = 0;
for (const sym of pairsN) {
  let ltf, htf;
  try { [ltf, htf] = await Promise.all([fetchKlines(sym, '1h', KLINE_LIM), fetchKlines(sym, '4h', HTF_LIM)]); }
  catch (e) { continue; }
  let openTrade = null;
  for (let i = 160; i < ltf.length; i++) {
    const c = ltf[i];
    if (openTrade) { const res = v8StepExit(openTrade, c); if (res) { openTrade.res = res; TR.push(openTrade); openTrade = null; } else continue; }
    const htfSlice = htf.filter(h => h.time <= c.time);
    if (htfSlice.length < 60) continue;
    const r = analyzeCandles(ltf.slice(0, i + 1), htfSlice, minProb, c.time);
    if (r && r.direction && r.grade) {
      const isL = r.direction === 'LONG';
      const sl = isL ? r.longSL : r.shortSL;
      const R = Math.abs(r.entry - sl);
      const tr = { sym, dir: r.direction, grade: r.grade, entry: r.entry, sl, slPct: R / r.entry * 100,
        tp1: isL ? r.longTP1 : r.shortTP1, tp2: isL ? r.longTP2 : r.shortTP2 };
      v8InitExit(tr); openTrade = tr;
    }
  }
  if (openTrade) nOpen++;
}
const stats = (arr, net) => {
  const rs = arr.map(t => net ? t.res.rMult - net / t.slPct : t.res.rMult);
  const n = rs.length, w = rs.filter(x => x > 0);
  const s = rs.reduce((a, x) => a + x, 0), m = s / n;
  const sd = Math.sqrt(rs.reduce((a, x) => a + (x - m) * (x - m), 0) / n);
  const gw = w.reduce((a, x) => a + x, 0), gl = Math.abs(rs.filter(x => x <= 0).reduce((a, x) => a + x, 0));
  return { n, wr: (100 * w.length / n).toFixed(1) + '%', exp: m.toFixed(3), se: (sd / Math.sqrt(n)).toFixed(3),
    pf: gl > 0 ? (gw / gl).toFixed(2) : (gw > 0 ? 'inf' : '-'), sum: s.toFixed(1) };
};
console.log('TRADES closed=' + TR.length + ' open@pute=' + nOpen + ' (jangka: semua-signal, default v8.1)');
console.log('GROSS : ' + JSON.stringify(stats(TR, 0)));
console.log('NET010: ' + JSON.stringify(stats(TR, 0.10)));
console.log('NET020: ' + JSON.stringify(stats(TR, 0.20)));
for (const T of [0.05, 0.075, 0.10, 0.15, 0.20]) {
  const kept = TR.filter(t => 0.10 / t.slPct <= T);
  const skip = TR.filter(t => 0.10 / t.slPct > T);
  const gk = stats(kept, 0), nk = stats(kept, 0.10), gs = skip.length ? stats(skip, 0) : { n: 0 };
  console.log('FEETF' + T.toFixed(3) + ': kept=' + kept.length + '/' + TR.length +
    ' grossKept EXP=' + gk.exp + ' PF=' + gk.pf + ' | net010Kept EXP=' + nk.exp + ' PF=' + nk.pf +
    ' | skippedGross EXP=' + gs.exp + ' (n=' + gs.n + ')');
}
