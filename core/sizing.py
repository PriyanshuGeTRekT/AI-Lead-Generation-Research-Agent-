"""
Right-sizing — keep the HRMS sweet spot, drop enterprises and micro shops.
--------------------------------------------------------------------------
Two gates:
  1. ENTERPRISE / at-scale exclusion (name-based, free, instant): big brands and
     MNCs (Tata, Infosys, Genpact, Accenture, 1mg…) already run an HRMS — drop them.
     Also drops franchise/service-center/branch listings (not the buying entity).
  2. HEADCOUNT gate (Serper LinkedIn lookup): keep ~15–800 employees. Bigger =
     already has HRMS; smaller (<~10) = too small to need/buy one.

`is_enterprise(name)` is free. `employee_count(company)` costs one Serper call.
"""
import re
from typing import Optional

# Big brands / conglomerates / IT-BPO-consulting giants / global MNCs / consumer
# giants — any company already operating at the scale where an HRMS is a given.
_ENTERPRISE = re.compile(
    r"\b("
    r"tata|reliance|adani|birla|aditya birla|mahindra|bajaj|jindal|vedanta|"
    r"infosys|wipro|hcl|tcs|tech mahindra|mindtree|mphasis|ltimindtree|persistent|"
    r"accenture|capgemini|cognizant|genpact|concentrix|teleperformance|wns|firstsource|"
    r"ibm|microsoft|google|amazon|oracle|sap|dell|lenovo|hp |hewlett|cisco|intel|"
    r"deloitte|kpmg|pwc|pricewaterhouse|ernst|mckinsey|bain|boston consulting|bcg|"
    r"flipkart|paytm|byju|zomato|swiggy|ola |oyo|1mg|tata 1mg|pharmeasy|nykaa|policybazaar|"
    r"airtel|vodafone|idea|jio|bsnl|hdfc|icici|axis bank|sbi|kotak|yes bank|"
    r"maruti|hyundai|honda|toyota|hero |bajaj auto|ashok leyland|"
    r"hindustan unilever|hul|itc|nestle|pepsi|coca.?cola|britannia|dabur|"
    r"larsen|l&t|siemens|bosch|samsung|sony|panasonic|lg electronics"
    r")\b", re.I)

# Franchise / outlet / branch listings — a location, not the decision-making company.
_OUTLET = re.compile(r"\b(service cent(er|re)|service station|branch|outlet|showroom|"
                     r"authorized (dealer|service)|franchise|atm|kiosk|customer care cent)\b", re.I)


def is_enterprise(name: str) -> bool:
    n = name or ""
    return bool(_ENTERPRISE.search(n) or _OUTLET.search(n))


def employee_count(company: str, city: str = "") -> Optional[int]:
    """LinkedIn-style employee count via Serper (1 call). None if unknown. Fail-safe."""
    from core import signals
    if not company:
        return None
    d = signals._serper(f'"{company}" {city} linkedin employees'.strip())
    for h in (d.get("organic") or [])[:5]:
        t = (h.get("title", "") + " " + h.get("snippet", ""))
        m = re.search(r"([\d,]+)\s*(?:\+|-\s*[\d,]+)?\s*(?:employees|staff|team members)", t, re.I)
        if m:
            try:
                return int(m.group(1).replace(",", ""))
            except ValueError:
                pass
        # LinkedIn band text e.g. "51-200 employees"
        m2 = re.search(r"(\d+)\s*-\s*(\d+)\s*employees", t, re.I)
        if m2:
            return (int(m2.group(1)) + int(m2.group(2))) // 2
    return None


def size_band(emp: Optional[int]) -> str:
    if emp is None:
        return "unknown"
    if emp < 10:
        return "micro"
    if emp <= 800:
        return "sweet-spot"
    return "enterprise"
