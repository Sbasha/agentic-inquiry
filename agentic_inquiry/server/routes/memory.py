"""Memory endpoints - store and recall via shared service layer."""

import logging
import uuid

from fastapi import APIRouter, Request
from pydantic import BaseModel

from agentic_inquiry.memory.models import MemoryContext, RetrievalResult

logger = logging.getLogger("ai.server.routes.memory")

router = APIRouter()


class MemoryStoreRequest(BaseModel):
    content: str
    category: str = "observation"
    importance: float = 0.7
    metadata: dict | None = None
    file_paths: list[str] | None = None
    entity_names: list[str] | None = None


class MemoryRecallRequest(BaseModel):
    query: str
    limit: int = 5
    include_global: bool = False


@router.post("/memory/store")
async def memory_store(request: Request, body: MemoryStoreRequest) -> dict:
    """Store a memory with git versioning."""
    version_manager = request.app.state.version_manager
    cache_manager = request.app.state.cache_manager
    services = request.app.state.services
    memory_system = services.get("memory_system")

    memory_id = str(uuid.uuid4())[:8]
    stored = False

    version_meta = version_manager.create_version_metadata(
        file_paths=body.file_paths,
        entity_names=body.entity_names,
    )

    combined_metadata = {
        "category": body.category,
        "project_id": request.app.state.project_id,
        "scope": "project",
        **(body.metadata or {}),
        **version_meta,
    }

    if memory_system:
        try:
            session_id = str(uuid.uuid4())
            context = MemoryContext(
                agent_id="rest_api",
                session_id=session_id,
                conversation_id=session_id,
                project_id=request.app.state.project_id,
            )
            result = await memory_system.store(
                content=body.content,
                context=context,
                importance=body.importance,
                metadata=combined_metadata,
            )
            memory_id = str(getattr(result, "id", memory_id))
            stored = True
        except Exception:
            logger.warning("Memory store failed via memory system")

    cache_manager.invalidate_memories()

    return {"id": memory_id, "stored": stored}


@router.post("/memory/recall")
async def memory_recall(request: Request, body: MemoryRecallRequest) -> dict:
    """Recall memories by query with project isolation."""
    cache_manager = request.app.state.cache_manager
    version_manager = request.app.state.version_manager
    services = request.app.state.services
    memory_system = services.get("memory_system")

    cache_key = cache_manager.hash_key(
        body.query, request.app.state.project_id, str(body.include_global)
    )
    cached = cache_manager.get_memories(cache_key)
    if cached is not None:
        return {"memories": cached, "cached": True}

    memories = []
    if memory_system:
        try:
            session_id = str(uuid.uuid4())
            context = MemoryContext(
                agent_id="rest_api",
                session_id=session_id,
                conversation_id=session_id,
                project_id=request.app.state.project_id,
            )
            results = await memory_system.retrieve(
                query=body.query,
                context=context,
                limit=body.limit,
                strategy="adaptive",
            )
            items = results.get("results", []) if isinstance(results, dict) else results
            for item in items:
                memory = _format_memory(item)
                if memory:
                    memories.append(memory)
        except Exception:
            logger.debug("Memory recall failed", exc_info=True)

    memories = version_manager.check_staleness(memories)
    cache_manager.put_memories(cache_key, memories)

    return {"memories": memories[:body.limit], "cached": False}


@router.get("/memory/list")
async def memory_list(request: Request) -> dict:
    """List all stored memories."""
    services = request.app.state.services
    memory_system = services.get("memory_system")
    
    memories = []
    if memory_system:
        try:
            # This depends on memory_system implementation
            # For now return dummy or try to retrieve all
            results = await memory_system.retrieve(query="", limit=100)
            items = results.get("results", []) if isinstance(results, dict) else results
            for item in items:
                memory = _format_memory(item)
                if memory:
                    memories.append(memory)
        except Exception:
            logger.debug("Memory list failed", exc_info=True)
            
    return {"memories": memories}

def _format_memory(item) -> dict | None:
    """Format a memory retrieval result."""
    try:
        if isinstance(item, RetrievalResult):
            mem = item.item
            meta = mem.metadata
            return {
                "content": mem.content,
                "created": str(mem.created_at),
                "importance": mem.importance,
                "confidence": meta.get("confidence", 1.0),
                "file_paths": meta.get("file_paths", []),
                "category": meta.get("category", "unknown"),
            }
        elif isinstance(item, dict):
            return {
                "content": item.get("content", ""),
                "created": item.get("created", "unknown"),
                "importance": item.get("importance", 0.5),
                "confidence": item.get("confidence", 1.0),
                "file_paths": item.get("file_paths", []),
                "category": item.get("category", "unknown"),
            }
        else:
            return {"content": str(item), "created": "unknown", "importance": 0.5,
                    "confidence": 1.0, "file_paths": [], "category": "unknown"}
    except Exception:
        return None
