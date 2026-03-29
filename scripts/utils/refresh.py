#!/usr/bin/env python3
"""
Daily maintenance: refresh stale IPs, flush OCI cache, restart chall-manager.

Safe to run while CTFd is live — only touches operational metadata.
Does NOT modify: challenges, flags, hints, solves, submissions, scores, users.

Usage:
  python3 scripts/refresh.py          # run interactively
  python3 scripts/refresh.py --cron   # non-interactive (for cron jobs, no prompts)

Cron example (4 AM daily):
  0 4 * * * cd /home/kali/ctf-archive && python3 scripts/refresh.py --cron >> /var/log/ctf-refresh.log 2>&1
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ENV_FILE = Path(__file__).parent.parent / ".ctf-deploy.env"
ZONE     = "asia-southeast1-b"
HEAD_VM  = "ctf-head"


# -- helpers ------------------------------------------------------------------

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def load_env() -> dict:
    if not ENV_FILE.exists():
        sys.exit(f"ERROR: {ENV_FILE} not found")
    env = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def ssh(cmd: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(
            ["gcloud", "compute", "ssh", HEAD_VM, f"--zone={ZONE}",
             f"--command={cmd}"],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip()
    except Exception as e:
        log(f"  SSH failed: {e}")
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
    """Detect current GKE node IP, patch any pwn challenges with stale node_ip.
    Returns number of challenges patched."""
    log("Refreshing GKE node IP...")

    # Get current node external IP
    current_ip = ssh(
        "sudo kubectl get nodes -o "
        "jsonpath='{.items[0].status.addresses[?(@.type==\"ExternalIP\")].address}'"
    ).strip("'")

    if not current_ip:
        log("  WARN: Could not detect GKE node IP — skipping")
        return 0

    log(f"  Current node IP: {current_ip}")

    # List all dynamic_iac challenges
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

        # Patch
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
    """Flush chall-manager OCI cache and restart for fresh AR auth."""
    log("Flushing OCI cache + restarting chall-manager...")

    ssh(
        "sudo docker exec ctfd-chall-manager-1 sh -c "
        "'rm -rf /root/.cache/chall-manager/oci/*' 2>/dev/null; "
        "cd /opt/ctfd && sudo docker compose --env-file .env restart chall-manager",
        timeout=60,
    )

    # Wait for chall-manager to come back
    log("  Waiting for chall-manager to be ready...")
    deadline = time.time() + 60
    while time.time() < deadline:
        status = ssh(
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


def refresh_image_warmer() -> bool:
    """Regenerate and apply the image-warmer DaemonSet to pre-pull challenge images."""
    log("Refreshing image-warmer DaemonSet...")

    # Import and reuse gen-image-warmer logic
    script_dir = Path(__file__).parent
    repo_root  = script_dir.parent.parent
    env = load_env()
    ar_images  = env.get("AR_IMAGES", "")

    if not ar_images:
        log("  WARN: AR_IMAGES not set — skipping image warmer")
        return False

    # Find all challenge image slugs
    slugs = []
    challenges_dir = repo_root / "challenges"
    for dockerfile in sorted(challenges_dir.rglob("image/Dockerfile")):
        slugs.append(dockerfile.parent.parent.name)

    if not slugs:
        log("  No challenge images found — skipping")
        return False

    log(f"  Found {len(slugs)} challenge image(s)")

    # Generate DaemonSet YAML inline (avoid subprocess to self)
    init_containers = ""
    for slug in slugs:
        safe_name = slug.replace("_", "-")
        init_containers += (
            f"      - name: pull-{safe_name}\n"
            f"        image: {ar_images}/{slug}:latest\n"
            f"        imagePullPolicy: Always\n"
            f'        command: ["true"]\n'
            f"        resources:\n"
            f"          requests:\n"
            f"            cpu: 1m\n"
            f"            memory: 1Mi\n"
        )

    yaml_str = (
        "apiVersion: apps/v1\n"
        "kind: DaemonSet\n"
        "metadata:\n"
        "  name: image-warmer\n"
        "  namespace: ctf-challenges\n"
        "  labels:\n"
        "    app: image-warmer\n"
        "spec:\n"
        "  selector:\n"
        "    matchLabels:\n"
        "      app: image-warmer\n"
        "  template:\n"
        "    metadata:\n"
        "      labels:\n"
        "        app: image-warmer\n"
        "    spec:\n"
        "      initContainers:\n"
        f"{init_containers}"
        "      containers:\n"
        "      - name: idle\n"
        "        image: busybox:1.36\n"
        '        command: ["sleep", "infinity"]\n'
        "        resources:\n"
        "          requests:\n"
        "            cpu: 10m\n"
        "            memory: 16Mi\n"
        "          limits:\n"
        "            cpu: 10m\n"
        "            memory: 16Mi\n"
    )

    # Apply via SSH + kubectl
    try:
        r = subprocess.run(
            ["gcloud", "compute", "ssh", HEAD_VM, f"--zone={ZONE}",
             "--command=sudo kubectl apply -f -"],
            input=yaml_str, capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            log(f"  Applied: {r.stdout.strip()}")
            return True
        else:
            log(f"  WARN: kubectl apply failed: {r.stderr.strip()}")
            return False
    except Exception as e:
        log(f"  WARN: image warmer apply failed: {e}")
        return False


def cleanup_zombie_pods() -> int:
    """Delete pods stuck in Terminating/Error/CrashLoopBackOff state.
    Returns number of pods cleaned."""
    log("Checking for zombie pods...")

    raw = ssh(
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
        ssh(f"sudo kubectl delete pod {pod} -n ctf-challenges --force --grace-period=0 2>/dev/null",
            timeout=15)
        log(f"  Deleted {pod}")

    return len(pods)


def verify_services(base: str, headers: dict) -> bool:
    """Quick health check: CTFd API + chall-manager reachable."""
    log("Verifying services...")

    # CTFd
    r = api_call("GET", f"{base}/api/v1/challenges?view=admin", headers)
    if r.get("success"):
        count = len(r.get("data", []))
        log(f"  CTFd: OK ({count} challenges)")
    else:
        log(f"  CTFd: FAIL ({r.get('error', r)})")
        return False

    # chall-manager
    cm_status = ssh(
        "sudo docker inspect --format='{{.State.Status}}' "
        "ctfd-chall-manager-1 2>/dev/null",
        timeout=10,
    )
    if cm_status == "running":
        log(f"  chall-manager: OK (running)")
    else:
        log(f"  chall-manager: WARN (status={cm_status or 'unknown'})")

    # Docker compose services
    services = ssh("cd /opt/ctfd && sudo docker compose ps --format '{{.Name}} {{.Status}}' 2>/dev/null",
                   timeout=15)
    if services:
        for line in services.strip().split("\n"):
            log(f"  {line}")

    return True


# -- deploy cron to ctf-head --------------------------------------------------

def deploy_cron():
    """Copy refresh-remote.py to ctf-head and set up a daily 4 AM cron job."""
    env = load_env()
    token = env.get("CTFD_TOKEN", "")
    if not token:
        sys.exit("ERROR: CTFD_TOKEN not set in .ctf-deploy.env")

    remote_script = Path(__file__).parent / "refresh-remote.py"
    if not remote_script.exists():
        sys.exit(f"ERROR: {remote_script} not found")

    log("Deploying refresh-cron.py to ctf-head...")

    # 1. Copy script to ctf-head (scp to /tmp, then sudo mv)
    log("  Copying refresh-remote.py → /opt/ctfd/refresh-cron.py")
    subprocess.run(
        ["gcloud", "compute", "scp", str(remote_script),
         f"{HEAD_VM}:/tmp/refresh-cron.py", f"--zone={ZONE}"],
        check=True,
    )
    ssh("sudo mv /tmp/refresh-cron.py /opt/ctfd/refresh-cron.py && "
        "sudo chmod 755 /opt/ctfd/refresh-cron.py",
        timeout=15)

    # 2. Create /opt/ctfd/refresh.env with CTFD_TOKEN
    log("  Writing /opt/ctfd/refresh.env (CTFD_TOKEN)")
    ssh(f"echo 'CTFD_TOKEN={token}' | sudo tee /opt/ctfd/refresh.env > /dev/null && "
        "sudo chmod 600 /opt/ctfd/refresh.env",
        timeout=15)

    # 3. Set up cron job (4 AM daily, idempotent)
    cron_line = "0 4 * * * python3 /opt/ctfd/refresh-cron.py >> /var/log/ctf-refresh.log 2>&1"
    log(f"  Setting up cron: {cron_line}")
    ssh(
        f"(sudo crontab -l 2>/dev/null | grep -v 'refresh-cron.py'; "
        f"echo '{cron_line}') | sudo crontab -",
        timeout=15,
    )

    # 4. Verify
    installed_cron = ssh("sudo crontab -l 2>/dev/null | grep refresh-cron", timeout=10)
    if installed_cron:
        log(f"  Cron installed: {installed_cron}")
    else:
        log("  WARN: cron entry not found after install")

    log("Done. Refresh will run daily at 4 AM on ctf-head.")
    log("Logs: gcloud compute ssh ctf-head --zone=asia-southeast1-b "
        '--command="tail -50 /var/log/ctf-refresh.log"')


# -- main ---------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Daily CTF platform maintenance.")
    ap.add_argument("--cron", action="store_true",
                    help="Non-interactive mode (no prompts, for cron jobs)")
    ap.add_argument("--deploy-cron", action="store_true",
                    help="Install refresh script + cron job on ctf-head VM")
    args = ap.parse_args()

    if args.deploy_cron:
        deploy_cron()
        return

    env  = load_env()
    base = env["CTFD_URL"].rstrip("/")
    hdrs = {"Authorization": f"Token {env['CTFD_TOKEN']}",
            "Content-Type": "application/json"}

    log("=" * 50)
    log("CTF Platform Daily Refresh")
    log("=" * 50)

    if not args.cron:
        log(f"Target: {base}")
        try:
            answer = input("Proceed? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer == "n":
            log("Aborted.")
            return

    # 1. Refresh stale node IPs
    refresh_node_ip(base, hdrs)
    print()

    # 2. Flush OCI cache + restart chall-manager
    flush_oci_cache()
    print()

    # 3. Refresh image-warmer DaemonSet (pre-pull challenge images)
    refresh_image_warmer()
    print()

    # 4. Clean zombie pods
    cleanup_zombie_pods()
    print()

    # 5. Verify services
    verify_services(base, hdrs)
    print()

    log("=" * 50)
    log("Refresh complete.")
    log("=" * 50)


if __name__ == "__main__":
    main()
