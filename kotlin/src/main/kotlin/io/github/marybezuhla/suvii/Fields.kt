// SPDX-License-Identifier: GPL-3.0-or-later
package io.github.marybezuhla.suvii

/** One filterable field of a collection (SPEC.md, 7): its type, names and, for enums, values. */
data class Field(
    val key: String,
    val type: String, // text, int, date, bool or enum
    val title: Map<String, String>,
    val multi: Boolean,
    val values: Map<String, Map<String, String>>, // enum value -> names by language
)

object Fields {
    private val TYPES = setOf("text", "int", "date", "bool", "enum")

    @Suppress("UNCHECKED_CAST")
    private fun names(value: Any?): Map<String, String> =
        (value as? Map<String, Any?>)?.mapNotNull { (lang, name) -> (name as? String)?.let { lang to it } }?.toMap() ?: emptyMap()

    /** Reads and checks `collection.fields`; the same rules as check_fields in python/. */
    @Suppress("UNCHECKED_CAST")
    fun parse(json: String): Map<String, Field> {
        val root = Json.parse(json) as? Map<String, Any?> ?: throw SuviiException("bad_fields")
        return root.mapValues { (key, raw) ->
            Spec.checkText(key, Spec.MAX_SHORT, "field key")
            val spec = raw as? Map<String, Any?> ?: throw SuviiException("bad_fields", key)
            val type = spec["type"] as? String
            if (type !in TYPES) throw SuviiException("bad_fields", key)
            val values = if (type == "enum") {
                val map = spec["values"] as? Map<String, Any?> ?: throw SuviiException("bad_fields", key)
                map.mapValues { (_, v) -> names(v) }
            } else {
                emptyMap()
            }
            Field(key, type!!, names(spec["title"]), spec["multi"] == true, values)
        }
    }
}
