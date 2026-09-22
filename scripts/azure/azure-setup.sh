#!/usr/bin/env bash
# Azure Database for PostgreSQL setup for Agentic Inquiry
#
# Prerequisites:
#   - Azure CLI installed and authenticated (az login)
#   - Subscription with Azure Database for PostgreSQL and Azure OpenAI access
#
# Usage:
#   ./azure-setup.sh --resource-group MY_RG --server-name MY_SERVER --location eastus

set -euo pipefail

# Defaults
RG=""
SERVER=""
LOCATION="eastus"
DATABASE="agentic-inquiry"
ADMIN_USER="agvadmin"
ADMIN_PASSWORD=""
OPENAI_NAME=""
OPENAI_DEPLOYMENT="text-embedding-3-small"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --resource-group) RG="$2"; shift 2 ;;
        --server-name) SERVER="$2"; shift 2 ;;
        --location) LOCATION="$2"; shift 2 ;;
        --database) DATABASE="$2"; shift 2 ;;
        --password) ADMIN_PASSWORD="$2"; shift 2 ;;
        --openai-name) OPENAI_NAME="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -z "${RG}" || -z "${SERVER}" ]]; then
    echo "Error: --resource-group and --server-name are required."
    exit 1
fi

echo "=== Azure PostgreSQL Setup for Agentic Inquiry ==="
echo "Resource Group: ${RG}"
echo "Server Name:    ${SERVER}"
echo "Location:       ${LOCATION}"
echo "Database:       ${DATABASE}"
echo ""

# Step 1: Create Resource Group
echo "--- Ensuring Resource Group exists ---"
az group create --name "${RG}" --location "${LOCATION}" --quiet

# Step 2: Create PostgreSQL Flexible Server
echo ""
echo "--- Creating Azure PostgreSQL Flexible Server ---"
# Note: We enable azure_ai and vector extensions in the server parameters
CREATE_CMD=(
    az postgres flexible-server create
    --resource-group "${RG}"
    --name "${SERVER}"
    --location "${LOCATION}"
    --admin-user "${ADMIN_USER}"
    --database-name "${DATABASE}"
    --public-access 0.0.0.0
)

if [[ -n "${ADMIN_PASSWORD}" ]]; then
    CREATE_CMD+=(--admin-password "${ADMIN_PASSWORD}")
fi

"${CREATE_CMD[@]}"

# Step 3: Enable extensions in server parameters
echo ""
echo "--- Enabling 'azure_ai' and 'vector' extensions ---"
az postgres flexible-server parameter set \
    --resource-group "${RG}" \
    --server-name "${SERVER}" \
    --name "azure.extensions" \
    --value "VECTOR,AZURE_AI"

# Step 4: Setup Azure OpenAI (Optional but recommended)
if [[ -n "${OPENAI_NAME}" ]]; then
    echo ""
    echo "--- Configuring Azure OpenAI Integration ---"
    # Get the endpoint and key
    ENDPOINT=$(az cognitiveservices account show --name "${OPENAI_NAME}" --resource-group "${RG}" --query "properties.endpoint" -o tsv)
    KEY=$(az cognitiveservices account keys list --name "${OPENAI_NAME}" --resource-group "${RG}" --query "key1" -o tsv)
    
    echo "Azure OpenAI integration requires connecting to the database and running:"
    echo "  SELECT azure_ai.set_setting('azure_openai.endpoint', '${ENDPOINT}');"
    echo "  SELECT azure_ai.set_setting('azure_openai.subscription_key', '${KEY}');"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Connect to your database:"
echo "     psql \"host=${SERVER}.postgres.database.azure.com port=5432 dbname=${DATABASE} user=${ADMIN_USER} password=YOUR_PASSWORD sslmode=require\""
echo ""
echo "  2. Enable the extensions inside the database:"
echo "     CREATE EXTENSION IF NOT EXISTS vector;"
echo "     CREATE EXTENSION IF NOT EXISTS azure_ai;"
echo ""
echo "  3. Configure Agentic Inquiry:"
echo "     ai setup azure"
