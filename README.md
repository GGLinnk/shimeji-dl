# shimeji-dl

Asynchronous Shimeji downloader with pluggable source adapters, XML-driven asset discovery, and adaptive numeric probing.

## Install / run with uv

```bash
uv run shimeji-dl https://shimejis.xyz/directory/undertale-shimeji-pack
```

```bash
uv run shimeji-dl https://shimejis.xyz/directory/shimeji/undertale-nightmare-sans-by-niuniu-nuko
```

By default, output is written to `shimeji-downloads/`.

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
│   └── rich.py            # Rich progress/reporting
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
- `rich` - Concurrent terminal progress and formatted reporting.
- `typer` - CLI declaration, validation, help and option parsing.

## Useful options

```text
-o, --output PATH
-j, --jobs INTEGER
--connections INTEGER
--timeout FLOAT
--retries INTEGER
--probe auto|off|deep
--force
--strict
--metadata / --no-metadata
--archive
-v, --verbose
-q, --quiet
--version
```

## License

MIT License. See `LICENSE`.
