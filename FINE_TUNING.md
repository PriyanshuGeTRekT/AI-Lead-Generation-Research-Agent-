# Fine-Tuning Strategy for the Qualification Agent

The current system uses few-shot prompting with RAG to score leads. `QualificationAgent` retrieves the top 4 chunks from the ChromaDB HRMS knowledge base, injects them into `QUALIFICATION_PROMPT`, and calls `llama-3.1-8b-instant` via Groq to get back a `QualificationResult` (score, reasoning, key_signals, recommended_action). This works well at launch because you have no labeled data yet. RAG grounding keeps scores coherent with actual product features and prevents hallucinated capabilities. Fine-tuning only pays off once you have enough human-labeled examples from your actual sales context — real decisions made by people who know your ICP, not synthetic examples.

---

## When to Fine-Tune

Fine-tuning the qualification agent is worth the effort when all three of these are true:

**1. You have 200+ human-labeled decisions from actual sales reps.**

Not just any 200 examples. They need to come from people who understand your ICP: what "good" looks like for HumanMaximizer HRMS, which industries you close, which company sizes stall in procurement. Every Approve/Reject click in Slack is one labeled example. At 5–10 leads per run and a few runs per week, you reach 200 examples in 2–4 months of real usage.

**2. The RAG-based scores are systematically wrong for your market.**

If you pull your labeled leads and plot LLM score vs. human decision, you might see a pattern: IT services companies consistently overscored, manufacturing companies with 50+ plants consistently underscored. That's a bias baked into Llama 3's pretraining that RAG context alone can't fix. A fine-tuned model learns your specific scoring calibration.

**3. You want scores grounded in your customer profile, not general LLM reasoning.**

The base model knows HRMS generically. It does not know that your best customers are mid-market manufacturing companies in Tier 1 and Tier 2 Indian cities with blue-collar workforces over 200. A fine-tuned model can learn that signal from your actual data.

If you are at fewer than 200 labeled examples, stay on the current setup. The prompt engineering in `QUALIFICATION_PROMPT` plus RAG retrieval gives you good baseline scores without any training cost.

---

## Data Collection via the Slack Approval Flow

The Slack review step in `notifications/slack.py` is already your data collection mechanism. When a sales rep clicks Approve or Reject on the Slack message, that decision is a labeled training example:

- The lead info sent to `QUALIFICATION_PROMPT` is the **prompt**
- The LLM's `QualificationResult` (`score`, `reasoning`, `key_signals`) plus the human's Approve/Reject decision is the **completion**

You need to log both at the time of the Slack interaction. The approve/reject endpoints at `/leads/{lead_id}/approve` and `/leads/{lead_id}/reject` should write the full example to a JSONL file.

### Dataset Format

Use the Llama 3 chat template format. Unsloth expects conversations, not raw prompt/completion strings, because Llama 3 instruction models were trained with special tokens (`<|begin_of_text|>`, `<|start_header_id|>`, etc.) that the chat template handles. If you pass raw strings, the model never learns to respond in instruction-following mode.

```json
{
  "conversations": [
    {
      "from": "human",
      "value": "Qualify this lead for HumanMaximizer HRMS software:\n\nCompany: Mahindra & Mahindra\nIndustry: Automotive Manufacturing\nEmployees: 40,000\nLocation: Mumbai, India\nPain Points: Manual attendance tracking, multiple plant HR policies, high blue-collar turnover\n\nProduct context: HumanMaximizer offers unified HRMS with attendance automation, multi-site policy management, and workforce analytics.\n\nScore this lead from 0-10 with reasoning."
    },
    {
      "from": "gpt",
      "value": "{\"score\": 8.5, \"reasoning\": \"Large manufacturing company with explicit pain points matching HumanMaximizer core features. Multi-site operations and blue-collar workforce are strong HRMS buying signals. Decision maker likely VP HR or CHRO.\", \"key_signals\": [\"40k employees\", \"multi-plant operations\", \"manual attendance\"], \"recommended_action\": \"outreach\"}"
    }
  ]
}
```

The `"from": "gpt"` label is Unsloth's convention for the assistant turn, even when you are training Llama. `get_chat_template("llama-3")` maps it to the correct Llama 3 special tokens at tokenization time.

Note the field names in the completion: `score`, `reasoning`, `key_signals`, `recommended_action` — these must match the `QualificationResult` Pydantic schema exactly. Using the wrong field names here would cause the fine-tuned model to return wrong keys, just like the prompt/schema mismatch that was fixed during development.

Store one JSON object per line in `data/training_leads.jsonl`. When a human Rejects a lead the LLM scored 7+, that is an especially valuable example because it shows the model where its confidence was wrong. Include those — they are more informative than the easy cases.

---

## Training Setup with Unsloth

### Hardware

You need a GPU with at least 16GB VRAM. An RTX 3090 (24GB) works fine for Llama 3.1 8B with QLoRA. With 4-bit quantization, the base model weights take roughly 5GB, leaving ~11GB for LoRA adapter parameters and optimizer state. An A100 40GB is faster but not required for 200–500 examples.

### Install

```bash
pip install unsloth
pip install torch transformers datasets trl peft
```

If you are on CUDA 12.1:

```bash
pip install unsloth[cu121]
```

### Training Script

```python
from unsloth import FastLanguageModel, get_chat_template
from trl import SFTTrainer
from transformers import TrainingArguments
from datasets import Dataset

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="unsloth/Meta-Llama-3.1-8B-Instruct",
    max_seq_length=2048,
    load_in_4bit=True,  # QLoRA: 4-bit base weights + full-precision LoRA adapters
)

model = FastLanguageModel.get_peft_model(
    model,
    r=16,              # LoRA rank
    lora_alpha=32,
    target_modules=["q_proj", "v_proj"],
    lora_dropout=0.05,
)

# Apply the Llama 3 chat template so conversations map to correct special tokens
tokenizer = get_chat_template(tokenizer, chat_template="llama-3")

# Load your Slack-collected labeled leads
dataset = Dataset.from_json("data/training_leads.jsonl")

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
    dataset_text_field="conversations",
    max_seq_length=2048,
    args=TrainingArguments(
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        warmup_steps=20,
        num_train_epochs=3,
        learning_rate=2e-4,
        output_dir="./fine_tuned_qualification",
        fp16=True,
    ),
)
trainer.train()
model.save_pretrained("./fine_tuned_qualification")
tokenizer.save_pretrained("./fine_tuned_qualification")
```

### Key Hyperparameters

- `r=16`: LoRA rank; higher means more trainable parameters and better quality but more VRAM. 16 is the right default for 200–500 examples.
- `lora_alpha=32`: scaling factor applied to LoRA updates; convention is 2x the rank.
- `num_train_epochs=3`: enough passes for 200–500 examples without memorizing them. Go to 5 only if eval loss keeps dropping.
- `learning_rate=2e-4`: standard QLoRA rate. Drop to 1e-4 if training loss oscillates.
- `target_modules=["q_proj", "v_proj"]`: adapts the query and value projections, which control how attention weights are computed. This is where scoring calibration lives.

---

## How to Use the Fine-Tuned Model

After training you have a LoRA adapter saved to `./fine_tuned_qualification`. You need to serve it locally and point the pipeline at it. Two options:

### Option A — Ollama (easiest for development)

Convert the merged model to GGUF format and load it into Ollama:

```bash
# Merge LoRA adapters into base weights first
python -c "
from unsloth import FastLanguageModel
model, tokenizer = FastLanguageModel.from_pretrained('./fine_tuned_qualification')
model.save_pretrained_merged('./merged_qualification', tokenizer, save_method='merged_16bit')
"

# Convert to GGUF (requires llama.cpp)
python llama.cpp/convert_hf_to_gguf.py ./merged_qualification --outfile qualification.gguf

# Create an Ollama Modelfile
echo 'FROM ./qualification.gguf' > Modelfile
ollama create qualification-agent -f Modelfile
```

Then in `agents/base.py`, swap `ChatGroq` for `ChatOllama`:

```python
from langchain_ollama import ChatOllama
llm = ChatOllama(model="qualification-agent", temperature=0.1)
```

The `GROQ_MODEL` env var becomes irrelevant for the qualification step. You can keep Groq for the Sales Agent (email writing) and run the qualification model locally.

### Option B — vLLM (for production)

vLLM serves the fine-tuned model behind an OpenAI-compatible API endpoint:

```bash
python -m vllm.entrypoints.openai.api_server \
  --model ./fine_tuned_qualification \
  --port 8001 \
  --served-model-name qualification-agent
```

Update `agents/base.py` to use `ChatOpenAI` with `base_url="http://localhost:8001/v1"` for the qualification path. The `QualificationResult` structured output schema in `models/schemas.py` does not change — field names `score`, `reasoning`, `key_signals`, `recommended_action` remain identical.

---

## Evaluation

Before deploying the fine-tuned model, verify it is actually better than the baseline.

**Split your labeled data**: hold out 20% of examples before training. If you have 250 labeled leads, train on 200, test on 50. The test set should be random, not chronologically last (recent leads may be from a different campaign with different characteristics).

**Primary metric**: on the 50 held-out examples, what percentage of the fine-tuned model's qualification decisions (Approve if score ≥ 5.0, Reject if score < 5.0) match the human decision? Compare this against the same metric for the current RAG-only baseline on the same 50 examples.

**Focus on the edge cases**: leads where the LLM scored 4.0–6.0. These are where RAG-based reasoning is weakest because the signal is ambiguous. Fine-tuning should move the needle most in this range. If the fine-tuned model is more accurate on scores 4–6 but the same on clear accepts and clear rejects, that is still a win — those borderline cases are where human review time is spent.

**Check score distribution**: after deploying the fine-tuned model, compare the distribution of qualification scores across 2–3 runs against the baseline distribution. If the fine-tuned model starts scoring everything 7+ or 3–, it has overfit to a subset of your training data.

**Track close rate by cohort**: the only real validation is whether more Approved leads convert. Tag leads processed by the fine-tuned model separately in the data store and check conversion rate in 30–60 days. A higher close rate on approved leads means the model learned your ICP correctly.

---

## What Not to Fine-Tune

Only the Qualification Agent benefits from fine-tuning. The other two agents should stay on the current setup:

**Sales Agent (email writing)**: each outreach email is personalized to a specific lead's pain points and context. The email content that works for Mahindra manufacturing is different from what works for a Bengaluru SaaS startup. RAG-grounded prompts with `temperature=0.4` (your current `llm_temperature_creative` setting) handle this well. Fine-tuning email writing would bake in stylistic patterns that get stale as your messaging evolves.

**Research Agent (extraction)**: the `LeadExtraction` schema is deterministic — company name, industry, employee count, location, decision maker. Structured output with `llm.with_structured_output(LeadExtraction)` at `temperature=0.1` already produces reliable extraction. There is no subjective judgment in extraction that fine-tuning would improve.

Qualification is the one agent where the output is inherently subjective and domain-specific. The score a generic LLM assigns to a 40,000-person Indian manufacturing conglomerate is not the same as the score your best sales rep would assign. That gap is exactly what fine-tuning closes.
