# Build the Figure 1 exemplar for the manuscript: the INSTAR framework
# applied to Manzi et al. (2026) "Flexible self-protection as evidence of
# pain-like states in house crickets", Proc. R. Soc. B.
#
# Run from the project root. Output lands in figs/.

library(instarreport)

# instar_set() takes item_id = "what the study reports" pairs, and sets
# `value` and `status` together. That pairing is the point: `status` is
# the single source of truth, and instar_report() blanks `value` wherever
# status is not "reported", so assigning `value` alone discards the text
# without erroring. Items omitted here stay unreported; NA marks an item
# as not applicable to this study.
items <- instar_set(
  instar_template(),

  # --- Subjects ---
  subjects_taxon = "Acheta domesticus (house cricket); adults of both sexes",
  subjects_source = "Commercially reared; Petstock (Australia); founding stock and generations in captivity not recorded",
  subjects_n = "n = 80 adults (40 M, 40 F); all analysed; fully within-subjects design; sample size not formally justified",

  # --- Procedures ---  (proc_biosecurity: not reported by the study)
  proc_handling = "Crickets gently immobilized on a sponge for each treatment application; immediately transferred to observation arena; identical handling across all three treatments",
  proc_anaesthesia = "Sponge immobilization only; no anaesthesia or analgesia (noxious heat was the experimental treatment)",

  # --- Ethics & compliance ---
  ethics_review = "No formal ethics approval required in Australia for invertebrate research; welfare reasoning explicitly provided in lieu (see Ethics statement)",
  ethics_endpoints = "No early termination triggered; all individuals completed the protocol without harm and lived out their natural lifespans in captivity",
  ethics_statement = "Welfare reasoning given: stable environment, continuous food and water, probe set to avoid lasting harm, post-study return to housing",

  # --- Nutrition ---
  nutrition_diet = "Wheatgerm ad libitum; peaches in juice as combined food and water source; no pre-experimental fasting",

  # --- Environment ---  (env_acclimation: not reported by the study)
  env_housing = "Shared holding containers 40 x 40 x 100 cm; 12:12 L:D; 23 plus/minus 1 C. Test arenas 30 x 22 x 10.5 cm at ~100 lux (low-stress) or ~1000 lux (high-stress)",
  env_field = NA,   # laboratory study only, so this does not apply

  # --- Health ---
  health_monitoring = "Crickets monitored throughout the trial period (daily checks of responsiveness and condition); no formal scoring rubric",
  health_injury = "No injuries or unexpected deaths; all individuals lived out their natural lifespans post-experiment with no lasting effects",
  fate_end = "Returned to housing containers after the study and lived out their natural lifespans under continued laboratory care with free access to food and water",

  # --- Behaviour ---
  behaviour_general = "Arena context deliberately varied in cover, substrate and illumination as part of the stress manipulation; 10-min intertrial interval in individual holding containers",

  # --- Affective state ---
  affect_indicators = "Site-directed grooming of focal antenna as pain-like behavioural indicator; 65 C noxious probe set point chosen to elicit response while avoiding lasting tissue damage (per Gibbons et al. 2024)"
)

# --- Build and save ---
report <- instar_report(
  items,
  paper = list(
    title   = "Flexible self-protection as evidence of pain-like states in house crickets",
    authors = "Manzi, Lynch, Allman, Latty, & White (2026)",
    journal = "Proc. R. Soc. B 293: 20260609"
  )
)

report   # coverage summary

# Guard against the failure this script previously had: assigning `value`
# without `status` blanks every entry, and the figure renders as wholly
# unreported without erroring. Fifteen items reported, one not applicable,
# two left unreported (acclimation, biosecurity).
stopifnot(
  report$coverage$reported == 15L,
  report$coverage$not_applicable == 1L,
  report$coverage$not_reported == 2L
)

save_figure(report, "figs/fig_S1_welfare_reporting_manzi.pdf")
save_figure(report, "figs/fig_S1_welfare_reporting_manzi.png", dpi = 300)
