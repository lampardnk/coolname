#!/usr/bin/env python3
"""
Generate and apply a DaemonSet that pre-pulls all challenge Docker images
on every GKE node, so instance creation skips the image pull step (~10-30s saved).

Usage:
  python3 scripts/gen-image-warmer.py            # generate + apply
  python3 scripts/gen-image-warmer.py --dry-run   # print YAML only
"""

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT   = Path(__file__).parent.parent.parent
ENV_FILE    = Path(__file__).parent.parent / ".ctf-deploy.env"
ZONE        = "asia-southeast1-b"
HEAD_VM     = "ctf-head"
NAMESPACE   = "ctf-challenges"
DS_NAME     = "image-warmer"


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


def find_image_slugs() -> list:
    """Find all challenge slugs that have an image/ directory."""
    challenges_dir = REPO_ROOT / "challenges"
    slugs = []
    for dockerfile in sorted(challenges_dir.rglob("image/Dockerfile")):
        # slug = parent of image/ dir name (leaf directory)
        slug = dockerfile.parent.parent.name
        slugs.append(slug)
    return slugs


def generate_yaml(ar_images: str, slugs: list) -> str:
    """Generate DaemonSet YAML with init containers for each image."""
    init_containers = ""
    for slug in slugs:
        safe_name = slug.replace("_", "-")
        init_containers += f"""      - name: pull-{safe_name}
        image: {ar_images}/{slug}:latest
        imagePullPolicy: Always
        command: ["true"]
        resources:
          requests:
            cpu: 1m
            memory: 1Mi
"""

    return f"""apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: {DS_NAME}
  namespace: {NAMESPACE}
  labels:
    app: {DS_NAME}
spec:
  selector:
    matchLabels:
      app: {DS_NAME}
  template:
    metadata:
      labels:
        app: {DS_NAME}
    spec:
      initContainers:
{init_containers}      containers:
      - name: idle
        image: busybox:1.36
        command: ["sleep", "infinity"]
        resources:
          requests:
            cpu: 10m
            memory: 16Mi
          limits:
            cpu: 10m
            memory: 16Mi
"""


def ssh(cmd: str, input_data: str = None, timeout: int = 60) -> str:
    try:
        r = subprocess.run(
            ["gcloud", "compute", "ssh", HEAD_VM, f"--zone={ZONE}",
             f"--command={cmd}"],
            input=input_data, capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode != 0 and r.stderr:
            print(f"  stderr: {r.stderr.strip()}", file=sys.stderr)
        return r.stdout.strip()
    except Exception as e:
        print(f"  SSH failed: {e}", file=sys.stderr)
        return ""


def apply_yaml(yaml_str: str) -> bool:
    """Apply YAML to cluster via SSH + kubectl."""
    result = ssh("sudo kubectl apply -f -", input_data=yaml_str)
    if result:
        print(f"  {result}")
        return True
    return False


def main():
    ap = argparse.ArgumentParser(description="Generate and apply image-warmer DaemonSet.")
    ap.add_argument("--dry-run", action="store_true", help="Print YAML without applying")
    args = ap.parse_args()

    env = load_env()
    ar_images = env.get("AR_IMAGES", "")
    if not ar_images:
        sys.exit("ERROR: AR_IMAGES not set in .ctf-deploy.env")

    slugs = find_image_slugs()
    if not slugs:
        sys.exit("ERROR: No challenge image/ directories found")

    print(f"Found {len(slugs)} challenge image(s):")
    for s in slugs:
        print(f"  {ar_images}/{s}:latest")

    yaml_str = generate_yaml(ar_images, slugs)

    if args.dry_run:
        print("\n--- DaemonSet YAML ---")
        print(yaml_str)
        return

    print(f"\nApplying DaemonSet '{DS_NAME}' to cluster...")
    if apply_yaml(yaml_str):
        print("Done. DaemonSet will pull images on all nodes.")
        print(f"Check status: gcloud compute ssh {HEAD_VM} --zone={ZONE} "
              f'--command="sudo kubectl get ds {DS_NAME} -n {NAMESPACE}"')
    else:
        print("Failed to apply DaemonSet.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
