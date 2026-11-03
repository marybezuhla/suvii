# SPDX-License-Identifier: GPL-3.0-or-later
"""Безпечне відкриття й читання сувою (SPEC.md, розділи 9–11)."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import struct
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from . import _zstd, hashing, keys, spec
from .html import check_html
from .model import Document, Link, TocEntry
from .spec import SuviiError

FTS_SHADOW = {"fts_data", "fts_idx", "fts_content", "fts_docsize", "fts_config"}
_FTS_SQL = re.compile(r"^CREATE VIRTUAL TABLE\s+\"?fts\"?\s+USING\s+fts5\s*\(", re.IGNORECASE)


@dataclass
class DocInfo:
    path: str
    title: str
    mime: str
    size: int
    updated: str


def read_header(path: str | os.PathLike) -> tuple[int, int]:
    """Повертає (application_id, user_version), не відкриваючи базу SQLite."""
    with open(path, "rb") as f:
        head = f.read(100)
    if len(head) < 100 or not head.startswith(b"SQLite format 3\x00"):
        raise SuviiError("not_sqlite")
    user_version = struct.unpack(">I", head[60:64])[0]
    app_id = struct.unpack(">I", head[68:72])[0]
    return app_id, user_version


def _blen(col: str) -> str:
    return f"length(CAST({col} AS BLOB))"


class Scroll:
    """Відкритий сувій. Створюється через `open_scroll`."""

    def __init__(self, path: Path, conn: sqlite3.Connection, meta: dict[str, str], trusted_by: str) -> None:
        self.path = path
        self.conn = conn
        self.meta = meta
        self.trusted_by = trusted_by  # 'trusted' | 'embedded' | 'unverified'
        self.kind = meta["suvii.kind"]
        self.seq = int(meta["state.seq"])
        self.collection_id = meta["collection.id"]
        self.cid_bytes = spec.check_uuid(self.collection_id)
        self.fields = json.loads(meta["collection.fields"])
        self.has_fts = bool(conn.execute("SELECT 1 FROM sqlite_schema WHERE name='fts'").fetchone())
        self._dicts: dict[int, bytes] = {}

    # ----- життєвий цикл -----
    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Scroll":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ----- читання -----
    def count(self) -> int:
        return self.conn.execute("SELECT count(*) FROM docs").fetchone()[0]

    def infos(self) -> Iterator[DocInfo]:
        for row in self.conn.execute("SELECT path, title, mime, size, updated FROM docs ORDER BY path"):
            yield DocInfo(*row)

    def path_hashes(self) -> list[tuple[str, bytes]]:
        return self.conn.execute("SELECT path, hash FROM docs ORDER BY path").fetchall()

    def tombstones(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT path FROM tombstones ORDER BY path")]

    def _dict(self, dict_id: int | None) -> bytes | None:
        if dict_id is None:
            return None
        if dict_id not in self._dicts:
            row = self.conn.execute("SELECT data FROM dicts WHERE id=?", (dict_id,)).fetchone()
            if row is None:
                raise SuviiError("corrupt", "missing dictionary")
            self._dicts[dict_id] = row[0]
        return self._dicts[dict_id]

    def _doc_id(self, path: str) -> tuple[int, str, str, int, str, bytes]:
        row = self.conn.execute("SELECT id, title, mime, size, updated, hash FROM docs WHERE path=?", (path,)).fetchone()
        if row is None:
            raise SuviiError("not_found", path)
        return row

    def raw_body(self, doc_id: int, size: int) -> bytes:
        if size < 0 or size > spec.MAX_DOC:
            raise SuviiError("corrupt", "size")
        out = bytearray()
        expected = 0
        for n, dict_id, data in self.conn.execute(
            "SELECT n, dict_id, data FROM chunks WHERE doc_id=? ORDER BY n", (doc_id,)
        ):
            if n != expected or not isinstance(data, bytes) or len(data) > spec.MAX_CHUNK_COMPRESSED:
                raise SuviiError("corrupt", "chunk")
            expected += 1
            try:
                piece = _zstd.decompress(data, spec.MAX_CHUNK_RAW, self._dict(dict_id))
            except SuviiError:
                raise
            except Exception as e:  # zstd, MemoryError тощо
                raise SuviiError("corrupt", "chunk data") from e
            out += piece
            if len(out) > size:
                raise SuviiError("corrupt", "size")
        if len(out) != size:
            raise SuviiError("corrupt", "size")
        return bytes(out)

    def document(self, path: str, check_hash: bool = True) -> Document:
        doc_id, title, mime, size, updated, stored = self._doc_id(path)
        body = self.raw_body(doc_id, size)
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as e:
            raise SuviiError("corrupt", "utf-8") from e
        doc = Document(
            path=path,
            title=title,
            body=text,
            updated=updated,
            mime=mime,
            facets=self.conn.execute("SELECT key, value FROM facets WHERE doc_id=?", (doc_id,)).fetchall(),
            toc=[TocEntry(*r) for r in self.conn.execute(
                "SELECT level, anchor, title FROM toc WHERE doc_id=? ORDER BY ord", (doc_id,))],
            links=[Link(*r) for r in self.conn.execute(
                "SELECT kind, target, anchor FROM links WHERE doc_id=?", (doc_id,))],
        )
        if check_hash and hashing.doc_hash(doc) != stored:
            raise SuviiError("bad_doc_hash", path)
        if mime == "text/html":
            check_html(text)
        return doc

    def search(self, query: str, limit: int = 50) -> list[tuple[str, str]]:
        words = re.findall(r"\w+", query)
        if not words:
            return []
        if self.has_fts:
            expr = " ".join('"' + w.replace('"', "") + '"*' for w in words)
            rows = self.conn.execute(
                "SELECT d.path, d.title FROM fts JOIN docs d ON d.id = fts.rowid "
                "WHERE fts MATCH ? ORDER BY rank LIMIT ?",
                (expr, limit),
            ).fetchall()
            return rows
        like = "%" + "%".join(words) + "%"
        return self.conn.execute(
            "SELECT path, title FROM docs WHERE title LIKE ? ORDER BY path LIMIT ?", (like, limit)
        ).fetchall()

    # ----- корені й підпис -----
    def state_root(self) -> bytes:
        return hashing.state_root(self.cid_bytes, self.seq, self.path_hashes())

    def patch_root(self) -> bytes:
        return hashing.patch_root(
            self.cid_bytes,
            int(self.meta["patch.from_seq"]),
            int(self.meta["patch.to_seq"]),
            self.path_hashes(),
            self.tombstones(),
        )

    def signature_ok(self, trusted_keys: list[str]) -> bool:
        if self.kind == "base":
            msg = hashing.base_message(self.meta, self.state_root())
        else:
            expected = bytes.fromhex(self.meta["patch.state_root"])
            msg = hashing.patch_message(self.meta, self.patch_root(), expected)
        return keys.verify(trusted_keys, self.meta["sign.sig"], msg)

    # ----- повна перевірка -----
    def verify_all(self) -> list[str]:
        """Перевіряє кожен документ. Повертає список проблем (порожній — усе гаразд)."""
        problems: list[str] = []
        for info in list(self.infos()):
            try:
                self.document(info.path)
            except SuviiError as e:
                problems.append(f"{info.path}: {e.code}")
        orphans = self.conn.execute("SELECT count(*) FROM chunks WHERE doc_id NOT IN (SELECT id FROM docs)").fetchone()[0]
        if orphans:
            problems.append(f"{orphans} orphan chunks")
        if self.kind == "base" and self.tombstones():
            problems.append("tombstones in base")
        return problems


def _check_schema(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_schema").fetchall()
    tables = set()
    for typ, name, _tbl, sql in rows:
        if typ in ("trigger", "view"):
            raise SuviiError("forbidden_schema", f"{typ} {name}")
        if typ == "table":
            tables.add(name)
            if sql and sql.upper().startswith("CREATE VIRTUAL TABLE"):
                if name != "fts" or not _FTS_SQL.match(sql):
                    raise SuviiError("forbidden_schema", f"virtual table {name}")
    for t, cols in spec.EXPECTED_COLUMNS.items():
        if t not in tables:
            raise SuviiError("bad_schema", f"missing {t}")
        got = [(r[1], r[2].upper(), r[3], r[5]) for r in conn.execute(f"PRAGMA table_info({t})")]
        if got != cols:
            raise SuviiError("bad_schema", t)


def _check_limits(conn: sqlite3.Connection) -> None:
    q = conn.execute
    checks = [
        (f"SELECT count(*) FROM docs WHERE typeof(path)!='text' OR {_blen('path')} NOT BETWEEN 1 AND {spec.MAX_PATH}"
         f" OR typeof(title)!='text' OR {_blen('title')} > {spec.MAX_TITLE}"
         f" OR typeof(mime)!='text' OR mime NOT IN ('text/plain','text/html')"
         f" OR typeof(updated)!='text' OR {_blen('updated')} > {spec.MAX_SHORT}"
         f" OR typeof(size)!='integer' OR size < 0 OR size > {spec.MAX_DOC}"
         f" OR typeof(hash)!='blob' OR length(hash) != 32", "docs"),
        (f"SELECT count(*) FROM chunks WHERE typeof(data)!='blob' OR length(data) > {spec.MAX_CHUNK_COMPRESSED}"
         f" OR typeof(n)!='integer' OR n < 0", "chunks"),
        (f"SELECT count(*) FROM dicts WHERE typeof(data)!='blob' OR length(data) > {spec.MAX_DICT}", "dicts"),
        (f"SELECT count(*) FROM facets WHERE typeof(key)!='text' OR typeof(value)!='text'"
         f" OR {_blen('key')} > {spec.MAX_SHORT} OR {_blen('value')} > {spec.MAX_SHORT}", "facets"),
        (f"SELECT count(*) FROM toc WHERE typeof(anchor)!='text' OR typeof(title)!='text'"
         f" OR {_blen('anchor')} > {spec.MAX_SHORT} OR {_blen('title')} > {spec.MAX_TOC_TITLE}"
         f" OR typeof(level)!='integer' OR level NOT BETWEEN 1 AND 32", "toc"),
        (f"SELECT count(*) FROM links WHERE typeof(kind)!='text' OR typeof(target)!='text' OR typeof(anchor)!='text'"
         f" OR {_blen('kind')} > {spec.MAX_SHORT} OR {_blen('target')} > {spec.MAX_PATH}"
         f" OR {_blen('anchor')} > {spec.MAX_SHORT}", "links"),
        (f"SELECT count(*) FROM tombstones WHERE typeof(path)!='text' OR {_blen('path')} > {spec.MAX_PATH}", "tombstones"),
        (f"SELECT count(*) FROM meta WHERE typeof(key)!='text' OR typeof(value)!='text'"
         f" OR {_blen('key')} > {spec.MAX_SHORT} OR {_blen('value')} > {spec.MAX_META_VALUE}", "meta"),
    ]
    for sql, what in checks:
        if q(sql).fetchone()[0]:
            raise SuviiError("limit_exceeded", what)
    if q("SELECT count(*) FROM dicts").fetchone()[0] > spec.MAX_DICTS:
        raise SuviiError("limit_exceeded", "dict count")
    for t in ("facets", "toc", "links"):
        if q(f"SELECT 1 FROM {t} GROUP BY doc_id HAVING count(*) > {spec.MAX_ITEMS_PER_DOC} LIMIT 1").fetchone():
            raise SuviiError("limit_exceeded", t)
    if q(f"SELECT count(*) FROM docs").fetchone()[0] > spec.MAX_DOCS:
        raise SuviiError("limit_exceeded", "docs")


def _check_meta(meta: dict[str, str]) -> None:
    for k in spec.REQUIRED_META:
        if k not in meta:
            raise SuviiError("missing_meta", k)
    fmt = meta["suvii.format"]
    m = re.fullmatch(r"(\d{1,4})\.(\d{1,4})", fmt)
    if not m:
        raise SuviiError("bad_meta", "suvii.format")
    if int(m.group(1)) != spec.MAJOR_VERSION:
        raise SuviiError("unsupported_version", fmt)
    if meta["suvii.kind"] not in spec.KINDS:
        raise SuviiError("bad_meta", "suvii.kind")
    if meta["sign.alg"] != "ed25519":
        raise SuviiError("bad_meta", "sign.alg")
    spec.check_uuid(meta["collection.id"])
    seq = spec.check_seq(meta["state.seq"])
    spec.check_datetime(meta["state.created"], "state.created")
    spec.check_date(meta["state.source_date"], "state.source_date")
    if spec.blen(meta.get("collection.icon", "")) > spec.MAX_ICON:
        raise SuviiError("limit_exceeded", "collection.icon")
    try:
        spec.check_fields(json.loads(meta["collection.fields"]))
    except (ValueError, RecursionError) as e:
        raise SuviiError("bad_meta", "collection.fields") from e
    if meta["suvii.kind"] == "patch":
        for k in spec.REQUIRED_PATCH_META:
            if k not in meta:
                raise SuviiError("missing_meta", k)
        f = spec.check_seq(meta["patch.from_seq"], "patch.from_seq")
        t = spec.check_seq(meta["patch.to_seq"], "patch.to_seq")
        if t != seq or f >= t:
            raise SuviiError("bad_meta", "patch seq")
        if not re.fullmatch(r"[0-9a-f]{64}", meta["patch.state_root"]):
            raise SuviiError("bad_meta", "patch.state_root")


def connect(path: Path, writable: bool) -> sqlite3.Connection:
    mode = "rw" if writable else "ro"
    uri = "file:" + str(path.resolve()).replace("?", "%3f").replace("#", "%23") + f"?mode={mode}"
    conn = sqlite3.connect(uri, uri=True, isolation_level=None)
    conn.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True)
    conn.setconfig(sqlite3.SQLITE_DBCONFIG_TRUSTED_SCHEMA, False)
    conn.execute("PRAGMA trusted_schema = OFF")
    conn.execute("PRAGMA cell_size_check = ON")
    if writable:
        conn.execute("PRAGMA foreign_keys = ON")
    else:
        conn.execute("PRAGMA query_only = ON")
    return conn


def open_scroll(
    path: str | os.PathLike,
    trusted_keys: list[str] | None = None,
    *,
    trust_embedded_key: bool = False,
    writable: bool = False,
    verify_signature: bool = True,
) -> Scroll:
    """Відкриває сувій з усіма перевірками з розділу 10.

    trusted_keys — публічні ключі (base64), яким довіряє програма.
    trust_embedded_key — довіритися ключу з самого файлу (лише для інструментів, не для читалок).
    """
    p = Path(path)
    app_id, user_version = read_header(p)
    if app_id != spec.APPLICATION_ID:
        raise SuviiError("not_suvii")
    if user_version != spec.MAJOR_VERSION:
        raise SuviiError("unsupported_version", str(user_version))
    conn = connect(p, writable)
    try:
        _check_schema(conn)
        _check_limits(conn)
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        _check_meta(meta)
        scroll = Scroll(p, conn, meta, "unverified")
        if verify_signature:
            keys_to_try = list(trusted_keys or [])
            trusted_by = "trusted"
            if not keys_to_try and trust_embedded_key:
                keys_to_try = [meta["sign.key"]]
                trusted_by = "embedded"
            if not keys_to_try:
                raise SuviiError("no_trusted_key")
            if not scroll.signature_ok(keys_to_try):
                raise SuviiError("bad_signature")
            scroll.trusted_by = trusted_by
        return scroll
    except SuviiError:
        conn.close()
        raise
    except (sqlite3.DatabaseError, ValueError, KeyError, MemoryError) as e:
        conn.close()
        raise SuviiError("corrupt", type(e).__name__) from e
