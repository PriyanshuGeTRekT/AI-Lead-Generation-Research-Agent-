"""
Derive a NAMED decision-maker (owner/founder/MD/director/HR-head) for the
Delhi-NCR IT/BPO/consulting campaign leads that have a website but no name yet,
by fetching their OWN site (about/team/contact) and reading it with the LLM pool.

FREE: requests + NVIDIA NIM pool. No Docker, no paid API. Their own site has no
anti-bot wall, and the LLM reliably extracts "Rahul Kumar Gupta, Proprietor".
"""
import json
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from agents import llm_pool
from core.contact_finder import valid_person

DB = "data/warehouse.db"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
# Pages most likely to name a person, in priority order.
SUBPAGES = ["", "about", "about-us", "aboutus", "team", "our-team", "leadership",
            "management", "contact", "contact-us", "company", "who-we-are"]
TAG_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.I | re.S)
HTML_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t\r\f\v]+")
NL_RE = re.compile(r"\n{3,}")

PROMPT = """You are reading the website text of an Indian small/medium company. \
Find the SINGLE most senior NAMED human (owner, founder, proprietor, partner, \
director, managing director, CEO, or HR head) explicitly named on the site.

Return ONLY a JSON object, nothing else:
{{"name": "<full name or null>", "role": "<their title or null>", "phone": "<a phone number on the page or null>"}}

Rules:
- name MUST be a real person's full name (2-3 words) that appears in the text. \
NEVER return the company name, a city, a product, or a generic word.
- If no individual person is named anywhere, return name = null.
- role = their designation if stated, else null.
- phone = a contact phone digits string if present, else null.

COMPANY: {company}
WEBSITE TEXT:
{text}
"""


def norm_url(w: str) -> str:
    w = (w or "").strip()
    if not w or w.endswith(".lead"):
        return ""
    if not w.startswith("http"):
        w = "https://" + w
    return w.rstrip("/")


def fetch_text(base: str) -> str:
    """Fetch homepage + a few key subpages, return concatenated visible text."""
    chunks, got = [], 0
    s = requests.Session()
    s.headers["User-Agent"] = UA
    for sub in SUBPAGES:
        if got >= 7000:
            break
        url = base if sub == "" else f"{base}/{sub}"
        try:
            r = s.get(url, timeout=8, allow_redirects=True)
            if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
                continue
            html = r.text
            txt = HTML_RE.sub(" ", TAG_RE.sub(" ", html))
            txt = WS_RE.sub(" ", txt)
            txt = NL_RE.sub("\n", txt).strip()
            if len(txt) > 60:
                tag = sub or "home"
                chunks.append(f"[{tag}] {txt[:2500]}")
                got += min(len(txt), 2500)
        except Exception:
            continue
    return "\n\n".join(chunks)[:7000]


def extract_json(s: str) -> dict:
    m = re.search(r"\{.*?\}", s, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


def process(row: dict) -> dict:
    base = norm_url(row["website"])
    out = {"domain": row["domain"], "company": row["company_name"], "name": None, "role": None, "phone": None}
    if not base:
        return out
    text = fetch_text(base)
    if len(text) < 80:
        out["note"] = "no_text"
        return out
    try:
        resp = llm_pool.complete(
            PROMPT.format(company=row["company_name"], text=text),
            tier="strong", temperature=0.0, max_tokens=200)
    except Exception as e:
        out["note"] = f"llm_err:{type(e).__name__}"
        return out
    data = extract_json(resp)
    name = (data.get("name") or "").strip() if isinstance(data.get("name"), str) else ""
    role = (data.get("role") or "").strip() if isinstance(data.get("role"), str) else ""
    phone = (data.get("phone") or "").strip() if isinstance(data.get("phone"), str) else ""
    if name and name.lower() not in ("null", "none") and valid_person(name):
        # reject if the "name" is just the company name echoed back
        cn = re.sub(r"[^a-z]", "", row["company_name"].lower())
        nn = re.sub(r"[^a-z]", "", name.lower())
        if nn and nn not in cn:
            out["name"] = name
            out["role"] = role[:60] if role and role.lower() not in ("null", "none") else None
    if phone and phone.lower() not in ("null", "none"):
        digits = re.sub(r"\D", "", phone)
        if 10 <= len(digits) <= 13:
            out["phone"] = phone
    return out


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    c = con.cursor()
    I = ("IT services", "BPO", "consulting")
    rows = [dict(r) for r in c.execute(
        f"""SELECT domain, company_name, website, phone, payload FROM leads
            WHERE state='Delhi NCR' AND industry IN ({','.join('?'*3)})
              AND phone!='' AND status NOT IN ('excluded','disqualified','raw')
              AND website LIKE 'http%' AND website NOT LIKE '%.lead'
              AND (dm_name IS NULL OR dm_name='')""", I).fetchall()]
    con.close()
    print(f"targets (website, no name yet): {len(rows)}", flush=True)

    found = 0
    done = 0
    results = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(process, r): r for r in rows}
        for fut in as_completed(futs):
            done += 1
            res = fut.result()
            results.append(res)
            if res.get("name"):
                found += 1
                print(f"  [{done}/{len(rows)}] ✓ {res['company'][:40]} → {res['name']} ({res.get('role') or '—'})", flush=True)
            if done % 20 == 0:
                print(f"  ...{done}/{len(rows)} processed, {found} named so far", flush=True)

    # write back
    con = sqlite3.connect(DB, timeout=30)
    c = con.cursor()
    now = time.time()
    wrote = 0
    for res in results:
        if not res.get("name"):
            continue
        c.execute("SELECT payload FROM leads WHERE domain=?", (res["domain"],))
        prow = c.fetchone()
        payload = {}
        if prow and prow[0]:
            try:
                payload = json.loads(prow[0])
            except Exception:
                payload = {}
        payload["dm_source"] = "own-site (LLM)"
        if res.get("role"):
            payload["dm_role"] = res["role"]
        if res.get("phone"):
            payload.setdefault("site_phone", res["phone"])
        c.execute(
            "UPDATE leads SET dm_name=?, contact_enriched_at=?, payload=? WHERE domain=?",
            (res["name"], now, json.dumps(payload), res["domain"]))
        wrote += 1
    con.commit()
    con.close()
    print(f"\nDONE: {found} names found, {wrote} written to warehouse.", flush=True)


if __name__ == "__main__":
    main()
