# SPDX-License-Identifier: GPL-3.0-or-later
"""Тонкий адаптер над zstd: пакет `zstandard` або стандартний `compression.zstd` (Python 3.14+)."""

from __future__ import annotations

try:  # pragma: no cover - вибір залежить від середовища
    import zstandard as _zs

    def compress(data: bytes, level: int, dictionary: bytes | None = None) -> bytes:
        d = _zs.ZstdCompressionDict(dictionary) if dictionary else None
        return _zs.ZstdCompressor(level=level, dict_data=d, write_content_size=True).compress(data)

    def decompress(data: bytes, max_size: int, dictionary: bytes | None = None) -> bytes:
        d = _zs.ZstdCompressionDict(dictionary) if dictionary else None
        dobj = _zs.ZstdDecompressor(dict_data=d).decompressobj()
        out = dobj.decompress(data)
        if len(out) > max_size:
            raise ValueError("decompressed chunk too large")
        if not dobj.eof:
            raise ValueError("truncated zstd frame")
        return out

    def train_dictionary(samples: list[bytes], size: int) -> bytes:
        return _zs.train_dictionary(size, samples).as_bytes()

except ImportError:  # pragma: no cover
    from compression import zstd as _cz  # type: ignore[import-not-found]

    def compress(data: bytes, level: int, dictionary: bytes | None = None) -> bytes:
        d = _cz.ZstdDict(dictionary) if dictionary else None
        return _cz.compress(data, level=level, zstd_dict=d)

    def decompress(data: bytes, max_size: int, dictionary: bytes | None = None) -> bytes:
        d = _cz.ZstdDict(dictionary) if dictionary else None
        dec = _cz.ZstdDecompressor(zstd_dict=d)
        out = dec.decompress(data, max_length=max_size + 1)
        if len(out) > max_size:
            raise ValueError("decompressed chunk too large")
        if not dec.eof:
            raise ValueError("truncated zstd frame")
        return out

    def train_dictionary(samples: list[bytes], size: int) -> bytes:
        return _cz.train_dict(samples, size).dict_content
