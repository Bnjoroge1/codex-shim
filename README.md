# codex-shim

Run **Codex Desktop** with any model exposed by your local **VibeProxy**
instance, without recompiling Codex.

VibeProxy already speaks the OpenAI Responses API on `http://127.0.0.1:8317`.
This shim simply generates a Codex-compatible model catalog from VibeProxy's
`/v1/models` endpoint (on `http://127.0.0.1:8318`) and points Codex at it
directly. No middleman server.

> Status: tested on Codex Desktop **0.133.0-alpha.1** for macOS arm64.
> Linux/Windows users should be able to skip the ASAR patch section and use the
> shim itself unchanged.

---

## Why

Codex Desktop only shows the models its server-side Statsig config whitelists.
If you have VibeProxy routing to OpenAI / Anthropic / Moonshot / Z.ai /
DeepSeek / Gemini / OpenRouter / etc., this shim surfaces all of those models
as first-class picker entries.

---

## Install

```bash
git clone https://github.com/<you>/codex-shim ~/Documents/codex-shim
cd ~/Documents/codex-shim
python3 -m pip install --user -e .
```

Requires Python 3.11+ and `aiohttp`.

---

## Quick start

### 1. Make sure VibeProxy is running

The shim expects:
- Model list at `http://127.0.0.1:8318/v1/models`
- API at `http://127.0.0.1:8317/v1`

(Use `--vibeproxy-url` and `--vibeproxy-api-url` if yours is elsewhere.)

### 2. Generate the catalog

```bash
codex-shim generate          # reads VibeProxy /v1/models, writes catalog
codex-shim list              # show generated slugs and upstream routes
```

### 3. Point Codex Desktop at it (no global config changes)

```bash
codex-shim app .             # launch Codex with the shim wired in
```

That command applies opt-in `-c` overrides only for this launch. Your
`~/.codex/config.toml` is left untouched. After this Codex Desktop sees every
model VibeProxy exposes as picker entries.

If your Codex Desktop's model picker only shows "default" and refuses to render
the catalog entries, you also need the **picker patch** below.

### 4. (Optional) Switch the active Desktop model

```bash
codex-shim model list
codex-shim model use gpt-5.5      # or kimi-k2.6, etc.
codex-shim app .                   # relaunch Codex with new default
```

---

## Custom VibeProxy URL

```bash
codex-shim --vibeproxy-url http://localhost:8318 --vibeproxy-api-url http://localhost:8317 generate
codex-shim --vibeproxy-url http://localhost:8318 --vibeproxy-api-url http://localhost:8317 app
```

---

## Picker patch for Codex Desktop on macOS

Codex Desktop has a Statsig server-side allowlist (`use_hidden_models: true`)
that hides any model whose slug isn't on a hardcoded list. Custom catalog
entries fall into the hidden bucket and never render in the picker.

A single‑boolean ASAR patch flips the allowlist branch off so the picker only
checks the local `hidden` flag (which our catalog never sets).

> **Always back up `app.asar` and `Info.plist` before patching.**

```bash
APP=/Applications/Codex.app
sudo cp -R "$APP" "$APP.unpatched-$(date +%Y%m%d-%H%M%S)"

# 1. Extract the ASAR
cd /tmp && rm -rf codex-asar-patch && mkdir codex-asar-patch && cd codex-asar-patch
npx --yes @electron/asar extract "$APP/Contents/Resources/app.asar" extracted

# 2. Patch the picker filter (this match is single-occurrence, unique to that file)
PATCH_FILE=$(grep -RIl 'useHiddenModels' extracted/webview/assets/model-queries-*.js | head -n1)
sed -i.bak -E 's/let u=c\.useHiddenModels&&o!==`amazonBedrock`,d;/let u=!1,d;/' "$PATCH_FILE"
diff "$PATCH_FILE.bak" "$PATCH_FILE" || true   # confirm exactly one change
rm "$PATCH_FILE.bak"

# 3. Repack
npx --yes @electron/asar pack extracted app.asar.new
sudo cp app.asar.new "$APP/Contents/Resources/app.asar"
```

That alone will crash Codex on next launch with `EXC_BREAKPOINT`. Electron's
`ElectronAsarIntegrity` field in `Info.plist` is a SHA-256 of the **JSON
header** of the asar archive (not the whole file). Recompute it and re-sign:

```bash
# 4. Compute new header hash
HEADER_HASH=$(python3 - "$APP/Contents/Resources/app.asar" <<'PY'
import struct, hashlib, sys
with open(sys.argv[1], 'rb') as f:
    data_size, header_size, _, json_size = struct.unpack('<4I', f.read(16))
    header_json = f.read(json_size)
print(hashlib.sha256(header_json).hexdigest())
PY
)
echo "new header hash: $HEADER_HASH"

# 5. Patch Info.plist (replaces the hash for Resources/app.asar)
sudo /usr/libexec/PlistBuddy -c \
  "Set :ElectronAsarIntegrity:Resources/app.asar:hash $HEADER_HASH" \
  "$APP/Contents/Info.plist"

# 6. Ad-hoc re-sign (drops Apple signature; Gatekeeper will warn once)
sudo codesign --force --deep --sign - "$APP"

# 7. Launch
open "$APP"
```

To roll back: `sudo rm -rf "$APP" && sudo mv "$APP.unpatched-…" "$APP"`.

---

## How it works

```
Codex Desktop ── /v1/responses ──▶ VibeProxy (127.0.0.1:8317)
```

Because VibeProxy already speaks the OpenAI Responses API, there is no need
for a middleman proxy. The shim only does one thing:

1. **Catalog generation** — fetches `/v1/models` from VibeProxy and builds a
   Codex-compatible `custom_model_catalog.json` with inferred context windows,
   reasoning levels, and metadata.

Codex then talks to VibeProxy directly.

---

## MCP

Codex Desktop forwards three generic MCP tools to every model:

- `list_mcp_resources`
- `list_mcp_resource_templates`
- `read_mcp_resource`

It does **not** flatten individual MCP server tools into the function list.
That's a Codex client behavior, not a shim limitation. Shim-routed models
receive the same MCP tools as built-in OpenAI models. The model is expected
to call `list_mcp_resources` to discover what's available.

---

## Commands

```
codex-shim generate         regenerate catalog/config
codex-shim list             list generated slugs and VibeProxy routes
codex-shim enable           install shim config into ~/.codex/config.toml
codex-shim disable          restore original ~/.codex/config.toml
codex-shim model list       list slugs currently usable in the picker
codex-shim model use <slug> set the Desktop default model
codex-shim codex -- <args>  exec `codex` CLI through the shim
codex-shim app [path]       launch Codex Desktop through the shim
```

All commands accept `--vibeproxy-url <url>` and `--vibeproxy-api-url <url>`.

---

## File layout

```
codex_shim/             python source (catalog + cli + settings)
bin/                    wrapper scripts (optional, for repo-local use)
.codex-shim/            generated catalog, config, backups (gitignored)
tests/                  pytest suite
```

The shim never edits `~/.codex/config.toml` unless you run `codex-shim enable`
or `codex-shim app`. All Codex overrides are passed inline as `-c key=value`
arguments per launch.

---

## License

MIT — see `LICENSE`.

Codex Desktop is a trademark of OpenAI. VibeProxy is a trademark of Automaze,
Ltd. This project is unaffiliated with either.
