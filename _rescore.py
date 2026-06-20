"""Recompute offline signal_score for the Delhi-NCR IT/BPO/consulting campaign
with the refreshed scorer (reflects the 88 named DMs + name-based HR-intensity)."""
import json
import sqlite3
import collections

from core.signals import score_offline

DB = "data/warehouse.db"
I = ("IT services", "BPO", "consulting")

con = sqlite3.connect(DB, timeout=30)
con.row_factory = sqlite3.Row
rows = [dict(r) for r in con.execute(
    f"""SELECT * FROM leads WHERE state='Delhi NCR' AND industry IN ({','.join('?'*3)})
        AND phone!='' AND status NOT IN ('excluded','disqualified','raw')""", I).fetchall()]

c = con.cursor()
buckets = collections.Counter()
ranked = []
for r in rows:
    try:
        p = json.loads(r["payload"]) if r["payload"] else {}
    except Exception:
        p = {}
    lead = {**p, **{k: r[k] for k in r.keys() if k != "payload"}}  # columns win
    lead["payload"] = p
    sc, reasons = score_offline(lead)
    p["signal_score"] = sc
    p["signal_reasons"] = reasons
    c.execute("UPDATE leads SET signal_score=?, payload=? WHERE domain=?",
              (sc, json.dumps(p), r["domain"]))
    buckets[(sc // 10) * 10] += 1
    ranked.append((sc, r["company_name"], r.get("dm_name") or "", reasons))
con.commit()
con.close()

print("NEW signal_score distribution (239):")
for b in sorted(buckets, reverse=True):
    print(f"  {b:>3}-{b+9}: {buckets[b]}")
ranked.sort(key=lambda x: -x[0])
print("\nTop 12 (the first calls):")
for sc, name, dm, rs in ranked[:12]:
    who = f" — {dm}" if dm else ""
    print(f"  {sc:>3}  {name[:42]}{who}")
print(f"\n40-floor leads now: {buckets[40]}  (was 129)")
