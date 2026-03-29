#!/usr/bin/env python3
"""
Shutdown: destroys all active challenge instances (cleans up GKE pods),
then stops the head-node VM.

CTFd data (challenges, scores, solves, submissions, files) lives on the
persistent disk and is fully preserved.

Usage: python3 scripts/shutdown.py
"""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ZONE     = "asia-southeast1-b"
INSTANCE = "ctf-head"
ENV_FILE = Path(__file__).parent.parent / ".ctf-deploy.env"


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


def ssh(cmd: str) -> str:
    r = subprocess.run(
        ["gcloud", "compute", "ssh", INSTANCE, f"--zone={ZONE}", f"--command={cmd}"],
        capture_output=True, text=True,
    )
    return r.stdout.strip()


def api_delete(url: str, token: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Token {token}", "Content-Type": "application/json"},
        method="DELETE",
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"success": False, "status": e.code, "error": e.read().decode()}


def main():
    env      = load_env()
    ctfd_url = env["CTFD_URL"]
    token    = env["CTFD_TOKEN"]

    # ── 1. wait for chall-manager API, then list instances ───────────────────
    print("[1/4] Fetching active instances from chall-manager...")

    raw = ""
    for attempt in range(1):  # up to 2 minutes
        raw = ssh("sudo docker exec ctfd-chall-manager-1 curl -sf http://localhost:8080/api/v1/instance 2>/dev/null")
        if raw:
            break
        print(f"  → chall-manager not ready yet, waiting 10s... ({attempt+1}/12)")
        time.sleep(10)

    instances = []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            instances = data
        else:
            instances = data.get("instances", [])
    except (json.JSONDecodeError, AttributeError):
        if raw:
            print(f"  Warning: unexpected response: {raw!r}")
        else:
            print("  Warning: chall-manager did not respond — will force-clean GKE pods")

    print(f"  Found {len(instances)} active instance(s)")

    if instances:
        print()
        for inst in instances:
            cid = inst.get("challengeId", inst.get("challenge_id", "?"))
            sid = inst.get("sourceId",    inst.get("source_id",    "?"))
            print(f"  challenge={cid} source={sid}")
        print()
        try:
            answer = input(f"About to destroy {len(instances)} running instance(s). Proceed? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer != "y":
            print("Aborted — no instances deleted. VM will not be stopped.")
            sys.exit(0)

    # ── 2. delete each instance via CTFd admin API ────────────────────────────
    print("[2/4] Deleting instances...")
    for inst in instances:
        cid = inst.get("challengeId", inst.get("challenge_id", "?"))
        sid = inst.get("sourceId",    inst.get("source_id",    "?"))
        print(f"  challenge={cid} source={sid} ...", end=" ", flush=True)
        url = (
            f"{ctfd_url}/api/v1/plugins/ctfd-chall-manager/admin/instance"
            f"?challengeId={cid}&sourceId={sid}"
        )
        result = api_delete(url, token)
        print("ok" if result.get("success") else f"warn: {result}")

    # ── 3. delete image-warmer + wait for GKE pods to drain ─────────────────
    print("[3/4] Cleaning up GKE namespace...")
    print("  Deleting image-warmer DaemonSet...")
    ssh("sudo kubectl delete ds image-warmer -n ctf-challenges --ignore-not-found 2>/dev/null")

    print("  Waiting for challenge pods to drain...")
    prompted = False
    for i in range(18):
        raw_pods = ssh(
            "sudo kubectl get pods -n ctf-challenges --no-headers 2>/dev/null"
        )
        if not raw_pods or not raw_pods.strip():
            print("  → GKE namespace empty")
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
                ssh("sudo kubectl delete all --all -n ctf-challenges --force --grace-period=0 2>/dev/null || true")
                break

        print(f"  Waiting 10s... ({elapsed}s elapsed)")
        time.sleep(10)
    else:
        print("  → Pods still present after 3 min — force-deleting")
        ssh("sudo kubectl delete all --all -n ctf-challenges --force --grace-period=0 2>/dev/null || true")
        print("  → Force-deleted.")

    # ── 4. stop VM ────────────────────────────────────────────────────────────
    print("[4/4] Stopping VM...")
    subprocess.run(
        ["gcloud", "compute", "instances", "stop", INSTANCE, f"--zone={ZONE}"],
        check=True,
    )

    print()
    print("Done.")
    print("  CTFd data (challenges, scores, solves, submissions) preserved on persistent disk.")
    print("  GKE autoscaler will scale to 0 nodes once pods finish terminating.")


if __name__ == "__main__":
    main()
