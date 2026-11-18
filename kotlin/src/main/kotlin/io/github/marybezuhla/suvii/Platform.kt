// SPDX-License-Identifier: GPL-3.0-or-later
package io.github.marybezuhla.suvii

/**
 * What the library needs from the platform: SQLite and zstd. On Android these are sqlite-android
 * and zstd-jni; in the JVM tests, sqlite-jdbc and zstd-jni. Keeping them behind interfaces lets
 * every rule of the format live here, in plain Kotlin, tested once.
 *
 * The platform opens the file and MUST, before handing the connection over (SPEC.md, 10):
 * open a downloaded file read-only, enable SQLITE_DBCONFIG_DEFENSIVE and turn trusted_schema off.
 */
interface SqlDatabase {
    /** Runs a query and passes each row to [row], in order. */
    fun query(sql: String, args: List<Any?> = emptyList(), row: (SqlRow) -> Unit)

    /** Runs a statement that returns no rows. */
    fun execute(sql: String, args: List<Any?> = emptyList())

    /** Runs an INSERT and returns the new rowid. */
    fun insert(sql: String, args: List<Any?>): Long

    /** Runs [block] in one write transaction: everything is kept, or nothing if it throws. */
    fun <T> transaction(block: () -> T): T
}

interface SqlRow {
    fun isNull(column: Int): Boolean

    fun long(column: Int): Long

    fun string(column: Int): String

    fun blob(column: Int): ByteArray
}

fun interface Decompressor {
    /**
     * Unpacks one zstd frame. MUST fail (throw anything) if the result would be larger than
     * [maxSize] or the frame is incomplete; MUST NOT allocate more than [maxSize] for the result.
     */
    fun decompress(data: ByteArray, maxSize: Int, dictionary: ByteArray?): ByteArray
}

/** All rows of a query, read with [read]. */
fun <T> SqlDatabase.all(sql: String, args: List<Any?> = emptyList(), read: (SqlRow) -> T): List<T> {
    val out = mutableListOf<T>()
    query(sql, args) { out += read(it) }
    return out
}

/** The first row of a query, or null. */
fun <T> SqlDatabase.first(sql: String, args: List<Any?> = emptyList(), read: (SqlRow) -> T): T? {
    var out: T? = null
    var seen = false
    query(sql, args) { if (!seen) { seen = true; out = read(it) } }
    return out
}
