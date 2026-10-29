#!/usr/bin/env bash
set -euo pipefail

revision="${1:?revision is required}"
project_dir="/home/ubuntu/Project/persona-voice"
runtime_dir="$project_dir/runtime"
previous_dir="$project_dir/runtime.previous"
staging_dir="$project_dir/.runtime-$revision"

if [[ ! "$revision" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Invalid Git revision" >&2
  exit 2
fi

cd "$project_dir"
rm -rf -- "$staging_dir"
mkdir -p "$staging_dir/app" "$staging_dir/static"
cp -a services/api/app/. "$staging_dir/app/"
cp -a web/out/. "$staging_dir/static/"

rm -rf -- "$previous_dir"
if [[ -d "$runtime_dir" ]]; then
  mv "$runtime_dir" "$previous_dir"
fi
mv "$staging_dir" "$runtime_dir"

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
  echo "Deployment health check failed; restoring previous runtime" >&2
  if [[ -d "$previous_dir" ]]; then
    rm -rf -- "$runtime_dir"
    mv "$previous_dir" "$runtime_dir"
    sudo docker compose up -d --no-build --force-recreate
  fi
  exit 1
fi

rm -rf -- "$previous_dir"
echo "Deployed ${revision} successfully"
