# MEMORY.md — Memori projek untuk sesi ejen (dikemas kini 12 Sep 2026)

> Fail ini ialah lapisan memori mudah-alih (ilham: amalan unified-memory ECC — Markdown ringkas, recall-sebelum-tulis).
> Ejen: baca fail ini + Roadmap v9 dahulu sebelum kerja. Kemas kini selepas keputusan penting.

## 1. Peta sistem (30 saat)
- Produk: `Trading Grid Bot/Sep 2026/GridBot_Signal_v8.html` — dashboard signal crypto satu-fail (HTML+JS, tiada build).
- Aliran: scan 80 pair Binance Spot (`/api/v3/klines`) → enjin SMC (OB/FVG/sweep/displacement/BOS+CHoCH) → gred A+/A/B/C → exit BE+separa → Grid Translator Pionex.
- Validasi: jurnal localStorage + backtest replay walk-forward dalam browser; harness Node di `/home/user/v8test/` (belum dalam repo — lihat G1).
- Dokumen: `Analisis_Repo_GitHub_Cadangan_v7.md` (roadmap 5 fasa), `Cadangan_v9_Roadmap.md` (hala tuju semasa).

## 2. Keputusan kekal (JANGAN UBAH tanpa kebenaran pengguna)
- Endpoint `fetchKlines`, struktur `PAIRS` 80 pair, format rekod jurnal (tambah medan sahaja), `buildGridPlan`, `genDemoCandles`.
- Falsafah backtest: tiada look-ahead, SL disemak dahulu (konservatif), n<30 = belum signifikan.
- Tiada rahsia dalam repo (token Telegram/Pionex masa depan → prompt browser + localStorage sahaja).

## 3. Pengajaran diabadikan (jangan ulang kesilapan)
- **Jangan edit selari fail sama** — dua `edit_file` serentak pada satu fail pernah merosakkan v8 (serpihan duplikat + `</script>` berganda). Gunakan SATU skrip patch atomik (Python + assertion) untuk batch suntingan.
- **P4 (Sep 2026): gate keras "flip segar ≤5 bar" → N≈0.** Median trend ST(10,3) >100 bar; freshness sebagai penalti lembut pun memotong trade untung. Prinsip: penapis keras baru mesti disemak funnel-nya (berapa % langkah lulus) SEBELUM diterima; kekalkan N sihat.
- **P3: pool likuiditi mesti bertapis hingar** — equal H/L perlu ≥2 sentuhan TERPISAH ≥8 candle; jika tidak N runtuh.
- **A+ dalam backtest**: gate derivatif 2/3 dikecualikan bila tiada data (backtest tidak ambil derivatif sejarah) — jika tidak A+ mustahil.
- **Demo deterministik**: `genDemoCandles` seed-ikut-simbol → backtest demo boleh dibanding merentas versi. Baseline v7 demo-80: N=22, WR 32%, EXP −0.05R, PF 0.93 (≈ angka live pengguna!).
- Sandbox Arena disekat dari Binance API → semua ujian melalui Mod Demo + harness Node.

## 4. Pintu pengesahan wajib sebelum PR (ilham: verification-loop ECC)
1. `node --check` ke atas JS yang diekstrak. 2. Unit test (semasa: 22) lulus. 3. Backtest demo ≥20 pair: N>0, tiada NaN, R betul. 4. Ujian jurnal: rekod lama tidak pecah, tiada medan `_` bocor. 5. Semak diff — tiada perubahan luar skop.

## 5. Status & langkah seterusnya
- v8 (P1–P4) siap + PR #2 dibuka (12 Sep 2026). Merit sebenar menunggu backtest live pengguna (sasaran: WR ≥38%, EXP ≥+0.10R, PF ≥1.2, SL <55%, gred tidak terbalik).
- Seterusnya (ikut Roadmap v9): Fasa A (funnel + sesi/regime) → Fasa B (varian exit) → Fasa C/D.
- Harness ujian masih di luar repo (`/home/user/v8test/`) — cadang G1: pindahkan ke `Sep 2026/tests/`.
