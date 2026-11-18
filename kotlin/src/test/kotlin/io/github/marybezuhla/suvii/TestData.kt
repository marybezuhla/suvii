// SPDX-License-Identifier: GPL-3.0-or-later
package io.github.marybezuhla.suvii

import java.io.File
import java.util.Base64

/** Reads the shared test data of the repository: testdata/vectors.json and the exported scrolls. */
object TestData {
    private val root = generateSequence(File("").absoluteFile) { it.parentFile }.first { File(it, "testdata/vectors.json").exists() }

    val vectors: Map<String, Any?> by lazy {
        @Suppress("UNCHECKED_CAST")
        Json.parse(File(root, "testdata/vectors.json").readText()) as Map<String, Any?>
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
