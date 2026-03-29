#!/usr/bin/env python3
"""
Healthcheck: validates every challenge in CTFd.

  Phase 0 — teardown (with confirmation prompt):
    - Lists all active admin instances (sourceId=ADMIN_SOURCE_ID)
    - Prompts before deleting them, then polls until the namespace is clear

  dynamic_iac (web/pwn):
    - Creates a fresh admin test instance (bypasses mana)
    - Polls until connection_info is returned (up to 2 min)
    - For web (http://...): checks the URL returns HTTP 200
    - Grouped challenges (group_master_id in additional): satellites reuse the
      master's already-created instance instead of spawning a duplicate

  standard (static):
    - Checks every attached file download link returns HTTP 200

Usage: python3 scripts/healthcheck.py
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ENV_FILE = Path(__file__).parent.parent / ".ctf-deploy.env"

# ── config ────────────────────────────────────────────────────────────────────
INSTANCE_POLL_INTERVAL  = 8    # seconds between polls waiting for connection_info
INSTANCE_POLL_TIMEOUT   = 90  # max seconds to wait for instance to be ready
DRAIN_POLL_INTERVAL     = 10   # seconds between polls while waiting for teardown
DRAIN_TIMEOUT           = 60  # max seconds to wait for all instances to go away
ADMIN_SOURCE_ID         = 1    # source_id used for healthcheck instances (admin user)


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


# ── CTFd API ──────────────────────────────────────────────────────────────────

class CTFdAPI:
    def __init__(self, url: str, token: str):
        self.base  = url.rstrip("/")
        self.token = token
        self._h    = {
            "Authorization": f"Token {token}",
            "Content-Type":  "application/json",
        }

    def _call(self, method: str, path: str) -> dict:
        req = urllib.request.Request(
            f"{self.base}{path}", headers=self._h, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return {"success": False, "http_status": e.code, "error": e.read().decode()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get(self, path):    return self._call("GET",    path)
    def post(self, path):   return self._call("POST",   path)
    def delete(self, path): return self._call("DELETE", path)


# ── URL reachability ──────────────────────────────────────────────────────────

def check_url(url: str, timeout: int = 15) -> tuple:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ctf-healthcheck/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status < 400, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return e.code < 400, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)


# ── group challenge helpers ───────────────────────────────────────────────────

def build_satellite_map(api: CTFdAPI, challenges: list) -> dict:
    """
    Return {satellite_challenge_id: master_challenge_id} for all dynamic_iac
    challenges that have additional.group_master_id set.
    """
    satellite_map = {}
    for chal in challenges:
        if chal.get("type") != "dynamic_iac":
            continue
        r = api.get(f"/api/v1/challenges/{chal['id']}")
        additional = (r.get("data") or {}).get("additional") or {}
        if isinstance(additional, str):
            try:
                additional = json.loads(additional)
            except (json.JSONDecodeError, ValueError):
                additional = {}
        master_id_str = additional.get("group_master_id", "")
        if master_id_str:
            try:
                satellite_map[chal["id"]] = int(master_id_str)
            except ValueError:
                pass
    return satellite_map


# ── phase 0: teardown existing admin instances ────────────────────────────────

def list_admin_instances(api: CTFdAPI, challenges: list) -> list:
    """Return list of (chal, qs) tuples for challenges that have an active admin instance."""
    active = []
    for chal in challenges:
        if chal.get("type") != "dynamic_iac":
            continue
        cid = chal["id"]
        qs  = f"?challengeId={cid}&sourceId={ADMIN_SOURCE_ID}"
        r   = api.get(f"/api/v1/plugins/ctfd-chall-manager/admin/instance{qs}")
        if r.get("success") and r.get("data", {}).get("connectionInfo") is not None:
            active.append((chal, qs))
    return active


def teardown_all(api: CTFdAPI, challenges: list):
    """Prompt then delete all active admin instances, wait for them to disappear."""
    print("Phase 0 — Teardown existing admin instances")
    print("  Scanning for active instances...", flush=True)

    active = list_admin_instances(api, challenges)
    if not active:
        print("  No active admin instances found.\n")
        return

    print(f"  Found {len(active)} active instance(s):")
    for chal, _ in active:
        print(f"    [{chal['name']}]")
    print()

    try:
        answer = input(f"Tear down these {len(active)} instance(s) before healthcheck? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"

    if answer != "y":
        print("  Skipping teardown — existing instances may interfere with healthcheck results.\n")
        return

    print(f"  Deleting {len(active)} instance(s):")
    for chal, qs in active:
        print(f"    [{chal['name']}] ...", end=" ", flush=True)
        api.delete(f"/api/v1/plugins/ctfd-chall-manager/admin/instance{qs}")
        print("delete sent")

    # Poll until all are gone
    print(f"  Waiting for instances to terminate (max {DRAIN_TIMEOUT}s)...")
    deadline = time.time() + DRAIN_TIMEOUT
    while time.time() < deadline:
        remaining = list_admin_instances(api, challenges)
        if not remaining:
            print("  All instances terminated.\n")
            return
        names = ", ".join(c["name"] for c, _ in remaining)
        elapsed = int(DRAIN_TIMEOUT - (deadline - time.time()))
        print(f"  Still running ({elapsed}s): {names} — retrying in {DRAIN_POLL_INTERVAL}s...", flush=True)
        time.sleep(DRAIN_POLL_INTERVAL)

    # Timed out — report and continue anyway
    remaining = list_admin_instances(api, challenges)
    if remaining:
        names = ", ".join(c["name"] for c, _ in remaining)
        print(f"  WARNING: {len(remaining)} instance(s) still present after {DRAIN_TIMEOUT}s: {names}")
        print("  Continuing with healthcheck anyway.\n")
    else:
        print("  All instances terminated.\n")


# ── per-type checks ───────────────────────────────────────────────────────────

def check_dynamic(api: CTFdAPI, chal: dict) -> tuple:
    """
    Create admin test instance, wait for connection_info, optionally check URL.
    Returns (ok: bool, detail: str).
    Does NOT delete the instance — caller decides after confirmation.
    """
    cid = chal["id"]
    sid = ADMIN_SOURCE_ID
    qs  = f"?challengeId={cid}&sourceId={sid}"

    # create (or accept already-exists / client-side timeout — instance may still be provisioning)
    r = api.post(f"/api/v1/plugins/ctfd-chall-manager/admin/instance{qs}")
    if not r.get("success"):
        err = str(r.get("error", "")).lower()
        already   = "already exist" in str(r.get("data", {}).get("message", ""))
        timed_out = "timed out" in err or "timeout" in err
        if not already and not timed_out:
            return False, f"create failed: {r.get('error', r)}"

    # poll for connection_info
    conn_info = ""
    deadline  = time.time() + INSTANCE_POLL_TIMEOUT
    dots      = 0
    while time.time() < deadline:
        r = api.get(f"/api/v1/plugins/ctfd-chall-manager/admin/instance{qs}")
        if r.get("success"):
            conn_info = r.get("data", {}).get("connectionInfo", "")
            if conn_info:
                break
        dots += 1
        print("." if dots % 5 else f"({int(deadline - time.time())}s left)", end="", flush=True)
        time.sleep(INSTANCE_POLL_INTERVAL)

    if not conn_info:
        return False, f"no connection_info after {INSTANCE_POLL_TIMEOUT}s"

    # for web challenges, also verify the URL is reachable
    ok, url_detail = True, ""
    if conn_info.startswith("http"):
        ok, url_detail = check_url(conn_info)
        detail = f"{conn_info} → {url_detail}"
    else:
        detail = f"connection_info: {conn_info}"

    return ok, detail


def check_static(api: CTFdAPI, chal: dict) -> tuple:
    """Check all file download links. Returns (ok: bool, detail: str)."""
    r = api.get(f"/api/v1/challenges/{chal['id']}")
    if not r.get("success"):
        return False, f"failed to fetch challenge detail: {r.get('error', r)}"

    files = r.get("data", {}).get("files", [])
    if not files:
        return True, "no files attached"

    results = []
    all_ok  = True
    for f in files:
        url      = f"{api.base}/{f.lstrip('/')}"
        ok, stat = check_url(url)
        results.append(f"{f.split('/')[-1]} → {stat}")
        if not ok:
            all_ok = False

    return all_ok, ", ".join(results)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    env = load_env()
    api = CTFdAPI(env["CTFD_URL"], env["CTFD_TOKEN"])

    print(f"Healthcheck: {env['CTFD_URL']}")
    print("─" * 60)

    r = api.get("/api/v1/challenges?view=admin")
    if not r.get("success"):
        sys.exit(f"ERROR: failed to list challenges: {r}")

    challenges = r.get("data", [])
    print(f"Found {len(challenges)} challenge(s)\n")

    # ── build satellite map (group_master_id delegation) ──────────────────────
    print("Scanning for grouped challenges...", flush=True)
    satellite_map = build_satellite_map(api, challenges)
    if satellite_map:
        print(f"  {len(satellite_map)} satellite challenge(s) detected — will reuse master instance:")
        id_to_name = {c["id"]: c["name"] for c in challenges}
        for sat_id, master_id in satellite_map.items():
            print(f"    [{id_to_name.get(sat_id, sat_id)}] → master [{id_to_name.get(master_id, master_id)}]")
    else:
        print("  No grouped challenges found.")
    print()

    # ── phase 0: clean slate ──────────────────────────────────────────────────
    teardown_all(api, challenges)

    # ── phase 1: healthcheck ──────────────────────────────────────────────────
    print("Phase 1 — Healthcheck")
    passed, failed, skipped = 0, 0, 0
    created_dynamic = []   # (chal, qs) for instances we created this run
    master_results  = {}   # master_id -> (ok, detail) so satellites can look up

    for chal in challenges:
        name  = chal["name"]
        cid   = chal["id"]
        ctype = chal.get("type", "?")
        state = chal.get("state", "?")
        label = f"[{ctype}] {name}"

        if state == "hidden":
            print(f"  {label}  →  skip (hidden)")
            skipped += 1
            continue

        print(f"  {label}  ...", end=" ", flush=True)

        if ctype == "dynamic_iac":
            if cid in satellite_map:
                # Satellite challenge: reuse master's instance result
                master_id = satellite_map[cid]
                if master_id in master_results:
                    ok, detail = master_results[master_id]
                    master_name = next((c["name"] for c in challenges if c["id"] == master_id), str(master_id))
                    status = "PASS" if ok else "FAIL"
                    print(f"  {status}  shared instance with [{master_name}] → {detail}")
                else:
                    # Master hasn't been checked yet (shouldn't happen if master ID < satellite ID)
                    ok, detail = False, f"master id={master_id} not yet checked"
                    print(f"  WARN  {detail}")
            else:
                # Master or standalone challenge: create instance
                ok, detail = check_dynamic(api, chal)
                master_results[cid] = (ok, detail)
                if ok:
                    created_dynamic.append((chal, f"?challengeId={cid}&sourceId={ADMIN_SOURCE_ID}"))
                status = "PASS" if ok else "FAIL"
                print(f"  {status}  {detail}")

        elif ctype in ("standard", "multiple_choice"):
            ok, detail = check_static(api, chal)
            status = "PASS" if ok else "FAIL"
            print(f"  {status}  {detail}")

        else:
            print("skip (unhandled type)")
            skipped += 1
            continue

        if ok:
            passed += 1
        else:
            failed += 1

    print()
    print("─" * 60)
    print(f"Results: {passed} passed  {failed} failed  {skipped} skipped")

    # ── phase 2: confirm teardown ─────────────────────────────────────────────
    if created_dynamic:
        print()
        print(f"{len(created_dynamic)} admin instance(s) are still running:")
        for chal, _ in created_dynamic:
            print(f"  [{chal['name']}]")
        print()
        try:
            answer = input("Tear down all admin instances now? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"

        if answer == "y":
            print("Tearing down...")
            for chal, qs in created_dynamic:
                print(f"  [{chal['name']}] ...", end=" ", flush=True)
                api.delete(f"/api/v1/plugins/ctfd-chall-manager/admin/instance{qs}")
                print("done")
            print("All admin instances removed.")
        else:
            print("Instances left running.")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
