# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json

from conftest import COLLECTION_ID, FIELDS

from suvii import _zstd, open_scroll
from suvii.cli import main


def _write_inputs(tmp_path, seq, docs):
    (tmp_path / f"c{seq}.json").write_text(json.dumps({
        "id": COLLECTION_ID, "title": "CLI", "language": "uk", "publisher": "Test",
        "fields": FIELDS, "seq": seq, "source_date": "2026-11-01", "created": "2026-11-02T00:00:00Z",
    }), encoding="utf-8")
    with open(tmp_path / f"d{seq}.jsonl", "w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")


def test_end_to_end(tmp_path, capsys):
    assert main(["keygen", str(tmp_path / "k")]) == 0
    pub = (tmp_path / "k.pub").read_text().strip()
    a = {"path": "a", "title": "Перший", "updated": "2026-11-01T00:00:00Z", "body": "<p>один</p>",
         "facets": [["kind", "law"]]}
    b = {"path": "b", "title": "Другий", "updated": "2026-11-01T00:00:00Z", "body": "<p>два</p>"}
    b2 = dict(b, body="<p>два, нова редакція</p>", updated="2026-11-02T00:00:00Z")
    _write_inputs(tmp_path, 1, [a, b])
    _write_inputs(tmp_path, 2, [a, b2])
    for seq in (1, 2):
        assert main(["create", "--collection", str(tmp_path / f"c{seq}.json"), "--docs", str(tmp_path / f"d{seq}.jsonl"),
                     "--key", str(tmp_path / "k"), "--level", "3", str(tmp_path / f"b{seq}.suvii")]) == 0
    assert main(["diff", str(tmp_path / "b1.suvii"), str(tmp_path / "b2.suvii"), "--key", str(tmp_path / "k"),
                 "--trust", pub, str(tmp_path / "p.suvii")]) == 0
    assert main(["apply", str(tmp_path / "b1.suvii"), str(tmp_path / "p.suvii"), "--trust", pub]) == 0
    assert main(["cat", str(tmp_path / "b1.suvii"), "b", "--trust", pub]) == 0
    assert "нова редакція" in capsys.readouterr().out
    assert main(["verify", str(tmp_path / "b1.suvii"), "--trust", str(tmp_path / "k.pub")]) == 0


def test_errors_are_short(tmp_path, capsys):
    (tmp_path / "x.suvii").write_bytes(b"not a scroll")
    assert main(["info", str(tmp_path / "x.suvii")]) == 2
    err = capsys.readouterr().err
    assert "not_sqlite" in err and "Traceback" not in err


def test_dictionary(make_base, pub, tmp_path):
    from conftest import doc

    docs = [doc(f"laws/{i}", f"Закон {i}", f"Стаття про право номер {i}: громадяни мають рівні права і свободи.")
            for i in range(300)]
    samples = [d.body_bytes for d in docs]
    dictionary = _zstd.train_dictionary(samples, 4096)
    from suvii import Writer, keys

    key = keys.generate()
    out = tmp_path / "dict.suvii"
    with Writer(out, collection_id=COLLECTION_ID, title="D", language="uk", publisher="T", fields=FIELDS, seq=1,
                source_date="2026-11-01", dictionary=dictionary, level=3) as w:
        for d in docs:
            w.add(d)
        w.finish(key)
    with open_scroll(out, [keys.public_text(key)]) as s:
        assert s.conn.execute("SELECT count(*) FROM dicts").fetchone()[0] == 1
        assert s.verify_all() == []
        assert "номер 42" in s.document("laws/42").body
