# Install, upgrade, and uninstall plan

The transaction client never installs the plugin. Installation is a separate,
explicitly authorized operation.

## Build and inspect

```bash
python scripts/build_xpi.py /absolute/zotero-declarative-bridge.xpi
sha256sum /absolute/zotero-declarative-bridge.xpi
unzip -l /absolute/zotero-declarative-bridge.xpi
```

The XPI must contain only `manifest.json`, `bridge_core.js`, and `bootstrap.js`
at its root. Inspect them before installation. The manifest is compatible only
with Zotero `9.0.*`; a newer minor/major requires review and retest.

## Install through Zotero Desktop (preferred)

1. In Zotero Desktop, open **Tools -> Add-ons**.
2. Choose **Install Add-on From File** and select the inspected XPI.
3. Confirm the add-on ID is `zotero-declarative-bridge@deep-research.local`.
4. Find `zotero-declarative-bridge-capability.json` in the active Zotero
   profile. Verify its containing directory is user-only and the file mode is
   `0600` before passing its absolute path to the client.
5. Run authenticated `probe`, then a no-write `preview`. Do not start with
   `apply`.

This is Zotero's documented packed-XPI route:
<https://www.zotero.org/support/plugins>.

## Packed-XPI profile fallback

Use this only when the UI route is inaccessible and the user explicitly
authorizes profile installation. Close Zotero first, preserve any same-ID
state, and run:

```bash
python scripts/install_packed_xpi.py /absolute/reviewed.xpi \
  --profile /absolute/active/profile \
  --receipt /absolute/private-install-receipt.json \
  --backup-dir /absolute/private-backup
```

The helper accepts only the fixed three-file XPI and Zotero `9.0.*`, verifies
the unique default profile, refuses a listening Zotero process, and atomically
writes `extensions/zotero-declarative-bridge@deep-research.local.xpi`. It does
not edit `extensions.json`, preferences, or SQLite.

Never place an unpacked directory at the bare plugin-ID path. Zotero's source
development route uses a **text proxy file** named by the plugin ID whose
contents are the source directory path; it is not a same-named directory. That
route also requires loader-cache preference handling and belongs in an isolated
development profile, not this production workflow. See
<https://www.zotero.org/support/dev/client_coding/plugin_development>.

After restart require all three gates before any transaction preview:

1. The extension registry or Plugins window shows the exact ID/version as
   active and compatible.
2. The private capability file exists as a regular `0600` file in the active
   profile.
3. Authenticated `probe` returns the same plugin and Zotero versions.

An XPI merely present on disk is not an installed or active plugin. If the
loader rejects, disables, or removes it, preserve the loader log and stop.

## Upgrade

Build the new XPI, record its SHA-256, inspect the diff, install it through the
Plugins manager or the explicitly authorized packed-XPI fallback, and rerun all
three activation gates. Startup rotates the capability token, so an old
capability descriptor or preview receipt cannot authorize the new process.

## Uninstall

1. Do not begin a new preview or apply.
2. Remove/disable the add-on in **Tools -> Add-ons**.
3. Confirm authenticated `probe` no longer succeeds and the endpoint returns
   `404` (or Zotero is not listening).
4. Confirm the capability file was removed. If Zotero crashed, delete only the
   stale regular file at the documented profile path after Zotero is closed;
   never follow a symlink.

For a packed-profile rollback, close Zotero and move only the exact same-ID XPI
to the private evidence/backup location. Restart and confirm registry removal,
endpoint absence, and capability removal. Never repair uninstallation by
editing `extensions.json` or SQLite.

Shutdown unregisters only the exact endpoint constructor installed by this
plugin and removes only the capability file whose key ID matches the current
process.
