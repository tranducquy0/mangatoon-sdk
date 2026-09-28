"""Command line interface for :mod:`mangatoon`.

Subcommands mirror the library: ``search``, ``detail``, ``chapters``,
``read``, ``pages`` and ``comments``. Output is plain text or JSON, so the tool
composes with ``jq`` and shell scripts.

Run ``mangatoon --help`` for usage.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any, Sequence

from ._client import MangaToon
from ._exceptions import (
    APIError,
    DirectAccessBlocked,
    MangaToonError,
    NotAvailable,
    TransportError,
    ValidationError,
)

_TYPES = {"comic": "COMIC", "novel": "NOVEL", "chat": "CHAT_STORY", "all": None}


def _parse_type(value: str | None) -> Any:
    """Map a CLI ``--type`` value to a :class:`ContentType`."""
    from ._models import ContentType

    if value is None or value == "all":
        return None
    try:
        return ContentType[_TYPES[value]]
    except KeyError:
        raise argparse.ArgumentTypeError(
            f"unknown type {value!r}; expected one of {', '.join(_TYPES)}"
        ) from None


def _dump(value: Any) -> str:
    """Serialise a dataclass tree to indented JSON."""
    from dataclasses import asdict, is_dataclass
    from enum import Enum

    def convert(node: Any) -> Any:
        if is_dataclass(node) and not isinstance(node, type):
            return {k: convert(v) for k, v in asdict(node).items()}
        if isinstance(node, Enum):
            return node.name
        if isinstance(node, dict):
            return {k: convert(v) for k, v in node.items()}
        if isinstance(node, (list, tuple)):
            return [convert(v) for v in node]
        return node

    return json.dumps(convert(value), indent=2, ensure_ascii=False)


def _type_label(value: Any) -> str:
    return value.name if value is not None else "?"


def _series_row(item: Any) -> str:
    """One line describing a series, for listings."""
    author = getattr(item.author, "name", None) or "-"
    count = getattr(item, "episode_count", None)
    suffix = f"  {count} eps" if count else ""
    return f"{item.id:>9}  [{_type_label(item.type):<10}] {item.title}{suffix}  - {author}"


def _emit(items: Any, out: Any, *, as_json: bool) -> None:
    for item in items:
        print(_dump(item) if as_json else _series_row(item), file=out)


def _client_for(args: argparse.Namespace) -> MangaToon:
    return MangaToon(
        language=args.language,
        transport=args.transport,
        timeout=args.timeout,
        rate_limit=0.0 if args.no_delay else 1.0,
        max_retries=args.retries,
    )


def _run(coro: Any, args: argparse.Namespace) -> int:
    """Execute a command coroutine, mapping expected failures to exit codes."""
    try:
        return asyncio.run(coro)
    except NotAvailable as exc:
        kind = "locked or unavailable" if exc.looks_locked else "unavailable"
        print(f"error: episode {exc.episode_id} is {kind}: {exc}", file=sys.stderr)
        return 3
    except DirectAccessBlocked as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4
    except (TransportError, APIError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 5
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 6
    except MangaToonError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


# -- commands -------------------------------------------------------------


async def cmd_search(args: argparse.Namespace) -> int:
    async with _client_for(args) as client:
        results = client.iter_search(
            args.query, type=_parse_type(args.type), limit=args.limit, max_pages=args.pages
        )
        shown = 0
        async for page in results:
            if not shown and not args.json:
                print(f"results for {args.query!r}:\n", file=sys.stderr)
            _emit(page.items, sys.stdout, as_json=args.json)
            shown += len(page.items)
    if not shown:
        print("no results", file=sys.stderr)
        return 7
    return 0


async def cmd_browse(args: argparse.Namespace) -> int:
    async with _client_for(args) as client:
        results = client.iter_browse(
            type=_parse_type(args.type), limit=args.limit, order=args.order, max_pages=args.pages
        )
        shown = 0
        async for page in results:
            if not shown and not args.json:
                print(f"{args.order} {args.type or 'all'}:\n", file=sys.stderr)
            _emit(page.items, sys.stdout, as_json=args.json)
            shown += len(page.items)
    return 0 if shown else 7


async def cmd_detail(args: argparse.Namespace) -> int:
    async with _client_for(args) as client:
        series = await client.get_detail(args.content_id)
        if args.json:
            print(_dump(series))
            return 0
        print(f"{series.title}")
        print(f"  id       {series.id}  [{_type_label(series.type)}]")
        print(f"  author   {getattr(series.author, 'name', None) or '-'}")
        print(f"  episodes {series.episode_count if series.episode_count is not None else '?'}")
        print(f"  category {series.category_name or '-'}")
        print(f"  status   {'finished' if series.is_end else 'ongoing'}")
        if series.tag_names:
            print(f"  tags     {', '.join(series.tag_names)}")
        if series.description:
            print(f"\n{series.description.strip()}")
    return 0


async def cmd_chapters(args: argparse.Namespace) -> int:
    async with _client_for(args) as client:
        episodes = await client.episodes(args.content_id)
        if args.json:
            print(_dump(episodes))
            return 0
        free = sum(1 for e in episodes if not e.is_fee)
        print(f"{len(episodes)} episodes ({free} free, {len(episodes) - free} paywalled)")
        print("  $ paywalled   M mature\n", file=sys.stderr)
        for episode in episodes:
            # Trailing flag keeps the id column aligned for plain `cut`/`awk`.
            flags = ("$" if episode.is_fee else "") + ("M" if episode.is_mature else "")
            print(f"{episode.id:>9}  {episode.title}  {flags}".rstrip(), file=sys.stdout)
    return 0


async def cmd_read(args: argparse.Namespace) -> int:
    async with _client_for(args) as client:
        if args.kind == "novel":
            chapter = await client.get_novel_chapter(args.episode_id, markdown=args.markdown)
            if args.json:
                print(_dump(chapter))
                return 0
            if chapter.title:
                print(f"# {chapter.title}\n")
            for paragraph in chapter.paragraphs:
                print(paragraph)
                print()
            return 0

        chat = await client.get_chat_chapter(args.episode_id)
        if args.json:
            print(_dump(chat))
            return 0
        if chat.title:
            print(f"# {chat.title}\n")
        for message in chat.messages:
            if message.is_image:
                print(f"[image] {message.image_url or message.image_path or ''}")
            elif message.is_narration:
                print(f"  {message.content or ''}")
            else:
                print(f"{chat.speaker(message) or '?'}: {message.content or ''}")
    return 0


async def cmd_pages(args: argparse.Namespace) -> int:
    if args.download and not args.output:
        print("error: --download needs --output DIR", file=sys.stderr)
        return 2

    async with _client_for(args) as client:
        pages = await client.get_comic_pages(args.episode_id)
        if not args.download:
            if args.json:
                print(_dump(pages))
            else:
                print(f"{len(pages)} pages")
                for number, page in enumerate(pages, start=1):
                    print(f"{number:>4}  {page.width:>5}x{page.height:<5}  {page.url}")
            return 0

        import pathlib

        directory = pathlib.Path(args.output)
        directory.mkdir(parents=True, exist_ok=True)
        for number, page in enumerate(pages, start=1):
            destination = directory / f"{number:04d}.jpg"
            if destination.exists() and not args.force:
                print(f"skip {destination.name} (exists)", file=sys.stderr)
                continue
            print(f"get  {page.url}", file=sys.stderr)
            # Through the transport, not httpx directly: the CDN shares hosts
            # with the API, so this must work when the origin needs a proxy.
            body = await client.fetch_bytes(page.url)
            destination.write_bytes(body)
            print(f"  -> {destination} ({len(body)} bytes)", file=sys.stderr)
        print(f"saved {len(pages)} pages to {directory}")
    return 0


async def cmd_comments(args: argparse.Namespace) -> int:
    async with _client_for(args) as client:
        entries = await client.comments(args.content_id, page=args.page, limit=args.limit)
        if args.json:
            print(_dump(entries))
            return 0
        for entry in entries:
            print(f"- {entry.nickname or 'anonymous'}: {entry.content}")
    return 0 if entries else 7


# -- parser ---------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mangatoon",
        description="Read MangaToon and NovelToon comics, novels and chat stories.",
    )
    parser.add_argument("--language", default="en", help="API language (default: en)")
    parser.add_argument(
        "--transport",
        choices=("auto", "direct", "proxy"),
        default="auto",
        help="network path; auto probes direct then falls back to a proxy (default: auto)",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="request timeout seconds")
    parser.add_argument("--retries", type=int, default=3, help="retries per request")
    parser.add_argument(
        "--no-delay", action="store_true", help="do not rate limit (use sparingly)"
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_listing(target: argparse.ArgumentParser) -> None:
        target.add_argument("--type", choices=tuple(_TYPES), default="all", help="catalogue filter")
        target.add_argument("--limit", type=int, default=20, help="results per page")
        target.add_argument("--pages", type=int, default=1, help="max pages to fetch")

    p = sub.add_parser("search", help="search titles")
    p.add_argument("query")
    add_listing(p)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("browse", help="list a catalogue")
    p.add_argument("--order", choices=("hot", "new"), default="hot")
    add_listing(p)
    p.set_defaults(func=cmd_browse)

    p = sub.add_parser("detail", help="series metadata")
    p.add_argument("content_id", type=int)
    p.set_defaults(func=cmd_detail)

    p = sub.add_parser("chapters", help="episode list; $ marks paywalled")
    p.add_argument("content_id", type=int)
    p.set_defaults(func=cmd_chapters)

    p = sub.add_parser("read", help="print a novel or chat episode")
    p.add_argument("episode_id", type=int)
    p.add_argument("--kind", choices=("novel", "chat"), required=True)
    p.add_argument("--markdown", action="store_true", help="novel: prefer the markdown variant")
    p.set_defaults(func=cmd_read)

    p = sub.add_parser("pages", help="comic episode page URLs, or download them")
    p.add_argument("episode_id", type=int)
    p.add_argument("--download", action="store_true", help="fetch the images")
    p.add_argument("--output", help="directory for --download")
    p.add_argument("--force", action="store_true", help="re-download existing files")
    p.set_defaults(func=cmd_pages)

    p = sub.add_parser("comments", help="reader comments")
    p.add_argument("content_id", type=int)
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_comments)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return _run(args.func(args), args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
