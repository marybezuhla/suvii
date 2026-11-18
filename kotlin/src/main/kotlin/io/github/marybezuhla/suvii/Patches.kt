// SPDX-License-Identifier: GPL-3.0-or-later
package io.github.marybezuhla.suvii

/** Applying a patch to a base (SPEC.md, 12). The same steps as apply_patch in python/. */
object Patches {
    private fun deleteDoc(db: SqlDatabase, docId: Long, hasFts: Boolean) {
        if (hasFts) db.execute("DELETE FROM fts WHERE rowid = ?", listOf(docId))
        // Chunks, facets, contents and links go with ON DELETE CASCADE; the platform enables foreign keys.
        for (table in listOf("chunks", "facets", "toc", "links")) db.execute("DELETE FROM $table WHERE doc_id = ?", listOf(docId))
        db.execute("DELETE FROM docs WHERE id = ?", listOf(docId))
    }

    /** Copies a document with all its parts as they are (no repacking). Returns its new id. */
    private fun copyDoc(src: SqlDatabase, dst: SqlDatabase, srcId: Long, dictMap: MutableMap<Long, Long>): Long {
        val row = src.first("SELECT path, title, mime, size, updated, hash FROM docs WHERE id = ? LIMIT 1", listOf(srcId)) {
            listOf<Any?>(it.string(0), it.string(1), it.string(2), it.long(3), it.string(4), it.blob(5))
        } ?: throw SuviiException("corrupt", "document vanished")
        val newId = dst.insert("INSERT INTO docs(path, title, mime, size, updated, hash) VALUES (?,?,?,?,?,?)", row)
        val chunks = src.all("SELECT n, dict_id, data FROM chunks WHERE doc_id = ? ORDER BY n", listOf(srcId)) {
            Triple(it.long(0), if (it.isNull(1)) null else it.long(1), it.blob(2))
        }
        for ((n, dictId, data) in chunks) {
            val newDict = dictId?.let { id ->
                dictMap.getOrPut(id) {
                    val dict = src.first("SELECT data FROM dicts WHERE id = ? LIMIT 1", listOf(id)) { it.blob(0) }
                        ?: throw SuviiException("corrupt", "missing dictionary")
                    dst.insert("INSERT INTO dicts(data) VALUES (?)", listOf(dict))
                }
            }
            dst.execute("INSERT INTO chunks(doc_id, n, dict_id, data) VALUES (?,?,?,?)", listOf(newId, n, newDict, data))
        }
        src.all("SELECT key, value FROM facets WHERE doc_id = ?", listOf(srcId)) { it.string(0) to it.string(1) }
            .forEach { (k, v) -> dst.execute("INSERT INTO facets(doc_id, key, value) VALUES (?,?,?)", listOf(newId, k, v)) }
        src.all("SELECT ord, level, anchor, title FROM toc WHERE doc_id = ?", listOf(srcId)) {
            listOf<Any?>(newId, it.long(0), it.long(1), it.string(2), it.string(3))
        }.forEach { dst.execute("INSERT INTO toc(doc_id, ord, level, anchor, title) VALUES (?,?,?,?,?)", it) }
        src.all("SELECT kind, target, anchor FROM links WHERE doc_id = ?", listOf(srcId)) {
            listOf<Any?>(newId, it.string(0), it.string(1), it.string(2))
        }.forEach { dst.execute("INSERT INTO links(doc_id, kind, target, anchor) VALUES (?,?,?,?)", it) }
        return newId
    }

    /**
     * Applies [patch] to [base] in one transaction and returns the new state number. [base] must
     * be opened writable. If anything does not match (collection, state, a document hash, the
     * resulting state root or the signature of the result), nothing is changed.
     */
    fun apply(base: Scroll, patch: Scroll, trustedKeys: List<String>): Long {
        if (patch.kind != "patch") throw SuviiException("not_patch")
        if (base.kind != "base") throw SuviiException("not_base")
        if (base.collectionId != patch.collectionId) throw SuviiException("collection_mismatch")
        if (patch.meta.getValue("patch.from_seq").toLong() != base.seq) {
            throw SuviiException("wrong_base_seq", "${base.seq} != ${patch.meta["patch.from_seq"]}")
        }
        patch.verifyAll().firstOrNull()?.let { throw SuviiException("corrupt_patch", it) }
        val db = base.db
        val oldMeta = base.meta
        try {
            db.transaction {
                fun idOf(path: String) = db.first("SELECT id FROM docs WHERE path = ? LIMIT 1", listOf(path)) { it.long(0) }
                for (path in patch.tombstones()) idOf(path)?.let { deleteDoc(db, it, base.hasFts) }
                val dictMap = HashMap<Long, Long>()
                for ((srcId, path) in patch.db.all("SELECT id, path FROM docs ORDER BY id") { it.long(0) to it.string(1) }) {
                    idOf(path)?.let { deleteDoc(db, it, base.hasFts) }
                    val newId = copyDoc(patch.db, db, srcId, dictMap)
                    if (base.hasFts) {
                        val doc = patch.document(path, checkHash = false) // every hash was checked by verifyAll
                        val text = if (doc.mime == "text/html") SafeHtml.toText(doc.body) else doc.body
                        db.execute("INSERT INTO fts(rowid, title, body) VALUES (?,?,?)", listOf(newId, doc.title, text))
                    }
                }
                db.execute("DELETE FROM dicts WHERE id NOT IN (SELECT DISTINCT dict_id FROM chunks WHERE dict_id IS NOT NULL)")
                val newMeta = Hashing.baseMetaAfterPatch(patch.meta)
                db.execute("DELETE FROM meta")
                newMeta.toSortedMap(Hashing.BY_UTF8).forEach { (k, v) -> db.execute("INSERT INTO meta(key, value) VALUES (?,?)", listOf(k, v)) }
                base.meta = newMeta
                if (!base.stateRoot().contentEquals(Scroll.hexToBytes(patch.meta.getValue("patch.state_root")))) {
                    throw SuviiException("state_root_mismatch")
                }
                if (!base.signatureOk(trustedKeys)) throw SuviiException("bad_signature", "updated base")
            }
        } catch (e: Exception) {
            base.meta = oldMeta // the transaction was rolled back; so is our copy of the metadata
            throw if (e is SuviiException) e else SuviiException("corrupt", e.javaClass.simpleName)
        }
        return base.seq
    }
}
