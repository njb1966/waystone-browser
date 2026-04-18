"""Gemtext parser — converts raw gemtext into a list of typed lines."""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class LineType(Enum):
    TEXT = auto()
    LINK = auto()
    H1 = auto()
    H2 = auto()
    H3 = auto()
    LIST = auto()
    QUOTE = auto()
    PREFORMAT = auto()


@dataclass
class GemLine:
    type: LineType
    text: str
    url: Optional[str] = field(default=None)   # LINK lines only


def parse(text: str) -> list[GemLine]:
    """Parse a gemtext document into a list of GemLine objects."""
    lines: list[GemLine] = []
    in_pre = False

    for raw in text.splitlines():
        # Preformat toggle
        if raw.startswith("```"):
            in_pre = not in_pre
            # Alt text (raw[3:]) intentionally ignored in v1
            continue

        if in_pre:
            lines.append(GemLine(LineType.PREFORMAT, raw))
            continue

        # Link line  =>  URL [optional label]
        if raw.startswith("=>"):
            rest = raw[2:].strip()
            parts = rest.split(None, 1)
            url = parts[0] if parts else ""
            label = parts[1].strip() if len(parts) > 1 else url
            lines.append(GemLine(LineType.LINK, label, url=url))

        # Headings — check longest prefix first
        elif raw.startswith("###"):
            lines.append(GemLine(LineType.H3, raw[3:].strip()))
        elif raw.startswith("##"):
            lines.append(GemLine(LineType.H2, raw[2:].strip()))
        elif raw.startswith("#"):
            lines.append(GemLine(LineType.H1, raw[1:].strip()))

        # Unordered list item
        elif raw.startswith("* "):
            lines.append(GemLine(LineType.LIST, raw[2:].strip()))

        # Blockquote
        elif raw.startswith(">"):
            lines.append(GemLine(LineType.QUOTE, raw[1:].strip()))

        else:
            lines.append(GemLine(LineType.TEXT, raw))

    return lines
