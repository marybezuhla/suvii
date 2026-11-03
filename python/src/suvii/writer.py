# SPDX-License-Identifier: GPL-3.0-or-later
"""Створення основи сувою."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from . import _zstd, hashing, keys, spec
from .html import body_to_text, check_html
from .model import Document
from .spec import SuviiError

RAW_CHUNK_TARGET = 512 * spec.KIB
DEFAULT_LEVEL = 19


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _split_point(data: bytes, start: int, limit: int) -> int:
    """Кінець частини: бажано після '>' чи '\\n', ніколи посеред символу UTF-8."""
    end = start + limit
    if end >= len(data):
        return len(data)
    window_start = max(start + 1, end - 64 * spec.KIB)
    for marker in (b">", b"\n"):
        i = data.rfind(marker, window_start, end)
        if i != -1:
            return i + 1
    while end > start + 1 and (data[end] & 0xC0) == 0x80:
        end -= 1
    return end


def compress_body(data: bytes, level: int, dictionary: bytes | None) -> list[bytes]:
    frames: list[bytes] = []

    def push(piece: bytes) -> None:
        frame = _zstd.compress(piece, level, dictionary)
        if len(frame) <= spec.MAX_CHUNK_COMPRESSED:
            frames.append(frame)
            return
        mid = _split_point(piece, 0, len(piece) // 2)
        if mid <= 0 or mid >= len(piece):
            raise SuviiError("incompressible_chunk")
        push(piece[:mid])
        push(piece[mid:])

    pos = 0
    while pos < len(data):
        end = _split_point(data, pos, RAW_CHUNK_TARGET)
        push(data[pos:end])
        pos = end
    return frames


def validate_document(doc: Document, fields: dict) -> None:
    spec.check_path(doc.path)
    spec.check_text(doc.title, spec.MAX_TITLE, "title")
    if doc.mime not in spec.MIME_TYPES:
        raise SuviiError("bad_mime", doc.mime)
    spec.check_datetime(doc.updated, "updated")
    body = doc.body_bytes
    if len(body) > spec.MAX_DOC:
        raise SuviiError("doc_too_large", doc.path)
    spec.check_nfc(doc.body, f"body of {doc.path}")
    for name, items in (("facets", doc.facets), ("toc", doc.toc), ("links", doc.links)):
        if len(items) > spec.MAX_ITEMS_PER_DOC:
            raise SuviiError("too_many", f"{name} in {doc.path}")
    seen = set()
    multi_used: dict[str, int] = {}
    for k, v in doc.facets:
        spec.check_text(k, spec.MAX_SHORT, "facet key")
        spec.check_text(v, spec.MAX_SHORT, "facet value", allow_empty=True)
        spec.check_facet_value(fields, k, v)
        if (k, v) in seen:
            raise SuviiError("duplicate_facet", f"{k}={v}")
        seen.add((k, v))
        multi_used[k] = multi_used.get(k, 0) + 1
        if multi_used[k] > 1 and not fields[k].get("multi"):
            raise SuviiError("facet_not_multi", k)
    ids: set[str] = check_html(doc.body) if doc.mime == "text/html" else set()
    for t in doc.toc:
        if not isinstance(t.level, int) or not 1 <= t.level <= 32:
            raise SuviiError("bad_toc_level", doc.path)
        spec.check_text(t.anchor, spec.MAX_SHORT, "toc anchor")
        spec.check_text(t.title, spec.MAX_TOC_TITLE, "toc title")
        if doc.mime == "text/html" and t.anchor not in ids:
            raise SuviiError("toc_anchor_missing", f"{doc.path}#{t.anchor}")
    seen_links = set()
    for lk in doc.links:
        spec.check_text(lk.kind, spec.MAX_SHORT, "link kind")
        spec.check_path(lk.target)
        spec.check_text(lk.anchor, spec.MAX_SHORT, "link anchor", allow_empty=True)
        key = (lk.kind, lk.target, lk.anchor)
        if key in seen_links:
            raise SuviiError("duplicate_link", str(key))
        seen_links.add(key)


def create_schema(conn: sqlite3.Connection, with_fts: bool) -> None:
    conn.execute("PRAGMA page_size = 4096")
    conn.execute(f"PRAGMA application_id = {spec.APPLICATION_ID}")
    conn.execute(f"PRAGMA user_version = {spec.MAJOR_VERSION}")
    conn.executescript(spec.SCHEMA)
    if with_fts:
        conn.execute(spec.FTS_SCHEMA)


def insert_document(
    conn: sqlite3.Connection,
    doc: Document,
    frames: list[bytes],
    dict_id: int | None,
    dhash: bytes,
    with_fts: bool,
) -> int:
    cur = conn.execute(
        "INSERT INTO docs(path, title, mime, size, updated, hash) VALUES (?,?,?,?,?,?)",
        (doc.path, doc.title, doc.mime, len(doc.body_bytes), doc.updated, dhash),
    )
    doc_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO chunks(doc_id, n, dict_id, data) VALUES (?,?,?,?)",
        [(doc_id, n, dict_id, f) for n, f in enumerate(frames)],
    )
    conn.executemany("INSERT INTO facets(doc_id, key, value) VALUES (?,?,?)", [(doc_id, k, v) for k, v in doc.facets])
    conn.executemany(
        "INSERT INTO toc(doc_id, ord, level, anchor, title) VALUES (?,?,?,?,?)",
        [(doc_id, i, t.level, t.anchor, t.title) for i, t in enumerate(doc.toc)],
    )
    conn.executemany(
        "INSERT INTO links(doc_id, kind, target, anchor) VALUES (?,?,?,?)",
        [(doc_id, lk.kind, lk.target, lk.anchor) for lk in doc.links],
    )
    if with_fts:
        conn.execute(
            "INSERT INTO fts(rowid, title, body) VALUES (?,?,?)",
            (doc_id, doc.title, body_to_text(doc.mime, doc.body)),
        )
    return doc_id


def finalize_file(conn: sqlite3.Connection) -> None:
    conn.commit()
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.execute("VACUUM")
    conn.close()


class Writer:
    """Пише нову основу. Використання: `with Writer(...) as w: w.add(doc); ...; w.finish(key)`."""

    def __init__(
        self,
        path: str | os.PathLike,
        *,
        collection_id: str,
        title: str,
        language: str,
        publisher: str,
        fields: dict,
        seq: int,
        source_date: str,
        created: str | None = None,
        extra_meta: dict[str, str] | None = None,
        level: int = DEFAULT_LEVEL,
        dictionary: bytes | None = None,
        fts: bool = True,
    ) -> None:
        self.path = Path(path)
        if self.path.exists():
            raise SuviiError("file_exists", str(self.path))
        self.cid_bytes = spec.check_uuid(collection_id)
        if not 1 <= seq <= spec.MAX_SEQ:
            raise SuviiError("bad_seq")
        spec.check_date(source_date, "state.source_date")
        self.fields = spec.check_fields(fields)
        self.level = level
        self.dictionary = dictionary
        self.fts = fts
        self.seq = seq
        if dictionary is not None and len(dictionary) > spec.MAX_DICT:
            raise SuviiError("dict_too_large")
        self.meta: dict[str, str] = {
            "suvii.format": spec.FORMAT_VERSION,
            "suvii.kind": "base",
            "collection.id": collection_id,
            "collection.title": title,
            "collection.language": language,
            "collection.publisher": publisher,
            "collection.fields": json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            "state.seq": str(seq),
            "state.created": created or utc_now(),
            "state.source_date": source_date,
            "sign.alg": "ed25519",
        }
        for k, v in (extra_meta or {}).items():
            if k.startswith(("sign.", "patch.", "suvii.", "state.")):
                raise SuviiError("reserved_meta_key", k)
            self.meta[k] = v
        for k, v in self.meta.items():
            spec.check_text(k, spec.MAX_SHORT, "meta key")
            spec.check_text(v, spec.MAX_ICON if k == "collection.icon" else spec.MAX_META_VALUE, f"meta {k}")
        spec.check_datetime(self.meta["state.created"], "state.created")
        self.tmp = self.path.with_name(self.path.name + ".part")
        if self.tmp.exists():
            self.tmp.unlink()
        self.conn = sqlite3.connect(self.tmp, isolation_level=None)
        self.conn.execute("PRAGMA journal_mode = OFF")
        self.conn.execute("PRAGMA synchronous = OFF")
        create_schema(self.conn, fts)
        self.conn.execute("BEGIN")
        self.dict_id: int | None = None
        if dictionary:
            self.dict_id = self.conn.execute("INSERT INTO dicts(data) VALUES (?)", (dictionary,)).lastrowid
        self.count = 0
        self.closed = False

    def __enter__(self) -> "Writer":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self.closed:
            self.abort()

    def add(self, doc: Document) -> None:
        validate_document(doc, self.fields)
        if self.count >= spec.MAX_DOCS:
            raise SuviiError("too_many_docs")
        frames = compress_body(doc.body_bytes, self.level, self.dictionary)
        try:
            insert_document(self.conn, doc, frames, self.dict_id, hashing.doc_hash(doc), self.fts)
        except sqlite3.IntegrityError as e:
            raise SuviiError("duplicate_path", doc.path) from e
        self.count += 1

    def finish(self, key: Ed25519PrivateKey) -> bytes:
        rows = self.conn.execute("SELECT path, hash FROM docs ORDER BY path").fetchall()
        root = hashing.state_root(self.cid_bytes, self.seq, rows)
        self.meta["sign.key"] = keys.public_text(key)
        self.meta["sign.sig"] = keys.sign(key, hashing.base_message(self.meta, root))
        self.conn.executemany("INSERT INTO meta(key, value) VALUES (?,?)", sorted(self.meta.items()))
        self.conn.execute("COMMIT")
        finalize_file(self.conn)
        os.replace(self.tmp, self.path)
        self.closed = True
        return root

    def abort(self) -> None:
        try:
            self.conn.close()
        finally:
            self.tmp.unlink(missing_ok=True)
            self.closed = True
