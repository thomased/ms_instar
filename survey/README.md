# INSTAR baseline literature survey

Small pipeline to generate the "current state of reporting" baseline
(§3 of the manuscript) — Figure 2 and the `[N]`/`[X]%` placeholders.

## What is in this directory

`results/` holds everything the manuscript's section 3 depends on: the bibliographic
records for all 150 surveyed papers, the per-item scores, the per-cell
scoring justifications, and the aggregate summaries. That is the data
behind section 3 and Figure 2, and it is the part worth citing.

Two directories used by the pipeline are deliberately **not** here:

- `pdfs/` — the full-text PDFs of the 150 surveyed papers
- `texts/` — the methods sections extracted from those PDFs

Those are the publishers' copyright rather than ours, so they cannot be
redistributed. They are listed in `.gitignore`. Everything in `results/`
was generated from them and stands on its own, so the analysis is fully
reproducible without them. Re-running the pipeline
end to end from scratch is not, since steps 1 and 2 would have to
re-download the papers.

Note also that for a minority of papers, metadata extraction fell back to
scraping the PDF front matter, which on two-column layouts interleaves
the title with affiliations, funding statements, and in some cases the
corresponding author's email. Those email addresses have been removed
(see `code/redact_pii.py`); they were never read by the scoring step,
which works from `texts/`. The surrounding text in the affected `title`
and `abstract` fields is still garbled. Those two columns are metadata
only and no reported result depends on them.

## Install

```
pip install requests pdfplumber anthropic
```

For the R figure step:

```
install.packages(c("readr", "dplyr", "ggplot2", "forcats"))
```

Optional: set a contact address. OpenAlex and Crossref give faster,
more reliable service to requests that identify one, and Unpaywall
requires one for lookups on non-OA papers.

```
export SURVEY_CONTACT_EMAIL=you@example.com
export UNPAYWALL_EMAIL=you@example.com
```

Neither is required. Without them the requests still work, anonymously.

For the scoring step:

```
export ANTHROPIC_API_KEY=sk-ant-...
```

## Workflow

Everything runs from this directory. Each step is idempotent — safe to
re-run; already-processed items are skipped unless you pass `--force`.

**Cost:** only step 3 (`score`) makes paid API calls. Steps 1
(`fetch`), 2 (`texts`), and 4 (`summarise`) hit only free endpoints
(OpenAlex, Unpaywall) or run locally. Always run `python3 code/survey.py
score --dry-run` before the real thing to see the token estimate.

### 1. Fetch candidate papers &nbsp;·&nbsp; *free*

```
python code/survey.py fetch --per-journal 10 --dry-run  # sanity-check the list
python code/survey.py fetch --per-journal 10            # write papers.csv
```

Pulls recent 2025 papers from each of the fifteen target journals via
OpenAlex (cursor-paginated), keyword-filters to invertebrate work on
title/abstract, and caps at `--per-journal` matches per venue. The
journal list spans ecology and evolution, behaviour, physiology and
neurobiology, invertebrate pathology, mass rearing for food and feed,
and general biology (PLOS ONE, PeerJ, RSOS) — matching the scope
described in §3 of the manuscript.

**Open-access-only by default.** The query includes
`open_access.is_oa:true`, so `papers.csv` only contains papers whose
full text is legitimately downloadable. Pass `--include-paywalled` to
turn this off; the trade-off is you'll need to drop paywalled PDFs
into `pdfs/<slug>.pdf` yourself before running `texts`.

The default of 10 is a ceiling, not a quota, since not every journal
yields ten eligible OA papers in a single year. The survey reported in
the manuscript is 150 papers across 15 journals. Keyword false positives
are caught downstream by the eligibility check in the scoring step, so
it's fine to lean broad here. Tweak `--year` if you want a different
vintage.

### 2. Grab methods sections &nbsp;·&nbsp; *free*

```
python code/survey.py texts --unpaywall-email "$UNPAYWALL_EMAIL"
```

Downloads each paper's OA PDF (from OpenAlex's OA URL or Unpaywall),
extracts the full text with pdfplumber, and slices the methods section
by regex on section heads. Writes to `texts/<slug>.txt`.

For papers behind a paywall the script will tell you it couldn't fetch
and print the expected filename. Drop the PDF into `pdfs/<slug>.pdf`
manually and re-run — it'll pick it up.

If the methods extractor misses a section (some journals use unusual
heads), you can hand-edit the `.txt` file to just the methods and the
scorer will use whatever's there.

### 3. Score with Claude &nbsp;·&nbsp; *paid — Anthropic API*

```
python code/survey.py score --dry-run   # cost preview (tokens, no calls)
python code/survey.py score             # actually score
```

One Claude Haiku call per paper. The rubric (see `rubric.md`) is
compact; expected cost is around US$1–2 for a full run.

Each call first decides eligibility ("is this an empirical study of
live invertebrates?") — reviews, purely genomic/computational studies,
and papers whose focal organism is a vertebrate come back with
`eligible=N` and are excluded from `summarise` totals. This lets the
`fetch` keyword net stay generous without polluting the baseline.

Outputs:

- `scores.csv` — one row per paper, `eligible` column plus one column
  per INSTAR item in {Y, N, NA} (yes / no / not-applicable). Item
  columns are blank for ineligible papers. The LLM is instructed to
  commit — no "uncertain" code.
- `scores_notes.csv` — brief per-item justification for each score
  (short quote or one-line reason), plus an `_eligibility` note for
  each paper. Handy for spot-checking.

Re-runs are incremental: papers already scored are skipped unless you
pass `--force`. The API call retries with backoff on rate limits, and
paces at ~5 requests/sec.

### 4. Aggregate + plot Figure 2 &nbsp;·&nbsp; *free*

**Canonical route — one command:**

```
Rscript R/01_analysis.R
```

`R/01_analysis.R` ships with the manuscript materials rather than with
this pipeline, and is run from the manuscript project root (the directory
containing `survey/`). It requires the `instarreport` package, available
at <https://github.com/thomased/instarreport>.

Runs the whole aggregation through the `instarreport` package
(`audit_from_matrix()`), writes all three summary CSVs, renders Figure
2, and checks the headline numbers against what the manuscript
currently says — warning loudly if any have moved. The framework
definition, item labels, domain grouping and coverage arithmetic all
come from the package, so nothing here can drift from Table 1.

The Python route below does the same aggregation and is kept for
running the pipeline without R installed:

```
python code/survey.py summarise
```

Filters to `eligible=Y` papers, then writes:

- `summary.csv` — per-item denominator, numerator, and % reported
  among applicable eligible papers.
- `summary_by_journal.csv` — median per-paper coverage by journal.
- `summary_meta.csv` — headline stats (n eligible, n excluded,
  median and mean coverage).

Printed to stdout: `n_papers` eligible (fills the `[N]` slot in §3),
median coverage (fills the `[X]%` slot), file paths, and the R
command to render the figure.

### 5. Render Figure 2 separately &nbsp;·&nbsp; *free*

`R/01_analysis.R` already renders the figure, so this step is only
needed if you took the Python route in step 4.

```
Rscript code/plot_figure_2.R
```

Reads `results/summary.csv` and `results/summary_meta.csv` and writes
`results/figure_2.png`. Requires: `readr`, `dplyr`, `ggplot2`,
`forcats`. Pass a different output path as the first argument (e.g.
`Rscript code/plot_figure_2.R results/figure_2.pdf`) if you want a PDF or
SVG.

Note this script keeps its own hand-maintained copy of the 18 items,
which had already drifted from the package's labels. Prefer
`R/01_analysis.R`.

## A note on `doi`

DOI extraction failed for 25 of the 150 PDFs, leaving those rows with an
empty `doi` in `scores.csv`. The papers are distinct — every `slug` and
title is unique — so `slug` is the identifier to key on. `n = 150`
is unaffected.

## Validation

Two rounds of hand-checking, both at 10% (one paper per journal), are
recorded in `scores.csv`:

- `validated_prior` — the first paper of each journal in the original
  row order. This round was used to refine the scoring prompts, so
  agreement on it is in-sample and not evidence of accuracy.
- `validated_post` — a second, held-out sample drawn at random from the
  papers not used in that refinement (seed 20260903). This is the round
  the manuscript reports.

`validation_notes.csv` holds the second round in workable form: one row
per item per paper, carrying the automated score, its justification, and
an `agree` column recording whether the hand-check upheld it. Agreement
was 262 of 270 item-level scores (97%). Every disagreement ran the same
way, with the automated scoring crediting an item that had not clearly
been reported, so coverage is if anything slightly overstated. Those
eight scores were left as scored rather than corrected, so the validated
subset is treated no differently from the other 135 papers.

To repeat the exercise, re-score by hand from `scores_notes.csv` — that
is fast, since the notes are per-item quotes.
Common places to expect drift:

- `behaviour_general` and `affect_indicators` are the least literal, so
  Claude sometimes reads implicit reporting as Y.
- `env_field` vs `env_housing` NA judgements can slip if a study
  mixes field collection with lab holding.
- `ethics_review` needs Y even when the study just says "no ethics
  approval was required for invertebrate work" — that IS a report.
- `health_injury` should not be Y for planned experimental mortality;
  the item is about unexpected injury and death.
- `proc_biosecurity` is easily marked NA for lab work on an introduced
  species, which is exactly where it does apply.

If a per-item drift is systematic, tweak the corresponding prompt line
in `RUBRIC` inside `survey.py` and re-score with `--force`.

## Layout after a full run

```
survey/
├── README.md                           # this file
├── rubric.md                           # the 18-item scoring rubric (human-readable)
├── code/                               # all scripts
│   ├── survey.py                       # the Python pipeline
│   ├── build_papers_from_pdfs.py       # metadata harvest from local PDFs
│   ├── enrich_papers_from_crossref.py  # optional CrossRef enrichment
│   ├── redact_pii.py                   # strips scraped emails from metadata
│   └── plot_figure_2.R                 # R/ggplot2 figure renderer
├── pdfs/                               # NOT IN REPO - publisher copyright
├── texts/                              # NOT IN REPO - publisher copyright
└── results/                            # all deliverables live here
    ├── papers.csv                      # candidate papers
    ├── scores.csv                      # per-paper × per-item scores + eligibility
    ├── scores_notes.csv                # per-cell justifications + eligibility notes
    ├── validation_notes.csv            # held-out hand-check of 15 papers
    ├── summary.csv                     # per-item aggregate stats
    ├── summary_by_journal.csv          # per-journal median coverage
    ├── summary_meta.csv                # headline stats (n, medians, means)
    └── figure_2.png                    # baseline barchart (rendered by R)
```

## Licence

Code in `code/` is MIT licensed (see `LICENSE` at the repository root).
The data in `results/` is released under CC0. Bibliographic metadata originates from OpenAlex
and Crossref. The surveyed papers themselves remain under their
publishers' terms and are not redistributed here.
