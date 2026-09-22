#!/usr/bin/env bash
#
# gcp-test-cleanup.sh - List and clean up old Cloud SQL test environments
#
# Usage:
#   ./gcp-test-cleanup.sh --project=PROJECT_ID [OPTIONS]
#
# Options:
#   --project         GCP project ID (required)
#   --list            List all test environments
#   --older-than=H    Clean up environments older than H hours
#   --test-id=ID      Clean up specific test ID
#   --force           Skip confirmation prompts
#   --help            Show this help message
#
# Examples:
#   ./gcp-test-cleanup.sh --project=my-project --list
#   ./gcp-test-cleanup.sh --project=my-project --older-than=24
#   ./gcp-test-cleanup.sh --project=my-project --test-id=20260113-120000-abc123
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Default values
PROJECT=""
LIST_ONLY=false
OLDER_THAN=""
TEST_ID=""
FORCE=false

# Parse arguments
for arg in "$@"; do
    case $arg in
        --project=*)
            PROJECT="${arg#*=}"
            ;;
        --list)
            LIST_ONLY=true
            ;;
        --older-than=*)
            OLDER_THAN="${arg#*=}"
            ;;
        --test-id=*)
            TEST_ID="${arg#*=}"
            ;;
        --force)
            FORCE=true
            ;;
        --help)
            head -22 "$0" | tail -20
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
    echo "Usage: $0 --project=PROJECT_ID [--list|--older-than=H|--test-id=ID]"
    exit 1
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  GCP Cloud SQL Test Environment Cleanup${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "Project: ${GREEN}${PROJECT}${NC}"
echo ""

# Get list of test instances
echo -e "${YELLOW}Scanning for test instances...${NC}"
INSTANCES=$(gcloud sql instances list --project="$PROJECT" --format="csv[no-heading](name,createTime,state)" 2>/dev/null | grep "^agv-test-" || echo "")

if [[ -z "$INSTANCES" ]]; then
    echo -e "${GREEN}No test instances found.${NC}"

    # Also check for orphaned env files
    ENV_DIR=".agv/test"
    ENV_FILES=$(ls -1 "${ENV_DIR}"/gcp-test-*.env .gcp-test-*.env 2>/dev/null || echo "")
    if [[ -n "$ENV_FILES" ]]; then
        echo ""
        echo -e "${YELLOW}Found orphaned env files:${NC}"
        echo "$ENV_FILES"
        if [[ "$FORCE" == true ]] || [[ "$LIST_ONLY" != true ]]; then
            read -p "Delete orphaned env files? [y/N] " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                rm -f "${ENV_DIR}"/gcp-test-*.env .gcp-test-*.env 2>/dev/null
                echo -e "${GREEN}  ✓ Deleted orphaned env files${NC}"
            fi
        fi
    fi
    exit 0
fi

# Parse and display instances
echo ""
echo -e "${CYAN}Test Instances:${NC}"
echo "----------------------------------------"
printf "%-40s %-20s %-10s %-10s\n" "INSTANCE" "CREATED" "AGE" "STATE"
echo "----------------------------------------"

NOW=$(date +%s)
declare -a INSTANCES_TO_DELETE=()

# Cross-platform date parsing function
parse_date() {
    local datestr="$1"
    # Try GNU date first (Linux), then BSD date (macOS)
    if date -d "$datestr" +%s 2>/dev/null; then
        return
    elif date -j -f "%Y-%m-%dT%H:%M:%S" "${datestr%.*}" +%s 2>/dev/null; then
        return
    else
        echo "0"
    fi
}

while IFS=',' read -r name created state; do
    # Extract test ID from instance name
    test_id="${name#agv-test-}"

    # Calculate age in hours
    created_ts=$(parse_date "$created")
    if [[ "$created_ts" -gt 0 ]]; then
        age_seconds=$((NOW - created_ts))
        age_hours=$((age_seconds / 3600))
        age_display="${age_hours}h"
    else
        age_hours=0
        age_display="unknown"
    fi

    # Format created time
    created_short="${created:0:16}"

    printf "%-40s %-20s %-10s %-10s\n" "$name" "$created_short" "$age_display" "$state"

    # Check if this instance should be deleted
    if [[ -n "$TEST_ID" && "$test_id" == "$TEST_ID" ]]; then
        INSTANCES_TO_DELETE+=("$name")
    elif [[ -n "$OLDER_THAN" && "$age_hours" -ge "$OLDER_THAN" ]]; then
        INSTANCES_TO_DELETE+=("$name")
    fi
done <<< "$INSTANCES"

echo "----------------------------------------"

# Also list local env files
echo ""
echo -e "${CYAN}Local Environment Files:${NC}"
ENV_DIR=".agv/test"
if ls "${ENV_DIR}"/gcp-test-*.env .gcp-test-*.env 1>/dev/null 2>&1; then
    ls -la "${ENV_DIR}"/gcp-test-*.env .gcp-test-*.env 2>/dev/null
else
    echo "  (none)"
fi

# If just listing, exit
if [[ "$LIST_ONLY" == true ]]; then
    exit 0
fi

# If no cleanup criteria specified
if [[ -z "$TEST_ID" && -z "$OLDER_THAN" ]]; then
    echo ""
    echo -e "${YELLOW}Specify --test-id=ID or --older-than=H to clean up instances${NC}"
    exit 0
fi

# Delete instances
if [[ ${#INSTANCES_TO_DELETE[@]} -eq 0 ]]; then
    echo ""
    echo -e "${GREEN}No instances match the cleanup criteria.${NC}"
    exit 0
fi

echo ""
echo -e "${YELLOW}Instances to delete:${NC}"
for instance in "${INSTANCES_TO_DELETE[@]}"; do
    echo "  - $instance"
done
echo ""

if [[ "$FORCE" != true ]]; then
    read -p "Delete these instances? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Cancelled.${NC}"
        exit 0
    fi
fi

# Perform deletion
for instance in "${INSTANCES_TO_DELETE[@]}"; do
    echo -e "${YELLOW}Deleting ${instance}...${NC}"
    test_id="${instance#agv-test-}"

    # Delete instance
    gcloud sql instances delete "$instance" --project="$PROJECT" --quiet
    echo -e "${GREEN}  ✓ Instance deleted${NC}"

    # Delete env file if exists
    env_file=".agv/test/gcp-test-${test_id}.env"
    legacy_env_file=".gcp-test-${test_id}.env"
    if [[ -f "$env_file" ]]; then
        rm -f "$env_file"
        echo -e "${GREEN}  ✓ Removed ${env_file}${NC}"
    elif [[ -f "$legacy_env_file" ]]; then
        rm -f "$legacy_env_file"
        echo -e "${GREEN}  ✓ Removed legacy ${legacy_env_file}${NC}"
    fi
done

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Cleanup Complete${NC}"
echo -e "${GREEN}========================================${NC}"
