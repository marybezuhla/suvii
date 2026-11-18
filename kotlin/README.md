# Сувій для Kotlin · Suvii for Kotlin

Ядро бібліотеки формату «Сувій» для застосунків на Kotlin (Android 12+ і JVM 17+): ті самі правила, що й еталонна бібліотека в [`python/`](../python), байт у байт.

- `Spec` — сталі, межі й перевірка метаданих (SPEC.md, 4.1, 11);
- `Hashing` — хеш документа, корінь стану, хеш метаданих, корінь латки й повідомлення для підпису (SPEC.md, 9);
- `Signatures` — перевірка підпису ed25519 (BouncyCastle, бо Android 12 не має вбудованого ed25519);
- `SafeHtml` — перевірка безпечної підмножини HTML і текст для пошуку (SPEC.md, 6.2);
- `Scroll` — безпечне відкриття сувою з усіма перевірками розділу 10: заголовок, схема, межі, метадані, підпис; документи, зміст, поля, пошук;
- `Patches` — застосування латки однією транзакцією з перевіркою кореня стану й підпису результату (SPEC.md, 12);
- `Json`, `Fields` — строгий розбір `collection.fields`.

SQLite і zstd дає платформа через два малі інтерфейси (`SqlDatabase`, `Decompressor` у `Platform.kt`): на Android — `sqlite-android` і `zstd-jni`, у тестах на JVM — `sqlite-jdbc` і `zstd-jni`. Так усі правила формату живуть в одному місці й перевіряються один раз.

Тести звіряються з [`testdata/vectors.json`](../testdata) і тестовими сувоями. Сувої — це SQLite, тож для тестів їхні метадані й хеші вивантажено в текст скриптом `python/scripts/export_for_kotlin.py`; CI перевіряє, що вивантаження не застаріло.

```
gradle -p kotlin test
```

---

The core of the Suvii format library for Kotlin (Android 12+, JVM 17+), byte-for-byte the same rules as the reference library in `python/`: constants and metadata checks, hashes and signed messages, ed25519 verification (BouncyCastle), the safe HTML subset, opening a scroll with every check of section 10, reading and searching documents, and applying a patch in one transaction. SQLite and zstd come from the platform through two small interfaces (`Platform.kt`): sqlite-android and zstd-jni on Android, sqlite-jdbc and zstd-jni in the JVM tests. Tests check against `testdata/vectors.json` and the test scrolls, exported to text by `python/scripts/export_for_kotlin.py`; CI checks the export is current.
