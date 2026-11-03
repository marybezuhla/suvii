# Сувій · Suvii

**Відкритий формат для офлайн-колекцій текстів, які можна оновлювати.**
Законодавство, словники, довідники, енциклопедії — в одному файлі, з пошуком, без інтернету, з невеликими підписаними оновленнями.

*An open format for offline, updatable collections of text documents.* [English below](#english).

> **Стан:** чернетка 0.1. Формат ще може змінюватися.

## Що вміє

- **Оновлюється латками.** Не треба качати всю колекцію наново, лише зміни.
- **Підписаний.** Кожна колекція й латка підписані видавцем (ed25519), тож читалка перевіряє, що текст ніхто не підмінив.
- **Компактний.** Тексти стиснуті zstd.
- **Пошук офлайн.** Повнотекстовий індекс у самому файлі.
- **Простий.** Файл `.suvii` — звичайна база SQLite 3 з опублікованою схемою.
- **Сумісний.** Експорт у ZIM для Kiwix.

## Документи

- [Специфікація (українською)](SPEC.md) — основна версія
- [Specification (English)](SPEC.en.md)

## Інструменти

- [`python/`](python/) — еталонна бібліотека й командний рядок: створити сувій, перевірити, шукати, зробити й застосувати латку.
- [`testdata/`](testdata/) — тестові сувої та контрольні значення хешів для інших реалізацій.
- Бібліотека для Android/Kotlin — у розробці.

## Хто використовує

- [Чинність](https://github.com/Marybezu/chynnist) — законодавство України офлайн для Android (у розробці).

## Ліцензія

- Текст специфікації: [CC BY-SA 4.0](LICENSE-SPEC).
- Код інструментів і бібліотек: [GPL-3.0-or-later](LICENSE).

Програму надано «як є», без жодних гарантій.

---

## English

**Suvii** (Ukrainian «сувій», *scroll*) is an open format for offline collections of text documents that can be updated: legislation, dictionaries, reference works, encyclopedias.

- **Updatable with patches** — download only the changes, not the whole collection.
- **Signed** — every collection and patch is signed by its publisher (ed25519).
- **Compact** — texts are compressed with zstd.
- **Offline search** — a full-text index inside the file.
- **Simple** — a `.suvii` file is a plain SQLite 3 database with a published schema.
- **Compatible** — export to ZIM for Kiwix.

> **Status:** draft 0.1. The format may still change.

**Documents:** [Specification (Ukrainian, primary)](SPEC.md) · [Specification (English)](SPEC.en.md)

**Tools:** [`python/`](python/) — reference library and CLI (create, verify, search, diff, apply) · [`testdata/`](testdata/) — test scrolls and hash vectors · Android/Kotlin library — in progress.

**Used by:** [Chynnist](https://github.com/Marybezu/chynnist) — Ukrainian legislation offline for Android (in development).

**License:** specification text under [CC BY-SA 4.0](LICENSE-SPEC); code of the tools and libraries under [GPL-3.0-or-later](LICENSE). Provided "as is", without any warranty.
