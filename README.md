# shimeji-dl

`shimeji-dl` is an asynchronous, extractor-based downloader for Shimeji character packs.
Source extraction is separated from downloading, downloads are concurrent and resumable, XML is preserved, sprite discovery combines authoritative metadata with adaptive probing, and every character gets a machine-readable manifest.

The first extractor supports **shimejis.xyz** pack URLs, character URLs and raw slugs.

## Requirements

- Python 3.10+
- Windows, macOS or Linux
- [`uv`](https://docs.astral.sh/uv/)

## Setup

```console
uv sync
uv run shimeji-dl https://shimejis.xyz/directory/undertale-shimeji-pack
```

Or install it as a tool:

```console
uv tool install .
shimeji-dl https://shimejis.xyz/directory/undertale-shimeji-pack
```

## Inputs

```console
shimeji-dl https://shimejis.xyz/directory/undertale-shimeji-pack
shimeji-dl https://shimejis.xyz/directory/shimeji/undertale-nightmare-sans-by-niuniu-nuko
shimeji-dl undertale-nightmare-sans-by-niuniu-nuko
```

Multiple targets are accepted; duplicate characters are downloaded once.

## Output

```text
shimeji-downloads/
└── undertale-nightmare-sans-by-niuniu-nuko/
    ├── shime1.png
    ├── ...
    ├── conf/
    │   ├── actions.xml
    │   └── behaviors.xml
    └── metadata.json
```

The character directory is directly usable as a VShimeji image-set directory.

## XML + adaptive probing

Sprite discovery is deliberately **not bounded by a `--probe-max` or `--probe-limit` number**.

For each character, `shimeji-dl`:

1. Fetches `actions.xml` and `behaviors.xml` when the source exposes them;
2. Parses every image reference from both XML files;
3. Downloads all XML-referenced assets exactly, including custom names and nested paths;
4. Treats conventional `shimeN.png` references as numeric anchors;
5. Probes the numeric namespace **even when XML exists**, so unused/unreferenced sprites can still be archived;
6. Gallops from the highest known hit using `+1, +2, +4, +8, ...`;
7. On the first miss, bisects the hit/miss interval to locate the dense frontier efficiently;
8. Fills the discovered range so skipped sprites are actually downloaded;
9. Searches beyond the frontier until it reaches an adaptive **quiescent tail** derived from the pack's observed gaps and search span.

In other words:

```text
final sprites = XML referenced assets ∪ adaptively probed numeric assets
```

There is no fixed highest sprite number.
A character with `shime257.png`, `shime1000.png`, etc. can continue extending the search as long as discoveries provide evidence that the namespace continues.

No HTTP algorithm can prove that an infinite filename namespace contains no isolated file arbitrarily far away.
`auto` therefore stops on evidence-based quiescence rather than pretending a fixed numeric ceiling is complete.

### Probe modes

```console
shimeji-dl URL --probe auto   # default: XML + adaptive probing
shimeji-dl URL --probe off    # XML only
shimeji-dl URL --probe deep   # wider sparse-tail exploration
```

`--no-probe` remains as a compatibility alias for `--probe off`.

`deep` does not introduce a larger maximum index.
It increases the amount of empty space required before the numeric namespace is considered quiescent.

## Async/concurrency

Character concurrency and HTTP concurrency are independent:

```console
shimeji-dl URL -j 8 --connections 32
```

Defaults:

- 5 characters concurrently
- 20 HTTP requests concurrently
- 3 retries
- 20 second timeout

The adaptive probe itself works in async batches while the shared HTTP client enforces the global connection limit.

All files are written atomically through `.part` files.
Existing valid files are reused unless `--force` is supplied.

## Missing resources and strict mode

An XML reference is authoritative.  
If it cannot be downloaded:

```text
warning: referenced-missing: shime56.png
```

With `-v`, every attempted URL is displayed.

```console
shimeji-dl URL --strict
```

`--strict` returns a non-zero status when a character is unusable or an XML-referenced image is missing.
Probe misses are normal discovery evidence and never fail strict mode.

## metadata.json

Manifest schema v2 records, among other things:

- source/extractor and tool version;
- `actions.xml` and `behaviors.xml` source information;
- All XML-referenced images;
- All downloaded sprites;
- Probe-only discoveries;
- Numeric XML anchors;
- gallop, bisection, fill and quiescence probe counts;
- Highest hit / highest tested index;
- Adaptive quiescence span and stop reason;
- Missing XML-referenced resources;
- Completeness classification.

Completeness deliberately means **XML completeness**, not proof that no unreferenced file exists somewhere in an unbounded HTTP namespace.

## Useful options

```text
-o, --output PATH       output directory
-j, --jobs N            concurrent characters
--connections N         concurrent HTTP requests
--probe auto|off|deep   adaptive numeric discovery
--force                 redownload existing files
--strict                fail on unusable/missing referenced assets
--no-metadata           disable metadata.json
--archive               create <output>.zip afterwards
-v, --verbose           adaptive-probe details
-q, --quiet             minimal output
```

## Development

```console
uv sync --group dev
uv run --group dev pytest
```

Extractors live in `src/shimeji_dl/extractors/`;
Additional sites can be added without coupling source-specific parsing to the download engine.


## License

`shimeji-dl` itself is released under the **MIT License**.
See [`LICENSE`](LICENSE).

Downloaded Shimeji characters, sprites, XML files and other source assets are **not relicensed by shimeji-dl**;
They remain subject to the rights and terms of their respective creators and sources.
