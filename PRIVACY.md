# Privacy policy

*Applies to Retina, published at <https://github.com/jromang/retina>. Last updated
2026-07-31.*

> This program will not transfer any information to other networked systems unless
> specifically requested by the user or the person installing or operating it.

## The short version

**Retina collects nothing.** No telemetry, no analytics, no usage statistics, no crash
reporting, no update check, no unique identifier, no account. It does not contact its author,
and there is no server operated by this project that your copy talks to.

Your images, projects, scripts and settings stay on the machine that opens them. They are
written only where you ask, plus a configuration and cache directory belonging to your user
account.

Nothing below changes with a setting you have to find and switch off, because there is nothing
running in the background to switch off. Every network request Retina makes is one you asked
for, by invoking a feature that says what it does.

## What is stored on your machine

| Location (Windows) | Contents |
|---|---|
| `%APPDATA%\retina` | preferences, recently opened files, the session to reopen, the token for the local interface |
| `%LOCALAPPDATA%\Retina` | caches: WebView2 profile, downloaded models, astrometry indexes, sample datasets |

On Linux and macOS the equivalents follow the platform conventions (`~/.config/retina`,
`~/.cache/retina`). Deleting either directory is safe; Retina recreates what it needs.

The application's own interface — including its Python console and its API — is served on
`127.0.0.1` and is reachable only from the machine it runs on, behind a token regenerated for
each session. It is not exposed to your network unless you deliberately run it with
`--no-shell` and forward the port yourself.

## When Retina reaches the network, and what it sends

Four features contact a remote service. Each is invoked explicitly — by running a process, or
by clicking a download — and none runs on startup or in the background.

### 1. Plate solving (`PlateSolve`)

Determines where an image points. By default on Windows this runs **entirely offline**, using
a bundled copy of ASTAP and a local star database; nothing leaves your machine.

If you explicitly select the `astrometry_net` backend, the detected star positions of that
image are sent to <https://nova.astrometry.net> together with the API key you supply.
The image itself is not uploaded. Their privacy policy applies:
<https://nova.astrometry.net/legal>.

### 2. Star catalogs (`GaiaCatalog`, `APASSCatalog`, `CatalogAnnotation`, `ConeSearch`, colour calibration)

Queries a catalog for the stars in a region of sky. Retina sends the coordinates and radius of
the region, never your image. Depending on the process, the service is one of:

- **Gaia** (ESA), via `astroquery` — <https://www.cosmos.esa.int/web/gaia-users/archive>
- **VizieR / SIMBAD** (CDS, Strasbourg) — <https://cds.unistra.fr/vizier-org/licences_vizier.html>
- **MAST** (STScI) — <https://outerspace.stsci.edu/display/MASTDOCS>

### 3. Survey references (`SurveyReference`, `MultiscaleGradientCorrection`)

Requests a FITS cutout of a sky region, used as a gradient-free reference. Retina sends the
WCS of the region — coordinates, size, projection — to the CDS `hips2fits` service at
<https://alasky.cds.unistra.fr>. Your image is not sent. CDS privacy notice:
<https://cds.unistra.fr/legal-notice.html>.

### 4. Downloads on demand

Fetches a file you asked for, verifying its SHA-256 against a manifest shipped in the
application. Nothing is sent beyond the HTTP request itself.

- **AI models** — <https://huggingface.co/jromanghf/graxpert-models>
  (<https://huggingface.co/privacy>), or a local GraXpert installation if you have one, in
  which case nothing is downloaded.
- **Astrometry index files** — <https://astrometry.net>, or
  <https://data.starnet.astro> for StarNet.
- **Sample datasets** — Zenodo (<https://about.zenodo.org/privacy-policy/>).
- **ASTAP and its star database** — SourceForge, for developers running
  `scripts/fetch_astap.py`. End users receive ASTAP inside the installer and download nothing.

As with any HTTP request, the operator of these services can see your IP address and the time
of the request. Retina adds no identifier of its own to them.

## The built-in assistant

The optional **Assistant** panel runs the `claude` command-line tool **that you installed and
signed in yourself**, on your own subscription. Retina does not have, ask for, or transmit any
credential for it, and injects no API key. What you type in that panel goes to Anthropic under
your own agreement with them, subject to their privacy policy
(<https://www.anthropic.com/legal/privacy>). If the tool is not installed, the panel explains
how to install it and does nothing else.

The assistant's access is bounded in the command line Retina builds: it is given only Retina's
own tools, and explicitly not your shell, your other MCP servers, or your `CLAUDE.md` files.

## Children

Retina is a tool for processing astronomical images. It is not directed at children and
collects no data from anyone.

## Changes

This policy is versioned with the source. Its history is at
<https://github.com/jromang/retina/commits/master/PRIVACY.md>, so any change to it is public
and dated.

## Contact

<https://github.com/jromang/retina/issues>, or <jromang@protonmail.com>.
