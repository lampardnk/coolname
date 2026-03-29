#!/usr/bin/env bash
set -euo pipefail

ZONE="asia-southeast1-b"
INSTANCE="ctf-head"
SCRIPT_DIR="$(dirname "$(realpath "$0")")"
DEPLOY_ENV="${SCRIPT_DIR}/../.ctf-deploy.env"

echo "[1/6] Starting VM..."
gcloud compute instances start "$INSTANCE" --zone="$ZONE"

echo "[2/6] Getting external IP..."
NEW_IP=$(gcloud compute instances describe "$INSTANCE" --zone="$ZONE" \
  --format='value(networkInterfaces[0].accessConfigs[0].natIP)')
echo "      Head IP: $NEW_IP"

echo "[3/6] Waiting for SSH to be ready..."
for i in $(seq 1 24); do
  if gcloud compute ssh "$INSTANCE" --zone="$ZONE" --command="echo ok" &>/dev/null; then
    echo "      → SSH ready"
    break
  fi
  echo "      → not ready yet, waiting 10s... (${i}/24)"
  sleep 10
done

echo "[4/6] Updating configs..."
# Update HEAD_IP in .env on the head node
gcloud compute ssh "$INSTANCE" --zone="$ZONE" --command="
  sudo sed -i \"s/^HEAD_IP=.*/HEAD_IP=${NEW_IP}/\" /opt/ctfd/.env"
echo "      → HEAD_IP updated on head node"

# Update CTFD_URL in local deploy config
if [ -f "$DEPLOY_ENV" ]; then
  sed -i "s|^CTFD_URL=.*|CTFD_URL=http://${NEW_IP}|" "$DEPLOY_ENV"
  echo "      → CTFD_URL updated in scripts/.ctf-deploy.env"
else
  echo "      → Warning: scripts/.ctf-deploy.env not found — run: cp scripts/.ctf-deploy.env.example scripts/.ctf-deploy.env"
fi

echo "[5/6] Starting services..."
gcloud compute ssh "$INSTANCE" --zone="$ZONE" --command="
  cd /opt/ctfd && sudo docker compose --env-file .env up -d"

echo "[6/6] Verifying services..."
gcloud compute ssh "$INSTANCE" --zone="$ZONE" --command="
  cd /opt/ctfd && sudo docker compose ps"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "CTFd: http://${NEW_IP}"
echo "Deploy script: python3 scripts/utils/deploy.py --all"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
