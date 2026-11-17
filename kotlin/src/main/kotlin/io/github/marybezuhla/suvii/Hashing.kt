// SPDX-License-Identifier: GPL-3.0-or-later
package io.github.marybezuhla.suvii

import java.io.ByteArrayOutputStream
import java.security.MessageDigest

/** One entry of a document's table of contents. */
data class TocEntry(val level: Int, val anchor: String, val title: String)

/** A link from a document to another one (SPEC.md, 4, table `links`). */
data class Link(val kind: String, val target: String, val anchor: String = "")

/**
 * Hashes and signed messages of SPEC.md, section 9. Every byte here must match the reference
 * library in python/; the tests check it against testdata/vectors.json.
 */
object Hashing {
    private val BY_BYTES = Comparator<ByteArray> { a, b ->
        val n = minOf(a.size, b.size)
        for (i in 0 until n) {
            val d = (a[i].toInt() and 0xff) - (b[i].toInt() and 0xff)
            if (d != 0) return@Comparator d
        }
        a.size - b.size
    }

    private fun utf8(text: String) = text.toByteArray(Charsets.UTF_8)

    /** Orders strings by their UTF-8 bytes, as the specification requires (not by UTF-16 units). */
    val BY_UTF8 = Comparator<String> { a, b -> BY_BYTES.compare(utf8(a), utf8(b)) }

    private class Writer(prefix: String) {
        val digest: MessageDigest = MessageDigest.getInstance("SHA-256").apply { update(prefix.toByteArray(Charsets.US_ASCII)) }

        fun u32(value: Int) = apply { digest.update(ByteArray(4) { (value ushr (24 - 8 * it)).toByte() }) }

        fun u64(value: Long) = apply { digest.update(ByteArray(8) { (value ushr (56 - 8 * it)).toByte() }) }

        fun s(text: String) = apply {
            val bytes = utf8(text)
            u32(bytes.size)
            digest.update(bytes)
        }

        fun raw(bytes: ByteArray) = apply { digest.update(bytes) }

        fun finish(): ByteArray = digest.digest()
    }

    fun docHash(
        path: String,
        title: String,
        mime: String,
        updated: String,
        facets: List<Pair<String, String>>,
        toc: List<TocEntry>,
        links: List<Link>,
        body: ByteArray,
    ): ByteArray {
        val w = Writer("suvii-doc-1\n").s(path).s(title).s(mime).s(updated)
        val sortedFacets = facets.sortedWith(compareBy(BY_UTF8) { it: Pair<String, String> -> it.first }.thenBy(BY_UTF8) { it.second })
        w.u32(sortedFacets.size)
        for ((key, value) in sortedFacets) w.s(key).s(value)
        w.u32(toc.size)
        for (entry in toc) w.u32(entry.level).s(entry.anchor).s(entry.title)
        val sortedLinks = links.sortedWith(
            compareBy(BY_UTF8) { it: Link -> it.kind }.thenBy(BY_UTF8) { it.target }.thenBy(BY_UTF8) { it.anchor },
        )
        w.u32(sortedLinks.size)
        for (link in sortedLinks) w.s(link.kind).s(link.target).s(link.anchor)
        return w.u64(body.size.toLong()).raw(body).finish()
    }

    /** [pathHashes] must already be ordered by the UTF-8 bytes of the path, without repeats. */
    fun stateRoot(collectionId: ByteArray, seq: Long, pathHashes: List<Pair<String, ByteArray>>): ByteArray {
        val w = Writer("suvii-state-1\n").raw(collectionId).u64(seq).u64(pathHashes.size.toLong())
        var previous: ByteArray? = null
        for ((path, hash) in pathHashes) {
            val bytes = utf8(path)
            if (previous != null && BY_BYTES.compare(bytes, previous) <= 0) throw SuviiException("bad_order", path)
            previous = bytes
            w.s(path).raw(hash)
        }
        return w.finish()
    }

    /** Every key except `sign.*` and `patch.base_sig`, ordered by bytes (SPEC.md, 9.3). */
    fun metaHash(meta: Map<String, String>): ByteArray {
        val w = Writer("suvii-meta-1\n")
        meta.keys.filter { !it.startsWith("sign.") && it != "patch.base_sig" }.sortedWith(BY_UTF8)
            .forEach { w.s(it).s(meta.getValue(it)) }
        return w.finish()
    }

    fun patchRoot(
        collectionId: ByteArray,
        fromSeq: Long,
        toSeq: Long,
        pathHashes: List<Pair<String, ByteArray>>,
        tombstones: List<String>,
    ): ByteArray {
        val w = Writer("suvii-patch-1\n").raw(collectionId).u64(fromSeq).u64(toSeq).u64(pathHashes.size.toLong())
        for ((path, hash) in pathHashes.sortedWith(compareBy(BY_UTF8) { it.first })) w.s(path).raw(hash)
        w.u64(tombstones.size.toLong())
        for (path in tombstones.sortedWith(BY_UTF8)) w.s(path)
        return w.finish()
    }

    private fun message(kind: String, vararg parts: ByteArray): ByteArray =
        ByteArrayOutputStream().apply {
            write("suvii-sig-1\n$kind\n".toByteArray(Charsets.US_ASCII))
            parts.forEach { write(it) }
        }.toByteArray()

    fun baseMessage(meta: Map<String, String>, stateRoot: ByteArray) = message("base", metaHash(meta), stateRoot)

    fun patchMessage(meta: Map<String, String>, patchRoot: ByteArray, expectedStateRoot: ByteArray) =
        message("patch", metaHash(meta), patchRoot, expectedStateRoot)

    /**
     * The metadata of the base a patch produces (SPEC.md, 12, step 4): no `patch.*` keys,
     * `suvii.kind = base` and `sign.sig = patch.base_sig`.
     */
    fun baseMetaAfterPatch(patchMeta: Map<String, String>): Map<String, String> {
        val baseSig = patchMeta["patch.base_sig"] ?: throw SuviiException("missing_meta", "patch.base_sig")
        return patchMeta.filterKeys { !it.startsWith("patch.") } + mapOf("suvii.kind" to "base", "sign.sig" to baseSig)
    }
}
