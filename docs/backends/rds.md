---
name: AWS RDS / Aurora PostgreSQL
description: AWS-managed PostgreSQL with optional Bedrock-backed embeddings
type: rds
requires_setup: true
config_file: config/rds.yaml

setup:
  duration_minutes: 15
  steps:
    - description: Create RDS or Aurora instance with PostgreSQL engine
      command: |
        aws rds create-db-instance \
          --db-instance-identifier agent-vault \
          --engine postgres --engine-version 16 \
          --db-instance-class db.t3.medium \
          --allocated-storage 20 \
          --master-username agv_admin \
          --master-user-password "${DB_PASSWORD}"
      wait_for_completion: true
    - description: (Aurora only) Attach the `aws_ml` permission policy to the cluster IAM role
      command: aws iam attach-role-policy --role-name <cluster-role> --policy-arn arn:aws:iam::aws:policy/AmazonBedrockReadOnly
    - description: Create the application database (the agent-vault DB doesn't exist on a fresh instance — connect to the default `postgres` DB to create it)
      command: psql -h <endpoint> -U agv_admin -d postgres -c "CREATE DATABASE agent-vault;"
    - description: Enable required PostgreSQL extensions inside the new database
      command: psql -h <endpoint> -U agv_admin -d agent-vault -c "CREATE EXTENSION IF NOT EXISTS vector;"

teardown:
  steps:
    - description: Delete RDS instance
      command: aws rds delete-db-instance --db-instance-identifier agent-vault --skip-final-snapshot
---

# AWS RDS / Aurora PostgreSQL Backend

Agent-Vault supports AWS-managed PostgreSQL — both **RDS for PostgreSQL** and
**Aurora PostgreSQL** — through the unified PostgreSQL provider. The
`backend_type: rds` configuration covers both engines today; [RFC 0002](../rfc/0002-aws-support.md)
proposes splitting into two backend types (`rds` for the local-embedding
path, `aurora` for the in-DB Bedrock path) since the two engines have
materially different capabilities. **Read RFC 0002 before standing up
the server-side embedding path** — the current adapter declares
`aws_ml` as required, which is Aurora-only.

## When to use

- **AWS-native deployments** — IAM, VPC, KMS, CloudWatch all integrate
- **Existing AWS spend / commitments** — leverage Reserved Instances or Savings Plans
- **Compliance / data residency** — HIPAA, PCI-DSS, FedRAMP boundaries
- **Multi-region or cross-account** — Aurora Global Database, RDS read replicas

## Embedding strategies

Three deployment shapes, in increasing AWS dependency:

| Shape | Engine | Embedder | Where embeddings run |
|---|---|---|---|
| **A. RDS + local SentenceTransformer** | RDS for PostgreSQL | `default_provider: sentence_transformer` | Indexer process (CPU/GPU) |
| **B. RDS + client-side Bedrock** | RDS for PostgreSQL | `default_provider: bedrock` ([RFC 0003](../rfc/0003-pluggable-embedding-providers.md)) | Indexer calls `bedrock-runtime.invoke_model` |
| **C. Aurora + server-side Bedrock** | Aurora PostgreSQL | server-side via `aws_ml` | Inside the database via `aws_bedrock.invoke_model` |

Shape A is the simplest and works on any RDS instance that supports
`pgvector` (PostgreSQL 15.2+). Shape B adds Titan v2 quality without
needing the `aws_ml` extension — the embedder runs in the indexer's
Python process and writes 1024-dim vectors to pgvector. Shape C
requires Aurora; the SQL adapter's `agv_embed(...)` helper wraps
`aws_bedrock.invoke_model` and runs at indexing time inside the
database engine.

## Quick start (Shape A — RDS + SentenceTransformer)

### Prerequisites

- AWS account with RDS API access
- PostgreSQL 15.2+ (so `pgvector` is available as a managed extension)
- Network path from the indexer host to the RDS endpoint (VPC peering,
  bastion, or public access — operators decide)

### Create the instance

```bash
aws rds create-db-instance \
  --db-instance-identifier agent-vault \
  --engine postgres \
  --engine-version 16.2 \
  --db-instance-class db.t3.medium \
  --allocated-storage 20 \
  --master-username agv_admin \
  --master-user-password "${DB_PASSWORD}" \
  --vpc-security-group-ids sg-xxxxxxxx \
  --db-subnet-group-name default \
  --publicly-accessible

# Wait for the instance to come online (~10 minutes)
aws rds wait db-instance-available --db-instance-identifier agent-vault
```

### Create the application database + enable pgvector

`agent-vault` doesn't exist on a fresh RDS instance — you have to
create it first, then connect into it before enabling extensions.
`CREATE EXTENSION` is per-database; running it against the default
`postgres` DB doesn't help when the indexer connects to `agent-vault`.

```sql
-- Connect to the default `postgres` database via psql first.
-- (psql -h <endpoint> -U agv_admin -d postgres)

-- 1. Create the application database
CREATE DATABASE agent-vault;

-- 2. Reconnect into the new database. In psql:
\c agent-vault

-- 3. Enable the extension *inside* agent-vault, not the default DB.
CREATE EXTENSION IF NOT EXISTS vector;
```

### Configure Agent-Vault

```yaml
# config/rds.yaml
storage:
  backends:
    rds:
      type: rds
      region: us-east-1
      instance: agent-vault
      host: agent-vault.xxxxxxxxxx.us-east-1.rds.amazonaws.com
      database: agent-vault
      user: agv_admin
      password: ${agv_DB_PASSWORD}
      pool_size: 10
      max_overflow: 5

  vector_backend: rds
  graph_backend: rds
  events_backend: rds

embeddings:
  default_provider: sentence_transformer
  default_dimensions: 384
```

### Run

```bash
export agv_DB_PASSWORD=your_app_password
uv run agv --config config/rds.yaml index .
```

## Quick start (Shape B — RDS + client-side Bedrock)

This shape pairs the RDS backend with the `BedrockEmbedder` from
[RFC 0003](../rfc/0003-pluggable-embedding-providers.md). Same RDS
instance setup as Shape A; the difference is purely in the
`embeddings:` block of the config and an extra optional dependency.

### Install the AWS extra

```bash
pip install 'agent-vault[aws]'  # adds boto3
```

### Configure

```yaml
# config/rds.yaml — embeddings section
embeddings:
  default_provider: bedrock
  default_dimensions: 1024
  bedrock:
    model_id: amazon.titan-embed-text-v2:0
    region: us-east-1               # required when provider == bedrock
    output_dim: 1024                 # 256 | 512 | 1024 for Titan v2
    normalize: true
    request_concurrency: 16          # raise for parallel InvokeModel calls
```

AWS credentials use the standard boto3 chain (env vars, profile,
instance role). The Bedrock IAM policy on the indexer host needs
`bedrock:InvokeModel` on the Titan v2 model ARN. **`AWS_REGION` is
not honoured for the Bedrock embedder** — region must come from
`embeddings.bedrock.region` or `AGV_EMBEDDINGS_BEDROCK_REGION`.

### Re-index after switching to Bedrock

A 384-dim MiniLM corpus is not compatible with a 1024-dim Titan
corpus. The pgvector column type rejects mis-sized vectors at insert.
After switching providers, drop the existing tables and re-index.

## Quick start (Shape C — Aurora + server-side Bedrock)

⚠️ **`aws_ml` is Aurora-only — it is not in the supported-extensions
list for RDS for PostgreSQL.** Setting `embedding_strategy: server_side`
against a non-Aurora RDS instance fails at `CREATE EXTENSION` time.

The adapter only requests `aws_ml` when `embedding_strategy: server_side`
is configured, so Shapes A and B above run cleanly on plain RDS for
PostgreSQL — only Shape C requires Aurora. [RFC 0002](../rfc/0002-aws-support.md)
tracks the planned backend-type split (`rds` vs `aurora`) so this shape
gets a name that matches what it actually supports. Until that RFC's
implementation lands:

- Use Aurora PostgreSQL (engine `aurora-postgresql`, version 15.13+
  or any 16.x) — these are the versions that ship `aws_ml` 2.0+.
- Set the cluster IAM role with `bedrock:InvokeModel` permission on
  the Titan model ARN.
- Set `embedding_strategy: server_side` and the Titan dim (1024) in
  the backend config.
- The provider's `initialize()` runs `CREATE EXTENSION aws_ml` and
  installs the `agv_embed(...)` SQL helper.

```yaml
storage:
  backends:
    rds:
      type: rds                    # RFC 0002 will rename to "aurora"
      region: us-east-1
      instance: agent-vault-aurora
      host: agent-vault-aurora.cluster-xxxxxxxxxx.us-east-1.rds.amazonaws.com
      database: agent-vault
      user: agv_admin
      password: ${agv_DB_PASSWORD}
      embedding_strategy: server_side
      embedding_model: amazon.titan-embed-text-v2:0
      embedding_dim: 1024
```

## Authentication

Two options:

- **Password auth** (shown above) — simple, works everywhere
- **IAM database auth** — recommended for production. Agent-Vault's
  `BackendPoolManager._build_rds_dsn` (`storage/pool.py`) generates
  IAM auth tokens via `boto3.client("rds").generate_db_auth_token()`
  when `password` is omitted from config. Tokens have a 15-minute
  lifetime; the connection manager regenerates them per new connection.

For IAM auth, omit `password` from config and grant the indexer's
IAM principal `rds-db:connect` on the database user ARN.

## Pgvector index tuning

RDS for PostgreSQL ships pgvector 0.5+ (instance versions vary —
check the AWS docs for your engine version). HNSW indexes are the
default for agent-vault's vector columns. Tune `m` and
`ef_construction` for your corpus size — the defaults
(`m=16, ef_construction=64`) work well up to ~1M chunks.

## Bedrock quotas (for shapes B and C)

Titan Text Embeddings v2 default quotas in `us-east-1`:

- **2,000 RPM** (requests per minute)
- **1,000,000 TPM** (tokens per minute)

For shape B (`request_concurrency: N`), sustained indexing throughput
is bounded by RPM × 60. With a 100k-chunk corpus and `request_concurrency: 16`
you'll hit the RPM ceiling on the first burst — `RemoteEmbedder`
retries `ThrottlingException` with exponential backoff, so the
indexing run will eventually drain. To go faster, request a quota
increase via the AWS Service Quotas console or use shape C (Aurora
server-side, where in-DB calls are accounted differently).

## Cost considerations

| Shape | DB cost | Embedding cost | Notes |
|---|---|---|---|
| A | RDS instance only | Zero (CPU/GPU local) | Cheapest if you have indexer compute |
| B | RDS instance + boto3 traffic | Bedrock InvokeModel × N chunks | ~$0.0001 per 1k tokens for Titan v2 |
| C | Aurora cluster (~+30%) | Same Bedrock cost | DB does the boto3 calls; pay for DB CPU |

## Troubleshooting

### `ERROR: extension "aws_ml" is not available`

`aws_ml` is **Aurora-only**. If you're on RDS for PostgreSQL, you
cannot use `embedding_strategy: server_side`. Either move to Aurora
(shape C) or stay client-side with shape A or B.

### IAM token errors (`PAM authentication failed`)

The IAM token has a 15-minute lifetime. If the connection pool's
`max_inactive_connection_lifetime` is longer than 15 minutes, idle
connections will fail re-authentication. Set
`max_inactive_connection_lifetime: 600` (10 min) for IAM-auth pools.

### Bedrock `AccessDeniedException`

The indexer's IAM principal needs `bedrock:InvokeModel` on the model
ARN. The model ARN format is
`arn:aws:bedrock:<region>::foundation-model/amazon.titan-embed-text-v2:0`.
A successful `bedrock:ListFoundationModels` does not imply
`InvokeModel` access.

### Connection pool exhaustion

Same symptoms and fix as CloudSQL — see the [CloudSQL doc](./cloudsql.md#connection-pool-exhaustion).
RDS doesn't impose a hard 25-connection limit like CloudSQL but
`db.t3.micro` / `db.t3.small` instances should still use modest
pool sizing (`pool_size: 5–10`).

## Related documentation

- [RFC 0002 — AWS support](../rfc/0002-aws-support.md) — tracks the
  rds-vs-aurora backend split
- [RFC 0003 — Pluggable embedding providers](../rfc/0003-pluggable-embedding-providers.md) —
  RemoteEmbedder + BedrockEmbedder reference
- [PostgreSQL backend](./postgresql.md) — provider-level details
  shared with all PostgreSQL-compatible backends
- [Embeddings architecture](../architecture/embeddings.md) — how the
  embedder gets selected for any LOCAL-strategy backend
