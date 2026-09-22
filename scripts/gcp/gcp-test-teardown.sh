#!/usr/bin/env bash
#
# gcp-test-teardown.sh - Tear down a Cloud SQL test environment
#
# Usage:
#   ./gcp-test-teardown.sh --test-id=ID [--project=PROJECT_ID]
#
# Parameters:
#   --test-id     Test identifier (required, or use --env-file)
#   --env-file    Path to env file (alternative to --test-id)
#   --project     GCP project ID (optional if env file exists)
#   --force       Skip confirmation prompt
#   --help        Show this help message
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default values
TEST_ID=""
PROJECT=""
ENV_FILE=""
FORCE=false

# Parse arguments
for arg in "$@"; do
    case $arg in
        --test-id=*)
            TEST_ID="${arg#*=}"
            ;;
        --project=*)
            PROJECT="${arg#*=}"
            ;;
        --env-file=*)
            ENV_FILE="${arg#*=}"
            ;;
        --force)
            FORCE=true
            ;;
        --help)
            head -16 "$0" | tail -14
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown argument: $arg${NC}"
            exit 1
            ;;
    esac
done

# Try to find env file if test-id provided
if [[ -n "$TEST_ID" && -z "$ENV_FILE" ]]; then
    ENV_FILE=".agv/test/gcp-test-${TEST_ID}.env"
    # Fallback to legacy location
    if [[ ! -f "$ENV_FILE" && -f ".gcp-test-${TEST_ID}.env" ]]; then
        ENV_FILE=".gcp-test-${TEST_ID}.env"
    fi
fi

# Load from env file if it exists
if [[ -n "$ENV_FILE" && -f "$ENV_FILE" ]]; then
    echo -e "${BLUE}Loading from ${ENV_FILE}...${NC}"
    source "$ENV_FILE"
    TEST_ID="${GCP_TEST_ID:-$TEST_ID}"
    PROJECT="${GCP_PROJECT:-$PROJECT}"
fi

# Validate required parameters
if [[ -z "$TEST_ID" ]]; then
    echo -e "${RED}Error: --test-id is required${NC}"
    echo "Usage: $0 --test-id=ID [--project=PROJECT_ID]"
    exit 1
fi

if [[ -z "$PROJECT" ]]; then
    echo -e "${RED}Error: --project is required (or provide --env-file)${NC}"
    exit 1
fi

INSTANCE_NAME="agv-test-${TEST_ID}"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  GCP Cloud SQL Test Environment Teardown${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "Project:      ${GREEN}${PROJECT}${NC}"
echo -e "Test ID:      ${GREEN}${TEST_ID}${NC}"
echo -e "Instance:     ${GREEN}${INSTANCE_NAME}${NC}"
echo ""

# Confirmation
if [[ "$FORCE" != true ]]; then
    echo -e "${YELLOW}This will permanently delete the Cloud SQL instance and all data.${NC}"
    read -p "Are you sure? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Cancelled.${NC}"
        exit 0
    fi
fi

# Step 1: Delete Cloud SQL instance
echo -e "${YELLOW}[1/2] Deleting Cloud SQL instance...${NC}"
if gcloud sql instances describe "$INSTANCE_NAME" --project="$PROJECT" &>/dev/null; then
    gcloud sql instances delete "$INSTANCE_NAME" --project="$PROJECT" --quiet
    echo -e "${GREEN}  ✓ Instance deleted${NC}"
else
    echo -e "${YELLOW}  Instance not found (already deleted?)${NC}"
fi

# Step 2: Clean up env file
echo -e "${YELLOW}[2/2] Cleaning up local files...${NC}"
ENV_FILE=".agv/test/gcp-test-${TEST_ID}.env"
LEGACY_ENV_FILE=".gcp-test-${TEST_ID}.env"
if [[ -f "$ENV_FILE" ]]; then
    rm -f "$ENV_FILE"
    echo -e "${GREEN}  ✓ Removed ${ENV_FILE}${NC}"
elif [[ -f "$LEGACY_ENV_FILE" ]]; then
    rm -f "$LEGACY_ENV_FILE"
    echo -e "${GREEN}  ✓ Removed legacy ${LEGACY_ENV_FILE}${NC}"
else
    echo -e "${YELLOW}  No env file found${NC}"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Teardown Complete${NC}"
echo -e "${GREEN}========================================${NC}"
