#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SF FDN vs Databricks Delta Price:Performance Report Generator

Generates self-contained HTML reports comparing Snowflake (FDN) vs Databricks (Delta)
on TPC-DS 10TB power/serial runs using a price-performance frontier approach.

Key insight: Customers don't care about t-shirt sizes - they care about
performance at an acceptable price point. This report answers:
1. "At this budget, who's faster?"
2. "To hit this SLA, what's the cheapest option?"

Usage:
    python generate-sf-vs-dbx-report.py \
        --sf-runs 3760762,3760760,3760763,3760740,3760766 \
        --sf-sizes S,M,L,XL,2XL \
        --dbx-runs 3760299,3760291,3760696,3760002,3760804 \
        --dbx-sizes S,M,L,XL,2XL \
        --output sf-fdn-vs-dbx-delta-10tb.html

Requires: snowflake-connector-python
"""

import argparse
import json
import math
import os
import shutil
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

try:
    import snowflake.connector
except ImportError:
    print("ERROR: snowflake-connector-python required. Install with: pip install snowflake-connector-python")
    sys.exit(1)

# Shared TPC-DS category utilities (single source of truth for classifications)
from tpcds_categories import (
    QUERY_CLASSIFICATIONS as SHARED_QUERY_CLASSIFICATIONS,
    calc_category_geomean as shared_calc_category_geomean,
    calc_category_total as shared_calc_category_total,
    build_category_breakdown, render_category_table_html,
    get_category, get_category_queries
)


# =============================================================================
# CONSTANTS
# =============================================================================

# TPC-DS Query Classifications (per TPC-DS spec)
QUERY_CLASSIFICATIONS = {
    'Reporting': ['q01','q02','q03','q05','q07','q12','q13','q15','q17','q18','q20','q25','q26','q42','q43','q52','q53','q55','q62','q89','q98','q99'],
    'Ad-hoc': ['q06','q08','q19','q32','q34','q40','q45','q46','q48','q61','q63','q68','q73','q79','q88','q90','q92','q96'],
    'OLAP': ['q04','q09','q10','q11','q14a','q14b','q22','q23a','q23b','q27','q28','q31','q33','q35','q36','q38','q44','q47','q49','q51','q54','q56','q57','q58','q59','q60','q64','q65','q66','q67','q70','q71','q74','q75','q76','q77','q78','q80','q86','q87','q97'],
    'Data Mining': ['q16','q21','q24a','q24b','q29','q30','q37','q39a','q39b','q41','q50','q69','q72','q81','q82','q83','q84','q85','q91','q93','q94','q95']
}

# Snowflake Gen2 Pricing (AWS: Gen2 uses 1.35x credits vs Gen1)
# Gen1 credits: XS=1, S=2, M=4, L=8, XL=16, 2XL=32, 3XL=64, 4XL=128
SF_CREDITS_PER_HOUR_GEN2 = {
    'XS': 1.35, 'S': 2.7, 'M': 5.4, 'L': 10.8, 'XL': 21.6, '2XL': 43.2, '3XL': 86.4, '4XL': 172.8
}
SF_CREDIT_RATE_SE = 2.00  # Standard Edition list price
SF_CREDIT_RATE_EE = 3.00  # Enterprise Edition list price

# Databricks SQL Warehouse Pricing (combined DBU + compute, $/hour)
DBX_COST_PER_HOUR = {
    'XXS': 1.4,
    'XS': 2.8,
    'S': 8.4,
    'M': 16.8,
    'L': 28.0,
    'XL': 56.0,
    '2XL': 100.8,
    '3XL': 190.4,
    '4XL': 369.6
}

SIZE_ORDER = ['XS', 'S', 'M', 'L', 'XL', '2XL', '3XL', '4XL']

# TPC-DS Query Descriptions (per TPC-DS spec)
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
    else:  # Databricks - use server/total_time_ms (duration_ms is NULL)
        metric_field = "metrics:\"server/total_time_ms\"::FLOAT / 1000"
    
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
            # Convert P1/P2 to a/b
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
        run_date_raw = str(row[1]).strip('"')
        return {
            'run_key': row[0], 'run_date': run_date_raw, 'platform': row[2],
            'wh_size': row[3], 'wh_type': row[4], 'data_format': row[5],
            'warm_queries': row[6] or 0
        }
    return {}


# =============================================================================
# CALCULATIONS
# =============================================================================

def calc_geomean(values: List[float]) -> float:
    """Calculate geometric mean of values."""
    valid = [v for v in values if v and v > 0]
    if not valid:
        return 0
    product = 1
    for v in valid:
        product *= v
    return round(product ** (1/len(valid)), 2)


def calc_total(values: List[float]) -> float:
    """Calculate sum of values."""
    valid = [v for v in values if v]
    return round(sum(valid), 1)


def calc_sf_cost(runtime_seconds: float, wh_size: str, credit_rate: float = SF_CREDIT_RATE_SE) -> float:
    """Calculate Snowflake cost for a run."""
    hours = runtime_seconds / 3600
    credits = hours * SF_CREDITS_PER_HOUR_GEN2.get(wh_size, 21.6)
    return round(credits * credit_rate, 2)


def calc_sf_hourly_rate(wh_size: str, credit_rate: float = SF_CREDIT_RATE_SE) -> float:
    """Get SF hourly rate for a size."""
    return SF_CREDITS_PER_HOUR_GEN2.get(wh_size, 21.6) * credit_rate


def calc_dbx_cost(runtime_seconds: float, dbx_size: str) -> float:
    """Calculate Databricks cost for a run."""
    hours = runtime_seconds / 3600
    hourly_rate = DBX_COST_PER_HOUR.get(dbx_size, 56)
    return round(hours * hourly_rate, 2)


def calc_dbx_hourly_rate(dbx_size: str) -> float:
    """Get DBX hourly rate for a size."""
    return DBX_COST_PER_HOUR.get(dbx_size, 56)


def build_performance_tiers(sf_stats: Dict, dbx_stats: Dict, num_tiers: int = 4):
    """
    Build SLA tiers using log-scale across the full performance range.
    
    UNBIASED APPROACH:
    1. First tier starts just above the FASTEST config (either vendor) — rewards speed leadership
    2. Log-spaced tiers across the full range to slowest config
    3. Shows capability gaps - if one vendor can't meet a tight SLA, that's valuable data
    """
    import numpy as np
    
    # Get each vendor's performance range
    sf_geomeans = [s['geomean'] for s in sf_stats.values() if s.get('geomean')]
    dbx_geomeans = [s['geomean'] for s in dbx_stats.values() if s.get('geomean')]
    
    if not sf_geomeans or not dbx_geomeans:
        return []
    
    # Full range - first tier rewards the fastest provider
    fastest = min(min(sf_geomeans), min(dbx_geomeans))
    slowest = max(max(sf_geomeans), max(dbx_geomeans))
    
    # Start SLA just above fastest config (rewards speed leadership)
    # No artificial floor - if SF can do 3.7s, first tier should be ~4s
    min_sla = fastest * 1.1  # 10% buffer above fastest
    max_sla = slowest * 1.05  # Just above slowest
    
    # Create log-spaced SLA targets
    sla_targets = np.geomspace(min_sla, max_sla, num_tiers)
    
    # Round to nice numbers
    def round_to_nice(x):
        if x < 10:
            return round(x)
        elif x < 100:
            return round(x / 5) * 5
        else:
            return round(x / 10) * 10
    
    # Build tier definitions, avoiding duplicates
    tiers = []
    seen = set()
    for target in sla_targets:
        nice = round_to_nice(target)
        if nice not in seen:
            seen.add(nice)
            tiers.append({
                'label': f'≤{nice}s SLA',
                'target': nice
            })
    
    return tiers[:num_tiers]


def find_cheapest_config_for_sla(configs: Dict, sla_target: float) -> Tuple[str, Dict]:
    """Find the cheapest config that meets an SLA target (geomean <= target)."""
    best_size = None
    best_stats = None
    
    for size, stats in configs.items():
        geomean = stats.get('geomean', 999)
        if geomean <= sla_target:  # Meets the SLA
            if best_stats is None or stats['hourly_rate'] < best_stats['hourly_rate']:
                best_size = size
                best_stats = stats
    
    return best_size, best_stats


def find_best_config_for_tier(configs: Dict, tier: Dict) -> Tuple[str, Dict]:
    """Find the best performing config within a price tier."""
    best_size = None
    best_stats = None
    
    for size, stats in configs.items():
        hourly_rate = stats.get('hourly_rate', 0)
        if tier['min'] <= hourly_rate <= tier['max']:
            if best_stats is None or stats['geomean'] < best_stats['geomean']:
                best_size = size
                best_stats = stats
    
    return best_size, best_stats


def find_cheapest_config_for_perf_tier(configs: Dict, tier: Dict) -> Tuple[str, Dict]:
    """Find the cheapest config that meets a performance tier (geomean latency)."""
    best_size = None
    best_stats = None
    
    for size, stats in configs.items():
        geomean = stats.get('geomean', 999)
        if tier['min'] <= geomean <= tier['max']:
            if best_stats is None or stats['hourly_rate'] < best_stats['hourly_rate']:
                best_size = size
                best_stats = stats
    
    return best_size, best_stats


def calc_category_geomean(times: Dict[str, float], category: str) -> float:
    """Calculate geomean for queries in a specific category."""
    category_queries = QUERY_CLASSIFICATIONS.get(category, [])
    values = [times.get(q) for q in category_queries if times.get(q) and times.get(q) > 0]
    return calc_geomean(values) if values else 0


def calc_category_total(times: Dict[str, float], category: str) -> float:
    """Calculate total for queries in a specific category."""
    category_queries = QUERY_CLASSIFICATIONS.get(category, [])
    values = [times.get(q) for q in category_queries if times.get(q)]
    return calc_total(values) if values else 0


def compute_head_to_head(sf_times: Dict[str, float], dbx_times: Dict[str, float],
                          sf_data: Dict = None, dbx_data: Dict = None,
                          threshold_pct: float = 5.0) -> Dict:
    """
    Compute head-to-head query comparison between SF and DBX.
    
    Args:
        sf_times: Dict of query -> time in seconds for Snowflake (at comparison size)
        dbx_times: Dict of query -> time in seconds for Databricks (at comparison size)
        sf_data: Full SF data dict with all sizes (for scaling analysis)
        dbx_data: Full DBX data dict with all sizes (for scaling analysis)
        threshold_pct: Percentage difference below which we call it "close"
    
    Returns:
        Dict with comparison stats and per-query results including scaling
    """
    comparisons = []
    sf_wins = 0
    dbx_wins = 0
    close = 0
    
    # Scaling stats
    sf_scales_better = 0
    dbx_scales_better = 0
    scaling_close = 0
    
    # Get common queries
    all_queries = sorted(set(sf_times.keys()) & set(dbx_times.keys()))
    
    # Determine size range for scaling calculation
    sf_sizes = list(sf_data.keys()) if sf_data else []
    dbx_sizes = list(dbx_data.keys()) if dbx_data else []
    
    # Find common sizes for scaling comparison
    size_order = ['S', 'M', 'L', 'XL', '2XL', '3XL', '4XL']
    common_sizes = set(sf_sizes) & set(dbx_sizes)
    ordered_common = [s for s in size_order if s in common_sizes]
    
    can_compute_scaling = len(ordered_common) >= 2
    smallest = ordered_common[0] if can_compute_scaling else None
    largest = ordered_common[-1] if can_compute_scaling else None
    
    for q in all_queries:
        sf_t = sf_times.get(q)
        dbx_t = dbx_times.get(q)
        
        if not sf_t or not dbx_t or sf_t <= 0 or dbx_t <= 0:
            continue
        
        # Calculate advantage (positive = SF faster)
        diff_pct = ((dbx_t - sf_t) / dbx_t) * 100
        
        # Determine winner
        if abs(diff_pct) < threshold_pct:
            winner = 'close'
            close += 1
        elif diff_pct > 0:
            winner = 'sf'
            sf_wins += 1
        else:
            winner = 'dbx'
            dbx_wins += 1
        
        # Find category
        category = 'Other'
        for cat, queries in QUERY_CLASSIFICATIONS.items():
            if q in queries:
                category = cat
                break
        
        # Compute scaling factor for this query (time_largest / time_smallest)
        # Lower scaling factor = better scaling (less slowdown as data grows)
        sf_scaling = None
        dbx_scaling = None
        scaling_winner = None
        scaling_diff = None
        
        if can_compute_scaling and sf_data and dbx_data:
            sf_small = sf_data.get(smallest, {}).get('times', {}).get(q)
            sf_large = sf_data.get(largest, {}).get('times', {}).get(q)
            dbx_small = dbx_data.get(smallest, {}).get('times', {}).get(q)
            dbx_large = dbx_data.get(largest, {}).get('times', {}).get(q)
            
            if sf_small and sf_large and sf_small > 0:
                sf_scaling = sf_large / sf_small
            if dbx_small and dbx_large and dbx_small > 0:
                dbx_scaling = dbx_large / dbx_small
            
            if sf_scaling and dbx_scaling:
                # Scaling diff: positive = SF scales better (lower ratio)
                scaling_diff = ((dbx_scaling - sf_scaling) / dbx_scaling) * 100
                
                if abs(scaling_diff) < threshold_pct:
                    scaling_winner = 'close'
                    scaling_close += 1
                elif scaling_diff > 0:
                    scaling_winner = 'sf'
                    sf_scales_better += 1
                else:
                    scaling_winner = 'dbx'
                    dbx_scales_better += 1
        
        comparisons.append({
            'query': q,
            'sf_time': sf_t,
            'dbx_time': dbx_t,
            'diff_pct': round(diff_pct, 1),
            'winner': winner,
            'category': category,
            'sf_scaling': round(sf_scaling, 2) if sf_scaling else None,
            'dbx_scaling': round(dbx_scaling, 2) if dbx_scaling else None,
            'scaling_diff': round(scaling_diff, 1) if scaling_diff else None,
            'scaling_winner': scaling_winner
        })
    
    # Sort by advantage (biggest SF wins first)
    comparisons.sort(key=lambda x: -x['diff_pct'])
    
    # Category summary
    category_stats = {}
    for cat in QUERY_CLASSIFICATIONS.keys():
        cat_comps = [c for c in comparisons if c['category'] == cat]
        if cat_comps:
            cat_sf_wins = sum(1 for c in cat_comps if c['winner'] == 'sf')
            cat_dbx_wins = sum(1 for c in cat_comps if c['winner'] == 'dbx')
            cat_close = sum(1 for c in cat_comps if c['winner'] == 'close')
            avg_diff = sum(c['diff_pct'] for c in cat_comps) / len(cat_comps)
            category_stats[cat] = {
                'total': len(cat_comps),
                'sf_wins': cat_sf_wins,
                'dbx_wins': cat_dbx_wins,
                'close': cat_close,
                'avg_diff': round(avg_diff, 1)
            }
    
    return {
        'sf_wins': sf_wins,
        'dbx_wins': dbx_wins,
        'close': close,
        'total': len(comparisons),
        'comparisons': comparisons,
        'category_stats': category_stats,
        'sf_scales_better': sf_scales_better,
        'dbx_scales_better': dbx_scales_better,
        'scaling_close': scaling_close,
        'scaling_range': f"{smallest} → {largest}" if can_compute_scaling else None
    }


def generate_h2h_html(h2h: Dict) -> str:
    """Generate HTML for the head-to-head tab."""
    if not h2h:
        return '<p>Head-to-head comparison not available (no common sizes)</p>'
    
    size = h2h['size']
    sf_wins = h2h['sf_wins']
    dbx_wins = h2h['dbx_wins']
    close = h2h['close']
    total = h2h['total']
    
    # Scaling stats
    sf_scales_better = h2h.get('sf_scales_better', 0)
    dbx_scales_better = h2h.get('dbx_scales_better', 0)
    scaling_close = h2h.get('scaling_close', 0)
    scaling_range = h2h.get('scaling_range', '')
    has_scaling = scaling_range is not None
    
    # Summary cards
    sf_pct = round(sf_wins/total*100) if total else 0
    dbx_pct = round(dbx_wins/total*100) if total else 0
    
    # Category rows
    cat_rows = []
    for cat, stats in h2h['category_stats'].items():
        bg = '#e3f2fd' if cat=='Reporting' else '#fff3e0' if cat=='Ad-hoc' else '#f3e5f5' if cat=='OLAP' else '#e8f5e9'
        diff_color = '#29b5e8' if stats['avg_diff'] > 0 else '#ff6b35'
        dominant = '<strong style="color:#29b5e8">SF</strong>' if stats['sf_wins'] > stats['dbx_wins'] else '<strong style="color:#ff6b35">DBX</strong>' if stats['dbx_wins'] > stats['sf_wins'] else '—'
        cat_rows.append(f'''<tr>
            <td><span style="background:{bg};padding:2px 8px;border-radius:3px;font-weight:600;">{cat}</span></td>
            <td style="text-align:right;">{stats['total']}</td>
            <td style="text-align:right;color:#29b5e8;">{stats['sf_wins']}</td>
            <td style="text-align:right;color:#ff6b35;">{stats['dbx_wins']}</td>
            <td style="text-align:right;color:#888;">{stats['close']}</td>
            <td style="text-align:right;color:{diff_color};">{stats['avg_diff']:+.1f}%</td>
            <td>{dominant}</td>
        </tr>''')
    
    # Query rows with scaling (sorted by SF advantage)
    query_rows = []
    for c in h2h['comparisons']:
        diff_color = '#29b5e8' if c['diff_pct'] > 5 else '#ff6b35' if c['diff_pct'] < -5 else '#888'
        if c['winner'] == 'sf':
            winner_badge = '<span style="background:#e3f2fd;color:#29b5e8;padding:2px 8px;border-radius:3px;font-weight:600;">SF</span>'
        elif c['winner'] == 'dbx':
            winner_badge = '<span style="background:#fff3e0;color:#ff6b35;padding:2px 8px;border-radius:3px;font-weight:600;">DBX</span>'
        else:
            winner_badge = '<span style="color:#888;">≈</span>'
        
        # Scaling badge
        scaling_winner = c.get('scaling_winner')
        if scaling_winner == 'sf':
            scaling_badge = '<span style="background:#e3f2fd;color:#29b5e8;padding:2px 6px;border-radius:3px;font-size:0.8em;">SF</span>'
        elif scaling_winner == 'dbx':
            scaling_badge = '<span style="background:#fff3e0;color:#ff6b35;padding:2px 6px;border-radius:3px;font-size:0.8em;">DBX</span>'
        elif scaling_winner == 'close':
            scaling_badge = '<span style="color:#888;font-size:0.8em;">≈</span>'
        else:
            scaling_badge = '<span style="color:#ccc;font-size:0.8em;">—</span>'
        
        sf_scale = f"{c['sf_scaling']:.1f}×" if c.get('sf_scaling') else '—'
        dbx_scale = f"{c['dbx_scaling']:.1f}×" if c.get('dbx_scaling') else '—'
        
        query_rows.append(f'''<tr>
            <td><strong>{c['query']}</strong></td>
            <td style="font-size:0.85em;color:#666;">{c['category']}</td>
            <td style="text-align:right;">{c['sf_time']:.2f}</td>
            <td style="text-align:right;">{c['dbx_time']:.2f}</td>
            <td style="text-align:right;color:{diff_color};font-weight:600;">{c['diff_pct']:+.1f}%</td>
            <td style="text-align:center;">{winner_badge}</td>
            <td style="text-align:right;color:#29b5e8;">{sf_scale}</td>
            <td style="text-align:right;color:#ff6b35;">{dbx_scale}</td>
            <td style="text-align:center;">{scaling_badge}</td>
        </tr>''')
    
    # Scaling-sorted rows (for scaling table)
    scaling_sorted = sorted(
        [c for c in h2h['comparisons'] if c.get('scaling_diff') is not None],
        key=lambda x: x['scaling_diff']  # DBX scales better first (negative values)
    )
    
    scaling_rows = []
    for c in scaling_sorted:
        sf_scale = f"{c['sf_scaling']:.1f}×" if c.get('sf_scaling') else '—'
        dbx_scale = f"{c['dbx_scaling']:.1f}×" if c.get('dbx_scaling') else '—'
        scaling_diff = c.get('scaling_diff', 0)
        diff_color = '#29b5e8' if scaling_diff > 5 else '#ff6b35' if scaling_diff < -5 else '#888'
        
        if c.get('scaling_winner') == 'sf':
            scaling_badge = '<span style="background:#e3f2fd;color:#29b5e8;padding:2px 8px;border-radius:3px;font-weight:600;">SF</span>'
        elif c.get('scaling_winner') == 'dbx':
            scaling_badge = '<span style="background:#fff3e0;color:#ff6b35;padding:2px 8px;border-radius:3px;font-weight:600;">DBX</span>'
        else:
            scaling_badge = '<span style="color:#888;">≈</span>'
        
        scaling_rows.append(f'''<tr>
            <td><strong>{c['query']}</strong></td>
            <td style="font-size:0.85em;color:#666;">{c['category']}</td>
            <td style="text-align:right;color:#29b5e8;">{sf_scale}</td>
            <td style="text-align:right;color:#ff6b35;">{dbx_scale}</td>
            <td style="text-align:right;color:{diff_color};font-weight:600;">{scaling_diff:+.1f}%</td>
            <td style="text-align:center;">{scaling_badge}</td>
        </tr>''')
    
    # Chart data JSON
    chart_data = json.dumps([{'query': c['query'], 'diff': c['diff_pct'], 'category': c['category']} for c in h2h['comparisons']])
    scaling_chart_data = json.dumps([{'query': c['query'], 'diff': c.get('scaling_diff', 0)} for c in scaling_sorted])
    
    winner_class = 'winner' if sf_wins > dbx_wins else ''
    scaling_winner_class = 'winner' if sf_scales_better > dbx_scales_better else ''
    
    # Scaling section HTML
    scaling_section = ''
    if has_scaling:
        scaling_section = f'''
        <h3 style="margin-top:40px;border-top:2px solid #eee;padding-top:20px;">Scaling Comparison ({scaling_range})</h3>
        <p style="color:#666;margin-bottom:15px;">
            Scaling factor = time at {scaling_range.split(" → ")[1]} ÷ time at {scaling_range.split(" → ")[0]}. 
            Lower = better scaling. Shows how query time grows as data increases.
        </p>
        
        <div class="summary-row">
            <div class="card sf">
                <div class="label">SF Scales Better</div>
                <div class="value">{sf_scales_better}</div>
                <div class="detail">queries</div>
            </div>
            <div class="card dbx">
                <div class="label">DBX Scales Better</div>
                <div class="value">{dbx_scales_better}</div>
                <div class="detail">queries</div>
            </div>
            <div class="card">
                <div class="label">Close (&lt;5%)</div>
                <div class="value">{scaling_close}</div>
                <div class="detail">similar scaling</div>
            </div>
        </div>
        
        <div class="insight-box {scaling_winner_class}">
            <strong>Scaling Summary:</strong> From {scaling_range}, Snowflake scales better on <strong>{sf_scales_better}</strong> queries 
            while Databricks scales better on <strong>{dbx_scales_better}</strong>. 
            {scaling_close} queries have similar scaling behavior.
        </div>
        
        <h4>Scaling Advantage Chart</h4>
        <div class="chart-container" style="height:400px;">
            <canvas id="scalingChart"></canvas>
        </div>
        
        <h4>Scaling Comparison (sorted by DBX advantage)</h4>
        <p>Sorted to show queries where DBX scales better first. Positive = SF scales better, Negative = DBX scales better.</p>
        <div class="table-container" style="max-height:400px;overflow-y:auto;">
            <table>
                <thead style="position:sticky;top:0;background:white;">
                    <tr>
                        <th style="text-align:left;">Query</th>
                        <th style="text-align:left;">Category</th>
                        <th style="text-align:right;">SF Scaling</th>
                        <th style="text-align:right;">DBX Scaling</th>
                        <th style="text-align:right;">SF Advantage</th>
                        <th style="text-align:center;">Better Scaling</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(scaling_rows)}
                </tbody>
            </table>
        </div>
        
        <script>
            // Scaling Butterfly Chart
            const scalingData = {scaling_chart_data};
            
            new Chart(document.getElementById("scalingChart"), {{
                type: "bar",
                data: {{
                    labels: scalingData.map(d => d.query),
                    datasets: [{{
                        label: "SF Scaling Advantage %",
                        data: scalingData.map(d => d.diff),
                        backgroundColor: scalingData.map(d => d.diff > 5 ? "#29b5e8" : d.diff < -5 ? "#ff6b35" : "#ccc"),
                        borderWidth: 0
                    }}]
                }},
                options: {{
                    indexAxis: "y",
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{ display: false }},
                        tooltip: {{
                            callbacks: {{
                                label: ctx => {{
                                    const val = ctx.raw;
                                    return val > 0 ? `SF scales ${{val.toFixed(1)}}% better` : `DBX scales ${{Math.abs(val).toFixed(1)}}% better`;
                                }}
                            }}
                        }}
                    }},
                    scales: {{
                        x: {{
                            title: {{ display: true, text: "SF Scaling Advantage %" }},
                            grid: {{ color: "#eee" }}
                        }},
                        y: {{
                            ticks: {{ font: {{ size: 9 }} }}
                        }}
                    }}
                }}
            }});
        </script>
        '''
    
    return f'''
        <div class="summary-row">
            <div class="card sf">
                <div class="label">SF Wins</div>
                <div class="value">{sf_wins}</div>
                <div class="detail">{sf_pct}% of queries</div>
            </div>
            <div class="card dbx">
                <div class="label">DBX Wins</div>
                <div class="value">{dbx_wins}</div>
                <div class="detail">{dbx_pct}% of queries</div>
            </div>
            <div class="card">
                <div class="label">Close (&lt;5%)</div>
                <div class="value">{close}</div>
                <div class="detail">too close to call</div>
            </div>
        </div>
        
        <div class="insight-box {winner_class}">
            <strong>Summary:</strong> At {size} size, Snowflake is faster on <strong>{sf_wins}</strong> queries 
            while Databricks wins on <strong>{dbx_wins}</strong>. 
            {close} queries are within 5% (too close to call).
        </div>
        
        <h3>Performance by Query Category</h3>
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th style="text-align:left;">Category</th>
                        <th style="text-align:right;">Total</th>
                        <th style="text-align:right;">SF Wins</th>
                        <th style="text-align:right;">DBX Wins</th>
                        <th style="text-align:right;">Close</th>
                        <th style="text-align:right;">Avg SF Advantage</th>
                        <th style="text-align:left;">Dominant</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(cat_rows)}
                </tbody>
            </table>
        </div>
        
        <h3>Speed Advantage Chart</h3>
        <div class="chart-container" style="height:400px;">
            <canvas id="h2hChart"></canvas>
        </div>
        
        <h3>Full Query Comparison</h3>
        <p>Sorted by SF speed advantage (biggest wins first). Includes scaling factor ({scaling_range or 'N/A'}).</p>
        <div class="table-container" style="max-height:500px;overflow-y:auto;">
            <table>
                <thead style="position:sticky;top:0;background:white;">
                    <tr>
                        <th style="text-align:left;">Query</th>
                        <th style="text-align:left;">Category</th>
                        <th style="text-align:right;">SF {size} (s)</th>
                        <th style="text-align:right;">DBX {size} (s)</th>
                        <th style="text-align:right;">Speed Adv</th>
                        <th style="text-align:center;">Faster</th>
                        <th style="text-align:right;">SF Scale</th>
                        <th style="text-align:right;">DBX Scale</th>
                        <th style="text-align:center;">Scales</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(query_rows)}
                </tbody>
            </table>
        </div>
        
        <script>
            // Head-to-Head Butterfly Chart
            const h2hData = {chart_data};
            
            new Chart(document.getElementById("h2hChart"), {{
                type: "bar",
                data: {{
                    labels: h2hData.map(d => d.query),
                    datasets: [{{
                        label: "SF Advantage %",
                        data: h2hData.map(d => d.diff),
                        backgroundColor: h2hData.map(d => d.diff > 5 ? "#29b5e8" : d.diff < -5 ? "#ff6b35" : "#ccc"),
                        borderWidth: 0
                    }}]
                }},
                options: {{
                    indexAxis: "y",
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{ display: false }},
                        tooltip: {{
                            callbacks: {{
                                label: ctx => {{
                                    const val = ctx.raw;
                                    return val > 0 ? `SF ${{val.toFixed(1)}}% faster` : `DBX ${{Math.abs(val).toFixed(1)}}% faster`;
                                }}
                            }}
                        }}
                    }},
                    scales: {{
                        x: {{
                            title: {{ display: true, text: "SF Advantage %" }},
                            grid: {{ color: "#eee" }}
                        }},
                        y: {{
                            ticks: {{ font: {{ size: 9 }} }}
                        }}
                    }}
                }}
            }});
        </script>
        
        {scaling_section}
    '''


def build_sf_stats_for_edition(sf_data: Dict, all_queries: List[str], credit_rate: float) -> Dict:
    """Build SF stats for a specific edition (SE or EE)."""
    sf_stats = {}
    for size in sf_data.keys():
        times = sf_data[size]['times']
        values = [times.get(q) for q in all_queries if times.get(q)]
        total = calc_total(values)
        geomean = calc_geomean(values)
        cost = calc_sf_cost(total, size, credit_rate)
        hourly_rate = calc_sf_hourly_rate(size, credit_rate)
        sf_stats[size] = {
            'total': total, 'geomean': geomean, 'cost': cost,
            'hourly_rate': hourly_rate, 'count': len(values),
            'price_perf': round(cost * geomean, 1)
        }
    return sf_stats


def build_edition_price_tiers(sf_stats: Dict, dbx_stats: Dict, num_tiers: int = 4) -> List[Dict]:
    """
    Build budget tiers using log-scale within the overlapping price range.
    
    UNBIASED APPROACH:
    1. Find overlapping range where BOTH vendors can compete
    2. Create log-spaced budget centers within that range (mathematical, not vendor-derived)
    3. Neither vendor's specific pricing determines tier boundaries
    4. Use wide enough ranges to ensure configs fall within tiers
    """
    import numpy as np
    
    # Get each vendor's price range
    sf_rates = sorted([s['hourly_rate'] for s in sf_stats.values() if s.get('hourly_rate')])
    dbx_rates = sorted([s['hourly_rate'] for s in dbx_stats.values() if s.get('hourly_rate')])
    
    if not sf_rates or not dbx_rates:
        return []
    
    # Overlapping range where both vendors can compete
    min_budget = max(min(sf_rates), min(dbx_rates))
    max_budget = min(max(sf_rates), max(dbx_rates))
    
    if min_budget >= max_budget:
        min_budget = min(min(sf_rates), min(dbx_rates))
        max_budget = max(max(sf_rates), max(dbx_rates))
    
    # Create log-spaced budget centers
    budget_centers = np.geomspace(min_budget, max_budget, num_tiers)
    
    # Round to nice numbers
    def round_to_nice(x):
        if x < 10:
            return round(x)
        elif x < 100:
            return round(x / 5) * 5
        else:
            return round(x / 10) * 10
    
    # Build non-overlapping tier ranges that span from one center to the next
    tiers = []
    for i, center in enumerate(budget_centers):
        if i == 0:
            # First tier: from 0 to midpoint between this and next center
            low = 0
            high = (center + budget_centers[i+1]) / 2 if i+1 < len(budget_centers) else center * 1.5
        elif i == len(budget_centers) - 1:
            # Last tier: from midpoint with previous to infinity
            low = (budget_centers[i-1] + center) / 2
            high = center * 1.5
        else:
            # Middle tiers: from midpoint with previous to midpoint with next
            low = (budget_centers[i-1] + center) / 2
            high = (center + budget_centers[i+1]) / 2
        
        low_nice = round_to_nice(low) if low > 0 else 0
        high_nice = round_to_nice(high)
        
        tiers.append({
            'label': f'~${low_nice}-{high_nice}/hr',
            'min': low_nice,
            'max': high_nice
        })
    
    return tiers[:num_tiers]


def build_tier_comparisons_for_edition(sf_data: Dict, dbx_data: Dict, sf_stats: Dict, dbx_stats: Dict, credit_rate: float) -> List[Dict]:
    """Build price tier comparisons for a specific edition."""
    price_tiers = build_edition_price_tiers(sf_stats, dbx_stats, num_tiers=4)
    tier_comparisons = []
    categories = ['Reporting', 'Ad-hoc', 'OLAP', 'Data Mining']
    
    for tier in price_tiers:
        sf_size, sf_tier_stats = find_best_config_for_tier(sf_stats, tier)
        dbx_size, dbx_tier_stats = find_best_config_for_tier(dbx_stats, tier)
        if sf_tier_stats and dbx_tier_stats and sf_tier_stats['geomean'] > 0 and dbx_tier_stats['geomean'] > 0:
            winner = 'SF' if sf_tier_stats['geomean'] < dbx_tier_stats['geomean'] else 'DBX'
            ratio = round(dbx_tier_stats['geomean'] / sf_tier_stats['geomean'], 2) if winner == 'SF' else round(sf_tier_stats['geomean'] / dbx_tier_stats['geomean'], 2)
            
            # Calculate per-category breakdowns
            sf_times = sf_data[sf_size]['times']
            dbx_times = dbx_data[dbx_size]['times']
            
            category_breakdown = []
            for cat in categories:
                sf_cat_geomean = calc_category_geomean(sf_times, cat)
                dbx_cat_geomean = calc_category_geomean(dbx_times, cat)
                sf_cat_total = calc_category_total(sf_times, cat)
                dbx_cat_total = calc_category_total(dbx_times, cat)
                
                if sf_cat_geomean > 0 and dbx_cat_geomean > 0:
                    cat_winner = 'SF' if sf_cat_geomean < dbx_cat_geomean else 'DBX'
                    cat_ratio = round(dbx_cat_geomean / sf_cat_geomean, 2) if cat_winner == 'SF' else round(sf_cat_geomean / dbx_cat_geomean, 2)
                else:
                    cat_winner = '-'
                    cat_ratio = 0
                
                category_breakdown.append({
                    'category': cat,
                    'count': len(QUERY_CLASSIFICATIONS.get(cat, [])),
                    'sf_geomean': sf_cat_geomean,
                    'sf_total': sf_cat_total,
                    'dbx_geomean': dbx_cat_geomean,
                    'dbx_total': dbx_cat_total,
                    'winner': cat_winner,
                    'ratio': cat_ratio
                })
            
            tier_comparisons.append({
                'tier': tier['label'],
                'sf_size': sf_size, 'sf_geomean': sf_tier_stats['geomean'], 'sf_total': sf_tier_stats['total'], 
                'sf_cost': sf_tier_stats['cost'], 'sf_hourly': sf_tier_stats['hourly_rate'],
                'dbx_size': dbx_size, 'dbx_geomean': dbx_tier_stats['geomean'], 'dbx_total': dbx_tier_stats['total'], 
                'dbx_cost': dbx_tier_stats['cost'], 'dbx_hourly': dbx_tier_stats['hourly_rate'],
                'winner': winner, 'ratio': ratio,
                'categories': category_breakdown
            })
    
    return tier_comparisons


def build_perf_tier_comparisons_for_edition(sf_data: Dict, dbx_data: Dict, sf_stats: Dict, dbx_stats: Dict) -> List[Dict]:
    """Build performance tier comparisons (anchor on latency SLA, compare cost)."""
    perf_tiers = build_performance_tiers(sf_stats, dbx_stats, num_tiers=4)
    perf_tier_comparisons = []
    categories = list(QUERY_CLASSIFICATIONS.keys())
    
    for perf_tier in perf_tiers:
        sla_target = perf_tier['target']
        sf_size, sf_perf_stats = find_cheapest_config_for_sla(sf_stats, sla_target)
        dbx_size, dbx_perf_stats = find_cheapest_config_for_sla(dbx_stats, sla_target)
        
        # Handle cases where one or both vendors can meet the SLA
        if sf_perf_stats and dbx_perf_stats:
            # Both can meet SLA - compare costs
            if sf_perf_stats['hourly_rate'] < dbx_perf_stats['hourly_rate']:
                winner = 'SF'
                savings = round((1 - sf_perf_stats['hourly_rate'] / dbx_perf_stats['hourly_rate']) * 100)
            else:
                winner = 'DBX'
                savings = round((1 - dbx_perf_stats['hourly_rate'] / sf_perf_stats['hourly_rate']) * 100)
            
            # Calculate per-category breakdowns
            sf_times = sf_data[sf_size]['times']
            dbx_times = dbx_data[dbx_size]['times']
            
            category_breakdown = []
            for cat in categories:
                sf_cat_geomean = calc_category_geomean(sf_times, cat)
                dbx_cat_geomean = calc_category_geomean(dbx_times, cat)
                sf_cat_total = calc_category_total(sf_times, cat)
                dbx_cat_total = calc_category_total(dbx_times, cat)
                
                if sf_cat_geomean > 0 and dbx_cat_geomean > 0:
                    cat_winner = 'SF' if sf_cat_geomean < dbx_cat_geomean else 'DBX'
                    cat_ratio = round(dbx_cat_geomean / sf_cat_geomean, 2) if cat_winner == 'SF' else round(sf_cat_geomean / dbx_cat_geomean, 2)
                else:
                    cat_winner = '-'
                    cat_ratio = 0
                
                category_breakdown.append({
                    'category': cat,
                    'count': len(QUERY_CLASSIFICATIONS.get(cat, [])),
                    'sf_geomean': sf_cat_geomean,
                    'sf_total': sf_cat_total,
                    'dbx_geomean': dbx_cat_geomean,
                    'dbx_total': dbx_cat_total,
                    'winner': cat_winner,
                    'ratio': cat_ratio
                })
            
            perf_tier_comparisons.append({
                'tier': perf_tier['label'],
                'sf_size': sf_size, 'sf_geomean': sf_perf_stats['geomean'], 'sf_hourly': sf_perf_stats['hourly_rate'],
                'dbx_size': dbx_size, 'dbx_geomean': dbx_perf_stats['geomean'], 'dbx_hourly': dbx_perf_stats['hourly_rate'],
                'winner': winner, 'savings': savings,
                'categories': category_breakdown
            })
        elif sf_perf_stats and not dbx_perf_stats:
            # Only SF can meet this SLA - capability gap (show SF-only category data)
            sf_times = sf_data[sf_size]['times']
            category_breakdown = []
            for cat in categories:
                sf_cat_geomean = calc_category_geomean(sf_times, cat)
                sf_cat_total = calc_category_total(sf_times, cat)
                category_breakdown.append({
                    'category': cat,
                    'count': len(QUERY_CLASSIFICATIONS.get(cat, [])),
                    'sf_geomean': sf_cat_geomean,
                    'sf_total': sf_cat_total,
                    'dbx_geomean': 0,
                    'dbx_total': 0,
                    'winner': 'SF',
                    'ratio': 0
                })
            
            perf_tier_comparisons.append({
                'tier': perf_tier['label'],
                'sf_size': sf_size, 'sf_geomean': sf_perf_stats['geomean'], 'sf_hourly': sf_perf_stats['hourly_rate'],
                'dbx_size': '—', 'dbx_geomean': 0, 'dbx_hourly': 0,
                'winner': 'SF', 'savings': 100,  # 100% advantage = DBX can't compete
                'capability_gap': True,
                'categories': category_breakdown
            })
        elif dbx_perf_stats and not sf_perf_stats:
            # Only DBX can meet this SLA - capability gap (show DBX-only category data)
            dbx_times = dbx_data[dbx_size]['times']
            category_breakdown = []
            for cat in categories:
                dbx_cat_geomean = calc_category_geomean(dbx_times, cat)
                dbx_cat_total = calc_category_total(dbx_times, cat)
                category_breakdown.append({
                    'category': cat,
                    'count': len(QUERY_CLASSIFICATIONS.get(cat, [])),
                    'sf_geomean': 0,
                    'sf_total': 0,
                    'dbx_geomean': dbx_cat_geomean,
                    'dbx_total': dbx_cat_total,
                    'winner': 'DBX',
                    'ratio': 0
                })
            
            perf_tier_comparisons.append({
                'tier': perf_tier['label'],
                'sf_size': '—', 'sf_geomean': 0, 'sf_hourly': 0,
                'dbx_size': dbx_size, 'dbx_geomean': dbx_perf_stats['geomean'], 'dbx_hourly': dbx_perf_stats['hourly_rate'],
                'winner': 'DBX', 'savings': -100,
                'capability_gap': True,
                'categories': category_breakdown
            })
    
    return perf_tier_comparisons


def calculate_okr_metrics(tier_comparisons: List[Dict], perf_tier_comparisons: List[Dict], sf_stats: Dict, dbx_stats: Dict) -> Dict:
    """Calculate OKR metrics for price:performance advantage using both anchors."""
    
    target = 35  # OKR target is 35%
    
    # === COST ANCHOR: At same budget, who's faster? ===
    # Price:perf score = cost × geomean (lower is better)
    cost_tier_advantages = []
    for t in tier_comparisons:
        sf_score = t['sf_cost'] * t['sf_geomean']
        dbx_score = t['dbx_cost'] * t['dbx_geomean']
        advantage = round((1 - sf_score / dbx_score) * 100, 1) if dbx_score > 0 else 0
        cost_tier_advantages.append({
            'tier': t['tier'],
            'sf_score': round(sf_score, 1),
            'dbx_score': round(dbx_score, 1),
            'advantage': advantage,
            'sf_size': t['sf_size'],
            'dbx_size': t['dbx_size'],
            'sf_hourly': t.get('sf_hourly', 0),
            'dbx_hourly': t.get('dbx_hourly', 0),
            'sf_geomean': t['sf_geomean'],
            'dbx_geomean': t['dbx_geomean']
        })
    
    cost_avg = round(sum(t['advantage'] for t in cost_tier_advantages) / len(cost_tier_advantages), 1) if cost_tier_advantages else 0
    cost_weakest = min(cost_tier_advantages, key=lambda x: x['advantage']) if cost_tier_advantages else None
    cost_meeting = sum(1 for t in cost_tier_advantages if t['advantage'] >= target)
    
    # === PERF ANCHOR: At same SLA, who's cheaper? ===
    # Advantage = cost savings percentage
    perf_tier_advantages = []
    for p in perf_tier_comparisons:
        if p['winner'] == 'SF':
            advantage = p['savings']
        else:
            advantage = -p['savings']
        perf_tier_advantages.append({
            'tier': p['tier'],
            'advantage': advantage,
            'sf_size': p['sf_size'],
            'dbx_size': p['dbx_size'],
            'sf_hourly': p['sf_hourly'],
            'dbx_hourly': p['dbx_hourly'],
            'sf_geomean': p['sf_geomean'],
            'dbx_geomean': p['dbx_geomean']
        })
    
    perf_avg = round(sum(t['advantage'] for t in perf_tier_advantages) / len(perf_tier_advantages), 1) if perf_tier_advantages else 0
    perf_weakest = min(perf_tier_advantages, key=lambda x: x['advantage']) if perf_tier_advantages else None
    perf_meeting = sum(1 for t in perf_tier_advantages if t['advantage'] >= target)
    
    def get_grade(avg, target):
        """
        Standard OKR scoring: 0-1 scale based on % of target achieved.
        Green: ≥90% of target
        Yellow: 70-90% of target
        Red: <70% of target
        """
        score = min(avg / target, 1.0) if target > 0 else 0  # Cap at 1.0
        pct_of_target = score * 100
        
        if score >= 0.9:
            return f'🟢 {pct_of_target:.0f}%', 'okr-green', score
        elif score >= 0.7:
            return f'🟡 {pct_of_target:.0f}%', 'okr-yellow', score
        else:
            return f'🔴 {pct_of_target:.0f}%', 'okr-red', score
    
    cost_grade, cost_class, cost_score = get_grade(cost_avg, target)
    perf_grade, perf_class, perf_score = get_grade(perf_avg, target)
    
    return {
        'target': target,
        # Cost anchor metrics
        'cost_average': cost_avg,
        'cost_grade': cost_grade,
        'cost_grade_class': cost_class,
        'cost_tier_advantages': cost_tier_advantages,
        'cost_weakest': cost_weakest,
        'cost_meeting': cost_meeting,
        'cost_total': len(cost_tier_advantages),
        # Perf anchor metrics  
        'perf_average': perf_avg,
        'perf_grade': perf_grade,
        'perf_grade_class': perf_class,
        'perf_tier_advantages': perf_tier_advantages,
        'perf_weakest': perf_weakest,
        'perf_meeting': perf_meeting,
        'perf_total': len(perf_tier_advantages),
    }


def generate_okr_scorecard_html(okr: Dict, edition: str, credit_rate: float) -> str:
    """Generate the OKR scorecard HTML section with both scoring methods."""
    
    target = okr['target']
    
    # Calculate SF hourly rate range for this edition
    sf_rates = [credits * credit_rate for credits in SF_CREDITS_PER_HOUR_GEN2.values()]
    sf_min_rate = min(sf_rates)
    sf_max_rate = max(sf_rates)
    
    # === COST ANCHOR TABLE ===
    cost_rows = ""
    target = okr['target']
    for t in okr['cost_tier_advantages']:
        # OKR scoring: % of target achieved
        score = t['advantage'] / target if target > 0 else 0
        if score >= 0.9:
            icon = '🟢'
            row_class = 'okr-row-green'
        elif score >= 0.7:
            icon = '🟡'
            row_class = 'okr-row-yellow'
        else:
            icon = '🔴'
            row_class = 'okr-row-red'
        
        cost_rows += f'''
            <tr class="{row_class}">
                <td>{t['tier']}</td>
                <td>SF {t['sf_size']} ({t['sf_geomean']}s)</td>
                <td>DBX {t['dbx_size']} ({t['dbx_geomean']}s)</td>
                <td style="text-align:right;">{int(t['sf_score'])}</td>
                <td style="text-align:right;">{int(t['dbx_score'])}</td>
                <td style="text-align:right;font-weight:700;">{t['advantage']:.0f}%</td>
                <td style="text-align:center;">{icon}</td>
            </tr>'''
    
    # === PERF ANCHOR TABLE ===
    perf_rows = ""
    for t in okr['perf_tier_advantages']:
        # OKR scoring: % of target achieved
        score = t['advantage'] / target if target > 0 else 0
        if score >= 0.9:
            icon = '🟢'
            row_class = 'okr-row-green'
        elif score >= 0.7:
            icon = '🟡'
            row_class = 'okr-row-yellow'
        else:
            icon = '🔴'
            row_class = 'okr-row-red'
        
        perf_rows += f'''
            <tr class="{row_class}">
                <td>{t['tier']}</td>
                <td>SF {t['sf_size']} (${t['sf_hourly']:.0f}/hr)</td>
                <td>DBX {t['dbx_size']} (${t['dbx_hourly']:.0f}/hr)</td>
                <td style="text-align:right;font-weight:700;">{t['advantage']:.0f}%</td>
                <td style="text-align:center;">{icon}</td>
            </tr>'''
    
    # === WHAT IF: DBX 20% FASTER - COST ANCHOR ===
    # If DBX is 20% faster:
    # - Geomean drops to 0.8x
    # - Runtime drops to 0.8x (queries finish faster)
    # - Cost drops to 0.8x (pay for less compute time)
    # - Score (Cost × Geomean) drops to 0.64x (0.8 × 0.8)
    # This is a 36% improvement in their score!
    
    whatif_cost_rows = ""
    whatif_cost_meeting = 0
    
    for t in okr['cost_tier_advantages']:
        sf_score = t['sf_score']
        orig_dbx_score = t['dbx_score']
        
        # DBX score improves by 36% (0.8 × 0.8 = 0.64)
        adjusted_dbx_score = orig_dbx_score * 0.64
        
        # Recalculate advantage
        new_advantage = round((1 - sf_score / adjusted_dbx_score) * 100, 1) if adjusted_dbx_score > 0 else 0
        
        # How much did we lose?
        advantage_delta = t['advantage'] - new_advantage
        
        # OKR scoring: % of target achieved
        okr_score = new_advantage / target if target > 0 else 0
        if okr_score >= 0.9:
            icon = '🟢'
            row_class = 'okr-row-green'
            whatif_cost_meeting += 1
        elif okr_score >= 0.7:
            icon = '🟡'
            row_class = 'okr-row-yellow'
        else:
            icon = '🔴'
            row_class = 'okr-row-red'
        
        whatif_cost_rows += f'''
            <tr class="{row_class}">
                <td>{t['tier']}</td>
                <td>SF {t['sf_size']} — {int(sf_score)}</td>
                <td>DBX {t['dbx_size']} — <s>{int(orig_dbx_score)}</s> → <strong>{int(adjusted_dbx_score)}</strong></td>
                <td style="text-align:right;"><s>{t['advantage']:.0f}%</s></td>
                <td style="text-align:right;font-weight:700;">{new_advantage:.0f}%</td>
                <td style="text-align:right;color:#c62828;">−{advantage_delta:.0f}pp</td>
                <td style="text-align:center;">{icon}</td>
            </tr>'''
    
    # === WHAT IF: DBX 20% FASTER - PERF ANCHOR ===
    # For Perf Anchor, if DBX is 20% faster:
    # - Their geomean drops by 20%
    # - They complete in 80% of the time at the same hourly rate
    # - So their effective cost = hourly_rate × 0.8 (for same workload)
    # - This means their "score" (cost × geomean) also drops to 0.64×
    # Same math as Cost Anchor!
    
    whatif_perf_rows = ""
    whatif_perf_meeting = 0
    
    for t in okr['perf_tier_advantages']:
        sf_hourly = t['sf_hourly']
        sf_size = t['sf_size']
        sf_geomean = t['sf_geomean']
        orig_dbx_hourly = t['dbx_hourly']
        orig_dbx_size = t['dbx_size']
        orig_dbx_geomean = t['dbx_geomean']
        orig_advantage = t['advantage']
        
        # Calculate scores (cost × geomean proxy for total cost-effectiveness)
        sf_score = sf_hourly * sf_geomean if sf_hourly > 0 and sf_geomean > 0 else 0
        orig_dbx_score = orig_dbx_hourly * orig_dbx_geomean if orig_dbx_hourly > 0 and orig_dbx_geomean > 0 else 0
        
        # DBX adjusted: 20% faster means score drops to 0.64× (same as cost anchor)
        # Because: new_score = hourly × (0.8 × runtime) AND geomean drops 0.8×
        # Effective score = hourly × 0.8 × geomean × 0.8 = 0.64 × original
        adjusted_dbx_score = orig_dbx_score * 0.64
        adjusted_dbx_geomean = orig_dbx_geomean * 0.8 if orig_dbx_geomean > 0 else 0
        
        # Parse SLA from tier label
        tier_str = t['tier'].replace('≤', '').replace('s SLA', '').replace('s', '').strip()
        try:
            sla = float(tier_str)
        except ValueError:
            sla = 999
        
        if orig_dbx_hourly > 0 and sf_score > 0 and adjusted_dbx_score > 0:
            # Both can meet SLA - recalculate advantage using scores
            new_advantage = round((1 - sf_score / adjusted_dbx_score) * 100, 1)
            status_note = f"{adjusted_dbx_geomean:.1f}s"
            dbx_cell = f"DBX {orig_dbx_size} — <s>{int(orig_dbx_score)}</s> → <strong>{int(adjusted_dbx_score)}</strong>"
        elif adjusted_dbx_geomean <= sla and adjusted_dbx_geomean > 0:
            # DBX can NOW meet this SLA with 20% improvement!
            # Find cheapest DBX config that would qualify
            best_dbx_score = 0
            best_dbx_size = "?"
            for check_t in okr['perf_tier_advantages']:
                if check_t['dbx_geomean'] > 0 and (check_t['dbx_geomean'] * 0.8) <= sla:
                    check_score = check_t['dbx_hourly'] * check_t['dbx_geomean'] * 0.64
                    if best_dbx_score == 0 or check_score < best_dbx_score:
                        best_dbx_score = check_score
                        best_dbx_size = check_t['dbx_size']
            
            if best_dbx_score > 0 and sf_score > 0:
                new_advantage = round((1 - sf_score / best_dbx_score) * 100, 1)
                dbx_cell = f"DBX {best_dbx_size} — <strong>{int(best_dbx_score)}</strong> <span style='color:#d84315;font-weight:600;'>NOW qualifies!</span>"
            else:
                new_advantage = 100
                dbx_cell = "<em>still N/A</em>"
        else:
            # DBX still can't meet SLA
            new_advantage = 100
            dbx_cell = "<em>still N/A</em>"
        
        # How much did we lose?
        advantage_delta = orig_advantage - new_advantage
        
        # OKR scoring
        okr_score = new_advantage / target if target > 0 else 0
        if okr_score >= 0.9:
            icon = '🟢'
            row_class = 'okr-row-green'
            whatif_perf_meeting += 1
        elif okr_score >= 0.7:
            icon = '🟡'
            row_class = 'okr-row-yellow'
        else:
            icon = '🔴'
            row_class = 'okr-row-red'
        
        # Format advantage change
        if advantage_delta > 0:
            delta_cell = f"<span style='color:#c62828;'>−{advantage_delta:.0f}pp</span>"
        elif advantage_delta < 0:
            delta_cell = f"<span style='color:#2e7d32;'>+{-advantage_delta:.0f}pp</span>"
        else:
            delta_cell = "—"
        
        # Format SF cell with score
        sf_cell = f"SF {sf_size} — {int(sf_score)}" if sf_score > 0 else f"SF {sf_size}"
        
        whatif_perf_rows += f'''
            <tr class="{row_class}">
                <td>{t['tier']}</td>
                <td>{sf_cell}</td>
                <td>{dbx_cell}</td>
                <td style="text-align:right;"><s>{orig_advantage:.0f}%</s></td>
                <td style="text-align:right;font-weight:700;">{new_advantage:.0f}%</td>
                <td style="text-align:right;">{delta_cell}</td>
                <td style="text-align:center;">{icon}</td>
            </tr>'''
    
    # Calculate OKR grades for each section based on % of tiers meeting target
    def get_section_grade(meeting, total):
        if total == 0:
            return '🔴', 0
        pct = meeting / total
        if pct >= 0.9:
            return '🟢', pct * 100
        elif pct >= 0.7:
            return '🟡', pct * 100
        else:
            return '🔴', pct * 100
    
    cost_grade_icon, cost_grade_pct = get_section_grade(okr['cost_meeting'], okr['cost_total'])
    perf_grade_icon, perf_grade_pct = get_section_grade(okr['perf_meeting'], okr['perf_total'])
    whatif_cost_grade_icon, whatif_cost_grade_pct = get_section_grade(whatif_cost_meeting, okr['cost_total'])
    whatif_perf_grade_icon, whatif_perf_grade_pct = get_section_grade(whatif_perf_meeting, okr['perf_total'])
    
    return f'''
        <div class="okr-scorecard">
            <h2>OKR Scorecard: 35% Price:Performance Advantage — {edition} (SF: ${sf_min_rate:.0f}–${sf_max_rate:.0f}/hr)</h2>
            
            <div class="okr-explanation">
                <strong>Target:</strong> 35% advantage at each tier<br>
                <strong>OKR Scoring:</strong> 🟢 ≥90% of target (≥31.5%) | 🟡 70-90% (24.5-31.5%) | 🔴 &lt;70% (&lt;24.5%)<br>
                <strong>Cost Anchor:</strong> Score = Run Cost × Geomean. Advantage = (1 - SF/DBX) × 100%<br>
                <strong>Perf Anchor:</strong> At same latency SLA, how much cheaper is SF?
            </div>
            
            <details style="margin:15px 0;padding:10px;background:#f8f9fa;border-radius:6px;font-size:0.9em;">
                <summary style="cursor:pointer;font-weight:600;color:#0066cc;">ℹ️ How are tiers determined? (click to expand)</summary>
                <div style="margin-top:10px;padding:10px;background:white;border-radius:4px;">
                    <p><strong>Tier boundaries are vendor-neutral and mathematically derived:</strong></p>
                    <ul style="margin:10px 0;padding-left:20px;">
                        <li><strong>Budget Tiers:</strong> Log-spaced across the overlapping price range where both vendors have configs. 
                            Boundaries are midpoints between adjacent centers, ensuring complete coverage with no gaps.</li>
                        <li><strong>SLA Tiers:</strong> First tier starts just above the <em>fastest</em> config (rewards speed leadership).
                            Log-spaced from there to the slowest config. Shows capability gaps where only one vendor can compete.</li>
                    </ul>
                    <p style="margin-top:10px;"><strong>Why this is fair:</strong></p>
                    <ul style="margin:10px 0;padding-left:20px;">
                        <li>Tier boundaries come from <em>mathematical distribution</em>, not either vendor's specific config values</li>
                        <li>Log-scale spacing is natural for both cost and latency metrics</li>
                        <li>No t-shirt size assumptions — SF's L might compete with DBX's XL at a given tier</li>
                        <li>Each tier finds the <em>best qualifying config</em> from each vendor independently</li>
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
                                    <th class="dbx">DBX</th>
                                    <th>SF Score</th>
                                    <th class="dbx">DBX Score</th>
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
                        {cost_grade_icon} Meeting target: {okr['cost_meeting']}/{okr['cost_total']} tiers ({cost_grade_pct:.0f}%)
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
                                    <th>SF ($/hr)</th>
                                    <th class="dbx">DBX ($/hr)</th>
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
                        {perf_grade_icon} Meeting target: {okr['perf_meeting']}/{okr['perf_total']} tiers ({perf_grade_pct:.0f}%)
                    </div>
                </div>
            </div>
            
            <!-- What If: DBX 20% Faster -->
            <div style="margin-top:30px;padding:20px;background:#fff3e0;border-radius:8px;border:1px solid #ffb74d;">
                <h3 style="margin-top:0;color:#e65100;">🔮 What If: DBX Were 20% Faster?</h3>
                <p style="font-size:0.9em;color:#666;margin-bottom:15px;">
                    Sensitivity analysis: If Databricks improved all query latencies by 20%, how would our OKR standing change?
                </p>
                
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">
                    <!-- Cost Anchor What If -->
                    <div>
                        <h4 style="margin-top:0;">Cost Anchor Impact</h4>
                        <p style="font-size:0.85em;color:#666;margin-bottom:10px;">
                            DBX Score improves by <strong>36%</strong> (0.8 cost × 0.8 geomean = 0.64)
                        </p>
                        <div class="table-container">
                            <table>
                                <thead>
                                    <tr>
                                        <th style="text-align:left;">Budget Tier</th>
                                        <th>SF Score</th>
                                        <th class="dbx">DBX Score</th>
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
                            {whatif_cost_grade_icon} Green tiers after: {whatif_cost_meeting}/{okr['cost_total']} ({whatif_cost_grade_pct:.0f}%)
                        </div>
                    </div>
                    
                    <!-- Perf Anchor What If -->
                    <div>
                        <h4 style="margin-top:0;">Perf Anchor Impact</h4>
                        <p style="font-size:0.85em;color:#666;margin-bottom:10px;">
                            DBX Score improves by <strong>36%</strong> (same math: 0.8 runtime × 0.8 geomean)
                        </p>
                        <div class="table-container">
                            <table>
                                <thead>
                                    <tr>
                                        <th style="text-align:left;">Latency SLA</th>
                                        <th>SF Score</th>
                                        <th class="dbx">DBX Score</th>
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
                            {whatif_perf_grade_icon} Green tiers after: {whatif_perf_meeting}/{okr['perf_total']} ({whatif_perf_grade_pct:.0f}%)
                        </div>
                    </div>
                </div>
            </div>
        </div>
    '''


def generate_edition_tab_html(tab_id: str, edition: str, credit_rate: float, sf_data: Dict, dbx_data: Dict, 
                              sf_stats: Dict, dbx_stats: Dict, tier_comparisons: List[Dict], 
                              perf_tier_comparisons: List[Dict]) -> str:
    """Generate a complete edition analysis tab (SE or EE)."""
    
    # Calculate OKR metrics
    okr = calculate_okr_metrics(tier_comparisons, perf_tier_comparisons, sf_stats, dbx_stats)
    
    # Generate OKR scorecard
    okr_html = generate_okr_scorecard_html(okr, edition, credit_rate)
    
    # Generate price tier comparison rows
    comparison_overall_rows = ""
    for t in tier_comparisons:
        winner_class = 'sf-winner' if t['winner'] == 'SF' else 'dbx-winner'
        comparison_overall_rows += f'''
            <tr>
                <td>{t['tier']}</td>
                <td class="sf-col">{t['sf_size']} (${t['sf_hourly']:.0f}/hr)</td>
                <td class="sf-col">{int(t['sf_total']):,}s</td>
                <td class="sf-col">{t['sf_geomean']}s</td>
                <td class="dbx-col">{t['dbx_size']} (${t['dbx_hourly']:.0f}/hr)</td>
                <td class="dbx-col">{int(t['dbx_total']):,}s</td>
                <td class="dbx-col">{t['dbx_geomean']}s</td>
                <td class="{winner_class}">{t['winner']} {t['ratio']}x</td>
            </tr>'''
    
    # Generate category breakdown sections for price tiers
    comparison_category_sections = ""
    for t in tier_comparisons:
        category_rows = ""
        for c in t['categories']:
            if c['winner'] == 'SF':
                winner_class = 'sf-winner'
            elif c['winner'] == 'DBX':
                winner_class = 'dbx-winner'
            else:
                winner_class = ''
            category_rows += f'''
                <tr>
                    <td><strong>{c['category']}</strong></td>
                    <td style="text-align:right;">{c['count']}</td>
                    <td class="sf-col">{c['sf_geomean']}s</td>
                    <td class="sf-col">{int(c['sf_total'])}s</td>
                    <td class="dbx-col">{c['dbx_geomean']}s</td>
                    <td class="dbx-col">{int(c['dbx_total'])}s</td>
                    <td class="{winner_class}">{c['winner']} {c['ratio']}x</td>
                </tr>'''
        
        comparison_category_sections += f'''
        <h3 style="margin-top:25px;color:var(--sf-dark-blue);">{t['tier']} — SF {t['sf_size']} @ ${t['sf_hourly']:.0f}/hr vs DBX {t['dbx_size']} @ ${t['dbx_hourly']:.0f}/hr</h3>
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th style="text-align:left;">Category</th>
                        <th style="text-align:right;">Queries</th>
                        <th>SF Geomean</th>
                        <th>SF Total</th>
                        <th class="dbx">DBX Geomean</th>
                        <th class="dbx">DBX Total</th>
                        <th>Winner</th>
                    </tr>
                </thead>
                <tbody>
                    {category_rows}
                </tbody>
            </table>
        </div>'''
    
    # Generate performance tier comparison rows
    perf_tier_rows = ""
    for p in perf_tier_comparisons:
        winner_class = 'sf-winner' if p['winner'] == 'SF' else 'dbx-winner'
        # Handle capability gaps - show "N/A" instead of $0/hr
        sf_hourly_str = f"${p['sf_hourly']:.0f}/hr" if p['sf_hourly'] > 0 else "N/A"
        dbx_hourly_str = f"${p['dbx_hourly']:.0f}/hr" if p['dbx_hourly'] > 0 else "N/A"
        sf_geomean_str = f"{p['sf_geomean']}s" if p['sf_geomean'] > 0 else "—"
        dbx_geomean_str = f"{p['dbx_geomean']}s" if p['dbx_geomean'] > 0 else "—"
        savings_str = f"{p['winner']} saves {p['savings']}%" if p['savings'] < 100 else "SF only option"
        
        perf_tier_rows += f'''
            <tr>
                <td><strong>{p['tier']}</strong></td>
                <td class="sf-col">{p['sf_size']}</td>
                <td class="sf-col">{sf_geomean_str}</td>
                <td class="sf-col">{sf_hourly_str}</td>
                <td class="dbx-col">{p['dbx_size']}</td>
                <td class="dbx-col">{dbx_geomean_str}</td>
                <td class="dbx-col">{dbx_hourly_str}</td>
                <td class="{winner_class}">{savings_str}</td>
            </tr>'''
    
    # Generate performance tier category breakdown sections
    perf_category_sections = ""
    for p in perf_tier_comparisons:
        category_rows = ""
        for c in p.get('categories', []):
            winner_class = 'sf-winner' if c['winner'] == 'SF' else 'dbx-winner' if c['winner'] == 'DBX' else ''
            # Handle capability gaps in category data
            sf_geomean_str = f"{c['sf_geomean']}s" if c['sf_geomean'] > 0 else "—"
            dbx_geomean_str = f"{c['dbx_geomean']}s" if c['dbx_geomean'] > 0 else "—"
            sf_total_str = f"{int(c['sf_total'])}s" if c['sf_total'] > 0 else "—"
            dbx_total_str = f"{int(c['dbx_total'])}s" if c['dbx_total'] > 0 else "—"
            ratio_str = f"{c['ratio']}x" if c['ratio'] > 0 else ""
            
            category_rows += f'''
                <tr>
                    <td><strong>{c['category']}</strong></td>
                    <td style="text-align:right;">{c['count']}</td>
                    <td class="sf-col">{sf_geomean_str}</td>
                    <td class="sf-col">{sf_total_str}</td>
                    <td class="dbx-col">{dbx_geomean_str}</td>
                    <td class="dbx-col">{dbx_total_str}</td>
                    <td class="{winner_class}">{c['winner']} {ratio_str}</td>
                </tr>'''
        
        perf_category_sections += f'''
        <h3 style="margin-top:25px;color:var(--sf-dark-blue);">{p['tier']} — SF {p['sf_size']} @ ${p['sf_hourly']:.0f}/hr vs DBX {p['dbx_size']} @ ${p['dbx_hourly']:.0f}/hr</h3>''' if p['dbx_hourly'] > 0 else f'''
        <h3 style="margin-top:25px;color:var(--sf-dark-blue);">{p['tier']} — SF {p['sf_size']} @ ${p['sf_hourly']:.0f}/hr vs DBX: <em>Can't meet SLA</em></h3>'''
        perf_category_sections += f'''
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th style="text-align:left;">Category</th>
                        <th style="text-align:right;">Queries</th>
                        <th>SF Geomean</th>
                        <th>SF Total</th>
                        <th class="dbx">DBX Geomean</th>
                        <th class="dbx">DBX Total</th>
                        <th>Faster</th>
                    </tr>
                </thead>
                <tbody>
                    {category_rows}
                </tbody>
            </table>
        </div>'''
    
    return f'''
    <div id="{tab_id}" class="tab-content">
        {okr_html}
        
        <div class="insight-box" style="background:#e8f4fc;border-color:var(--sf-blue);margin-top:30px;">
            <strong>📊 {edition} @ ${credit_rate:.2f}/credit</strong> — See <a href="#" onclick="showTab('frontier');return false;">Overview tab</a> for full pricing breakdown.
        </div>
        
        <h2 style="margin-top:30px;">Price Tier Comparison: At Each Budget, Who's Faster?</h2>
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th style="text-align:left;">Price Tier</th>
                        <th>SF Config</th>
                        <th>SF Total</th>
                        <th>SF Geomean</th>
                        <th class="dbx">DBX Config</th>
                        <th class="dbx">DBX Total</th>
                        <th class="dbx">DBX Geomean</th>
                        <th>Winner</th>
                    </tr>
                </thead>
                <tbody>
                    {comparison_overall_rows}
                </tbody>
            </table>
        </div>
        
        <h2>Price Tier Breakdown by Query Category</h2>
        {comparison_category_sections}
        
        <h2 style="margin-top:40px;">Performance Tier Comparison: To Hit This SLA, What's the Cheapest?</h2>
        <div class="insight-box">
            <strong>The flip side:</strong> Instead of asking "At this budget, who's faster?", 
            we now ask "To achieve this latency SLA, who's cheaper?"
        </div>
        
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th style="text-align:left;">Performance SLA</th>
                        <th>SF Size</th>
                        <th>SF Latency</th>
                        <th>SF Cost</th>
                        <th class="dbx">DBX Size</th>
                        <th class="dbx">DBX Latency</th>
                        <th class="dbx">DBX Cost</th>
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
    </div>
    '''


# =============================================================================
# HTML GENERATION
# =============================================================================

def compute_scaling_efficiency(platform_data: Dict, all_queries: List[str]) -> Dict[str, Dict]:
    """
    Compute scaling efficiency for each query across warehouse sizes.
    Uses log-log regression: T = c * N^beta. Efficiency = |beta| * 100% (capped at 100%).
    Works for both SF and DBX data.
    """
    sizes = list(platform_data.keys())
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
            t = platform_data[s]['times'].get(q)
            if t and t > 0:
                times.append(t)
                valid_mults.append(m)

        if len(times) < 2:
            results[q] = {'beta': None, 'efficiency': None, 'sparkline': [platform_data[s]['times'].get(q) for s in ordered]}
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
            'sparkline': [platform_data[s]['times'].get(q) for s in ordered]
        }

    return results


def generate_html(sf_data: Dict, dbx_data: Dict, output_path: str,
                  publish_date: Optional[str] = None):
    """Generate the complete HTML report."""
    
    sf_sizes = list(sf_data.keys())
    dbx_sizes = list(dbx_data.keys())
    
    # Get all queries
    all_queries = set()
    for size_data in sf_data.values():
        all_queries.update(size_data['times'].keys())
    for size_data in dbx_data.values():
        all_queries.update(size_data['times'].keys())
    all_queries = sorted(all_queries)
    
    # Calculate DBX stats (same for both editions)
    dbx_stats = {}
    for size in dbx_sizes:
        times = dbx_data[size]['times']
        values = [times.get(q) for q in all_queries if times.get(q)]
        total = calc_total(values)
        geomean = calc_geomean(values)
        cost = calc_dbx_cost(total, size)
        hourly_rate = calc_dbx_hourly_rate(size)
        dbx_stats[size] = {
            'total': total, 'geomean': geomean, 'cost': cost,
            'hourly_rate': hourly_rate, 'count': len(values),
            'price_perf': round(cost * geomean, 1)
        }
    
    # Calculate SF stats for BOTH editions
    sf_stats_se = build_sf_stats_for_edition(sf_data, all_queries, SF_CREDIT_RATE_SE)
    sf_stats_ee = build_sf_stats_for_edition(sf_data, all_queries, SF_CREDIT_RATE_EE)
    
    # Build tier comparisons for both editions
    tier_comparisons_se = build_tier_comparisons_for_edition(sf_data, dbx_data, sf_stats_se, dbx_stats, SF_CREDIT_RATE_SE)
    tier_comparisons_ee = build_tier_comparisons_for_edition(sf_data, dbx_data, sf_stats_ee, dbx_stats, SF_CREDIT_RATE_EE)
    
    # Build performance tier comparisons for both editions
    perf_tier_comparisons_se = build_perf_tier_comparisons_for_edition(sf_data, dbx_data, sf_stats_se, dbx_stats)
    perf_tier_comparisons_ee = build_perf_tier_comparisons_for_edition(sf_data, dbx_data, sf_stats_ee, dbx_stats)
    
    # Compute head-to-head query comparison for ALL common sizes (let user pick)
    common_sizes = set(sf_data.keys()) & set(dbx_data.keys())
    size_order = ['S', 'M', 'L', 'XL', '2XL', '3XL', '4XL']
    ordered_common_sizes = [s for s in size_order if s in common_sizes]
    
    h2h_by_size = {}
    for size in ordered_common_sizes:
        h2h = compute_head_to_head(
            sf_data[size]['times'],
            dbx_data[size]['times'],
            sf_data=sf_data,
            dbx_data=dbx_data
        )
        h2h['size'] = size
        h2h_by_size[size] = h2h
    
    # Default to XL for initial display (or largest common if no XL)
    default_h2h_size = 'XL' if 'XL' in ordered_common_sizes else (ordered_common_sizes[-1] if ordered_common_sizes else None)
    
    # Use SE stats for the overview tab (default)
    sf_stats = sf_stats_se
    tier_comparisons = tier_comparisons_se
    
    # Find best overall price:perf for each platform (using SE)
    sf_best_pp = min(sf_stats.items(), key=lambda x: x[1]['price_perf'])
    dbx_best_pp = min(dbx_stats.items(), key=lambda x: x[1]['price_perf'])
    
    # Find fastest for each platform
    sf_fastest = min(sf_stats.items(), key=lambda x: x[1]['total'])
    dbx_fastest = min(dbx_stats.items(), key=lambda x: x[1]['total'])
    
    # Generate HTML
    html = generate_full_html(
        sf_data=sf_data, dbx_data=dbx_data,
        sf_stats_se=sf_stats_se, sf_stats_ee=sf_stats_ee, dbx_stats=dbx_stats,
        sf_sizes=sf_sizes, dbx_sizes=dbx_sizes,
        all_queries=all_queries,
        sf_best_pp=sf_best_pp, dbx_best_pp=dbx_best_pp,
        sf_fastest=sf_fastest, dbx_fastest=dbx_fastest,
        tier_comparisons_se=tier_comparisons_se, tier_comparisons_ee=tier_comparisons_ee,
        perf_tier_comparisons_se=perf_tier_comparisons_se, perf_tier_comparisons_ee=perf_tier_comparisons_ee,
        h2h_by_size=h2h_by_size,
        h2h_sizes=ordered_common_sizes,
        default_h2h_size=default_h2h_size,
        publish_date=publish_date
    )
    
    with open(output_path, 'w') as f:
        f.write(html)
    
    print(f"Report generated: {output_path}")


def generate_full_html(**kwargs) -> str:
    """Generate the full HTML template."""
    
    sf_data = kwargs['sf_data']
    dbx_data = kwargs['dbx_data']
    sf_stats_se = kwargs['sf_stats_se']
    sf_stats_ee = kwargs['sf_stats_ee']
    dbx_stats = kwargs['dbx_stats']
    sf_sizes = kwargs['sf_sizes']
    dbx_sizes = kwargs['dbx_sizes']
    all_queries = kwargs['all_queries']
    sf_best_pp = kwargs['sf_best_pp']
    dbx_best_pp = kwargs['dbx_best_pp']
    sf_fastest = kwargs['sf_fastest']
    dbx_fastest = kwargs['dbx_fastest']
    tier_comparisons_se = kwargs['tier_comparisons_se']
    tier_comparisons_ee = kwargs['tier_comparisons_ee']
    perf_tier_comparisons_se = kwargs.get('perf_tier_comparisons_se', [])
    perf_tier_comparisons_ee = kwargs.get('perf_tier_comparisons_ee', [])
    h2h_by_size = kwargs.get('h2h_by_size', {})
    h2h_sizes = kwargs.get('h2h_sizes', [])
    default_h2h_size = kwargs.get('default_h2h_size', None)
    publish_date = kwargs.get('publish_date', None)
    
    # --- Publish badge ---
    publish_badge = ''
    publish_title_suffix = ''
    if publish_date:
        publish_badge = f'<span style="display:inline-block;background:#32963C;color:white;padding:4px 12px;border-radius:4px;font-size:0.85em;font-weight:600;margin-left:10px;vertical-align:middle;">Published {publish_date}</span>'
        publish_title_suffix = f' | Published {publish_date}'

    # --- Scaling efficiency (both platforms) ---
    sf_scaling = compute_scaling_efficiency(sf_data, all_queries)
    dbx_scaling = compute_scaling_efficiency(dbx_data, all_queries)

    sf_ordered_sizes = [s for s in SIZE_ORDER if s in sf_sizes]
    dbx_ordered_sizes = [s for s in SIZE_ORDER if s in dbx_sizes]

    # SF scaling summary
    sf_sorted_scaling = sorted(
        [(q, sf_scaling.get(q, {})) for q in all_queries if sf_scaling.get(q, {}).get('efficiency') is not None],
        key=lambda x: -(x[1].get('efficiency') or 0)
    )
    sf_efficiencies = [sc.get('efficiency') for _, sc in sf_sorted_scaling if sc.get('efficiency') is not None]
    sf_avg_eff = round(sum(sf_efficiencies) / len(sf_efficiencies), 1) if sf_efficiencies else 0
    sf_good = sum(1 for e in sf_efficiencies if e >= 70)
    sf_moderate = sum(1 for e in sf_efficiencies if 40 <= e < 70)
    sf_poor = sum(1 for e in sf_efficiencies if e < 40)

    # DBX scaling summary
    dbx_sorted_scaling = sorted(
        [(q, dbx_scaling.get(q, {})) for q in all_queries if dbx_scaling.get(q, {}).get('efficiency') is not None],
        key=lambda x: -(x[1].get('efficiency') or 0)
    )
    dbx_efficiencies = [sc.get('efficiency') for _, sc in dbx_sorted_scaling if sc.get('efficiency') is not None]
    dbx_avg_eff = round(sum(dbx_efficiencies) / len(dbx_efficiencies), 1) if dbx_efficiencies else 0
    dbx_good = sum(1 for e in dbx_efficiencies if e >= 70)
    dbx_moderate = sum(1 for e in dbx_efficiencies if 40 <= e < 70)
    dbx_poor = sum(1 for e in dbx_efficiencies if e < 40)

    # Combined scaling rows (sorted by SF efficiency)
    scaling_queries = sorted(
        [q for q in all_queries if sf_scaling.get(q, {}).get('efficiency') is not None or dbx_scaling.get(q, {}).get('efficiency') is not None],
        key=lambda q: -(sf_scaling.get(q, {}).get('efficiency') or 0)
    )

    def _make_sparkline(sparkline_data, color='#29B5E8'):
        valid_vals = [v for v in sparkline_data if v is not None and v > 0]
        if len(valid_vals) < 2:
            return ''
        max_v, min_v = max(valid_vals), min(valid_vals)
        rng = max_v - min_v if max_v > min_v else 1
        width, height = 80, 20
        points = []
        x_step = width / (len(valid_vals) - 1)
        for i, v in enumerate(valid_vals):
            x = i * x_step
            y = height - ((v - min_v) / rng * height)
            points.append(f'{x:.1f},{y:.1f}')
        polyline = ' '.join(points)
        return f'<svg width="{width}" height="{height}" style="vertical-align:middle;"><polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="1.5"/></svg>'

    def _eff_badge(eff):
        if eff is None:
            return '<span style="color:#999;">—</span>'
        if eff >= 70:
            color, badge = '#32963C', '🟢'
        elif eff >= 40:
            color, badge = '#CC7A00', '🟡'
        else:
            color, badge = '#CC3333', '🔴'
        return f'<span style="color:{color};font-weight:600;">{badge} {eff:.0f}%</span>'

    scaling_rows_html = ''
    for q in scaling_queries:
        sf_sc = sf_scaling.get(q, {})
        dbx_sc = dbx_scaling.get(q, {})
        sf_eff = sf_sc.get('efficiency')
        dbx_eff = dbx_sc.get('efficiency')

        category = 'Other'
        for cat, queries in QUERY_CLASSIFICATIONS.items():
            if q in queries:
                category = cat
                break

        sf_spark = _make_sparkline(sf_sc.get('sparkline', []), '#29B5E8')
        dbx_spark = _make_sparkline(dbx_sc.get('sparkline', []), '#FF9900')

        # Determine which platform scales better for this query
        winner_indicator = ''
        if sf_eff is not None and dbx_eff is not None:
            if sf_eff > dbx_eff + 5:
                winner_indicator = '<span style="color:#29B5E8;font-size:0.8em;" title="SF scales better">◀ SF</span>'
            elif dbx_eff > sf_eff + 5:
                winner_indicator = '<span style="color:#FF9900;font-size:0.8em;" title="DBX scales better">DBX ▶</span>'
            else:
                winner_indicator = '<span style="color:#888;font-size:0.8em;">≈</span>'

        scaling_rows_html += f'''<tr>
            <td><strong>{q}</strong></td>
            <td style="font-size:0.85em;color:#666;">{category}</td>
            <td style="text-align:center;">{sf_spark}</td>
            <td style="text-align:right;">{_eff_badge(sf_eff)}</td>
            <td style="text-align:center;">{dbx_spark}</td>
            <td style="text-align:right;">{_eff_badge(dbx_eff)}</td>
            <td style="text-align:center;">{winner_indicator}</td>
        </tr>'''

    # Count scaling wins
    sf_scales_better_count = sum(1 for q in scaling_queries
        if sf_scaling.get(q, {}).get('efficiency') is not None
        and dbx_scaling.get(q, {}).get('efficiency') is not None
        and (sf_scaling[q]['efficiency'] or 0) > (dbx_scaling[q]['efficiency'] or 0) + 5)
    dbx_scales_better_count = sum(1 for q in scaling_queries
        if sf_scaling.get(q, {}).get('efficiency') is not None
        and dbx_scaling.get(q, {}).get('efficiency') is not None
        and (dbx_scaling[q]['efficiency'] or 0) > (sf_scaling[q]['efficiency'] or 0) + 5)

    # --- Query reference rows ---
    query_ref_rows = ""
    for cat, queries in QUERY_CLASSIFICATIONS.items():
        for q in queries:
            desc = QUERY_DESCRIPTIONS.get(q, '')
            class_tag = cat.lower().replace(' ', '').replace('-', '')
            query_ref_rows += f'<tr><td>{q}</td><td style="text-align:left;">{desc}</td><td><span class="class-tag class-{class_tag}">{cat}</span></td></tr>\n'

    # --- Run metadata rows ---
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
    for size in dbx_sizes:
        md = dbx_data[size].get('metadata', {})
        run_date = md.get('run_date', '—')
        wh_type = md.get('wh_type', '—') or '—'
        data_fmt = md.get('data_format', '—') or '—'
        warm_q = md.get('warm_queries', '—')
        run_metadata_rows += f'''<tr>
            <td><span style="color:#FF9900;font-weight:600;">Databricks</span></td>
            <td><strong>{size}</strong></td>
            <td style="font-family:monospace;">{dbx_data[size]["run_key"]}</td>
            <td>{run_date}</td>
            <td>{wh_type}</td>
            <td>{data_fmt}</td>
            <td style="text-align:center;">{warm_q}</td>
        </tr>'''
    
    # Build H2H JSON data for JavaScript (must be done before f-string)
    h2h_json_data = {}
    for size, h2h in h2h_by_size.items():
        h2h_json_data[size] = {
            'size': h2h['size'],
            'sf_wins': h2h['sf_wins'],
            'dbx_wins': h2h['dbx_wins'],
            'close': h2h['close'],
            'total': h2h['total'],
            'sf_scales_better': h2h.get('sf_scales_better', 0),
            'dbx_scales_better': h2h.get('dbx_scales_better', 0),
            'scaling_close': h2h.get('scaling_close', 0),
            'scaling_range': h2h.get('scaling_range'),
            'comparisons': h2h['comparisons'],
            'category_stats': h2h['category_stats']
        }
    import json as json_module
    h2h_json_str = json_module.dumps(h2h_json_data)
    
    # Build raw query data for flexible SF vs DBX size comparison
    sf_raw_data = {size: sf_data[size]['times'] for size in sf_data}
    dbx_raw_data = {size: dbx_data[size]['times'] for size in dbx_data}
    sf_raw_json = json_module.dumps(sf_raw_data)
    dbx_raw_json = json_module.dumps(dbx_raw_data)
    sf_sizes_json = json_module.dumps(list(sf_data.keys()))
    dbx_sizes_json = json_module.dumps(list(dbx_data.keys()))
    
    # Calculate SF hourly rate ranges for tab labels
    sf_rates_se = [credits * SF_CREDIT_RATE_SE for credits in SF_CREDITS_PER_HOUR_GEN2.values()]
    sf_rates_ee = [credits * SF_CREDIT_RATE_EE for credits in SF_CREDITS_PER_HOUR_GEN2.values()]
    se_rate_range = f"${min(sf_rates_se):.0f}–${max(sf_rates_se):.0f}/hr"
    ee_rate_range = f"${min(sf_rates_ee):.0f}–${max(sf_rates_ee):.0f}/hr"
    
    # Use SE for default overview metrics
    sf_stats = sf_stats_se
    tier_comparisons = tier_comparisons_se
    perf_tier_comparisons = perf_tier_comparisons_se
    
    # Calculate key metrics
    pp_ratio = round(dbx_best_pp[1]['price_perf'] / sf_best_pp[1]['price_perf'], 1)
    speed_ratio = round(dbx_fastest[1]['total'] / sf_fastest[1]['total'], 1)
    
    # Count SF wins across tiers
    sf_tier_wins = sum(1 for t in tier_comparisons if t['winner'] == 'SF')
    
    # Generate tier comparison rows
    tier_rows = ""
    for t in tier_comparisons:
        winner_class = 'sf-winner' if t['winner'] == 'SF' else 'dbx-winner'
        tier_rows += f'''
            <tr>
                <td>{t['tier']}</td>
                <td class="sf-col">{t['sf_size']} ({t['sf_geomean']}s)</td>
                <td class="dbx-col">{t['dbx_size']} ({t['dbx_geomean']}s)</td>
                <td class="{winner_class}">{t['winner']} {t['ratio']}x faster</td>
            </tr>'''
    
    # Compute multipliers for each warehouse size (relative to S)
    # S=1, M=2, L=4, XL=8, 2XL=16, 3XL=32
    size_multipliers = {'S': 1, 'M': 2, 'L': 4, 'XL': 8, '2XL': 16, '3XL': 32}
    
    import math
    
    def compute_scaling_coefficient(sizes, values):
        """
        Compute scaling coefficient using log-log linear regression.
        
        Model: T = c * N^β  →  log(T) = log(c) + β * log(N)
        
        β = -1.0: Perfect linear scaling (2× compute → 2× speedup)
        β = -0.5: Sublinear scaling (2× compute → 1.4× speedup)
        β = 0: No scaling (serial workload)
        
        Returns: (β, R², scaling_efficiency)
        - β: slope coefficient
        - R²: coefficient of determination (fit quality)
        - scaling_efficiency: |β| as percentage (100% = perfect)
        """
        # Build data points: (log(compute_multiplier), log(runtime))
        points = []
        for size, val in zip(sizes, values):
            if val is not None and val != '-' and val > 0:
                mult = size_multipliers.get(size, 1)
                points.append((math.log(mult), math.log(val)))
        
        if len(points) < 2:
            return None, None, None
        
        # Linear regression: y = a + b*x
        n = len(points)
        sum_x = sum(p[0] for p in points)
        sum_y = sum(p[1] for p in points)
        sum_xy = sum(p[0] * p[1] for p in points)
        sum_x2 = sum(p[0] ** 2 for p in points)
        sum_y2 = sum(p[1] ** 2 for p in points)
        
        # Slope (β)
        denom = n * sum_x2 - sum_x ** 2
        if abs(denom) < 1e-10:
            return None, None, None
        
        beta = (n * sum_xy - sum_x * sum_y) / denom
        
        # R² (coefficient of determination)
        mean_y = sum_y / n
        ss_tot = sum((p[1] - mean_y) ** 2 for p in points)
        
        # Predicted values
        alpha = (sum_y - beta * sum_x) / n
        ss_res = sum((p[1] - (alpha + beta * p[0])) ** 2 for p in points)
        
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        
        # Scaling efficiency: |β| capped at 100%
        # Perfect scaling = -1.0, so efficiency = min(|β|, 1.0) * 100
        scaling_eff = min(abs(beta), 1.0) * 100
        
        return beta, r_squared, scaling_eff
    
    def make_scaling_cell(sizes, values, color='#29B5E8', width=80, height=24):
        """
        Generate sparkline SVG with scaling efficiency indicator.
        
        Shows:
        - Sparkline visualization
        - Scaling efficiency percentage with color coding
        - Tooltip with statistical details
        """
        # Compute scaling statistics
        beta, r_sq, eff = compute_scaling_coefficient(sizes, values)
        
        # Filter valid values for sparkline
        valid_vals = [(i, v) for i, v in enumerate(values) if v is not None and v != '-']
        if len(valid_vals) < 2:
            return '<span style="color:#999;font-size:11px;">—</span>'
        
        indices, vals = zip(*valid_vals)
        min_val = min(vals)
        max_val = max(vals)
        val_range = max_val - min_val if max_val != min_val else 1
        
        # Build sparkline path
        padding = 3
        usable_width = width - 2 * padding
        usable_height = height - 2 * padding
        
        points = []
        for i, (idx, v) in enumerate(valid_vals):
            x = padding + (i / (len(valid_vals) - 1)) * usable_width
            y = padding + ((v - min_val) / val_range) * usable_height
            points.append(f"{x:.1f},{y:.1f}")
        
        path = "M" + " L".join(points)
        first_x, first_y = points[0].split(',')
        last_x, last_y = points[-1].split(',')
        
        # Color code the efficiency
        # Green: ≥70% (good scaling)
        # Yellow: 40-70% (moderate)
        # Red: <40% (poor scaling)
        if eff is not None:
            if eff >= 70:
                eff_color = '#22c55e'  # green
                grade = 'A'
            elif eff >= 40:
                eff_color = '#eab308'  # yellow
                grade = 'B'
            else:
                eff_color = '#ef4444'  # red
                grade = 'C'
            
            # Tooltip with details (use &#10; for newlines in HTML title attribute)
            tooltip = f"Scaling: {eff:.0f}% efficient&#10;Slope β={beta:.2f} (ideal=-1.0)&#10;R²={r_sq:.2f}&#10;&#10;β=-1: Perfect (2× compute → 2× speedup)&#10;β=-0.5: Poor (2× compute → 1.4× speedup)"
            
            eff_badge = f'''<span style="display:inline-block;min-width:38px;padding:1px 4px;border-radius:3px;font-size:10px;font-weight:600;background:{eff_color}22;color:{eff_color};border:1px solid {eff_color}44;cursor:help;" title="{tooltip}">{eff:.0f}%</span>'''
        else:
            eff_badge = ''
        
        sparkline_svg = f'''<svg width="{width}" height="{height}" style="vertical-align:middle;">
            <path d="{path}" fill="none" stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            <circle cx="{first_x}" cy="{first_y}" r="2" fill="{color}"/>
            <circle cx="{last_x}" cy="{last_y}" r="2" fill="{color}"/>
        </svg>'''
        
        return f'<div style="display:flex;align-items:center;gap:6px;justify-content:center;">{sparkline_svg}{eff_badge}</div>'
    
    # Generate SF matrix rows with sparklines and scaling efficiency
    sf_matrix_rows = ""
    for q in all_queries:
        vals = [sf_data[size]['times'].get(q) for size in sf_sizes]
        scaling_cell = make_scaling_cell(sf_sizes, vals, color='#29B5E8')
        
        sf_matrix_rows += f'<tr><td>{q}</td>'
        for size in sf_sizes:
            val = sf_data[size]['times'].get(q, '-')
            sf_matrix_rows += f'<td>{val}</td>'
        sf_matrix_rows += f'<td style="text-align:center;">{scaling_cell}</td>'
        sf_matrix_rows += '</tr>\n'
    
    # Generate DBX matrix rows with sparklines and scaling efficiency
    dbx_matrix_rows = ""
    for q in all_queries:
        vals = [dbx_data[size]['times'].get(q) for size in dbx_sizes]
        scaling_cell = make_scaling_cell(dbx_sizes, vals, color='#FF3621')
        
        dbx_matrix_rows += f'<tr><td>{q}</td>'
        for size in dbx_sizes:
            val = dbx_data[size]['times'].get(q, '-')
            dbx_matrix_rows += f'<td>{val}</td>'
        dbx_matrix_rows += f'<td style="text-align:center;">{scaling_cell}</td>'
        dbx_matrix_rows += '</tr>\n'
    
    # SF summary rows
    sf_summary = f'''
        <tr class="summary-row-table"><td>Total (s)</td>{''.join(f'<td>{int(sf_stats[s]["total"]):,}</td>' for s in sf_sizes)}</tr>
        <tr class="summary-row-table"><td>Geomean (s)</td>{''.join(f'<td>{sf_stats[s]["geomean"]}</td>' for s in sf_sizes)}</tr>
        <tr class="summary-row-table"><td>Hourly Rate</td>{''.join(f'<td>${sf_stats[s]["hourly_rate"]:.0f}</td>' for s in sf_sizes)}</tr>
        <tr class="metric-row"><td>Run Cost</td>{''.join(f'<td>${sf_stats[s]["cost"]:.2f}</td>' for s in sf_sizes)}</tr>
        <tr class="metric-row"><td>Cost × Geomean</td>{''.join(f'<td>{int(sf_stats[s]["price_perf"])}</td>' for s in sf_sizes)}</tr>
    '''
    
    # DBX summary rows
    dbx_summary = f'''
        <tr class="summary-row-table"><td>Total (s)</td>{''.join(f'<td>{int(dbx_stats[s]["total"]):,}</td>' for s in dbx_sizes)}</tr>
        <tr class="summary-row-table"><td>Geomean (s)</td>{''.join(f'<td>{dbx_stats[s]["geomean"]}</td>' for s in dbx_sizes)}</tr>
        <tr class="summary-row-table"><td>Hourly Rate</td>{''.join(f'<td>${dbx_stats[s]["hourly_rate"]:.0f}</td>' for s in dbx_sizes)}</tr>
        <tr class="metric-row"><td>Run Cost</td>{''.join(f'<td>${dbx_stats[s]["cost"]:.2f}</td>' for s in dbx_sizes)}</tr>
        <tr class="metric-row"><td>Cost × Geomean</td>{''.join(f'<td>{int(dbx_stats[s]["price_perf"])}</td>' for s in dbx_sizes)}</tr>
    '''
    
    # Prepare chart data for graphs tab (SE and EE pricing for SF)
    import json
    
    # SF SE data points
    sf_se_chart_data = []
    for s in sf_sizes:
        sf_se_chart_data.append({
            'size': s,
            'cost': round(sf_stats_se[s]['cost'], 2),
            'geomean': sf_stats_se[s]['geomean'],
            'total': round(sf_stats_se[s]['total'], 1),
            'hourly': sf_stats_se[s]['hourly_rate']
        })
    
    # SF EE data points
    sf_ee_chart_data = []
    for s in sf_sizes:
        sf_ee_chart_data.append({
            'size': s,
            'cost': round(sf_stats_ee[s]['cost'], 2),
            'geomean': sf_stats_ee[s]['geomean'],
            'total': round(sf_stats_ee[s]['total'], 1),
            'hourly': sf_stats_ee[s]['hourly_rate']
        })
    
    # DBX data points
    dbx_chart_data = []
    for s in dbx_sizes:
        dbx_chart_data.append({
            'size': s,
            'cost': round(dbx_stats[s]['cost'], 2),
            'geomean': dbx_stats[s]['geomean'],
            'total': round(dbx_stats[s]['total'], 1),
            'hourly': dbx_stats[s]['hourly_rate']
        })
    
    sf_se_chart_json = json.dumps(sf_se_chart_data)
    sf_ee_chart_json = json.dumps(sf_ee_chart_data)
    dbx_chart_json = json.dumps(dbx_chart_data)
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TPC-DS 10TB: Snowflake FDN vs Databricks Delta{publish_title_suffix}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {{
            --sf-blue: #29B5E8;
            --sf-dark-blue: #11567F;
            --sf-navy: #0D2C54;
            --sf-light-bg: #F4FAFF;
            --sf-gray: #6E7681;
            --dbx-red: #FF3621;
            --dbx-light: #FFF5F4;
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
        
        .tab-nav {{
            display: flex;
            gap: 0;
            margin: 20px 0;
            border-bottom: 2px solid var(--sf-blue);
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
        .card.dbx {{ background: var(--dbx-red); color: white; }}
        .card.winner {{ background: var(--green); color: white; }}
        
        .card .label {{ font-size: 0.85em; opacity: 0.9; }}
        .card .value {{ font-size: 1.6em; font-weight: bold; margin: 4px 0; }}
        .card .detail {{ font-size: 0.75em; opacity: 0.8; }}
        
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
        }}
        
        th:first-child {{ text-align: left; }}
        th.dbx {{ background: linear-gradient(135deg, #FF3621 0%, #CC2A1A 100%); }}
        
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
        
        .summary-row-table td {{
            background: #E8F4FC !important;
            font-weight: 600;
        }}
        
        .metric-row td {{
            background: #FFF8E8 !important;
            font-weight: 600;
        }}
        
        .sf-col {{ background: #F4FAFF !important; }}
        .dbx-col {{ background: #FFF5F4 !important; }}
        
        .sf-winner {{ background: #E8F5E9 !important; color: var(--green); font-weight: 700; }}
        .dbx-winner {{ background: #FFEBE9 !important; color: var(--dbx-red); font-weight: 700; }}
        
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
        
        .footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #eee;
            font-size: 0.8em;
            color: var(--sf-gray);
        }}
        
        .price-tier-table th:first-child {{ text-align: left; }}
        .price-tier-table td:first-child {{ font-weight: 700; }}
        
        /* OKR Scorecard Styles */
        .okr-scorecard {{
            margin: 20px 0;
        }}
        
        .okr-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 25px;
            border-radius: 10px;
            margin-bottom: 20px;
        }}
        
        .okr-exceeding {{ background: linear-gradient(135deg, #e8f5e9, #c8e6c9); border: 2px solid #4caf50; }}
        .okr-meeting {{ background: linear-gradient(135deg, #e3f2fd, #bbdefb); border: 2px solid #2196f3; }}
        .okr-at-risk {{ background: linear-gradient(135deg, #fff8e1, #ffecb3); border: 2px solid #ff9800; }}
        .okr-failing {{ background: linear-gradient(135deg, #ffebee, #ffcdd2); border: 2px solid #f44336; }}
        
        .okr-main {{
            text-align: left;
        }}
        
        .okr-grade {{
            font-size: 1.8em;
            font-weight: 700;
            margin-bottom: 5px;
        }}
        
        .okr-score {{
            font-size: 1.3em;
            font-weight: 600;
        }}
        
        .okr-details {{
            text-align: right;
            font-size: 0.95em;
            line-height: 1.6;
        }}
        
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
        
        .class-tag {{ padding: 2px 8px; border-radius: 3px; font-size: 0.85em; font-weight: 600; }}
        .class-reporting {{ background: #e3f2fd; color: #1565c0; }}
        .class-adhoc {{ background: #fff3e0; color: #e65100; }}
        .class-olap {{ background: #f3e5f5; color: #7b1fa2; }}
        .class-datamining {{ background: #e8f5e9; color: #2e7d32; }}
        
        .search-box {{ margin: 15px 0; }}
        .search-box input {{ width: 300px; padding: 8px 12px; border: 2px solid #ddd; border-radius: 6px; font-size: 0.95em; }}
        .search-box input:focus {{ border-color: var(--sf-blue); outline: none; }}
    </style>
</head>
<body>
    <h1>TPC-DS 10TB: Snowflake FDN vs Databricks Delta{publish_badge}</h1>
    <p class="subtitle">Price:Performance Frontier Analysis — Native formats, Gen2 vs Photon</p>
    
    <div class="tab-nav">
        <button class="tab-btn active" onclick="showTab('frontier', this)">Overview</button>
        <button class="tab-btn" onclick="showTab('ee-analysis', this)">EE Analysis ({ee_rate_range})</button>
        <button class="tab-btn" onclick="showTab('se-analysis', this)">SE Analysis ({se_rate_range})</button>
        <button class="tab-btn" onclick="showTab('graphs', this)">Graphs</button>
        <button class="tab-btn" onclick="showTab('head-to-head', this)">Head-to-Head</button>
        <button class="tab-btn" onclick="showTab('sf-matrix', this)">Snowflake Details</button>
        <button class="tab-btn" onclick="showTab('dbx-matrix', this)">Databricks Details</button>
        <button class="tab-btn" onclick="showTab('scaling', this)">Scaling Analysis</button>
        <button class="tab-btn" onclick="showTab('reference', this)">Query Reference</button>
    </div>
    
    <!-- Tab 1: Price:Performance Frontier -->
    <div id="frontier" class="tab-content active">
        <h2>Executive Summary</h2>
        
        <div class="summary-row" id="summary-cards">
            <div class="card winner" id="card-best-pp">
                <div class="label">Best Price:Perf</div>
                <div class="value" id="best-pp-value">SF {sf_best_pp[0]}</div>
                <div class="detail" id="best-pp-detail">Score {int(sf_best_pp[1]['price_perf'])} ({pp_ratio}x better than DBX)</div>
            </div>
            <div class="card sf" id="card-sf-fastest">
                <div class="label">SF Fastest</div>
                <div class="value" id="sf-fastest-value">{sf_fastest[0]}</div>
                <div class="detail" id="sf-fastest-detail">{int(sf_fastest[1]['total'])}s total</div>
            </div>
            <div class="card dbx" id="card-dbx-fastest">
                <div class="label">DBX Fastest</div>
                <div class="value" id="dbx-fastest-value">{dbx_fastest[0]}</div>
                <div class="detail" id="dbx-fastest-detail">{int(dbx_fastest[1]['total'])}s total</div>
            </div>
            <div class="card" id="card-tier-wins">
                <div class="label">Tier Wins</div>
                <div class="value" id="tier-wins-value">SF {sf_tier_wins}/{len(tier_comparisons)}</div>
                <div class="detail">price tiers</div>
            </div>
        </div>
        
        <div class="insight-box winner" id="key-finding-box">
            <strong>Key Finding:</strong> <span id="key-finding-text">At every comparable price point, Snowflake delivers faster performance than Databricks. 
            SF's best price:performance ({sf_best_pp[0]} at ${sf_best_pp[1]['cost']:.2f}) beats DBX's best ({dbx_best_pp[0]} at ${dbx_best_pp[1]['cost']:.2f}) by <strong>{pp_ratio}x</strong>.</span>
        </div>
        
        <h2>At Each Budget, Who's Faster?</h2>
        <p>This table answers: <em>"If I have $X/hour to spend, what latency do I get?"</em></p>
        
        <div class="table-container">
            <table class="price-tier-table">
                <thead>
                    <tr>
                        <th>Budget ($/hr)</th>
                        <th>Snowflake Best</th>
                        <th>Databricks Best</th>
                        <th>Winner</th>
                    </tr>
                </thead>
                <tbody>
                    {tier_rows}
                </tbody>
            </table>
        </div>
        
        <h2>Understanding the Comparison</h2>
        
        <div class="insight-box" style="background: #fff3cd; border-color: #ffc107;">
            <strong>⚠️ Pricing Assumptions — THIS REPORT USES STANDARD EDITION (verify for your contract):</strong><br>
            <table style="margin-top:10px; font-size:0.9em; width:100%;">
                <tr>
                    <td style="padding-right:20px; vertical-align:top; width:50%;">
                        <strong>Snowflake Gen2 (AWS)</strong><br>
                        <em>Gen2 = 1.35× Gen1 credits/hr</em><br><br>
                        <table style="font-size:0.95em; border-collapse:collapse;">
                            <tr style="background:#e8f4f8;">
                                <th style="padding:4px 8px; text-align:left;">Size</th>
                                <th style="padding:4px 8px;">Cr/hr</th>
                                <th style="padding:4px 8px;">SE @$2</th>
                                <th style="padding:4px 8px;">EE @$3</th>
                            </tr>
                            <tr><td style="padding:2px 8px;">S</td><td style="padding:2px 8px; text-align:center;">2.7</td><td style="padding:2px 8px; text-align:center;"><strong>$5.40</strong></td><td style="padding:2px 8px; text-align:center;">$8.10</td></tr>
                            <tr><td style="padding:2px 8px;">M</td><td style="padding:2px 8px; text-align:center;">5.4</td><td style="padding:2px 8px; text-align:center;"><strong>$10.80</strong></td><td style="padding:2px 8px; text-align:center;">$16.20</td></tr>
                            <tr><td style="padding:2px 8px;">L</td><td style="padding:2px 8px; text-align:center;">10.8</td><td style="padding:2px 8px; text-align:center;"><strong>$21.60</strong></td><td style="padding:2px 8px; text-align:center;">$32.40</td></tr>
                            <tr><td style="padding:2px 8px;">XL</td><td style="padding:2px 8px; text-align:center;">21.6</td><td style="padding:2px 8px; text-align:center;"><strong>$43.20</strong></td><td style="padding:2px 8px; text-align:center;">$64.80</td></tr>
                            <tr><td style="padding:2px 8px;">2XL</td><td style="padding:2px 8px; text-align:center;">43.2</td><td style="padding:2px 8px; text-align:center;"><strong>$86.40</strong></td><td style="padding:2px 8px; text-align:center;">$129.60</td></tr>
                            <tr><td style="padding:2px 8px;">3XL</td><td style="padding:2px 8px; text-align:center;">86.4</td><td style="padding:2px 8px; text-align:center;"><strong>$172.80</strong></td><td style="padding:2px 8px; text-align:center;">$259.20</td></tr>
                        </table>
                    </td>
                    <td style="vertical-align:top; width:50%;">
                        <strong>Databricks SQL Serverless</strong><br>
                        <em>$0.70/DBU (includes compute)</em><br><br>
                        <table style="font-size:0.95em; border-collapse:collapse;">
                            <tr style="background:#fce4d6;">
                                <th style="padding:4px 8px; text-align:left;">Size</th>
                                <th style="padding:4px 8px;">DBU/hr</th>
                                <th style="padding:4px 8px;">$/hr</th>
                            </tr>
                            <tr><td style="padding:2px 8px;">S</td><td style="padding:2px 8px; text-align:center;">12</td><td style="padding:2px 8px; text-align:center;"><strong>$8.40</strong></td></tr>
                            <tr><td style="padding:2px 8px;">M</td><td style="padding:2px 8px; text-align:center;">24</td><td style="padding:2px 8px; text-align:center;"><strong>$16.80</strong></td></tr>
                            <tr><td style="padding:2px 8px;">L</td><td style="padding:2px 8px; text-align:center;">40</td><td style="padding:2px 8px; text-align:center;"><strong>$28.00</strong></td></tr>
                            <tr><td style="padding:2px 8px;">XL</td><td style="padding:2px 8px; text-align:center;">80</td><td style="padding:2px 8px; text-align:center;"><strong>$56.00</strong></td></tr>
                            <tr><td style="padding:2px 8px;">2XL</td><td style="padding:2px 8px; text-align:center;">144</td><td style="padding:2px 8px; text-align:center;"><strong>$100.80</strong></td></tr>
                            <tr><td style="padding:2px 8px;">3XL</td><td style="padding:2px 8px; text-align:center;">272</td><td style="padding:2px 8px; text-align:center;"><strong>$190.40</strong></td></tr>
                        </table>
                    </td>
                </tr>
            </table>
            <p style="margin-top:15px; margin-bottom:0; font-size:0.85em; color:#856404;">
                <strong>Note:</strong> This analysis uses <strong>Standard Edition ($2/credit)</strong>. 
                Enterprise Edition ($3/credit) would increase SF costs by 50%, narrowing the price advantage.
                Contracted rates vary — adjust accordingly.
            </p>
        </div>
        
        <div class="insight-box">
            <strong>Why Price Tiers?</strong> T-shirt sizes (S, M, L) mean different things on each platform. 
            A "Large" on Snowflake costs ${calc_sf_hourly_rate('L'):.0f}/hr, while a "Large" on Databricks costs ${calc_dbx_hourly_rate('L'):.0f}/hr. 
            Comparing by price ensures apples-to-apples evaluation.
        </div>
        
        <div class="insight-box">
            <strong>Cost × Geomean:</strong> This metric balances cost and latency. Lower is better. 
            You can't game it by being cheap-but-slow or fast-but-expensive.
        </div>

        <h2>Included Runs</h2>
        <p style="color:var(--sf-gray);">Validation table: confirm the correct benchmark runs are included.</p>
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
    </div>
    
    <!-- Tab 2: EE Analysis -->
    {generate_edition_tab_html('ee-analysis', 'Enterprise Edition', SF_CREDIT_RATE_EE, sf_data, dbx_data, sf_stats_ee, dbx_stats, tier_comparisons_ee, perf_tier_comparisons_ee)}
    
    <!-- Tab 3: SE Analysis -->
    {generate_edition_tab_html('se-analysis', 'Standard Edition', SF_CREDIT_RATE_SE, sf_data, dbx_data, sf_stats_se, dbx_stats, tier_comparisons_se, perf_tier_comparisons_se)}
    
    <!-- Tab 4: Graphs -->
    <div id="graphs" class="tab-content">
        <h2>Performance & Cost Visualization</h2>
        <p class="subtitle">Comparing Snowflake (SE & EE pricing) vs Databricks across warehouse sizes</p>
        
        <!-- Toggle Controls -->
        <div style="display:flex;gap:30px;margin:20px 0;padding:15px;background:#f0f4f8;border-radius:8px;align-items:center;flex-wrap:wrap;">
            <div style="display:flex;align-items:center;gap:10px;">
                <span style="font-weight:600;color:#333;">Scale:</span>
                <button id="scaleLinear" class="toggle-btn active" onclick="setScale('linear')">Linear</button>
                <button id="scaleLog" class="toggle-btn" onclick="setScale('log')">Log Scale</button>
            </div>
            <div style="display:flex;align-items:center;gap:10px;">
                <span style="font-weight:600;color:#333;">View:</span>
                <button id="viewAbsolute" class="toggle-btn active" onclick="setView('absolute')">Absolute Values</button>
                <button id="viewAdvantage" class="toggle-btn" onclick="setView('advantage')">% Advantage vs DBX</button>
            </div>
        </div>
        
        <style>
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
            .toggle-btn:hover {{
                background: #e8f7fc;
            }}
            .toggle-btn.active {{
                background: #29B5E8;
                color: white;
            }}
        </style>
        
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:30px;margin-top:20px;">
            <!-- Run Cost by Size -->
            <div style="background:#f8f9fa;padding:20px;border-radius:8px;">
                <h3 style="margin-top:0;">Run Cost by Warehouse Size</h3>
                <canvas id="costChart"></canvas>
            </div>
            
            <!-- Geomean by Size -->
            <div style="background:#f8f9fa;padding:20px;border-radius:8px;">
                <h3 style="margin-top:0;" id="geomeanTitle">Geomean Latency by Warehouse Size</h3>
                <canvas id="geomeanChart"></canvas>
            </div>
            
            <!-- Total Time by Size -->
            <div style="background:#f8f9fa;padding:20px;border-radius:8px;">
                <h3 style="margin-top:0;" id="totalTitle">Total Runtime by Warehouse Size</h3>
                <canvas id="totalChart"></canvas>
            </div>
            
            <!-- Price:Perf Score by Size -->
            <div style="background:#f8f9fa;padding:20px;border-radius:8px;">
                <h3 style="margin-top:0;" id="pricePerTitle">Price:Performance Score by Size</h3>
                <p style="font-size:0.85em;color:#666;margin-top:-10px;" id="pricePerSubtitle">Lower is better (Cost × Geomean)</p>
                <canvas id="pricePerChart"></canvas>
            </div>
        </div>
        
        <h2 style="margin-top:40px;">Cost vs Performance Scatter Plots</h2>
        <p class="subtitle">Each point is a warehouse size. Shows the cost-performance tradeoff curve.</p>
        
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:30px;margin-top:20px;">
            <!-- Cost vs Geomean Scatter -->
            <div style="background:#f8f9fa;padding:20px;border-radius:8px;">
                <h3 style="margin-top:0;">Run Cost vs Geomean Latency</h3>
                <canvas id="scatterGeomean"></canvas>
            </div>
            
            <!-- Cost vs Total Time Scatter -->
            <div style="background:#f8f9fa;padding:20px;border-radius:8px;">
                <h3 style="margin-top:0;">Run Cost vs Total Runtime</h3>
                <canvas id="scatterTotal"></canvas>
            </div>
        </div>
        
        <script>
            // Chart data - SF SE, SF EE, and DBX
            const sfSeData = {sf_se_chart_json};
            const sfEeData = {sf_ee_chart_json};
            const dbxData = {dbx_chart_json};
            
            // Current state
            let currentScale = 'linear';
            let currentView = 'absolute';
            
            // Get all unique sizes for x-axis labels
            const allSizes = ['S', 'M', 'L', 'XL', '2XL', '3XL', '4XL'].filter(s => 
                sfSeData.some(d => d.size === s) || dbxData.some(d => d.size === s)
            );
            
            // Calculate % advantage: ((DBX - SF) / DBX) * 100
            function calcAdvantage(sfVal, dbxVal) {{
                if (!dbxVal || dbxVal === 0) return null;
                return ((dbxVal - sfVal) / dbxVal) * 100;
            }}
            
            // Store chart instances
            let charts = {{}};
            
            // Color scheme
            const colors = {{
                sfSe: '#29B5E8',
                sfEe: '#11567F', 
                dbx: '#FF3621',
                target: '#32963C',
                parity: '#888'
            }};
            
            // Build charts
            function buildCharts() {{
                // Destroy existing charts
                Object.values(charts).forEach(c => c && c.destroy());
                
                const isLog = currentScale === 'log';
                const isAdvantage = currentView === 'advantage';
                
                // Update titles
                document.getElementById('geomeanTitle').textContent = isAdvantage ? 
                    'Geomean Latency — SF Advantage vs DBX' : 'Geomean Latency by Warehouse Size';
                document.getElementById('totalTitle').textContent = isAdvantage ? 
                    'Total Runtime — SF Advantage vs DBX' : 'Total Runtime by Warehouse Size';
                document.getElementById('pricePerTitle').textContent = isAdvantage ? 
                    'Price:Performance Score — SF Advantage vs DBX' : 'Price:Performance Score by Size';
                document.getElementById('pricePerSubtitle').textContent = isAdvantage ? 
                    'Positive = SF wins, 35% target shown' : 'Lower is better (Cost × Geomean)';
                
                // 1. Run Cost Chart (always absolute, no advantage view)
                charts.cost = new Chart(document.getElementById('costChart'), {{
                    type: 'line',
                    data: {{
                        labels: allSizes,
                        datasets: [{{
                            label: 'Snowflake SE',
                            data: allSizes.map(s => {{ const d = sfSeData.find(x => x.size === s); return d ? d.cost : null; }}),
                            borderColor: colors.sfSe,
                            backgroundColor: colors.sfSe,
                            tension: 0.1
                        }}, {{
                            label: 'Snowflake EE',
                            data: allSizes.map(s => {{ const d = sfEeData.find(x => x.size === s); return d ? d.cost : null; }}),
                            borderColor: colors.sfEe,
                            backgroundColor: colors.sfEe,
                            borderDash: [5, 5],
                            tension: 0.1
                        }}, {{
                            label: 'Databricks',
                            data: allSizes.map(s => {{ const d = dbxData.find(x => x.size === s); return d ? d.cost : null; }}),
                            borderColor: colors.dbx,
                            backgroundColor: colors.dbx,
                            tension: 0.1
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        plugins: {{ legend: {{ position: 'bottom' }} }},
                        scales: {{
                            y: {{ 
                                type: isLog ? 'logarithmic' : 'linear',
                                beginAtZero: !isLog,
                                title: {{ display: true, text: 'Run Cost ($)' }}
                            }}
                        }}
                    }}
                }});
                
                // 2. Geomean Chart
                if (isAdvantage) {{
                    charts.geomean = new Chart(document.getElementById('geomeanChart'), {{
                        type: 'line',
                        data: {{
                            labels: allSizes,
                            datasets: [{{
                                label: 'SF Advantage (%)',
                                data: allSizes.map(s => {{
                                    const sf = sfSeData.find(x => x.size === s);
                                    const dbx = dbxData.find(x => x.size === s);
                                    return sf && dbx ? calcAdvantage(sf.geomean, dbx.geomean) : null;
                                }}),
                                borderColor: colors.sfSe,
                                backgroundColor: colors.sfSe,
                                tension: 0.1,
                                fill: false
                            }}, {{
                                label: '35% Target',
                                data: allSizes.map(() => 35),
                                borderColor: colors.target,
                                borderDash: [6, 6],
                                pointRadius: 0,
                                fill: false
                            }}, {{
                                label: 'Parity (0%)',
                                data: allSizes.map(() => 0),
                                borderColor: colors.parity,
                                borderDash: [2, 2],
                                pointRadius: 0,
                                fill: false
                            }}]
                        }},
                        options: {{
                            responsive: true,
                            plugins: {{ legend: {{ position: 'bottom' }} }},
                            scales: {{
                                y: {{ 
                                    title: {{ display: true, text: 'SF Advantage (%) — positive = SF wins' }}
                                }}
                            }}
                        }}
                    }});
                }} else {{
                    charts.geomean = new Chart(document.getElementById('geomeanChart'), {{
                        type: 'line',
                        data: {{
                            labels: allSizes,
                            datasets: [{{
                                label: 'Snowflake',
                                data: allSizes.map(s => {{ const d = sfSeData.find(x => x.size === s); return d ? d.geomean : null; }}),
                                borderColor: colors.sfSe,
                                backgroundColor: colors.sfSe,
                                tension: 0.1
                            }}, {{
                                label: 'Databricks',
                                data: allSizes.map(s => {{ const d = dbxData.find(x => x.size === s); return d ? d.geomean : null; }}),
                                borderColor: colors.dbx,
                                backgroundColor: colors.dbx,
                                tension: 0.1
                            }}]
                        }},
                        options: {{
                            responsive: true,
                            plugins: {{ legend: {{ position: 'bottom' }} }},
                            scales: {{
                                y: {{ 
                                    type: isLog ? 'logarithmic' : 'linear',
                                    reverse: !isLog,
                                    title: {{ display: true, text: isLog ? 'Geomean (seconds) — log scale' : 'Geomean (seconds) — lower is better ↓' }}
                                }}
                            }}
                        }}
                    }});
                }}
                
                // 3. Total Runtime Chart
                if (isAdvantage) {{
                    charts.total = new Chart(document.getElementById('totalChart'), {{
                        type: 'line',
                        data: {{
                            labels: allSizes,
                            datasets: [{{
                                label: 'SF Advantage (%)',
                                data: allSizes.map(s => {{
                                    const sf = sfSeData.find(x => x.size === s);
                                    const dbx = dbxData.find(x => x.size === s);
                                    return sf && dbx ? calcAdvantage(sf.total, dbx.total) : null;
                                }}),
                                borderColor: colors.sfSe,
                                backgroundColor: colors.sfSe,
                                tension: 0.1,
                                fill: false
                            }}, {{
                                label: '35% Target',
                                data: allSizes.map(() => 35),
                                borderColor: colors.target,
                                borderDash: [6, 6],
                                pointRadius: 0,
                                fill: false
                            }}, {{
                                label: 'Parity (0%)',
                                data: allSizes.map(() => 0),
                                borderColor: colors.parity,
                                borderDash: [2, 2],
                                pointRadius: 0,
                                fill: false
                            }}]
                        }},
                        options: {{
                            responsive: true,
                            plugins: {{ legend: {{ position: 'bottom' }} }},
                            scales: {{
                                y: {{ 
                                    title: {{ display: true, text: 'SF Advantage (%) — positive = SF wins' }}
                                }}
                            }}
                        }}
                    }});
                }} else {{
                    charts.total = new Chart(document.getElementById('totalChart'), {{
                        type: 'line',
                        data: {{
                            labels: allSizes,
                            datasets: [{{
                                label: 'Snowflake',
                                data: allSizes.map(s => {{ const d = sfSeData.find(x => x.size === s); return d ? d.total : null; }}),
                                borderColor: colors.sfSe,
                                backgroundColor: colors.sfSe,
                                tension: 0.1
                            }}, {{
                                label: 'Databricks',
                                data: allSizes.map(s => {{ const d = dbxData.find(x => x.size === s); return d ? d.total : null; }}),
                                borderColor: colors.dbx,
                                backgroundColor: colors.dbx,
                                tension: 0.1
                            }}]
                        }},
                        options: {{
                            responsive: true,
                            plugins: {{ legend: {{ position: 'bottom' }} }},
                            scales: {{
                                y: {{ 
                                    type: isLog ? 'logarithmic' : 'linear',
                                    reverse: !isLog,
                                    title: {{ display: true, text: isLog ? 'Total Runtime (seconds) — log scale' : 'Total Runtime (seconds) — lower is better ↓' }}
                                }}
                            }}
                        }}
                    }});
                }}
                
                // 4. Price:Perf Score Chart
                if (isAdvantage) {{
                    charts.pricePer = new Chart(document.getElementById('pricePerChart'), {{
                        type: 'line',
                        data: {{
                            labels: allSizes,
                            datasets: [{{
                                label: 'SF SE Advantage (%)',
                                data: allSizes.map(s => {{
                                    const sf = sfSeData.find(x => x.size === s);
                                    const dbx = dbxData.find(x => x.size === s);
                                    if (!sf || !dbx) return null;
                                    return calcAdvantage(sf.cost * sf.geomean, dbx.cost * dbx.geomean);
                                }}),
                                borderColor: colors.sfSe,
                                backgroundColor: colors.sfSe,
                                tension: 0.1,
                                fill: false
                            }}, {{
                                label: 'SF EE Advantage (%)',
                                data: allSizes.map(s => {{
                                    const sf = sfEeData.find(x => x.size === s);
                                    const dbx = dbxData.find(x => x.size === s);
                                    if (!sf || !dbx) return null;
                                    return calcAdvantage(sf.cost * sf.geomean, dbx.cost * dbx.geomean);
                                }}),
                                borderColor: colors.sfEe,
                                backgroundColor: colors.sfEe,
                                borderDash: [5, 5],
                                tension: 0.1,
                                fill: false
                            }}, {{
                                label: '35% Target',
                                data: allSizes.map(() => 35),
                                borderColor: colors.target,
                                borderDash: [6, 6],
                                pointRadius: 0,
                                fill: false
                            }}, {{
                                label: 'Parity (0%)',
                                data: allSizes.map(() => 0),
                                borderColor: colors.parity,
                                borderDash: [2, 2],
                                pointRadius: 0,
                                fill: false
                            }}]
                        }},
                        options: {{
                            responsive: true,
                            plugins: {{ legend: {{ position: 'bottom' }} }},
                            scales: {{
                                y: {{ 
                                    title: {{ display: true, text: 'SF Advantage (%) — positive = SF wins' }}
                                }}
                            }}
                        }}
                    }});
                }} else {{
                    charts.pricePer = new Chart(document.getElementById('pricePerChart'), {{
                        type: 'line',
                        data: {{
                            labels: allSizes,
                            datasets: [{{
                                label: 'Snowflake SE',
                                data: allSizes.map(s => {{ const d = sfSeData.find(x => x.size === s); return d ? d.cost * d.geomean : null; }}),
                                borderColor: colors.sfSe,
                                backgroundColor: colors.sfSe,
                                tension: 0.1
                            }}, {{
                                label: 'Snowflake EE',
                                data: allSizes.map(s => {{ const d = sfEeData.find(x => x.size === s); return d ? d.cost * d.geomean : null; }}),
                                borderColor: colors.sfEe,
                                backgroundColor: colors.sfEe,
                                borderDash: [5, 5],
                                tension: 0.1
                            }}, {{
                                label: 'Databricks',
                                data: allSizes.map(s => {{ const d = dbxData.find(x => x.size === s); return d ? d.cost * d.geomean : null; }}),
                                borderColor: colors.dbx,
                                backgroundColor: colors.dbx,
                                tension: 0.1
                            }}]
                        }},
                        options: {{
                            responsive: true,
                            plugins: {{ legend: {{ position: 'bottom' }} }},
                            scales: {{
                                y: {{ 
                                    type: isLog ? 'logarithmic' : 'linear',
                                    reverse: !isLog,
                                    title: {{ display: true, text: isLog ? 'Score (Cost × Geomean) — log scale' : 'Score (Cost × Geomean) — lower is better ↓' }}
                                }}
                            }}
                        }}
                    }});
                }}
                
                // 5. Scatter: Cost vs Geomean
                charts.scatterGeomean = new Chart(document.getElementById('scatterGeomean'), {{
                    type: 'scatter',
                    data: {{
                        datasets: [{{
                            label: 'Snowflake SE',
                            data: sfSeData.map(d => ({{ x: d.cost, y: d.geomean, label: d.size }})),
                            borderColor: colors.sfSe,
                            backgroundColor: 'rgba(41, 181, 232, 0.6)',
                            pointRadius: 8,
                            pointHoverRadius: 10
                        }}, {{
                            label: 'Snowflake EE',
                            data: sfEeData.map(d => ({{ x: d.cost, y: d.geomean, label: d.size }})),
                            borderColor: colors.sfEe,
                            backgroundColor: 'rgba(17, 86, 127, 0.6)',
                            pointRadius: 8,
                            pointHoverRadius: 10,
                            pointStyle: 'triangle'
                        }}, {{
                            label: 'Databricks',
                            data: dbxData.map(d => ({{ x: d.cost, y: d.geomean, label: d.size }})),
                            borderColor: colors.dbx,
                            backgroundColor: 'rgba(255, 54, 33, 0.6)',
                            pointRadius: 8,
                            pointHoverRadius: 10
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        plugins: {{
                            legend: {{ position: 'bottom' }},
                            tooltip: {{
                                callbacks: {{
                                    label: function(context) {{
                                        const point = context.raw;
                                        return context.dataset.label + ' ' + (point.label || '') + ': $' + point.x.toFixed(2) + ', ' + point.y.toFixed(1) + 's';
                                    }}
                                }}
                            }}
                        }},
                        scales: {{
                            x: {{ 
                                type: isLog ? 'logarithmic' : 'linear',
                                reverse: !isLog,
                                title: {{ display: true, text: isLog ? 'Run Cost ($) — log scale' : 'Run Cost ($) — lower is better ←' }}
                            }},
                            y: {{ 
                                type: isLog ? 'logarithmic' : 'linear',
                                reverse: !isLog,
                                title: {{ display: true, text: isLog ? 'Geomean (seconds) — log scale' : 'Geomean (seconds) — lower is better ↓' }}
                            }}
                        }}
                    }}
                }});
                
                // 6. Scatter: Cost vs Total
                charts.scatterTotal = new Chart(document.getElementById('scatterTotal'), {{
                    type: 'scatter',
                    data: {{
                        datasets: [{{
                            label: 'Snowflake SE',
                            data: sfSeData.map(d => ({{ x: d.cost, y: d.total, label: d.size }})),
                            borderColor: colors.sfSe,
                            backgroundColor: 'rgba(41, 181, 232, 0.6)',
                            pointRadius: 8,
                            pointHoverRadius: 10
                        }}, {{
                            label: 'Snowflake EE',
                            data: sfEeData.map(d => ({{ x: d.cost, y: d.total, label: d.size }})),
                            borderColor: colors.sfEe,
                            backgroundColor: 'rgba(17, 86, 127, 0.6)',
                            pointRadius: 8,
                            pointHoverRadius: 10,
                            pointStyle: 'triangle'
                        }}, {{
                            label: 'Databricks',
                            data: dbxData.map(d => ({{ x: d.cost, y: d.total, label: d.size }})),
                            borderColor: colors.dbx,
                            backgroundColor: 'rgba(255, 54, 33, 0.6)',
                            pointRadius: 8,
                            pointHoverRadius: 10
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        plugins: {{
                            legend: {{ position: 'bottom' }},
                            tooltip: {{
                                callbacks: {{
                                    label: function(context) {{
                                        const point = context.raw;
                                        return context.dataset.label + ' ' + (point.label || '') + ': $' + point.x.toFixed(2) + ', ' + point.y.toFixed(0) + 's';
                                    }}
                                }}
                            }}
                        }},
                        scales: {{
                            x: {{ 
                                type: isLog ? 'logarithmic' : 'linear',
                                reverse: !isLog,
                                title: {{ display: true, text: isLog ? 'Run Cost ($) — log scale' : 'Run Cost ($) — lower is better ←' }}
                            }},
                            y: {{ 
                                type: isLog ? 'logarithmic' : 'linear',
                                reverse: !isLog,
                                title: {{ display: true, text: isLog ? 'Total Runtime (seconds) — log scale' : 'Total Runtime (seconds) — lower is better ↓' }}
                            }}
                        }}
                    }}
                }});
            }}
            
            // Toggle functions
            function setScale(scale) {{
                currentScale = scale;
                document.getElementById('scaleLinear').classList.toggle('active', scale === 'linear');
                document.getElementById('scaleLog').classList.toggle('active', scale === 'log');
                buildCharts();
            }}
            
            function setView(view) {{
                currentView = view;
                document.getElementById('viewAbsolute').classList.toggle('active', view === 'absolute');
                document.getElementById('viewAdvantage').classList.toggle('active', view === 'advantage');
                buildCharts();
            }}
            
            // Initial build
            buildCharts();
        </script>
    </div>
    
    <!-- Tab 5: Head-to-Head Query Comparison -->
    <div id="head-to-head" class="tab-content">
        <div style="display:flex;align-items:center;gap:15px;margin-bottom:20px;flex-wrap:wrap;">
            <h2 style="margin:0;">Query-by-Query Comparison:</h2>
            <div style="display:flex;align-items:center;gap:8px;">
                <span style="color:#29b5e8;font-weight:600;">SF</span>
                <select id="sfSizeSelector" onchange="renderH2HComparison()" style="font-size:1.1em;padding:6px 12px;border-radius:6px;border:2px solid #29b5e8;font-weight:600;cursor:pointer;">
                    {''.join(f'<option value="{s}" {"selected" if s == default_h2h_size else ""}>{s}</option>' for s in sf_sizes)}
                </select>
            </div>
            <span style="font-size:1.2em;font-weight:bold;">vs</span>
            <div style="display:flex;align-items:center;gap:8px;">
                <span style="color:#ff6b35;font-weight:600;">DBX</span>
                <select id="dbxSizeSelector" onchange="renderH2HComparison()" style="font-size:1.1em;padding:6px 12px;border-radius:6px;border:2px solid #ff6b35;font-weight:600;cursor:pointer;">
                    {''.join(f'<option value="{s}" {"selected" if s == default_h2h_size else ""}>{s}</option>' for s in dbx_sizes)}
                </select>
            </div>
        </div>
        
        <div id="h2hComparisonContent">
            <p>Loading comparison...</p>
        </div>
        
        <script>
            // Raw query data by size
            const sfRawData = {sf_raw_json};
            const dbxRawData = {dbx_raw_json};
            const sfSizes = {sf_sizes_json};
            const dbxSizes = {dbx_sizes_json};
            const sizeOrder = ['S', 'M', 'L', 'XL', '2XL', '3XL', '4XL'];
            
            // Query classifications
            const queryClassifications = {{
                'Reporting': ['q1','q2','q3','q5','q7','q12','q13','q15','q17','q18','q20','q25','q26','q42','q43','q52','q53','q55','q62','q89','q98','q99'],
                'Ad-hoc': ['q6','q8','q19','q32','q34','q40','q45','q46','q48','q61','q63','q68','q73','q79','q88','q90','q92','q96'],
                'OLAP': ['q4','q9','q10','q11','q14a','q14b','q22','q23a','q23b','q27','q28','q31','q33','q35','q36','q38','q44','q47','q49','q51','q54','q56','q57','q58','q59','q60','q64','q65','q66','q67','q70','q71','q74','q75','q76','q77','q78','q80','q86','q87','q97'],
                'Data Mining': ['q16','q21','q24a','q24b','q29','q30','q37','q39a','q39b','q41','q50','q69','q72','q81','q82','q83','q84','q85','q91','q93','q94','q95']
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
                const dbxSize = document.getElementById('dbxSizeSelector').value;
                
                const sfTimes = sfRawData[sfSize] || {{}};
                const dbxTimes = dbxRawData[dbxSize] || {{}};
                
                // Find common queries
                const allQueries = [...new Set([...Object.keys(sfTimes), ...Object.keys(dbxTimes)])].sort();
                const commonQueries = allQueries.filter(q => sfTimes[q] && dbxTimes[q] && sfTimes[q] > 0 && dbxTimes[q] > 0);
                
                // Compute comparison
                let sfWins = 0, dbxWins = 0, close = 0;
                const comparisons = [];
                const categoryStats = {{}};
                
                for (const q of commonQueries) {{
                    const sfT = sfTimes[q];
                    const dbxT = dbxTimes[q];
                    const diffPct = ((dbxT - sfT) / dbxT) * 100;
                    const category = getCategory(q);
                    
                    let winner;
                    if (Math.abs(diffPct) < 5) {{
                        winner = 'close';
                        close++;
                    }} else if (diffPct > 0) {{
                        winner = 'sf';
                        sfWins++;
                    }} else {{
                        winner = 'dbx';
                        dbxWins++;
                    }}
                    
                    comparisons.push({{ query: q, sfTime: sfT, dbxTime: dbxT, diffPct, winner, category }});
                    
                    if (!categoryStats[category]) categoryStats[category] = {{ total: 0, sfWins: 0, dbxWins: 0, close: 0, totalDiff: 0 }};
                    categoryStats[category].total++;
                    categoryStats[category].totalDiff += diffPct;
                    if (winner === 'sf') categoryStats[category].sfWins++;
                    else if (winner === 'dbx') categoryStats[category].dbxWins++;
                    else categoryStats[category].close++;
                }}
                
                // Sort by SF advantage
                comparisons.sort((a, b) => b.diffPct - a.diffPct);
                
                const total = comparisons.length;
                const sfPct = Math.round(sfWins / total * 100);
                const dbxPct = Math.round(dbxWins / total * 100);
                const winnerClass = sfWins > dbxWins ? 'winner' : '';
                
                // Build category rows
                let catRows = '';
                const catColors = {{'Reporting': '#e3f2fd', 'Ad-hoc': '#fff3e0', 'OLAP': '#f3e5f5', 'Data Mining': '#e8f5e9'}};
                for (const [cat, stats] of Object.entries(categoryStats)) {{
                    const bg = catColors[cat] || '#f5f5f5';
                    const avgDiff = stats.totalDiff / stats.total;
                    const diffColor = avgDiff > 0 ? '#29b5e8' : '#ff6b35';
                    const dominant = stats.sfWins > stats.dbxWins ? '<strong style="color:#29b5e8">SF</strong>' : 
                                     stats.dbxWins > stats.sfWins ? '<strong style="color:#ff6b35">DBX</strong>' : '—';
                    catRows += `<tr>
                        <td><span style="background:${{bg}};padding:2px 8px;border-radius:3px;font-weight:600;">${{cat}}</span></td>
                        <td style="text-align:right;">${{stats.total}}</td>
                        <td style="text-align:right;color:#29b5e8;">${{stats.sfWins}}</td>
                        <td style="text-align:right;color:#ff6b35;">${{stats.dbxWins}}</td>
                        <td style="text-align:right;color:#888;">${{stats.close}}</td>
                        <td style="text-align:right;color:${{diffColor}};">${{avgDiff > 0 ? '+' : ''}}${{avgDiff.toFixed(1)}}%</td>
                        <td>${{dominant}}</td>
                    </tr>`;
                }}
                
                // Build query rows
                let queryRows = '';
                for (const c of comparisons) {{
                    const diffColor = c.diffPct > 5 ? '#29b5e8' : c.diffPct < -5 ? '#ff6b35' : '#888';
                    const winnerBadge = c.winner === 'sf' ? '<span style="background:#e3f2fd;color:#29b5e8;padding:2px 8px;border-radius:3px;font-weight:600;">SF</span>' :
                                        c.winner === 'dbx' ? '<span style="background:#fff3e0;color:#ff6b35;padding:2px 8px;border-radius:3px;font-weight:600;">DBX</span>' :
                                        '<span style="color:#888;">≈</span>';
                    
                    queryRows += `<tr class="query-row" data-query="${{c.query}}" onclick="showScalingCurve('${{c.query}}')" style="cursor:pointer;">
                        <td><strong>${{c.query}}</strong></td>
                        <td style="font-size:0.85em;color:#666;">${{c.category}}</td>
                        <td style="text-align:right;">${{c.sfTime.toFixed(2)}}</td>
                        <td style="text-align:right;">${{c.dbxTime.toFixed(2)}}</td>
                        <td style="text-align:right;color:${{diffColor}};font-weight:600;">${{c.diffPct > 0 ? '+' : ''}}${{c.diffPct.toFixed(1)}}%</td>
                        <td style="text-align:center;">${{winnerBadge}}</td>
                    </tr>`;
                }}
                
                // Render HTML
                document.getElementById('h2hComparisonContent').innerHTML = `
                    <div class="summary-row">
                        <div class="card sf">
                            <div class="label">SF Wins</div>
                            <div class="value">${{sfWins}}</div>
                            <div class="detail">${{sfPct}}% of queries</div>
                        </div>
                        <div class="card dbx">
                            <div class="label">DBX Wins</div>
                            <div class="value">${{dbxWins}}</div>
                            <div class="detail">${{dbxPct}}% of queries</div>
                        </div>
                        <div class="card">
                            <div class="label">Close (&lt;5%)</div>
                            <div class="value">${{close}}</div>
                            <div class="detail">too close to call</div>
                        </div>
                    </div>
                    
                    <div class="insight-box ${{winnerClass}}">
                        <strong>Summary:</strong> Comparing SF ${{sfSize}} vs DBX ${{dbxSize}}, Snowflake is faster on <strong>${{sfWins}}</strong> queries 
                        while Databricks wins on <strong>${{dbxWins}}</strong>. 
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
                                    <th style="text-align:right;">DBX Wins</th>
                                    <th style="text-align:right;">Close</th>
                                    <th style="text-align:right;">Avg SF Advantage</th>
                                    <th style="text-align:left;">Dominant</th>
                                </tr>
                            </thead>
                            <tbody>${{catRows}}</tbody>
                        </table>
                    </div>
                    
                    <h3>Speed Advantage Chart</h3>
                    <div class="chart-container" style="height:400px;">
                        <canvas id="h2hChart"></canvas>
                    </div>
                    
                    <h3>Query Comparison <span style="font-weight:normal;font-size:0.8em;color:#666;">(click a row to see scaling curve)</span></h3>
                    <div class="table-container" style="max-height:500px;overflow-y:auto;">
                        <table>
                            <thead style="position:sticky;top:0;background:white;">
                                <tr>
                                    <th style="text-align:left;">Query</th>
                                    <th style="text-align:left;">Category</th>
                                    <th style="text-align:right;">SF ${{sfSize}} (s)</th>
                                    <th style="text-align:right;">DBX ${{dbxSize}} (s)</th>
                                    <th style="text-align:right;">SF Advantage</th>
                                    <th style="text-align:center;">Faster</th>
                                </tr>
                            </thead>
                            <tbody>${{queryRows}}</tbody>
                        </table>
                    </div>
                    
                    <h2 style="margin-top:40px;border-top:2px solid #eee;padding-top:20px;">Scaling Overview</h2>
                    <p style="color:#666;margin-bottom:20px;">
                        How each platform scales as data size increases. Scaling factor = time at largest size ÷ time at smallest size. 
                        <strong>Lower is better</strong> (means performance degrades less with more data).
                    </p>
                    
                    <div id="scalingOverviewContent"></div>
                    
                    <h3 style="margin-top:30px;">Individual Query Scaling</h3>
                    <p style="color:#666;">Click a query row above or select below to see detailed scaling curve.</p>
                    <div style="display:flex;align-items:center;gap:10px;margin-bottom:15px;">
                        <label>Query:</label>
                        <select id="scalingQuerySelector" onchange="showScalingCurve(this.value)" style="padding:6px 12px;border-radius:4px;border:1px solid #ccc;">
                            <option value="">-- Select Query --</option>
                            ${{comparisons.map(c => `<option value="${{c.query}}">${{c.query}} (${{c.category}})</option>`).join('')}}
                        </select>
                    </div>
                    <div id="scalingCurveContainer" style="display:none;">
                        <div class="chart-container" style="height:350px;">
                            <canvas id="scalingCurveChart"></canvas>
                        </div>
                        <div id="scalingCurveStats" style="margin-top:15px;padding:15px;background:#f8f9fa;border-radius:8px;"></div>
                    </div>
                `;
                
                // Render scaling overview
                renderScalingOverview();
                
                // Destroy old charts
                if (h2hCharts.h2h) h2hCharts.h2h.destroy();
                
                // Speed chart
                const h2hChartEl = document.getElementById('h2hChart');
                if (h2hChartEl) {{
                    h2hCharts.h2h = new Chart(h2hChartEl, {{
                        type: 'bar',
                        data: {{
                            labels: comparisons.map(d => d.query),
                            datasets: [{{
                                label: 'SF Advantage %',
                                data: comparisons.map(d => d.diffPct),
                                backgroundColor: comparisons.map(d => d.diffPct > 5 ? '#29b5e8' : d.diffPct < -5 ? '#ff6b35' : '#ccc'),
                                borderWidth: 0
                            }}]
                        }},
                        options: {{
                            indexAxis: 'y',
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {{
                                legend: {{ display: false }},
                                tooltip: {{
                                    callbacks: {{
                                        label: ctx => ctx.raw > 0 ? `SF ${{ctx.raw.toFixed(1)}}% faster` : `DBX ${{Math.abs(ctx.raw).toFixed(1)}}% faster`
                                    }}
                                }}
                            }},
                            scales: {{
                                x: {{ title: {{ display: true, text: 'SF Advantage %' }}, grid: {{ color: '#eee' }} }},
                                y: {{ ticks: {{ font: {{ size: 9 }} }} }}
                            }}
                        }}
                    }});
                }}
            }}
            
            function renderScalingOverview() {{
                const orderedSfSizes = sizeOrder.filter(s => sfSizes.includes(s));
                const orderedDbxSizes = sizeOrder.filter(s => dbxSizes.includes(s));
                
                // Get all queries
                const allQueries = [...new Set([
                    ...Object.values(sfRawData).flatMap(d => Object.keys(d)),
                    ...Object.values(dbxRawData).flatMap(d => Object.keys(d))
                ])].sort();
                
                // Compute geomean at each size
                function geomean(arr) {{
                    const valid = arr.filter(v => v > 0);
                    if (valid.length === 0) return null;
                    return Math.exp(valid.reduce((sum, v) => sum + Math.log(v), 0) / valid.length);
                }}
                
                const sfGeomeans = orderedSfSizes.map(size => {{
                    const times = allQueries.map(q => sfRawData[size]?.[q]).filter(t => t > 0);
                    return geomean(times);
                }});
                
                const dbxGeomeans = orderedDbxSizes.map(size => {{
                    const times = allQueries.map(q => dbxRawData[size]?.[q]).filter(t => t > 0);
                    return geomean(times);
                }});
                
                // Compute per-query scaling factors
                const scalingData = [];
                for (const q of allQueries) {{
                    const sfTimes = orderedSfSizes.map(s => sfRawData[s]?.[q]).filter(t => t > 0);
                    const dbxTimes = orderedDbxSizes.map(s => dbxRawData[s]?.[q]).filter(t => t > 0);
                    
                    const sfFactor = sfTimes.length >= 2 ? sfTimes[sfTimes.length - 1] / sfTimes[0] : null;
                    const dbxFactor = dbxTimes.length >= 2 ? dbxTimes[dbxTimes.length - 1] / dbxTimes[0] : null;
                    
                    let winner = null;
                    let scalingDiff = null;
                    if (sfFactor && dbxFactor) {{
                        scalingDiff = ((dbxFactor - sfFactor) / dbxFactor) * 100;
                        if (Math.abs(scalingDiff) < 5) winner = 'close';
                        else if (scalingDiff > 0) winner = 'sf';
                        else winner = 'dbx';
                    }}
                    
                    scalingData.push({{
                        query: q,
                        category: getCategory(q),
                        sfFactor,
                        dbxFactor,
                        scalingDiff,
                        winner
                    }});
                }}
                
                // Sort by SF advantage (biggest SF wins first, same as speed chart)
                scalingData.sort((a, b) => (b.scalingDiff || -999) - (a.scalingDiff || -999));
                
                // Count winners
                const sfScalesBetter = scalingData.filter(d => d.winner === 'sf').length;
                const dbxScalesBetter = scalingData.filter(d => d.winner === 'dbx').length;
                const scalingClose = scalingData.filter(d => d.winner === 'close').length;
                
                // Build scaling table rows
                let scalingRows = '';
                for (const d of scalingData) {{
                    if (!d.sfFactor && !d.dbxFactor) continue;
                    const sfStr = d.sfFactor ? d.sfFactor.toFixed(2) + '×' : '—';
                    const dbxStr = d.dbxFactor ? d.dbxFactor.toFixed(2) + '×' : '—';
                    const diffStr = d.scalingDiff !== null ? (d.scalingDiff > 0 ? '+' : '') + d.scalingDiff.toFixed(1) + '%' : '—';
                    const diffColor = d.scalingDiff > 5 ? '#29b5e8' : d.scalingDiff < -5 ? '#ff6b35' : '#888';
                    const winnerBadge = d.winner === 'sf' ? '<span style="background:#e3f2fd;color:#29b5e8;padding:2px 8px;border-radius:3px;font-weight:600;">SF</span>' :
                                        d.winner === 'dbx' ? '<span style="background:#fff3e0;color:#ff6b35;padding:2px 8px;border-radius:3px;font-weight:600;">DBX</span>' :
                                        d.winner === 'close' ? '<span style="color:#888;">≈</span>' : '—';
                    
                    scalingRows += `<tr class="query-row" data-query="${{d.query}}" onclick="showScalingCurve('${{d.query}}')" style="cursor:pointer;">
                        <td><strong>${{d.query}}</strong></td>
                        <td style="font-size:0.85em;color:#666;">${{d.category}}</td>
                        <td style="text-align:right;color:#29b5e8;">${{sfStr}}</td>
                        <td style="text-align:right;color:#ff6b35;">${{dbxStr}}</td>
                        <td style="text-align:right;color:${{diffColor}};font-weight:600;">${{diffStr}}</td>
                        <td style="text-align:center;">${{winnerBadge}}</td>
                    </tr>`;
                }}
                
                // Compute overall scaling factors
                const sfOverallFactor = sfGeomeans.length >= 2 && sfGeomeans[0] && sfGeomeans[sfGeomeans.length - 1] 
                    ? sfGeomeans[sfGeomeans.length - 1] / sfGeomeans[0] : null;
                const dbxOverallFactor = dbxGeomeans.length >= 2 && dbxGeomeans[0] && dbxGeomeans[dbxGeomeans.length - 1]
                    ? dbxGeomeans[dbxGeomeans.length - 1] / dbxGeomeans[0] : null;
                
                const sfRange = orderedSfSizes.length >= 2 ? `${{orderedSfSizes[0]}} → ${{orderedSfSizes[orderedSfSizes.length - 1]}}` : '';
                const dbxRange = orderedDbxSizes.length >= 2 ? `${{orderedDbxSizes[0]}} → ${{orderedDbxSizes[orderedDbxSizes.length - 1]}}` : '';
                
                document.getElementById('scalingOverviewContent').innerHTML = `
                    <div class="summary-row">
                        <div class="card sf">
                            <div class="label">SF Scales Better</div>
                            <div class="value">${{sfScalesBetter}}</div>
                            <div class="detail">queries</div>
                        </div>
                        <div class="card dbx">
                            <div class="label">DBX Scales Better</div>
                            <div class="value">${{dbxScalesBetter}}</div>
                            <div class="detail">queries</div>
                        </div>
                        <div class="card">
                            <div class="label">Similar Scaling</div>
                            <div class="value">${{scalingClose}}</div>
                            <div class="detail">within 5%</div>
                        </div>
                    </div>
                    
                    <div class="insight-box ${{sfScalesBetter > dbxScalesBetter ? 'winner' : ''}}">
                        <strong>Scaling Summary:</strong> 
                        Snowflake scales better on <strong>${{sfScalesBetter}}</strong> queries while Databricks scales better on <strong>${{dbxScalesBetter}}</strong>.
                        ${{sfOverallFactor && dbxOverallFactor ? `Overall workload scaling: SF ${{sfOverallFactor.toFixed(2)}}× (${{sfRange}}) vs DBX ${{dbxOverallFactor.toFixed(2)}}× (${{dbxRange}}).` : ''}}
                    </div>
                    
                    <h3>Aggregate Scaling Curves (Geomean)</h3>
                    <p style="color:#666;margin-bottom:10px;">Geometric mean of all query times at each warehouse size. Shows how each platform scales overall.</p>
                    <div class="chart-container" style="height:350px;">
                        <canvas id="aggregateScalingChart"></canvas>
                    </div>
                    
                    <h3 style="margin-top:30px;">Scaling Advantage Chart</h3>
                    <p style="color:#666;margin-bottom:10px;">SF scaling advantage per query. Positive (blue) = SF scales better, Negative (orange) = DBX scales better.</p>
                    <div class="chart-container" style="height:450px;">
                        <canvas id="scalingFactorChart"></canvas>
                    </div>
                    
                    <h3 style="margin-top:30px;">Full Scaling Table</h3>
                    <p style="color:#666;">All queries with scaling factors. Click a row to see detailed curve.</p>
                    <div class="table-container" style="max-height:400px;overflow-y:auto;">
                        <table>
                            <thead style="position:sticky;top:0;background:white;">
                                <tr>
                                    <th style="text-align:left;">Query</th>
                                    <th style="text-align:left;">Category</th>
                                    <th style="text-align:right;">SF Factor</th>
                                    <th style="text-align:right;">DBX Factor</th>
                                    <th style="text-align:right;">SF Advantage</th>
                                    <th style="text-align:center;">Better Scaling</th>
                                </tr>
                            </thead>
                            <tbody>${{scalingRows}}</tbody>
                        </table>
                    </div>
                `;
                
                // Destroy old charts
                if (h2hCharts.aggregateScaling) h2hCharts.aggregateScaling.destroy();
                if (h2hCharts.scalingFactor) h2hCharts.scalingFactor.destroy();
                
                // Aggregate scaling chart
                const allSizesForChart = sizeOrder.filter(s => sfSizes.includes(s) || dbxSizes.includes(s));
                const sfGeoForChart = allSizesForChart.map(s => {{
                    const idx = orderedSfSizes.indexOf(s);
                    return idx >= 0 ? sfGeomeans[idx] : null;
                }});
                const dbxGeoForChart = allSizesForChart.map(s => {{
                    const idx = orderedDbxSizes.indexOf(s);
                    return idx >= 0 ? dbxGeomeans[idx] : null;
                }});
                
                const aggCtx = document.getElementById('aggregateScalingChart');
                if (aggCtx) {{
                    h2hCharts.aggregateScaling = new Chart(aggCtx, {{
                        type: 'line',
                        data: {{
                            labels: allSizesForChart,
                            datasets: [
                                {{
                                    label: 'Snowflake (Geomean)',
                                    data: sfGeoForChart,
                                    borderColor: '#29b5e8',
                                    backgroundColor: 'rgba(41, 181, 232, 0.1)',
                                    borderWidth: 3,
                                    pointRadius: 8,
                                    pointBackgroundColor: '#29b5e8',
                                    tension: 0.3,
                                    fill: true,
                                    spanGaps: true
                                }},
                                {{
                                    label: 'Databricks (Geomean)',
                                    data: dbxGeoForChart,
                                    borderColor: '#ff6b35',
                                    backgroundColor: 'rgba(255, 107, 53, 0.1)',
                                    borderWidth: 3,
                                    pointRadius: 8,
                                    pointBackgroundColor: '#ff6b35',
                                    tension: 0.3,
                                    fill: true,
                                    spanGaps: true
                                }}
                            ]
                        }},
                        options: {{
                            responsive: true,
                            maintainAspectRatio: false,
                            interaction: {{ intersect: false, mode: 'index' }},
                            plugins: {{
                                title: {{ display: true, text: 'Overall Workload Scaling (Geomean Time)', font: {{ size: 14 }} }},
                                tooltip: {{
                                    callbacks: {{
                                        label: ctx => `${{ctx.dataset.label}}: ${{ctx.raw ? ctx.raw.toFixed(2) + 's' : 'N/A'}}`
                                    }}
                                }}
                            }},
                            scales: {{
                                x: {{ title: {{ display: true, text: 'Warehouse Size' }} }},
                                y: {{ title: {{ display: true, text: 'Geomean Time (seconds)' }}, beginAtZero: true }}
                            }}
                        }}
                    }});
                }}
                
                // Scaling factor comparison chart (SF advantage %, same style as speed chart)
                const validScaling = scalingData.filter(d => d.scalingDiff !== null);
                const factorCtx = document.getElementById('scalingFactorChart');
                if (factorCtx) {{
                    h2hCharts.scalingFactor = new Chart(factorCtx, {{
                        type: 'bar',
                        data: {{
                            labels: validScaling.map(d => d.query),
                            datasets: [{{
                                label: 'SF Scaling Advantage %',
                                data: validScaling.map(d => d.scalingDiff),
                                backgroundColor: validScaling.map(d => d.scalingDiff > 5 ? '#29b5e8' : d.scalingDiff < -5 ? '#ff6b35' : '#ccc'),
                                borderWidth: 0
                            }}]
                        }},
                        options: {{
                            indexAxis: 'y',
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {{
                                legend: {{ display: false }},
                                tooltip: {{
                                    callbacks: {{
                                        label: ctx => ctx.raw > 0 ? `SF scales ${{ctx.raw.toFixed(1)}}% better` : `DBX scales ${{Math.abs(ctx.raw).toFixed(1)}}% better`
                                    }}
                                }}
                            }},
                            scales: {{
                                x: {{ title: {{ display: true, text: 'SF Scaling Advantage %' }}, grid: {{ color: '#eee' }} }},
                                y: {{ ticks: {{ font: {{ size: 9 }} }} }}
                            }}
                        }}
                    }});
                }}
            }}
            
            function showScalingCurve(query) {{
                if (!query) {{
                    document.getElementById('scalingCurveContainer').style.display = 'none';
                    return;
                }}
                
                document.getElementById('scalingCurveContainer').style.display = 'block';
                document.getElementById('scalingQuerySelector').value = query;
                
                // Highlight selected row
                document.querySelectorAll('.query-row').forEach(row => {{
                    row.style.background = row.dataset.query === query ? '#f0f7ff' : '';
                }});
                
                // Get scaling data for this query
                const sfPoints = [];
                const dbxPoints = [];
                const orderedSfSizes = sizeOrder.filter(s => sfSizes.includes(s));
                const orderedDbxSizes = sizeOrder.filter(s => dbxSizes.includes(s));
                
                for (const size of orderedSfSizes) {{
                    if (sfRawData[size] && sfRawData[size][query]) {{
                        sfPoints.push({{ size, time: sfRawData[size][query] }});
                    }}
                }}
                
                for (const size of orderedDbxSizes) {{
                    if (dbxRawData[size] && dbxRawData[size][query]) {{
                        dbxPoints.push({{ size, time: dbxRawData[size][query] }});
                    }}
                }}
                
                // Build combined size labels
                const allSizesUsed = [...new Set([...sfPoints.map(p => p.size), ...dbxPoints.map(p => p.size)])];
                const orderedLabels = sizeOrder.filter(s => allSizesUsed.includes(s));
                
                // Map data to labels
                const sfData = orderedLabels.map(s => {{
                    const pt = sfPoints.find(p => p.size === s);
                    return pt ? pt.time : null;
                }});
                const dbxData = orderedLabels.map(s => {{
                    const pt = dbxPoints.find(p => p.size === s);
                    return pt ? pt.time : null;
                }});
                
                // Destroy old chart
                if (h2hCharts.scaling) h2hCharts.scaling.destroy();
                
                // Create scaling curve chart
                const ctx = document.getElementById('scalingCurveChart');
                h2hCharts.scaling = new Chart(ctx, {{
                    type: 'line',
                    data: {{
                        labels: orderedLabels,
                        datasets: [
                            {{
                                label: 'Snowflake',
                                data: sfData,
                                borderColor: '#29b5e8',
                                backgroundColor: 'rgba(41, 181, 232, 0.1)',
                                borderWidth: 3,
                                pointRadius: 6,
                                pointBackgroundColor: '#29b5e8',
                                tension: 0.3,
                                fill: true,
                                spanGaps: true
                            }},
                            {{
                                label: 'Databricks',
                                data: dbxData,
                                borderColor: '#ff6b35',
                                backgroundColor: 'rgba(255, 107, 53, 0.1)',
                                borderWidth: 3,
                                pointRadius: 6,
                                pointBackgroundColor: '#ff6b35',
                                tension: 0.3,
                                fill: true,
                                spanGaps: true
                            }}
                        ]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        interaction: {{
                            intersect: false,
                            mode: 'index'
                        }},
                        plugins: {{
                            title: {{
                                display: true,
                                text: `Scaling Curve: ${{query}} (${{getCategory(query)}})`,
                                font: {{ size: 16, weight: 'bold' }}
                            }},
                            legend: {{
                                position: 'top'
                            }},
                            tooltip: {{
                                callbacks: {{
                                    label: ctx => `${{ctx.dataset.label}}: ${{ctx.raw ? ctx.raw.toFixed(2) + 's' : 'N/A'}}`
                                }}
                            }}
                        }},
                        scales: {{
                            x: {{
                                title: {{ display: true, text: 'Warehouse Size' }},
                                grid: {{ color: '#eee' }}
                            }},
                            y: {{
                                title: {{ display: true, text: 'Time (seconds)' }},
                                grid: {{ color: '#eee' }},
                                beginAtZero: true
                            }}
                        }}
                    }}
                }});
                
                // Compute scaling stats
                let statsHtml = '<div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(200px, 1fr));gap:15px;">';
                
                // SF scaling factor (largest/smallest)
                const sfValid = sfPoints.filter(p => p.time > 0);
                const dbxValid = dbxPoints.filter(p => p.time > 0);
                
                if (sfValid.length >= 2) {{
                    const sfSmallest = sfValid[0];
                    const sfLargest = sfValid[sfValid.length - 1];
                    const sfScaling = sfLargest.time / sfSmallest.time;
                    statsHtml += `<div style="padding:10px;background:#e3f2fd;border-radius:6px;">
                        <div style="font-weight:600;color:#29b5e8;margin-bottom:5px;">SF Scaling (${{sfSmallest.size}} → ${{sfLargest.size}})</div>
                        <div style="font-size:1.5em;font-weight:bold;">${{sfScaling.toFixed(2)}}×</div>
                        <div style="font-size:0.85em;color:#666;">${{sfSmallest.time.toFixed(2)}}s → ${{sfLargest.time.toFixed(2)}}s</div>
                    </div>`;
                }}
                
                if (dbxValid.length >= 2) {{
                    const dbxSmallest = dbxValid[0];
                    const dbxLargest = dbxValid[dbxValid.length - 1];
                    const dbxScaling = dbxLargest.time / dbxSmallest.time;
                    statsHtml += `<div style="padding:10px;background:#fff3e0;border-radius:6px;">
                        <div style="font-weight:600;color:#ff6b35;margin-bottom:5px;">DBX Scaling (${{dbxSmallest.size}} → ${{dbxLargest.size}})</div>
                        <div style="font-size:1.5em;font-weight:bold;">${{dbxScaling.toFixed(2)}}×</div>
                        <div style="font-size:0.85em;color:#666;">${{dbxSmallest.time.toFixed(2)}}s → ${{dbxLargest.time.toFixed(2)}}s</div>
                    </div>`;
                }}
                
                // Winner by size
                let sizeWinners = '';
                for (const s of orderedLabels) {{
                    const sfT = sfRawData[s]?.[query];
                    const dbxT = dbxRawData[s]?.[query];
                    if (sfT && dbxT) {{
                        const diff = ((dbxT - sfT) / dbxT) * 100;
                        const winner = Math.abs(diff) < 5 ? '≈' : diff > 0 ? '<span style="color:#29b5e8">SF</span>' : '<span style="color:#ff6b35">DBX</span>';
                        sizeWinners += `<span style="margin-right:10px;"><strong>${{s}}:</strong> ${{winner}}</span>`;
                    }}
                }}
                if (sizeWinners) {{
                    statsHtml += `<div style="padding:10px;background:#f5f5f5;border-radius:6px;">
                        <div style="font-weight:600;margin-bottom:5px;">Winner by Size</div>
                        <div>${{sizeWinners}}</div>
                    </div>`;
                }}
                
                statsHtml += '</div>';
                document.getElementById('scalingCurveStats').innerHTML = statsHtml;
            }}
            
            // Initial render
            renderH2HComparison();
        </script>
    </div>
    
    <!-- Tab 6: SF Matrix -->
    <div id="sf-matrix" class="tab-content">
        <h2>Snowflake FDN Gen2 — Full Results</h2>
        
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Query</th>
                        {''.join(f'<th>SF {s}</th>' for s in sf_sizes)}
                        <th>Scaling</th>
                    </tr>
                </thead>
                <tbody>
                    <tr class="section-row"><td colspan="{len(sf_sizes)+2}">Query Times (seconds)</td></tr>
                    {sf_matrix_rows}
                    <tr class="section-row"><td colspan="{len(sf_sizes)+2}">Summary</td></tr>
                    {sf_summary}
                </tbody>
            </table>
        </div>
        
        <p class="footer">
            <strong>Pricing:</strong> Gen2 Standard Edition @ $2.70/credit<br>
            <strong>Credits/hr:</strong> S=2, M=4, L=8, XL=16, 2XL=32, 3XL=64
        </p>
    </div>
    
    <!-- Tab 4: DBX Matrix -->
    <div id="dbx-matrix" class="tab-content">
        <h2>Databricks Delta (Photon) — Full Results</h2>
        
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>Query</th>
                        {''.join(f'<th class="dbx">DBX {s}</th>' for s in dbx_sizes)}
                        <th>Scaling</th>
                    </tr>
                </thead>
                <tbody>
                    <tr class="section-row"><td colspan="{len(dbx_sizes)+2}">Query Times (seconds)</td></tr>
                    {dbx_matrix_rows}
                    <tr class="section-row"><td colspan="{len(dbx_sizes)+2}">Summary</td></tr>
                    {dbx_summary}
                </tbody>
            </table>
        </div>
        
        <p class="footer">
            <strong>Pricing:</strong> SQL Warehouse (DBU + Compute combined)<br>
            <strong>$/hr:</strong> S=$8.4, M=$16.8, L=$28, XL=$56, 2XL=$101, 3XL=$190
        </p>
    </div>
    
    <!-- Tab 8: Scaling Analysis -->
    <div id="scaling" class="tab-content">
        <h2>Scaling Efficiency: Snowflake vs Databricks</h2>
        <p style="color:var(--sf-gray);">
            How well do queries scale as warehouse size increases?
            Uses log-log regression: T = c × N<sup>β</sup>. Scaling Efficiency = |β| × 100%.
            Both platforms compared side-by-side across {', '.join(sf_ordered_sizes)} (SF) and {', '.join(dbx_ordered_sizes)} (DBX).
        </p>

        <div class="summary-row">
            <div class="card sf">
                <div class="label">SF Avg Efficiency</div>
                <div class="value">{sf_avg_eff:.0f}%</div>
                <div class="detail">across {len(sf_efficiencies)} queries</div>
            </div>
            <div class="card" style="background:#FFF5F4;border-color:#FF9900;">
                <div class="label">DBX Avg Efficiency</div>
                <div class="value" style="color:#FF9900;">{dbx_avg_eff:.0f}%</div>
                <div class="detail">across {len(dbx_efficiencies)} queries</div>
            </div>
            <div class="card" style="background:#e8f5e9;">
                <div class="label">SF Scales Better</div>
                <div class="value">{sf_scales_better_count}</div>
                <div class="detail">queries (&gt;5% gap)</div>
            </div>
            <div class="card" style="background:#fff3e0;">
                <div class="label">DBX Scales Better</div>
                <div class="value">{dbx_scales_better_count}</div>
                <div class="detail">queries (&gt;5% gap)</div>
            </div>
        </div>

        <div class="insight-box">
            <strong>What this means:</strong>
            A query with 100% efficiency gets 2× speedup from 2× compute.
            At 50%, 2× compute only gives 1.4× speedup.
            Queries with poor scaling may be bottlenecked on I/O, network, or serial operations.
            <br><br>
            <strong>Legend:</strong> 🟢 Good (≥70%) | 🟡 Moderate (40-70%) | 🔴 Poor (&lt;40%)
        </div>

        <div class="summary-row">
            <div class="card" style="background:#e8f5e9;">
                <div class="label">🟢 SF Good</div>
                <div class="value">{sf_good}</div>
            </div>
            <div class="card" style="background:#fff8e1;">
                <div class="label">🟡 SF Moderate</div>
                <div class="value">{sf_moderate}</div>
            </div>
            <div class="card" style="background:#ffebee;">
                <div class="label">🔴 SF Poor</div>
                <div class="value">{sf_poor}</div>
            </div>
            <div class="card" style="background:#e8f5e9;">
                <div class="label">🟢 DBX Good</div>
                <div class="value">{dbx_good}</div>
            </div>
            <div class="card" style="background:#fff8e1;">
                <div class="label">🟡 DBX Moderate</div>
                <div class="value">{dbx_moderate}</div>
            </div>
            <div class="card" style="background:#ffebee;">
                <div class="label">🔴 DBX Poor</div>
                <div class="value">{dbx_poor}</div>
            </div>
        </div>

        <h3>Query Scaling Matrix</h3>
        <p style="color:var(--sf-gray);">Sorted by SF scaling efficiency (best first). Sparklines show time across sizes.</p>
        <div class="table-container" style="max-height:600px;overflow-y:auto;">
            <table>
                <thead style="position:sticky;top:0;background:white;">
                    <tr>
                        <th style="text-align:left;">Query</th>
                        <th style="text-align:left;">Category</th>
                        <th style="text-align:center;color:#29B5E8;">SF Trend</th>
                        <th style="text-align:right;color:#29B5E8;">SF Eff.</th>
                        <th style="text-align:center;color:#FF9900;">DBX Trend</th>
                        <th style="text-align:right;color:#FF9900;">DBX Eff.</th>
                        <th style="text-align:center;">Better</th>
                    </tr>
                </thead>
                <tbody>
                    {scaling_rows_html}
                </tbody>
            </table>
        </div>
    </div>

    <!-- Tab 9: Query Reference -->
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
        <p><strong>DBX Pricing:</strong> $0.70/DBU (SQL Serverless) | <strong>DBX Sizes:</strong> {', '.join(dbx_sizes)}</p>
        <p><strong>Run Keys:</strong> SF: {', '.join(str(sf_data[s]["run_key"]) for s in sf_sizes)} | DBX: {', '.join(str(dbx_data[s]["run_key"]) for s in dbx_sizes)}</p>
        <p><strong>Generator:</strong> <code>scripts/generate-sf-vs-dbx-report.py</code></p>
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
    </script>
</body>
</html>'''
    
    return html


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='Generate SF FDN vs DBX Delta Price:Performance Report')
    parser.add_argument('--sf-runs', required=True, help='Comma-separated SF run keys')
    parser.add_argument('--sf-sizes', required=True, help='Comma-separated SF sizes (matching run order)')
    parser.add_argument('--dbx-runs', required=True, help='Comma-separated DBX run keys')
    parser.add_argument('--dbx-sizes', required=True, help='Comma-separated DBX sizes (matching run order)')
    parser.add_argument('--output', required=True, help='Output HTML file path')
    parser.add_argument('--publish', action='store_true',
                        help='Publish report to results/competitive/ with date-stamped filename')
    
    args = parser.parse_args()
    
    sf_runs = [int(x.strip()) for x in args.sf_runs.split(',')]
    sf_sizes = [x.strip() for x in args.sf_sizes.split(',')]
    dbx_runs = [int(x.strip()) for x in args.dbx_runs.split(',')]
    dbx_sizes = [x.strip() for x in args.dbx_sizes.split(',')]
    
    if len(sf_runs) != len(sf_sizes):
        print(f"ERROR: SF runs ({len(sf_runs)}) must match sizes ({len(sf_sizes)})")
        sys.exit(1)
    if len(dbx_runs) != len(dbx_sizes):
        print(f"ERROR: DBX runs ({len(dbx_runs)}) must match sizes ({len(dbx_sizes)})")
        sys.exit(1)
    
    publish_date = datetime.now().strftime("%Y-%m-%d") if args.publish else None
    
    print("Connecting to Snowflake...")
    conn = get_snowflake_connection()
    
    # Fetch SF data
    sf_data = {}
    for run_key, size in zip(sf_runs, sf_sizes):
        print(f"Fetching SF {size} run {run_key}...")
        times = fetch_query_times(conn, run_key, 'snowflake')
        metadata = fetch_run_metadata(conn, run_key)
        sf_data[size] = {'run_key': run_key, 'times': times, 'metadata': metadata}
    
    # Fetch DBX data
    dbx_data = {}
    for run_key, size in zip(dbx_runs, dbx_sizes):
        print(f"Fetching DBX {size} run {run_key}...")
        times = fetch_query_times(conn, run_key, 'databricks')
        metadata = fetch_run_metadata(conn, run_key)
        dbx_data[size] = {'run_key': run_key, 'times': times, 'metadata': metadata}
    
    conn.close()
    
    print("Generating HTML report...")
    generate_html(sf_data, dbx_data, args.output, publish_date=publish_date)
    
    if args.publish:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(script_dir)
        results_dir = os.path.join(project_root, 'results', 'competitive')
        os.makedirs(results_dir, exist_ok=True)
        publish_filename = f"sf-vs-databricks-tpcds-10tb-{publish_date}.html"
        publish_path = os.path.join(results_dir, publish_filename)
        shutil.copy2(args.output, publish_path)
        print(f"Published: {publish_path}")
    
    print("Done!")


if __name__ == '__main__':
    main()
