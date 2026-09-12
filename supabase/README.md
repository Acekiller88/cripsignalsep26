# Supabase — Cloud Sync (v8.5)

Simpan jurnal, signal, lejar paper-trade & larian Tune Lab dalam database kekal.
Tanpa setup ini dashboard kekal berfungsi 100% (mod local sahaja).

## Setup sekali (~10 minit)

1. Buka **supabase.com** → daftar/log masuk → **New project**
   - Nama: `gridsignal` · Region: **Singapore** (paling dekat) · Plan: Free
2. Tunggu projek siap (~1 minit) → menu **SQL Editor** → **New query**
3. Tampal keseluruhan `supabase/schema.sql` → **Run** (mesti SUCCESS, 5 jadual)
4. Menu **Project Settings → API** → salin:
   - **Project URL** (`https://xxx.supabase.co`)
   - **anon public key** (`eyJ…` panjang)
5. Dalam dashboard GridBot → seksyen **☁ CLOUD SYNC** → tampal URL + key → **🔗 Sambung**
   - Pil header bertukar **Cloud: ON** · badge seksyen tunjuk projek
6. Jalankan **SCAN** → semak dalam Supabase **Table Editor**: `signals`, `journal_trades`, `paper_trades` mula berisi.

## Cara ia berfungsi

- Setiap signal baharu → baris `signals` + `journal_trades` + buka paper trade.
- Bila signal selesai (TP/SL/BE/luput) → jurnal & paper dikemas kini (gross R, fee USD, **net R**).
- Buka dashboard di peranti lain + Sambung → rekod cloud digabung automatik (rekod selesai menang).
- Gagal/offline → senyap fallback ke local; tiada data hilang.

## Troubleshoot

| Simptom | Punca / ubat |
|---|---|
| `Pustaka Supabase belum dimuat` | CDN disekat (adblock/offline) — benarkan `cdn.jsdelivr.net` |
| `Gagal sambung: 401` | Anon key salah — salin semula dari Settings → API |
| `permission denied` / jadual kosong | Skema belum dijalankan — ulang langkah 2–3 |
| Data lama tidak muncul | Projek free **auto-pause** jika lama tidak aktif — buka Supabase → **Unpause** (data kekal) |

## Keselamatan

Polisi RLS dalam `schema.sql` membenarkan kunci anon baca/tulis (sesuai dashboard peribadi).
**Jangan kongsi URL dashboard + key kepada umum.** Perlindungan Auth penuh = Fasa 2.
