# Vercel Serverless Functions (Fasa 2)

Konvensyen (ditetapkan jurubina Arena, diapply operator GPT):

- Fail: `api/<nama>.js` (Node runtime, `module.exports` handler).
- Had hobby: timeout **10s**, cron **2 job / harian sahaja** → kerja berat dilarang.
- Cron routes MESTI semak `Authorization: Bearer <CRON_SECRET>`.
- Rahsia dari `process.env` (nama dalam `.env.example`). Jangan hardcode.
- Cron didaftar dalam `vercel.json` (`crons` array) oleh jurubina.
- Setiap route baharu: sertakan arahan uji manual (curl) + jangkapan output.
