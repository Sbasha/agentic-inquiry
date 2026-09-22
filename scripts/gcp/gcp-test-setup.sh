#!/usr/bin/env bash
#
# gcp-test-setup.sh - Create a Cloud SQL test environment
#
# Usage:
#   ./gcp-test-setup.sh --project=PROJECT_ID [--region=REGION] [--test-id=ID] [--tier=TIER]
#
# Parameters:
#   --project     GCP project ID (required)
#   --region      GCP region (default: us-central1)
#   --test-id     Unique test identifier (default: timestamp-based)
#   --tier        Machine tier (default: db-f1-micro)
#   --help        Show this help message
#
# Output:
#   Creates .agentic-inquiry/test/gcp-test-{TEST_ID}.env with connection details
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
REGION="us-central1"
TIER="db-f1-micro"
TEST_ID=""
PROJECT=""

# Parse arguments
for arg in "$@"; do
    case $arg in
        --project=*)
            PROJECT="${arg#*=}"
            ;;
        --region=*)
            REGION="${arg#*=}"
            ;;
        --test-id=*)
            TEST_ID="${arg#*=}"
            ;;
        --tier=*)
            TIER="${arg#*=}"
            ;;
        --help)
            head -20 "$0" | tail -18
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown argument: $arg${NC}"
            exit 1
            ;;
    esac
done

# Validate required parameters
if [[ -z "$PROJECT" ]]; then
    echo -e "${RED}Error: --project is required${NC}"
    echo "Usage: $0 --project=PROJECT_ID [--region=REGION] [--test-id=ID]"
    exit 1
fi

# Cross-platform random string generation
generate_random() {
    if command -v openssl &>/dev/null; then
        openssl rand -hex 4
    elif [[ -r /dev/urandom ]]; then
        head -c 4 /dev/urandom | xxd -p
    else
        echo "$(date +%N)" | md5sum | head -c 8
    fi
}

# Generate TEST_ID if not provided
if [[ -z "$TEST_ID" ]]; then
    TEST_ID="$(date +%Y%m%d-%H%M%S)-$(generate_random)"
fi

# Derived names
INSTANCE_NAME="ai-test-${TEST_ID}"
DATABASE_NAME="agentic-inquiry_test"
USER_NAME="ai_test_user"
# Cross-platform password generation
generate_password() {
    if command -v openssl &>/dev/null; then
        openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 20
    elif [[ -r /dev/urandom ]]; then
        head -c 20 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 20
    else
        date +%s%N | sha256sum | head -c 20
    fi
}
USER_PASSWORD="$(generate_password)"
ENV_DIR=".agentic-inquiry/test"
mkdir -p "$ENV_DIR"
ENV_FILE="${ENV_DIR}/gcp-test-${TEST_ID}.env"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  GCP Cloud SQL Test Environment Setup${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "Project:      ${GREEN}${PROJECT}${NC}"
echo -e "Region:       ${GREEN}${REGION}${NC}"
echo -e "Test ID:      ${GREEN}${TEST_ID}${NC}"
echo -e "Instance:     ${GREEN}${INSTANCE_NAME}${NC}"
echo -e "Tier:         ${GREEN}${TIER}${NC}"
echo ""

# Step 1: Validate gcloud auth
echo -e "${YELLOW}[1/7] Validating gcloud authentication...${NC}"
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null | head -1; then
    echo -e "${RED}Error: Not authenticated with gcloud${NC}"
    echo "Run: gcloud auth login"
    exit 1
fi
echo -e "${GREEN}  ✓ Authenticated${NC}"

# Step 2: Set project
echo -e "${YELLOW}[2/7] Setting project...${NC}"
gcloud config set project "$PROJECT" --quiet
echo -e "${GREEN}  ✓ Project set to ${PROJECT}${NC}"

# Step 3: Enable required APIs
echo -e "${YELLOW}[3/7] Enabling required APIs...${NC}"
gcloud services enable sqladmin.googleapis.com compute.googleapis.com --quiet
echo -e "${GREEN}  ✓ APIs enabled${NC}"

# Step 4: Create Cloud SQL instance
echo -e "${YELLOW}[4/7] Creating Cloud SQL instance (this may take 5-10 minutes)...${NC}"
if gcloud sql instances describe "$INSTANCE_NAME" --project="$PROJECT" &>/dev/null; then
    echo -e "${YELLOW}  Instance already exists, reusing...${NC}"
else
    gcloud sql instances create "$INSTANCE_NAME" \
        --project="$PROJECT" \
        --database-version=POSTGRES_15 \
        --tier="$TIER" \
        --region="$REGION" \
        --storage-type=SSD \
        --storage-size=10GB \
        --root-password="$USER_PASSWORD" \
        --quiet
fi
echo -e "${GREEN}  ✓ Instance created${NC}"

# Step 5: Create database
echo -e "${YELLOW}[5/7] Creating database...${NC}"
if gcloud sql databases describe "$DATABASE_NAME" --instance="$INSTANCE_NAME" --project="$PROJECT" &>/dev/null; then
    echo -e "${YELLOW}  Database already exists, reusing...${NC}"
else
    gcloud sql databases create "$DATABASE_NAME" --instance="$INSTANCE_NAME" --quiet
fi
echo -e "${GREEN}  ✓ Database created${NC}"

# Step 6: Create user
echo -e "${YELLOW}[6/7] Creating database user...${NC}"
if gcloud sql users describe "$USER_NAME" --instance="$INSTANCE_NAME" --project="$PROJECT" &>/dev/null; then
    echo -e "${YELLOW}  User already exists, updating password...${NC}"
    gcloud sql users set-password "$USER_NAME" --instance="$INSTANCE_NAME" --password="$USER_PASSWORD" --quiet
else
    gcloud sql users create "$USER_NAME" --instance="$INSTANCE_NAME" --password="$USER_PASSWORD" --quiet
fi
echo -e "${GREEN}  ✓ User created${NC}"

# Step 7: Get connection info and enable pgvector
echo -e "${YELLOW}[7/7] Finalizing setup...${NC}"
CONNECTION_NAME=$(gcloud sql instances describe "$INSTANCE_NAME" --format="value(connectionName)")
PUBLIC_IP=$(gcloud sql instances describe "$INSTANCE_NAME" --format="value(ipAddresses[0].ipAddress)" 2>/dev/null || echo "")

# Cross-platform UTC date
utc_date() {
    if date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null; then
        return
    else
        date +"%Y-%m-%dT%H:%M:%SZ"
    fi
}

# Write env file
cat > "$ENV_FILE" << EOF
# GCP Cloud SQL Test Environment
# Created: $(utc_date)
# Test ID: ${TEST_ID}

export GCP_TEST_ID="${TEST_ID}"
export GCP_PROJECT="${PROJECT}"
export GCP_REGION="${REGION}"
export GCP_INSTANCE_NAME="${INSTANCE_NAME}"
export GCP_CONNECTION_NAME="${CONNECTION_NAME}"
export GCP_DATABASE="${DATABASE_NAME}"
export GCP_USER="${USER_NAME}"
export GCP_PASSWORD="${USER_PASSWORD}"
export GCP_PUBLIC_IP="${PUBLIC_IP}"

# Connection string for direct connection (requires Cloud SQL Proxy or authorized network)
export GCP_CONNECTION_STRING="postgresql://${USER_NAME}:${USER_PASSWORD}@localhost:5432/${DATABASE_NAME}"

# For agentic-inquiry BackendConfig
export CLOUDSQL_PROJECT="${PROJECT}"
export CLOUDSQL_REGION="${REGION}"
export CLOUDSQL_INSTANCE="${INSTANCE_NAME}"
export CLOUDSQL_DATABASE="${DATABASE_NAME}"
export CLOUDSQL_USER="${USER_NAME}"

# Generic connection string for agentic-inquiry.yaml
export DB_CONNECTION_STRING="postgresql://${USER_NAME}:${USER_PASSWORD}@localhost:5433/${DATABASE_NAME}"
EOF

chmod 600 "$ENV_FILE"

echo -e "${GREEN}  ✓ Setup complete${NC}"
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Environment Ready${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "Environment file: ${GREEN}${ENV_FILE}${NC}"
echo ""
echo "To use this environment:"
echo -e "  ${YELLOW}source ${ENV_FILE}${NC}"
echo ""
echo "To start Cloud SQL Proxy:"
echo -e "  ${YELLOW}cloud-sql-proxy --port 5432 ${CONNECTION_NAME}${NC}"
echo ""
echo "To run tests:"
echo -e "  ${YELLOW}uv run pytest tests/integration/postgresql/ -v${NC}"
echo ""
echo "To tear down:"
echo -e "  ${YELLOW}./scripts/gcp/gcp-test-teardown.sh --test-id=${TEST_ID}${NC}"
echo ""
