"""Segmentación de texto en fragmentos (chunks) conservando ubicación."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .extractors import Segment, _detect_section


@dataclass
class Chunk:
    seq: int
    text: str
    page: int | None
    section: str | None
    location: str | None


def chunk_segments(segments: list[Segment], size: int = 1200, overlap: int = 150) -> list[Chunk]:
    chunks: list[Chunk] = []
    seq = 0
    for seg in segments:
        text = re.sub(r"[ \t]+", " ", seg.text).strip()
        if not text:
            continue
        section = seg.section
        paragraphs = [p for p in re.split(r"\n+", text) if p.strip()]
        buf = ""
        buf_section = section
        for para in paragraphs:
            sec = _detect_section(para)
            if sec and buf and len(buf) > size * 0.3:
                chunks.append(Chunk(seq, buf.strip(), seg.page, buf_section, seg.location))
                seq += 1
                buf = ""
            if sec:
                section = sec
                if not buf:
                    buf_section = sec
            if len(buf) + len(para) + 1 > size and buf:
                chunks.append(Chunk(seq, buf.strip(), seg.page, buf_section, seg.location))
                seq += 1
                tail = buf[-overlap:] if overlap else ""
                # empezar en un límite de palabra
                tail = tail[tail.find(" ") + 1:] if " " in tail else tail
                buf = tail + "\n" if tail else ""
                buf_section = section
            while len(para) > size:  # párrafos muy largos
                cut = para.rfind(" ", 0, size)
                cut = cut if cut > size // 2 else size
                chunks.append(Chunk(seq, (buf + para[:cut]).strip(), seg.page, section, seg.location))
                seq += 1
                buf = ""
                para = para[max(cut - overlap, 0):]
            buf += para + "\n"
        if buf.strip():
            chunks.append(Chunk(seq, buf.strip(), seg.page, buf_section, seg.location))
            seq += 1
    return chunks
