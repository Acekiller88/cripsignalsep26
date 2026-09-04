#!/usr/bin/env bash
# =============================================================================
# telegram_test.sh – verify a bot token + channel id with plain curl.
#
#   TELEGRAM_BOT_TOKEN=123:abc TELEGRAM_CHANNEL_ID=-100123 ./scripts/telegram_test.sh
#   ./scripts/telegram_test.sh            # reads the values from .env
#
# Prints who the bot is, whether it can post to the channel, and – if the
# channel id is unknown – lists the chats the bot has seen (getUpdates).
# =============================================================================
set -u
cd "$(dirname "$0")/.."
if [[ -f .env ]]; then
  : "${TELEGRAM_BOT_TOKEN:=$(grep -E '^TELEGRAM_BOT_TOKEN=' .env | cut -d= -f2- | tr -d '"')}"
  : "${TELEGRAM_CHANNEL_ID:=$(grep -E '^TELEGRAM_CHANNEL_ID=' .env | cut -d= -f2- | tr -d '"')}"
fi
TOKEN="${TELEGRAM_BOT_TOKEN:-}"; CHAT="${TELEGRAM_CHANNEL_ID:-}"
echo "===== REPORT ====="
if [[ -z "$TOKEN" ]]; then echo "FAIL  TELEGRAM_BOT_TOKEN is empty"; echo "===== END REPORT ====="; exit 1; fi

ME="$(curl -s -m 15 "https://api.telegram.org/bot${TOKEN}/getMe")"
if echo "$ME" | grep -q '"ok":true'; then
  echo "PASS  token valid – bot @$(echo "$ME" | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["username"])')"
else
  echo "FAIL  token invalid: $ME"; echo "===== END REPORT ====="; exit 1
fi

if [[ -z "$CHAT" ]]; then
  # Same discovery rule as the bot: first channel/group the bot was added to wins.
  CHAT="$(curl -s -m 15 "https://api.telegram.org/bot${TOKEN}/getUpdates" | python3 scripts/report_lib.py tg_discover 2>/dev/null | tee /dev/stderr | awk '/^channel /{print $2; exit}')"
  if [[ -z "$CHAT" ]]; then
    echo "INFO  TELEGRAM_CHANNEL_ID empty and no channel seen yet – the running bot will pick the channel up"
    echo "      automatically as soon as it is added as administrator (or set TELEGRAM_CHANNEL_ID in .env)."
    echo "===== END REPORT ====="; exit 0
  fi
  echo "PASS  channel auto-discovered: ${CHAT} (the bot will use it automatically)"
fi

CH="$(curl -s -m 15 "https://api.telegram.org/bot${TOKEN}/getChat" -d "chat_id=${CHAT}")"
if echo "$CH" | grep -q '"ok":true'; then
  echo "PASS  channel reachable – $(echo "$CH" | python3 -c 'import sys,json; r=json.load(sys.stdin)["result"]; print(r.get("type"), r.get("title") or r.get("username"))')"
else
  echo "FAIL  getChat failed: $CH"
  echo "      hints: private channel ids start with -100 ; the bot must be a channel ADMIN"
fi

MEMBER="$(curl -s -m 15 "https://api.telegram.org/bot${TOKEN}/getChatMember" -d "chat_id=${CHAT}" -d "user_id=$(echo "$ME" | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["id"])')")"
STATUS="$(echo "$MEMBER" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["result"]["status"] if d.get("ok") else d.get("description"))' 2>/dev/null)"
if [[ "$STATUS" == "administrator" || "$STATUS" == "creator" ]]; then echo "PASS  bot is $STATUS of the channel"; else echo "FAIL  bot membership: $STATUS (must be administrator with 'Post messages')"; fi

SEND="$(curl -s -m 15 "https://api.telegram.org/bot${TOKEN}/sendMessage" -d "chat_id=${CHAT}" -d "parse_mode=HTML" --data-urlencode "text=✅ <b>Crypto Signal Bot</b> – Telegram test message $(date -u '+%Y-%m-%d %H:%M UTC')")"
if echo "$SEND" | grep -q '"ok":true'; then echo "PASS  test message sent (message_id $(echo "$SEND" | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["message_id"])'))"; else echo "FAIL  sendMessage: $SEND"; fi
echo "===== END REPORT ====="
