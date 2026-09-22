#!/usr/bin/env python3
"""Generate server-side embeddings for remaining NULL-embedding rows.

Uses parallel asyncpg connections for higher throughput.
"""
import asyncio
import asyncpg
import os
import time
import sys

MODEL = "text-embedding-005"
DB_CONFIG = {
    "host": os.environ.get("INQUIRY_DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("INQUIRY_DB_PORT", "5434")),
    "user": os.environ.get("INQUIRY_DB_USER", "postgres"),
    "password": os.environ["INQUIRY_DB_PASSWORD"],  # Required - no default
    "database": os.environ.get("INQUIRY_DB_NAME", "agentic-inquiry"),
}
WORKERS = 5
BATCH_SIZE = 25  # Smaller batches = more parallelism


async def worker(pool, table, content_col, ids, worker_id, stats):
    """Process a partition of IDs."""
    for i in range(0, len(ids), BATCH_SIZE):
        batch = ids[i : i + BATCH_SIZE]
        try:
            async with pool.acquire() as conn:
                if content_col == "content":
                    result = await conn.execute(
                        f"UPDATE {table} SET embedding = embedding('{MODEL}', "
                        f"LEFT(content, 8000))::vector "
                        f"WHERE id = ANY($1) AND embedding IS NULL",
                        batch,
                    )
                else:
                    result = await conn.execute(
                        f"UPDATE {table} SET embedding = embedding('{MODEL}', "
                        f"{content_col})::vector "
                        f"WHERE id = ANY($1) AND embedding IS NULL",
                        batch,
                    )
                count = int(result.split()[-1]) if result else 0
                stats["embedded"] += count
        except Exception as e:
            stats["failed"] += len(batch)
            if "4MB" in str(e) or "too large" in str(e).lower():
                # Try one-by-one for oversized rows
                for row_id in batch:
                    try:
                        async with pool.acquire() as conn:
                            await conn.execute(
                                f"UPDATE {table} SET embedding = embedding('{MODEL}', "
                                f"LEFT({content_col}, 4000))::vector "
                                f"WHERE id = $1 AND embedding IS NULL",
                                row_id,
                            )
                            stats["embedded"] += 1
                            stats["failed"] -= 1
                    except Exception:
                        pass  # Truly failed


async def embed_table(table, content_col, label):
    """Embed all NULL-embedding rows in a table using parallel workers."""
    pool = await asyncpg.create_pool(**DB_CONFIG, min_size=WORKERS, max_size=WORKERS + 2)

    total = await pool.fetchval(
        f"SELECT COUNT(*) FROM {table} WHERE embedding IS NULL"
    )
    print(f"[{label}] {total:,} rows need embeddings ({WORKERS} workers, batch={BATCH_SIZE})")

    if total == 0:
        await pool.close()
        return 0

    # Get all IDs
    rows = await pool.fetch(
        f"SELECT id FROM {table} WHERE embedding IS NULL ORDER BY id"
    )
    all_ids = [r["id"] for r in rows]

    # Partition IDs across workers
    partitions = [[] for _ in range(WORKERS)]
    for i, row_id in enumerate(all_ids):
        partitions[i % WORKERS].append(row_id)

    stats = {"embedded": 0, "failed": 0}
    start = time.time()

    # Progress monitor
    async def monitor():
        while True:
            await asyncio.sleep(15)
            elapsed = time.time() - start
            rate = stats["embedded"] / elapsed if elapsed > 0 else 0
            remaining = total - stats["embedded"] - stats["failed"]
            eta = remaining / rate if rate > 0 else 0
            print(
                f"  [{label}] {stats['embedded']:,}/{total:,} "
                f"({rate:.0f}/sec, ETA {eta:.0f}s, failed {stats['failed']})",
                flush=True,
            )

    monitor_task = asyncio.create_task(monitor())

    # Launch workers
    tasks = [
        asyncio.create_task(worker(pool, table, content_col, part, i, stats))
        for i, part in enumerate(partitions)
    ]
    await asyncio.gather(*tasks)
    monitor_task.cancel()

    elapsed = time.time() - start
    rate = stats["embedded"] / elapsed if elapsed > 0 else 0
    print(
        f"[{label}] DONE: {stats['embedded']:,}/{total:,} embedded in {elapsed:.0f}s "
        f"({rate:.0f}/sec), {stats['failed']} failed",
        flush=True,
    )
    await pool.close()
    return stats["embedded"]


async def main():
    print(f"Parallel embedding generation ({WORKERS} workers)")
    print("=" * 60, flush=True)
    start = time.time()

    chunks = await embed_table("ai_v_chunks", "content", "CHUNKS")
    entities = await embed_table("ai_g_entities", "qualified_name", "ENTITIES")

    elapsed = time.time() - start
    print(f"\nTOTAL: {chunks + entities:,} embeddings in {elapsed:.0f}s")


if __name__ == "__main__":
    asyncio.run(main())
