"""Contract tests for storage provider protocols.

This package contains contract tests that verify storage providers correctly
implement the VectorStorageProtocol and GraphStorageProtocol interfaces.

Contract tests are parameterized to run against multiple provider implementations,
ensuring all backends behave consistently.

Usage:
    # Run all contract tests
    pytest tests/storage/contracts/

    # Run against specific provider
    pytest tests/storage/contracts/ -k "lancedb"
    pytest tests/storage/contracts/ -k "memory"
"""
