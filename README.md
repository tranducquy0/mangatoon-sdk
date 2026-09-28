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

This SDK does not bypass paywalls, and never tries. A locked episode reports
itself as `NotAvailable` rather than failing with a generic error, and the
`looks_locked` flag records how confident the SDK is about that reading.

```python
from mangatoon import NotAvailable, PaymentRequired

try:
    chapter = await mt.get_novel_chapter(ep_id)
except NotAvailable as exc:
    if exc.looks_locked:
        print("locked, or not published yet")
except PaymentRequired:
    print("flagged as paid with no readable payload")
```

The API reports a locked episode the same way as a nonexistent one — `status:
"error"` with `error_code: 404` and the message *"This episode is not ready for
online right now."* — so the two cannot be separated with certainty. That is
why the exception carries `looks_locked` instead of asserting the reason.
`PaymentRequired` is reserved for the rarer case where the API returns a
successful response that is flagged `is_fee` yet carries no payload.

`episode.is_fee` marks a paywalled chapter up front, so you can filter an
episode list without triggering any of this:

```python
episodes = await mt.episodes(content_id)
free = [e for e in episodes if not e.is_fee]
```

## Command line

Installing the package also provides a `mangatoon` command covering the same
operations, with `--json` for scripting:

```bash
mangatoon search "romance" --type novel
mangatoon detail 6067953
mangatoon chapters 6067953              # $ marks a paywalled episode
mangatoon read 4209230 --kind chat
mangatoon pages 5150000 --download --output ./ch1
mangatoon --json browse --type comic --order new | jq '.[].title'
```

Exit codes: `0` ok, `2` bad arguments, `3` locked or unavailable, `4` origin
unreachable, `5` API or transport error, `7` no results.

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

### A caveat about proxies

The public proxies this SDK falls back to are a best-effort convenience, not
infrastructure. JSON endpoints usually work, but chapter payloads go through
free CORS proxies that **throttle aggressively**; they rotate through
`DEFAULT_BINARY_PROXIES` and can still return `429` for every candidate. A
`TransportError` naming each proxy it tried is the expected symptom, and the
fix is to wait, fetch fewer episodes, or supply your own:

```python
MangaToon(transport="proxy", binary_proxies=("https://your-proxy/?url=",))
```

Prefer `transport="direct"` on a network that can reach the origin — it is both
faster and free of these limits. Comic page images also route through the
transport, so `mt.fetch_bytes(url)` works behind a proxy where a bare
`httpx.get` would not.

Proxied requests deliberately omit the browser `User-Agent` used for direct
access: the read proxy challenges browser-like agents.

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
