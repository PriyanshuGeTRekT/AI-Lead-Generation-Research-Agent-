# Startup India Lead-Gen & Enrichment — Working Playbook

> **Purpose of this file:** a complete, self-contained handoff. A fresh agent with
> **zero prior context** can read this top-to-bottom and continue the work with no
> loss of quality. It documents the business goal, the data source, the exact
> enrichment method that finally worked, what failed (so you don't repeat it),
> the code map, how to run/resume everything, and the recommended next steps.
>
> Last updated: 2026-06-18.

---

## 1. Business goal (why this exists)

- Company: **RazorInfotech**, selling an HRMS product (**HumanMaximizer**, humanmaximizer.com).
- We find **Indian B2B companies that do NOT already have an HRMS** and pitch them, **by phone** (phone is the primary outreach channel; numbers must be **accurate** and ideally of the **relevant person** — owner/founder/director/HR head).
- The old company tool closed only **0.05%** of deals. We're beating that by targeting better and giving sales accurate, named, reachable contacts.
- **Sweet spot:** not too big (already have HRMS), not too tiny (don't need one). Growing companies with a real team.

## 2. THE source that works: Startup India registry

`startupindia.gov.in` is a government registry of **454,591** companies (≈146k DPIIT-recognized). It's free and covers a huge, ICP-relevant pool of growing Indian companies. We scrape it, filter to our ICP slice, then enrich contacts.

### Reverse-engineered search API (how the harvest works)
- Endpoint: `POST https://api.startupindia.gov.in/sih/api/noauth/search/profiles`
- **Quirks (critical):**
  - `page` goes in the **BODY**, not the query string (query-string page is ignored → returns a fixed 9-record teaser).
  - **Page size is server-capped at 9.** The `size` param is ignored. So the full crawl is ~50,500 pages.
  - sort: `{"orders":[{"field":"registeredOn","direction":"DESC"}]}`
  - `dpiitRecogniseUser:true` filters to the ~146k DPIIT-recognized subset.
  - Body shape: `{"query":"","industries":[],"sectors":[],"states":[],"cities":[],"stages":[],"badges":[],"roles":["Startup"],"page":N,"sort":{...},"dpiitRecogniseUser":false,"internationalUser":false}`
- Each record returns: `id, name, state, city, industries[], sectors[], stages[], dippCertified, dippNumber, registeredOn`. **No website/phone/contact** — those come from enrichment (section 5).
- The public per-company **profile detail** page is login-gated → no extra public data there.

## 3. The target ICP slice (what we're working right now)

**Delhi-NCR × DPIIT-recognized × stage = "Scaling" = 862 companies.**

- "Delhi-NCR" = `state='Delhi'` OR city in `{gurugram, gurgaon, noida, greater noida, gautam buddha nagar, ghaziabad, faridabad}` (Delhi is its own state; NCR cities sit in Haryana/UP, so we match on city).
- DPIIT-recognized = `dpiit_certified=1`.
- Stage taxonomy (only 4 exist): **Prototype, Validation, EarlyTraction, Scaling.** Scaling = proven, growing, hiring → best HRMS prospects.
- Why this slice: DPIIT-recognized (real vetted company) + Scaling (has a team, feels HR pain, likely no HRMS yet) + in our operating region.

## 4. Database (where everything lives)

- SQLite file: **`data/warehouse.db`** (shared with the rest of the app; WAL mode).
- Table **`startups`** — one row per company. Key columns:
  - Identity/harvest: `sid` (PK = portal id), `name, state, city, industry, industries, sector, sectors, stage, dpiit_certified, dipp_number, registered_on, role, raw` (full JSON), `discovered_at`
  - Enrichment: `website, phone, dm_name, dm_role, email, linkedin, company_linkedin, cin, reg_address, reg_email, incorporation, directors_json, contact_status, enriched_at`
  - `contact_status` values: `pending` (not enriched), `enriched` (deep pass), `registry` (registry/CIN), `agent_verified` (workflow), `no_data`.
- Table **`startup_harvest`** — resume tracking: `filter_key, last_page, total, updated_at`.

## 5. Enrichment methods — what works, what doesn't (THE core knowledge)

These companies are mostly **brand-new (2024-2025) micro-startups**, so third-party
coverage is thin and uneven. We use multiple sources and **gate every field for
accuracy** (never bank a wrong-company phone). Tooling = **Apify** (apify.com) with
the user's own credits. Token cost ≈ 0 for the Apify paths (it's Apify API + Python).

### ✅ WORKS — Apify "deep" pass (the workhorse): Google → own website → phone + LinkedIn + CIN
- Actor: **`apify~google-search-scraper`** (search `"{name} {city}"`).
- From the organic results we extract, **with an accuracy gate**:
  - **website** = first organic result whose **domain token-matches the company name** (`_domain_matches`). Skips directories (justdial, tracxn, zauba, indiafilings, ynos, cleartax, internshala, …). If no match → leave blank (accurate > complete).
  - **phone** = scraped from that website's home/contact/about page (`_site_phone`, tel: links first, Indian `[6-9]\d{9}` format). Accurate (company's own published number).
  - **linkedin** = a `linkedin.com/in/...` (personal) or `/company/...` URL from results.
  - **cin** = MCA Corporate Identification Number, regex `[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}`, found embedded in directory result URLs (even 2025 companies appear in directories by CIN).
- **Measured yield (per 50):** website ~66%, phone ~44%, LinkedIn ~66%. **Cost ≈ $0.004/company.**

### ✅ WORKS — Registry **by CIN** (token-free director + email): foxlabs Tofler/MCA
- Actor: **`foxlabs~indian-company-data`**. Input `{"cins":[...]}` (NOT names — see below).
- Returns: **directors** (name + designation + DIN), **registered email**, registered address, incorporation date, CIN, status. Pick the most senior director (`_pick_director`: Managing Director > longest-tenure Director).
- **CIN lookup is EXACT** → works even for brand-new 2025 companies. **Cost ≈ $0.002/result.**
- The CINs come from the deep pass (step above). This is the **token-smart way to get the "relevant person" (a director) for ~80%+** of the slice.

### ✅ WORKS (high quality, but EXPENSIVE in tokens) — multi-agent research + verify workflow
- File: **`startup_contact_workflow.js`** (run via the Workflow tool).
- 2-stage per batch of 8: a **research agent** finds CIN/director/website/phone/LinkedIn/email from real pages (cites source URLs, returns null rather than guess), then an **adversarial verify agent** independently re-checks and nulls anything unconfirmed.
- **Measured yield (50 leads):** director **82%**, CIN **84%**, website 42%, phone 26%, LinkedIn 32%, email 26%. All source-verified/accurate.
- **Cost: ~700k Claude tokens for 50 (~14k/lead).** Use it only for the hard residual or accuracy spot-checks — NOT as the default (the Apify deep + registry-by-CIN combo gets most of the same data for ~zero tokens).

### ⚠️ PARTIAL — Google Maps (`lukaskrivka~google-maps-with-contact-details`)
- Gives a verified phone where the company has a Maps listing, BUT **fuzzy-matches** (returned "Eurus" for "Quantorus"). Must gate by name-similarity. ~24% phone coverage. Deprioritized in favor of the deep pass.

### ⚠️ PARTIAL — Apollo (`microworlds~leads-finder`)
- Great for established companies (returns person + title + personal LinkedIn + email by `company_domains`), but **thin coverage of tiny new startups** ("No results found"). Needs a domain. Input gotcha: `email_status` only accepts `"verified"`.

### ❌ DOESN'T WORK — Registry **by name** (foxlabs with `companyNames`)
- ~90% fail with **"Could not resolve company name to a CIN"** — Tofler/Zauba **lag MCA by months** and don't have most brand-new 2025 companies indexed by name yet. **Always look up by CIN, not by name.**

### ❌ Free-only sources (don't bother re-testing)
- MCA `data.gov.in` API = registry-only (no contacts) + network-blocked in the dev sandbox.
- Apollo/Crustdata/PDL free tiers = no decision-maker direct dials.
- Email→name derivation from registered emails = low yield (most are generic gmail).
- The startupindia profile detail endpoint = login-gated.

### Honest ceiling (set expectations)
For brand-new micro-startups, an accurate **phone** for 100% does **not exist publicly** anywhere — do NOT fabricate. Realistic accurate coverage: **director + email ~80%** (registry-by-CIN), **website ~66%, phone ~45%, LinkedIn ~60%** (deep pass). For phone-less ones, the contact path is director name + email + LinkedIn.

## 6. Current state (as of 2026-06-18)

- **Harvested: 219,004** companies into `startups`. **Resume point: page 24,383 of ~454,591** (harvest is paused; resumable — see §9).
- **862-slice enrichment coverage so far:** phone **108**, named decision-maker **48**, LinkedIn **65**, website **178**, CIN **45**, email **22**.
- `contact_status` in slice: agent_verified 50, enriched 19, no_data 29, pending 764. (Only ~98 of 862 have had a full enrichment pass; the rest are pending.)
- **First real lead obtained** from the 108-phone sheet → method validated.

### Deliverables produced
- `data/StartupIndia_DelhiNCR_DPIIT_Scaling_PHONES.xlsx` — the **108 leads with a phone** (most-complete first; Company/City/Industry/Phone/Decision-maker/Role/LinkedIn/Email/Website/CIN + sales fill-in columns + Summary). Built by `_build_startup_phonesheet.py`.
- `data/Delhi_NCR_IT_BPO_Consulting_CallSheet.xlsx` — earlier, separate campaign (different segment; not this slice).

## 7. Code map

| File | What it does |
|---|---|
| `core/startup_india.py` | Harvest (reverse-engineered API, resumable) + the `startups`/`startup_harvest` tables + `query()/counts()/filter_options()/export_rows()`. Has the `_NCR_CITIES` list and `_where()` (filters: ncr, dpiit, stage, state, industry, q). `harvest()`, `stop()`, `status()`. |
| `core/startup_enrich.py` | All enrichment. Key fns: `enrich()` (Maps→Apollo→site-LLM), `enrich_registry()` (foxlabs by NAME — low yield, avoid), **`enrich_deep()`** (Google→site→phone/LinkedIn/CIN, the workhorse), **`enrich_registry_by_cin()`** (foxlabs by CIN — director/email). Helpers: `_run_actor()` (Apify async run+poll+cost), `_domain_matches()`, `_site_phone()`, `_parse_google()` (extracts website/linkedin/cin), `_pick_director()`. |
| `api/main.py` | Endpoints (see §8). Search for `/startups`. |
| `frontend/src/components/startups/StartupIndia.tsx` | The "Startup India" portal tab: harvest control, filters (Delhi-NCR/DPIIT/stage chips + 🎯 preset), table (Phone/Decision-maker/LinkedIn cols), ✨ Enrich button, CSV export. |
| `frontend/src/App.tsx` | Registers the 3rd portal `'startups'`. |
| `frontend/src/api/client.ts` | `startups*` API methods + `StartupRow` type. |
| `frontend/vite.config.ts` | Dev proxy — `/startups` (and `/signals /segment /enrich /verify`) added to the proxied list. |
| `startup_contact_workflow.js` | The agent research+verify workflow (Workflow tool). Currently scoped to first 50 of `data/_si862.json`; regenerate to change scope. |
| `_build_startup_phonesheet.py` | Builds the phone Excel from the DB. |
| `data/_si862.json` | Snapshot of the 862 slice (used as workflow input). |

## 8. API endpoints (all behind `_require_admin`, base `http://localhost:8000`)

- `POST /startups/harvest?dpiit=&states=&industries=&max_pages=&restart=` + `GET /startups/harvest/status` + `POST /startups/harvest/stop`
- `GET /startups?ncr=&dpiit=&stage=&state=&industry=&q=&limit=&offset=&has_contact=&sort=&direction=` (list)
- `GET /startups/counts`, `GET /startups/options`, `GET /startups/export?...` (CSV)
- `POST /startups/enrich?ncr=&dpiit=&stage=&limit=` + `GET /startups/enrich/status` (Maps→Apollo→site-LLM)
- `POST /startups/enrich/registry?...` + `GET /startups/enrich/registry/status` (foxlabs by NAME — low yield)
- `POST /startups/enrich/deep?ncr=&dpiit=&stage=&limit=` + `GET /startups/enrich/deep/status` (Google→site→phone/LinkedIn/CIN — **the main one**)
- **NOT YET WIRED:** `enrich_registry_by_cin()` exists in `core/startup_enrich.py` but has **no endpoint yet** — add a `POST /startups/enrich/registry-cin` that calls it (mirror the registry endpoint). It reuses `_reg_state` / `reg_enrich_status()`.

## 9. How to run / resume (do this first in a new session)

1. **Keys:** the Apify token is stored in `data/runtime_config.json` as `apify_api_token` (gitignored; already set). NVIDIA NIM keys (for the site-LLM) are also there. Don't hardcode secrets.
2. **Backend:** `python -m uvicorn api.main:app --host 127.0.0.1 --port 8000` (run with the sandbox disabled so it can reach Apify/Google/sites). After editing `core/startup_enrich.py` you MUST restart for changes to load.
3. **Frontend:** `cd frontend && npm run dev` → http://localhost:5173 → "Startup India" tab. Proxies to :8000.
4. **Resume the harvest** (to grow past 219k): `POST /startups/harvest` (no restart param) → continues from page 24,383. Or click "Start / Resume harvest" in the UI.
5. **Enrich the slice (token-smart, recommended):**
   - `POST /startups/enrich/deep?ncr=true&dpiit=true&stage=Scaling&limit=2000` → fills website/phone/LinkedIn/CIN for all pending. Poll `/startups/enrich/deep/status`.
   - Then run registry-by-CIN (wire the endpoint first, §8) → fills director/email from the CINs.
   - Then rebuild the Excel: `python _build_startup_phonesheet.py`.
6. **Status of any pass:** the `/status` endpoints return `{running, done, total, with_*, cost_usd}`.

### Environment gotchas (Windows dev box)
- External network (Apify, Google, company sites) needs the Bash tool's **`dangerouslyDisableSandbox: true`**, and the backend must be started the same way.
- **`/tmp` differs between Git Bash and Windows Python** — write temp files to the project dir or pass explicit paths.
- Apify actors run **async**: `POST /v2/acts/{actor}/runs?token=` → poll `GET /v2/actor-runs/{runId}` until `SUCCEEDED` → `GET /v2/datasets/{datasetId}/items?clean=true`. `run.usageTotalUsd` = cost. (`_run_actor()` already does this.)
- SQLite is one shared connection across threads → **all DB reads/writes go through `warehouse._LOCK`** (a missed read-lock caused intermittent `NoneType` 500s — already fixed; keep new queries locked).

## 10. Recommended next steps (token-smart path to scale 108 → all 862)

1. **Wire the `/startups/enrich/registry-cin` endpoint** (calls `enrich_registry_by_cin`).
2. **Restart backend** (loads the new CIN-capture in `enrich_deep` + the new endpoint).
3. Run **`enrich_deep` on all 862** (`limit=2000`) → website/phone/LinkedIn/**CIN**. (~$3-4 Apify, ~0 tokens, ~1-2h, rate-limited.)
4. Run **`enrich_registry_by_cin` on all 862** → director + registered email for every CIN found (~80% of the slice). (~$1-2 Apify, ~0 tokens.)
5. Optionally run the **agent workflow** only on the residual that still lacks a director (token cost ~14k/lead — get user OK first).
6. Rebuild the Excel (`_build_startup_phonesheet.py`) — or generalize it to export "any contact" not just phone.
7. Then: feed the best leads into the CRM / signal-scoring, and start calling.

## 11. One-line summary of the winning method

> Scrape Startup India (registry, free) → filter to the ICP slice → **Apify Google
> search → company's own website (gated for accuracy) for phone + LinkedIn + CIN**,
> then **Apify foxlabs registry lookup BY CIN** for the director + registered email.
> Mostly token-free, accurate, and works even on brand-new companies. The expensive
> multi-agent workflow is a quality booster for the hard tail only.

---

## 12. Where this fits in the bigger app (don't get lost)

This Startup-India work is **one feature inside a much larger existing app** (an AI lead-gen platform). A fresh agent should know:
- The app has **3 frontend portals**: **CRM · Sales**, **Startup India** (this work), **Lead Gen & Training**. Router in `frontend/src/App.tsx` (hash routes `#/crm`, `#/startups`, `#/leadgen`).
- There is a separate **906k-lead main warehouse** (the `leads` table in the same `data/warehouse.db`) with its own CRM, signal-scoring (`core/signals.py`), and enrichment. **The `startups` table is intentionally ISOLATED from `leads`** ("just for this"). Don't mix them unless asked.
- **Cross-session memory** (auto-loaded each session) lives at `C:\Users\Admin\.claude\projects\C--Users-Admin-Documents-AI-lead-generation\memory\` — index is `MEMORY.md`. The most relevant entries: `startup-india-source.md` (this), `lead-warehouse.md`, `signal-scoring-hotlist.md`, `data-accuracy-and-providers.md`. These give the full app history.
- Today is referenced as 2026; companies "incorporated 2025" = brand new (~months old) — that's why third-party data is thin.

## 13. Apify account & budget (so you don't overspend)

- Account: **`Razor_infotech`**, plan **FREE**, spend cap **`maxMonthlyUsageUsd` = $105/mo**. ~\$0.25 used before this effort; this effort added ~\$1-2 (pilots).
- Token is the user's own, stored in `data/runtime_config.json` → `apify_api_token` (gitignored — never paste it into committed files or chat).
- **Check remaining budget:** `GET https://api.apify.com/v2/users/me/limits?token=$T` → compare `current.monthlyUsageUsd` vs `limits.maxMonthlyUsageUsd`. `GET .../users/me?token=$T` for account.
- **Full-slice cost estimate (862):** deep pass ~$0.004×862 ≈ **$3.4** + registry-by-CIN ~$0.002×~700 ≈ **$1.4** ≈ **~$5 total, ~0 Claude tokens.** Agent workflow for all 862 ≈ **~12M tokens — avoid** unless explicitly approved.

## 14. Apify actor cookbook (exact working inputs + gotchas)

All runs are async: `POST /v2/acts/{actor}/runs?token=$T` (body = input JSON) → poll `GET /v2/actor-runs/{id}?token=$T` until `SUCCEEDED` → `GET /v2/datasets/{datasetId}/items?token=$T&clean=true`. `run.usageTotalUsd` = cost. (`core/startup_enrich.py::_run_actor` does all this.)

1. **`apify~google-search-scraper`** — website/LinkedIn/CIN discovery.
   - Input: `{"queries":"NAME1 CITY1\nNAME2 CITY2","resultsPerPage":5,"maxPagesPerQuery":1,"countryCode":"in"}` (queries = newline-separated string).
   - Output: list of pages; each has `searchQuery.term` (map back by this) + `organicResults[].url/title/snippet`. CIN is embedded in directory URLs.
2. **`foxlabs~indian-company-data`** — directors + email (Tofler/MCA).
   - Input (USE THIS): `{"cins":["U74900DL2025PTC448306", "AAM-4134"], "maxResults":N, "maxConcurrency":8}` — by CIN (also accepts LLPIN for LLPs). EXACT, reliable.
   - DON'T use `{"companyNames":[...]}` → ~90% "Could not resolve company name to a CIN" for new companies.
   - Output: `name, cin, email, directors[{name,designation,din,tenure}], registeredAddress, incorporationDate, status`.
3. **`lukaskrivka~google-maps-with-contact-details`** — Maps phone (fuzzy; deprioritized).
   - Input: `{"searchStringsArray":["NAME CITY"],"maxCrawledPlacesPerSearch":1,"language":"en","scrapePlaceDetailPage":true}`.
   - Gotcha: `scrapeSocialMediaProfiles` must be an **object** not bool; results fuzzy-match → gate by name similarity.
4. **`microworlds~leads-finder`** (Apollo) — person+LinkedIn for established cos only.
   - Input: `{"company_domains":["x.com"],"contact_job_titles":["founder","ceo",...],"max_result":N}`.
   - Gotcha: `email_status` only accepts `"verified"`; needs a domain; thin for tiny cos.
   - Output: `first_name,last_name,title,linkedin_url,email,organization_primary_domain,organization_linkedin_url`.

## 15. 60-second smoke test (validate env + token + the whole chain before scaling)

Run with the sandbox disabled. Confirms Apify token + Google→CIN→registry-by-CIN works:
```python
import json, urllib.request, re
T="<apify_api_token from data/runtime_config.json>"
def run(actor, inp):
    u=f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items?token={T}"
    return json.loads(urllib.request.urlopen(urllib.request.Request(u, json.dumps(inp).encode(), {"Content-Type":"application/json"}), timeout=280).read())
g=run("apify~google-search-scraper", {"queries":"QUANTORUS PRIVATE LIMITED South Delhi","resultsPerPage":6,"maxPagesPerQuery":1,"countryCode":"in"})
cin=re.search(r"[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}", json.dumps(g)).group(0)
print("CIN:", cin)
print(run("foxlabs~indian-company-data", {"cins":[cin],"maxResults":1,"maxConcurrency":1})[0]["directors"])
# expect → CIN: U74900DL2025PTC448306 ; directors include "Saurabh Mani Tiwari"
```

## 16. Changing/scaling the slice

- Current harvested pool: **219,004** of 454,591 (resume page 24,383 to grow it). Of the 219k: `dpiit_certified` ≈ **58,600**; stages ≈ Prototype 84k / Validation 65k / EarlyTraction 44k / **Scaling 23k**.
- The slice is just a filter (`core/startup_india.py::_where`, or API params `ncr/dpiit/stage/state/industry/q`). To broaden the funnel:
  - Add **EarlyTraction** (next-best HRMS prospects) → bigger list.
  - Other regions (drop `ncr`, set `state=`), or industries (`industry=`, e.g. IT Services / BPO).
- Same enrichment pipeline applies to any slice. Mind the Apify budget (§13) for larger slices.

## 17. Data-quality rules (keep it accurate — the user's #1 requirement)

- **Never fabricate** a phone/name/URL. Missing > wrong.
- **Phone** only from the company's OWN website (domain token-matches name) or a verified listing — never a directory page (those numbers are wrong).
- **Director** = from MCA/Tofler/Zauba by CIN, or the company's own About/Team page. Reject company-name-as-person (e.g. "Compatible Concepts" as a person) and validate via `core/contact_finder.valid_person`.
- **LLPs** have an LLPIN (e.g. `AAM-4134`), not a CIN — the CIN regex won't catch it; `foxlabs` still resolves LLPINs if found on the directory page.
- All DB access goes through `warehouse._LOCK` (single shared SQLite connection).
- Enrichment fields are filled **only when empty** (`CASE WHEN ... THEN ? ELSE col END`) so re-runs are idempotent and never overwrite better data.
