#!/usr/bin/env bash
#
# aws-deploy.sh — Deploy Agentic Inquiry to AWS (RDS PostgreSQL + App Runner)
#
# Usage:
#   ./aws-deploy.sh
#
# Required environment variables:
#   AI_AWS_REGION         AWS region (default: us-east-1)
#   AI_AWS_ACCOUNT_ID     AWS account ID (required)
#   AI_RDS_PASSWORD       RDS postgres user password (required)
#   AI_API_KEY            Agentic Inquiry API key (pre-generated)
#
# Optional environment variables:
#   AI_RDS_INSTANCE_ID    RDS instance identifier (default: ai-postgres)
#   AI_RDS_INSTANCE_CLASS RDS instance class (default: db.t3.micro)
#   AI_ECR_REPO           ECR repository name (default: agentic-inquiry)
#   AI_SERVICE_NAME       App Runner service name (default: agentic-inquiry)
#   AI_IMAGE_TAG          Container image tag (default: latest)
#   AI_DB_NAME            Database name (default: agentic-inquiry)
#   AI_DB_USER            Database user (default: postgres)
#   AI_DEPLOY_STATE_DIR   Dir to write step completion markers (default: .agentic-inquiry/deploy)
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
AI_AWS_REGION="${AI_AWS_REGION:-us-east-1}"
AI_RDS_INSTANCE_ID="${AI_RDS_INSTANCE_ID:-ai-postgres}"
AI_RDS_INSTANCE_CLASS="${AI_RDS_INSTANCE_CLASS:-db.t3.micro}"
AI_ECR_REPO="${AI_ECR_REPO:-agentic-inquiry}"
AI_SERVICE_NAME="${AI_SERVICE_NAME:-agentic-inquiry}"
AI_IMAGE_TAG="${AI_IMAGE_TAG:-latest}"
AI_DB_NAME="${AI_DB_NAME:-agentic-inquiry}"
AI_DB_USER="${AI_DB_USER:-postgres}"
AI_DEPLOY_STATE_DIR="${AI_DEPLOY_STATE_DIR:-.agentic-inquiry/deploy}"
AI_IAM_ROLE_NAME="${AI_IAM_ROLE_NAME:-ai-app-runner-role}"

# ─── Validate required vars ────────────────────────────────────────────────────
[[ -n "${AI_AWS_ACCOUNT_ID:-}" ]] || die "AI_AWS_ACCOUNT_ID is required"
[[ -n "${AI_RDS_PASSWORD:-}" ]]   || die "AI_RDS_PASSWORD is required"
[[ -n "${AI_API_KEY:-}" ]]        || die "AI_API_KEY is required"

# ─── Step marker helpers ────────────────────────────────────────────────────────
mkdir -p "${AI_DEPLOY_STATE_DIR}"

step_done() { [[ -f "${AI_DEPLOY_STATE_DIR}/step-${1}.done" ]]; }
mark_done() { touch "${AI_DEPLOY_STATE_DIR}/step-${1}.done"; log_ok "Step ${1} complete"; }

# ─── Step 1: Check prerequisites ───────────────────────────────────────────────
if step_done "01-prereqs"; then
    log_info "Step 01-prereqs: already done, skipping"
else
    log_info "Step 01: Checking prerequisites..."
    command -v aws    >/dev/null 2>&1 || die "aws CLI not found — install AWS CLI v2"
    command -v docker >/dev/null 2>&1 || die "docker not found — install Docker"
    aws sts get-caller-identity --region "${AI_AWS_REGION}" --output text >/dev/null 2>&1 \
        || die "Not authenticated with AWS — configure credentials (aws configure or IAM role)"
    mark_done "01-prereqs"
fi

# ─── Step 2: Create RDS PostgreSQL instance ─────────────────────────────────
if step_done "02-rds"; then
    log_info "Step 02-rds: already done, skipping"
else
    log_info "Step 02: Creating RDS PostgreSQL instance '${AI_RDS_INSTANCE_ID}'..."

    if aws rds describe-db-instances \
        --db-instance-identifier "${AI_RDS_INSTANCE_ID}" \
        --region "${AI_AWS_REGION}" \
        --output text >/dev/null 2>&1; then
        log_warn "RDS instance '${AI_RDS_INSTANCE_ID}' already exists, skipping"
    else
        aws rds create-db-instance \
            --db-instance-identifier "${AI_RDS_INSTANCE_ID}" \
            --db-instance-class "${AI_RDS_INSTANCE_CLASS}" \
            --engine postgres \
            --engine-version "15" \
            --master-username "${AI_DB_USER}" \
            --master-user-password "${AI_RDS_PASSWORD}" \
            --db-name "${AI_DB_NAME}" \
            --allocated-storage 20 \
            --storage-type gp2 \
            --publicly-accessible \
            --backup-retention-period 7 \
            --region "${AI_AWS_REGION}" \
            --no-cli-pager

        log_info "  Waiting for RDS instance to become available (may take ~10 min)..."
        aws rds wait db-instance-available \
            --db-instance-identifier "${AI_RDS_INSTANCE_ID}" \
            --region "${AI_AWS_REGION}"
    fi

    # Retrieve RDS endpoint
    RDS_ENDPOINT=$(aws rds describe-db-instances \
        --db-instance-identifier "${AI_RDS_INSTANCE_ID}" \
        --region "${AI_AWS_REGION}" \
        --query "DBInstances[0].Endpoint.Address" \
        --output text)
    echo "${RDS_ENDPOINT}" > "${AI_DEPLOY_STATE_DIR}/rds-endpoint.txt"
    log_ok "RDS endpoint: ${RDS_ENDPOINT}"

    mark_done "02-rds"
fi

# ─── Step 3: Configure IAM role for App Runner ────────────────────────────────
if step_done "03-iam"; then
    log_info "Step 03-iam: already done, skipping"
else
    log_info "Step 03: Configuring IAM role '${AI_IAM_ROLE_NAME}'..."

    TRUST_POLICY='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"tasks.apprunner.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

    if aws iam get-role --role-name "${AI_IAM_ROLE_NAME}" --output text >/dev/null 2>&1; then
        log_warn "IAM role '${AI_IAM_ROLE_NAME}' already exists, skipping creation"
    else
        aws iam create-role \
            --role-name "${AI_IAM_ROLE_NAME}" \
            --assume-role-policy-document "${TRUST_POLICY}" \
            --no-cli-pager >/dev/null
        aws iam attach-role-policy \
            --role-name "${AI_IAM_ROLE_NAME}" \
            --policy-arn "arn:aws:iam::aws:policy/AmazonSSMReadOnlyAccess" \
            --no-cli-pager
    fi

    # Store API key in SSM Parameter Store
    aws ssm put-parameter \
        --name "/ai/api-key" \
        --value "${AI_API_KEY}" \
        --type SecureString \
        --overwrite \
        --region "${AI_AWS_REGION}" \
        --no-cli-pager >/dev/null
    log_ok "API key stored in SSM /ai/api-key"

    mark_done "03-iam"
fi

# ─── Step 4: Build and push container to ECR ──────────────────────────────────
if step_done "04-container"; then
    log_info "Step 04-container: already done, skipping"
else
    log_info "Step 04: Building and pushing container image to ECR..."

    # Create ECR repo if needed
    if aws ecr describe-repositories \
        --repository-names "${AI_ECR_REPO}" \
        --region "${AI_AWS_REGION}" \
        --output text >/dev/null 2>&1; then
        log_warn "ECR repo '${AI_ECR_REPO}' already exists"
    else
        aws ecr create-repository \
            --repository-name "${AI_ECR_REPO}" \
            --region "${AI_AWS_REGION}" \
            --no-cli-pager >/dev/null
    fi

    ECR_URI="${AI_AWS_ACCOUNT_ID}.dkr.ecr.${AI_AWS_REGION}.amazonaws.com/${AI_ECR_REPO}:${AI_IMAGE_TAG}"

    # Docker login to ECR
    aws ecr get-login-password --region "${AI_AWS_REGION}" \
        | docker login --username AWS --password-stdin \
          "${AI_AWS_ACCOUNT_ID}.dkr.ecr.${AI_AWS_REGION}.amazonaws.com"

    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

    docker build --tag "${ECR_URI}" "${REPO_ROOT}"
    docker push "${ECR_URI}"
    echo "${ECR_URI}" > "${AI_DEPLOY_STATE_DIR}/image-path.txt"

    mark_done "04-container"
fi

# ─── Step 5: Deploy to App Runner ─────────────────────────────────────────────
if step_done "05-app-runner"; then
    log_info "Step 05-app-runner: already done, skipping"
else
    log_info "Step 05: Deploying to App Runner..."

    ECR_URI=$(cat "${AI_DEPLOY_STATE_DIR}/image-path.txt")
    RDS_ENDPOINT=$(cat "${AI_DEPLOY_STATE_DIR}/rds-endpoint.txt" 2>/dev/null || echo "")

    ROLE_ARN="arn:aws:iam::${AI_AWS_ACCOUNT_ID}:role/${AI_IAM_ROLE_NAME}"

    SERVICE_ARN=$(aws apprunner create-service \
        --service-name "${AI_SERVICE_NAME}" \
        --source-configuration "{
            \"ImageRepository\": {
                \"ImageIdentifier\": \"${ECR_URI}\",
                \"ImageRepositoryType\": \"ECR\",
                \"ImageConfiguration\": {
                    \"Port\": \"8000\",
                    \"RuntimeEnvironmentVariables\": {
                        \"AI_ENV\": \"${AI_SERVICE_NAME}\",
                        \"AI_STORAGE_BACKEND\": \"postgresql\",
                        \"AI_DB_HOST\": \"${RDS_ENDPOINT}\",
                        \"AI_DB_NAME\": \"${AI_DB_NAME}\",
                        \"AI_DB_USER\": \"${AI_DB_USER}\"
                    }
                }
            },
            \"AuthenticationConfiguration\": {
                \"AccessRoleArn\": \"${ROLE_ARN}\"
            }
        }" \
        --instance-configuration "Cpu=1 vCPU,Memory=2 GB" \
        --region "${AI_AWS_REGION}" \
        --query "Service.ServiceArn" \
        --output text \
        --no-cli-pager 2>/dev/null || \
        aws apprunner list-services \
            --region "${AI_AWS_REGION}" \
            --query "ServiceSummaryList[?ServiceName=='${AI_SERVICE_NAME}'].ServiceArn" \
            --output text \
            --no-cli-pager)

    echo "${SERVICE_ARN}" > "${AI_DEPLOY_STATE_DIR}/service-arn.txt"

    # Wait for service to be running
    log_info "  Waiting for App Runner service to reach RUNNING state..."
    aws apprunner wait service-running \
        --service-arn "${SERVICE_ARN}" \
        --region "${AI_AWS_REGION}" \
        --no-cli-pager 2>/dev/null || true

    # Get service URL
    SERVICE_URL=$(aws apprunner describe-service \
        --service-arn "${SERVICE_ARN}" \
        --region "${AI_AWS_REGION}" \
        --query "Service.ServiceUrl" \
        --output text \
        --no-cli-pager)
    echo "https://${SERVICE_URL}" > "${AI_DEPLOY_STATE_DIR}/service-url.txt"
    log_ok "App Runner service URL: https://${SERVICE_URL}"

    mark_done "05-app-runner"
fi

# ─── Step 6: Smoke test ────────────────────────────────────────────────────────
if step_done "06-smoke-test"; then
    log_info "Step 06-smoke-test: already done, skipping"
else
    log_info "Step 06: Running smoke test..."
    SERVICE_URL=$(cat "${AI_DEPLOY_STATE_DIR}/service-url.txt" 2>/dev/null || "")
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

SERVICE_URL=$(cat "${AI_DEPLOY_STATE_DIR}/service-url.txt" 2>/dev/null || "unknown")
log_ok "======================================================"
log_ok "Agentic Inquiry deployed successfully to AWS!"
log_ok "  Account:  ${AI_AWS_ACCOUNT_ID}"
log_ok "  Region:   ${AI_AWS_REGION}"
log_ok "  Service:  ${AI_SERVICE_NAME}"
log_ok "  URL:      ${SERVICE_URL}"
log_ok "======================================================"
