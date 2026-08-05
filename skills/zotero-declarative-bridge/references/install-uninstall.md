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

`applications.zotero.update_url` is a Zotero runtime loader gate even when a
generic WebExtension schema treats it as optional. It must point to the public
external `updates.json`, whose current entry binds the versioned GitHub Release
XPI with `update_hash`. `updates.json` is not packaged inside the XPI. Before a
release or installation, verify the public URL returns that JSON, its asset URL
returns the exact XPI, and Zotero's own `loadManifestFromFile` reports the
expected ID/version with no `additionalErrors`. A successful loader preflight
does not prove bootstrap activation, capability creation, or mutation behavior.
For repository release `v0.6.1`, the exact plugin asset contract is
`zotero-declarative-bridge-0.1.5.xpi` with SHA-256 `10c0e06c7a7fa85afe73b3a9c49d518d7777513a1d55cb01eb8ed8182d1db76b`.

## Install through Zotero Desktop (preferred)

1. In Zotero Desktop, open **Tools -> Plugins**.
2. Drag the inspected XPI into the Plugins window and confirm installation.
3. Confirm the add-on ID is `zotero-declarative-bridge@deep-research.local`.
4. Find `zotero-declarative-bridge-capability.json` in the active Zotero
   profile. Verify its containing directory is user-only and the file mode is
   `0600` before passing its absolute path to the client.
5. Run authenticated `probe`, then a no-write `preview`. Do not start with
   `apply`.

This is Zotero's documented packed-XPI route:
<https://www.zotero.org/support/plugins>.

## No profile-copy or source-proxy fallback

The packed XPI has no supported profile-copy fallback. A filesystem copy is not
evidence that Zotero registered or activated it. `install_packed_xpi.py` now
fails closed and directs the operator to the visible Plugins UI.

The stable skill does not ship a source-proxy installer and does not change
profile discovery, automatic-disablement, registry, or cache preferences.
Those changes have security and recovery implications and belong in separately
reviewed developer tooling, not the transaction executor installed for normal
use.

After visible installation require all three gates before any transaction
preview:

1. The extension registry or Plugins window shows the exact ID/version as
   active and compatible.
2. The private capability file exists as a regular `0600` file in the active
   profile.
3. Authenticated `probe` returns the same plugin and Zotero versions.

An XPI merely present on disk is not an installed or active plugin. If the
loader rejects, disables, or removes it, preserve the loader log and stop.

## Upgrade

Build the new XPI, record its SHA-256, inspect the diff, install it through the
Plugins manager, and rerun all three activation gates. Startup rotates the
capability token, so an old capability descriptor or preview receipt cannot
authorize the new process.

## Uninstall

1. Do not begin a new preview or apply.
2. Remove/disable the add-on in **Tools -> Plugins**.
3. Confirm authenticated `probe` no longer succeeds and the endpoint returns
   `404` (or Zotero is not listening).
4. Confirm the capability file was removed. If Zotero crashed, delete only the
   stale regular file at the documented profile path after Zotero is closed;
   never follow a symlink.

Shutdown unregisters only the exact endpoint constructor installed by this
plugin and removes only the capability file whose key ID matches the current
process.
