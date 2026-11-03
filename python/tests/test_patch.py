# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import sqlite3

import pytest
from conftest import SAMPLE, doc

from suvii import SuviiError, apply_patch, apply_patch_copy, keys, make_patch, open_scroll

CHANGED = doc("laws/2341-14", "Кримінальний кодекс України", "Нова редакція статті про охорону прав.",
              updated="2026-11-03T00:00:00Z", facets=[("kind", "code"), ("status", "in_force")])
NEW = doc("laws/9999-ix", "Закон про офлайн-доступ", "Кожен має право читати закони без інтернету.",
          updated="2026-11-03T00:00:00Z")


@pytest.fixture
def two_bases(make_base):
    old = make_base("old.suvii", SAMPLE, seq=1)
    new = make_base("new.suvii", [SAMPLE[0], CHANGED, NEW], seq=2)  # old-1 видалено
    return old, new


@pytest.fixture
def patch_file(two_bases, tmp_path, key, pub):
    old, new = two_bases
    out = tmp_path / "1-2.patch.suvii"
    with open_scroll(old, [pub]) as o, open_scroll(new, [pub]) as n:
        stats = make_patch(o, n, out, key)
    assert stats == {"changed": 2, "removed": 1}
    return out


def test_patch_is_valid_scroll(patch_file, pub):
    with open_scroll(patch_file, [pub]) as p:
        assert p.kind == "patch"
        assert p.meta["patch.from_seq"] == "1" and p.meta["patch.to_seq"] == "2"
        assert p.tombstones() == ["laws/old-1"]
        assert not p.has_fts
        assert p.verify_all() == []


def test_apply_gives_same_state_as_new_base(two_bases, patch_file, tmp_path, pub):
    old, new = two_bases
    out = tmp_path / "patched.suvii"
    assert apply_patch_copy(old, patch_file, out, [pub]) == 2
    with open_scroll(out, [pub]) as r, open_scroll(new, [pub]) as n:
        assert r.kind == "base" and r.seq == 2
        assert r.state_root() == n.state_root()
        assert r.path_hashes() == n.path_hashes()
        assert r.verify_all() == []
        assert r.document("laws/2341-14").body == CHANGED.body
        assert [p for p, _ in r.search("інтернету")] == ["laws/9999-ix"]
        assert r.search("втратив") == []
        assert r.search("охорону")[0][0] == "laws/2341-14"
    # вихідна основа не змінилася
    with open_scroll(old, [pub]) as o:
        assert o.seq == 1 and o.count() == 3


def test_apply_in_place(two_bases, patch_file, pub):
    old, _ = two_bases
    assert apply_patch(old, patch_file, [pub]) == 2
    with open_scroll(old, [pub]) as r:
        assert r.seq == 2 and r.count() == 3


def test_apply_twice_fails(two_bases, patch_file, pub):
    old, _ = two_bases
    apply_patch(old, patch_file, [pub])
    with pytest.raises(SuviiError) as e:
        apply_patch(old, patch_file, [pub])
    assert e.value.code == "wrong_base_seq"


def test_untrusted_patch_rejected(two_bases, patch_file):
    old, _ = two_bases
    with pytest.raises(SuviiError) as e:
        apply_patch(old, patch_file, [keys.public_text(keys.generate())])
    assert e.value.code == "bad_signature"


def test_tampered_patch_rejected(two_bases, patch_file, pub):
    old, _ = two_bases
    c = sqlite3.connect(patch_file)
    c.execute("DELETE FROM tombstones")
    c.commit()
    c.close()
    with pytest.raises(SuviiError) as e:
        apply_patch(old, patch_file, [pub])
    assert e.value.code == "bad_signature"
    with open_scroll(old, [pub]) as o:  # основа ціла
        assert o.seq == 1 and o.count() == 3


def test_tampered_patch_body_rolls_back(two_bases, patch_file, pub):
    old, _ = two_bases
    c = sqlite3.connect(patch_file)
    c.execute("UPDATE docs SET title='Підробка'")
    c.commit()
    c.close()
    with pytest.raises(SuviiError):
        apply_patch(old, patch_file, [pub])
    with open_scroll(old, [pub]) as o:
        assert o.seq == 1 and o.verify_all() == []


def test_patch_needs_new_base_key(two_bases, tmp_path, pub):
    old, new = two_bases
    with open_scroll(old, [pub]) as o, open_scroll(new, [pub]) as n:
        with pytest.raises(SuviiError) as e:
            make_patch(o, n, tmp_path / "x.suvii", keys.generate())
    assert e.value.code == "key_mismatch"


def test_patch_other_collection(make_base, tmp_path, key, pub):
    a = make_base("a.suvii", SAMPLE, seq=1)
    b = make_base("b.suvii", SAMPLE, seq=2)
    c = sqlite3.connect(b)
    c.execute("UPDATE meta SET value='11111111-1111-1111-1111-111111111111' WHERE key='collection.id'")
    c.commit()
    c.close()
    with open_scroll(a, [pub]) as o, open_scroll(b, verify_signature=False) as n:
        with pytest.raises(SuviiError) as e:
            make_patch(o, n, tmp_path / "x.suvii", key)
    assert e.value.code == "collection_mismatch"


def test_chain_of_patches(make_base, tmp_path, key, pub):
    b1 = make_base("b1.suvii", SAMPLE, seq=1)
    b2 = make_base("b2.suvii", [SAMPLE[0], CHANGED, SAMPLE[2]], seq=2)
    b3 = make_base("b3.suvii", [SAMPLE[0], CHANGED, NEW], seq=3)
    p12, p23 = tmp_path / "12.suvii", tmp_path / "23.suvii"
    with open_scroll(b1, [pub]) as a, open_scroll(b2, [pub]) as b:
        make_patch(a, b, p12, key)
    with open_scroll(b2, [pub]) as a, open_scroll(b3, [pub]) as b:
        make_patch(a, b, p23, key)
    apply_patch(b1, p12, [pub])
    apply_patch(b1, p23, [pub])
    with open_scroll(b1, [pub]) as r, open_scroll(b3, [pub]) as e:
        assert r.seq == 3 and r.state_root() == e.state_root()
