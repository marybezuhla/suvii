// SPDX-License-Identifier: GPL-3.0-or-later
package io.github.marybezuhla.suvii

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class JsonTest {
    @Test
    fun values() {
        assertEquals(
            mapOf("a" to listOf(1L, -2.5, true, false, null), "b" to "й\n\"\u0001"),
            Json.parse(""" { "a": [1, -2.5, true, false, null], "b": "й\n\"\u0001" } """),
        )
    }

    @Test
    fun malformedAndHostileTextIsRefused() {
        for (bad in listOf("", "{", "[1,]", "{\"a\":1,}", "{\"a\" 1}", "\"x", "nul", "01x", "{\"a\":1,\"a\":2}", "[1] 2", "NaN", "1e999", "\"a\u0001\"")) {
            assertThrows(bad, SuviiException::class.java) { Json.parse(bad) }
        }
        assertThrows(SuviiException::class.java) { Json.parse("[".repeat(Json.MAX_DEPTH + 2) + "]".repeat(Json.MAX_DEPTH + 2)) }
    }

    @Test
    fun fieldsOfTheTestScroll() {
        val fields = Fields.parse(TestData.scroll("base-1").meta.getValue("collection.fields"))
        assertEquals("enum", fields.getValue("kind").type)
        assertEquals("Закон", fields.getValue("kind").values.getValue("law")["uk"])
        assertThrows(SuviiException::class.java) { Fields.parse("""{"x": {"type": "colour"}}""") }
        assertThrows(SuviiException::class.java) { Fields.parse("""{"x": {"type": "enum"}}""") }
        assertThrows(SuviiException::class.java) { Fields.parse("[]") }
    }
}
