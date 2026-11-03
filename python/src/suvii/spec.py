# SPDX-License-Identifier: GPL-3.0-or-later
"""Сталі й перевірки з SPEC.md (версія 0.1)."""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import date, datetime

FORMAT_VERSION = "0.1"
MAJOR_VERSION = 0
APPLICATION_ID = 0x53555649  # 'SUVI'

KIB = 1024
MIB = 1024 * KIB

MAX_PATH = 1024
MAX_TITLE = 4096
MAX_SHORT = 1024  # mime, updated, facet key/value, anchor, link kind/target
MAX_TOC_TITLE = 4096
MAX_ITEMS_PER_DOC = 10_000
MAX_CHUNK_COMPRESSED = 256 * KIB
MAX_CHUNK_RAW = 1 * MIB
MAX_DOC = 64 * MIB
MAX_DICT = 1 * MIB
MAX_DICTS = 256
MAX_META_VALUE = 1 * MIB
MAX_ICON = 64 * 1000
MAX_DOCS = 2**31 - 1
MAX_SEQ = 2**63 - 1

MIME_TYPES = ("text/plain", "text/html")
KINDS = ("base", "patch")

REQUIRED_META = (
    "suvii.format",
    "suvii.kind",
    "collection.id",
    "collection.title",
    "collection.language",
    "collection.publisher",
    "collection.fields",
    "state.seq",
    "state.created",
    "state.source_date",
    "sign.alg",
    "sign.key",
    "sign.sig",
)
REQUIRED_PATCH_META = ("patch.from_seq", "patch.to_seq", "patch.state_root", "patch.base_sig")

SCHEMA = """
CREATE TABLE meta (
  key   TEXT PRIMARY KEY NOT NULL,
  value TEXT NOT NULL
) WITHOUT ROWID;
CREATE TABLE docs (
  id       INTEGER PRIMARY KEY,
  path     TEXT    NOT NULL UNIQUE,
  title    TEXT    NOT NULL,
  mime     TEXT    NOT NULL,
  size     INTEGER NOT NULL,
  updated  TEXT    NOT NULL,
  hash     BLOB    NOT NULL
);
CREATE TABLE chunks (
  doc_id   INTEGER NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
  n        INTEGER NOT NULL,
  dict_id  INTEGER REFERENCES dicts(id),
  data     BLOB    NOT NULL,
  PRIMARY KEY (doc_id, n)
) WITHOUT ROWID;
CREATE TABLE dicts (
  id   INTEGER PRIMARY KEY,
  data BLOB NOT NULL
);
CREATE TABLE facets (
  doc_id INTEGER NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
  key    TEXT    NOT NULL,
  value  TEXT    NOT NULL,
  PRIMARY KEY (doc_id, key, value)
) WITHOUT ROWID;
CREATE INDEX facets_kv ON facets(key, value);
CREATE TABLE toc (
  doc_id INTEGER NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
  ord    INTEGER NOT NULL,
  level  INTEGER NOT NULL,
  anchor TEXT    NOT NULL,
  title  TEXT    NOT NULL,
  PRIMARY KEY (doc_id, ord)
) WITHOUT ROWID;
CREATE TABLE links (
  doc_id   INTEGER NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
  kind     TEXT    NOT NULL,
  target   TEXT    NOT NULL,
  anchor   TEXT    NOT NULL DEFAULT '',
  PRIMARY KEY (doc_id, kind, target, anchor)
) WITHOUT ROWID;
CREATE INDEX links_target ON links(target);
CREATE TABLE tombstones (
  path    TEXT PRIMARY KEY NOT NULL,
  deleted TEXT NOT NULL
) WITHOUT ROWID;
"""

FTS_SCHEMA = (
    "CREATE VIRTUAL TABLE fts USING fts5("
    "title, body, content = '', contentless_delete = 1, "
    "tokenize = 'unicode61 remove_diacritics 0')"
)

# Очікувані колонки обов'язкових таблиць: (назва, тип, notnull, pk)
EXPECTED_COLUMNS: dict[str, list[tuple[str, str, int, int]]] = {
    "meta": [("key", "TEXT", 1, 1), ("value", "TEXT", 1, 0)],
    "docs": [
        ("id", "INTEGER", 0, 1),
        ("path", "TEXT", 1, 0),
        ("title", "TEXT", 1, 0),
        ("mime", "TEXT", 1, 0),
        ("size", "INTEGER", 1, 0),
        ("updated", "TEXT", 1, 0),
        ("hash", "BLOB", 1, 0),
    ],
    "chunks": [("doc_id", "INTEGER", 1, 1), ("n", "INTEGER", 1, 2), ("dict_id", "INTEGER", 0, 0), ("data", "BLOB", 1, 0)],
    "dicts": [("id", "INTEGER", 0, 1), ("data", "BLOB", 1, 0)],
    "facets": [("doc_id", "INTEGER", 1, 1), ("key", "TEXT", 1, 2), ("value", "TEXT", 1, 3)],
    "toc": [
        ("doc_id", "INTEGER", 1, 1),
        ("ord", "INTEGER", 1, 2),
        ("level", "INTEGER", 1, 0),
        ("anchor", "TEXT", 1, 0),
        ("title", "TEXT", 1, 0),
    ],
    "links": [("doc_id", "INTEGER", 1, 1), ("kind", "TEXT", 1, 2), ("target", "TEXT", 1, 3), ("anchor", "TEXT", 1, 4)],
    "tombstones": [("path", "TEXT", 1, 1), ("deleted", "TEXT", 1, 0)],
}


class SuviiError(Exception):
    """Будь-яка проблема з сувоєм. `code` — сталий машинний код для перекладу повідомлень."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INT = re.compile(r"^-?\d{1,18}$")


def blen(s: str) -> int:
    return len(s.encode("utf-8"))


def check_nfc(s: str, what: str) -> None:
    if unicodedata.normalize("NFC", s) != s:
        raise SuviiError("not_nfc", what)


def check_text(s: str, limit: int, what: str, allow_empty: bool = False) -> None:
    if not isinstance(s, str):
        raise SuviiError("bad_type", what)
    if not allow_empty and not s:
        raise SuviiError("empty", what)
    if blen(s) > limit:
        raise SuviiError("too_long", what)
    check_nfc(s, what)


def check_path(path: str) -> None:
    check_text(path, MAX_PATH, "path")
    if _CTRL.search(path) or any(c in path for c in "\\?#"):
        raise SuviiError("bad_path", path)
    if path.startswith("/") or path.endswith("/"):
        raise SuviiError("bad_path", path)
    for seg in path.split("/"):
        if seg in ("", ".", ".."):
            raise SuviiError("bad_path", path)


def check_datetime(s: str, what: str) -> None:
    if not isinstance(s, str) or not _DATETIME.match(s):
        raise SuviiError("bad_datetime", what)
    try:
        datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as e:
        raise SuviiError("bad_datetime", what) from e


def check_date(s: str, what: str) -> None:
    if not isinstance(s, str) or not _DATE.match(s):
        raise SuviiError("bad_date", what)
    try:
        d = date.fromisoformat(s)
    except ValueError as e:
        raise SuviiError("bad_date", what) from e
    if d.year < 1:
        raise SuviiError("bad_date", what)


def check_uuid(s: str) -> bytes:
    try:
        u = uuid.UUID(s)
    except (ValueError, AttributeError, TypeError) as e:
        raise SuviiError("bad_collection_id", str(s)) from e
    if str(u) != s:
        raise SuviiError("bad_collection_id", s)
    return u.bytes


def check_seq(s: str, what: str = "state.seq") -> int:
    if not isinstance(s, str) or not re.fullmatch(r"[1-9]\d{0,18}", s):
        raise SuviiError("bad_seq", what)
    v = int(s)
    if v > MAX_SEQ:
        raise SuviiError("bad_seq", what)
    return v


def check_facet_value(fields: dict, key: str, value: str) -> None:
    spec = fields.get(key)
    if spec is None:
        raise SuviiError("unknown_facet", key)
    t = spec.get("type")
    if t == "text":
        return
    if t == "int":
        if not _INT.match(value):
            raise SuviiError("bad_facet", f"{key}={value}")
    elif t == "date":
        check_date(value, f"facet {key}")
    elif t == "bool":
        if value not in ("0", "1"):
            raise SuviiError("bad_facet", f"{key}={value}")
    elif t == "enum":
        if value not in spec.get("values", {}):
            raise SuviiError("bad_facet", f"{key}={value}")
    else:
        raise SuviiError("bad_fields", key)


def check_fields(fields: object) -> dict:
    if not isinstance(fields, dict):
        raise SuviiError("bad_fields")
    for k, v in fields.items():
        check_text(k, MAX_SHORT, "field key")
        if not isinstance(v, dict) or v.get("type") not in ("text", "int", "date", "bool", "enum"):
            raise SuviiError("bad_fields", k)
        if v["type"] == "enum" and not isinstance(v.get("values"), dict):
            raise SuviiError("bad_fields", k)
    return fields
