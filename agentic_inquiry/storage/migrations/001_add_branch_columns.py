"""Migration 001: Add branch indexing columns to ai_chunks."""

UPGRADE_SQL = """
ALTER TABLE {table_prefix}chunks ADD COLUMN IF NOT EXISTS branch VARCHAR(255) NOT NULL DEFAULT 'main';
ALTER TABLE {table_prefix}chunks ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE {table_prefix}chunks ADD COLUMN IF NOT EXISTS expired_at TIMESTAMP NULL;

UPDATE {table_prefix}chunks SET branch = 'main' WHERE branch = 'main';

ALTER TABLE {table_prefix}chunks DROP CONSTRAINT IF EXISTS {table_prefix}chunks_project_id_file_path_chunk_index_key;
ALTER TABLE {table_prefix}chunks ADD CONSTRAINT {table_prefix}chunks_project_branch_file_chunk_key
    UNIQUE (project_id, branch, file_path, chunk_index);

CREATE INDEX IF NOT EXISTS idx_{table_prefix}chunks_branch ON {table_prefix}chunks (branch);
CREATE INDEX IF NOT EXISTS idx_{table_prefix}chunks_active_branch ON {table_prefix}chunks (is_active, branch);
"""

DOWNGRADE_SQL = """
DROP INDEX IF EXISTS idx_{table_prefix}chunks_active_branch;
DROP INDEX IF EXISTS idx_{table_prefix}chunks_branch;
ALTER TABLE {table_prefix}chunks DROP COLUMN IF EXISTS expired_at;
ALTER TABLE {table_prefix}chunks DROP COLUMN IF EXISTS is_active;
ALTER TABLE {table_prefix}chunks DROP COLUMN IF EXISTS branch;
"""


async def upgrade(connection, table_prefix: str = "ai_") -> None:
    sql = UPGRADE_SQL.format(table_prefix=table_prefix)
    for statement in sql.strip().split(";"):
        statement = statement.strip()
        if statement:
            await connection.execute(statement)


async def downgrade(connection, table_prefix: str = "ai_") -> None:
    sql = DOWNGRADE_SQL.format(table_prefix=table_prefix)
    for statement in sql.strip().split(";"):
        statement = statement.strip()
        if statement:
            await connection.execute(statement)
