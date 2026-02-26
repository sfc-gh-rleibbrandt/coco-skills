---
name: athena-snowflake-benchmark
description: Generate TPC-DS 10TB price:performance comparison reports for Snowflake vs AWS Athena
trigger_patterns:
  - "athena vs snowflake"
  - "snowflake vs athena"
  - "athena benchmark"
  - "athena comparison"
  - "sf vs athena report"
---

# Athena vs Snowflake TPC-DS Benchmark Skill

Generate comprehensive price:performance comparison reports between Snowflake Gen2 Iceberg and AWS Athena on TPC-DS 10TB.

## Quick Start

Generate a report using the Python generator:

```bash
python /Users/rleibbrandt/codePad/projects/benchmarking/scripts/generate-tpcds-price-perf.py \
  --sf-runs 3761057,3761059,3761060,3760798,3761053 \
  --sf-sizes S,M,L,XL,2XL \
  --competitor-run 3473166 \
  --competitor-name "Athena" \
  --competitor-cost 10.30 \
  --output notes/artifacts/sf-vs-athena-10tb.html
```

## Default Run Keys

### Snowflake Gen2 Iceberg (TPC-DS 10TB Warm)
| Size | Run Key | Credits/hr | Gen2 SE Rate |
|------|---------|------------|--------------|
| S    | 3761057 | 2          | $2.70/cr     |
| M    | 3761059 | 4          | $2.70/cr     |
| L    | 3761060 | 8          | $2.70/cr     |
| XL   | 3760798 | 16         | $2.70/cr     |
| 2XL  | 3761053 | 32         | $2.70/cr     |

### Athena (TPC-DS 10TB)
| Run Key | Data Scanned | Cost Model      |
|---------|--------------|-----------------|
| 3473166 | 2.06 TB      | $5.00/TB = $10.30 |

## Script Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--sf-runs` | Yes | Comma-separated Snowflake run keys (must match size order) |
| `--sf-sizes` | Yes | Comma-separated sizes: XS, S, M, L, XL, 2XL, 3XL, 4XL |
| `--competitor-run` | Yes | Competitor run key from bench_store |
| `--competitor-name` | Yes | Display name (e.g., "Athena") |
| `--competitor-cost` | Yes | Competitor total cost in USD |
| `--output` | Yes | Output HTML file path |
| `--publish` | No | Copy report to `results/competitive/` with date-stamped filename |

## Pricing Models

The report now generates **both SE and EE analysis** in a single report (no `--pricing` flag needed):

| Edition | Credit Rate | Report Tab |
|---------|-------------|------------|
| Standard Edition (SE) | $2.00/credit | SE Analysis tab |
| Enterprise Edition (EE) | $3.00/credit | EE Analysis tab |

Gen2 warehouses use 1.35× credits vs Gen1 (e.g., XL = 21.6 cr/hr instead of 16).

## Finding New Run Keys

Query bench_store for available runs:

```sql
-- Find Snowflake TPC-DS runs
SELECT run_key, run_date, 
       tags_by_key:"warehouse_size"::STRING as wh_size,
       COALESCE(tags_by_key:"warehouse-type"::STRING, tags_by_key:"warehouse_type"::STRING) as wh_type
FROM bench_store.publicdata.run_info_v
WHERE platform = 'snowflake'
  AND tags_by_key:"data-format"::STRING = 'iceberg'
  AND run_date >= DATEADD('day', -30, CURRENT_DATE())
ORDER BY run_date DESC;

-- Find Athena runs
SELECT run_key, run_date
FROM bench_store.publicdata.run_info_v
WHERE platform ILIKE '%athena%'
  AND run_date >= DATEADD('day', -90, CURRENT_DATE())
ORDER BY run_date DESC;
```

## Calculating Athena Cost

Athena pricing is $5.00 per TB scanned. To find total data scanned for a run:

```sql
SELECT 
    SUM(metrics:"bytes_scanned"::NUMBER) / POWER(1024, 4) as tb_scanned,
    (SUM(metrics:"bytes_scanned"::NUMBER) / POWER(1024, 4)) * 5.00 as cost_usd
FROM bench_store.publicdata.sample_batch_pivot
WHERE run_key = 3473166
  AND query_label LIKE '%_warm%'
  AND query_label NOT LIKE '%_cold%';
```

## Report Features

The generated HTML report includes 7 tabs:

1. **Overview** - Executive summary, pricing breakdown, key findings
2. **EE Analysis** - Enterprise Edition ($3/credit) comparison with OKR scorecard, What-If, Budget/SLA match
3. **SE Analysis** - Standard Edition ($2/credit) comparison with OKR scorecard, What-If, Budget/SLA match
4. **Graphs** - 6 interactive Chart.js charts with Linear/Log toggle (cost, geomean, total, price:perf, scatter plots)
5. **Head-to-Head** - Dynamic JS-driven query comparison with SF size selector, butterfly chart, category breakdown, click-to-show scaling curves
6. **SF Scaling** - Scaling efficiency (log-log regression) with sparklines for all 103 queries
7. **Query Reference** - TPC-DS query descriptions, classifications, and Metrics Explained

All self-contained — no external dependencies except Chart.js CDN (pinned to 4.4.1).

## TPC-DS Query Classifications

| Category | Count | Description |
|----------|-------|-------------|
| Reporting | 22 | Well-known queries, optimizable |
| Ad-hoc | 18 | Unknown queries, no pre-optimization |
| OLAP | 41 | Interactive drill-down analysis |
| Data Mining | 22 | Extraction and mining queries |

## Workflow

1. **Find/confirm run keys** using the SQL queries above
2. **Calculate competitor cost** (for Athena: TB scanned × $5.00)
3. **Run the generator** with appropriate parameters (no `--publish` yet)
4. **Review the output** HTML in a browser — check the "Included Runs" table on the Overview tab to validate run keys, dates, and query counts
5. **Publish** — re-run with `--publish` to copy to `results/competitive/` with a date-stamped filename

## Publishing

When you're happy with the report, add `--publish` to the command:

```bash
python scripts/generate-tpcds-price-perf.py \
  --sf-runs 3761057,3761059,3761060,3760798,3761053 \
  --sf-sizes S,M,L,XL,2XL \
  --competitor-run 3473166 \
  --competitor-name "Athena" \
  --competitor-cost 10.30 \
  --output notes/artifacts/sf-vs-athena-10tb.html \
  --publish
```

This will:
- Generate the report at `--output` as usual
- Copy it to `results/competitive/sf-vs-athena-tpcds-10tb-YYYY-MM-DD.html`
- Embed the publish date in the report header (green badge), `<title>` tag, and footer

**File naming:** `sf-vs-{competitor}-tpcds-10tb-{YYYY-MM-DD}.html`
Example: `results/competitive/sf-vs-athena-tpcds-10tb-2026-02-21.html`

## Example: Regenerate Default Report (Draft)

```bash
cd /Users/rleibbrandt/codePad/projects/benchmarking

python scripts/generate-tpcds-price-perf.py \
  --sf-runs 3761057,3761059,3761060,3760798,3761053 \
  --sf-sizes S,M,L,XL,2XL \
  --competitor-run 3473166 \
  --competitor-name "Athena" \
  --competitor-cost 10.30 \
  --output notes/artifacts/sf-vs-athena-$(date +%Y%m%d).html
```

## Troubleshooting

### Connection Issues
The script uses the `snowhouse` connection. Ensure it's configured:
```bash
snow connection list
```

### Missing Queries
If some queries are missing from a run, check:
```sql
SELECT DISTINCT query_label 
FROM bench_store.publicdata.sample_batch_pivot
WHERE run_key = <your_run_key>
ORDER BY 1;
```

### Time Units
- Snowflake times are in **milliseconds** (`metrics:TOTAL_DURATION_MS`)
- Athena times are in **milliseconds** (`metrics:"e2e_latency"`)
- The script divides both platforms' times by 1000 to get seconds for display