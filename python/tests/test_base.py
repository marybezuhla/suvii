# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import sqlite3

import pytest
from conftest import SAMPLE, doc

from suvii import Document, SuviiError, Writer, keys, open_scroll, spec
from suvii.reader import _check_limits


def test_roundtrip(make_base, pub):
    f = make_base("a.suvii", SAMPLE)
    with open_scroll(f, [pub]) as s:
        assert s.kind == "base" and s.seq == 1 and s.count() == 3
        assert s.trusted_by == "trusted"
        d = s.document("laws/254к/96-вр")
        assert d.title == "Конституція України" and "суверенна" in d.body
        assert [t.anchor for t in d.toc] == ["st-1"]
        assert s.verify_all() == []
        assert [p for p, _ in s.search("суверенна")] == ["laws/254к/96-вр"]
        assert [p for p, _ in s.search("кримінальн")] == ["laws/2341-14"]


def test_header_and_pragmas(make_base):
    f = make_base("a.suvii", SAMPLE)
    c = sqlite3.connect(f)
    assert c.execute("PRAGMA application_id").fetchone()[0] == spec.APPLICATION_ID
    assert c.execute("PRAGMA user_version").fetchone()[0] == spec.MAJOR_VERSION
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    c.close()


def test_large_document_is_chunked(make_base, pub):
    import random

    rnd = random.Random(7)
    words = ["закон", "стаття", "чинність", "Україна", "право", "особа", "суд", "держава", "громадянин"]
    text = " ".join(rnd.choice(words) + str(rnd.randint(0, 99999)) for _ in range(400_000))
    big = Document(path="laws/big", title="Великий", body=f"<p>{text}</p>", updated="2026-11-01T00:00:00Z")
    f = make_base("big.suvii", [big])
    with open_scroll(f, [pub]) as s:
        rows = s.conn.execute("SELECT length(data) FROM chunks").fetchall()
        assert len(rows) >= 4
        assert all(n <= spec.MAX_CHUNK_COMPRESSED for (n,) in rows)
        assert s.document("laws/big").body == big.body


def test_wrong_key_rejected(make_base):
    f = make_base("a.suvii", SAMPLE)
    other = keys.public_text(keys.generate())
    with pytest.raises(SuviiError) as e:
        open_scroll(f, [other])
    assert e.value.code == "bad_signature"


def test_no_key_rejected(make_base):
    f = make_base("a.suvii", SAMPLE)
    with pytest.raises(SuviiError) as e:
        open_scroll(f)
    assert e.value.code == "no_trusted_key"


def _tamper(path, sql, params=()):
    c = sqlite3.connect(path)
    c.execute(sql, params)
    c.commit()
    c.close()


def test_changed_title_breaks_signature(make_base, pub):
    f = make_base("a.suvii", SAMPLE)
    # зміна назви без зміни хешу: документ не збігатиметься з хешем
    _tamper(f, "UPDATE docs SET title='Підробка' WHERE path='laws/254к/96-вр'")
    with open_scroll(f, [pub]) as s:
        with pytest.raises(SuviiError) as e:
            s.document("laws/254к/96-вр")
        assert e.value.code == "bad_doc_hash"
        assert s.verify_all()


def test_changed_hash_breaks_signature(make_base, pub):
    f = make_base("a.suvii", SAMPLE)
    _tamper(f, "UPDATE docs SET hash=zeroblob(32) WHERE path='laws/old-1'")
    with pytest.raises(SuviiError) as e:
        open_scroll(f, [pub])
    assert e.value.code == "bad_signature"


def test_changed_meta_breaks_signature(make_base, pub):
    f = make_base("a.suvii", SAMPLE)
    _tamper(f, "UPDATE meta SET value='Інша назва' WHERE key='collection.title'")
    with pytest.raises(SuviiError) as e:
        open_scroll(f, [pub])
    assert e.value.code == "bad_signature"


def test_corrupted_chunk(make_base, pub):
    f = make_base("a.suvii", SAMPLE)
    _tamper(f, "UPDATE chunks SET data=x'28b52ffd00' WHERE doc_id=1")
    with open_scroll(f, [pub]) as s:
        with pytest.raises(SuviiError) as e:
            s.document(s.conn.execute("SELECT path FROM docs WHERE id=1").fetchone()[0])
        assert e.value.code == "corrupt"


def test_trigger_rejected(make_base, pub):
    f = make_base("a.suvii", SAMPLE)
    _tamper(f, "CREATE TRIGGER t AFTER INSERT ON docs BEGIN DELETE FROM docs; END")
    with pytest.raises(SuviiError) as e:
        open_scroll(f, [pub])
    assert e.value.code == "forbidden_schema"


def test_view_rejected(make_base, pub):
    f = make_base("a.suvii", SAMPLE)
    _tamper(f, "CREATE VIEW v AS SELECT * FROM docs")
    with pytest.raises(SuviiError) as e:
        open_scroll(f, [pub])
    assert e.value.code == "forbidden_schema"


def test_huge_title_rejected_before_reading(make_base, pub):
    f = make_base("a.suvii", SAMPLE)
    _tamper(f, "UPDATE docs SET title=? WHERE id=1", ("я" * 5000,))
    c = sqlite3.connect(f)
    with pytest.raises(SuviiError) as e:
        _check_limits(c)
    c.close()
    assert e.value.code == "limit_exceeded"


def test_not_suvii(tmp_path, pub):
    f = tmp_path / "x.suvii"
    c = sqlite3.connect(f)
    c.execute("CREATE TABLE a(b)")
    c.commit()
    c.close()
    with pytest.raises(SuviiError) as e:
        open_scroll(f, [pub])
    assert e.value.code == "not_suvii"


def test_garbage_file(tmp_path, pub):
    f = tmp_path / "x.suvii"
    f.write_bytes(b"\x00" * 50)
    with pytest.raises(SuviiError) as e:
        open_scroll(f, [pub])
    assert e.value.code == "not_sqlite"


@pytest.mark.parametrize("body", [
    "<script>alert(1)</script>",
    '<p onclick="x()">a</p>',
    '<a href="javascript:x()">a</a>',
    '<a href="http://example.com">a</a>',
    '<p style="color:red">a</p>',
    "<img src=x>",
    "<!-- прихований коментар -->",
    '<p class="evil">a</p>',
])
def test_unsafe_html_rejected(make_base, body):
    d = Document(path="a", title="A", body=body, updated="2026-11-01T00:00:00Z")
    with pytest.raises(SuviiError) as e:
        make_base("u.suvii", [d])
    assert e.value.code == "unsafe_html"


@pytest.mark.parametrize("path", ["", "/a", "a/", "a//b", "a/../b", "./a", "a?b", "a#b", "a\\b", "a\nb"])
def test_bad_paths(make_base, path):
    d = Document(path=path, title="A", body="<p>a</p>", updated="2026-11-01T00:00:00Z")
    with pytest.raises(SuviiError):
        make_base("p.suvii", [d])


def test_duplicate_path(make_base):
    with pytest.raises(SuviiError) as e:
        make_base("d.suvii", [doc("a", "A", "x"), doc("a", "B", "y")])
    assert e.value.code == "duplicate_path"


def test_bad_facet(make_base):
    with pytest.raises(SuviiError) as e:
        make_base("f.suvii", [doc("a", "A", "x", facets=[("status", "maybe")])])
    assert e.value.code == "bad_facet"


def test_non_nfc_rejected(make_base):
    with pytest.raises(SuviiError) as e:
        make_base("n.suvii", [doc("a", "Ки\u0306в", "x")])  # «й» записана як «и» + надрядковий знак
    assert e.value.code == "not_nfc"


def test_toc_anchor_must_exist(make_base):
    from suvii import TocEntry

    d = doc("a", "A", "x")
    d.toc.append(TocEntry(1, "st-404", "Немає"))
    with pytest.raises(SuviiError) as e:
        make_base("t.suvii", [d])
    assert e.value.code == "toc_anchor_missing"


def test_no_fts_falls_back_to_titles(make_base, pub):
    f = make_base("n.suvii", SAMPLE, fts=False)
    with open_scroll(f, [pub]) as s:
        assert not s.has_fts
        assert [p for p, _ in s.search("Конституція")] == ["laws/254к/96-вр"]


def test_writer_refuses_existing_file(make_base):
    f = make_base("a.suvii", SAMPLE)
    with pytest.raises(SuviiError):
        Writer(f, collection_id="0b6f3a52-3d1e-4c2a-9a57-6f8d2a1c4e10", title="x", language="uk",
               publisher="x", fields={}, seq=1, source_date="2026-01-01")
