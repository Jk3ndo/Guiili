#!/usr/bin/env bash
# Deploie le backend sur Cloud Run : build -> migrations (Cloud Run Job) -> service.
# Un echec de migration arrete tout AVANT de toucher au service.
#
#   ./scripts/deploy-backend.sh staging
#   ./scripts/deploy-backend.sh production
#   ./scripts/deploy-backend.sh production --dry-run    # affiche sans rien executer
#
# Prerequis : gcloud connecte, deploy/env.<env>.yaml (voir deploy/env.example.yaml et
# scripts/export-service-env.sh), depot Artifact Registry `cloud-run-source-deploy`.
set -euo pipefail

ENVIRONMENT_NAME="${1:?usage: deploy-backend.sh <staging|production> [--dry-run]}"
DRY_RUN=""
[ "${2:-}" = "--dry-run" ] && DRY_RUN=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${GCP_PROJECT:-guiili}"
REGION="${GCP_REGION:-us-central1}"

case "$ENVIRONMENT_NAME" in
  production) SERVICE="backend-guiili" ;;
  staging) SERVICE="backend-guiili-staging" ;;
  *) echo "environnement inconnu : $ENVIRONMENT_NAME" >&2; exit 2 ;;
esac
JOB="${SERVICE}-migrate"
ENV_FILE="$ROOT/deploy/env.${ENVIRONMENT_NAME}.yaml"
TAG="$(git -C "$ROOT" rev-parse --short HEAD)"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/cloud-run-source-deploy/${SERVICE}:${TAG}"

run() {
  echo "+ $*"
  if [ -z "$DRY_RUN" ]; then "$@"; fi
}

[ -f "$ENV_FILE" ] || { echo "manquant : $ENV_FILE (voir deploy/env.example.yaml)" >&2; exit 2; }

if ! git -C "$ROOT" diff --quiet || ! git -C "$ROOT" diff --cached --quiet; then
  echo "ATTENTION : des modifications non committees seront absentes de l'image (tag $TAG)." >&2
fi

echo "== 1/5 Verification du fichier d'environnement"
PY="$ROOT/backend/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="$ROOT/backend/.venv/bin/python"
[ -x "$PY" ] || { echo "venv backend introuvable (uv sync dans backend/)" >&2; exit 2; }
( cd "$ROOT/backend" && "$PY" -m app.tools.check_env "$ENV_FILE" )

echo "== 2/5 Construction de l'image $IMAGE"
run gcloud builds submit "$ROOT/backend" --tag "$IMAGE" --project "$PROJECT" --region "$REGION"

echo "== 3/5 Migrations (Cloud Run Job $JOB)"
run gcloud run jobs deploy "$JOB" --image "$IMAGE" --project "$PROJECT" --region "$REGION" \
  --command alembic --args upgrade,head --env-vars-file "$ENV_FILE" \
  --max-retries 0 --task-timeout 600 --execute-now --wait

echo "== 4/5 Deploiement du service $SERVICE"
run gcloud run deploy "$SERVICE" --image "$IMAGE" --project "$PROJECT" --region "$REGION" \
  --env-vars-file "$ENV_FILE" --allow-unauthenticated \
  --memory 512Mi --cpu 1 --cpu-boost --max-instances 3

echo "== 5/5 Verification"
if [ -n "$DRY_RUN" ]; then
  echo "(dry-run : verification non executee)"; exit 0
fi
URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')"
for attempt in 1 2 3 4 5; do
  if curl -fsS "$URL/health/db" >/dev/null; then
    echo "OK : $URL/health/db repond (image $TAG)."
    exit 0
  fi
  echo "tentative $attempt/5 : pas encore pret, nouvel essai dans 5 s"
  sleep 5
done
echo "ECHEC : $URL/health/db ne repond pas. Retour arriere :" >&2
echo "  gcloud run services update-traffic $SERVICE --project $PROJECT --region $REGION --to-revisions=<REVISION_PRECEDENTE>=100" >&2
exit 1
