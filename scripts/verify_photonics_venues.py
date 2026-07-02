"""Verify the exact Semantic Scholar `venue` strings for the photonics
publisher presets, and emit a ready-to-paste registry block.

Why this exists
---------------
The `venue` filter in this server is an exact-string OR filter, encoded as a
comma-joined list (`core/requests.py`: `params["venue"] = ",".join(self.venue)`).
Two consequences:

1. S2's venue strings are inconsistent in casing/form (a live response has
   shown "Optics express" lowercase), so preset strings must be *observed*,
   not guessed.
2. Any venue string that itself contains a comma (e.g. the MEDLINE-style
   "Journal of the Optical Society of America. A, Optics, image science, and
   vision") is INEXPRESSIBLE in this filter — the comma would be read as an OR
   separator. Those are flagged as UNFILTERABLE.

This script is run manually (network required, no API key needed but a key
raises rate limits). It does not write any files — it prints:
  * per-candidate PASS / FAIL / UNFILTERABLE(comma) diagnostics, and
  * a `PHOTONICS_SOURCES` venues block + `KNOWN_UNFILTERABLE` block you paste
    into `semantic_scholar/api/photonics.py`.

Usage:
    cd ~/projects/semantic-scholar-mcp-merged
    uv run python scripts/verify_photonics_venues.py
"""

import asyncio
import sys
from pathlib import Path

# Allow running as a plain script (`python scripts/...`) as well as via uv.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from semantic_scholar.utils.http import cleanup_client, make_request  # noqa: E402

# Rate limit: unauthenticated S2 allows ~1 req / sec for search endpoints.
_SLEEP_SECONDS = 1.1

# Anchor DOIs: one well-known, guaranteed-in-index paper per journal, used to
# read back the exact `venue` string S2 stores. NOTE: S2 sometimes stores an
# empty `venue` on an individual paper even when the venue filter works, so the
# authoritative signal is the round-trip filter test below, not this lookup.
ANCHORS: dict[str, list[tuple[str, str]]] = {
    "optica": [
        ("Optics Express", "10.1364/OE.26.014487"),
        ("Optics Letters", "10.1364/OL.43.006106"),
        ("Optica", "10.1364/OPTICA.5.001181"),
        ("Applied Optics", "10.1364/AO.57.000B209"),
        ("Photonics Research", "10.1364/PRJ.7.000823"),
    ],
    "spie": [
        ("Advanced Photonics", "10.1117/1.AP.1.4.046005"),
        ("Optical Engineering", "10.1117/1.OE.57.6.060501"),
        ("Proc. SPIE (conf paper)", "10.1117/12.2642249"),
    ],
    "nature_lsa": [
        ("Light: Science & Applications", "10.1038/s41377-018-0060-7"),
    ],
    "nature_photonics": [
        ("Nature Photonics", "10.1038/s41566-018-0246-9"),
    ],
}

# Candidate venue strings to probe directly with the round-trip filter. This is
# the authoritative check: individual-paper `venue` fields are often empty, but
# the filter still resolves the string. Strings are our best guess at S2's exact
# form; the round-trip prints the observed `venue` on returned hits so we can
# confirm the exact casing. SPIE is indexed PER-CONFERENCE, so no single
# umbrella string covers it — we list the major optics/photonics conferences.
CANDIDATE_VENUES: dict[str, list[str]] = {
    "optica": [
        "Optics Express",
        "Optics Letters",
        "Optica",
        "Applied Optics",
        "Photonics Research",
        "Optics Continuum",
        "Biomedical Optics Express",
        "Optical Materials Express",
        "Advances in Optics and Photonics",
        "Journal of the Optical Society of America A",
        "Journal of the Optical Society of America B",
    ],
    "spie": [
        "Advanced Photonics",
        "Advanced Photonics Nexus",
        "Optical Engineering",
        "Neurophotonics",
        "Journal of Biomedical Optics",
        "SPIE/COS Photonics Asia",
        "Defense + Commercial Sensing",
        "Optical Engineering + Applications",
        "Photonics West",
    ],
    "nature_lsa": [
        # S2 stores the venue as "Light: Science & Applications" (with '&'),
        # but the literal '&' breaks the query string. S2 normalizes "and" to
        # "&", so the "and"-spelled form is the working filter string.
        "Light: Science and Applications",
    ],
    "nature_photonics": [
        "Nature Photonics",
    ],
}


async def _get_venue_info(doi: str) -> dict:
    """Fetch venue / publicationVenue / journal for a DOI-identified paper."""
    resp = await make_request(
        f"/paper/DOI:{doi}",
        params={"fields": "title,venue,publicationVenue,journal"},
    )
    return resp if isinstance(resp, dict) else {}


async def _venue_has_hits(venue_string: str) -> tuple[bool, int, set[str]]:
    """Round-trip: does filtering by this exact venue string return papers?
    Also returns the distinct `venue` strings observed on the returned hits so
    we can confirm the exact casing S2 uses."""
    resp = await make_request(
        "/paper/search/bulk",
        params={
            "venue": venue_string,
            "fields": "venue",
            "publicationDateOrYear": "2015:",
        },
    )
    if not isinstance(resp, dict) or "error" in resp:
        return False, 0, set()
    total = resp.get("total", 0) or 0
    observed = {
        (p.get("venue") or "").strip()
        for p in (resp.get("data") or [])
        if isinstance(p, dict) and (p.get("venue") or "").strip()
    }
    return total > 0, total, observed


async def main() -> None:
    observed: dict[str, list[str]] = {k: [] for k in ANCHORS}
    unfilterable: dict[str, list[str]] = {}
    print("=" * 72)
    print("Anchor lookup — reading exact S2 venue strings")
    print("=" * 72)

    for source_key, anchors in ANCHORS.items():
        for label, doi in anchors:
            info = await _get_venue_info(doi)
            venue = (info.get("venue") or "").strip()
            pv = info.get("publicationVenue") or {}
            pv_id = pv.get("id")
            pv_name = pv.get("name")
            print(f"\n[{source_key}] {label}  (DOI:{doi})")
            print(f"    venue           = {venue!r}")
            print(f"    publicationVenue.name = {pv_name!r}")
            print(f"    publicationVenue.id   = {pv_id!r}  # stable id (future extension)")

            if not venue:
                print("    -> SKIP: no venue string returned")
            elif "," in venue:
                print("    -> UNFILTERABLE: contains a comma (comma rule)")
                unfilterable.setdefault(source_key, []).append(venue)
            elif venue not in observed[source_key]:
                observed[source_key].append(venue)
            await asyncio.sleep(_SLEEP_SECONDS)

    print("\n" + "=" * 72)
    print("Round-trip filter test — probe candidate venue strings directly")
    print("(authoritative: individual `venue` fields are often empty)")
    print("=" * 72)
    verified: dict[str, list[str]] = {k: [] for k in CANDIDATE_VENUES}
    for source_key, venues in CANDIDATE_VENUES.items():
        for venue in venues:
            if "," in venue:
                print(f"[{source_key}] UNFILTERABLE (comma)      {venue!r}")
                unfilterable.setdefault(source_key, []).append(venue)
                continue
            ok, total, seen = await _venue_has_hits(venue)
            status = "PASS" if ok else "FAIL(0 hits)"
            # Flag when the observed venue casing differs from our candidate.
            mismatch = ""
            if ok and seen and venue not in seen:
                mismatch = f"  ⚠ observed={sorted(seen)[:2]}"
            print(f"[{source_key}] {status:12} total={total:<8} {venue!r}{mismatch}")
            if ok:
                verified[source_key].append(venue)
            await asyncio.sleep(_SLEEP_SECONDS)

    print("\n" + "=" * 72)
    print("PASTE-READY BLOCK for semantic_scholar/api/photonics.py")
    print("=" * 72)
    print("# --- verified venues (generated by scripts/verify_photonics_venues.py) ---")
    for source_key, venues in verified.items():
        joined = ", ".join(f'"{v}"' for v in venues)
        print(f'# {source_key}: venues=({joined},)')
    print("\n# --- KNOWN_UNFILTERABLE (comma rule) ---")
    print(f"# {unfilterable!r}")
    print(
        "\nNOTE: add photonics journals not covered by an anchor manually, then "
        "re-run test/test_photonics_live.py to confirm they still filter."
    )

    await cleanup_client()


if __name__ == "__main__":
    asyncio.run(main())
