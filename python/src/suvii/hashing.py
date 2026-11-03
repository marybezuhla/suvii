# SPDX-License-Identifier: GPL-3.0-or-later
"""Хеші й повідомлення для підпису (SPEC.md, розділ 9)."""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Iterable

from .model import Document


def u32(x: int) -> bytes:
    return struct.pack(">I", x)


def u64(x: int) -> bytes:
    return struct.pack(">Q", x)


def s(text: str) -> bytes:
    b = text.encode("utf-8")
    return u32(len(b)) + b


def doc_hash_parts(
    path: str,
    title: str,
    mime: str,
    updated: str,
    facets: Iterable[tuple[str, str]],
    toc: Iterable[tuple[int, str, str]],
    links: Iterable[tuple[str, str, str]],
    body: bytes,
) -> bytes:
    """toc — у порядку ord; facets і links сортуються тут за байтами."""
    h = hashlib.sha256()
    h.update(b"suvii-doc-1\n")
    h.update(s(path) + s(title) + s(mime) + s(updated))
    fs = sorted(facets, key=lambda kv: (kv[0].encode(), kv[1].encode()))
    h.update(u32(len(fs)))
    for k, v in fs:
        h.update(s(k) + s(v))
    ts = list(toc)
    h.update(u32(len(ts)))
    for level, anchor, title_ in ts:
        h.update(u32(level) + s(anchor) + s(title_))
    ls = sorted(links, key=lambda x: (x[0].encode(), x[1].encode(), x[2].encode()))
    h.update(u32(len(ls)))
    for kind, target, anchor in ls:
        h.update(s(kind) + s(target) + s(anchor))
    h.update(u64(len(body)))
    h.update(body)
    return h.digest()


def doc_hash(doc: Document) -> bytes:
    return doc_hash_parts(
        doc.path,
        doc.title,
        doc.mime,
        doc.updated,
        doc.facets,
        [(t.level, t.anchor, t.title) for t in doc.toc],
        [(lk.kind, lk.target, lk.anchor) for lk in doc.links],
        doc.body_bytes,
    )


def state_root(collection_id: bytes, seq: int, path_hashes: Iterable[tuple[str, bytes]]) -> bytes:
    """path_hashes МУСИТЬ бути впорядкованим за байтами шляху."""
    items = list(path_hashes)
    h = hashlib.sha256()
    h.update(b"suvii-state-1\n" + collection_id + u64(seq) + u64(len(items)))
    prev: bytes | None = None
    for path, dh in items:
        pb = path.encode("utf-8")
        if prev is not None and pb <= prev:
            raise ValueError("paths not sorted or duplicated")
        prev = pb
        h.update(s(path) + dh)
    return h.digest()


def meta_hash(meta: dict[str, str]) -> bytes:
    h = hashlib.sha256()
    h.update(b"suvii-meta-1\n")
    for k in sorted((k for k in meta if not k.startswith("sign.") and k != "patch.base_sig"), key=str.encode):
        h.update(s(k) + s(meta[k]))
    return h.digest()


def patch_root(
    collection_id: bytes,
    from_seq: int,
    to_seq: int,
    path_hashes: Iterable[tuple[str, bytes]],
    tombstones: Iterable[str],
) -> bytes:
    docs = list(path_hashes)
    tomb = sorted(tombstones, key=str.encode)
    h = hashlib.sha256()
    h.update(b"suvii-patch-1\n" + collection_id + u64(from_seq) + u64(to_seq))
    h.update(u64(len(docs)))
    for path, dh in sorted(docs, key=lambda x: x[0].encode()):
        h.update(s(path) + dh)
    h.update(u64(len(tomb)))
    for p in tomb:
        h.update(s(p))
    return h.digest()


def base_message(meta: dict[str, str], root: bytes) -> bytes:
    return b"suvii-sig-1\nbase\n" + meta_hash(meta) + root


def patch_message(meta: dict[str, str], proot: bytes, expected_root: bytes) -> bytes:
    return b"suvii-sig-1\npatch\n" + meta_hash(meta) + proot + expected_root
