"""Clean polluted dm_name values in the campaign: the old Serper/crawl enrichment
banked webpage fragments ("Your Digital Marketing", "Public Sector"...) as names.
Keep a name only if a real 2-3 token person-name can be recovered; else null it."""
import json
import re
import sqlite3

DB = "data/warehouse.db"
I = ("IT services", "BPO", "consulting")

HONOR = {"col", "dr", "mr", "mrs", "ms", "capt", "maj", "lt", "smt", "shri", "sri"}
# Words that are never part of a person's name (web/business/role jargon seen in the
# scraped junk). Common Indian surnames are deliberately NOT here.
BLOCK = {
    "services", "service", "security", "solutions", "solution", "outsourcing",
    "marketing", "digital", "growth", "recruitment", "recruiters", "recruiter",
    "hiring", "consulting", "consultants", "consultant", "consultancy",
    "compliance", "compliances", "certifications", "certification", "certificates",
    "certificate", "certified", "technologies", "technology", "software", "web",
    "website", "design", "designing", "login", "customer", "support", "our", "your",
    "us", "price", "list", "popular", "brands", "brand", "success", "stories",
    "story", "preferred", "public", "sector", "transformation", "corporate",
    "clients", "client", "partnership", "trusted", "premium", "verified",
    "manufacturing", "industry", "industries", "largest", "leadership", "message",
    "from", "the", "read", "more", "pharma", "salesforce", "summit", "star",
    "tally", "responsive", "engineer", "engineering", "agents", "agent", "for",
    "value", "submit", "quote", "vision", "profit", "proprietorship", "registration",
    "annual", "information", "conscious", "reliable", "strategic", "place", "meet",
    "useful", "cheers", "advisor", "designation", "startup", "network", "networks",
    "systems", "system", "uttar", "pradesh", "global", "top", "best", "preschool",
    "gurgaon", "india", "online", "company", "companies", "group", "enterprises",
    "work", "workers", "hard", "communications", "innovates", "innovations",
    "creators", "infotech", "exim", "erp", "gem", "fssai", "food", "neet", "and",
    "managing", "manager", "director", "founder", "owner", "ceo", "partner",
}


def name_like(tok: str) -> bool:
    t = tok.strip()
    if len(t) < 2 or not t.isalpha():
        return False
    if t.lower() in BLOCK or t.lower() in HONOR:
        return False
    return t[0].isupper()


def recover(raw: str) -> str:
    """Return a clean 2-3 token person name, or '' if none can be recovered."""
    s = re.sub(r"\s+", " ", (raw or "").replace("\n", " ")).strip()
    toks = s.split(" ")
    # find maximal runs of consecutive name-like tokens
    best = []
    cur = []
    for tk in toks:
        if name_like(tk):
            cur.append(tk)
        else:
            if len(cur) > len(best):
                best = cur
            cur = []
    if len(cur) > len(best):
        best = cur
    if len(best) < 2:
        return ""
    run = best[:3]  # cap at 3 tokens
    # re-attach a leading honorific if it sat right before the run
    idx = toks.index(run[0])
    if idx > 0 and toks[idx - 1].lower().strip(".") in HONOR:
        return toks[idx - 1].strip(".").title() + " " + " ".join(run)
    return " ".join(run)


con = sqlite3.connect(DB, timeout=30)
con.row_factory = sqlite3.Row
c = con.cursor()
rows = [dict(r) for r in c.execute(
    f"""SELECT domain, company_name, dm_name, payload FROM leads
        WHERE state='Delhi NCR' AND industry IN ({','.join('?'*3)})
          AND phone!='' AND dm_name!='' AND status NOT IN ('excluded','disqualified','raw')""", I).fetchall()]

kept = cleaned = dropped = 0
for r in rows:
    raw = r["dm_name"]
    new = recover(raw)
    try:
        p = json.loads(r["payload"]) if r["payload"] else {}
    except Exception:
        p = {}
    if not new:
        c.execute("UPDATE leads SET dm_name='' WHERE domain=?", (r["domain"],))
        p.pop("dm_name", None)
        c.execute("UPDATE leads SET payload=? WHERE domain=?", (json.dumps(p), r["domain"]))
        dropped += 1
        print(f"  DROP  {raw!r:<40} <- {r['company_name'][:30]}")
    elif new != raw:
        p["dm_name"] = new
        c.execute("UPDATE leads SET dm_name=?, payload=? WHERE domain=?", (new, json.dumps(p), r["domain"]))
        cleaned += 1
        print(f"  CLEAN {raw!r:<40} -> {new!r}")
    else:
        kept += 1
con.commit()
con.close()
print(f"\nkept clean: {kept} | recovered/trimmed: {cleaned} | dropped junk: {dropped}")
print(f"named DM now: {kept + cleaned}")
