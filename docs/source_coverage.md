# Source coverage and access notes

Reviewed 2026-11-02. Claims below distinguish rating history from downloadable PDF availability. No complete archive was collected.

| Source | Official entry point | Coverage and collection status |
|---|---|---|
| OCC | https://www.occ.gov/publications-and-resources/tools/index-cra-search.html | States PDFs from April 1996 onward; search offers CSV export. Collector currently uses official monthly HTML listings, which supply identifiers, location, examination date, rating, and PDF links. CSV download integration is not implemented. |
| FDIC | https://crapes.fdic.gov/ | Search application describes current/past ratings since July 1990. FDIC's explanatory page says some evaluations since that date are online, not all historical PDFs. Public search API provides JSON histories and PDF file references, but the retrieved response exposes publication date rather than examination date. |
| Federal Reserve | https://www.federalreserve.gov/apps/CRAPubWeb/CRA/BankRating | Search has examination-year and public-year filters. Earliest available PDF date and complete coverage not yet verified. Adapter not implemented in this four-document stage. |
| OTS | https://www.ffiec.gov/craratings/ | Historical rating records exist; OTS no longer active after 2011. Complete historical PDF hosting and coverage remain unresolved. No OTS adapter implemented. |
| FFIEC | https://www.ffiec.gov/craratings/Rtg_spec.html | Bulk-file specification states examination ratings since July 1990 across all four regulators. This is not a claim that PDFs accompany each record. Direct bulk-page access returned 403 in this environment; no bypass attempted. Automatic date linkage not implemented. |

FDIC coverage explanation: https://www.fdic.gov/banker-resource-center/what-performance-evaluation

## Access review

- OCC policies: https://www.occ.gov/about/policies/index-policies.html. Reviewed policy index; no CRA-specific automation rate stated there. This is not blanket authorization for unrestricted archive collection.
- FDIC policies: https://www.fdic.gov/policies. General disclaimer notes information accuracy limitations and restrictions applicable to external copyrighted material. No CRAPES-specific bulk request rate identified.
- https://www.occ.gov/robots.txt returns text with agent-specific exclusions, not a blanket CRA prohibition for this collector. Runtime parses applicable rules.
- https://crapes.fdic.gov/robots.txt returns HTTP 200 application HTML, not valid robots directives. This behavior was explicitly reviewed; saved as HTML and treated as no machine-readable robots rule, not as explicit permission.
- https://www.fdic.gov/robots.txt supplies Crawl-delay: 1. The collector's two-second minimum is slower.
- Only `www.occ.gov`, `occ.gov`, `crapes.fdic.gov`, and `www.fdic.gov` are allowed. New PDF hosts require source review and configuration changes.
- FRB and FFIEC robots were not successfully retrieved through the earlier web-tool checks. They are not enabled collector hosts. OTS hosting remains unverified.

Saved search responses and robots checks are under `data/source_snapshots/`. Policy index/disclaimer snapshots are `occ_policies.html` and `fdic_policies.html` there. Review policies and host rules again before expanding collection.

## Current limitations

The four-document manifest contains two researched OCC monthly-listing URLs. Removing those uses target-year monthly-listing discovery, which can miss evaluations released in a later year. A negative search result never establishes that a document does not exist.

FDIC candidates with missing examination dates remain unresolved even if a plausible year appears inside their PDF filename. Farmers Savings Bank also has multiple institution identities. These are explicit review issues, not permission to guess.
