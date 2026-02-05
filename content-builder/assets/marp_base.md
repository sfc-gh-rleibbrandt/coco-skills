---
marp: true
theme: default
paginate: true
backgroundColor: #ffffff
color: #1a1a1a
footer: '© 2026 Snowflake Inc. All Rights Reserved | Confidential'
style: |
  /* Snowflake Brand Colors */
  :root {
    --sf-blue: #29B5E8;
    --sf-dark-blue: #11567F;
    --sf-navy: #0D2C54;
    --sf-light-bg: #F4FAFF;
    --sf-gray: #6E7681;
  }
  section {
    font-family: 'Nunito Sans', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
    font-size: 20px;
    padding: 110px 80px 60px 80px;
    background: #ffffff;
    color: #1a1a1a;
    position: relative;
    display: flex;
    flex-direction: column;
    justify-content: flex-start;
    align-items: center;
  }
  section > * {
    width: 100%;
    max-width: 1000px;
    margin-left: auto;
    margin-right: auto;
  }
  footer {
    font-size: 9px;
    color: #999999;
    position: absolute;
    bottom: 12px;
    left: 20px;
    right: auto;
  }
  /* Fixed position header bar - centered */
  section::before {
    content: '';
    position: absolute;
    top: 35px;
    left: calc(50% - 500px - 25px);
    width: 5px;
    height: 55px;
    background: var(--sf-blue);
  }
  h1 {
    color: var(--sf-dark-blue);
    font-size: 1.4em;
    margin: 0 0 0.1em 0;
    padding: 0;
    font-weight: 700;
    border-left: none;
    position: absolute;
    top: 35px;
    left: calc(50% - 500px);
    right: calc(50% - 500px);
    max-width: 1000px;
  }
  h2 {
    color: var(--sf-gray);
    font-size: 0.95em;
    font-weight: 500;
    margin: 0;
    padding: 0;
    border-left: none;
    position: absolute;
    top: 68px;
    left: calc(50% - 500px);
    right: calc(50% - 500px);
    max-width: 1000px;
  }
  h3 {
    color: var(--sf-dark-blue);
    font-size: 0.95em;
    font-weight: 600;
    margin-top: 0.5em;
    margin-bottom: 0.2em;
  }
  code {
    background: #E8F4FC;
    color: var(--sf-navy);
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 0.85em;
  }
  pre {
    background: #EDF5FB;
    border-left: 4px solid var(--sf-blue);
    border-radius: 8px;
    padding: 12px;
    font-size: 0.65em;
    overflow-x: auto;
    color: #1a1a1a;
  }
  pre code {
    padding: 0;
    background: transparent;
  }
  table {
    font-size: 0.72em;
    width: 100%;
    max-width: 1000px;
    border-collapse: collapse;
    margin: 0.5em auto;
  }
  th {
    background: linear-gradient(135deg, var(--sf-dark-blue) 0%, var(--sf-navy) 100%);
    color: #ffffff;
    padding: 8px 10px;
    text-align: left;
  }
  td {
    background: #F8FCFE;
    border-bottom: 1px solid #D0E8F5;
    padding: 6px 10px;
    color: #1a1a1a;
  }
  tr:nth-child(even) td {
    background: #EDF5FB;
  }
  a {
    color: var(--sf-blue);
  }
  /* Title slides - dark blue background, centered */
  section.title {
    text-align: center;
    display: flex;
    flex-direction: column;
    justify-content: center;
    background: #11567F !important;
    color: #ffffff !important;
    padding: 50px;
  }
  section.title::before {
    display: none;
  }
  section.title h1 {
    font-size: 2.2em;
    color: #ffffff !important;
    position: static;
    text-align: center;
    margin-bottom: 0.3em;
  }
  section.title h2 {
    color: #E8F4FC !important;
    font-weight: 400;
    position: static;
    text-align: center;
    font-size: 1.3em;
  }
  section.title h3 {
    color: #ffffff !important;
    text-align: center;
    position: static;
  }
  section.title p, section.title strong, section.title em {
    color: #E8F4FC !important;
  }
  section.title footer {
    color: rgba(255,255,255,0.5) !important;
  }
  blockquote {
    border-left: 4px solid var(--sf-blue);
    background: #E8F4FC;
    padding: 10px 16px;
    font-style: italic;
    margin: 10px 0;
    font-size: 0.85em;
    border-radius: 0 8px 8px 0;
    color: #1a1a1a;
  }
  .docs-link {
    font-size: 0.52em;
    color: var(--sf-gray);
    position: absolute;
    bottom: 35px;
    left: 50px;
  }
  .docs-link a {
    color: var(--sf-blue);
  }
  ul, ol {
    font-size: 0.88em;
    margin: 0.3em 0;
  }
  li {
    margin: 0.2em 0;
  }
  p {
    margin: 0.4em 0;
  }
  .preview-badge {
    background: linear-gradient(135deg, #FF9800 0%, #F57C00 100%);
    color: white;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.65em;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  .ga-badge {
    background: linear-gradient(135deg, #4CAF50 0%, #388E3C 100%);
    color: white;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.65em;
    font-weight: bold;
  }
---

<!-- _class: title -->

# Presentation Title
## Subtitle Here

**Customer/Event Name**

*Optional tagline or description*

Date | Presenter Name

---

# Agenda

| Section | Topics |
|---------|--------|
| **Part 1** | First topic area |
| **Part 2** | Second topic area |
| **Part 3** | Third topic area |
| **Part 4** | Q&A |

<div class="docs-link">📚 <a href="https://docs.snowflake.com">docs.snowflake.com</a></div>

---

<!-- _class: title -->

# Part 1: Section Title

---

# Content Slide with Table
## Optional Subtitle

| Column 1 | Column 2 | Column 3 |
|----------|----------|----------|
| Data 1 | Data 2 | Data 3 |
| Data 4 | Data 5 | Data 6 |

**Key point:** Important information here.

<div class="docs-link">📚 <a href="https://docs.snowflake.com">docs.snowflake.com/path/to/docs</a></div>

---

# Before vs After Comparison ✅ GA

### ❌ BEFORE: The complex old way
```sql
-- Complex, error-prone, slow
WITH complex_cte AS (
  SELECT *, ROW_NUMBER() OVER (...) AS rn
  FROM table1 t1
  LEFT JOIN (
    SELECT *, LEAD(...) OVER (...) AS next_val
    FROM table2
  ) t2 ON t1.id = t2.id
    AND t1.ts >= t2.start_ts
    AND t1.ts < t2.end_ts
)
SELECT * FROM complex_cte WHERE rn = 1;
```

### ✅ AFTER: Clean simple way
```sql
-- Clean, fast, correct
SELECT * FROM table1 t1
CLEAN_JOIN table2 t2
  MATCH_CONDITION(t1.ts >= t2.ts)
  ON t1.id = t2.id;
```

<div class="docs-link">📚 <a href="https://docs.snowflake.com">docs.snowflake.com/path/to/docs</a></div>

---

# Feature Overview
## Value proposition subtitle

| Function | What It Solves | Without It... |
|----------|---------------|---------------|
| Feature A | Problem it solves | Manual workaround |
| Feature B | Another problem | Complex alternative |
| Feature C | Third problem | Tedious approach |

**Struggles We Solve:** ❌ Pain point 1 • ❌ Pain point 2 • ❌ Pain point 3

**Value Delivered:** ✅ Benefit 1 • ✅ Benefit 2 • ✅ Benefit 3

> 🏆 "Customer quote about success" — Customer Name

<div class="docs-link">📚 <a href="https://docs.snowflake.com">docs.snowflake.com/path/to/docs</a></div>

---

# Feature with Badge <span class="preview-badge">PUBLIC PREVIEW</span>

**Problem:** Description of the problem this solves

| Input | | Output |
|-------|---|--------|
| Before state | → | After state |

```sql
SELECT * FROM feature_example;
```

<div class="docs-link">📚 <a href="https://docs.snowflake.com">docs.snowflake.com/path/to/docs</a></div>

---

# Roadmap Slide

> *"Customer pain point quote"*

**Current Behavior:** How it works today

| Milestone | Timeline |
|-----------|----------|
| Design | Q4 FY26 (Complete) |
| **Preview** | **Q1 FY27** |
| GA | Q2 FY27 |

### Planned Syntax
```sql
CREATE FEATURE new_feature
    SETTING = 'value'
AS SELECT ...;
```

<div class="docs-link">📚 <a href="https://docs.snowflake.com">docs.snowflake.com/path/to/docs</a></div>

---

# Summary

| Status | Features |
|--------|----------|
| ✅ GA Today | Feature A, Feature B, Feature C |
| 🟡 Public Preview | Feature D, Feature E |
| 🔜 Coming Soon | Feature F (Q1 FY27), Feature G (Q2 FY27) |

<div class="docs-link">📚 <a href="https://docs.snowflake.com">docs.snowflake.com</a></div>

---

<!-- _class: title -->

# Thank You!

### Questions?

**Contact:** email@snowflake.com

**Next Session:** Topic @ Time
