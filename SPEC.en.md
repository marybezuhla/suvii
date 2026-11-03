# The Suvii format (`.suvii`) — specification

**Version:** 0.1 (draft)
**Status:** working draft; may change without backward compatibility until version 1.0
**Specification text license:** [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Code of the reference tools and libraries — GPL-3.0-or-later.
**Languages:** [Українська](SPEC.md) (primary) · English (this version). If the versions differ, the Ukrainian version prevails.

*Suvii* (Ukrainian «сувій», pronounced *SOO-viy*) means "scroll".

The key words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are to be interpreted as described in RFC 2119.

---

## 1. What it is and why

Suvii is an open format for **offline collections of text documents** that **can be updated**: legislation, dictionaries, reference works, encyclopedias.

Goals:

1. **Updatability.** A collection can be updated with a small **patch** instead of downloading everything again.
2. **Authenticity.** Every collection and every patch is signed by its publisher. A reader verifies that no one has altered the text.
3. **Compactness.** Texts are compressed with zstd, optionally with a shared dictionary.
4. **Offline search.** A full-text index lives inside the file.
5. **Simplicity and openness.** A file is a plain SQLite 3 database with the schema described here. Any SQLite tool can open it.
6. **Compatibility.** A collection can be exported to ZIM for Kiwix (see section 13).

Out of scope for version 0.1: images and other media, edition history, key rotation, encryption. See section 14.

## 2. Terms

| Term | Meaning |
|---|---|
| **Collection** | A set of documents with one identifier (`collection.id`) and one publisher. |
| **Scroll** | A `.suvii` file. There are two kinds: a **base** or a **patch**. |
| **Base** | The full state of a collection at a given **state number** (`seq`). |
| **Patch** | The changes between two state numbers: new and changed documents, plus deleted paths. |
| **State number** (`seq`) | An integer ≥ 1 that increases with every change to the collection. |
| **Path** | A stable identifier of a document within a collection, e.g. `laws/254к/96-вр`. |
| **Publisher** | Whoever signs the collection's scrolls with their ed25519 key. |
| **Reader** | A program that opens scrolls. |

## 3. The file

- The file **MUST** be an SQLite 3 database.
- `PRAGMA application_id` **MUST** equal `0x53555649` (ASCII `SUVI`, decimal `1398101577`).
- `PRAGMA user_version` **MUST** equal the major version of the format: `0` for versions 0.x, `1` for 1.x.
- The full format version is stored in `meta` under the key `suvii.format` (e.g. `0.1`).
- File extension: `.suvii`. MIME type until registration: `application/x-suvii`.
- A file intended for distribution **SHOULD** be stored with `journal_mode=DELETE`, after `VACUUM`, with no `-wal`/`-journal` files beside it.
- Recommended file names: `<collection>-<language>-<YYYY-MM-DD>.suvii` for a base, `<collection>-<language>-<from_seq>-<to_seq>.patch.suvii` for a patch.

## 4. Schema

All text values are UTF-8 in **NFC** normalization. All date-times are RFC 3339 in UTC (`2026-11-04T12:00:00Z`); dates without time are `YYYY-MM-DD`.

```sql
-- Collection metadata
CREATE TABLE meta (
  key   TEXT PRIMARY KEY NOT NULL,
  value TEXT NOT NULL
) WITHOUT ROWID;

-- Documents
CREATE TABLE docs (
  id       INTEGER PRIMARY KEY,         -- local number, differs between files
  path     TEXT    NOT NULL UNIQUE,     -- stable identifier (section 5)
  title    TEXT    NOT NULL,
  mime     TEXT    NOT NULL,            -- 'text/plain' or 'text/html' (section 6)
  size     INTEGER NOT NULL,            -- uncompressed text length in bytes
  updated  TEXT    NOT NULL,            -- when the document last changed (RFC 3339)
  hash     BLOB    NOT NULL             -- 32 bytes, section 9.1
);

-- Parts of a document's text
CREATE TABLE chunks (
  doc_id   INTEGER NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
  n        INTEGER NOT NULL,            -- 0, 1, 2, … without gaps
  dict_id  INTEGER REFERENCES dicts(id),-- NULL = no dictionary
  data     BLOB    NOT NULL,            -- a zstd frame
  PRIMARY KEY (doc_id, n)
) WITHOUT ROWID;

-- zstd dictionaries
CREATE TABLE dicts (
  id   INTEGER PRIMARY KEY,
  data BLOB NOT NULL
);

-- Document fields for filtering (type, status, date, etc.)
CREATE TABLE facets (
  doc_id INTEGER NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
  key    TEXT    NOT NULL,
  value  TEXT    NOT NULL,
  PRIMARY KEY (doc_id, key, value)
) WITHOUT ROWID;
CREATE INDEX facets_kv ON facets(key, value);

-- Table of contents (parts, articles)
CREATE TABLE toc (
  doc_id INTEGER NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
  ord    INTEGER NOT NULL,              -- order, 0, 1, 2, …
  level  INTEGER NOT NULL,              -- 1 = top level
  anchor TEXT    NOT NULL,              -- value of an id attribute in the text
  title  TEXT    NOT NULL,
  PRIMARY KEY (doc_id, ord)
) WITHOUT ROWID;

-- Relations between documents
CREATE TABLE links (
  doc_id   INTEGER NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
  kind     TEXT    NOT NULL,            -- e.g. 'amends', 'amended_by', 'refers'
  target   TEXT    NOT NULL,            -- target path (may be absent from the collection)
  anchor   TEXT    NOT NULL DEFAULT '',
  PRIMARY KEY (doc_id, kind, target, anchor)
) WITHOUT ROWID;
CREATE INDEX links_target ON links(target);

-- Deleted paths (patches only)
CREATE TABLE tombstones (
  path    TEXT PRIMARY KEY NOT NULL,
  deleted TEXT NOT NULL
) WITHOUT ROWID;

-- Full-text search (optional, section 8)
CREATE VIRTUAL TABLE fts USING fts5(
  title, body,
  content = '',
  contentless_delete = 1,
  tokenize = 'unicode61 remove_diacritics 0'
);
-- fts rowid = docs.id
```

- A file **MUST NOT** contain triggers or views. Other tables and indexes **MAY** be added. A reader **MUST** ignore unknown tables (see section 10).
- In a patch, the `tombstones` table **MAY** be non-empty. In a base it **MUST** be empty.

### 4.1. Required `meta` keys

| Key | Example | Description |
|---|---|---|
| `suvii.format` | `0.1` | Format version. |
| `suvii.kind` | `base` or `patch` | Kind of scroll. |
| `collection.id` | `6f0d…` | Collection UUID (36 characters, lowercase). The same for all bases and patches of the collection. |
| `collection.title` | `Законодавство України` | Title. Translations MAY be added: `collection.title.en`. |
| `collection.language` | `uk` | Language of the documents (BCP 47). |
| `collection.publisher` | `Chynnist` | Publisher. |
| `collection.fields` | JSON, section 7 | Description of the `facets` fields. |
| `state.seq` | `42` | State number of the base. In a patch — the state number **after** applying. |
| `state.created` | `2026-11-04T03:00:00Z` | When this scroll was created. |
| `state.source_date` | `2026-11-03` | The date as of which the data was collected. |
| `sign.alg` | `ed25519` | Signature algorithm. |
| `sign.key` | base64 | Publisher's public key (32 bytes). |
| `sign.sig` | base64 | Signature (64 bytes), section 9. |

Patches only:

| Key | Description |
|---|---|
| `patch.from_seq` | The state number the patch applies to. |
| `patch.to_seq` | The state number after applying (equal to `state.seq`). |
| `patch.state_root` | The expected state root after applying, hex (section 9.2). |
| `patch.base_sig` | The signature of the base that results from applying, base64 (section 9.4). |

Optional: `collection.description`, `collection.homepage`, `collection.license` (license of the data), `collection.source` (where the data comes from), `collection.icon` (SVG, at most 64 KB).

## 5. Paths

- A path is a UTF-8 string in NFC, 1 to 1024 bytes long.
- It consists of segments separated by `/`. A segment is non-empty and is not `.` or `..`.
- No leading or trailing `/`, no control characters (U+0000–U+001F, U+007F), no `\`, `?`, `#`.
- A path **MUST** be stable: the same document keeps the same path in later states of the collection.

## 6. Document text

### 6.1. Compression and chunks

- A document's text is split into `chunks`. Each chunk is a separate zstd frame that decompresses on its own (with the referenced dictionary, if `dict_id` is not NULL).
- A decompressed chunk **MUST NOT** exceed 1 MiB (1,048,576 bytes); a compressed one, 256 KiB (262,144 bytes). The limit exists because Android cannot read database rows larger than 2 MB.
- Chunks are ordered `n = 0, 1, 2, …`. The document text is the concatenation of the decompressed chunks. Chunk boundaries **SHOULD** fall between HTML elements (but a reader MUST handle any boundary correctly, because the text is joined before display).
- The sum of decompressed chunk lengths **MUST** equal `docs.size`.
- A document **MUST NOT** exceed 64 MiB.

### 6.2. Text types

- `text/plain` — plain text, lines separated by `\n`.
- `text/html` — an HTML fragment (no `<html>`, `<head>`, `<body>`) using only the **safe subset**:
  - elements: `p br hr h1 h2 h3 h4 h5 h6 div span blockquote pre code ul ol li dl dt dd table thead tbody tfoot tr th td caption b strong i em u s sub sup small a`;
  - attributes: `id` (any element), `lang`, `dir`, `colspan`, `rowspan`, `href` (only on `a`), `class` (only values prefixed `suvii-`);
  - `href` **MUST** be one of: `#anchor`, `suvii:<path>` or `suvii:<path>#anchor` (links within the collection), `https://…` (external).
  - **MUST NOT** contain: `script`, `style`, `on*` attributes, `style` attributes, `src`, or anything that loads from the network.
- A reader **MUST** reject or strip anything outside this subset, even if the signature is valid. It **SHOULD** ask the person before opening an external link.

## 7. Fields (`facets`)

`collection.fields` is a JSON object describing the keys used in the `facets` table:

```json
{
  "kind":   {"type": "enum", "title": {"uk": "Вид", "en": "Type"},
             "values": {"law": {"uk": "Закон"}, "code": {"uk": "Кодекс"}, "resolution": {"uk": "Постанова"}}},
  "number": {"type": "text", "title": {"uk": "Номер"}},
  "status": {"type": "enum", "title": {"uk": "Стан"},
             "values": {"in_force": {"uk": "Чинний"}, "repealed": {"uk": "Втратив чинність"}}},
  "adopted":{"type": "date", "title": {"uk": "Дата ухвалення"}},
  "edition":{"type": "date", "title": {"uk": "Редакція від"}},
  "issuer": {"type": "text", "title": {"uk": "Видавник"}, "multi": true}
}
```

- Types: `text`, `int` (decimal integer, at most 18 digits), `date` (`YYYY-MM-DD`, years 0001–9999), `bool` (`0`/`1`), `enum` (values only from `values`).
- `multi: true` allows several values of the same key per document.
- Values in `facets` are always text in the given format.

## 8. Search

- The `fts` table is optional. If present, its `rowid` **MUST** equal `docs.id`, and `body` contains the document text without HTML markup.
- If it is absent (for example, to make the file smaller), a reader **MAY** build the index itself.
- A contentless index (`content=''`) cannot be transferred from one file to another, so a patch **does NOT contain** `fts`. When applying a patch, the reader indexes its documents itself (section 12).

## 9. Integrity and signature

Hash: SHA-256. Signature: ed25519 (RFC 8032), pure, without pre-hashing.

Notation: `u32(x)` and `u64(x)` are big-endian unsigned integers of 4 and 8 bytes; `str(s)` = `u32(length in bytes) ‖ UTF-8 bytes`; `‖` is concatenation.

### 9.1. Document hash

```
doc_hash = SHA-256(
  "suvii-doc-1\n"
  ‖ str(path) ‖ str(title) ‖ str(mime) ‖ str(updated)
  ‖ u32(number of facets) ‖ for each (key, value), ordered by key bytes, then value bytes: str(key) ‖ str(value)
  ‖ u32(number of toc)    ‖ for each by ord: u32(level) ‖ str(anchor) ‖ str(title)
  ‖ u32(number of links)  ‖ for each, ordered by bytes of kind, target, anchor: str(kind) ‖ str(target) ‖ str(anchor)
  ‖ u64(size) ‖ decompressed text
)
```

The value is stored in `docs.hash`. Compression and chunking do not affect the hash.

### 9.2. State root

```
state_root = SHA-256(
  "suvii-state-1\n"
  ‖ 16 bytes of collection.id ‖ u64(state.seq) ‖ u64(number of documents)
  ‖ for each document, ordered by path bytes: str(path) ‖ doc_hash
)
```

Computing the root only requires reading `path` and `hash`; texts need not be decompressed.

### 9.3. Metadata hash

```
meta_hash = SHA-256("suvii-meta-1\n" ‖ for each meta key except those prefixed "sign.", ordered by bytes: str(key) ‖ str(value))
```

### 9.4. What is signed

Base:
```
message = "suvii-sig-1\nbase\n" ‖ meta_hash ‖ state_root
```

Patch:
```
patch_root = SHA-256("suvii-patch-1\n"
  ‖ 16 bytes of collection.id ‖ u64(from_seq) ‖ u64(to_seq)
  ‖ u64(number of documents) ‖ for each by path bytes: str(path) ‖ doc_hash
  ‖ u64(number of tombstones) ‖ for each by path bytes: str(path))

message = "suvii-sig-1\npatch\n" ‖ meta_hash ‖ patch_root ‖ expected state_root after applying
```

In addition, a patch carries in `patch.base_sig` a **ready-made signature of the base** that results from applying it: the signature of the base message (above), where `meta_hash` is computed from the patch's metadata without the `patch.*` keys and with `suvii.kind = base`. Thanks to this, an updated base is verified exactly like a freshly downloaded one, and patches need not be kept after applying.

A patch's `meta_hash` is computed from all its keys except `sign.*`; the `patch.base_sig` key is not included either.

### 9.5. Verification

- A reader **MUST** verify the signature with a key it trusts (for example, one built into the app), not only with the key from `sign.key`. The key in the file is useful only for display and for tools.
- When opening a base, a reader **MUST** compute `state_root` and verify the signature.
- Before displaying a document, a reader **SHOULD** verify its `doc_hash`. If the hash does not match, the document is corrupted and must not be shown as authentic.

## 10. Safe opening

A scroll is a file from someone else's hands. A reader **MUST**:

1. Check `application_id` and `user_version`. If the major version is higher than supported, refuse with the explanation "a newer version of the program is needed".
2. Open with `PRAGMA trusted_schema=OFF` and in defensive mode (`SQLITE_DBCONFIG_DEFENSIVE`), and open a distributed file read-only until its signature is verified.
3. Check `sqlite_schema`: no triggers or views; the required tables have exactly the schema described here.
4. Check the limits from section 11 **before** allocating memory for the data.
5. Verify the signature (section 9.5).
6. Treat any error as "the file is corrupted", without crashing and without raw error texts.

## 11. Limits

| What | Limit |
|---|---|
| Path | 1024 bytes |
| Document title | 4096 bytes |
| `mime`, `updated`, facet key and value, anchor, `kind`, `target` | 1024 bytes each |
| `toc` title | 4096 bytes |
| Number of `facets`, `toc`, `links` per document | 10,000 each |
| Chunk: compressed / decompressed | 256 KiB / 1 MiB |
| Decompressed document | 64 MiB |
| zstd dictionary | 1 MiB, at most 256 dictionaries |
| A `meta` value | 1 MiB (except `collection.icon` — 64 KB) |
| Number of documents | 2³¹ − 1 |
| `state.seq` | 1 … 2⁶³ − 1 |

## 12. Applying patches

A patch can be applied to a base if:

- the `collection.id` values match;
- `patch.from_seq` equals the base's `state.seq` (patches may be **cumulative**: from any older state to a newer one; a reader chooses the shortest chain);
- the patch signature is valid.

Applying is **a single transaction**:

1. For each path in `tombstones`, delete the document with that path (together with its chunks, facets, toc, links and its `fts` row).
2. For each document in the patch: delete the document with the same path, if present, and insert the new one with all its chunks, facets, toc and links. If the base has `fts`, add a row for the new document, computing its text without markup. `id` numbers, like dictionary numbers, are assigned anew.
3. Copy the needed dictionaries from the patch (with new numbers).
4. Replace the base's `meta` with the patch's metadata without the `patch.*` keys, with `suvii.kind = base` and `sign.sig = patch.base_sig`.
5. Compute `state_root` and compare it with `patch.state_root`, and verify the updated base's signature (section 9.5). If anything does not match, **roll back the transaction**.

The result is logically identical to the base with number `to_seq` that the publisher would issue.

Dictionaries no longer referenced by any chunk **MAY** be deleted.

## 13. Export to ZIM

The `suvii export-zim` tool converts a base into a standard ZIM:

- each document becomes an entry `A/<path>` (HTML; `text/plain` is wrapped in `<pre>`), titled `title`;
- `suvii:<path>#anchor` links become relative ZIM links;
- `facets` and `toc` are added as a hidden table at the top of the document page and as a separate index page;
- ZIM metadata (`Title`, `Language`, `Creator`, `Publisher`, `Date`, `Description`) is taken from `meta`;
- the ZIM file records `collection.id` and `state.seq`, so it is clear which state it was made from.

ZIM is only a read-only snapshot: the scroll itself is updated, and the ZIM is regenerated.

## 14. Future (not in version 0.1)

- **Media:** a `files` table for images and attachments (needed for Wikipedia).
- **Edition history:** several editions of one document with dates, to show "how it read on a given date".
- **Publisher key rotation:** a signed transition to a new key.
- **Partial collections:** a signed list of paths, allowing a device to hold only part of a collection.
- **Splitting into several files** for very large collections.

## 15. Version compatibility

- Versions `0.x` are drafts; compatibility between them is not guaranteed.
- From `1.0` on: a minor version change (`1.1`, `1.2`) only **adds** optional tables, columns or `meta` keys; a version `1.0` reader opens `1.x` files, ignoring what it does not know. A major version change (`2.0`) changes `user_version`.

## Appendix A. Example: legislation of Ukraine

- `collection.id`: a fixed UUID for the "Chynnist" collection.
- Path: `laws/<document number on zakon.rada.gov.ua>`, e.g. `laws/254к/96-вр` (the Constitution).
- `facets`: `kind`, `number`, `status`, `adopted`, `edition`, `issuer`.
- `toc`: parts, chapters, articles; the anchor is the article number, e.g. `st-10`.
- `links`: `amends` / `amended_by` — amendments between documents.
- `collection.source`: `https://data.rada.gov.ua` (Open Data Portal of the Verkhovna Rada of Ukraine).
- `collection.license`: the Open Data Portal's terms: free use and redistribution with attribution to the source.
