# mangatoon-sdk

Async Python SDK for the **MangaToon / NovelToon** content API. Retrieves
comics, novels and **chat stories** — including chat story text, which the
website does not otherwise expose.

Only dependency is `httpx`. Python 3.11+.

```bash
pip install mangatoon-sdk
```

## Quick start

```python
import asyncio
from mangatoon import MangaToon, ContentType

async def main() -> None:
    async with MangaToon(language="en") as mt:
        results = await mt.search("romance", type=ContentType.CHAT_STORY)
        for item in results:
            print(item.id, item.title)

asyncio.run(main())
```

## Reading content

Chapter readers are **separate per content type**, because the payloads and
return types genuinely differ:

```python
async with MangaToon() as mt:
    series   = await mt.get_detail(6067953)
    episodes = await mt.episodes(6067953)

    if series.type is ContentType.CHAT_STORY:
        chapter = await mt.get_chat_chapter(episodes[0].id)
        print(chapter.render())          # speaker names inlined

    elif series.type is ContentType.NOVEL:
        chapter = await mt.get_novel_chapter(episodes[0].id, markdown=True)
        print(chapter.text)              # paragraphs joined by blank lines

    else:                                 # COMIC
        for page in await mt.get_comic_pages(episodes[0].id):
            print(page.url)               # fetch as-is, no decryption needed
```

`get_comic_pages` returns CDN URLs that need **no** decryption. Novel and chat
chapter payloads are obfuscated and are decoded transparently by the SDK.

## Chat stories

Chat stories are **API-only** — `/{lang}/watch/{id}/{n}` returns a 404 and the
site hides the episode list. A chat chapter is a list of bubbles plus a
character roster:

```python
chapter = await mt.get_chat_chapter(4209230)

for msg in chapter.messages:
    if msg.is_dialogue:
        print(chapter.speaker(msg), "->", msg.content)
    elif msg.is_image:
        print("[image]", msg.image_url)
```

`ChatMessageType` distinguishes `NARRATION` (1), `DIALOGUE` (2) and `IMAGE` (3).
`chapter.render()` produces a plain transcript.

## Browsing

```python
await mt.browse(type=ContentType.NOVEL, order="new")
await mt.browse(type=ContentType.CHAT_STORY, order="hot")

async for page in mt.iter_browse(type=ContentType.NOVEL, max_pages=5):
    ...
```

`page` is **1-indexed**; the API rejects `page=0`.

## Paywalled chapters

Paid episodes raise `PaymentRequired` rather than being silently skipped. This
SDK does not bypass paywalls.

```python
from mangatoon import PaymentRequired

try:
    chapter = await mt.get_novel_chapter(ep_id)
except PaymentRequired:
    ...
```

## Network reachability

`mangatoon.mobi` is unreachable on some networks while general internet access
works. The default `"auto"` transport probes the origin once, then either talks
to it directly or falls back to a read proxy, and re-probes if things change.

```python
MangaToon(transport="direct")   # origin only; fails fast when blocked
MangaToon(transport="proxy")    # always proxy
MangaToon(transport="auto")     # default: detect at runtime
```

Check which one is in use via `mt.active_transport_name`. The rate limiter
defaults to 1 request/second; raise it only if you know the origin allows more.

## How the API works

Every request carries an MD5 signature over the path and its sorted query
string, using an anonymous device id. No account or token is required.

Chapter payloads are served as `application/octet-stream` and protected by a
byte-substitution cipher: two 256-byte permutation tables plus a per-file
rotation offset. The offset is recovered by brute force over all 256 candidates;
in practice exactly one yields a well-formed header.

Two constants encode the current protocol — the signing salt in
`_signing.SIGNING_SALT` and the API version in `_signing.API_VERSION`. If
requests start failing, check those first.

## Testing

Tests run entirely offline against recorded fixtures:

```bash
pip install -e ".[test]"
pytest
```

## Legal

Respect MangaToon's Terms of Use and `robots.txt`. Fetch only what you are
entitled to, rate-limit responsibly, and do not redistribute copyrighted
content.

## License

MIT
