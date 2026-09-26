"""Fallback text parser for files that don't have specialized parsers.

This parser provides basic text extraction without requiring external dependencies.
It's used as a last resort when no other parser can handle a file.
"""

import re
from pathlib import Path
from typing import List, Tuple

from agentic_inquiry.config import FallbackTextParserConfig
from agentic_inquiry.exceptions import ParsingError
from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk

# Files at or under this size stay one chunk. Matches the AFP 8 KB evidence pack
# and covers LoCoMo / LongMemEval session files in those corpora (max ~7 KB).
WHOLE_FILE_MAX_CHARS = 8192

_SESSION_LINE = re.compile(r"^Session:\s+\S", re.IGNORECASE)
_DATE_LINE = re.compile(r"^(?:Date:|S\d+\s+Date:)", re.IGNORECASE)


def session_date_header(content: str) -> str:
    """Return the first two lines when they are a Session / Date header.

    Recognizes ``Session: …`` followed by ``Date: …`` or ``S0xx Date: …``.
    """
    lines = content.splitlines()
    if len(lines) < 2:
        return ""
    if _SESSION_LINE.match(lines[0].strip()) and _DATE_LINE.match(lines[1].strip()):
        return lines[0] + "\n" + lines[1]
    return ""


class FallbackTextParser:
    """Fallback parser that reads files as plain text with semantic chunking.
    
    This parser:
    - Reads files as UTF-8 text (with fallback to latin-1, cp1252, ASCII)
    - Keeps files at or under whole_file_max_chars as a single chunk
    - Splits larger files on paragraphs and sentences, copying Session/Date
      headers onto every remaining slice
    - Supports configurable chunk size and overlap
    - Does not extract symbols or relationships
    - Works with any text-based file
    """
    
    def __init__(
        self,
        max_chunk_size: int = 1000,
        chunk_overlap: int = 100,
        whole_file_max_chars: int = WHOLE_FILE_MAX_CHARS,
    ):
        """Initialize the fallback text parser.
        
        Args:
            max_chunk_size: Maximum number of characters per chunk when a file
                is larger than whole_file_max_chars (default: 1000)
            chunk_overlap: Number of characters to overlap between chunks (default: 100)
            whole_file_max_chars: Files at or under this size stay one chunk.
                Zero disables whole-file mode. Default is 8192.
        """
        self.max_chunk_size = max_chunk_size
        self.chunk_overlap = chunk_overlap
        self.whole_file_max_chars = whole_file_max_chars

    def apply_config(self, config: FallbackTextParserConfig) -> None:
        """Copy chunk settings from the loaded parser configuration."""
        self.max_chunk_size = config.max_chunk_size
        self.chunk_overlap = config.chunk_overlap
        self.whole_file_max_chars = config.whole_file_max_chars
    
    async def parse(self, path: str, **kwargs) -> ParsedDocument:
        """Parse a file as plain text with semantic chunking.

        Args:
            path: Path to the file to parse
            **kwargs: Additional arguments (ignored)

        Returns:
            ParsedDocument with semantically chunked content

        Raises:
            ParsingError: If the file cannot be read
        """
        file_path = Path(path)

        if not file_path.exists():
            raise ParsingError(f"File not found: {path}")

        if not file_path.is_file():
            raise ParsingError(f"Not a file: {path}")

        # Try multiple encodings (async)
        content = await self._read_with_encoding_detection(file_path)

        # Create semantic chunks (synchronous - fast, in-memory)
        chunks = self._create_semantic_chunks(content, str(file_path.absolute()))

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
    
    def _create_semantic_chunks(self, content: str, file_path: str) -> List[ParserChunk]:
        """Create semantic chunks from text content.
        
        Chunks are created based on:
        1. Paragraphs (split on double newlines)
        2. Sentences (for long paragraphs)
        3. Character limits (max_chunk_size)
        
        Args:
            content: Text content to chunk
            file_path: Path to the file (for metadata)
            
        Returns:
            List of ParserChunk objects
        """
        if not content.strip():
            # Empty file - return single empty chunk
            return [ParserChunk(
                content="",
                fts_text="",
                content_type="OTHER",
                line_start=1,
                line_end=1,
                metadata={'chunk_index': 0, 'total_chunks': 1, 'chunk_type': 'empty'}
            )]

        # Small prose files (sessions, abstracts) stay one retrieval unit.
        if self.whole_file_max_chars > 0 and len(content) <= self.whole_file_max_chars:
            line_end = max(content.count("\n") + 1, 1)
            chunk = self._create_chunk(content, 1, line_end, "file")
            chunk.metadata["chunk_index"] = 0
            chunk.metadata["total_chunks"] = 1
            return [chunk]
        
        # Split into paragraphs (double newlines)
        paragraphs = self._split_into_paragraphs(content)
        
        # Process paragraphs into chunks
        chunks = []
        current_chunk_text = ""
        current_start_line = 1
        current_line = 1
        
        for para_text, para_start_line, para_end_line in paragraphs:
            # If paragraph is too long, split by sentences
            if len(para_text) > self.max_chunk_size:
                # Flush current chunk if any
                if current_chunk_text:
                    chunks.append(self._create_chunk(
                        current_chunk_text,
                        current_start_line,
                        current_line - 1,
                        'paragraph'
                    ))
                    current_chunk_text = ""
                
                # Split long paragraph into sentences
                sentence_chunks = self._split_long_paragraph(
                    para_text, para_start_line, para_end_line
                )
                chunks.extend(sentence_chunks)
                current_start_line = para_end_line + 1
                current_line = para_end_line + 1
            else:
                # Check if adding this paragraph would exceed max size
                if current_chunk_text and len(current_chunk_text) + len(para_text) + 2 > self.max_chunk_size:
                    # Flush current chunk
                    chunks.append(self._create_chunk(
                        current_chunk_text,
                        current_start_line,
                        current_line - 1,
                        'paragraph'
                    ))
                    
                    # Start new chunk with overlap
                    overlap_text = self._get_overlap_text(current_chunk_text)
                    current_chunk_text = overlap_text + para_text
                    current_start_line = current_line
                else:
                    # Add paragraph to current chunk
                    if current_chunk_text:
                        current_chunk_text += "\n\n" + para_text
                    else:
                        current_chunk_text = para_text
                        current_start_line = para_start_line
                
                current_line = para_end_line + 1
        
        # Flush remaining chunk
        if current_chunk_text:
            chunks.append(self._create_chunk(
                current_chunk_text,
                current_start_line,
                current_line - 1,
                'paragraph'
            ))
        
        # Keep Session/Date on every slice so temporal retrieval still sees it.
        header = session_date_header(content)
        if header:
            chunks = [self._prefix_header(chunk, header) for chunk in chunks]

        # Set chunk indices
        total_chunks = len(chunks)
        for idx, chunk in enumerate(chunks):
            if chunk.metadata is None:
                chunk.metadata = {}
            chunk.metadata['chunk_index'] = idx
            chunk.metadata['total_chunks'] = total_chunks
        
        return chunks

    def _prefix_header(self, chunk: ParserChunk, header: str) -> ParserChunk:
        """Copy the session/date header onto a slice that does not already have it."""
        text = chunk.content or ""
        if text.startswith(header):
            return chunk
        prefixed = header + "\n" + text
        chunk.content = prefixed
        chunk.fts_text = prefixed
        return chunk
    
    def _split_into_paragraphs(self, content: str) -> List[Tuple[str, int, int]]:
        """Split content into paragraphs.
        
        Args:
            content: Text content
            
        Returns:
            List of tuples (paragraph_text, start_line, end_line)
        """
        lines = content.splitlines()
        paragraphs = []
        current_para = []
        para_start_line = 1
        
        for line_num, line in enumerate(lines, start=1):
            if line.strip():
                current_para.append(line)
            else:
                # Empty line - end of paragraph
                if current_para:
                    para_text = "\n".join(current_para)
                    para_end_line = line_num - 1
                    paragraphs.append((para_text, para_start_line, para_end_line))
                    current_para = []
                para_start_line = line_num + 1
        
        # Add final paragraph
        if current_para:
            para_text = "\n".join(current_para)
            para_end_line = len(lines)
            paragraphs.append((para_text, para_start_line, para_end_line))
        
        return paragraphs
    
    def _split_long_paragraph(
        self, text: str, start_line: int, end_line: int
    ) -> List[ParserChunk]:
        """Split a long paragraph into sentence-based chunks.
        
        Args:
            text: Paragraph text
            start_line: Starting line number
            end_line: Ending line number
            
        Returns:
            List of ParserChunk objects
        """
        # Split into sentences using regex
        sentence_pattern = r'(?<=[.!?])\s+'
        sentences = re.split(sentence_pattern, text)
        
        chunks = []
        current_chunk_text = ""
        chunk_start_line = start_line
        
        # Estimate lines per character for line number calculation
        total_lines = end_line - start_line + 1
        lines_per_char = total_lines / len(text) if text else 0
        current_char_pos = 0
        
        for sentence in sentences:
            if not sentence.strip():
                continue
            
            # Check if adding this sentence would exceed max size
            if current_chunk_text and len(current_chunk_text) + len(sentence) + 1 > self.max_chunk_size:
                # Calculate end line for current chunk
                chunk_end_line = start_line + int(current_char_pos * lines_per_char)
                
                # Flush current chunk
                chunks.append(self._create_chunk(
                    current_chunk_text,
                    chunk_start_line,
                    chunk_end_line,
                    'sentence'
                ))
                
                # Start new chunk with overlap
                overlap_text = self._get_overlap_text(current_chunk_text)
                current_chunk_text = overlap_text + sentence
                chunk_start_line = chunk_end_line
            else:
                # Add sentence to current chunk
                if current_chunk_text:
                    current_chunk_text += " " + sentence
                else:
                    current_chunk_text = sentence
            
            current_char_pos += len(sentence) + 1
        
        # Flush remaining chunk
        if current_chunk_text:
            chunks.append(self._create_chunk(
                current_chunk_text,
                chunk_start_line,
                end_line,
                'sentence'
            ))
        
        return chunks
    
    def _get_overlap_text(self, text: str) -> str:
        """Get overlap text from the end of a chunk.
        
        Args:
            text: Text to extract overlap from
            
        Returns:
            Overlap text (last chunk_overlap characters)
        """
        if len(text) <= self.chunk_overlap:
            return text
        
        overlap = text[-self.chunk_overlap:]
        
        # Try to start at a word boundary
        space_idx = overlap.find(' ')
        if space_idx > 0:
            overlap = overlap[space_idx + 1:]
        
        return overlap + " "
    
    def _create_chunk(
        self, text: str, start_line: int, end_line: int, chunk_type: str
    ) -> ParserChunk:
        """Create a ParserChunk from text.
        
        Args:
            text: Chunk text
            start_line: Starting line number
            end_line: Ending line number
            chunk_type: Type of chunk (paragraph, sentence, empty)
            
        Returns:
            ParserChunk object
        """
        return ParserChunk(
            content=text,
            fts_text=text,  # For plain text, FTS text is the same as content
            content_type="OTHER",
            line_start=start_line,
            line_end=end_line,
            metadata={'chunk_type': chunk_type}
        )
    
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
