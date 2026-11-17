// SPDX-License-Identifier: GPL-3.0-or-later
package io.github.marybezuhla.suvii

import io.github.marybezuhla.suvii.TestData.hex
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/** Every hash and signature must match the reference library byte for byte (testdata/vectors.json). */
class HashingTest {
    private val publicKey = TestData.str("public_key")
    private val base1 = TestData.scroll("base-1")
    private val patch = TestData.scroll("patch-1-2")
    private val base2 = TestData.scroll("base-2")

    private fun cid(meta: Map<String, String>) = Spec.checkUuid(meta.getValue("collection.id"))

    private fun seq(meta: Map<String, String>) = meta.getValue("state.seq").toLong()

    @Test
    fun documentHash() {
        val doc = TestData.obj("doc")

        @Suppress("UNCHECKED_CAST")
        val facets = (doc["facets"] as List<List<String>>).map { it[0] to it[1] }

        @Suppress("UNCHECKED_CAST")
        val toc = (doc["toc"] as List<List<Any>>).map { TocEntry((it[0] as Long).toInt(), it[1] as String, it[2] as String) }

        @Suppress("UNCHECKED_CAST")
        val links = (doc["links"] as List<List<String>>).map { Link(it[0], it[1], it[2]) }
        val hash = Hashing.docHash(
            doc["path"] as String, doc["title"] as String, doc["mime"] as String, doc["updated"] as String,
            facets, toc, links, (doc["body"] as String).toByteArray(Charsets.UTF_8),
        )
        assertEquals(doc["doc_hash"], hex(hash))
        // Facets are sorted inside: their order in the input must not matter.
        val again = Hashing.docHash(
            doc["path"] as String, doc["title"] as String, doc["mime"] as String, doc["updated"] as String,
            facets.reversed(), toc, links, (doc["body"] as String).toByteArray(Charsets.UTF_8),
        )
        assertArrayEquals(hash, again)
    }

    @Test
    fun baseRootsAndSignature() {
        assertEquals(TestData.str("base_1", "meta_hash"), hex(Hashing.metaHash(base1.meta)))
        val root = Hashing.stateRoot(cid(base1.meta), seq(base1.meta), base1.docs)
        assertEquals(TestData.str("base_1", "state_root"), hex(root))
        assertEquals(TestData.str("base_1", "signature"), base1.meta["sign.sig"])
        assertTrue(Signatures.verify(listOf(publicKey), base1.meta.getValue("sign.sig"), Hashing.baseMessage(base1.meta, root)))
        assertEquals(TestData.str("base_2", "state_root"), hex(Hashing.stateRoot(cid(base2.meta), seq(base2.meta), base2.docs)))
    }

    @Test
    fun patchRootsAndBothSignatures() {
        assertEquals(TestData.str("patch_1_2", "meta_hash"), hex(Hashing.metaHash(patch.meta)))
        val proot = Hashing.patchRoot(cid(patch.meta), 1, 2, patch.docs, patch.tombstones)
        assertEquals(TestData.str("patch_1_2", "patch_root"), hex(proot))
        val expected = hex(TestData.str("patch_1_2", "expected_state_root"))
        assertArrayEquals(expected, hex(patch.meta.getValue("patch.state_root")))
        assertTrue(Signatures.verify(listOf(publicKey), patch.meta.getValue("sign.sig"), Hashing.patchMessage(patch.meta, proot, expected)))

        // After the patch the base is checked as if it had been downloaded whole.
        val after = Hashing.baseMetaAfterPatch(patch.meta)
        assertEquals("base", after["suvii.kind"])
        assertFalse(after.keys.any { it.startsWith("patch.") })
        assertTrue(Signatures.verify(listOf(publicKey), after.getValue("sign.sig"), Hashing.baseMessage(after, expected)))
        assertEquals(base2.meta.filterKeys { it != "state.created" }, after.filterKeys { it != "state.created" })
    }

    @Test
    fun anythingChangedBreaksTheSignature() {
        val root = Hashing.stateRoot(cid(base1.meta), seq(base1.meta), base1.docs)
        val sig = base1.meta.getValue("sign.sig")
        assertFalse(Signatures.verify(listOf(publicKey), sig, Hashing.baseMessage(base1.meta + ("collection.title" to "Інше"), root)))
        assertFalse(Signatures.verify(listOf(publicKey), sig, Hashing.baseMessage(base1.meta, root.copyOf().also { it[0] = 1 })))
        // A key given by the file itself is not trusted unless the app trusts it.
        val otherKey = "A".repeat(43) + "="
        assertFalse(Signatures.verify(listOf(otherKey), sig, Hashing.baseMessage(base1.meta, root)))
        assertTrue(Signatures.verify(listOf(otherKey, publicKey), sig, Hashing.baseMessage(base1.meta, root)))
        for (bad in listOf("", "not base64!", "AAAA", sig.dropLast(4))) {
            assertFalse(Signatures.verify(listOf(publicKey), bad, Hashing.baseMessage(base1.meta, root)))
        }
        assertFalse(Signatures.verify(listOf("short"), sig, Hashing.baseMessage(base1.meta, root)))
    }

    @Test
    fun pathsAreOrderedByUtf8BytesNotUtf16() {
        // "ﬁ" (U+FB01) comes before "😀" in UTF-16 units but after it... no: compare by bytes.
        val bmp = "ﬁ" // EF AC 81
        val astral = "😀" // F0 9F 98 80
        assertTrue(Hashing.BY_UTF8.compare(bmp, astral) < 0)
        val high = "�" // EF BF BD, a BMP code unit larger than the surrogate D83D
        assertTrue(high > astral) // UTF-16 order
        assertTrue(Hashing.BY_UTF8.compare(high, astral) < 0) // byte order
    }

    @Test
    fun unorderedPathsAreRefused() {
        val docs = base1.docs
        assertTrue(docs.size >= 2)
        val e = assertThrows(SuviiException::class.java) { Hashing.stateRoot(cid(base1.meta), 1, docs.reversed()) }
        assertEquals("bad_order", e.code)
        assertThrows(SuviiException::class.java) { Hashing.stateRoot(cid(base1.meta), 1, listOf(docs[0], docs[0])) }
    }
}
