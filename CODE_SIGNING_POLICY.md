# Code signing policy

This document describes how Retina's Windows binaries are produced and signed, who can
authorize a signature, and what the signed software does with your data. It exists because
code signing is a claim about provenance, and a claim of that kind should be checkable.

## What is signed

The Windows installer, `Retina-<version>.msi`, published on the
[releases page](https://github.com/jromang/retina/releases). Nothing else is signed, and no
signed binary is distributed through any other channel.

## How the binaries are built

Every released artifact is produced by a public, automated build from the public source of
this repository. Nothing is built on a developer machine and uploaded by hand.

- The build is [`.github/workflows/release-windows.yml`](.github/workflows/release-windows.yml),
  running on a GitHub-hosted Windows runner.
- It is triggered by pushing a `v*` tag, and the workflow refuses to proceed if the tag
  disagrees with the version declared in `pyproject.toml`.
- The complete build log of every release is public and retained by GitHub Actions.
- Third-party components enter the bundle only through the dependency lists in
  `pyproject.toml`; a test (`tests/test_packaging_manifest.py`) and a bundle smoke test
  (`scripts/smoke_bundle.py`) check that what ships matches what is declared.

A reader who wants to verify a release can compare the published `SHA256SUMS.txt` against the
artifact of the corresponding workflow run. Note that MSI packaging is not bit-for-bit
reproducible — WiX embeds timestamps and generated GUIDs — so two builds of the same commit
produce different checksums. The checksum identifies an artifact, not a version.

## Roles

Retina is currently maintained by one person. The roles below are distinct responsibilities
rather than distinct people, and this section will be updated if that changes.

| Role | Held by | Responsibility |
|---|---|---|
| Author | Jean-Francois Romang ([@jromang](https://github.com/jromang)) | Writes and reviews the source; merges changes. |
| Reviewer | Jean-Francois Romang | Confirms that the tagged commit is the intended release. |
| Approver | Jean-Francois Romang | Authorizes each signing request. |

Signing requests are submitted only by the release workflow, from a tag on the `master` branch
of this repository, and are approved individually. A signing request that does not correspond
to a tag pushed by a maintainer is not approved.

## Account security

All accounts able to influence a release — the GitHub account with write access to this
repository, and the code signing account — have multi-factor authentication enabled. API
tokens used by the build are stored as GitHub Actions secrets, are not printed by any workflow
step, and are scoped to a dedicated CI identity that cannot sign interactively.

## Privacy

**Retina collects no data.** It does not phone home, does not report telemetry, does not
transmit usage statistics, and has no analytics of any kind. Images and projects stay on the
machine that opens them.

Three features reach the network, all of them only when the user explicitly invokes them, and
each is documented where it is offered:

- **Plate solving and catalog queries** send the coordinates or the star positions of the image
  being solved to the selected service (a local ASTAP install by default on Windows; optionally
  Astrometry.net, Gaia, APASS, SIMBAD).
- **Survey references** request a FITS cutout of a sky region from the CDS `hips2fits` service.
- **Downloads on demand** — AI models, astrometry index files and sample datasets — fetch files
  from the URLs listed in `python/retina/resources/credits.json`, with their SHA-256 verified.

The application's own interface, including its Python console, runs on `127.0.0.1` and is
reachable only from the machine it runs on, behind a token generated per session.

## Uninstallation

The MSI installs per user and registers with Windows: *Settings → Apps → Installed apps →
Retina → Uninstall* removes it. Configuration and cache directories, which the installer does
not create, are `%APPDATA%\retina` and `%LOCALAPPDATA%\Retina`; they can be deleted safely.

## System changes

The installer writes only to its own installation directory and its Add/Remove Programs entry.
It does not install drivers or services, does not modify system-wide settings, does not add
anything to `PATH`, and does not configure itself to start with Windows.

## Licence and third-party components

Retina is [GPL-3.0-or-later](LICENSE) and contains no proprietary component. Every bundled
third-party component is listed with its licence in `python/retina/resources/credits.json`,
visible in the application under **Help → Licences** and from the console via `app.credits()`.

## Reporting a problem

Security or provenance concerns: open an issue at
<https://github.com/jromang/retina/issues>, or contact the maintainer at
<jromang@protonmail.com>.
