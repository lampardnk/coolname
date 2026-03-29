#!/usr/bin/env python3
"""
Stress test: concurrent instance creation across all dynamic_iac challenges.

Prompts for number of users (1-10), creates hidden admin accounts, generates
API tokens, then fires simultaneous instance creation requests per challenge.
Instances are left running. After testing, enters a live monitoring loop
showing CPU/mem/network/disk for the head VM, GKE nodes, and challenge pods.

Usage:
  python3 scripts/stress.py
"""

import concurrent.futures
import http.cookiejar
import json
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ENV_FILE = Path(__file__).parent.parent / ".ctf-deploy.env"

POLL_INTERVAL = 8   # seconds between connection_info polls
POLL_TIMEOUT  = 60  # max seconds to wait for instance ready
MONITOR_INTERVAL = 10  # seconds between monitoring refreshes

ZONE     = "asia-southeast1-b"
HEAD_VM  = "ctf-head"


# -- config -------------------------------------------------------------------

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


# -- CTFd API helpers ---------------------------------------------------------

def api_call(method: str, url: str, headers: dict, data=None) -> dict:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        msg = e.read().decode()
        return {"success": False, "http_status": e.code, "error": msg}
    except Exception as e:
        return {"success": False, "error": str(e)}


def admin_headers(token: str) -> dict:
    return {"Authorization": f"Token {token}", "Content-Type": "application/json"}


# -- account setup ------------------------------------------------------------

def find_user_by_name(base: str, headers: dict, name: str):
    """Return user ID if name exists, else None."""
    r = api_call("GET", f"{base}/api/v1/users?view=admin&field=name&q={name}", headers)
    for u in r.get("data", []):
        if u["name"] == name:
            return u["id"]
    return None


def create_or_find_user(base: str, headers: dict, user: dict) -> int:
    """Create stress user or find existing. Returns user ID."""
    existing = find_user_by_name(base, headers, user["name"])
    if existing:
        return existing

    email = f"{user['name']}-{int(time.time())}@stress.test"
    r = api_call("POST", f"{base}/api/v1/users", headers, {
        "name":     user["name"],
        "email":    email,
        "password": user["password"],
        "type":     "admin",
        "verified": True,
        "hidden":   True,
        "banned":   False,
    })
    if not r.get("success"):
        sys.exit(f"ERROR: Failed to create {user['name']}: {r.get('error', r)}")
    return r["data"]["id"]


def login_and_get_token(base: str, name: str, password: str) -> str:
    """Login as user via web form, then generate an API token. Returns token string."""
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    # GET /login to extract CSRF nonce
    resp = opener.open(f"{base}/login")
    html = resp.read().decode()
    m = re.search(r'name="nonce"[^>]*value="([^"]+)"', html)
    if not m:
        sys.exit(f"ERROR: Could not find CSRF nonce on login page")
    nonce = m.group(1)

    # POST /login
    login_data = urllib.parse.urlencode({
        "name": name, "password": password, "nonce": nonce,
    }).encode()
    opener.open(f"{base}/login", login_data)

    # Get csrfNonce from an authenticated page (needed for session-auth API calls)
    resp = opener.open(f"{base}/settings")
    html2 = resp.read().decode()
    m2 = re.search(r'csrfNonce[^a-zA-Z0-9]+([0-9a-f]{64})', html2)
    if not m2:
        sys.exit(f"ERROR: Could not find csrfNonce after login for {name}")
    csrf = m2.group(1)

    # POST /api/v1/tokens to generate API token
    req = urllib.request.Request(
        f"{base}/api/v1/tokens",
        data=b"{}",
        headers={"Content-Type": "application/json", "CSRF-Token": csrf},
        method="POST",
    )
    resp = opener.open(req)
    r = json.loads(resp.read())
    if not r.get("success"):
        sys.exit(f"ERROR: Failed to create token for {name}: {r}")
    return r["data"]["value"]


# -- instance creation worker -------------------------------------------------

def check_url(url: str, timeout: int = 10) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ctf-stress/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status < 400
    except urllib.error.HTTPError as e:
        return e.code < 400
    except Exception:
        return False


# -- OCI auth recovery --------------------------------------------------------

_oci_fix_lock = threading.Lock()
_oci_fixed = False  # only attempt once per run


def fix_oci_auth():
    """Restart chall-manager to re-authenticate to Artifact Registry."""
    global _oci_fixed
    with _oci_fix_lock:
        if _oci_fixed:
            return  # another thread already fixed it
        _oci_fixed = True
        print("\n  \033[93m[oci-fix]\033[0m OCI auth error detected — restarting chall-manager...")
        # Flush OCI cache and restart
        ssh(
            "sudo docker exec ctfd-chall-manager-1 sh -c "
            "'rm -rf /root/.cache/chall-manager/oci/*' 2>/dev/null; "
            "cd /opt/ctfd && sudo docker compose --env-file .env restart chall-manager",
            timeout=60,
        )
        # Wait for chall-manager to become healthy
        print("  \033[93m[oci-fix]\033[0m Waiting for chall-manager to come back up...", flush=True)
        deadline = time.time() + 60
        while time.time() < deadline:
            out = ssh("sudo docker inspect --format='{{.State.Health.Status}}' ctfd-chall-manager-1 2>/dev/null", timeout=10)
            if out == "healthy":
                print("  \033[93m[oci-fix]\033[0m chall-manager is healthy. Resuming.\n")
                return
            # Also accept "running" if no healthcheck is configured
            out2 = ssh("sudo docker inspect --format='{{.State.Status}}' ctfd-chall-manager-1 2>/dev/null", timeout=10)
            if out2 == "running" and out != "starting":
                print("  \033[93m[oci-fix]\033[0m chall-manager is running. Resuming.\n")
                return
            time.sleep(5)
        print("  \033[93m[oci-fix]\033[0m Timed out waiting — continuing anyway.\n")


def _is_oci_error(r: dict) -> bool:
    """Check if an API response indicates an OCI authentication/interaction failure."""
    for field in [r.get("error", ""), str(r.get("data", ""))]:
        if any(kw in str(field).lower() for kw in ["oci interaction", "oci auth", "oci error", "oci"]):
            return True
    return False


# -- instance creation --------------------------------------------------------

def create_instance(base: str, token: str, challenge_id: int, source_id: int):
    """
    Fire instance creation request with OCI auto-recovery.
    Returns (ok: bool, elapsed: float, detail: str).
    """
    h  = admin_headers(token)
    qs = f"?challengeId={challenge_id}&sourceId={source_id}"
    ep = f"{base}/api/v1/plugins/ctfd-chall-manager/admin/instance{qs}"

    t0 = time.time()
    r = api_call("POST", ep, h)
    elapsed = time.time() - t0

    if r.get("success"):
        return True, elapsed, "create accepted"

    err = str(r.get("error", "")).lower()
    already = "already exist" in str(r.get("data", {}).get("message", "")).lower()
    timed_out = "timed out" in err or "timeout" in err
    if already:
        return True, elapsed, "already exists"
    if timed_out:
        return True, elapsed, "create sent (server timeout, may still be provisioning)"

    # OCI auth failure — fix and retry once
    if _is_oci_error(r) and not _oci_fixed:
        fix_oci_auth()
        # Retry
        t0 = time.time()
        r = api_call("POST", ep, h)
        elapsed = time.time() - t0
        if r.get("success"):
            return True, elapsed, "create accepted (after oci fix)"
        already = "already exist" in str(r.get("data", {}).get("message", "")).lower()
        if already:
            return True, elapsed, "already exists (after oci fix)"

    return False, elapsed, f"create failed: {r.get('error', r)}"


def poll_connection_info(base: str, token: str, challenge_id: int, source_id: int,
                         timeout: int = POLL_TIMEOUT):
    """
    Poll until connection_info is available. Verifies web URLs.
    Returns (ok: bool, elapsed: float, detail: str).
    """
    h  = admin_headers(token)
    qs = f"?challengeId={challenge_id}&sourceId={source_id}"
    ep = f"{base}/api/v1/plugins/ctfd-chall-manager/admin/instance{qs}"

    t0 = time.time()
    deadline = t0 + timeout
    while time.time() < deadline:
        r = api_call("GET", ep, h)
        if r.get("success"):
            conn = r.get("data", {}).get("connectionInfo", "")
            if conn:
                elapsed = time.time() - t0
                if conn.startswith("http"):
                    ok = check_url(conn)
                    status = "reachable" if ok else "unreachable"
                    return ok, elapsed, f"{conn} ({status})"
                return True, elapsed, conn
        time.sleep(POLL_INTERVAL)

    return False, time.time() - t0, f"no connection_info after {timeout}s"


# -- SSH / kubectl helpers for monitoring -------------------------------------

def ssh(cmd: str, timeout: int = 15) -> str:
    """Run command on head VM via gcloud SSH. Returns stdout or empty on error."""
    try:
        r = subprocess.run(
            ["gcloud", "compute", "ssh", HEAD_VM, f"--zone={ZONE}",
             f"--command={cmd}"],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def run_local(cmd: list, timeout: int = 15) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


# -- monitoring ---------------------------------------------------------------

def monitor_head_vm() -> str:
    """Get CPU, mem, network, disk stats from ctf-head VM."""
    # Single SSH call with multiple commands
    cmd = (
        # CPU: 1-second average via top
        "echo '=CPU=';"
        "top -bn1 | grep '%Cpu' | head -1;"
        # Memory
        "echo '=MEM=';"
        "free -h | grep -E 'Mem|Swap';"
        # Disk
        "echo '=DISK=';"
        "df -h / | tail -1;"
        # Network: bytes rx/tx on primary interface
        "echo '=NET=';"
        "cat /proc/net/dev | grep -E 'ens|eth' | head -1;"
        # Docker container stats (one-shot)
        "echo '=DOCKER=';"
        "sudo docker stats --no-stream --format "
        "'{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}' 2>/dev/null | head -10"
    )
    return ssh(cmd, timeout=20)


def monitor_gke_nodes() -> str:
    """Get GKE node resource usage via kubectl top."""
    return ssh("sudo kubectl top nodes 2>/dev/null", timeout=15)


def monitor_gke_pods() -> str:
    """Get per-pod resource usage in ctf-challenges namespace."""
    return ssh(
        "sudo kubectl top pods -n ctf-challenges --no-headers 2>/dev/null | sort -k2 -rh",
        timeout=15,
    )


def monitor_pod_count() -> str:
    """Get pod counts by status."""
    return ssh(
        "sudo kubectl get pods -n ctf-challenges --no-headers 2>/dev/null "
        "| awk '{print $3}' | sort | uniq -c | sort -rn",
        timeout=15,
    )


def print_monitor():
    """Print one monitoring snapshot."""
    print(f"\n{'=' * 60}")
    print(f"  MONITORING  [{time.strftime('%H:%M:%S')}]  (Ctrl+C to stop)")
    print(f"{'=' * 60}")

    # Head VM
    raw = monitor_head_vm()
    if raw:
        print(f"\n-- Head VM ({HEAD_VM}) --")
        section = ""
        for line in raw.split("\n"):
            if line.startswith("=") and line.endswith("="):
                section = line.strip("=")
                continue
            if not line.strip():
                continue
            if section == "CPU":
                print(f"  CPU:  {line.strip()}")
            elif section == "MEM":
                print(f"  Mem:  {line.strip()}")
            elif section == "DISK":
                parts = line.split()
                if len(parts) >= 5:
                    print(f"  Disk: {parts[2]} used / {parts[1]} total ({parts[4]} full)")
            elif section == "NET":
                # /proc/net/dev format: iface: rx_bytes ... tx_bytes ...
                parts = line.split()
                if len(parts) >= 10:
                    iface = parts[0].rstrip(":")
                    rx_mb = int(parts[1]) / 1024 / 1024
                    tx_mb = int(parts[9]) / 1024 / 1024
                    print(f"  Net:  {iface}  rx={rx_mb:.1f}MB  tx={tx_mb:.1f}MB")
            elif section == "DOCKER":
                if section == "DOCKER" and line.strip():
                    print(f"  {line}")
    else:
        print(f"\n-- Head VM ({HEAD_VM}) -- (SSH failed)")

    # GKE nodes
    print(f"\n-- GKE Nodes --")
    nodes = monitor_gke_nodes()
    if nodes:
        for line in nodes.split("\n"):
            print(f"  {line}")
    else:
        print("  (kubectl top nodes failed)")

    # Pod summary
    counts = monitor_pod_count()
    if counts:
        print(f"\n-- Pod Status --")
        for line in counts.strip().split("\n"):
            print(f"  {line.strip()}")

    # Per-pod usage
    print(f"\n-- Challenge Pods (by CPU) --")
    pods = monitor_gke_pods()
    if pods:
        print(f"  {'POD':<55} {'CPU':>6} {'MEM':>10}")
        for line in pods.split("\n"):
            parts = line.split()
            if len(parts) >= 3:
                print(f"  {parts[0]:<55} {parts[1]:>6} {parts[2]:>10}")
    else:
        print("  (no pods or kubectl top failed)")


# -- main ---------------------------------------------------------------------

def main():
    env      = load_env()
    base     = env["CTFD_URL"].rstrip("/")
    adm_tok  = env["CTFD_TOKEN"]
    adm_h    = admin_headers(adm_tok)

    print("stress.py -- CTF Instance Stress Test")
    print("-" * 50)

    # -- restart chall-manager for clean OCI auth ------------------------------
    print("\nRestarting chall-manager (fresh OCI auth)...", flush=True)
    ssh(
        "sudo docker exec ctfd-chall-manager-1 sh -c "
        "'rm -rf /root/.cache/chall-manager/oci/*' 2>/dev/null; "
        "cd /opt/ctfd && sudo docker compose --env-file .env restart chall-manager",
        timeout=60,
    )
    deadline = time.time() + 60
    while time.time() < deadline:
        out = ssh("sudo docker inspect --format='{{.State.Status}}' ctfd-chall-manager-1 2>/dev/null", timeout=10)
        if out == "running":
            break
        time.sleep(5)
    print("  chall-manager ready.\n")

    # -- prompt for user count -------------------------------------------------
    while True:
        try:
            n = int(input("Number of concurrent users (1-10): ").strip())
            if 1 <= n <= 10:
                break
            print("  Enter a number between 1 and 10.")
        except (ValueError, EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)

    # -- prompt for connection info timeout ------------------------------------
    while True:
        try:
            raw = input(f"Connection info timeout in seconds [{POLL_TIMEOUT}]: ").strip()
            if not raw:
                poll_timeout = POLL_TIMEOUT
                break
            poll_timeout = int(raw)
            if poll_timeout > 0:
                break
            print("  Enter a positive number.")
        except (ValueError, EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)

    stress_users = [
        {"name": f"stress{i}", "password": f"stress{i}"}
        for i in range(n)
    ]

    # -- phase 0: setup accounts -----------------------------------------------
    print(f"\nSetup ({n} user(s))")
    users = []  # list of {name, id, token}
    for u in stress_users:
        uid = create_or_find_user(base, adm_h, u)
        tok = login_and_get_token(base, u["name"], u["password"])
        users.append({"name": u["name"], "id": uid, "token": tok})
        print(f"  {u['name']}  id={uid}  token={tok[:20]}...")

    # -- list dynamic_iac challenges, detect satellites --------------------------
    r = api_call("GET", f"{base}/api/v1/challenges?view=admin", adm_h)
    if not r.get("success"):
        sys.exit(f"ERROR: failed to list challenges: {r}")

    all_dynamic = [c for c in r.get("data", []) if c.get("type") == "dynamic_iac"]

    # Build satellite map: {satellite_id: master_id}
    satellite_map = {}
    print(f"  Scanning {len(all_dynamic)} dynamic_iac challenge(s) for groups...")
    for chal in all_dynamic:
        detail = api_call("GET", f"{base}/api/v1/challenges/{chal['id']}", adm_h)
        additional = (detail.get("data") or {}).get("additional") or {}
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

    # Only test non-satellite challenges (masters + standalone)
    challenges = [c for c in all_dynamic if c["id"] not in satellite_map]
    skipped = len(all_dynamic) - len(challenges)

    if satellite_map:
        id_to_name = {c["id"]: c["name"] for c in all_dynamic}
        print(f"  {skipped} satellite(s) skipped (share master instance):")
        for sat_id, master_id in satellite_map.items():
            print(f"    [{id_to_name.get(sat_id, sat_id)}] -> [{id_to_name.get(master_id, master_id)}]")

    total_instances = len(challenges) * n
    print(f"  Testing {len(challenges)} challenge(s) x {n} user(s) = {total_instances} instance(s) to spawn ({skipped} satellites skipped)\n")

    if not challenges:
        print("Nothing to test.")
        return

    # -- phase 1: fire all instance creation requests ---------------------------
    # Track all (challenge, user) pairs for optional connection info check later
    all_pairs = []  # list of (chal, user, ok, elapsed, detail)
    results = []

    for idx, chal in enumerate(challenges, 1):
        cid  = chal["id"]
        name = chal["name"]
        print(f"Deploying [{name}] ({idx}/{len(challenges)})")

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(users)) as pool:
            futures = {
                pool.submit(create_instance, base, u["token"], cid, u["id"]): u
                for u in users
            }
            user_results = []
            for future in concurrent.futures.as_completed(futures):
                u = futures[future]
                ok, elapsed, detail = future.result()
                if ok:
                    status = "PASS"
                else:
                    status = "\033[91mFAIL\033[0m"
                print(f"  {u['name']}  {status}  {elapsed:.1f}s  {detail}")
                user_results.append({
                    "name": u["name"], "ok": ok, "elapsed": elapsed, "detail": detail,
                })
                all_pairs.append((chal, u, ok))

        results.append({"name": name, "user_results": user_results})
        print()

    # -- phase 2: deployment summary -------------------------------------------
    print("-" * 50)
    total    = sum(len(r["user_results"]) for r in results)
    passed   = sum(1 for r in results for ur in r["user_results"] if ur["ok"])
    failed   = total - passed
    all_times = [ur["elapsed"] for r in results for ur in r["user_results"] if ur["ok"]]
    avg_time  = sum(all_times) / len(all_times) if all_times else 0

    if failed:
        print(f"Deploy results: {passed}/{total} accepted  \033[91m{failed} failed\033[0m")
    else:
        print(f"Deploy results: {passed}/{total} accepted  {failed} failed")
    if all_times:
        print(f"Avg request time: {avg_time:.1f}s  (min {min(all_times):.1f}s / max {max(all_times):.1f}s)")
    print(f"All instances left running.")

    # -- phase 2b: optional connection info check ------------------------------
    ok_pairs = [(chal, u) for chal, u, ok in all_pairs if ok]
    if ok_pairs:
        print()
        try:
            answer = input(f"Check connection_info for {len(ok_pairs)} instance(s)? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"

        if answer == "y":
            print(f"\nPolling connection_info (timeout {poll_timeout}s each)...")
            conn_passed = 0
            conn_failed = 0
            for chal, u in ok_pairs:
                print(f"  [{chal['name']}] {u['name']} ...", end=" ", flush=True)
                ok, elapsed, detail = poll_connection_info(
                    base, u["token"], chal["id"], u["id"],
                    timeout=poll_timeout,
                )
                if ok:
                    print(f"PASS  {elapsed:.1f}s  {detail}")
                    conn_passed += 1
                else:
                    print(f"\033[91mFAIL\033[0m  {elapsed:.1f}s  {detail}")
                    conn_failed += 1

            print(f"\nConnection check: {conn_passed}/{conn_passed + conn_failed} reachable"
                  + (f"  \033[91m{conn_failed} failed\033[0m" if conn_failed else ""))

    # -- phase 3: live monitoring ----------------------------------------------
    print(f"\nEntering live monitoring (every {MONITOR_INTERVAL}s, Ctrl+C to stop)...")
    try:
        while True:
            print_monitor()
            time.sleep(MONITOR_INTERVAL)
    except KeyboardInterrupt:
        print("\n\nMonitoring stopped.")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
