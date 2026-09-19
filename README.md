# shimeji-dl

An asynchronous downloader that turns remote Shimeji sources into packages ready for Shimeji-ee, VShimeji, and compatible alternatives.

## Features

- Multiple sources and exact package inventories.
- XML and adaptive asset discovery.
- Sprite-atlas, image, and audio handling.
- Native layout and persistent local reuse.
- Concurrent downloads and compact reporting.

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

By default, output is written using the native layout shared by Shimeji-ee, VShimeji, and compatible alternatives:

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
Point `--output` at the installation root of Shimeji-ee, VShimeji, or a compatible alternative to install downloaded image sets directly under its `img/` directory.  
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

## How assets are found

1. **Read the Source Manifest When Available**  
Use the exact configuration, metadata, and asset inventory whenever the source provides a manifest.
2. **Extract Sprite Atlases**  
Split source-provided sprite atlases into the individual PNG files expected by Shimeji-ee, VShimeji, and compatible alternatives.
3. **Look for Standard Configuration Files**  
Fetch `actions.xml`, `behaviors.xml`, and optional `info.xml` directly when the manifest does not supply them.
4. **Follow Configuration References**  
Find the images, preview images, splash images, and sounds named by the configuration.
5. **Download Remaining Files**  
Download referenced resources not supplied by the sprite atlas, placing sounds under the character's `sound/` directory.
6. **Report Missing Source Files**  
Distinguish assets absent from the published package from temporary download failures.
7. **Fall Back to Adaptive Discovery**  
Use adaptive numeric discovery when a manifest is unavailable or cannot be loaded.  
Explicit `--probe deep` also searches beyond the published inventory.
8. **Continue Around Successful Ranges**  
Search around discovered image numbers and across occasional gaps without imposing a fixed upper limit.
9. **Download Only Referenced Sounds**  
Download sounds only when configuration references them; audio filenames are never numerically probed.
10. **Honor Strict Mode**  
Source omissions still make a package incomplete under `--strict`, but they are not retried indefinitely.

`--probe auto` is the default.  
`--probe deep` widens sparse-tail exploration.  
`--probe off` disables numeric probing entirely.

## shimejis.xyz support

- Accepts slugs, character URLs, pack URLs, and directory targets.
- Reads `/api/shimeji/<slug>/configuration` for the exact package inventory.
- Uses published configuration, metadata, sprite maps, and spritesheets.
- Falls back to the legacy sprite CDN layout.
- Identifies assets omitted from the public source package.

## Dependencies

Each runtime dependency replaces a concrete piece of infrastructure rather than duplicating it locally:

- `httpx` - Async HTTP transport and connection pooling.
- `tenacity` - Retry policy and exponential backoff.
- `lxml` - HTML/XML parsing and XPath.
- `Pillow` - Safe extraction of individual PNG files from source-provided sprite atlases.
- `rich` - Concurrent terminal progress, wrapping output and interactive confirmations.
- `typer` - CLI declaration, validation, help and option parsing.

## Useful options

| Option | Description |
| --- | --- |
| `-o, --output PATH` | Set the Shimeji installation or download root. |
| `-j, --jobs INTEGER` | Set concurrent character downloads, defaulting to `5`. |
| `--connections INTEGER` | Set concurrent HTTP connections, defaulting to `20`. |
| `--timeout FLOAT` | Set the HTTP timeout in seconds, defaulting to `20`. |
| `--retries INTEGER` | Set HTTP retry attempts, defaulting to `3`. |
| `--probe auto\|off\|deep` | Select the adaptive asset discovery mode. |
| `--overwrite` | Replace existing valid files. |
| `--retry` | Retry failed characters automatically. |
| `-y, --yes` | Accept confirmation prompts automatically. |
| `--strict` | Fail when a character or referenced asset is incomplete. |
| `--metadata / --no-metadata` | Enable or disable `metadata.json`. |
| `--archive` | Create a ZIP archive after downloading. |
| `-v, --verbose` | Show detailed discovery and URL diagnostics. |
| `-q, --quiet` | Suppress progress output. |
| `--version` | Print the installed version. |

## License

MIT License. See [LICENSE](LICENSE).  
THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED.

## LLM Notice

Large language models, including Codex and Claude Code, were used in the development of this project.
