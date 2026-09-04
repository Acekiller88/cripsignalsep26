# Hand-off: getting the bot live without anyone running commands

GPT (the operator) has no shell, and neither does the developer. The system is
therefore designed so that **the server installs and verifies itself** and
everything else is readable over HTTP. The owner does exactly three things in a
browser; GPT's job shrinks to reading public URLs and relaying what it sees.

## What the owner does (once, ~20 minutes)

### 1. Telegram bot token (2 min)
In Telegram open **@BotFather** → `/newbot` → pick a name and a username ending
in `bot` → copy the token (`123456789:AAF...`). Keep it private.

### 2. Create the server (10 min, Oracle Cloud Always-Free)
1. https://cloud.oracle.com → sign up / sign in. **Home region: Singapore
   (or Tokyo / Frankfurt) – NOT a US region** (Binance blocks US IPs).
2. Menu → **Compute → Instances → Create instance**
   - Image: **Ubuntu 22.04** (or 24.04)
   - Shape: **Ampere → VM.Standard.A1.Flex**, 2 OCPU / 12 GB (Always Free)
   - Networking: create new VCN (default), **assign a public IPv4 address**
   - SSH keys: "No SSH keys" is fine (nothing is done over SSH)
3. **Show advanced options → Management → Initialization script → Paste
   cloud-init script.** Paste the contents of
   https://raw.githubusercontent.com/Acekiller88/cripsignalsep26/arena/01a06815-cripsignalsep26/scripts/cloud-init.sh
   and replace `PASTE_TOKEN_FROM_BOTFATHER_HERE` with the token from step 1.
4. **Create.** Note the public IP shown on the instance page.
5. Open the firewall for the dashboard: instance page → subnet link →
   Security list → **Add ingress rules**: source `0.0.0.0/0`, TCP,
   destination ports `8000` and `8501` (or restrict source to your own IP).

### 3. Telegram channel (2 min)
Create a new channel (private is fine, e.g. "Crypto Signals") → channel
settings → Administrators → **Add administrator** → search your bot → enable
**Post messages**. Within about a minute the bot posts *"Crypto Signal Bot
online"*. No chat id is needed. Optionally open a private chat with the bot and
press **Start** to also receive error alerts there.

That is all. The bot now screens 5 pairs every 15 minutes on Binance testnet,
tracks TP/SL, posts to the channel and serves the dashboard.

## What GPT does (relay only)

Send GPT this message together with the public IP:

```
You are the OPERATOR for the Crypto Signal Bot. You have no shell; you only read
URLs and report. The server is at <PUBLIC_IP>. Read these three URLs and paste
their raw content back to me verbatim (JSON, no summary, mask nothing – they
contain no secrets):

  http://<PUBLIC_IP>:8000/health
  http://<PUBLIC_IP>:8000/api/status
  http://<PUBLIC_IP>:8000/api/performance

Also confirm whether http://<PUBLIC_IP>:8501 loads a dashboard page. If any URL
does not respond, say exactly which one and what error you got.
```

Healthy means: `/health` → `"status":"ok"`, `/api/status` →
`live.cycles_completed ≥ 1`, `live.data_source.source = "binance"`,
`live.telegram.ready = true` with a `channel_id`, `live.last_error = null`.
If `live.telegram.hint` mentions "waiting for a channel", step 3 is missing.

Repeat the same message once a day during the 1–2 week testnet observation;
the developer interprets the numbers and decides on parameter changes.

## Fallbacks

- If GPT's browsing tool cannot fetch plain `http://` URLs, open them yourself
  in any browser and paste the text; they are small JSON documents.
- If cloud-init failed, the instance page → **Console connection → Launch
  Cloud Shell connection** gives a browser terminal; run
  `sudo tail -50 /var/log/crypto-signal-bot-install.log` and paste the output.
- Switching to live market data later (owner approval): Cloud Shell →
  `cd ~/crypto-signal-bot && sed -i 's/^BINANCE_TESTNET=.*/BINANCE_TESTNET=false/' .env && docker compose up -d backend`.
- Updates from the developer: Cloud Shell →
  `cd ~/crypto-signal-bot && git pull && docker compose up -d --build`.
