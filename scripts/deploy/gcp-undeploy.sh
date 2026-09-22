#!/usr/bin/env bash
#
# gcp-undeploy.sh — Tear down a Agentic Inquiry GCP deployment
#
# Usage:
#   ./gcp-undeploy.sh
#
# Required environment variables:
#   AI_GCP_PROJECT        GCP project ID
#   AI_GCP_REGION         GCP region (default: us-central1)
#   AI_ALLOYDB_CLUSTER    AlloyDB cluster ID (default: ai-cluster)
#   AI_SERVICE_NAME       Cloud Run service name (default: agentic-inquiry)
#   AI_SA_NAME            Service account name (default: ai-run)
#   AI_DEPLOY_STATE_DIR   Dir containing step completion markers (default: .agentic-inquiry/deploy)
#
# The script tears down resources in reverse deploy order.
# Resources that do not exist are skipped (idempotent).
#

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()       { log_error "$*"; exit 1; }

AI_GCP_REGION="${AI_GCP_REGION:-us-central1}"
AI_ALLOYDB_CLUSTER="${AI_ALLOYDB_CLUSTER:-ai-cluster}"
AI_SERVICE_NAME="${AI_SERVICE_NAME:-agentic-inquiry}"
AI_SA_NAME="${AI_SA_NAME:-ai-run}"
AI_DEPLOY_STATE_DIR="${AI_DEPLOY_STATE_DIR:-.agentic-inquiry/deploy}"

[[ -n "${AI_GCP_PROJECT:-}" ]] || die "AI_GCP_PROJECT is required"

# ─── Step 1: Delete Cloud Run service ─────────────────────────────────────────
log_info "Deleting Cloud Run service '${AI_SERVICE_NAME}'..."
if gcloud run services describe "${AI_SERVICE_NAME}" \
    --region="${AI_GCP_REGION}" \
    --project="${AI_GCP_PROJECT}" \
    --quiet >/dev/null 2>&1; then
    gcloud run services delete "${AI_SERVICE_NAME}" \
        --region="${AI_GCP_REGION}" \
        --project="${AI_GCP_PROJECT}" \
        --quiet
    log_ok "Cloud Run service deleted"
else
    log_warn "Cloud Run service '${AI_SERVICE_NAME}' not found, skipping"
fi

# ─── Step 2: Delete Secret Manager secret ─────────────────────────────────────
log_info "Deleting Secret Manager secret 'ai-api-key'..."
if gcloud secrets describe ai-api-key \
    --project="${AI_GCP_PROJECT}" \
    --quiet >/dev/null 2>&1; then
    gcloud secrets delete ai-api-key \
        --project="${AI_GCP_PROJECT}" \
        --quiet
    log_ok "Secret deleted"
else
    log_warn "Secret 'ai-api-key' not found, skipping"
fi

# ─── Step 3: Delete AlloyDB cluster (deletes all instances) ───────────────────
log_info "Deleting AlloyDB cluster '${AI_ALLOYDB_CLUSTER}'..."
if gcloud alloydb clusters describe "${AI_ALLOYDB_CLUSTER}" \
    --region="${AI_GCP_REGION}" \
    --project="${AI_GCP_PROJECT}" \
    --quiet >/dev/null 2>&1; then
    gcloud alloydb clusters delete "${AI_ALLOYDB_CLUSTER}" \
        --region="${AI_GCP_REGION}" \
        --project="${AI_GCP_PROJECT}" \
        --force \
        --quiet
    log_ok "AlloyDB cluster deleted"
else
    log_warn "AlloyDB cluster '${AI_ALLOYDB_CLUSTER}' not found, skipping"
fi

# ─── Step 4: Delete service account ───────────────────────────────────────────
SA_EMAIL="${AI_SA_NAME}@${AI_GCP_PROJECT}.iam.gserviceaccount.com"
log_info "Deleting service account '${SA_EMAIL}'..."
if gcloud iam service-accounts describe "${SA_EMAIL}" \
    --project="${AI_GCP_PROJECT}" \
    --quiet >/dev/null 2>&1; then
    gcloud iam service-accounts delete "${SA_EMAIL}" \
        --project="${AI_GCP_PROJECT}" \
        --quiet
    log_ok "Service account deleted"
else
    log_warn "Service account '${SA_EMAIL}' not found, skipping"
fi

# ─── Step 5: Remove deploy state markers ──────────────────────────────────────
log_info "Removing deploy state markers from '${AI_DEPLOY_STATE_DIR}'..."
if [[ -d "${AI_DEPLOY_STATE_DIR}" ]]; then
    rm -f "${AI_DEPLOY_STATE_DIR}"/step-*.done \
          "${AI_DEPLOY_STATE_DIR}"/gcp-state.json \
          "${AI_DEPLOY_STATE_DIR}"/service-url.txt \
          "${AI_DEPLOY_STATE_DIR}"/image-path.txt
    log_ok "State markers removed"
fi

log_ok "GCP undeploy complete for project '${AI_GCP_PROJECT}'"
