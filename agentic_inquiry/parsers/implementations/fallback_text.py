"""Fallback parser for text files that have no specialized parser."""

from pathlib import Path
from typing import List

from agentic_inquiry.config import FallbackTextParserConfig
from agentic_inquiry.exceptions import ParsingError
from agentic_inquiry.parsers.implementations.utils.chunking import pack_lines
from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk


class FallbackTextParser:
    """Reads a file as text and chunks it on line boundaries.

    Each chunk is exactly lines ``line_start``..``line_end`` of the file and at
    most ``max_chunk_size`` characters (one longer line stands alone), breaking
    after blank lines where possible. Chunks never overlap. No symbols or
    relationships are extracted.
    """

    def __init__(self, max_chunk_size: int = 1000):
        """Initialize the parser.

        Args:
            max_chunk_size: Maximum characters per chunk, newlines included.
        """
        self.max_chunk_size = max_chunk_size

    def apply_config(self, config: FallbackTextParserConfig) -> None:
        """Copy chunk settings from the loaded parser configuration."""
        self.max_chunk_size = config.max_chunk_size

    async def parse(self, path: str, **kwargs) -> ParsedDocument:
        """Parse a file into line-aligned chunks.

        Args:
            path: Path to the file to parse
            **kwargs: Additional arguments (ignored)

        Returns:
            ParsedDocument with one chunk per packed line span

        Raises:
            ParsingError: If the file cannot be read
        """
        file_path = Path(path)

        if not file_path.exists():
            raise ParsingError(f"File not found: {path}")

        if not file_path.is_file():
            raise ParsingError(f"Not a file: {path}")

        content = await self._read_with_encoding_detection(file_path)
        chunks = self._create_line_chunks(content)

        return ParsedDocument(
            doc_id=str(file_path.absolute()),
            file_path=str(file_path.absolute()),
            chunks=chunks,
            metadata={
                'language': file_path.suffix.lstrip('.') if file_path.suffix else 'text',
                'total_chunks': len(chunks),
            }
        )

    async def _read_with_encoding_detection(self, path: Path) -> str:
        """Read file with automatic encoding detection using aiofiles.
        
        Tries encodings in order: UTF-8, Latin-1, cp1252, ASCII.
        Falls back to UTF-8 with error replacement if all fail.
        
        Args:
            path: Path to the file
            
        Returns:
            File content as string
            
        Raises:
            ParsingError: If file cannot be read
        """
        import aiofiles
        
        encodings = ['utf-8', 'latin-1', 'cp1252', 'ascii']
        
        for encoding in encodings:
            try:
                async with aiofiles.open(path, mode='r', encoding=encoding) as f:
                    return await f.read()
            except (UnicodeDecodeError, LookupError):
                continue
        
        # Last resort: UTF-8 with error replacement
        try:
            async with aiofiles.open(path, mode='r', encoding='utf-8', errors='replace') as f:
                return await f.read()
        except Exception as e:
            raise ParsingError(f"Failed to read file {path}: {e}") from e
    
    def _create_line_chunks(self, content: str) -> List[ParserChunk]:
        """Pack the file's lines into chunks; whitespace-only spans are dropped."""
        lines = content.splitlines()
        chunks = []
        for start, end in pack_lines(lines, 1, self.max_chunk_size):
            text = "\n".join(lines[start - 1:end])
            if not text.strip():
                continue
            chunks.append(ParserChunk(
                content=text,
                fts_text=text,
                content_type="OTHER",
                line_start=start,
                line_end=end,
                metadata={'chunk_type': 'lines'},
            ))
        if not chunks:
            chunks.append(ParserChunk(
                content="",
                fts_text="",
                content_type="OTHER",
                line_start=1,
                line_end=1,
                metadata={'chunk_type': 'empty'},
            ))
        total = len(chunks)
        for index, chunk in enumerate(chunks):
            chunk.metadata['chunk_index'] = index
            chunk.metadata['total_chunks'] = total
        return chunks

    async def can_parse(self, file_path: str) -> bool:
        """Check if this parser can handle the file.
        
        The fallback parser can handle any text file, so this always returns True
        for files that exist and are readable.
        
        Args:
            file_path: Path to check
            
        Returns:
            True if the file exists and is a file
        """
        path = Path(file_path)
        return path.exists() and path.is_file()
