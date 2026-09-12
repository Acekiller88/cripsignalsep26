# Cadangan v9 — Roadmap Penambahbaikan GridBot Signal (v8 → v9)

**Tarikh:** 12 September 2026
**Kaedah:** research-first — kod v8 diteliti dahulu, kemudian fakta luar disahkan dengan jejak bukti (sumber + tarikh). Semua dakwaan luar di bawah ada rujukannya di §2.
**Prinsip:** ukur dahulu sebelum ubah (§Fasa A), satu eksperimen satu backtest, tiada regresi teknikal (N>0, tiada NaN, R betul).

---

## 1. Ringkasan eksekutif — 5 idea berimpak tertinggi

| # | Idea | Jangkaan impak | Usaha |
|---|------|---------------|-------|
| 1 | **Eksperimen varian exit** (BE vs Chandelier/ATR-trail vs structure-trail selepas TP1) — BE di entry membunuh winner yang retrace (kos tersembunyi) | Tinggi (pulih scratched winners) | Sederhana |
| 2 | **Simulator grid dalam backtest** — buktikan P&L grid (caj fee) atas replay, bukan setakat signal | Tinggi (tutup gelung signal→grid) | Sederhana–Tinggi |
| 3 | **Jadual statistik mengikut sesi + regime + cap-jari setup** — data untuk talaan berasaskan bukti (meta-labeling lite) | Tinggi (asas semua talaan) | Rendah |
| 4 | **Killzones ICT + penapis pra-scan (spread/volume) + PDH/PDL** — sambung Fasa 2–3 roadmap v7 yang belum siap | Sederhana–Tinggi | Rendah–Sederhana |
| 5 | **Pengawal korelasi portfolio** (had signal serentak searah + penarafan silang funding) — elak 20 LONG serentak ketika BTC crash | Sederhana (kurang drawdown) | Rendah |

---

## 2. Jejak bukti (penyelidikan luar, 12 Sep 2026)

| Dakwaan | Sumber | Tarikh | Implikasi untuk kita |
|---|---|---|---|
| Sweep confirmation +16.4 mata WR vs entry buta; OB bersendirian 43.1% (edge negatif); FVG 64.8% mitigation (intraday FX) | fxnx.com audit SMC | 4 Sep 2026 | Menyokong pemberat P2 (sweep berat, OB ringan) untuk TF intraday |
| Model SMC bertapis (HTF + killzone London/NY + TP 1:2.5 di opposing liquidity): WR 41.2% → 58.4% | fxnx.com | 4 Sep 2026 | Laksanakan killzones (§Fasa C); uji tangga TP 2.5R sebagai varian |
| Daily-bar backtest 4 pasaran: HANYA Order Block mengatasi rawak di semua pasaran; FVG/sweep tiada edge signifikan pada daily | StatOasis | 3 Sep 2026 | Edge komponen bergantung timeframe — wajib sahkan pemberat ikut-TF dengan data sendiri (§Fasa A+E), bukan andaian sejagat |
| Setup bertindan (sweep + discount + OB-dalam-FVG + CHoCH) jauh lebih tinggi WR dari single-confluence | backtrex.com | 16 Jun 2026 | Sokong "cap jari setup" (§Fasa E): rekod kombinasi, bukan kiraan |
| Funding-rate changes menerangkan 12.5% variasi harga 7-hari (lemah, p signifikan); lebih berguna **keratan-rentas** pelbagai aset | Presto Labs | 2 Ogos 2024 | Funding kekal bonus ringan + blacklist; tambah **ranking silang** (§Fasa C) |
| Funding >0.1%/8j = overheated; OI naik + funding melampau → amaran reversal | Gate Research/wiki | 26 Dis 2025 | Sahkan threshold blacklist 0.1% kita ✓; tambah gabungan OI×funding sebagai amaran (bukan sekadar skor) |
| Scaling-out (separa TP) menaikkan nominal WR, stabilkan equity curve; lebih efektif di crypto (mean-reversion + wick) | quantstrategy.io | 28 Feb 2026 | Sahkan P1 ✓ — teruskan separa-TP1 |
| **BE stop di entry membunuh winner**: entry ialah anchor, bukan paras — pasaran retrace melaluinya secara rutin; ganti dengan trail ATR/structure; "backtest 3 varian exit, biar expectancy putuskan" | arrowalgo.com | 9 Sep 2026 | **Idea #1**: uji BE vs Chandelier vs structure-trail dalam backtest kita sendiri |
| Spacing grid optimum BTC: 1% → 1.8% bersih, 0.5% → 1.76%, 0.25% → 1.33%; saran 0.5–1% ikut volatiliti; spacing mesti tewaskan fee | Gainium | 29 Jan 2025 | Sahkan peraturan 2×fee kita ✓; tambah mod geometri + jadual ikut-regime (§Fasa D) |
| Grid gagal dalam trend kuat satu arah; guna S/R & julat terkini; 5–15 grid permulaan; SL wajib | Bitsgap | 12 Jun 2026 | Tambah amaran "julat terlalu sempit/luas" + semak julat vs julat 30-candle (§Fasa D) |
| Spacing ikut keadaan: sideways 1–3%, bull 2–4%, bear 2–5%; julat 15–40%; leverage konservatif | WunderTrading | 20 Mei 2025 | Jadual spacing adaptif-regime dalam Grid Translator (§Fasa D) |
| Position management (DCA/separa/trailing/BE) sebagai warga kelas-pertama dalam backtester | backtest-kit docs | 2026 | Sahkan seni bina Enjin Exit v8 ✓; hala tuju: exit-mode boleh tukar |

> Nota kejujuran: fxnx (pro-SMC intraday) dan StatOasis (skeptikal, daily equity) **bercanggah separa** — pengajaran sebenar: edge mesti disahkan atas **data, TF dan pasaran sendiri**. Itulah rasional Fasa A sebelum sebarang talaan.

---

## 3. Jurang v8 yang dikenal pasti (dari kod + data)

1. **Exit tidak pernah dibandingkan** — BE @+1R andaian baik; tiada bukti ia menewaskan trail alternatif atas data sendiri.
2. **Grid Translator tidak tervalidasi** — parameter grid (range/grid/spacing) tidak pernah disimulasi; P&L grid sebenar tidak diketahui.
3. **Data sedia ada tidak diagregat** — jurnal sudah simpan regime+sesi+MAE/MFE, tetapi tiada paparan mengikut sesi/regime/cap-jari; talaan masih tekaan.
4. **Tiada pengawal portfolio** — 80 pair dinilai bebas; krisis korelasi (semua LONG serentak) tidak dikesan.
5. **Fasa 2–3 roadmap v7 belum habis** — spread/volume pra-tapis, killzones, PDH/PDL, OB skor-volume masih tiada.
6. **A+ payah diukur live** — gate derivatif 2/3; kadar A+ live tidak dipantau; tiada amaran automatik jika gred terbalik semula.
7. **Backtest tiada ralat keyakinan** — EXP/PF titik tunggal; tiada drawdown curve, tiada selang keyakinan walau n kecil.
8. **Tiada time-stop** — modal terperangkap 100 bar (EXPIRE) tanpa sumbangan; kecekapan modal tidak diukur.

---

## 4. Cadangan berfasa

### FASA A — Ukur dahulu (tiada perubahan strategi; 1–2 sesi)
- **A1. Jadual mengikut sesi + regime** (jurnal & backtest): pecahan N/WR/EXP/PF mengikut sesi (Asia/London/NY/Overlap) dan regime. Data sudah wujud — agregat sahaja.
- **A2. Penggera "gred terbalik" automatik**: banding R/trade A+ vs A vs B; jika songsang dengan n≥10 setiap gred → bar amaran + cadangan ("turunkan kepekaan sweep / semak pemberat").
- **A3. Lengkung R + drawdown + CI dalam backtest**: plot equity-R kumulatif (SVG ringan, tiada library), max drawdown (R), selang keyakinan expectancy (bootstrap 1000× dalam JS — murah untuk n<1000).
- **A4. Kadar tapisan (funnel)**: di akhir backtest, lapor berapa calon gugur di setiap pintu (regime/prob/sweep/liq/ADX) — tunjuk pintu mana paling membunuh (pengajaran P4: jangan ulang N=0).
- **Kriteria siap:** semua nombor v8 boleh dihasilkan semula + funnel menjelaskan N semasa.

### FASA B — Eksperimen exit (jangkaan impak terbesar)
- **B1. Mod exit boleh tukar** (dropdown backtest + jurnal hormat tetapan ketika rekod):
  - `BE` (semasa): SL→entry @+1R, 50% @TP1.
  - `CHANDELIER`: selepas TP1, stop = highest-high 22 bar − 3×ATR (LONG); kekal separa-TP1.
  - `STRUCT`: selepas TP1, stop = swing terakhir / OB terdekat (bukan entry).
  - Protokol arrowalgo: jalankan ketiga-tiga atas data sama, pilih via EXP+PF+drawdown, bukan pendapat.
- **B2. Time-stop**: tutup @pasaran jika tiada separa-TP1 dalam 48 bar (parameter boleh tala 24/48/72); ukur putaran modal.
- **B3. Kalibrasi MAE/MFE**: gunakan taburan MAE winner/loser (Fasa A) untuk cadangkan anjakan trigger BE (cth. +0.8R vs +1.2R) — uji sebagai grid kecil 3 nilai.
- **Kriteria siap:** satu mod exit terpilih dengan bukti (EXP/PF/drawdown lebih baik, n≥50).

### FASA C — Entry & penapis (sambung roadmap v7)
- **C1. Killzones ICT** (ganti/.srcsesi umum): London KZ 07–10 UTC, NY KZ 12–16 UTC, overlap bonus; kekal sebagai bonus prob + pecahan sesi (bukan gate keras — pengajaran P4).
- **C2. Pra-tapis universe**: quoteVolume 24j minimum + spread `bookTicker` <0.1% (public API, tiada key) — bunuh sweep palsu pair nipis.
- **C3. PDH/PDL/PWH/PWL**: high/low semalam & minggu lepas sebagai magnet TP (sertai pool P3) + pin "premium/discount harian".
- **C4. Ranking funding silang**: setiap scan, ranking funding 80 pair; bonus kontrarian untuk LONG funding-terendah / SHORT funding-tertinggi (1–2 mata) — guna data sedia ada.
- **C5. Gabungan amaran OI×funding**: OI naik + funding melampau = amaran reversal (turun gred satu takuk / blacklist lembut), bukan sekadar skor.
- **Kriteria siap:** setiap penapis dibuktikan oleh funnel A4 (bunuh >10% calon DAN menaikkan EXP out-of-sample).

### FASA D — Buktikan grid (tutup gelung signal→bot)
- **D1. Simulator grid dalam backtest**: untuk setiap signal, simulasi fill grid SL→TP2 (bil. grid & spacing dari `buildGridPlan`, tolak fee 0.1% round-trip setiap kitaran) atas candle replay; lapor P&L grid vs P&L signal. Ini jawapan jujur "adakah bot grid untung?".
- **D2. Spacing adaptif-regime + mod geometri**: jadual (SQUEEZE/RANGE 0.5–0.8%, TREND 1.0–1.5%, CHAOS=blacklist kekal) + pilihan geometri untuk pair volatil; amaran julat terlalu sempit/luas vs julat 30-candle.
- **D3. Anggaran modal**: modal-per-grid + pendedahan maksimum atas kad (input modal pilihan, default $1000).
- **Kriteria siap:** ≥60% signal menguntungkan-grid (bersih fee) pada backtest 80-pair; jika tidak, ketatkan julat/spacing, bukan signal.

### FASA E — Meta-labeling lite (Lopez de Prado berperingkat)
- **E1. Cap-jari setup**: rekod bitmask 7 konfluens + regime + sesi setiap trade (jurnal & backtest); jadual WR/EXP mengikut cap-jari (top-10 & bottom-10).
- **E2. Cadangan pemberat automatik**: selepas n≥100, kira WR setiap komponen (sweep/FVG/BOS/...) dan cadangkan anjakan pemberat ±0.25 (paparan sahaja — manusia sahkan).
- **E3. (Jangka panjang)** Model ringan dalam-browser (regresi logistik atas cap-jari, <50KB JS) — hanya jika E1–E2 menunjukkan corak stabil merentas masa.
- **Kriteria siap:** E1 mendedahkan ≥1 cap-jari dengan edge jelas (WR×RR − kos > 0, n≥20).

### FASA F — Automasi & disiplin (roadmap v7 Fasa 5)
- **F1. Telegram push** (manual + auto A+): token via prompt penyemak imbas → localStorage sahaja. **Keselamatan: kunci tidak sesekali dalam fail HTML/repo.**
- **F2. Deploy Pionex** (manual-sah): parameter dari kad → pautan deeplink/API; kekal pengesahan manusia.
- **F3. Pengawal korelasi**: had 5 signal aktif searah serentak (ambil skor tertinggi); papar "portfolio heat" (bil. LONG vs SHORT terbuka); sekat alts melawan BTC HTF (pilihan).
- **F4. Cooldown adaptif**: 4j asas → 12j selepas 2 SL berturut pair sama (data jurnal mengesahkan dahulu).
- **Kriteria siap:** notifikasi hujung-ke-hujung diuji atas demo; tiada rahsia dalam repo (semak `git log -p | grep -i token` kosong).

### FASA G — Infra ujian (ilham ECC: eval-harness + memori dalam repo)
- **G1. Harness Node dalam repo** (`Sep 2026/tests/`): pindahkan `run.cjs` + driver (laluan relatif) supaya sesiapa/ejen boleh `node tests/run.cjs ../GridBot_Signal_vX.html backtest 80`. Pintu wajib sebelum PR: `node --check` + 22 unit + backtest demo N>0.
- **G2. `MEMORY.md`** di root (SUDAH DIBUAT sesi ini): keputusan kekal + pengajaran untuk sesi ejen akan datang.
- **G3. (Pilihan)** GitHub Actions cron: backtest demo mingguan atas Node + amaran jika N=0 / regresi — kos $0, kesan "penjaga malam".

---

## 5. Cadangan susunan mula (vista pelaburan–usaha)

```
Minggu 1:  A1+A4 (funnel + sesi/regime) → faham enjin semasa
Minggu 2:  B1 (3 varian exit) → pilih exit dengan data
Minggu 3:  C1+C2 (killzone + pra-tapis) + D2 (spacing adaptif)
Minggu 4:  D1 (simulator grid) → bukti P&L grid
Bulan 2:   E1+E2 (cap-jari) → talaan automatik cadangan
Bila-bila: F1+F3 (Telegram + korelasi), G1+G3 (harness + CI)
```

**Stop-rule (disiplin anti-overfit):** sebarang peraturan baru mesti (i) diuji atas TF kedua (15m ATAU 4H) sebagai out-of-sample kasar, dan (ii) tidak mengurangkan N melebihi 40% tanpa menggandakan EXP. Pengajaran P4 diabadikan.

---

## 6. Apa yang TIDAK dicadangkan (dan kenapa)

- **Model ML berat / LLM dalam browser** — overkill untuk n≈171; E3 berperingkat dahulu.
- ** ramalan funding dengan siri-masa (DAR/ARIMA)** — bukti (SSRN 2025) menarik tetapi nilai dagangan marginal vs usaha; ranking silang C4 capai 80% manfaat dengan 5% usaha.
- **Grid neutral (non-directional)** — sistem ini signal-arah; grid neutral perlukan enjin julat berasingan. Kekal Long/Short Grid.
- **Leverage >3× / auto-deploy tanpa sah** — risiko akaun; F2 kekal manual-sah.

---

*Disediakan 12 Sep 2026 melalui aliran research-first (kod dahulu, bukti luar kemudian). Bukan nasihat kewangan.*
