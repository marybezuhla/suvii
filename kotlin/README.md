# Сувій для Kotlin · Suvii for Kotlin

Ядро бібліотеки формату «Сувій» для застосунків на Kotlin (Android 12+ і JVM 17+): ті самі правила, що й еталонна бібліотека в [`python/`](../python), байт у байт.

- `Spec` — сталі, межі й перевірка метаданих (SPEC.md, 4.1, 11);
- `Hashing` — хеш документа, корінь стану, хеш метаданих, корінь латки й повідомлення для підпису (SPEC.md, 9);
- `Signatures` — перевірка підпису ed25519 (BouncyCastle, бо Android 12 не має вбудованого ed25519);
- `SafeHtml` — перевірка безпечної підмножини HTML і текст для пошуку (SPEC.md, 6.2).

Читання самого файлу (SQLite, zstd) — окремий шар для Android, ще не написаний.

Тести звіряються з [`testdata/vectors.json`](../testdata) і тестовими сувоями. Сувої — це SQLite, тож для тестів їхні метадані й хеші вивантажено в текст скриптом `python/scripts/export_for_kotlin.py`; CI перевіряє, що вивантаження не застаріло.

```
gradle -p kotlin test
```

---

The core of the Suvii format library for Kotlin (Android 12+, JVM 17+), byte-for-byte the same rules as the reference library in `python/`: constants and metadata checks, hashes and signed messages, ed25519 verification (BouncyCastle), and the safe HTML subset. Reading the file itself (SQLite, zstd) is a separate Android layer, not written yet. Tests check against `testdata/vectors.json` and the test scrolls, exported to text by `python/scripts/export_for_kotlin.py`; CI checks the export is current.
