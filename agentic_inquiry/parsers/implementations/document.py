"""
Document parser using unstructured library with entity extraction.

This module parses documents and extracts structural elements (headings, sections,
tables, figures) as individual entities with hierarchical relationships.

Key approach:
- One chunk per element (no combining)
- Accurate element_type and element_name for each chunk
- Hierarchical relationships via graph (not chunking)
- Context provided through graph traversal
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import logging
import hashlib
from concurrent.futures import ThreadPoolExecutor

from unstructured.partition.auto import partition

from ..models import ParsedDocument, ParserChunk, ParserRelationship
from ...exceptions import DocumentParsingError
from ...models.graph_entity import EntityType


logger = logging.getLogger(__name__)

# Thread-safe document processing: pypdfium2 segfaults and unstructured import
# deadlocks under concurrent thread access. Single worker serializes all parsing.
_doc_executor = ThreadPoolExecutor(max_workers=1)

# Max file size for document parsing (50MB) - larger files crash lxml/pdftext
_MAX_DOC_FILE_SIZE = 50 * 1024 * 1024


# Mapping from Unstructured element types to standardized entity types
# Note: DOCX files use "Heading 1"-"Heading 6" styles (with space) from unstructured
# We support both formats for compatibility across different document sources
UNSTRUCTURED_TO_ENTITY_TYPE = {
    "Title": EntityType.DOC_SECTION.value,
    "Header": EntityType.DOC_SECTION.value,
    # DOCX heading styles without space (legacy format)
    "Heading1": EntityType.DOC_SECTION.value,
    "Heading2": EntityType.DOC_SECTION.value,
    "Heading3": EntityType.DOC_SECTION.value,
    "Heading4": EntityType.DOC_SECTION.value,
    "Heading5": EntityType.DOC_SECTION.value,
    "Heading6": EntityType.DOC_SECTION.value,
    # DOCX heading styles with space (unstructured library output for DOCX)
    "Heading 1": EntityType.DOC_SECTION.value,
    "Heading 2": EntityType.DOC_SECTION.value,
    "Heading 3": EntityType.DOC_SECTION.value,
    "Heading 4": EntityType.DOC_SECTION.value,
    "Heading 5": EntityType.DOC_SECTION.value,
    "Heading 6": EntityType.DOC_SECTION.value,
    "NarrativeText": "section",
    "UncategorizedText": "section",
    "ListItem": "list_item",
    "Table": "table",
    "Image": "figure",
    "Figure": "figure",
    "FigureCaption": "figure",
    "PageBreak": "page",
    "Footer": "section",
    "Address": "section",
    "EmailAddress": "section",
    "Text": "section",  # Generic text elements
}

# Allowed metadata types for LanceDB schema compliance
ALLOWED_METADATA_TYPES = (str, int, float, bool, type(None))

# Font size thresholds for PDF heading detection (relative to body text)
# Headings are detected when font_size >= body_size * threshold
PDF_HEADING_THRESHOLDS = {
    1: 1.8,   # h1: 80% larger than body
    2: 1.5,   # h2: 50% larger than body
    3: 1.3,   # h3: 30% larger than body
    4: 1.15,  # h4: 15% larger than body
}


class PDFElement:
    """
    Lightweight element class matching the unstructured Element interface.

    This allows PDF extraction via pdftext to integrate with the existing
    element processing pipeline that expects unstructured-style elements.
    """

    def __init__(
        self,
        text: str,
        element_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self._text = text
        self._element_type = element_type
        self._metadata = metadata or {}

    @property
    def text(self) -> str:
        return self._text

    @property
    def category(self) -> str:
        """Element category (same as element_type for compatibility)."""
        return self._element_type

    @property
    def metadata(self) -> Dict[str, Any]:
        return self._metadata

    def __str__(self) -> str:
        return self._text


class DocumentParser:
    """
    Document parser that extracts structural elements as individual entities.

    Creates one chunk per document element (heading, section, table, figure, etc.)
    with accurate element_type and element_name. Hierarchical relationships are
    created via ParserRelationship objects for graph-based context retrieval.

    This approach prioritizes precision and entity extraction over chunking for context.
    """

    SUPPORTED_EXTENSIONS = {
        ".pdf",
        ".doc",
        ".docx",
        ".ppt",
        ".pptx",
        ".xls",
        ".xlsx",
        ".rtf",
        ".odt",
        ".odp",
        ".ods",
        ".epub",
        ".html",
        ".htm",
        ".xml",
        ".md",
        ".markdown",
        ".rst",
    }

    def __init__(
        self,
        include_metadata: bool = True,
        multipage_sections: bool = True,
    ):
        """
        Initialize the document parser.

        Args:
            include_metadata: Include element metadata in chunks
            multipage_sections: Allow sections to span multiple pages
        """
        self.include_metadata = include_metadata
        self.multipage_sections = multipage_sections

    async def can_parse(self, path: str) -> bool:
        """Check if this parser can handle the given file."""
        return Path(path).suffix.lower() in self.SUPPORTED_EXTENSIONS

    async def parse(self, path: str, **kwargs) -> ParsedDocument:
        """Parse document and extract individual elements as entities."""
        import asyncio
        from functools import partial

        file_path = Path(path)

        # Skip files that are too large to parse safely
        try:
            file_size = file_path.stat().st_size
            if file_size > _MAX_DOC_FILE_SIZE:
                logger.warning(
                    "Skipping oversized document (%s MB): %s",
                    file_size / (1024 * 1024), file_path,
                )
                return ParsedDocument(
                    chunks=[],
                    relationships=[],
                    metadata={"skipped": True, "reason": "file_too_large"},
                )
        except OSError:
            pass  # Let the actual parsing handle missing files

        try:
            logger.info("Starting document parsing: %s", file_path)

            # Elements can be from unstructured or PDFElement (both provide text, category, metadata)
            elements: List[Any]

            # Use pdftext for PDF files to get font-based heading detection
            if file_path.suffix.lower() == ".pdf":
                logger.debug("Using pdftext for PDF structure extraction: %s", file_path)
                loop = asyncio.get_running_loop()
                elements = await loop.run_in_executor(
                    _doc_executor, self._extract_pdf_with_structure, file_path
                )
            else:
                # Build partition arguments for non-PDF documents
                partition_kwargs: Dict[str, Any] = {
                    "filename": str(file_path),
                    "strategy": "fast",
                    "include_page_breaks": True,
                    "include_metadata": self.include_metadata,
                    "multipage_sections": self.multipage_sections,
                }

                # Only add infer_table_structure for non-markdown files
                if file_path.suffix.lower() not in {".md", ".markdown"}:
                    partition_kwargs["infer_table_structure"] = True

                logger.debug("Partitioning document with strategy: %s", partition_kwargs['strategy'])

                # Execute unstructured library calls in run_in_executor (I/O and CPU-bound)
                # Use functools.partial to pass kwargs to run_in_executor
                loop = asyncio.get_running_loop()
                partition_func = partial(partition, **partition_kwargs)
                elements = await loop.run_in_executor(_doc_executor, partition_func)

            if not elements:
                logger.warning(
                    "No elements extracted from %s. "
                    "Document may be empty or in an unsupported format.",
                    file_path
                )
                return ParsedDocument(
                    doc_id=self._generate_doc_id(path),
                    file_path=path,
                    chunks=[],
                    metadata={"error": "No content extracted from document"}
                )

            logger.debug("Extracted %d raw elements from %s", len(elements), file_path)

            # Extract hierarchical relationships (synchronous - fast, in-memory)
            relationships, heading_hierarchy = self._extract_relationships(elements, file_path)

            # Create one chunk per element with accurate metadata (synchronous - fast, in-memory)
            chunks = self._elements_to_chunks(elements, heading_hierarchy, relationships, file_path)
            
            logger.info(
                "Successfully parsed %s: %d chunks, %d relationships",
                file_path, len(chunks), len(relationships)
            )

            # Extract metadata (synchronous - fast, in-memory)
            metadata = self._extract_metadata(file_path, elements, chunks)

            return ParsedDocument(
                doc_id=self._generate_doc_id(path),
                file_path=path,
                chunks=chunks,
                metadata=metadata,
            )

        except Exception as e:
            logger.warning(
                "Document parsing failed for %s: %s: %s",
                file_path,
                type(e).__name__,
                e,
                exc_info=True
            )
            raise DocumentParsingError(
                f"Document parsing failed for {file_path}: {e}",
                file_path=str(file_path),
                parser_type="document",
                original_error=e
            ) from e

    def _generate_doc_id(self, path: str) -> str:
        """Generate a stable document ID from the file path."""
        return hashlib.md5(path.encode()).hexdigest()

    def _extract_pdf_with_structure(self, file_path: Path) -> List[PDFElement]:
        """
        Extract PDF content with font-based heading detection using pdftext.

        Uses font size analysis to classify text as headings vs body text:
        - Determines body text size as the most common font size
        - Classifies larger text as h1-h4 based on size thresholds
        - Short text lines with larger fonts are likely headings

        Args:
            file_path: Path to the PDF file

        Returns:
            List of PDFElement objects compatible with existing processing
        """
        from collections import Counter
        from pdftext.extraction import dictionary_output  # type: ignore[import-untyped]

        logger.debug("Extracting PDF with pdftext: %s", file_path)

        # Extract structured content from PDF
        pages = dictionary_output(str(file_path), sort=True, keep_chars=False)

        if not pages:
            logger.warning("No pages extracted from PDF: %s", file_path)
            return []

        # Collect all font sizes to determine body text size
        font_sizes: List[float] = []
        for page in pages:
            for block in page.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        font = span.get("font", {})
                        size = font.get("size", 0)
                        if size > 0:
                            font_sizes.append(size)

        if not font_sizes:
            logger.warning("No font sizes found in PDF: %s", file_path)
            return []

        # Filter out tiny fonts (< 5pt) which are often invisible text or artifacts
        # then find body text as the most common remaining font size
        valid_sizes = [s for s in font_sizes if s >= 5.0]
        if not valid_sizes:
            # Fallback if all fonts are tiny - use the largest ones
            valid_sizes = sorted(font_sizes, reverse=True)[:100]

        size_counter = Counter(valid_sizes)
        body_size = size_counter.most_common(1)[0][0]
        logger.debug(
            "PDF body text size: %.1f (from %d valid samples, %d total)",
            body_size, len(valid_sizes), len(font_sizes)
        )

        # Convert PDF structure to elements
        # Process each LINE separately (not blocks) because headings are often
        # on individual lines with distinct font sizes
        elements: List[PDFElement] = []

        for page_idx, page in enumerate(pages):
            page_num = page.get("page", page_idx + 1)

            for block in page.get("blocks", []):
                for line in block.get("lines", []):
                    # Combine all spans in the line to get full text
                    line_text_parts: List[str] = []
                    line_font_sizes: List[float] = []
                    line_font_weights: List[float] = []

                    for span in line.get("spans", []):
                        text = span.get("text", "").strip()
                        if text:
                            line_text_parts.append(text)
                            font = span.get("font", {})
                            size = font.get("size", body_size)
                            weight = font.get("weight", 400)
                            # Skip tiny fonts when calculating average
                            if size >= 5.0:
                                line_font_sizes.append(size)
                                line_font_weights.append(weight)

                    if not line_text_parts:
                        continue

                    line_text = " ".join(line_text_parts)

                    # Determine element type based on font characteristics
                    avg_font_size = (
                        sum(line_font_sizes) / len(line_font_sizes)
                        if line_font_sizes else body_size
                    )
                    avg_font_weight = (
                        sum(line_font_weights) / len(line_font_weights)
                        if line_font_weights else 400
                    )

                    element_type = self._classify_pdf_element(
                        text=line_text,
                        font_size=avg_font_size,
                        font_weight=avg_font_weight,
                        body_size=body_size,
                    )

                    # Create element with metadata
                    metadata = {
                        "page_number": page_num,
                        "font_size": round(avg_font_size, 1),
                        "font_weight": int(avg_font_weight),
                        "coordinates": line.get("bbox", []),
                    }

                    elements.append(PDFElement(
                        text=line_text,
                        element_type=element_type,
                        metadata=metadata,
                    ))

        logger.info(
            "Extracted %d elements from PDF %s (body size: %.1f)",
            len(elements), file_path, body_size
        )

        return elements

    def _classify_pdf_element(
        self,
        text: str,
        font_size: float,
        font_weight: float,
        body_size: float,
    ) -> str:
        """
        Classify a PDF text block as heading or body text.

        Classification logic:
        1. Must be significantly larger than body text
        2. Must be short (headings are typically single lines)
        3. Bold text (weight >= 600) is more likely a heading

        Args:
            text: The text content
            font_size: Average font size of the block
            font_weight: Average font weight (400=normal, 700=bold)
            body_size: Baseline body text size

        Returns:
            Element type string (Title, Header, or NarrativeText)
        """
        # Calculate size ratio
        size_ratio = font_size / body_size if body_size > 0 else 1.0

        # Headings are typically short (< 100 chars, no multiple paragraphs)
        is_short = len(text) < 100 and "\n" not in text
        is_bold = font_weight >= 600

        # Check heading thresholds (h1 to h4)
        for level, threshold in sorted(PDF_HEADING_THRESHOLDS.items()):
            if size_ratio >= threshold and is_short:
                # Map heading level to element type
                if level == 1:
                    return "Title"
                else:
                    return "Header"

        # Check for bold headings that might not be larger
        if is_bold and is_short and size_ratio >= 1.0:
            return "Header"

        return "NarrativeText"

    def _process_heading_element(
        self,
        element: Any,
        index: int,
        heading_stack: List[Dict[str, Any]],
        relationships: List[ParserRelationship],
        heading_hierarchy: Dict[int, str],
        file_path: Path
    ) -> None:
        """Process a heading element and update relationships.
        
        Extracts heading information, manages the heading stack, and creates
        hierarchical relationships (contains and follows) between headings.
        
        Args:
            element: The heading element to process
            index: Index of the element in the document
            heading_stack: Stack tracking current heading hierarchy
            relationships: List to append new relationships to
            heading_hierarchy: Dict mapping element indices to parent heading names
            file_path: Path to the document being processed
        """
        element_name = self._get_element_name(element)
        if not element_name:
            logger.debug("Skipping heading at index %d with no name", index)
            return
            
        # Determine heading level
        level = self._get_heading_level(element)
        logger.debug("Processing heading '%s' at level %d", element_name, level)
        
        # Create "follows" relationship with previous sibling BEFORE popping
        # Must do this before popping to find siblings at the same level
        prev_sibling = self._find_previous_sibling(heading_stack, level)
        if prev_sibling:
            logger.debug(
                "Creating 'follows' relationship: '%s' -> '%s'",
                prev_sibling['name'], element_name
            )
            relationships.append(
                ParserRelationship(
                    source_type=EntityType.DOC_SECTION.value,
                    source_name=prev_sibling["name"],
                    target_type=EntityType.DOC_SECTION.value,
                    target_name=element_name,
                    type="follows",
                    metadata={}
                )
            )
        
        # Pop stack until we find the parent level
        while heading_stack and int(heading_stack[-1]["level"]) >= level:
            popped = heading_stack.pop()
            logger.debug("Popped heading '%s' from stack", popped['name'])
        
        # Create "contains" relationship to parent
        if heading_stack:
            parent = heading_stack[-1]
            parent_name = str(parent["name"])
            logger.debug(
                "Creating 'contains' relationship: '%s' -> '%s'",
                parent_name, element_name
            )
            relationships.append(
                ParserRelationship(
                    source_type=EntityType.DOC_SECTION.value,
                    source_name=parent_name,
                    target_type=EntityType.DOC_SECTION.value,
                    target_name=element_name,
                    type="contains",
                    metadata={"hierarchy_level": level}
                )
            )
            # Set parent for this heading
            heading_hierarchy[index] = parent_name
        else:
            # Top-level heading - parent is document
            logger.debug(
                "Creating top-level 'contains' relationship: '%s' -> '%s'",
                file_path.name, element_name
            )
            relationships.append(
                ParserRelationship(
                    source_type="document",
                    source_name=file_path.name,
                    target_type=EntityType.DOC_SECTION.value,
                    target_name=element_name,
                    type="contains",
                    metadata={"hierarchy_level": level}
                )
            )
        
        # Add to stack
        heading_stack.append({
            "name": element_name,
            "level": level,
            "index": index
        })

    def _process_non_heading_element(
        self,
        index: int,
        heading_stack: List[Dict[str, Any]],
        heading_hierarchy: Dict[int, str],
        mapped_type: str
    ) -> None:
        """Process a non-heading element and update hierarchy.
        
        Assigns the current heading as the parent for non-heading elements
        (paragraphs, lists, tables, etc.).
        
        Args:
            index: Index of the element in the document
            heading_stack: Stack tracking current heading hierarchy
            heading_hierarchy: Dict mapping element indices to parent heading names
            mapped_type: The mapped element type (for logging)
        """
        # Non-heading elements get parent from current heading
        if heading_stack:
            heading_hierarchy[index] = str(heading_stack[-1]["name"])
            logger.debug(
                "Assigning parent '%s' to %s at index %d",
                heading_stack[-1]['name'], mapped_type, index
            )

    def _extract_relationships(
        self, 
        elements: List[Any], 
        file_path: Path
    ) -> Tuple[List[ParserRelationship], Dict[int, str]]:
        """Extract hierarchical relationships and heading hierarchy.
        
        Args:
            elements: List of unstructured elements
            file_path: Path to the document
            
        Returns:
            Tuple of (relationships, heading_hierarchy) where:
            - relationships: List of ParserRelationship objects
            - heading_hierarchy: Dict mapping element index to parent heading name
        """
        # Implements subtasks 1.1, 1.4, 1.5, 1.6
        try:
            logger.debug("Starting relationship extraction for %s", file_path)
            
            relationships: List[ParserRelationship] = []
            heading_stack: List[Dict[str, Any]] = []  # Track heading hierarchy: [{name, level, index}]
            heading_hierarchy: Dict[int, str] = {}  # Map element index to parent heading name
            has_headings = False

            # Count element types for logging
            element_type_counts: Dict[str, int] = {}
            
            for i, element in enumerate(elements):
                try:
                    element_type = self._get_element_type(element)
                    mapped_type = self._map_element_type(element_type)
                    
                    # Track element types
                    element_type_counts[mapped_type] = element_type_counts.get(mapped_type, 0) + 1
                    
                    # Delegate processing based on element type
                    if mapped_type == EntityType.DOC_SECTION.value:
                        has_headings = True
                        self._process_heading_element(
                            element, i, heading_stack, relationships, heading_hierarchy, file_path
                        )
                    else:
                        self._process_non_heading_element(
                            i, heading_stack, heading_hierarchy, mapped_type
                        )
                
                except Exception as e:
                    logger.warning(
                        "Error processing element %d in %s: %s. Skipping element.",
                        i, file_path, e,
                        exc_info=True
                    )
                    continue
            
            # Log entity counts
            logger.info(
                "Extracted entities from %s: %s",
                file_path,
                ', '.join(f'{count} {etype}(s)' for etype, count in sorted(element_type_counts.items()))
            )
            
            # Log relationship counts
            contains_count = sum(1 for r in relationships if r.type == "contains")
            follows_count = sum(1 for r in relationships if r.type == "follows")
            logger.info(
                "Created %d relationships for %s: %d contains, %d follows",
                len(relationships), file_path, contains_count, follows_count
            )
            
            # Log warning if no structural elements found
            if not has_headings:
                logger.warning(
                    "No heading elements found in %s. "
                    "Document will be processed as flat structure with element_type='section'.",
                    file_path
                )
            
            return relationships, heading_hierarchy
            
        except Exception as e:
            logger.error(
                "Failed to extract relationships from %s: %s. "
                "Returning empty relationships.",
                file_path, e,
                exc_info=True
            )
            # Return empty relationships to allow document processing to continue
            return [], {}
    
    def _get_heading_level(self, element: Any) -> int:
        """Determine heading level from element.

        Args:
            element: Unstructured element

        Returns:
            Integer level (1-6)
        """
        # Implements subtask 1.2
        try:
            element_type = self._get_element_type(element)

            # Handle "Heading X" format (with or without space) from DOCX
            # Supports: "Heading1", "Heading 1", "Heading2", "Heading 2", etc.
            if element_type.startswith("Heading"):
                try:
                    # Extract the number part: "Heading 1" -> "1", "Heading2" -> "2"
                    level_str = element_type.replace("Heading", "").strip()
                    level = int(level_str)
                    return max(1, min(level, 6))  # Clamp to 1-6
                except ValueError:
                    return 3  # Default if parsing fails

            # Unstructured library element types
            if element_type == "Title":
                # Check if category_depth is available (markdown)
                if hasattr(element, "metadata") and element.metadata:
                    if hasattr(element.metadata, "category_depth"):
                        depth = element.metadata.category_depth
                        if depth is not None:
                            # category_depth: 0=H1, 1=H2, etc.
                            return min(depth + 1, 6)
                return 1  # Default Title to H1
            elif element_type == "Header":
                # Check if category_depth is available
                if hasattr(element, "metadata") and element.metadata:
                    if hasattr(element.metadata, "category_depth"):
                        depth = element.metadata.category_depth
                        if depth is not None:
                            return min(depth + 1, 6)
                return 2  # Default Header to H2

            return 3  # Default for other types
        except Exception as e:
            logger.debug("Error determining heading level: %s. Using default level 2.", e)
            return 2

    def _get_element_name(self, element: Any) -> str:
        """Extract element name for all element types.
        
        Args:
            element: Unstructured element
            
        Returns:
            Element name string (empty string if no name available)
        """
        # Implements subtask 1.3
        try:
            element_type = self._get_element_type(element)
            text = self._get_element_text(element)
            
            if not text:
                return ""
            
            # For headings: use the heading text
            if element_type in ["Title", "Header"]:
                name = text.strip()
            # For tables: try to extract title or caption
            elif element_type == "Table":
                lines = text.split("\n")
                name = lines[0].strip() if lines else text.strip()
            # For figures: extract caption or alt text
            elif element_type in ["Image", "Figure", "FigureCaption"]:
                name = text.strip()
            # For lists: extract first few words
            elif element_type == "ListItem":
                name = text.strip()[:50]
            # For sections: extract first sentence or paragraph start
            else:
                sentences = text.split(".")
                if sentences:
                    name = sentences[0].strip()
                else:
                    name = text.strip()[:100]
            
            # Clean and truncate to 200 characters
            if len(name) > 200:
                name = name[:200] + "..."
            
            return name
        except Exception as e:
            logger.debug("Error extracting element name: %s. Returning empty string.", e)
            return ""
    
    def _find_previous_sibling(
        self, 
        heading_stack: List[Dict], 
        level: int
    ) -> Optional[Dict]:
        """Find the previous heading at the same level.
        
        Args:
            heading_stack: Stack of heading dictionaries
            level: Level to search for
            
        Returns:
            Previous sibling heading dict or None
        """
        # Used in subtask 1.6
        # Search backwards through stack for same level
        for i in range(len(heading_stack) - 1, -1, -1):
            if heading_stack[i]["level"] == level:
                return heading_stack[i]
        return None
    
    def _map_element_type(self, element_type: str) -> str:
        """Map Unstructured element type to standardized entity type.
        
        Args:
            element_type: Unstructured element type name
            
        Returns:
            Standardized entity type
        """
        # Implements subtask 1.7
        return UNSTRUCTURED_TO_ENTITY_TYPE.get(element_type, "section")

    def _elements_to_chunks(
        self,
        elements: List[Any],
        heading_hierarchy: Dict[int, str],
        relationships: List[ParserRelationship],
        file_path: Path
    ) -> List[ParserChunk]:
        """Convert unstructured elements to ParserChunk objects.

        Creates one chunk per element with accurate element_type, element_name,
        and parent_id set from the heading hierarchy. Also creates a file chunk
        to hold document-level relationships (contains relationships to top-level headings).

        Args:
            elements: List of unstructured elements
            heading_hierarchy: Dict mapping element index to parent heading name
            relationships: List of relationships to attach to heading chunks
            file_path: Path to the document file

        Returns:
            List of ParserChunk objects with element fields populated
        """
        # Implements subtask 1.8
        try:
            logger.debug("Converting %d elements to chunks", len(elements))

            chunks: List[ParserChunk] = []
            skipped_count = 0

            # Group relationships by both source and target name for bidirectional lookup
            rels_by_source: Dict[str, List[ParserRelationship]] = {}
            rels_by_target: Dict[str, List[ParserRelationship]] = {}
            for rel in relationships:
                # Index by source (for outgoing relationships like "contains")
                source = rel.source_name
                if source not in rels_by_source:
                    rels_by_source[source] = []
                rels_by_source[source].append(rel)

                # Index by target (for incoming relationships)
                target = rel.target_name
                if target not in rels_by_target:
                    rels_by_target[target] = []
                rels_by_target[target].append(rel)
            
            for i, element in enumerate(elements):
                try:
                    text = self._get_element_text(element)
                    if not text:
                        skipped_count += 1
                        continue
                    
                    # Get element type and map to standard type
                    raw_element_type = self._get_element_type(element)
                    mapped_element_type = self._map_element_type(raw_element_type)
                    
                    # Get element name
                    element_name = self._get_element_name(element)
                    
                    # Get parent_id from heading_hierarchy
                    parent_id = heading_hierarchy.get(i, "")
                    
                    # Get relationships for this element (only outgoing)
                    # Note: Incoming relationships are NOT attached here - the query layer
                    # handles bidirectional traversal via the graph_relationships table
                    element_relationships = []
                    if element_name:
                        # Get relationships where this element is the source (outgoing)
                        element_relationships.extend(rels_by_source.get(element_name, []))
                    
                    # Extract other metadata
                    metadata = self._extract_element_metadata(element)
                    
                    # Generate FTS text for prose content
                    fts_text = self._generate_fts_text(text)
                    
                    # Extract top-level fields from metadata
                    page_number = metadata.pop("page_number", -1)
                    content_type = metadata.pop("content_type", "PROSE")
                    language = metadata.pop("language", "")
                    
                    chunks.append(
                        ParserChunk(
                            content=text,
                            fts_text=fts_text,
                            content_type=content_type,
                            language=language,
                            page_number=page_number,
                            line_start=-1,
                            line_end=-1,
                            element_type=mapped_element_type,
                            element_name=element_name,
                            parent_id=parent_id,
                            relationships=element_relationships,
                            metadata=metadata,
                        )
                    )
                
                except Exception as e:
                    logger.warning(
                        "Error converting element %d to chunk: %s. Skipping element.",
                        i,
                        e,
                        exc_info=True
                    )
                    skipped_count += 1
                    continue
            
            if skipped_count > 0:
                logger.debug("Skipped %d elements (empty or failed to convert)", skipped_count)

            # Create a file chunk to hold document-level relationships
            # This ensures "contains" relationships from the document to top-level headings
            # are attached to a chunk and make it to the graph_relationships table
            file_name = file_path.name
            file_relationships = rels_by_source.get(file_name, [])
            if file_relationships:
                file_chunk = ParserChunk(
                    content=f"Document: {file_name}",
                    fts_text=file_name,
                    content_type="PROSE",
                    language="",
                    page_number=-1,
                    line_start=-1,
                    line_end=-1,
                    element_type="file",
                    element_name=file_name,
                    parent_id="",
                    relationships=file_relationships,
                    metadata={},
                )
                # Insert at beginning so file chunk is processed first
                chunks.insert(0, file_chunk)
                logger.debug(
                    "Created file chunk for %s with %d document-level relationships",
                    file_name, len(file_relationships)
                )

            logger.debug("Successfully converted %d elements to chunks", len(chunks))
            return chunks
            
        except Exception as e:
            logger.error("Failed to convert elements to chunks: %s", e, exc_info=True)
            # Return empty list to allow parsing to continue
            return []

    def _get_element_text(self, element: Any) -> str:
        """Extract text from an unstructured element.
        
        Args:
            element: Unstructured element object
            
        Returns:
            Text content of the element, or empty string if no text available
        """
        if hasattr(element, "text"):
            return element.text
        elif hasattr(element, "__str__"):
            return str(element)
        return ""

    def _get_element_type(self, element: Any) -> str:
        """Get the type of an element.

        For unstructured elements, the class name is the type (e.g., Title, NarrativeText).
        For PDFElement, we use the category property which stores the element type.

        Args:
            element: Unstructured element object or PDFElement

        Returns:
            Element type name (e.g., "Title", "NarrativeText") or "Unknown"
        """
        # PDFElement and similar classes use category property for element type
        if hasattr(element, "category"):
            return element.category
        # Unstructured elements use class name as type
        if hasattr(element, "__class__"):
            return element.__class__.__name__
        return "Unknown"

    def _validate_metadata_types(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Filter metadata to only include allowed types.
        
        LanceDB has strict schema constraints and only supports simple types
        (str, int, float, bool, None) in metadata fields. Complex types like
        lists, dicts, and custom objects must be filtered out.
        
        Args:
            metadata: Raw metadata dictionary that may contain complex types
            
        Returns:
            Filtered metadata dictionary containing only allowed types
            
        Side Effects:
            Logs debug messages for any filtered fields
        """
        validated = {}
        
        for field, value in metadata.items():
            if isinstance(value, ALLOWED_METADATA_TYPES):
                validated[field] = value
            else:
                logger.debug(
                    "Skipping metadata field '%s' with unsupported type %s",
                    field,
                    type(value).__name__
                )
        
        return validated

    def _extract_element_metadata(self, element: Any) -> Dict[str, Any]:
        """Extract metadata from an element.

        Handles both unstructured elements (metadata as object with attributes)
        and PDFElement (metadata as dict).

        Extracts metadata from the element and validates that all values
        are simple types compatible with LanceDB schema constraints.

        Args:
            element: Unstructured element object or PDFElement

        Returns:
            Dictionary of metadata with only simple types (str, int, float, bool, None)
        """
        metadata: Dict[str, Any] = {}

        try:
            if hasattr(element, "metadata") and element.metadata:
                elem_metadata = element.metadata

                # Handle PDFElement (dict-based metadata)
                if isinstance(elem_metadata, dict):
                    for field in ["page_number", "font_size", "font_weight"]:
                        if field in elem_metadata and elem_metadata[field] is not None:
                            metadata[field] = elem_metadata[field]
                    # Store coordinates as string for LanceDB compatibility
                    if "coordinates" in elem_metadata and elem_metadata["coordinates"]:
                        coords = elem_metadata["coordinates"]
                        if isinstance(coords, list) and len(coords) == 4:
                            metadata["bbox"] = ",".join(str(round(c, 1)) for c in coords)
                else:
                    # Handle unstructured elements (object with attributes)
                    for field in ["page_number", "filename", "section", "type"]:
                        try:
                            if hasattr(elem_metadata, field):
                                value = getattr(elem_metadata, field)
                                if value is not None:
                                    metadata[field] = value
                        except Exception as e:
                            logger.debug("Error extracting metadata field '%s': %s", field, e)
                            continue

            # Set content type
            metadata["content_type"] = "PROSE"

        except Exception as e:
            logger.debug("Error extracting element metadata: %s", e)
            metadata["content_type"] = "PROSE"

        # Validate metadata types before returning
        return self._validate_metadata_types(metadata)

    def _extract_metadata(
        self, 
        file_path: Path, 
        elements: List[Any], 
        chunks: List[ParserChunk]
    ) -> Dict[str, Any]:
        """Build document-level metadata.
        
        Args:
            file_path: Path to the document file
            elements: List of unstructured elements
            chunks: List of ParserChunk objects created from elements
            
        Returns:
            Dictionary containing document-level metadata including element counts,
            chunk statistics, and parser information
        """
        try:
            # Count element types
            element_types: Dict[str, int] = {}
            for element in elements:
                try:
                    elem_type = self._get_element_type(element)
                    element_types[elem_type] = element_types.get(elem_type, 0) + 1
                except Exception as e:
                    logger.debug("Error getting element type for metadata: %s", e)
                    continue

            return {
                "type": "document_entity_extraction",
                "element_count": len(elements),
                "chunk_count": len(chunks),
                "element_types": element_types,
                "avg_chunk_size": sum(len(c.content or "") for c in chunks) // len(chunks) if chunks else 0,
                "parser": "document",
                "approach": "individual_elements",
            }
        except Exception as e:
            logger.warning("Error extracting document metadata: %s", e, exc_info=True)
            return {
                "type": "document_entity_extraction",
                "parser": "document",
                "error": str(e),
            }

    def _generate_fts_text(self, text: str) -> str:
        """Generate FTS-optimized text for prose content."""
        if not text:
            return ""
        
        # Basic cleaning: normalize whitespace
        cleaned = " ".join(text.split())
        
        return cleaned
