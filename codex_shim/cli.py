from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import struct
import sys

from .catalog import codex_config_overrides, write_catalog, write_config
from .config import CodexConfig
from .settings import VIBEPROXY_URL, VIBEPROXY_API_URL, VibeProxySettings, default_model_slug


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = PROJECT_ROOT / ".codex-shim"
CATALOG_PATH = RUNTIME_DIR / "custom_model_catalog.json"
CONFIG_PATH = RUNTIME_DIR / "config.toml"
CODEX_CONFIG_PATH = Path.home() / ".codex" / "config.toml"
CODEX_CONFIG_BACKUP_PATH = RUNTIME_DIR / "config.toml.before-codex-shim"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex-shim")
    parser.add_argument("--vibeproxy-url", default=VIBEPROXY_URL,
                        help="URL for fetching the model list (default: http://127.0.0.1:8318)")
    parser.add_argument("--vibeproxy-api-url", default=VIBEPROXY_API_URL,
                        help="URL for the Responses/Chat API (default: http://127.0.0.1:8317)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate")
    sub.add_parser("list")
    sub.add_parser("enable")
    sub.add_parser("disable")
    sub.add_parser("toggle", help="Toggle persistent VibeProxy routing in ~/.codex/config.toml.")
    sub.add_parser("status", help="Show whether persistent VibeProxy routing is enabled.")
    sub.add_parser("patch-app", help="Patch Codex Desktop model dropdown to allow custom catalog models.")
    sub.add_parser("restore-app", help="Restore Codex Desktop app.asar from the pre-patch backup.")

    model_parser = sub.add_parser("model", help="List or set the active shim model in Codex config.")
    model_sub = model_parser.add_subparsers(dest="model_command", required=True)
    model_sub.add_parser("list")
    use_parser = model_sub.add_parser("use")
    use_parser.add_argument("model_slug")

    codex_parser = sub.add_parser("codex", help="Run Codex CLI with opt-in shim config overrides.")
    codex_parser.add_argument("args", nargs=argparse.REMAINDER)

    app_parser = sub.add_parser("app", help="Launch Codex Desktop with opt-in shim config overrides.")
    app_parser.add_argument("-m", "--model", dest="model_slug")
    app_parser.add_argument("path", nargs="?", default=".")

    args = parser.parse_args(argv)
    base_url = _effective_base_url(args.vibeproxy_api_url)

    if args.command == "generate":
        generate(args.vibeproxy_url, base_url)
        return 0
    if args.command == "list":
        return list_models(args.vibeproxy_url)
    if args.command == "enable":
        generate(args.vibeproxy_url, base_url)
        models = VibeProxySettings(args.vibeproxy_url).load()
        default_slug = _resolve_model_slug(models, None)
        config = CodexConfig(CODEX_CONFIG_PATH, CODEX_CONFIG_BACKUP_PATH)
        config.install_shim(default_slug, base_url, CATALOG_PATH, provider_name=default_slug)
        return 0
    if args.command == "disable":
        config = CodexConfig(CODEX_CONFIG_PATH, CODEX_CONFIG_BACKUP_PATH)
        config.disable_shim()
        return 0
    if args.command == "toggle":
        config = CodexConfig(CODEX_CONFIG_PATH, CODEX_CONFIG_BACKUP_PATH)
        if config.is_shim_enabled():
            config.disable_shim()
            print("VibeProxy shim: disabled")
        else:
            generate(args.vibeproxy_url, base_url)
            models = VibeProxySettings(args.vibeproxy_url).load()
            default_slug = _resolve_model_slug(models, None)
            config.install_shim(default_slug, base_url, CATALOG_PATH, provider_name=default_slug)
            print("VibeProxy shim: enabled")
        return 0
    if args.command == "status":
        config = CodexConfig(CODEX_CONFIG_PATH, CODEX_CONFIG_BACKUP_PATH)
        print("enabled" if config.is_shim_enabled() else "disabled")
        return 0
    if args.command == "patch-app":
        return patch_codex_app()
    if args.command == "restore-app":
        return restore_codex_app_bundle()
    if args.command == "model":
        if args.model_command == "list":
            return list_models(args.vibeproxy_url)
        if args.model_command == "use":
            generate(args.vibeproxy_url, base_url)
            models = VibeProxySettings(args.vibeproxy_url).load()
            default_slug = _resolve_model_slug(models, args.model_slug)
            config = CodexConfig(CODEX_CONFIG_PATH, CODEX_CONFIG_BACKUP_PATH)
            config.install_shim(default_slug, base_url, CATALOG_PATH, provider_name=default_slug)
            print(f"Active Codex shim model: {args.model_slug}")
            return 0
    if args.command == "codex":
        generate(args.vibeproxy_url, base_url)
        exec_codex(args.vibeproxy_url, base_url, args.args)
        return 0
    if args.command == "app":
        generate(args.vibeproxy_url, base_url)
        models = VibeProxySettings(args.vibeproxy_url).load()
        default_slug = _resolve_model_slug(models, args.model_slug)
        overrides = _override_args(args.vibeproxy_url, base_url, default_slug=default_slug)
        exec_codex_app(args.path, overrides)
        return 0
    return 2


def generate(vibeproxy_url: str, base_url: str) -> None:
    models = VibeProxySettings(vibeproxy_url).load()
    write_catalog(models, CATALOG_PATH)
    default_slug = default_model_slug(models)
    write_config(models, CONFIG_PATH, CATALOG_PATH, base_url, provider_name=default_slug)
    print(f"Generated {len(models)} model entries:")
    print(f"  catalog: {CATALOG_PATH}")
    print(f"  config:  {CONFIG_PATH}")
    print("No files under ~/.codex were modified.")


def list_models(vibeproxy_url: str) -> int:
    models = VibeProxySettings(vibeproxy_url).load()
    width = max([len(m.slug) for m in models] + [4])
    for model in models:
        print(f"{model.slug:<{width}}  {model.display_name}  ->  {model.model} ({model.owned_by})")
    return 0


def exec_codex(vibeproxy_url: str, base_url: str, codex_args: list[str]) -> None:
    overrides = _override_args(vibeproxy_url, base_url)
    codex_args = list(codex_args or [])
    if codex_args[:1] == ["--"]:
        codex_args = codex_args[1:]
    args = ["codex", *overrides, *codex_args]
    os.execvp("codex", args)


def exec_codex_app(path: str, overrides: list[str]) -> None:
    _quit_codex_app()
    args = ["codex", "app", *overrides, path]
    subprocess.Popen(args)
    _foreground_codex_app()


def _quit_codex_app() -> None:
    script = 'tell application "Codex" to if it is running then quit'
    try:
        subprocess.run(["osascript", "-e", script], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import time
        time.sleep(1.0)
    except OSError:
        pass


def patch_codex_app() -> int:
    app_asar = Path("/Applications/Codex.app/Contents/Resources/app.asar")
    backup = RUNTIME_DIR / "app.asar.before-codex-shim-model-picker-patch"
    workdir = RUNTIME_DIR / "app-asar-work"
    needle = "let u=c.useHiddenModels&&o!==`amazonBedrock`,d;"
    replacement = "let u=!1,d;"

    if not app_asar.exists():
        print(f"Codex app bundle not found at {app_asar}.", file=sys.stderr)
        return 1
    if not _has_command("npx"):
        print("npx is required to patch the Electron asar bundle.", file=sys.stderr)
        return 1

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        backup.write_bytes(app_asar.read_bytes())
        print(f"Backed up original app.asar to {backup}.")
    versioned_backup = RUNTIME_DIR / f"app.asar.before-codex-shim-model-picker-patch.{_app_asar_hash(app_asar)[:12]}"
    if not versioned_backup.exists():
        versioned_backup.write_bytes(app_asar.read_bytes())
        print(f"Backed up current app.asar to {versioned_backup}.")

    _quit_codex_app()
    if workdir.exists():
        import shutil
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)

    subprocess.run(["npx", "--yes", "asar", "extract", str(app_asar), str(workdir)], check=True)
    bundle_file = _find_model_queries_bundle(workdir, needle, replacement)
    if bundle_file is None:
        print("Could not find the expected model picker filter in Codex Desktop.", file=sys.stderr)
        return 1
    text = bundle_file.read_text()
    changed = False
    if replacement in text:
        print("Codex Desktop model picker patch is already applied.")
    elif needle in text:
        bundle_file.write_text(text.replace(needle, replacement))
        changed = True
        print("Patched Codex Desktop model picker allowlist filter.")
    else:
        print("Could not find the expected model picker filter in Codex Desktop.", file=sys.stderr)
        return 1
    menu_changed = _patch_codex_shim_menu(workdir)
    bootstrap_changed = _patch_codex_shim_bootstrap_menu(workdir)
    if changed or menu_changed or bootstrap_changed:
        subprocess.run(["npx", "--yes", "asar", "pack", str(workdir), str(app_asar)], check=True)
        _update_asar_integrity(app_asar)
        _resign_codex_app()
    return 0


def restore_codex_app_bundle() -> int:
    app_asar = Path("/Applications/Codex.app/Contents/Resources/app.asar")
    backup = RUNTIME_DIR / "app.asar.before-codex-shim-model-picker-patch"
    if not backup.exists():
        print(f"No app.asar backup found at {backup}.")
        return 0
    _quit_codex_app()
    app_asar.write_bytes(backup.read_bytes())
    _update_asar_integrity(app_asar)
    _resign_codex_app()
    print(f"Restored {app_asar} from {backup}.")
    return 0


def _has_command(command: str) -> bool:
    from shutil import which
    return which(command) is not None


def _app_asar_hash(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _find_model_queries_bundle(workdir: Path, needle: str, replacement: str) -> Path | None:
    assets_dir = workdir / "webview" / "assets"
    if not assets_dir.exists():
        return None
    candidates = sorted(assets_dir.glob("model-queries-*.js"))
    candidates.extend(p for p in sorted(assets_dir.glob("*.js")) if p not in candidates)
    for path in candidates:
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            text = path.read_text(errors="ignore")
        if needle in text or replacement in text:
            return path
    return None


def _patch_codex_shim_menu(workdir: Path) -> bool:
    build_dir = workdir / ".vite" / "build"
    if not build_dir.exists():
        return False
    target = "oe=ue.refreshApplicationMenu;let de=()=>{ue.refreshApplicationMenu()};"
    replacement = f"{_codex_shim_menu_js()};oe=()=>{{ue.refreshApplicationMenu(),__codexShimMenu()}};let de=()=>{{oe()}};"
    startup_target = "ue.refreshApplicationMenu(),w(`application menu refreshed`,A)"
    startup_replacement = "oe(),w(`application menu refreshed`,A)"
    direct_refresh = "=>{ue.refreshApplicationMenu()}"
    wrapped_refresh = "=>{oe()}"
    for path in sorted(build_dir.glob("main-*.js")):
        text = path.read_text()
        if "codex-shim-menu-enable" in text:
            if direct_refresh in text:
                path.write_text(text.replace(direct_refresh, wrapped_refresh))
                print("Patched Codex Desktop VibeProxy menu refresh hooks.")
                return True
            return False
        if "codex-shim-toggle-enable" in text:
            pattern = r"let __codexShimMenu=\(\)=>\{try\{.*?\}\};oe=\(\)=>\{ue\.refreshApplicationMenu\(\),__codexShimMenu\(\)\};"
            text, count = re.subn(pattern, f"{_codex_shim_menu_js()};oe=()=>{{ue.refreshApplicationMenu(),__codexShimMenu()}};", text, count=1)
            if count:
                text = text.replace(direct_refresh, wrapped_refresh)
                path.write_text(text)
                print("Updated Codex Desktop VibeProxy menu placement.")
                return True
            return False
        if target not in text:
            continue
        text = (
            text.replace(target, replacement, 1)
            .replace(startup_target, startup_replacement, 1)
            .replace(direct_refresh, wrapped_refresh)
        )
        path.write_text(text)
        print("Patched Codex Desktop VibeProxy menu.")
        return True
    print("Could not find the expected application menu hook in Codex Desktop.", file=sys.stderr)
    return False


def _patch_codex_shim_bootstrap_menu(workdir: Path) -> bool:
    bootstrap = workdir / ".vite" / "build" / "bootstrap.js"
    if not bootstrap.exists():
        return False
    text = bootstrap.read_text()
    if "codex-shim-bootstrap-menu-enable" in text:
        return False
    target = "let n=require(`electron`),r=require(`node:path`);"
    if target not in text:
        print("Could not find the expected bootstrap menu hook in Codex Desktop.", file=sys.stderr)
        return False
    hook = target + _codex_shim_bootstrap_menu_js()
    bootstrap.write_text(text.replace(target, hook, 1))
    print("Patched Codex Desktop bootstrap VibeProxy menu hook.")
    return True


def _codex_shim_menu_js() -> str:
    return """let __codexShimMenu=()=>{try{let e=n.Menu.getApplicationMenu();if(!e||e.getMenuItemById(`codex-shim-menu-enable`))return;let t=`${process.env.HOME}/.local/bin/codex-shim`,r=(e,r,i=!0)=>{d.execFile(t,[e],(e,t,a)=>{let o=e?`VibeProxy ${r} failed`:`VibeProxy ${r}`,s=(t||a||e?.message||``).trim(),c=i&&!e?[`Restart Codex`,`Later`]:[`OK`];n.dialog.showMessageBox({type:e?`error`:`info`,buttons:c,defaultId:0,cancelId:c.length-1,message:o,detail:`${s}${s?`\\n\\n`:``}Restart Codex Desktop for model picker changes to apply.`}).then(t=>{i&&!e&&t.response===0&&(n.app.relaunch(),n.app.exit(0))})})};let i=n.Menu.buildFromTemplate([{type:`separator`},{id:`codex-shim-menu-enable`,label:`Enable VibeProxy`,click:()=>r(`enable`,`enabled`)},{id:`codex-shim-menu-disable`,label:`Disable VibeProxy`,click:()=>r(`disable`,`disabled`)},{id:`codex-shim-menu-status`,label:`Show VibeProxy Status`,click:()=>r(`status`,`status`,!1)}]),a=e.items[0]?.submenu;if(!a)return;for(let e of i.items)a.append(e);n.Menu.setApplicationMenu(e)}catch(e){}}"""


def _codex_shim_bootstrap_menu_js() -> str:
    return """(()=>{try{let e=n.Menu.setApplicationMenu.bind(n.Menu),t=(e,t,a=!0)=>{i.execFile(`${process.env.HOME}/.local/bin/codex-shim`,[e],(e,i,o)=>{let s=e?`VibeProxy ${t} failed`:`VibeProxy ${t}`,c=(i||o||e?.message||``).trim(),l=a&&!e?[`Restart Codex`,`Later`]:[`OK`];n.dialog.showMessageBox({type:e?`error`:`info`,buttons:l,defaultId:0,cancelId:l.length-1,message:s,detail:`${c}${c?`\\n\\n`:``}Restart Codex Desktop for model picker changes to apply.`}).then(t=>{a&&!e&&t.response===0&&(n.app.relaunch(),n.app.exit(0))})})},r=e=>{try{if(!e||e.getMenuItemById(`codex-shim-bootstrap-menu-enable`))return e;let r=e.items[0]?.submenu;if(!r)return e;let a=n.Menu.buildFromTemplate([{type:`separator`},{id:`codex-shim-bootstrap-menu-enable`,label:`Enable VibeProxy`,click:()=>t(`enable`,`enabled`)},{id:`codex-shim-bootstrap-menu-disable`,label:`Disable VibeProxy`,click:()=>t(`disable`,`disabled`)},{id:`codex-shim-bootstrap-menu-status`,label:`Show VibeProxy Status`,click:()=>t(`status`,`status`,!1)}]);for(let e of a.items)r.append(e)}catch(e){}return e};n.Menu.setApplicationMenu=t=>e(r(t))}catch(e){}})();"""


def _resign_codex_app() -> None:
    subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", "/Applications/Codex.app"],
        check=True,
    )
    print("Re-signed Codex.app after patch.")


def _update_asar_integrity(app_asar: Path) -> None:
    info_plist = Path("/Applications/Codex.app/Contents/Info.plist")
    if not info_plist.exists():
        return
    header_hash = _asar_header_hash(app_asar)
    subprocess.run(
        [
            "/usr/libexec/PlistBuddy",
            "-c",
            f"Set :ElectronAsarIntegrity:Resources/app.asar:hash {header_hash}",
            str(info_plist),
        ],
        check=True,
    )
    print("Updated Electron ASAR integrity hash.")


def _asar_header_hash(path: Path) -> str:
    import hashlib

    with path.open("rb") as f:
        _, _, _, json_size = struct.unpack("<4I", f.read(16))
        header_json = f.read(json_size)
    return hashlib.sha256(header_json).hexdigest()


def _foreground_codex_app() -> None:
    import time
    script = '''
tell application "Codex" to activate
delay 0.5
tell application "System Events"
  if exists process "Codex" then
    tell process "Codex"
      set frontmost to true
      if (count of windows) is 0 then
        keystroke "n" using command down
        delay 0.3
      end if
      if (count of windows) > 0 then
        set position of window 1 to {80, 60}
        set size of window 1 to {1400, 980}
      end if
    end tell
  end if
end tell
'''
    try:
        subprocess.run(["osascript", "-e", script], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def _override_args(vibeproxy_url: str, base_url: str, default_slug: str | None = None) -> list[str]:
    models = VibeProxySettings(vibeproxy_url).load()
    resolved_slug = default_slug or default_model_slug(models)
    pairs = codex_config_overrides(CATALOG_PATH, resolved_slug, base_url, provider_name=resolved_slug)
    args: list[str] = []
    for pair in pairs:
        args.extend(["-c", pair])
    return args


def _resolve_model_slug(models, requested: str | None) -> str:
    if requested is None:
        current = CodexConfig(CODEX_CONFIG_PATH).read_active_model()
        return current or default_model_slug(models)
    by_slug = {model.slug: model.slug for model in models}
    by_model = {}
    for model in models:
        by_model.setdefault(model.model, []).append(model.slug)
    if requested in by_slug:
        return requested
    if requested in by_model and len(by_model[requested]) == 1:
        return by_model[requested][0]
    matches = [model.slug for model in models if requested.lower() in model.display_name.lower()]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise SystemExit(f"Ambiguous model {requested!r}. Matches: {', '.join(matches)}")
    raise SystemExit(f"Unknown shim model {requested!r}. Run: codex-shim model list")


def _effective_base_url(vibeproxy_url: str) -> str:
    base = vibeproxy_url.rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"
    return base


if __name__ == "__main__":
    raise SystemExit(main())
