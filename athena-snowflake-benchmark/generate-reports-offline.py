#!/usr/bin/env python3
"""
Offline report generator - feeds pre-fetched JSON data into generate-tpcds-price-perf.py
without needing a live Snowflake connection.

This script patches get_snowflake_connection() and the fetch functions to use cached data,
then delegates to the main report generator.
"""
import json
import sys
import os
import re

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def normalize_query(label):
    """Normalize query label: q_tpcds_07_warm -> q7, q_tpcds_14P1_warm -> q14a"""
    # Extract query part
    m = re.match(r'q_tpcds_(\d+)(P[12]|[a-zA-Z]*)_warm', label)
    if not m:
        return None
    num = str(int(m.group(1)))  # remove leading zeros
    suffix = m.group(2)
    suffix = suffix.replace('P1', 'a').replace('P2', 'b')
    return f'q{num}{suffix}'


def build_times_dict(rows):
    """Convert list of [query_label, seconds] to normalized dict."""
    result = {}
    for label, sec in rows:
        if sec is None:
            continue
        q = normalize_query(label)
        if q:
            result[q] = round(sec, 2)
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Generate TPC-DS reports from pre-fetched data')
    parser.add_argument('--data-file', required=True, help='JSON file with pre-fetched benchmark data')
    parser.add_argument('--output', required=True, help='Output HTML file path')
    parser.add_argument('--sf-label', default='Gen2 Iceberg', help='Label for SF data format')
    parser.add_argument('--competitor-data-scanned-gb', type=float, help='GB scanned by competitor (overrides JSON value)')
    parser.add_argument('--competitor-cost', type=float, help='Competitor cost in USD (overrides JSON and auto-calc)')
    parser.add_argument('--publish', action='store_true', help='Publish with date-stamped filename')
    args = parser.parse_args()

    with open(args.data_file) as f:
        data = json.load(f)

    # Build sf_data structure
    sf_data = {}
    for size_entry in data['sf_runs']:
        size = size_entry['size']
        times = build_times_dict(size_entry['query_times'])
        meta = size_entry['metadata']
        # Clean run_date
        run_date = str(meta.get('run_date', '')).strip('"')
        sf_data[size] = {
            'run_key': meta['run_key'],
            'times': times,
            'metadata': {
                'run_key': meta['run_key'],
                'run_date': run_date,
                'platform': meta.get('platform', 'snowflake'),
                'wh_size': meta.get('wh_size', size),
                'wh_type': meta.get('wh_type', 'GEN2'),
                'data_format': meta.get('data_format', 'iceberg'),
                'warm_queries': meta.get('warm_queries', len(times))
            }
        }

    # Build competitor_data structure
    comp = data['competitor']
    comp_times = build_times_dict(comp['query_times'])
    comp_run_date = str(comp['metadata'].get('run_date', '')).strip('"')

    # Resolve data_scanned_gb: CLI flag > JSON field > None
    data_scanned_gb = args.competitor_data_scanned_gb
    if data_scanned_gb is None:
        data_scanned_gb = comp.get('data_scanned_gb')

    # Resolve cost: CLI flag > auto-calc from GB > JSON field
    comp_cost = args.competitor_cost
    if comp_cost is None and data_scanned_gb is not None:
        comp_cost = 5.0 * data_scanned_gb / 1000.0
        print(f"Competitor cost: ${comp_cost:.2f} (derived from {data_scanned_gb:.4f} GB × $5/TB)")
    elif comp_cost is None:
        comp_cost = comp['cost']

    competitor_data = {
        'name': comp['name'],
        'run_key': comp['run_key'],
        'times': comp_times,
        'cost': comp_cost,
        'data_scanned_gb': data_scanned_gb,
        'metadata': {
            'run_key': comp['run_key'],
            'run_date': comp_run_date,
            'platform': comp['metadata'].get('platform', 'athena'),
            'wh_size': comp['metadata'].get('wh_size'),
            'wh_type': comp['metadata'].get('wh_type'),
            'data_format': comp['metadata'].get('data_format', 'iceberg'),
            'warm_queries': comp['metadata'].get('warm_queries', len(comp_times))
        }
    }

    # Now import the main module's generate_html function
    # We need to import the module by manipulating the path
    import importlib.util
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'generate-tpcds-price-perf.py')
    spec = importlib.util.spec_from_file_location("report_gen", script_path)
    mod = importlib.util.module_from_spec(spec)
    
    # We need to prevent the module from running main() on import
    # The module likely has if __name__ == '__main__' guard, so this should be safe
    spec.loader.exec_module(mod)

    publish_date = None
    if args.publish:
        from datetime import datetime
        publish_date = datetime.now().strftime("%Y-%m-%d")

    print(f"Generating report: {args.output}")
    print(f"  SF label: {args.sf_label}")
    print(f"  SF sizes: {list(sf_data.keys())}")
    print(f"  Competitor: {competitor_data['name']}")
    print(f"  Queries: SF={len(list(sf_data.values())[0]['times'])}, Comp={len(competitor_data['times'])}")

    mod.generate_html(sf_data, competitor_data, args.output, publish_date=publish_date, sf_label=args.sf_label)
    print(f"Report written: {args.output}")

    # Publish
    if args.publish:
        import shutil
        script_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(script_dir)
        results_dir = os.path.join(project_root, 'results', 'competitive')
        os.makedirs(results_dir, exist_ok=True)

        comp_slug = competitor_data['name'].lower().replace(' ', '-')
        publish_filename = f"sf-vs-{comp_slug}-tpcds-10tb-{publish_date}.html"
        publish_path = os.path.join(results_dir, publish_filename)
        shutil.copy2(args.output, publish_path)
        print(f"Published: {publish_path}")

        latest_filename = f"sf-vs-{comp_slug}-tpcds-10tb_latest.html"
        latest_path = os.path.join(results_dir, latest_filename)
        shutil.copy2(args.output, latest_path)
        print(f"Latest:    {latest_path}")


if __name__ == '__main__':
    main()
