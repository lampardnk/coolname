#!/usr/bin/env python3
"""
CTF Challenge Deployer
Builds and deploys web/pwn/static challenges to CTFd + chall-manager.

Usage:
  python3 deploy.py --all                                    # deploy every challenges/**/challenge.yml
  python3 deploy.py --dir challenges/test-web/sqli-login     # deploy one challenge
  python3 deploy.py --dir challenges/test-web --force       # delete & re-create if exists
  python3 deploy.py --dir challenges/test-web --dry-run     # print steps, do nothing
  python3 deploy.py --dir challenges/test-web --skip-build  # skip docker/oras, API only

Requirements (local machine):
  pip3 install pyyaml
  docker, gcloud, oras, go  (for web/pwn challenges)
  curl                       (for file uploads)

challenge.yml reference:
  see challenges/test-web/challenge.yml for a fully-commented example
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("ERROR: pyyaml not installed — run: pip3 install pyyaml")

REPO_ROOT = Path(__file__).parent.parent.parent
ENV_FILE  = Path(__file__).parent.parent / ".ctf-deploy.env"


# ── config ────────────────────────────────────────────────────────────────────

def load_env() -> dict:
    if not ENV_FILE.exists():
        sys.exit(
            f"ERROR: {ENV_FILE} not found.\n"
            f"Copy scripts/.ctf-deploy.env.example, fill it in, then retry."
        )
    env = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    required = ["CTFD_URL", "CTFD_TOKEN", "AR_IMAGES", "AR_SCENARIOS", "TRAEFIK_IP"]
    missing = [k for k in required if k not in env]
    if missing:
        sys.exit(f"ERROR: Missing keys in .ctf-deploy.env: {', '.join(missing)}")
    return env


# ── CTFd API ─────────────────────────────────────────────────────────────────

class CTFdAPI:
    def __init__(self, url: str, token: str):
        self.base  = url.rstrip("/")
        self.token = token
        self._headers = {
            "Authorization": f"Token {token}",
            "Content-Type":  "application/json",
        }

    def _call(self, method: str, path: str, data=None) -> dict:
        body = json.dumps(data).encode() if data is not None else None
        req  = urllib.request.Request(
            f"{self.base}{path}", data=body, headers=self._headers, method=method
        )
        try:
            with urllib.request.urlopen(req) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            msg = e.read().decode()
            sys.exit(f"ERROR: CTFd API {method} {path} → HTTP {e.code}: {msg}")

    def get(self,    path):        return self._call("GET",    path)
    def post(self,   path, data):  return self._call("POST",   path, data)
    def patch(self,  path, data):  return self._call("PATCH",  path, data)
    def delete(self, path):        return self._call("DELETE", path)

    def find_challenge(self, name: str):
        """Return challenge ID if name exists (admin view), else None."""
        for c in self.get("/api/v1/challenges?view=admin").get("data", []):
            if c["name"] == name:
                return c["id"]
        return None

    def upload_file(self, challenge_id: int, filepath: Path) -> None:
        """Upload a handout file to a challenge (multipart via curl)."""
        _run(["curl", "-sf",
              "-H", f"Authorization: Token {self.token}",
              "-F", f"file=@{filepath}",
              "-F", f"challenge={challenge_id}",
              "-F", "type=challenge",
              f"{self.base}/api/v1/files"])


# ── shell helpers ─────────────────────────────────────────────────────────────

def _run(cmd: list, cwd=None, extra_env: dict = None, capture=True, dry_run=False) -> str:
    """Run a command; exit on non-zero. Returns stdout if capture=True."""
    print("    $", " ".join(str(c) for c in cmd))
    if dry_run:
        return "(dry-run)"
    env = {**os.environ, **(extra_env or {})}
    r = subprocess.run(
        cmd, cwd=cwd, env=env,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        text=True,
    )
    if r.returncode != 0:
        if capture and r.stderr:
            print(f"    stderr: {r.stderr.strip()}")
        sys.exit(f"    FAILED (exit {r.returncode})")
    return r.stdout.strip() if capture else ""


def _gcloud_token() -> str:
    return subprocess.check_output(["gcloud", "auth", "print-access-token"]).decode().strip()


def _oras_login(registry: str, dry_run: bool) -> None:
    if dry_run:
        return
    token = _gcloud_token()
    r = subprocess.run(
        ["oras", "login", registry, "-u", "oauth2accesstoken", "--password-stdin"],
        input=token, text=True, check=True, capture_output=True,
    )
    if r.returncode != 0:
        sys.exit(f"oras login failed: {r.stderr}")


# ── step: docker build + push ─────────────────────────────────────────────────

def step_image(chall_dir: Path, cfg: dict, env: dict, dry_run: bool) -> None:
    image_dir = chall_dir / "image"
    if not image_dir.exists():
        return
    ref = f"{env['AR_IMAGES']}/{cfg['slug']}:latest"
    print(f"  [docker] {ref}")
    _run(
        ["docker", "build", "--platform", "linux/amd64", "-t", ref, "."],
        cwd=image_dir, capture=False, dry_run=dry_run,
    )
    _run(["docker", "push", ref], capture=False, dry_run=dry_run)


# ── step: go build + oras push ────────────────────────────────────────────────

def step_scenario(chall_dir: Path, cfg: dict, env: dict, dry_run: bool) -> str:
    """Build Go binary and push OCI scenario. Returns the full OCI ref."""
    scenario_dir = chall_dir / "scenario"
    if not scenario_dir.exists():
        return ""
    ref      = f"{env['AR_SCENARIOS']}/{cfg['slug']}:latest"
    registry = env["AR_SCENARIOS"].split("/")[0]

    print(f"  [go] Building scenario binary (linux/amd64)")
    _run(
        ["go", "build", "-o", "main", "."],
        cwd=scenario_dir,
        extra_env={"CGO_ENABLED": "0", "GOOS": "linux", "GOARCH": "amd64"},
        capture=False,
        dry_run=dry_run,
    )

    print(f"  [oras] Pushing {ref}")
    _oras_login(registry, dry_run)
    _run(
        ["oras", "push",
         "--artifact-type", "application/vnd.ctfer-io.scenario",
         ref,
         "main:application/vnd.ctfer-io.file",
         "Pulumi.yaml:application/vnd.ctfer-io.file"],
        cwd=scenario_dir, capture=False, dry_run=dry_run,
    )

    # chall-manager caches OCI tag→digest in memory.
    # After a re-push to the same tag, the old binary will be used until chall-manager
    # is restarted. Remind the user if this is likely an update.
    print("  [note] If updating an existing scenario, restart chall-manager on the head node:")
    print("         gcloud compute ssh ctf-head --zone=asia-southeast1-b --command=")
    print('         "cd /opt/ctfd && sudo docker compose --env-file .env restart chall-manager"')

    return ref


# ── step: CTFd API ────────────────────────────────────────────────────────────

def step_ctfd(
    chall_dir: Path, cfg: dict, env: dict,
    scenario_ref: str, api: CTFdAPI,
    force: bool, dry_run: bool,
    slug_registry: dict = None,
) -> None:
    name      = cfg["name"]
    chal_type = cfg["type"]  # web | pwn | static

    # idempotency check
    existing_id = None if dry_run else api.find_challenge(name)
    if existing_id:
        if not force:
            print(f"  [ctfd] '{name}' already exists (id={existing_id}) — skipping.")
            print(f"         Use --force to delete and re-create.")
            return
        print(f"  [ctfd] Deleting existing '{name}' (id={existing_id})")
        if not dry_run:
            api.delete(f"/api/v1/challenges/{existing_id}")

    # additional config — domain is auto-filled from TRAEFIK_IP unless overridden
    # node_ip is auto-filled from GKE node for pwn challenges (NodePort routing)
    additional = dict(cfg.get("additional", {}))
    if chal_type in ("web", "pwn") and "domain" not in additional:
        additional["domain"] = f"{env['TRAEFIK_IP']}.nip.io"
    if chal_type == "pwn" and "node_ip" not in additional:
        additional["node_ip"] = env.get("NODE_IP", "")

    # Resolve group_master_slug → group_master_id for satellite challenges
    if "group_master_slug" in additional:
        master_slug = additional.pop("group_master_slug")
        resolved_id = None
        # Check local registry first (populated during --all runs)
        if slug_registry and master_slug in slug_registry:
            resolved_id = slug_registry[master_slug]
        # Fallback: read master's challenge.yml, look up by name in CTFd
        if not resolved_id and not dry_run:
            master_yml = chall_dir.parent / master_slug / "challenge.yml"
            if master_yml.exists():
                master_cfg = yaml.safe_load(master_yml.read_text())
                resolved_id = api.find_challenge(master_cfg["name"])
        if resolved_id:
            additional["group_master_id"] = str(resolved_id)
            print(f"  [group] Resolved master '{master_slug}' → id={resolved_id}")
        elif dry_run:
            additional["group_master_id"] = f"<resolved from {master_slug} at deploy time>"
            print(f"  [group] Will resolve master '{master_slug}' → group_master_id at deploy time")
        else:
            print(f"  [group] WARN: Could not resolve master '{master_slug}' — satellite grouping may not work")

    # build payload
    # Field name mapping (challenge.yml → CTFd API):
    #   value    → initial  (DynamicValueChallenge parent; also needs minimum+decay)
    #   mana     → mana_cost
    #   duration → timeout  (seconds as integer; plugin converts to "Xs" for chall-manager)
    if chal_type in ("web", "pwn"):
        payload = {
            "name":        name,
            "category":    cfg["category"],
            "description": cfg.get("description", ""),
            "initial":     cfg["value"],
            "minimum":     cfg.get("minimum", 0),
            "decay":       cfg.get("decay", 0),
            "type":        "dynamic_iac",
            "scenario":    cfg.get("scenario") or scenario_ref or f"{env['AR_SCENARIOS']}/{cfg['slug']}:latest",
            "mana_cost":   cfg.get("mana", 1),
            "timeout":     cfg.get("duration", 3600),
            "additional":  additional,
            "state":       cfg.get("state", "hidden"),
        }
    else:  # static
        payload = {
            "name":        name,
            "category":    cfg["category"],
            "description": cfg.get("description", ""),
            "initial":     cfg["value"],
            "minimum":     cfg.get("minimum", 0),
            "decay":       cfg.get("decay", 0),
            "type":        "standard",
            "state":       cfg.get("state", "hidden"),
        }

    print(f"  [ctfd] Creating '{name}' (type={payload['type']}, state={payload['state']})")
    if dry_run:
        print(f"         payload: {json.dumps(payload, indent=10)}")
        return

    r            = api.post("/api/v1/challenges", payload)
    challenge_id = r["data"]["id"]
    print(f"         → id={challenge_id}")

    # Register slug → id for satellite resolution in subsequent deploys
    if slug_registry is not None:
        slug_registry[cfg["slug"]] = challenge_id

    # flags
    flags = cfg.get("flag", [])
    if isinstance(flags, str):
        flags = [flags]
    for flag in flags:
        api.post("/api/v1/flags", {
            "challenge": challenge_id,
            "type":      "static",
            "content":   flag,
        })
        print(f"         → flag: {flag}")

    # hints
    for hint in cfg.get("hints", []):
        if isinstance(hint, str):
            hint = {"content": hint, "cost": 0}
        api.post("/api/v1/hints", {
            "challenge": challenge_id,
            "content":   hint["content"],
            "cost":      hint.get("cost", 0),
        })
        print(f"         → hint added (cost={hint.get('cost', 0)})")

    # handout files (for static challenges, or any challenge with a dist/ dir)
    handout_dir = chall_dir / "handout"
    if handout_dir.exists():
        for f in sorted(handout_dir.iterdir()):
            if f.is_file():
                print(f"         → uploading handout: {f.name}")
                api.upload_file(challenge_id, f)

    print(f"  [ctfd] Done — '{name}' deployed (id={challenge_id})")
    if payload.get("state") == "hidden":
        print(f"         Challenge is hidden. Make visible: CTFd admin > Challenges > {name} > Edit > State: Visible")


# ── main ─────────────────────────────────────────────────────────────────────

def deploy_one(
    chall_dir: Path, env: dict, api: CTFdAPI,
    force: bool, dry_run: bool, skip_build: bool,
    slug_registry: dict = None,
) -> None:
    yml = chall_dir / "challenge.yml"
    if not yml.exists():
        print(f"  skip {chall_dir.name} — no challenge.yml")
        return

    cfg = yaml.safe_load(yml.read_text())

    # slug defaults to directory name; used as Docker image name + scenario OCI tag
    if "slug" not in cfg:
        cfg["slug"] = chall_dir.name

    print(f"\n── {cfg['name']}  [{cfg['type']}]  {chall_dir.name} ──")

    if not skip_build:
        step_image(chall_dir, cfg, env, dry_run)
        if cfg.get("scenario"):
            scenario_ref = ""  # explicit OCI ref in challenge.yml; skip build
            print(f"  [scenario] Using explicit ref from challenge.yml: {cfg['scenario']}")
        else:
            scenario_ref = step_scenario(chall_dir, cfg, env, dry_run)
    else:
        scenario_ref = f"{env['AR_SCENARIOS']}/{cfg['slug']}:latest"
        print(f"  [build] skipped — using {scenario_ref}")

    step_ctfd(chall_dir, cfg, env, scenario_ref, api, force, dry_run, slug_registry)


def main():
    ap = argparse.ArgumentParser(description="Deploy CTF challenges to CTFd.")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--all",  action="store_true",
                     help="Deploy all challenges/**/challenge.yml (recursive)")
    grp.add_argument("--dir",  metavar="PATH",
                     help="Deploy a single challenge directory")
    ap.add_argument("--force",       action="store_true",
                    help="Delete existing challenge and re-create (implies full redeploy)")
    ap.add_argument("--dry-run",     action="store_true",
                    help="Print all steps without executing anything")
    ap.add_argument("--skip-build",  action="store_true",
                    help="Skip docker build and oras push; run CTFd API steps only")
    args = ap.parse_args()

    env = load_env()
    api = CTFdAPI(env["CTFD_URL"], env["CTFD_TOKEN"])

    # Detect GKE node external IP for pwn NodePort routing
    try:
        r = subprocess.run(
            ["kubectl", "get", "nodes", "-o",
             "jsonpath={.items[0].status.addresses[?(@.type=='ExternalIP')].address}"],
            capture_output=True, text=True, timeout=10,
        )
        env["NODE_IP"] = r.stdout.strip()
        if env["NODE_IP"]:
            print(f"[info] GKE node IP: {env['NODE_IP']} (used for pwn NodePort routing)")
        else:
            print("[warn] Could not detect GKE node external IP — pwn node_ip will be empty")
    except Exception as e:
        print(f"[warn] kubectl node lookup failed: {e}")
        env["NODE_IP"] = ""

    if args.dry_run:
        print("DRY RUN — no changes will be made\n")

    if args.all:
        challenges_dir = REPO_ROOT / "challenges"
        dirs = sorted(
            p.parent for p in challenges_dir.rglob("challenge.yml")
        )
        print(f"Found {len(dirs)} challenge(s): {[str(d.relative_to(challenges_dir)) for d in dirs]}")
        slug_registry = {}
        for d in dirs:
            deploy_one(d, env, api, args.force, args.dry_run, args.skip_build, slug_registry)
    else:
        deploy_one(
            Path(args.dir).resolve(), env, api,
            args.force, args.dry_run, args.skip_build,
        )

    print("\n── Done ──")


if __name__ == "__main__":
    main()
