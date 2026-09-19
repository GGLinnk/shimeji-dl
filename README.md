# shimeji-dl

Asynchronous Shimeji downloader with pluggable source adapters, optional source manifests, XML-driven asset discovery, adaptive numeric probing, persistent local reuse, and concurrent terminal progress.

## Install / run with uv

From a checkout:

```bash
uv run shimeji-dl https://shimejis.xyz/directory/undertale-shimeji-pack
```

Once published as a package:

```bash
uvx shimeji-dl https://shimejis.xyz/directory/undertale-shimeji-pack
```

A character URL or slug is also accepted:

```bash
uv run shimeji-dl https://shimejis.xyz/directory/shimeji/undertale-nightmare-sans-by-niuniu-nuko
uv run shimeji-dl undertale-nightmare-sans-by-niuniu-nuko
```

By default, output is written using the native Shimeji-ee / VShimeji layout:

```text
shimeji-downloads/
└── img/
    └── <character>/
        ├── shime*.png
        ├── sound/
        │   └── ...
        ├── conf/
        │   ├── actions.xml
        │   ├── behaviors.xml
        │   └── info.xml
        └── metadata.json
```

`info.xml` and `sound/` are created only when those resources are available or referenced.  
Point `--output` at a Shimeji-ee / VShimeji installation root to install downloaded image sets directly under its `img/` directory.  
If the supplied output directory is itself named `img`, it is used directly instead of creating `img/img`.

## Existing downloads

Existing valid configuration files, images, and referenced sounds are reused by default.  
Re-running the same command therefore does not download files that are already present and valid.

Use `--overwrite` to explicitly refresh and replace existing valid files:

```bash
uv run shimeji-dl https://shimejis.xyz/directory/undertale-shimeji-pack --overwrite
```

An internal retry never overwrites successful files from the preceding attempt.  
It retries only failed characters and reuses everything that was already downloaded successfully.

## Retry and confirmations

When one or more characters fail, an interactive terminal offers to retry only those failed characters once.

Use `--retry` to perform that retry automatically:

```bash
uv run shimeji-dl https://shimejis.xyz/directory/undertale-shimeji-pack --retry
```

`--yes` / `-y` answers yes to all confirmation prompts, including the retry prompt and potentially expensive target validations:

```bash
uv run shimeji-dl https://shimejis.xyz --yes
```

Downloading the entire `shimejis.xyz` directory requires confirmation unless `--yes` is supplied.

## Architecture

The project deliberately separates reusable mechanics from source-specific behavior:

```text
src/shimeji_dl/
├── core/                  # Generic HTTP, models, engine, storage and adaptive probing
├── formats/               # Shimeji configuration formats
│   └── shimeji_xml.py     # lxml-backed XML implementation
├── sources/               # Remote source adapters
│   └── shimejis_xyz/      # shimejis.xyz extraction and URL layout
├── ui/                    # Presentation implementations
│   └── rich.py            # Rich progress/reporting and confirmations
├── cli.py                 # Typer CLI composition root
└── version.py             # Reads installed metadata; pyproject.toml is the SSOT
```

The generic downloader only talks to protocols (`SourceAdapter`, optional `ManifestSourceAdapter`, `ConfigFormat`, and `Reporter`).

Adding another site does not require modifying the probing engine or download core.
A source can optionally expose an authoritative manifest and sprite atlas without making that capability mandatory for other adapters.

## Discovery and fallback strategy

1. **Use a Source Manifest When Available** - The `shimejis.xyz` adapter reads `/api/shimeji/<slug>/configuration`, including the exact XML, sprite map, spritesheet URL, and public metadata.
2. **Materialize the Sprite Atlas** - The generic engine safely crops manifest regions into the individual PNG files expected by Shimeji-ee and VShimeji.
3. **Fetch Configuration Fallbacks** - Fetch `actions.xml`, `behaviors.xml`, and optional `info.xml` from traditional source URLs when no manifest supplies them.
4. **Parse XML** - Parse configuration with `lxml` and discover referenced images, preview/splash images, and sounds.
5. **Download Remaining References** - Download XML-referenced resources not supplied by the atlas, placing sounds under the character's `sound/` directory.
6. **Classify Source Omissions** - A manifest-backed source distinguishes assets absent from its public package from retryable transfer failures.
7. **Keep Probing Available** - The original adaptive numeric strategy remains the generic fallback for sources without an authoritative manifest or whenever manifest retrieval fails.
   Explicit `--probe deep` also probes beyond an authoritative manifest.
8. **Gallop, Bisect, and Explore Quiescence** - The fallback prober expands successful ranges, narrows the frontier, and searches sparse tails without a fixed index ceiling.
9. **Avoid Sound Guessing** - Download sounds only when configuration references them; audio filenames are never numerically probed.
10. **Preserve Strict Semantics** - Source omissions still make a package incomplete under `--strict`, but they are not retried indefinitely.

`--probe auto` is the default.  
`--probe deep` widens sparse-tail exploration.  
`--probe off` disables numeric probing entirely.

## Dependencies

Each runtime dependency replaces a concrete piece of infrastructure rather than duplicating it locally:

- `httpx` - Async HTTP transport and connection pooling.
- `tenacity` - Retry policy and exponential backoff.
- `lxml` - HTML/XML parsing and XPath.
- `Pillow` - Safe extraction of individual PNG files from source-provided sprite atlases.
- `rich` - Concurrent terminal progress, wrapping output and interactive confirmations.
- `typer` - CLI declaration, validation, help and option parsing.

## Useful options

```text
-o, --output PATH
-j, --jobs INTEGER
--connections INTEGER
--timeout FLOAT
--retries INTEGER
--probe auto|off|deep
--overwrite
--retry
-y, --yes
--strict
--metadata / --no-metadata
--archive
-v, --verbose
-q, --quiet
--version
```

## License

MIT License.
See `LICENSE`.
THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED.

## LLM Notice

Large language models, including Codex and Claude Code, were used in the development of this project.
