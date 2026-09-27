"""File watching system for automatic change detection.

This module provides a protocol-based file watching system that monitors
directories for file changes and triggers callbacks. It uses hash-based
change detection for reliability.
"""

import logging
import threading
from typing import Callable, List, Optional, Protocol, runtime_checkable

from agentic_inquiry.watching.watcher import FileWatcher

logger = logging.getLogger(__name__)


@runtime_checkable
class WatcherProtocol(Protocol):
    """Protocol for file watcher implementations.
    
    File watchers monitor directories for changes and trigger callbacks
    when files are created, modified, or deleted.
    """
    
    def register_callback(self, callback: Callable[[str, str], None]) -> None:
        """Register a callback for file events.
        
        Args:
            callback: Function with signature callback(file_path: str, event_type: str)
                     where event_type is one of: "created", "modified", "deleted"
        """
        ...
    
    def unregister_callback(self, callback: Callable[[str, str], None]) -> None:
        """Unregister a previously registered callback.
        
        Args:
            callback: The callback function to remove
        """
        ...
    
    def watch_directory(self, path: str, recursive: bool = True, 
                       ignore_patterns: Optional[List[str]] = None) -> None:
        """Start watching a directory for changes.
        
        Args:
            path: Directory path to watch
            recursive: Whether to watch subdirectories
            ignore_patterns: Optional list of glob patterns to ignore
        """
        ...
    
    def start(self) -> None:
        """Start the file watcher."""
        ...
    
    def stop(self) -> None:
        """Stop the file watcher and clean up resources."""
        ...
    
    def pause(self) -> None:
        """Pause the file watcher without stopping it."""
        ...
    
    def resume(self) -> None:
        """Resume a paused file watcher."""
        ...
    
    def is_running(self) -> bool:
        """Check if the watcher is currently running.
        
        Returns:
            True if watcher is running, False otherwise
        """
        ...


class WatcherRegistry:
    """Registry for file watcher implementations.
    
    Similar to ParserRegistry and EmbeddingRegistry, this provides a
    centralized way to register and retrieve file watcher implementations.
    """
    
    def __init__(self) -> None:
        """Initialize the watcher registry."""
        self._watchers: dict[str, WatcherProtocol] = {}
        self._default: Optional[str] = None
    
    def register(self, name: str, watcher: WatcherProtocol, *, 
                set_default: bool = False) -> None:
        """Register a watcher implementation.
        
        Args:
            name: Descriptive name for the watcher
            watcher: Watcher instance implementing WatcherProtocol
            set_default: Whether to set this as the default watcher
            
        Raises:
            ValueError: If watcher name already registered
        """
        if name in self._watchers:
            raise ValueError(f"Watcher '{name}' already registered")
        
        self._watchers[name] = watcher
        
        if set_default or self._default is None:
            self._default = name
        
        logger.info("Registered watcher: %s", name)
    
    def unregister(self, name: str) -> None:
        """Unregister a watcher.
        
        Args:
            name: Name of the watcher to unregister
        """
        if name in self._watchers:
            del self._watchers[name]
            if self._default == name:
                self._default = None
            logger.info("Unregistered watcher: %s", name)
    
    def get(self, name: Optional[str] = None) -> WatcherProtocol:
        """Get a watcher by name, or the default watcher.
        
        Args:
            name: Optional watcher name (uses default if None)
            
        Returns:
            The requested watcher instance
            
        Raises:
            ValueError: If no default watcher set
            KeyError: If named watcher not found
        """
        watcher_name = name or self._default
        
        if watcher_name is None:
            raise ValueError("No default watcher set")
        
        try:
            return self._watchers[watcher_name]
        except KeyError as exc:
            raise KeyError(f"Watcher '{watcher_name}' not registered") from exc
    
    def available(self) -> List[str]:
        """List all registered watcher names.
        
        Returns:
            List of registered watcher names
        """
        return list(self._watchers.keys())


# Global registry instance
_watcher_registry = WatcherRegistry()


def register_watcher(name: str, watcher: WatcherProtocol, *, 
                    set_default: bool = False) -> None:
    """Register a watcher implementation globally.
    
    Args:
        name: Descriptive name for the watcher
        watcher: Watcher instance implementing WatcherProtocol
        set_default: Whether to set this as the default watcher
    """
    _watcher_registry.register(name, watcher, set_default=set_default)


def unregister_watcher(name: str) -> None:
    """Unregister a watcher globally.
    
    Args:
        name: Name of the watcher to unregister
    """
    _watcher_registry.unregister(name)


def get_watcher(name: Optional[str] = None) -> WatcherProtocol:
    """Get a registered watcher (default if name not specified).

    With no name and no default set, the watcher registered as ``"default"``
    is returned. The built-in ``FileWatcher`` is built and registered under
    that name when it is requested and absent.

    Args:
        name: Optional watcher name (uses default if None)

    Returns:
        The requested watcher instance

    Raises:
        ValueError: If the built-in watcher cannot be built, for example
            when no ``storage.default_project_id`` is configured.
    """
    if name is None and _watcher_registry._default is None:
        name = "default"
    if name == "default":
        _ensure_default_registered()
    return _watcher_registry.get(name)


def available_watchers() -> List[str]:
    """List all registered watcher names, building the built-in ``"default"``.

    Returns:
        List of registered watcher names

    Raises:
        ValueError: If the built-in watcher cannot be built, for example
            when no ``storage.default_project_id`` is configured.
    """
    _ensure_default_registered()
    return _watcher_registry.available()


_default_lock = threading.Lock()


def _ensure_default_registered() -> None:
    """Register the built-in ``FileWatcher`` as ``"default"`` if absent.

    Building it constructs a ``FileTracker``, which loads configuration and
    creates the tracker database's parent directory, so it must not run at
    import. It becomes the registry default only when none is set, so a
    watcher the caller registered keeps precedence.
    """
    with _default_lock:
        if "default" in _watcher_registry.available():
            return
        _watcher_registry.register("default", FileWatcher())
        logger.info("Registered built-in FileWatcher as the default watcher")


# Export public API
__all__ = [
    "WatcherProtocol",
    "WatcherRegistry",
    "FileWatcher",
    "register_watcher",
    "unregister_watcher",
    "get_watcher",
    "available_watchers",
]
