# SPDX-License-Identifier: GPL-3.0-or-later
"""Еталонна реалізація формату «Сувій» (.suvii)."""

__version__ = "0.1.0"

from .model import Document, Link, TocEntry  # noqa: E402
from .patch import apply_patch, apply_patch_copy, make_patch  # noqa: E402
from .reader import Scroll, open_scroll  # noqa: E402
from .spec import SuviiError  # noqa: E402
from .writer import Writer  # noqa: E402

__all__ = [
    "Document",
    "Link",
    "TocEntry",
    "Scroll",
    "SuviiError",
    "Writer",
    "apply_patch",
    "apply_patch_copy",
    "make_patch",
    "open_scroll",
]
