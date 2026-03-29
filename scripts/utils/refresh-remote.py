#!/usr/bin/env python3
"""
Daily CTF platform maintenance — runs directly on ctf-head VM.

Tasks:
  1. Refresh stale GKE node IPs in pwn challenges
  2. Flush OCI cache + restart chall-manager
  3. Clean zombie pods
  4. Verify services

Config: reads /opt/ctfd/refresh.env for CTFD_TOKEN, /opt/ctfd/.env for HEAD_IP.

Install from local machine:
  python3 scripts/utils/refresh.py --deploy-cron

Cron (set up automatically by --deploy-cron):
  0 4 * * * python3 /opt/ctfd/refresh-cron.py >> /var/log/ctf-refresh.log 2>&1
"""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

CTFD_ENV    = "/opt/ctfd/.env"
REFRESH_ENV = "/opt/ctfd/refresh.env"


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def load_config() -> dict:
    """Load HEAD_IP from .env, CTFD_TOKEN from refresh.env."""
    config = {}
    for path in [CTFD_ENV, REFRESH_ENV]:
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        config[k.strip()] = v.strip()
        except FileNotFoundError:
            log(f"WARN: {path} not found")
    return config


def run(cmd: str, timeout: int = 30) -> str:
    """Run shell command locally on ctf-head."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip()
    except Exception as e:
        log(f"  Command failed: {e}")
        return ""


def api_call(method: str, url: str, headers: dict, data=None) -> dict:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"success": False, "http_status": e.code, "error": e.read().decode()}
    except Exception as e:
        return {"success": False, "error": str(e)}


# -- refresh tasks ------------------------------------------------------------

def refresh_node_ip(base: str, headers: dict) -> int:
    log("Refreshing GKE node IP...")

    current_ip = run(
        "sudo kubectl get nodes -o "
        "jsonpath='{.items[0].status.addresses[?(@.type==\"ExternalIP\")].address}'"
    ).strip("'")

    if not current_ip:
        log("  WARN: Could not detect GKE node IP — skipping")
        return 0

    log(f"  Current node IP: {current_ip}")

    r = api_call("GET", f"{base}/api/v1/challenges?view=admin", headers)
    if not r.get("success"):
        log(f"  ERROR: failed to list challenges: {r.get('error', r)}")
        return 0

    patched = 0
    for chal in r.get("data", []):
        if chal.get("type") != "dynamic_iac":
            continue

        detail = api_call("GET", f"{base}/api/v1/challenges/{chal['id']}", headers)
        additional = (detail.get("data") or {}).get("additional") or {}
        if isinstance(additional, str):
            try:
                additional = json.loads(additional)
            except (json.JSONDecodeError, ValueError):
                continue

        old_ip = additional.get("node_ip", "")
        if not old_ip or old_ip == current_ip:
            continue

        additional["node_ip"] = current_ip
        pr = api_call("PATCH", f"{base}/api/v1/challenges/{chal['id']}", headers,
                       {"additional": additional})
        if pr.get("success"):
            log(f"  Patched [{chal['name']}] node_ip: {old_ip} -> {current_ip}")
            patched += 1
        else:
            log(f"  WARN: failed to patch [{chal['name']}]: {pr.get('error', pr)}")

    if patched == 0:
        log("  All node_ip values already current.")
    else:
        log(f"  Patched {patched} challenge(s).")
    return patched


def flush_oci_cache() -> bool:
    log("Flushing OCI cache + restarting chall-manager...")

    run(
        "sudo docker exec ctfd-chall-manager-1 sh -c "
        "'rm -rf /root/.cache/chall-manager/oci/*' 2>/dev/null; "
        "cd /opt/ctfd && sudo docker compose --env-file .env restart chall-manager",
        timeout=60,
    )

    log("  Waiting for chall-manager to be ready...")
    deadline = time.time() + 60
    while time.time() < deadline:
        status = run(
            "sudo docker inspect --format='{{.State.Status}}' "
            "ctfd-chall-manager-1 2>/dev/null",
            timeout=10,
        )
        if status == "running":
            log("  chall-manager is running.")
            return True
        time.sleep(5)

    log("  WARN: chall-manager did not come back within 60s")
    return False


def cleanup_zombie_pods() -> int:
    log("Checking for zombie pods...")

    raw = run(
        "sudo kubectl get pods -n ctf-challenges --no-headers 2>/dev/null "
        "| awk '$3 ~ /Error|CrashLoopBackOff|Terminating|ImagePullBackOff/ {print $1}'",
        timeout=15,
    )

    if not raw:
        log("  No zombie pods found.")
        return 0

    pods = raw.strip().split("\n")
    log(f"  Found {len(pods)} zombie pod(s), cleaning up...")
    for pod in pods:
        run(f"sudo kubectl delete pod {pod} -n ctf-challenges --force --grace-period=0 2>/dev/null",
            timeout=15)
        log(f"  Deleted {pod}")

    return len(pods)


def verify_services(base: str, headers: dict) -> bool:
    log("Verifying services...")

    r = api_call("GET", f"{base}/api/v1/challenges?view=admin", headers)
    if r.get("success"):
        count = len(r.get("data", []))
        log(f"  CTFd: OK ({count} challenges)")
    else:
        log(f"  CTFd: FAIL ({r.get('error', r)})")
        return False

    cm_status = run(
        "sudo docker inspect --format='{{.State.Status}}' "
        "ctfd-chall-manager-1 2>/dev/null",
        timeout=10,
    )
    if cm_status == "running":
        log(f"  chall-manager: OK (running)")
    else:
        log(f"  chall-manager: WARN (status={cm_status or 'unknown'})")

    services = run(
        "cd /opt/ctfd && sudo docker compose ps --format '{{.Name}} {{.Status}}' 2>/dev/null",
        timeout=15,
    )
    if services:
        for line in services.strip().split("\n"):
            log(f"  {line}")

    return True


# -- main ---------------------------------------------------------------------

def main():
    config = load_config()
    token  = config.get("CTFD_TOKEN", "")
    head_ip = config.get("HEAD_IP", "")

    if not token:
        sys.exit("ERROR: CTFD_TOKEN not found in /opt/ctfd/refresh.env")
    if not head_ip:
        sys.exit("ERROR: HEAD_IP not found in /opt/ctfd/.env")

    # CTFd rejects token auth on localhost (302 redirect), must use external IP
    base = f"http://{head_ip}"
    hdrs = {"Authorization": f"Token {token}", "Content-Type": "application/json"}

    log("=" * 50)
    log("CTF Platform Daily Refresh (on ctf-head)")
    log("=" * 50)

    refresh_node_ip(base, hdrs)
    print()

    flush_oci_cache()
    print()

    cleanup_zombie_pods()
    print()

    verify_services(base, hdrs)
    print()

    log("=" * 50)
    log("Refresh complete.")
    log("=" * 50)


if __name__ == "__main__":
    main()
