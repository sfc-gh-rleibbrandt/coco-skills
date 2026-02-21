# Databricks vs Snowflake Benchmark Skill

Generate price:performance comparison reports for Snowflake FDN vs Databricks Delta.

## Prerequisites

### 1. Snowflake Connection
You need a Snowflake connection named `snowhouse` configured. This connects to the benchmark data store.

```bash
# Check if connection exists
snow connection list

# If not, add it (get credentials from team lead)
snow connection add snowhouse
```

### 2. Python Dependencies
```bash
pip install snowflake-connector-python
```

### 3. Access to Benchmark Data
The script queries `bench_store.publicdata.sample_batch_pivot`. Verify access:
```sql
SELECT COUNT(*) FROM bench_store.publicdata.sample_batch_pivot LIMIT 1;
```

## Quick Start

```bash
cd /Users/rleibbrandt/codePad/projects/benchmarking

python3 scripts/generate-sf-vs-dbx-report.py \
    --sf-runs 3760762,3760760,3760763,3760740,3760766,3760764,3761124 \
    --sf-sizes "S,M,L,XL,2XL,3XL,4XL" \
    --dbx-runs 3762414,3760819,3760696,3777742,3760804,3760808 \
    --dbx-sizes "S,M,L,XL,2XL,3XL" \
    --output results/sf-vs-dbx-price-perf.html
```

## Report Features

The generated HTML report includes **7 tabs**:

| Tab | Description |
|-----|-------------|
| **Overview** | Executive summary with price:performance frontier analysis, key findings, and comparison cards |
| **EE Analysis** | Enterprise Edition OKR scorecard with tier-based comparisons (Cost Anchor + Perf Anchor) |
| **SE Analysis** | Standard Edition OKR scorecard with tier-based comparisons (Cost Anchor + Perf Anchor) |
| **Graphs** | 6 interactive charts with scale/view toggle controls |
| **Snowflake Details** | Full 103-query matrix with scaling efficiency analysis |
| **Databricks Details** | Full 103-query matrix with scaling efficiency analysis |
| **Query Reference** | Full query-by-query comparison table |

### OKR Scorecards (EE & SE Analysis Tabs)

Each edition tab includes comprehensive tier-based analysis:

#### Cost Anchor: "At Same Budget, Who's Faster?"
- Budget tiers derived from overlapping price ranges
- Each tier finds the best qualifying config from each vendor
- Shows price:performance score (Cost × Geomean) comparison
- OKR grading: 🟢 ≥90% of 35% target | 🟡 70-90% | 🔴 <70%

#### Perf Anchor: "At Same SLA, Who's Cheaper?"
- Latency-based SLA tiers (e.g., ≤3s, ≤5s, ≤10s)
- Shows which vendor can meet SLA at lowest cost
- Highlights capability gaps where only one vendor can compete

#### What-If Analysis
- "If DBX improved 20%, how would OKR standing change?"
- Models 36% score improvement (0.8 × 0.8 = 0.64)
- Shows impact on each tier and overall grade

### Interactive Graph Features (Graphs Tab)

**6 chart types:**
1. **Run Cost** — Cost to execute full benchmark by size
2. **Geomean Latency** — Geometric mean query time
3. **Total Runtime** — Sum of all 103 queries
4. **Price:Performance Score** — Cost × Geomean (lower = better)
5. **Scatter: Cost vs Geomean** — Frontier visualization
6. **Scatter: Cost vs Total** — Alternative frontier view

**3 data series per chart:**
- Snowflake SE (Standard Edition)
- Snowflake EE (Enterprise Edition)
- Databricks

**Toggle controls:**
- **Scale**: Linear / Log Scale
- **View**: Absolute Values / % Advantage vs DBX

### Scaling Efficiency Analysis

Each query row in the Matrix tabs shows:
- **Sparkline**: Visual trend across warehouse sizes
- **Scaling Efficiency %**: Statistical measure using log-log regression

#### The Math (Log-Log Regression)

Model: `T = c × N^β` where T=runtime, N=compute multiplier

Taking logs: `log(T) = log(c) + β × log(N)`

| β value | Meaning | Interpretation |
|---------|---------|----------------|
| **-1.0** | Perfect scaling | 2× compute → 2× speedup |
| **-0.7** | Good scaling | 2× compute → 1.6× speedup |
| **-0.5** | Sublinear | 2× compute → 1.4× speedup |
| **0** | No scaling | Serial workload |

**Scaling Efficiency** = `|β| × 100%` (capped at 100%)

Color coding:
- 🟢 Green (≥70%): Good scaling
- 🟡 Yellow (40-70%): Moderate scaling  
- 🔴 Red (<40%): Poor scaling

## Philosophy: Price-Performance Frontier

**Key insight:** Customers don't care about t-shirt sizes — they care about **performance at an acceptable price point**.

This report answers:
1. **"At this budget, who's faster?"** — For a given $/hour spend, compare latency
2. **"To hit this SLA, what's the cheapest?"** — For a given latency target, compare cost

### Why Not Size-Matching?

T-shirt sizes are meaningless across platforms:
- SF Large: $21.60/hr (8 credits × $2.70 SE)
- DBX Large: $28.00/hr

A "size-to-size" comparison would mislead. **Price tiers** are the fair comparison.

## Pricing Model

### Snowflake Gen2

| Edition | $/Credit | Notes |
|---------|----------|-------|
| Standard Edition (SE) | $2.00 | Default for most customers |
| Enterprise Edition (EE) | $3.00 | Additional features |

**Credits/hour by size (Gen2 = 1.35× Gen1):**
```
S=2.7, M=5.4, L=10.8, XL=21.6, 2XL=43.2, 3XL=86.4, 4XL=172.8
```

**Hourly rates:**
| Size | SE $/hr | EE $/hr |
|------|---------|---------|
| S    | $5.40   | $8.10   |
| M    | $10.80  | $16.20  |
| L    | $21.60  | $32.40  |
| XL   | $43.20  | $64.80  |
| 2XL  | $86.40  | $129.60 |
| 3XL  | $172.80 | $259.20 |
| 4XL  | $345.60 | $518.40 |

### Databricks SQL Warehouse

Combined DBU + compute cost per hour (no separate editions):
```
S=$16, M=$16.8, L=$28, XL=$56, 2XL=$100.8, 3XL=$190.4
```

## Current Default Run Keys (10TB TPC-DS, Feb 2025)

### Snowflake FDN Gen2
| Size | Run Key | SE $/hr | EE $/hr |
|------|---------|---------|---------|
| S    | 3760762 | $5.40   | $8.10   |
| M    | 3760760 | $10.80  | $16.20  |
| L    | 3760763 | $21.60  | $32.40  |
| XL   | 3760740 | $43.20  | $64.80  |
| 2XL  | 3760766 | $86.40  | $129.60 |
| 3XL  | 3760764 | $172.80 | $259.20 |
| 4XL  | 3761124 | $345.60 | $518.40 |

### Databricks Delta (Photon) — Unclustered Schema
| Size | Run Key | $/hr    | Notes |
|------|---------|---------|-------|
| S    | 3762414 | $16.00  | schema=DEFAULT (unclustered) |
| M    | 3760819 | $16.80  | schema=DEFAULT (unclustered) |
| L    | 3760696 | $28.00  | schema=DEFAULT (unclustered) |
| XL   | 3777742 | $56.00  | **Golden reference** - schema=DEFAULT |
| 2XL  | 3760804 | $100.80 | schema=DEFAULT (unclustered) |
| 3XL  | 3760808 | $190.40 | schema=DEFAULT (unclustered) |

**Important:** Use unclustered schema runs for fair comparison. Clustered runs (`tags_by_key:"schema"='10tb_clustered'`) are slower and not apples-to-apples.

## Finding New Runs (Auto-Discovery)

### Auto-Discover Latest SF Runs
```sql
WITH sf_runs AS (
    SELECT 
        r.run_key,
        r.run_date::DATE as run_date,
        CASE r.tags_by_key:"warehouse_size"::STRING
            WHEN 'X2L' THEN '2XL'
            WHEN 'X3L' THEN '3XL'
            WHEN 'X4L' THEN '4XL'
            ELSE r.tags_by_key:"warehouse_size"::STRING
        END as size,
        COUNT(DISTINCT s.query_label) as query_count
    FROM bench_store.publicdata.run_info_v r
    JOIN bench_store.publicdata.sample_batch_pivot s ON r.run_key = s.run_key
    WHERE r.platform = 'snowflake'
      AND r.tags_by_key:"data-format"::STRING = 'fdn'
      AND COALESCE(r.tags_by_key:"warehouse-type"::STRING, 
                   r.tags_by_key:"warehouse_type"::STRING) = 'GEN2'
      AND r.tags_by_key:"apg-benchmark-name"::STRING = 'APG_tpcds_benchmark'
      AND s.query_label LIKE '%_warm%'
      AND r.run_date >= CURRENT_DATE - 30
    GROUP BY 1, 2, 3
    HAVING COUNT(DISTINCT s.query_label) = 103
),
ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY size ORDER BY run_date DESC) as rn
    FROM sf_runs
)
SELECT run_key, run_date, size, query_count
FROM ranked
WHERE rn = 1 AND size IN ('S', 'M', 'L', 'XL', '2XL', '3XL', '4XL')
ORDER BY CASE size 
    WHEN 'S' THEN 1 WHEN 'M' THEN 2 WHEN 'L' THEN 3 
    WHEN 'XL' THEN 4 WHEN '2XL' THEN 5 WHEN '3XL' THEN 6 WHEN '4XL' THEN 7 
END;
```

### Auto-Discover Latest DBX Runs (Unclustered)
```sql
WITH dbx_runs AS (
    SELECT 
        r.run_key,
        r.run_date::DATE as run_date,
        r.tags_by_key:"platform-size"::STRING as size,
        r.tags_by_key:"schema"::STRING as schema,
        COUNT(DISTINCT s.query_label) as query_count
    FROM bench_store.publicdata.run_info_v r
    JOIN bench_store.publicdata.sample_batch_pivot s ON r.run_key = s.run_key
    WHERE r.platform = 'databricks'
      AND r.tags_by_key:"data-format"::STRING = 'delta'
      AND r.tags_by_key:"data-size"::STRING IN ('10TB', '10tb')
      AND (r.tags_by_key:"schema"::STRING IN ('10tb', 'DEFAULT') 
           OR r.tags_by_key:"schema" IS NULL)
      AND s.query_label LIKE '%_warm%'
      AND r.run_date >= CURRENT_DATE - 30
    GROUP BY 1, 2, 3, 4
    HAVING COUNT(DISTINCT s.query_label) = 103
),
ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY size ORDER BY run_date DESC) as rn
    FROM dbx_runs
)
SELECT run_key, run_date, size, query_count, schema
FROM ranked
WHERE rn = 1 AND size IN ('S', 'M', 'L', 'XL', '2XL', '3XL')
ORDER BY CASE size 
    WHEN 'S' THEN 1 WHEN 'M' THEN 2 WHEN 'L' THEN 3 
    WHEN 'XL' THEN 4 WHEN '2XL' THEN 5 WHEN '3XL' THEN 6
END;
```

## Key Metrics

| Metric | Description |
|--------|-------------|
| **Total (s)** | Sum of all query times (103 queries) |
| **Geomean (s)** | Geometric mean — robust average less skewed by outliers |
| **Run Cost** | Cost to execute full benchmark = (total_seconds / 3600) × hourly_rate |
| **Cost × Geomean** | Price:Performance score (lower = better) |
| **% Advantage** | `((DBX - SF) / DBX) × 100` — positive = SF wins |

## Common Workflows

### 1. Generate report with current defaults
```bash
cd /Users/rleibbrandt/codePad/projects/benchmarking

python3 scripts/generate-sf-vs-dbx-report.py \
    --sf-runs 3760762,3760760,3760763,3760740,3760766,3760764,3761124 \
    --sf-sizes "S,M,L,XL,2XL,3XL,4XL" \
    --dbx-runs 3762414,3760819,3760696,3777742,3760804,3760808 \
    --dbx-sizes "S,M,L,XL,2XL,3XL" \
    --output results/sf-vs-dbx-price-perf.html
```

### 2. Open report
```bash
open results/sf-vs-dbx-price-perf.html
```

### 3. Update with new runs
1. Query latest runs using SQL above
2. Verify 103 queries per run
3. **Verify DBX runs use unclustered schema** (vars.schema='10tb' or DEFAULT)
4. Update run keys in command
5. Regenerate report

### 4. Share findings
The HTML is self-contained — email it or drop in Slack.

## Script Details

**Location:** `scripts/generate-sf-vs-dbx-report.py`

**Dependencies:**
- Python 3.11+
- `snowflake-connector-python`
- Snowflake connection named `snowhouse`

**Data source:** `bench_store.publicdata.sample_batch_pivot`

**Metrics extraction:**
- Snowflake: `metrics:TOTAL_DURATION_MS::FLOAT / 1000`
- Databricks: `metrics:"server/total_time_ms"::FLOAT / 1000`

## Troubleshooting

### Script times out
The script fetches data from Snowflake for each run. If connection is slow:
- Ensure you're authenticated to Snowflake
- Check `snowhouse` connection is configured
- Script may take 2-3 minutes for 13 runs (7 SF + 6 DBX)

### Missing queries
If a run has < 103 queries, check:
```sql
SELECT query_label, COUNT(*) 
FROM bench_store.publicdata.sample_batch_pivot
WHERE run_key = <your_run_key>
  AND query_label LIKE '%_warm%'
GROUP BY 1
ORDER BY 1;
```

### Wrong DBX schema (clustered vs unclustered)
Check the vars.schema field:
```sql
SELECT run_key, vars:schema::STRING as schema
FROM bench_store.publicdata.run_info_v
WHERE run_key IN (3762414, 3760819, 3760824, 3777742, 3760945, 3760808);
```
- `'10tb'` or `NULL`/`DEFAULT` = unclustered (correct)
- `'10tb_clustered'` = clustered (slower, avoid for fair comparison)

### Scaling efficiency shows "—"
Needs at least 2 valid data points across warehouse sizes. Check if query failed on some sizes.
