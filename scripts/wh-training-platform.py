#!/usr/bin/env python3
"""
WH Training Platform — Full platform reset, redeploy, and stress test.

Steps:
  1. Remove all deployed challenges from CTFd
  2. Destroy all running instances + stop VM
  3. Start VM + update configs + start services
  4. Deploy all challenges
  5. Apply image-warmer DaemonSet
  6. Run stress test

Each step prompts for confirmation before proceeding.

Usage: python3 scripts/wh-training-platform.py
"""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SCRIPTS   = Path(__file__).parent
UTILS     = SCRIPTS / "utils"
ENV_FILE  = SCRIPTS / ".ctf-deploy.env"
ZONE      = "asia-southeast1-b"
HEAD_VM   = "ctf-head"


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


def api_call(method: str, url: str, headers: dict, data=None) -> dict:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"success": False, "http_status": e.code, "error": e.read().decode()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def ssh(cmd: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(
            ["gcloud", "compute", "ssh", HEAD_VM, f"--zone={ZONE}",
             f"--command={cmd}"],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip()
    except Exception as e:
        print(f"  SSH failed: {e}")
        return ""


def confirm(msg: str) -> bool:
    try:
        answer = input(f"\n{msg} [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"
    return answer != "n"


# ── Step 1: Remove all challenges from CTFd ──────────────────────────────────

def step_remove_challenges(base: str, headers: dict) -> bool:
    print("\n" + "=" * 60)
    print("STEP 1: Remove all deployed challenges from CTFd")
    print("=" * 60)

    r = api_call("GET", f"{base}/api/v1/challenges?view=admin", headers)
    if not r.get("success"):
        print(f"  ERROR: Could not fetch challenges: {r.get('error', r)}")
        return False

    challenges = r.get("data", [])
    if not challenges:
        print("  No challenges found — nothing to remove.")
        return True

    print(f"  Found {len(challenges)} challenge(s):")
    for c in challenges:
        print(f"    id={c['id']}  [{c.get('type', '?')}]  {c['name']}")

    if not confirm(f"Delete all {len(challenges)} challenges?"):
        print("  Skipped.")
        return True

    for c in challenges:
        print(f"  Deleting [{c['name']}]...", end=" ", flush=True)
        dr = api_call("DELETE", f"{base}/api/v1/challenges/{c['id']}", headers)
        if dr.get("success"):
            print("ok")
        else:
            print(f"WARN: {dr.get('error', dr)}")

    print("  All challenges removed.")
    return True


# ── Step 2: Destroy instances + stop VM ───────────────────────────────────────

def step_shutdown(base: str, headers: dict) -> bool:
    print("\n" + "=" * 60)
    print("STEP 2: Destroy instances + stop VM")
    print("=" * 60)

    if not confirm("Destroy all running instances and stop the head VM?"):
        print("  Skipped.")
        return True

    # List instances from chall-manager
    print("  Fetching active instances from chall-manager...")
    raw = ssh(
        "sudo docker exec ctfd-chall-manager-1 "
        "curl -sf http://localhost:8080/api/v1/instance 2>/dev/null",
        timeout=15,
    )

    instances = []
    try:
        data = json.loads(raw)
        instances = data if isinstance(data, list) else data.get("instances", [])
    except (json.JSONDecodeError, AttributeError):
        pass

    # Delete instances via CTFd admin API
    if instances:
        print(f"  Destroying {len(instances)} instance(s)...")
        for inst in instances:
            cid = inst.get("challengeId", inst.get("challenge_id", "?"))
            sid = inst.get("sourceId", inst.get("source_id", "?"))
            print(f"    challenge={cid} source={sid} ...", end=" ", flush=True)
            url = (
                f"{base}/api/v1/plugins/ctfd-chall-manager/admin/instance"
                f"?challengeId={cid}&sourceId={sid}"
            )
            result = api_call("DELETE", url, headers)
            print("ok" if result.get("success") else f"warn: {result}")
    else:
        print("  No active instances found.")

    # Delete image-warmer DaemonSet (it won't drain on its own)
    print("  Deleting image-warmer DaemonSet...")
    ssh("sudo kubectl delete ds image-warmer -n ctf-challenges --ignore-not-found 2>/dev/null")

    # Wait for pods to drain
    print("  Waiting for challenge pods to drain...")
    prompted = False
    for i in range(18):
        raw_pods = ssh(
            "sudo kubectl get pods -n ctf-challenges --no-headers 2>/dev/null",
            timeout=15,
        )
        if not raw_pods or not raw_pods.strip():
            print("  GKE namespace empty.")
            break

        lines = [l for l in raw_pods.strip().split("\n") if l.strip()]
        for line in lines:
            parts = line.split()
            name   = parts[0] if parts else "?"
            status = parts[2] if len(parts) > 2 else "?"
            print(f"    {name}  ({status})")

        elapsed = (i + 1) * 10
        if elapsed >= 60 and not prompted:
            prompted = True
            try:
                answer = input(f"\n  {len(lines)} pod(s) still present after {elapsed}s. Keep waiting? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "n"
            if answer != "y":
                print("  Force-deleting remaining pods...")
                ssh("sudo kubectl delete all --all -n ctf-challenges --force --grace-period=0 2>/dev/null || true",
                    timeout=30)
                break

        print(f"  Waiting 10s... ({elapsed}s elapsed)")
        time.sleep(10)
    else:
        print("  Force-deleting remaining pods...")
        ssh("sudo kubectl delete all --all -n ctf-challenges --force --grace-period=0 2>/dev/null || true",
            timeout=30)

    # Stop VM
    print("  Stopping VM...")
    subprocess.run(
        ["gcloud", "compute", "instances", "stop", HEAD_VM, f"--zone={ZONE}"],
        check=True,
    )
    print("  VM stopped.")
    return True


# ── Step 3: Start VM + services ──────────────────────────────────────────────

def step_startup() -> bool:
    print("\n" + "=" * 60)
    print("STEP 3: Start VM + update configs + start services")
    print("=" * 60)

    if not confirm("Start the head VM and bring up services?"):
        print("  Skipped.")
        return True

    # Run startup.sh (it handles VM start, SSH wait, config update, docker compose up)
    startup_script = UTILS / "startup.sh"
    print(f"  Running {startup_script}...")
    r = subprocess.run(["bash", str(startup_script)], cwd=str(REPO_ROOT))
    if r.returncode != 0:
        print(f"  ERROR: startup.sh failed (exit {r.returncode})")
        return False

    # Reload env since startup.sh updates CTFD_URL
    print("  Reloading .ctf-deploy.env...")
    return True


# ── Step 4: Deploy all challenges ────────────────────────────────────────────

def step_deploy() -> bool:
    print("\n" + "=" * 60)
    print("STEP 4: Deploy all challenges")
    print("=" * 60)

    if not confirm("Deploy all challenges (docker build + push + CTFd API)?"):
        print("  Skipped.")
        return True

    deploy_script = UTILS / "deploy.py"
    print(f"  Running {deploy_script} --all ...")
    r = subprocess.run(
        [sys.executable, str(deploy_script), "--all"],
        cwd=str(REPO_ROOT),
    )
    if r.returncode != 0:
        print(f"  ERROR: deploy.py failed (exit {r.returncode})")
        return False

    print("  All challenges deployed.")
    return True


# ── Step 5: Apply image-warmer DaemonSet ─────────────────────────────────────

def step_image_warmer() -> bool:
    print("\n" + "=" * 60)
    print("STEP 5: Apply image-warmer DaemonSet (pre-pull challenge images)")
    print("=" * 60)

    if not confirm("Generate and apply the image-warmer DaemonSet?"):
        print("  Skipped.")
        return True

    warmer_script = UTILS / "gen-image-warmer.py"
    print(f"  Running {warmer_script}...")
    r = subprocess.run(
        [sys.executable, str(warmer_script)],
        cwd=str(REPO_ROOT),
    )
    if r.returncode != 0:
        print(f"  ERROR: gen-image-warmer.py failed (exit {r.returncode})")
        return False

    print("  Image-warmer DaemonSet applied.")
    return True


# ── Step 6: Stress test ──────────────────────────────────────────────────────

def step_stress() -> bool:
    print("\n" + "=" * 60)
    print("STEP 6: Stress test (concurrent instance creation)")
    print("=" * 60)

    if not confirm("Run stress test?"):
        print("  Skipped.")
        return True

    stress_script = UTILS / "stress.py"
    print(f"  Running {stress_script}...")
    # stress.py is interactive (prompts for user count etc), so don't capture
    r = subprocess.run(
        [sys.executable, str(stress_script)],
        cwd=str(REPO_ROOT),
    )
    if r.returncode != 0:
        print(f"  WARNING: stress.py exited with code {r.returncode}")
    return True


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  WH Training Platform — Full Reset & Redeploy")
    print("=" * 60)
    print()
    print("This script will:")
    print("  1. Remove all deployed challenges from CTFd")
    print("  2. Destroy all running instances + stop VM")
    print("  3. Start VM + update configs + start services")
    print("  4. Deploy all challenges (build + push + API)")
    print("  5. Apply image-warmer DaemonSet")
    print("  6. Run stress test")
    print()
    print("Each step prompts for confirmation.")

    if not confirm("Ready to begin?"):
        print("Aborted.")
        return

    # Load env for API calls in steps 1-2
    env = load_env()
    base = env["CTFD_URL"].rstrip("/")
    headers = {
        "Authorization": f"Token {env['CTFD_TOKEN']}",
        "Content-Type": "application/json",
    }

    # Steps 1-2 use the current CTFd URL (before VM restart)
    step_remove_challenges(base, headers)
    step_shutdown(base, headers)

    # Step 3: startup.sh updates CTFD_URL in .ctf-deploy.env
    step_startup()

    # Reload env for steps 4+ (CTFD_URL may have changed after startup)
    env = load_env()
    base = env["CTFD_URL"].rstrip("/")
    headers = {
        "Authorization": f"Token {env['CTFD_TOKEN']}",
        "Content-Type": "application/json",
    }

    # Verify CTFd is reachable before deploying
    print("\n  Verifying CTFd is reachable...")
    for attempt in range(12):
        r = api_call("GET", f"{base}/api/v1/challenges?view=admin", headers)
        if r.get("success"):
            print(f"  CTFd OK at {base}")
            break
        print(f"  Not ready yet, waiting 10s... ({attempt+1}/12)")
        time.sleep(10)
    else:
        print(f"  WARNING: CTFd not reachable at {base} after 2 min — deploy may fail")

    # Steps 4-6: deploy first, then image warmer, then stress
    step_deploy()
    step_image_warmer()
    step_stress()

    print("\n" + "=" * 60)
    print("  Reset complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
