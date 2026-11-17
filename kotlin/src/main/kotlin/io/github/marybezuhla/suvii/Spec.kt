// SPDX-License-Identifier: GPL-3.0-or-later
package io.github.marybezuhla.suvii

import java.nio.ByteBuffer
import java.text.Normalizer
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import java.time.format.ResolverStyle
import java.util.UUID

/** Constants and checks of SPEC.md, version 0.1. The same rules as python/src/suvii/spec.py. */
object Spec {
    const val FORMAT_VERSION = "0.1"
    const val MAJOR_VERSION = 0
    const val APPLICATION_ID = 0x53555649 // "SUVI"

    private const val KIB = 1024
    private const val MIB = 1024 * KIB
    const val MAX_PATH = 1024
    const val MAX_TITLE = 4096
    const val MAX_SHORT = 1024 // mime, updated, facet key and value, anchor, link kind and target
    const val MAX_TOC_TITLE = 4096
    const val MAX_ITEMS_PER_DOC = 10_000
    const val MAX_CHUNK_COMPRESSED = 256 * KIB
    const val MAX_CHUNK_RAW = 1 * MIB
    const val MAX_DOC = 64 * MIB
    const val MAX_DICT = 1 * MIB
    const val MAX_DICTS = 256
    const val MAX_META_VALUE = 1 * MIB
    const val MAX_ICON = 64 * 1000
    const val MAX_DOCS = Int.MAX_VALUE.toLong()
    const val MAX_SEQ = Long.MAX_VALUE

    val MIME_TYPES = setOf("text/plain", "text/html")
    val KINDS = setOf("base", "patch")
    val REQUIRED_META = listOf(
        "suvii.format", "suvii.kind", "collection.id", "collection.title", "collection.language",
        "collection.publisher", "collection.fields", "state.seq", "state.created", "state.source_date",
        "sign.alg", "sign.key", "sign.sig",
    )
    val REQUIRED_PATCH_META = listOf("patch.from_seq", "patch.to_seq", "patch.state_root", "patch.base_sig")

    private val CONTROL = Regex("[\\x00-\\x1f\\x7f]")
    private val DATETIME = Regex("^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z$")
    private val DATE = Regex("^\\d{4}-\\d{2}-\\d{2}$")
    private val SEQ = Regex("^[1-9]\\d{0,18}$")
    private val FORMAT = Regex("^(\\d{1,4})\\.(\\d{1,4})$")
    private val HEX_ROOT = Regex("^[0-9a-f]{64}$")
    private val DATETIME_FORMAT = DateTimeFormatter.ofPattern("uuuu-MM-dd'T'HH:mm:ss'Z'").withResolverStyle(ResolverStyle.STRICT)

    fun byteLength(text: String): Int = text.toByteArray(Charsets.UTF_8).size

    fun checkNfc(text: String, what: String) {
        if (!Normalizer.isNormalized(text, Normalizer.Form.NFC)) throw SuviiException("not_nfc", what)
    }

    fun checkText(text: String, limit: Int, what: String, allowEmpty: Boolean = false) {
        if (!allowEmpty && text.isEmpty()) throw SuviiException("empty", what)
        if (byteLength(text) > limit) throw SuviiException("too_long", what)
        checkNfc(text, what)
    }

    fun checkPath(path: String) {
        checkText(path, MAX_PATH, "path")
        if (CONTROL.containsMatchIn(path) || path.any { it in "\\?#" }) throw SuviiException("bad_path", path)
        if (path.startsWith("/") || path.endsWith("/")) throw SuviiException("bad_path", path)
        if (path.split("/").any { it.isEmpty() || it == "." || it == ".." }) throw SuviiException("bad_path", path)
    }

    fun checkDateTime(text: String, what: String) {
        if (!DATETIME.matches(text)) throw SuviiException("bad_datetime", what)
        try {
            LocalDateTime.parse(text, DATETIME_FORMAT)
        } catch (e: DateTimeParseException) {
            throw SuviiException("bad_datetime", what)
        }
    }

    fun checkDate(text: String, what: String) {
        if (!DATE.matches(text)) throw SuviiException("bad_date", what)
        val date = try {
            LocalDate.parse(text)
        } catch (e: DateTimeParseException) {
            throw SuviiException("bad_date", what)
        }
        if (date.year < 1) throw SuviiException("bad_date", what)
    }

    /** The 16 bytes of a collection id written in the canonical lower-case form. */
    fun checkUuid(text: String): ByteArray {
        val uuid = try {
            UUID.fromString(text)
        } catch (e: IllegalArgumentException) {
            throw SuviiException("bad_collection_id", text)
        }
        if (uuid.toString() != text) throw SuviiException("bad_collection_id", text)
        return ByteBuffer.allocate(16).putLong(uuid.mostSignificantBits).putLong(uuid.leastSignificantBits).array()
    }

    fun checkSeq(text: String, what: String = "state.seq"): Long {
        if (!SEQ.matches(text)) throw SuviiException("bad_seq", what)
        return text.toLongOrNull() ?: throw SuviiException("bad_seq", what) // 19 digits may exceed MAX_SEQ
    }

    /**
     * Checks the metadata of a base or a patch (SPEC.md, 4.1) as a reader must before trusting
     * anything else in the file. `collection.fields` is JSON and is checked by the platform layer,
     * which has a JSON parser; here only its presence is required.
     */
    fun checkMeta(meta: Map<String, String>) {
        for (key in REQUIRED_META) if (key !in meta) throw SuviiException("missing_meta", key)
        for ((key, value) in meta) {
            val limit = if (key == "collection.icon") MAX_ICON else MAX_META_VALUE
            if (byteLength(value) > limit) throw SuviiException("limit_exceeded", key)
        }
        val format = FORMAT.matchEntire(meta.getValue("suvii.format")) ?: throw SuviiException("bad_meta", "suvii.format")
        if (format.groupValues[1].toInt() != MAJOR_VERSION) {
            throw SuviiException("unsupported_version", meta.getValue("suvii.format"))
        }
        val kind = meta.getValue("suvii.kind")
        if (kind !in KINDS) throw SuviiException("bad_meta", "suvii.kind")
        if (meta["sign.alg"] != "ed25519") throw SuviiException("bad_meta", "sign.alg")
        checkUuid(meta.getValue("collection.id"))
        val seq = checkSeq(meta.getValue("state.seq"))
        checkDateTime(meta.getValue("state.created"), "state.created")
        checkDate(meta.getValue("state.source_date"), "state.source_date")
        if (kind == "patch") {
            for (key in REQUIRED_PATCH_META) if (key !in meta) throw SuviiException("missing_meta", key)
            val from = checkSeq(meta.getValue("patch.from_seq"), "patch.from_seq")
            val to = checkSeq(meta.getValue("patch.to_seq"), "patch.to_seq")
            if (to != seq || from >= to) throw SuviiException("bad_meta", "patch seq")
            if (!HEX_ROOT.matches(meta.getValue("patch.state_root"))) throw SuviiException("bad_meta", "patch.state_root")
        }
    }
}
