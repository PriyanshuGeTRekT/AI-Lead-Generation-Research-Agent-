export const meta = {
  name: 'startup-contact-verify',
  description: 'Research + adversarially verify accurate contacts (CIN, director, website, phone, LinkedIn, email) for 862 Delhi-NCR DPIIT Scaling startups',
  phases: [{ title: 'Research' }, { title: 'Verify' }],
}

const COMPANIES = [{"n": "4U MEDCARE PRIVATE LIMITED", "c": "South Delhi", "s": "Delhi"}, {"n": "A&S CREATIONS TECH LLP", "c": "Gautam Buddha Nagar", "s": "Uttar Pradesh"}, {"n": "AA ELECTRO MAGNETIC TEST LABORATORY PRIVATE LIMITED", "c": "Gurugram", "s": "Haryana"}, {"n": "AAATS CONNECT PRIVATE LIMITED", "c": "South West Delhi", "s": "Delhi"}, {"n": "AAROGYADAYNEE YOGA SCHOOL & CHIKITSHA KENDER PRIVATE LIMITED", "c": "Gurugram", "s": "Haryana"}, {"n": "AASTHA FACILITIES PRIVATE LIMITED", "c": "Ghaziabad", "s": "Uttar Pradesh"}, {"n": "ABASAN AUTOMATION (OPC) PRIVATE LIMITED", "c": "North West Delhi", "s": "Delhi"}, {"n": "ABBVK KHAZANI SOLUTIONS PRIVATE LIMITED", "c": "Central Delhi", "s": "Delhi"}, {"n": "ABC FUELS PRIVATE LIMITED", "c": "Gurugram", "s": "Haryana"}, {"n": "ABHIPSA CONSTRUCTION PRIVATE LIMITED", "c": "Gurugram", "s": "Haryana"}, {"n": "ABLAZE ELECTRONICS PRIVATE LIMITED", "c": "Ghaziabad", "s": "Uttar Pradesh"}, {"n": "ABPR JEWELS PRIVATE LIMITED", "c": "South West Delhi", "s": "Delhi"}, {"n": "ABRACADABRA FOODS PRIVATE LIMITED", "c": "South West Delhi", "s": "Delhi"}, {"n": "ACCUFOX ENTERPRISES PRIVATE LIMITED", "c": "New Delhi", "s": "Delhi"}, {"n": "ACUMEN GPS INDIA PRIVATE LIMITED", "c": "South Eastdelhi", "s": "Delhi"}, {"n": "ADBREW SOFTWARE PRIVATE LIMITED", "c": "South Delhi", "s": "Delhi"}, {"n": "ADC BRANDS PRIVATE LIMITED", "c": "New Delhi", "s": "Delhi"}, {"n": "ADD A DELTA PRIVATE LIMITED", "c": "Gautam Buddha Nagar", "s": "Uttar Pradesh"}, {"n": "ADDENSURE MEDIA LLP", "c": "Gurugram", "s": "Haryana"}, {"n": "ADEQUATE STEEL FABRICATORS LLP", "c": "Central Delhi", "s": "Delhi"}, {"n": "ADIXSAM VENTURES PRIVATE LIMITED", "c": "Gurugram", "s": "Haryana"}, {"n": "ADJECTUS SERVICES PRIVATE LIMITED", "c": "Gautam Buddha Nagar", "s": "Uttar Pradesh"}, {"n": "ADUCLICK BUSINESS SERVICES PRIVATE LIMITED", "c": "Central Delhi", "s": "Delhi"}, {"n": "ADVANCED AMORPHOUS TECHNOLOGY LLP", "c": "New Delhi", "s": "Delhi"}, {"n": "ADWAIT YOGA & HEALTH SERVICES PRIVATE LIMITED", "c": "North Delhi", "s": "Delhi"}, {"n": "ADWARDS INTELLITECH PRIVATE LIMITED", "c": "East Delhi", "s": "Delhi"}, {"n": "AE LIFE SCIENCES PRIVATE LIMITED", "c": "Central Delhi", "s": "Delhi"}, {"n": "AE TRANSCOM PRIVATE LIMITED", "c": "South Delhi", "s": "Delhi"}, {"n": "AEROSEARCH TECHNOLOGIES PRIVATE LIMITED", "c": "Gautam Buddha Nagar", "s": "Uttar Pradesh"}, {"n": "AETHERRAX TECHNOLOGIES (OPC) PRIVATE LIMITED", "c": "Gurugram", "s": "Haryana"}, {"n": "AICK CORPORATE ADVISORS LLP", "c": "Ghaziabad", "s": "Uttar Pradesh"}, {"n": "AIMLAY PRIVATE LIMITED", "c": "North West Delhi", "s": "Delhi"}, {"n": "AIRSURGE LOGISTICS PRIVATE LIMITED", "c": "South West Delhi", "s": "Delhi"}, {"n": "AJAYA KUMAS PRIVATE LIMITED", "c": "East Delhi", "s": "Delhi"}, {"n": "AKCEL EQUITY INDIA PRIVATE LIMITED", "c": "South Delhi", "s": "Delhi"}, {"n": "AKHANDJYOTI FARM PRODUCTS PRIVATE LIMITED", "c": "North Delhi", "s": "Delhi"}, {"n": "AKIR ADVISORY INDIA LLP", "c": "Faridabad", "s": "Haryana"}, {"n": "AKITA SMT SOLUTIONS PRIVATE LIMITED", "c": "South Eastdelhi", "s": "Delhi"}, {"n": "AKMV CONSULTANTS PRIVATE LIMITED", "c": "Gurugram", "s": "Haryana"}, {"n": "ALCOLITE INDIA ROAD SAFETY PRIVATE LIMITED", "c": "West Delhi", "s": "Delhi"}, {"n": "ALFENNZO NEXTGEN PRIVATE LIMITED", "c": "Delhi", "s": "Delhi"}, {"n": "ALIVE COMMUNITY PRIVATE LIMITED", "c": "North Delhi", "s": "Delhi"}, {"n": "ALTAN'S FARM SHOP PRIVATE LIMITED", "c": "South Eastdelhi", "s": "Delhi"}, {"n": "ALTF SPACES PRIVATE LIMITED", "c": "New Delhi", "s": "Delhi"}, {"n": "AMBESTEN PACKAGINGS ", "c": "Ghaziabad", "s": "Uttar Pradesh"}, {"n": "AMBUQUICK HEALTHCARE PRIVATE LIMITED", "c": "Gurugram", "s": "Haryana"}, {"n": "AMIRSONS ALUMINIUM WORK LLP", "c": "South Delhi", "s": "Delhi"}, {"n": "AMITOJE INDIA PRIVATE LIMITED", "c": "New Delhi", "s": "Delhi"}, {"n": "AMOLICONCEPTS PRIVATE LIMITED", "c": "Gautam Buddha Nagar", "s": "Uttar Pradesh"}, {"n": "AMROC BREMSE OIL TOOLS PRIVATE LIMITED", "c": "Faridabad", "s": "Haryana"}]
const BATCH = 8
const groups = []
for (let i = 0; i < COMPANIES.length; i += BATCH) groups.push(COMPANIES.slice(i, i + BATCH))
log(`Researching ${COMPANIES.length} companies in ${groups.length} batches of ${BATCH}`)

const SCHEMA = {
  type: 'object',
  properties: {
    companies: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          name: { type: 'string' },
          cin: { type: ['string', 'null'] },
          website: { type: ['string', 'null'] },
          phone: { type: ['string', 'null'] },
          director_name: { type: ['string', 'null'] },
          director_role: { type: ['string', 'null'] },
          linkedin: { type: ['string', 'null'] },
          email: { type: ['string', 'null'] },
          source_urls: { type: ['string', 'null'] },
          verified: { type: 'boolean' },
        },
        required: ['name', 'cin', 'website', 'phone', 'director_name', 'director_role', 'linkedin', 'email', 'verified'],
        additionalProperties: false,
      },
    },
  },
  required: ['companies'],
  additionalProperties: false,
}

const researchPrompt = (grp) => `You are an accurate B2B contact researcher. For EACH Indian company below (all are Delhi-NCR, DPIIT-recognized startups), use WebSearch and WebFetch to find ACCURATE contact data. ACCURACY OVER COMPLETENESS — only return a value you actually found on a real page; otherwise use null. NEVER guess or fabricate a phone number, name, or URL.

For each company find:
- cin: the MCA Corporate Identification Number (format like U74900DL2025PTC448306). Often visible on zaubacorp.com, tofler.in, indiafilings.com, falconebiz.com result pages/URLs. null if not found.
- website: the company's OWN official website domain (NOT a directory like justdial/indiamart/zauba/tofler/tracxn/linkedin). null if they have none.
- phone: a contact phone — ONLY from the company's own website (contact/about page) or a clearly-official listing. Indian format. null if not confidently found.
- director_name + director_role: a director/founder (the person to contact). From MCA/Tofler/Zauba director listings or the company's own About/Team page. null if not found.
- linkedin: the founder's personal LinkedIn profile URL (linkedin.com/in/...) OR the company LinkedIn page (linkedin.com/company/...). Must be a real URL you saw. null otherwise.
- email: a contact email if shown on the site/registry. null otherwise.
- source_urls: comma-separated URLs where you found the above.
- verified: false (the verify step will set this).

Companies (JSON): ${JSON.stringify(grp)}

Return {companies:[...]} with one entry per input company, names exactly as given.`

const verifyPrompt = (found) => `You are an adversarial verifier. For each company record below, INDEPENDENTLY verify each non-null field is genuinely correct for THAT company using WebSearch/WebFetch. Be skeptical: a phone or website that belongs to a different (similarly-named) company, a directory, or cannot be confirmed must be set to null. A director name that is actually the company name must be null. Confirm LinkedIn URLs resolve to the right entity.
Set verified=true ONLY if at least the director_name OR (website AND phone) were confirmed from a credible source. Keep confirmed fields, null out the rest. Do not invent new data.

Records (JSON): ${JSON.stringify(found)}

Return {companies:[...]} with the cleaned, verified records (same names).`

const results = await pipeline(
  groups,
  (grp, _o, idx) => agent(researchPrompt(grp), { label: `research:b${idx}`, phase: 'Research', schema: SCHEMA }),
  (res, grp, idx) => {
    const found = (res && res.companies) ? res.companies : []
    if (!found.length) return { companies: [] }
    return agent(verifyPrompt(found), { label: `verify:b${idx}`, phase: 'Verify', schema: SCHEMA })
  },
)

const all = results.filter(Boolean).flatMap((r) => (r && r.companies) ? r.companies : [])
const withContact = all.filter((c) => c.director_name || c.phone || c.website || c.linkedin)
log(`Done: ${all.length} researched, ${withContact.length} with at least one contact field`)
return { total: all.length, companies: all }
