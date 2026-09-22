#!/usr/bin/env bash
#
# azure-deploy.sh — Deploy Agentic Inquiry to Azure (PostgreSQL Flexible Server + Container Apps)
#
# Usage:
#   ./azure-deploy.sh
#
# Required environment variables:
#   INQUIRY_AZURE_SUBSCRIPTION_ID  Azure subscription ID (required)
#   INQUIRY_AZURE_RESOURCE_GROUP   Azure resource group (required)
#   INQUIRY_PG_PASSWORD            PostgreSQL admin password (required)
#   INQUIRY_API_KEY                Agentic Inquiry API key (pre-generated)
#
# Optional environment variables:
#   INQUIRY_AZURE_LOCATION         Azure region (default: eastus)
#   INQUIRY_PG_SERVER_NAME         PostgreSQL server name (default: ai-postgres)
#   INQUIRY_PG_SKU                 PostgreSQL SKU (default: Standard_B1ms)
#   INQUIRY_ACR_NAME               Azure Container Registry name (default: agvimages)
#   INQUIRY_SERVICE_NAME           Container App name (default: agentic-inquiry)
#   INQUIRY_IMAGE_TAG              Container image tag (default: latest)
#   INQUIRY_DB_NAME                Database name (default: agentic-inquiry)
#   INQUIRY_DB_USER                Database admin user (default: agvadmin)
#   INQUIRY_CA_ENV_NAME            Container Apps Environment name (default: ai-env)
#   INQUIRY_DEPLOY_STATE_DIR       Dir to write step completion markers (default: .agentic-inquiry/deploy)
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

INQUIRY_AZURE_LOCATION="${INQUIRY_AZURE_LOCATION:-eastus}"
INQUIRY_PG_SERVER_NAME="${INQUIRY_PG_SERVER_NAME:-ai-postgres}"
INQUIRY_PG_SKU="${INQUIRY_PG_SKU:-Standard_B1ms}"
INQUIRY_ACR_NAME="${INQUIRY_ACR_NAME:-agvimages}"
INQUIRY_SERVICE_NAME="${INQUIRY_SERVICE_NAME:-agentic-inquiry}"
INQUIRY_IMAGE_TAG="${INQUIRY_IMAGE_TAG:-latest}"
INQUIRY_DB_NAME="${INQUIRY_DB_NAME:-agentic-inquiry}"
INQUIRY_DB_USER="${INQUIRY_DB_USER:-agvadmin}"
INQUIRY_CA_ENV_NAME="${INQUIRY_CA_ENV_NAME:-ai-env}"
INQUIRY_DEPLOY_STATE_DIR="${INQUIRY_DEPLOY_STATE_DIR:-.agentic-inquiry/deploy}"

[[ -n "${INQUIRY_AZURE_SUBSCRIPTION_ID:-}" ]] || die "INQUIRY_AZURE_SUBSCRIPTION_ID is required"
[[ -n "${INQUIRY_AZURE_RESOURCE_GROUP:-}" ]]  || die "INQUIRY_AZURE_RESOURCE_GROUP is required"
[[ -n "${INQUIRY_PG_PASSWORD:-}" ]]           || die "INQUIRY_PG_PASSWORD is required"
[[ -n "${INQUIRY_API_KEY:-}" ]]               || die "INQUIRY_API_KEY is required"

mkdir -p "${INQUIRY_DEPLOY_STATE_DIR}"
step_done() { [[ -f "${INQUIRY_DEPLOY_STATE_DIR}/step-${1}.done" ]]; }
mark_done() { touch "${INQUIRY_DEPLOY_STATE_DIR}/step-${1}.done"; log_ok "Step ${1} complete"; }

# ─── Step 1: Check prerequisites ───────────────────────────────────────────────
if step_done "01-prereqs"; then
    log_info "Step 01-prereqs: already done, skipping"
else
    log_info "Step 01: Checking prerequisites..."
    command -v az     >/dev/null 2>&1 || die "az CLI not found — install Azure CLI"
    command -v docker >/dev/null 2>&1 || die "docker not found — install Docker"
    az account show --output none 2>/dev/null \
        || die "Not authenticated with Azure — run: az login"
    az account set --subscription "${INQUIRY_AZURE_SUBSCRIPTION_ID}"
    mark_done "01-prereqs"
fi

# ─── Step 2: Create resource group ────────────────────────────────────────────
if step_done "02-resource-group"; then
    log_info "Step 02-resource-group: already done, skipping"
else
    log_info "Step 02: Ensuring resource group '${INQUIRY_AZURE_RESOURCE_GROUP}'..."
    az group create \
        --name "${INQUIRY_AZURE_RESOURCE_GROUP}" \
        --location "${INQUIRY_AZURE_LOCATION}" \
        --output none
    mark_done "02-resource-group"
fi

# ─── Step 3: Create PostgreSQL Flexible Server ────────────────────────────────
if step_done "03-postgres"; then
    log_info "Step 03-postgres: already done, skipping"
else
    log_info "Step 03: Creating PostgreSQL Flexible Server '${INQUIRY_PG_SERVER_NAME}'..."

    if az postgres flexible-server show \
        --name "${INQUIRY_PG_SERVER_NAME}" \
        --resource-group "${INQUIRY_AZURE_RESOURCE_GROUP}" \
        --output none 2>/dev/null; then
        log_warn "PostgreSQL server '${INQUIRY_PG_SERVER_NAME}' already exists, skipping"
    else
        az postgres flexible-server create \
            --name "${INQUIRY_PG_SERVER_NAME}" \
            --resource-group "${INQUIRY_AZURE_RESOURCE_GROUP}" \
            --location "${INQUIRY_AZURE_LOCATION}" \
            --admin-user "${INQUIRY_DB_USER}" \
            --admin-password "${INQUIRY_PG_PASSWORD}" \
            --sku-name "${INQUIRY_PG_SKU}" \
            --tier Burstable \
            --storage-size 32 \
            --version 15 \
            --public-access 0.0.0.0 \
            --output none
    fi

    # Create database
    az postgres flexible-server db create \
        --resource-group "${INQUIRY_AZURE_RESOURCE_GROUP}" \
        --server-name "${INQUIRY_PG_SERVER_NAME}" \
        --database-name "${INQUIRY_DB_NAME}" \
        --output none 2>/dev/null || true

    # Get FQDN
    PG_HOST=$(az postgres flexible-server show \
        --name "${INQUIRY_PG_SERVER_NAME}" \
        --resource-group "${INQUIRY_AZURE_RESOURCE_GROUP}" \
        --query "fullyQualifiedDomainName" \
        --output tsv)
    echo "${PG_HOST}" > "${INQUIRY_DEPLOY_STATE_DIR}/pg-host.txt"
    log_ok "PostgreSQL host: ${PG_HOST}"

    mark_done "03-postgres"
fi

# ─── Step 4: Configure Managed Identity + Key Vault ─────────────────────────
if step_done "04-identity"; then
    log_info "Step 04-identity: already done, skipping"
else
    log_info "Step 04: Configuring Managed Identity and Key Vault..."

    KV_NAME="ai-kv-${INQUIRY_AZURE_RESOURCE_GROUP:0:10}"

    # Create Key Vault
    if az keyvault show --name "${KV_NAME}" --resource-group "${INQUIRY_AZURE_RESOURCE_GROUP}" --output none 2>/dev/null; then
        log_warn "Key Vault '${KV_NAME}' already exists"
    else
        az keyvault create \
            --name "${KV_NAME}" \
            --resource-group "${INQUIRY_AZURE_RESOURCE_GROUP}" \
            --location "${INQUIRY_AZURE_LOCATION}" \
            --output none
    fi

    # Store API key
    az keyvault secret set \
        --vault-name "${KV_NAME}" \
        --name "ai-api-key" \
        --value "${INQUIRY_API_KEY}" \
        --output none
    log_ok "API key stored in Key Vault '${KV_NAME}'"

    echo "${KV_NAME}" > "${INQUIRY_DEPLOY_STATE_DIR}/kv-name.txt"
    mark_done "04-identity"
fi

# ─── Step 5: Build and push container to ACR ─────────────────────────────────
if step_done "05-container"; then
    log_info "Step 05-container: already done, skipping"
else
    log_info "Step 05: Building and pushing container to ACR '${INQUIRY_ACR_NAME}'..."

    # Create ACR if needed
    if az acr show --name "${INQUIRY_ACR_NAME}" --resource-group "${INQUIRY_AZURE_RESOURCE_GROUP}" --output none 2>/dev/null; then
        log_warn "ACR '${INQUIRY_ACR_NAME}' already exists"
    else
        az acr create \
            --name "${INQUIRY_ACR_NAME}" \
            --resource-group "${INQUIRY_AZURE_RESOURCE_GROUP}" \
            --location "${INQUIRY_AZURE_LOCATION}" \
            --sku Basic \
            --output none
    fi

    ACR_LOGIN_SERVER=$(az acr show \
        --name "${INQUIRY_ACR_NAME}" \
        --resource-group "${INQUIRY_AZURE_RESOURCE_GROUP}" \
        --query "loginServer" \
        --output tsv)

    IMAGE_PATH="${ACR_LOGIN_SERVER}/agentic-inquiry:${INQUIRY_IMAGE_TAG}"

    az acr login --name "${INQUIRY_ACR_NAME}"

    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

    docker build --tag "${IMAGE_PATH}" "${REPO_ROOT}"
    docker push "${IMAGE_PATH}"
    echo "${IMAGE_PATH}" > "${INQUIRY_DEPLOY_STATE_DIR}/image-path.txt"

    mark_done "05-container"
fi

# ─── Step 6: Deploy to Container Apps ────────────────────────────────────────
if step_done "06-container-apps"; then
    log_info "Step 06-container-apps: already done, skipping"
else
    log_info "Step 06: Deploying to Azure Container Apps..."

    IMAGE_PATH=$(cat "${INQUIRY_DEPLOY_STATE_DIR}/image-path.txt")
    PG_HOST=$(cat "${INQUIRY_DEPLOY_STATE_DIR}/pg-host.txt" 2>/dev/null || echo "")

    # Create Container Apps Environment
    if az containerapp env show \
        --name "${INQUIRY_CA_ENV_NAME}" \
        --resource-group "${INQUIRY_AZURE_RESOURCE_GROUP}" \
        --output none 2>/dev/null; then
        log_warn "Container Apps Environment '${INQUIRY_CA_ENV_NAME}' already exists"
    else
        az containerapp env create \
            --name "${INQUIRY_CA_ENV_NAME}" \
            --resource-group "${INQUIRY_AZURE_RESOURCE_GROUP}" \
            --location "${INQUIRY_AZURE_LOCATION}" \
            --output none
    fi

    # Deploy container app
    az containerapp create \
        --name "${INQUIRY_SERVICE_NAME}" \
        --resource-group "${INQUIRY_AZURE_RESOURCE_GROUP}" \
        --environment "${INQUIRY_CA_ENV_NAME}" \
        --image "${IMAGE_PATH}" \
        --registry-server "$(echo "${IMAGE_PATH}" | cut -d'/' -f1)" \
        --target-port 8000 \
        --ingress external \
        --min-replicas 1 \
        --max-replicas 10 \
        --cpu 1.0 \
        --memory 2.0Gi \
        --env-vars \
            "INQUIRY_ENV=${INQUIRY_SERVICE_NAME}" \
            "INQUIRY_STORAGE_BACKEND=postgresql" \
            "INQUIRY_DB_HOST=${PG_HOST}" \
            "INQUIRY_DB_NAME=${INQUIRY_DB_NAME}" \
            "INQUIRY_DB_USER=${INQUIRY_DB_USER}" \
            "INQUIRY_API_KEY=${INQUIRY_API_KEY}" \
        --output none 2>/dev/null || \
    az containerapp update \
        --name "${INQUIRY_SERVICE_NAME}" \
        --resource-group "${INQUIRY_AZURE_RESOURCE_GROUP}" \
        --image "${IMAGE_PATH}" \
        --output none

    # Get service URL
    APP_FQDN=$(az containerapp show \
        --name "${INQUIRY_SERVICE_NAME}" \
        --resource-group "${INQUIRY_AZURE_RESOURCE_GROUP}" \
        --query "properties.configuration.ingress.fqdn" \
        --output tsv)
    echo "https://${APP_FQDN}" > "${INQUIRY_DEPLOY_STATE_DIR}/service-url.txt"
    log_ok "Container App URL: https://${APP_FQDN}"

    mark_done "06-container-apps"
fi

# ─── Step 7: Smoke test ────────────────────────────────────────────────────────
if step_done "07-smoke-test"; then
    log_info "Step 07-smoke-test: already done, skipping"
else
    log_info "Step 07: Running smoke test..."
    SERVICE_URL=$(cat "${INQUIRY_DEPLOY_STATE_DIR}/service-url.txt" 2>/dev/null || "")
    [[ -n "${SERVICE_URL}" ]] || die "Service URL not found"

    HEALTH_URL="${SERVICE_URL}/api/v1/health"
    MAX_ATTEMPTS=30
    SLEEP_SECONDS=10

    for i in $(seq 1 "${MAX_ATTEMPTS}"); do
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "${HEALTH_URL}" 2>/dev/null || echo "000")
        if [[ "${HTTP_CODE}" == "200" ]]; then
            log_ok "Health check passed (attempt ${i})"
            mark_done "07-smoke-test"
            break
        fi
        [[ "${i}" -lt "${MAX_ATTEMPTS}" ]] && { log_info "  Attempt ${i}/${MAX_ATTEMPTS}: HTTP ${HTTP_CODE}..."; sleep "${SLEEP_SECONDS}"; } \
            || die "Smoke test failed after ${MAX_ATTEMPTS} attempts"
    done
fi

SERVICE_URL=$(cat "${INQUIRY_DEPLOY_STATE_DIR}/service-url.txt" 2>/dev/null || "unknown")
log_ok "======================================================"
log_ok "Agentic Inquiry deployed successfully to Azure!"
log_ok "  Subscription: ${INQUIRY_AZURE_SUBSCRIPTION_ID}"
log_ok "  Resource Grp: ${INQUIRY_AZURE_RESOURCE_GROUP}"
log_ok "  Service:      ${INQUIRY_SERVICE_NAME}"
log_ok "  URL:          ${SERVICE_URL}"
log_ok "======================================================"
