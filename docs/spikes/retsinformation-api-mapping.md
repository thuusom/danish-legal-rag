# Spike: retsinformation-api.dk schema mapping (Issue #19)

Time-boxed investigation to validate that
[retsinformation-api.dk](https://retsinformation-api.dk/) returns a JSON
shape that maps cleanly onto our `shared/models.py` `LegalChunk` and the
`Provision`-shaped objects in `ingest/data/*.json`.

Sample fetched **2026-04-27** for Afskrivningsloven (LBK nr 1147 af
29/08/2016):

| Endpoint | Saved as |
|---|---|
| `GET /v1/lovgivning/2016/1147` | `retsinformation-api-sample.json` |
| `GET /v1/lovgivning/2016/1147/versions/latest` | `retsinformation-api-versions-latest.json` |
| `GET /v1/openapi.json` | `retsinformation-api-openapi.json` |

All three returned HTTP 200. No auth required. We used 3 of the
documented 20 req/hour budget.

## Their schema (top-level)

A `GET /v1/lovgivning/{year}/{number}` response has these top-level fields
(taken directly from the AFL sample):

| Field | Type | Example | Notes |
|---|---|---|---|
| `id` | uuid string | `8ddd7dfa-…` | Identifies this *version document* in their store |
| `law_id` | uuid string | `7f6afaff-…` | Identifies the *law* (stable across versions) |
| `version_number` | int | `1` | The base endpoint returns version 1; `versions/latest` returned 24 |
| `effective_date` | ISO date | `2016-09-06` | Date this version took effect |
| `amendment_id` | uuid \| null | `null` on v1, set on later versions | Links to the amendment that produced this version |
| `created_at` | ISO datetime | `2026-04-15T08:06:55…` | When *they* indexed it; not legally meaningful |
| `year`, `number` | int | `2016`, `1147` | Standard Danish lovbekendtgørelse identifier |
| `eli_uri` | string \| null | `/eli/lta/2016/1147` | Present on the base endpoint, **null on `versions/latest`** |
| `title` | string | `Bekendtgørelse af lov om skattemæssige afskrivninger (afskrivningsloven)` | Full official title |
| `short_name` | string | `LBK nr 1147 af 29/08/2016` | Matches our existing `law_number` field exactly |
| `popular_title` | string | `Afskrivningsloven` | Matches our `law_name` |
| `ressort`, `ministry` | string \| null | `null`, `Skatteministeriet` | Issuing ministry |
| `document_type`, `document_type_id` | string, int | `LBKH`, `30` | LBK = lovbekendtgørelse |
| `document_id`, `accession_number` | int, string | `183481`, `A20160114729` | Their internal identifiers |
| `historical`, `is_historical`, `is_consolidated` | bool | `true`, `true`, `false` | Currency flags |
| `signature_date`, `publication_date` | ISO date | `2016-08-29`, `2016-09-06` | `signature_date` matches our `effective_date` field |
| `structure` | object | (see below) | The body |
| `case_history` | array | `[]` on AFL | Related cases/amendments — empty for this law |
| `paragraph_count`, `chapter_count` | int \| null | `81`, `8` | **Only present on base endpoint, null on `versions/latest`** |

## Their paragraph structure

Inside `structure`:

```
structure
├── title          (string, mirrors top-level title)
├── preamble       (array of strings — opening "Herved bekendtgøres…")
├── chapters       (array)
│   └── { chapter_number: "Kapitel 1",
│         chapter_title: "Lovens anvendelsesområde",
│         afsnit: "",                        # higher-level part heading; empty in AFL
│         paragraph_groups: [
│           { id: "",                        # always empty in AFL
│             number: "",                    # always empty in AFL
│             heading: "Fælles bestemmelser",   # subsection heading inside a chapter; usually ""
│             paragraphs: [
│               { id: "id39cb96dc-…",        # stable XML anchor id
│                 number: "§ 2.",            # paragraph number, dot-suffixed
│                 stk: [
│                   { number: "Stk. 1.",
│                     text: "Maskiner, …",
│                     litra: [               # numbered list inside a stk
│                       { number: "1)", text: "leveret til en igangværende virksomhed," }
│                     ]
│                   }, …
│                 ]
│               }, …
│             ]
│           }, …
│         ]
│       }
├── signature      (object: location, date, royal_signature, minister)
├── appendices     (array — empty for AFL)
├── notes          (array — 2 entries for AFL)
├── tables         (array — empty for AFL)
├── images         (array — empty for AFL)
└── metadata       ({ format_type: "xml_lovh", has_chapters, has_appendices, has_tables, has_images })
```

Concrete observations from AFL (81 paragraphs across 8 chapters):

- **Every paragraph has at least one `stk`**, even single-stk ones. `0/81`
  paragraphs were missing a `stk` array. Single-stk paragraphs still get
  a `Stk. 1.` wrapper in the JSON, even though Danish convention would
  print such a paragraph without a "Stk. 1." prefix. We need to detect
  this and *not* emit `subsection: "stk. 1"` for those — otherwise we
  would diverge from the existing hand-curated AFL JSON, which writes
  `subsection: null` for single-stk paragraphs (e.g. § 1, § 17, § 19).
- **`53/81` paragraphs have multiple stk** — typical for AFL.
- **`8/81` paragraphs have litra entries** under at least one stk
  (e.g. § 3 stk. 1 with `1) leveret til en igangværende virksomhed,`,
  `2) bestemt til at indgå i virksomhedens drift og`, `3) færdiggjort…`).
  Litra map to our existing `item` field.
- **Letter-suffix paragraphs (§ 5 a, § 5 b, § 40 a, § 44 a, § 58 a)
  exist** and are represented as `"§ 5 a."` (lowercase letter, single
  space). Our existing AFL JSON uses uppercase (`"§ 5 B"`, `"§ 40 A"`) —
  case + space-vs-no-space normalisation is needed during mapping.
- **`paragraph_groups[].heading`** is occasionally used as an inline
  Danish subsection title within a chapter (e.g. *Fælles bestemmelser*,
  *Bygninger og installationer*). It is **not** a `kapitel`, but it IS
  semantically meaningful and should probably propagate to a chunk's
  context — most simply by appending it to `chapter` like
  `Kapitel 2 – Driftsmidler og skibe – Fælles bestemmelser` or by adding
  a new optional `paragraph_group_heading` field on `Provision`. Our
  existing AFL JSON ignores these headings; the schema neither has a
  field for them nor needs one if we keep parity.
- **`paragraph_groups[].id` and `.number`** are always empty in this
  sample. Probably populated for laws that use the `Afsnit` (Part) level
  above chapter; AFL doesn't.
- **No tables, no images, no appendices** in AFL. `metadata.has_tables`
  etc. correctly reports this. Other laws (e.g. Bogføringsbekendtgørelsen
  with its bilag) will populate these and we'll need a follow-up
  decision about whether to ingest them.

## Mapping table

`Provision` is the per-chunk record we already serialise in
`ingest/data/*.json` and pass to `LegalChunk`. The mapping below assumes
we flatten their `chapters → paragraph_groups → paragraphs → stk → litra`
tree into one `Provision` per `(paragraph, stk)` combination, with one
extra row per `litra` only when needed (the existing AFL JSON does NOT
break out litra into separate provisions — they stay inside the parent
stk's text. We should preserve that behaviour unless retrieval quality
demands finer chunks).

| Our field (`Provision` / `LegalChunk`) | Their field | Transform needed |
|---|---|---|
| `law_code` (e.g. `"AFL"`) | — | **Manual / from manifest.** Not derivable from the response. Comes from a config map keyed by `law_id` or `(year, number)`. |
| `law_name` | `popular_title` | Direct copy. Falls back to derived title if `popular_title` is null (other laws may not have one — we should check). |
| `law_title` | `title` (or `structure.title`) | Direct copy. Drop the parenthetical short form if we want it cleaner, but our existing JSON keeps it. |
| `law_number` | `short_name` | Direct copy. |
| `source_url` | derive from `eli_uri` | `f"https://www.retsinformation.dk{eli_uri}"`. **Note:** `eli_uri` is null on `versions/latest`, so for non-base versions we must construct it from `(year, number)`: `f"https://www.retsinformation.dk/eli/lta/{year}/{number}"`. |
| `effective_date` | `signature_date` (or `effective_date` on the version) | We currently store the signature date (`2016-08-29`); use `signature_date` to keep parity. Add `law_version_date = effective_date` for the new `Issue #22` field. |
| `chapter` | `chapters[].chapter_number + " – " + chapters[].chapter_title` | Concatenate to match existing format `"Kapitel 1 – Almindelige bestemmelser"`. Note: their AFL chapter 1 title is `"Lovens anvendelsesområde"`, NOT `"Almindelige bestemmelser"` as our hand-curated JSON has — so the live data will differ from our cache and that's fine (their version is canonical). |
| `section` | `paragraphs[].number` | Strip trailing `.`. Normalise letter suffix: `"§ 5 a." → "§ 5 a"`. Decide whether to upper-case (`"§ 5 A"`) for parity with current data — recommend **keep lowercase to match retsinformation.dk's HTML convention** and add a one-time migration of existing data. |
| `subsection` | `stk[].number` | Strip trailing `.`. Lowercase: `"Stk. 1." → "stk. 1"`. **Set to `null` if the paragraph has exactly one stk AND no litra**, to match the existing hand-curated convention. |
| `item` | `stk[].litra[].number` | Strip trailing `)`. Convention: `"1) → "nr. 1"`. Only populate when we choose to chunk-by-litra; otherwise inline into `text`. |
| `title` | — | **Not directly available.** The retsinformation API does not expose the per-stk Danish heading like `"Driftsmidler og skibe – saldoafskrivning"` that our hand-curated JSON uses. These were authored by us. Two options: (a) leave `title` null on live-fetched chunks; (b) auto-generate a short title from the first sentence. Recommend **(a) leave null** — embedding text falls back gracefully without it. |
| `text` | `stk[].text` (+ optional litra rendering) | Direct copy. If we keep litra inline, append `\n1) ...\n2) ...` after the stk text. |
| `id` | derived | Compute UUID5 from `(law_code, section, subsection)` exactly as today via `_compute_stable_id` (existing logic in ingest). |
| `citation_label` | derived | `f"{law_name} {section}" + (f", {subsection}" if subsection else "")`. Existing helper, no change. |
| `embedding_model`, `embedding_content_hash`, `ingested_at` | derived | Set during ingestion, unchanged. |

### New metadata fields proposed for Issue #22

Issue #22 should add these to `LegalChunk` (and the Qdrant payload), all
derivable from the API:

| New field | Source | Why |
|---|---|---|
| `law_version_date` (ISO date) | `effective_date` (top-level) | Distinguish chunks from different versions of the same law in the index. |
| `law_version_number` (int) | `version_number` | Cheap diagnostic when a re-ingestion brings in a newer version. |
| `eli` (string) | `eli_uri` or constructed | Stable canonical reference; useful in citations and de-duping. |
| `retsinformation_law_id` (uuid string) | `law_id` | Lets us query their API again for updates without keeping `(year, number)` hardcoded. |
| `retsinformation_paragraph_id` (string) | `paragraphs[].id` | Stable XML anchor — lets us cross-link to retsinformation.dk's HTML viewer at the §-level. |

`source_fetched_at` (= ingestion timestamp) is already covered by
`ingested_at`. No need for a separate field.

## Edge cases observed in AFL response

1. **`eli_uri` is null on `versions/latest`** but present on the base
   endpoint. The fetcher should call the base endpoint to get the ELI,
   or construct it deterministically from `(year, number)`.
2. **`paragraph_count` and `chapter_count` are null on `versions/latest`**
   but populated on the base endpoint (81, 8). Diagnostic only — not
   load-bearing.
3. **Single-stk paragraphs always carry a `Stk. 1.` wrapper.** Must be
   detected and elided, otherwise our `subsection` field will be
   over-populated relative to the existing data.
4. **Letter-suffix paragraphs are lowercase** (`§ 5 a.`) in their JSON
   but uppercase (`§ 5 B`) in our existing JSON. Need a normalisation
   decision plus a one-time migration if we want to keep parity. Doesn't
   block the spike.
5. **`paragraph_groups[].heading`** is used as an in-chapter sub-heading
   in 5 places in AFL. Our model has nowhere to put this. Either ignore,
   fold into `chapter`, or add a new `Provision.subheading` field.
   Recommend **ignore for v1** to keep the model unchanged.
6. **`afsnit` (Part) level** above chapter exists in the schema but is
   empty for AFL. Other laws may use it (e.g. Skatteforvaltningsloven).
   Need to test on a second law before going live.
7. **`case_history`** is empty on AFL but the field exists. Could be a
   source of cross-references for downstream features — out of scope
   here.
8. **`tables`, `images`, `appendices`** are empty in AFL. Other laws
   (Bogføringsbekendtgørelsen, Mindstekravsbekendtgørelsen) will have
   bilag. Out of scope for the live fetcher MVP — those laws stay on
   hand-curated JSON until a separate ticket.

## Open questions / risks

- **Sample size = 1 law.** Have not yet validated against
  Årsregnskabsloven, Skatteforvaltningsloven, Selskabsskatteloven, or
  any bekendtgørelse. The fetcher PR (#20) MUST validate against at
  least 3 distinct laws before flipping any default.
- **Versioning model.** The `versions/latest` endpoint returned
  `version_number: 24` for AFL with `effective_date: 2021-01-01`. This
  is the *currently in-force* text. The base `2016/1147` endpoint
  returned the original 2016 v1 text. We almost certainly want
  `versions/latest` for production retrieval, NOT the base endpoint —
  that means our existing AFL JSON (which is the 2016 base text) is
  already stale by 23 amendments. Worth flagging to Thomas.
- **Stability.** No SLA published. The host has been up during the
  spike. Add retries with backoff and a clear error path; do not let a
  retsinformation outage block ingestion of cached laws.
- **Rate limits.** 20/hour, 50/day, per IP. A full re-ingestion of all
  ~12 laws is well under budget, but we should serialise the fetcher
  and add a `time.sleep(3.0)` between calls to be a polite client.
- **`/markdown` endpoint exists.** Their OpenAPI lists
  `/v1/lovgivning/{year}/{number}/markdown`. If parsing the structured
  JSON ever breaks on a particular law, falling back to their markdown
  + our existing chunker is a viable plan B. Not needed today.

## Recommendation: **GO**

Their JSON maps cleanly onto our `Provision`/`LegalChunk` model with
purely mechanical transforms — string normalisation on §/stk numbers,
flatten the chapter→group→paragraph→stk tree, derive
`source_url`/`citation_label` the same way we do today. No new model
fields are required beyond the five proposed for Issue #22, all of
which are direct copies from their response.

Issue #20 should proceed with two non-trivial deviations from any
naïve plan: (1) **fetch `versions/latest`, not the base endpoint**, so
we get the in-force text rather than the original; supplement with a
single base-endpoint call to recover `eli_uri` and counts; (2) **drop
the synthetic `Stk. 1.` wrapper** for single-stk paragraphs to preserve
the existing convention that single-stk provisions have
`subsection = null`. A third nice-to-have is a small `(year, number) →
law_code` manifest committed to `ingest/` since `law_code` is not
derivable from the API.
