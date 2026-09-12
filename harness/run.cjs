// Harness: muatkan <script> dari fail HTML GridBot ke dalam Node dengan stub browser.
// Guna: node run.cjs <path-html> <backtest|unit|extract> [skop]
const fs = require('fs');
const htmlPath = process.argv[2];
const mode = process.argv[3] || 'backtest';
const scopeArg = process.argv[4] || '20';
if (!htmlPath) { console.error('Guna: node run.cjs <html> <backtest|unit|extract> [skop]'); process.exit(1); }

// ---------- Stub browser minimum ----------
function makeEl(id) {
  return {
    id, value: '', checked: false, textContent: '', innerHTML: '',
    className: '', disabled: false, style: {}, _h: null,
    classList: { add() {}, remove() {}, toggle() {} }
  };
}
const __els = {};
global.document = {
  getElementById: (id) => __els[id] || (__els[id] = makeEl(id)),
  createElement: () => ({ click() {}, href: '', download: '' })
};
const __store = {};
global.localStorage = {
  getItem: (k) => (__store[k] ?? null),
  setItem: (k, v) => { __store[k] = String(v); },
  removeItem: (k) => { delete __store[k]; }
};
// PIN MASA (kebolehulangan mutlak): demo candle-times & sesi kekal merentas larian/mesin.
const PIN_TS = Date.UTC(2026, 8, 9, 12, 0, 0); // Rab 9 Sep 2026 12:00 UTC
Date.now = () => PIN_TS;
// setInterval wujud dalam Node; driver akan process.exit di hujung.

// ---------- Muat skrip dari HTML ----------
const html = fs.readFileSync(htmlPath, 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) { console.error('FAIL: tiada blok <script> dalam ' + htmlPath); process.exit(1); }
const src = m[1];

if (mode === 'extract') {
  fs.writeFileSync('/home/user/v8test/last.js', src);
  console.log('extract OK: ' + src.length + ' chars -> /home/user/v8test/last.js');
  process.exit(0);
}

let driver = fs.readFileSync('/home/user/v8test/driver_' + mode + '.js', 'utf8');
driver = driver.split('__SCOPE__').join(JSON.stringify(scopeArg));

// Balut dalam async IIFE supaya `await` sah; eval kembalikan promise.
const wrapped = `(async()=>{ ${src} \n;${driver} })()`;
Promise.resolve(eval(wrapped))
  .then(() => process.exit(0))
  .catch((e) => { console.error('DRIVER FAIL:', e && e.stack || e); process.exit(1); });
