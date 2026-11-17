// SPDX-License-Identifier: GPL-3.0-or-later
package io.github.marybezuhla.suvii

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class SafeHtmlTest {
    @Test
    fun whatAConverterWritesIsAccepted() {
        val body = "<p id=\"n1\" class=\"suvii-center\"><b>Розділ I<br>ЗАГАЛЬНІ ЗАСАДИ</b></p>\n" +
            "<p id=\"n2\"><b>Стаття 1.</b> Текст <a href=\"suvii:laws/2341-14#n12\">кодексу</a>, " +
            "<a href=\"#n1\">вище</a>, <a href=\"https://data.rada.gov.ua\">джерело</a> &amp; &lt;b&gt; &#x338;</p>\n" +
            "<table>\n<tr>\n<td colspan=\"2\"><p>A</p></td>\n</tr>\n</table>"
        assertEquals(setOf("n1", "n2"), SafeHtml.check(body))
    }

    @Test
    fun theVectorDocumentIsAccepted() {
        SafeHtml.check(TestData.str("doc", "body"))
    }

    @Test
    fun unsafeMarkupIsRefused() {
        val bad = listOf(
            "<script>alert(1)</script>", "<p onclick=\"x()\">a</p>", "<p style=\"color:red\">a</p>",
            "<img src=\"x\">", "<iframe></iframe>", "<a href=\"javascript:alert(1)\">a</a>",
            "<a href=\"http://example.org\">a</a>", "<a href=\"\">a</a>", "<a href>a</a>", "<p class=\"x\">a</p>",
            "<p class=\"suvii-a b\">a</p>", "<td colspan=\"0\">a</td>", "<td rowspan=\"99999\">a</td>",
            "<p dir=\"up\">a</p>", "<p id=\"\">a</p>", "<!-- c -->", "<!DOCTYPE html>", "<?xml?>", "<p", "<p id=\"x>",
            "</script>", "<svg><a href=\"#x\">a</a></svg>", "<a href=\"#a b\">x</a>", "<A HREF=\"JAVASCRIPT:x\">a</A>",
        )
        for (body in bad) assertThrows(body, SuviiException::class.java) { SafeHtml.check(body) }
    }

    @Test
    fun loneLessThanIsText() {
        assertEquals(emptySet<String>(), SafeHtml.check("<p>1 < 2 and a <3</p>"))
        assertEquals("1 < 2 and a <3", SafeHtml.toText("<p>1 < 2 and a <3</p>"))
    }

    @Test
    fun textForSearch() {
        val text = SafeHtml.toText("<p id=\"n1\"><b>Розділ I<br>ЗАГАЛЬНІ</b></p>\n<p>  Текст   &amp;\tще&nbsp;раз </p><p></p>")
        assertEquals("Розділ I\nЗАГАЛЬНІ\nТекст & ще раз", text)
    }

    @Test
    fun characterReferences() {
        assertEquals("&<>\"' й😀", SafeHtml.decode("&amp;&lt;&gt;&quot;&apos;&nbsp;&#1081;&#x1F600;"))
        assertEquals("&unknown; & &;x", SafeHtml.decode("&unknown; & &;x"))
        assertEquals("��", SafeHtml.decode("&#xD800;&#99999999;"))
    }
}
