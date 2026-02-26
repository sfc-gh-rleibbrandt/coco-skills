"""
Shared TPC-DS query classification and category breakdown utilities.

Used by all TPC-DS benchmark report generators to produce consistent
"Per-Size Category Breakdown" tables across competitors.

Categories come from the TPC-DS specification's workload classification:
  - Reporting (22 queries): Periodic, known-pattern reports
  - Ad-hoc (18 queries): User-driven exploratory queries  
  - OLAP (41 queries): Complex analytical processing
  - Data Mining (22 queries): Deep pattern discovery

Total: 103 queries (99 base + 4 split queries: q14a/b, q23a/b, q24a/b, q39a/b)
"""

import math
from typing import Dict, List, Optional, Tuple

# =============================================================================
# TPC-DS QUERY CLASSIFICATIONS (per TPC-DS spec)
# =============================================================================

# Canonical form uses zero-padded single-digit numbers (q01, q02, ... q09)
# to match the TPC-DS spec. The lookup functions handle both padded (q01)
# and unpadded (q1) query names transparently.

QUERY_CLASSIFICATIONS = {
    'Reporting': [
        'q01','q02','q03','q05','q07','q12','q13','q15','q17','q18',
        'q20','q25','q26','q42','q43','q52','q53','q55','q62','q89','q98','q99'
    ],
    'Ad-hoc': [
        'q06','q08','q19','q32','q34','q40','q45','q46','q48','q61',
        'q63','q68','q73','q79','q88','q90','q92','q96'
    ],
    'OLAP': [
        'q04','q09','q10','q11','q14a','q14b','q22','q23a','q23b','q27',
        'q28','q31','q33','q35','q36','q38','q44','q47','q49','q51',
        'q54','q56','q57','q58','q59','q60','q64','q65','q66','q67',
        'q70','q71','q74','q75','q76','q77','q78','q80','q86','q87','q97'
    ],
    'Data Mining': [
        'q16','q21','q24a','q24b','q29','q30','q37','q39a','q39b','q41',
        'q50','q69','q72','q81','q82','q83','q84','q85','q91','q93','q94','q95'
    ]
}

# Pre-build reverse lookup: query_name -> category (both padded and unpadded)
_QUERY_TO_CATEGORY = {}
for _cat, _queries in QUERY_CLASSIFICATIONS.items():
    for _q in _queries:
        _QUERY_TO_CATEGORY[_q] = _cat
        # Also register unpadded form: q01 -> q1, q06 -> q6
        _unpadded = _q.replace('q0', 'q', 1) if _q.startswith('q0') and len(_q) > 2 and _q[2:3].isdigit() else _q
        if _unpadded != _q:
            _QUERY_TO_CATEGORY[_unpadded] = _cat


def get_category(query_name: str) -> Optional[str]:
    """Get the TPC-DS category for a query name. Handles both q01 and q1 formats."""
    return _QUERY_TO_CATEGORY.get(query_name)


def get_category_queries(category: str, padded: bool = True) -> List[str]:
    """Get query names for a category. Set padded=False for q1/q2 format."""
    queries = QUERY_CLASSIFICATIONS.get(category, [])
    if not padded:
        return [q.replace('q0', 'q', 1) if q.startswith('q0') and len(q) > 2 and q[2:3].isdigit() else q for q in queries]
    return queries


# =============================================================================
# CORE MATH FUNCTIONS
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
    valid = [v for v in values if v and v > 0]
    return round(sum(valid), 1)


# =============================================================================
# CATEGORY BREAKDOWN FUNCTIONS
# =============================================================================

def _lookup_time(times: Dict[str, float], query: str) -> Optional[float]:
    """Look up a query time, trying both padded (q01) and unpadded (q1) forms."""
    t = times.get(query)
    if t is not None:
        return t
    # Try the alternate form
    if query.startswith('q0') and len(query) > 2 and query[2:3].isdigit():
        # Padded -> try unpadded: q01 -> q1
        return times.get(query.replace('q0', 'q', 1))
    elif query.startswith('q') and len(query) >= 2 and query[1:2].isdigit():
        # Unpadded -> try padded: q1 -> q01 (only for single-digit)
        num_part = query[1:]
        if len(num_part) >= 1 and num_part[0].isdigit() and (len(num_part) == 1 or not num_part[1].isdigit()):
            return times.get(f'q0{num_part}')
    return None


def calc_category_geomean(times: Dict[str, float], category: str) -> float:
    """Calculate geomean for queries in a specific category.
    Handles both q01 and q1 query name formats transparently."""
    category_queries = QUERY_CLASSIFICATIONS.get(category, [])
    values = []
    for q in category_queries:
        t = _lookup_time(times, q)
        if t and t > 0:
            values.append(t)
    return calc_geomean(values) if values else 0


def calc_category_total(times: Dict[str, float], category: str) -> float:
    """Calculate total for queries in a specific category.
    Handles both q01 and q1 query name formats transparently."""
    category_queries = QUERY_CLASSIFICATIONS.get(category, [])
    values = []
    for q in category_queries:
        t = _lookup_time(times, q)
        if t and t > 0:
            values.append(t)
    return calc_total(values) if values else 0


def build_category_breakdown(
    sf_times: Dict[str, float],
    comp_times: Dict[str, float]
) -> List[Dict]:
    """
    Build per-category breakdown comparing SF vs a competitor.
    
    Args:
        sf_times: Dict of query_name -> seconds for Snowflake
        comp_times: Dict of query_name -> seconds for competitor
    
    Returns:
        List of dicts, one per category:
        {category, count, sf_geomean, sf_total, comp_geomean, comp_total, winner, ratio}
    """
    categories = list(QUERY_CLASSIFICATIONS.keys())
    breakdown = []
    
    for cat in categories:
        sf_cat_geomean = calc_category_geomean(sf_times, cat)
        comp_cat_geomean = calc_category_geomean(comp_times, cat)
        sf_cat_total = calc_category_total(sf_times, cat)
        comp_cat_total = calc_category_total(comp_times, cat)
        
        if sf_cat_geomean > 0 and comp_cat_geomean > 0:
            if sf_cat_geomean < comp_cat_geomean:
                winner = 'SF'
                ratio = round(comp_cat_geomean / sf_cat_geomean, 2)
            else:
                winner = 'COMP'
                ratio = round(sf_cat_geomean / comp_cat_geomean, 2)
        else:
            winner = '-'
            ratio = 0
        
        breakdown.append({
            'category': cat,
            'count': len(QUERY_CLASSIFICATIONS[cat]),
            'sf_geomean': sf_cat_geomean,
            'sf_total': sf_cat_total,
            'comp_geomean': comp_cat_geomean,
            'comp_total': comp_cat_total,
            'winner': winner,
            'ratio': ratio
        })
    
    return breakdown


def render_category_table_html(
    category_breakdown: List[Dict],
    comp_label: str,
    sf_col_class: str = 'sf-col',
    comp_col_class: str = '',
    sf_winner_class: str = 'sf-winner',
    comp_winner_class: str = 'comp-winner'
) -> str:
    """
    Render a category breakdown as an HTML table.
    
    Args:
        category_breakdown: Output from build_category_breakdown()
        comp_label: Competitor display name (e.g., "Athena", "DBX")
        sf_col_class: CSS class for SF value cells
        comp_col_class: CSS class for competitor value cells
        sf_winner_class: CSS class when SF wins
        comp_winner_class: CSS class when competitor wins
    
    Returns:
        HTML string for the table (without container div)
    """
    rows = ""
    for c in category_breakdown:
        if c['winner'] == 'SF':
            winner_class = sf_winner_class
        elif c['winner'] == 'COMP':
            winner_class = comp_winner_class
        else:
            winner_class = ''
        
        sf_geomean_str = f"{c['sf_geomean']}s" if c['sf_geomean'] > 0 else "—"
        comp_geomean_str = f"{c['comp_geomean']}s" if c['comp_geomean'] > 0 else "—"
        sf_total_str = f"{int(c['sf_total'])}s" if c['sf_total'] > 0 else "—"
        comp_total_str = f"{int(c['comp_total'])}s" if c['comp_total'] > 0 else "—"
        ratio_str = f"{c['ratio']}x" if c['ratio'] > 0 else ""
        winner_str = f"{c['winner']} {ratio_str}" if c['winner'] != '-' else "—"
        
        rows += f'''
                <tr>
                    <td><strong>{c['category']}</strong></td>
                    <td style="text-align:right;">{c['count']}</td>
                    <td class="{sf_col_class}">{sf_geomean_str}</td>
                    <td class="{sf_col_class}">{sf_total_str}</td>
                    <td class="{comp_col_class}">{comp_geomean_str}</td>
                    <td class="{comp_col_class}">{comp_total_str}</td>
                    <td class="{winner_class}">{winner_str}</td>
                </tr>'''
    
    return f'''
            <table>
                <thead>
                    <tr>
                        <th style="text-align:left;">Category</th>
                        <th style="text-align:right;">Queries</th>
                        <th>SF Geomean</th>
                        <th>SF Total</th>
                        <th class="{comp_col_class}">{comp_label} Geomean</th>
                        <th class="{comp_col_class}">{comp_label} Total</th>
                        <th>Winner</th>
                    </tr>
                </thead>
                <tbody>{rows}
                </tbody>
            </table>'''


def render_size_category_sections_html(
    sf_data: Dict,
    comp_times: Dict[str, float],
    sf_sizes: List[str],
    comp_label: str,
    comp_hourly: Optional[float] = None,
    credit_rate: float = 2.0,
    sf_credits_per_hour: Optional[Dict[str, float]] = None,
    sf_col_class: str = 'sf-col',
    comp_col_class: str = '',
    sf_winner_class: str = 'sf-winner',
    comp_winner_class: str = 'comp-winner'
) -> str:
    """
    Generate per-SF-size category breakdown sections.
    
    For serverless competitors (Athena, BigQuery, etc.), this produces one
    table per SF size, each comparing that SF size vs the single competitor
    price point — the universal equivalent of DBX's "Price Tier Breakdown".
    
    Args:
        sf_data: Dict of size -> {times: {query: seconds}, ...}
        comp_times: Dict of query -> seconds for competitor
        sf_sizes: Ordered list of SF sizes to include
        comp_label: Competitor display name
        comp_hourly: Competitor hourly rate (None for serverless/usage-based)
        credit_rate: SF credit rate (SE=2.0, EE=3.0)
        sf_credits_per_hour: Dict of size -> credits/hr
        sf_col_class: CSS class for SF cells
        comp_col_class: CSS class for competitor cells
        sf_winner_class: CSS class for SF winner
        comp_winner_class: CSS class for competitor winner
    
    Returns:
        HTML string with all section headers + tables
    """
    SIZE_ORDER = ['XS', 'S', 'M', 'L', 'XL', '2XL', '3XL', '4XL']
    ordered = [s for s in SIZE_ORDER if s in sf_sizes]
    
    sections_html = ""
    for size in ordered:
        sf_times = sf_data[size]['times']
        breakdown = build_category_breakdown(sf_times, comp_times)
        
        # Build header with pricing info
        if sf_credits_per_hour:
            sf_hourly = sf_credits_per_hour.get(size, 0) * credit_rate
            sf_price_str = f"${sf_hourly:.0f}/hr"
        else:
            sf_price_str = size
        
        if comp_hourly is not None:
            comp_price_str = f"${comp_hourly:.0f}/hr"
            header = f"SF {size} @ {sf_price_str} vs {comp_label} @ {comp_price_str}"
        else:
            header = f"SF {size} @ {sf_price_str} vs {comp_label} (serverless)"
        
        table_html = render_category_table_html(
            breakdown, comp_label,
            sf_col_class=sf_col_class,
            comp_col_class=comp_col_class,
            sf_winner_class=sf_winner_class,
            comp_winner_class=comp_winner_class
        )
        
        sections_html += f'''
        <h3 style="margin-top:25px;color:var(--sf-dark-blue);">{header}</h3>
        <div class="table-container">{table_html}
        </div>'''
    
    return sections_html


def build_category_summary(
    sf_data: Dict,
    comp_times: Dict[str, float],
    sf_sizes: List[str]
) -> List[Dict]:
    """
    Build a cross-size category summary showing where SF dominates.
    
    Returns list of dicts per category:
    {category, count, sf_wins_count, comp_wins_count, best_sf_ratio, worst_sf_ratio}
    """
    SIZE_ORDER = ['XS', 'S', 'M', 'L', 'XL', '2XL', '3XL', '4XL']
    ordered = [s for s in SIZE_ORDER if s in sf_sizes]
    
    categories = list(QUERY_CLASSIFICATIONS.keys())
    summary = []
    
    for cat in categories:
        sf_wins = 0
        comp_wins = 0
        best_ratio = 0  # best for SF (highest comp/sf ratio)
        worst_ratio = float('inf')
        
        for size in ordered:
            sf_geomean = calc_category_geomean(sf_data[size]['times'], cat)
            comp_geomean = calc_category_geomean(comp_times, cat)
            
            if sf_geomean > 0 and comp_geomean > 0:
                ratio = comp_geomean / sf_geomean
                if ratio > 1:
                    sf_wins += 1
                    best_ratio = max(best_ratio, ratio)
                    worst_ratio = min(worst_ratio, ratio)
                else:
                    comp_wins += 1
                    best_ratio = max(best_ratio, ratio)
                    worst_ratio = min(worst_ratio, ratio)
        
        summary.append({
            'category': cat,
            'count': len(QUERY_CLASSIFICATIONS[cat]),
            'sf_wins_count': sf_wins,
            'comp_wins_count': comp_wins,
            'total_sizes': len(ordered),
            'best_sf_ratio': round(best_ratio, 2) if best_ratio > 0 else 0,
            'worst_sf_ratio': round(worst_ratio, 2) if worst_ratio < float('inf') else 0,
        })
    
    return summary
