# SPDX-License-Identifier: GPL-3.0-or-later
"""Документ сувою в пам'яті."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TocEntry:
    level: int
    anchor: str
    title: str


@dataclass
class Link:
    kind: str
    target: str
    anchor: str = ""


@dataclass
class Document:
    path: str
    title: str
    body: str
    updated: str
    mime: str = "text/html"
    facets: list[tuple[str, str]] = field(default_factory=list)
    toc: list[TocEntry] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)

    @property
    def body_bytes(self) -> bytes:
        return self.body.encode("utf-8")
