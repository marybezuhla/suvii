// SPDX-License-Identifier: GPL-3.0-or-later
package io.github.marybezuhla.suvii

import com.github.luben.zstd.Zstd
import com.github.luben.zstd.ZstdDecompressCtx
import java.io.File
import java.sql.Connection
import java.sql.DriverManager
import java.sql.PreparedStatement
import java.sql.ResultSet
import java.util.Properties

/** The platform for the JVM tests: sqlite-jdbc and zstd-jni. The Android app has its own. */
class JdbcDatabase(file: File, writable: Boolean) : SqlDatabase, AutoCloseable {
    private val connection: Connection = DriverManager.getConnection(
        "jdbc:sqlite:${file.absolutePath}",
        Properties().apply {
            setProperty("open_mode", if (writable) "6" else "1") // READWRITE|CREATE or READONLY
            setProperty("foreign_keys", "true")
        },
    )

    private fun prepare(sql: String, args: List<Any?>): PreparedStatement =
        connection.prepareStatement(sql).apply {
            args.forEachIndexed { i, value ->
                when (value) {
                    null -> setNull(i + 1, java.sql.Types.NULL)
                    is Long -> setLong(i + 1, value)
                    is Int -> setLong(i + 1, value.toLong())
                    is String -> setString(i + 1, value)
                    is ByteArray -> setBytes(i + 1, value)
                    else -> error("unsupported argument ${value::class}")
                }
            }
        }

    override fun query(sql: String, args: List<Any?>, row: (SqlRow) -> Unit) {
        prepare(sql, args).use { statement ->
            statement.executeQuery().use { rs ->
                val wrapped = Row(rs)
                while (rs.next()) row(wrapped)
            }
        }
    }

    override fun execute(sql: String, args: List<Any?>) {
        prepare(sql, args).use { it.execute() }
    }

    override fun insert(sql: String, args: List<Any?>): Long {
        execute(sql, args)
        return connection.createStatement().use { s -> s.executeQuery("SELECT last_insert_rowid()").use { it.next(); it.getLong(1) } }
    }

    override fun <T> transaction(block: () -> T): T {
        connection.autoCommit = false
        try {
            return block().also { connection.commit() }
        } catch (e: Throwable) {
            connection.rollback()
            throw e
        } finally {
            connection.autoCommit = true
        }
    }

    override fun close() = connection.close()

    private class Row(private val rs: ResultSet) : SqlRow {
        override fun isNull(column: Int): Boolean = rs.getObject(column + 1) == null

        override fun long(column: Int): Long = rs.getLong(column + 1)

        override fun string(column: Int): String = rs.getString(column + 1)

        override fun blob(column: Int): ByteArray = rs.getBytes(column + 1)
    }
}

object JvmZstd : Decompressor {
    override fun decompress(data: ByteArray, maxSize: Int, dictionary: ByteArray?): ByteArray {
        val size = Zstd.getFrameContentSize(data)
        require(size in 0..maxSize.toLong()) { "bad or unknown content size" }
        ZstdDecompressCtx().use { ctx ->
            if (dictionary != null) ctx.loadDict(dictionary)
            val out = ctx.decompress(data, size.toInt())
            require(out.size.toLong() == size) { "short frame" }
            return out
        }
    }
}

/** Opens a scroll file the way an app would. */
fun openScroll(file: File, keys: List<String>, writable: Boolean = false, verify: Boolean = true): Pair<Scroll, JdbcDatabase> {
    val header = file.inputStream().use { it.readNBytes(100) }
    val db = JdbcDatabase(file, writable)
    try {
        return Scroll.open(header, db, JvmZstd, keys, verifySignature = verify) to db
    } catch (e: Exception) {
        db.close()
        throw e
    }
}
