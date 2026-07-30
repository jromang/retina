# ASTAP bundle (offline plate solving, Windows)

This directory holds the **ASTAP** executable and its **star database**, used by the `astap`
backend of `retina.processes.astrometry.PlateSolve` for **offline** astrometric solving **on
Windows**. On Linux/macOS, retina uses the `astrometry` Python package (backend `astrometry`).

The binaries (~105 MB with the D05 database) are **not versioned** (see `.gitignore`). Fetch them
with:

```bash
python scripts/fetch_astap.py                 # win64 + D05 database (FOV > 0.6°)
python scripts/fetch_astap.py --database d20  # narrower fields (FOV > 0.3°)
```

Expected tree after the fetch:

```
vendor/astap/win64/
├── astap_cli.exe          # CLI solver (stripped), ~0.8 MB
└── d05_*.1476             # D05 star database (1476 files, ~104 MB)
```

The backend locates the executable in this order: the `astap_exe` parameter → the `RETINA_ASTAP`
environment variable → this `vendor/astap/<platform>/` directory → `PATH`. The star database must
be extracted **next to the executable** (ASTAP detects it automatically).

## Licences

- **ASTAP** — © Han Kleijn, **MPL 2.0** ([www.hnsky.org](https://www.hnsky.org/astap.htm)).
- **Star databases** — freely redistributable.

Compatible with retina's GPL-3.0 licence (distributed alongside, without closed static linking).
