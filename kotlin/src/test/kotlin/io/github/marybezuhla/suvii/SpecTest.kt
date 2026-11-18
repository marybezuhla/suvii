// SPDX-License-Identifier: GPL-3.0-or-later
package io.github.marybezuhla.suvii

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class SpecTest {
    private fun code(block: () -> Unit): String = assertThrows(SuviiException::class.java) { block() }.code

    @Test
    fun metadataOfTheTestScrolls() {
        for (name in listOf("base-1", "patch-1-2", "base-2")) Spec.checkMeta(TestData.scroll(name).meta)
    }

    @Test
    fun badMetadata() {
        val base = TestData.scroll("base-1").meta
        val patch = TestData.scroll("patch-1-2").meta
        assertEquals("missing_meta", code { Spec.checkMeta(base - "sign.sig") })
        assertEquals("unsupported_version", code { Spec.checkMeta(base + ("suvii.format" to "1.0")) })
        assertEquals("bad_meta", code { Spec.checkMeta(base + ("suvii.format" to "zero")) })
        assertEquals("bad_meta", code { Spec.checkMeta(base + ("suvii.kind" to "other")) })
        assertEquals("bad_meta", code { Spec.checkMeta(base + ("sign.alg" to "rsa")) })
        assertEquals("bad_collection_id", code { Spec.checkMeta(base + ("collection.id" to "0B6F3A52-3D1E-4C2A-9A57-6F8D2A1C4E10")) })
        assertEquals("bad_seq", code { Spec.checkMeta(base + ("state.seq" to "0")) })
        assertEquals("bad_seq", code { Spec.checkMeta(base + ("state.seq" to "99999999999999999999")) })
        assertEquals("bad_datetime", code { Spec.checkMeta(base + ("state.created" to "2026-02-30T00:00:00Z")) })
        assertEquals("bad_date", code { Spec.checkMeta(base + ("state.source_date" to "2026-13-01")) })
        assertEquals("limit_exceeded", code { Spec.checkMeta(base + ("collection.icon" to "x".repeat(Spec.MAX_ICON + 1))) })
        assertEquals("missing_meta", code { Spec.checkMeta(patch - "patch.base_sig") })
        assertEquals("bad_meta", code { Spec.checkMeta(patch + ("patch.from_seq" to "2")) })
        assertEquals("bad_meta", code { Spec.checkMeta(patch + ("patch.state_root" to "ABC")) })
    }

    @Test
    fun paths() {
        Spec.checkPath("laws/254к/96-вр")
        for (bad in listOf("", "/a", "a/", "a//b", "a/./b", "a/../b", "a?b", "a#b", "a\\b", "a\u0000b", "й")) {
            assertThrows(bad, SuviiException::class.java) { Spec.checkPath(bad) }
        }
        assertEquals("too_long", code { Spec.checkPath("a".repeat(Spec.MAX_PATH + 1)) })
    }

    @Test
    fun numbersAndDates() {
        assertEquals(Long.MAX_VALUE, Spec.checkSeq(Long.MAX_VALUE.toString()))
        assertEquals("bad_seq", code { Spec.checkSeq("9223372036854775808") })
        assertEquals("bad_seq", code { Spec.checkSeq("01") })
        Spec.checkDate("2024-02-29", "d")
        assertEquals("bad_date", code { Spec.checkDate("2023-02-29", "d") })
        Spec.checkDateTime("2026-11-01T23:59:59Z", "t")
        assertEquals("bad_datetime", code { Spec.checkDateTime("2026-11-01 23:59:59", "t") })
        assertEquals(16, Spec.checkUuid("8e3b6c1a-5d2f-4b7e-9a41-2c6f0d8e7b53").size)
    }
}
