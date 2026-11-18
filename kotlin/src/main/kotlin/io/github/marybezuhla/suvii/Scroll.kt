// SPDX-License-Identifier: GPL-3.0-or-later
package io.github.marybezuhla.suvii

/** A document as stored in a scroll (SPEC.md, 4). */
data class Document(
    val path: String,
    val title: String,
    val mime: String,
    val updated: String,
    val body: String,
    val facets: List<Pair<String, String>>,
    val toc: List<TocEntry>,
    val links: List<Link>,
)

/** What a list of documents needs, without reading any text. */
data class DocInfo(val path: String, val title: String, val mime: String, val size: Long, val updated: String)

/**
 * An opened scroll. Created only by [open], which runs every check of SPEC.md, section 10 before
 * anything is read; a [Scroll] object therefore always has a valid schema, limits, metadata and
 * (unless asked otherwise) a valid signature by a key the app trusts.
 */
class Scroll private constructor(
    val db: SqlDatabase,
    meta: Map<String, String>,
    private val zstd: Decompressor,
) {
    var meta: Map<String, String> = meta
        internal set
    val kind: String get() = meta.getValue("suvii.kind")
    val seq: Long get() = meta.getValue("state.seq").toLong()
    val collectionId: String = meta.getValue("collection.id")
    internal val collectionIdBytes: ByteArray = Spec.checkUuid(collectionId)
    val fields: Map<String, Field> = Fields.parse(meta.getValue("collection.fields"))
    val hasFts: Boolean = db.first("SELECT 1 FROM sqlite_schema WHERE name = 'fts' LIMIT 1") { true } ?: false
    private val dicts = HashMap<Long, ByteArray>()

    fun count(): Long = db.first("SELECT count(*) FROM docs") { it.long(0) } ?: 0

    fun infos(): List<DocInfo> =
        db.all("SELECT path, title, mime, size, updated FROM docs ORDER BY path") {
            DocInfo(it.string(0), it.string(1), it.string(2), it.long(3), it.string(4))
        }.sortedWith(compareBy(Hashing.BY_UTF8) { it.path })

    /** (path, doc_hash) in the order of SPEC.md: by the UTF-8 bytes of the path. */
    fun pathHashes(): List<Pair<String, ByteArray>> =
        db.all("SELECT path, hash FROM docs") { it.string(0) to it.blob(1) }.sortedWith(compareBy(Hashing.BY_UTF8) { it.first })

    fun tombstones(): List<String> = db.all("SELECT path FROM tombstones") { it.string(0) }.sortedWith(Hashing.BY_UTF8)

    private fun dictionary(id: Long): ByteArray =
        dicts.getOrPut(id) {
            db.first("SELECT data FROM dicts WHERE id = ? LIMIT 1", listOf(id)) { it.blob(0) }
                ?: throw SuviiException("corrupt", "missing dictionary")
        }

    internal fun rawBody(docId: Long, size: Long): ByteArray {
        if (size < 0 || size > Spec.MAX_DOC) throw SuviiException("corrupt", "size")
        val out = java.io.ByteArrayOutputStream(size.toInt())
        var expected = 0L
        db.query("SELECT n, dict_id, data FROM chunks WHERE doc_id = ? ORDER BY n", listOf(docId)) { row ->
            val data = row.blob(2)
            if (row.long(0) != expected || data.size > Spec.MAX_CHUNK_COMPRESSED) throw SuviiException("corrupt", "chunk")
            expected++
            val dict = if (row.isNull(1)) null else dictionary(row.long(1))
            val piece = try {
                zstd.decompress(data, Spec.MAX_CHUNK_RAW, dict)
            } catch (e: SuviiException) {
                throw e
            } catch (e: Exception) {
                throw SuviiException("corrupt", "chunk data")
            }
            if (piece.size > Spec.MAX_CHUNK_RAW || out.size() + piece.size > size) throw SuviiException("corrupt", "size")
            out.write(piece)
        }
        if (out.size().toLong() != size) throw SuviiException("corrupt", "size")
        return out.toByteArray()
    }

    /** The document at [path], checked against its stored hash and, for HTML, the safe subset. */
    fun document(path: String, checkHash: Boolean = true): Document {
        class Row(val id: Long, val title: String, val mime: String, val size: Long, val updated: String, val hash: ByteArray)
        val row = db.first("SELECT id, title, mime, size, updated, hash FROM docs WHERE path = ? LIMIT 1", listOf(path)) {
            Row(it.long(0), it.string(1), it.string(2), it.long(3), it.string(4), it.blob(5))
        } ?: throw SuviiException("not_found", path)
        val bytes = rawBody(row.id, row.size)
        val decoder = Charsets.UTF_8.newDecoder()
            .onMalformedInput(java.nio.charset.CodingErrorAction.REPORT)
            .onUnmappableCharacter(java.nio.charset.CodingErrorAction.REPORT)
        val body = try {
            decoder.decode(java.nio.ByteBuffer.wrap(bytes)).toString()
        } catch (e: java.nio.charset.CharacterCodingException) {
            throw SuviiException("corrupt", "utf-8")
        }
        val doc = Document(
            path = path,
            title = row.title,
            mime = row.mime,
            updated = row.updated,
            body = body,
            facets = db.all("SELECT key, value FROM facets WHERE doc_id = ?", listOf(row.id)) { it.string(0) to it.string(1) },
            toc = db.all("SELECT level, anchor, title FROM toc WHERE doc_id = ? ORDER BY ord", listOf(row.id)) {
                TocEntry(it.long(0).toInt(), it.string(1), it.string(2))
            },
            links = db.all("SELECT kind, target, anchor FROM links WHERE doc_id = ?", listOf(row.id)) {
                Link(it.string(0), it.string(1), it.string(2))
            },
        )
        if (checkHash) {
            val hash = Hashing.docHash(doc.path, doc.title, doc.mime, doc.updated, doc.facets, doc.toc, doc.links, bytes)
            if (!hash.contentEquals(row.hash)) throw SuviiException("bad_doc_hash", path)
        }
        if (doc.mime == "text/html") SafeHtml.check(doc.body)
        return doc
    }

    /** Documents whose text has all words of [query] (as word beginnings); by title if there is no index. */
    fun search(query: String, limit: Int = 50): List<Pair<String, String>> {
        val words = WORD.findAll(query).map { it.value }.toList()
        if (words.isEmpty()) return emptyList()
        if (hasFts) {
            val expr = words.joinToString(" ") { "\"" + it.replace("\"", "") + "\"*" }
            return db.all(
                "SELECT d.path, d.title FROM fts JOIN docs d ON d.id = fts.rowid WHERE fts MATCH ? ORDER BY rank LIMIT ?",
                listOf(expr, limit.toLong()),
            ) { it.string(0) to it.string(1) }
        }
        val like = "%" + words.joinToString("%") + "%"
        return db.all("SELECT path, title FROM docs WHERE title LIKE ? ORDER BY path LIMIT ?", listOf(like, limit.toLong())) {
            it.string(0) to it.string(1)
        }
    }

    fun stateRoot(): ByteArray = Hashing.stateRoot(collectionIdBytes, seq, pathHashes())

    fun patchRoot(): ByteArray =
        Hashing.patchRoot(
            collectionIdBytes, meta.getValue("patch.from_seq").toLong(), meta.getValue("patch.to_seq").toLong(),
            pathHashes(), tombstones(),
        )

    fun signatureOk(trustedKeys: List<String>): Boolean {
        val message = if (kind == "base") {
            Hashing.baseMessage(meta, stateRoot())
        } else {
            Hashing.patchMessage(meta, patchRoot(), hexToBytes(meta.getValue("patch.state_root")))
        }
        return Signatures.verify(trustedKeys, meta.getValue("sign.sig"), message)
    }

    /** Checks every document; returns the problems found (empty if all is well). */
    fun verifyAll(): List<String> {
        val problems = mutableListOf<String>()
        for (info in infos()) {
            try {
                document(info.path)
            } catch (e: SuviiException) {
                problems += "${info.path}: ${e.code}"
            }
        }
        val orphans = db.first("SELECT count(*) FROM chunks WHERE doc_id NOT IN (SELECT id FROM docs)") { it.long(0) } ?: 0
        if (orphans > 0) problems += "$orphans orphan chunks"
        if (kind == "base" && tombstones().isNotEmpty()) problems += "tombstones in base"
        return problems
    }

    companion object {
        private val WORD = Regex("(?U)\\w+")
        private val FTS_SQL = Regex("^CREATE VIRTUAL TABLE\\s+\"?fts\"?\\s+USING\\s+fts5\\s*\\(", RegexOption.IGNORE_CASE)
        private const val SQLITE_MAGIC = "SQLite format 3\u0000"

        /** Expected columns of each table: name, declared type, not null, primary key position. */
        private val EXPECTED_COLUMNS = mapOf(
            "meta" to listOf(Col("key", "TEXT", 1, 1), Col("value", "TEXT", 1, 0)),
            "docs" to listOf(
                Col("id", "INTEGER", 0, 1), Col("path", "TEXT", 1, 0), Col("title", "TEXT", 1, 0), Col("mime", "TEXT", 1, 0),
                Col("size", "INTEGER", 1, 0), Col("updated", "TEXT", 1, 0), Col("hash", "BLOB", 1, 0),
            ),
            "chunks" to listOf(Col("doc_id", "INTEGER", 1, 1), Col("n", "INTEGER", 1, 2), Col("dict_id", "INTEGER", 0, 0), Col("data", "BLOB", 1, 0)),
            "dicts" to listOf(Col("id", "INTEGER", 0, 1), Col("data", "BLOB", 1, 0)),
            "facets" to listOf(Col("doc_id", "INTEGER", 1, 1), Col("key", "TEXT", 1, 2), Col("value", "TEXT", 1, 3)),
            "toc" to listOf(
                Col("doc_id", "INTEGER", 1, 1), Col("ord", "INTEGER", 1, 2), Col("level", "INTEGER", 1, 0),
                Col("anchor", "TEXT", 1, 0), Col("title", "TEXT", 1, 0),
            ),
            "links" to listOf(Col("doc_id", "INTEGER", 1, 1), Col("kind", "TEXT", 1, 2), Col("target", "TEXT", 1, 3), Col("anchor", "TEXT", 1, 4)),
            "tombstones" to listOf(Col("path", "TEXT", 1, 1), Col("deleted", "TEXT", 1, 0)),
        )

        private data class Col(val name: String, val type: String, val notNull: Long, val pk: Long)

        private fun blen(column: String) = "length(CAST($column AS BLOB))"

        /** The limits of SPEC.md, 11, checked inside SQLite before any value is loaded. */
        private val LIMIT_CHECKS = listOf(
            "docs" to "SELECT count(*) FROM docs WHERE typeof(path)!='text' OR ${blen("path")} NOT BETWEEN 1 AND ${Spec.MAX_PATH}" +
                " OR typeof(title)!='text' OR ${blen("title")} > ${Spec.MAX_TITLE}" +
                " OR typeof(mime)!='text' OR mime NOT IN ('text/plain','text/html')" +
                " OR typeof(updated)!='text' OR ${blen("updated")} > ${Spec.MAX_SHORT}" +
                " OR typeof(size)!='integer' OR size < 0 OR size > ${Spec.MAX_DOC}" +
                " OR typeof(hash)!='blob' OR length(hash) != 32",
            "chunks" to "SELECT count(*) FROM chunks WHERE typeof(data)!='blob' OR length(data) > ${Spec.MAX_CHUNK_COMPRESSED}" +
                " OR typeof(n)!='integer' OR n < 0",
            "dicts" to "SELECT count(*) FROM dicts WHERE typeof(data)!='blob' OR length(data) > ${Spec.MAX_DICT}",
            "facets" to "SELECT count(*) FROM facets WHERE typeof(key)!='text' OR typeof(value)!='text'" +
                " OR ${blen("key")} > ${Spec.MAX_SHORT} OR ${blen("value")} > ${Spec.MAX_SHORT}",
            "toc" to "SELECT count(*) FROM toc WHERE typeof(anchor)!='text' OR typeof(title)!='text'" +
                " OR ${blen("anchor")} > ${Spec.MAX_SHORT} OR ${blen("title")} > ${Spec.MAX_TOC_TITLE}" +
                " OR typeof(level)!='integer' OR level NOT BETWEEN 1 AND 32",
            "links" to "SELECT count(*) FROM links WHERE typeof(kind)!='text' OR typeof(target)!='text' OR typeof(anchor)!='text'" +
                " OR ${blen("kind")} > ${Spec.MAX_SHORT} OR ${blen("target")} > ${Spec.MAX_PATH}" +
                " OR ${blen("anchor")} > ${Spec.MAX_SHORT}",
            "tombstones" to "SELECT count(*) FROM tombstones WHERE typeof(path)!='text' OR ${blen("path")} > ${Spec.MAX_PATH}",
            "meta" to "SELECT count(*) FROM meta WHERE typeof(key)!='text' OR typeof(value)!='text'" +
                " OR ${blen("key")} > ${Spec.MAX_SHORT} OR ${blen("value")} > ${Spec.MAX_META_VALUE}",
        )

        internal fun hexToBytes(hex: String): ByteArray = ByteArray(hex.length / 2) { hex.substring(2 * it, 2 * it + 2).toInt(16).toByte() }

        /** Checks the first 100 bytes of the file before it is given to SQLite at all. */
        fun checkHeader(header: ByteArray) {
            if (header.size < 100 || String(header, 0, 16, Charsets.ISO_8859_1) != SQLITE_MAGIC) throw SuviiException("not_sqlite")
            fun u32(at: Int) = (0 until 4).fold(0L) { acc, k -> (acc shl 8) or (header[at + k].toLong() and 0xff) }
            if (u32(68) != Spec.APPLICATION_ID.toLong()) throw SuviiException("not_suvii")
            if (u32(60) != Spec.MAJOR_VERSION.toLong()) throw SuviiException("unsupported_version", u32(60).toString())
        }

        private fun checkSchema(db: SqlDatabase) {
            val tables = mutableSetOf<String>()
            db.query("SELECT type, name, sql FROM sqlite_schema") { row ->
                val type = row.string(0)
                val name = row.string(1)
                if (type == "trigger" || type == "view") throw SuviiException("forbidden_schema", "$type $name")
                if (type == "table") {
                    tables += name
                    val sql = if (row.isNull(2)) "" else row.string(2)
                    if (sql.uppercase().startsWith("CREATE VIRTUAL TABLE") && (name != "fts" || !FTS_SQL.containsMatchIn(sql))) {
                        throw SuviiException("forbidden_schema", "virtual table $name")
                    }
                }
            }
            for ((table, expected) in EXPECTED_COLUMNS) {
                if (table !in tables) throw SuviiException("bad_schema", "missing $table")
                val got = db.all("PRAGMA table_info($table)") { Col(it.string(1), it.string(2).uppercase(), it.long(3), it.long(5)) }
                if (got != expected) throw SuviiException("bad_schema", table)
            }
        }

        private fun checkLimits(db: SqlDatabase) {
            for ((what, sql) in LIMIT_CHECKS) {
                if ((db.first(sql) { it.long(0) } ?: 0) > 0) throw SuviiException("limit_exceeded", what)
            }
            if ((db.first("SELECT count(*) FROM dicts") { it.long(0) } ?: 0) > Spec.MAX_DICTS) throw SuviiException("limit_exceeded", "dict count")
            for (table in listOf("facets", "toc", "links")) {
                val over = db.first("SELECT 1 FROM $table GROUP BY doc_id HAVING count(*) > ${Spec.MAX_ITEMS_PER_DOC} LIMIT 1") { true }
                if (over == true) throw SuviiException("limit_exceeded", table)
            }
        }

        /**
         * Opens a scroll with every check of SPEC.md, section 10. [header] is the first 100 bytes of
         * the file. With [verifySignature] off (tools only, never a reader) the signature is not checked.
         * Any problem is a [SuviiException]; nothing else escapes.
         */
        fun open(
            header: ByteArray,
            db: SqlDatabase,
            zstd: Decompressor,
            trustedKeys: List<String>,
            verifySignature: Boolean = true,
        ): Scroll =
            try {
                checkHeader(header)
                db.execute("PRAGMA trusted_schema = OFF")
                checkSchema(db)
                checkLimits(db)
                val meta = LinkedHashMap<String, String>()
                db.query("SELECT key, value FROM meta") { meta[it.string(0)] = it.string(1) }
                Spec.checkMeta(meta)
                val scroll = Scroll(db, meta, zstd)
                if (verifySignature) {
                    if (trustedKeys.isEmpty()) throw SuviiException("no_trusted_key")
                    if (!scroll.signatureOk(trustedKeys)) throw SuviiException("bad_signature")
                }
                scroll
            } catch (e: SuviiException) {
                throw e
            } catch (e: Exception) {
                throw SuviiException("corrupt", e.javaClass.simpleName)
            }
    }
}
