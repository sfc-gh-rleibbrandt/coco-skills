#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TPC-DS 10TB Price:Performance Report Generator

Generates self-contained HTML reports comparing Snowflake vs a serverless
competitor (e.g., Athena) on TPC-DS 10TB power/serial runs.

Key insight: The competitor is serverless with a SINGLE price point (pay-per-scan),
while Snowflake has multiple warehouse sizes. This report answers:
  1. "At the competitor's budget, how much faster is SF?"
  2. "To beat the competitor's latency, what does SF cost?"
  3. "What's the price:performance frontier across SF sizes?"

Tabs: Overview | EE Analysis | SE Analysis | Graphs | Head-to-Head | SF Scaling | Query Reference

Usage:
    python generate-tpcds-price-perf.py \
        --sf-runs 3761057,3761059,3761060,3760798,3761053 \
        --sf-sizes S,M,L,XL,2XL \
        --competitor-run 3473166 \
        --competitor-name "Athena" \
        --competitor-cost 10.30 \
        --output sf-vs-athena-10tb.html

Requires: snowflake-connector-python
"""

import argparse
import json
import math
import os
import shutil
import sys
from datetime import datetime
from typing import Dict, List, Tuple, Optional

try:
    import snowflake.connector
except ImportError:
    print("ERROR: snowflake-connector-python required. Install with: pip install snowflake-connector-python")
    sys.exit(1)

# Shared TPC-DS category utilities
from tpcds_categories import (
    QUERY_CLASSIFICATIONS as SHARED_QUERY_CLASSIFICATIONS,
    calc_category_geomean, calc_category_total,
    build_category_breakdown, render_category_table_html,
    render_size_category_sections_html, get_category, get_category_queries
)


# =============================================================================
# CONSTANTS
# =============================================================================

# TPC-DS Query Classifications (per TPC-DS spec)
# Note: query names use NO leading zeros (q1, q7, q14a) to match DBX report format
QUERY_CLASSIFICATIONS = {
    'Reporting': ['q1','q2','q3','q5','q7','q12','q13','q15','q17','q18','q20','q25','q26','q42','q43','q52','q53','q55','q62','q89','q98','q99'],
    'Ad-hoc': ['q6','q8','q19','q32','q34','q40','q45','q46','q48','q61','q63','q68','q73','q79','q88','q90','q92','q96'],
    'OLAP': ['q4','q9','q10','q11','q14a','q14b','q22','q23a','q23b','q27','q28','q31','q33','q35','q36','q38','q44','q47','q49','q51','q54','q56','q57','q58','q59','q60','q64','q65','q66','q67','q70','q71','q74','q75','q76','q77','q78','q80','q86','q87','q97'],
    'Data Mining': ['q16','q21','q24a','q24b','q29','q30','q37','q39a','q39b','q41','q50','q69','q72','q81','q82','q83','q84','q85','q91','q93','q94','q95']
}

# TPC-DS Query Descriptions
QUERY_DESCRIPTIONS = {
    'q1': 'Find customers who have returned items more than 20% of the average return rate for their state',
    'q2': 'Compare weekly sales for each item and week against same week last year',
    'q3': 'Report sales by brand in a specific category for items sold in November',
    'q4': 'Find customers who spent more in stores than online/catalog this year vs last year',
    'q5': 'Report on sales, returns, and profit by store and item category',
    'q6': 'List states with above-average catalog sales for customers with specific demographics',
    'q7': 'Compute average quantity, price, and profit by promotion status for items sold with a promotion',
    'q8': 'Compute net profit from store sales for customers in specific zip codes',
    'q9': 'Find reason for excess inventory: compare store sales across 5 buckets of quantity ranges',
    'q10': 'Find customers who have purchased from all 3 channels (store, web, catalog) in a given year',
    'q11': 'Find customers whose increase in web/catalog sales exceeds store sales increase year-over-year',
    'q12': 'Find web page types with above-average session duration from catalog sales',
    'q13': 'Calculate average sales by demographic, promotion, and item attributes for store channel',
    'q14a': 'Find items sold through multiple channels (store/web/catalog) in the same quarter - Part 1',
    'q14b': 'Find items sold through multiple channels (store/web/catalog) in the same quarter - Part 2',
    'q15': 'Report catalog sales revenue by state for a specific month',
    'q16': 'Identify counties where orders were returned more than they were ordered (potential fraud)',
    'q17': 'Compute sales by store, promotion, quarter for items that were returned',
    'q18': 'Calculate revenue by item class, state, and customer demographics for catalog channel',
    'q19': 'Find items with highest revenue-to-profit ratio sold via specific retail channel in December',
    'q20': 'Report catalog sales by item, state for a specified date range',
    'q21': 'Find inventory items with quantity on hand larger than average for their warehouse',
    'q22': 'Compute inventory rollup by item, warehouse using ROLLUP grouping',
    'q23a': 'Find items with negative profit in store channel, show their catalog/web sales - Part 1',
    'q23b': 'Find items with negative profit in store channel, show their catalog/web sales - Part 2',
    'q24a': 'Find customers with substantial returns in given state, calculate net loss - Part 1',
    'q24b': 'Find customers with substantial returns in given state, calculate net loss - Part 2',
    'q25': 'Calculate sales and returns by store and item for items sold and returned in the same quarter',
    'q26': 'Compute average quantity, list price, coupon amount by promotion for catalog channel',
    'q27': 'Analyze store sales by customer demographics with ROLLUP aggregation',
    'q28': 'Calculate store sales for different quantity ranges by item and analyze distribution',
    'q29': 'Find items purchased at store, returned at store, and then purchased from catalog',
    'q30': 'Find customers with high returns in specific state using web channel',
    'q31': 'Compare web and store sales by county for counties where web sales grew more than store sales',
    'q32': 'Compute catalog sales for items with price exceeding 2x the category average',
    'q33': 'Calculate sales revenue across all 3 channels for specific manufacturers and categories',
    'q34': 'Find customers who made purchases in specific counties with ticket count in range',
    'q35': 'Find customers with store purchases who also bought from web or catalog',
    'q36': 'Compute store sales gross margin ranked by store using ROLLUP',
    'q37': 'Find inventory items with specific characteristics (price, color, units)',
    'q38': 'Count distinct customers who purchased from all 3 channels in a 30-day window',
    'q39a': 'Compute inventory deviation from expected levels by item and warehouse - Part 1',
    'q39b': 'Compute inventory deviation from expected levels by item and warehouse - Part 2',
    'q40': 'Calculate catalog sales for items sold at discounted price during specific dates',
    'q41': 'Find all products manufactured by specific manufacturers',
    'q42': 'Compute monthly sales totals by item, month for items in a given category',
    'q43': 'Report weekly store sales by store for weeks in a specific month',
    'q44': 'Find best and worst performing items by net profit in store channel',
    'q45': 'Find web sales for customers in specific zip codes with household demographics',
    'q46': 'Analyze store sales by customer household demographics and city',
    'q47': 'Compute month-over-month sales variance by item and store (time-series analysis)',
    'q48': 'Calculate store sales revenue by demographic segment for specific date range',
    'q49': 'Compare return rates across all 3 channels by item category',
    'q50': 'Analyze store returns by return reason, duration between purchase and return',
    'q51': 'Compute running cumulative web sales compared to store sales by date',
    'q52': 'Find brand/department combinations with highest monthly store sales',
    'q53': 'Compute quarterly sales by manufacturer for selected categories',
    'q54': 'Count web customers who also made store purchases in the same month',
    'q55': 'Report monthly brand sales by manager for a specific year',
    'q56': 'Calculate cross-channel revenue for specific item colors in given month',
    'q57': 'Analyze month-over-month catalog sales by call center and item category',
    'q58': 'Compute weekly sales for items sold in all 3 channels in same week',
    'q59': 'Report weekly store sales by store, comparing to prior and following week',
    'q60': 'Calculate total revenue across all 3 channels by item category',
    'q61': 'Calculate promotional revenue ratio for store vs web sales',
    'q62': 'Report web sales by warehouse and shipping mode with ship time analysis',
    'q63': 'Compute store sales for specific brands and demographic segments',
    'q64': 'Multi-fact table join: store/catalog/web sales with promotions and demographics',
    'q65': 'Compare store revenue for preferred vs non-preferred customers by department',
    'q66': 'Calculate sales and profit across all 3 channels by warehouse using ROLLUP',
    'q67': 'Compute store sales by item, store, quarter using hierarchical ROLLUP',
    'q68': 'Find customers who made purchases from specific store locations with demographics',
    'q69': 'Find customers with store purchases who did NOT make web or catalog purchases',
    'q70': 'Compute store sales by customer state with ROLLUP for subtotals',
    'q71': 'Calculate sales by brand, item class, and time period across all channels',
    'q72': 'Calculate catalog sales for promotional items with specific inventory levels',
    'q73': 'Find customers with specific purchase patterns in given counties',
    'q74': 'Find customers with year-over-year sales growth in both web and store channels',
    'q75': 'Multi-year channel comparison: year-over-year sales change by brand and channel',
    'q76': 'Compute sales by channel and item for items not sold online in previous year',
    'q77': 'Compute profit across all 3 channels by channel type with ROLLUP',
    'q78': 'HEAVY: Multi-year web/catalog comparison for customers who decreased store purchases',
    'q79': 'Analyze store sales by customer demographics, household size, and city',
    'q80': 'Compute net profit across all 3 channels with customer demographics',
    'q81': 'Find customers with substantial catalog returns living in specific county',
    'q82': 'Find items with specific price and inventory characteristics',
    'q83': 'Calculate refund percentages across all 3 channels for specific weeks',
    'q84': 'Find specific customer demographics from store channel',
    'q85': 'Compute web sales by reason, quantity bucket for returns with specific characteristics',
    'q86': 'Calculate web sales ROLLUP by item class and revenue',
    'q87': 'Count customers who purchased from all 3 channels in specific months',
    'q88': 'Analyze store sales by hour of day, demographic, and purchase amount ranges',
    'q89': 'Report quarterly store sales by class for specific manufacturers',
    'q90': 'Compare morning vs evening web sales ratios',
    'q91': 'Find call centers with above-average return rates for given manager',
    'q92': 'Compute total web sales for items with price between 1-1.5x category average',
    'q93': 'Compute store sales for returned items by reason code',
    'q94': 'Find orders shipped from same warehouse with substantial delay',
    'q95': 'Find duplicate web orders shipped from same warehouse (variant of q94)',
    'q96': 'Count store sales by hour for specific time slots',
    'q97': 'Calculate overlap between catalog and store purchases by customer',
    'q98': 'Report catalog sales by category and class for specific months',
    'q99': 'Analyze catalog order fulfillment by warehouse and ship mode',
}

# Snowflake Gen2 Pricing (AWS: Gen2 uses 1.35x credits vs Gen1)
# Gen1 credits: XS=1, S=2, M=4, L=8, XL=16, 2XL=32, 3XL=64, 4XL=128
SF_CREDITS_PER_HOUR_GEN2 = {
    'XS': 1.35, 'S': 2.7, 'M': 5.4, 'L': 10.8, 'XL': 21.6, '2XL': 43.2, '3XL': 86.4, '4XL': 172.8
}

SF_CREDIT_RATE_SE = 2.00  # Standard Edition list price
SF_CREDIT_RATE_EE = 3.00  # Enterprise Edition list price

SIZE_ORDER = ['XS', 'S', 'M', 'L', 'XL', '2XL', '3XL', '4XL']

OKR_TARGET = 35  # 35% price:performance advantage target


# =============================================================================
# DATA FETCHING
# =============================================================================

def get_snowflake_connection():
    """Get Snowflake connection using default connection."""
    return snowflake.connector.connect(
        connection_name='snowhouse',
        authenticator='externalbrowser'
    )


def fetch_query_times(conn, run_key: int, platform: str) -> Dict[str, float]:
    """Fetch query times for a run, returning dict of query -> seconds."""

    if platform == 'snowflake':
        metric_field = "metrics:TOTAL_DURATION_MS::FLOAT / 1000"
    else:  # Athena, etc. — e2e_latency is in milliseconds
        metric_field = "metrics:\"e2e_latency\"::FLOAT / 1000"

    sql = f"""
    SELECT 
        REGEXP_REPLACE(
            REGEXP_REPLACE(query_label, 'q_tpcds_([0-9]+)([a-zA-Z0-9]*)_warm', 'q\\\\1\\\\2'),
            'P([12])', 
            CASE WHEN REGEXP_SUBSTR(query_label, 'P([12])') = 'P1' THEN 'a' ELSE 'b' END
        ) as query,
        MEDIAN({metric_field}) as seconds
    FROM bench_store.publicdata.sample_batch_pivot
    WHERE run_key = {run_key}
      AND query_label LIKE '%_warm%'
      AND query_label NOT LIKE '%_cold%'
    GROUP BY 1
    ORDER BY 1
    """

    cursor = conn.cursor()
    cursor.execute(sql)
    results = cursor.fetchall()
    cursor.close()

    # Normalize query names: q07 -> q7, q14P1 -> q14a, q14P2 -> q14b
    normalized = {}
    for row in results:
        if row[0] and row[1]:
            q = row[0]
            # Remove leading zeros: q07 -> q7
            q = q.replace('q0', 'q') if q.startswith('q0') else q
            # Convert P1/P2 to a/b (belt-and-suspenders)
            q = q.replace('P1', 'a').replace('P2', 'b')
            normalized[q] = round(row[1], 2)

    return normalized


def fetch_run_metadata(conn, run_key: int) -> Dict:
    """Fetch run metadata including warm query count."""
    sql = f"""
    SELECT 
        r.run_key,
        r.run_date,
        r.platform,
        r.tags_by_key:"warehouse_size"::STRING as wh_size,
        COALESCE(r.tags_by_key:"warehouse-type"::STRING, r.tags_by_key:"warehouse_type"::STRING) as wh_type,
        r.tags_by_key:"data-format"::STRING as data_format,
        q.warm_queries
    FROM bench_store.publicdata.run_info_v r
    LEFT JOIN (
        SELECT run_key, COUNT(DISTINCT query_label) as warm_queries
        FROM bench_store.publicdata.sample_batch_pivot
        WHERE run_key = {run_key}
          AND query_label LIKE '%_warm%'
          AND query_label NOT LIKE '%_cold%'
        GROUP BY 1
    ) q ON r.run_key = q.run_key
    WHERE r.run_key = {run_key}
    """

    cursor = conn.cursor()
    cursor.execute(sql)
    row = cursor.fetchone()
    cursor.close()

    if row:
        # Clean run_date: strip extra quotes from JSON encoding
        run_date_raw = str(row[1]).strip('"')
        return {
            'run_key': row[0],
            'run_date': run_date_raw,
            'platform': row[2],
            'wh_size': row[3],
            'wh_type': row[4],
            'data_format': row[5],
            'warm_queries': row[6] or 0
        }
    return {}


# =============================================================================
# CALCULATIONS
# =============================================================================

def calc_geomean(values: List[float]) -> float:
    """Calculate geometric mean of values. Filters zeros/nulls for robustness."""
    valid = [v for v in values if v and v > 0]
    if not valid:
        return 0
    product = 1
    for v in valid:
        product *= v
    return round(product ** (1/len(valid)), 2)


def calc_total(values: List[float]) -> float:
    """Calculate sum of values."""
    return round(sum(v for v in values if v and v > 0), 1)


def calc_sf_hourly_rate(wh_size: str, credit_rate: float) -> float:
    """Get SF hourly rate for a size and credit rate."""
    credits = SF_CREDITS_PER_HOUR_GEN2.get(wh_size, 21.6)
    return credits * credit_rate


def calc_sf_cost(runtime_seconds: float, wh_size: str, credit_rate: float) -> float:
    """Calculate Snowflake cost for a benchmark run."""
    hours = runtime_seconds / 3600
    hourly_rate = calc_sf_hourly_rate(wh_size, credit_rate)
    return round(hours * hourly_rate, 2)


def compute_stats_for_edition(sf_data: Dict, sf_sizes: List[str], credit_rate: float,
                               competitor_data: Dict, all_queries: List[str]) -> Dict:
    """Compute stats for all SF sizes + competitor at a given credit rate."""
    stats = {}
    competitor_name = competitor_data['name']

    for size in sf_sizes:
        times = sf_data[size]['times']
        values = [times.get(q, 0) for q in all_queries if q in times]
        total = calc_total(values)
        geomean = calc_geomean(values)
        cost = calc_sf_cost(total, size, credit_rate)
        hourly_rate = calc_sf_hourly_rate(size, credit_rate)
        stats[size] = {
            'total': total, 'geomean': geomean, 'cost': cost,
            'count': len([v for v in values if v and v > 0]),
            'hourly_rate': hourly_rate,
            'price_perf': round(cost * geomean, 1)
        }

    # Competitor stats (pricing-independent)
    comp_values = [competitor_data['times'].get(q, 0) for q in all_queries if q in competitor_data['times']]
    comp_total = calc_total(comp_values)
    comp_geomean = calc_geomean(comp_values)
    comp_cost = competitor_data['cost']
    stats[competitor_name] = {
        'total': comp_total, 'geomean': comp_geomean, 'cost': comp_cost,
        'count': len([v for v in comp_values if v and v > 0]),
        'hourly_rate': 0,
        'price_perf': round(comp_cost * comp_geomean, 1)
    }

    return stats


def find_best_price_perf(stats: Dict, sf_sizes: List[str]) -> Tuple[str, float]:
    """Find the SF size with best price:performance (lowest cost * geomean)."""
    best_score = float('inf')
    best_size = ''
    for size in sf_sizes:
        score = stats[size]['cost'] * stats[size]['geomean']
        if score < best_score:
            best_score = score
            best_size = size
    if math.isinf(best_score):
        best_score = 0
    return best_size, best_score


def find_budget_match(stats: Dict, sf_sizes: List[str], comp_cost: float) -> Optional[str]:
    """Find the SF size whose run cost is closest to (but not exceeding) competitor cost."""
    best_size = None
    best_diff = float('inf')

    for size in sf_sizes:
        cost = stats[size]['cost']
        if cost <= comp_cost * 1.2:  # Allow 20% buffer
            diff = abs(cost - comp_cost)
            if diff < best_diff:
                best_diff = diff
                best_size = size

    if best_size is None:
        for size in sf_sizes:
            diff = abs(stats[size]['cost'] - comp_cost)
            if diff < best_diff:
                best_diff = diff
                best_size = size

    return best_size


def find_sla_match(stats: Dict, sf_sizes: List[str], comp_geomean: float) -> Optional[str]:
    """Find the smallest (cheapest) SF size that beats competitor's geomean latency."""
    ordered = [s for s in SIZE_ORDER if s in sf_sizes]

    for size in ordered:
        if stats[size]['geomean'] <= comp_geomean:
            return size

    return None


def compute_head_to_head(sf_times: Dict[str, float], comp_times: Dict[str, float],
                         competitor_name: str, threshold_pct: float = 5.0) -> Dict:
    """Compute head-to-head query comparison between SF and competitor."""
    comparisons = []
    sf_wins = 0
    comp_wins = 0
    close = 0

    all_queries = sorted(set(sf_times.keys()) & set(comp_times.keys()))

    for q in all_queries:
        sf_t = sf_times.get(q)
        comp_t = comp_times.get(q)

        if not sf_t or not comp_t or sf_t <= 0 or comp_t <= 0:
            continue

        diff_pct = ((comp_t - sf_t) / comp_t) * 100

        if abs(diff_pct) < threshold_pct:
            winner = 'close'
            close += 1
        elif diff_pct > 0:
            winner = 'sf'
            sf_wins += 1
        else:
            winner = 'comp'
            comp_wins += 1

        category = 'Other'
        for cat, queries in QUERY_CLASSIFICATIONS.items():
            if q in queries:
                category = cat
                break

        comparisons.append({
            'query': q,
            'sf_time': sf_t,
            'comp_time': comp_t,
            'diff_pct': round(diff_pct, 1),
            'winner': winner,
            'category': category,
        })

    comparisons.sort(key=lambda x: -x['diff_pct'])

    # Category summary
    category_stats = {}
    for cat in QUERY_CLASSIFICATIONS.keys():
        cat_comps = [c for c in comparisons if c['category'] == cat]
        if cat_comps:
            cat_sf_wins = sum(1 for c in cat_comps if c['winner'] == 'sf')
            cat_comp_wins = sum(1 for c in cat_comps if c['winner'] == 'comp')
            cat_close = sum(1 for c in cat_comps if c['winner'] == 'close')
            avg_diff = sum(c['diff_pct'] for c in cat_comps) / len(cat_comps)
            category_stats[cat] = {
                'total': len(cat_comps),
                'sf_wins': cat_sf_wins,
                'comp_wins': cat_comp_wins,
                'close': cat_close,
                'avg_diff': round(avg_diff, 1)
            }

    return {
        'sf_wins': sf_wins,
        'comp_wins': comp_wins,
        'close': close,
        'total': len(comparisons),
        'comparisons': comparisons,
        'category_stats': category_stats,
    }


def compute_scaling_efficiency(sf_data: Dict, all_queries: List[str]) -> Dict[str, Dict]:
    """
    Compute scaling efficiency for each query across SF warehouse sizes.
    Uses log-log regression: T = c * N^beta. Efficiency = |beta| * 100% (capped at 100%).
    """
    sizes = list(sf_data.keys())
    ordered = [s for s in SIZE_ORDER if s in sizes]

    if len(ordered) < 2:
        return {}

    base_idx = SIZE_ORDER.index(ordered[0])
    multipliers = []
    for s in ordered:
        idx = SIZE_ORDER.index(s)
        multipliers.append(2 ** (idx - base_idx))

    results = {}
    for q in all_queries:
        times = []
        valid_mults = []
        for s, m in zip(ordered, multipliers):
            t = sf_data[s]['times'].get(q)
            if t and t > 0:
                times.append(t)
                valid_mults.append(m)

        if len(times) < 2:
            results[q] = {'beta': None, 'efficiency': None, 'sparkline': [sf_data[s]['times'].get(q) for s in ordered]}
            continue

        log_n = [math.log(m) for m in valid_mults]
        log_t = [math.log(t) for t in times]

        n = len(log_n)
        sum_x = sum(log_n)
        sum_y = sum(log_t)
        sum_xy = sum(x * y for x, y in zip(log_n, log_t))
        sum_xx = sum(x * x for x in log_n)

        denom = n * sum_xx - sum_x * sum_x
        if denom == 0:
            beta = 0
        else:
            beta = (n * sum_xy - sum_x * sum_y) / denom

        efficiency = min(abs(beta) * 100, 100)

        results[q] = {
            'beta': round(beta, 3),
            'efficiency': round(efficiency, 1),
            'sparkline': [sf_data[s]['times'].get(q) for s in ordered]
        }

    return results


# =============================================================================
# DUAL-ANCHOR TIER FUNCTIONS (Price Anchor + Performance Anchor)
# =============================================================================

def build_athena_price_tiers(sf_stats: Dict, num_tiers: int = 4) -> List[Dict]:
    """
    Build price tiers from SF hourly rates using log-spacing.

    Since the competitor is serverless (single price point), tiers are derived
    entirely from SF's rate range. Each tier answers: "At this hourly budget,
    how does SF compare to the serverless competitor?"
    """
    import numpy as np

    sf_rates = sorted([s['hourly_rate'] for s in sf_stats.values()
                       if s.get('hourly_rate') and s['hourly_rate'] > 0])
    if not sf_rates:
        return []

    # Log-spaced centres across SF's rate range
    centres = np.geomspace(sf_rates[0], sf_rates[-1], num_tiers)

    def _nice(x):
        if x < 10:
            return round(x)
        elif x < 100:
            return round(x / 5) * 5
        else:
            return round(x / 10) * 10

    tiers = []
    for i, c in enumerate(centres):
        if i == 0:
            lo = 0
            hi = (c + centres[i + 1]) / 2 if i + 1 < len(centres) else c * 1.5
        elif i == len(centres) - 1:
            lo = (centres[i - 1] + c) / 2
            hi = c * 1.5
        else:
            lo = (centres[i - 1] + c) / 2
            hi = (c + centres[i + 1]) / 2

        lo_nice = _nice(lo) if lo > 0 else 0
        hi_nice = _nice(hi)
        tiers.append({'label': f'~${lo_nice}-{hi_nice}/hr', 'min': lo_nice, 'max': hi_nice})

    return tiers[:num_tiers]


def build_athena_perf_tiers(sf_stats: Dict, comp_geomean: float,
                            num_tiers: int = 4) -> List[Dict]:
    """
    Build performance (SLA) tiers using log-spacing across the full latency range.

    Tiers start just above the fastest config (SF or competitor) and extend
    to the slowest. Tight SLAs expose capability gaps; loose SLAs expose cost
    differences.
    """
    import numpy as np

    sf_geomeans = [s['geomean'] for s in sf_stats.values()
                   if s.get('geomean') and s['geomean'] > 0]
    if not sf_geomeans:
        return []

    fastest = min(min(sf_geomeans), comp_geomean) if comp_geomean > 0 else min(sf_geomeans)
    slowest = max(max(sf_geomeans), comp_geomean) if comp_geomean > 0 else max(sf_geomeans)

    min_sla = fastest * 1.1   # 10 % buffer above fastest
    max_sla = slowest * 1.05  # just above slowest

    targets = np.geomspace(min_sla, max_sla, num_tiers)

    def _nice(x):
        if x < 10:
            return round(x)
        elif x < 100:
            return round(x / 5) * 5
        else:
            return round(x / 10) * 10

    tiers = []
    seen = set()
    for t in targets:
        n = _nice(t)
        if n not in seen:
            seen.add(n)
            tiers.append({'label': f'≤{n}s SLA', 'target': n})

    return tiers[:num_tiers]


def build_price_tier_comparisons(sf_data: Dict, sf_stats: Dict,
                                 comp_times: Dict[str, float],
                                 comp_cost: float, comp_geomean: float,
                                 comp_total: float,
                                 competitor_name: str) -> List[Dict]:
    """
    For each price tier, find the best SF config and compare vs the serverless
    competitor (which is the same at every tier).
    """
    tiers = build_athena_price_tiers(sf_stats)
    comparisons = []

    for tier in tiers:
        # Find best-performing SF size in this hourly-rate range
        best_sf_size = None
        best_sf = None
        for size, st in sf_stats.items():
            if size == competitor_name:
                continue
            hr = st.get('hourly_rate', 0)
            if tier['min'] <= hr <= tier['max']:
                if best_sf is None or st['geomean'] < best_sf['geomean']:
                    best_sf_size = size
                    best_sf = st

        if best_sf is None:
            continue  # no SF config in this tier

        # Winner by geomean
        if best_sf['geomean'] < comp_geomean:
            winner = 'SF'
            ratio = round(comp_geomean / best_sf['geomean'], 2)
        else:
            winner = competitor_name
            ratio = round(best_sf['geomean'] / comp_geomean, 2)

        # Category breakdown
        sf_times = sf_data[best_sf_size]['times']
        categories = []
        for cat in QUERY_CLASSIFICATIONS:
            from tpcds_categories import calc_category_geomean as _cg, calc_category_total as _ct
            sf_cg = _cg(sf_times, cat)
            comp_cg = _cg(comp_times, cat)
            sf_ct = _ct(sf_times, cat)
            comp_ct = _ct(comp_times, cat)

            if sf_cg > 0 and comp_cg > 0:
                cat_winner = 'SF' if sf_cg < comp_cg else competitor_name
                cat_ratio = round(comp_cg / sf_cg, 2) if cat_winner == 'SF' else round(sf_cg / comp_cg, 2)
            else:
                cat_winner = '-'
                cat_ratio = 0

            categories.append({
                'category': cat,
                'count': len(QUERY_CLASSIFICATIONS[cat]),
                'sf_geomean': sf_cg, 'sf_total': sf_ct,
                'comp_geomean': comp_cg, 'comp_total': comp_ct,
                'winner': cat_winner, 'ratio': cat_ratio
            })

        comparisons.append({
            'tier': tier['label'],
            'sf_size': best_sf_size,
            'sf_geomean': best_sf['geomean'],
            'sf_total': best_sf['total'],
            'sf_cost': best_sf['cost'],
            'sf_hourly': best_sf['hourly_rate'],
            'comp_geomean': comp_geomean,
            'comp_total': comp_total,
            'comp_cost': comp_cost,
            'winner': winner, 'ratio': ratio,
            'categories': categories
        })

    return comparisons


def build_perf_tier_comparisons(sf_data: Dict, sf_stats: Dict,
                                comp_times: Dict[str, float],
                                comp_cost: float, comp_geomean: float,
                                comp_hourly: float,  # 0 for serverless
                                competitor_name: str) -> List[Dict]:
    """
    For each SLA tier, find the cheapest SF config that meets it and check
    whether the competitor can also meet it. Exposes capability gaps.
    """
    tiers = build_athena_perf_tiers(sf_stats, comp_geomean)
    comparisons = []

    for tier in tiers:
        target = tier['target']

        # Cheapest SF that meets SLA
        sf_size = None
        sf_best = None
        for size, st in sf_stats.items():
            if size == competitor_name:
                continue
            if st['geomean'] <= target:
                if sf_best is None or st['hourly_rate'] < sf_best['hourly_rate']:
                    sf_size = size
                    sf_best = st

        # Does competitor meet the SLA?
        comp_meets = comp_geomean <= target

        # Determine winner (by cost) and build entry
        entry = {'tier': tier['label'], 'sla_target': target}

        if sf_best and comp_meets:
            # Both meet — compare costs (run cost for a fair single-run comparison)
            if sf_best['cost'] < comp_cost:
                winner = 'SF'
                savings = round((1 - sf_best['cost'] / comp_cost) * 100)
            else:
                winner = competitor_name
                savings = round((1 - comp_cost / sf_best['cost']) * 100)

            entry.update({
                'sf_size': sf_size, 'sf_geomean': sf_best['geomean'],
                'sf_hourly': sf_best['hourly_rate'], 'sf_cost': sf_best['cost'],
                'comp_geomean': comp_geomean, 'comp_cost': comp_cost,
                'comp_meets': True,
                'winner': winner, 'savings': savings,
                'capability_gap': False,
            })
        elif sf_best and not comp_meets:
            # Only SF meets — capability gap
            entry.update({
                'sf_size': sf_size, 'sf_geomean': sf_best['geomean'],
                'sf_hourly': sf_best['hourly_rate'], 'sf_cost': sf_best['cost'],
                'comp_geomean': comp_geomean, 'comp_cost': comp_cost,
                'comp_meets': False,
                'winner': 'SF', 'savings': 100,
                'capability_gap': True,
            })
        elif not sf_best and comp_meets:
            # Only competitor meets
            entry.update({
                'sf_size': '—', 'sf_geomean': 0, 'sf_hourly': 0, 'sf_cost': 0,
                'comp_geomean': comp_geomean, 'comp_cost': comp_cost,
                'comp_meets': True,
                'winner': competitor_name, 'savings': 100,
                'capability_gap': True,
            })
        else:
            continue  # neither meets — skip tier

        # Category breakdown (only if SF has a config)
        cats = []
        if sf_size:
            sf_times = sf_data[sf_size]['times']
            for cat in QUERY_CLASSIFICATIONS:
                from tpcds_categories import calc_category_geomean as _cg, calc_category_total as _ct
                sf_cg = _cg(sf_times, cat)
                comp_cg = _cg(comp_times, cat)
                sf_ct = _ct(sf_times, cat)
                comp_ct = _ct(comp_times, cat)

                if sf_cg > 0 and comp_cg > 0:
                    cat_winner = 'SF' if sf_cg < comp_cg else competitor_name
                    cat_ratio = (round(comp_cg / sf_cg, 2) if cat_winner == 'SF'
                                 else round(sf_cg / comp_cg, 2))
                else:
                    cat_winner = '-'
                    cat_ratio = 0

                cats.append({
                    'category': cat,
                    'count': len(QUERY_CLASSIFICATIONS[cat]),
                    'sf_geomean': sf_cg, 'sf_total': sf_ct,
                    'comp_geomean': comp_cg, 'comp_total': comp_ct,
                    'winner': cat_winner, 'ratio': cat_ratio
                })
        entry['categories'] = cats
        comparisons.append(entry)

    return comparisons


def calculate_dual_anchor_okr(price_tier_comparisons: List[Dict],
                              perf_tier_comparisons: List[Dict],
                              competitor_name: str) -> Dict:
    """
    Calculate OKR metrics using both anchors, matching the DBX report pattern.

    Cost anchor: At same budget, who has better price:perf score?
    Perf anchor: At same SLA, who's cheaper?
    """
    target = OKR_TARGET  # 35 %

    # === COST ANCHOR ===
    cost_advantages = []
    for t in price_tier_comparisons:
        sf_score = t['sf_cost'] * t['sf_geomean']
        comp_score = t['comp_cost'] * t['comp_geomean']
        adv = round((1 - sf_score / comp_score) * 100, 1) if comp_score > 0 else 0
        cost_advantages.append({
            'tier': t['tier'],
            'sf_score': round(sf_score, 1), 'comp_score': round(comp_score, 1),
            'advantage': adv,
            'sf_size': t['sf_size'], 'sf_hourly': t['sf_hourly'],
            'sf_geomean': t['sf_geomean'],
            'comp_geomean': t['comp_geomean'],
        })

    cost_avg = (round(sum(a['advantage'] for a in cost_advantages) / len(cost_advantages), 1)
                if cost_advantages else 0)
    cost_meeting = sum(1 for a in cost_advantages if a['advantage'] >= target)

    # === PERF ANCHOR ===
    perf_advantages = []
    for p in perf_tier_comparisons:
        if p.get('capability_gap') and p['winner'] == 'SF' and not p.get('comp_meets', True):
            adv = 100.0  # competitor can't meet SLA — maximum advantage
        elif p['winner'] == 'SF':
            adv = float(p['savings'])
        else:
            adv = -float(p['savings'])
        perf_advantages.append({
            'tier': p['tier'],
            'advantage': adv,
            'sf_size': p['sf_size'],
            'sf_hourly': p.get('sf_hourly', 0),
            'sf_geomean': p.get('sf_geomean', 0),
            'sf_cost': p.get('sf_cost', 0),
            'comp_geomean': p.get('comp_geomean', 0),
            'comp_cost': p.get('comp_cost', 0),
            'capability_gap': p.get('capability_gap', False),
            'comp_meets': p.get('comp_meets', True),
        })

    perf_avg = (round(sum(a['advantage'] for a in perf_advantages) / len(perf_advantages), 1)
                if perf_advantages else 0)
    perf_meeting = sum(1 for a in perf_advantages if a['advantage'] >= target)

    def _grade(avg):
        score = min(avg / target, 1.0) if target > 0 else 0
        pct = score * 100
        if score >= 0.9:
            return f'🟢 {pct:.0f}%', 'okr-green'
        elif score >= 0.7:
            return f'🟡 {pct:.0f}%', 'okr-yellow'
        else:
            return f'🔴 {pct:.0f}%', 'okr-red'

    cost_grade, cost_class = _grade(cost_avg)
    perf_grade, perf_class = _grade(perf_avg)

    return {
        'target': target,
        'cost_average': cost_avg, 'cost_grade': cost_grade,
        'cost_grade_class': cost_class,
        'cost_advantages': cost_advantages,
        'cost_meeting': cost_meeting, 'cost_total': len(cost_advantages),
        'perf_average': perf_avg, 'perf_grade': perf_grade,
        'perf_grade_class': perf_class,
        'perf_advantages': perf_advantages,
        'perf_meeting': perf_meeting, 'perf_total': len(perf_advantages),
    }


def compute_okr_metrics(stats: Dict, sf_sizes: List[str], comp_score: float,
                        competitor_name: str) -> Dict:
    """Compute OKR scorecard metrics for a single-point competitor."""
    best_size, best_score = find_best_price_perf(stats, sf_sizes)

    if comp_score > 0 and best_score > 0:
        advantage = round((1 - best_score / comp_score) * 100, 1)
    else:
        advantage = 0

    score = advantage / OKR_TARGET if OKR_TARGET > 0 else 0
    if score >= 0.9:
        grade = '🟢'
        grade_class = 'okr-row-green'
    elif score >= 0.7:
        grade = '🟡'
        grade_class = 'okr-row-yellow'
    else:
        grade = '🔴'
        grade_class = 'okr-row-red'

    # What-if: competitor 20% faster → score drops to 0.64x (0.8 × 0.8)
    adjusted_comp_score = comp_score * 0.64
    if adjusted_comp_score > 0 and best_score > 0:
        whatif_advantage = round((1 - best_score / adjusted_comp_score) * 100, 1)
    else:
        whatif_advantage = 0

    whatif_score = whatif_advantage / OKR_TARGET if OKR_TARGET > 0 else 0
    if whatif_score >= 0.9:
        whatif_grade = '🟢'
        whatif_grade_class = 'okr-row-green'
    elif whatif_score >= 0.7:
        whatif_grade = '🟡'
        whatif_grade_class = 'okr-row-yellow'
    else:
        whatif_grade = '🔴'
        whatif_grade_class = 'okr-row-red'

    return {
        'best_size': best_size,
        'best_score': best_score,
        'comp_score': comp_score,
        'advantage': advantage,
        'grade': grade,
        'grade_class': grade_class,
        'target': OKR_TARGET,
        'whatif_advantage': whatif_advantage,
        'whatif_grade': whatif_grade,
        'whatif_grade_class': whatif_grade_class,
        'whatif_delta': round(advantage - whatif_advantage, 1),
        'adjusted_comp_score': adjusted_comp_score,
    }


# =============================================================================
# HTML GENERATION
# =============================================================================

def generate_html(
    sf_data: Dict[str, Dict],
    competitor_data: Dict,
    output_path: str,
    publish_date: Optional[str] = None
):
    """Generate the complete HTML report with both SE and EE analysis."""

    sf_sizes = list(sf_data.keys())
    competitor_name = competitor_data['name']

    # Get all queries (union of all runs)
    all_queries = set()
    for size_data in sf_data.values():
        all_queries.update(size_data['times'].keys())
    all_queries.update(competitor_data['times'].keys())
    all_queries = sorted(all_queries)

    # Compute stats for both editions
    stats_se = compute_stats_for_edition(sf_data, sf_sizes, SF_CREDIT_RATE_SE, competitor_data, all_queries)
    stats_ee = compute_stats_for_edition(sf_data, sf_sizes, SF_CREDIT_RATE_EE, competitor_data, all_queries)

    # Competitor score is the same regardless of edition
    comp_score_se = stats_se[competitor_name]['cost'] * stats_se[competitor_name]['geomean']
    comp_score_ee = stats_ee[competitor_name]['cost'] * stats_ee[competitor_name]['geomean']
    if math.isinf(comp_score_se):
        comp_score_se = 0
    if math.isinf(comp_score_ee):
        comp_score_ee = 0

    # Best price:perf for each edition
    best_size_se, best_score_se = find_best_price_perf(stats_se, sf_sizes)
    best_size_ee, best_score_ee = find_best_price_perf(stats_ee, sf_sizes)

    # OKR metrics
    okr_se = compute_okr_metrics(stats_se, sf_sizes, comp_score_se, competitor_name)
    okr_ee = compute_okr_metrics(stats_ee, sf_sizes, comp_score_ee, competitor_name)

    # Budget/SLA match for both
    budget_match_se = find_budget_match(stats_se, sf_sizes, competitor_data['cost'])
    budget_match_ee = find_budget_match(stats_ee, sf_sizes, competitor_data['cost'])
    sla_match_se = find_sla_match(stats_se, sf_sizes, stats_se[competitor_name]['geomean'])
    sla_match_ee = find_sla_match(stats_ee, sf_sizes, stats_ee[competitor_name]['geomean'])

    # --- Dual-anchor tier comparisons (per edition) ---
    comp_geomean_val = stats_se[competitor_name]['geomean']
    comp_total_val = stats_se[competitor_name]['total']
    comp_cost_val = competitor_data['cost']

    price_tiers_se = build_price_tier_comparisons(
        sf_data, stats_se, competitor_data['times'],
        comp_cost_val, comp_geomean_val, comp_total_val, competitor_name)
    price_tiers_ee = build_price_tier_comparisons(
        sf_data, stats_ee, competitor_data['times'],
        comp_cost_val, stats_ee[competitor_name]['geomean'],
        stats_ee[competitor_name]['total'], competitor_name)

    perf_tiers_se = build_perf_tier_comparisons(
        sf_data, stats_se, competitor_data['times'],
        comp_cost_val, comp_geomean_val, 0, competitor_name)
    perf_tiers_ee = build_perf_tier_comparisons(
        sf_data, stats_ee, competitor_data['times'],
        comp_cost_val, stats_ee[competitor_name]['geomean'], 0, competitor_name)

    dual_okr_se = calculate_dual_anchor_okr(price_tiers_se, perf_tiers_se, competitor_name)
    dual_okr_ee = calculate_dual_anchor_okr(price_tiers_ee, perf_tiers_ee, competitor_name)

    # Scaling efficiency (independent of pricing)
    scaling = compute_scaling_efficiency(sf_data, all_queries)

    # Ordered sizes for scaling tab
    ordered_sizes = [s for s in SIZE_ORDER if s in sf_sizes]

    # Compute SE rate range for tab labels
    se_rates = [SF_CREDITS_PER_HOUR_GEN2[s] * SF_CREDIT_RATE_SE for s in sf_sizes]
    ee_rates = [SF_CREDITS_PER_HOUR_GEN2[s] * SF_CREDIT_RATE_EE for s in sf_sizes]
    se_rate_range = f"${min(se_rates):.0f}-${max(se_rates):.0f}/hr"
    ee_rate_range = f"${min(ee_rates):.0f}-${max(ee_rates):.0f}/hr"

    # --- Chart data for Graphs tab ---
    sf_se_chart_data = []
    sf_ee_chart_data = []
    for size in sf_sizes:
        sf_se_chart_data.append({
            'size': size,
            'cost': stats_se[size]['cost'],
            'geomean': stats_se[size]['geomean'],
            'total': stats_se[size]['total'],
            'price_perf': round(stats_se[size]['cost'] * stats_se[size]['geomean'], 1),
        })
        sf_ee_chart_data.append({
            'size': size,
            'cost': stats_ee[size]['cost'],
            'geomean': stats_ee[size]['geomean'],
            'total': stats_ee[size]['total'],
            'price_perf': round(stats_ee[size]['cost'] * stats_ee[size]['geomean'], 1),
        })

    comp_chart_data = {
        'cost': competitor_data['cost'],
        'geomean': stats_se[competitor_name]['geomean'],
        'total': stats_se[competitor_name]['total'],
        'price_perf': round(comp_score_se, 1),
    }

    sf_se_chart_json = json.dumps(sf_se_chart_data)
    sf_ee_chart_json = json.dumps(sf_ee_chart_data)
    comp_chart_json = json.dumps(comp_chart_data)

    # --- Raw query data for dynamic H2H ---
    sf_raw_data = {}
    for size in sf_sizes:
        sf_raw_data[size] = sf_data[size]['times']
    sf_raw_json = json.dumps(sf_raw_data)
    comp_times_json = json.dumps(competitor_data['times'])

    # --- Frontier scatter data ---
    frontier_data_se = []
    for size in sf_sizes:
        frontier_data_se.append({
            'label': f'SF {size}',
            'cost': stats_se[size]['cost'],
            'geomean': stats_se[size]['geomean'],
            'total': stats_se[size]['total'],
            'is_best': size == best_size_se,
            'is_sf': True,
        })
    frontier_data_se.append({
        'label': competitor_name,
        'cost': stats_se[competitor_name]['cost'],
        'geomean': stats_se[competitor_name]['geomean'],
        'total': stats_se[competitor_name]['total'],
        'is_best': False,
        'is_sf': False,
    })
    frontier_json = json.dumps(frontier_data_se)

    # --- Overview metrics (use SE as default display) ---
    stats = stats_se
    best_size = best_size_se
    best_score = best_score_se
    comp_score = comp_score_se
    comp_time = stats[competitor_name]['total']
    comp_latency = stats[competitor_name]['geomean']
    fastest_size = min(sf_sizes, key=lambda s: stats[s]['total'])
    fastest_time = stats[fastest_size]['total']
    speed_ratio = round(comp_time / fastest_time, 1) if fastest_time > 0 else 0
    best_latency_size = min(sf_sizes, key=lambda s: stats[s]['geomean'])
    best_latency = stats[best_latency_size]['geomean']
    latency_ratio = round(comp_latency / best_latency, 1) if best_latency > 0 else 0
    price_perf_ratio = round(comp_score / best_score, 1) if best_score > 0 else 0

    # --- Publish date handling ---
    publish_badge = ''
    publish_title_suffix = ''
    if publish_date:
        publish_badge = f'<span style="display:inline-block;background:#32963C;color:white;padding:4px 12px;border-radius:4px;font-size:0.85em;font-weight:600;margin-left:10px;vertical-align:middle;">Published {publish_date}</span>'
        publish_title_suffix = f' | Published {publish_date}'

    # --- Build "Included Runs" metadata table ---
    run_metadata_rows = ''
    for size in sf_sizes:
        md = sf_data[size].get('metadata', {})
        run_date = md.get('run_date', '—')
        wh_type = md.get('wh_type', '—') or '—'
        data_fmt = md.get('data_format', '—') or '—'
        warm_q = md.get('warm_queries', '—')
        run_metadata_rows += f'''<tr>
            <td><span style="color:#29B5E8;font-weight:600;">Snowflake</span></td>
            <td><strong>{size}</strong></td>
            <td style="font-family:monospace;">{sf_data[size]["run_key"]}</td>
            <td>{run_date}</td>
            <td>{wh_type}</td>
            <td>{data_fmt}</td>
            <td style="text-align:center;">{warm_q}</td>
        </tr>'''

    comp_md = competitor_data.get('metadata', {})
    comp_run_date = comp_md.get('run_date', '—')
    comp_data_fmt = comp_md.get('data_format', '—') or '—'
    comp_warm_q = comp_md.get('warm_queries', '—')
    run_metadata_rows += f'''<tr style="background:{competitor_data.get("bg_color", "#FFF8F0")};">
        <td><span style="color:#FF9900;font-weight:600;">{competitor_name}</span></td>
        <td>serverless</td>
        <td style="font-family:monospace;">{competitor_data["run_key"]}</td>
        <td>{comp_run_date}</td>
        <td>—</td>
        <td>{comp_data_fmt}</td>
        <td style="text-align:center;">{comp_warm_q}</td>
    </tr>'''

    # --- Scaling summary ---
    sorted_scaling = sorted(
        [(q, scaling.get(q, {})) for q in all_queries if scaling.get(q, {}).get('efficiency') is not None],
        key=lambda x: -(x[1].get('efficiency') or 0)
    )
    efficiencies = [sc.get('efficiency') for _, sc in sorted_scaling if sc.get('efficiency') is not None]
    avg_efficiency = round(sum(efficiencies) / len(efficiencies), 1) if efficiencies else 0
    good_scaling = sum(1 for e in efficiencies if e >= 70)
    moderate_scaling = sum(1 for e in efficiencies if 40 <= e < 70)
    poor_scaling = sum(1 for e in efficiencies if e < 40)

    # --- Build scaling rows HTML ---
    scaling_header = ''.join(f'<th style="text-align:right;">SF {s}</th>' for s in ordered_sizes)
    scaling_rows = ''
    for q, sc in sorted_scaling:
        eff = sc.get('efficiency')
        sparkline = sc.get('sparkline', [])
        if eff is None:
            continue

        if eff >= 70:
            eff_color = '#32963C'
            eff_badge = '🟢'
        elif eff >= 40:
            eff_color = '#CC7A00'
            eff_badge = '🟡'
        else:
            eff_color = '#CC3333'
            eff_badge = '🔴'

        valid_vals = [v for v in sparkline if v is not None and v > 0]
        sparkline_svg = ''
        if len(valid_vals) >= 2:
            max_v = max(valid_vals)
            min_v = min(valid_vals)
            rng = max_v - min_v if max_v > min_v else 1
            width = 80
            height = 20
            points = []
            x_step = width / (len(valid_vals) - 1)
            for i, v in enumerate(valid_vals):
                x = i * x_step
                y = height - ((v - min_v) / rng * height)
                points.append(f'{x:.1f},{y:.1f}')
            polyline = ' '.join(points)
            sparkline_svg = f'<svg width="{width}" height="{height}" style="vertical-align:middle;"><polyline points="{polyline}" fill="none" stroke="#29B5E8" stroke-width="1.5"/></svg>'

        time_cells = ''
        for s in ordered_sizes:
            t = sf_data[s]['times'].get(q)
            t_display = f'{t:.2f}' if t else '—'
            time_cells += f'<td style="text-align:right;">{t_display}</td>'

        category = 'Other'
        for cat, queries in QUERY_CLASSIFICATIONS.items():
            if q in queries:
                category = cat
                break

        scaling_rows += f'''<tr>
            <td><strong>{q}</strong></td>
            <td style="font-size:0.85em;color:#666;">{category}</td>
            {time_cells}
            <td style="text-align:center;">{sparkline_svg}</td>
            <td style="text-align:right;color:{eff_color};font-weight:600;">{eff_badge} {eff:.0f}%</td>
        </tr>'''

    # --- Query Reference rows ---
    query_ref_rows = ""
    for cat, queries in QUERY_CLASSIFICATIONS.items():
        for q in queries:
            desc = QUERY_DESCRIPTIONS.get(q, '')
            class_tag = cat.lower().replace(' ', '').replace('-', '')
            query_ref_rows += f'<tr><td>{q}</td><td style="text-align:left;">{desc}</td><td><span class="class-tag class-{class_tag}">{cat}</span></td></tr>\n'

    # --- Build edition tab HTML helper ---
    def build_edition_tab(tab_id, edition_name, credit_rate, ed_stats, ed_best_size,
                          ed_best_score, ed_comp_score, ed_okr, ed_budget_match, ed_sla_match,
                          ed_price_tiers, ed_perf_tiers, ed_dual_okr):
        """Build the HTML for an edition analysis tab."""
        ed_comp_time = ed_stats[competitor_name]['total']
        ed_comp_latency = ed_stats[competitor_name]['geomean']
        ed_fastest = min(sf_sizes, key=lambda s: ed_stats[s]['total'])
        ed_pp_ratio = round(ed_comp_score / ed_best_score, 1) if ed_best_score > 0 else 0

        # Size comparison table
        size_rows = ''
        for size in sf_sizes:
            score = int(ed_stats[size]['cost'] * ed_stats[size]['geomean'])
            is_best = size == ed_best_size
            row_bg = ' style="background:#e8f5e9;"' if is_best else ''
            star = '  ⭐' if is_best else ''
            vs_comp = round((1 - score / ed_comp_score) * 100) if ed_comp_score > 0 else 0
            vs_color = '#32963C' if score < ed_comp_score else '#CC3333'
            vs_label = 'better' if score < ed_comp_score else 'worse'
            size_rows += f'''<tr{row_bg}>
                <td><strong>SF {size}</strong>{star}</td>
                <td style="text-align:right;">${ed_stats[size]["hourly_rate"]:.2f}/hr</td>
                <td style="text-align:right;">{int(ed_stats[size]["total"]):,}</td>
                <td style="text-align:right;">{ed_stats[size]["geomean"]:.2f}</td>
                <td style="text-align:right;">${ed_stats[size]["cost"]:.2f}</td>
                <td style="text-align:right;">{score}</td>
                <td style="text-align:right;color:{vs_color};">{vs_comp}% {vs_label}</td>
            </tr>'''

        # Budget match
        budget_html = ''
        if ed_budget_match:
            bm = ed_stats[ed_budget_match]
            bm_speed = round(ed_comp_time / bm['total'], 1) if bm['total'] > 0 else 0
            bm_latency = round(ed_comp_latency / bm['geomean'], 1) if bm['geomean'] > 0 else 0
            budget_html = f'''
        <div class="insight-box winner">
            <strong>💰 Budget Match:</strong> At {competitor_name}'s ${ed_stats[competitor_name]["cost"]:.2f} budget,
            <strong>SF {ed_budget_match}</strong> (cost: ${bm["cost"]:.2f}) delivers
            <strong>{bm_speed}x faster</strong> total runtime and <strong>{bm_latency}x lower</strong> typical query latency.
        </div>'''

        # SLA match
        sla_html = ''
        if ed_sla_match:
            sm = ed_stats[ed_sla_match]
            if sm['cost'] < ed_stats[competitor_name]['cost']:
                sla_html = f'''
        <div class="insight-box winner">
            <strong>⚡ SLA Match:</strong> To beat {competitor_name}'s {ed_comp_latency:.2f}s typical latency,
            <strong>SF {ed_sla_match}</strong> achieves {sm["geomean"]:.2f}s geomean at just <strong>${sm["cost"]:.2f}</strong>
            — {round((1 - sm["cost"]/ed_stats[competitor_name]["cost"])*100)}% cheaper than {competitor_name}'s ${ed_stats[competitor_name]["cost"]:.2f}.
        </div>'''
            else:
                sla_html = f'''
        <div class="insight-box">
            <strong>⚡ SLA Match:</strong> To beat {competitor_name}'s {ed_comp_latency:.2f}s typical latency,
            <strong>SF {ed_sla_match}</strong> achieves {sm["geomean"]:.2f}s geomean at <strong>${sm["cost"]:.2f}</strong>
            ({round((sm["cost"]/ed_stats[competitor_name]["cost"] - 1)*100)}% more, but {round(ed_comp_latency / sm["geomean"], 1)}x faster).
        </div>'''

        # === PRICE TIER TABLE ===
        price_tier_rows = ''
        for t in ed_price_tiers:
            winner_class = 'sf-winner' if t['winner'] == 'SF' else 'comp-winner'
            price_tier_rows += f'''
                <tr>
                    <td>{t['tier']}</td>
                    <td class="sf-col">SF {t['sf_size']} (${t['sf_hourly']:.0f}/hr)</td>
                    <td class="sf-col">{int(t['sf_total']):,}s</td>
                    <td class="sf-col">{t['sf_geomean']:.2f}s</td>
                    <td class="comp-col">serverless</td>
                    <td class="comp-col">{int(t['comp_total']):,}s</td>
                    <td class="comp-col">{t['comp_geomean']:.2f}s</td>
                    <td class="{winner_class}">{t['winner']} {t['ratio']}x</td>
                </tr>'''

        # === PRICE TIER CATEGORY DRILL-DOWNS ===
        price_category_sections = ''
        for t in ed_price_tiers:
            cat_rows = ''
            for c in t.get('categories', []):
                if c['winner'] == 'SF':
                    w_class = 'sf-winner'
                elif c['winner'] == competitor_name:
                    w_class = 'comp-winner'
                else:
                    w_class = ''
                ratio_str = f"{c['ratio']}x" if c['ratio'] > 0 else ''
                cat_rows += f'''
                    <tr>
                        <td><strong>{c['category']}</strong></td>
                        <td style="text-align:right;">{c['count']}</td>
                        <td class="sf-col">{c['sf_geomean']:.2f}s</td>
                        <td class="sf-col">{int(c['sf_total'])}s</td>
                        <td class="comp-col">{c['comp_geomean']:.2f}s</td>
                        <td class="comp-col">{int(c['comp_total'])}s</td>
                        <td class="{w_class}">{c['winner']} {ratio_str}</td>
                    </tr>'''

            price_category_sections += f'''
            <h3 style="margin-top:25px;color:var(--sf-dark-blue);">{t['tier']} — SF {t['sf_size']} @ ${t['sf_hourly']:.0f}/hr vs {competitor_name} (serverless)</h3>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th style="text-align:left;">Category</th>
                            <th style="text-align:right;">Queries</th>
                            <th>SF Geomean</th>
                            <th>SF Total</th>
                            <th class="comp">{competitor_name} Geomean</th>
                            <th class="comp">{competitor_name} Total</th>
                            <th>Winner</th>
                        </tr>
                    </thead>
                    <tbody>
                        {cat_rows}
                    </tbody>
                </table>
            </div>'''

        # === PERF TIER TABLE ===
        perf_tier_rows = ''
        for p in ed_perf_tiers:
            sf_cost_str = f"${p['sf_cost']:.2f}" if p.get('sf_cost', 0) > 0 else '—'
            sf_geomean_str = f"{p['sf_geomean']:.2f}s" if p.get('sf_geomean', 0) > 0 else '—'
            sf_size_str = f"SF {p['sf_size']}" if p.get('sf_size', '—') != '—' else '—'

            if p.get('capability_gap') and not p.get('comp_meets', True):
                comp_geomean_str = f"<span style='color:#c62828;font-weight:600;'>{p['comp_geomean']:.2f}s ❌ Can't meet SLA</span>"
                comp_cost_str = f"${p['comp_cost']:.2f}"
                savings_str = "<span style='color:#2e7d32;font-weight:700;'>SF only option</span>"
                winner_class = 'sf-winner'
            elif p.get('comp_meets', True):
                comp_geomean_str = f"{p['comp_geomean']:.2f}s"
                comp_cost_str = f"${p['comp_cost']:.2f}"
                winner_class = 'sf-winner' if p['winner'] == 'SF' else 'comp-winner'
                savings_str = f"{p['winner']} saves {p['savings']}%"
            else:
                comp_geomean_str = '—'
                comp_cost_str = '—'
                winner_class = ''
                savings_str = '—'

            perf_tier_rows += f'''
                <tr>
                    <td><strong>{p['tier']}</strong></td>
                    <td class="sf-col">{sf_size_str}</td>
                    <td class="sf-col">{sf_geomean_str}</td>
                    <td class="sf-col">{sf_cost_str}</td>
                    <td class="comp-col">{comp_geomean_str}</td>
                    <td class="comp-col">{comp_cost_str}</td>
                    <td class="{winner_class}">{savings_str}</td>
                </tr>'''

        # === PERF TIER CATEGORY DRILL-DOWNS ===
        perf_category_sections = ''
        for p in ed_perf_tiers:
            cat_rows = ''
            for c in p.get('categories', []):
                w_class = 'sf-winner' if c['winner'] == 'SF' else 'comp-winner' if c['winner'] == competitor_name else ''
                sf_gm = f"{c['sf_geomean']:.2f}s" if c['sf_geomean'] > 0 else '—'
                comp_gm = f"{c['comp_geomean']:.2f}s" if c['comp_geomean'] > 0 else '—'
                sf_tot = f"{int(c['sf_total'])}s" if c['sf_total'] > 0 else '—'
                comp_tot = f"{int(c['comp_total'])}s" if c['comp_total'] > 0 else '—'
                ratio_str = f"{c['ratio']}x" if c['ratio'] > 0 else ''
                cat_rows += f'''
                    <tr>
                        <td><strong>{c['category']}</strong></td>
                        <td style="text-align:right;">{c['count']}</td>
                        <td class="sf-col">{sf_gm}</td>
                        <td class="sf-col">{sf_tot}</td>
                        <td class="comp-col">{comp_gm}</td>
                        <td class="comp-col">{comp_tot}</td>
                        <td class="{w_class}">{c['winner']} {ratio_str}</td>
                    </tr>'''

            sf_label = f"SF {p['sf_size']} @ ${p.get('sf_hourly', 0):.0f}/hr" if p.get('sf_size', '—') != '—' else 'N/A'
            comp_label = f"{competitor_name} (serverless)" if p.get('comp_meets', True) else f"{competitor_name}: <em>Can't meet SLA</em>"
            perf_category_sections += f'''
            <h3 style="margin-top:25px;color:var(--sf-dark-blue);">{p['tier']} — {sf_label} vs {comp_label}</h3>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th style="text-align:left;">Category</th>
                            <th style="text-align:right;">Queries</th>
                            <th>SF Geomean</th>
                            <th>SF Total</th>
                            <th class="comp">{competitor_name} Geomean</th>
                            <th class="comp">{competitor_name} Total</th>
                            <th>Faster</th>
                        </tr>
                    </thead>
                    <tbody>
                        {cat_rows}
                    </tbody>
                </table>
            </div>'''

        # === DUAL-ANCHOR OKR SCORECARD ===
        target = ed_dual_okr['target']

        # Cost anchor rows
        cost_rows = ''
        for a in ed_dual_okr['cost_advantages']:
            score_pct = a['advantage'] / target if target > 0 else 0
            if score_pct >= 0.9:
                icon, row_class = '🟢', 'okr-row-green'
            elif score_pct >= 0.7:
                icon, row_class = '🟡', 'okr-row-yellow'
            else:
                icon, row_class = '🔴', 'okr-row-red'
            cost_rows += f'''
                <tr class="{row_class}">
                    <td>{a['tier']}</td>
                    <td>SF {a['sf_size']} ({a['sf_geomean']:.2f}s)</td>
                    <td>{competitor_name} ({a['comp_geomean']:.2f}s)</td>
                    <td style="text-align:right;">{int(a['sf_score'])}</td>
                    <td style="text-align:right;">{int(a['comp_score'])}</td>
                    <td style="text-align:right;font-weight:700;">{a['advantage']:.0f}%</td>
                    <td style="text-align:center;">{icon}</td>
                </tr>'''

        # Perf anchor rows
        perf_rows = ''
        for a in ed_dual_okr['perf_advantages']:
            score_pct = a['advantage'] / target if target > 0 else 0
            if score_pct >= 0.9:
                icon, row_class = '🟢', 'okr-row-green'
            elif score_pct >= 0.7:
                icon, row_class = '🟡', 'okr-row-yellow'
            else:
                icon, row_class = '🔴', 'okr-row-red'

            if a.get('capability_gap') and not a.get('comp_meets', True):
                comp_cell = f"<em>Can't meet SLA</em>"
                adv_str = f"<span style='color:#2e7d32;'>SF only option</span>"
            else:
                comp_cell = f"{competitor_name} (${a['comp_cost']:.2f})"
                adv_str = f"{a['advantage']:.0f}%"

            perf_rows += f'''
                <tr class="{row_class}">
                    <td>{a['tier']}</td>
                    <td>SF {a['sf_size']} (${a.get('sf_cost', 0):.2f})</td>
                    <td>{comp_cell}</td>
                    <td style="text-align:right;font-weight:700;">{adv_str}</td>
                    <td style="text-align:center;">{icon}</td>
                </tr>'''

        def _section_grade(meeting, total):
            if total == 0:
                return '🔴', 0
            pct = meeting / total * 100
            if pct >= 90:
                return '🟢', pct
            elif pct >= 70:
                return '🟡', pct
            else:
                return '🔴', pct

        cost_grade_icon, cost_grade_pct = _section_grade(ed_dual_okr['cost_meeting'], ed_dual_okr['cost_total'])
        perf_grade_icon, perf_grade_pct = _section_grade(ed_dual_okr['perf_meeting'], ed_dual_okr['perf_total'])

        # === WHAT-IF: COMPETITOR 20% FASTER — COST ANCHOR ===
        whatif_cost_rows = ''
        whatif_cost_meeting = 0
        for a in ed_dual_okr['cost_advantages']:
            sf_sc = a['sf_score']
            orig_comp_sc = a['comp_score']
            adj_comp_sc = orig_comp_sc * 0.64  # 0.8 cost × 0.8 geomean
            new_adv = round((1 - sf_sc / adj_comp_sc) * 100, 1) if adj_comp_sc > 0 else 0
            delta = a['advantage'] - new_adv
            okr_sc = new_adv / target if target > 0 else 0
            if okr_sc >= 0.9:
                icon, row_class = '🟢', 'okr-row-green'
                whatif_cost_meeting += 1
            elif okr_sc >= 0.7:
                icon, row_class = '🟡', 'okr-row-yellow'
            else:
                icon, row_class = '🔴', 'okr-row-red'
            whatif_cost_rows += f'''
                <tr class="{row_class}">
                    <td>{a['tier']}</td>
                    <td>SF {a['sf_size']} — {int(sf_sc)}</td>
                    <td>{competitor_name} — <s>{int(orig_comp_sc)}</s> → <strong>{int(adj_comp_sc)}</strong></td>
                    <td style="text-align:right;"><s>{a['advantage']:.0f}%</s></td>
                    <td style="text-align:right;font-weight:700;">{new_adv:.0f}%</td>
                    <td style="text-align:right;color:#c62828;">−{delta:.0f}pp</td>
                    <td style="text-align:center;">{icon}</td>
                </tr>'''

        # === WHAT-IF: COMPETITOR 20% FASTER — PERF ANCHOR ===
        whatif_perf_rows = ''
        whatif_perf_meeting = 0
        for a in ed_dual_okr['perf_advantages']:
            orig_adv = a['advantage']
            sf_cost_val = a.get('sf_cost', 0)
            comp_cost_val = a.get('comp_cost', 0)
            orig_comp_gm = a.get('comp_geomean', 0)
            adj_comp_gm = orig_comp_gm * 0.8 if orig_comp_gm > 0 else 0

            sla_str = a['tier'].replace('≤', '').replace('s SLA', '').replace('s', '').strip()
            try:
                sla_val = float(sla_str)
            except ValueError:
                sla_val = 999

            if a.get('capability_gap') and not a.get('comp_meets', True):
                # Competitor currently can't meet SLA. Can they with 20% improvement?
                if adj_comp_gm > 0 and adj_comp_gm <= sla_val:
                    # They can now meet it!
                    new_adv = round((1 - sf_cost_val / comp_cost_val) * 100, 1) if comp_cost_val > 0 else 0
                    comp_cell = f"{competitor_name} — <strong>NOW qualifies!</strong> ({adj_comp_gm:.1f}s)"
                else:
                    new_adv = 100
                    comp_cell = f"<em>still can't meet SLA</em>"
            else:
                # Both meet — recalculate with adjusted competitor score
                sf_sc = sf_cost_val * a.get('sf_geomean', 0) if sf_cost_val > 0 else 0
                orig_comp_sc = comp_cost_val * orig_comp_gm if comp_cost_val > 0 else 0
                adj_comp_sc = orig_comp_sc * 0.64
                new_adv = round((1 - sf_sc / adj_comp_sc) * 100, 1) if adj_comp_sc > 0 else 0
                comp_cell = f"{competitor_name} — <s>{int(orig_comp_sc)}</s> → <strong>{int(adj_comp_sc)}</strong>"

            delta = orig_adv - new_adv
            okr_sc = new_adv / target if target > 0 else 0
            if okr_sc >= 0.9:
                icon, row_class = '🟢', 'okr-row-green'
                whatif_perf_meeting += 1
            elif okr_sc >= 0.7:
                icon, row_class = '🟡', 'okr-row-yellow'
            else:
                icon, row_class = '🔴', 'okr-row-red'

            if delta > 0:
                delta_cell = f"<span style='color:#c62828;'>−{delta:.0f}pp</span>"
            elif delta < 0:
                delta_cell = f"<span style='color:#2e7d32;'>+{-delta:.0f}pp</span>"
            else:
                delta_cell = '—'

            sf_cell = f"SF {a['sf_size']} — ${sf_cost_val:.2f}" if sf_cost_val > 0 else f"SF {a['sf_size']}"
            whatif_perf_rows += f'''
                <tr class="{row_class}">
                    <td>{a['tier']}</td>
                    <td>{sf_cell}</td>
                    <td>{comp_cell}</td>
                    <td style="text-align:right;"><s>{orig_adv:.0f}%</s></td>
                    <td style="text-align:right;font-weight:700;">{new_adv:.0f}%</td>
                    <td style="text-align:right;">{delta_cell}</td>
                    <td style="text-align:center;">{icon}</td>
                </tr>'''

        whatif_cost_icon, whatif_cost_pct = _section_grade(whatif_cost_meeting, ed_dual_okr['cost_total'])
        whatif_perf_icon, whatif_perf_pct = _section_grade(whatif_perf_meeting, ed_dual_okr['perf_total'])

        okr_html = f'''
        <div class="okr-scorecard">
            <h2>OKR Scorecard: {target}% Price:Performance Advantage — {edition_name}</h2>

            <div class="okr-explanation">
                <strong>Target:</strong> {target}% advantage at each tier<br>
                <strong>OKR Scoring:</strong> 🟢 ≥90% of target (≥{target*0.9:.1f}%) | 🟡 70-90% ({target*0.7:.1f}-{target*0.9:.1f}%) | 🔴 &lt;70% (&lt;{target*0.7:.1f}%)<br>
                <strong>Cost Anchor:</strong> Score = Run Cost × Geomean. Advantage = (1 - SF/{competitor_name}) × 100%<br>
                <strong>Perf Anchor:</strong> At same latency SLA, who's cheaper? Capability gaps = {competitor_name} can't meet tight SLAs.
            </div>

            <details style="margin:15px 0;padding:10px;background:#f8f9fa;border-radius:6px;font-size:0.9em;">
                <summary style="cursor:pointer;font-weight:600;color:#0066cc;">ℹ️ How are tiers determined? (click to expand)</summary>
                <div style="margin-top:10px;padding:10px;background:white;border-radius:4px;">
                    <p><strong>Tier boundaries are vendor-neutral and mathematically derived:</strong></p>
                    <ul style="margin:10px 0;padding-left:20px;">
                        <li><strong>Budget Tiers:</strong> Log-spaced across SF's hourly rate range (since {competitor_name} is serverless with a fixed cost).
                            At each tier, SF's best config competes against {competitor_name}'s single price point.</li>
                        <li><strong>SLA Tiers:</strong> Log-spaced from just above the fastest config to the slowest.
                            Tight SLAs expose <em>capability gaps</em> where {competitor_name} can't compete at all.</li>
                    </ul>
                    <p style="margin-top:10px;"><strong>Why this is fair:</strong></p>
                    <ul style="margin:10px 0;padding-left:20px;">
                        <li>Tier boundaries come from <em>mathematical distribution</em>, not either vendor's specific config values</li>
                        <li>Log-scale spacing is natural for both cost and latency metrics</li>
                        <li>Each tier finds the <em>best qualifying config</em> from SF independently</li>
                        <li>{competitor_name}'s serverless model means it appears identically in every price tier — a fair reflection of its fixed-cost model</li>
                    </ul>
                </div>
            </details>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:20px;">
                <!-- Cost Anchor Detail -->
                <div>
                    <h3>Cost Anchor: At Same Budget, Who's Faster?</h3>
                    <div class="table-container">
                        <table>
                            <thead>
                                <tr>
                                    <th style="text-align:left;">Budget Tier</th>
                                    <th>SF</th>
                                    <th class="comp">{competitor_name}</th>
                                    <th>SF Score</th>
                                    <th class="comp">{competitor_name} Score</th>
                                    <th>Advantage</th>
                                    <th></th>
                                </tr>
                            </thead>
                            <tbody>
                                {cost_rows}
                            </tbody>
                        </table>
                    </div>
                    <div style="margin-top:8px;font-size:0.85em;color:#666;">
                        {cost_grade_icon} Meeting target: {ed_dual_okr['cost_meeting']}/{ed_dual_okr['cost_total']} tiers ({cost_grade_pct:.0f}%)
                    </div>
                </div>

                <!-- Perf Anchor Detail -->
                <div>
                    <h3>Perf Anchor: At Same SLA, Who's Cheaper?</h3>
                    <div class="table-container">
                        <table>
                            <thead>
                                <tr>
                                    <th style="text-align:left;">Latency SLA</th>
                                    <th>SF (cost)</th>
                                    <th class="comp">{competitor_name}</th>
                                    <th>SF Savings</th>
                                    <th></th>
                                </tr>
                            </thead>
                            <tbody>
                                {perf_rows}
                            </tbody>
                        </table>
                    </div>
                    <div style="margin-top:8px;font-size:0.85em;color:#666;">
                        {perf_grade_icon} Meeting target: {ed_dual_okr['perf_meeting']}/{ed_dual_okr['perf_total']} tiers ({perf_grade_pct:.0f}%)
                    </div>
                </div>
            </div>

            <!-- What If: Competitor 20% Faster -->
            <div style="margin-top:30px;padding:20px;background:#fff3e0;border-radius:8px;border:1px solid #ffb74d;">
                <h3 style="margin-top:0;color:#e65100;">🔮 What If: {competitor_name} Were 20% Faster?</h3>
                <p style="font-size:0.9em;color:#666;margin-bottom:15px;">
                    Sensitivity analysis: If {competitor_name} improved all query latencies by 20%, how would our OKR standing change?
                    Score drops to 0.64× (0.8 cost × 0.8 geomean = 36% improvement).
                </p>

                <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">
                    <!-- Cost Anchor What If -->
                    <div>
                        <h4 style="margin-top:0;">Cost Anchor Impact</h4>
                        <div class="table-container">
                            <table>
                                <thead>
                                    <tr>
                                        <th style="text-align:left;">Budget Tier</th>
                                        <th>SF Score</th>
                                        <th class="comp">{competitor_name} Score</th>
                                        <th>Was</th>
                                        <th>Now</th>
                                        <th>Δ</th>
                                        <th></th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {whatif_cost_rows}
                                </tbody>
                            </table>
                        </div>
                        <div style="margin-top:8px;font-size:0.85em;color:#666;">
                            {whatif_cost_icon} Green tiers after: {whatif_cost_meeting}/{ed_dual_okr['cost_total']} ({whatif_cost_pct:.0f}%)
                        </div>
                    </div>

                    <!-- Perf Anchor What If -->
                    <div>
                        <h4 style="margin-top:0;">Perf Anchor Impact</h4>
                        <div class="table-container">
                            <table>
                                <thead>
                                    <tr>
                                        <th style="text-align:left;">Latency SLA</th>
                                        <th>SF</th>
                                        <th class="comp">{competitor_name}</th>
                                        <th>Was</th>
                                        <th>Now</th>
                                        <th>Δ</th>
                                        <th></th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {whatif_perf_rows}
                                </tbody>
                            </table>
                        </div>
                        <div style="margin-top:8px;font-size:0.85em;color:#666;">
                            {whatif_perf_icon} Green tiers after: {whatif_perf_meeting}/{ed_dual_okr['perf_total']} ({whatif_perf_pct:.0f}%)
                        </div>
                    </div>
                </div>
            </div>
        </div>'''

        return f'''
    <div id="{tab_id}" class="tab-content">
        <h2>{edition_name} Analysis — ${credit_rate:.2f}/credit</h2>

        {budget_html}
        {sla_html}

        <div class="insight-box {"winner" if ed_okr["advantage"] > 0 else ""}">
            <strong>Key Finding:</strong> SF {ed_best_size} ({edition_name}) is the sweet spot — delivers
            <strong>{round(ed_comp_time/ed_stats[ed_best_size]["total"], 1)}x faster</strong> runtime than {competitor_name}.
            The Cost × Geomean score ({int(ed_best_score)}) beats {competitor_name} ({int(ed_comp_score)}) by {ed_pp_ratio}x.
        </div>

        {okr_html}

        <h2 style="margin-top:40px;">Price Tier Comparison: At Each Budget, Who's Faster?</h2>
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th style="text-align:left;">Price Tier</th>
                        <th>SF Config</th>
                        <th>SF Total</th>
                        <th>SF Geomean</th>
                        <th class="comp">{competitor_name} Config</th>
                        <th class="comp">{competitor_name} Total</th>
                        <th class="comp">{competitor_name} Geomean</th>
                        <th>Winner</th>
                    </tr>
                </thead>
                <tbody>
                    {price_tier_rows}
                </tbody>
            </table>
        </div>

        <h2>Price Tier Breakdown by Query Category</h2>
        {price_category_sections}

        <h2 style="margin-top:40px;">Performance Tier Comparison: To Hit This SLA, Who's Cheaper?</h2>
        <div class="insight-box">
            <strong>The flip side:</strong> Instead of asking "At this budget, who's faster?",
            we now ask "To achieve this latency SLA, who's cheaper?"
            Capability gaps highlight where {competitor_name}'s serverless model <em>can't</em> meet tight SLAs.
        </div>

        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th style="text-align:left;">Performance SLA</th>
                        <th>SF Size</th>
                        <th>SF Latency</th>
                        <th>SF Cost</th>
                        <th class="comp">{competitor_name} Latency</th>
                        <th class="comp">{competitor_name} Cost</th>
                        <th>Cost Winner</th>
                    </tr>
                </thead>
                <tbody>
                    {perf_tier_rows}
                </tbody>
            </table>
        </div>

        <h2 style="margin-top:40px;">Performance Tier Breakdown by Query Category</h2>
        {perf_category_sections}

        <h2 style="margin-top:40px;">Size Comparison — {edition_name}</h2>
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th style="text-align:left;">Config</th>
                        <th style="text-align:right;">Hourly Rate</th>
                        <th style="text-align:right;">Total (s)</th>
                        <th style="text-align:right;">Geomean (s)</th>
                        <th style="text-align:right;">Run Cost</th>
                        <th style="text-align:right;">Cost × Geomean</th>
                        <th style="text-align:right;">vs {competitor_name}</th>
                    </tr>
                </thead>
                <tbody>
                    {size_rows}
                    <tr style="background:#fff8f0;">
                        <td><strong>{competitor_name}</strong></td>
                        <td style="text-align:right;color:#999;">serverless</td>
                        <td style="text-align:right;">{int(ed_comp_time):,}</td>
                        <td style="text-align:right;">{ed_comp_latency:.2f}</td>
                        <td style="text-align:right;">${ed_stats[competitor_name]["cost"]:.2f}</td>
                        <td style="text-align:right;">{int(ed_comp_score)}</td>
                        <td style="text-align:right;color:#999;">baseline</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <h2 style="margin-top:40px;">Size Breakdown by Query Category</h2>
        <div class="insight-box" style="background:#e8f4fc;border-color:var(--sf-blue);">
            <strong>📊 Drill-down:</strong> For each SF size, how does performance compare across 
            TPC-DS workload types? Categories: <strong>Reporting</strong> (22q), <strong>Ad-hoc</strong> (18q), 
            <strong>OLAP</strong> (41q), <strong>Data Mining</strong> (22q).
        </div>
        {render_size_category_sections_html(
            sf_data=sf_data,
            comp_times=competitor_data['times'],
            sf_sizes=sf_sizes,
            comp_label=competitor_name,
            comp_hourly=None,
            credit_rate=credit_rate,
            sf_credits_per_hour=SF_CREDITS_PER_HOUR_GEN2,
            sf_col_class='sf-col',
            comp_col_class='comp-col',
            sf_winner_class='sf-winner',
            comp_winner_class='comp-winner'
        )}
    </div>'''

    # Build both edition tabs
    ee_tab = build_edition_tab('ee-analysis', 'Enterprise Edition', SF_CREDIT_RATE_EE,
                                stats_ee, best_size_ee, best_score_ee, comp_score_ee,
                                okr_ee, budget_match_ee, sla_match_ee,
                                price_tiers_ee, perf_tiers_ee, dual_okr_ee)
    se_tab = build_edition_tab('se-analysis', 'Standard Edition', SF_CREDIT_RATE_SE,
                                stats_se, best_size_se, best_score_se, comp_score_se,
                                okr_se, budget_match_se, sla_match_se,
                                price_tiers_se, perf_tiers_se, dual_okr_se)

    # --- Pricing breakdown table ---
    pricing_table = '<table style="font-size:0.95em; border-collapse:collapse; width:100%;">'
    pricing_table += '<tr><th style="padding:4px 8px; text-align:left;">Size</th><th style="padding:4px 8px;">Cr/hr</th><th style="padding:4px 8px;">SE @$2</th><th style="padding:4px 8px;">EE @$3</th></tr>'
    for s in sf_sizes:
        cr = SF_CREDITS_PER_HOUR_GEN2[s]
        se_cost = cr * SF_CREDIT_RATE_SE
        ee_cost = cr * SF_CREDIT_RATE_EE
        pricing_table += f'<tr><td style="padding:2px 8px;">{s}</td><td style="padding:2px 8px; text-align:center;">{cr}</td><td style="padding:2px 8px; text-align:center;"><strong>${se_cost:.2f}</strong></td><td style="padding:2px 8px; text-align:center;">${ee_cost:.2f}</td></tr>'
    pricing_table += '</table>'

    # =========================================================================
    # FULL HTML
    # =========================================================================
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TPC-DS 10TB: Snowflake vs {competitor_name}{publish_title_suffix}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <style>
        :root {{
            --sf-blue: #29B5E8;
            --sf-dark-blue: #11567F;
            --sf-navy: #0D2C54;
            --sf-light-bg: #F4FAFF;
            --sf-gray: #6E7681;
            --comp-orange: #FF9900;
            --comp-light: #FFF8F0;
            --green: #32963C;
        }}

        * {{ box-sizing: border-box; }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1400px;
            margin: 0 auto;
            padding: 30px 20px;
            background: #fff;
            color: #333;
            line-height: 1.5;
        }}

        h1 {{
            color: var(--sf-dark-blue);
            border-bottom: 3px solid var(--sf-blue);
            padding-bottom: 10px;
            margin-bottom: 5px;
        }}

        .subtitle {{ color: var(--sf-gray); margin-bottom: 20px; font-size: 1.1em; }}

        h2 {{
            color: var(--sf-dark-blue);
            margin-top: 35px;
            border-left: 4px solid var(--sf-blue);
            padding-left: 12px;
            font-size: 1.3em;
        }}

        h3 {{
            color: var(--sf-dark-blue);
            margin-top: 25px;
        }}

        .tab-nav {{
            display: flex;
            gap: 0;
            margin: 20px 0;
            border-bottom: 2px solid var(--sf-blue);
            flex-wrap: wrap;
        }}

        .tab-btn {{
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
        }}

        .tab-btn:hover {{ background: #d8eef8; }}
        .tab-btn.active {{ background: var(--sf-blue); color: white; }}

        .tab-content {{ display: none; }}
        .tab-content.active {{ display: block; }}

        .summary-row {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            margin: 20px 0;
        }}

        .card {{
            background: var(--sf-light-bg);
            padding: 18px;
            border-radius: 8px;
            text-align: center;
        }}

        .card.sf {{ background: var(--sf-blue); color: white; }}
        .card.comp {{ background: var(--comp-orange); color: white; }}
        .card.winner {{ background: var(--green); color: white; }}

        .card .label {{ font-size: 0.85em; opacity: 0.9; }}
        .card .value {{ font-size: 1.6em; font-weight: bold; margin: 4px 0; }}
        .card .detail {{ font-size: 0.75em; opacity: 0.8; }}

        .chart-container {{
            position: relative;
            margin: 20px 0;
            padding: 15px;
            background: #fafcff;
            border-radius: 8px;
            border: 1px solid #e8f4fc;
        }}

        .table-container {{
            overflow-x: auto;
            margin: 20px 0;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.82em;
        }}

        th {{
            background: linear-gradient(135deg, var(--sf-dark-blue) 0%, var(--sf-navy) 100%);
            color: white;
            padding: 10px 8px;
            text-align: right;
            font-weight: 600;
            position: sticky;
            top: 0;
            z-index: 1;
        }}

        th:first-child {{ text-align: left; }}
        th.comp {{ background: linear-gradient(135deg, #FF9900 0%, #CC7A00 100%); }}

        td {{
            padding: 6px 8px;
            border-bottom: 1px solid #E8F4FC;
            text-align: right;
            font-variant-numeric: tabular-nums;
        }}

        td:first-child {{
            text-align: left;
            font-weight: 500;
            color: var(--sf-dark-blue);
        }}

        tr:nth-child(even) {{ background: #FAFCFF; }}
        tr:hover {{ background: #E8F4FC; }}

        .section-row td {{
            background: var(--sf-light-bg) !important;
            font-weight: 700;
            color: var(--sf-dark-blue);
            border-top: 2px solid var(--sf-blue);
            padding: 12px 8px;
        }}

        .winner-cell {{
            background: #E8F5E9 !important;
            color: var(--green);
            font-weight: 700;
        }}

        /* Category breakdown table styling */
        .sf-col {{ color: var(--sf-dark-blue); }}
        .comp-col {{ color: #CC7A00; }}
        .sf-winner {{ color: var(--green); font-weight: 700; }}
        .comp-winner {{ color: #CC7A00; font-weight: 700; }}

        .insight-box {{
            background: #E8F4FC;
            border-left: 4px solid var(--sf-blue);
            padding: 15px 20px;
            margin: 20px 0;
            border-radius: 0 8px 8px 0;
        }}

        .insight-box.winner {{
            background: #e8f5e9;
            border-left-color: var(--green);
        }}

        .insight-box.warning {{
            background: #fff8e1;
            border-left-color: #f9a825;
        }}

        .footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #eee;
            font-size: 0.8em;
            color: var(--sf-gray);
        }}

        .query-name {{
            cursor: help;
            border-bottom: 1px dotted var(--sf-gray);
            position: relative;
        }}

        .query-name:hover::after {{
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
        }}

        .class-tag {{
            display: inline-block;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 0.75em;
            font-weight: 600;
            text-transform: uppercase;
        }}

        .class-reporting {{ background: #e3f2fd; color: #1565c0; }}
        .class-adhoc {{ background: #fff3e0; color: #e65100; }}
        .class-olap {{ background: #f3e5f5; color: #7b1fa2; }}
        .class-datamining {{ background: #e8f5e9; color: #2e7d32; }}

        .search-box {{ margin-bottom: 15px; }}
        .search-box input {{
            padding: 10px 15px;
            width: 300px;
            border: 2px solid var(--sf-blue);
            border-radius: 6px;
            font-size: 0.95em;
        }}
        .search-box input:focus {{
            outline: none;
            box-shadow: 0 0 0 3px rgba(41, 181, 232, 0.2);
        }}

        .model-note {{
            background: #f5f5f5;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 15px 20px;
            margin: 20px 0;
            font-size: 0.9em;
        }}

        .model-note strong {{ color: var(--sf-dark-blue); }}

        .toggle-btn {{
            padding: 8px 16px;
            border: 2px solid #29B5E8;
            background: white;
            color: #29B5E8;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 500;
            transition: all 0.2s;
        }}
        .toggle-btn:hover {{ background: #e8f7fc; }}
        .toggle-btn.active {{ background: #29B5E8; color: white; }}

        .okr-explanation {{
            background: #f5f5f5;
            padding: 15px;
            border-radius: 8px;
            font-size: 0.9em;
            margin-bottom: 20px;
        }}

        .okr-row-green td {{ background: #e8f5e9 !important; }}
        .okr-row-yellow td {{ background: #fff8e1 !important; }}
        .okr-row-red td {{ background: #ffebee !important; }}

        .okr-scorecard {{
            background: #fafafa;
            border: 1px solid #e0e0e0;
            border-radius: 10px;
            padding: 25px;
            margin: 30px 0;
        }}
        .okr-scorecard h2 {{ margin-top: 0; }}

        th.comp, th.comp {{ color: var(--comp-orange); }}
    </style>
</head>
<body>
    <h1>TPC-DS 10TB: Snowflake vs {competitor_name} {publish_badge}</h1>
    <p class="subtitle">Price:Performance Comparison — Snowflake Gen2 Iceberg vs {competitor_name} Serverless</p>

    <div class="model-note">
        <strong>⚠️ Different pricing models:</strong>
        Snowflake charges per compute-hour (warehouse size × time).
        {competitor_name} charges per data scanned ($5/TB).
        {competitor_name} has a single "size" — it's serverless with no knobs to tune.
        SF has {len(sf_sizes)} warehouse sizes ({', '.join(sf_sizes)}).
        This report finds where {competitor_name} sits on SF's price:performance curve.
    </div>

    <div class="tab-nav">
        <button class="tab-btn active" onclick="showTab('overview', this)">Overview</button>
        <button class="tab-btn" onclick="showTab('ee-analysis', this)">EE Analysis ({ee_rate_range})</button>
        <button class="tab-btn" onclick="showTab('se-analysis', this)">SE Analysis ({se_rate_range})</button>
        <button class="tab-btn" onclick="showTab('graphs', this)">Graphs</button>
        <button class="tab-btn" onclick="showTab('h2h', this)">Head-to-Head</button>
        <button class="tab-btn" onclick="showTab('scaling', this)">SF Scaling</button>
        <button class="tab-btn" onclick="showTab('reference', this)">Query Reference</button>
    </div>

    <!-- ================================================================== -->
    <!-- TAB 1: OVERVIEW                                                     -->
    <!-- ================================================================== -->
    <div id="overview" class="tab-content active">
        <h2>Executive Summary</h2>

        <div class="summary-row">
            <div class="card sf">
                <div class="label">Fastest SF</div>
                <div class="value">{fastest_size}</div>
                <div class="detail">{int(fastest_time)}s total ({speed_ratio}x faster)</div>
            </div>
            <div class="card comp">
                <div class="label">{competitor_name}</div>
                <div class="value">${stats[competitor_name]["cost"]:.2f}</div>
                <div class="detail">{int(comp_time)}s total, {comp_latency:.2f}s geomean</div>
            </div>
            <div class="card winner">
                <div class="label">Best Price × Perf</div>
                <div class="value">SF {best_size}</div>
                <div class="detail">Score: {int(best_score)} ({price_perf_ratio}x better)</div>
            </div>
            <div class="card">
                <div class="label">Best Latency</div>
                <div class="value">SF {best_latency_size}</div>
                <div class="detail">{best_latency:.2f}s geomean ({latency_ratio}x faster)</div>
            </div>
        </div>

        <div class="insight-box winner">
            <strong>Key Finding:</strong> SF {best_size} SE is the sweet spot — delivers
            <strong>{round(comp_time/stats[best_size]["total"], 1)}x faster</strong> runtime than {competitor_name}.
            The Cost × Geomean score ({int(best_score)}) beats {competitor_name} ({int(comp_score)}) by {price_perf_ratio}x.
        </div>

        <h2>Included Runs</h2>
        <p style="color:var(--sf-gray);">All benchmark data used in this report. Verify run keys, dates, and query counts before sharing.</p>
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th style="text-align:left;">Platform</th>
                        <th style="text-align:left;">Config</th>
                        <th style="text-align:left;">Run Key</th>
                        <th style="text-align:left;">Run Date</th>
                        <th style="text-align:left;">WH Type</th>
                        <th style="text-align:left;">Data Format</th>
                        <th style="text-align:center;">Warm Queries</th>
                    </tr>
                </thead>
                <tbody>
                    {run_metadata_rows}
                </tbody>
            </table>
        </div>

        <h2>Understanding the Comparison</h2>

        <div class="insight-box" style="background: #fff3cd; border-color: #ffc107;">
            <strong>⚠️ Pricing Assumptions — verify for your contract:</strong><br>
            <table style="margin-top:10px; font-size:0.9em; width:100%;">
                <tr>
                    <td style="padding-right:20px; vertical-align:top; width:50%;">
                        <strong>Snowflake Gen2 (AWS)</strong><br>
                        <em>Gen2 = 1.35× Gen1 credits/hr</em><br><br>
                        {pricing_table}
                    </td>
                    <td style="vertical-align:top; width:50%;">
                        <strong>{competitor_name} Serverless</strong><br>
                        <em>$5/TB scanned — no size options</em><br><br>
                        <table style="font-size:0.95em; border-collapse:collapse;">
                            <tr style="background:#fff3e0;">
                                <th style="padding:4px 8px; text-align:left;">Model</th>
                                <th style="padding:4px 8px;">Pricing</th>
                            </tr>
                            <tr><td style="padding:2px 8px;">Serverless</td><td style="padding:2px 8px; text-align:center;"><strong>$5.00/TB scanned</strong></td></tr>
                            <tr><td style="padding:2px 8px;">This run</td><td style="padding:2px 8px; text-align:center;"><strong>${competitor_data["cost"]:.2f}</strong></td></tr>
                        </table>
                    </td>
                </tr>
            </table>
            <p style="margin-top:15px; margin-bottom:0; font-size:0.85em; color:#856404;">
                <strong>Note:</strong> This report generates separate tabs for Standard Edition ($2/credit)
                and Enterprise Edition ($3/credit). EE costs are 50% higher, narrowing the price advantage.
                Contracted rates vary — adjust accordingly.
            </p>
        </div>

        <div class="insight-box">
            <strong>Cost × Geomean:</strong> This metric balances cost and latency. Lower is better.
            You can't game it by being cheap-but-slow or fast-but-expensive.
        </div>
    </div>

    <!-- ================================================================== -->
    <!-- TAB 2: EE Analysis                                                  -->
    <!-- ================================================================== -->
    {ee_tab}

    <!-- ================================================================== -->
    <!-- TAB 3: SE Analysis                                                  -->
    <!-- ================================================================== -->
    {se_tab}

    <!-- ================================================================== -->
    <!-- TAB 4: GRAPHS                                                       -->
    <!-- ================================================================== -->
    <div id="graphs" class="tab-content">
        <h2>Performance & Cost Visualization</h2>
        <p class="subtitle">Comparing Snowflake (SE & EE pricing) vs {competitor_name} across warehouse sizes</p>

        <div style="display:flex;gap:30px;margin:20px 0;padding:15px;background:#f0f4f8;border-radius:8px;align-items:center;flex-wrap:wrap;">
            <div style="display:flex;align-items:center;gap:10px;">
                <span style="font-weight:600;color:#333;">Scale:</span>
                <button id="scaleLinear" class="toggle-btn active" onclick="setScale('linear')">Linear</button>
                <button id="scaleLog" class="toggle-btn" onclick="setScale('log')">Log Scale</button>
            </div>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:30px;margin-top:20px;">
            <div style="background:#f8f9fa;padding:20px;border-radius:8px;">
                <h3 style="margin-top:0;">Run Cost by Warehouse Size</h3>
                <canvas id="costChart"></canvas>
            </div>
            <div style="background:#f8f9fa;padding:20px;border-radius:8px;">
                <h3 style="margin-top:0;" id="geomeanTitle">Geomean Latency by Warehouse Size</h3>
                <canvas id="geomeanChart"></canvas>
            </div>
            <div style="background:#f8f9fa;padding:20px;border-radius:8px;">
                <h3 style="margin-top:0;" id="totalTitle">Total Runtime by Warehouse Size</h3>
                <canvas id="totalTimeChart"></canvas>
            </div>
            <div style="background:#f8f9fa;padding:20px;border-radius:8px;">
                <h3 style="margin-top:0;" id="pricePerTitle">Price:Performance Score by Size</h3>
                <p style="font-size:0.85em;color:#666;margin-top:-10px;">Lower is better (Cost × Geomean)</p>
                <canvas id="pricePerChart"></canvas>
            </div>
        </div>

        <h2 style="margin-top:40px;">Cost vs Performance Scatter Plots</h2>
        <p class="subtitle">Each point is a warehouse size. {competitor_name} shown as a triangle. Lower-left is better.</p>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:30px;margin-top:20px;">
            <div style="background:#f8f9fa;padding:20px;border-radius:8px;">
                <h3 style="margin-top:0;">Run Cost vs Geomean Latency</h3>
                <canvas id="scatterGeomean"></canvas>
            </div>
            <div style="background:#f8f9fa;padding:20px;border-radius:8px;">
                <h3 style="margin-top:0;">Run Cost vs Total Runtime</h3>
                <canvas id="scatterTotal"></canvas>
            </div>
        </div>
    </div>

    <!-- ================================================================== -->
    <!-- TAB 5: HEAD-TO-HEAD (Dynamic)                                       -->
    <!-- ================================================================== -->
    <div id="h2h" class="tab-content">
        <div style="display:flex;align-items:center;gap:15px;margin-bottom:20px;flex-wrap:wrap;">
            <h2 style="margin:0;">Query-by-Query Comparison:</h2>
            <div style="display:flex;align-items:center;gap:8px;">
                <span style="color:#29b5e8;font-weight:600;">SF</span>
                <select id="sfSizeSelector" onchange="renderH2HComparison()" style="font-size:1.1em;padding:6px 12px;border-radius:6px;border:2px solid #29b5e8;font-weight:600;cursor:pointer;">
                    {''.join(f'<option value="{s}" {"selected" if s == best_size else ""}>{s}</option>' for s in sf_sizes)}
                </select>
            </div>
            <span style="font-size:1.2em;font-weight:bold;">vs</span>
            <span style="color:#FF9900;font-weight:700;font-size:1.1em;">{competitor_name}</span>
        </div>

        <div id="h2hComparisonContent">
            <p>Loading comparison...</p>
        </div>
    </div>

    <!-- ================================================================== -->
    <!-- TAB 6: SF SCALING                                                   -->
    <!-- ================================================================== -->
    <div id="scaling" class="tab-content">
        <h2>Snowflake Scaling Efficiency</h2>
        <p style="color:var(--sf-gray);">
            How well do queries scale as Snowflake warehouse size increases from {ordered_sizes[0]} to {ordered_sizes[-1]}?
            Uses log-log regression: T = c × N<sup>β</sup>. Scaling Efficiency = |β| × 100%.
        </p>

        <div class="summary-row">
            <div class="card sf">
                <div class="label">Avg Efficiency</div>
                <div class="value">{avg_efficiency:.0f}%</div>
                <div class="detail">across {len(efficiencies)} queries</div>
            </div>
            <div class="card" style="background:#e8f5e9;">
                <div class="label">🟢 Good (≥70%)</div>
                <div class="value">{good_scaling}</div>
                <div class="detail">scale well</div>
            </div>
            <div class="card" style="background:#fff8e1;">
                <div class="label">🟡 Moderate (40-70%)</div>
                <div class="value">{moderate_scaling}</div>
                <div class="detail">some benefit</div>
            </div>
            <div class="card" style="background:#ffebee;">
                <div class="label">🔴 Poor (&lt;40%)</div>
                <div class="value">{poor_scaling}</div>
                <div class="detail">limited scaling</div>
            </div>
        </div>

        <div class="insight-box">
            <strong>What this means:</strong>
            A query with 100% efficiency gets 2× speedup from 2× compute.
            At 50%, 2× compute only gives 1.4× speedup.
            Queries with poor scaling may be bottlenecked on I/O, network, or serial operations.
        </div>

        <h3>Query Scaling Matrix</h3>
        <p style="color:var(--sf-gray);">Sorted by scaling efficiency (best first). Sparkline shows time across sizes.</p>
        <div class="table-container" style="max-height:600px;overflow-y:auto;">
            <table>
                <thead style="position:sticky;top:0;background:white;">
                    <tr>
                        <th style="text-align:left;">Query</th>
                        <th style="text-align:left;">Category</th>
                        {scaling_header}
                        <th style="text-align:center;">Trend</th>
                        <th style="text-align:right;">Efficiency</th>
                    </tr>
                </thead>
                <tbody>
                    {scaling_rows}
                </tbody>
            </table>
        </div>
    </div>

    <!-- ================================================================== -->
    <!-- TAB 7: QUERY REFERENCE                                              -->
    <!-- ================================================================== -->
    <div id="reference" class="tab-content">
        <h2>TPC-DS Query Classifications</h2>

        <div class="insight-box">
            <strong>About TPC-DS:</strong> 103 queries (99 base + 4 variants: 14a/b, 23a/b, 24a/b, 39a/b) designed to model real-world decision support workloads across retail, inventory, and customer analytics.
        </div>

        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th style="text-align:left;">Category</th>
                        <th style="text-align:left;">Description</th>
                        <th style="text-align:right;">Count</th>
                        <th style="text-align:left;">Queries</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td><span style="background:#e3f2fd;padding:2px 8px;border-radius:3px;font-weight:600;">Reporting</span></td>
                        <td>Well-known, optimizable queries</td>
                        <td style="text-align:right;">{len(QUERY_CLASSIFICATIONS['Reporting'])}</td>
                        <td style="font-size:0.8em;color:#666;">{', '.join(QUERY_CLASSIFICATIONS['Reporting'])}</td>
                    </tr>
                    <tr>
                        <td><span style="background:#fff3e0;padding:2px 8px;border-radius:3px;font-weight:600;">Ad-hoc</span></td>
                        <td>Unknown queries in advance</td>
                        <td style="text-align:right;">{len(QUERY_CLASSIFICATIONS['Ad-hoc'])}</td>
                        <td style="font-size:0.8em;color:#666;">{', '.join(QUERY_CLASSIFICATIONS['Ad-hoc'])}</td>
                    </tr>
                    <tr>
                        <td><span style="background:#f3e5f5;padding:2px 8px;border-radius:3px;font-weight:600;">OLAP</span></td>
                        <td>Interactive drill-down analysis</td>
                        <td style="text-align:right;">{len(QUERY_CLASSIFICATIONS['OLAP'])}</td>
                        <td style="font-size:0.8em;color:#666;">{', '.join(QUERY_CLASSIFICATIONS['OLAP'])}</td>
                    </tr>
                    <tr>
                        <td><span style="background:#e8f5e9;padding:2px 8px;border-radius:3px;font-weight:600;">Data Mining</span></td>
                        <td>Extraction & pattern queries</td>
                        <td style="text-align:right;">{len(QUERY_CLASSIFICATIONS['Data Mining'])}</td>
                        <td style="font-size:0.8em;color:#666;">{', '.join(QUERY_CLASSIFICATIONS['Data Mining'])}</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <h2>Metrics Explained</h2>
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th style="text-align:left;">Metric</th>
                        <th style="text-align:left;">What It Measures</th>
                        <th style="text-align:left;">Why It Matters</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td><strong>Total (s)</strong></td>
                        <td>Sum of all 103 query times</td>
                        <td>Overall benchmark duration</td>
                    </tr>
                    <tr>
                        <td><strong>Geomean (s)</strong></td>
                        <td>Geometric mean of query times</td>
                        <td>Robust average, less skewed by outliers</td>
                    </tr>
                    <tr>
                        <td><strong>Run Cost ($)</strong></td>
                        <td>Cost to execute full benchmark</td>
                        <td>Direct dollar comparison</td>
                    </tr>
                    <tr>
                        <td><strong>Cost × Geomean</strong></td>
                        <td>Price:performance score</td>
                        <td>Lower = better value (balances cost & speed)</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <h2>Detailed Query Reference</h2>

        <div class="search-box">
            <input type="text" id="querySearch" placeholder="Search queries..." onkeyup="filterQueries()">
        </div>

        <div class="table-container">
            <table id="queryTable">
                <thead>
                    <tr>
                        <th>Query</th>
                        <th style="text-align:left;">Business Question</th>
                        <th>Classification</th>
                    </tr>
                </thead>
                <tbody>
                    {query_ref_rows}
                </tbody>
            </table>
        </div>
    </div>

    <!-- ================================================================== -->
    <!-- FOOTER                                                              -->
    <!-- ================================================================== -->
    <div class="footer">
        <p><strong>Generated:</strong> {datetime.now().strftime("%Y-%m-%d %H:%M")}{f' | <strong>Published:</strong> {publish_date}' if publish_date else ''} | <strong>Data:</strong> TPC-DS 10TB</p>
        <p><strong>SF Pricing:</strong> SE @$2/credit, EE @$3/credit (Gen2) | <strong>SF Sizes:</strong> {', '.join(sf_sizes)}</p>
        <p><strong>{competitor_name} Cost:</strong> ${competitor_data["cost"]:.2f} ($5/TB × data scanned)</p>
        <p><strong>Run Keys:</strong> SF: {', '.join(str(sf_data[s]["run_key"]) for s in sf_sizes)} | {competitor_name}: {competitor_data["run_key"]}</p>
        <p><strong>Generator:</strong> <code>scripts/generate-tpcds-price-perf.py</code></p>
    </div>

    <!-- ================================================================== -->
    <!-- JAVASCRIPT                                                          -->
    <!-- ================================================================== -->
    <script>
        // ---- TAB NAVIGATION ----
        function showTab(tabId, btn) {{
            document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            btn.classList.add('active');
        }}

        // ---- QUERY SEARCH ----
        function filterQueries() {{
            const input = document.getElementById('querySearch').value.toLowerCase();
            const rows = document.querySelectorAll('#queryTable tbody tr');
            rows.forEach(row => {{
                const text = row.textContent.toLowerCase();
                row.style.display = text.includes(input) ? '' : 'none';
            }});
        }}

        // ================================================================
        // GRAPHS TAB - Charts
        // ================================================================
        const sfSeData = {sf_se_chart_json};
        const sfEeData = {sf_ee_chart_json};
        const compData = {comp_chart_json};
        const allSizes = {json.dumps(sf_sizes)};

        let currentScale = 'linear';
        let charts = {{}};

        const colors = {{
            sfSe: '#29B5E8',
            sfEe: '#11567F',
            comp: '#FF9900',
            target: '#32963C'
        }};

        function setScale(scale) {{
            currentScale = scale;
            document.getElementById('scaleLinear').classList.toggle('active', scale === 'linear');
            document.getElementById('scaleLog').classList.toggle('active', scale === 'log');
            buildCharts();
        }}

        function buildCharts() {{
            Object.values(charts).forEach(c => c && c.destroy());
            const isLog = currentScale === 'log';

            // 1. Run Cost Chart
            charts.cost = new Chart(document.getElementById('costChart'), {{
                type: 'line',
                data: {{
                    labels: allSizes,
                    datasets: [{{
                        label: 'Snowflake SE',
                        data: allSizes.map(s => {{ const d = sfSeData.find(x => x.size === s); return d ? d.cost : null; }}),
                        borderColor: colors.sfSe, backgroundColor: colors.sfSe, tension: 0.1
                    }}, {{
                        label: 'Snowflake EE',
                        data: allSizes.map(s => {{ const d = sfEeData.find(x => x.size === s); return d ? d.cost : null; }}),
                        borderColor: colors.sfEe, backgroundColor: colors.sfEe, borderDash: [5, 5], tension: 0.1
                    }}, {{
                        label: '{competitor_name}',
                        data: allSizes.map(() => compData.cost),
                        borderColor: colors.comp, backgroundColor: colors.comp, borderDash: [10, 5], pointRadius: 0
                    }}]
                }},
                options: {{
                    responsive: true,
                    plugins: {{ legend: {{ position: 'bottom' }} }},
                    scales: {{ y: {{ type: isLog ? 'logarithmic' : 'linear', beginAtZero: !isLog, title: {{ display: true, text: 'Run Cost ($)' }} }} }}
                }}
            }});

            // 2. Geomean Chart
            charts.geomean = new Chart(document.getElementById('geomeanChart'), {{
                type: 'line',
                data: {{
                    labels: allSizes,
                    datasets: [{{
                        label: 'Snowflake',
                        data: allSizes.map(s => {{ const d = sfSeData.find(x => x.size === s); return d ? d.geomean : null; }}),
                        borderColor: colors.sfSe, backgroundColor: colors.sfSe, tension: 0.1
                    }}, {{
                        label: '{competitor_name}',
                        data: allSizes.map(() => compData.geomean),
                        borderColor: colors.comp, backgroundColor: colors.comp, borderDash: [10, 5], pointRadius: 0
                    }}]
                }},
                options: {{
                    responsive: true,
                    plugins: {{ legend: {{ position: 'bottom' }} }},
                    scales: {{ y: {{ type: isLog ? 'logarithmic' : 'linear', reverse: !isLog, title: {{ display: true, text: isLog ? 'Geomean (s) — log' : 'Geomean (s) — lower is better ↓' }} }} }}
                }}
            }});

            // 3. Total Runtime Chart
            charts.total = new Chart(document.getElementById('totalTimeChart'), {{
                type: 'line',
                data: {{
                    labels: allSizes,
                    datasets: [{{
                        label: 'Snowflake',
                        data: allSizes.map(s => {{ const d = sfSeData.find(x => x.size === s); return d ? d.total : null; }}),
                        borderColor: colors.sfSe, backgroundColor: colors.sfSe, tension: 0.1
                    }}, {{
                        label: '{competitor_name}',
                        data: allSizes.map(() => compData.total),
                        borderColor: colors.comp, backgroundColor: colors.comp, borderDash: [10, 5], pointRadius: 0
                    }}]
                }},
                options: {{
                    responsive: true,
                    plugins: {{ legend: {{ position: 'bottom' }} }},
                    scales: {{ y: {{ type: isLog ? 'logarithmic' : 'linear', reverse: !isLog, title: {{ display: true, text: isLog ? 'Total Runtime (s) — log' : 'Total Runtime (s) — lower is better ↓' }} }} }}
                }}
            }});

            // 4. Price:Perf Chart
            charts.pricePer = new Chart(document.getElementById('pricePerChart'), {{
                type: 'line',
                data: {{
                    labels: allSizes,
                    datasets: [{{
                        label: 'Snowflake SE',
                        data: allSizes.map(s => {{ const d = sfSeData.find(x => x.size === s); return d ? d.price_perf : null; }}),
                        borderColor: colors.sfSe, backgroundColor: colors.sfSe, tension: 0.1
                    }}, {{
                        label: 'Snowflake EE',
                        data: allSizes.map(s => {{ const d = sfEeData.find(x => x.size === s); return d ? d.price_perf : null; }}),
                        borderColor: colors.sfEe, backgroundColor: colors.sfEe, borderDash: [5, 5], tension: 0.1
                    }}, {{
                        label: '{competitor_name}',
                        data: allSizes.map(() => compData.price_perf),
                        borderColor: colors.comp, backgroundColor: colors.comp, borderDash: [10, 5], pointRadius: 0
                    }}]
                }},
                options: {{
                    responsive: true,
                    plugins: {{ legend: {{ position: 'bottom' }} }},
                    scales: {{ y: {{ type: isLog ? 'logarithmic' : 'linear', title: {{ display: true, text: 'Cost × Geomean — lower is better' }} }} }}
                }}
            }});

            // 5. Scatter: Cost vs Geomean
            const frontierData = {frontier_json};
            const sfPts = frontierData.filter(d => d.is_sf);
            const compPt = frontierData.find(d => !d.is_sf);

            charts.scatterGeo = new Chart(document.getElementById('scatterGeomean'), {{
                type: 'scatter',
                data: {{
                    datasets: [{{
                        label: 'SF SE',
                        data: sfPts.map(d => ({{ x: d.cost, y: d.geomean }})),
                        backgroundColor: sfPts.map(d => d.is_best ? '#32963C' : '#29B5E8'),
                        borderColor: sfPts.map(d => d.is_best ? '#32963C' : '#11567F'),
                        borderWidth: 2, pointRadius: sfPts.map(d => d.is_best ? 10 : 7)
                    }}, {{
                        label: '{competitor_name}',
                        data: [{{ x: compPt.cost, y: compPt.geomean }}],
                        backgroundColor: '#FF9900', borderColor: '#CC7A00',
                        borderWidth: 2, pointRadius: 10, pointStyle: 'triangle'
                    }}]
                }},
                options: {{
                    responsive: true, maintainAspectRatio: true,
                    plugins: {{
                        tooltip: {{ callbacks: {{ label: ctx => {{
                            const d = ctx.datasetIndex === 0 ? sfPts[ctx.dataIndex] : compPt;
                            return `${{d.label}}: $${{d.cost.toFixed(2)}} cost, ${{d.geomean}}s geomean`;
                        }} }} }},
                        legend: {{ position: 'top' }}
                    }},
                    scales: {{
                        x: {{ title: {{ display: true, text: 'Run Cost ($)' }} }},
                        y: {{ title: {{ display: true, text: 'Geomean (s) — lower is better' }} }}
                    }}
                }},
                plugins: [{{
                    afterDraw: (chart) => {{
                        const ctx = chart.ctx;
                        ctx.font = '11px -apple-system, sans-serif';
                        sfPts.forEach((d, i) => {{
                            const meta = chart.getDatasetMeta(0);
                            const pt = meta.data[i];
                            if (pt) {{ ctx.fillStyle = '#11567F'; ctx.textAlign = 'center'; ctx.fillText(d.label.replace('SF ', ''), pt.x, pt.y - 14); }}
                        }});
                        const cm = chart.getDatasetMeta(1);
                        const cp = cm.data[0];
                        if (cp) {{ ctx.fillStyle = '#CC7A00'; ctx.textAlign = 'center'; ctx.fillText(compPt.label, cp.x, cp.y - 14); }}
                    }}
                }}]
            }});

            // 6. Scatter: Cost vs Total
            charts.scatterTotal = new Chart(document.getElementById('scatterTotal'), {{
                type: 'scatter',
                data: {{
                    datasets: [{{
                        label: 'SF SE',
                        data: sfPts.map(d => ({{ x: d.cost, y: d.total }})),
                        backgroundColor: sfPts.map(d => d.is_best ? '#32963C' : '#29B5E8'),
                        borderColor: sfPts.map(d => d.is_best ? '#32963C' : '#11567F'),
                        borderWidth: 2, pointRadius: sfPts.map(d => d.is_best ? 10 : 7)
                    }}, {{
                        label: '{competitor_name}',
                        data: [{{ x: compPt.cost, y: compPt.total }}],
                        backgroundColor: '#FF9900', borderColor: '#CC7A00',
                        borderWidth: 2, pointRadius: 10, pointStyle: 'triangle'
                    }}]
                }},
                options: {{
                    responsive: true, maintainAspectRatio: true,
                    plugins: {{
                        tooltip: {{ callbacks: {{ label: ctx => {{
                            const d = ctx.datasetIndex === 0 ? sfPts[ctx.dataIndex] : compPt;
                            return `${{d.label}}: $${{d.cost.toFixed(2)}} cost, ${{d.total.toFixed(0)}}s total`;
                        }} }} }},
                        legend: {{ position: 'top' }}
                    }},
                    scales: {{
                        x: {{ title: {{ display: true, text: 'Run Cost ($)' }} }},
                        y: {{ title: {{ display: true, text: 'Total Runtime (s) — lower is better' }} }}
                    }}
                }},
                plugins: [{{
                    afterDraw: (chart) => {{
                        const ctx = chart.ctx;
                        ctx.font = '11px -apple-system, sans-serif';
                        sfPts.forEach((d, i) => {{
                            const meta = chart.getDatasetMeta(0);
                            const pt = meta.data[i];
                            if (pt) {{ ctx.fillStyle = '#11567F'; ctx.textAlign = 'center'; ctx.fillText(d.label.replace('SF ', ''), pt.x, pt.y - 14); }}
                        }});
                        const cm = chart.getDatasetMeta(1);
                        const cp = cm.data[0];
                        if (cp) {{ ctx.fillStyle = '#CC7A00'; ctx.textAlign = 'center'; ctx.fillText(compPt.label, cp.x, cp.y - 14); }}
                    }}
                }}]
            }});
        }}

        // Build charts on load
        document.addEventListener('DOMContentLoaded', buildCharts);

        // ================================================================
        // HEAD-TO-HEAD - Dynamic JS
        // ================================================================
        const sfRawData = {sf_raw_json};
        const compTimes = {comp_times_json};
        const sfSizes = {json.dumps(sf_sizes)};
        const competitorName = '{competitor_name}';

        const queryClassifications = {{
            'Reporting': {json.dumps(QUERY_CLASSIFICATIONS['Reporting'])},
            'Ad-hoc': {json.dumps(QUERY_CLASSIFICATIONS['Ad-hoc'])},
            'OLAP': {json.dumps(QUERY_CLASSIFICATIONS['OLAP'])},
            'Data Mining': {json.dumps(QUERY_CLASSIFICATIONS['Data Mining'])}
        }};

        function getCategory(query) {{
            for (const [cat, queries] of Object.entries(queryClassifications)) {{
                if (queries.includes(query)) return cat;
            }}
            return 'Other';
        }}

        let h2hCharts = {{}};

        function renderH2HComparison() {{
            const sfSize = document.getElementById('sfSizeSelector').value;
            const sfTimes = sfRawData[sfSize] || {{}};

            const allQueries = [...new Set([...Object.keys(sfTimes), ...Object.keys(compTimes)])].sort();
            const commonQueries = allQueries.filter(q => sfTimes[q] && compTimes[q] && sfTimes[q] > 0 && compTimes[q] > 0);

            let sfWins = 0, compWins = 0, close = 0;
            const comparisons = [];
            const categoryStats = {{}};

            for (const q of commonQueries) {{
                const sfT = sfTimes[q];
                const compT = compTimes[q];
                const diffPct = ((compT - sfT) / compT) * 100;
                const category = getCategory(q);

                let winner;
                if (Math.abs(diffPct) < 5) {{ winner = 'close'; close++; }}
                else if (diffPct > 0) {{ winner = 'sf'; sfWins++; }}
                else {{ winner = 'comp'; compWins++; }}

                comparisons.push({{ query: q, sfTime: sfT, compTime: compT, diffPct, winner, category }});

                if (!categoryStats[category]) categoryStats[category] = {{ total: 0, sfWins: 0, compWins: 0, close: 0, totalDiff: 0 }};
                categoryStats[category].total++;
                categoryStats[category].totalDiff += diffPct;
                if (winner === 'sf') categoryStats[category].sfWins++;
                else if (winner === 'comp') categoryStats[category].compWins++;
                else categoryStats[category].close++;
            }}

            comparisons.sort((a, b) => b.diffPct - a.diffPct);
            const total = comparisons.length;
            const sfPct = Math.round(sfWins / total * 100);
            const compPct = Math.round(compWins / total * 100);
            const winnerClass = sfWins > compWins ? 'winner' : '';

            // Category rows
            let catRows = '';
            const catColors = {{'Reporting': '#e3f2fd', 'Ad-hoc': '#fff3e0', 'OLAP': '#f3e5f5', 'Data Mining': '#e8f5e9'}};
            for (const [cat, stats] of Object.entries(categoryStats)) {{
                const bg = catColors[cat] || '#f5f5f5';
                const avgDiff = stats.totalDiff / stats.total;
                const diffColor = avgDiff > 0 ? '#29b5e8' : '#FF9900';
                const dominant = stats.sfWins > stats.compWins ? '<strong style="color:#29b5e8">SF</strong>' :
                                 stats.compWins > stats.sfWins ? `<strong style="color:#FF9900">${{competitorName}}</strong>` : '—';
                catRows += `<tr>
                    <td><span style="background:${{bg}};padding:2px 8px;border-radius:3px;font-weight:600;">${{cat}}</span></td>
                    <td style="text-align:right;">${{stats.total}}</td>
                    <td style="text-align:right;color:#29b5e8;">${{stats.sfWins}}</td>
                    <td style="text-align:right;color:#FF9900;">${{stats.compWins}}</td>
                    <td style="text-align:right;color:#888;">${{stats.close}}</td>
                    <td style="text-align:right;color:${{diffColor}};">${{avgDiff > 0 ? '+' : ''}}${{avgDiff.toFixed(1)}}%</td>
                    <td>${{dominant}}</td>
                </tr>`;
            }}

            // Query rows
            let queryRows = '';
            for (const c of comparisons) {{
                const diffColor = c.diffPct > 5 ? '#29b5e8' : c.diffPct < -5 ? '#FF9900' : '#888';
                const winnerBadge = c.winner === 'sf' ? '<span style="background:#e3f2fd;color:#29b5e8;padding:2px 8px;border-radius:3px;font-weight:600;">SF</span>' :
                                    c.winner === 'comp' ? `<span style="background:#fff3e0;color:#FF9900;padding:2px 8px;border-radius:3px;font-weight:600;">${{competitorName.slice(0,3)}}</span>` :
                                    '<span style="color:#888;">≈</span>';

                queryRows += `<tr class="query-row" data-query="${{c.query}}" onclick="showScalingCurve('${{c.query}}')" style="cursor:pointer;">
                    <td><strong>${{c.query}}</strong></td>
                    <td style="font-size:0.85em;color:#666;">${{c.category}}</td>
                    <td style="text-align:right;">${{c.sfTime.toFixed(2)}}</td>
                    <td style="text-align:right;">${{c.compTime.toFixed(2)}}</td>
                    <td style="text-align:right;color:${{diffColor}};font-weight:600;">${{c.diffPct > 0 ? '+' : ''}}${{c.diffPct.toFixed(1)}}%</td>
                    <td style="text-align:center;">${{winnerBadge}}</td>
                </tr>`;
            }}

            // Competitor losses callout
            const compLosses = comparisons.filter(c => c.winner === 'comp' && Math.abs(c.diffPct) > 10);
            let lossHtml = '';
            if (compLosses.length > 0) {{
                for (const c of compLosses) {{
                    const pct = Math.abs(c.diffPct);
                    const delta = (c.sfTime - c.compTime).toFixed(1);
                    lossHtml += `<div class="insight-box warning">
                        <strong>${{c.query}}</strong>: ${{competitorName}} is ${{pct.toFixed(0)}}% faster
                        (${{c.compTime.toFixed(2)}}s vs ${{c.sfTime.toFixed(2)}}s, +${{delta}}s delta)
                    </div>`;
                }}
            }} else {{
                lossHtml = '<div class="insight-box winner"><strong>No significant losses!</strong> SF wins or ties on all queries at this size.</div>';
            }}

            document.getElementById('h2hComparisonContent').innerHTML = `
                <div class="summary-row">
                    <div class="card sf">
                        <div class="label">SF Wins</div>
                        <div class="value">${{sfWins}}</div>
                        <div class="detail">${{sfPct}}% of queries</div>
                    </div>
                    <div class="card comp">
                        <div class="label">${{competitorName}} Wins</div>
                        <div class="value">${{compWins}}</div>
                        <div class="detail">${{compPct}}% of queries</div>
                    </div>
                    <div class="card">
                        <div class="label">Close (&lt;5%)</div>
                        <div class="value">${{close}}</div>
                        <div class="detail">too close to call</div>
                    </div>
                </div>

                <div class="insight-box ${{winnerClass}}">
                    <strong>Summary:</strong> Comparing SF ${{sfSize}} vs ${{competitorName}}, Snowflake is faster on <strong>${{sfWins}}</strong> queries
                    while ${{competitorName}} wins on <strong>${{compWins}}</strong>.
                    ${{close}} queries are within 5% (too close to call).
                </div>

                <h3>Performance by Query Category</h3>
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th style="text-align:left;">Category</th>
                                <th style="text-align:right;">Total</th>
                                <th style="text-align:right;">SF Wins</th>
                                <th style="text-align:right;">${{competitorName}} Wins</th>
                                <th style="text-align:right;">Close</th>
                                <th style="text-align:right;">Avg SF Advantage</th>
                                <th style="text-align:left;">Dominant</th>
                            </tr>
                        </thead>
                        <tbody>${{catRows}}</tbody>
                    </table>
                </div>

                <h3>Speed Advantage Chart</h3>
                <p style="color:var(--sf-gray);">Blue = SF faster, Orange = ${{competitorName}} faster. Bar length shows magnitude.</p>
                <div class="chart-container" style="height:500px;">
                    <canvas id="h2hChart"></canvas>
                </div>

                <h3>Query Comparison <span style="font-weight:normal;font-size:0.8em;color:#666;">(click a row to see SF scaling curve)</span></h3>
                <div class="table-container" style="max-height:500px;overflow-y:auto;">
                    <table>
                        <thead style="position:sticky;top:0;background:white;">
                            <tr>
                                <th style="text-align:left;">Query</th>
                                <th style="text-align:left;">Category</th>
                                <th style="text-align:right;">SF ${{sfSize}} (s)</th>
                                <th style="text-align:right;">${{competitorName}} (s)</th>
                                <th style="text-align:right;">SF Advantage</th>
                                <th style="text-align:center;">Faster</th>
                            </tr>
                        </thead>
                        <tbody>${{queryRows}}</tbody>
                    </table>
                </div>

                <h3>Queries Where ${{competitorName}} Wins</h3>
                ${{lossHtml}}

                <div id="scalingCurveContainer" style="margin-top:30px;display:none;">
                    <h3 id="scalingCurveTitle">Scaling Curve</h3>
                    <div class="chart-container" style="height:300px;">
                        <canvas id="scalingCurveChart"></canvas>
                    </div>
                </div>
            `;

            // Build H2H butterfly chart
            if (h2hCharts.butterfly) h2hCharts.butterfly.destroy();
            h2hCharts.butterfly = new Chart(document.getElementById('h2hChart'), {{
                type: 'bar',
                data: {{
                    labels: comparisons.map(d => d.query),
                    datasets: [{{
                        label: 'SF Advantage %',
                        data: comparisons.map(d => d.diffPct),
                        backgroundColor: comparisons.map(d => d.diffPct > 5 ? '#29b5e8' : d.diffPct < -5 ? '#FF9900' : '#ccc'),
                        borderWidth: 0
                    }}]
                }},
                options: {{
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{ display: false }},
                        tooltip: {{ callbacks: {{ label: ctx => {{
                            const val = ctx.raw;
                            return val > 0 ? `SF ${{val.toFixed(1)}}% faster` : `${{competitorName}} ${{Math.abs(val).toFixed(1)}}% faster`;
                        }} }} }}
                    }},
                    scales: {{
                        x: {{ title: {{ display: true, text: 'SF Advantage %' }} }},
                        y: {{ ticks: {{ font: {{ size: 9 }} }} }}
                    }}
                }}
            }});
        }}

        // ---- INDIVIDUAL QUERY SCALING CURVE ----
        function showScalingCurve(query) {{
            const container = document.getElementById('scalingCurveContainer');
            if (!container) return;
            container.style.display = 'block';
            document.getElementById('scalingCurveTitle').textContent = `Scaling Curve: ${{query}}`;

            const sfTimes = sfSizes.map(s => sfRawData[s] ? sfRawData[s][query] || null : null);
            const compTime = compTimes[query] || null;

            if (h2hCharts.scaling) h2hCharts.scaling.destroy();
            h2hCharts.scaling = new Chart(document.getElementById('scalingCurveChart'), {{
                type: 'line',
                data: {{
                    labels: sfSizes,
                    datasets: [{{
                        label: 'Snowflake',
                        data: sfTimes,
                        borderColor: '#29B5E8',
                        backgroundColor: '#29B5E8',
                        tension: 0.1,
                        pointRadius: 5
                    }}, {{
                        label: competitorName,
                        data: sfSizes.map(() => compTime),
                        borderColor: '#FF9900',
                        backgroundColor: '#FF9900',
                        borderDash: [10, 5],
                        pointRadius: 0
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{ legend: {{ position: 'bottom' }} }},
                    scales: {{
                        y: {{ title: {{ display: true, text: 'Seconds — lower is better' }}, beginAtZero: false }}
                    }}
                }}
            }});

            container.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
        }}

        // Initialize H2H on load
        document.addEventListener('DOMContentLoaded', renderH2HComparison);
    </script>
</body>
</html>'''

    with open(output_path, 'w') as f:
        f.write(html)

    print(f"Report generated: {output_path}")
    return output_path


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='Generate TPC-DS Price:Performance Report')
    parser.add_argument('--sf-runs', required=True, help='Comma-separated SF run keys')
    parser.add_argument('--sf-sizes', required=True, help='Comma-separated SF warehouse sizes (matching run order)')
    parser.add_argument('--competitor-run', required=True, type=int, help='Competitor run key')
    parser.add_argument('--competitor-name', required=True, help='Competitor name (e.g., Athena)')
    parser.add_argument('--competitor-cost', required=True, type=float, help='Competitor cost in USD')
    parser.add_argument('--output', required=True, help='Output HTML file path')
    parser.add_argument('--publish', action='store_true',
                        help='Publish report to results/competitive/ with date-stamped filename')

    args = parser.parse_args()

    sf_runs = [int(x.strip()) for x in args.sf_runs.split(',')]
    sf_sizes = [x.strip() for x in args.sf_sizes.split(',')]

    if len(sf_runs) != len(sf_sizes):
        print(f"ERROR: Number of runs ({len(sf_runs)}) must match number of sizes ({len(sf_sizes)})")
        sys.exit(1)

    publish_date = None
    if args.publish:
        publish_date = datetime.now().strftime("%Y-%m-%d")

    print("Connecting to Snowflake...")
    conn = get_snowflake_connection()

    # Fetch SF data
    sf_data = {}
    for run_key, size in zip(sf_runs, sf_sizes):
        print(f"Fetching SF {size} run {run_key}...")
        times = fetch_query_times(conn, run_key, 'snowflake')
        metadata = fetch_run_metadata(conn, run_key)
        sf_data[size] = {
            'run_key': run_key,
            'times': times,
            'metadata': metadata
        }

    # Fetch competitor data
    print(f"Fetching {args.competitor_name} run {args.competitor_run}...")
    competitor_times = fetch_query_times(conn, args.competitor_run, 'athena')
    competitor_metadata = fetch_run_metadata(conn, args.competitor_run)

    competitor_data = {
        'name': args.competitor_name,
        'run_key': args.competitor_run,
        'times': competitor_times,
        'cost': args.competitor_cost,
        'metadata': competitor_metadata
    }

    conn.close()

    # Generate report
    print("Generating HTML report...")
    generate_html(sf_data, competitor_data, args.output, publish_date=publish_date)

    # Publish to results folder
    if args.publish:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(script_dir)
        results_dir = os.path.join(project_root, 'results', 'competitive')
        os.makedirs(results_dir, exist_ok=True)

        comp_slug = args.competitor_name.lower().replace(' ', '-')
        publish_filename = f"sf-vs-{comp_slug}-tpcds-10tb-{publish_date}.html"
        publish_path = os.path.join(results_dir, publish_filename)

        shutil.copy2(args.output, publish_path)
        print(f"Published: {publish_path}")

    print("Done!")


if __name__ == '__main__':
    main()
