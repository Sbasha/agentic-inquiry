#!/usr/bin/env bash
#
# azure-undeploy.sh — Tear down a Agentic Inquiry Azure deployment
#
# Required environment variables:
#   INQUIRY_AZURE_SUBSCRIPTION_ID  Azure subscription ID (required)
#   INQUIRY_AZURE_RESOURCE_GROUP   Azure resource group (required)
#
# Optional environment variables:
#   INQUIRY_SERVICE_NAME           Container App name (default: agentic-inquiry)
#   INQUIRY_PG_SERVER_NAME         PostgreSQL server name (default: ai-postgres)
#   INQUIRY_CA_ENV_NAME            Container Apps Environment name (default: ai-env)
#   INQUIRY_DEPLOY_STATE_DIR       Dir containing state markers (default: .agentic-inquiry/deploy)
#   INQUIRY_DELETE_RESOURCE_GROUP  Set to "1" to delete the entire resource group (default: 0)
#

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
die()       { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

INQUIRY_SERVICE_NAME="${INQUIRY_SERVICE_NAME:-agentic-inquiry}"
INQUIRY_PG_SERVER_NAME="${INQUIRY_PG_SERVER_NAME:-ai-postgres}"
INQUIRY_CA_ENV_NAME="${INQUIRY_CA_ENV_NAME:-ai-env}"
INQUIRY_DEPLOY_STATE_DIR="${INQUIRY_DEPLOY_STATE_DIR:-.agentic-inquiry/deploy}"
INQUIRY_DELETE_RESOURCE_GROUP="${INQUIRY_DELETE_RESOURCE_GROUP:-0}"

[[ -n "${INQUIRY_AZURE_SUBSCRIPTION_ID:-}" ]] || die "INQUIRY_AZURE_SUBSCRIPTION_ID is required"
[[ -n "${INQUIRY_AZURE_RESOURCE_GROUP:-}" ]]  || die "INQUIRY_AZURE_RESOURCE_GROUP is required"

az account set --subscription "${INQUIRY_AZURE_SUBSCRIPTION_ID}" 2>/dev/null || true

if [[ "${INQUIRY_DELETE_RESOURCE_GROUP}" == "1" ]]; then
    log_info "Deleting resource group '${INQUIRY_AZURE_RESOURCE_GROUP}' and all its resources..."
    az group delete --name "${INQUIRY_AZURE_RESOURCE_GROUP}" --yes --no-wait --output none
    log_ok "Resource group deletion initiated (background)"
else
    # Granular teardown (reverse deploy order)
    log_info "Deleting Container App '${INQUIRY_SERVICE_NAME}'..."
    az containerapp delete \
        --name "${INQUIRY_SERVICE_NAME}" \
        --resource-group "${INQUIRY_AZURE_RESOURCE_GROUP}" \
        --yes --output none 2>/dev/null || log_warn "Container App not found, skipping"

    log_info "Deleting Container Apps Environment '${INQUIRY_CA_ENV_NAME}'..."
    az containerapp env delete \
        --name "${INQUIRY_CA_ENV_NAME}" \
        --resource-group "${INQUIRY_AZURE_RESOURCE_GROUP}" \
        --yes --output none 2>/dev/null || log_warn "Environment not found, skipping"

    log_info "Deleting PostgreSQL server '${INQUIRY_PG_SERVER_NAME}'..."
    az postgres flexible-server delete \
        --name "${INQUIRY_PG_SERVER_NAME}" \
        --resource-group "${INQUIRY_AZURE_RESOURCE_GROUP}" \
        --yes --output none 2>/dev/null || log_warn "PostgreSQL server not found, skipping"

    KV_NAME="ai-kv-${INQUIRY_AZURE_RESOURCE_GROUP:0:10}"
    log_info "Purging Key Vault '${KV_NAME}'..."
    az keyvault delete --name "${KV_NAME}" --resource-group "${INQUIRY_AZURE_RESOURCE_GROUP}" --output none 2>/dev/null || true
    az keyvault purge --name "${KV_NAME}" --output none 2>/dev/null || true
fi

log_info "Removing deploy state markers..."
if [[ -d "${INQUIRY_DEPLOY_STATE_DIR}" ]]; then
    rm -f "${INQUIRY_DEPLOY_STATE_DIR}"/step-*.done \
          "${INQUIRY_DEPLOY_STATE_DIR}"/azure-state.json \
          "${INQUIRY_DEPLOY_STATE_DIR}"/service-url.txt \
          "${INQUIRY_DEPLOY_STATE_DIR}"/image-path.txt \
          "${INQUIRY_DEPLOY_STATE_DIR}"/pg-host.txt \
          "${INQUIRY_DEPLOY_STATE_DIR}"/kv-name.txt
fi

log_ok "Azure undeploy complete for resource group '${INQUIRY_AZURE_RESOURCE_GROUP}'"
