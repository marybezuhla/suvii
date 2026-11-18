# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes what the Kotlin tests need from testdata/*.suvii as plain text, because the Kotlin core
has no SQLite: metadata, (path, doc_hash) pairs and tombstones of each test scroll.

Format, one item per line, fields separated by a tab:
  meta  <key>  <value as base64 of UTF-8>
  doc   <path as base64 of UTF-8>  <doc_hash hex>
  tomb  <path as base64 of UTF-8>

Usage: python scripts/export_for_kotlin.py ../testdata ../kotlin/src/test/resources
"""

from __future__ import annotations

import base64
import sqlite3
import sys
from pathlib import Path


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def export(scroll: Path) -> str:
    conn = sqlite3.connect(f"file:{scroll}?mode=ro", uri=True)
    try:
        lines = [f"meta\t{k}\t{b64(v)}" for k, v in conn.execute("SELECT key, value FROM meta ORDER BY key")]
        lines += [f"doc\t{b64(p)}\t{h.hex()}" for p, h in conn.execute("SELECT path, hash FROM docs ORDER BY path")]
        lines += [f"tomb\t{b64(p)}" for (p,) in conn.execute("SELECT path FROM tombstones ORDER BY path")]
    finally:
        conn.close()
    return "\n".join(lines) + "\n"


def main() -> None:
    source, target = Path(sys.argv[1]), Path(sys.argv[2])
    target.mkdir(parents=True, exist_ok=True)
    for name in ("base-1", "patch-1-2", "base-2"):
        (target / f"{name}.txt").write_text(export(source / f"{name}.suvii"), encoding="utf-8")


if __name__ == "__main__":
    main()
