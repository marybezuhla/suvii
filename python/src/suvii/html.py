# SPDX-License-Identifier: GPL-3.0-or-later
"""Безпечна підмножина HTML (SPEC.md, розділ 6.2): перевірка і витягнення тексту для пошуку."""

from __future__ import annotations

import re
from html.parser import HTMLParser

from .spec import SuviiError

ALLOWED_TAGS = frozenset(
    "p br hr h1 h2 h3 h4 h5 h6 div span blockquote pre code ul ol li dl dt dd "
    "table thead tbody tfoot tr th td caption b strong i em u s sub sup small a".split()
)
VOID_TAGS = frozenset({"br", "hr"})
BLOCK_TAGS = frozenset(
    "p br hr h1 h2 h3 h4 h5 h6 div blockquote pre ul ol li dl dt dd table thead tbody tfoot tr th td caption".split()
)
COMMON_ATTRS = frozenset({"id", "lang", "dir", "class"})
TAG_ATTRS = {"a": {"href"}, "td": {"colspan", "rowspan"}, "th": {"colspan", "rowspan"}}

_HREF = re.compile(r"^(#[^\s]+|suvii:[^\s#]+(#[^\s]+)?|https://[^\s]+)$")
_NUM = re.compile(r"^[1-9]\d{0,3}$")


class _Checker(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.text: list[str] = []
        self.error: str | None = None

    def _fail(self, msg: str) -> None:
        if self.error is None:
            self.error = msg

    def _check_attrs(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        allowed = COMMON_ATTRS | TAG_ATTRS.get(tag, set())
        for name, value in attrs:
            if name not in allowed:
                self._fail(f"attribute {name} on <{tag}>")
                continue
            v = value or ""
            if name == "href" and not _HREF.match(v):
                self._fail(f"href {v[:80]}")
            elif name == "class" and not all(c.startswith("suvii-") for c in v.split()):
                self._fail(f"class {v[:80]}")
            elif name in ("colspan", "rowspan") and not _NUM.match(v):
                self._fail(f"{name} {v[:20]}")
            elif name == "dir" and v not in ("ltr", "rtl", "auto"):
                self._fail(f"dir {v[:20]}")
            elif name == "id":
                if not v or len(v) > 1024:
                    self._fail("id")
                self.ids.add(v)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in ALLOWED_TAGS:
            self._fail(f"<{tag}>")
            return
        self._check_attrs(tag, attrs)
        if tag in BLOCK_TAGS:
            self.text.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag not in ALLOWED_TAGS:
            self._fail(f"</{tag}>")
        elif tag in BLOCK_TAGS:
            self.text.append("\n")

    def handle_data(self, data: str) -> None:
        self.text.append(data)

    def handle_comment(self, data: str) -> None:
        self._fail("comment")

    def handle_decl(self, decl: str) -> None:
        self._fail("declaration")

    def handle_pi(self, data: str) -> None:
        self._fail("processing instruction")

    def unknown_decl(self, data: str) -> None:
        self._fail("declaration")


def _clean_text(parts: list[str]) -> str:
    text = "".join(parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n[ \n]*", "\n", text)
    return text.strip()


def check_html(body: str) -> set[str]:
    """Перевіряє, що фрагмент лише з безпечної підмножини. Повертає множину id."""
    p = _Checker()
    p.feed(body)
    p.close()
    if p.error:
        raise SuviiError("unsafe_html", p.error)
    return p.ids


def html_to_text(body: str) -> str:
    p = _Checker()
    p.feed(body)
    p.close()
    return _clean_text(p.text)


def body_to_text(mime: str, body: str) -> str:
    return html_to_text(body) if mime == "text/html" else body
