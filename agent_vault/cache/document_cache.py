"""In-memory document cache with LRU eviction and file modification tracking.

This module provides a default cache implementation that stores parsed
documents in memory with automatic invalidation based on file modification
time and size tracking. Optionally supports disk persistence for cache entries.
"""

from typing import Optional, Dict, Any, Tuple, Callable, cast
from pathlib import Path
from datetime import datetime
import functools
import hashlib
import logging
import json
import pickle
import asyncio
import uuid
import io

import aiofiles
import aiofiles.os

from agent_vault.config import Config

logger = logging.getLogger(__name__)


# Safe classes that can be deserialized from cache files
# This prevents arbitrary code execution from tampered cache files
SAFE_PICKLE_MODULES = frozenset({
    "agent_vault.parsers.models",
    "agent_vault.models.document",
    "agent_vault.models.graph_entity",
    "agent_vault.indexing.models",
    "builtins",
    "datetime",
    "pathlib",
    "collections",
    "numpy",
    "numpy.core.multiarray",
})


class RestrictedUnpickler(pickle.Unpickler):
    """Restricted unpickler that only allows known safe classes.

    This prevents arbitrary code execution from tampered cache files
    by limiting deserialization to a whitelist of safe modules.
    """

    def find_class(self, module: str, name: str) -> type:
        """Only allow classes from safe modules."""
        # Check if module is in safe list or is a submodule of a safe module
        is_safe = any(
            module == safe_mod or module.startswith(f"{safe_mod}.")
            for safe_mod in SAFE_PICKLE_MODULES
        )

        if not is_safe:
            raise pickle.UnpicklingError(
                f"Unsafe pickle class blocked: {module}.{name}. "
                f"If this is a legitimate class, add the module to SAFE_PICKLE_MODULES."
            )

        return super().find_class(module, name)


def safe_pickle_loads(data: bytes) -> object:
    """Safely load pickle data using restricted unpickler.

    Args:
        data: Pickled bytes to deserialize

    Returns:
        Deserialized object

    Raises:
        pickle.UnpicklingError: If data contains unsafe classes
    """
    return RestrictedUnpickler(io.BytesIO(data)).load()


class DocumentCache:
    """Cache for parsed documents with file modification tracking.
    
    This cache stores ParsedDocuments in memory and automatically invalidates
    entries when files are modified. Uses LRU eviction when the cache reaches
    its maximum size. Optionally supports disk persistence for cache entries.
    
    The cache key is based on file path, modification time, and size to ensure
    cached documents are only returned when the source file hasn't changed.
    Cache keys are prefixed with project_id for isolation across projects.
    
    Attributes:
        max_size: Maximum number of documents to cache
        hits: Number of cache hits
        misses: Number of cache misses
    
    Example:
        >>> cache = DocumentCache(max_size=1000)
        >>> doc = cache.get("/path/to/file.py")
        >>> if doc is None:
        ...     doc = parse_file("/path/to/file.py")
        ...     cache.put("/path/to/file.py", doc)
    """
    
    def __init__(
        self,
        config: Optional[Config] = None,
        project_id: Optional[str] = None,
        max_size: Optional[int] = None,
    ):
        """Initialize document cache.
        
        Note: This constructor does not load cache from disk. Use the async
        factory method `from_config()` to create a fully initialized cache
        with disk persistence loaded.
        
        Args:
            config: Config instance. If None, loads default configuration.
            project_id: Project ID for data isolation. If None, uses
                config.storage.default_project_id.
            max_size: Maximum number of documents to cache. If None, uses value
                from configuration (default: 1000)
        
        Example:
            >>> # Preferred: Use async factory method
            >>> config = Config.load()
            >>> cache = await DocumentCache.from_config(config, project_id="my_project")
            
            >>> # Or create without loading from disk
            >>> cache = DocumentCache(config, project_id="my_project")
            >>> await cache._load_from_disk()  # Load manually if needed
        """
        # Load config if not provided
        if config is None:
            config = Config.load()
        
        self.config = config
        
        # Resolve project_id
        if project_id is None:
            project_id = config.storage.default_project_id
            if not project_id:
                raise ValueError(
                    "project_id must be provided or set as storage.default_project_id in configuration"
                )
        
        self._project_id = project_id
        
        # Set max_size from parameter or config
        if max_size is None:
            max_size = self.config.cache.document_cache.max_size
        
        self._cache: Dict[str, Tuple[Any, float, str]] = {}
        self.max_size = max_size
        self.hits = 0
        self.misses = 0
        
        # Disk persistence configuration
        self._disk_enabled = self.config.storage.document_cache.enabled
        
        if self._disk_enabled:
            try:
                # Get cache directory path
                self._cache_dir: Optional[Path] = self.config.storage.get_document_cache_path()
                self._entries_dir: Optional[Path] = self._cache_dir / "entries"
                self._index_file: Optional[Path] = self._cache_dir / "cache_index.json"
                
                # Create cache directories (backend owns its own resource setup)
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                self._entries_dir.mkdir(parents=True, exist_ok=True)
                
                # Test write permissions by creating and removing a unique test file
                # Use uuid to prevent race conditions with concurrent initialization
                test_file = self._cache_dir / f".write_test_{uuid.uuid4().hex}"
                test_file.write_text("test")
                test_file.unlink()
                
                logger.debug("Initialized DocumentCache with disk persistence at %s", self._cache_dir)
            except (OSError, PermissionError) as e:
                logger.warning(
                    "Disk persistence disabled due to error: %s. "
                    "Falling back to memory-only mode.",
                    e
                )
                self._disk_enabled = False
                # Clear any partially initialized paths
                self._cache_dir = None
                self._entries_dir = None
                self._index_file = None
            except Exception as e:
                logger.warning(
                    "Failed to initialize disk persistence: %s. "
                    "Falling back to memory-only mode.",
                    e
                )
                self._disk_enabled = False
                # Clear any partially initialized paths
                self._cache_dir = None
                self._entries_dir = None
                self._index_file = None
        
        logger.debug("Initialized DocumentCache with max_size=%s, disk_enabled=%s, project_id=%s", max_size, self._disk_enabled, self._project_id)
    
    @classmethod
    async def from_config(
        cls,
        config: Optional[Config] = None,
        project_id: Optional[str] = None
    ) -> "DocumentCache":
        """Create DocumentCache from configuration asynchronously.
        
        This is the preferred way to create a DocumentCache instance as it
        properly loads the cache from disk if persistence is enabled.
        
        Args:
            config: Optional Config instance. If None, loads default configuration.
            project_id: Project ID for data isolation. If None, uses
                config.storage.default_project_id.
            
        Returns:
            DocumentCache instance configured from settings with disk cache loaded
            
        Example:
            >>> from agent_vault.config import Config
            >>> config = Config.load()
            >>> cache = await DocumentCache.from_config(config, project_id="my_project")
            
            >>> # Or load default config
            >>> cache = await DocumentCache.from_config()
        """
        if config is None:
            config = Config.load()
        
        # Get max_size from config
        max_size = config.cache.document_cache.max_size
        
        # Create instance
        instance = cls(config=config, project_id=project_id, max_size=max_size)
        
        # Load from disk if enabled
        if instance._disk_enabled:
            await instance._load_from_disk()
        
        return instance
    
    def _get_cache_key(self, path: str, mtime: float, size: int) -> str:
        """Generate cache key from path, mtime, and size.
        
        Cache keys are prefixed with project_id for isolation across projects.
        
        Args:
            path: File path
            mtime: File modification time
            size: File size in bytes
            
        Returns:
            MD5 hash of the combined key data, prefixed with project_id
        """
        key_data = f"{path}:{mtime}:{size}"
        key_hash = hashlib.md5(key_data.encode()).hexdigest()
        return f"{self._project_id}:{key_hash}"
    
    async def _load_from_disk(self) -> None:
        """Load cache index and entries from disk asynchronously.
        
        Loads the cache index JSON file and then loads each entry from disk.
        Corrupted entries are skipped and optionally cleaned up.
        Falls back to memory-only mode on critical errors.
        """
        if not self._disk_enabled:
            logger.debug("Disk persistence disabled, skipping load from disk")
            return
        
        if not self._index_file.exists():  # type: ignore[union-attr]
            logger.debug("No cache index file found, starting with empty cache")
            return
        
        try:
            async with aiofiles.open(self._index_file, 'r') as f:
                content = await f.read()
                index = json.loads(content)
            
            loaded_count = 0
            corrupted_entries = []
            
            for key, entry_file in index.items():
                # Only load entries for current project
                if not key.startswith(f"{self._project_id}:"):
                    continue
                
                entry_path = self._entries_dir / entry_file
                if entry_path.exists():
                    try:
                        async with aiofiles.open(entry_path, 'rb') as f:
                            content = await f.read()
                            # Execute safe pickle load in executor (CPU-bound)
                            # Uses RestrictedUnpickler to prevent arbitrary code execution
                            loop = asyncio.get_running_loop()
                            safe_load_fn = cast(
                                Callable[[], Any],
                                functools.partial(safe_pickle_loads, content)
                            )
                            self._cache[key] = await loop.run_in_executor(
                                None, safe_load_fn
                            )
                        loaded_count += 1
                    except Exception as e:
                        logger.warning("Failed to load cache entry %s: %s. Entry will be removed.", entry_file, e)
                        corrupted_entries.append((key, entry_file))
                else:
                    logger.debug("Cache entry file not found: %s", entry_file)
                    corrupted_entries.append((key, entry_file))
            
            # Clean up corrupted entries from index
            if corrupted_entries:
                await self._cleanup_corrupted_entries(corrupted_entries)
            
            logger.debug("Loaded %s cache entries from disk", loaded_count)
            
        except Exception as e:
            logger.warning("Failed to load cache from disk: %s", e)

    async def _cleanup_corrupted_entries(self, corrupted_entries: list[tuple[str, str]]) -> None:
        """Remove corrupted entries from index and disk.
        
        Args:
            corrupted_entries: List of (key, entry_file) tuples to remove
        """
        if not self._disk_enabled:
            return

        # Type narrowing: these are not None when disk is enabled
        assert self._index_file is not None
        assert self._entries_dir is not None

        try:
            # Load current index
            if self._index_file.exists():
                async with aiofiles.open(self._index_file, 'r') as f:
                    content = await f.read()
                    index = json.loads(content)
            else:
                return
            
            # Remove corrupted entries from index
            for key, entry_file in corrupted_entries:
                if key in index:
                    del index[key]
                
                # Try to remove the corrupted file
                entry_path = self._entries_dir / entry_file
                try:
                    if entry_path.exists():
                        await aiofiles.os.remove(str(entry_path))
                except Exception as e:
                    logger.debug("Failed to remove corrupted entry file %s: %s", entry_file, e)
            
            # Save updated index atomically
            temp_index_file = self._index_file.with_suffix('.json.tmp')
            async with aiofiles.open(temp_index_file, 'w') as f:
                await f.write(json.dumps(index, indent=2))
            
            await aiofiles.os.replace(str(temp_index_file), str(self._index_file))
            
            logger.debug("Cleaned up %s corrupted cache entries", len(corrupted_entries))
            
        except Exception as e:
            logger.warning("Failed to cleanup corrupted entries: %s", e)
    
    async def _save_to_disk(self, key: str, value: Tuple[Any, float, str]) -> None:
        """Save cache entry to disk asynchronously with atomic write.
        
        Persists the cache entry as a pickle file and updates the cache index.
        Uses atomic write (write to temp file, then rename) to prevent corruption.
        Logs warnings on failures but doesn't crash.
        
        Args:
            key: Cache key (already includes project_id prefix)
            value: Cache value tuple (document, timestamp, path)
        """
        if not self._disk_enabled:
            return

        # Type narrowing: these are not None when disk is enabled
        assert self._entries_dir is not None

        try:
            # Generate filename from key hash (remove project_id prefix for filename)
            key_hash = key.split(":", 1)[1] if ":" in key else key
            entry_file = f"{key_hash}.pkl"
            entry_path = self._entries_dir / entry_file
            temp_entry_path = self._entries_dir / f"{entry_file}.tmp"
            
            # Execute pickle.dump in executor (CPU-bound)
            loop = asyncio.get_running_loop()
            pickled_data = await loop.run_in_executor(
                None, pickle.dumps, value
            )
            
            # Save entry atomically (write to temp file, then rename)
            async with aiofiles.open(temp_entry_path, 'wb') as f:
                await f.write(pickled_data)
            
            # Atomic rename
            await aiofiles.os.replace(str(temp_entry_path), str(entry_path))
            
            # Update index
            await self._update_index(key, entry_file)
            
        except Exception as e:
            logger.warning("Failed to save cache entry to disk: %s", e)
            # Clean up temp file if it exists
            try:
                if temp_entry_path.exists():
                    await aiofiles.os.remove(str(temp_entry_path))
            except Exception:
                pass  # Ignore cleanup errors
    
    async def _update_index(self, key: str, entry_file: str) -> None:
        """Update cache index file asynchronously.
        
        Maintains a JSON index mapping cache keys to entry filenames.
        Logs warnings on failures but doesn't crash.
        
        Args:
            key: Cache key (already includes project_id prefix)
            entry_file: Filename of the cache entry
        """
        if not self._disk_enabled:
            return

        # Type narrowing: this is not None when disk is enabled
        assert self._index_file is not None

        try:
            # Load existing index
            if self._index_file.exists():
                async with aiofiles.open(self._index_file, 'r') as f:
                    content = await f.read()
                    index = json.loads(content)
            else:
                index = {}
            
            # Update index
            index[key] = entry_file
            
            # Save index atomically (write to temp file, then rename)
            temp_index_file = self._index_file.with_suffix('.json.tmp')
            async with aiofiles.open(temp_index_file, 'w') as f:
                await f.write(json.dumps(index, indent=2))
            
            # Use aiofiles.os for atomic rename
            await aiofiles.os.replace(str(temp_index_file), str(self._index_file))
            
        except Exception as e:
            logger.warning("Failed to update cache index: %s", e)
    
    async def get(self, path: str) -> Optional[Any]:
        """Retrieve cached document if file hasn't changed.
        
        Checks if the file exists and hasn't been modified since caching.
        Returns None if file has changed or is not in cache.
        
        Args:
            path: File path to retrieve from cache
            
        Returns:
            Cached ParsedDocument if available and valid, None otherwise
        """
        try:
            file_path = Path(path)
            
            # Check if file exists using aiofiles
            exists = await aiofiles.os.path.exists(str(file_path))
            if not exists:
                logger.debug("File not found: %s", path)
                self.misses += 1
                return None
            
            # Get current file stats using aiofiles
            stat = await aiofiles.os.stat(str(file_path))
            cache_key = self._get_cache_key(path, stat.st_mtime, stat.st_size)
            
            # Check if cached version exists
            if cache_key in self._cache:
                doc, _, _ = self._cache[cache_key]
                self.hits += 1
                logger.debug("Cache hit for %s", path)
                return doc
            
            # Cache miss
            self.misses += 1
            logger.debug("Cache miss for %s", path)
            return None
            
        except Exception as e:
            logger.warning("Cache lookup failed for %s: %s", path, e)
            self.misses += 1
            return None
    
    async def put(self, path: str, document: Any) -> None:
        """Store parsed document in cache asynchronously.
        
        If the cache is full, evicts the oldest entry (LRU) before adding
        the new document. If disk persistence is enabled, also saves to disk.
        
        Args:
            path: File path to cache
            document: ParsedDocument to store
        """
        try:
            file_path = Path(path)
            
            # Check if file exists using aiofiles
            exists = await aiofiles.os.path.exists(str(file_path))
            if not exists:
                logger.warning("Cannot cache non-existent file: %s", path)
                return
            
            # Get file stats using aiofiles
            stat = await aiofiles.os.stat(str(file_path))
            cache_key = self._get_cache_key(path, stat.st_mtime, stat.st_size)
            
            # Evict oldest entry if cache is full
            if len(self._cache) >= self.max_size and cache_key not in self._cache:
                oldest_key = min(
                    self._cache.keys(), 
                    key=lambda k: self._cache[k][1]
                )
                oldest_path = self._cache[oldest_key][2]
                del self._cache[oldest_key]
                logger.debug("Evicted oldest cache entry: %s", oldest_path)
            
            # Store document with timestamp and path
            cache_value = (
                document, 
                datetime.now().timestamp(), 
                path
            )
            self._cache[cache_key] = cache_value
            logger.debug("Cached parse result for %s", path)
            
            # Save to disk if enabled
            if self._disk_enabled:
                await self._save_to_disk(cache_key, cache_value)
            
        except Exception as e:
            logger.warning("Failed to cache result for %s: %s", path, e)
    
    async def invalidate(self, path: str) -> None:
        """Remove cached entry for a file asynchronously.
        
        Removes all cache entries associated with the given file path,
        regardless of modification time or size.
        
        Args:
            path: File path to invalidate
        """
        keys_to_remove = [
            k for k, (_, _, p) in self._cache.items() 
            if p == path
        ]
        
        for key in keys_to_remove:
            del self._cache[key]
        
        if keys_to_remove:
            logger.debug("Invalidated %s cache entries for %s", len(keys_to_remove), path)
    
    async def clear(self) -> None:
        """Clear entire cache and reset statistics asynchronously."""
        self._cache.clear()
        self.hits = 0
        self.misses = 0
        logger.debug("Cleared cache")
    
    def stats(self) -> Dict[str, Any]:
        """Return cache statistics.
        
        Returns:
            Dictionary with cache size, hits, misses, and hit rate
        """
        total = self.hits + self.misses
        hit_rate = self.hits / total if total > 0 else 0.0
        
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": hit_rate
        }


__all__ = ["DocumentCache"]
