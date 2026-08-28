# Auto-deploy to cumulus

When a PR is merged to `main`, GitHub Actions runs [`deploy.sh`](deploy.sh) on a
**self-hosted runner installed on cumulus**. The runner connects *outbound* to
GitHub, so no inbound ports are opened and no SSH key or server credential is
stored in GitHub.

```
PR merged → push to main → GitHub Actions → self-hosted runner on cumulus
          → git fetch + reset --hard origin/main → docker compose up -d --build
          → health check (rollback on failure)
```

## One-time setup on cumulus

### 1. Install the runner

In GitHub: **Settings → Actions → Runners → New self-hosted runner** (Linux/x64)
and follow the shown commands. When it asks for labels, add **`cumulus`** (the
workflow targets `runs-on: [self-hosted, cumulus]`).

Run it as the `cumulus` user (or whoever owns the production checkout and can run
`docker`), then install it as a service so it survives reboots:

```bash
sudo ./svc.sh install cumulus
sudo ./svc.sh start
```

Confirm the runner shows **Idle** under Settings → Actions → Runners.

### 2. Point the deploy at your live checkout

`deploy.sh` deploys into `DEPLOY_DIR` — the directory the compose stack actually
runs from (where `docker-compose.yml` and the `../cumulus/edge` sibling live).
The default is `/home/cumulus/github/energy-pebble-api`. If yours differs, set a
repo **Variable** (not a secret): Settings → Secrets and variables → Actions →
Variables → **`DEPLOY_DIR`** = your path.

Make sure that checkout is clean and on `main` before the first run (the script
does `git reset --hard`, which discards tracked-file changes; runtime state under
`data/` and the `../cumulus/edge` secrets are gitignored and preserved).

### 3. Ensure the runner user can build

The runner user must be able to run `docker` and `docker compose` without sudo:

```bash
sudo usermod -aG docker cumulus   # then re-login / restart the runner service
```

## Behaviour notes

- **Trigger:** any push to `main` (which is what merging a PR does) and manual
  **Run workflow** (`workflow_dispatch`).
- **Concurrency:** deploys never overlap; an in-flight deploy finishes before the
  next starts.
- **Migrations:** schema changes are idempotent and applied at app startup, so a
  restart migrates automatically — no separate step.
- **Rollback:** if the API doesn't answer `GET /api/sample` within ~60s after
  restart, the script resets to the previous commit and rebuilds, then fails the
  job so you get a red ❌ on the merge.
- **Manual run:** `DEPLOY_DIR=/your/path ./deploy/deploy.sh` on the server does
  the same thing outside CI.

## Security note

This is convenience automation, not a hardened release gate. Because it deploys
whatever lands on `main`, protect `main` with a branch rule requiring PR review
(and, ideally, a passing test workflow) before merge — otherwise a direct push to
`main` deploys straight to production. Pair this with the fixes in
`FIRMWARE_SIGNING.md` and the platform security review before going commercial.
