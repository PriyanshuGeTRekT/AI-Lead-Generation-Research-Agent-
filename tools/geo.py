"""
Geo Filter
----------
Lets a search be scoped to a country and (optionally) a state/region. Used to
(a) inject geo terms into search queries and (b) post-filter extracted leads by
matching location/address text. India ships with full state + metro tables; other
countries match on country name and the provided region string.
"""
import re
from typing import Optional

# India: state → representative cities (for query expansion + matching)
INDIA_STATES: dict[str, list[str]] = {
    "Maharashtra": ["Mumbai", "Pune", "Nagpur", "Nashik", "Thane", "Aurangabad"],
    "Karnataka": ["Bengaluru", "Bangalore", "Mysuru", "Hubli", "Mangalore"],
    "Tamil Nadu": ["Chennai", "Coimbatore", "Madurai", "Tiruppur", "Salem"],
    "Telangana": ["Hyderabad", "Warangal"],
    "Delhi": ["Delhi", "New Delhi"],
    "Haryana": ["Gurugram", "Gurgaon", "Faridabad", "Panipat"],
    "Uttar Pradesh": ["Noida", "Lucknow", "Kanpur", "Ghaziabad", "Agra"],
    "Gujarat": ["Ahmedabad", "Surat", "Vadodara", "Rajkot"],
    "West Bengal": ["Kolkata", "Howrah", "Siliguri"],
    "Telangana ": ["Hyderabad"],
    "Rajasthan": ["Jaipur", "Jodhpur", "Udaipur"],
    "Punjab": ["Ludhiana", "Amritsar", "Jalandhar"],
    "Kerala": ["Kochi", "Thiruvananthapuram", "Kozhikode"],
    "Madhya Pradesh": ["Indore", "Bhopal", "Gwalior"],
    "Andhra Pradesh": ["Visakhapatnam", "Vijayawada", "Guntur"],
}

# We deliberately target INDIA ONLY — foreign markets have different HR
# compliance/regulation, so they are out of scope for HumanMaximizer's ICP.
_COUNTRY_ALIASES = {
    "india": "India",
    "in": "India",
    "bharat": "India",
}

# Serper geo code — India only.
COUNTRY_GL = {"India": "in"}

# Region PRESETS for the Hindi + English speaking belt (the active ICP).
# "Hindi belt" = the Hindi-heartland states; "Metros" = the big English-first
# business metros. A preset expands into query/match tokens.
HINDI_BELT = [
    "Uttar Pradesh", "Madhya Pradesh", "Bihar", "Rajasthan", "Haryana", "Delhi",
    "Jharkhand", "Chhattisgarh", "Uttarakhand", "Himachal Pradesh",
    "Noida", "Lucknow", "Kanpur", "Indore", "Bhopal", "Jaipur", "Gurugram",
    "Faridabad", "Patna", "Ranchi", "Raipur", "Dehradun", "Chandigarh",
]
METROS = [
    "Mumbai", "Pune", "Bengaluru", "Hyderabad", "Chennai", "Delhi", "Gurugram",
    "Noida", "Kolkata", "Ahmedabad", "Jaipur",
]
REGION_PRESETS = {
    "hindi belt": HINDI_BELT,
    "metros": METROS,
}


def normalize_country(country: Optional[str]) -> str:
    if not country:
        return ""
    return _COUNTRY_ALIASES.get(country.strip().lower(), country.strip().title())


def gl_code(country: Optional[str]) -> Optional[str]:
    return COUNTRY_GL.get(normalize_country(country))


def query_terms(country: Optional[str], region: Optional[str]) -> list[str]:
    """Geo tokens to weave into search query variants."""
    country = normalize_country(country) or "India"
    terms: list[str] = []
    if region and region.strip().lower() in REGION_PRESETS:
        terms.extend(REGION_PRESETS[region.strip().lower()][:6])
        terms.append(country)
        return _dedup(terms)
    if region:
        terms.append(region.strip())
        if country == "India":
            for st, cities in INDIA_STATES.items():
                if region.strip().lower() in st.lower() or any(
                    region.strip().lower() == c.lower() for c in cities
                ):
                    terms.extend(cities[:3])
                    break
    if country:
        terms.append(country)
    return _dedup(terms)


def _dedup(terms: list[str]) -> list[str]:
    seen, out = set(), []
    for t in terms:
        k = t.lower()
        if k and k not in seen:
            seen.add(k)
            out.append(t)
    return out


def _region_tokens(country: str, region: str) -> list[str]:
    if region.strip().lower() in REGION_PRESETS:
        return [t.lower() for t in REGION_PRESETS[region.strip().lower()]]
    toks = [region.lower()]
    if country == "India":
        for st, cities in INDIA_STATES.items():
            if region.lower() in st.lower() or any(region.lower() == c.lower() for c in cities):
                toks.append(st.lower())
                toks += [c.lower() for c in cities]
                break
    return toks


def geo_match(lead: dict, country: Optional[str], region: Optional[str]) -> bool:
    """True if the lead's location/address is consistent with the geo filter."""
    country = normalize_country(country)
    if not country and not region:
        return True
    blob = " ".join(
        str(lead.get(k) or "") for k in ("location", "address", "company_name", "description")
    ).lower()

    if country and country.lower() not in blob:
        # allow common India city names to stand in for "India"
        if country == "India":
            india_cities = [c.lower() for cs in INDIA_STATES.values() for c in cs]
            if not any(c in blob for c in india_cities) and "india" not in blob:
                return False
        else:
            return False

    if region:
        if not any(tok in blob for tok in _region_tokens(country, region)):
            return False
    return True
