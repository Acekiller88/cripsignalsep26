# Deployment guide – Oracle Cloud (Always Free) + Docker

This guide takes a fresh Oracle Cloud account to a 24/7 running signal bot with
dashboard, backups and monitoring. It also applies to any Ubuntu VPS
(Hetzner, DigitalOcean, AWS Lightsail …) – skip the Oracle-specific parts.

---

## 1. Create the VM

1. Oracle Cloud Console → **Compute → Instances → Create instance**
2. Image: **Canonical Ubuntu 22.04** (or 24.04)
3. Shape: **Ampere A1 Flex** (Always Free: up to 4 OCPU / 24 GB) – choose e.g. 2 OCPU / 12 GB.
   `VM.Standard.E2.1.Micro` (1 GB) also works but is tight; the stack uses ~700 MB RAM.
4. Networking: create/select a VCN with a public subnet, **assign a public IPv4**.
5. Add your SSH public key, create the instance and note the public IP.

> Ampere A1 is ARM64. All images used here (`python:3.11-slim`, `postgres:15-alpine`)
> are multi-arch and the Python wheels (numpy, pandas, psycopg2-binary) ship ARM builds.

## 2. Open the firewall (dashboard + API)

**Oracle security list** (VCN → Subnet → Security list → Ingress rules), add:

| Source | Protocol | Dest. port | Purpose |
|--------|----------|-----------|---------|
| your.ip.addr.0/32 | TCP | 8501 | Dashboard |
| your.ip.addr.0/32 | TCP | 8000 | API (optional) |

Restrict to your own IP where possible – or keep both closed and use an SSH tunnel
(`ssh -L 8501:localhost:8501 ubuntu@<ip>`), which is the safest option.

**Ubuntu iptables** (Oracle images ship with restrictive rules):

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8501 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT
sudo netfilter-persistent save
```

## 3. Install Docker

```bash
sudo apt-get update && sudo apt-get upgrade -y
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker                      # or log out / in
docker --version && docker compose version
```

Optional but recommended on small VMs – swap:

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 4. Deploy

```bash
git clone <your-repo-url> crypto-signal-bot
cd crypto-signal-bot
cp .env.example .env
nano .env
```

Minimum to edit in `.env`:

```
POSTGRES_PASSWORD=<strong random password>
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHANNEL_ID=-100xxxxxxxxxx
BINANCE_TESTNET=true            # start on testnet
ADMIN_TOKEN=<random string>     # protects the admin endpoints
```

Start the stack:

```bash
docker compose up -d --build
docker compose ps                # wait until all three are "healthy"/"running"
docker compose logs -f backend   # Ctrl-C to stop following
```

You should see:

```
🚀 Crypto Signal Bot v1.0.0 started — 5 pairs, 15m timeframe, source=binance
Loaded 5xx Binance futures markets from https://testnet.binancefuture.com/fapi/v1
WebSocket streams started for BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, DOGEUSDT (15m)
──── Screening cycle #1 started (15m) ────
BTCUSDT close=... rsi=... | L0 S1 (conditions_not_met)
...
Next screening cycle in 612s (at 12:15:08 UTC)
```

and a "bot online" message in your Telegram channel.

Verify:

```bash
curl -s localhost:8000/health
docker compose exec backend python main.py --check     # DB + exchange + Telegram test message
```

Open `http://<public-ip>:8501` for the dashboard.

## 5. Auto-restart & 24/7 operation

- All services use `restart: unless-stopped` → they come back after crashes and reboots
  (the Docker daemon is enabled at boot by the install script).
- Each container has a **health check**; `docker compose ps` shows `(healthy)`.
  The backend health check fails when the screening loop has not completed for
  > 3 candles, so a stuck bot becomes visible.
- The bot itself reconnects WebSockets with back-off, retries REST calls, and never
  lets a Telegram failure stop signal generation.

Optional watchdog that restarts unhealthy containers automatically:

```bash
docker run -d --name autoheal --restart=always \
  -e AUTOHEAL_CONTAINER_LABEL=all \
  -v /var/run/docker.sock:/var/run/docker.sock willfarrell/autoheal
```

## 6. Backups

Daily PostgreSQL dump, keep 14 days:

```bash
mkdir -p ~/backups
( crontab -l 2>/dev/null; echo '15 3 * * * cd $HOME/crypto-signal-bot && docker compose exec -T postgres pg_dump -U crypto_user crypto_signals | gzip > $HOME/backups/crypto_signals_$(date +\%F).sql.gz && find $HOME/backups -name "*.sql.gz" -mtime +14 -delete' ) | crontab -
```

Restore:

```bash
gunzip -c ~/backups/crypto_signals_2026-09-04.sql.gz | docker compose exec -T postgres psql -U crypto_user crypto_signals
```

## 7. Upgrades

```bash
cd ~/crypto-signal-bot
git pull
docker compose up -d --build
docker image prune -f
```

Database schema changes are applied automatically on start (new columns are added).

## 8. HTTPS / reverse proxy (optional)

If you want the dashboard on a domain with TLS, put Caddy in front:

```bash
sudo apt-get install -y caddy
sudo tee /etc/caddy/Caddyfile <<'EOF'
dash.example.com {
    reverse_proxy localhost:8501
    basicauth {
        admin $2a$14$...   # caddy hash-password
    }
}
api.example.com {
    reverse_proxy localhost:8000
}
EOF
sudo systemctl reload caddy
```

Open ports 80/443 in the Oracle security list and iptables, and remove 8501/8000.

## 9. Monitoring

- Telegram: start-up message, every signal / TP / close, daily summary at 00:05 UTC.
- `GET /health` for uptime monitors (UptimeRobot, Better Stack …) – returns 503 when stale.
- Logs: `docker compose logs --since 1h backend` (rotated, max 5 × 20 MB).
- Dashboard header shows heartbeat age, last/next scan, WebSocket state and last error.

## 10. Switching from testnet to live market data

1. Review 1-2 weeks of testnet statistics and a 60-90 day backtest on live history
   (`BINANCE_TESTNET=false python backtest.py --days 90`).
2. In `.env` set `BINANCE_TESTNET=false` (API keys remain optional – the bot only reads
   public market data; it never places orders).
3. `docker compose up -d backend` – the start-up Telegram message now says **LIVE**.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Could not load markets` / `NetworkError` on start | VM has no outbound access to `fapi.binance.com` / `testnet.binancefuture.com`. Check DNS/egress rules. The bot keeps retrying; use `DATA_SOURCE=synthetic` to test everything else. |
| Telegram `Chat not found` | Bot is not an admin of the channel, or the id is missing the `-100` prefix. |
| Telegram `Forbidden` | Bot was removed from the channel / token revoked. |
| Dashboard "NO HEARTBEAT" | Backend not running or pointing at a different database. `docker compose logs backend`. |
| `/health` returns 503 `stale` | Screening loop stuck – check logs, `docker compose restart backend`. |
| Testnet candles look odd | Testnet is thinly traded; for realistic signals use live market data (read-only). |
| Container keeps restarting on 1 GB VM | Add swap (section 3) or use a 2 GB+ shape. |
