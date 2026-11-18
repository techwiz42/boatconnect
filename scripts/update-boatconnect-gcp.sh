#!/usr/bin/env bash
# Puts a commit of this (public) repository on jaynes-vm (GCP) and (re)starts the service there.
#   update-boatconnect-gcp.sh [<sha|ref>]     default origin/main
#   update-boatconnect-gcp.sh --restart       just (re)start the service, e.g. after the settings secret changed
#   update-boatconnect-gcp.sh --status        what is deployed and whether it is answering
# The VM clones the code itself; web/ is built here from the same commit (the VM has no Node) and uploaded. The commit must be pushed. Rollback: run it again with an earlier sha.
# Reaches the VM through IAP (no open SSH port). The settings come from Secret Manager (boatconnect-env). The service user, systemd unit, web server and backup are set up by
# the startup script of that VM (cyberiad-infra/envs/jaynes), which also runs Jaynes.
set -euo pipefail
VM=${BOATCONNECT_VM:-jaynes-vm}
ZONE=${BOATCONNECT_ZONE:-us-west1-b}
PROJECT=${BOATCONNECT_PROJECT:-cyberiad-demo-gcp}
REPO_URL=https://github.com/techwiz42/boatconnect.git
cd "$(dirname "$0")/.."

vm() { gcloud compute ssh "$VM" --zone "$ZONE" --project "$PROJECT" --tunnel-through-iap --quiet --command "$1" 2> >(grep -v -i -E 'numpy|increase the performance|^$|^WARNING: $' >&2); }
health() { vm 'curl -s -m 5 http://127.0.0.1:8001/api/healthz' 2>/dev/null || true; }

ARG=origin/main
for a in "$@"; do ARG=$a; done

if [ "$ARG" = "--status" ]; then
  vm 'echo "deployed: $(sudo -u boatconnect git -C /opt/boatconnect/app log --oneline -1 2>/dev/null || echo nothing)"; echo "service: $(systemctl is-active boatconnect)"; echo "caddy: $(systemctl is-active caddy)"'
  echo "healthz: $(health)"
  exit 0
fi

restart() {
  vm 'sudo systemctl restart boatconnect; for i in $(seq 1 40); do curl -s -m 2 http://127.0.0.1:8001/api/healthz | grep -q "\"ok\":true" && { echo "answering: $(sudo -u boatconnect git -C /opt/boatconnect/app log --oneline -1)"; exit 0; }; sleep 1; done; echo "the service did not answer in 40 seconds:"; sudo journalctl -u boatconnect -n 15 --no-pager; exit 1'
}

if [ "$ARG" = "--restart" ]; then restart; exit $?; fi

git fetch -q origin
SHA=$(git rev-parse "$ARG^{commit}")
git branch -r --contains "$SHA" | grep -q . || { echo "$SHA is not pushed; the VM can only fetch pushed commits"; exit 1; }
echo "deploying ${SHA:0:8}"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
git archive "$SHA" web | tar -x -C "$WORK"
(cd "$WORK/web" && npm ci --silent && npm run build --silent)

vm "sudo -u boatconnect bash -s -- '$REPO_URL' '$SHA'" <<'REMOTE'
set -euo pipefail
REPO_URL=$1; SHA=$2
cd /opt/boatconnect
[ -d app/.git ] || git clone -q "$REPO_URL" app
git -C app fetch -q origin
git -C app checkout -q --detach "$SHA"
[ -d .venv ] || python3.12 -m venv .venv
.venv/bin/pip install -q --disable-pip-version-check -e app
echo "code at $(git -C app log --oneline -1)"
REMOTE

COPYFILE_DISABLE=1 tar -C "$WORK/web" -cf - dist | vm 'sudo -u boatconnect sh -c "rm -rf /opt/boatconnect/app/web/dist && mkdir -p /opt/boatconnect/app/web && tar -xf - -C /opt/boatconnect/app/web"'
restart
