#!/usr/bin/env bash
# Exporte les variables d'un service Cloud Run existant vers deploy/env.<env>.yaml
# (ignore par git). A lancer UNE fois par environnement pour amorcer le fichier, puis
# relire et corriger a la main. Les variables devenues inutiles (bases de test, Redis)
# ne sont pas exportees.
#
#   ./scripts/export-service-env.sh production
set -euo pipefail
umask 077

ENVIRONMENT_NAME="${1:?usage: export-service-env.sh <staging|production>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="${GCP_PROJECT:-guiili}"
REGION="${GCP_REGION:-us-central1}"

case "$ENVIRONMENT_NAME" in
  production) SERVICE="backend-guiili" ;;
  staging) SERVICE="backend-guiili-staging" ;;
  *) echo "environnement inconnu : $ENVIRONMENT_NAME" >&2; exit 2 ;;
esac

OUT="$ROOT/deploy/env.${ENVIRONMENT_NAME}.yaml"
if [ -e "$OUT" ]; then
  echo "$OUT existe deja : le supprimer d'abord pour le regenerer." >&2
  exit 1
fi
mkdir -p "$ROOT/deploy"
TMP="$(mktemp "$ROOT/deploy/.env-export.XXXXXX")"
trap 'rm -f "$TMP"' EXIT

gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" \
  --format=json | python -c '
import json, sys
skip = {"DATABASE_URL_TEST", "DATABASE_URL_MIGRATIONS_TEST", "REDIS_URL"}
service = json.load(sys.stdin)
env = service["spec"]["template"]["spec"]["containers"][0].get("env", [])
for item in env:
    name = item["name"]
    if name in skip:
        print("# ignore : " + name, file=sys.stderr)
        continue
    if "value" not in item:
        print("# ATTENTION : " + name + " vient d un secret Cloud Run, a renseigner a la main", file=sys.stderr)
        continue
    print(name + ": " + json.dumps(item["value"]))
' > "$TMP"
mv "$TMP" "$OUT"

chmod 600 "$OUT" 2>/dev/null || true
echo "Ecrit : $OUT (contient des secrets, ne pas committer)."
echo "Verifier ensuite : (cd backend && .venv/Scripts/python.exe -m app.tools.check_env ../deploy/env.${ENVIRONMENT_NAME}.yaml --expect ${ENVIRONMENT_NAME})"
