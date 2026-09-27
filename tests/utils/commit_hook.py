"""Run a competing write at a chosen point around LanceDBManager commits."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Awaitable, Callable, Optional

from agentic_inquiry.database.lancedb_manager import LanceDBManager

Hook = Callable[[str], Awaitable[None]]


@asynccontextmanager
async def commit_hook(
    manager: LanceDBManager,
    *,
    on_enter: Optional[Hook] = None,
    on_exit: Optional[Hook] = None,
) -> AsyncIterator[None]:
    """Await ``on_enter`` before and ``on_exit`` after each hold of the commit lock.

    Every write to an existing table commits inside ``manager._locked``, so
    ``on_exit`` runs between the commits of a write that takes more than one.
    ``on_exit`` is skipped when the write inside the lock raises.
    Table creation does not pass through the lock: seed tables before arming.
    Writes a hook makes itself do not re-trigger the hooks. Each hook receives
    the table name.
    """
    original = manager._locked
    patched_before = "_locked" in vars(manager)
    in_hook = False

    async def run(hook: Optional[Hook], table_name: str) -> None:
        nonlocal in_hook
        if hook is None or in_hook:
            return
        in_hook = True
        try:
            await hook(table_name)
        finally:
            in_hook = False

    @asynccontextmanager
    async def locked(table_name: str) -> AsyncIterator[None]:
        await run(on_enter, table_name)
        async with original(table_name):
            yield
        await run(on_exit, table_name)

    manager._locked = locked  # type: ignore[method-assign]
    try:
        yield
    finally:
        if patched_before:
            manager._locked = original  # type: ignore[method-assign]
        else:
            del manager._locked
