# Harness Ujian (Node) — dibina semula di workspace baharu

Harness TIDAK memerlukan pelayar: ia extract `<script>` dari produk, stub
global pelayar minimum (`document`, `localStorage`, `fetchKlines`, dll),
`eval` kod, kemudian jalankan driver ujian. Data = JSON 1H sebenar
(Pennyihui, 8 tahun, 10 pair) — **data TIDAK dalam repo** (terlalu besar).

## Fail

- `run.cjs` — pelancar: `node run.cjs <html> <mod> [args]`
  (`extract` | `unit` | `backtest` | `seenet` | `tune`).
- `driver_unit.js` — 47 assert (indikator, gred, exit, jurnal, FGI, kalibrasi,
  kad-e2e, baris cloud, matematik paper). MESTI 47/47.
- `driver_backtest.js` — pinned regression 10×2000: mesti tepat
  **N=151 / WR43% / EXP−0.14R / PF0.66**.
- `driver_seenet.js` — perakaunan fee sebenar (gross→net).
- `driver_tune.js` — Tune Lab e2e (mod rawak + mod LLM dengan fetch stub).

## Data sebenar (sediakan sekali)

1. Muat turun CSV 1H Pennyihui (10 pair: BTC ETH BNB SOL XRP DOGE ADA TRX AVAX LINK),
   lajur pertama ada BOM (`\ufeffOpen Time`) — strip semasa parse.
2. Tukar kepada `realdata/json/<COIN>.json`: array `[timeMs, open, high, low, close, volume]`.
3. Saiz rujukan: BTC 68331 baris; jumlah ~90MB CSV.
4. Sesuaikan pemalar path `JDIR` dalam setiap driver kepada lokasi data anda.

## Perangkap diketahui (jangan ulang)

- Driver mesti guna `const FSR = require('fs')` (bukan `fs` — bertembung skop run.cjs).
- `Date.now` dipin dalam eval — guna `process.hrtime.bigint()` untuk masa dinding.
- Nama mod MESTI sepadan: `node run.cjs <html> <mod>` → `driver_<mod>.js`.
- Full-history tanpa cap = O(n²) — sentiasa guna cap (≤1000) + HTF binary-search.
- `grep -i demo` pada produk MESTI kosong (dasar sifar-demo).
