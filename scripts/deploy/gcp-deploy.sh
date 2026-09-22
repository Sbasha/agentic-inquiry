#!/usr/bin/env bash
#
# gcp-deploy.sh — Deploy Agentic Inquiry to GCP (AlloyDB + Cloud Run)
#
# Usage:
#   ./gcp-deploy.sh
#
# Required environment variables:
#   INQUIRY_GCP_PROJECT        GCP project ID
#   INQUIRY_GCP_REGION         GCP region (default: us-central1)
#   INQUIRY_ALLOYDB_CLUSTER    AlloyDB cluster ID (default: ai-cluster)
#   INQUIRY_ALLOYDB_INSTANCE   AlloyDB instance ID (default: ai-primary)
#   INQUIRY_ALLOYDB_PASSWORD   AlloyDB postgres user password
#   INQUIRY_API_KEY            Agentic Inquiry API key (pre-generated)
#   INQUIRY_IMAGE_TAG          Container image tag (default: latest)
#   INQUIRY_SERVICE_NAME       Cloud Run service name (default: agentic-inquiry)
#   INQUIRY_DEPLOY_STATE_DIR   Dir to write step completion markers (default: .agentic-inquiry/deploy)
#
# The script is idempotent: completed steps are skipped via marker files.
# Exit non-zero on any failure with a clear error message.
#

set -euo pipefail

# ─── Colour helpers ────────────────────────────────────────────────────────────
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

# ─── Defaults ──────────────────────────────────────────────────────────────────
INQUIRY_GCP_REGION="${INQUIRY_GCP_REGION:-us-central1}"
INQUIRY_ALLOYDB_CLUSTER="${INQUIRY_ALLOYDB_CLUSTER:-ai-cluster}"
INQUIRY_ALLOYDB_INSTANCE="${INQUIRY_ALLOYDB_INSTANCE:-ai-primary}"
INQUIRY_IMAGE_TAG="${INQUIRY_IMAGE_TAG:-latest}"
INQUIRY_SERVICE_NAME="${INQUIRY_SERVICE_NAME:-agentic-inquiry}"
INQUIRY_DEPLOY_STATE_DIR="${INQUIRY_DEPLOY_STATE_DIR:-.agentic-inquiry/deploy}"
INQUIRY_DB_USER="${INQUIRY_DB_USER:-postgres}"
INQUIRY_DB_NAME="${INQUIRY_DB_NAME:-agentic-inquiry}"
INQUIRY_SA_NAME="${INQUIRY_SA_NAME:-ai-run}"

# ─── Validate required vars ────────────────────────────────────────────────────
[[ -n "${INQUIRY_GCP_PROJECT:-}" ]]    || die "INQUIRY_GCP_PROJECT is required"
[[ -n "${INQUIRY_ALLOYDB_PASSWORD:-}" ]] || die "INQUIRY_ALLOYDB_PASSWORD is required"
[[ -n "${INQUIRY_API_KEY:-}" ]]        || die "INQUIRY_API_KEY is required"

# ─── Step marker helpers ────────────────────────────────────────────────────────
mkdir -p "${INQUIRY_DEPLOY_STATE_DIR}"

step_done() {
    local step="$1"
    [[ -f "${INQUIRY_DEPLOY_STATE_DIR}/step-${step}.done" ]]
}

mark_done() {
    local step="$1"
    touch "${INQUIRY_DEPLOY_STATE_DIR}/step-${step}.done"
    log_ok "Step ${step} complete"
}

# ─── Step 1: Check prerequisites ───────────────────────────────────────────────
if step_done "01-prereqs"; then
    log_info "Step 01-prereqs: already done, skipping"
else
    log_info "Step 01: Checking prerequisites..."

    command -v gcloud >/dev/null 2>&1 || die "gcloud CLI not found — install Google Cloud SDK"
    command -v docker  >/dev/null 2>&1 || die "docker not found — install Docker"

    # Verify gcloud authentication
    if ! gcloud auth print-access-token --quiet >/dev/null 2>&1; then
        die "Not authenticated with gcloud — run: gcloud auth login"
    fi

    # Verify project access
    gcloud projects describe "${INQUIRY_GCP_PROJECT}" --quiet >/dev/null 2>&1 \
        || die "Cannot access project '${INQUIRY_GCP_PROJECT}' — check permissions"

    mark_done "01-prereqs"
fi

# ─── Step 2: Enable APIs ───────────────────────────────────────────────────────
if step_done "02-apis"; then
    log_info "Step 02-apis: already done, skipping"
else
    log_info "Step 02: Enabling required GCP APIs..."

    APIS=(
        "alloydb.googleapis.com"
        "run.googleapis.com"
        "artifactregistry.googleapis.com"
        "iam.googleapis.com"
        "secretmanager.googleapis.com"
        "servicenetworking.googleapis.com"
    )

    for api in "${APIS[@]}"; do
        log_info "  Enabling ${api}..."
        gcloud services enable "${api}" --project="${INQUIRY_GCP_PROJECT}" --quiet
    done

    mark_done "02-apis"
fi

# ─── Step 3: Create AlloyDB cluster ───────────────────────────────────────────
if step_done "03-alloydb-cluster"; then
    log_info "Step 03-alloydb-cluster: already done, skipping"
else
    log_info "Step 03: Creating AlloyDB cluster '${INQUIRY_ALLOYDB_CLUSTER}'..."

    # Check if cluster already exists (idempotent)
    if gcloud alloydb clusters describe "${INQUIRY_ALLOYDB_CLUSTER}" \
        --region="${INQUIRY_GCP_REGION}" \
        --project="${INQUIRY_GCP_PROJECT}" \
        --quiet >/dev/null 2>&1; then
        log_warn "AlloyDB cluster '${INQUIRY_ALLOYDB_CLUSTER}' already exists, skipping creation"
    else
        # Create private services access if not already present
        gcloud compute addresses create google-managed-services-default \
            --global \
            --purpose=VPC_PEERING \
            --prefix-length=16 \
            --network=default \
            --project="${INQUIRY_GCP_PROJECT}" \
            --quiet 2>/dev/null || true

        gcloud services vpc-peerings connect \
            --service=servicenetworking.googleapis.com \
            --ranges=google-managed-services-default \
            --network=default \
            --project="${INQUIRY_GCP_PROJECT}" \
            --quiet 2>/dev/null || true

        gcloud alloydb clusters create "${INQUIRY_ALLOYDB_CLUSTER}" \
            --region="${INQUIRY_GCP_REGION}" \
            --password="${INQUIRY_ALLOYDB_PASSWORD}" \
            --project="${INQUIRY_GCP_PROJECT}" \
            --quiet
    fi

    # Check if primary instance already exists
    if gcloud alloydb instances describe "${INQUIRY_ALLOYDB_INSTANCE}" \
        --cluster="${INQUIRY_ALLOYDB_CLUSTER}" \
        --region="${INQUIRY_GCP_REGION}" \
        --project="${INQUIRY_GCP_PROJECT}" \
        --quiet >/dev/null 2>&1; then
        log_warn "AlloyDB instance '${INQUIRY_ALLOYDB_INSTANCE}' already exists, skipping creation"
    else
        log_info "  Creating AlloyDB primary instance '${INQUIRY_ALLOYDB_INSTANCE}'..."
        gcloud alloydb instances create "${INQUIRY_ALLOYDB_INSTANCE}" \
            --instance-type=PRIMARY \
            --cluster="${INQUIRY_ALLOYDB_CLUSTER}" \
            --region="${INQUIRY_GCP_REGION}" \
            --cpu-count=2 \
            --project="${INQUIRY_GCP_PROJECT}" \
            --quiet
    fi

    mark_done "03-alloydb-cluster"
fi

# ─── Step 4: Configure IAM + Service Account ──────────────────────────────────
if step_done "04-iam"; then
    log_info "Step 04-iam: already done, skipping"
else
    log_info "Step 04: Configuring IAM and service account..."

    SA_EMAIL="${INQUIRY_SA_NAME}@${INQUIRY_GCP_PROJECT}.iam.gserviceaccount.com"

    # Create service account (idempotent)
    if gcloud iam service-accounts describe "${SA_EMAIL}" \
        --project="${INQUIRY_GCP_PROJECT}" \
        --quiet >/dev/null 2>&1; then
        log_warn "Service account '${SA_EMAIL}' already exists, skipping"
    else
        gcloud iam service-accounts create "${INQUIRY_SA_NAME}" \
            --display-name="Agentic Inquiry Cloud Run SA" \
            --project="${INQUIRY_GCP_PROJECT}" \
            --quiet
    fi

    # Grant required IAM roles
    ROLES=(
        "roles/alloydb.client"
        "roles/secretmanager.secretAccessor"
        "roles/aiplatform.user"
        "roles/logging.logWriter"
        "roles/cloudtrace.agent"
    )

    for role in "${ROLES[@]}"; do
        gcloud projects add-iam-policy-binding "${INQUIRY_GCP_PROJECT}" \
            --member="serviceAccount:${SA_EMAIL}" \
            --role="${role}" \
            --condition=None \
            --quiet >/dev/null 2>&1 || true
    done

    # Store API key in Secret Manager
    if gcloud secrets describe ai-api-key \
        --project="${INQUIRY_GCP_PROJECT}" \
        --quiet >/dev/null 2>&1; then
        log_warn "Secret 'ai-api-key' already exists, updating value..."
        printf '%s' "${INQUIRY_API_KEY}" | gcloud secrets versions add ai-api-key \
            --data-file=- \
            --project="${INQUIRY_GCP_PROJECT}" \
            --quiet
    else
        printf '%s' "${INQUIRY_API_KEY}" | gcloud secrets create ai-api-key \
            --data-file=- \
            --replication-policy=automatic \
            --project="${INQUIRY_GCP_PROJECT}" \
            --quiet
    fi

    # Grant SA access to the secret
    gcloud secrets add-iam-policy-binding ai-api-key \
        --member="serviceAccount:${SA_EMAIL}" \
        --role="roles/secretmanager.secretAccessor" \
        --project="${INQUIRY_GCP_PROJECT}" \
        --quiet >/dev/null 2>&1 || true

    mark_done "04-iam"
fi

# ─── Step 5: Initialize embeddings (AlloyDB AI extension) ─────────────────────
if step_done "05-embeddings"; then
    log_info "Step 05-embeddings: already done, skipping"
else
    log_info "Step 05: Initializing AlloyDB AI embedding extension..."

    # Get instance IP
    ALLOYDB_IP=$(gcloud alloydb instances describe "${INQUIRY_ALLOYDB_INSTANCE}" \
        --cluster="${INQUIRY_ALLOYDB_CLUSTER}" \
        --region="${INQUIRY_GCP_REGION}" \
        --project="${INQUIRY_GCP_PROJECT}" \
        --format="value(ipAddress)" \
        --quiet 2>/dev/null || echo "")

    if [[ -z "${ALLOYDB_IP}" ]]; then
        log_warn "Could not retrieve AlloyDB IP — embeddings init will happen at first run"
    else
        log_info "  AlloyDB IP: ${ALLOYDB_IP}"
        log_info "  Embedding init will be triggered by the indexing pipeline on first use"
    fi

    mark_done "05-embeddings"
fi

# ─── Step 6: Build and push container ─────────────────────────────────────────
if step_done "06-container"; then
    log_info "Step 06-container: already done, skipping"
else
    log_info "Step 06: Building and pushing container image..."

    # Create Artifact Registry repo if needed
    AR_REPO="ai-images"
    if gcloud artifacts repositories describe "${AR_REPO}" \
        --location="${INQUIRY_GCP_REGION}" \
        --project="${INQUIRY_GCP_PROJECT}" \
        --quiet >/dev/null 2>&1; then
        log_warn "Artifact Registry repo '${AR_REPO}' already exists"
    else
        gcloud artifacts repositories create "${AR_REPO}" \
            --repository-format=docker \
            --location="${INQUIRY_GCP_REGION}" \
            --description="Agentic Inquiry container images" \
            --project="${INQUIRY_GCP_PROJECT}" \
            --quiet
    fi

    IMAGE_PATH="${INQUIRY_GCP_REGION}-docker.pkg.dev/${INQUIRY_GCP_PROJECT}/${AR_REPO}/agentic-inquiry:${INQUIRY_IMAGE_TAG}"

    # Configure Docker auth
    gcloud auth configure-docker "${INQUIRY_GCP_REGION}-docker.pkg.dev" --quiet

    # Build image (assumes Dockerfile at repo root)
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

    docker build \
        --tag "${IMAGE_PATH}" \
        --label "ai.deploy.project=${INQUIRY_GCP_PROJECT}" \
        --label "ai.deploy.timestamp=$(date -u +%Y%m%dT%H%M%SZ)" \
        "${REPO_ROOT}"

    docker push "${IMAGE_PATH}"

    # Write image path for next steps
    echo "${IMAGE_PATH}" > "${INQUIRY_DEPLOY_STATE_DIR}/image-path.txt"

    mark_done "06-container"
fi

# ─── Step 7: Deploy to Cloud Run ──────────────────────────────────────────────
if step_done "07-cloud-run"; then
    log_info "Step 07-cloud-run: already done, skipping"
else
    log_info "Step 07: Deploying to Cloud Run..."

    IMAGE_PATH=$(cat "${INQUIRY_DEPLOY_STATE_DIR}/image-path.txt" 2>/dev/null \
        || echo "${INQUIRY_GCP_REGION}-docker.pkg.dev/${INQUIRY_GCP_PROJECT}/ai-images/agentic-inquiry:${INQUIRY_IMAGE_TAG}")

    SA_EMAIL="${INQUIRY_SA_NAME}@${INQUIRY_GCP_PROJECT}.iam.gserviceaccount.com"

    gcloud run deploy "${INQUIRY_SERVICE_NAME}" \
        --image="${IMAGE_PATH}" \
        --region="${INQUIRY_GCP_REGION}" \
        --project="${INQUIRY_GCP_PROJECT}" \
        --service-account="${SA_EMAIL}" \
        --set-secrets="INQUIRY_API_KEY=ai-api-key:latest" \
        --set-env-vars="INQUIRY_ENV=${INQUIRY_SERVICE_NAME},INQUIRY_STORAGE_BACKEND=alloydb" \
        --allow-unauthenticated \
        --min-instances=1 \
        --max-instances=10 \
        --cpu=1 \
        --memory=2Gi \
        --timeout=300 \
        --quiet

    # Retrieve the service URL
    SERVICE_URL=$(gcloud run services describe "${INQUIRY_SERVICE_NAME}" \
        --region="${INQUIRY_GCP_REGION}" \
        --project="${INQUIRY_GCP_PROJECT}" \
        --format="value(status.url)" \
        --quiet)

    echo "${SERVICE_URL}" > "${INQUIRY_DEPLOY_STATE_DIR}/service-url.txt"
    log_ok "Cloud Run service URL: ${SERVICE_URL}"

    mark_done "07-cloud-run"
fi

# ─── Step 8: Smoke test ────────────────────────────────────────────────────────
if step_done "08-smoke-test"; then
    log_info "Step 08-smoke-test: already done, skipping"
else
    log_info "Step 08: Running smoke test..."

    SERVICE_URL=$(cat "${INQUIRY_DEPLOY_STATE_DIR}/service-url.txt" 2>/dev/null || "")
    if [[ -z "${SERVICE_URL}" ]]; then
        die "Cannot find service URL — did step 07 complete successfully?"
    fi

    HEALTH_URL="${SERVICE_URL}/api/v1/health"
    MAX_ATTEMPTS=30
    SLEEP_SECONDS=10

    log_info "  Polling ${HEALTH_URL} (up to $((MAX_ATTEMPTS * SLEEP_SECONDS))s)..."
    for i in $(seq 1 "${MAX_ATTEMPTS}"); do
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
            --max-time 10 \
            "${HEALTH_URL}" 2>/dev/null || echo "000")

        if [[ "${HTTP_CODE}" == "200" ]]; then
            log_ok "Health check passed (attempt ${i})"
            mark_done "08-smoke-test"
            break
        fi

        if [[ "${i}" -lt "${MAX_ATTEMPTS}" ]]; then
            log_info "  Attempt ${i}/${MAX_ATTEMPTS}: HTTP ${HTTP_CODE}, retrying in ${SLEEP_SECONDS}s..."
            sleep "${SLEEP_SECONDS}"
        else
            die "Smoke test failed after ${MAX_ATTEMPTS} attempts — service did not become healthy"
        fi
    done
fi

# ─── Summary ───────────────────────────────────────────────────────────────────
SERVICE_URL=$(cat "${INQUIRY_DEPLOY_STATE_DIR}/service-url.txt" 2>/dev/null || "unknown")
echo ""
log_ok "======================================================"
log_ok "Agentic Inquiry deployed successfully!"
log_ok "  Project:     ${INQUIRY_GCP_PROJECT}"
log_ok "  Region:      ${INQUIRY_GCP_REGION}"
log_ok "  Service:     ${INQUIRY_SERVICE_NAME}"
log_ok "  URL:         ${SERVICE_URL}"
log_ok "======================================================"
