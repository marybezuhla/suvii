# SPDX-License-Identifier: GPL-3.0-or-later
"""Латки: створення з двох основ і застосування (SPEC.md, розділ 12)."""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from . import hashing, keys, spec
from .html import body_to_text
from .reader import Scroll, connect, open_scroll
from .spec import SuviiError
from .writer import create_schema, finalize_file, utc_now

_DOC_TABLES = ("facets", "toc", "links")


def _copy_doc(src: sqlite3.Connection, dst: sqlite3.Connection, src_id: int, dict_map: dict[int, int]) -> int:
    """Копіює документ з усіма частинами (без перепакування). Повертає новий id."""
    row = src.execute("SELECT path, title, mime, size, updated, hash FROM docs WHERE id=?", (src_id,)).fetchone()
    new_id = dst.execute(
        "INSERT INTO docs(path, title, mime, size, updated, hash) VALUES (?,?,?,?,?,?)", row
    ).lastrowid
    for n, dict_id, data in src.execute("SELECT n, dict_id, data FROM chunks WHERE doc_id=? ORDER BY n", (src_id,)):
        if dict_id is not None and dict_id not in dict_map:
            d = src.execute("SELECT data FROM dicts WHERE id=?", (dict_id,)).fetchone()
            if d is None:
                raise SuviiError("corrupt", "missing dictionary")
            dict_map[dict_id] = dst.execute("INSERT INTO dicts(data) VALUES (?)", (d[0],)).lastrowid
        dst.execute(
            "INSERT INTO chunks(doc_id, n, dict_id, data) VALUES (?,?,?,?)",
            (new_id, n, dict_map[dict_id] if dict_id is not None else None, data),
        )
    dst.executemany(
        "INSERT INTO facets(doc_id, key, value) VALUES (?,?,?)",
        [(new_id, k, v) for k, v in src.execute("SELECT key, value FROM facets WHERE doc_id=?", (src_id,))],
    )
    dst.executemany(
        "INSERT INTO toc(doc_id, ord, level, anchor, title) VALUES (?,?,?,?,?)",
        [(new_id, *r) for r in src.execute("SELECT ord, level, anchor, title FROM toc WHERE doc_id=?", (src_id,))],
    )
    dst.executemany(
        "INSERT INTO links(doc_id, kind, target, anchor) VALUES (?,?,?,?)",
        [(new_id, *r) for r in src.execute("SELECT kind, target, anchor FROM links WHERE doc_id=?", (src_id,))],
    )
    return new_id


def make_patch(
    old: Scroll,
    new: Scroll,
    out_path: str | os.PathLike,
    key: Ed25519PrivateKey,
) -> dict[str, int]:
    """Створює латку old → new. Обидві основи мають бути вже перевірені."""
    if old.kind != "base" or new.kind != "base":
        raise SuviiError("not_base")
    if old.collection_id != new.collection_id:
        raise SuviiError("collection_mismatch")
    if new.seq <= old.seq:
        raise SuviiError("bad_seq", "new seq must be greater")
    if keys.public_text(key) != new.meta["sign.key"]:
        raise SuviiError("key_mismatch", "patch must be signed by the key of the new base")

    old_hashes = dict(old.path_hashes())
    new_rows = new.conn.execute("SELECT id, path, hash FROM docs ORDER BY path").fetchall()
    new_paths = {p for _, p, _ in new_rows}
    changed = [(i, p, h) for i, p, h in new_rows if old_hashes.get(p) != h]
    removed = sorted((p for p in old_hashes if p not in new_paths), key=str.encode)

    out = Path(out_path)
    if out.exists():
        raise SuviiError("file_exists", str(out))
    tmp = out.with_name(out.name + ".part")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode = OFF")
        create_schema(conn, with_fts=False)
        conn.execute("BEGIN")
        dict_map: dict[int, int] = {}
        for src_id, _p, _h in changed:
            _copy_doc(new.conn, conn, src_id, dict_map)
        now = utc_now()
        conn.executemany("INSERT INTO tombstones(path, deleted) VALUES (?,?)", [(p, now) for p in removed])

        meta = {k: v for k, v in new.meta.items() if not k.startswith("sign.")}
        meta.update({
            "suvii.kind": "patch",
            "patch.from_seq": str(old.seq),
            "patch.to_seq": str(new.seq),
            "patch.state_root": new.state_root().hex(),
            "patch.base_sig": new.meta["sign.sig"],
            "sign.alg": "ed25519",
            "sign.key": keys.public_text(key),
        })
        proot = hashing.patch_root(new.cid_bytes, old.seq, new.seq, [(p, h) for _, p, h in changed], removed)
        meta["sign.sig"] = keys.sign(key, hashing.patch_message(meta, proot, bytes.fromhex(meta["patch.state_root"])))
        conn.executemany("INSERT INTO meta(key, value) VALUES (?,?)", sorted(meta.items()))
        conn.execute("COMMIT")
        finalize_file(conn)
    except BaseException:
        conn.close()
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, out)
    return {"changed": len(changed), "removed": len(removed)}


def _delete_doc(conn: sqlite3.Connection, doc_id: int, has_fts: bool) -> None:
    if has_fts:
        conn.execute("DELETE FROM fts WHERE rowid=?", (doc_id,))
    conn.execute("DELETE FROM docs WHERE id=?", (doc_id,))  # решта — ON DELETE CASCADE


def apply_patch(
    base_path: str | os.PathLike,
    patch_path: str | os.PathLike,
    trusted_keys: list[str],
) -> int:
    """Застосовує латку до основи на місці, однією транзакцією. Повертає новий номер стану."""
    patch = open_scroll(patch_path, trusted_keys)
    try:
        if patch.kind != "patch":
            raise SuviiError("not_patch")
        base = open_scroll(base_path, trusted_keys, writable=True)
        try:
            if base.kind != "base":
                raise SuviiError("not_base")
            if base.collection_id != patch.collection_id:
                raise SuviiError("collection_mismatch")
            if int(patch.meta["patch.from_seq"]) != base.seq:
                raise SuviiError("wrong_base_seq", f"{base.seq} != {patch.meta['patch.from_seq']}")
            # латка теж має пройти перевірку кожного документа
            problems = patch.verify_all()
            if problems:
                raise SuviiError("corrupt_patch", problems[0])
            conn = base.conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                for path in patch.tombstones():
                    row = conn.execute("SELECT id FROM docs WHERE path=?", (path,)).fetchone()
                    if row:
                        _delete_doc(conn, row[0], base.has_fts)
                dict_map: dict[int, int] = {}
                for (src_id, path) in patch.conn.execute("SELECT id, path FROM docs ORDER BY id").fetchall():
                    row = conn.execute("SELECT id FROM docs WHERE path=?", (path,)).fetchone()
                    if row:
                        _delete_doc(conn, row[0], base.has_fts)
                    new_id = _copy_doc(patch.conn, conn, src_id, dict_map)
                    if base.has_fts:
                        d = patch.document(path, check_hash=False)  # хеш уже перевірено у verify_all
                        conn.execute(
                            "INSERT INTO fts(rowid, title, body) VALUES (?,?,?)",
                            (new_id, d.title, body_to_text(d.mime, d.body)),
                        )
                conn.execute("DELETE FROM dicts WHERE id NOT IN (SELECT DISTINCT dict_id FROM chunks WHERE dict_id IS NOT NULL)")
                new_meta = {k: v for k, v in patch.meta.items() if not k.startswith("patch.")}
                new_meta["suvii.kind"] = "base"
                new_meta["sign.sig"] = patch.meta["patch.base_sig"]
                conn.execute("DELETE FROM meta")
                conn.executemany("INSERT INTO meta(key, value) VALUES (?,?)", sorted(new_meta.items()))

                base.meta = new_meta
                base.seq = int(new_meta["state.seq"])
                root = base.state_root()
                if root.hex() != patch.meta["patch.state_root"]:
                    raise SuviiError("state_root_mismatch")
                if not base.signature_ok(trusted_keys):
                    raise SuviiError("bad_signature", "updated base")
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            return base.seq
        finally:
            base.close()
    finally:
        patch.close()


def apply_patch_copy(
    base_path: str | os.PathLike,
    patch_path: str | os.PathLike,
    out_path: str | os.PathLike,
    trusted_keys: list[str],
) -> int:
    """Як apply_patch, але лишає вихідну основу незмінною."""
    out = Path(out_path)
    if out.exists():
        raise SuviiError("file_exists", str(out))
    tmp = out.with_name(out.name + ".part")
    shutil.copyfile(base_path, tmp)
    try:
        seq = apply_patch(tmp, patch_path, trusted_keys)
        conn = connect(tmp, writable=True)
        conn.execute("VACUUM")
        conn.close()
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, out)
    return seq
