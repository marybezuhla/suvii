// SPDX-License-Identifier: GPL-3.0-or-later
package io.github.marybezuhla.suvii

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/** Reading and patching the test scrolls of testdata/ exactly as the reference library does. */
class ScrollTest {
    @get:Rule
    val tmp = TemporaryFolder()

    private val key = TestData.str("public_key")
    private val testdata = generateSequence(File("").absoluteFile) { it.parentFile }.first { File(it, "testdata/base-1.suvii").exists() }
        .let { File(it, "testdata") }

    private fun copy(name: String): File = File(testdata, name).copyTo(File(tmp.newFolder(), name))

    private fun code(block: () -> Unit): String = assertThrows(SuviiException::class.java) { block() }.code

    private fun <T> withScroll(file: File, writable: Boolean = false, verify: Boolean = true, block: (Scroll) -> T): T {
        val (scroll, db) = openScroll(file, listOf(key), writable, verify)
        return db.use { block(scroll) }
    }

    @Test
    fun theTestBaseOpensAndEveryDocumentIsWhole() = withScroll(File(testdata, "base-1.suvii")) { scroll ->
        assertEquals("base", scroll.kind)
        assertEquals(1L, scroll.seq)
        assertEquals(TestData.str("base_1", "state_root"), TestData.hex(scroll.stateRoot()))
        assertEquals(emptyList<String>(), scroll.verifyAll())
        assertTrue(scroll.count() >= 2)
        assertTrue(scroll.fields.isNotEmpty())
        val vector = TestData.obj("doc")
        val doc = scroll.document(vector["path"] as String)
        assertEquals(vector["title"], doc.title)
        assertEquals(vector["body"], doc.body)
    }

    @Test
    fun searchFindsWordsByTheirBeginning() = withScroll(File(testdata, "base-1.suvii")) { scroll ->
        val path = TestData.str("doc", "path")
        assertTrue(scroll.hasFts)
        assertTrue(scroll.search("суверен").any { it.first == path })
        assertEquals(emptyList<Pair<String, String>>(), scroll.search("   "))
        assertEquals(emptyList<Pair<String, String>>(), scroll.search("неіснуючеслово"))
    }

    @Test
    fun patchTurnsBaseOneIntoBaseTwo() {
        val base = copy("base-1.suvii")
        val expected = withScroll(File(testdata, "base-2.suvii")) { it.stateRoot() }
        val (patch, patchDb) = openScroll(File(testdata, "patch-1-2.suvii"), listOf(key))
        patchDb.use {
            withScroll(base, writable = true) { scroll -> assertEquals(2L, Patches.apply(scroll, patch, listOf(key))) }
        }
        withScroll(base) { scroll ->
            // Opened anew: the patched base passes every check a downloaded one would.
            assertEquals(2L, scroll.seq)
            assertArrayEquals(expected, scroll.stateRoot())
            assertEquals(emptyList<String>(), scroll.verifyAll())
            assertEquals("base", scroll.kind)
        }
    }

    @Test
    fun patchForAnotherStateIsRefusedAndChangesNothing() {
        val base = copy("base-2.suvii")
        val before = base.readBytes()
        val (patch, patchDb) = openScroll(File(testdata, "patch-1-2.suvii"), listOf(key))
        patchDb.use {
            withScroll(base, writable = true) { scroll -> assertEquals("wrong_base_seq", code { Patches.apply(scroll, patch, listOf(key)) }) }
        }
        assertArrayEquals(before, base.readBytes())
    }

    @Test
    fun failedPatchIsRolledBack() {
        val base = copy("base-1.suvii")
        // An extra document the publisher never had: the state after the patch cannot match.
        JdbcDatabase(base, writable = true).use { db ->
            db.execute("INSERT INTO docs(path, title, mime, size, updated, hash) VALUES ('extra', 'x', 'text/plain', 0, '2026-01-01T00:00:00Z', zeroblob(32))")
        }
        val (patch, patchDb) = openScroll(File(testdata, "patch-1-2.suvii"), listOf(key))
        patchDb.use {
            withScroll(base, writable = true, verify = false) { scroll ->
                val count = scroll.count()
                assertEquals("state_root_mismatch", code { Patches.apply(scroll, patch, listOf(key)) })
                assertEquals(1L, scroll.seq)
                assertEquals(count, scroll.count())
            }
        }
        withScroll(base, verify = false) { scroll ->
            assertEquals("1", scroll.meta["state.seq"])
            assertEquals("base", scroll.meta["suvii.kind"])
        }
    }

    @Test
    fun keysThatAreNotTrustedOpenNothing() {
        val file = File(testdata, "base-1.suvii")
        val header = file.inputStream().use { it.readNBytes(100) }
        JdbcDatabase(file, writable = false).use { db ->
            assertEquals("bad_signature", code { Scroll.open(header, db, JvmZstd, listOf("A".repeat(43) + "=")) })
            assertEquals("no_trusted_key", code { Scroll.open(header, db, JvmZstd, emptyList()) })
        }
    }

    @Test
    fun changedTextIsCaughtByTheDocumentHash() {
        val base = copy("base-1.suvii")
        val path = TestData.str("doc", "path")
        JdbcDatabase(base, writable = true).use { db -> db.execute("UPDATE docs SET title = 'Інша назва' WHERE path = ?", listOf(path)) }
        withScroll(base) { scroll ->
            // The signature covers stored hashes, so the file still opens; the document does not.
            assertEquals("bad_doc_hash", code { scroll.document(path) })
            assertTrue(scroll.verifyAll().single().endsWith("bad_doc_hash"))
        }
    }

    @Test
    fun damagedChunkIsCorrupt() {
        val base = copy("base-1.suvii")
        JdbcDatabase(base, writable = true).use { db -> db.execute("UPDATE chunks SET data = X'28B52FFD0000'") }
        withScroll(base) { scroll -> assertTrue(scroll.verifyAll().all { it.endsWith("corrupt") }) }
    }

    @Test
    fun forbiddenSchemaIsRefused() {
        for (sql in listOf(
            "CREATE TRIGGER t AFTER INSERT ON meta BEGIN SELECT 1; END",
            "CREATE VIEW v AS SELECT 1",
            "CREATE TABLE extra(x)",
        )) {
            val base = copy("base-1.suvii")
            JdbcDatabase(base, writable = true).use { db -> db.execute(sql) }
            val expected = if (sql.startsWith("CREATE TABLE")) null else "forbidden_schema"
            if (expected == null) {
                withScroll(base) { } // an extra table is allowed, as in the reference library
            } else {
                assertEquals(sql, expected, code { withScroll(base) { } })
            }
        }
        val base = copy("base-1.suvii")
        JdbcDatabase(base, writable = true).use { db -> db.execute("ALTER TABLE docs ADD COLUMN extra TEXT") }
        assertEquals("bad_schema", code { withScroll(base) { } })
    }

    @Test
    fun valuesOverTheLimitsAreRefusedBeforeReading() {
        val base = copy("base-1.suvii")
        JdbcDatabase(base, writable = true).use { db -> db.execute("UPDATE toc SET level = 99") }
        assertEquals("limit_exceeded", code { withScroll(base) { } })
    }

    @Test
    fun headerIsCheckedBeforeSqlite() {
        val header = File(testdata, "base-1.suvii").inputStream().use { it.readNBytes(100) }
        Scroll.checkHeader(header)
        assertEquals("not_sqlite", code { Scroll.checkHeader(ByteArray(100)) })
        assertEquals("not_sqlite", code { Scroll.checkHeader(header.copyOf(50)) })
        assertEquals("not_suvii", code { Scroll.checkHeader(header.copyOf().also { it[71] = 0 }) })
        assertEquals("unsupported_version", code { Scroll.checkHeader(header.copyOf().also { it[63] = 1 }) })
    }
}
