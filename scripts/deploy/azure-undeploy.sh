#!/usr/bin/env bash
#
# azure-undeploy.sh — Tear down a Agent-Vault Azure deployment
#
# Required environment variables:
#   agv_AZURE_SUBSCRIPTION_ID  Azure subscription ID (required)
#   agv_AZURE_RESOURCE_GROUP   Azure resource group (required)
#
# Optional environment variables:
#   agv_SERVICE_NAME           Container App name (default: agent-vault)
#   agv_PG_SERVER_NAME         PostgreSQL server name (default: agv-postgres)
#   agv_CA_ENV_NAME            Container Apps Environment name (default: agv-env)
#   agv_DEPLOY_STATE_DIR       Dir containing state markers (default: .agv/deploy)
#   agv_DELETE_RESOURCE_GROUP  Set to "1" to delete the entire resource group (default: 0)
#

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
die()       { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

agv_SERVICE_NAME="${agv_SERVICE_NAME:-agent-vault}"
agv_PG_SERVER_NAME="${agv_PG_SERVER_NAME:-agv-postgres}"
agv_CA_ENV_NAME="${agv_CA_ENV_NAME:-agv-env}"
agv_DEPLOY_STATE_DIR="${agv_DEPLOY_STATE_DIR:-.agv/deploy}"
agv_DELETE_RESOURCE_GROUP="${agv_DELETE_RESOURCE_GROUP:-0}"

[[ -n "${agv_AZURE_SUBSCRIPTION_ID:-}" ]] || die "agv_AZURE_SUBSCRIPTION_ID is required"
[[ -n "${agv_AZURE_RESOURCE_GROUP:-}" ]]  || die "agv_AZURE_RESOURCE_GROUP is required"

az account set --subscription "${agv_AZURE_SUBSCRIPTION_ID}" 2>/dev/null || true

if [[ "${agv_DELETE_RESOURCE_GROUP}" == "1" ]]; then
    log_info "Deleting resource group '${agv_AZURE_RESOURCE_GROUP}' and all its resources..."
    az group delete --name "${agv_AZURE_RESOURCE_GROUP}" --yes --no-wait --output none
    log_ok "Resource group deletion initiated (background)"
else
    # Granular teardown (reverse deploy order)
    log_info "Deleting Container App '${agv_SERVICE_NAME}'..."
    az containerapp delete \
        --name "${agv_SERVICE_NAME}" \
        --resource-group "${agv_AZURE_RESOURCE_GROUP}" \
        --yes --output none 2>/dev/null || log_warn "Container App not found, skipping"

    log_info "Deleting Container Apps Environment '${agv_CA_ENV_NAME}'..."
    az containerapp env delete \
        --name "${agv_CA_ENV_NAME}" \
        --resource-group "${agv_AZURE_RESOURCE_GROUP}" \
        --yes --output none 2>/dev/null || log_warn "Environment not found, skipping"

    log_info "Deleting PostgreSQL server '${agv_PG_SERVER_NAME}'..."
    az postgres flexible-server delete \
        --name "${agv_PG_SERVER_NAME}" \
        --resource-group "${agv_AZURE_RESOURCE_GROUP}" \
        --yes --output none 2>/dev/null || log_warn "PostgreSQL server not found, skipping"

    KV_NAME="agv-kv-${agv_AZURE_RESOURCE_GROUP:0:10}"
    log_info "Purging Key Vault '${KV_NAME}'..."
    az keyvault delete --name "${KV_NAME}" --resource-group "${agv_AZURE_RESOURCE_GROUP}" --output none 2>/dev/null || true
    az keyvault purge --name "${KV_NAME}" --output none 2>/dev/null || true
fi

log_info "Removing deploy state markers..."
if [[ -d "${agv_DEPLOY_STATE_DIR}" ]]; then
    rm -f "${agv_DEPLOY_STATE_DIR}"/step-*.done \
          "${agv_DEPLOY_STATE_DIR}"/azure-state.json \
          "${agv_DEPLOY_STATE_DIR}"/service-url.txt \
          "${agv_DEPLOY_STATE_DIR}"/image-path.txt \
          "${agv_DEPLOY_STATE_DIR}"/pg-host.txt \
          "${agv_DEPLOY_STATE_DIR}"/kv-name.txt
fi

log_ok "Azure undeploy complete for resource group '${agv_AZURE_RESOURCE_GROUP}'"
