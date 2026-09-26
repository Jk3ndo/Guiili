#!/usr/bin/env bash
# Deploie le backend sur Cloud Run : deux images (API sans Chromium, worker avec
# Chromium) -> migrations (Cloud Run Job) -> deux services (API publique, worker prive).
# Un echec de migration arrete tout AVANT de toucher aux services.
#
#   ./scripts/deploy-backend.sh staging
#   ./scripts/deploy-backend.sh production
#   ./scripts/deploy-backend.sh production --dry-run    # affiche sans rien executer
#
# Prerequis : gcloud connecte, deploy/env.<env>.yaml (voir deploy/env.example.yaml et
# scripts/export-service-env.sh), depot Artifact Registry `cloud-run-source-deploy`,
# comptes de service et files Cloud Tasks du lot B (docs/ops/runbook.md §15).
# DEPLOY_ENV_FILE remplace le chemin du fichier d'environnement (utilise par les tests
# du --dry-run) ; WORKER_SERVICE_ACCOUNT remplace le compte de service du worker.
set -euo pipefail

USAGE="usage: deploy-backend.sh <staging|production> [--dry-run]"
ENVIRONMENT_NAME="${1:?$USAGE}"
DRY_RUN=""
if [ "$#" -gt 2 ]; then echo "$USAGE" >&2; exit 2; fi
case "${2:-}" in
  "") ;;
  --dry-run) DRY_RUN=1 ;;
  *) echo "option inconnue : ${2} (seul --dry-run est accepte)" >&2; echo "$USAGE" >&2; exit 2 ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${GCP_PROJECT:-guiili}"
REGION="${GCP_REGION:-us-central1}"

case "$ENVIRONMENT_NAME" in
  production) SERVICE="backend-guiili" ;;
  staging) SERVICE="backend-guiili-staging" ;;
  *) echo "environnement inconnu : $ENVIRONMENT_NAME" >&2; exit 2 ;;
esac
WORKER="${SERVICE}-worker"
WORKER_SA="${WORKER_SERVICE_ACCOUNT:-${WORKER}@${PROJECT}.iam.gserviceaccount.com}"
JOB="${SERVICE}-migrate"
ENV_FILE="${DEPLOY_ENV_FILE:-$ROOT/deploy/env.${ENVIRONMENT_NAME}.yaml}"
TAG="$(git -C "$ROOT" rev-parse --short HEAD)"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT}/cloud-run-source-deploy"
IMAGE="${REGISTRY}/${SERVICE}:${TAG}"
WORKER_IMAGE="${REGISTRY}/${WORKER}:${TAG}"

run() {
  echo "+ $*"
  if [ -z "$DRY_RUN" ]; then "$@"; fi
}

[ -f "$ENV_FILE" ] || { echo "manquant : $ENV_FILE (voir deploy/env.example.yaml)" >&2; exit 2; }

if ! git -C "$ROOT" diff --quiet || ! git -C "$ROOT" diff --cached --quiet; then
  echo "ATTENTION : des modifications non committees seront absentes des images (tag $TAG)." >&2
fi

echo "== 1/5 Verification du fichier d'environnement (API puis worker)"
PY="$ROOT/backend/.venv/Scripts/python.exe"
[ -x "$PY" ] || PY="$ROOT/backend/.venv/bin/python"
[ -x "$PY" ] || { echo "venv backend introuvable (uv sync dans backend/)" >&2; exit 2; }
( cd "$ROOT/backend" && "$PY" -m app.tools.check_env "$ENV_FILE" --expect "$ENVIRONMENT_NAME" )
( cd "$ROOT/backend" && "$PY" -m app.tools.check_env "$ENV_FILE" --expect "$ENVIRONMENT_NAME" --service worker )

echo "== 2/5 Construction des images $IMAGE et $WORKER_IMAGE"
run gcloud builds submit "$ROOT/backend" --tag "$IMAGE" --project "$PROJECT" --region "$REGION"
run gcloud builds submit "$ROOT/backend" --config "$ROOT/backend/cloudbuild.worker.yaml" \
  --substitutions "_IMAGE=$WORKER_IMAGE" --project "$PROJECT" --region "$REGION"

echo "== 3/5 Migrations (Cloud Run Job $JOB)"
run gcloud run jobs deploy "$JOB" --image "$IMAGE" --project "$PROJECT" --region "$REGION" \
  --command alembic --args upgrade,head --env-vars-file "$ENV_FILE" \
  --max-retries 0 --task-timeout 600 --execute-now --wait

echo "== 4/5 Deploiement des services $SERVICE (public) et $WORKER (prive)"
run gcloud run deploy "$SERVICE" --image "$IMAGE" --project "$PROJECT" --region "$REGION" \
  --env-vars-file "$ENV_FILE" --allow-unauthenticated \
  --memory 512Mi --cpu 1 --cpu-boost --max-instances 3
run gcloud run deploy "$WORKER" --image "$WORKER_IMAGE" --project "$PROJECT" --region "$REGION" \
  --env-vars-file "$ENV_FILE" --no-allow-unauthenticated --service-account "$WORKER_SA" \
  --memory 2Gi --cpu 1 --max-instances 2 --concurrency 10 --timeout 900

echo "== 5/5 Verification"
if [ -n "$DRY_RUN" ]; then
  echo "(dry-run : verification non executee)"; exit 0
fi
URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')"
WORKER_URL="$(gcloud run services describe "$WORKER" --project "$PROJECT" --region "$REGION" --format='value(status.url)')"
for attempt in 1 2 3 4 5; do
  if curl -fsS "$URL/health/db" >/dev/null \
    && curl -fsS -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$WORKER_URL/health/db" >/dev/null; then
    echo "OK : $URL/health/db et $WORKER_URL/health/db repondent (images $TAG)."
    exit 0
  fi
  echo "tentative $attempt/5 : pas encore pret, nouvel essai dans 5 s"
  sleep 5
done
echo "ECHEC : un des services ne repond pas. Retour arriere :" >&2
echo "  gcloud run services update-traffic $SERVICE --project $PROJECT --region $REGION --to-revisions=<REVISION_PRECEDENTE>=100" >&2
echo "  gcloud run services update-traffic $WORKER --project $PROJECT --region $REGION --to-revisions=<REVISION_PRECEDENTE>=100" >&2
exit 1
