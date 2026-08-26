#!/usr/bin/env python3
"""INSTAR baseline literature survey.

Pipeline in four subcommands:
    fetch        Query OpenAlex for recent invertebrate papers across the
                 twelve target journals; write papers.csv.
    texts        Download OA PDFs (or use manually-supplied ones from
                 pdfs/), extract the methods section; write texts/*.txt.
    score        Ask Claude to score each paper's methods against the 18
                 INSTAR items; write scores.csv.
    summarise    Aggregate per-item and per-journal, save summary.csv and
                 a matplotlib figure.

Typical flow (from this directory):
    python survey.py fetch --per-journal 6 --dry-run   # inspect the list
    python survey.py fetch --per-journal 6             # write papers.csv
    python survey.py texts                             # fetch/extract
    export ANTHROPIC_API_KEY=...
    python survey.py score --dry-run                   # cost preview
    python survey.py score                             # run scoring
    python survey.py summarise

Manually add a paywalled paper: drop its PDF at pdfs/<slug>.pdf where
<slug> matches the `slug` column of papers.csv.

Requires: requests, pdfplumber, anthropic (>=0.34).
Install: pip install requests pdfplumber anthropic
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Constants: journals, invert keywords, scoring rubric
# ---------------------------------------------------------------------------

JOURNALS: list[tuple[str, str]] = [
    # (display name, ISSN — either print or electronic; OpenAlex resolves both)
    ("The American Naturalist",             "0003-0147"),
    ("Animal Behaviour",                    "0003-3472"),
    ("Aquaculture",                         "0044-8486"),
    ("Behavioral Ecology",                  "1045-2249"),
    ("Behavioral Ecology and Sociobiology", "0340-5443"),
    ("Biology Letters",                     "1744-9561"),
    ("Current Zoology",                     "1674-5507"),
    ("Ecology Letters",                     "1461-023X"),
    ("Ethology",                            "0179-1613"),
    ("Evolution",                           "0014-3820"),
    ("Functional Ecology",                  "0269-8463"),
    ("Journal of Comparative Physiology A", "0340-7594"),
    ("Journal of Experimental Biology",     "0022-0949"),
    ("Journal of Insect Physiology",        "0022-1910"),
    ("Journal of Insects as Food and Feed", "2352-4588"),
    ("Journal of Invertebrate Pathology",   "0022-2011"),
    ("PLOS ONE",                            "1932-6203"),
    ("PeerJ",                               "2167-8359"),
    ("Proceedings of the Royal Society B",  "0962-8452"),
    ("Royal Society Open Science",          "2054-5703"),
]

# Title-only positive screen: word-boundary matches so "worm" hits
# "worms" but not "warming". The pre-scoring filter is strict — better
# to lose a few real invert papers than to spend Claude tokens on
# vertebrate/plant papers that mention an invert in passing.
INVERT_TITLE_RE = re.compile(
    r"\b("
    r"insect\w*|arthropod\w*|invertebrate\w*|crustacean\w*|"
    r"mollus[ck]\w*|gastropod\w*|nematode\w*|annelid\w*|"
    r"spider\w*|arachnid\w*|beetle\w*|moth|moths|butterfl(?:y|ies)|"
    r"bee|bees|bumblebee\w*|honeybee\w*|wasp\w*|ant|ants|hornet\w*|"
    r"cricket\w*|cockroach\w*|drosophila|cephalopod\w*|"
    r"octopus|octopi|octopod\w*|squid|cuttlefish|nautilus|"
    r"lobster\w*|crab|crabs|crayfish|shrimp\w*|prawn\w*|"
    r"aphid\w*|worm|worms|nematod\w*|isopod\w*|amphipod\w*|"
    r"copepod\w*|krill|coral\w*|anemone\w*|jellyfish|"
    r"urchin\w*|starfish|planarian\w*|flatworm\w*|roundworm\w*|"
    r"earthworm\w*|leech\w*|millipede\w*|centipede\w*|"
    r"scorpion\w*|mite|mites|tick|ticks|"
    r"fly|flies|grasshopper\w*|locust\w*|termite\w*|"
    r"mayfl(?:y|ies)|damselfl(?:y|ies)|dragonfl(?:y|ies)|"
    r"bug|bugs|hemiptera\w*|coleoptera\w*|diptera\w*|"
    r"hymenoptera\w*|lepidoptera\w*|orthoptera\w*|arachnida|"
    # taxonomic terms
    r"parasitoid\w*|entomopath\w+|pollinator\w*|silkworm\w*|"
    r"mosquito\w*|housefl(?:y|ies)|oyster\w*|mussel\w*|scallop\w*|"
    r"waterflea|daphnid\w*|"
    # common invert genera in behaviour/ecology/physiology lit
    r"acheta|gryllus|gryllodes|apis|bombus|tribolium|manduca|"
    r"caenorhabditis|plutella|nasonia|daphnia|aphis|bombyx|vespula|"
    r"anopheles|aedes|culex|musca|crassostrea|mytilus|ostrea|"
    r"litopenaeus|penaeus|homarus|argopecten|hermetia|tenebrio|"
    r"sepia|loligo|nautilus|carcinus|drosophila\w*|nasonia"
    r")\b",
    re.IGNORECASE,
)

# Title-level negative screen: papers that obviously aren't about a
# live invertebrate. Broader than the positive list because a match
# here always overrides.
VERTEBRATE_TITLE_RE = re.compile(
    r"\b("
    r"mammal\w*|rodent\w*|primate\w*|hominin\w*|"
    r"frog\w*|toad\w*|salamander\w*|newt|anuran\w*|amphibian\w*|"
    r"reptil\w*|lizard\w*|snake\w*|turtle\w*|tortoise\w*|"
    r"gecko\w*|crocodil\w*|alligator\w*|"
    r"bird\w*|avian|passerine\w*|songbird\w*|hummingbird\w*|"
    r"sparrow\w*|finch\w*|warbler\w*|owl\w*|raptor\w*|"
    r"chicken\w*|duck\w*|goose|geese|swan\w*|"
    r"fish|fishes|shark\w*|salmon\w*|trout|zebrafish\w*|tilapia\w*|"
    r"guppy|guppies|cichlid\w*|stickleback\w*|goldfish\w*|minnow\w*|"
    # -fish compounds (jellyfish/starfish/shellfish/cuttlefish are
    # already invert-caught upstream so safe to catch here)
    r"\w{3,}fish(?:es)?|"
    r"seabass|bass|carp|cod\b|eel\b|ray\b|"
    r"cormorant\w*|ratite\w*|palaeognath\w*|neognath\w*|"
    r"human\w*|monkey\w*|chimpanzee\w*|gorilla\w*|orangutan\w*|"
    r"macaque\w*|baboon\w*|lemur\w*|marmoset\w*|"
    r"mouse|mice|rat|rats|vole\w*|hamster\w*|"
    r"squirrel\w*|rabbit\w*|hare\w*|"
    r"sheep|goat\w*|cow|cows|cattle|bovine|pig|pigs|porcine|"
    r"horse\w*|equine|dog|dogs|canine|cat|cats|feline|"
    r"carnivor\w*|ungulate\w*|marsupial\w*|"
    r"whale\w*|dolphin\w*|cetacean\w*|porpoise\w*|manatee\w*|"
    r"seal|seals|pinniped\w*|bat|bats|myotis|chiroptera\w*|"
    r"vertebrate\w*|tetrapod\w*|"
    r"algae|algal|seaweed\w*|kelp|"
    r"plant\w*|flower\w*|leaf|leaves|tree|trees|forest\w*|"
    r"herb|herbaceous|shrub\w*|grass|grasses|moss|mosses|fern\w*|"
    r"fungus|fungi|fungal|mycorr\w*|mushroom\w*|"
    r"bacteria\w*|bacterial|microbi\w*|virus\w*|viral|"
    r"phytoplankton|diatom\w*"
    r")\b",
    re.IGNORECASE,
)

# Compact LLM-friendly rubric. Keep entries short; the model already
# knows the domain. Items match framework `item_id` column.
RUBRIC: list[dict[str, str]] = [
    {"id": "subjects_taxon",
     "prompt": "Taxonomic ID at species or lowest practicable level, "
               "how identified, life stage and sex."},
    {"id": "subjects_source",
     "prompt": "Origin: wild-collected (with locality and date), lab "
               "colony (founding stock, source, date), or commercial "
               "supplier (named)."},
    {"id": "subjects_n",
     "prompt": "Sample size (individuals or effort units), any attrition "
               "between collection and analysis, and a justification for "
               "the sample size chosen."},
    {"id": "proc_handling",
     "prompt": "Capture, transport, handling and restraint; any marking "
               "or tagging; broad-sampling effort (trap-days) and design "
               "where relevant."},
    {"id": "proc_anaesthesia",
     "prompt": "Anaesthesia agent and method AND analgesia (or an "
               "explicit reason for omission of either) AND details of "
               "any surgical or invasive procedure. Merely describing "
               "the invasive procedure without any statement about "
               "anaesthesia/analgesia (or an explicit justification for "
               "omitting them) is N, not Y. NA only if no invasive "
               "procedure of any kind was performed."},
    {"id": "proc_biosecurity",
     "prompt": "Measures against escape (especially non-native taxa) "
               "and disposal of contaminated material. NA if no captive "
               "holding or non-native risk."},
    {"id": "ethics_review",
     "prompt": "Institutional/regulatory ethics review, permit numbers, "
               "and conservation status of focal taxa — OR an explicit "
               "statement that none was required with welfare reasoning."},
    {"id": "ethics_endpoints",
     "prompt": "Predefined humane endpoints, and (for field work) "
               "anticipated and observed non-target impacts."},
    {"id": "ethics_statement",
     "prompt": "A statement engaging with welfare considerations and/or "
               "the three Rs (Replacement, Reduction, Refinement) as "
               "these informed the study design. A bare mention of an "
               "institutional or regulatory permit belongs to "
               "ethics_review and does NOT count here — this item "
               "requires the paper to actually discuss welfare "
               "reasoning or how the study was designed to reduce, "
               "refine, or replace animal use."},
    {"id": "nutrition_diet",
     "prompt": "Diet or bait composition and source; feeding frequency "
               "and access; water or moisture provision; any pre- or "
               "post-experimental fasting."},
    {"id": "env_housing",
     "prompt": "Enclosure materials, dimensions, substrate, structural "
               "complexity; density and grouping; temperature, humidity, "
               "ventilation, photoperiod; water parameters (aquatic); "
               "cleaning. NA for pure field studies with no captive "
               "holding."},
    {"id": "env_acclimation",
     "prompt": "Duration and conditions of any acclimation period "
               "before procedures. NA if none applies."},
    {"id": "env_field",
     "prompt": "Field site (habitat, location, abiotic conditions, "
               "seasonality), trap design and deployment, checking "
               "frequency, mitigation of injury or exposure. NA for "
               "pure lab studies."},
    {"id": "health_monitoring",
     "prompt": "Methods and criteria for assessing physical condition; "
               "any disease or parasite screening; frequency of welfare "
               "checks."},
    {"id": "health_injury",
     "prompt": "Number and timing of injuries and unexpected deaths, "
               "causes, interventions — OR an explicit statement that "
               "none occurred; or (for mass-rearing) aggregate "
               "disease-screening and condition monitoring. Silence on "
               "injuries/mortality is N, not Y."},
    {"id": "fate_end",
     "prompt": "End of study: the SPECIFIC method of killing must be "
               "named (e.g. CO2 asphyxiation, cold anaesthesia + "
               "decapitation, formalin fixation, freezing at -80°C, "
               "immersion in ethanol) with justification. Killing "
               "merely implied by downstream processing (e.g. 'fillets "
               "prepared', 'RNA extracted') without an explicit "
               "method statement is N. Also covers: release, holding, "
               "rehoming; voucher specimen deposition."},
    {"id": "behaviour_general",
     "prompt": "Aspects of the setup supporting or constraining "
               "species-typical behaviour; refugia and enrichment; "
               "disturbance minimisation; social grouping."},
    {"id": "affect_indicators",
     "prompt": "Behavioural or physiological indicators of stress, pain, "
               "or distress; precautionary measures adopted where "
               "affective capacity is uncertain."},
]

# Column ordering for scores.csv (includes eligibility flag)
SCORE_COLS = (
    ["slug", "doi", "journal", "title", "eligible"]
    + [r["id"] for r in RUBRIC]
)

# Valid per-item score values (U is retired — any hedged code coerces to N)
SCORE_VALUES = {"Y", "N", "NA"}
ELIGIBILITY_VALUES = {"Y", "N"}

# Anthropic model for scoring
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# HTTP settings
# OpenAlex and Crossref give faster, more reliable service to requests
# that identify a contact address ("polite pool"). Set SURVEY_CONTACT_EMAIL
# to opt in; without it the requests still work, just anonymously.
_CONTACT = os.environ.get("SURVEY_CONTACT_EMAIL", "").strip()
USER_AGENT = (f"instar-survey/0.1 (mailto:{_CONTACT})" if _CONTACT
              else "instar-survey/0.1")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------
def _here() -> Path:
    """Project root — one level above the code/ folder this script sits in.
    All data (pdfs/, texts/, results/) resolves relative to this."""
    return Path(__file__).resolve().parent.parent


def slugify(doi: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-",
                  doi.lower().replace("https://doi.org/", "")).strip("-")


def _get_json(url: str, params: dict | None = None, retries: int = 3) -> dict:
    import requests
    for attempt in range(retries):
        r = requests.get(url, params=params or {},
                         headers={"User-Agent": USER_AGENT}, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt)
            continue
        raise RuntimeError(f"HTTP {r.status_code} on {url}: {r.text[:200]}")
    raise RuntimeError(f"Exhausted retries on {url}")


def playwright_download_pdf(url: str, timeout_s: int = 45) -> bytes | None:
    """Render `url` in headless Chromium and capture the first PDF
    response. Handles the JavaScript landing pages served by Elsevier,
    Oxford, and U of Chicago Press. Falls back to clicking common
    'Download PDF' selectors if no PDF appears from the initial nav.

    Returns raw PDF bytes on success, None otherwise. Requires
    playwright + chromium; install with:
        pip install playwright
        playwright install chromium
    """
    try:
        from playwright.sync_api import (sync_playwright,
                                         TimeoutError as PWTimeout)
    except ImportError:
        return None

    captured: dict[str, bytes | None] = {"data": None}

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception:
            return None
        try:
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                accept_downloads=True,
                viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()

            def on_response(resp) -> None:
                if captured["data"] is not None:
                    return
                try:
                    ct = (resp.headers.get("content-type") or "").lower()
                    if "application/pdf" not in ct:
                        return
                    body = resp.body()
                    if body[:4] == b"%PDF":
                        captured["data"] = body
                except Exception:
                    return

            page.on("response", on_response)

            try:
                page.goto(url, timeout=timeout_s * 1000,
                          wait_until="domcontentloaded")
            except PWTimeout:
                pass
            except Exception:
                pass

            if captured["data"] is None:
                try:
                    page.wait_for_load_state("networkidle",
                                             timeout=15_000)
                except Exception:
                    pass

            # Still nothing — look for a PDF link and click it.
            if captured["data"] is None:
                selectors = [
                    "a[href$='.pdf']",
                    "a[href*='.pdf?']",
                    "a[title*='PDF']",
                    "a[aria-label*='PDF']",
                    "a:has-text('Download PDF')",
                    "a:has-text('View PDF')",
                    "a:has-text('Full text PDF')",
                    "a.pdf-link",
                ]
                for sel in selectors:
                    try:
                        el = page.query_selector(sel)
                    except Exception:
                        continue
                    if not el:
                        continue
                    try:
                        with page.expect_download(timeout=8_000) as info:
                            el.click()
                        dl = info.value
                        path = dl.path()
                        if path:
                            body = Path(path).read_bytes()
                            if body[:4] == b"%PDF":
                                captured["data"] = body
                                break
                    except PWTimeout:
                        # Might have navigated instead — retry via URL
                        href = el.get_attribute("href")
                        if href:
                            if href.startswith("/"):
                                base = re.match(r"https?://[^/]+", url)
                                if base:
                                    href = base.group(0) + href
                            try:
                                page.goto(href, timeout=15_000,
                                          wait_until="networkidle")
                            except Exception:
                                pass
                    except Exception:
                        continue
                    if captured["data"] is not None:
                        break
        finally:
            try:
                browser.close()
            except Exception:
                pass

    return captured["data"]


def _download(url: str, dest: Path) -> bool:
    """Fetch `url` into `dest`. Return True only if the response body
    is a real PDF (starts with %PDF magic bytes). Fails fast on
    landing pages, wrong content-type, or network timeouts."""
    import requests
    try:
        r = requests.get(
            url,
            headers={"User-Agent": USER_AGENT,
                     "Accept": "application/pdf,*/*"},
            timeout=20, allow_redirects=True,
        )
    except requests.RequestException:
        return False
    if r.status_code == 200 and r.content[:4] == b"%PDF":
        dest.write_bytes(r.content)
        return True
    return False


# ---------------------------------------------------------------------------
# fetch: OpenAlex → papers.csv
# ---------------------------------------------------------------------------
# Title patterns for non-research items — corrections, replies,
# editorials, reviews, meta-analyses, front-matter. Kept tight so it
# doesn't reject real research whose title happens to include one of
# these words in a different sense.
NON_RESEARCH_TITLE_RE = re.compile(
    r"(?:^|\b)("
    r"correction\s+to|corrigend\w+|erratum|errata|retraction|"
    r"comment\s+on|commentary(?:\s+on|:)|"
    r"reply\s+to|"
    r"response\s+to\s+(?:comment|review|the\s+comment|"
    r"criticism|critique)|"
    r":\s*a\s+critique\b|\bcritique\s*$|"
    r"reassessment\s+(?:confirms|refutes|challenges|"
    r"does\s+not|fails\s+to)|"
    r"obituary|in\s+memoriam|foreword|"
    r"editorial(?:\s*:|\s*$)|"
    r"digest\s*:|"
    r"cover\s+(?:image|picture|photo)|issue\s+information|"
    r"a\s+review\s+of|a\s+systematic\s+review|"
    r"review\s+of\s+(?:the|current|recent)|"
    r"systematic\s+review|scoping\s+review|narrative\s+review|"
    r"meta[-\s]?analys[ie]s"
    r")(?=\W|$)",  # boundary that works after ':' as well as after words
    re.IGNORECASE,
)


def is_invertebrate_paper(title: str, abstract: str) -> bool:
    """Strict title-based screen.

    - Reject non-research items (corrections, replies, reviews,
      meta-analyses, editorials, obituaries).
    - Accept if the title names an invert taxon — an invert word in
      the title outweighs any vertebrate/plant word also present
      ("Ant-plant mutualism", "Bee-flower interactions").
    - Reject if the title obviously names a non-invert focal taxon and
      no invert word is present.
    - Otherwise fall back to the abstract, but only if the abstract
      opens with an invert reference (first ~250 chars), which is
      typically the study-system sentence. This keeps out papers that
      only mention inverts as prey/comparators later on.
    """
    title = (title or "").strip()
    if not title or len(title) < 15:  # front-matter, cover blurbs
        return False
    if NON_RESEARCH_TITLE_RE.search(title):
        return False
    if INVERT_TITLE_RE.search(title):
        return True
    if VERTEBRATE_TITLE_RE.search(title):
        return False
    # Abstract fallback — invert reference must appear in the first
    # ~250 chars AND no vertebrate word appears anywhere in that
    # opening window (catches "insect meal for European seabass" cases
    # where an invert is used as a resource, not the study organism).
    abs_head = (abstract or "")[:250]
    if INVERT_TITLE_RE.search(abs_head) and not VERTEBRATE_TITLE_RE.search(abs_head):
        return True
    return False


def reconstruct_abstract(inverted_index: dict | None) -> str:
    if not inverted_index:
        return ""
    positions: dict[int, str] = {}
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions[i] = word
    return " ".join(positions[i] for i in sorted(positions))


def openalex_journal_works(issn: str, year: int, per_page: int = 200,
                           max_pages: int = 10,
                           oa_only: bool = True) -> Iterable[dict]:
    """Yield recent journal works published in a given year, paging as
    needed. Cursor pagination avoids offset limits.

    When `oa_only`, filters at the OpenAlex level so only open-access
    works come back — no need to try Unpaywall or manual PDF drops
    downstream.
    """
    url = "https://api.openalex.org/works"
    cursor = "*"
    pages = 0
    filt = (f"locations.source.issn:{issn},"
            f"publication_year:{year},has_abstract:true")
    if oa_only:
        filt += ",open_access.is_oa:true"
    while cursor and pages < max_pages:
        params = {
            "filter": filt,
            "sort": "publication_date:desc",
            "per-page": per_page,
            "cursor": cursor,
        }
        data = _get_json(url, params=params)
        results = data.get("results", []) or []
        if not results:
            break
        for r in results:
            yield r
        cursor = (data.get("meta") or {}).get("next_cursor")
        pages += 1
        time.sleep(0.1)  # be polite


def cmd_fetch(args: argparse.Namespace) -> None:
    year = args.year
    per_journal = args.per_journal
    out = _here() / args.out
    rows: list[dict] = []

    oa_only = not args.include_paywalled
    for name, issn in JOURNALS:
        oa_tag = "OA-only" if oa_only else "all-access"
        print(f"[{name}] querying OpenAlex ({oa_tag}, ISSN {issn})...",
              flush=True)
        matched: list[dict] = []
        n_screened = 0
        try:
            for w in openalex_journal_works(issn, year, oa_only=oa_only):
                n_screened += 1
                title = w.get("title") or ""
                abstract = reconstruct_abstract(
                    w.get("abstract_inverted_index"))
                if not is_invertebrate_paper(title, abstract):
                    continue
                doi = (w.get("doi") or "").replace("https://doi.org/", "")
                if not doi:
                    continue
                oa = w.get("open_access") or {}
                pdf_url = oa.get("oa_url") or ""
                best_loc = w.get("best_oa_location") or {}
                if not pdf_url:
                    pdf_url = best_loc.get("pdf_url", "") or ""
                matched.append({
                    "slug": slugify(doi),
                    "doi": doi,
                    "journal": name,
                    "title": title,
                    "abstract": abstract,
                    "publication_date": w.get("publication_date", ""),
                    "oa_status": oa.get("oa_status", ""),
                    "pdf_url": pdf_url,
                    "openalex_id": w.get("id", ""),
                })
                if len(matched) >= per_journal:
                    break
        except Exception as e:
            print(f"  ! query failed after {n_screened} results: {e}",
                  file=sys.stderr)

        print(f"  matched {len(matched):3d}/{per_journal} invertebrate "
              f"papers (screened {n_screened})", flush=True)
        rows.extend(matched)

    if args.dry_run:
        print("\n=== DRY RUN — would write ===")
        for r in rows:
            print(f"  [{r['journal']}] {r['title'][:100]}  ({r['doi']})")
        print(f"\nTotal: {len(rows)} papers across {len(JOURNALS)} journals")
        return

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [
            "slug", "doi", "journal", "title", "abstract",
            "publication_date", "oa_status", "pdf_url", "openalex_id",
        ])
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\nWrote {out} ({len(rows)} papers)")


# ---------------------------------------------------------------------------
# texts: fetch PDFs / extract methods
# ---------------------------------------------------------------------------
def unpaywall_pdf_url(doi: str, email: str) -> str | None:
    try:
        data = _get_json(f"https://api.unpaywall.org/v2/{doi}",
                         params={"email": email})
    except Exception:
        return None
    loc = data.get("best_oa_location") or {}
    return loc.get("url_for_pdf") or None


def semanticscholar_pdf_url(doi: str) -> str | None:
    """Look up OA PDF URL via Semantic Scholar's graph API. Free, no
    key needed. Aggregates PDF locations from many sources and often
    finds URLs for eco/evo/behaviour venues that PMC misses."""
    try:
        data = _get_json(
            f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}",
            params={"fields": "openAccessPdf"},
        )
    except Exception:
        return None
    oa = data.get("openAccessPdf") or {}
    return oa.get("url") or None


def europepmc_pdf_url(doi: str) -> str | None:
    """Look up a DOI in Europe PMC; if it's mirrored there, return a
    direct PDF URL that doesn't require JS or cookies. Reliably works
    for Elsevier, Oxford, PLOS, and BMC OA papers."""
    try:
        data = _get_json(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={"query": f"DOI:{doi}", "format": "json",
                    "resultType": "lite", "pageSize": 1},
        )
    except Exception:
        return None
    results = ((data.get("resultList") or {}).get("result") or [])
    if not results:
        return None
    pmcid = results[0].get("pmcid")
    if not pmcid:
        return None
    # This backend endpoint consistently serves the PDF directly.
    return (f"https://europepmc.org/backend/ptpmcrender.fcgi"
            f"?accid={pmcid}&blobtype=pdf")


def extract_pdf_text(pdf_bytes: bytes) -> str:
    import pdfplumber
    text_parts: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            text_parts.append(t)
    return "\n\n".join(text_parts)


METHODS_HEADS = re.compile(
    r"^\s*("
    r"(?:2\.?\s*)?materials?\s+and\s+methods?"
    r"|methods?"
    r"|experimental\s+(?:procedures?|methods?|design)"
    r"|methodology"
    r")\s*$",
    re.IGNORECASE | re.MULTILINE,
)

METHODS_END = re.compile(
    r"^\s*("
    r"(?:3\.?\s*)?results?"
    r"|discussion"
    r"|conclusions?"
    r"|acknowledge?ments?"
    r"|references?"
    r"|literature\s+cited"
    r")\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def extract_methods(full_text: str) -> str:
    """Return the methods section, or the whole text if the split fails."""
    start_m = METHODS_HEADS.search(full_text)
    if not start_m:
        return full_text
    tail = full_text[start_m.end():]
    end_m = METHODS_END.search(tail)
    if end_m:
        return tail[:end_m.start()].strip()
    return tail.strip()


def cmd_texts(args: argparse.Namespace) -> None:
    papers_path = _here() / args.papers
    texts_dir = _here() / args.texts_dir
    pdfs_dir = _here() / args.pdfs_dir
    texts_dir.mkdir(parents=True, exist_ok=True)
    pdfs_dir.mkdir(parents=True, exist_ok=True)

    with papers_path.open(encoding="utf-8") as f:
        papers = list(csv.DictReader(f))

    # Prune orphaned text files whose slug is no longer in papers.csv.
    # This keeps `texts/` in sync when PDFs are swapped in/out.
    valid_slugs = {p["slug"] for p in papers}
    n_pruned = 0
    for txt in texts_dir.glob("*.txt"):
        if txt.stem not in valid_slugs:
            txt.unlink()
            n_pruned += 1
    if n_pruned:
        print(f"pruned {n_pruned} orphaned text file(s) from {texts_dir}")

    n_ok = n_local = n_oa = n_fail = 0
    fails_by_journal: dict[str, list[str]] = {}
    for p in papers:
        slug = p["slug"]
        out_txt = texts_dir / f"{slug}.txt"
        if out_txt.exists() and not args.force:
            n_ok += 1
            continue

        # Look for the PDF in the location the papers.csv points to
        # (subfolder per journal), falling back to the flat pdfs/<slug>.pdf
        # convention if pdf_path is empty. This lets you organise PDFs
        # into per-journal folders without renaming everything.
        pdf_path_hint = (p.get("pdf_path") or "").strip()
        if pdf_path_hint:
            local_pdf = _here() / pdf_path_hint
        else:
            local_pdf = pdfs_dir / f"{slug}.pdf"
        pdf_bytes: bytes | None = None

        if local_pdf.exists() and local_pdf.stat().st_size > 100:
            pdf_bytes = local_pdf.read_bytes()
            if pdf_bytes[:4] == b"%PDF":
                n_local += 1
            else:
                pdf_bytes = None  # stale non-PDF from a previous run
                local_pdf.unlink()

        if pdf_bytes is None:
            # Assemble candidate sources. Order: Europe PMC (biomedical
            # OA), Semantic Scholar (best for eco/evo/beh), OpenAlex
            # (often just a landing page), Unpaywall.
            candidate_urls: list[tuple[str, str]] = []
            seen: set[str] = set()

            def add(label: str, u: str | None) -> None:
                if u and u not in seen:
                    candidate_urls.append((label, u))
                    seen.add(u)

            add("europepmc", europepmc_pdf_url(p["doi"]))
            add("semanticscholar", semanticscholar_pdf_url(p["doi"]))
            add("openalex", p.get("pdf_url"))
            if args.unpaywall_email:
                add("unpaywall",
                    unpaywall_pdf_url(p["doi"], args.unpaywall_email))

            for label, url in candidate_urls:
                print(f"  fetching {slug} ({label})...", flush=True)
                if _download(url, local_pdf):
                    pdf_bytes = local_pdf.read_bytes()
                    n_oa += 1
                    break

            # Last resort: headless-browser render of the DOI landing
            # page. Slow but works on JS-only publisher endpoints.
            if pdf_bytes is None:
                print(f"  fetching {slug} (browser)...", flush=True)
                body = playwright_download_pdf(
                    f"https://doi.org/{p['doi']}"
                )
                if body:
                    local_pdf.write_bytes(body)
                    pdf_bytes = body
                    n_oa += 1

        if pdf_bytes is None:
            n_fail += 1
            fails_by_journal.setdefault(p["journal"], []).append(
                f"{p['doi']}  ({slug})")
            continue

        try:
            full = extract_pdf_text(pdf_bytes)
        except Exception as e:
            print(f"  ! PDF parse failed for {slug}: {e}",
                  file=sys.stderr)
            n_fail += 1
            continue

        methods = extract_methods(full)
        out_txt.write_text(methods, encoding="utf-8")
        n_ok += 1

    print(f"\nready: {n_ok} texts (already-cached + newly written); "
          f"fetched-OA: {n_oa}; local-PDF: {n_local}; failed: {n_fail}")
    if fails_by_journal:
        print("\nfailures by journal (drop PDF into pdfs/<slug>.pdf to fix):")
        for j in sorted(fails_by_journal):
            fs = fails_by_journal[j]
            print(f"  [{j}]  {len(fs)}:")
            for line in fs:
                print(f"    - {line}")


# ---------------------------------------------------------------------------
# score: Claude scoring
# ---------------------------------------------------------------------------
SCORING_SYSTEM = (
    "You are an experienced peer reviewer scoring the reporting of "
    "invertebrate welfare methods against the INSTAR framework.\n\n"
    "First decide eligibility. ELIGIBLE = any empirical study that used "
    "LIVE invertebrates (insects, crustaceans, molluscs, arachnids, "
    "worms, cnidarians, echinoderms, etc.) at any point — REGARDLESS of "
    "the study's framing or how welfare-relevant the procedures were. "
    "Molecular, developmental, neurobiological, and physiological work "
    "on live invertebrates all count as eligible. INELIGIBLE only if: "
    "(a) it is a review, commentary, or purely computational study, "
    "(b) the focal organism is a vertebrate — including amphibians and "
    "amphibian larvae (tadpoles), fish, fish larvae or eggs, reptiles, "
    "birds, chick embryos, or mammals — a plant, or a micro-organism, "
    "or (c) only preserved specimens were used (fixed tissue, museum "
    "specimens, or animals that were never held alive by the authors).\n\n"
    "If ELIGIBLE, commit to exactly one of three codes per item:\n"
    "  Y  = reported (any level of detail counts as reported)\n"
    "  N  = not reported (default when in doubt)\n"
    "  NA = not applicable to this study design\n"
    "Do NOT use 'uncertain' or hedged codes — if you cannot find a "
    "positive statement in the methods, mark N. Reserve NA only for "
    "items that genuinely cannot apply given the study design "
    "(e.g. env_field for a pure lab study; proc_anaesthesia if no "
    "invasive procedures were performed).\n\n"
    "CRITICAL — silence is not reporting. If the paper does not "
    "mention an item at all, mark N. Do not treat the absence of any "
    "mention (e.g. no discussion of injuries, no mention of humane "
    "endpoints) as positive evidence that zero events occurred. The "
    "item must be affirmatively addressed in the text — even a "
    "statement 'no injuries were observed' counts as reporting, but "
    "silence does not.\n\n"
    "Return ONLY one JSON object with this shape:\n"
    "{\n"
    '  "eligible": "Y" or "N",\n'
    '  "eligibility_note": "one short sentence",\n'
    '  "items": { <item_id>: {"score": <Y|N|NA>, "note": <optional short '
    'quote or reason, up to 20 words>}, ... }\n'
    "}\n"
    "If eligible is N, `items` may be omitted or empty."
)


def build_scoring_prompt(methods: str, max_chars: int = 120_000) -> str:
    rubric_lines = "\n".join(
        f"- {r['id']}: {r['prompt']}" for r in RUBRIC
    )
    m = methods.strip()
    if len(m) > max_chars:
        m = m[:max_chars] + "\n[...text truncated...]"
    return (
        "INSTAR items to score:\n"
        f"{rubric_lines}\n\n"
        "Methods text (extracted from PDF, may include OCR noise):\n"
        f"```\n{m}\n```\n\n"
        "Return the JSON object described in the system prompt. No prose."
    )


def parse_score_json(text: str) -> tuple[str, str, dict[str, dict]]:
    """Return (eligible, eligibility_note, per_item_scores)."""
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError("no JSON object in response")
    obj = json.loads(m.group(0))
    eligible = str(obj.get("eligible", "U")).upper()
    if eligible not in ELIGIBILITY_VALUES:
        eligible = "N"  # be conservative: exclude ambiguous papers
    elig_note = str(obj.get("eligibility_note", ""))[:200]
    items_obj = obj.get("items") or {}
    scores: dict[str, dict] = {}
    for r in RUBRIC:
        entry = items_obj.get(r["id"]) or {}
        score = str(entry.get("score", "N")).upper()
        # Coerce any hedged/unknown code (including a legacy "U") to N.
        if score not in SCORE_VALUES:
            score = "N"
        note = str(entry.get("note", ""))[:200]
        scores[r["id"]] = {"score": score, "note": note}
    return eligible, elig_note, scores


def cmd_score(args: argparse.Namespace) -> None:
    papers_path = _here() / args.papers
    texts_dir = _here() / args.texts_dir
    scores_path = _here() / args.scores
    notes_path = _here() / args.notes
    scores_path.parent.mkdir(parents=True, exist_ok=True)

    with papers_path.open(encoding="utf-8") as f:
        papers = list(csv.DictReader(f))

    # Load existing scores so re-runs are incremental
    existing: dict[str, dict] = {}
    if scores_path.exists() and not args.force:
        with scores_path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing[row["slug"]] = row

    to_score: list[dict] = []
    skipped_no_text = 0
    for p in papers:
        if p["slug"] in existing:
            continue
        if not (texts_dir / f"{p['slug']}.txt").exists():
            skipped_no_text += 1
            continue
        to_score.append(p)

    if args.dry_run:
        # Rough token estimate: 4 chars ≈ 1 token
        total_chars = 0
        for p in to_score:
            total_chars += len((texts_dir / f"{p['slug']}.txt")
                               .read_text(encoding="utf-8"))
        est_tokens = total_chars // 4 + 2000 * len(to_score)  # + rubric
        print(f"papers to score: {len(to_score)}")
        print(f"skipped (no text): {skipped_no_text}")
        print(f"est. input tokens ≈ {est_tokens:,}")
        print(f"model: {args.model}")
        print("(no API calls made)")
        return

    from anthropic import Anthropic
    client = Anthropic()  # picks up ANTHROPIC_API_KEY

    # Prepare output writers (append mode after header exists)
    header_written = scores_path.exists() and existing
    scores_f = scores_path.open("a" if header_written else "w",
                                newline="", encoding="utf-8")
    notes_f = notes_path.open("a" if header_written else "w",
                              newline="", encoding="utf-8")
    scores_w = csv.DictWriter(scores_f, fieldnames=SCORE_COLS)
    notes_w = csv.DictWriter(
        notes_f,
        fieldnames=["slug", "doi", "journal", "item_id", "score", "note"],
    )
    if not header_written:
        scores_w.writeheader()
        notes_w.writeheader()

    n_ineligible = 0
    for i, p in enumerate(to_score, 1):
        text = (texts_dir / f"{p['slug']}.txt").read_text(encoding="utf-8")
        prompt = build_scoring_prompt(text)
        print(f"[{i}/{len(to_score)}] {p['slug']}", flush=True)

        # retry with exponential backoff on rate-limit / transient errors
        parsed = None
        for attempt in range(4):
            try:
                resp = client.messages.create(
                    model=args.model,
                    max_tokens=2000,
                    system=SCORING_SYSTEM,
                    messages=[{"role": "user", "content": prompt}],
                )
                payload = resp.content[0].text
                parsed = parse_score_json(payload)
                break
            except Exception as e:
                msg = str(e).lower()
                transient = ("rate" in msg or "overload" in msg
                             or "timeout" in msg or "connection" in msg)
                if attempt < 3 and transient:
                    delay = 2 ** attempt
                    print(f"  transient error, retrying in {delay}s: {e}",
                          file=sys.stderr)
                    time.sleep(delay)
                    continue
                print(f"  ! scoring failed: {e}", file=sys.stderr)
                break
        if parsed is None:
            continue

        eligible, elig_note, scores = parsed
        row = {"slug": p["slug"], "doi": p["doi"],
               "journal": p["journal"], "title": p["title"],
               "eligible": eligible}
        for r in RUBRIC:
            row[r["id"]] = scores[r["id"]]["score"] if eligible == "Y" else ""
        scores_w.writerow(row)
        scores_f.flush()

        if elig_note:
            notes_w.writerow({
                "slug": p["slug"], "doi": p["doi"],
                "journal": p["journal"],
                "item_id": "_eligibility",
                "score": eligible,
                "note": elig_note,
            })
        if eligible == "Y":
            for r in RUBRIC:
                n = scores[r["id"]]["note"]
                if n:
                    notes_w.writerow({
                        "slug": p["slug"], "doi": p["doi"],
                        "journal": p["journal"],
                        "item_id": r["id"],
                        "score": scores[r["id"]]["score"],
                        "note": n,
                    })
        else:
            n_ineligible += 1
        notes_f.flush()
        # gentle pace on the API
        time.sleep(0.2)

    scores_f.close()
    notes_f.close()
    print(f"\nDone. Scores at {scores_path}, notes at {notes_path} "
          f"(ineligible: {n_ineligible})")


# ---------------------------------------------------------------------------
# summarise: aggregate + plot
# ---------------------------------------------------------------------------
def cmd_summarise(args: argparse.Namespace) -> None:
    scores_path = _here() / args.scores
    summary_path = _here() / args.summary
    journal_path = _here() / args.by_journal
    meta_path = _here() / args.meta
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    with scores_path.open(encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))

    if not all_rows:
        print("no scored papers yet")
        return

    # Handle both new (with `eligible` column) and old scoring runs.
    has_elig = "eligible" in all_rows[0]
    if has_elig:
        rows = [r for r in all_rows if r.get("eligible", "").upper() == "Y"]
        excluded = len(all_rows) - len(rows)
    else:
        rows = all_rows
        excluded = 0

    n = len(rows)
    if n == 0:
        print(f"no eligible papers ({excluded} excluded as ineligible)")
        return

    # Per-item: fraction of applicable eligible papers that report the item
    per_item: dict[str, dict[str, float]] = {}
    for r in RUBRIC:
        applicable = [row for row in rows if row[r["id"]] not in ("NA", "")]
        n_app = len(applicable)
        n_rep = sum(1 for row in applicable if row[r["id"]] == "Y")
        pct = 100.0 * n_rep / n_app if n_app else float("nan")
        per_item[r["id"]] = {
            "n_applicable": n_app,
            "n_reported": n_rep,
            "pct_reported": pct,
        }

    with summary_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["item_id", "n_applicable", "n_reported",
                    "pct_reported"])
        for r in RUBRIC:
            v = per_item[r["id"]]
            w.writerow([r["id"], v["n_applicable"], v["n_reported"],
                        f"{v['pct_reported']:.1f}"])

    # Per-paper coverage: fraction of applicable items reported.
    #
    # Keep each coverage value attached to the row it came from. A prior
    # version accumulated a bare list, sorted it for the median, and then
    # zipped the sorted list back against `rows` to group by journal --
    # which handed every paper some other paper's coverage and made the
    # per-journal table meaningless. Pairing them removes the chance of
    # that happening again, and also handles the case where a row has no
    # applicable items and so contributes no coverage value at all.
    paper_cov: list[tuple[dict, float]] = []
    for row in rows:
        applicable = [row[r["id"]] for r in RUBRIC
                      if row[r["id"]] not in ("NA", "")]
        if applicable:
            paper_cov.append((
                row,
                100.0 * sum(1 for v in applicable if v == "Y")
                / len(applicable),
            ))

    coverages = [c for _, c in paper_cov]
    median_cov = statistics.median(coverages) if coverages else float("nan")
    mean_cov = statistics.mean(coverages) if coverages else float("nan")

    # Per-journal median coverage
    with journal_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["journal", "n_papers", "median_coverage_pct"])
        by_j: dict[str, list[float]] = {}
        for row, cov in paper_cov:
            by_j.setdefault(row["journal"], []).append(cov)
        for j, vs in sorted(by_j.items()):
            w.writerow([j, len(vs), f"{statistics.median(vs):.1f}"])

    # Meta file (for R plotting to pick up)
    with meta_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["key", "value"])
        w.writerow(["n_eligible", n])
        w.writerow(["n_excluded", excluded])
        w.writerow(["median_coverage_pct", f"{median_cov:.2f}"])
        w.writerow(["mean_coverage_pct", f"{mean_cov:.2f}"])

    print(f"\n== INSTAR baseline ==")
    print(f"papers eligible: {n}  (excluded: {excluded})")
    print(f"median paper coverage: {median_cov:.1f}%")
    print(f"mean   paper coverage: {mean_cov:.1f}%")
    print(f"per-item summary:  {summary_path}")
    print(f"per-journal:       {journal_path}")
    print(f"meta:              {meta_path}")
    print(f"\nRender the figure with:")
    print(f"  Rscript {_here() / 'code' / 'plot_figure_2.R'}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    subs = p.add_subparsers(dest="cmd", required=True)

    pf = subs.add_parser("fetch", help="OpenAlex → papers.csv")
    pf.add_argument("--year", type=int, default=2025)
    pf.add_argument("--per-journal", type=int, default=10)
    pf.add_argument("--include-paywalled", action="store_true",
                    help="include non-OA papers (default: OA-only)")
    pf.add_argument("--out", default="results/papers.csv")
    pf.add_argument("--dry-run", action="store_true")
    pf.set_defaults(func=cmd_fetch)

    pt = subs.add_parser("texts", help="Fetch/extract methods sections")
    pt.add_argument("--papers", default="results/papers.csv")
    pt.add_argument("--texts-dir", default="texts")
    pt.add_argument("--pdfs-dir", default="pdfs")
    pt.add_argument("--unpaywall-email", default="")
    pt.add_argument("--force", action="store_true",
                    help="re-extract even if the text file already exists")
    pt.set_defaults(func=cmd_texts)

    ps = subs.add_parser("score", help="Claude scoring → scores.csv")
    ps.add_argument("--papers", default="results/papers.csv")
    ps.add_argument("--texts-dir", default="texts")
    ps.add_argument("--scores", default="results/scores.csv")
    ps.add_argument("--notes", default="results/scores_notes.csv")
    ps.add_argument("--model", default=DEFAULT_MODEL)
    ps.add_argument("--dry-run", action="store_true",
                    help="print token estimate; make no API calls")
    ps.add_argument("--force", action="store_true",
                    help="re-score papers already present in scores.csv")
    ps.set_defaults(func=cmd_score)

    pu = subs.add_parser("summarise", help="Aggregate + plot Figure 2")
    pu.add_argument("--scores", default="results/scores.csv")
    pu.add_argument("--summary", default="results/summary.csv")
    pu.add_argument("--by-journal", default="results/summary_by_journal.csv")
    pu.add_argument("--meta", default="results/summary_meta.csv")
    pu.set_defaults(func=cmd_summarise)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
