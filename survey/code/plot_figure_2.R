# SUPERSEDED by ../../R/01_analysis.R, which aggregates and plots in one
# pass through instarreport. Kept only as a fallback for rendering from
# already-committed CSVs without the package installed.
#
# Prefer:  Rscript R/01_analysis.R    (from the project root)
#
# Note the `framework` tribble below is a hand-kept copy of the 18 items
# and had already drifted from the package's labels. 01_analysis.R takes
# them from instar_items instead, so they cannot.
#
# Render results/figure_2.png from the CSVs produced by `survey.py summarise`.
#
# Requires: readr, dplyr, ggplot2, forcats
#   install.packages(c("readr", "dplyr", "ggplot2", "forcats"))
#
# Run from the survey/ directory:
#   Rscript plot_figure_2.R
# Or with a custom output path:
#   Rscript plot_figure_2.R results/figure_2.pdf

suppressPackageStartupMessages({
  library(readr)
  library(dplyr)
  library(ggplot2)
  library(forcats)
})

# ---- locate paths ----------------------------------------------------------
# Script lives in survey/code/; project root is one level up.
script_dir <- (function() {
  args <- commandArgs(trailingOnly = FALSE)
  file_arg <- grep("^--file=", args, value = TRUE)
  if (length(file_arg) == 1) {
    return(normalizePath(dirname(sub("^--file=", "", file_arg))))
  }
  getwd()
})()

project_root <- dirname(script_dir)
results_dir <- file.path(project_root, "results")
summary_csv <- file.path(results_dir, "summary.csv")
meta_csv    <- file.path(results_dir, "summary_meta.csv")

cli_args <- commandArgs(trailingOnly = TRUE)
out_path <- if (length(cli_args) >= 1) {
  cli_args[[1]]
} else {
  file.path(results_dir, "figure_2.png")
}

if (!file.exists(summary_csv)) {
  stop("missing ", summary_csv,
       " — run `python3 survey.py summarise` first")
}

# ---- read ------------------------------------------------------------------
d <- read_csv(summary_csv, show_col_types = FALSE)
meta <- if (file.exists(meta_csv)) {
  read_csv(meta_csv, show_col_types = FALSE)
} else {
  data.frame(key = character(), value = character())
}

# ---- item → domain lookup (matches R/framework.R) --------------------------
framework <- tribble(
  ~item_id,             ~item_label,                                    ~domain,
  "subjects_taxon",     "Taxonomic ID, life stage, & sex",              "Subjects",
  "subjects_source",    "Source & culture history",                     "Subjects",
  "subjects_n",         "Sample size & attrition",                      "Subjects",
  "proc_handling",      "Capture, transport, & handling",               "Procedures",
  "proc_anaesthesia",   "Anaesthesia, analgesia, & invasive procedures","Procedures",
  "proc_biosecurity",   "Containment & biosecurity",                    "Procedures",
  "ethics_review",      "Ethics review, permits, & conservation",       "Ethics & Compliance",
  "ethics_endpoints",   "Humane endpoints & non-target impacts",        "Ethics & Compliance",
  "ethics_statement",   "Welfare & 3Rs statement",                      "Ethics & Compliance",
  "nutrition_diet",     "Diet, feeding, & water",                       "Nutrition",
  "env_housing",        "Housing & abiotic conditions",                 "Environment",
  "env_acclimation",    "Acclimation",                                  "Environment",
  "env_field",          "Field site & collection",                      "Environment",
  "health_monitoring",  "Health monitoring",                            "Health",
  "health_injury",      "Injury & mortality",                           "Health",
  "fate_end",           "End of study",                                 "Health",
  "behaviour_general",  "Behavioural opportunities & agency",           "Behaviour",
  "affect_indicators",  "Indicators & precautionary measures",          "Affective state"
)

# foundations in blue, welfare domains in green — matches Figure 1
domain_cols <- c(
  "Subjects"            = "#3B6EA8",
  "Procedures"          = "#3B6EA8",
  "Ethics & Compliance" = "#3B6EA8",
  "Nutrition"           = "#4B9E6E",
  "Environment"         = "#4B9E6E",
  "Health"              = "#4B9E6E",
  "Behaviour"           = "#4B9E6E",
  "Affective state"     = "#4B9E6E"
)

# ---- prep ------------------------------------------------------------------
d <- d %>%
  mutate(
    pct_reported = as.numeric(pct_reported),
    n_applicable = as.integer(n_applicable),
    n_reported   = as.integer(n_reported)
  ) %>%
  left_join(framework, by = "item_id") %>%
  mutate(item_label = fct_rev(fct_inorder(item_label)))

meta_val <- function(k) {
  v <- meta$value[meta$key == k]
  if (length(v) == 0) NA else v[[1]]
}
n_eligible <- suppressWarnings(as.integer(meta_val("n_eligible")))
median_cov <- suppressWarnings(as.numeric(meta_val("median_coverage_pct")))

subtitle_text <- if (!is.na(n_eligible)) {
  sprintf("n = %d eligible papers; median coverage = %.0f%%",
          n_eligible, median_cov)
} else {
  NULL
}

# ---- plot ------------------------------------------------------------------
p <- ggplot(d, aes(x = pct_reported, y = item_label, fill = domain)) +
  geom_col(width = 0.75) +
  geom_text(
    aes(label = sprintf("%.0f%%  (n = %d)",
                        pct_reported, n_applicable)),
    hjust = -0.05, size = 3, colour = "grey30"
  ) +
  scale_x_continuous(
    limits = c(0, 130), breaks = seq(0, 100, 20),
    expand = c(0, 0),
    labels = function(x) if_else(x > 100, "", paste0(x, "%"))
  ) +
  scale_fill_manual(values = domain_cols, guide = "none") +
  labs(
    x = "Papers reporting item (% of applicable)",
    y = NULL,
    title = "INSTAR reporting baseline",
    subtitle = subtitle_text
  ) +
  theme_minimal(base_size = 10) +
  theme(
    panel.grid.major.y = element_blank(),
    panel.grid.minor.x = element_blank(),
    axis.text.y = element_text(angle = 10, hjust = 1,
                               vjust = 0.5, size = 9),
    axis.title.x = element_text(margin = margin(t = 8)),
    plot.title = element_text(face = "bold", size = 12),
    plot.subtitle = element_text(colour = "grey30",
                                 margin = margin(b = 8))
  )

# ---- save ------------------------------------------------------------------
ext <- tolower(tools::file_ext(out_path))
device <- switch(ext, pdf = "pdf", svg = "svg", "png")
ggsave(out_path, p,
       width = 7.5, height = 8.5, dpi = 200, device = device)

message("wrote ", out_path)
