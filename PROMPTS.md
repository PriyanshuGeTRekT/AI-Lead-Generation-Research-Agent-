# Prompt Reference: AI Lead Generation Pipeline

These are the actual prompts sent to Llama 3.1 8B (model ID: `llama3-8b-8192`) via the Groq API during pipeline execution. Each of the three agents has one primary prompt. All prompts use RAG context injected at runtime from a ChromaDB vector store that contains HumanMaximizer HRMS product knowledge. The hallucination guard does not use an LLM prompt of its own -- it runs regex pattern matching and keyword grounding checks on the LLM output after the fact.

---

## Section 1: Research Agent -- Lead Extraction Prompt

**File:** `agents/research_agent.py`

### The Prompt

```
You are a B2B lead research specialist.
Given search results about companies, extract structured lead information.

Focus on companies that could benefit from HRMS (Human Resource Management Software).
Look for: company name, website, industry, size, location, and what they do.

Search Results:
{search_results}

Scraped Website Content:
{scraped_content}

Extract lead information and respond with a JSON object ONLY (no explanation):
{
  "company_name": "...",
  "website": "...",
  "industry": "...",
  "size": "...(e.g. 50-200 employees)",
  "location": "...",
  "description": "...(what the company does, 2-3 sentences)",
  "decision_makers": ["...", "..."],
  "contact_emails": [],
  "pain_points": ["...", "...(likely HR challenges they face)"],
  "status": "researched"
}

If you cannot extract valid company info, return: {"status": "invalid"}
```

### What the Prompt Does

The prompt asks the LLM to act as a B2B research analyst and pull structured company data from two sources of raw text: the web search result snippet and the scraped homepage content. It does not ask the LLM to reason about product fit -- that is the qualification agent's job. The goal here is pure extraction: get the fields, return them in JSON.

The "pain_points" field is an exception -- the LLM is asked to infer likely HR challenges even when the website does not state them explicitly. This is intentional because companies rarely advertise their operational problems on their homepage.

### Variables Injected

| Variable | Source | Content |
|---|---|---|
| `{search_results}` | DuckDuckGo / SerpAPI | JSON-serialized search result dict (title, URL, snippet) |
| `{scraped_content}` | `tools/web_search.py` scraper | First 1500 characters of the company homepage |

The 1500-character cap on `scraped_content` is hardcoded in `research_agent.py` line 94. It keeps the prompt within token budget for the 8B model.

### Why Temperature 0.1

This call uses `llm_temperature_extract = 0.1` (set in `core/config.py`). Extraction tasks need the model to copy information from the input rather than generate new content. A low temperature makes the model more deterministic and less likely to paraphrase or invent details. If the company name is "Bharat Steel Pvt Ltd" in the scraped text, the model should return exactly that, not "Bharat Steel" or "Bharat Steel Limited."

### Example Input

**`{search_results}`:**
```json
{
  "url": "https://www.zomato.com/about",
  "title": "About Zomato | Food Delivery Platform",
  "snippet": "Zomato is India's leading food delivery and restaurant discovery platform, operating across 500+ cities with a workforce of over 5000 employees."
}
```

**`{scraped_content}`** (first 1500 chars of scraped homepage):
```
Zomato connects people to food across 500+ cities in India. We work with 
300,000+ restaurant partners and employ over 5,000 full-time staff in 
technology, operations, and logistics. Our teams handle real-time order 
management, partner payouts, and last-mile delivery across every major 
Indian city. We are hiring aggressively in 2024...
```

### Example Output

```json
{
  "company_name": "Zomato",
  "website": "https://www.zomato.com",
  "industry": "Food Technology / Food Delivery",
  "size": "5000+ employees",
  "location": "Gurugram, India",
  "description": "Zomato is India's leading food delivery platform operating across 500+ cities. It manages a large workforce across technology, operations, and logistics functions. The company is actively hiring in 2024.",
  "decision_makers": ["HR Director", "People Operations Lead"],
  "contact_emails": [],
  "pain_points": [
    "Managing payroll and attendance across a distributed delivery workforce",
    "High-volume recruitment and onboarding at scale",
    "Tracking performance across technology and operations teams"
  ],
  "status": "researched"
}
```

---

## Section 2: Qualification Agent -- Scoring Prompt

**File:** `agents/qualification_agent.py`

### The Prompt

```
You are a B2B sales qualification expert for an HRMS software company.

Your product knowledge (from our HRMS product, use ONLY this, do not fabricate features):
{rag_context}

Company to qualify:
{lead_info}

Score this lead from 0-10 based on:
- Likelihood they need HRMS software (employee management, payroll, attendance, recruitment)
- Company size (10-500 employees is ideal)
- Industry fit (any industry with significant workforce)
- Growth signals (hiring, expanding)
- Decision maker accessibility

Respond with JSON ONLY:
{
  "qualification_score": <float 0-10>,
  "qualification_reason": "...(2-3 sentences explaining the score)",
  "pain_points_identified": ["...", "..."],
  "recommended_approach": "...(how to approach this lead)"
}
```

### What the Prompt Does

The qualification prompt asks the LLM to evaluate a lead against five explicit criteria and produce a numeric score. The explicit criteria list (company size, growth signals, etc.) anchors what the LLM is rewarded for -- without them, the model would use its own judgment about what "good lead" means, which is inconsistent across runs.

The instruction "use ONLY this, do not fabricate features" is placed right after the RAG context block. Positioning matters: the model needs to see the constraint immediately after the content it constrains, not buried at the end.

The structured output is validated using Pydantic via `QualificationResult` (defined in `models/schemas.py`) with `.with_structured_output()`. The actual fields enforced are `score`, `reasoning`, `key_signals`, and `recommended_action`. The JSON schema in the prompt above is what the LLM sees; Pydantic validates the parsed result afterward.

### RAG Context Injection

Before the prompt is built, the agent calls `retrieve_hrms_context(description)` from `rag/retriever.py`. This queries ChromaDB with the lead's description and pain points as the search query and returns the top 4 most relevant chunks (controlled by `rag_top_k = 4` in config). These chunks contain real product documentation -- features like "automated payroll processing," "biometric attendance integration," "employee self-service portal" -- and are injected at `{rag_context}`.

This grounding step means the LLM is scoring leads against actual HumanMaximizer capabilities, not general HRMS knowledge from its training data.

### Scoring Criteria: What Separates a Score of 8 from a Score of 3

**High score (8-10):** Company has 50-500 employees, is in a workforce-heavy industry (manufacturing, logistics, IT services), shows hiring signals (job postings, expansion news), and has an HR or People decision maker named in the lead data.

**Mid score (5-7):** Company size fits but industry is less workforce-intensive, or size is at the edge of the ideal range (e.g., 800 employees), or no growth signal is visible.

**Low score (1-4):** Solo founders, companies under 10 employees, companies that already mention an existing HRMS in their website content, or companies where the scraped content is too thin for the LLM to assess.

The threshold for qualification is `qualification_threshold = 5.0`, set in `core/config.py`. Leads scoring below 5.0 get status `disqualified` and are not passed to the sales agent.

### Why This Prompt Does Not Need Few-Shot Examples

The five-criteria scoring rubric in the prompt itself acts as implicit anchoring. The LLM has enough structure from the criteria list and the score range (0-10) to produce consistent results without needing example score/reasoning pairs. Few-shot examples would add token cost for each of the 5 leads processed per run. If scoring consistency becomes a problem in practice, adding 2-3 examples at the bottom of this prompt would be the first thing to try.

### Example Input

**`{rag_context}`** (retrieved from ChromaDB):
```
HumanMaximizer supports attendance tracking with biometric integration, 
automated payroll processing with compliance for Indian labor laws, 
an employee self-service portal for leave and expense requests, 
and a recruitment module with applicant tracking and offer letter generation.
It is best suited for companies between 50 and 1000 employees in any industry.
```

**`{lead_info}`:**
```json
{
  "company_name": "Zomato",
  "industry": "Food Technology / Food Delivery",
  "size": "5000+ employees",
  "description": "Zomato is India's leading food delivery platform...",
  "pain_points": [
    "Managing payroll across a distributed delivery workforce",
    "High-volume recruitment and onboarding at scale"
  ],
  "decision_makers": ["HR Director", "People Operations Lead"],
  "status": "researched"
}
```

### Example Output (QualificationResult)

```json
{
  "score": 6.5,
  "reasoning": "Zomato has strong HRMS need signals -- large workforce, recruitment at scale, and distributed payroll complexity. However, at 5000+ employees the company is above the ideal size range for HumanMaximizer, which targets 50-1000 employees. The HR Director contact point is a positive signal.",
  "key_signals": [
    "High-volume recruitment and onboarding need",
    "Distributed workforce payroll complexity",
    "Named HR decision maker in lead data"
  ],
  "recommended_action": "nurture"
}
```

---

## Section 3: Sales Agent -- Outreach Email Prompt

**File:** `agents/sales_agent.py`

### The Prompt

```
You are a B2B sales copywriter for HumanMaximizer, an HRMS software company.

Our product capabilities (use ONLY what is stated below, do not invent features):
{rag_context}

Prospect company details:
{lead_info}

Write a personalized cold outreach email that:
1. Opens with something specific about their company (not generic)
2. Mentions a specific pain point they likely face
3. Connects our HRMS solution to that pain point using ONLY the product info above
4. Has a clear, low-friction CTA (demo, quick call)
5. Is concise (max 150 words)

Respond with JSON ONLY:
{
  "subject": "...",
  "email_body": "...",
  "follow_up_note": "...(internal note: why this angle was chosen)"
}
```

### What the Prompt Does

This prompt generates a cold outreach email customized to the individual lead. Unlike the extraction and qualification prompts, this is a creative writing task -- the LLM needs to make choices about tone, angle, and framing. The five numbered instructions serve as a checklist the model follows when drafting: specificity in the opener, pain-point mention, product grounding, CTA, and length constraint.

The `follow_up_note` field is an internal-only field that captures the LLM's reasoning about why it chose a particular angle. It is stored in the lead record and shown in the Slack review notification. It is never sent to the prospect.

### Variables Injected

| Variable | Source | Content |
|---|---|---|
| `{rag_context}` | ChromaDB retrieval | Top 4 product knowledge chunks, retrieved using the lead's description + pain points as the query |
| `{lead_info}` | Lead record (dict) | company_name, industry, size, description, pain_points, decision_makers, qualification_reason |

Note that `{lead_info}` for the sales agent is a subset of the full lead dict. Fields like `website`, `contact_emails`, and `status` are excluded because they are not useful to the email writer.

### Why Temperature 0.4

This call uses `llm_temperature_creative = 0.4` (set in `core/config.py`), which is higher than the 0.1 used for extraction and scoring. Email writing benefits from some variability -- two leads in the same industry should not receive identical emails. At 0.4 the model still stays grounded (it is not generating fiction) but has enough room to vary sentence structure, opening hooks, and word choice across leads.

### use_cache=False

The `call_llm()` call for this agent passes `use_cache=False`. The Redis LLM response cache (TTL: 1 hour) would return the same email for two leads with identical prompts. Since email text is sensitive to repetition -- a sales rep might send multiple emails in one day -- cache is disabled so every email is freshly generated.

### The Hallucination Guard on Outreach

After the email is generated, the sales agent passes the `email_body` through `guard_llm_response()` from `rag/hallucination_guard.py`. For outreach emails, the guard runs three checks:

1. **Pattern scan:** Looks for fabricated revenue figures (`$50 million`), year ranges (`2015-2022`), founding years (`founded in 2003`), and suspiciously precise headcounts (`12,500+ employees`). These are patterns the LLM tends to hallucinate when asked to sound specific.

2. **Product claim grounding:** If the email contains phrases like "our platform," "our HRMS," or "HumanMaximizer," the guard checks that the same phrase appears in the RAG context. If the LLM invented a feature that was not in the retrieved chunks, this check catches it.

3. **Retrieval confidence:** If the RAG retrieval returned poor cosine similarity scores (distance > 0.8), the guard flags the entire response as low-confidence regardless of content.

If the guard action is `"reject"` (confidence below 0.3), the lead's `outreach_draft` is set to `None` and the email is not used. If the action is `"warn"`, the event is logged to LangSmith and the email proceeds with the warning attached to the lead record.

### Example Output (Manufacturing Company)

Input lead: Precision Auto Parts Pvt Ltd, manufacturing, 300 employees, Pune, India. Pain points: attendance tracking across shifts, contract worker payroll.

```json
{
  "subject": "Streamlining shift attendance and payroll at Precision Auto Parts",
  "email_body": "Hi [Name],\n\nI came across Precision Auto Parts and noticed you run multi-shift manufacturing operations in Pune -- managing attendance and payroll across shifts and contract workers is one of the messiest HR problems in the industry.\n\nHumanMaximizer handles exactly this: biometric attendance integration, automated payroll with compliance for contract workers, and an employee self-service portal so your HR team is not chasing paper every month.\n\nWould a 20-minute demo make sense this week? I can show you how similar manufacturing companies set this up.\n\n[Sender name]",
  "follow_up_note": "Chose shift attendance + contract worker payroll angle because the lead data shows multi-shift ops and manufacturing context. Both are directly supported per product RAG context. Avoided generic HRMS pitch."
}
```

---

## Section 4: Prompt Design Principles

### RAG Context Injected Before the Task

In both the qualification and sales prompts, the `{rag_context}` block appears before the company details and before the task instructions. This is deliberate: the model reads context top-to-bottom, so putting the product knowledge first means it is loaded into the model's attention before it starts reasoning about the lead. Injecting context after the question (which is what some tutorials show) lets the model start generating an answer before it has processed the grounding material, which increases hallucination rates.

### JSON Output with Field Names from the Schema

Each prompt ends with a JSON template that explicitly names every expected field. For example, the qualification prompt shows `"qualification_score"`, `"qualification_reason"`, `"pain_points_identified"`, and `"recommended_approach"` with their types. Repeating the field names from the Pydantic schema in the prompt text significantly reduces parse failures: the model knows exactly what keys to produce and does not invent synonyms like `"score_value"` or `"reason"`.

### Temperature Split: 0.1 for Structure, 0.4 for Writing

Extraction and scoring are treated as lookup tasks -- the right answer is in the input text, the model just needs to find and format it. Temperature 0.1 keeps outputs consistent across identical inputs (which matters for the Redis cache to work correctly). Email generation is a composition task where the model needs to make stylistic choices. Temperature 0.4 provides that flexibility without letting the model drift far enough to hallucinate product claims.

### "Use ONLY what is stated below, do not fabricate" Instruction

Both the qualification and sales prompts include an explicit constraint immediately below the RAG context block: the model is told to use only the retrieved product knowledge and not to invent features. This instruction does not eliminate hallucination on its own, but it shifts the model's behavior noticeably and makes the subsequent hallucination guard checks more meaningful (a model that was told not to fabricate but still does is more clearly failing than one that was never told).

---

## Section 5: Example Keywords That Work Well

These are search queries passed to the pipeline as the `keyword` parameter via `POST /generate-leads`. The pipeline runs a multi-source web search on this keyword and processes the top results.

| Keyword | Why It Works |
|---|---|
| `manufacturing company India 200 employees` | Industry + country + explicit size. All three are signals the qualification prompt scores on. |
| `IT services company Bangalore 500 employees` | High-density tech hub. Companies in this category frequently have fragmented HR tooling. |
| `logistics company India HR challenges` | Adding "HR challenges" biases search results toward content that mentions workforce problems, which gives the research agent richer pain point material. |
| `textile manufacturing company Surat hiring` | "Hiring" is a growth signal. Surat is a dense textile cluster -- multiple relevant results per search. |
| `BPO company Hyderabad workforce management` | BPO companies have high headcount and shift-based attendance, a core HumanMaximizer use case. |
| `pharma company India 100 to 500 employees` | Pharma has compliance requirements that HRMS addresses (shift logs, certifications). |
| `construction company India 300 employees` | Construction firms have contract-heavy workforces and irregular payroll, which maps to product features. |
| `hospital HR management India` | Healthcare is workforce-intensive with shift management and attendance complexity. |
| `retail chain India staff management` | Multi-location retail has distributed HR needs. "Staff management" in the keyword attracts relevant content. |
| `engineering firm Pune payroll software` | Adding "payroll software" signals the company is actively looking for a solution, not just a prospect. |

**Why location + industry + size work together:** The research agent scrapes homepage content that may not explicitly mention employee count. When all three signals appear in the search results snippet, the LLM has enough to produce a complete lead record without having to infer size from indirect cues. Keywords that omit size tend to produce leads where the `size` field is populated with vague strings like "mid-sized company," which hurts the qualification scorer's accuracy.
