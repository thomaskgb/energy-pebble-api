#!/usr/bin/env bash
#
# Pull the latest main and (re)start the Energy Pebble stack on cumulus.
# Invoked by .github/workflows/deploy.yml on the self-hosted runner, but also
# safe to run by hand on the server:  DEPLOY_DIR=/path ./deploy/deploy.sh
#
# It operates on the LIVE production checkout ($DEPLOY_DIR), which is separate
# from the runner's own workspace.
set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-/home/cumulus/github/energy-pebble-api}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"

log() { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }
fail() { printf '\n\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

[ -d "$DEPLOY_DIR/.git" ] || fail "DEPLOY_DIR is not a git checkout: $DEPLOY_DIR"

# Pick the docker compose invocation available on this host.
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  fail "docker compose is not installed"
fi

cd "$DEPLOY_DIR"

log "Updating $DEPLOY_DIR to origin/$DEPLOY_BRANCH"
PREV_SHA="$(git rev-parse HEAD)"
git fetch --prune origin "$DEPLOY_BRANCH"
# Hard reset so the deploy can never stall on a merge conflict. Tracked files
# are replaced; runtime state (data/, ../cumulus/edge secrets) is gitignored
# and untouched. If you keep manual hotfixes on the server, commit them first.
git checkout "$DEPLOY_BRANCH"
git reset --hard "origin/$DEPLOY_BRANCH"
NEW_SHA="$(git rev-parse HEAD)"

if [ "$PREV_SHA" = "$NEW_SHA" ]; then
  log "Already at $NEW_SHA, nothing to deploy"
  exit 0
fi
log "Deploying $PREV_SHA → $NEW_SHA"
git --no-pager log --oneline "$PREV_SHA..$NEW_SHA" | sed 's/^/    /' || true

log "Rebuilding and restarting containers"
# Schema migrations are idempotent and run at app startup (init_database), so a
# restart applies them; no separate migration step needed.
$COMPOSE up -d --build

log "Waiting for the API to become healthy"
ok=false
for i in $(seq 1 20); do
  # Public, side-effect-free endpoint served by the API container.
  if curl -fsS --max-time 5 http://127.0.0.1:8000/api/sample >/dev/null 2>&1; then
    ok=true; break
  fi
  sleep 3
done

rollback() {
  log "$1, rolling back to $PREV_SHA"
  git reset --hard "$PREV_SHA"
  $COMPOSE up -d --build
  fail "Deploy of $NEW_SHA failed ($1); rolled back to $PREV_SHA"
}

if [ "$ok" != true ]; then
  rollback "health check failed"
fi

# Caddy reads its Caddyfile once at startup and the file is bind-mounted, so
# `up -d` leaves the old config running in memory: a Caddyfile-only change
# would deploy the file and silently never take effect. Validate the deployed
# config, then hand it to the running Caddy.
#
# A reload is not enough on its own. The Caddyfile is bind-mounted as a single
# FILE, and Docker resolves that to an inode when the container is created.
# `git reset --hard` replaces the file rather than editing it in place, so the
# new Caddyfile lands on a new inode and the container keeps reading the one it
# was created with. Production ran a Caddyfile from 2025-11-12 for ten months
# that way: every deploy wrote a new file, every reload succeeded, and Caddy
# reloaded the same stale copy each time. Recreating the container is what
# re-resolves the mount, so do that whenever the file has actually changed.
if git diff --quiet "$PREV_SHA" "$NEW_SHA" -- Caddyfile; then
  log "Caddyfile unchanged, leaving the web container alone"
else
  log "Caddyfile changed, recreating the web container so the mount re-resolves"
  # The Caddy container is the `web` service in docker-compose.yml; `caddy` is
  # only the binary inside it. exec-ing a nonexistent `caddy` service fails and,
  # with the output swallowed, was misread as an invalid Caddyfile - rolling
  # back every deploy.
  if ! $COMPOSE run --rm --no-deps --entrypoint caddy web validate --config /etc/caddy/Caddyfile >/dev/null 2>&1; then
    rollback "deployed Caddyfile is invalid"
  fi
  $COMPOSE up -d --force-recreate web || rollback "could not recreate the web container"
fi

log "Pruning dangling images"
docker image prune -f >/dev/null 2>&1 || true

log "Deployed $NEW_SHA successfully"
