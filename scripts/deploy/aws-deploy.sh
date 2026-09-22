#!/usr/bin/env bash
#
# aws-deploy.sh — Deploy Agent-Vault to AWS (RDS PostgreSQL + App Runner)
#
# Usage:
#   ./aws-deploy.sh
#
# Required environment variables:
#   agv_AWS_REGION         AWS region (default: us-east-1)
#   agv_AWS_ACCOUNT_ID     AWS account ID (required)
#   agv_RDS_PASSWORD       RDS postgres user password (required)
#   agv_API_KEY            Agent-Vault API key (pre-generated)
#
# Optional environment variables:
#   agv_RDS_INSTANCE_ID    RDS instance identifier (default: agv-postgres)
#   agv_RDS_INSTANCE_CLASS RDS instance class (default: db.t3.micro)
#   agv_ECR_REPO           ECR repository name (default: agent-vault)
#   agv_SERVICE_NAME       App Runner service name (default: agent-vault)
#   agv_IMAGE_TAG          Container image tag (default: latest)
#   agv_DB_NAME            Database name (default: agent-vault)
#   agv_DB_USER            Database user (default: postgres)
#   agv_DEPLOY_STATE_DIR   Dir to write step completion markers (default: .agv/deploy)
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

# ─── Defaults ──────────────────────────────────────────────────────────────────
agv_AWS_REGION="${agv_AWS_REGION:-us-east-1}"
agv_RDS_INSTANCE_ID="${agv_RDS_INSTANCE_ID:-agv-postgres}"
agv_RDS_INSTANCE_CLASS="${agv_RDS_INSTANCE_CLASS:-db.t3.micro}"
agv_ECR_REPO="${agv_ECR_REPO:-agent-vault}"
agv_SERVICE_NAME="${agv_SERVICE_NAME:-agent-vault}"
agv_IMAGE_TAG="${agv_IMAGE_TAG:-latest}"
agv_DB_NAME="${agv_DB_NAME:-agent-vault}"
agv_DB_USER="${agv_DB_USER:-postgres}"
agv_DEPLOY_STATE_DIR="${agv_DEPLOY_STATE_DIR:-.agv/deploy}"
agv_IAM_ROLE_NAME="${agv_IAM_ROLE_NAME:-agv-app-runner-role}"

# ─── Validate required vars ────────────────────────────────────────────────────
[[ -n "${agv_AWS_ACCOUNT_ID:-}" ]] || die "agv_AWS_ACCOUNT_ID is required"
[[ -n "${agv_RDS_PASSWORD:-}" ]]   || die "agv_RDS_PASSWORD is required"
[[ -n "${agv_API_KEY:-}" ]]        || die "agv_API_KEY is required"

# ─── Step marker helpers ────────────────────────────────────────────────────────
mkdir -p "${agv_DEPLOY_STATE_DIR}"

step_done() { [[ -f "${agv_DEPLOY_STATE_DIR}/step-${1}.done" ]]; }
mark_done() { touch "${agv_DEPLOY_STATE_DIR}/step-${1}.done"; log_ok "Step ${1} complete"; }

# ─── Step 1: Check prerequisites ───────────────────────────────────────────────
if step_done "01-prereqs"; then
    log_info "Step 01-prereqs: already done, skipping"
else
    log_info "Step 01: Checking prerequisites..."
    command -v aws    >/dev/null 2>&1 || die "aws CLI not found — install AWS CLI v2"
    command -v docker >/dev/null 2>&1 || die "docker not found — install Docker"
    aws sts get-caller-identity --region "${agv_AWS_REGION}" --output text >/dev/null 2>&1 \
        || die "Not authenticated with AWS — configure credentials (aws configure or IAM role)"
    mark_done "01-prereqs"
fi

# ─── Step 2: Create RDS PostgreSQL instance ─────────────────────────────────
if step_done "02-rds"; then
    log_info "Step 02-rds: already done, skipping"
else
    log_info "Step 02: Creating RDS PostgreSQL instance '${agv_RDS_INSTANCE_ID}'..."

    if aws rds describe-db-instances \
        --db-instance-identifier "${agv_RDS_INSTANCE_ID}" \
        --region "${agv_AWS_REGION}" \
        --output text >/dev/null 2>&1; then
        log_warn "RDS instance '${agv_RDS_INSTANCE_ID}' already exists, skipping"
    else
        aws rds create-db-instance \
            --db-instance-identifier "${agv_RDS_INSTANCE_ID}" \
            --db-instance-class "${agv_RDS_INSTANCE_CLASS}" \
            --engine postgres \
            --engine-version "15" \
            --master-username "${agv_DB_USER}" \
            --master-user-password "${agv_RDS_PASSWORD}" \
            --db-name "${agv_DB_NAME}" \
            --allocated-storage 20 \
            --storage-type gp2 \
            --publicly-accessible \
            --backup-retention-period 7 \
            --region "${agv_AWS_REGION}" \
            --no-cli-pager

        log_info "  Waiting for RDS instance to become available (may take ~10 min)..."
        aws rds wait db-instance-available \
            --db-instance-identifier "${agv_RDS_INSTANCE_ID}" \
            --region "${agv_AWS_REGION}"
    fi

    # Retrieve RDS endpoint
    RDS_ENDPOINT=$(aws rds describe-db-instances \
        --db-instance-identifier "${agv_RDS_INSTANCE_ID}" \
        --region "${agv_AWS_REGION}" \
        --query "DBInstances[0].Endpoint.Address" \
        --output text)
    echo "${RDS_ENDPOINT}" > "${agv_DEPLOY_STATE_DIR}/rds-endpoint.txt"
    log_ok "RDS endpoint: ${RDS_ENDPOINT}"

    mark_done "02-rds"
fi

# ─── Step 3: Configure IAM role for App Runner ────────────────────────────────
if step_done "03-iam"; then
    log_info "Step 03-iam: already done, skipping"
else
    log_info "Step 03: Configuring IAM role '${agv_IAM_ROLE_NAME}'..."

    TRUST_POLICY='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"tasks.apprunner.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

    if aws iam get-role --role-name "${agv_IAM_ROLE_NAME}" --output text >/dev/null 2>&1; then
        log_warn "IAM role '${agv_IAM_ROLE_NAME}' already exists, skipping creation"
    else
        aws iam create-role \
            --role-name "${agv_IAM_ROLE_NAME}" \
            --assume-role-policy-document "${TRUST_POLICY}" \
            --no-cli-pager >/dev/null
        aws iam attach-role-policy \
            --role-name "${agv_IAM_ROLE_NAME}" \
            --policy-arn "arn:aws:iam::aws:policy/AmazonSSMReadOnlyAccess" \
            --no-cli-pager
    fi

    # Store API key in SSM Parameter Store
    aws ssm put-parameter \
        --name "/agv/api-key" \
        --value "${agv_API_KEY}" \
        --type SecureString \
        --overwrite \
        --region "${agv_AWS_REGION}" \
        --no-cli-pager >/dev/null
    log_ok "API key stored in SSM /agv/api-key"

    mark_done "03-iam"
fi

# ─── Step 4: Build and push container to ECR ──────────────────────────────────
if step_done "04-container"; then
    log_info "Step 04-container: already done, skipping"
else
    log_info "Step 04: Building and pushing container image to ECR..."

    # Create ECR repo if needed
    if aws ecr describe-repositories \
        --repository-names "${agv_ECR_REPO}" \
        --region "${agv_AWS_REGION}" \
        --output text >/dev/null 2>&1; then
        log_warn "ECR repo '${agv_ECR_REPO}' already exists"
    else
        aws ecr create-repository \
            --repository-name "${agv_ECR_REPO}" \
            --region "${agv_AWS_REGION}" \
            --no-cli-pager >/dev/null
    fi

    ECR_URI="${agv_AWS_ACCOUNT_ID}.dkr.ecr.${agv_AWS_REGION}.amazonaws.com/${agv_ECR_REPO}:${agv_IMAGE_TAG}"

    # Docker login to ECR
    aws ecr get-login-password --region "${agv_AWS_REGION}" \
        | docker login --username AWS --password-stdin \
          "${agv_AWS_ACCOUNT_ID}.dkr.ecr.${agv_AWS_REGION}.amazonaws.com"

    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

    docker build --tag "${ECR_URI}" "${REPO_ROOT}"
    docker push "${ECR_URI}"
    echo "${ECR_URI}" > "${agv_DEPLOY_STATE_DIR}/image-path.txt"

    mark_done "04-container"
fi

# ─── Step 5: Deploy to App Runner ─────────────────────────────────────────────
if step_done "05-app-runner"; then
    log_info "Step 05-app-runner: already done, skipping"
else
    log_info "Step 05: Deploying to App Runner..."

    ECR_URI=$(cat "${agv_DEPLOY_STATE_DIR}/image-path.txt")
    RDS_ENDPOINT=$(cat "${agv_DEPLOY_STATE_DIR}/rds-endpoint.txt" 2>/dev/null || echo "")

    ROLE_ARN="arn:aws:iam::${agv_AWS_ACCOUNT_ID}:role/${agv_IAM_ROLE_NAME}"

    SERVICE_ARN=$(aws apprunner create-service \
        --service-name "${agv_SERVICE_NAME}" \
        --source-configuration "{
            \"ImageRepository\": {
                \"ImageIdentifier\": \"${ECR_URI}\",
                \"ImageRepositoryType\": \"ECR\",
                \"ImageConfiguration\": {
                    \"Port\": \"8000\",
                    \"RuntimeEnvironmentVariables\": {
                        \"agv_ENV\": \"${agv_SERVICE_NAME}\",
                        \"agv_STORAGE_BACKEND\": \"postgresql\",
                        \"agv_DB_HOST\": \"${RDS_ENDPOINT}\",
                        \"agv_DB_NAME\": \"${agv_DB_NAME}\",
                        \"agv_DB_USER\": \"${agv_DB_USER}\"
                    }
                }
            },
            \"AuthenticationConfiguration\": {
                \"AccessRoleArn\": \"${ROLE_ARN}\"
            }
        }" \
        --instance-configuration "Cpu=1 vCPU,Memory=2 GB" \
        --region "${agv_AWS_REGION}" \
        --query "Service.ServiceArn" \
        --output text \
        --no-cli-pager 2>/dev/null || \
        aws apprunner list-services \
            --region "${agv_AWS_REGION}" \
            --query "ServiceSummaryList[?ServiceName=='${agv_SERVICE_NAME}'].ServiceArn" \
            --output text \
            --no-cli-pager)

    echo "${SERVICE_ARN}" > "${agv_DEPLOY_STATE_DIR}/service-arn.txt"

    # Wait for service to be running
    log_info "  Waiting for App Runner service to reach RUNNING state..."
    aws apprunner wait service-running \
        --service-arn "${SERVICE_ARN}" \
        --region "${agv_AWS_REGION}" \
        --no-cli-pager 2>/dev/null || true

    # Get service URL
    SERVICE_URL=$(aws apprunner describe-service \
        --service-arn "${SERVICE_ARN}" \
        --region "${agv_AWS_REGION}" \
        --query "Service.ServiceUrl" \
        --output text \
        --no-cli-pager)
    echo "https://${SERVICE_URL}" > "${agv_DEPLOY_STATE_DIR}/service-url.txt"
    log_ok "App Runner service URL: https://${SERVICE_URL}"

    mark_done "05-app-runner"
fi

# ─── Step 6: Smoke test ────────────────────────────────────────────────────────
if step_done "06-smoke-test"; then
    log_info "Step 06-smoke-test: already done, skipping"
else
    log_info "Step 06: Running smoke test..."
    SERVICE_URL=$(cat "${agv_DEPLOY_STATE_DIR}/service-url.txt" 2>/dev/null || "")
    [[ -n "${SERVICE_URL}" ]] || die "Service URL not found — did step 05 complete?"

    HEALTH_URL="${SERVICE_URL}/api/v1/health"
    MAX_ATTEMPTS=30
    SLEEP_SECONDS=10

    for i in $(seq 1 "${MAX_ATTEMPTS}"); do
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "${HEALTH_URL}" 2>/dev/null || echo "000")
        if [[ "${HTTP_CODE}" == "200" ]]; then
            log_ok "Health check passed (attempt ${i})"
            mark_done "06-smoke-test"
            break
        fi
        [[ "${i}" -lt "${MAX_ATTEMPTS}" ]] && { log_info "  Attempt ${i}/${MAX_ATTEMPTS}: HTTP ${HTTP_CODE}..."; sleep "${SLEEP_SECONDS}"; } \
            || die "Smoke test failed after ${MAX_ATTEMPTS} attempts"
    done
fi

SERVICE_URL=$(cat "${agv_DEPLOY_STATE_DIR}/service-url.txt" 2>/dev/null || "unknown")
log_ok "======================================================"
log_ok "Agent-Vault deployed successfully to AWS!"
log_ok "  Account:  ${agv_AWS_ACCOUNT_ID}"
log_ok "  Region:   ${agv_AWS_REGION}"
log_ok "  Service:  ${agv_SERVICE_NAME}"
log_ok "  URL:      ${SERVICE_URL}"
log_ok "======================================================"
