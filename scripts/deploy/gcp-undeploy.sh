#!/usr/bin/env bash
#
# gcp-undeploy.sh — Tear down a Agent-Vault GCP deployment
#
# Usage:
#   ./gcp-undeploy.sh
#
# Required environment variables:
#   agv_GCP_PROJECT        GCP project ID
#   agv_GCP_REGION         GCP region (default: us-central1)
#   agv_ALLOYDB_CLUSTER    AlloyDB cluster ID (default: agv-cluster)
#   agv_SERVICE_NAME       Cloud Run service name (default: agent-vault)
#   agv_SA_NAME            Service account name (default: agv-run)
#   agv_DEPLOY_STATE_DIR   Dir containing step completion markers (default: .agv/deploy)
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

agv_GCP_REGION="${agv_GCP_REGION:-us-central1}"
agv_ALLOYDB_CLUSTER="${agv_ALLOYDB_CLUSTER:-agv-cluster}"
agv_SERVICE_NAME="${agv_SERVICE_NAME:-agent-vault}"
agv_SA_NAME="${agv_SA_NAME:-agv-run}"
agv_DEPLOY_STATE_DIR="${agv_DEPLOY_STATE_DIR:-.agv/deploy}"

[[ -n "${agv_GCP_PROJECT:-}" ]] || die "agv_GCP_PROJECT is required"

# ─── Step 1: Delete Cloud Run service ─────────────────────────────────────────
log_info "Deleting Cloud Run service '${agv_SERVICE_NAME}'..."
if gcloud run services describe "${agv_SERVICE_NAME}" \
    --region="${agv_GCP_REGION}" \
    --project="${agv_GCP_PROJECT}" \
    --quiet >/dev/null 2>&1; then
    gcloud run services delete "${agv_SERVICE_NAME}" \
        --region="${agv_GCP_REGION}" \
        --project="${agv_GCP_PROJECT}" \
        --quiet
    log_ok "Cloud Run service deleted"
else
    log_warn "Cloud Run service '${agv_SERVICE_NAME}' not found, skipping"
fi

# ─── Step 2: Delete Secret Manager secret ─────────────────────────────────────
log_info "Deleting Secret Manager secret 'agv-api-key'..."
if gcloud secrets describe agv-api-key \
    --project="${agv_GCP_PROJECT}" \
    --quiet >/dev/null 2>&1; then
    gcloud secrets delete agv-api-key \
        --project="${agv_GCP_PROJECT}" \
        --quiet
    log_ok "Secret deleted"
else
    log_warn "Secret 'agv-api-key' not found, skipping"
fi

# ─── Step 3: Delete AlloyDB cluster (deletes all instances) ───────────────────
log_info "Deleting AlloyDB cluster '${agv_ALLOYDB_CLUSTER}'..."
if gcloud alloydb clusters describe "${agv_ALLOYDB_CLUSTER}" \
    --region="${agv_GCP_REGION}" \
    --project="${agv_GCP_PROJECT}" \
    --quiet >/dev/null 2>&1; then
    gcloud alloydb clusters delete "${agv_ALLOYDB_CLUSTER}" \
        --region="${agv_GCP_REGION}" \
        --project="${agv_GCP_PROJECT}" \
        --force \
        --quiet
    log_ok "AlloyDB cluster deleted"
else
    log_warn "AlloyDB cluster '${agv_ALLOYDB_CLUSTER}' not found, skipping"
fi

# ─── Step 4: Delete service account ───────────────────────────────────────────
SA_EMAIL="${agv_SA_NAME}@${agv_GCP_PROJECT}.iam.gserviceaccount.com"
log_info "Deleting service account '${SA_EMAIL}'..."
if gcloud iam service-accounts describe "${SA_EMAIL}" \
    --project="${agv_GCP_PROJECT}" \
    --quiet >/dev/null 2>&1; then
    gcloud iam service-accounts delete "${SA_EMAIL}" \
        --project="${agv_GCP_PROJECT}" \
        --quiet
    log_ok "Service account deleted"
else
    log_warn "Service account '${SA_EMAIL}' not found, skipping"
fi

# ─── Step 5: Remove deploy state markers ──────────────────────────────────────
log_info "Removing deploy state markers from '${agv_DEPLOY_STATE_DIR}'..."
if [[ -d "${agv_DEPLOY_STATE_DIR}" ]]; then
    rm -f "${agv_DEPLOY_STATE_DIR}"/step-*.done \
          "${agv_DEPLOY_STATE_DIR}"/gcp-state.json \
          "${agv_DEPLOY_STATE_DIR}"/service-url.txt \
          "${agv_DEPLOY_STATE_DIR}"/image-path.txt
    log_ok "State markers removed"
fi

log_ok "GCP undeploy complete for project '${agv_GCP_PROJECT}'"
