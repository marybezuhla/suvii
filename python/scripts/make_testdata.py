# SPDX-License-Identifier: GPL-3.0-or-later
"""Створює testdata/: тестовий ключ, маленькі сувої та контрольні значення хешів.

Запуск з теки python/:  python scripts/make_testdata.py ../testdata
Файли .suvii можуть відрізнятися байтами між версіями zstd, але хеші, корені й підписи — ні.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

from suvii import Document, Link, TocEntry, Writer, hashing, keys, make_patch, open_scroll

# УВАГА: цей ключ лише для тестів. Він публічний — ним НЕ МОЖНА підписувати справжні колекції.
TEST_PRIVATE_KEY = base64.b64encode(bytes(range(32))).decode()

COLLECTION = {
    "id": "0b6f3a52-3d1e-4c2a-9a57-6f8d2a1c4e10",
    "title": "Тестова колекція",
    "language": "uk",
    "publisher": "Suvii test",
    "fields": {
        "kind": {"type": "enum", "title": {"uk": "Вид", "en": "Type"},
                 "values": {"law": {"uk": "Закон"}, "code": {"uk": "Кодекс"}}},
        "status": {"type": "enum", "title": {"uk": "Стан", "en": "Status"},
                   "values": {"in_force": {"uk": "Чинний"}, "repealed": {"uk": "Втратив чинність"}}},
        "adopted": {"type": "date", "title": {"uk": "Дата ухвалення"}},
    },
}


def docs_v1() -> list[Document]:
    return [
        Document(
            path="laws/254к/96-вр",
            title="Конституція України",
            body='<h2 id="st-1">Стаття 1</h2><p>Україна є суверенна і незалежна, демократична, соціальна, правова держава.</p>',
            updated="2026-11-01T00:00:00Z",
            facets=[("status", "in_force"), ("kind", "law"), ("adopted", "1996-06-28")],
            toc=[TocEntry(1, "st-1", "Стаття 1")],
        ),
        Document(
            path="laws/old-1",
            title="Старий закон",
            body="Цей закон втратив чинність.",
            mime="text/plain",
            updated="2026-11-01T00:00:00Z",
            facets=[("kind", "law"), ("status", "repealed")],
            links=[Link("refers", "laws/254к/96-вр", "st-1"), Link("amended_by", "laws/new-1")],
        ),
    ]


def docs_v2() -> list[Document]:
    first = docs_v1()[0]
    return [
        first,
        Document(
            path="laws/new-1",
            title="Новий закон",
            body='<p id="p1">Кожен має право читати закони без інтернету.</p>',
            updated="2026-11-03T00:00:00Z",
            facets=[("kind", "law"), ("status", "in_force")],
        ),
    ]


def build(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    key = keys.private_from_text(TEST_PRIVATE_KEY)
    (out_dir / "test-key.txt").write_text(TEST_PRIVATE_KEY + "\n")
    (out_dir / "test-key.pub").write_text(keys.public_text(key) + "\n")

    files = {}
    for name, seq, docs, created in (("base-1.suvii", 1, docs_v1(), "2026-11-02T00:00:00Z"),
                                     ("base-2.suvii", 2, docs_v2(), "2026-11-04T00:00:00Z")):
        p = out_dir / name
        p.unlink(missing_ok=True)
        with Writer(p, collection_id=COLLECTION["id"], title=COLLECTION["title"], language=COLLECTION["language"],
                    publisher=COLLECTION["publisher"], fields=COLLECTION["fields"], seq=seq,
                    source_date=created[:10], created=created) as w:
            for d in docs:
                w.add(d)
            files[name] = w.finish(key).hex()

    patch = out_dir / "patch-1-2.suvii"
    patch.unlink(missing_ok=True)
    pub = keys.public_text(key)
    with open_scroll(out_dir / "base-1.suvii", [pub]) as a, open_scroll(out_dir / "base-2.suvii", [pub]) as b:
        make_patch(a, b, patch, key)

    # контрольні значення для інших реалізацій
    d = docs_v1()[0]
    with open_scroll(out_dir / "base-1.suvii", [pub]) as s:
        meta = s.meta
    with open_scroll(patch, [pub]) as p:
        pmeta = p.meta
        proot = p.patch_root().hex()
    vectors = {
        "comment": "Контрольні значення для реалізацій формату Suvii 0.1 / test vectors for Suvii 0.1 implementations",
        "public_key": pub,
        "doc": {
            "path": d.path, "title": d.title, "mime": d.mime, "updated": d.updated, "body": d.body,
            "facets": d.facets, "toc": [[t.level, t.anchor, t.title] for t in d.toc], "links": [],
            "doc_hash": hashing.doc_hash(d).hex(),
        },
        "base_1": {
            "state_root": files["base-1.suvii"],
            "meta_hash": hashing.meta_hash(meta).hex(),
            "signature": meta["sign.sig"],
        },
        "patch_1_2": {
            "patch_root": proot,
            "meta_hash": hashing.meta_hash(pmeta).hex(),
            "expected_state_root": pmeta["patch.state_root"],
            "signature": pmeta["sign.sig"],
            "base_sig": pmeta["patch.base_sig"],
        },
        "base_2": {"state_root": files["base-2.suvii"]},
    }
    (out_dir / "vectors.json").write_text(json.dumps(vectors, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "README.md").write_text(
        "# testdata\n\n"
        "Тестові сувої та контрольні значення. Створено скриптом `python/scripts/make_testdata.py`.\n\n"
        "**`test-key.txt` — публічний тестовий ключ. Ним НЕ МОЖНА підписувати справжні колекції.**\n\n"
        "- `base-1.suvii`, `base-2.suvii` — дві основи однієї колекції (стани 1 і 2)\n"
        "- `patch-1-2.suvii` — латка між ними\n"
        "- `vectors.json` — хеш документа, корені стану, хеші метаданих і підписи, які мусить отримати будь-яка реалізація\n\n"
        "Test scrolls and vectors. `test-key.txt` is a public test-only key: never sign real collections with it.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    build(Path(sys.argv[1] if len(sys.argv) > 1 else "../testdata"))
