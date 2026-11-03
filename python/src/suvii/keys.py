# SPDX-License-Identifier: GPL-3.0-or-later
"""Ключі ed25519 видавця."""

from __future__ import annotations

import base64
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def generate() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def private_to_text(key: Ed25519PrivateKey) -> str:
    raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    return base64.b64encode(raw).decode()


def private_from_text(text: str) -> Ed25519PrivateKey:
    raw = base64.b64decode(text.strip(), validate=True)
    if len(raw) != 32:
        raise ValueError("ed25519 private key must be 32 bytes")
    return Ed25519PrivateKey.from_private_bytes(raw)


def load_private(path: str | Path) -> Ed25519PrivateKey:
    return private_from_text(Path(path).read_text())


def public_text(key: Ed25519PrivateKey | Ed25519PublicKey) -> str:
    pub = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    return base64.b64encode(pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def public_from_text(text: str) -> Ed25519PublicKey:
    raw = base64.b64decode(text.strip(), validate=True)
    if len(raw) != 32:
        raise ValueError("ed25519 public key must be 32 bytes")
    return Ed25519PublicKey.from_public_bytes(raw)


def sign(key: Ed25519PrivateKey, message: bytes) -> str:
    return base64.b64encode(key.sign(message)).decode()


def verify(public_keys: list[str], signature_b64: str, message: bytes) -> bool:
    try:
        sig = base64.b64decode(signature_b64, validate=True)
    except (ValueError, TypeError):
        return False
    if len(sig) != 64:
        return False
    for pk in public_keys:
        try:
            public_from_text(pk).verify(sig, message)
            return True
        except (InvalidSignature, ValueError):
            continue
    return False
