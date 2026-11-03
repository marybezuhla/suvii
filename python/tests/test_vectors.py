# SPDX-License-Identifier: GPL-3.0-or-later
"""Контрольні значення з testdata/vectors.json мусять відтворюватися."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from suvii import Document, Link, TocEntry, apply_patch_copy, hashing, keys, open_scroll

TESTDATA = Path(__file__).resolve().parents[2] / "testdata"
V = json.loads((TESTDATA / "vectors.json").read_text(encoding="utf-8"))
PUB = V["public_key"]


def test_doc_hash():
    d = V["doc"]
    doc = Document(path=d["path"], title=d["title"], body=d["body"], updated=d["updated"], mime=d["mime"],
                   facets=[tuple(x) for x in d["facets"]], toc=[TocEntry(*t) for t in d["toc"]],
                   links=[Link(*x) for x in d["links"]])
    assert hashing.doc_hash(doc).hex() == d["doc_hash"]


def test_test_key_matches():
    priv = (TESTDATA / "test-key.txt").read_text().strip()
    assert keys.public_text(keys.private_from_text(priv)) == PUB


def test_base_vectors():
    with open_scroll(TESTDATA / "base-1.suvii", [PUB]) as s:
        assert s.state_root().hex() == V["base_1"]["state_root"]
        assert hashing.meta_hash(s.meta).hex() == V["base_1"]["meta_hash"]
        assert s.meta["sign.sig"] == V["base_1"]["signature"]
        assert s.verify_all() == []


def test_patch_vectors(tmp_path):
    with open_scroll(TESTDATA / "patch-1-2.suvii", [PUB]) as p:
        assert p.patch_root().hex() == V["patch_1_2"]["patch_root"]
        assert hashing.meta_hash(p.meta).hex() == V["patch_1_2"]["meta_hash"]
        assert p.meta["sign.sig"] == V["patch_1_2"]["signature"]
    base = tmp_path / "b.suvii"
    shutil.copy(TESTDATA / "base-1.suvii", base)
    out = tmp_path / "out.suvii"
    apply_patch_copy(base, TESTDATA / "patch-1-2.suvii", out, [PUB])
    with open_scroll(out, [PUB]) as r:
        assert r.state_root().hex() == V["base_2"]["state_root"] == V["patch_1_2"]["expected_state_root"]
        assert r.meta["sign.sig"] == V["patch_1_2"]["base_sig"]
