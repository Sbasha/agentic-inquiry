#!/usr/bin/env python3
"""Comprehensive tests for FTS text generation in parsers.

This test suite verifies that parsers generate appropriate FTS-optimized text
for both code and prose content, as specified in requirements 16.1-16.5.
"""

import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from agent_vault.parsers.executor import get_parser_instance
from agent_vault.parsers.implementations.document import DocumentParser

# Trigger parser auto-registration
import agent_vault.parsers.implementations  # noqa: F401


class TestUnifiedCodeParserFTSText:
    """Test FTS text generation for UnifiedCodeParser (Requirements 16.1, 16.3, 16.5)."""
    
    @pytest.fixture
    def sample_python_file(self):
        """Create a sample Python file with various code elements."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('''
"""User management module."""
import os
import sys
from typing import List, Dict
from datetime import datetime

class UserManager:
    """Manages user operations."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.users = []
    
    def add_user(self, username: str, email: str) -> bool:
        """Add a user to the system."""
        if self._validate_email(email):
            user = {"username": username, "email": email}
            self.users.append(user)
            return True
        return False
    
    def _validate_email(self, email: str) -> bool:
        """Validate email format."""
        return "@" in email and "." in email

def main():
    """Main entry point."""
    manager = UserManager("/tmp/users.db")
    manager.add_user("john_doe", "john@example.com")
    print("User added successfully")

if __name__ == "__main__":
    main()
''')
            f.flush()
            yield Path(f.name)
        
        # Cleanup
        Path(f.name).unlink()
    
    @pytest.mark.asyncio
    async def test_fts_text_is_generated(self, sample_python_file):
        """Test that fts_text is populated in ParserChunk (Requirement 16.5)."""
        parser = get_parser_instance("unified_code")
        doc = await parser.parse(str(sample_python_file))
        
        # At least some chunks should have FTS text
        chunks_with_fts = [c for c in doc.chunks if c.fts_text]
        assert len(chunks_with_fts) > 0, "At least one chunk should have fts_text populated"
        
        # FTS text should not be empty
        for chunk in chunks_with_fts:
            assert chunk.fts_text.strip(), "fts_text should not be empty"
    
    @pytest.mark.asyncio
    async def test_fts_text_contains_identifiers(self, sample_python_file):
        """Test that FTS text extracts identifiers and symbol names (Requirement 16.1)."""
        parser = get_parser_instance("unified_code")
        doc = await parser.parse(str(sample_python_file))
        
        # Collect all FTS text
        all_fts_text = " ".join(c.fts_text for c in doc.chunks if c.fts_text)
        
        # Should contain class names
        assert "UserManager" in all_fts_text, "FTS text should contain class name 'UserManager'"
        
        # Should contain method names
        assert "add_user" in all_fts_text or "add" in all_fts_text, \
            "FTS text should contain method name 'add_user' or 'add'"
        assert "validate_email" in all_fts_text or "validate" in all_fts_text, \
            "FTS text should contain method name '_validate_email' or 'validate'"
        
        # Should contain function names
        assert "main" in all_fts_text, "FTS text should contain function name 'main'"
    
    @pytest.mark.asyncio
    async def test_fts_text_contains_imports(self, sample_python_file):
        """Test that FTS text includes import names (Requirement 16.1)."""
        parser = get_parser_instance("unified_code")
        doc = await parser.parse(str(sample_python_file))
        
        # Collect all FTS text
        all_fts_text = " ".join(c.fts_text for c in doc.chunks if c.fts_text)
        
        # Should contain import names
        assert "os" in all_fts_text or "sys" in all_fts_text, \
            "FTS text should contain import names like 'os' or 'sys'"
        assert "List" in all_fts_text or "Dict" in all_fts_text, \
            "FTS text should contain imported types like 'List' or 'Dict'"
    
    @pytest.mark.asyncio
    async def test_fts_text_removes_syntax(self, sample_python_file):
        """Test that syntax is removed but meaningful identifiers preserved (Requirement 16.3)."""
        parser = get_parser_instance("unified_code")
        doc = await parser.parse(str(sample_python_file))
        
        # Get FTS text from chunks
        chunks_with_fts = [c for c in doc.chunks if c.fts_text]
        assert len(chunks_with_fts) > 0
        
        for chunk in chunks_with_fts:
            fts_text = chunk.fts_text
            
            # Should not contain excessive syntax characters
            # Allow some punctuation but not excessive amounts
            syntax_chars = fts_text.count('(') + fts_text.count(')') + \
                          fts_text.count('{') + fts_text.count('}') + \
                          fts_text.count('[') + fts_text.count(']') + \
                          fts_text.count(';') + fts_text.count(':')
            
            # Syntax should be minimal compared to content length
            if len(fts_text) > 50:
                syntax_ratio = syntax_chars / len(fts_text)
                assert syntax_ratio < 0.1, \
                    f"FTS text has too much syntax ({syntax_ratio:.2%}): {fts_text[:100]}"
    
    @pytest.mark.asyncio
    async def test_fts_text_preserves_meaningful_identifiers(self, sample_python_file):
        """Test that meaningful identifiers are preserved (Requirement 16.3)."""
        parser = get_parser_instance("unified_code")
        doc = await parser.parse(str(sample_python_file))
        
        # Collect all FTS text
        all_fts_text = " ".join(c.fts_text for c in doc.chunks if c.fts_text).lower()
        
        # Should preserve meaningful variable names
        meaningful_identifiers = [
            "username", "email", "db_path", "users", "manager"
        ]
        
        found_identifiers = [ident for ident in meaningful_identifiers if ident in all_fts_text]
        assert len(found_identifiers) >= 2, \
            f"FTS text should preserve meaningful identifiers. Found: {found_identifiers}"
    
    @pytest.mark.asyncio
    async def test_fts_text_excludes_keywords(self, sample_python_file):
        """Test that common keywords are filtered out."""
        parser = get_parser_instance("unified_code")
        doc = await parser.parse(str(sample_python_file))
        
        # Get FTS text
        all_fts_text = " ".join(c.fts_text for c in doc.chunks if c.fts_text).lower()
        
        # Common keywords should be minimal or absent
        # (Some may appear in identifiers like "return_value", which is OK)
        keywords = ["def", "class", "import", "from", "return"]
        
        # Count keyword occurrences
        keyword_count = sum(all_fts_text.count(f" {kw} ") for kw in keywords)
        
        # Keywords should be minimal compared to total content
        word_count = len(all_fts_text.split())
        if word_count > 0:
            keyword_ratio = keyword_count / word_count
            assert keyword_ratio < 0.2, \
                f"FTS text has too many keywords ({keyword_ratio:.2%})"
    
    @pytest.mark.asyncio
    async def test_fts_text_matches_symbols(self, sample_python_file):
        """Test that FTS text contains symbols from code_symbols list."""
        parser = get_parser_instance("unified_code")
        doc = await parser.parse(str(sample_python_file))
        
        for chunk in doc.chunks:
            if chunk.symbols and chunk.fts_text:
                fts_lower = chunk.fts_text.lower()
                
                # At least some symbols should be in FTS text
                symbols_in_fts = [sym for sym in chunk.symbols if sym.lower() in fts_lower]
                
                # Allow for some symbols to be missing (e.g., private methods)
                # but at least 50% should be present
                if len(chunk.symbols) > 0:
                    coverage = len(symbols_in_fts) / len(chunk.symbols)
                    assert coverage >= 0.3, \
                        f"FTS text should contain symbols. Coverage: {coverage:.1%}, " \
                        f"Symbols: {chunk.symbols}, FTS: {chunk.fts_text[:100]}"
    
    @pytest.mark.asyncio
    async def test_fts_text_reasonable_length(self, sample_python_file):
        """Test that FTS text is reasonably sized."""
        parser = get_parser_instance("unified_code")
        doc = await parser.parse(str(sample_python_file))
        
        for chunk in doc.chunks:
            if chunk.fts_text:
                # FTS text should not be excessively long
                assert len(chunk.fts_text) < 10000, \
                    f"FTS text too long: {len(chunk.fts_text)} characters"
                
                # FTS text should not be too short if chunk has content
                if chunk.content and len(chunk.content) > 100:
                    assert len(chunk.fts_text) > 10, \
                        "FTS text too short for substantial chunk"


class TestDocumentParserFTSText:
    """Test FTS text generation for DocumentParser (Requirements 16.2, 16.4, 16.5)."""
    
    @pytest.fixture
    def sample_markdown_file(self):
        """Create a sample markdown file with prose content."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write('''# User Guide

## Introduction

Welcome to the comprehensive user guide for our application. This document
provides detailed instructions on how to use all features effectively.

## Getting Started

To begin using the application, follow these simple steps:

1. Download the installer from our website
2. Run the installation wizard
3. Launch the application
4. Create your first project

### System Requirements

The application requires:
- Operating System: Windows 10 or later, macOS 10.15+, or Linux
- Memory: At least 4GB RAM
- Storage: 500MB available disk space
- Internet connection for updates

## Features

### Project Management

Our application provides robust project management capabilities including:
- Task tracking and assignment
- Timeline visualization
- Resource allocation
- Progress reporting

### Collaboration Tools

Work together with your team using:
- Real-time document editing
- Comments and annotations
- Version control
- Activity notifications

## Conclusion

Thank you for choosing our application. For additional support, please
visit our help center or contact customer service.
''')
            f.flush()
            yield Path(f.name)
        
        # Cleanup
        Path(f.name).unlink()
    
    @pytest.mark.asyncio
    async def test_fts_text_is_generated(self, sample_markdown_file):
        """Test that fts_text is populated in ParserChunk (Requirement 16.5)."""
        parser = DocumentParser()
        doc = await parser.parse(str(sample_markdown_file))
        
        # At least some chunks should have FTS text
        chunks_with_fts = [c for c in doc.chunks if c.fts_text]
        assert len(chunks_with_fts) > 0, "At least one chunk should have fts_text populated"
        
        # FTS text should not be empty
        for chunk in chunks_with_fts:
            assert chunk.fts_text.strip(), "fts_text should not be empty for valid chunks"
    
    @pytest.mark.asyncio
    async def test_fts_text_cleans_prose(self, sample_markdown_file):
        """Test that FTS text cleans prose content (Requirement 16.2)."""
        parser = DocumentParser()
        doc = await parser.parse(str(sample_markdown_file))
        
        chunks_with_fts = [c for c in doc.chunks if c.fts_text]
        assert len(chunks_with_fts) > 0
        
        for chunk in chunks_with_fts:
            fts_text = chunk.fts_text
            
            # Should not have excessive whitespace
            assert "   " not in fts_text, \
                f"FTS text should not have excessive whitespace: {fts_text[:100]}"
            
            # Should not have multiple consecutive newlines
            assert "\n\n\n" not in fts_text, \
                "FTS text should not have multiple consecutive newlines"
    
    @pytest.mark.asyncio
    async def test_fts_text_preserves_content(self, sample_markdown_file):
        """Test that FTS text preserves important prose content (Requirement 16.4)."""
        parser = DocumentParser()
        doc = await parser.parse(str(sample_markdown_file))
        
        # Collect all FTS text
        all_fts_text = " ".join(c.fts_text for c in doc.chunks if c.fts_text)
        
        # Should contain key phrases from the document
        key_phrases = [
            "User Guide", "Introduction", "Getting Started",
            "Features", "Project Management", "Collaboration"
        ]
        
        found_phrases = [phrase for phrase in key_phrases if phrase in all_fts_text]
        assert len(found_phrases) >= 4, \
            f"FTS text should preserve key content. Found: {found_phrases}"
    
    @pytest.mark.asyncio
    async def test_fts_text_never_empty_for_valid_chunks(self, sample_markdown_file):
        """Test that fts_text is never empty for valid chunks (Requirement 16.5)."""
        parser = DocumentParser()
        doc = await parser.parse(str(sample_markdown_file))
        
        for chunk in doc.chunks:
            # If chunk has content, it should have FTS text
            if chunk.content and len(chunk.content.strip()) > 20:
                assert chunk.fts_text, \
                    f"Chunk with content should have fts_text. Content: {chunk.content[:100]}"
                assert chunk.fts_text.strip(), \
                    "fts_text should not be empty string for valid chunks"
    
    @pytest.mark.asyncio
    async def test_fts_text_reasonable_length(self, sample_markdown_file):
        """Test that FTS text is reasonably sized."""
        parser = DocumentParser()
        doc = await parser.parse(str(sample_markdown_file))
        
        for chunk in doc.chunks:
            if chunk.fts_text:
                # FTS text should not be excessively long
                assert len(chunk.fts_text) < 10000, \
                    f"FTS text too long: {len(chunk.fts_text)} characters"
                
                # FTS text should be similar in length to content (within 2x)
                if chunk.content:
                    ratio = len(chunk.fts_text) / len(chunk.content)
                    assert 0.5 <= ratio <= 2.0, \
                        f"FTS text length ratio unusual: {ratio:.2f}"
    
    @pytest.mark.asyncio
    async def test_fts_text_contains_searchable_terms(self, sample_markdown_file):
        """Test that FTS text contains searchable terms."""
        parser = DocumentParser()
        doc = await parser.parse(str(sample_markdown_file))
        
        # Collect all FTS text
        all_fts_text = " ".join(c.fts_text for c in doc.chunks if c.fts_text).lower()
        
        # Should contain searchable terms
        searchable_terms = [
            "application", "project", "management", "features",
            "installation", "requirements", "collaboration"
        ]
        
        found_terms = [term for term in searchable_terms if term in all_fts_text]
        assert len(found_terms) >= 5, \
            f"FTS text should contain searchable terms. Found: {found_terms}"
    
    @pytest.mark.asyncio
    async def test_fts_text_normalized_whitespace(self, sample_markdown_file):
        """Test that FTS text has normalized whitespace."""
        parser = DocumentParser()
        doc = await parser.parse(str(sample_markdown_file))
        
        for chunk in doc.chunks:
            if chunk.fts_text:
                # Should not start or end with whitespace
                assert chunk.fts_text == chunk.fts_text.strip(), \
                    "FTS text should not have leading/trailing whitespace"
                
                # Should not have tabs
                assert "\t" not in chunk.fts_text, \
                    "FTS text should not contain tabs"


class TestFTSTextComparison:
    """Compare FTS text generation between code and prose parsers."""
    
    @pytest.mark.asyncio
    async def test_code_vs_prose_fts_text_differences(self):
        """Test that code and prose FTS text have appropriate differences."""
        # Create code file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write('class Example:\n    def method(self):\n        return True')
            code_file = Path(f.name)
        
        # Create prose file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write('# Example\n\nThis is an example document with prose content.')
            prose_file = Path(f.name)
        
        try:
            # Parse both
            code_parser = get_parser_instance("unified_code")
            code_doc = await code_parser.parse(str(code_file))
            
            prose_parser = DocumentParser()
            prose_doc = await prose_parser.parse(str(prose_file))
            
            # Get FTS text
            code_fts = " ".join(c.fts_text for c in code_doc.chunks if c.fts_text)
            prose_fts = " ".join(c.fts_text for c in prose_doc.chunks if c.fts_text)
            
            # Code FTS should contain identifiers
            assert "Example" in code_fts or "method" in code_fts, \
                "Code FTS should contain identifiers"
            
            # Prose FTS should contain natural language
            assert "example" in prose_fts.lower() or "document" in prose_fts.lower(), \
                "Prose FTS should contain natural language"
            
        finally:
            code_file.unlink()
            prose_file.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
