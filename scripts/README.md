# CTF Scripts

All scripts run from the repo root (`~/ctf-archive/`).

Main entry point: `scripts/wh-training-platform.py` — full platform reset, redeploy, and stress test.
All utility scripts live in `scripts/utils/`.

## Prerequisites

```bash
pip3 install pyyaml
# Also required on PATH: gcloud, kubectl, docker, oras, go, curl
```

Copy and fill in the environment file before running anything:

```bash
cp scripts/.ctf-deploy.env.example scripts/.ctf-deploy.env
```

Edit `scripts/.ctf-deploy.env`:

```
CTFD_URL=http://<HEAD_NODE_IP>
CTFD_TOKEN=<admin-api-token>
AR_IMAGES=asia-southeast1-docker.pkg.dev/<PROJECT_ID>/ctf-images
AR_SCENARIOS=asia-southeast1-docker.pkg.dev/<PROJECT_ID>/ctf-scenarios
TRAEFIK_IP=<TRAEFIK_LB_IP>
```

---

## wh-training-platform.py

Full platform reset and redeploy. Runs 6 steps in order, each with a confirmation prompt.

**No flags.** Interactive only.

```bash
python3 scripts/wh-training-platform.py
```

Steps:
1. Remove all deployed challenges from CTFd
2. Destroy all running instances + delete image-warmer DaemonSet + stop VM
3. Start VM + update configs + start services (calls `startup.sh`)
4. Deploy all challenges (calls `deploy.py --all`)
5. Apply image-warmer DaemonSet (calls `gen-image-warmer.py`)
6. Run stress test (calls `stress.py`)

---

## deploy.py

Build Docker images, compile Go scenarios, push to Artifact Registry, and create challenges in CTFd.

### Flags

| Flag | Required | Description |
|------|----------|-------------|
| `--all` | one of `--all` or `--dir` | Deploy every `challenges/**/challenge.yml` found recursively |
| `--dir PATH` | one of `--all` or `--dir` | Deploy a single challenge directory |
| `--force` | no | Delete existing challenge in CTFd and re-create from scratch |
| `--dry-run` | no | Print all steps without executing anything (no builds, no API calls) |
| `--skip-build` | no | Skip Docker build and ORAS push; only run CTFd API steps |

### Examples

```bash
# Deploy all challenges (build + push + register in CTFd)
python3 scripts/utils/deploy.py --all

# Deploy one challenge
python3 scripts/utils/deploy.py --dir challenges/test-web/sqli-login

# Force re-create (deletes existing challenge in CTFd first)
python3 scripts/utils/deploy.py --dir challenges/test-web/sqli-login --force

# Preview what would happen without making changes
python3 scripts/utils/deploy.py --dir challenges/test-web/sqli-login --dry-run

# Re-register in CTFd without rebuilding Docker image or scenario
python3 scripts/utils/deploy.py --dir challenges/test-web/sqli-login --force --skip-build

# Deploy all, force re-create everything (full wipe + redeploy)
python3 scripts/utils/deploy.py --all --force

# Dry-run all to check challenge.yml syntax and group resolution
python3 scripts/utils/deploy.py --all --dry-run
```

### Notes

- `--all` and `--dir` are mutually exclusive
- `--all` deploys in alphabetical order by directory path. This matters for grouped challenges: the master (e.g. `web-noteshare-1`) must deploy before its satellites (`web-noteshare-2`, etc.) so the CTFd ID is available for `group_master_slug` resolution
- `--force` without `--skip-build` rebuilds everything from scratch (Docker image + Go scenario + CTFd)
- `--skip-build` is useful when only challenge metadata changed (name, description, hints, flag) but the container and scenario are unchanged
- After updating a scenario, you must also restart chall-manager on the head node to flush its OCI cache:
  ```bash
  gcloud compute ssh ctf-head --zone=asia-southeast1-b \
    --command="cd /opt/ctfd && sudo docker compose --env-file .env restart chall-manager"
  ```

---

## startup.sh

Start the head VM, wait for SSH, update HEAD_IP in configs, bring up Docker Compose services.

**No flags.** Non-interactive.

```bash
bash scripts/utils/startup.sh
```

What it does:
1. `gcloud compute instances start ctf-head`
2. Gets the new external IP
3. Waits for SSH to be ready (retries up to 4 minutes)
4. Updates `HEAD_IP` in `/opt/ctfd/.env` on the head node
5. Updates `CTFD_URL` in local `scripts/.ctf-deploy.env`
6. Runs `docker compose up -d` on the head node
7. Prints the CTFd URL

Run this at the start of every session (or whenever the VM has been stopped). The head node uses an ephemeral IP that changes on every stop/start — this script handles the update.

---

## shutdown.py

Destroy all running challenge instances, clean up GKE pods, stop the head VM.

**No flags.** Interactive — prompts before destroying instances.

```bash
python3 scripts/utils/shutdown.py
```

What it does:
1. Lists active instances from chall-manager
2. Prompts for confirmation, then deletes each instance via CTFd API
3. Deletes the image-warmer DaemonSet
4. Waits for GKE pods to drain (shows pod names + status, prompts after 60s if pods remain)
5. Stops the VM

CTFd data (challenges, scores, solves, submissions, users, files) is preserved on the persistent disk.

---

## stress.py

Concurrent instance creation load test. Creates hidden admin accounts, fires simultaneous boot requests, then enters a live monitoring loop.

**No flags.** Interactive — prompts for user count and timeout.

```bash
python3 scripts/utils/stress.py
```

Interactive prompts:
- `Number of concurrent users (1-10):` — how many simultaneous users to simulate
- `Connection info timeout in seconds [60]:` — how long to wait for each instance to return a URL/host

What it does:
1. Restarts chall-manager (fresh OCI auth)
2. Creates N hidden admin accounts in CTFd (or reuses existing)
3. Logs in as each user and generates API tokens
4. Detects satellite challenges and skips them (they share the master's instance)
5. For each non-satellite challenge, fires N concurrent instance creation requests
6. Optionally polls `connection_info` for each instance and checks reachability
7. Enters live monitoring loop showing CPU/mem/network/disk for head VM, GKE nodes, and pods (Ctrl+C to stop)

If any instance fails with an OCI auth error, the script automatically restarts chall-manager and retries once.

---

## healthcheck.py

Verify every visible challenge works end-to-end.

**No flags.** Interactive — prompts before teardown.

```bash
python3 scripts/utils/healthcheck.py
```

What it does:

**Phase 0 — Teardown:** Scans for leftover admin instances from a previous run. Prompts before deleting them.

**Phase 1 — Healthcheck:** For each visible challenge:
- `dynamic_iac` (web/pwn): creates an admin test instance, polls until `connection_info` appears (up to 90s), verifies web URLs return HTTP 200
- Satellite challenges (group): reuses the master's already-running instance
- `standard` (static): checks all attached file download links return HTTP 200
- Hidden challenges are skipped

**Phase 2 — Cleanup:** Lists all admin instances created during the run. Prompts whether to tear them down.

Exit code `0` = all passed. Exit code `1` = one or more failed.

---

## refresh.py

Daily maintenance: refresh stale GKE node IPs in pwn challenges, flush OCI cache, restart chall-manager, refresh image-warmer DaemonSet, clean zombie pods, verify services.

### Flags

| Flag | Description |
|------|-------------|
| `--cron` | Non-interactive mode (no confirmation prompt). For use in cron jobs |
| `--deploy-cron` | Install the self-contained refresh script + daily cron job on ctf-head |

### Examples

```bash
# Run interactively (prompts before proceeding)
python3 scripts/utils/refresh.py

# Run non-interactively (for scripting)
python3 scripts/utils/refresh.py --cron

# Install daily 4 AM cron job on the head node
python3 scripts/utils/refresh.py --deploy-cron
```

### `--deploy-cron` details

Copies `refresh-remote.py` to ctf-head as `/opt/ctfd/refresh-cron.py`, writes `CTFD_TOKEN` to `/opt/ctfd/refresh.env`, and sets up a root crontab entry:

```
0 4 * * * python3 /opt/ctfd/refresh-cron.py >> /var/log/ctf-refresh.log 2>&1
```

Check cron logs:

```bash
gcloud compute ssh ctf-head --zone=asia-southeast1-b \
  --command="tail -50 /var/log/ctf-refresh.log"
```

### refresh-remote.py

Self-contained script that runs directly on the head node (installed by `--deploy-cron`). Not meant to be run manually from your local machine.

Reads config from `/opt/ctfd/.env` (HEAD_IP) and `/opt/ctfd/refresh.env` (CTFD_TOKEN). Runs all maintenance tasks locally (no SSH — it's already on the head node). Does NOT include image-warmer refresh (no access to challenge source directories on ctf-head).

---

## gen-image-warmer.py

Generate and apply a Kubernetes DaemonSet that pre-pulls all challenge Docker images on every GKE node. Cuts ~10-30s off instance creation time.

### Flags

| Flag | Description |
|------|-------------|
| `--dry-run` | Print the generated DaemonSet YAML without applying it to the cluster |

### Examples

```bash
# Generate + apply the DaemonSet
python3 scripts/utils/gen-image-warmer.py

# Preview the YAML without applying
python3 scripts/utils/gen-image-warmer.py --dry-run
```

What it does:
1. Scans all `challenges/**/image/Dockerfile` directories to find challenge image slugs
2. Generates a DaemonSet YAML with one init container per challenge image (`imagePullPolicy: Always`)
3. Applies via `kubectl apply -f -` through SSH to the head node

Check status after applying:

```bash
gcloud compute ssh ctf-head --zone=asia-southeast1-b \
  --command="sudo kubectl get ds image-warmer -n ctf-challenges"
```

---

## .ctf-deploy.env reference

| Variable | Example | Used by |
|----------|---------|---------|
| `CTFD_URL` | `http://<HEAD_IP>` | All scripts that call CTFd API |
| `CTFD_TOKEN` | `ctfd_abc123...` | All scripts that call CTFd API |
| `AR_IMAGES` | `asia-southeast1-docker.pkg.dev/<PROJECT_ID>/ctf-images` | deploy.py, gen-image-warmer.py |
| `AR_SCENARIOS` | `asia-southeast1-docker.pkg.dev/<PROJECT_ID>/ctf-scenarios` | deploy.py |
| `TRAEFIK_IP` | `<TRAEFIK_LB_IP>` | deploy.py (auto-fills `additional.domain`) |

`CTFD_URL` is updated automatically by `startup.sh` when the VM IP changes.
`CTFD_TOKEN` is generated manually from the CTFd admin UI (Settings > Access Tokens).

---

See `README_beta1.md` in the repo root for the full platform setup, challenge authoring guide, and troubleshooting reference.
