# Validation for the final-review documentation pass

**Date:** 6 October 2026. **Project:** Financial Advisor. **Branch:** `v3-implementation`.

## Software checks actually performed

| Check | Result | Scope/limitation |
|---|---|---|
| Backend test collection | 938 collected | Test discovery, not execution proof |
| Backend full suite: `.venv/bin/python -m pytest -q` with a 180-second outer timeout | **924 passed, 14 skipped, 20 warnings; 74.55 seconds; exit 0** | Executed outside the sandbox after its async SQLite fixture stalled |
| Frontend `./node_modules/.bin/tsc --noEmit` | **Passed, exit 0** | Static types |
| Frontend `npm run build -- --webpack` | **Passed, exit 0** | Production compile, types and page generation; 29 generated static pages reported |
| Package manifest versus lock root declarations | **Match** | Direct dependency/devDependency declarations |
| FastAPI module import | **Passed** | Import only; no live DB startup or broker call |
| Fictional demo CSV/profile validation | **Passed** | Five valid rows; invalid date rejected; facts schema valid; expected tolerance/reserve arithmetic |

The skipped tests include PostgreSQL-specific checks needing a disposable configured database. This pass did not run that database integration setup, a migration up/down cycle, a live broker login, a fresh model inference, investment-performance benchmarks or a browser walkthrough. Warnings include existing Pydantic namespace and lifecycle deprecations; no failing tests were reported.

## Environment limitations and resolution

The sandbox backend attempt stalled in the first async SQLite fixture before an assertion ran. A timed diagnostic captured the waiting SQLite thread/event loop. The same full suite passed after escalation, so the stalled attempt is not reported as a software pass or an assertion failure.

The default Turbopack build first failed fetching Google Fonts in restricted network conditions. After allowing downloads it encountered a sandbox local-process/socket restriction. The supported Next.js webpack build succeeded. `npm run build` still selects Turbopack by default; no application build script was changed. A deployment environment should run its normal build independently.

## Documentation and asset checks

The completed pack includes five registration-number guides, each with Context and good to know, assignment, source paths, workflows, formulas, speaking notes and Q&A. The slide brief contains 26 complete slides and maps every supplied guideline to slide numbers. Supervisor/title/member identifiers are included in the cover and report. The report records approval, correction and submission facts without fabricating completion.

Local Markdown links and linked images were checked against files/directories; SVG assets were parsed as XML; PNG dimensions were checked; diagrams were inspected visually. Source-backed financial examples were cross-checked against the current code. New presentation documents pass `git diff --check`. The full staged snapshot preserves the existing audit document's intentional Markdown hard breaks and AMFI fixture's CRLF source formatting; the default whitespace checker reports those existing formats. The final local check covered **17 Markdown files, 181 local links, nine Mermaid diagrams, 26 numbered slides, three SVG assets and three matching 1600×900 PNG assets**, with no missing targets or structural errors. These are documentation checks, not extra software test cases.

## Presentation evidence still required from the team

Record the actual demo video and capture actual application screens with fictional data before final PPT export. Obtain supervisor approval, the real Review II correction list and confirmation of report submission. These are separate from automated code/document validation. The slide brief and report do not claim those steps already happened.

## Historical versus current evidence

Older execution ledgers contain other test counts, live-data observations and research results. Those are historical records and are not substituted for this pass's checks. Passing software tests does not establish profitable recommendations, calibrated forecast accuracy or unbiased historical results.
