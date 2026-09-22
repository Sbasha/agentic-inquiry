#!/usr/bin/env bash
#
# aws-undeploy.sh — Tear down a Agentic Inquiry AWS deployment
#
# Required environment variables:
#   INQUIRY_AWS_ACCOUNT_ID     AWS account ID (required)
#
# Optional environment variables:
#   INQUIRY_AWS_REGION         AWS region (default: us-east-1)
#   INQUIRY_SERVICE_NAME       App Runner service name (default: agentic-inquiry)
#   INQUIRY_RDS_INSTANCE_ID    RDS instance identifier (default: ai-postgres)
#   INQUIRY_IAM_ROLE_NAME      IAM role name (default: ai-app-runner-role)
#   INQUIRY_ECR_REPO           ECR repository name (default: agentic-inquiry)
#   INQUIRY_DEPLOY_STATE_DIR   Dir containing state markers (default: .agentic-inquiry/deploy)
#

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
die()       { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

INQUIRY_AWS_REGION="${INQUIRY_AWS_REGION:-us-east-1}"
INQUIRY_SERVICE_NAME="${INQUIRY_SERVICE_NAME:-agentic-inquiry}"
INQUIRY_RDS_INSTANCE_ID="${INQUIRY_RDS_INSTANCE_ID:-ai-postgres}"
INQUIRY_IAM_ROLE_NAME="${INQUIRY_IAM_ROLE_NAME:-ai-app-runner-role}"
INQUIRY_ECR_REPO="${INQUIRY_ECR_REPO:-agentic-inquiry}"
INQUIRY_DEPLOY_STATE_DIR="${INQUIRY_DEPLOY_STATE_DIR:-.agentic-inquiry/deploy}"

[[ -n "${INQUIRY_AWS_ACCOUNT_ID:-}" ]] || die "INQUIRY_AWS_ACCOUNT_ID is required"

# ─── 1. Delete App Runner service ─────────────────────────────────────────────
SERVICE_ARN=$(cat "${INQUIRY_DEPLOY_STATE_DIR}/service-arn.txt" 2>/dev/null || "")
if [[ -n "${SERVICE_ARN}" ]]; then
    log_info "Deleting App Runner service '${INQUIRY_SERVICE_NAME}'..."
    aws apprunner delete-service \
        --service-arn "${SERVICE_ARN}" \
        --region "${INQUIRY_AWS_REGION}" \
        --no-cli-pager >/dev/null 2>/dev/null || log_warn "App Runner service not found, skipping"
else
    log_warn "No service ARN in state, skipping App Runner deletion"
fi

# ─── 2. Delete RDS instance ───────────────────────────────────────────────────
log_info "Deleting RDS instance '${INQUIRY_RDS_INSTANCE_ID}'..."
aws rds delete-db-instance \
    --db-instance-identifier "${INQUIRY_RDS_INSTANCE_ID}" \
    --skip-final-snapshot \
    --region "${INQUIRY_AWS_REGION}" \
    --no-cli-pager >/dev/null 2>/dev/null || log_warn "RDS instance not found, skipping"

# ─── 3. Delete SSM parameter ──────────────────────────────────────────────────
log_info "Deleting SSM parameter '/ai/api-key'..."
aws ssm delete-parameter \
    --name "/ai/api-key" \
    --region "${INQUIRY_AWS_REGION}" \
    --no-cli-pager >/dev/null 2>/dev/null || log_warn "SSM parameter not found, skipping"

# ─── 4. Detach and delete IAM role ────────────────────────────────────────────
log_info "Cleaning up IAM role '${INQUIRY_IAM_ROLE_NAME}'..."
aws iam detach-role-policy \
    --role-name "${INQUIRY_IAM_ROLE_NAME}" \
    --policy-arn "arn:aws:iam::aws:policy/AmazonSSMReadOnlyAccess" \
    --no-cli-pager >/dev/null 2>/dev/null || true
aws iam delete-role \
    --role-name "${INQUIRY_IAM_ROLE_NAME}" \
    --no-cli-pager >/dev/null 2>/dev/null || log_warn "IAM role not found, skipping"

# ─── 5. Remove deploy state markers ──────────────────────────────────────────
log_info "Removing deploy state markers..."
if [[ -d "${INQUIRY_DEPLOY_STATE_DIR}" ]]; then
    rm -f "${INQUIRY_DEPLOY_STATE_DIR}"/step-*.done \
          "${INQUIRY_DEPLOY_STATE_DIR}"/aws-state.json \
          "${INQUIRY_DEPLOY_STATE_DIR}"/service-url.txt \
          "${INQUIRY_DEPLOY_STATE_DIR}"/service-arn.txt \
          "${INQUIRY_DEPLOY_STATE_DIR}"/image-path.txt \
          "${INQUIRY_DEPLOY_STATE_DIR}"/rds-endpoint.txt
fi

log_ok "AWS undeploy complete for account '${INQUIRY_AWS_ACCOUNT_ID}'"
