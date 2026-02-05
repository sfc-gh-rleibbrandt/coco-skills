---
name: content-builder
description: "Create professional Snowflake-branded presentations. Use when: user wants to create slides, build a presentation, make a deck, generate PPTX, or create Marp slides. Triggers: create presentation, build slides, make pptx, snowflake deck, create deck, presentation template."
---

# Content Builder

Create Snowflake-branded presentations in Marp (HTML/PDF) or PPTX format.

**Default format: Marp** - Use Marp unless user explicitly requests PPTX.

## Setup

**Load** `references/style_guide.md` for brand colors, typography, and layout patterns.

## Workflow

### Step 1: Gather Requirements

**Ask user:**
```
What presentation do you need?

1. Title:
2. Subtitle/tagline:
3. Audience/Event:
4. Presenter name:
5. Brief outline or topic areas:
```

**Note:** Default to Marp format. Only ask about format if user mentions PPTX or PowerPoint.

**⚠️ STOP**: Wait for user input.

### Step 2: Plan Slides

Based on user input, propose a slide outline:

| # | Type | Title |
|---|------|-------|
| 1 | Title | [Main title] |
| 2 | Agenda | Topics overview |
| 3+ | Content | [Based on outline] |
| N | Thank You | Q&A / Contact |

**⚠️ STOP**: Get approval on outline before generating.

### Step 3: Generate Presentation

**Default: Marp format (recommended)**
1. Copy `<SKILL_DIR>/assets/marp_base.md` to user's project
2. Customize content while preserving the ENTIRE CSS styling block (lines 1-294)
3. Generate output:
   ```bash
   npx --yes @marp-team/marp-cli <file>.md -o <output>.html
   npx --yes @marp-team/marp-cli <file>.md -o <output>.pdf --allow-local-files
   ```

**If user explicitly requests PPTX:**
1. Copy `<SKILL_DIR>/assets/pptx_base.py` to user's project
2. Customize the SLIDES section with user content
3. Run:
   ```bash
   uv run python <file>.py
   ```

### Step 4: Review & Iterate

Present output location to user. Offer to:
- Add/modify slides
- Adjust styling
- Generate additional formats

## Slide Types Available

| Type | Function | Use For |
|------|----------|---------|
| `add_title_slide()` | Dark blue bg, centered | Title, section dividers |
| `add_section_slide()` | Dark blue bg | Section breaks |
| `add_content_slide()` | White bg, blue accent | General content |
| `add_before_after_slide()` | Side-by-side comparison | Feature value demos |
| `add_value_prop_slide()` | Features + benefits | Product capabilities |
| `add_roadmap_slide()` | Timeline + syntax | Upcoming features |

## Brand Quick Reference

| Element | Value |
|---------|-------|
| SF Blue | `#29B5E8` |
| SF Dark Blue | `#11567F` |
| Body Font | Nunito Sans |
| Code Font | Courier New |
| GA Badge | Green |
| Preview Badge | Orange |

## Stopping Points

- ✋ Step 1: After gathering requirements
- ✋ Step 2: After proposing outline
- ✋ Step 4: After generation for review

## Output

- Marp: `.md` source + `.html` and/or `.pdf`
- PPTX: `.py` script + `.pptx` file
- TPC-DS Report: `.py` script + `.html` file

---

## TPC-DS Power Run Report Builder

Generate Snowflake-branded HTML reports for TPC-DS benchmark comparisons.

### Report Types

| Type | Use For |
|------|---------|
| Gap Analysis | Queries where competitor wins, prioritized by impact |
| Price:Performance | Cost comparison with performance metrics |
| Head-to-Head | Full query-by-query comparison |

### Workflow

**Step 1: Gather Requirements**

Ask user:
```
What TPC-DS report do you need?

1. Report type: (gap-analysis/price-perf/comparison)
2. Platforms compared: (e.g., SF Gen2 M vs Athena)
3. Scale: (1TB/3TB/10TB)
4. Run keys: (SF run key, competitor run key)
5. Additional context:
```

**⚠️ STOP**: Wait for user input.

**Step 2: Query Data**

Pull benchmark data from `bench_store.publicdata`:
```sql
-- Gap analysis query pattern
WITH sf_run AS (
    SELECT query_label, GET(metrics, 'TOTAL_DURATION_MS')::NUMBER / 1000 as sf_sec
    FROM bench_store.publicdata.sample_batch_pivot
    WHERE run_key = <SF_RUN_KEY> AND query_label LIKE '%warm%'
),
competitor_run AS (
    SELECT query_label, GET(metrics, 'e2e_latency')::NUMBER / 1000 as comp_sec
    FROM bench_store.publicdata.sample_batch_pivot  
    WHERE run_key = <COMP_RUN_KEY> AND query_label LIKE '%warm%'
)
SELECT ...
```

**Step 3: Generate Report**

1. Copy `<SKILL_DIR>/assets/tpcds_report_base.py` to user's project
2. Customize `REPORT_CONFIG` and `QUERY_DATA` sections with queried data
3. Run:
   ```bash
   uv run python tpcds_report.py
   ```
4. Open generated HTML:
   ```bash
   open tpcds_report.html
   ```

### Report Components

| Component | Description |
|-----------|-------------|
| Summary Cards | 3-4 key metrics (queries won, time lost, etc.) |
| Key Finding | One-sentence executive summary |
| Data Table | Query-level details with severity tags |
| Recommendations | Prioritized action items |

### Severity Classification

Severity considers **both** absolute time impact AND ratio (percentage slowdown):

|                    | Ratio < 1.5x | Ratio 1.5-2.5x | Ratio > 2.5x |
|--------------------|--------------|----------------|--------------|
| **Time > 60s**     | MODERATE     | SEVERE         | SEVERE       |
| **Time 30-60s**    | MINOR        | MODERATE       | SEVERE       |
| **Time < 30s**     | MINOR        | MINOR          | MODERATE     |

- **High ratio** = potential algorithmic/architectural issue (even if fast)
- **High absolute time** = big impact on total benchmark runtime
- Severity is auto-calculated from `diff` and `ratio` columns

### Example Usage

```python
# Customize REPORT_CONFIG
REPORT_CONFIG = {
    "title": "TPC-DS 10TB Gap Analysis",
    "subtitle": "Snowflake Gen2 Medium vs AWS Athena",
    "runs": [
        {"name": "SF Gen2 M", "run_key": "2775574", "config": "FDN tables"},
        {"name": "Athena", "run_key": "3473166", "config": "Serverless"},
    ],
    "summary_cards": [
        {"value": "19", "label": "Athena wins", "highlight": False},
        {"value": "80", "label": "SF wins", "highlight": True},
    ],
    "key_finding": "SF is 4.2x cheaper despite losing 19 queries.",
    ...
}
```
