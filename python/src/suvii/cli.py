# SPDX-License-Identifier: GPL-3.0-or-later
"""Командний рядок: `suvii <команда> …`."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__, keys, spec
from .jsonl import read_collection, read_docs
from .patch import apply_patch, apply_patch_copy, make_patch
from .reader import open_scroll
from .spec import SuviiError
from .writer import Writer


def _trust(args: argparse.Namespace) -> dict:
    trusted = [Path(t).read_text().strip() if os.path.isfile(t) else t for t in (args.trust or [])]
    if trusted:
        return {"trusted_keys": trusted}
    print("warning: no --trust key given; trusting the key embedded in the file", file=sys.stderr)
    return {"trust_embedded_key": True}


def cmd_keygen(args: argparse.Namespace) -> int:
    out = Path(args.out)
    if out.exists():
        raise SuviiError("file_exists", str(out))
    k = keys.generate()
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(keys.private_to_text(k) + "\n")
    Path(str(out) + ".pub").write_text(keys.public_text(k) + "\n")
    print(keys.public_text(k))
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    c = read_collection(args.collection)
    key = keys.load_private(args.key)
    with Writer(
        args.out,
        collection_id=c["id"],
        title=c["title"],
        language=c["language"],
        publisher=c["publisher"],
        fields=c["fields"],
        seq=int(c["seq"]),
        source_date=c["source_date"],
        created=c.get("created"),
        extra_meta=c.get("meta"),
        level=args.level,
        fts=not args.no_fts,
    ) as w:
        for doc in read_docs(args.docs):
            w.add(doc)
        root = w.finish(key)
        print(f"{w.count} documents, state {c['seq']}, root {root.hex()}")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    with open_scroll(args.file, **_trust(args)) as s:
        print(f"kind:        {s.kind}")
        print(f"format:      {s.meta['suvii.format']}")
        print(f"collection:  {s.meta['collection.title']} ({s.collection_id})")
        print(f"publisher:   {s.meta['collection.publisher']}")
        print(f"language:    {s.meta['collection.language']}")
        print(f"state:       {s.seq} (data as of {s.meta['state.source_date']}, created {s.meta['state.created']})")
        if s.kind == "patch":
            print(f"patch:       {s.meta['patch.from_seq']} -> {s.meta['patch.to_seq']}, "
                  f"{s.count()} documents, {len(s.tombstones())} deletions")
        else:
            print(f"documents:   {s.count()}")
        print(f"search:      {'yes' if s.has_fts else 'no'}")
        print(f"signature:   valid ({s.trusted_by} key {s.meta['sign.key']})")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    with open_scroll(args.file, **_trust(args)) as s:
        problems = s.verify_all()
    for p in problems:
        print(p)
    print("ok" if not problems else f"{len(problems)} problems")
    return 0 if not problems else 1


def cmd_cat(args: argparse.Namespace) -> int:
    with open_scroll(args.file, **_trust(args)) as s:
        doc = s.document(args.path)
    sys.stdout.write(doc.body)
    if not doc.body.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    with open_scroll(args.file, **_trust(args)) as s:
        for path, title in s.search(args.query, args.limit):
            print(f"{path}\t{title}")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    key = keys.load_private(args.key)
    t = _trust(args)
    with open_scroll(args.old, **t) as old, open_scroll(args.new, **t) as new:
        stats = make_patch(old, new, args.out, key)
    print(f"{stats['changed']} changed or new, {stats['removed']} removed")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    trusted = [Path(t).read_text().strip() if os.path.isfile(t) else t for t in args.trust]
    if args.out:
        seq = apply_patch_copy(args.base, args.patch, args.out, trusted)
    else:
        seq = apply_patch(args.base, args.patch, trusted)
    print(f"state {seq}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="suvii", description="Tools for the Suvii (.suvii) format")
    p.add_argument("--version", action="version", version=f"suvii {__version__} (format {spec.FORMAT_VERSION})")
    sub = p.add_subparsers(dest="cmd", required=True)

    def trust_opt(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--trust", action="append", metavar="PUBKEY",
                        help="trusted publisher public key (base64 or file); repeatable")

    sp = sub.add_parser("keygen", help="generate a publisher key pair")
    sp.add_argument("out", help="private key file (public key goes to OUT.pub)")
    sp.set_defaults(func=cmd_keygen)

    sp = sub.add_parser("create", help="create a base from collection.json and docs.jsonl")
    sp.add_argument("--collection", required=True)
    sp.add_argument("--docs", required=True)
    sp.add_argument("--key", required=True, help="private key file")
    sp.add_argument("--level", type=int, default=19, help="zstd level (default 19)")
    sp.add_argument("--no-fts", action="store_true", help="do not build the search index")
    sp.add_argument("out")
    sp.set_defaults(func=cmd_create)

    for name, func, hlp in (("info", cmd_info, "show metadata"), ("verify", cmd_verify, "verify every document")):
        sp = sub.add_parser(name, help=hlp)
        sp.add_argument("file")
        trust_opt(sp)
        sp.set_defaults(func=func)

    sp = sub.add_parser("cat", help="print a document")
    sp.add_argument("file")
    sp.add_argument("path")
    trust_opt(sp)
    sp.set_defaults(func=cmd_cat)

    sp = sub.add_parser("search", help="full-text search")
    sp.add_argument("file")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=20)
    trust_opt(sp)
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("diff", help="make a patch OLD -> NEW")
    sp.add_argument("old")
    sp.add_argument("new")
    sp.add_argument("--key", required=True, help="private key of the publisher")
    sp.add_argument("out")
    trust_opt(sp)
    sp.set_defaults(func=cmd_diff)

    sp = sub.add_parser("apply", help="apply a patch to a base")
    sp.add_argument("base")
    sp.add_argument("patch")
    sp.add_argument("--trust", action="append", required=True, metavar="PUBKEY")
    sp.add_argument("--out", help="write the result to a new file instead of updating BASE in place")
    sp.set_defaults(func=cmd_apply)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except SuviiError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as e:
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
