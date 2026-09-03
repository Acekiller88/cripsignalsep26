# Handoff messages for the GPT operator

The owner copies the message for the current phase to GPT verbatim, and copies
GPT's reply (the `===== REPORT =====` block) back to the developer. One phase at
a time. Nothing else is required from the owner.

---

## Message 1 – Phase A: validate on a real machine (no Docker needed)

```
You are the OPERATOR for the "Crypto Trading Signal Bot" project. Another AI (the
developer) wrote the code; you run it on a real machine with internet access and
report back. Read docs/OPERATOR_GUIDE.md in the repo first and follow its ground
rules: run only the commands given, do not edit code, never paste secrets, and
always reply with the full block between "===== REPORT =====" and
"===== END REPORT =====" verbatim (plus the last 40 lines of output if a
command fails before printing a report).

You need a Linux machine (Ubuntu 22.04/24.04, x86_64 or ARM64, >= 2 GB RAM)
with outbound internet. It must NOT be in the USA or another Binance-restricted
jurisdiction (Binance answers HTTP 451 there) – Singapore, Tokyo, Frankfurt,
Amsterdam are fine. An Oracle Cloud Always-Free VM is ideal (see
docs/DEPLOYMENT.md sections 1-3 for the click-path); any VPS works.

Run exactly this:

    git clone -b arena/01a06815-cripsignalsep26 https://github.com/Acekiller88/cripsignalsep26.git crypto-signal-bot
    cd crypto-signal-bot && chmod +x scripts/*.sh
    git log --oneline -1
    BACKTEST_DAYS=60 ./scripts/smoke_local.sh

It takes 3-8 minutes. Reply with:
1. the machine's provider + region + OS + architecture,
2. the output of `git log --oneline -1`,
3. the full REPORT block from smoke_local.sh.
```

## Message 2 – Phase B: Telegram

```
Phase B. Create the Telegram bot and channel, then validate them.

1. In Telegram, talk to @BotFather -> /newbot -> choose a name and a username
   ending in "bot" -> copy the token.
2. Create a NEW channel (private is fine) named e.g. "Crypto Signals".
   Channel settings -> Administrators -> Add administrator -> add your bot,
   enable "Post messages".
3. Post any message in the channel (e.g. "hello").
4. On the machine, in the crypto-signal-bot directory run (token only first,
   it lists the chat id it can see):

       TELEGRAM_BOT_TOKEN='<token>' ./scripts/telegram_test.sh

   then with the id it printed (private channel ids start with -100):

       TELEGRAM_BOT_TOKEN='<token>' TELEGRAM_CHANNEL_ID='<id>' ./scripts/telegram_test.sh

Reply with both REPORT blocks. Mask the token as 123456:***. Keep the token and
the channel id on the machine – you will need them in Phase C. Confirm that the
test message appeared in the channel.
```

## Message 3 – Phase C: deploy 24/7 (testnet)

```
Phase C. Deploy the 24/7 stack on the same machine (installs Docker if missing,
writes .env, builds and starts PostgreSQL + bot + dashboard, verifies).

    cd crypto-signal-bot && git pull
    TELEGRAM_BOT_TOKEN='<token>' TELEGRAM_CHANNEL_ID='<id>' BINANCE_TESTNET=true ./scripts/deploy.sh

If your user was just added to the docker group, the script may ask for sudo
or you may need to log out/in once and re-run it. It takes 5-10 minutes on the
first run (image build).

Then, after 2 minutes:

    ./scripts/verify.sh

Reply with:
1. the REPORT block from deploy.sh and the 3 URLs it prints,
2. the REPORT block from verify.sh,
3. whether the "Crypto Signal Bot online" message arrived in the channel,
4. the public IP (so the owner can open the dashboard), and confirm that ports
   8000/8501 are open in the cloud security list (docs/DEPLOYMENT.md section 2)
   or explain what you did instead (SSH tunnel is fine).
```

## Message 4 – Phase D: daily observation (repeat for 7-14 days)

```
Phase D, day N. Run on the machine:

    cd crypto-signal-bot && ./scripts/report_status.sh 7

Reply with the REPORT block only. Also mention if any Telegram message looked
wrong or if the channel was silent for more than 24 hours while the report shows
new signals.
```

## Message 5 – Phase E: apply an update from the developer

```
Phase E. The developer pushed an update (commit <sha>: <one-line summary>).

    cd crypto-signal-bot && git pull && docker compose up -d --build && sleep 90 && ./scripts/verify.sh --quick

Reply with the REPORT block.
```

## Message 6 – Phase F: go live (owner approval required)

```
Phase F – the owner has approved switching to live market data (the bot only
READS prices; it never places orders).

    cd crypto-signal-bot
    sed -i 's/^BINANCE_TESTNET=.*/BINANCE_TESTNET=false/' .env
    docker compose up -d backend && sleep 90 && ./scripts/verify.sh --quick

Reply with the REPORT block and confirm the Telegram start-up message now says
"Binance Futures LIVE".
```
