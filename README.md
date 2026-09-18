# shimeji-dl

Asynchronous Shimeji downloader with pluggable source adapters, XML-driven asset discovery, adaptive numeric probing, persistent local reuse, and concurrent terminal progress.

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

By default, output is written to `shimeji-downloads/`.

## Existing downloads

Existing valid configuration files and images are reused by default.  
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

The generic downloader only talks to protocols (`SourceAdapter`, `ConfigFormat`, `Reporter`).  
Adding another site does not require modifying the probing engine or download core.

## XML + adaptive probing

1. **Fetch Configuration** - Fetch `actions.xml` and `behaviors.xml` when the source exposes them.
2. **Parse XML** - Parse configuration with `lxml` and discover every referenced image path.
3. **Download References** - Download XML-referenced assets as authoritative resources.
4. **Use XML Anchors** - Feed numeric `shimeN.png` references into the adaptive explorer as known anchors.
5. **Probe Adaptively** - Probe the numeric namespace even when XML exists, so unreferenced extras can still be discovered.
6. **Gallop On Success** - Increase the search distance exponentially while probes continue to match.
7. **Bisect On Failure** - Narrow the dense frontier after the first failed exponential probe.
8. **Explore Quiescence** - Search beyond the frontier using a quiet span derived from observed gaps and namespace size instead of a fixed index ceiling.
9. **Separate Failure Semantics** - Treat XML-referenced misses as completeness errors while normal probe misses remain expected discovery evidence.

`--probe auto` is the default. `--probe deep` widens sparse-tail exploration, and `--probe off` disables numeric probing entirely.

## Dependencies

Each runtime dependency replaces a concrete piece of infrastructure rather than duplicating it locally:

- `httpx` - Async HTTP transport and connection pooling.
- `tenacity` - Retry policy and exponential backoff.
- `lxml` - HTML/XML parsing and XPath.
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

MIT License. See `LICENSE`.  
THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED.

## LLM Notice

Large language models, including Codex and Claude Code, were used in the development of this project.
