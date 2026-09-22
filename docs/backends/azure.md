---
name: Azure Database for PostgreSQL Flexible Server
description: Azure-managed PostgreSQL with the azure_ai extension for server-side embeddings via Azure OpenAI
type: azure
requires_setup: true
config_file: config/azure.yaml

setup:
  duration_minutes: 15
  steps:
    - description: Create Azure Database for PostgreSQL Flexible Server
      command: |
        az postgres flexible-server create \
          --resource-group agent-vault-rg \
          --name agent-vault-pg \
          --location eastus \
          --tier Burstable --sku-name Standard_B1ms \
          --version 16 \
          --storage-size 32 \
          --admin-user agv_admin \
          --admin-password "${DB_PASSWORD}"
      wait_for_completion: true
    - description: Allowlist `azure_ai`, `vector` in server parameters
      command: |
        az postgres flexible-server parameter set \
          --resource-group agent-vault-rg \
          --server-name agent-vault-pg \
          --name azure.extensions \
          --value AZURE_AI,VECTOR
    - description: Create the application database (agent-vault doesn't exist on a fresh server)
      command: |
        az postgres flexible-server db create \
          --resource-group agent-vault-rg \
          --server-name agent-vault-pg \
          --database-name agent-vault
    - description: Enable extensions inside the new database (CREATE EXTENSION is per-database, not server-wide)
      command: psql -h <endpoint> -U agv_admin -d agent-vault -c "CREATE EXTENSION IF NOT EXISTS azure_ai; CREATE EXTENSION IF NOT EXISTS vector;"

teardown:
  steps:
    - description: Delete server
      command: az postgres flexible-server delete --resource-group agent-vault-rg --name agent-vault-pg --yes
---

# Azure Database for PostgreSQL Backend

Agent-Vault supports **Azure Database for PostgreSQL Flexible Server**
through the unified PostgreSQL provider. The defining feature for
this backend is the `azure_ai` extension, which lets the database
call out to Azure OpenAI embedding deployments from inside SQL —
the same shape as AlloyDB's server-side `embedding()` and Aurora's
`aws_bedrock.invoke_model_get_embeddings`.

## When to use

- **Azure-native deployments** — Entra ID, Private Link, Defender for Cloud
- **Existing Azure spend** — Microsoft Enterprise Agreements,
  reserved capacity
- **Compliance / data residency** — sovereign Azure regions, FedRAMP,
  ISO/IEC 27001
- **Want server-side embeddings without leaving Azure** — Azure OpenAI
  deployments are accessed via the database's managed identity, no
  client-side AOAI keys

## Embedding strategy

Azure auto-configures to **server-side** when the backend is
selected. The SQL adapter
(`storage/providers/postgresql/adapter.py::AzurePostgresAdapter`)
emits:

```sql
azure_ai.generate_embeddings('<deployment-name>', <content_text>)::vector
```

The deployment-name maps 1:1 to your Azure OpenAI deployment
(typically `text-embedding-3-small` or `text-embedding-3-large`).
Dimensions are determined by the deployed model:

| Model | Dim | Notes |
|---|---|---|
| `text-embedding-3-small` | 1536 | Cheaper; default for most agent-vault deployments |
| `text-embedding-3-large` | 3072 | Higher recall; pgvector HNSW build is ~2× slower |
| `text-embedding-ada-002` | 1536 | Legacy; new deployments should pick a `-3-` variant |

## Quick start

### Prerequisites

- Azure subscription with Cognitive Services + Database for PostgreSQL
  resource providers registered
- Azure CLI authenticated (`az login`)
- An Azure OpenAI resource with at least one embedding deployment
  (`text-embedding-3-small` is the typical default)

### Create the server

```bash
RG=agent-vault-rg
SERVER=agent-vault-pg

az group create --name "$RG" --location eastus

az postgres flexible-server create \
  --resource-group "$RG" \
  --name "$SERVER" \
  --location eastus \
  --tier Burstable --sku-name Standard_B1ms \
  --version 16 \
  --storage-size 32 \
  --admin-user agv_admin \
  --admin-password "${DB_PASSWORD}" \
  --public-access 0.0.0.0
```

### Wire azure_ai to your Azure OpenAI deployment

```bash
# Get the AOAI endpoint + a managed-identity-friendly key
AOAI_RESOURCE=agent-vault-aoai
AOAI_ENDPOINT=$(az cognitiveservices account show -g $RG -n $AOAI_RESOURCE --query properties.endpoint -o tsv)
AOAI_KEY=$(az cognitiveservices account keys list -g $RG -n $AOAI_RESOURCE --query key1 -o tsv)
```

Create the application database before wiring extensions —
`agent-vault` doesn't exist on a fresh Flexible Server, and
`CREATE EXTENSION` is per-database (running it against the default
DB doesn't help when the indexer connects to `agent-vault`).

```bash
az postgres flexible-server db create \
  --resource-group "$RG" \
  --server-name "$SERVER" \
  --database-name agent-vault
```

Then connect with `psql -h <endpoint> -U agv_admin -d agent-vault`:

```sql
-- Enable extensions inside the agent-vault database
CREATE EXTENSION IF NOT EXISTS azure_ai;
CREATE EXTENSION IF NOT EXISTS vector;

-- Wire to your Azure OpenAI resource
SELECT azure_ai.set_setting('azure_openai.endpoint', '<AOAI_ENDPOINT>');
SELECT azure_ai.set_setting('azure_openai.subscription_key', '<AOAI_KEY>');
```

### Configure Agent-Vault

```yaml
# config/azure.yaml — matches the shape produced by `agv env init azure`
storage:
  backends:
    azure_db:                                  # backend key (arbitrary; the
                                               # wizard uses "azure_db"; the
                                               # capability dispatch routes
                                               # on the `type:` field below)
      type: azure
      host: agent-vault-pg.postgres.database.azure.com
      database: agent-vault
      user: agv_admin
      password: ${agv_DB_PASSWORD}
      pool_size: 10
      max_overflow: 5

      # Embedding strategy is auto-set to server_side for type: azure;
      # set explicitly only if overriding the deployment name:
      embedding_strategy: server_side
      embedding_model: text-embedding-3-small  # Azure deployment name
      embedding_dim: 1536

  vector_backend: azure_db
  graph_backend: azure_db
  events_backend: azure_db

embeddings:
  default_provider: none           # server-side; no client-side embedder
  default_dimensions: 1536
```

### Run

```bash
export agv_DB_PASSWORD=your_app_password
uv run agv --config config/azure.yaml index .
```

## Authentication

### Microsoft Entra ID + managed identity (recommended for production)

Azure Database for PostgreSQL Flexible Server supports Microsoft
Entra ID authentication. Two steps:

1. **Add the managed identity as a Microsoft Entra admin on the
   server** (Azure portal: *Authentication* → *Add Microsoft Entra
   admin*, or CLI):

   ```bash
   az postgres flexible-server ad-admin create \
     --resource-group agent-vault-rg \
     --server-name agent-vault-pg \
     --display-name <managed-identity-name> \
     --object-id <managed-identity-object-id>
   ```

2. **Grant per-database privileges** inside `psql`:

   ```sql
   -- Connect as a Microsoft Entra admin first
   GRANT CONNECT ON DATABASE agent-vault TO "<managed-identity-name>";
   GRANT CREATE, USAGE ON SCHEMA public TO "<managed-identity-name>";
   ```

Then omit `password` from config — the connection manager generates
an Entra access token via ``DefaultAzureCredential`` and uses it as
the password.

For client-side authentication only:

```bash
# Make the AOAI key available via az cli
az postgres flexible-server execute \
  -n agent-vault-pg \
  -d agent-vault \
  --querytext "SELECT azure_ai.set_setting('azure_openai.subscription_key', '${AOAI_KEY}');"
```

### Password auth

Simple, works everywhere. Same shape as the YAML example above.

## `azure_ai` extension caveats

- The extension must be in the server's `azure.extensions` allowlist
  before `CREATE EXTENSION azure_ai` will succeed at the database
  level. The Azure CLI snippet above sets this.
- `azure_ai.set_setting('azure_openai.subscription_key', ...)` stores
  the key as a server-level setting. Treat it like a database
  password — anyone with `pg_settings` read access can see it.
  Use Microsoft Entra ID + managed identity in production.
- `azure_ai.generate_embeddings(model, content)` returns a `real[]`
  array; the unified provider casts it to `vector` for pgvector
  compatibility (see `AzurePostgresAdapter.get_embedding_sql` in
  `storage/providers/postgresql/adapter.py`).

## Pgvector index tuning

Azure Database for PostgreSQL ships pgvector 0.7+ on PostgreSQL 16.
Both `ivfflat` and `hnsw` index types are supported; the unified
provider builds HNSW by default. Tune `m` and `ef_construction`
identically to other PostgreSQL backends.

## Cost considerations

Two cost dimensions:

- **Database** — Burstable B1ms is fine for indexes up to ~1M
  chunks; General Purpose D2s_v3 for larger corpora
- **Azure OpenAI embedding calls** — billed per token. The
  database makes one call per `INSERT` of a row with a NULL
  embedding column; bulk-indexing 100k chunks at
  `text-embedding-3-small` ($0.02/1M tokens) is roughly $1–3
  depending on chunk size

Unlike the AWS Bedrock path, there is no separate per-call quota
visible at the agent-vault layer — Azure OpenAI handles throttling
inside the `azure_ai` extension call. If your indexer hits the
deployment's TPM limit, `azure_ai.generate_embeddings` will raise
and the agent-vault pipeline retries via the standard
`generate_embeddings()` polling loop.

## Troubleshooting

### `ERROR: extension "azure_ai" is not available`

The extension isn't in the `azure.extensions` allowlist. Set it via
the Azure CLI:

```bash
az postgres flexible-server parameter set \
  --resource-group agent-vault-rg \
  --server-name agent-vault-pg \
  --name azure.extensions \
  --value AZURE_AI,VECTOR
```

### `ERROR: Azure OpenAI endpoint is not configured`

`azure_ai.set_setting('azure_openai.endpoint', ...)` was never run,
or the database role making the call doesn't have permission to
read the setting. Run the snippet from the setup section, then
verify with `SELECT azure_ai.get_setting('azure_openai.endpoint')`.

### Slow indexing

Server-side embedding throughput is bounded by Azure OpenAI's TPM
quota for the deployment. For 100k+ chunk corpora, request a quota
increase via the Azure portal or use a `text-embedding-3-small`
deployment with higher TPM allocation than the default.

### Connection pool exhaustion

Same symptoms and fix as CloudSQL — see the
[CloudSQL doc](./cloudsql.md#connection-pool-exhaustion). Flexible
Server's `max_connections` is tier-dependent; check with
`SHOW max_connections;` and stay under 50% with the configured
pool.

## Related documentation

- [RFC 0002 — AWS support](../rfc/0002-aws-support.md) — Azure isn't
  in scope for RFC 0002, but the SERVER_SIDE patterns there are
  relevant
- [PostgreSQL backend](./postgresql.md) — provider-level details
  shared with all PostgreSQL-compatible backends
- [Embeddings architecture](../architecture/embeddings.md) — how
  SERVER_SIDE strategies route to the SQL adapter
