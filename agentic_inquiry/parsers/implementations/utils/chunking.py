"""Line-aligned chunk packing shared by the text and code parsers."""
from __future__ import annotations

from typing import List, Sequence, Tuple


def pack_lines(lines: Sequence[str], first_line: int, budget: int) -> List[Tuple[int, int]]:
    """Partition consecutive lines into ``(start, end)`` spans of at most ``budget`` characters.

    Every line lands in exactly one span and spans never overlap, so a chunk's
    content is always exactly its source lines. A span closes before the line
    that would exceed the budget; when the open span contains a blank line, it
    closes after the last blank line instead, so paragraphs and blocks stay
    whole. A single line longer than the budget forms a span of its own.
    Character counts include one newline per line.
    """
    spans: List[Tuple[int, int]] = []
    start = 0  # index of the open span's first line
    size = 0  # characters in lines[start:index]
    for index, line in enumerate(lines):
        cost = len(line) + 1
        if index > start and size + cost > budget:
            blanks = [i for i in range(start + 1, index - 1) if not lines[i].strip()]
            cut = blanks[-1] + 1 if blanks else index
            spans.append((first_line + start, first_line + cut - 1))
            start = cut
            size = sum(len(lines[i]) + 1 for i in range(start, index))
            if index > start and size + cost > budget:
                spans.append((first_line + start, first_line + index - 1))
                start, size = index, 0
        size += cost
    if start < len(lines):
        spans.append((first_line + start, first_line + len(lines) - 1))
    return spans
