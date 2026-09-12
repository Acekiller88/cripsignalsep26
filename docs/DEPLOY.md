# Deploy — Dashboard di Domain Sendiri (v8.5)

## Pilihan A: Vercel (disyorkan — auto-deploy setiap push)

1. Buka **vercel.com** → daftar (boleh guna akaun GitHub) → **Add New → Project**
2. **Import** repo `Acekiller88/cripsignalsep26` → Framework Preset: **Other** → **Deploy**
   - `vercel.json` dalam repo mengarah `/` ke dashboard automatik
3. Buka URL `*.vercel.app` → sahkan dashboard + SCAN berfungsi
4. **Domain sendiri**: Project → **Settings → Domains** → Add domain anda
   - Di **Hostinger → DNS Zone**: tambah rekod
     - `A` `@` → `76.76.21.21`
     - `CNAME` `www` → `cname.vercel-dns.com`
   - Tunggu propagasi (5 min – 24 jam) → Vercel isu HTTPS automatik
5. Selepas ini: setiap push ke branch/deploy = live dalam ~1 minit. Tiada upload manual.

## Pilihan B: Hostinger Shared (manual)

1. **hPanel → File Manager** → `public_html` (atau folder subdomain)
2. Muat naik `GridBot_Signal_v8.html` → **rename** kepada `index.html`
3. Buka domain → sahkan SCAN berfungsi
4. Setiap kemas kini baharu = ulang langkah 2 (ganti fail). Simpan salinan lama sebagai rollback.

## Semakan selepas deploy

- [ ] Dashboard dibuka melalui domain + HTTPS (🔒)
- [ ] SCAN berjalan, kad signal + jurnal muncul
- [ ] Supabase: tampal URL + key → **Cloud: ON** (lihat `supabase/README.md`)
- [ ] Buka dari telefon: Sambung semula → rekod digabung dari cloud

## Rollback

- Vercel: **Deployments** → pilih deploy lama → **Promote to Production**
- Hostinger: muat naik semula salinan `index.html` lama
