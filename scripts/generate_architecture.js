"use strict";
const PptxGenJS = require("pptxgenjs");

const pres = new PptxGenJS();
pres.layout = "LAYOUT_16x9";

// ── Design tokens ────────────────────────────────────────────────────────────
const C = {
  darkBg:    "0D1B2A",
  lightBg:   "F7FAFC",
  teal:      "028090",
  mint:      "02C39A",
  amber:     "F59E0B",
  navy:      "0D1B2A",
  white:     "FFFFFF",
  muted:     "94A3B8",
  nearBlack: "0F172A",
  mutedDark: "475569",
  tealLight: "1C7293",
  codeLight: "F1F5F9",
  codeTeal:  "E0F7F7",
  grey:      "9CA3AF",
  greyFill:  "E5E7EB",
  red:       "EF4444",
  altRow:    "EFF6FF",
};

// CRITICAL: shadow factory — never reuse shadow objects
const mkShadow = () => ({ type: "outer", blur: 5, offset: 2, angle: 135, color: "000000", opacity: 0.12 });

// ── Helpers ───────────────────────────────────────────────────────────────────
function darkSlide() {
  const s = pres.addSlide();
  s.background = { color: C.darkBg };
  return s;
}
function lightSlide() {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  return s;
}

// Section title on light slide
function addLightTitle(slide, text, x, y, w, h, opts) {
  slide.addText(text, {
    x: x !== undefined ? x : 0.5,
    y: y !== undefined ? y : 0.3,
    w: w !== undefined ? w : 9,
    h: h !== undefined ? h : 0.65,
    fontSize: 36,
    bold: true,
    color: C.nearBlack,
    fontFace: "Trebuchet MS",
    ...opts,
  });
}

// Card: white rect + teal left accent bar
function addCard(slide, x, y, w, h) {
  slide.addShape(pres.ShapeType.rect, {
    x, y, w, h,
    fill: { color: C.white },
    line: { color: "E2E8F0", width: 0.5 },
    shadow: mkShadow(),
  });
  // teal left accent bar
  slide.addShape(pres.ShapeType.rect, {
    x, y, w: 0.06, h,
    fill: { color: C.teal },
    line: { type: "none" },
  });
}

// Card on dark slide
function addDarkCard(slide, x, y, w, h) {
  slide.addShape(pres.ShapeType.rect, {
    x, y, w, h,
    fill: { color: C.white },
    line: { color: "1E3A5F", width: 0.5 },
    shadow: mkShadow(),
  });
  slide.addShape(pres.ShapeType.rect, {
    x, y, w: 0.06, h,
    fill: { color: C.teal },
    line: { type: "none" },
  });
}

// Flow box helper
function flowBox(slide, label, x, y, w, h, fillColor, textColor, fontSize) {
  slide.addShape(pres.ShapeType.rect, {
    x, y, w, h,
    fill: { color: fillColor || C.teal },
    line: { color: "CCCCCC", width: 0.5 },
    rectRadius: 0.05,
  });
  slide.addText(label, {
    x, y, w, h,
    fontSize: fontSize || 11,
    bold: true,
    color: textColor || C.white,
    align: "center",
    valign: "middle",
    fontFace: "Calibri",
  });
}

// Arrow right (simple line with arrowhead)
function arrowRight(slide, x, y, w) {
  slide.addShape(pres.ShapeType.line, {
    x, y, w, h: 0,
    line: { color: C.teal, width: 1.5, endArrowType: "triangle" },
  });
}

// Arrow down
function arrowDown(slide, x, y, h) {
  slide.addShape(pres.ShapeType.line, {
    x, y, w: 0, h,
    line: { color: C.teal, width: 1.5, endArrowType: "triangle" },
  });
}

// Dashed line connector
function dashedLine(slide, x, y, w, h) {
  slide.addShape(pres.ShapeType.line, {
    x, y, w, h,
    line: { color: C.teal, width: 1, dashType: "dash", endArrowType: "triangle" },
  });
}

// ── SLIDE 1 — Title ───────────────────────────────────────────────────────────
{
  const s = darkSlide();

  // Left strip
  s.addShape(pres.ShapeType.rect, {
    x: 0, y: 0, w: 0.18, h: 5.625,
    fill: { color: C.teal },
    line: { type: "none" },
  });

  // Title
  s.addText("AI Lead Generation Agent", {
    x: 0.4, y: 1.6, w: 9, h: 1.2,
    fontSize: 44,
    bold: true,
    color: C.white,
    fontFace: "Trebuchet MS",
  });

  // Subtitle
  s.addText("Multi-agent HRMS prospect discovery using LangGraph, Groq, and RAG", {
    x: 0.4, y: 2.9, w: 8.5, h: 0.6,
    fontSize: 18,
    color: C.muted,
    fontFace: "Calibri",
  });

  // Tag pills
  const pills = [
    { label: "LangGraph Supervisor", x: 0.4, w: 2.2, fill: C.teal },
    { label: "Llama 3.1 via Groq",   x: 2.75, w: 2.0, fill: C.mint },
    { label: "RAG + ChromaDB/pgvector", x: 4.9, w: 2.6, fill: C.tealLight },
  ];
  for (const p of pills) {
    s.addShape(pres.ShapeType.roundRect, {
      x: p.x, y: 3.8, w: p.w, h: 0.38,
      fill: { color: p.fill },
      line: { type: "none" },
      rectRadius: 0.12,
    });
    s.addText(p.label, {
      x: p.x, y: 3.8, w: p.w, h: 0.38,
      fontSize: 12,
      color: C.white,
      align: "center",
      valign: "middle",
      fontFace: "Calibri",
    });
  }

  // Bottom right credit
  s.addText("Razor Infotech Take-Home Assignment", {
    x: 5.5, y: 5.1, w: 4.3, h: 0.4,
    fontSize: 11,
    color: C.mutedDark,
    align: "right",
    fontFace: "Calibri",
  });
}

// ── SLIDE 2 — What We Built ───────────────────────────────────────────────────
{
  const s = lightSlide();
  addLightTitle(s, "What We Built");

  const cards = [
    {
      x: 0.4,
      header: "The Problem",
      body: "HRMS companies struggle to find qualified prospects at scale. Manual research is slow, inconsistent, and wastes sales reps time on bad leads.",
    },
    {
      x: 3.45,
      header: "The Solution",
      body: "Autonomous multi-agent pipeline. Research, qualify, and draft outreach emails for HRMS prospects with zero human effort until review.",
    },
    {
      x: 6.5,
      header: "The Result",
      body: "Qualified leads with outreach emails, scored 0-10 against real product context, held for human approval before reaching any prospect.",
    },
  ];

  for (const c of cards) {
    addCard(s, c.x, 1.3, 2.8, 3.5);
    s.addText(c.header, {
      x: c.x + 0.15, y: 1.45, w: 2.5, h: 0.35,
      fontSize: 15,
      bold: true,
      color: C.teal,
      fontFace: "Trebuchet MS",
    });
    s.addText(c.body, {
      x: c.x + 0.12, y: 1.9, w: 2.55, h: 2.7,
      fontSize: 12,
      color: C.nearBlack,
      fontFace: "Calibri",
      bullet: false,
      valign: "top",
      wrap: true,
    });
  }

  // Stats row
  const stats = ["3 Agents", "3 Sources", "1 Command"];
  const statX = [0.4, 3.7, 7.0];
  for (let i = 0; i < 3; i++) {
    s.addShape(pres.ShapeType.rect, {
      x: statX[i], y: 5.05, w: 2.2, h: 0.4,
      fill: { color: C.white },
      line: { color: C.teal, width: 1.5 },
    });
    s.addText(stats[i], {
      x: statX[i], y: 5.05, w: 2.2, h: 0.4,
      fontSize: 13,
      bold: true,
      color: C.teal,
      align: "center",
      valign: "middle",
      fontFace: "Trebuchet MS",
    });
  }
}

// ── SLIDE 3 — System Architecture ────────────────────────────────────────────
{
  const s = lightSlide();
  addLightTitle(s, "System Architecture");

  // ── Source boxes (left half, above Research Agent) ──
  // Three compact boxes whose centers all fall within Research Agent width
  const srcLabels = ["DuckDuckGo", "Naukri.com", "Indeed.in"];
  const srcX = [0.4, 1.78, 3.16];
  const srcW = 1.2;
  const srcCY = 1.05; // top-left y of source boxes
  const srcH = 0.38;
  for (let i = 0; i < 3; i++) {
    flowBox(s, srcLabels[i], srcX[i], srcCY, srcW, srcH, C.teal, C.white, 10);
    // Arrow down from each source center to Research Agent top
    arrowDown(s, srcX[i] + srcW / 2, srcCY + srcH, 0.22);
  }

  // Lead Discovery label between sources and Research Agent
  s.addText("Lead Discovery", {
    x: 0.4, y: 1.09, w: 4.0, h: 0.22,
    fontSize: 8, color: C.mutedDark, fontFace: "Calibri", italic: true, align: "center",
  });

  // ── Research Agent (spans all three source centers) ──
  const raX = 0.4, raY = 1.65, raW = 4.0, raH = 0.42;
  flowBox(s, "Research Agent", raX, raY, raW, raH, C.navy, C.white, 13);

  // Arrow right: Research → Qualification
  arrowRight(s, raX + raW, raY + raH / 2, 0.55);

  // ── Qualification Agent (right half) ──
  const qaX = 4.95, qaY = raY, qaW = 4.65, qaH = raH;
  flowBox(s, "Qualification Agent", qaX, qaY, qaW, qaH, C.navy, C.white, 12);

  // ── Branch from Qualification ──
  // score >= 5: arrow straight down on right side of Qual
  const salX = 6.8, salY = 3.05, salW = 2.8, salH = 0.42;
  arrowDown(s, qaX + qaW * 0.7, qaY + qaH, 0.58);
  s.addText("score >= 5", {
    x: qaX + qaW * 0.55, y: qaY + qaH + 0.08, w: 1.5, h: 0.22,
    fontSize: 9, color: C.mint, fontFace: "Calibri", bold: true,
  });

  // score < 5: arrow down on left side of Qual then Discard
  arrowDown(s, qaX + qaW * 0.25, qaY + qaH, 0.58);
  s.addText("score < 5", {
    x: qaX, y: qaY + qaH + 0.08, w: 1.5, h: 0.22,
    fontSize: 9, color: C.red, fontFace: "Calibri", bold: true,
  });
  flowBox(s, "Discard", qaX, salY, 2.0, salH, C.greyFill, C.mutedDark, 11);

  // ── Sales Agent ──
  flowBox(s, "Sales Agent", salX, salY, salW, salH, C.navy, C.white, 12);

  // Arrow down: Sales → Human Review
  arrowDown(s, salX + salW / 2, salY + salH, 0.3);

  // ── Human Review (amber, directly below Sales) ──
  const hrX = salX, hrY = salY + salH + 0.3, hrW = salW, hrH = 0.42;
  flowBox(s, "Human Review (Slack)", hrX, hrY, hrW, hrH, C.amber, C.nearBlack, 11);

  // Approve: arrow down → Outreach Ready
  arrowDown(s, hrX + hrW / 2, hrY + hrH, 0.28);
  s.addText("Approve", {
    x: hrX + hrW / 2 + 0.08, y: hrY + hrH + 0.04, w: 0.9, h: 0.2,
    fontSize: 8, color: C.mint, fontFace: "Calibri", bold: true,
  });
  flowBox(s, "Outreach Ready", hrX, hrY + hrH + 0.28, hrW, 0.38, C.mint, C.nearBlack, 11);

  // ── ChromaDB / pgvector (left lower section) ──
  const dbX = 0.4, dbY = 3.05, dbW = 4.0, dbH = 0.42;
  flowBox(s, "ChromaDB / pgvector", dbX, dbY, dbW, dbH, C.tealLight, C.white, 11);

  // Dashed RAG lines: horizontal from DB right edge to Qual and Sales left edges
  // DB right edge: dbX + dbW = 4.4
  // Qual left edge: qaX = 4.95  → gap = 0.55 (connect with horizontal line at Qual center y)
  dashedLine(s, dbX + dbW, qaY + qaH / 2, 0.55, 0); // horizontal to Qual
  s.addText("RAG", {
    x: 4.4, y: qaY + qaH / 2 - 0.2, w: 0.55, h: 0.2,
    fontSize: 8, color: C.teal, fontFace: "Calibri", bold: true, align: "center",
  });

  // DB right edge to Sales left edge: Sales at salX=6.8, DB right=4.4
  // Draw at Sales mid-y, from DB right edge across
  dashedLine(s, dbX + dbW, salY + salH / 2, salX - (dbX + dbW), 0); // horizontal to Sales
  s.addText("RAG", {
    x: dbX + dbW + 0.05, y: salY + salH / 2 - 0.2, w: 0.6, h: 0.2,
    fontSize: 8, color: C.teal, fontFace: "Calibri", bold: true,
  });

  // Left side async label (rotated)
  s.addText("Celery Async", {
    x: 0.08, y: 2.35, w: 0.9, h: 1.3,
    fontSize: 8, color: C.mutedDark, fontFace: "Calibri", italic: true, rotate: 270,
  });
}

// ── SLIDE 4 — Multi-Source Lead Discovery ─────────────────────────────────────
{
  const s = lightSlide();
  addLightTitle(s, "Multi-Source Lead Discovery");

  s.addText("HR job postings are a buying signal. Companies actively hiring HR staff have active HR budgets.", {
    x: 0.5, y: 0.98, w: 9, h: 0.4,
    fontSize: 13,
    color: C.mutedDark,
    fontFace: "Calibri",
    italic: true,
  });

  const sources = [
    {
      x: 0.4,
      header: "DuckDuckGo Search",
      body: "Keyword-based company discovery. Fast, no API key required, covers news and directories.",
      tag: "Keyword Search",
    },
    {
      x: 3.45,
      header: "Naukri.com",
      body: "Scrapes companies posting HR Manager, HRIS, Payroll roles. Active HR hiring = active HRMS budget.",
      tag: "Buying Signal",
    },
    {
      x: 6.5,
      header: "Indeed.in",
      body: "Same signal from India's second-largest job board. Broader coverage, different company set.",
      tag: "Buying Signal",
    },
  ];

  for (const src of sources) {
    addCard(s, src.x, 1.5, 2.7, 2.8);
    s.addText(src.header, {
      x: src.x + 0.14, y: 1.65, w: 2.5, h: 0.35,
      fontSize: 14,
      bold: true,
      color: C.teal,
      fontFace: "Trebuchet MS",
    });
    s.addText(src.body, {
      x: src.x + 0.12, y: 2.1, w: 2.48, h: 1.5,
      fontSize: 12,
      color: C.nearBlack,
      fontFace: "Calibri",
      wrap: true,
      valign: "top",
    });
    // Tag
    s.addShape(pres.ShapeType.roundRect, {
      x: src.x + 0.12, y: 3.9, w: 1.5, h: 0.28,
      fill: { color: C.teal },
      line: { type: "none" },
      rectRadius: 0.1,
    });
    s.addText(src.tag, {
      x: src.x + 0.12, y: 3.9, w: 1.5, h: 0.28,
      fontSize: 10,
      color: C.white,
      align: "center",
      valign: "middle",
      fontFace: "Calibri",
    });
  }

  // Dedup box
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 4.6, w: 9.2, h: 0.75,
    fill: { color: C.white },
    line: { color: C.teal, width: 1 },
    shadow: mkShadow(),
  });
  s.addText(
    "Domain deduplication via urllib.parse ensures the same company appearing on multiple sources is processed exactly once.",
    {
      x: 0.55, y: 4.62, w: 9.0, h: 0.7,
      fontSize: 12,
      color: C.nearBlack,
      fontFace: "Calibri",
      valign: "middle",
    }
  );
}

// ── SLIDE 5 — Multi-Agent Pipeline ────────────────────────────────────────────
{
  const s = lightSlide();
  addLightTitle(s, "Three Specialized Agents");

  const agents = [
    {
      x: 0.4,
      headerFill: C.teal,
      headerText: "Research Agent",
      headerTextColor: C.white,
      body: [
        "Calls search_companies_multi_source()",
        "Scrapes company websites",
        "Calls Llama 3.1 with LeadExtraction schema",
        "Returns structured company data",
      ],
    },
    {
      x: 3.45,
      headerFill: C.navy,
      headerText: "Qualification Agent",
      headerTextColor: C.white,
      body: [
        "Retrieves product context from ChromaDB",
        "Calls LLM with QualificationResult schema",
        "Score 0-10 with reasoning + signals",
        "Score >= 5.0 advances, rest discarded",
      ],
    },
    {
      x: 6.5,
      headerFill: C.mint,
      headerText: "Sales Agent",
      headerTextColor: C.nearBlack,
      body: [
        "RAG-grounded email generation",
        "Hallucination guard on all product claims",
        "Routes to pending_review (Slack) or outreach_ready",
      ],
    },
  ];

  for (const ag of agents) {
    // Card body
    addCard(s, ag.x, 1.2, 2.8, 3.5);

    // Header area fill
    s.addShape(pres.ShapeType.rect, {
      x: ag.x + 0.06, y: 1.2, w: 2.74, h: 0.55,
      fill: { color: ag.headerFill },
      line: { type: "none" },
    });
    s.addText(ag.headerText, {
      x: ag.x + 0.1, y: 1.2, w: 2.65, h: 0.55,
      fontSize: 14,
      bold: true,
      color: ag.headerTextColor,
      fontFace: "Trebuchet MS",
      valign: "middle",
    });

    // Body bullets
    const bulletItems = ag.body.map((b) => ({ text: b, options: { bullet: true, fontSize: 11, color: C.nearBlack, fontFace: "Calibri", paraSpaceAfter: 4 } }));
    s.addText(bulletItems, {
      x: ag.x + 0.15, y: 1.85, w: 2.55, h: 2.7,
      valign: "top",
    });
  }

  // Arrows between cards
  arrowRight(s, 3.25, 2.95, 0.2);
  arrowRight(s, 6.3, 2.95, 0.2);

  // Supervisor note
  s.addText(
    "Supervisor (LangGraph StateGraph) routes between agents based on shared state. Low-quality leads exit at Qualification -- no wasted LLM calls.",
    {
      x: 0.4, y: 4.9, w: 9.2, h: 0.55,
      fontSize: 11,
      color: C.mutedDark,
      fontFace: "Calibri",
      align: "center",
      italic: true,
    }
  );
}

// ── SLIDE 6 — RAG Pipeline ────────────────────────────────────────────────────
{
  const s = lightSlide();
  addLightTitle(s, "RAG Knowledge Pipeline");

  // 5-step horizontal flow
  const steps = [
    { label: "Scrape humanmaximizer.com", fill: C.teal },
    { label: "Chunk 500 tokens\n50 overlap", fill: C.teal },
    { label: "Embed:\nall-MiniLM-L6-v2", fill: C.teal },
    { label: "Store:\nChromaDB or pgvector\n(HNSW index)", fill: C.teal },
    { label: "Semantic retrieval\nat qualify + outreach", fill: C.navy },
  ];

  const boxW = 1.7;
  const gap = 0.12;
  const startX = 0.35;
  const rowY = 1.05;
  const boxH = 0.8;

  for (let i = 0; i < steps.length; i++) {
    const x = startX + i * (boxW + gap + 0.25);
    flowBox(s, steps[i].label, x, rowY, boxW, boxH, steps[i].fill, C.white, 9);
    if (i < steps.length - 1) {
      arrowRight(s, x + boxW, rowY + boxH / 2, 0.25);
    }
  }

  // Two-column section below
  // Left: Why RAG
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 2.1, w: 4.4, h: 3.2,
    fill: { color: C.white },
    line: { color: "E2E8F0", width: 0.5 },
    shadow: mkShadow(),
  });
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 2.1, w: 0.06, h: 3.2,
    fill: { color: C.teal },
    line: { type: "none" },
  });
  s.addText("Why RAG over fine-tuning (v1)", {
    x: 0.6, y: 2.2, w: 4.1, h: 0.4,
    fontSize: 14, bold: true, color: C.teal, fontFace: "Trebuchet MS",
  });
  const ragBullets = [
    { text: "Grounds every claim in real product docs -- no hallucinated features", options: { bullet: true, fontSize: 11, color: C.nearBlack, fontFace: "Calibri", paraSpaceAfter: 5 } },
    { text: "No training data or GPU time needed to get started", options: { bullet: true, fontSize: 11, color: C.nearBlack, fontFace: "Calibri", paraSpaceAfter: 5 } },
    { text: "Instant updates when product docs change -- just re-ingest", options: { bullet: true, fontSize: 11, color: C.nearBlack, fontFace: "Calibri", paraSpaceAfter: 5 } },
    { text: "Same interface for both ChromaDB and pgvector backends", options: { bullet: true, fontSize: 11, color: C.nearBlack, fontFace: "Calibri", paraSpaceAfter: 5 } },
  ];
  s.addText(ragBullets, { x: 0.55, y: 2.7, w: 4.1, h: 2.4, valign: "top" });

  // Right: Hallucination Guard
  s.addShape(pres.ShapeType.rect, {
    x: 5.1, y: 2.1, w: 4.5, h: 3.2,
    fill: { color: C.white },
    line: { color: "E2E8F0", width: 0.5 },
    shadow: mkShadow(),
  });
  s.addShape(pres.ShapeType.rect, {
    x: 5.1, y: 2.1, w: 0.06, h: 3.2,
    fill: { color: C.amber },
    line: { type: "none" },
  });
  s.addText("Hallucination Guard", {
    x: 5.28, y: 2.2, w: 4.2, h: 0.4,
    fontSize: 14, bold: true, color: C.amber, fontFace: "Trebuchet MS",
  });
  const hallBullets = [
    { text: "Layer 1: Word overlap -- email vs. retrieved context chunks", options: { bullet: true, fontSize: 11, color: C.nearBlack, fontFace: "Calibri", paraSpaceAfter: 5 } },
    { text: "Layer 2: Claim extraction -- isolate all factual assertions", options: { bullet: true, fontSize: 11, color: C.nearBlack, fontFace: "Calibri", paraSpaceAfter: 5 } },
    { text: "Layer 3: Confidence scoring -- verify each claim vs. context", options: { bullet: true, fontSize: 11, color: C.nearBlack, fontFace: "Calibri", paraSpaceAfter: 5 } },
    { text: "All product claims verified before email is queued for review", options: { bullet: true, fontSize: 11, color: C.nearBlack, fontFace: "Calibri", paraSpaceAfter: 5 } },
  ];
  s.addText(hallBullets, { x: 5.25, y: 2.7, w: 4.2, h: 2.4, valign: "top" });
}

// ── SLIDE 7 — Structured Output ───────────────────────────────────────────────
{
  const s = lightSlide();
  addLightTitle(s, "Structured LLM Output via Pydantic");

  // Left: Before
  s.addText("Before: Manual JSON Parsing", {
    x: 0.4, y: 1.0, w: 4.2, h: 0.4,
    fontSize: 13, bold: true, color: C.red, fontFace: "Trebuchet MS",
  });
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 1.42, w: 4.2, h: 1.5,
    fill: { color: C.codeLight },
    line: { color: "CBD5E1", width: 0.5 },
  });
  s.addText(
    "raw = self.call_llm(prompt)\nparsed = self.parse_json_response(raw)\n# brittle: fails on LLM formatting quirks\n# two-pass fixer for control characters\n# no schema enforcement",
    {
      x: 0.55, y: 1.52, w: 4.0, h: 1.3,
      fontSize: 10,
      color: "1E293B",
      fontFace: "Courier New",
      valign: "top",
    }
  );

  // Right: After
  s.addText("After: .with_structured_output()", {
    x: 5.0, y: 1.0, w: 4.6, h: 0.4,
    fontSize: 13, bold: true, color: C.teal, fontFace: "Trebuchet MS",
  });
  s.addShape(pres.ShapeType.rect, {
    x: 5.0, y: 1.42, w: 4.6, h: 1.5,
    fill: { color: C.codeTeal },
    line: { color: C.teal, width: 0.5 },
  });
  s.addText(
    "result = self.call_llm_structured(\n    prompt, QualificationResult\n)\nscore = result.score   # float, validated\nsignals = result.key_signals  # List[str]",
    {
      x: 5.15, y: 1.52, w: 4.3, h: 1.3,
      fontSize: 10,
      color: C.nearBlack,
      fontFace: "Courier New",
      valign: "top",
    }
  );

  // Schema cards
  // LeadExtraction
  addCard(s, 0.4, 3.1, 4.2, 2.15);
  s.addText("LeadExtraction schema", {
    x: 0.6, y: 3.18, w: 3.9, h: 0.35,
    fontSize: 12, bold: true, color: C.teal, fontFace: "Trebuchet MS",
  });
  s.addText(
    "company_name: str\ndomain: str\nindustry: str\nemployee_count: Optional[int]\ntech_stack: List[str]\ncontact_info: Optional[ContactInfo]",
    {
      x: 0.6, y: 3.58, w: 3.9, h: 1.55,
      fontSize: 10,
      color: C.nearBlack,
      fontFace: "Courier New",
      valign: "top",
    }
  );

  // QualificationResult
  addCard(s, 5.0, 3.1, 4.6, 2.15);
  s.addText("QualificationResult schema", {
    x: 5.2, y: 3.18, w: 4.2, h: 0.35,
    fontSize: 12, bold: true, color: C.teal, fontFace: "Trebuchet MS",
  });
  s.addText(
    "score: float  # 0.0-10.0\nqualified: bool\nreasoning: str\nkey_signals: List[str]\npain_points: List[str]",
    {
      x: 5.2, y: 3.58, w: 4.2, h: 1.55,
      fontSize: 10,
      color: C.nearBlack,
      fontFace: "Courier New",
      valign: "top",
    }
  );

  // Fallback note
  s.addText(
    "Fallback: if structured output fails, drops back to raw LLM + JSON parser. Never hard-fails.",
    {
      x: 0.4, y: 5.35, w: 9.2, h: 0.3,
      fontSize: 10,
      color: C.mutedDark,
      fontFace: "Calibri",
      italic: true,
      align: "center",
    }
  );
}

// ── SLIDE 8 — Human-in-the-Loop Review ───────────────────────────────────────
{
  const s = lightSlide();
  addLightTitle(s, "Human-in-the-Loop Review");

  s.addText("LLM output should never reach customers without a human checkpoint.", {
    x: 0.5, y: 0.98, w: 9, h: 0.35,
    fontSize: 13, color: C.mutedDark, fontFace: "Calibri", italic: true,
  });

  // Flow: horizontal across the top
  flowBox(s, "Sales Agent\ngenerates email", 0.25, 1.55, 1.8, 0.65, C.navy, C.white, 10);
  arrowRight(s, 2.05, 1.875, 0.3);

  flowBox(s, "SLACK_WEBHOOK\n_URL set?", 2.35, 1.55, 1.6, 0.65, C.teal, C.white, 10);

  // Yes branch
  arrowRight(s, 3.95, 1.875, 0.25);
  s.addText("Yes", { x: 3.75, y: 1.3, w: 0.4, h: 0.22, fontSize: 9, color: C.mint, fontFace: "Calibri", bold: true });

  flowBox(s, "Status:\npending_review", 4.2, 1.55, 1.55, 0.65, C.tealLight, C.white, 10);
  arrowRight(s, 5.75, 1.875, 0.25);

  flowBox(s, "Slack\nnotification sent", 6.0, 1.55, 1.6, 0.65, C.tealLight, C.white, 10);
  arrowRight(s, 7.6, 1.875, 0.25);

  flowBox(s, "Human reads\nlead + email", 7.85, 1.55, 1.8, 0.65, C.amber, C.nearBlack, 10);

  // Approve branch
  arrowDown(s, 8.75, 2.2, 0.45);
  s.addText("Approve", { x: 8.82, y: 2.32, w: 0.8, h: 0.2, fontSize: 9, color: C.mint, fontFace: "Calibri", bold: true });
  flowBox(s, "outreach_ready", 8.15, 2.65, 1.5, 0.38, C.mint, C.nearBlack, 10);

  // Reject branch
  arrowDown(s, 8.15, 2.2, 0.82);
  s.addText("Reject", { x: 7.2, y: 2.62, w: 0.8, h: 0.2, fontSize: 9, color: C.red, fontFace: "Calibri", bold: true });
  flowBox(s, "disqualified", 7.1, 3.02, 1.5, 0.38, C.greyFill, C.mutedDark, 10);

  // No branch (dashed)
  arrowDown(s, 3.15, 2.2, 0.6);
  s.addText("No", { x: 2.5, y: 2.32, w: 0.5, h: 0.2, fontSize: 9, color: C.mutedDark, fontFace: "Calibri", bold: true });
  flowBox(s, "outreach_ready\ndirectly", 2.4, 2.8, 1.5, 0.42, C.mint, C.nearBlack, 10);
  s.addText("zero-config default", {
    x: 2.4, y: 3.22, w: 1.5, h: 0.25,
    fontSize: 9, color: C.mutedDark, fontFace: "Calibri", italic: true, align: "center",
  });

  // Endpoint cards
  const endpoints = [
    "GET /leads/pending-review",
    "POST /leads/{id}/approve",
    "POST /leads/{id}/reject",
  ];
  const epX = [0.4, 3.45, 6.5];
  for (let i = 0; i < 3; i++) {
    s.addShape(pres.ShapeType.rect, {
      x: epX[i], y: 3.75, w: 2.8, h: 0.45,
      fill: { color: C.codeLight },
      line: { color: C.teal, width: 0.8 },
    });
    s.addText(endpoints[i], {
      x: epX[i], y: 3.75, w: 2.8, h: 0.45,
      fontSize: 11,
      color: C.teal,
      fontFace: "Courier New",
      align: "center",
      valign: "middle",
      bold: true,
    });
  }

  // Slack Block Kit note
  s.addText(
    "Slack Block Kit message includes: company name, score, pain points, 250-char email preview, and Approve/Reject action buttons.",
    {
      x: 0.4, y: 4.35, w: 9.2, h: 0.55,
      fontSize: 11, color: C.nearBlack, fontFace: "Calibri",
      wrap: true, valign: "middle",
      fill: { color: C.white },
    }
  );
}

// ── SLIDE 9 — Async Pipeline with Celery ──────────────────────────────────────
{
  const s = lightSlide();
  addLightTitle(s, "Async Pipeline Execution");

  // Left: Default (Sync)
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 1.1, w: 4.4, h: 3.6,
    fill: { color: C.greyFill },
    line: { color: "CBD5E1", width: 0.5 },
    shadow: mkShadow(),
  });
  s.addText("Default (Sync)", {
    x: 0.55, y: 1.2, w: 4.1, h: 0.42,
    fontSize: 15, bold: true, color: C.nearBlack, fontFace: "Trebuchet MS",
  });
  s.addText(
    "No Celery worker needed. POST /generate-leads runs the pipeline inline and returns results directly. Works out of the box.",
    {
      x: 0.55, y: 1.7, w: 4.1, h: 0.8,
      fontSize: 11, color: C.nearBlack, fontFace: "Calibri", wrap: true,
    }
  );

  // Sync flow
  const syncSteps = ["Client", "FastAPI", "Pipeline", "Response"];
  for (let i = 0; i < syncSteps.length; i++) {
    flowBox(s, syncSteps[i], 0.55 + i * 1.0, 2.7, 0.85, 0.38, C.teal, C.white, 9);
    if (i < syncSteps.length - 1) {
      arrowRight(s, 0.55 + i * 1.0 + 0.85, 2.89, 0.15);
    }
  }

  // Right: Full Stack (Async)
  s.addShape(pres.ShapeType.rect, {
    x: 5.0, y: 1.1, w: 4.7, h: 3.6,
    fill: { color: C.codeTeal },
    line: { color: C.teal, width: 0.8 },
    shadow: mkShadow(),
  });
  s.addText("Full Stack (Async)", {
    x: 5.15, y: 1.2, w: 4.4, h: 0.42,
    fontSize: 15, bold: true, color: C.teal, fontFace: "Trebuchet MS",
  });
  s.addText(
    "With Celery worker running. POST /generate-leads queues the job and returns run_id immediately. Client polls /pipeline-status/{run_id}.",
    {
      x: 5.15, y: 1.7, w: 4.4, h: 0.82,
      fontSize: 11, color: C.nearBlack, fontFace: "Calibri", wrap: true,
    }
  );

  // Async flow row 1
  const asyncSteps1 = ["Client", "FastAPI", "Redis Queue", "Celery Worker", "leads.json"];
  const asyncStartX = 5.1;
  const asyncW = 0.75;
  const asyncGap = 0.12;
  for (let i = 0; i < asyncSteps1.length; i++) {
    const ax = asyncStartX + i * (asyncW + asyncGap + 0.1);
    flowBox(s, asyncSteps1[i], ax, 2.65, asyncW, 0.35, C.navy, C.white, 8);
    if (i < asyncSteps1.length - 1) {
      arrowRight(s, ax + asyncW, 2.825, 0.12);
    }
  }

  // Async flow row 2: poll
  flowBox(s, "Client", 5.1, 3.2, 0.75, 0.35, C.navy, C.white, 8);
  arrowRight(s, 5.85, 3.375, 0.12);
  flowBox(s, "GET /pipeline-status/{run_id}", 5.97, 3.2, 2.1, 0.35, C.teal, C.white, 8);
  arrowRight(s, 8.07, 3.375, 0.12);
  flowBox(s, "Result", 8.19, 3.2, 0.75, 0.35, C.mint, C.nearBlack, 8);

  // Redis DB note
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 4.9, w: 9.2, h: 0.55,
    fill: { color: C.white },
    line: { color: C.teal, width: 1 },
    shadow: mkShadow(),
  });
  s.addText(
    "Redis DB separation: DB 0 = LLM cache + dedup  |  DB 1 = Celery broker + results  |  docker compose --profile full up",
    {
      x: 0.55, y: 4.9, w: 9.0, h: 0.55,
      fontSize: 11, color: C.nearBlack, fontFace: "Calibri", valign: "middle", align: "center",
    }
  );
}

// ── SLIDE 10 — pgvector at Scale ──────────────────────────────────────────────
{
  const s = lightSlide();
  addLightTitle(s, "Vector Store: ChromaDB vs pgvector");

  const tableRows = [
    ["Feature", "ChromaDB (default)", "pgvector (production)"],
    ["Infrastructure", "Embedded, file-based", "PostgreSQL service"],
    ["Transactions", "None", "Full ACID"],
    ["SQL queries", "Not supported", "Native joins with lead data"],
    ["Backup", "Copy directory", "pg_dump"],
    ["Monitoring", "Custom", "Standard pg tooling"],
    ["Index type", "HNSW", "HNSW (same performance)"],
    ["Activate", "Default", "USE_PGVECTOR=true"],
  ];

  const tableData = tableRows.map((row, rowIdx) => {
    return row.map((cell, colIdx) => ({
      text: cell,
      options: {
        bold: rowIdx === 0,
        color: rowIdx === 0 ? C.white : C.nearBlack,
        fill: rowIdx === 0
          ? C.teal
          : rowIdx % 2 === 0
            ? C.altRow
            : C.white,
        fontSize: rowIdx === 0 ? 13 : 11,
        fontFace: rowIdx === 0 ? "Trebuchet MS" : "Calibri",
        align: colIdx === 0 ? "left" : "center",
        valign: "middle",
      },
    }));
  });

  s.addTable(tableData, {
    x: 0.4, y: 1.05, w: 9.2,
    rowH: 0.38,
    border: { type: "solid", color: "CBD5E1", pt: 0.5 },
  });

  // Config flag note
  s.addShape(pres.ShapeType.rect, {
    x: 0.4, y: 4.22, w: 9.2, h: 0.88,
    fill: { color: C.white },
    line: { color: C.teal, width: 1 },
    shadow: mkShadow(),
  });
  s.addText(
    "One config flag to switch: USE_PGVECTOR=true in .env\nThe PgVectorStore class is a drop-in replacement -- same add_documents() and similarity_search() interface.",
    {
      x: 0.55, y: 4.24, w: 9.0, h: 0.84,
      fontSize: 11, color: C.nearBlack, fontFace: "Calibri", valign: "middle",
    }
  );
}

// ── SLIDE 11 — Security and Production ───────────────────────────────────────
{
  const s = lightSlide();
  addLightTitle(s, "Production-Grade Features");

  const featureCards = [
    {
      x: 0.4, y: 1.1,
      header: "Prompt Injection Guard",
      headerColor: C.red,
      body: "Regex scan on all keyword input. Allowlist of safe characters enforced before any LLM call. Hard-stop on patterns like 'ignore instructions' or SQL keywords (DROP, SELECT, INSERT).",
    },
    {
      x: 5.0, y: 1.1,
      header: "Rate Limiting",
      headerColor: C.amber,
      body: "Redis atomic INCR with TTL. 10 requests/min per IP address. No race conditions under horizontal scaling. Returns HTTP 429 with Retry-After header.",
    },
    {
      x: 0.4, y: 3.2,
      header: "Lead Deduplication",
      headerColor: C.teal,
      body: "Redis 24-hour key per company name. Prevents the same company from being processed twice in the same pipeline run or across runs on the same day.",
    },
    {
      x: 5.0, y: 3.2,
      header: "LLM Response Caching",
      headerColor: C.teal,
      body: "SHA-256 keyed Redis cache. Identical company queries return in ~5ms instead of ~2s. Full prompt hashed (not just prefix) -- precise cache key, no false hits.",
    },
  ];

  for (const fc of featureCards) {
    addCard(s, fc.x, fc.y, 4.3, 1.9);
    s.addText(fc.header, {
      x: fc.x + 0.15, y: fc.y + 0.12, w: 4.0, h: 0.38,
      fontSize: 14, bold: true, color: fc.headerColor, fontFace: "Trebuchet MS",
    });
    s.addText(fc.body, {
      x: fc.x + 0.12, y: fc.y + 0.58, w: 4.1, h: 1.2,
      fontSize: 11, color: C.nearBlack, fontFace: "Calibri", wrap: true, valign: "top",
    });
  }
}

// ── SLIDE 12 — Observability ──────────────────────────────────────────────────
{
  const s = lightSlide();
  addLightTitle(s, "Two-Tier Observability");

  // Left: LangSmith
  addCard(s, 0.4, 1.05, 4.4, 4.3);
  s.addText("LangSmith (LLM-level)", {
    x: 0.6, y: 1.15, w: 4.1, h: 0.42,
    fontSize: 15, bold: true, color: C.teal, fontFace: "Trebuchet MS",
  });
  const langsmithBullets = [
    { text: "Every prompt, response, token count, and latency traced automatically", options: { bullet: true, fontSize: 11, color: C.nearBlack, fontFace: "Calibri", paraSpaceAfter: 6 } },
    { text: "Works because we use langchain_groq.ChatGroq (a LangChain Runnable), not the raw Groq SDK", options: { bullet: true, fontSize: 11, color: C.nearBlack, fontFace: "Calibri", paraSpaceAfter: 6 } },
    { text: "Full LangGraph run visible as a parent trace with per-agent child spans", options: { bullet: true, fontSize: 11, color: C.nearBlack, fontFace: "Calibri", paraSpaceAfter: 6 } },
    { text: "Zero extra instrumentation -- set LANGCHAIN_API_KEY and it just works", options: { bullet: true, fontSize: 11, color: C.nearBlack, fontFace: "Calibri", paraSpaceAfter: 6 } },
  ];
  s.addText(langsmithBullets, { x: 0.55, y: 1.65, w: 4.1, h: 3.5, valign: "top" });

  // Right: Custom Metrics
  addCard(s, 5.1, 1.05, 4.5, 4.3);
  s.addText("Custom Metrics (Business-level)", {
    x: 5.3, y: 1.15, w: 4.2, h: 0.42,
    fontSize: 15, bold: true, color: C.navy, fontFace: "Trebuchet MS",
  });
  const metricsBullets = [
    { text: "Pipeline stage latency logged to JSONL per run", options: { bullet: true, fontSize: 11, color: C.nearBlack, fontFace: "Calibri", paraSpaceAfter: 6 } },
    { text: "Hallucination warning count per run tracked and exposed", options: { bullet: true, fontSize: 11, color: C.nearBlack, fontFace: "Calibri", paraSpaceAfter: 6 } },
    { text: "Lead quality score distribution across all pipeline runs", options: { bullet: true, fontSize: 11, color: C.nearBlack, fontFace: "Calibri", paraSpaceAfter: 6 } },
    { text: "Correlation IDs link every agent log entry in a single run", options: { bullet: true, fontSize: 11, color: C.nearBlack, fontFace: "Calibri", paraSpaceAfter: 6 } },
    { text: "GET /metrics aggregates stats across all runs in one call", options: { bullet: true, fontSize: 11, color: C.nearBlack, fontFace: "Calibri", paraSpaceAfter: 6 } },
  ];
  s.addText(metricsBullets, { x: 5.28, y: 1.65, w: 4.2, h: 3.5, valign: "top" });
}

// ── SLIDE 13 — Tech Stack ─────────────────────────────────────────────────────
{
  const s = lightSlide();
  addLightTitle(s, "Tech Stack");

  const stackRows = [
    ["Component", "Technology"],
    ["LLM", "Llama 3.1 70B (via Groq API)"],
    ["LLM Client", "langchain_groq.ChatGroq"],
    ["Orchestration", "LangGraph StateGraph (Supervisor pattern)"],
    ["Lead Sources", "DuckDuckGo, Naukri.com, Indeed.in"],
    ["Structured Output", "Pydantic v2 + .with_structured_output()"],
    ["Vector Store", "ChromaDB (default) / pgvector (production)"],
    ["Embeddings", "all-MiniLM-L6-v2 (sentence-transformers)"],
    ["Caching", "Redis (LLM cache + dedup, DB 0)"],
    ["Async Queue", "Celery + Redis (DB 1)"],
    ["Human Review", "Slack Webhooks + FastAPI endpoints"],
    ["API", "FastAPI + Uvicorn"],
    ["Tracing", "LangSmith (automatic via LangChain)"],
    ["Containerization", "Docker Compose (default + full profiles)"],
  ];

  const tableData = stackRows.map((row, rowIdx) => {
    return row.map((cell, colIdx) => ({
      text: cell,
      options: {
        bold: rowIdx === 0,
        color: rowIdx === 0 ? C.white : C.nearBlack,
        fill: rowIdx === 0
          ? C.teal
          : rowIdx % 2 === 0
            ? C.altRow
            : C.white,
        fontSize: rowIdx === 0 ? 13 : 11,
        fontFace: rowIdx === 0 ? "Trebuchet MS" : "Calibri",
        align: colIdx === 0 ? "left" : "left",
        valign: "middle",
      },
    }));
  });

  s.addTable(tableData, {
    x: 0.4, y: 1.05, w: 9.2,
    rowH: 0.31,
    border: { type: "solid", color: "CBD5E1", pt: 0.5 },
    colW: [2.5, 6.7],
  });
}

// ── SLIDE 14 — Architectural Decisions (dark bg) ──────────────────────────────
{
  const s = darkSlide();

  s.addText("Key Architectural Decisions", {
    x: 0.5, y: 0.25, w: 9, h: 0.6,
    fontSize: 32, bold: true, color: C.white, fontFace: "Trebuchet MS",
  });

  const decisions = [
    {
      title: "Supervisor over sequential",
      body: "Conditional routing lets any agent exit early. Low-quality leads are discarded at Qualification -- no downstream LLM calls wasted.",
    },
    {
      title: "ChatGroq over raw Groq SDK",
      body: "LangSmith tracing is automatic for LangChain Runnables. Using the raw SDK would require manual instrumentation for every call.",
    },
    {
      title: "Structured output over JSON parsing",
      body: "Schema enforced at the LLM level via Pydantic. Fallback preserves reliability -- the pipeline never hard-fails on a bad response.",
    },
    {
      title: "Multi-source search strategy",
      body: "HR job postings are a buying intent signal, not just keyword matches. Three sources with dedup gives coverage without processing duplicates.",
    },
    {
      title: "Human review before outreach",
      body: "LLM-generated emails must never reach customers unreviewed. Slack checkpoint is mandatory when SLACK_WEBHOOK_URL is set.",
    },
    {
      title: "pgvector over ChromaDB at scale",
      body: "Fewer services to run, ACID transactions, standard SQL tooling, and native joins with lead data. Same HNSW index performance.",
    },
  ];

  const positions = [
    { x: 0.4,  y: 1.0 },
    { x: 3.45, y: 1.0 },
    { x: 6.5,  y: 1.0 },
    { x: 0.4,  y: 3.15 },
    { x: 3.45, y: 3.15 },
    { x: 6.5,  y: 3.15 },
  ];

  for (let i = 0; i < decisions.length; i++) {
    const d = decisions[i];
    const p = positions[i];
    addDarkCard(s, p.x, p.y, 2.8, 2.0);
    s.addText(d.title, {
      x: p.x + 0.15, y: p.y + 0.12, w: 2.55, h: 0.45,
      fontSize: 12, bold: true, color: C.teal, fontFace: "Trebuchet MS",
    });
    s.addText(d.body, {
      x: p.x + 0.12, y: p.y + 0.62, w: 2.58, h: 1.25,
      fontSize: 10, color: C.nearBlack, fontFace: "Calibri", wrap: true, valign: "top",
    });
  }
}

// ── SLIDE 15 — Closing (dark bg) ──────────────────────────────────────────────
{
  const s = darkSlide();

  // Left strip
  s.addShape(pres.ShapeType.rect, {
    x: 0, y: 0, w: 0.18, h: 5.625,
    fill: { color: C.teal },
    line: { type: "none" },
  });

  s.addText("Built for Scale. Designed for Review.", {
    x: 0.4, y: 1.8, w: 9, h: 1.0,
    fontSize: 36, bold: true, color: C.white, fontFace: "Trebuchet MS",
  });

  s.addText("Every architectural decision has a reason. Every LLM output has a human checkpoint.", {
    x: 0.4, y: 2.9, w: 8.5, h: 0.55,
    fontSize: 16, color: C.muted, fontFace: "Calibri",
  });

  s.addText("github.com/PriyanshuGeTRekT/AI-Lead-Generation-Research-Agent-", {
    x: 0.4, y: 3.5, w: 8.5, h: 0.4,
    fontSize: 13, color: C.mint, fontFace: "Calibri",
  });

  s.addText("Priyanshu", {
    x: 7.5, y: 5.1, w: 2.3, h: 0.35,
    fontSize: 12, color: C.mutedDark, fontFace: "Calibri", align: "right",
  });
}

// ── Save ──────────────────────────────────────────────────────────────────────
pres
  .writeFile({ fileName: "C:\\Users\\priya\\Documents\\ai-lead-gen\\AI_Lead_Gen_Architecture.pptx" })
  .then(() => {
    console.log("SUCCESS: AI_Lead_Gen_Architecture.pptx written.");
  })
  .catch((err) => {
    console.error("ERROR:", err);
    process.exit(1);
  });
