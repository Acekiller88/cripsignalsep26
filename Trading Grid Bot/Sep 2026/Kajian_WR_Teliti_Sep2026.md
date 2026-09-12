# Kajian Teliti Win-Rate & Kualiti Signal v8 — Laporan Empirikal

**Tarikh:** 12 September 2026 · **Matlamat:** pastikan sistem mampu hasilkan signal lebih berkualiti dengan WR lebih tinggi.
**Kaedah:** (i) penyelidikan luar 8 topik dengan jejak bukti; (ii) eksperimen terkawal atas harness Node+Mod Demo (masa di-pin — 100% boleh-ulang); (iii) instrumentasi produk (funnel + suis ablasi) untuk pengesahan live.

> ⚠️ **Batasan utama (baca dahulu):** data demo ialah hingar sintetik (N≈6–16/trades) — semua kesimpulan demo ialah **penjanaan hipotesis, BUKAN bukti**. Keputusan muktamad mesti datang dari backtest live pengguna (N≈100+). Jumlah trial demo sesi ini: **19 varian** (termasuk 4 era-P4) — mengikut literatur walk-forward, Sharpe mesti dideflate mengikut bilangan trial; angka demo tidak boleh cited sebagai prestasi jangkaan.

---

## 1. Penemuan penyelidikan luar (baru, ringkasan — trail penuh dalam roadmap v9 §2 + bawah)

| # | Penemuan | Sumber / tarikh | Implikasi |
|---|----------|-----------------|-----------|
| L1 | Overlap EU–US 13–16 UTC = volum/likuiditi tertinggi; Asia 00–09 UTC paling nipis; impak eksekusi terendah 11–13 UTC, tertinggi 00–03 UTC | Changelly 24 Jul 2026; Talos 14 Jan 2026; ScienceDirect 2024 | Sokong pembezaan sesi sedia ada; calon tala: hukum 00–07 UTC lebih keras, bonus 11–16 UTC |
| L2 | BTC: volum rendah sebelum 12 UTC, volatiliti tinggi dari ~14 UTC; pulangan positif signifikan 05, 08, 20 UTC | ScienceDirect 2024 | Sesi BUKAN simetri — mesti diukur ikut-sesi (kini boleh: jadual BYSESS) |
| L3 | Chandelier(22,3) mengatasi trail tetap: PF 1.61 vs 1.28/1.09 (BTC daily); WR 51% vs 38%, expectancy tertinggi, DD terendah | stratbase 4 Mei 2026; volatilitybox 18 Mac 2026 | Hipotesis B1: trail selepas TP1 mungkin menewaskan BE-di-entry — **mesti diuji live** (demo tidak mampu uji: §4) |
| L4 | Stop manual-struktur (PF 1.8) > ATR-trail (1.6) > trail tetap (1.1) | proptradingvibes 29 Mac 2026 | Varian STRUCT dalam eksperimen berpasangan (§4) |
| L5 | 3 trial cukup hasilkan "signifikan" palsu; Sharpe susut 33–44% out-of-sample; kira trial, deflate Sharpe, pra-daftar reka bentuk | pickmytrade 18 Jun 2026; darkbot 2 Sep 2026 | Disiplin kajian ini: bajet trial dilaporkan (§6), reka bentuk pin-masa pra-ditetap |
| L6 | Sweet-spot konsistensi 1–2R; 3R+ perlu trend bersih; padankan RR dengan persekitaran (trend 2R+, chop 1R) | Reddit r/Trading, r/Daytrading 2 Dis 2025 | Hipotesis: TP2 2.5R / regime-adaptif — diuji berpasangan (§4): **tiada bukti demo** |
| L7 | Sweep +16.4 WR, killzone+HTF 41%→58% (intraday FX) vs OB-sahaja survivor (daily equity) — edge bergantung TF | fxnx 4 Sep 2026; StatOasis 3 Sep 2026 | Sahkan pemberat ikut-TF atas data sendiri; jangan andaikan sejagat |

---

## 2. Funnel tapisan (dunia pinned, 80 pair × 140 langkah — kuasa TINGGI, n≈10k)

```
trend 10,872 → blacklist-lepas 10,872 (0% dibunuh) → regime 9,479 (13%)
→ SMC≥B 460 (95%!) → HTF 290 (37%) → prob≥70 216 (26%) → RSI 190 (12%)
→ liq 162 (15%) → ADX 10 (94%!!) → SIGNAL 10
```

- **SMC≥B dan ADX-menaik ialah dua penapis dominan** (masing-masing membunuh >90% calon yang tiba).
- Blacklist membunuh 0% dalam demo (tiada chaos) — dijangka; ia insurans live, bukan penapis harian.
- Kini funnel ini **dipapar dalam produk** setiap backtest (`🔻 Funnel`) — pengguna boleh sahkan corak yang sama atas data live.

## 3. Ablasi penapis entry (pinned, boleh banding — kesan ke atas N berkuasa; EXP lemah n≈6–14)

| Varian | N | WR | EXP | PF | ΔEXP | Verdict |
|---|---|---|---|---|---|---|
| **base v8** | 6 | 17% | +0.13 | 1.38 | — | rujukan |
| minProb 60 | 11 | 9% | −0.11 | 0.69 | −0.24 | ⛔ KEKAL 70 — jalur 60–69 tulen racun (5 trade, ~0 menang) |
| minProb 65 | 6 | 17% | +0.13 | 1.38 | 0 | ═ tiada signal 65–69 (kosong) |
| minProb 75 | 3 | 33% | +0.58 | 2.75 | +0.45 | ❓ uji live — arah positif, n terlalu kecil |
| regimeFilter=all | 9 | 11% | −0.14 | 0.69 | −0.27 | ⛔ KEKAL smart — 3 trade luar-regime rugi −2.1R |
| smcRequired=off | 7 | 14% | −0.04 | 0.92 | −0.17 | ⛔ KEKAL on (bukti lemah, n=1) |
| **ADX gate off** | 13 | 8% | **−0.48** | 0.31 | **−0.61** | ⛔⛔ **KEKAL — bukti paling kuat; 7 trade tanpa-gate hampir semua rugi** |
| liq gate off (cap kekal) | 14 | 64% | +0.28 | 2.98 | +0.15 | ❓ **EKSPERIMEN LIVE #1** — demo kata buang skip, tetapi pool demo ialah hingar (bukan supply sebenar). Cap tanpa skip mungkin betul di kedua-dua dunia — uji dengan suis produk |
| isB ≥3.0 (dari 3.5) | 6 | 17% | +0.13 | 1.38 | 0 | ═ tiada calon di jalur 3.0–3.5 — KEKAL 3.5 |

## 4. Eksperimen exit BERPASANGAN (entries SAMA × 7 varian — reka bentuk bersih)

- **Eksperimen pertama GAGAL** (dilapor jujur): entries longgar (minProb 55, tanpa gate) → 111 entries, majoriti OPEN/MTM → WR 68% palsu. Punca: SL struktur lebar + tiada trend pasca-entry dalam hingar. Diperbaiki: entries berkualiti (fail v8 + minProb 60, N=16) + metrik resolved-sahaja + delta berpasangan.
- Keputusan (16 entries, ~11 resolved):

| Varian | ΔEXP vs base (berpasangan) | better/worse | Verdict |
|---|---|---|---|
| fulltp1 (100% @TP1, tiada runner) | −0.039 | 2/2 | ═ **SERI** — dakwaan awal (+0.50) ialah artifak set-entry berbeza + set-resolved berbeza. **KEKAL runner** selagi tiada bukti live |
| tp25 (TP2 2.5R) | −0.029 | 1/1 | ═ SERI — KEKAL 3.5R+cap |
| be08 (BE @0.8R) | −0.226 | 1/2 | ⛔ BE awal membunuh drifter (+2.2R jadi scratch) — KEKAL 1.0R |
| be12 (BE @1.2R) | +0.090 | 2/2 | ═ seri/hingar — KEKAL 1.0R (lebih data: be08<be10≈be12) |
| **chand** (Chandelier pasca-TP1) | 0.000 | 0/0 | ❓ **TIDAK TERUJI** — 0 penglibatan (hanya 1 trade capai TP1). Mesti uji live |
| **struct** (trail swing pasca-TP1) | −0.042 | 0/1 | ❓ **TIDAK TERUJI** (n=1). Mesti uji live |

- Pengajaran metodologi: banding headline EXP merentas set-resolved berbeza adalah bias (varian pegang-lama nampak teruk: realisasi rugi, tangguh menang). **Delta berpasangan ialah pembanding sah** — diguna pakai untuk semua eksperimen exit akan datang.

## 5. Atribusi awal (n=6 — penerokaan sahaja, BUKAN bukti)

- Sweep YA (n=3, +0.58) vs TIDAK (n=3, −0.33) — selari pemberat P2 ✓ (lemah).
- Gred A (+0.58, n=3) > B (−0.33, n=3) — susunan betul ✓ (lemah).
- Kalibrasi: prob 75–79 (+0.58) > 70–74 (−0.33) — prob membezakan ✓ (lemah).
- Sesi NY (+1.8R, n=4) membawa; tiada trade Asia langsung (bonus −10 menyekat) — selari L1 ✓.
- Regime: hanya SQUEEZE+NEUTRAL berdagang; TREND_* sifar trade dalam demo — perhatian live (funnel akan tunjuk).
- SL mati dengan MFE 0.4R (tidak sampai +1R) — tiada exit boleh selamatkan; ini masalah ENTRY, bukan exit.
- 4 trade BE (MFE 1.0–1.5R) diselamatkan dari SL ✓ — BE berfungsi seperti direka.

## 6. Keputusan: KEKAL / UJI LIVE / JANGAN

> ⛔ SEKSYEN INI SUPERSEDED oleh §10 (data real 8 tahun, N≤4687). Jadual bawah dikekalkan sebagai rekod era-demo sahaja.

| Status | Item |
|---|---|
| ✅ KEKAL (bukti demo kukuh + teori) | Gate ADX-menaik · regime-smart · minProb 70 · SMC-required · BE@1.0R (bukan 0.8) · runner separa-TP1 · isB 3.5 |
| 🔬 UJI LIVE (suis/varian sedia) | **(1)** liq-skip ON vs OFF · **(2)** minProb 70 vs 75 · **(3)** Chandelier/STRUCT pasca-TP1 (kod pandu uji sedia, belum dalam produk) · **(4)** TP2 2.5R |
| ⛔ JANGAN (bukti negatif) | Longgar minProb ke 60 · regime=all · BE@0.8R · bunuh runner tanpa bukti · gate freshness keras (pengajaran P4) |

## 7. Tindakan live untuk pengguna (30 minit, 4 backtest 80-pair 1H)

1. **Base**: suis ON semua → catat N/WR/EXP/PF + funnel + BYSESS/BYREG (rujukan).
2. **Matikan Tapisan likuiditi P3** (suis) → jika EXP↑ dan N↑ dengan WR kekal: pertimbang cap-tanpa-skip kekal.
3. **Matikan Gate ADX P4** (suis) → jangkaan: N↑, EXP↓ (sahkan demo). Jika sebaliknya — lapor, kejutan besar.
4. **Prob.Min 75** (slider) → jika EXP/R-trade↑ dengan N≥30: naikkan default ke 72–75.
5. Beri saya 4 set angka + funnel — saya rumuskan keputusan v9 dari situ.

## 8. Perubahan produk sesi ini (instrumentasi, tingkah laku default bit-identikal)

- Panel backtest: suis `Tapisan likuiditi P3` + `Gate ADX menaik P4` (khusus backtest; live: liq ikut default OFF v8.1, ADX sentiasa ON).
- Paparan `🔻 Funnel` + jadual `PECAHAN SESI & REGIME` setiap backtest; trade ditag sesi+regime ketika entry.
- Ujian v8.2 (TIADA demo): 32/32 unit real-data ✓ · pinned backtest real (default v8.2, 10 pair × 2000 candle): N=151/WR43%/EXP−0.14R/PF0.66 ✓ · seenet N=465 kasar+0.019/bersih−0.049 ✓ · jurnal ✓. (Angka demo era-lalu tidak terpakai — kod demo dipadam, §11.)
- Metodologi: harness pin-masa (Rabu 9 Sep 2026 12:00 UTC) — semua angka kajian boleh-ulang merentas larian/mesin.
- v8.1 (data real §10): skip TP2-room OFF default (`liqGateOn=false`, kotak backtest tidak-checked, cap TP2 kekal). Demo-default kini N=14/EXP+0.28 (angka suis-OFF yang telah disahkan); pinned gates-ON eksplisit kekal N=6/+0.13.

## 9. Seterusnya (cadangan)

1. ~~Tunggu 4 angka live (§7)~~ — SELESAI in-sandbox: §10 (data real 8thn) menggantikan keperluan 4 backtest manual. Paper-trade live MASIH disyorkan sebelum wang sebenar (fee + slippage + regime semasa).
2. Jika live mengesahkan: implementasi B1 (dropdown mod exit: BE/Chandelier/STRUCT) + D1 (simulator grid) sebagai v9.
3. Jangka panjang: penjana senario ground-truth dalam harness (recall/precision vs setup berskrip — ditangguh: risiko circularity, kos bina tinggi).
4. Keutamaan baharu (dari §10.6): (a) penapis fee-aware (skip trade feeR>ambang — TETAPI trade ketat ialah pembawa edge, perlu ujian); (b) simulator grid D1 (P&L grid sebenar tidak dimodelkan backtest directional); (c) pengesahan live corak NEUTRAL-regime.

## 10. Pengesahan data sebenar — Binance 1H 2017–2025 (10 pair, 585k candle) ✅ SUPERSEDES §2–§6

**Sumber**: klines spot Binance 1H sebenar (cermin GitHub Pennyihui/data — sandbox menyekat semua API exchange di peringkat TLS; data ditarik melalui API GitHub yang dibenarkan, sifar-kos konteks). Pair: BTC ETH BNB SOL XRP ADA DOGE LINK AVAX LTC. Jangka: BTC/ETH Ogos 2017 → Jun 2025 (8 tahun); pair lain lebih pendek mengikut penyenaraian.

**Kaedah**: `runBacktest()` / `v8StepExit()` / `analyzeCandles()` produk asal — HANYA `genDemoCandles()` di-override kepada klines sebenar (harness `driver_real.js`, luar repo). HTF 4H = resample strict (hanya block TUTUP dimasukkan, tiada look-ahead). Derivatif neutral (sama seperti backtest demo — funding/OI/taker tidak boleh diuji atas klines). Tiada fee/slippage dalam enjin (analisis fee berasingan, §10.6). Tetingkap utama: 6000 candle (~8 bulan, Okt 24–Jun 25); pengesahan: full-history dengan cap hirisan 1000 (divalidasi: N=224 vs 226 tanpa-cap, verdicts sama, 3× laju — full-history tanpa-cap dianggar 5+ jam O(n²), dibatalkan).

**Bajet trial**: 19 (demo) + 11 backtest real-8bln + 1 exit-berpasangan real + 4 full-history + 1 validasi-cap + 1 analisis-fee + 1 fee-net = **38**.

### 10.1 Jadual ablasi (tetingkap 8 bulan, len=6000)

| Konfig | N | WR | EXP (95% CI hampiran) | PF | Nota |
|---|---|---|---|---|---|
| BASE | 226 | 24% | −0.04 [−0.20,+0.12] | 0.93 | rujukan |
| ADX-off | 447 | 23% | −0.05 [−0.17,+0.06] | 0.90 | N×2, EXP sama → KEKAL gate (jimat fee/masa) |
| LIQ-off (skip TP2-room) | 465 | **48%** | +0.02 [−0.12,+0.16] | 1.05 | WR×2; calon → disahkan §10.2 |
| P75 | 111 | 26% | +0.05 [−0.17,+0.28] | 1.11 | terbaik single 8bln — TETAPI full-history menolak |
| P60 | 333 | 26% | +0.01 [−0.12,+0.14] | 1.02 | tiada gain |
| SMC-off | 268 | 26% | +0.03 [−0.12,+0.18] | 1.06 | lean+ tidak signifikan → KEKAL required |
| REG-all | 316 | 26% | +0.00 [−0.13,+0.14] | 1.00 | RANGE +18.2R/112 — full-history MENTERBALIKKAN |
| REG-trend | 25 | 12% | −0.41 [−0.83,+0.01] | 0.40 | trend-only teruk (tetingkap ini; 8thn: +0.13R — tidak stabil) |
| BASE-recent (3.5 bln terkini) | 113 | 16% | **−0.24 [−0.45,−0.04]** | 0.59 | satu-satunya CI yang eksklusif-0 — semasa negatif |
| LIQ-off+P75 | 240 | 49% | +0.10 [−0.10,+0.29] | 1.26 | terbaik 8bln — full-history: P75 tambah TIADA |
| LIQ-off+REG-all | 612 | 47% | +0.02 [−0.10,+0.14] | 1.04 | REG-all tambah tiada |

### 10.2 Full-history (8 tahun) — pengesahan muktamad

| Konfig | N | WR | EXP (95% CI) | PF | Keputusan |
|---|---|---|---|---|---|
| BASE | 2120 | 26% | +0.03 [−0.03,+0.09] | 1.06 | **tiada edge** (termasuk 0; fee membunuh) |
| LIQ-off | 4687 | **51%** | **+0.052 [+0.025,+0.079]** | 1.14 | **edge kecil SIGNIFIKAN** (t≈3.8, p≈0.0001); 9/10 pair + |
| LIQ-off+P75 | 2659 | 50% | +0.05 [−0.01,+0.11] | 1.12 | P75 tambah TIADA → kekal minProb 70 |
| REG-all | 2878 | 25% | +0.00 | 1.00 | RANGE −20.4R/915, REVERSAL −15.6R/45 → **regime-smart DIBENARKAN** |

Mekanisme edge LIQ-off: trade yang disekat gate (= SL ketat / pool TP2 dekat) mempunyai kadar-hit TP1 tinggi; enjin exit (50% @TP1 + BE) memonetize mereka. Set LIQ-off: 66% TP2-tercap, median TP2R 1.54, purata trade status-TP2 hanya +0.80R — kemenangan kecil berfrekuensi tinggi, varians rendah (sebab ia signifikan). Anggaran: trade tambahan (bukan-liqOk) ≈ +0.07R setiap satu (hampiran — perbezaan occupancy satu-trade-per-pair).

### 10.3 Corak 8-bulan yang TUMBANG atas 8 tahun (pelajaran overfit)

- **Sesi**: London +0.22R/trade & NY −0.27R (8bln, konsisten 7/7!) → semua sesi ≈ 0 atas 8thn (London+Overlap +0.06 post-hoc, NY ≈ 0). Konsistensi merentas konfig TIDAK melindungi daripada overfit tetingkap (set bertindih). **JANGAN implementasi penapis sesi.**
- **Pair**: LINK paling teruk 6/7 (8bln) → LINK TERBAIK atas 8thn (+39.8R base, +58.5R liqoff). BTC paling konsisten (+ kedua-dua tetingkap) tetapi lemah. **JANGAN pilih pair.**
- **Regime**: RANGE +18.2R (8bln) → −20.4R (8thn); TREND_EXPANSION − (8bln) → +0.13R (8thn). **Regime-smart dikekalkan.**
- **Gred A**: kalah 3/3 full-history + 6/7 8bln (cth −65.1R/625) — **A tidak meramal untung; B ≥ A.** A+ jarang (~2% signal) tetapi tidak pernah negatif 4/4 (suggestive: +1.4/+11.2/+0.7/+15.5R — sampel kecil bertindih, bukan bukti).
- **NEUTRAL**: +0.08–0.10R dalam 4/4 lensa (+68.7/+82.2/+52.3/+118.2R) — corak terkuat tetapi post-hoc & set bertindih → **perlu pengesahan live**, JANGAN implementasi lagi.
- **P75**: terbaik 8bln (+0.10) → tiada nilai tambah atas 8thn. Kemenangan pemilihan (best-of-11) — DSR rendah seperti yang diramal teori walk-forward (§1).

### 10.4 Exit berpasangan REAL (N=334 entries, ~330 selesai — BERKUASA,esahkan/betulkan demo N=16)

| Varian | Δ vs base | better/worse | Verdict |
|---|---|---|---|
| fulltp1 (bunuh runner) | −0.005 | 31/54 | TIE → **kekal runner** (sah demo) |
| tp25 (TP2 2.5R) | −0.015 | 12/44 | TIE → **kekal 3.5R+cap** (sah demo) |
| be08 (BE@0.8R) | +0.019 | 18/7 | TIE/lean+ → verdict demo WORSE (N=16) **DITARIK BALIK**; kekal 1.0 (tidak signifikan) |
| be12 (BE@1.2R) | −0.021 | 3/13 | lean− → kekal 1.0 |
| chand/struct (trail pasca-TP1) | −0.047 | 0/11 | **WORSE** (sign-test p≈0.0005) TETAPI reka bentuk capped (trail tidak boleh melepasi TP2 tetap — hanya boleh potong runner awal). Trail TANPA-cap belum diuji. |

### 10.5 Perubahan produk v8.1 (satu-satunya, dari bukti signifikan)

1. **Skip TP2-room DIMATIKAN default** (`liqGateOn=false`; cap TP2 KEKAL): live scan + backtest (kotak kini tidak-checked, label dikemas kini).
2. Bukti MENOLAK semua perubahan lain: minProb kekal 70 · regime-smart kekal · ADX kekal · SMC-required kekal · BE@1.0 kekal · runner kekal · tiada penapis sesi/pair/regime.
3. Ujian: 22/22 unit ✓ · `node --check` ✓ · demo pinned (gates-ON eksplisit) N=6/+0.13 ✓ · suis-OFF N=14/+0.28 ✓ (laluan kod sama dengan default baharu — disahkan secara pembinaan).

### 10.6 AMARAN JUJUR: fee & semasa (baca sebelum wang sebenar)

- Analisis fee (n=152 trade real, set liq-off): SL median 1.83% → kos fee **0.055R median (Pionex/futures 0.10% RT)**; 0.11R median (spot 0.20% RT). Edge kasar +0.052R − fee 0.055R ≈ **−0.003R BERSIH** (Pionex) hingga −0.10R (spot tanpa BNB). **Sistem tidak terbukti untung bersih-fee.** Dengan BNB −25%: ≈ −0.006R — breakeven.
- Perakaunan tepat per-trade (susulan, 8bln Okt24–Jun25, N=465, harness `driver_feenet.js`): kasar +0.019 (SE 0.049) → **bersih −0.049 (0.10% RT, PF 0.89) / −0.116 (0.20% RT, PF 0.76)**. Penapis feeR diuji 5 ambang (maks 0.05–0.20R @0.10%): TIADA membaiki bersih (kept-net ≈ −0.04 semua) — trade disingkir (SL ketat) untung kasar +0.05..+0.09R, iaitu penapis membunuh pembawa edge. **Penapis fee DITOLAK.** Implikasi 8thn: +0.052 − ~0.07 ≈ −0.02 bersih (Pionex).
- Tetingkap terkini (Mac–Jun 2025): base −0.24R signifikan; LIQ-off 8bln hanya +0.02. Prestasi semasa MUNGKIN negatif (data berakhir Jul 2025; Sep 2026 tidak diketahui).
- Backtest ini directional-sahaja; P&L grid sebenar (berbilang fill kecil, maker-fee, redeploy) TIDAK dimodelkan — memerlukan simulator grid D1 sebelum sebarang dakwaan ke atas bot grid.
- **Syor operasi**: paper-trade dahulu (rekod jurnal live); saiz kecil; JANGAN sangka edge kasar = untung.

### 10.7 Keputusan akhir (ganti §6)

| Status | Item |
|---|---|
| ✅ KEKAL (bukti real) | ADX-menaik · regime-smart · minProb 70 · SMC-required · BE@1.0R · runner · TP2-3.5R+cap |
| ✅ UBAH (signifikan, dilaksanakan v8.1) | **Skip TP2-room OFF default** — cap TP2 kekal |
| 🔬 PERHATI (suggestive, JANGAN kod) | NEUTRAL-regime lean · London/Overlap lean · A+ sniper-jarang · be08 neutral |
| ⛔ JANGAN (bukti negatif/overfit) | minProb 75 · regime=all · trend-only · trail-capped · penapis feeR · penapis sesi/pair · harap gred A · dakwa untung bersih-fee |

## 11. v8.2 LIVE — pembersihan demo penuh (atas permintaan pengguna)

**Prinsip**: tiada data dummy/demo dalam sistem. `grep -i demo` ke atas produk = kosong.

**Dibuang**: kotak `Mod Demo` · cabang `demoMode` dalam `fetchKlines`/`fetchDerivatives` · `genDemoCandles()` · `genDemoDerivs()` · semua teks berkaitan demo. Tajuk: GRID SIGNAL v8.2.

**Tidak berubah (logik)**: `analyzeCandles`, exit engine, gred, regime, sesi, jurnal, backtest replay — disahkan: seenet pra/pasca purge identikal bit demi bit (N=465, kasar +0.019, bersih −0.049/−0.116).

**SOP data live (PC pengguna, internet biasa)**:
1. Buka fail HTML dalam pelayar → SCAN PASARAN → dashboard tarik klines + derivatif live Binance (3 endpoint ganti automatik; amaran jika rantau disekat → guna VPN).
2. Jurnal merekod signal gred A+/A (ikut penapis) dan menyelesaikannya semasa scan berikutnya (peraturan exit v8).
3. Protections aktif: cooldown 4j/pair, mod defensif selepas 3 SL/24j.

**SOP backtest manual (data sebenar)**:
1. Panel BACKTEST REPLAY → pilih skop pair + TF → JALANKAN → replay walk-forward atas klines live yang baru ditarik (300 LTF + 200 HTF setiap pair), tiada look-ahead, SL disemak dahulu.
2. Baca: N/WR/EXP/PF + funnel + pecahan sesi/regime + MAE/MFE. Sampel <30 = belum signifikan.
3. Suis P3/P4 untuk eksperimen sendiri (default = default live v8.2).

**Harness (pembangun)**: semua driver kini data-sebenar (override `fetchKlines` dengan klines 2017–2025 kerana sandbox sekat exchange): `backtest` (kanonik, AB+cap), `unit` (32), `seenet` (fee-net). Pin-masa dikekalkan untuk kebolehulangan.

---
*Bukan nasihat kewangan. Kajian penerokaan — keputusan strategi memerlukan pengesahan live.*
