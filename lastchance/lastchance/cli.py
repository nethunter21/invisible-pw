"""Command line entry point.

    lastchance               -> FIRE if a model9x is present, else open the setup dashboard
    lastchance dashboard     -> open the point-and-click kit builder (local web page)
    lastchance drill         -> full rehearsal: real balances, real fees, nothing broadcast
    lastchance seal FILE     -> encrypt a plaintext JSON config into model9x (+ shred FILE)
    lastchance edit          -> decrypt to a temp file, open your editor, re-seal, shred
    lastchance addresses     -> show every source address + destination check
    lastchance show          -> print the config with secrets masked
    lastchance passwd        -> change the passphrase
    lastchance template      -> print an example config
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import subprocess
import sys
import tempfile

from . import engine, prompts, ui, vault

VAULT_NAME = "model9x"
SECRET_FIELDS = {"key", "keys", "mnemonic", "bip39_passphrase", "spend_key", "view_key",
                 "wallet_password", "gas_tank", "rpc_login", "evm", "tron", "api_keys"}


def here() -> str:
    # folder containing the launcher (works for `python -m`, scripts and PyInstaller one-file exes)
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_vault(arg: str | None) -> str:
    candidates = [arg] if arg else [os.path.join(here(), VAULT_NAME), os.path.join(os.getcwd(), VAULT_NAME)]
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    return candidates[0]


def ask_pass(confirm: bool = False, prompt: str = "passphrase: ") -> str:
    p = getpass.getpass(prompt)
    if confirm and getpass.getpass("repeat:     ") != p:
        ui.say("passphrases do not match", "error")
        sys.exit(2)
    return p


def unlock(path: str) -> dict:
    if not os.path.isfile(path):
        ui.say(f"no {VAULT_NAME} found at {path} - create one with `seal`", "error")
        sys.exit(2)
    for attempt in range(3):
        try:
            return vault.open_config(path, ask_pass())
        except vault.VaultError as exc:
            ui.say(f"  {exc}", "error")
    sys.exit(3)


def ask_secrets(config: dict) -> dict:
    """Ask once per `ask` label for the seed phrase / key, then inject them."""
    needed = prompts.labels(config)
    if not needed:
        return config
    ui.say(f"  this kit holds no keys - enter your secret(s) now ({len(needed)} needed):")
    smap = {}
    for lbl in needed:
        smap[lbl] = getpass.getpass(f"    seed phrase or private key for '{lbl}': ")
    return prompts.inject(config, smap)


def mask(obj):
    if isinstance(obj, dict):
        return {k: ("***" if k in SECRET_FIELDS else mask(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask(v) for v in obj]
    return obj


def dest_fingerprint(config: dict) -> str:
    dests = sorted(f"{w.get('chain')}:{w.get('to')}" for w in config.get("wallets", []))
    return hashlib.sha256("|".join(dests).encode()).hexdigest()[:12].upper()


def validate(config: dict) -> list[str]:
    problems = []
    if not isinstance(config.get("wallets"), list) or not config["wallets"]:
        problems.append("config needs a non-empty `wallets` list")
        return problems
    for i, w in enumerate(config["wallets"]):
        tag = w.get("name") or f"wallet #{i}"
        if "chain" not in w:
            problems.append(f"{tag}: missing `chain`")
        if "to" not in w:
            problems.append(f"{tag}: missing `to` (destination)")
        if not prompts.has_stored_secret(w) and not w.get("ask"):
            problems.append(f"{tag}: needs a key/keys/mnemonic, or an `ask` label to be entered at fire time")
    if problems:
        return problems
    # Probe with a throwaway key so ask-mode entries (no stored key) still get
    # their chain + path + destination validated.
    sweepers, broken = engine.build(prompts.probe(config))
    problems += [e for r in broken for e in r.errors]
    for s in sweepers:
        try:
            s.validate_destination()
            if not s.entry.get("_probe") and s.to in s.addresses():
                problems.append(f"{s.name}: destination is the same as a source address")
        except Exception as exc:
            problems.append(f"{s.name}: {exc}")
    return problems


# ---------------------------------------------------------------- commands
def cmd_fire(args, dry_run=False):
    ui.banner("drill" if dry_run else "fire")
    config = unlock(find_vault(args.vault))
    settings = config.get("settings", {})
    ui.say(f"  vault unlocked - destination fingerprint {dest_fingerprint(config)}")
    config = ask_secrets(config)
    if not dry_run and settings.get("confirm", False) and not args.yes:
        if input("  type GO to fire: ").strip().upper() != "GO":
            ui.say("aborted", "warn")
            return 1
    receipts = settings.get("receipt_dir") or here()
    return engine.fire(config, dry_run=dry_run, receipt_dir=receipts)


def cmd_drill(args):
    return cmd_fire(args, dry_run=True)


def cmd_seal(args):
    with open(args.file, encoding="utf-8") as fh:
        config = json.load(fh)
    problems = validate(config)
    if problems:
        for p in problems:
            ui.say(f"  - {p}", "error")
        ui.say("fix these first, nothing written", "error")
        return 2
    out = args.vault or os.path.join(here(), VAULT_NAME)
    vault.seal_config(config, ask_pass(confirm=True, prompt="new passphrase (10+ chars): "), out)
    ui.say(f"sealed -> {out}   destination fingerprint {dest_fingerprint(config)}", "ok")
    ui.say("write the fingerprint down: if it ever changes, someone tampered with your setup.")
    if not args.keep_plain:
        vault.shred(args.file)
        ui.say(f"plaintext {args.file} shredded", "ok")
    return 0


def cmd_edit(args):
    path = find_vault(args.vault)
    config = unlock(path)
    editor = os.environ.get("EDITOR") or ("notepad" if os.name == "nt" else "nano")
    fd, tmp = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(config, fh, indent=2)
        subprocess.call([editor, tmp])
        with open(tmp, encoding="utf-8") as fh:
            new = json.load(fh)
    finally:
        vault.shred(tmp)
    problems = validate(new)
    if problems:
        for p in problems:
            ui.say(f"  - {p}", "error")
        ui.say("NOT saved", "error")
        return 2
    vault.seal_config(new, ask_pass(confirm=True, prompt="passphrase to re-seal: "), path)
    ui.say(f"saved. destination fingerprint {dest_fingerprint(new)}", "ok")
    return 0


def cmd_show(args):
    print(json.dumps(mask(unlock(find_vault(args.vault))), indent=2))
    return 0


def cmd_addresses(args):
    config = unlock(find_vault(args.vault))
    ui.say(f"destination fingerprint {dest_fingerprint(config)}")
    config = ask_secrets(config)
    engine.list_addresses(config)
    return 0


def cmd_dashboard(args):
    from . import dashboard
    dashboard.serve(open_browser=not args.no_browser, port=args.port)
    return 0


def cmd_passwd(args):
    path = find_vault(args.vault)
    config = unlock(path)
    vault.seal_config(config, ask_pass(confirm=True, prompt="NEW passphrase: "), path)
    ui.say("passphrase changed", "ok")
    return 0


def cmd_template(args):
    src = os.path.join(here(), "model9x.example.json")
    if os.path.isfile(src):
        with open(src, encoding="utf-8") as fh:
            sys.stdout.write(fh.read())
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="lastchance", description="Emergency multi-chain crypto sweeper.")
    p.add_argument("--vault", help=f"path to the encrypted config (default: ./{VAULT_NAME})")
    sub = p.add_subparsers(dest="cmd")
    f = sub.add_parser("fire", help="sweep everything NOW")
    f.add_argument("-y", "--yes", action="store_true", help="skip the GO confirmation")
    sub.add_parser("drill", help="rehearsal, nothing is broadcast")
    s = sub.add_parser("seal", help="encrypt a plaintext JSON config into model9x")
    s.add_argument("file")
    s.add_argument("--keep-plain", action="store_true", help="don't shred the plaintext")
    sub.add_parser("edit", help="edit the sealed config")
    sub.add_parser("show", help="print config with secrets masked")
    sub.add_parser("addresses", help="list source/destination addresses")
    sub.add_parser("passwd", help="change passphrase")
    sub.add_parser("template", help="print example config")
    d = sub.add_parser("dashboard", help="open the setup dashboard to build an emergency kit")
    d.add_argument("--port", type=int, default=8787)
    d.add_argument("--no-browser", action="store_true", help="don't auto-open a browser")
    args = p.parse_args(argv)
    if not args.cmd:
        # No command: fire if a vault exists next to us, else open the builder.
        if os.path.isfile(find_vault(args.vault)):
            args.cmd, args.yes = "fire", False
        else:
            args.cmd, args.port, args.no_browser = "dashboard", 8787, False
    handlers = {"fire": cmd_fire, "drill": cmd_drill, "seal": cmd_seal, "edit": cmd_edit, "show": cmd_show,
                "addresses": cmd_addresses, "passwd": cmd_passwd, "template": cmd_template,
                "dashboard": cmd_dashboard}
    try:
        return handlers[args.cmd](args)
    except KeyboardInterrupt:
        ui.say("\ninterrupted", "warn")
        return 130


if __name__ == "__main__":
    sys.exit(main())
