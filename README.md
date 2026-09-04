# INSTAR: data and code

Materials behind **INSTAR** (INvertebrate Standards for Treatment And
Reporting), an 18-item framework for reporting invertebrate welfare in
research.

> White, T. E., Lynch, K., Amory, J., Forster, C. Y., Hart, A. G.,
> Latty, T., Umbers, K., & Drinkwater, E. (in prep). INSTAR: reporting
> items for invertebrate welfare in research.

This repository holds the reporting sheet, the baseline literature
survey reported in section 3, and the scripts that produce every number
and figure in the paper. The framework itself is implemented as an R
package, which lives separately:

- **Package and web tool:** <https://instar-statement.org>
- **Source:** <https://github.com/thomased/instarreport>

## Layout

```
.
├── data/
│   ├── INSTAR.csv              # the blank reporting sheet (plain text)
│   └── INSTAR.xlsx             # identical, formatted for spreadsheet use
├── R/
│   ├── 01_analysis.R           # section 3: all numbers + Figure 2
│   └── 02_exemplar_manzi.R     # Figure 1 exemplar
├── survey/                     # the baseline literature survey (see its README)
│   ├── code/                   # the scoring pipeline
│   └── results/                # scores and summaries for all 150 papers
└── figs/                       # rendered figures
```

## Reproducing the paper

Everything runs from this directory. You will need the `instarreport`
package:

```r
# install.packages("remotes")
remotes::install_github("thomased/instarreport")
```

**Section 3 and Figure 2.** Reads the scoring table and computes every
value quoted in the results, writes the three summary tables, and renders
Figure 2:

```
Rscript R/01_analysis.R
```

Aggregation runs through `instarreport::audit_from_matrix()`, so the item
definitions, domain grouping and coverage arithmetic all come from the
package rather than being restated here.

**Figure 1.** The framework applied to a single published study, as a
worked example:

```
Rscript R/02_exemplar_manzi.R
```

**The survey itself.** Re-running the scoring pipeline that produced
`survey/results/` is a separate, longer job with its own requirements and
API costs. See [`survey/README.md`](survey/README.md).

## Licence

Code is MIT licensed (see `LICENSE`). The data in `survey/results/` and
`data/` is released under CC0. Bibliographic metadata originates from
OpenAlex and Crossref. The surveyed papers remain under their publishers'
terms and are not redistributed here.
