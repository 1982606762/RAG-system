#!/usr/bin/env bash
# Deploy an immutable release while preserving the existing database and routing.
set -Eeuo pipefail
umask 077
root=$(realpath "$1")
revision=$2
[[ "$revision" =~ ^[0-9a-f]{40}$ ]]
release="$root/.releases/$revision"
cd "$root"
exec 9>"$root/.deployment.lock"
flock -n 9
test -f "$release/docker-compose.yml"
test -f .env
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup="$root/.backups/$stamp-$revision"
mkdir -p "$backup"
cp .env "$backup/original.env"
cp docker-compose.yml "$backup/original-compose.yml"
git diff HEAD > "$backup/server-changes.patch"
# Use active container labels; an older release symlink can outlive a manual
# deployment from the root checkout.
python3 - "$backup/rollback.json" <<'PY'
import json
from pathlib import Path
import subprocess
import sys
info = json.loads(subprocess.check_output(['docker', 'inspect', 'rag-system-app-1']))[0]
labels = info['Config']['Labels']
command = ['docker', 'compose', '-p', 'rag-system', '--project-directory', labels['com.docker.compose.project.working_dir']]
for path in labels['com.docker.compose.project.config_files'].split(','):
    command.extend(['-f', path])
command.extend(['config', '--format', 'json'])
Path(sys.argv[1]).write_bytes(subprocess.check_output(command))
PY
cp .env "$release/.env"
export RAG_ROOT="$root" RAG_RELEASE="$release" RAG_BACKUP="$backup" RAG_REVISION="$revision"

# Freeze rollback images and discover only the RAG domain from Caddy's config.
python3 "$release/scripts/prepare-deployment.py"
compose=(docker compose --project-name rag-system --project-directory "$release" -f "$release/production.json")
rollback=(docker compose --project-name rag-system --project-directory "$root" -f "$backup/rollback.json")
read -r -a previous_services < "$backup/application-services"
"${compose[@]}" config --quiet
"${compose[@]}" pull postgres
"${compose[@]}" build app frontend
python3 "$release/scripts/verify-container-env.py"

changed=0
database_changed=0
database_verified=0
rollback_on_error() {
  result=$?
  trap - ERR
  if [[ "$changed" == 1 ]]; then
    echo 'Deployment failed; restoring previous application images.'
    # Before the new database has passed readiness/extension checks, restore
    # its old PG16 image too. After migrations, retain the healthy pgvector
    # image so the newly created extension remains installed.
    if [[ "$database_changed" == 1 && "$database_verified" == 0 ]]; then
      "${rollback[@]}" up -d --no-deps --no-build postgres || true
    fi
    "${rollback[@]}" up -d --no-deps --no-build "${previous_services[@]}" || true
  fi
  echo "Deployment failed with status $result; backup retained."
  exit "$result"
}
trap rollback_on_error ERR
changed=1
# Stop writers before taking a consistent database and original-file snapshot.
"${rollback[@]}" stop -t 120 "${previous_services[@]}"
docker exec rag-system-postgres-1 pg_dump -U postgres -d ragdb -Fc > "$backup/database.dump"
test -s "$backup/database.dump"
docker exec -i rag-system-postgres-1 pg_restore --list < "$backup/database.dump" > "$backup/database-contents.txt"
# Uploaded originals are private 0600 files owned by the app container's UID.
# Read them through a read-only bind without changing original permissions.
docker run --rm --network none --read-only --user 0:0 \
  --mount "type=bind,source=$root/files,target=/backup-source/files,readonly" \
  --entrypoint tar "rag-rollback-app:${revision:0:12}" \
  -czf - -C /backup-source files > "$backup/files.tar.gz"
tar -tzf "$backup/files.tar.gz" > "$backup/files-contents.txt"
mkdir -p "$root/files/mvp"
database_changed=1
"${compose[@]}" up -d --no-deps --no-build postgres
database_ready=0
for attempt in $(seq 1 45); do
  if docker exec rag-system-postgres-1 pg_isready -U postgres -d ragdb; then
    database_ready=1
    break
  fi
  sleep 2
done
test "$database_ready" = 1
test "$(docker exec rag-system-postgres-1 psql -U postgres -d ragdb -tAc "SELECT count(*) FROM pg_available_extensions WHERE name='vector'")" = 1
database_verified=1
"${compose[@]}" run --rm --no-deps app python cli.py init-db
"${compose[@]}" up -d --no-deps --no-build app frontend
healthy=0
for attempt in $(seq 1 30); do
  if "${compose[@]}" exec -T frontend wget -q -O /dev/null http://127.0.0.1/api/health; then
    healthy=1
    break
  fi
  sleep 2
done
test "$healthy" = 1
"${compose[@]}" exec -T app python /app/cli.py healthcheck
"${compose[@]}" exec -T app python - < "$release/scripts/verify-deployment.py"
domain=$(cat "$release/public-domain")
curl --fail --silent --show-error --retry 5 --retry-delay 2 "https://$domain/api/health"
curl --fail --silent --show-error "https://$domain/" > "$backup/frontend-response.html"
grep -q 'id="root"' "$backup/frontend-response.html"
# Retain previous application images and all data volumes for rollback.
ln -sfn "$release" "$root/.current-release"
trap - ERR
echo "Deployment verified: https://$domain"
echo "Release: $revision"
echo "Backup retained: $stamp-$revision"
