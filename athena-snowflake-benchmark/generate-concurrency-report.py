#!/usr/bin/env python3
"""
Generate BI Concurrency benchmark reports: SF Iceberg vs Athena Iceberg.

Produces separate HTML reports per Iceberg format:
  - Managed Iceberg: SF vs Athena (16/32/64 users)
  - Unmanaged (Spark) Iceberg: SF vs Athena (16/32/64 users)

Inspired by the TPC-DS price:perf report — rich per-query detail, Chart.js graphs,
head-to-head tables, P99 tail latency analysis, and steady-state QPS.

Usage:
    # Generate both reports:
    python3 generate-concurrency-report.py \\
        --data data/concurrency-data.json \\
        --output-dir results/competitive/ \\
        --publish

    # Generate only managed report:
    python3 generate-concurrency-report.py \\
        --data data/concurrency-data.json \\
        --format managed \\
        --output-dir results/competitive/
"""

import argparse
import json
import math
import sys
import os
import shutil
from datetime import datetime, date


# ── Helpers ──────────────────────────────────────────────────────────────────

def fmt_s(ms):
    """Milliseconds → seconds string."""
    return f"{ms / 1000.0:.2f}"

def fmt_comma(n):
    return f"{n:,.0f}"

def fmt_money(n):
    return f"${n:,.2f}"

def fmt_pct(n):
    return f"{n:+.0f}%"

def qpm(total_queries, run_duration_sec):
    return total_queries / (run_duration_sec / 60.0)

def cost_per_1000q(cost, total_queries):
    if total_queries == 0:
        return 0
    return cost / (total_queries / 1000.0)

def calc_sf_cost(credits_per_hour, price_per_credit, run_duration_min):
    return credits_per_hour * price_per_credit * (run_duration_min / 60.0)

def calc_athena_cost(gb_scanned):
    return 5.0 * gb_scanned / 1000.0

def geomean(values):
    valid = [v for v in values if v and v > 0]
    if not valid:
        return 0
    product = 1
    for v in valid:
        product *= v
    return product ** (1/len(valid))

def mult_class(ratio):
    if ratio >= 1.5:
        return "winner-cell"
    elif ratio >= 1.0:
        return ""
    else:
        return "loss-cell"


# ── Run grouping ─────────────────────────────────────────────────────────────

QUERY_ORDER = [
    'query03', 'query07', 'query19', 'query27', 'query42', 'query43',
    'query52', 'query53', 'query55', 'query63', 'query68', 'query73',
    'query89', 'query98'
]

QUERY_DESCRIPTIONS = {
    'query03': 'Sales by brand in specific category (November)',
    'query07': 'Average qty/price/profit by promotion status',
    'query19': 'Revenue-to-profit ratio via retail channel (Dec)',
    'query27': 'Store sales by demographics with ROLLUP',
    'query42': 'Monthly sales by item in given category',
    'query43': 'Weekly store sales for specific month',
    'query52': 'Brand/dept combos with highest monthly sales',
    'query53': 'Quarterly sales by manufacturer',
    'query55': 'Monthly brand sales by manager',
    'query63': 'Store sales for specific brands/demographics',
    'query68': 'Purchases from specific store locations',
    'query73': 'Customer purchase patterns in given counties',
    'query89': 'Quarterly store sales by class for manufacturers',
    'query98': 'Catalog sales by category/class for specific months',
}


def group_runs(data):
    """Group runs by format → platform → user_count."""
    groups = {'managed': {'sf': {}, 'athena': {}}, 'spark': {'sf': {}, 'athena': {}}}
    for rk_str, run in data['runs'].items():
        meta = run['metadata']
        platform = meta['platform']
        source = meta.get('data_source', '')
        users = meta['num_users']

        if source in ('snowflake', None) and platform == 'snowflake':
            fmt_key = 'managed'
        elif source == 'spark' and platform == 'snowflake':
            fmt_key = 'spark'
        elif source in ('snowflake', None) and platform == 'athena':
            fmt_key = 'managed'
        elif source == 'spark' and platform == 'athena':
            fmt_key = 'spark'
        else:
            continue

        plat_key = 'sf' if platform == 'snowflake' else 'athena'
        run['run_key'] = int(rk_str)
        groups[fmt_key][plat_key][users] = run
    return groups


# ── HTML building blocks ─────────────────────────────────────────────────────

def build_css():
    return """
    <style>
        :root {
            --sf-blue: #29B5E8;
            --sf-dark-blue: #11567F;
            --sf-navy: #0D2C54;
            --sf-light-bg: #F4FAFF;
            --sf-gray: #6E7681;
            --comp-orange: #FF9900;
            --comp-light: #FFF8F0;
            --green: #32963C;
            --red: #B43232;
        }

        * { box-sizing: border-box; }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1400px;
            margin: 0 auto;
            padding: 30px 20px;
            background: #fff;
            color: #333;
            line-height: 1.5;
        }

        h1 {
            color: var(--sf-dark-blue);
            border-bottom: 3px solid var(--sf-blue);
            padding-bottom: 10px;
            margin-bottom: 5px;
        }

        .subtitle { color: var(--sf-gray); margin-bottom: 20px; font-size: 1.1em; }

        h2 {
            color: var(--sf-dark-blue);
            margin-top: 35px;
            border-left: 4px solid var(--sf-blue);
            padding-left: 12px;
            font-size: 1.3em;
        }

        h3 { color: var(--sf-dark-blue); margin-top: 25px; }

        .tab-nav {
            display: flex;
            gap: 0;
            margin: 20px 0;
            border-bottom: 2px solid var(--sf-blue);
            flex-wrap: wrap;
        }

        .tab-btn {
            padding: 12px 24px;
            background: var(--sf-light-bg);
            border: 2px solid var(--sf-blue);
            border-bottom: none;
            border-radius: 8px 8px 0 0;
            cursor: pointer;
            font-size: 1em;
            font-weight: 600;
            color: var(--sf-dark-blue);
            transition: all 0.2s;
            margin-right: 4px;
        }

        .tab-btn:hover { background: #d8eef8; }
        .tab-btn.active { background: var(--sf-blue); color: white; }

        .tab-content { display: none; }
        .tab-content.active { display: block; }

        .summary-row {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            margin: 20px 0;
        }

        .card {
            background: var(--sf-light-bg);
            padding: 18px;
            border-radius: 8px;
            text-align: center;
        }

        .card.sf { background: var(--sf-blue); color: white; }
        .card.comp { background: var(--comp-orange); color: white; }
        .card.winner { background: var(--green); color: white; }

        .card .label { font-size: 0.85em; opacity: 0.9; }
        .card .value { font-size: 1.6em; font-weight: bold; margin: 4px 0; }
        .card .detail { font-size: 0.75em; opacity: 0.8; }

        .chart-container {
            position: relative;
            margin: 20px 0;
            padding: 15px;
            background: #fafcff;
            border-radius: 8px;
            border: 1px solid #e8f4fc;
        }

        .table-container {
            overflow-x: auto;
            margin: 20px 0;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }

        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.82em;
        }

        th {
            background: linear-gradient(135deg, var(--sf-dark-blue) 0%, var(--sf-navy) 100%);
            color: white;
            padding: 10px 8px;
            text-align: right;
            font-weight: 600;
            position: sticky;
            top: 0;
            z-index: 1;
        }

        th:first-child { text-align: left; }
        th.comp { background: linear-gradient(135deg, #FF9900 0%, #CC7A00 100%); }

        td {
            padding: 6px 8px;
            border-bottom: 1px solid #E8F4FC;
            text-align: right;
            font-variant-numeric: tabular-nums;
        }

        td:first-child {
            text-align: left;
            font-weight: 500;
            color: var(--sf-dark-blue);
        }

        tr:nth-child(even) { background: #FAFCFF; }
        tr:hover { background: #E8F4FC; }

        .winner-cell {
            background: #E8F5E9 !important;
            color: var(--green);
            font-weight: 700;
        }

        .loss-cell {
            background: #FFEBEE !important;
            color: var(--red);
        }

        .insight-box {
            background: #E8F4FC;
            border-left: 4px solid var(--sf-blue);
            padding: 15px 20px;
            margin: 20px 0;
            border-radius: 0 8px 8px 0;
        }

        .insight-box.winner {
            background: #e8f5e9;
            border-left-color: var(--green);
        }

        .insight-box.warning {
            background: #fff8e1;
            border-left-color: #f9a825;
        }

        .model-note {
            background: #f5f5f5;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 15px 20px;
            margin: 20px 0;
            font-size: 0.9em;
        }

        .model-note strong { color: var(--sf-dark-blue); }

        .footer {
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #eee;
            font-size: 0.8em;
            color: var(--sf-gray);
        }

        .query-name {
            cursor: help;
            border-bottom: 1px dotted var(--sf-gray);
            position: relative;
        }

        .query-name:hover::after {
            content: attr(data-desc);
            position: absolute;
            left: 0;
            top: 100%;
            background: var(--sf-navy);
            color: white;
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 0.85em;
            font-weight: normal;
            z-index: 100;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            max-width: 350px;
            white-space: normal;
            line-height: 1.4;
        }

        .chart-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }

        .sub-tab-nav {
            display: flex;
            gap: 0;
            margin: 15px 0 10px;
            border-bottom: 2px solid #ccc;
        }

        .sub-tab-btn {
            padding: 8px 20px;
            background: #f0f0f0;
            border: 1px solid #ccc;
            border-bottom: none;
            border-radius: 6px 6px 0 0;
            cursor: pointer;
            font-size: 0.9em;
            font-weight: 600;
            color: var(--sf-gray);
            transition: all 0.2s;
            margin-right: 2px;
        }

        .sub-tab-btn:hover { background: #e0e0e0; }
        .sub-tab-btn.active { background: var(--sf-dark-blue); color: white; border-color: var(--sf-dark-blue); }

        .sub-tab-content { display: none; }
        .sub-tab-content.active { display: block; }
    </style>
"""


def build_tab_js():
    return """
    <script>
    function showTab(tabId, btn) {
        document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.getElementById(tabId).classList.add('active');
        btn.classList.add('active');
    }
    function showSubTab(parentId, subId, btn) {
        var parent = document.getElementById(parentId);
        parent.querySelectorAll('.sub-tab-content').forEach(t => t.classList.remove('active'));
        parent.querySelectorAll('.sub-tab-btn').forEach(b => b.classList.remove('active'));
        document.getElementById(subId).classList.add('active');
        btn.classList.add('active');
    }
    </script>
"""


# ── Report generation for a single format ────────────────────────────────────

def generate_report(data, format_key, sf_cost_20min, credits_per_hour, price_per_credit, run_duration_min):
    """Generate a complete HTML report for one format (managed or spark)."""
    groups = group_runs(data)
    athena_gb = data.get('athena_gb_scanned', {})

    sf_runs = groups[format_key]['sf']     # {16: run, 32: run, 64: run}
    ath_runs = groups[format_key]['athena']
    user_counts = sorted(set(list(sf_runs.keys()) + list(ath_runs.keys())))

    if format_key == 'managed':
        format_label = 'Managed Iceberg'
        format_desc = 'Snowflake-managed Iceberg (Horizon catalog)'
        slug = 'managed-ib'
    else:
        format_label = 'Unmanaged (Spark) Iceberg'
        format_desc = 'Externally-written Iceberg (Spark, Glue catalog)'
        slug = 'spark-ib'

    today = date.today().strftime('%Y-%m-%d')
    today_display = date.today().strftime('%B %d, %Y')

    # ── Build per-user-count metrics ──
    rows = []
    for uc in user_counts:
        sf = sf_runs.get(uc, {})
        ath = ath_runs.get(uc, {})
        sf_agg = sf.get('aggregates', {})
        ath_agg = ath.get('aggregates', {})
        sf_meta = sf.get('metadata', {})
        ath_meta = ath.get('metadata', {})

        sf_total = sf_agg.get('total_queries', 0)
        ath_total = ath_agg.get('total_queries', 0)
        run_dur = sf_meta.get('run_duration_sec', 1200)

        ath_rk = str(ath.get('run_key', ''))
        ath_gb = athena_gb.get(ath_rk, 0)
        ath_cost = calc_athena_cost(ath_gb)

        rows.append({
            'users': uc,
            'sf_run_key': sf.get('run_key', ''),
            'ath_run_key': ath.get('run_key', ''),
            'sf_total': sf_total,
            'ath_total': ath_total,
            'sf_qpm': qpm(sf_total, run_dur),
            'ath_qpm': qpm(ath_total, run_dur),
            'sf_avg_s': sf_agg.get('avg_latency_ms', 0) / 1000.0,
            'ath_avg_s': ath_agg.get('avg_latency_ms', 0) / 1000.0,
            'sf_p50_s': sf_agg.get('p50_latency_ms', 0) / 1000.0,
            'ath_p50_s': ath_agg.get('p50_latency_ms', 0) / 1000.0,
            'sf_p99_s': sf_agg.get('p99_latency_ms', 0) / 1000.0,
            'ath_p99_s': ath_agg.get('p99_latency_ms', 0) / 1000.0,
            'sf_geomean_s': sf_agg.get('geomean_latency_ms', 0) / 1000.0,
            'ath_geomean_s': ath_agg.get('geomean_latency_ms', 0) / 1000.0,
            'sf_cost': sf_cost_20min,
            'ath_cost': ath_cost,
            'ath_gb': ath_gb,
            'sf_cost_per_1k': cost_per_1000q(sf_cost_20min, sf_total),
            'ath_cost_per_1k': cost_per_1000q(ath_cost, ath_total),
            'sf_ss': sf.get('steady_state', {}),
            'ath_ss': ath.get('steady_state', {}),
            'sf_per_query': sf.get('per_query', {}),
            'ath_per_query': ath.get('per_query', {}),
        })

    primary = next((r for r in rows if r['users'] == 32), rows[0])
    tput_ratio_32 = primary['sf_qpm'] / primary['ath_qpm'] if primary['ath_qpm'] > 0 else 0
    pp_ratio_32 = primary['ath_cost_per_1k'] / primary['sf_cost_per_1k'] if primary['sf_cost_per_1k'] > 0 else 0

    # ── Build head-to-head per-query for ALL concurrency levels ──
    h2h_by_uc = {}  # {user_count: {'sorted': [...], 'sf_wins': N, 'ath_wins': N, 'close': N}}
    for r in rows:
        uc = r['users']
        h2h_queries = []
        for q in QUERY_ORDER:
            sf_q = r['sf_per_query'].get(q, {})
            ath_q = r['ath_per_query'].get(q, {})
            sf_p50 = sf_q.get('p50_ms', 0)
            ath_p50 = ath_q.get('p50_ms', 0)
            if sf_p50 > 0 and ath_p50 > 0:
                diff_pct = ((ath_p50 - sf_p50) / ath_p50) * 100
                ratio = ath_p50 / sf_p50
            else:
                diff_pct = 0
                ratio = 0
            h2h_queries.append({
                'query': q,
                'desc': QUERY_DESCRIPTIONS.get(q, ''),
                'sf_p50': sf_p50, 'ath_p50': ath_p50,
                'sf_p99': sf_q.get('p99_ms', 0), 'ath_p99': ath_q.get('p99_ms', 0),
                'sf_avg': sf_q.get('avg_ms', 0), 'ath_avg': ath_q.get('avg_ms', 0),
                'sf_execs': sf_q.get('executions', 0), 'ath_execs': ath_q.get('executions', 0),
                'sf_geomean': sf_q.get('geomean_ms', 0), 'ath_geomean': ath_q.get('geomean_ms', 0),
                'diff_pct': diff_pct,
                'ratio': ratio,
            })
        h2h_sorted = sorted(h2h_queries, key=lambda x: -x['diff_pct'])
        sf_w = sum(1 for q in h2h_sorted if q['diff_pct'] > 5)
        ath_w = sum(1 for q in h2h_sorted if q['diff_pct'] < -5)
        h2h_by_uc[uc] = {
            'sorted': h2h_sorted,
            'sf_wins': sf_w,
            'ath_wins': ath_w,
            'close': len(h2h_sorted) - sf_w - ath_w,
        }

    # Use 32u as the "primary" for overview cards and chart defaults
    h2h_primary = h2h_by_uc.get(32, h2h_by_uc.get(user_counts[0], {}))
    h2h_sorted = h2h_primary.get('sorted', [])
    sf_wins = h2h_primary.get('sf_wins', 0)
    ath_wins = h2h_primary.get('ath_wins', 0)
    close = h2h_primary.get('close', 0)

    # ── Chart.js data ──
    chart_labels_json = json.dumps([q['query'] for q in h2h_sorted])
    chart_sf_p50_json = json.dumps([round(q['sf_p50']/1000, 2) for q in h2h_sorted])
    chart_ath_p50_json = json.dumps([round(q['ath_p50']/1000, 2) for q in h2h_sorted])
    chart_sf_p99_json = json.dumps([round(q['sf_p99']/1000, 2) for q in h2h_sorted])
    chart_ath_p99_json = json.dumps([round(q['ath_p99']/1000, 2) for q in h2h_sorted])

    scaling_users_json = json.dumps([str(uc) for uc in user_counts])
    scaling_sf_qpm_json = json.dumps([round(r['sf_qpm']) for r in rows])
    scaling_ath_qpm_json = json.dumps([round(r['ath_qpm']) for r in rows])
    scaling_sf_p99_json = json.dumps([round(r['sf_p99_s'], 1) for r in rows])
    scaling_ath_p99_json = json.dumps([round(r['ath_p99_s'], 1) for r in rows])

    # ────────────────────── BEGIN HTML ──────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BI Concurrency 3TB: Snowflake vs Athena — {format_label} | {today}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    {build_css()}
</head>
<body>
    <h1>BI Concurrency 3TB: Snowflake vs Athena <span style="display:inline-block;background:#32963C;color:white;padding:4px 12px;border-radius:4px;font-size:0.7em;font-weight:600;margin-left:10px;vertical-align:middle;">{format_label}</span></h1>
    <p class="subtitle">{format_desc} — Apples-to-apples comparison at 16/32/64 concurrent users</p>

    <div class="model-note">
        <strong>Benchmark:</strong> TPC-DS 3TB BI Concurrency — 14 query types run repeatedly by 16/32/64 concurrent users over 20-minute runs.<br>
        <strong>SF:</strong> Medium ×4 MCW (4 clusters), Gen2, prod1 — fixed cost of {fmt_money(sf_cost_20min)}/20min ({credits_per_hour} credits/hr × ${price_per_credit:.2f}/credit).<br>
        <strong>Athena:</strong> Serverless ($5/TB scanned) — cost scales with query volume.
    </div>

    <div class="tab-nav">
        <button class="tab-btn active" onclick="showTab('overview', this)">Overview</button>
        <button class="tab-btn" onclick="showTab('h2h', this)">Head-to-Head</button>
        <button class="tab-btn" onclick="showTab('per-query', this)">Per-Query Detail</button>
        <button class="tab-btn" onclick="showTab('charts', this)">Charts</button>
        <button class="tab-btn" onclick="showTab('cost', this)">Cost Analysis</button>
        <button class="tab-btn" onclick="showTab('steady-state', this)">Steady-State QPS</button>
        <button class="tab-btn" onclick="showTab('reference', this)">Run Reference</button>
    </div>
"""

    # ════════════════════════════════════════════════════════════
    # TAB 1: OVERVIEW
    # ════════════════════════════════════════════════════════════
    html += f"""
    <div id="overview" class="tab-content active">
        <h2>Executive Summary</h2>

        <div class="summary-row">
            <div class="card winner">
                <div class="label">Throughput (32u)</div>
                <div class="value">{tput_ratio_32:.1f}×</div>
                <div class="detail">SF {primary['sf_qpm']:.0f} vs Athena {primary['ath_qpm']:.0f} QPM</div>
            </div>
            <div class="card winner">
                <div class="label">Price:Performance</div>
                <div class="value">{pp_ratio_32:.0f}×</div>
                <div class="detail">SF advantage ($/1000 queries)</div>
            </div>
            <div class="card sf">
                <div class="label">SF Cost (20min)</div>
                <div class="value">{fmt_money(sf_cost_20min)}</div>
                <div class="detail">Fixed — M×4 MCW Gen2</div>
            </div>
            <div class="card comp">
                <div class="label">Athena Cost (32u)</div>
                <div class="value">{fmt_money(primary['ath_cost'])}</div>
                <div class="detail">{fmt_comma(primary['ath_gb'])} GB scanned</div>
            </div>
        </div>

        <div class="insight-box winner">
            <strong>Bottom Line:</strong> On the same {format_label} tables, Snowflake M×4 Gen2 delivers
            <strong>{tput_ratio_32:.1f}× higher throughput</strong> than Athena at 32 concurrent users,
            while costing <strong>{fmt_money(sf_cost_20min)} vs {fmt_money(primary['ath_cost'])}</strong>
            for the same 20-minute run. Head-to-head, Snowflake wins <strong>{sf_wins} of 14</strong> queries on P50 latency.
        </div>

        <h3>Concurrency Scaling</h3>
        <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th style="text-align:center;">Users</th>
                    <th colspan="5">Snowflake M×4 Gen2</th>
                    <th colspan="5" class="comp">Athena Serverless</th>
                    <th>SF Edge</th>
                </tr>
                <tr>
                    <th style="text-align:center;"></th>
                    <th>Queries</th>
                    <th>QPM</th>
                    <th>P50 (s)</th>
                    <th>P99 (s)</th>
                    <th>Cost</th>
                    <th class="comp">Queries</th>
                    <th class="comp">QPM</th>
                    <th class="comp">P50 (s)</th>
                    <th class="comp">P99 (s)</th>
                    <th class="comp">Cost</th>
                    <th>Throughput</th>
                </tr>
            </thead>
            <tbody>
"""
    for r in rows:
        is_primary = r['users'] == 32
        tr_style = ' style="font-weight:700;background:#E8F4FC;"' if is_primary else ''
        ratio = r['sf_qpm'] / r['ath_qpm'] if r['ath_qpm'] > 0 else 0
        p99_warn = ' style="color:var(--red);font-weight:bold;"' if r['ath_p99_s'] > 60 else ''
        html += f"""
                <tr{tr_style}>
                    <td style="text-align:center;"><strong>{r['users']}</strong></td>
                    <td>{fmt_comma(r['sf_total'])}</td>
                    <td class="winner-cell">{r['sf_qpm']:.0f}</td>
                    <td>{r['sf_p50_s']:.2f}</td>
                    <td>{r['sf_p99_s']:.2f}</td>
                    <td style="color:var(--green);">{fmt_money(r['sf_cost'])}</td>
                    <td>{fmt_comma(r['ath_total'])}</td>
                    <td>{r['ath_qpm']:.0f}</td>
                    <td>{r['ath_p50_s']:.2f}</td>
                    <td{p99_warn}>{r['ath_p99_s']:.2f}</td>
                    <td style="color:var(--comp-orange);">{fmt_money(r['ath_cost'])}</td>
                    <td style="text-align:center;font-weight:700;color:var(--green);">{ratio:.1f}×</td>
                </tr>"""

    html += """
            </tbody>
        </table>
        </div>
"""

    # P99 warning
    r64 = next((r for r in rows if r['users'] == 64), None)
    if r64 and r64['ath_p99_s'] > 60:
        html += f"""
        <div class="insight-box warning">
            <strong>⚠️ Athena P99 Alert at 64u:</strong> Athena's P99 latency explodes to
            <strong>{r64['ath_p99_s']:.1f}s</strong> at 64 concurrent users
            (vs {r64['sf_p99_s']:.1f}s for Snowflake). A {r64['ath_p99_s']:.0f}-second tail latency
            is unacceptable for interactive BI dashboards.
        </div>"""

    html += """
    </div>
"""

    # ════════════════════════════════════════════════════════════
    # TAB 2: HEAD-TO-HEAD (all concurrency levels with sub-tabs)
    # ════════════════════════════════════════════════════════════
    html += f"""
    <div id="h2h" class="tab-content">
        <h2>Head-to-Head: Per-Query Comparison</h2>
        <p class="subtitle">Each of the 14 BI queries compared — sorted by Snowflake advantage (P50 latency)</p>

        <div class="sub-tab-nav">
"""
    for i, uc in enumerate(user_counts):
        active = ' active' if uc == 32 else ''
        html += f'            <button class="sub-tab-btn{active}" onclick="showSubTab(\'h2h\', \'h2h-{uc}u\', this)">{uc} Users</button>\n'
    html += """        </div>
"""

    for uc in user_counts:
        h2h_uc = h2h_by_uc[uc]
        h2h_uc_sorted = h2h_uc['sorted']
        uc_sf_wins = h2h_uc['sf_wins']
        uc_ath_wins = h2h_uc['ath_wins']
        uc_close = h2h_uc['close']
        uc_row = next((r for r in rows if r['users'] == uc), rows[0])
        active = ' active' if uc == 32 else ''

        html += f"""
        <div id="h2h-{uc}u" class="sub-tab-content{active}">
            <div class="summary-row">
                <div class="card winner">
                    <div class="label">SF Wins</div>
                    <div class="value">{uc_sf_wins}</div>
                    <div class="detail">of 14 queries (&gt;5% faster)</div>
                </div>
                <div class="card comp">
                    <div class="label">Athena Wins</div>
                    <div class="value">{uc_ath_wins}</div>
                    <div class="detail">of 14 queries (&gt;5% faster)</div>
                </div>
                <div class="card">
                    <div class="label">Close</div>
                    <div class="value">{uc_close}</div>
                    <div class="detail">within 5%</div>
                </div>
                <div class="card sf">
                    <div class="label">SF Geomean P50</div>
                    <div class="value">{uc_row['sf_geomean_s']:.1f}s</div>
                    <div class="detail">vs Athena {uc_row['ath_geomean_s']:.1f}s</div>
                </div>
            </div>

            <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th style="text-align:left;">Query</th>
                        <th>SF P50 (s)</th>
                        <th class="comp">Athena P50 (s)</th>
                        <th>SF P99 (s)</th>
                        <th class="comp">Athena P99 (s)</th>
                        <th>SF Execs</th>
                        <th class="comp">Athena Execs</th>
                        <th>SF Advantage</th>
                        <th>Winner</th>
                    </tr>
                </thead>
                <tbody>
"""
        for q in h2h_uc_sorted:
            sf_faster = q['diff_pct'] > 5
            ath_faster = q['diff_pct'] < -5
            if sf_faster:
                winner_badge = '<span style="background:var(--green);color:white;padding:2px 8px;border-radius:4px;font-size:0.8em;font-weight:600;">SF</span>'
            elif ath_faster:
                winner_badge = '<span style="background:var(--comp-orange);color:white;padding:2px 8px;border-radius:4px;font-size:0.8em;font-weight:600;">Athena</span>'
            else:
                winner_badge = '<span style="background:#999;color:white;padding:2px 8px;border-radius:4px;font-size:0.8em;">~Tie</span>'

            adv_color = 'var(--green)' if q['diff_pct'] > 0 else 'var(--red)'
            p50_winner = 'winner-cell' if q['sf_p50'] < q['ath_p50'] else ''
            p50_loser = 'winner-cell' if q['ath_p50'] < q['sf_p50'] else ''
            p99_warn = ' style="color:var(--red);font-weight:bold;"' if q['ath_p99'] > 60000 else ''

            html += f"""
                    <tr>
                        <td><span class="query-name" data-desc="{q['desc']}">{q['query']}</span></td>
                        <td class="{p50_winner}">{q['sf_p50']/1000:.2f}</td>
                        <td class="{p50_loser}">{q['ath_p50']/1000:.2f}</td>
                        <td>{q['sf_p99']/1000:.2f}</td>
                        <td{p99_warn}>{q['ath_p99']/1000:.2f}</td>
                        <td>{q['sf_execs']:,}</td>
                        <td>{q['ath_execs']:,}</td>
                        <td style="color:{adv_color};font-weight:700;text-align:right;">{q['diff_pct']:+.0f}%</td>
                        <td style="text-align:center;">{winner_badge}</td>
                    </tr>"""

        html += """
                </tbody>
            </table>
            </div>
        </div>
"""

    html += """
        <div class="insight-box">
            <strong>How to read:</strong> "SF Advantage" shows how much faster Snowflake's P50 is vs Athena's P50.
            Positive = SF faster. Sorted by biggest SF advantage first.
            Hover over query names to see descriptions.
        </div>
    </div>
"""

    # ════════════════════════════════════════════════════════════
    # TAB 3: PER-QUERY DETAIL (all concurrency levels)
    # ════════════════════════════════════════════════════════════
    html += """
    <div id="per-query" class="tab-content">
        <h2>Per-Query Latency Across Concurrency Levels</h2>
        <p class="subtitle">P50 and P99 latency for each query at 16/32/64 users — both platforms side by side</p>
"""

    for q in QUERY_ORDER:
        desc = QUERY_DESCRIPTIONS.get(q, '')
        html += f"""
        <h3><span class="query-name" data-desc="{desc}">{q}</span> — <span style="font-weight:normal;color:var(--sf-gray);font-size:0.85em;">{desc}</span></h3>
        <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th style="text-align:center;">Users</th>
                    <th>SF P50 (s)</th>
                    <th>SF P99 (s)</th>
                    <th>SF Avg (s)</th>
                    <th>SF Execs</th>
                    <th class="comp">Ath P50 (s)</th>
                    <th class="comp">Ath P99 (s)</th>
                    <th class="comp">Ath Avg (s)</th>
                    <th class="comp">Ath Execs</th>
                    <th>P50 Δ</th>
                    <th>P99 Δ</th>
                </tr>
            </thead>
            <tbody>
"""
        for r in rows:
            sf_q = r['sf_per_query'].get(q, {})
            ath_q = r['ath_per_query'].get(q, {})
            sf_p50 = sf_q.get('p50_ms', 0)
            ath_p50 = ath_q.get('p50_ms', 0)
            sf_p99 = sf_q.get('p99_ms', 0)
            ath_p99 = ath_q.get('p99_ms', 0)

            p50_diff = ((ath_p50 - sf_p50) / ath_p50 * 100) if ath_p50 > 0 else 0
            p99_diff = ((ath_p99 - sf_p99) / ath_p99 * 100) if ath_p99 > 0 else 0
            p50_color = 'var(--green)' if p50_diff > 0 else 'var(--red)'
            p99_color = 'var(--green)' if p99_diff > 0 else 'var(--red)'
            p99_warn = ' style="color:var(--red);font-weight:bold;"' if ath_p99 > 60000 else ''

            is_primary = r['users'] == 32
            tr_style = ' style="font-weight:600;background:#E8F4FC;"' if is_primary else ''

            html += f"""
                <tr{tr_style}>
                    <td style="text-align:center;"><strong>{r['users']}</strong></td>
                    <td>{sf_p50/1000:.2f}</td>
                    <td>{sf_p99/1000:.2f}</td>
                    <td>{sf_q.get('avg_ms', 0)/1000:.2f}</td>
                    <td>{sf_q.get('executions', 0):,}</td>
                    <td>{ath_p50/1000:.2f}</td>
                    <td{p99_warn}>{ath_p99/1000:.2f}</td>
                    <td>{ath_q.get('avg_ms', 0)/1000:.2f}</td>
                    <td>{ath_q.get('executions', 0):,}</td>
                    <td style="color:{p50_color};font-weight:600;">{p50_diff:+.0f}%</td>
                    <td style="color:{p99_color};font-weight:600;">{p99_diff:+.0f}%</td>
                </tr>"""
        html += """
            </tbody>
        </table>
        </div>
"""

    html += """
    </div>
"""

    # ════════════════════════════════════════════════════════════
    # TAB 4: CHARTS
    # ════════════════════════════════════════════════════════════
    html += f"""
    <div id="charts" class="tab-content">
        <h2>Visual Comparisons</h2>

        <div class="chart-grid">
            <div class="chart-container">
                <h3 style="text-align:center;margin-top:0;">Throughput Scaling (QPM)</h3>
                <canvas id="chart-qpm" height="280"></canvas>
            </div>
            <div class="chart-container">
                <h3 style="text-align:center;margin-top:0;">P99 Latency Scaling (seconds)</h3>
                <canvas id="chart-p99-scaling" height="280"></canvas>
            </div>
        </div>

        <div class="chart-container">
            <h3 style="text-align:center;margin-top:0;">Per-Query P50 Latency at 32 Users (seconds) — Lower is Better</h3>
            <canvas id="chart-h2h-p50" height="350"></canvas>
        </div>

        <div class="chart-container">
            <h3 style="text-align:center;margin-top:0;">Per-Query P99 Latency at 32 Users (seconds) — Lower is Better</h3>
            <canvas id="chart-h2h-p99" height="350"></canvas>
        </div>
    </div>
"""

    # ════════════════════════════════════════════════════════════
    # TAB 5: COST ANALYSIS
    # ════════════════════════════════════════════════════════════
    html += f"""
    <div id="cost" class="tab-content">
        <h2>Cost Analysis</h2>

        <div class="model-note">
            <strong>⚠️ Different pricing models:</strong>
            Snowflake charges a fixed rate per compute-hour (M×4 MCW = {credits_per_hour} credits/hr × ${price_per_credit:.2f}/credit = ${credits_per_hour * price_per_credit:.2f}/hr).
            Athena charges $5/TB scanned — cost scales with query volume.
            <strong>SF cost is the same regardless of concurrency level.</strong> Athena cost grows with more users.
        </div>

        <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th style="text-align:center;">Users</th>
                    <th>SF QPM</th>
                    <th>SF Cost</th>
                    <th>SF $/1000q</th>
                    <th class="comp">Ath QPM</th>
                    <th class="comp">Ath GB Scanned</th>
                    <th class="comp">Ath Cost</th>
                    <th class="comp">Ath $/1000q</th>
                    <th>Price:Perf</th>
                </tr>
            </thead>
            <tbody>
"""
    for r in rows:
        pp = r['ath_cost_per_1k'] / r['sf_cost_per_1k'] if r['sf_cost_per_1k'] > 0 else 0
        is_primary = r['users'] == 32
        tr_style = ' style="font-weight:700;background:#E8F4FC;"' if is_primary else ''
        html += f"""
                <tr{tr_style}>
                    <td style="text-align:center;"><strong>{r['users']}</strong></td>
                    <td>{r['sf_qpm']:.0f}</td>
                    <td style="color:var(--green);">{fmt_money(r['sf_cost'])}</td>
                    <td class="winner-cell">{fmt_money(r['sf_cost_per_1k'])}</td>
                    <td>{r['ath_qpm']:.0f}</td>
                    <td>{fmt_comma(r['ath_gb'])}</td>
                    <td style="color:var(--comp-orange);">{fmt_money(r['ath_cost'])}</td>
                    <td>{fmt_money(r['ath_cost_per_1k'])}</td>
                    <td style="text-align:center;font-weight:700;color:var(--green);">{pp:.1f}×</td>
                </tr>"""

    html += """
            </tbody>
        </table>
        </div>

        <div class="insight-box winner">
            <strong>Key Insight:</strong> Snowflake's fixed-cost model means the price:performance advantage
            <em>increases</em> with concurrency — Athena scans more data as it runs more queries,
            while Snowflake's M×4 MCW cost stays constant.
        </div>
    </div>
"""

    # ════════════════════════════════════════════════════════════
    # TAB 6: STEADY-STATE QPS
    # ════════════════════════════════════════════════════════════
    html += """
    <div id="steady-state" class="tab-content">
        <h2>Steady-State Throughput (QPS)</h2>
        <p class="subtitle">Middle 40% of run — excludes ramp-up and ramp-down artifacts</p>

        <div class="model-note">
            <strong>Methodology:</strong> Steady-state QPS is measured from the middle 40% of the 20-minute run
            (seconds 360–840). This excludes ramp-up (cold caches, connection setup) and ramp-down
            (stragglers completing). CV% = coefficient of variation — lower means more stable throughput.
        </div>

        <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th style="text-align:center;">Users</th>
                    <th>Platform</th>
                    <th>Run Key</th>
                    <th>SS Seconds</th>
                    <th>SS Queries</th>
                    <th>SS QPS</th>
                    <th>QPS StdDev</th>
                    <th>CV%</th>
                </tr>
            </thead>
            <tbody>
"""
    for r in rows:
        for platform, ss, rk in [('Snowflake', r['sf_ss'], r['sf_run_key']),
                                   ('Athena', r['ath_ss'], r['ath_run_key'])]:
            if not ss:
                continue
            plat_style = 'color:var(--sf-blue);font-weight:600;' if platform == 'Snowflake' else 'color:var(--comp-orange);font-weight:600;'
            cv = ss.get('cv_pct', 0)
            cv_color = 'var(--green)' if cv < 30 else ('var(--comp-orange)' if cv < 50 else 'var(--red)')
            html += f"""
                <tr>
                    <td style="text-align:center;"><strong>{r['users']}</strong></td>
                    <td style="{plat_style}">{platform}</td>
                    <td style="font-family:monospace;">{rk}</td>
                    <td>{ss.get('steady_state_seconds', 0)}</td>
                    <td>{ss.get('total_steady_queries', 0):,}</td>
                    <td style="font-weight:700;">{ss.get('steady_state_qps', 0):.2f}</td>
                    <td>{ss.get('qps_stddev', 0):.2f}</td>
                    <td style="color:{cv_color};">{cv:.1f}%</td>
                </tr>"""

    html += """
            </tbody>
        </table>
        </div>
    </div>
"""

    # ════════════════════════════════════════════════════════════
    # TAB 7: RUN REFERENCE
    # ════════════════════════════════════════════════════════════
    html += """
    <div id="reference" class="tab-content">
        <h2>Included Runs</h2>
        <p class="subtitle">All benchmark runs used in this report. Verify run keys and dates before sharing.</p>

        <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th style="text-align:left;">Platform</th>
                    <th style="text-align:left;">Format</th>
                    <th>Users</th>
                    <th style="text-align:left;">Run Key</th>
                    <th style="text-align:left;">Run Date</th>
                    <th style="text-align:left;">WH Type</th>
                    <th>Total Queries</th>
                    <th>GB Scanned</th>
                    <th>Cost</th>
                </tr>
            </thead>
            <tbody>
"""
    for r in rows:
        sf_meta = sf_runs.get(r['users'], {}).get('metadata', {})
        ath_meta = ath_runs.get(r['users'], {}).get('metadata', {})
        html += f"""
                <tr>
                    <td><span style="color:var(--sf-blue);font-weight:600;">Snowflake</span></td>
                    <td>{format_label}</td>
                    <td style="text-align:center;">{r['users']}</td>
                    <td style="font-family:monospace;">{r['sf_run_key']}</td>
                    <td>{sf_meta.get('run_date', '—')}</td>
                    <td>{sf_meta.get('wh_type', '—')}</td>
                    <td>{fmt_comma(r['sf_total'])}</td>
                    <td>—</td>
                    <td style="color:var(--green);">{fmt_money(r['sf_cost'])}</td>
                </tr>
                <tr style="background:var(--comp-light);">
                    <td><span style="color:var(--comp-orange);font-weight:600;">Athena</span></td>
                    <td>{format_label}</td>
                    <td style="text-align:center;">{r['users']}</td>
                    <td style="font-family:monospace;">{r['ath_run_key']}</td>
                    <td>{ath_meta.get('run_date', '—')}</td>
                    <td>Serverless</td>
                    <td>{fmt_comma(r['ath_total'])}</td>
                    <td>{fmt_comma(r['ath_gb'])} GB</td>
                    <td style="color:var(--comp-orange);">{fmt_money(r['ath_cost'])}</td>
                </tr>"""

    html += """
            </tbody>
        </table>
        </div>
    </div>
"""

    # ── FOOTER ──
    html += f"""
    <div class="footer">
        <p><strong>Report generated:</strong> {today_display} | <strong>Format:</strong> {format_label}</p>
        <p><strong>Benchmark:</strong> TPC-DS 3TB BI Concurrency — 14 query types, 20-minute runs, 16/32/64 concurrent users</p>
        <p><strong>SF Config:</strong> Medium ×4 MCW (4 clusters), Gen2, prod1 | {credits_per_hour} credits/hr × ${price_per_credit:.2f}/credit = {fmt_money(sf_cost_20min)}/20min</p>
        <p><strong>Athena:</strong> Serverless, $5/TB scanned, {'Horizon' if format_key == 'managed' else 'Glue'} catalog, us-west-2</p>
        <p><strong>14 Queries:</strong> {', '.join(QUERY_ORDER)}</p>
        <p style="margin-top:10px;font-size:0.9em;color:#999;">Generated by generate-concurrency-report.py | Data: concurrency-data.json</p>
    </div>
"""

    # ── Chart.js scripts ──
    html += f"""
    {build_tab_js()}
    <script>
    // ── Throughput scaling ──
    new Chart(document.getElementById('chart-qpm'), {{
        type: 'bar',
        data: {{
            labels: {scaling_users_json},
            datasets: [
                {{label: 'Snowflake', data: {scaling_sf_qpm_json}, backgroundColor: '#29B5E8', borderRadius: 4}},
                {{label: 'Athena', data: {scaling_ath_qpm_json}, backgroundColor: '#FF9900', borderRadius: 4}},
            ]
        }},
        options: {{
            responsive: true,
            plugins: {{legend: {{position: 'bottom'}}, title: {{display: false}}}},
            scales: {{
                x: {{title: {{display: true, text: 'Concurrent Users'}}}},
                y: {{title: {{display: true, text: 'Queries per Minute (QPM)'}}, beginAtZero: true}}
            }}
        }}
    }});

    // ── P99 latency scaling ──
    new Chart(document.getElementById('chart-p99-scaling'), {{
        type: 'bar',
        data: {{
            labels: {scaling_users_json},
            datasets: [
                {{label: 'Snowflake P99', data: {scaling_sf_p99_json}, backgroundColor: '#29B5E8', borderRadius: 4}},
                {{label: 'Athena P99', data: {scaling_ath_p99_json}, backgroundColor: '#FF9900', borderRadius: 4}},
            ]
        }},
        options: {{
            responsive: true,
            plugins: {{legend: {{position: 'bottom'}}, title: {{display: false}}}},
            scales: {{
                x: {{title: {{display: true, text: 'Concurrent Users'}}}},
                y: {{title: {{display: true, text: 'P99 Latency (seconds)'}}, beginAtZero: true}}
            }}
        }}
    }});

    // ── Per-query P50 at 32u ──
    new Chart(document.getElementById('chart-h2h-p50'), {{
        type: 'bar',
        data: {{
            labels: {chart_labels_json},
            datasets: [
                {{label: 'Snowflake P50', data: {chart_sf_p50_json}, backgroundColor: '#29B5E8', borderRadius: 4}},
                {{label: 'Athena P50', data: {chart_ath_p50_json}, backgroundColor: '#FF9900', borderRadius: 4}},
            ]
        }},
        options: {{
            responsive: true,
            indexAxis: 'y',
            plugins: {{legend: {{position: 'bottom'}}}},
            scales: {{
                x: {{title: {{display: true, text: 'P50 Latency (seconds)'}}, beginAtZero: true}},
                y: {{ticks: {{font: {{size: 11}}}}}}
            }}
        }}
    }});

    // ── Per-query P99 at 32u ──
    new Chart(document.getElementById('chart-h2h-p99'), {{
        type: 'bar',
        data: {{
            labels: {chart_labels_json},
            datasets: [
                {{label: 'Snowflake P99', data: {chart_sf_p99_json}, backgroundColor: '#29B5E8', borderRadius: 4}},
                {{label: 'Athena P99', data: {chart_ath_p99_json}, backgroundColor: '#FF9900', borderRadius: 4}},
            ]
        }},
        options: {{
            responsive: true,
            indexAxis: 'y',
            plugins: {{legend: {{position: 'bottom'}}}},
            scales: {{
                x: {{title: {{display: true, text: 'P99 Latency (seconds)'}}, beginAtZero: true}},
                y: {{ticks: {{font: {{size: 11}}}}}}
            }}
        }}
    }});
    </script>
"""

    html += """
</body>
</html>
"""
    return html, slug, today


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Generate BI Concurrency benchmark reports')
    parser.add_argument('--data', required=True, help='Path to concurrency-data.json')
    parser.add_argument('--format', choices=['managed', 'spark', 'all'], default='all',
                        help='Which format to generate (default: all)')
    parser.add_argument('--output-dir', default='.', help='Output directory for HTML reports')
    parser.add_argument('--sf-credits-per-hour', type=float, default=16,
                        help='SF credits/hr (M×4 MCW = 16)')
    parser.add_argument('--sf-price-per-credit', type=float, default=2.70,
                        help='$/credit (EE = $2.70)')
    parser.add_argument('--run-duration-min', type=float, default=20,
                        help='Run duration in minutes')
    parser.add_argument('--publish', action='store_true',
                        help='Create dated + _latest files')

    args = parser.parse_args()

    with open(args.data) as f:
        data = json.load(f)

    sf_cost = calc_sf_cost(args.sf_credits_per_hour, args.sf_price_per_credit, args.run_duration_min)
    os.makedirs(args.output_dir, exist_ok=True)

    formats = ['managed', 'spark'] if args.format == 'all' else [args.format]

    for fmt in formats:
        print(f"\nGenerating {fmt} report...")
        html, slug, today = generate_report(
            data, fmt, sf_cost,
            args.sf_credits_per_hour, args.sf_price_per_credit, args.run_duration_min
        )

        base_name = f"sf-{slug}-vs-athena-concurrency-3tb"
        dated_name = f"{base_name}-{today}.html"
        latest_name = f"{base_name}_latest.html"

        dated_path = os.path.join(args.output_dir, dated_name)
        latest_path = os.path.join(args.output_dir, latest_name)

        with open(dated_path, 'w') as f:
            f.write(html)
        print(f"  Wrote {dated_path} ({os.path.getsize(dated_path):,} bytes)")

        if args.publish:
            shutil.copy2(dated_path, latest_path)
            print(f"  Published {latest_path}")

    print("\nDone!")


if __name__ == '__main__':
    main()
