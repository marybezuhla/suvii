// SPDX-License-Identifier: GPL-3.0-or-later
package io.github.marybezuhla.suvii

/**
 * The safe subset of HTML (SPEC.md, 6.2): checks a document body and extracts its plain text for
 * search. A body is text from the outside world, so the reader checks it before showing it.
 *
 * The tokenizer is deliberately small and strict: anything it does not understand (comments,
 * declarations, unfinished tags) is refused, never guessed.
 */
object SafeHtml {
    val ALLOWED_TAGS = setOf(
        "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "div", "span", "blockquote", "pre", "code",
        "ul", "ol", "li", "dl", "dt", "dd", "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption",
        "b", "strong", "i", "em", "u", "s", "sub", "sup", "small", "a",
    )
    private val BLOCK_TAGS = setOf(
        "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "div", "blockquote", "pre", "ul", "ol", "li",
        "dl", "dt", "dd", "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption",
    )
    private val COMMON_ATTRS = setOf("id", "lang", "dir", "class")
    private val TAG_ATTRS = mapOf("a" to setOf("href"), "td" to setOf("colspan", "rowspan"), "th" to setOf("colspan", "rowspan"))
    private val HREF = Regex("(?U)^(#\\S+|suvii:[^\\s#]+(#\\S+)?|https://\\S+)$")
    private val NUMBER = Regex("^[1-9]\\d{0,3}$")
    private val NAMED = mapOf("amp" to "&", "lt" to "<", "gt" to ">", "quot" to "\"", "apos" to "'", "nbsp" to " ")

    sealed interface Token {
        data class Text(val text: String) : Token

        data class Start(val tag: String, val attrs: List<Pair<String, String>>) : Token

        data class End(val tag: String) : Token
    }

    /** Splits a body into tokens; text and attribute values come with character references decoded. */
    fun tokens(body: String): List<Token> {
        val out = mutableListOf<Token>()
        val text = StringBuilder()
        var i = 0

        fun flush() {
            if (text.isNotEmpty()) out += Token.Text(decode(text.toString())).also { text.clear() }
        }

        while (i < body.length) {
            val c = body[i]
            val next = body.getOrNull(i + 1)
            when {
                c != '<' -> text.append(c).also { i++ }
                next == '!' || next == '?' -> throw SuviiException("unsafe_html", "comment or declaration")
                next == '/' && body.getOrNull(i + 2)?.isLetter() == true -> {
                    flush()
                    val close = body.indexOf('>', i)
                    if (close < 0) throw SuviiException("unsafe_html", "unfinished tag")
                    val name = body.substring(i + 2, close).trim().lowercase()
                    if (!name.all { it.isLetterOrDigit() }) throw SuviiException("unsafe_html", "end tag")
                    out += Token.End(name)
                    i = close + 1
                }
                next != null && next.isLetter() -> {
                    flush()
                    i = startTag(body, i + 1, out)
                }
                else -> text.append(c).also { i++ } // a lone "<" is text, as in a browser
            }
        }
        flush()
        return out
    }

    private fun startTag(body: String, from: Int, out: MutableList<Token>): Int {
        var i = from
        while (i < body.length && body[i].isLetterOrDigit()) i++
        val tag = body.substring(from, i).lowercase()
        val attrs = mutableListOf<Pair<String, String>>()
        while (true) {
            while (i < body.length && body[i].isWhitespace()) i++
            if (i >= body.length) throw SuviiException("unsafe_html", "unfinished tag")
            when (body[i]) {
                '>' -> return (i + 1).also { out += Token.Start(tag, attrs) }
                '/' -> if (body.getOrNull(i + 1) == '>') return (i + 2).also { out += Token.Start(tag, attrs) } else i++
                else -> {
                    val nameStart = i
                    while (i < body.length && !body[i].isWhitespace() && body[i] !in "/>=") i++
                    val name = body.substring(nameStart, i).lowercase()
                    while (i < body.length && body[i].isWhitespace()) i++
                    var value = ""
                    if (body.getOrNull(i) == '=') {
                        i++
                        while (i < body.length && body[i].isWhitespace()) i++
                        val quote = body.getOrNull(i)
                        if (quote == '"' || quote == '\'') {
                            val end = body.indexOf(quote, i + 1)
                            if (end < 0) throw SuviiException("unsafe_html", "unfinished attribute")
                            value = body.substring(i + 1, end)
                            i = end + 1
                        } else {
                            val valueStart = i
                            while (i < body.length && !body[i].isWhitespace() && body[i] != '>') i++
                            value = body.substring(valueStart, i)
                        }
                    }
                    attrs += name to decode(value)
                }
            }
        }
    }

    /** Decodes numeric references and the few named ones a writer uses; others stay as they are. */
    fun decode(text: String): String {
        if ('&' !in text) return text
        val out = StringBuilder(text.length)
        var i = 0
        while (i < text.length) {
            val semi = if (text[i] == '&') text.indexOf(';', i) else -1
            if (semi < 0 || semi - i > 10) {
                out.append(text[i++])
                continue
            }
            val name = text.substring(i + 1, semi)
            val code = when {
                name.startsWith("#x") || name.startsWith("#X") -> name.substring(2).toIntOrNull(16)
                name.startsWith("#") -> name.substring(1).toIntOrNull()
                else -> null
            }
            val decoded = when {
                code != null && code in 1..0x10FFFF && code !in 0xD800..0xDFFF -> String(Character.toChars(code))
                code != null -> "�"
                else -> NAMED[name]
            }
            if (decoded == null) {
                out.append(text[i++])
            } else {
                out.append(decoded)
                i = semi + 1
            }
        }
        return out.toString()
    }

    private fun checkAttrs(tag: String, attrs: List<Pair<String, String>>, ids: MutableSet<String>) {
        val allowed = COMMON_ATTRS + TAG_ATTRS.getOrDefault(tag, emptySet())
        for ((name, value) in attrs) {
            val ok = when (name) {
                !in allowed -> false
                "href" -> HREF.matches(value)
                "class" -> value.split(' ', '\t', '\n', '\r', '\u000c').filter { it.isNotEmpty() }.all { it.startsWith("suvii-") }
                "colspan", "rowspan" -> NUMBER.matches(value)
                "dir" -> value in setOf("ltr", "rtl", "auto")
                "id" -> value.isNotEmpty() && Spec.byteLength(value) <= Spec.MAX_SHORT
                else -> true
            }
            if (!ok) throw SuviiException("unsafe_html", "$name on <$tag>")
            if (name == "id") ids += value
        }
    }

    /** Checks that [body] uses only the safe subset. Returns the ids it defines (link targets). */
    fun check(body: String): Set<String> {
        val ids = mutableSetOf<String>()
        for (token in tokens(body)) {
            when (token) {
                is Token.Start -> {
                    if (token.tag !in ALLOWED_TAGS) throw SuviiException("unsafe_html", "<${token.tag}>")
                    checkAttrs(token.tag, token.attrs, ids)
                }
                is Token.End -> if (token.tag !in ALLOWED_TAGS) throw SuviiException("unsafe_html", "</${token.tag}>")
                is Token.Text -> Unit
            }
        }
        return ids
    }

    /** Plain text for the search index: block elements become line ends, spaces are collapsed. */
    fun toText(body: String): String {
        val parts = StringBuilder()
        for (token in tokens(body)) {
            when (token) {
                is Token.Text -> parts.append(token.text)
                is Token.Start -> if (token.tag in BLOCK_TAGS) parts.append('\n')
                is Token.End -> if (token.tag in BLOCK_TAGS) parts.append('\n')
            }
        }
        return parts.toString()
            .replace(Regex("[ \\t\\r\\u000b\\u000c]+"), " ")
            .replace(Regex(" *\\n[ \\n]*"), "\n")
            .trim()
    }
}
