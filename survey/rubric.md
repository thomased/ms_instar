# Scoring rubric

Same rubric the LLM sees, in a form convenient for hand-scoring the
spot-check sample. Codes: **Y** = reported, **N** = not reported,
**NA** = not applicable to this study design.

Commit to one of the three — no hedging. If you cannot find a positive
statement in the methods, mark N. Reserve NA only for items that
genuinely can't apply (e.g. `env_field` for pure lab work).

**Silence is not reporting.** Absence of any mention of an item is N,
not Y. Do not treat "the paper doesn't discuss injuries" as evidence
that no injuries occurred — the paper has to affirmatively address the
item (even a "no injuries observed" sentence counts as reporting).

## Essentials

**subjects_taxon** — Taxonomic ID at species or lowest practicable
level, how identified, life stage and sex.

**subjects_source** — Origin: wild-collected (with locality and date),
lab colony (founding stock, source, date), or commercial supplier
(named).

**subjects_n** — Sample size (individuals or effort units), any
attrition between collection and analysis, and a justification for the
sample size chosen.

**proc_handling** — Capture, transport, handling and restraint; any
marking or tagging; broad-sampling effort (trap-days) and design where
relevant.

**proc_anaesthesia** — Anaesthesia agent and method AND analgesia (or
an explicit reason for omission of either) AND details of any surgical
or invasive procedure. Merely describing the invasive procedure
without any statement about anaesthesia/analgesia (or an explicit
justification for omitting them) is N, not Y. NA only if no invasive
procedure of any kind was performed.

**proc_biosecurity** — Measures against escape (especially non-native
taxa) and disposal of contaminated material. NA if no captive holding
or non-native risk.

**ethics_review** — Institutional/regulatory ethics review, permit
numbers, and conservation status of focal taxa — OR an explicit
statement that none was required with welfare reasoning.

**ethics_endpoints** — Predefined humane endpoints, and (for field
work) anticipated and observed non-target impacts.

**ethics_statement** — A statement engaging with welfare
considerations and/or the three Rs (Replacement, Reduction,
Refinement) as these informed the study design. A bare mention of an
institutional or regulatory permit belongs to `ethics_review` and does
NOT count here — this item requires the paper to actually discuss
welfare reasoning or how the study was designed to reduce, refine, or
replace animal use.

## Welfare domains

**nutrition_diet** — Diet or bait composition and source; feeding
frequency and access; water or moisture provision; any pre- or
post-experimental fasting.

**env_housing** — Enclosure materials, dimensions, substrate,
structural complexity; density and grouping; temperature, humidity,
ventilation, photoperiod; water parameters (aquatic); cleaning. NA for
pure field studies with no captive holding.

**env_acclimation** — Duration and conditions of any acclimation
period before procedures. NA if none applies.

**env_field** — Field site (habitat, location, abiotic conditions,
seasonality), trap design and deployment, checking frequency,
mitigation of injury or exposure. NA for pure lab studies.

**health_monitoring** — Methods and criteria for assessing physical
condition; any disease or parasite screening; frequency of welfare
checks.

**health_injury** — Number and timing of injuries and unexpected
deaths, causes, interventions — OR an explicit statement that none
occurred; or (for mass-rearing) aggregate disease-screening and
condition monitoring. Silence is N.

**fate_end** — End of study: the SPECIFIC method of killing must be
named (e.g. CO2 asphyxiation, cold anaesthesia + decapitation,
formalin fixation, freezing at -80°C, immersion in ethanol) with
justification. Killing merely implied by downstream processing (e.g.
"fillets prepared", "RNA extracted") without an explicit method
statement is N. Also covers release, holding, rehoming, and voucher
specimen deposition.

**behaviour_general** — Aspects of the setup supporting or constraining
species-typical behaviour; refugia and enrichment; disturbance
minimisation; social grouping.

**affect_indicators** — Behavioural or physiological indicators of
stress, pain, or distress; precautionary measures adopted where
affective capacity is uncertain.
