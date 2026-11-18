// SPDX-License-Identifier: GPL-3.0-or-later
package io.github.marybezuhla.suvii

/**
 * A small strict JSON reader for metadata such as `collection.fields`. Objects become
 * [LinkedHashMap], arrays [List], numbers [Long] or [Double]. Anything malformed, too deep or too
 * large is refused, because the text comes from a file of unknown origin.
 */
object Json {
    const val MAX_DEPTH = 32
    const val MAX_CHARS = Spec.MAX_META_VALUE

    fun parse(text: String): Any? {
        if (text.length > MAX_CHARS) throw SuviiException("bad_json", "too long")
        val reader = Reader(text)
        val value = reader.value(0)
        reader.space()
        if (!reader.atEnd()) throw SuviiException("bad_json", "trailing data")
        return value
    }

    private class Reader(private val s: String) {
        private var i = 0

        fun atEnd() = i >= s.length

        private fun fail(what: String): Nothing = throw SuviiException("bad_json", "$what at $i")

        fun space() {
            while (i < s.length && s[i] in " \t\r\n") i++
        }

        private fun expect(c: Char) {
            if (i >= s.length || s[i] != c) fail("expected '$c'")
            i++
        }

        fun value(depth: Int): Any? {
            if (depth > MAX_DEPTH) fail("too deep")
            space()
            if (atEnd()) fail("unexpected end")
            return when (s[i]) {
                '{' -> obj(depth)
                '[' -> array(depth)
                '"' -> string()
                't' -> literal("true", true)
                'f' -> literal("false", false)
                'n' -> literal("null", null)
                else -> number()
            }
        }

        private fun literal(word: String, value: Any?): Any? {
            if (!s.startsWith(word, i)) fail("bad literal")
            i += word.length
            return value
        }

        private fun obj(depth: Int): Map<String, Any?> {
            expect('{')
            val out = LinkedHashMap<String, Any?>()
            space()
            if (s.getOrNull(i) == '}') return out.also { i++ }
            while (true) {
                space()
                val key = string()
                if (key in out) fail("repeated key")
                space()
                expect(':')
                out[key] = value(depth + 1)
                space()
                when (s.getOrNull(i)) {
                    ',' -> i++
                    '}' -> return out.also { i++ }
                    else -> fail("expected ',' or '}'")
                }
            }
        }

        private fun array(depth: Int): List<Any?> {
            expect('[')
            val out = mutableListOf<Any?>()
            space()
            if (s.getOrNull(i) == ']') return out.also { i++ }
            while (true) {
                out += value(depth + 1)
                space()
                when (s.getOrNull(i)) {
                    ',' -> i++
                    ']' -> return out.also { i++ }
                    else -> fail("expected ',' or ']'")
                }
            }
        }

        private fun string(): String {
            expect('"')
            val out = StringBuilder()
            while (true) {
                if (atEnd()) fail("unfinished string")
                val c = s[i++]
                when {
                    c == '"' -> return out.toString()
                    c < ' ' -> fail("control character in string")
                    c != '\\' -> out.append(c)
                    else -> {
                        if (atEnd()) fail("unfinished escape")
                        when (val e = s[i++]) {
                            '"', '\\', '/' -> out.append(e)
                            'b' -> out.append('\b')
                            'f' -> out.append('\u000c')
                            'n' -> out.append('\n')
                            'r' -> out.append('\r')
                            't' -> out.append('\t')
                            'u' -> {
                                val hex = s.substring(i, minOf(i + 4, s.length))
                                val code = hex.takeIf { it.length == 4 }?.toIntOrNull(16) ?: fail("bad \\u escape")
                                out.append(code.toChar())
                                i += 4
                            }
                            else -> fail("bad escape")
                        }
                    }
                }
            }
        }

        private fun number(): Number {
            val start = i
            if (s.getOrNull(i) == '-') i++
            while (i < s.length && (s[i].isDigit() || s[i] in ".eE+-")) i++
            val text = s.substring(start, i)
            if (text.isEmpty() || text == "-") fail("bad value")
            return text.toLongOrNull() ?: text.toDoubleOrNull()?.takeIf { it.isFinite() } ?: fail("bad number")
        }
    }
}
