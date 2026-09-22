#!/usr/bin/env bash
#
# aws-undeploy.sh — Tear down a Agent-Vault AWS deployment
#
# Required environment variables:
#   agv_AWS_ACCOUNT_ID     AWS account ID (required)
#
# Optional environment variables:
#   agv_AWS_REGION         AWS region (default: us-east-1)
#   agv_SERVICE_NAME       App Runner service name (default: agent-vault)
#   agv_RDS_INSTANCE_ID    RDS instance identifier (default: agv-postgres)
#   agv_IAM_ROLE_NAME      IAM role name (default: agv-app-runner-role)
#   agv_ECR_REPO           ECR repository name (default: agent-vault)
#   agv_DEPLOY_STATE_DIR   Dir containing state markers (default: .agv/deploy)
#

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
die()       { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

agv_AWS_REGION="${agv_AWS_REGION:-us-east-1}"
agv_SERVICE_NAME="${agv_SERVICE_NAME:-agent-vault}"
agv_RDS_INSTANCE_ID="${agv_RDS_INSTANCE_ID:-agv-postgres}"
agv_IAM_ROLE_NAME="${agv_IAM_ROLE_NAME:-agv-app-runner-role}"
agv_ECR_REPO="${agv_ECR_REPO:-agent-vault}"
agv_DEPLOY_STATE_DIR="${agv_DEPLOY_STATE_DIR:-.agv/deploy}"

[[ -n "${agv_AWS_ACCOUNT_ID:-}" ]] || die "agv_AWS_ACCOUNT_ID is required"

# ─── 1. Delete App Runner service ─────────────────────────────────────────────
SERVICE_ARN=$(cat "${agv_DEPLOY_STATE_DIR}/service-arn.txt" 2>/dev/null || "")
if [[ -n "${SERVICE_ARN}" ]]; then
    log_info "Deleting App Runner service '${agv_SERVICE_NAME}'..."
    aws apprunner delete-service \
        --service-arn "${SERVICE_ARN}" \
        --region "${agv_AWS_REGION}" \
        --no-cli-pager >/dev/null 2>/dev/null || log_warn "App Runner service not found, skipping"
else
    log_warn "No service ARN in state, skipping App Runner deletion"
fi

# ─── 2. Delete RDS instance ───────────────────────────────────────────────────
log_info "Deleting RDS instance '${agv_RDS_INSTANCE_ID}'..."
aws rds delete-db-instance \
    --db-instance-identifier "${agv_RDS_INSTANCE_ID}" \
    --skip-final-snapshot \
    --region "${agv_AWS_REGION}" \
    --no-cli-pager >/dev/null 2>/dev/null || log_warn "RDS instance not found, skipping"

# ─── 3. Delete SSM parameter ──────────────────────────────────────────────────
log_info "Deleting SSM parameter '/agv/api-key'..."
aws ssm delete-parameter \
    --name "/agv/api-key" \
    --region "${agv_AWS_REGION}" \
    --no-cli-pager >/dev/null 2>/dev/null || log_warn "SSM parameter not found, skipping"

# ─── 4. Detach and delete IAM role ────────────────────────────────────────────
log_info "Cleaning up IAM role '${agv_IAM_ROLE_NAME}'..."
aws iam detach-role-policy \
    --role-name "${agv_IAM_ROLE_NAME}" \
    --policy-arn "arn:aws:iam::aws:policy/AmazonSSMReadOnlyAccess" \
    --no-cli-pager >/dev/null 2>/dev/null || true
aws iam delete-role \
    --role-name "${agv_IAM_ROLE_NAME}" \
    --no-cli-pager >/dev/null 2>/dev/null || log_warn "IAM role not found, skipping"

# ─── 5. Remove deploy state markers ──────────────────────────────────────────
log_info "Removing deploy state markers..."
if [[ -d "${agv_DEPLOY_STATE_DIR}" ]]; then
    rm -f "${agv_DEPLOY_STATE_DIR}"/step-*.done \
          "${agv_DEPLOY_STATE_DIR}"/aws-state.json \
          "${agv_DEPLOY_STATE_DIR}"/service-url.txt \
          "${agv_DEPLOY_STATE_DIR}"/service-arn.txt \
          "${agv_DEPLOY_STATE_DIR}"/image-path.txt \
          "${agv_DEPLOY_STATE_DIR}"/rds-endpoint.txt
fi

log_ok "AWS undeploy complete for account '${agv_AWS_ACCOUNT_ID}'"
