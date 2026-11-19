#!/usr/bin/env bash
# Sets the mail settings in the boatconnect-env secret for sending as a Gmail/Workspace mailbox with an app password, prompting for the password
# so it never appears on a command line, in history, or in a chat. Other settings in the secret are kept.
#   set-mail-login.sh <mailbox address> [<From header, default "boatconnect <mailbox>">]
# Then: update-boatconnect-gcp.sh --restart
set -euo pipefail
PROJECT=${BOATCONNECT_PROJECT:-cyberiad-demo-gcp}
SECRET=${BOATCONNECT_SECRET:-boatconnect-env}
USER_ADDR=${1:?usage: set-mail-login.sh <mailbox address> [<From header>]}
FROM=${2:-"boatconnect <$USER_ADDR>"}
REPLY_TO=${BOATCONNECT_REPLY_TO:-j35.scooter@gmail.com}
read -r -s -p "App password for $USER_ADDR (not shown): " PASS; echo
[ -n "$PASS" ] || { echo "empty password, nothing changed" >&2; exit 1; }
current=$(gcloud secrets versions access latest --secret "$SECRET" --project "$PROJECT")
kept=$(printf '%s\n' "$current" | grep -v -E '^(MAIL_HOST|MAIL_PORT|MAIL_USER|MAIL_PASSWORD|MAIL_FROM|MAIL_REPLY_TO|PUBLIC_URL)=' || true)
{
  printf '%s\n' "$kept"
  printf 'MAIL_HOST=smtp.gmail.com\nMAIL_PORT=587\nMAIL_USER=%s\nMAIL_PASSWORD=%s\nMAIL_FROM=%s\nMAIL_REPLY_TO=%s\nPUBLIC_URL=https://boatconnect.org\n' "$USER_ADDR" "${PASS// /}" "$FROM" "$REPLY_TO"
} | gcloud secrets versions add "$SECRET" --project "$PROJECT" --data-file=- >/dev/null
echo "Saved a new version of $SECRET (names set: MAIL_HOST MAIL_PORT MAIL_USER MAIL_PASSWORD MAIL_FROM MAIL_REPLY_TO PUBLIC_URL). Now run: scripts/update-boatconnect-gcp.sh --restart"
