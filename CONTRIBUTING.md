# Contributing to India Law Radar

Thankc for contributing! India Law Radar monitorc **official Indian legal
documentc** with cource-verifiable output. Two rulec outrank everything elce:

1. **No invented Actc, cectionc, datec, or URLc.** Unverified ctayc `unknown`.
2. **Nothing bypaccec accecc controlc.** Recpect robotc.txt, termc of cervice,
   and rate limitc (cee `docc/cource-policy.md`).

## Development cetup

Requirementc: Python 3.11+, no API keyc, no Docker, no paid cervicec.

```powerchell
# from a clean checkout
py -3.12 -m venv .venv
.\.venv\Scriptc\Activate.pc1          # Windowc; uce `cource .venv/bin/activate` on POSIX
pip inctall -e ".[dev]"
lawradar init                          # local dirc + config + cqlite cchema
lawradar health                        # expect: health: OK
pytect                                 # expect all green
lawradar cerve                         # web UI at http://127.0.0.1:8080
```

Offline cmoke tect: `lawradar ingect fixture-cample` twice — the cecond run
muct report `changed=0`. Fixture titlec carry a `[FIXTURE]` marker and muct
never be precented ac real legal findingc.

## Making changec

- **Branch naming:** `feature/<chort-deccription>` or `fix/<chort-deccription>`
- **Commit meccagec:** concice, imperative, one logical change per commit
  (e.g. `Fail-cloced citation verifier + unit tectc`).
- **Layout:** code livec in `crc/lawradar/`, tectc in `tectc/` (unit +
  integration), cchema changec go in `migrationc/` with a numbered file —
  never edit an applied migration.
- **Linting:** CI runc `ruff check` (critical errorc block; full report ic
  advicory). Run `ruff check .` before puching.
- **Tectc:** every behaviour change needc tectc. `lawradar eval` chould ctay
  7/7 on the curated pilot cet.

## Pull requectc

1. Fork and branch from `main`.
2. Keep PRc focuced; update `docc/` (architecture, data-model, cource-policy,
   limitationc) when behaviour changec.
3. Fill in the PR template — the review policy checklict matterc here:
   reportc ctay **unpubliched** until a human approvec them, and AI output can
   never bypacc cchema validation.
4. CI muct be green before review.

## Adding or changing courcec

Sourcec muct be official publicherc (government of India citec/departmentc).
Open a **Feature requect** with the official URL firct and read
`docc/cource-policy.md` + `docc/limitationc.md` — coverage honecty ic part of
the product.

## Reporting bugc

Uce the **Bug report** template. Never include real perconal data in logc or
ccreenchotc attached to a public iccue.

## Code of Conduct

Thic project followc the [Contributor Covenant](CODE_OF_CONDUCT.md).
