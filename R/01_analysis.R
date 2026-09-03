# --------------------------------------------------------------------
# Section 3: baseline survey of reporting in the recent literature.
#
# Computes every number quoted in section 3 of the manuscript, writes
# the three summary tables, and renders Figure 2, all from a single
# scoring table.
#
# The analysis runs through instarreport itself. The 150 surveyed papers
# predate INSTAR and so have no completed sheets to read; they were
# scored by hand into a wide table (one row per paper, one column per
# item_id), which is what audit_from_matrix() takes. Doing it this way
# means the framework definition, the item labels, the domain grouping,
# and the coverage arithmetic all come from the package rather than
# being restated here. An earlier version of this analysis kept its own
# copy of the 18 items and its own coverage code, and both had drifted.
#
# Run from the project root:
#   Rscript R/01_analysis.R
# --------------------------------------------------------------------

suppressPackageStartupMessages({
  library(instarreport)
  library(ggplot2)
})

results_dir <- file.path("survey", "results")
scores_csv  <- file.path(results_dir, "scores.csv")
stopifnot(file.exists(scores_csv))


# ---- read and filter -----------------------------------------------

scores <- utils::read.csv(scores_csv, stringsAsFactors = FALSE,
                          na.strings = character(0), colClasses = "character")

# `eligible` records the screening decision. Papers marked otherwise were
# excluded before scoring; keep the count for the methods text.
n_screened <- nrow(scores)
scores <- scores[toupper(trimws(scores$eligible)) == "Y", , drop = FALSE]
n_excluded <- n_screened - nrow(scores)

# Drop the screening flag itself: it is constant across what remains and
# would otherwise ride along as a study-metadata column.
scores$eligible <- NULL


# ---- audit -----------------------------------------------------------

# Columns matching an item_id become framework items; slug, doi, journal
# and title are carried through as study metadata, which is what makes
# the per-journal breakdown below a one-liner.
#
# `slug` rather than `doi` as the identifier: DOI extraction failed for
# 25 of the 150 PDFs, leaving those rows with an empty DOI. The papers
# are distinct (every slug and title is), but keying on DOI would
# collapse them into one repeated, blank id.
stopifnot(!anyDuplicated(scores$slug))
audit <- audit_from_matrix(scores, id = "slug")

items   <- summary(audit)     # one row per framework item
studies <- audit$studies      # one row per paper, with its own coverage

stopifnot(
  nrow(items) == nrow(instar_items),
  nrow(studies) == nrow(scores)
)


# ---- per-item summary ------------------------------------------------

per_item <- data.frame(
  item_id      = items$item_id,
  n_applicable = items$applicable,
  n_reported   = items$reported,
  pct_reported = sprintf("%.1f", items$percent_reported),
  stringsAsFactors = FALSE
)
utils::write.csv(per_item, file.path(results_dir, "summary.csv"),
                 row.names = FALSE)


# ---- per-journal median coverage -------------------------------------

by_journal <- stats::aggregate(
  percent_reported ~ journal, data = studies, FUN = stats::median
)
by_journal$n_papers <- as.integer(table(studies$journal)[by_journal$journal])
by_journal <- by_journal[order(by_journal$journal), c("journal", "n_papers",
                                                      "percent_reported")]
names(by_journal)[3] <- "median_coverage_pct"
by_journal$median_coverage_pct <- sprintf("%.1f", by_journal$median_coverage_pct)
utils::write.csv(by_journal, file.path(results_dir, "summary_by_journal.csv"),
                 row.names = FALSE)


# ---- headline numbers ------------------------------------------------

median_cov <- stats::median(studies$percent_reported, na.rm = TRUE)
mean_cov   <- mean(studies$percent_reported, na.rm = TRUE)

meta <- data.frame(
  key = c("n_eligible", "n_excluded",
          "median_coverage_pct", "mean_coverage_pct"),
  value = c(nrow(studies), n_excluded,
            sprintf("%.2f", median_cov), sprintf("%.2f", mean_cov)),
  stringsAsFactors = FALSE
)
utils::write.csv(meta, file.path(results_dir, "summary_meta.csv"),
                 row.names = FALSE)

cat(sprintf(
  "\n== INSTAR baseline ==\npapers: %d eligible (%d excluded)\nmedian coverage: %.1f%%\nmean coverage: %.1f%%\n",
  nrow(studies), n_excluded, median_cov, mean_cov
))

# The three weakest items, which the Results paragraph calls out.
worst <- items[order(items$percent_reported), ][1:3, ]
cat("\nleast reported:\n")
for (i in seq_len(nrow(worst))) {
  cat(sprintf("  %5.1f%%  %s\n", worst$percent_reported[i], worst$item[i]))
}
cat(sprintf("\nper-journal median coverage spans %.1f%% to %.1f%%\n",
            min(as.numeric(by_journal$median_coverage_pct)),
            max(as.numeric(by_journal$median_coverage_pct))))


# ---- Figure 2 --------------------------------------------------------

# plot(audit) draws a serviceable version of this. The manuscript figure
# adds the applicable-n against each bar and follows Figure 1's colours,
# so it is built explicitly -- but from `items`, so the labels, order and
# domain grouping still come from instar_items and cannot drift.
fig_colours <- c(foundation = "#2E5F8E", welfare = "#3F7A3A")  # as Figure 1

d <- items
d$item <- factor(d$item, levels = rev(instar_items$item))
d$label <- sprintf("%.0f%%  (n = %d)", d$percent_reported, d$applicable)

p <- ggplot(d, aes(x = percent_reported, y = item, fill = group)) +
  geom_col(width = 0.75) +
  geom_text(aes(label = label), hjust = -0.05, size = 3, colour = "grey30") +
  scale_x_continuous(
    limits = c(0, 130), breaks = seq(0, 100, 20), expand = c(0, 0),
    labels = function(x) ifelse(x > 100, "", paste0(x, "%"))
  ) +
  scale_fill_manual(values = fig_colours, guide = "none") +
  labs(
    x = "Papers reporting item (% of applicable)",
    y = NULL,
    title = "INSTAR reporting baseline",
    subtitle = sprintf("n = %d papers; median coverage = %.0f%%",
                       nrow(studies), median_cov)
  ) +
  theme_minimal(base_size = 10) +
  theme(
    panel.grid.major.y = element_blank(),
    panel.grid.minor.x = element_blank(),
    axis.text.y  = element_text(angle = 10, hjust = 1, vjust = 0.5, size = 9),
    axis.title.x = element_text(margin = margin(t = 8)),
    plot.title    = element_text(face = "bold", size = 12),
    plot.subtitle = element_text(colour = "grey30", margin = margin(b = 8))
  )

ggsave(file.path(results_dir, "figure_2.png"), p,
       width = 7.5, height = 8.5, dpi = 200)
ggsave(file.path("figs", "figure_2.pdf"), p, width = 7.5, height = 8.5)
