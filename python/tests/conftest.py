# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pytest

from suvii import Document, Link, TocEntry, Writer, keys

COLLECTION_ID = "0b6f3a52-3d1e-4c2a-9a57-6f8d2a1c4e10"
FIELDS = {
    "kind": {"type": "enum", "title": {"uk": "Вид"}, "values": {"law": {"uk": "Закон"}, "code": {"uk": "Кодекс"}}},
    "status": {"type": "enum", "title": {"uk": "Стан"},
               "values": {"in_force": {"uk": "Чинний"}, "repealed": {"uk": "Втратив чинність"}}},
    "adopted": {"type": "date", "title": {"uk": "Дата ухвалення"}},
    "issuer": {"type": "text", "title": {"uk": "Видавник"}, "multi": True},
}


def doc(path: str, title: str, text: str, updated: str = "2026-11-01T00:00:00Z", **kw) -> Document:
    body = f'<h2 id="st-1">Стаття 1</h2><p>{text}</p>'
    return Document(
        path=path,
        title=title,
        body=body,
        updated=updated,
        facets=kw.get("facets", [("kind", "law"), ("status", "in_force")]),
        toc=[TocEntry(1, "st-1", "Стаття 1")],
        links=kw.get("links", []),
    )


@pytest.fixture
def key():
    return keys.generate()


@pytest.fixture
def pub(key):
    return keys.public_text(key)


@pytest.fixture
def make_base(tmp_path, key):
    def _make(name: str, docs: list[Document], seq: int = 1, fts: bool = True, **kw):
        out = tmp_path / name
        with Writer(
            out,
            collection_id=COLLECTION_ID,
            title="Тестова колекція",
            language="uk",
            publisher="Test",
            fields=FIELDS,
            seq=seq,
            source_date="2026-11-01",
            created="2026-11-02T00:00:00Z",
            fts=fts,
            level=kw.get("level", 3),
        ) as w:
            for d in docs:
                w.add(d)
            w.finish(kw.get("key", key))
        return out

    return _make


SAMPLE = [
    doc("laws/254к/96-вр", "Конституція України", "Україна є суверенна і незалежна, демократична, соціальна, правова держава."),
    doc("laws/2341-14", "Кримінальний кодекс України", "Кримінальний кодекс має своїм завданням правове забезпечення охорони прав і свобод людини.",
        facets=[("kind", "code"), ("status", "in_force"), ("issuer", "Верховна Рада України")],
        links=[Link("refers", "laws/254к/96-вр", "st-1")]),
    doc("laws/old-1", "Старий закон", "Цей закон втратив чинність.", facets=[("kind", "law"), ("status", "repealed")]),
]
