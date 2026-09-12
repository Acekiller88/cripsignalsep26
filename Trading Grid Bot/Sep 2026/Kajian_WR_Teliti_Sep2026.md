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

- Panel backtest: suis `Tapisan likuiditi P3` + `Gate ADX menaik P4` (backtest sahaja; live sentiasa ON).
- Paparan `🔻 Funnel` + jadual `PECAHAN SESI & REGIME` setiap backtest; trade ditag sesi+regime ketika entry.
- Ujian: 22/22 unit ✓ · base N=6/EXP+0.13 identikal ✓ · suis-OFF menghasilkan semula angka scratch (N=13/−0.48, N=14/+0.28) ✓ · jurnal ✓.
- Metodologi: harness pin-masa (Rabu 9 Sep 2026 12:00 UTC) — semua angka kajian boleh-ulang merentas larian/mesin.

## 9. Seterusnya (cadangan)

1. Tunggu 4 angka live (§7) sebelum sebarang perubahan strategi — elak overfit ke atas hingar demo (n≈6–16).
2. Jika live mengesahkan: implementasi B1 (dropdown mod exit: BE/Chandelier/STRUCT) + D1 (simulator grid) sebagai v9.
3. Jangka panjang: penjana senario ground-truth dalam harness (recall/precision vs setup berskrip — ditangguh: risiko circularity, kos bina tinggi).

---
*Bukan nasihat kewangan. Kajian penerokaan — keputusan strategi memerlukan pengesahan live.*
