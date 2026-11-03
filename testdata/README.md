# testdata

Тестові сувої та контрольні значення. Створено скриптом `python/scripts/make_testdata.py`.

**`test-key.txt` — публічний тестовий ключ. Ним НЕ МОЖНА підписувати справжні колекції.**

- `base-1.suvii`, `base-2.suvii` — дві основи однієї колекції (стани 1 і 2)
- `patch-1-2.suvii` — латка між ними
- `vectors.json` — хеш документа, корені стану, хеші метаданих і підписи, які мусить отримати будь-яка реалізація

Test scrolls and vectors. `test-key.txt` is a public test-only key: never sign real collections with it.
