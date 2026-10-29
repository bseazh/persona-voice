#!/usr/bin/env bash
set -euo pipefail

revision="${1:?revision is required}"
archive="${2:?image archive is required}"
project_dir="/home/ubuntu/Project/persona-voice"
new_image="persona-voice:${revision}"
old_image_id="$(sudo docker image inspect persona-voice:latest --format '{{.Id}}' 2>/dev/null || true)"

cleanup() {
  rm -f -- "$archive"
}
trap cleanup EXIT

gzip -dc -- "$archive" | sudo docker load
sudo docker tag "$new_image" persona-voice:latest

cd "$project_dir"
sudo docker compose up -d --no-build --force-recreate

healthy=false
for _ in $(seq 1 30); do
  if curl --fail --silent http://127.0.0.1:5050/api/health >/dev/null; then
    healthy=true
    break
  fi
  sleep 2
done

if [[ "$healthy" != "true" ]]; then
  echo "Deployment health check failed; restoring previous image" >&2
  if [[ -n "$old_image_id" ]]; then
    sudo docker tag "$old_image_id" persona-voice:latest
    sudo docker compose up -d --no-build --force-recreate
  fi
  exit 1
fi

sudo docker image prune -f >/dev/null
echo "Deployed ${revision} successfully"

