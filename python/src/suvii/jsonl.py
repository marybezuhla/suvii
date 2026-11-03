# SPDX-License-Identifier: GPL-3.0-or-later
"""Вхідні дані для `suvii create`: collection.json і docs.jsonl."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from .model import Document, Link, TocEntry
from .spec import SuviiError

MAX_LINE = 80 * 1024 * 1024


def read_collection(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for k in ("id", "title", "language", "publisher", "fields", "seq", "source_date"):
        if k not in data:
            raise SuviiError("bad_collection_json", f"missing {k}")
    return data


def _doc(obj: dict, line_no: int) -> Document:
    try:
        return Document(
            path=obj["path"],
            title=obj["title"],
            body=obj["body"],
            updated=obj["updated"],
            mime=obj.get("mime", "text/html"),
            facets=[(str(k), str(v)) for k, v in obj.get("facets", [])],
            toc=[TocEntry(int(lv), a, t) for lv, a, t in obj.get("toc", [])],
            links=[Link(*lk) for lk in obj.get("links", [])],
        )
    except (KeyError, TypeError, ValueError) as e:
        raise SuviiError("bad_docs_jsonl", f"line {line_no}") from e


def read_docs(path: str | Path) -> Iterator[Document]:
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if len(line) > MAX_LINE:
                raise SuviiError("bad_docs_jsonl", f"line {i} too long")
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise SuviiError("bad_docs_jsonl", f"line {i}") from e
            yield _doc(obj, i)
