// Unit v8.5: invarian enjin atas klines SEBENAR (BTC 1H) — TIADA demo.
const FSU = require('fs');
const rows = JSON.parse(FSU.readFileSync('/home/user/v8test/realdata/json/BTC.json', 'utf8'));
const C300 = rows.slice(-600, -300).map(r => ({ time: r[0], open: r[1], high: r[2], low: r[3], close: r[4], volume: r[5] }));
const H4 = [];
{ let cur = null, key = -1;
  for (const r of rows.slice(-1200, -300)) {
    const k = Math.floor(r[0] / 14400000);
    if (k !== key) { if (cur) H4.push(cur); key = k; cur = { time: key * 14400000, open: r[1], high: r[2], low: r[3], close: r[4], volume: r[5] }; }
    else { cur.high = Math.max(cur.high, r[2]); cur.low = Math.min(cur.low, r[3]); cur.close = r[4]; cur.volume += r[5]; }
  }
  if (cur) H4.push(cur);
}
let pass = 0, fail = 0;
const t = (n, c) => { if (c) pass++; else { fail++; console.log('FAIL: ' + n); } };
// 1) pengawal input
t('null->null', analyzeCandles(null, H4, 70) === null);
t('pendek->null', analyzeCandles(C300.slice(0, 100), H4, 70) === null);
// 2) analisis penuh atas data real: tiada NaN
const R = analyzeCandles(C300, H4, 70, C300[C300.length - 1].time);
t('objek', !!R && typeof R === 'object');
t('tiada-NaN', R && [R.rsiVal, R.adxVal, R.atrVal, R.close, R.entry, R.longProb, R.shortProb].every(v => v == null || (typeof v === 'number' && isFinite(v))));
t('prob-bounds', R && R.longProb >= 10 && R.longProb <= 92 && R.shortProb >= 10 && R.shortProb <= 92);
t('sl-tp-long', R && R.longSL < R.entry && R.longTP1 > R.entry && R.longTP2 > R.entry*0.998);
t('sl-tp-short', R && R.shortSL > R.entry && R.shortTP1 < R.entry && R.shortTP2 < R.entry*1.002);
t('rr2R', R && R.longRR >= 2.0 && R.shortRR >= 2.0);
t('sesi-real', R && typeof R.sessionCtx.session === 'string' && R.sessionCtx.utcH >= 0 && R.sessionCtx.utcH < 24);
// 3) matematik exit engine (deterministik)
const mk = (dir) => ({ dir, entry: 100, sl: dir === 'LONG' ? 99 : 101, tp1: dir === 'LONG' ? 102 : 98, tp2: dir === 'LONG' ? 103.5 : 96.5 });
{ const tr = mk('LONG'); v8InitExit(tr);
  t('R-tpR', Math.abs(tr._R - 1) < 1e-9 && Math.abs(tr._tp1R - 2) < 1e-9 && Math.abs(tr._tp2R - 3.5) < 1e-9);
  const s1 = v8StepExit(tr, { high: 100.2, low: 98.9 }); t('SL', s1 && s1.status === 'SL' && s1.rMult === -1); }
{ const tr = mk('LONG'); v8InitExit(tr);
  const a = v8StepExit(tr, { high: 101.2, low: 99.5 }); t('arm-tiada-res', a === null && tr._beArmed === true);
  const b = v8StepExit(tr, { high: 100.5, low: 99.8 }); t('BE', b && b.status === 'BE' && b.rMult === 0); }
{ const tr = mk('LONG'); v8InitExit(tr);
  v8StepExit(tr, { high: 102.3, low: 100.5 }); t('partial-arm', tr._partial === true);
  const b = v8StepExit(tr, { high: 101.5, low: 99.7 }); t('TP1+BE', b && b.status === 'TP1+BE' && b.rMult === 1.0); }
{ const tr = mk('LONG'); v8InitExit(tr);
  v8StepExit(tr, { high: 102.3, low: 100.5 });
  const b = v8StepExit(tr, { high: 103.8, low: 102.0 }); t('TP1+TP2', b && b.status === 'TP1+TP2' && b.rMult === 2.75); }
{ const tr = mk('SHORT'); v8InitExit(tr);
  const s1 = v8StepExit(tr, { high: 101.2, low: 100.0 }); t('SL-short', s1 && s1.status === 'SL' && s1.rMult === -1); }
// 4) gred / regime / sesi / grid / HTF / derivatif
{ const q = aplusFilter({ htfAligned: true, liquiditySweep: true, displacementOk: true, smcOB: true, smcFVG: true, bos: true, zoneOk: true }, null);
  t('Aplus-penuh', q.isAplus && Math.abs(q.wScore - 8.5) < 1e-9);
  const q0 = aplusFilter({}, null); t('gred-kosong', q0.wScore === 0 && !q0.isB); }
t('reg-chaos', detectRegime(50, 0.2).regime === 'VOLATILE_CHAOS' && !detectRegime(50, 0.2).tradeable);
t('reg-exp', detectRegime(30, 0.1).regime === 'TREND_EXPANSION');
t('reg-null', detectRegime(null, null).regime === 'NEUTRAL');
t('sesi-overlap', getSessionCtx(new Date(Date.UTC(2026, 0, 1, 14))).session === 'NY/LDN OVERLAP');
t('sesi-asia', getSessionCtx(new Date(Date.UTC(2026, 0, 1, 3))).session === 'ASIA');
{ const gp = buildGridPlan('LONG', 100, 1, 99, 103.5, 'TREND_EXPANSION');
  t('grid-ok', gp && gp.grids >= 5 && gp.grids <= 60 && gp.spacing > 0.2 && gp.lev === 3);
  t('grid-null', buildGridPlan('LONG', 100, 1, 104, 103, 'NEUTRAL') === null); }
{ const h = analyzeHTF(H4); t('htf-obj', h && typeof h.htfBull === 'boolean');
  const hn = analyzeHTF([]); t('htf-neutral', hn.htfNeutral === true); }
{ const e = scoreDerivatives({ funding: 0.5, oiChg: 1, takerRatio: 1.1, ok: true }, 'LONG'); t('deriv-extreme', e.extreme === true);
  const z = scoreDerivatives(null, 'LONG'); t('deriv-null', z.score === 0 && z.max === 0); }
// 5) RSI deterministik
{ const up = Array.from({ length: 30 }, (_, i) => 100 + i); t('rsi-100', calcRSI(up, 14)[29] === 100);
  const dn = Array.from({ length: 30 }, (_, i) => 100 - i); t('rsi-0', calcRSI(dn, 14)[29] === 0); }

// 6) v8.4: FGI parse + kalibrasi + pecahan kad
t('fgi-parse', JSON.stringify(parseFGI({data:[{value:'62',value_classification:'Greed'}]}))==='{"value":62,"label":"Greed"}');
t('fgi-null', parseFGI(null)===null&&parseFGI({})===null&&parseFGI({data:[{value:'xx'}]})===null);
{ const cal=jCalib([
    {status:'TP1+BE',prob:75,rMult:1.0},{status:'SL',prob:72,rMult:-1},{status:'BE',prob:62,rMult:0},
    {status:'OPEN',prob:90,rMult:null},{status:'TP1+TP2',prob:85,rMult:2.75}]);
  const b70=cal.find(c=>c.lbl==='70–79');
  t('calib-70', b70.n===2&&b70.wr===50&&b70.sumR===0);
  t('calib-80', cal.find(c=>c.lbl==='80+').n===1&&cal.find(c=>c.lbl==='80+').wr===100);
  t('calib-closed4', cal.reduce((s,c)=>s+c.n,0)===4); }
{ let card=null;
  const mk4h=(arr)=>{const o=[];let c=null,k=-1;for(const r of arr){const kk=Math.floor(r[0]/14400000);if(kk!==k){if(c)o.push(c);k=kk;c={time:k*14400000,open:r[1],high:r[2],low:r[3],close:r[4],volume:r[5]};}else{c.high=Math.max(c.high,r[2]);c.low=Math.min(c.low,r[3]);c.close=r[4];c.volume+=r[5];}}if(c)o.push(c);return o;};
  for(let e=2900;e<=40000&&!card;e+=25){
    const win=rows.slice(e-300,e).map(r=>({time:r[0],open:r[1],high:r[2],low:r[3],close:r[4],volume:r[5]}));
    const rr=analyzeCandles(win,mk4h(rows.slice(e-2900,e)),70,win[win.length-1].time);
    if(rr&&rr.direction&&rr.grade)card=buildCard('BTCUSDT',rr,1);
  }
  t('card-found', !!card);
  t('card-breakdown', card&&card.includes('Keyakinan')&&card.includes('asas 30'));
  t('card-invalidation', card&&card.includes('Invalidasi'));
}

// 7) v8.5: baris cloud + matematik paper
{ const rec={id:'1-BTCUSDT',ts:1726000000000,sym:'BTCUSDT',tf:'1h',dir:'LONG',grade:'A',prob:75,entry:100,sl:98,tp1:103,tp2:106,regime:'TREND',session:'NY',fgi:62};
  const sr=sbSignalRow(rec);
  t('sb-sig', sr.sym==='BTCUSDT'&&sr.entry===100&&sr.fgi===62&&sr.ts.slice(0,4)==='2024');
  t('sb-trade', sbTradeRow({id:'x'}).id==='x'&&sbTradeRow({id:'x'}).row.id==='x');
  const po=paperOpenRow(rec,5);
  t('paper-open', po.notion===500&&po.fee_usd===0.5&&po.risk_usd===10);
  const pc=paperCloseRow(po,1);
  t('paper-close', pc.status==='CLOSED'&&pc.net_r===0.95);
  const ps=paperStats([{status:'CLOSED',exit_gross_r:1,net_r:0.95,fee_usd:0.5},{status:'CLOSED',exit_gross_r:-1,net_r:-1.05,fee_usd:0.5},{status:'OPEN'}]);
  t('paper-stats', ps.closed===2&&ps.grossR===0&&ps.netR===-0.1&&ps.feesUsd===1);
  const tr=sbTuneRow({ts:1726000000000,mode:'rawak',seed:7,budget:4,scope:10,hypo:'h',verdict:'v',winner:null,winnerHold:null,trials:[],baseline:{}});
  t('sb-tune', tr.mode==='rawak'&&tr.seed===7&&tr.hypo==='h');
  sbInit();
  t('sb-offline', SB.ready===false);
}
console.log('UNIT v8.5 SELESAI pass=' + pass + ' fail=' + fail);
if (fail) throw new Error(fail + ' ujian gagal');
