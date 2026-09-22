#!/usr/bin/env bash
# AlloyDB cluster and instance setup for Agent-Vault
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - AlloyDB API enabled: gcloud services enable alloydb.googleapis.com
#   - Vertex AI API enabled: gcloud services enable aiplatform.googleapis.com
#
# Usage:
#   ./alloydb-setup.sh [--project PROJECT] [--region REGION] [--cluster CLUSTER] [--instance INSTANCE]

set -euo pipefail

# Defaults
PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
CLUSTER="${CLUSTER:-agv-cluster}"
INSTANCE="${INSTANCE:-agv-primary}"
DATABASE="${DATABASE:-agent-vault}"
NETWORK="${NETWORK:-default}"
PASSWORD="${PASSWORD:-}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --project) PROJECT="$2"; shift 2 ;;
        --region) REGION="$2"; shift 2 ;;
        --cluster) CLUSTER="$2"; shift 2 ;;
        --instance) INSTANCE="$2"; shift 2 ;;
        --database) DATABASE="$2"; shift 2 ;;
        --network) NETWORK="$2"; shift 2 ;;
        --password) PASSWORD="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo "=== AlloyDB Setup for Agent-Vault ==="
echo "Project:  ${PROJECT}"
echo "Region:   ${REGION}"
echo "Cluster:  ${CLUSTER}"
echo "Instance: ${INSTANCE}"
echo "Database: ${DATABASE}"
echo ""

# Step 1: Enable required APIs
echo "--- Enabling required APIs ---"
gcloud services enable alloydb.googleapis.com --project="${PROJECT}" 2>/dev/null || true
gcloud services enable aiplatform.googleapis.com --project="${PROJECT}" 2>/dev/null || true
echo "APIs enabled."

# Step 2: Create AlloyDB cluster
echo ""
echo "--- Creating AlloyDB cluster: ${CLUSTER} ---"
if gcloud alloydb clusters describe "${CLUSTER}" --project="${PROJECT}" --region="${REGION}" &>/dev/null; then
    echo "Cluster '${CLUSTER}' already exists."
else
    CLUSTER_CMD=(
        gcloud alloydb clusters create "${CLUSTER}"
        --project="${PROJECT}"
        --region="${REGION}"
        --network="${NETWORK}"
    )
    if [[ -n "${PASSWORD}" ]]; then
        CLUSTER_CMD+=(--password="${PASSWORD}")
    fi
    "${CLUSTER_CMD[@]}"
    echo "Cluster '${CLUSTER}' created."
fi

# Step 3: Create primary instance
echo ""
echo "--- Creating primary instance: ${INSTANCE} ---"
if gcloud alloydb instances describe "${INSTANCE}" --project="${PROJECT}" --region="${REGION}" --cluster="${CLUSTER}" &>/dev/null; then
    echo "Instance '${INSTANCE}' already exists."
else
    gcloud alloydb instances create "${INSTANCE}" \
        --project="${PROJECT}" \
        --region="${REGION}" \
        --cluster="${CLUSTER}" \
        --instance-type=PRIMARY \
        --cpu-count=2 \
        --database-flags="google_ml_integration.enable_model_support=on"
    echo "Instance '${INSTANCE}' created."
fi

# Step 4: Grant Vertex AI permissions to AlloyDB service agent
echo ""
echo "--- Granting Vertex AI permissions ---"
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT}" --format="value(projectNumber)")
SERVICE_AGENT="service-${PROJECT_NUMBER}@gcp-sa-alloydb.iam.gserviceaccount.com"

gcloud projects add-iam-policy-binding "${PROJECT}" \
    --member="serviceAccount:${SERVICE_AGENT}" \
    --role="roles/aiplatform.user" \
    --condition=None \
    --quiet 2>/dev/null || echo "IAM binding may already exist."
echo "Vertex AI permissions granted to AlloyDB service agent."

# Step 5: Create database
echo ""
echo "--- Creating database: ${DATABASE} ---"
# Note: AlloyDB database creation requires connecting via psql or alloydb-auth-proxy
echo "To create the database, connect via alloydb-auth-proxy and run:"
echo "  CREATE DATABASE ${DATABASE};"
echo ""
echo "To enable required extensions, run:"
echo "  CREATE EXTENSION IF NOT EXISTS vector;"
echo "  CREATE EXTENSION IF NOT EXISTS google_ml_integration;"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Install alloydb-auth-proxy:"
echo "     curl -o alloydb-auth-proxy https://storage.googleapis.com/alloydb-auth-proxy/v1.10.1/alloydb-auth-proxy.darwin.arm64"
echo "     chmod +x alloydb-auth-proxy && mv alloydb-auth-proxy /usr/local/bin/"
echo ""
echo "  2. Start the proxy:"
echo "     alloydb-auth-proxy \\"
echo "       projects/${PROJECT}/locations/${REGION}/clusters/${CLUSTER}/instances/${INSTANCE} \\"
echo "       --port=5432"
echo ""
echo "  3. Connect and create database:"
echo "     psql -h 127.0.0.1 -p 5432 -U postgres -c 'CREATE DATABASE ${DATABASE};'"
echo "     psql -h 127.0.0.1 -p 5432 -U postgres -d ${DATABASE} -c 'CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS google_ml_integration;'"
echo ""
echo "  4. Configure Agent-Vault:"
echo "     agv setup alloydb"
