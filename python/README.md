# suvii (Python)

Еталонні інструменти для формату [«Сувій»](../SPEC.md). *Reference tools for the [Suvii format](../SPEC.en.md).*

```sh
pip install ./python
```

Потрібно Python 3.12+. Залежності: `zstandard`, `cryptography`.

## Команди · Commands

```sh
suvii keygen publisher.key                     # ключ видавця (+ publisher.key.pub)
suvii create --collection collection.json --docs docs.jsonl --key publisher.key out.suvii
suvii info    out.suvii --trust publisher.key.pub
suvii verify  out.suvii --trust publisher.key.pub   # перевірити кожен документ
suvii cat     out.suvii laws/254к/96-вр --trust publisher.key.pub
suvii search  out.suvii "свобода слова" --trust publisher.key.pub
suvii diff    old.suvii new.suvii --key publisher.key patch.suvii
suvii apply   old.suvii patch.suvii --trust publisher.key.pub [--out new.suvii]
```

Без `--trust` команди довіряють ключу з самого файлу й попереджають про це. Читалки так робити **не повинні** (SPEC, розділ 9.5).

### `collection.json`

```json
{
  "id": "0b6f3a52-3d1e-4c2a-9a57-6f8d2a1c4e10",
  "title": "Законодавство України",
  "language": "uk",
  "publisher": "Chynnist",
  "fields": {"status": {"type": "enum", "title": {"uk": "Стан"}, "values": {"in_force": {"uk": "Чинний"}}}},
  "seq": 1,
  "source_date": "2026-11-03",
  "meta": {"collection.source": "https://data.rada.gov.ua"}
}
```

### `docs.jsonl`

Один документ на рядок:

```json
{"path": "laws/254к/96-вр", "title": "Конституція України", "updated": "2026-11-01T00:00:00Z", "mime": "text/html", "body": "<h2 id=\"st-1\">Стаття 1</h2><p>…</p>", "facets": [["status", "in_force"]], "toc": [[1, "st-1", "Стаття 1"]], "links": []}
```

## Як бібліотека · As a library

```python
from suvii import open_scroll

with open_scroll("zakony.suvii", trusted_keys=[PUBLISHER_KEY]) as s:
    for path, title in s.search("пенсія"):
        print(path, title)
    doc = s.document("laws/254к/96-вр")
```

## Тести · Tests

```sh
pip install ./python[test]
cd python && pytest
```

Ліцензія: GPL-3.0-or-later.
