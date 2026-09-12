# Edge Functions (Fasa 2)

Konvensyen (ditetapkan jurubina Arena, diapply operator GPT):

- Satu folder satu function: `supabase/functions/<nama>/index.ts` (Deno).
- MESTI muat timeout **30s** → kerja ringan sahaja (cth: scan ≤10 pair).
- Auth: semak secret header (`x-cron-secret` = `CRON_SECRET`), BUKAN JWT pengguna.
- Rahsia dari `Deno.env` (nama dalam `.env.example`). Jangan hardcode.
- Log ringkas: mula/selesai/ralat → pulangkan JSON `{ok, ...}`.
- Setiap function baharu: sertakan `DEPLOY.md` mini (deploy + env + uji manual + cron).
