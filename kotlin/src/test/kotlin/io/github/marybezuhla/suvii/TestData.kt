// SPDX-License-Identifier: GPL-3.0-or-later
package io.github.marybezuhla.suvii

import java.io.File
import java.util.Base64

/** Reads the shared test data of the repository: testdata/vectors.json and the exported scrolls. */
object TestData {
    private val root = generateSequence(File("").absoluteFile) { it.parentFile }.first { File(it, "testdata/vectors.json").exists() }

    val vectors: Map<String, Any?> by lazy {
        @Suppress("UNCHECKED_CAST")
        Json(File(root, "testdata/vectors.json").readText()).parse() as Map<String, Any?>
    }

    @Suppress("UNCHECKED_CAST")
    fun obj(vararg keys: String): Map<String, Any?> = keys.fold(vectors) { o, k -> o[k] as Map<String, Any?> }

    fun str(vararg keys: String): String = obj(*keys.dropLast(1).toTypedArray())[keys.last()] as String

    class Scroll(val meta: Map<String, String>, val docs: List<Pair<String, ByteArray>>, val tombstones: List<String>)

    /** One of the scrolls exported by python/scripts/export_for_kotlin.py. */
    fun scroll(name: String): Scroll {
        val meta = mutableMapOf<String, String>()
        val docs = mutableListOf<Pair<String, ByteArray>>()
        val tombs = mutableListOf<String>()
        fun text(b64: String) = String(Base64.getDecoder().decode(b64), Charsets.UTF_8)
        for (line in File(root, "kotlin/src/test/resources/$name.txt").readLines().filter { it.isNotEmpty() }) {
            val f = line.split('\t')
            when (f[0]) {
                "meta" -> meta[f[1]] = text(f[2])
                "doc" -> docs += text(f[1]) to hex(f[2])
                "tomb" -> tombs += text(f[1])
            }
        }
        return Scroll(meta, docs, tombs)
    }

    fun hex(text: String): ByteArray = ByteArray(text.length / 2) { text.substring(2 * it, 2 * it + 2).toInt(16).toByte() }

    fun hex(bytes: ByteArray): String = bytes.joinToString("") { "%02x".format(it) }
}

/** Just enough JSON for the test vectors; the library itself does not read JSON. */
private class Json(private val s: String) {
    private var i = 0

    fun parse(): Any? = value().also { space(); require(i == s.length) { "trailing data" } }

    private fun space() {
        while (i < s.length && s[i].isWhitespace()) i++
    }

    private fun value(): Any? {
        space()
        return when (s[i]) {
            '{' -> {
                i++
                val out = linkedMapOf<String, Any?>()
                space()
                if (s[i] == '}') return out.also { i++ }
                while (true) {
                    space()
                    val key = string()
                    space()
                    require(s[i++] == ':')
                    out[key] = value()
                    space()
                    if (s[i++] == '}') return out
                }
                @Suppress("UNREACHABLE_CODE") out
            }
            '[' -> {
                i++
                val out = mutableListOf<Any?>()
                space()
                if (s[i] == ']') return out.also { i++ }
                while (true) {
                    out += value()
                    space()
                    if (s[i++] == ']') return out
                }
                @Suppress("UNREACHABLE_CODE") out
            }
            '"' -> string()
            't' -> true.also { i += 4 }
            'f' -> false.also { i += 5 }
            'n' -> null.also { i += 4 }
            else -> {
                val start = i
                while (i < s.length && (s[i].isDigit() || s[i] in "+-.eE")) i++
                s.substring(start, i).toLong()
            }
        }
    }

    private fun string(): String {
        require(s[i++] == '"')
        val out = StringBuilder()
        while (true) {
            val c = s[i++]
            when (c) {
                '"' -> return out.toString()
                '\\' -> when (val e = s[i++]) {
                    'n' -> out.append('\n')
                    't' -> out.append('\t')
                    'r' -> out.append('\r')
                    'b' -> out.append('\b')
                    'f' -> out.append('\u000c')
                    'u' -> out.append(s.substring(i, i + 4).toInt(16).toChar()).also { i += 4 }
                    else -> out.append(e)
                }
                else -> out.append(c)
            }
        }
    }
}
