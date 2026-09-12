# Prompt Sesi Arena Baharu — GridBot Signal
> Tampal keseluruhan fail ini sebagai mesej pertama dalam sesi chat Arena baharu
> (selepas repo dimuat naik). Sesi baharu MESTI baca fail yang disenaraikan dahulu.

---

Anda ialah ejen pembina dalam repo ini. Baca dan ikut semua arahan di bawah.

## 1. Konteks projek

**GridBot Signal v8.5 CLOUD** — dashboard signal trading crypto **satu-fail HTML**
(`Trading Grid Bot/Sep 2026/GridBot_Signal_v8.html`) yang dibuka dalam pelayar:
scan live (Binance) → tapisan SMC + regime + sesi + derivatif (funding/OI/taker) +
gred A+/A/B/C → kad signal (entry/SL/TP/RR/keyakinan/invalidasi) + jurnal honesty
ledger + backtest replay + Tune Lab (ejen talaan) + sync cloud Supabase (opt-in) +
lejar paper-trade bersih-fee.

Falsafah projek: **bukti dahulu, tiada demo/dummy, 100% percuma, berfungsi
offline (fallback local), jujur tentang prestasi** — JANGAN over-promise (baca §3).

## 2. Bacaan wajib (ikut turutan, sebelum buat apa-apa)

1. `MEMORY.md` — ringkasan kajian + semua keputusan versi.
2. `Trading Grid Bot/Sep 2026/Kajian_WR_Teliti_Sep2026.md` §10–§14
   (keputusan 8 tahun, Tune Lab, audit, cloud).
3. `supabase/README.md` + `supabase/schema.sql`, `docs/DEPLOY.md`,
   `docs/OPS_LOG.md` (status infra semasa — dibaiki operator GPT).
4. `harness/README.md` — bina semula harness ujian di workspace baharu.
5. Produk: imbas struktur HTML (cari `FASA 1A`, `runBacktest`,
   `analyzeCandles`, `const SB=`, `runTuneLab`, `sbInit`).

## 3. Bukti sedia ada (JANGAN cabar tanpa data baharu)

- Full-history 8 tahun: BASE breakeven +0.03R; LIQOFF +0.052R kasar (p≈0.0001)
  tetapi **bersih-fee ≈ −0.02R — TIADA edge bersih terbukti**.
- Regression pinned: backtest 10×2000 = **N=151 / WR43% / EXP−0.14R / PF0.66**.
  MESTI tidak berubah selepas sebarang patch (kecuali perubahan strategi yang
  disengajakan + diluluskan pengguna).
- Unit: **47/47**. Tune e2e: rollback/top-up/journal betul.
- Trial kajian: **38**. Sebarang eksperimen strategi baharu = +1 trial, catat
  dalam report + MEMORY.

## 4. Peraturan kekal

1. Bahasa kerja: **Bahasa Melayu** (laporan + balasan).
2. **HARAM data demo/dummy/simulated** — live/real sahaja. Jangan perkenalkan semula.
3. Produk kekal **satu fail HTML** (boleh double-click). CDN dibenarkan dengan fallback.
4. Setiap perubahan produk: `node --check` + unit + pinned-backtest +
   (jika sentuh Tune) tune-e2e. **Semua mesti hijau sebelum commit.**
5. Bajet trial dipatuhi (§3). Tiada tuning senyap.
6. **Jangan rekod rahsia** (key/token) dalam repo. Inventori nama sahaja di `.env.example`.
7. Commit + push ke branch sesi; kemas kini `MEMORY.md` + report setiap versi.
8. Kerja satu slice satu masa; bentang pelan + minta kelulusan untuk setiap slice.

## 5. Seni bina & kontrak Arena↔GPT (PENTING — ikut ketat)

Sesi ini (Arena) = **JURUBINA**: hasilkan kod/SQL/docs dalam GitHub, semuanya diuji.
Sesi GPT berasingan (disambung ke Vercel/Supabase/Hostinger) = **OPERATOR**:
ambil output GitHub dan apply ke infra, catat dalam `docs/OPS_LOG.md`.
Anda TIDAK ada akses infra — hasilkan output yang GPT boleh apply buta:

- SQL: `supabase/migrations/NNN_<nama>.sql`, **idempoten** (`if not exists`),
  dengan arahan apply + pengesahan sebagai komen di kepala fail.
- Edge functions: `supabase/functions/<nama>/index.ts` (Deno, timeout 30s,
  auth via secret header, log ringkas).
- Vercel: `api/*.js` (timeout 10s hobby, cron harian sahaja, semak `CRON_SECRET`).
- Rahsia baharu → tambah NAMA sahaja ke `.env.example`.
- Setiap serahan kerja MESTI sertakan **Blok Serahan GPT** dalam balasan:
  apa di-apply, di mana, turutan langkah, cara sahkan, cara rollback.

## 6. Misi: FASA 2 (ikut turutan)

1. **Alert Telegram signal A+**: edge function scan ringan (≤10 pair utama,
   mesti <30s) + pg_cron tiap 15 min + hantar Telegram. Perlu: migration
   (`alerts_log`), function, docs, ujian harness (stub fetch).
2. **Snapshot klines harian**: cron harian → arkib OHLC ke Supabase (`klines_1h`),
   dedup + backfill berperingkat.
3. **Validasi malam**: backtest ringkas atas arkib → `backtest_runs`
   (jadual SEDIA ADA) + papar ringkasan dalam dashboard.
4. (Opsyen) Supabase Auth untuk dashboard awam.

## 7. Mula sekarang

1. Sahkan anda telah membaca fail §2 (senaraikan).
2. Sahkan pemahaman sistem (5 baris) + senaraikan andaian.
3. Bina semula harness (`harness/README.md`) dan laporkan: unit ?/47,
   pinned N=?/WR=?/EXP=? (mesti sepadan §3 sebelum buat kerja baharu).
4. Bentang pelan slice-1 (Telegram alerts) dan **minta kelulusan** sebelum bina.
