"""
TPC-DS Power Run Report Builder

Generates Snowflake-branded HTML reports for TPC-DS benchmark comparisons.
Supports: gap analysis, price:performance, head-to-head comparisons.

Usage:
    1. Copy this file to your project
    2. Customize the REPORT_CONFIG and DATA sections
    3. Run: uv run python tpcds_report.py
    4. Open the generated HTML file
"""

from datetime import datetime
from pathlib import Path

# =============================================================================
# REPORT CONFIGURATION - Customize this section
# =============================================================================

REPORT_CONFIG = {
    "title": "TPC-DS 10TB Gap Analysis",
    "subtitle": "Snowflake Gen2 Medium vs AWS Athena Serverless",
    "date": datetime.now().strftime("%B %d, %Y"),
    "benchmark": "TPC-DS 10TB, Warm Runs",
    "output_file": "tpcds_report.html",
    
    # Run metadata
    "runs": [
        {"name": "SF Gen2 Medium", "run_key": "2775574", "config": "Gen2 M, FDN tables"},
        {"name": "Athena", "run_key": "3473166", "config": "Serverless, non-provisioned"},
    ],
    
    # Summary cards (up to 4)
    "summary_cards": [
        {"value": "19", "label": "Queries where Athena wins", "highlight": False},
        {"value": "80", "label": "Queries where SF wins", "highlight": True},
        {"value": "~12 min", "label": "Total time lost to Athena", "highlight": False},
    ],
    
    # Key finding box
    "key_finding": "Despite losing 19 queries, SF Gen2 Medium is still 1.15x faster overall and 4.2x cheaper ($12 vs $50). The top 5 queries account for most of the gap (~12 min). These are candidates for optimization or warehouse upsizing.",
    
    # Recommendations (list of strings)
    "recommendations": [
        ("Priority 1 - Investigate q78", "Single query accounts for 5 minutes of gap. At 14 min runtime, this is the longest query in the benchmark. Worth profiling."),
        ("Priority 2 - High ratio queries", "q97 (3.0x), q44 (3.6x), q09 (2.4x) show Athena significantly outperforming. These may have query patterns that don't favor SF's execution model at Medium size."),
        ("Priority 3 - Test with larger warehouse", "Many of these gaps likely close at Large or XL. Consider running comparison to quantify."),
    ],
}

# =============================================================================
# QUERY DATA - Customize this section with your benchmark results
# =============================================================================

# Column definitions: (key, header, alignment, format)
# alignment: "left", "right", "center"
# format: None, "time", "ratio", "severity"
COLUMNS = [
    ("query", "Query", "left", None),
    ("platform1_time", "SF Gen2 M", "right", "time"),
    ("platform2_time", "Athena", "right", "time"),
    ("diff", "Time Lost", "right", "time"),
    ("ratio", "SF Slower By", "right", "ratio"),
    ("severity", "Severity", "left", "severity"),
]

# Query data rows - severity is auto-calculated if not provided
# You can override by setting severity explicitly
QUERY_DATA = [
    {"query": "q78", "platform1_time": 854.6, "platform2_time": 547.6, "diff": 307.0, "ratio": 1.56},
    {"query": "q97", "platform1_time": 204.7, "platform2_time": 68.7, "diff": 136.1, "ratio": 2.98},
    {"query": "q04", "platform1_time": 228.0, "platform2_time": 115.0, "diff": 113.0, "ratio": 1.98},
    {"query": "q75", "platform1_time": 182.8, "platform2_time": 84.1, "diff": 98.7, "ratio": 2.17},
    {"query": "q23P1", "platform1_time": 188.4, "platform2_time": 130.3, "diff": 58.0, "ratio": 1.45},
    {"query": "q09", "platform1_time": 91.9, "platform2_time": 37.8, "diff": 54.2, "ratio": 2.43},
    {"query": "q28", "platform1_time": 115.3, "platform2_time": 68.7, "diff": 46.6, "ratio": 1.68},
    {"query": "q11", "platform1_time": 110.7, "platform2_time": 68.6, "diff": 42.1, "ratio": 1.61},
    {"query": "q44", "platform1_time": 43.2, "platform2_time": 12.1, "diff": 31.1, "ratio": 3.58},
    {"query": "q76", "platform1_time": 58.8, "platform2_time": 32.6, "diff": 26.2, "ratio": 1.81},
    {"query": "q74", "platform1_time": 62.5, "platform2_time": 42.9, "diff": 19.5, "ratio": 1.45},
    {"query": "q59", "platform1_time": 42.9, "platform2_time": 27.5, "diff": 15.4, "ratio": 1.56},
    {"query": "q29", "platform1_time": 49.3, "platform2_time": 37.8, "diff": 11.5, "ratio": 1.30},
    {"query": "q14P2", "platform1_time": 88.9, "platform2_time": 79.5, "diff": 9.4, "ratio": 1.12},
    {"query": "q72", "platform1_time": 34.3, "platform2_time": 27.5, "diff": 6.8, "ratio": 1.25},
    {"query": "q88", "platform1_time": 39.2, "platform2_time": 32.6, "diff": 6.6, "ratio": 1.20},
    {"query": "q02", "platform1_time": 23.2, "platform2_time": 17.2, "diff": 6.0, "ratio": 1.35},
    {"query": "q87", "platform1_time": 47.0, "platform2_time": 43.0, "diff": 4.1, "ratio": 1.09},
    {"query": "q35", "platform1_time": 20.3, "platform2_time": 17.2, "diff": 3.1, "ratio": 1.18},
]

# =============================================================================
# HTML TEMPLATE - Snowflake branded styling
# =============================================================================

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        :root {{
            --sf-blue: #29B5E8;
            --sf-dark-blue: #11567F;
            --sf-navy: #0D2C54;
            --sf-light-bg: #F4FAFF;
            --sf-gray: #6E7681;
            --red: #B43232;
            --orange: #FF9800;
            --green: #32963C;
        }}
        
        body {{
            font-family: 'Nunito Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            max-width: 1000px;
            margin: 0 auto;
            padding: 40px 20px;
            background: #fff;
            color: #333;
            line-height: 1.6;
        }}
        
        h1 {{
            color: var(--sf-dark-blue);
            border-bottom: 3px solid var(--sf-blue);
            padding-bottom: 10px;
            margin-bottom: 5px;
        }}
        
        .subtitle {{
            font-size: 1.2em;
            color: var(--sf-gray);
            margin-bottom: 20px;
        }}
        
        h2 {{
            color: var(--sf-dark-blue);
            margin-top: 40px;
        }}
        
        .meta {{
            background: var(--sf-light-bg);
            padding: 15px 20px;
            border-radius: 8px;
            margin-bottom: 30px;
            border-left: 4px solid var(--sf-blue);
        }}
        
        .meta p {{
            margin: 5px 0;
        }}
        
        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin: 30px 0;
        }}
        
        .card {{
            background: var(--sf-light-bg);
            padding: 20px;
            border-radius: 8px;
            text-align: center;
        }}
        
        .card.highlight {{
            background: var(--sf-blue);
            color: white;
        }}
        
        .card .number {{
            font-size: 2.5em;
            font-weight: bold;
            display: block;
        }}
        
        .card .label {{
            font-size: 0.9em;
            opacity: 0.8;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
            font-size: 0.9em;
        }}
        
        th {{
            background: linear-gradient(135deg, var(--sf-dark-blue) 0%, var(--sf-navy) 100%);
            color: white;
            padding: 12px 15px;
            text-align: left;
            font-weight: 600;
        }}
        
        th.right {{ text-align: right; }}
        th.center {{ text-align: center; }}
        
        td {{
            padding: 10px 15px;
            border-bottom: 1px solid #D0E8F5;
        }}
        
        td.right {{ text-align: right; }}
        td.center {{ text-align: center; }}
        
        tr:nth-child(even) {{
            background: var(--sf-light-bg);
        }}
        
        tr:hover {{
            background: #E8F4FC;
        }}
        
        tr.severe {{
            background: #fdecea;
        }}
        tr.severe:hover {{
            background: #fbd6d2;
        }}
        
        tr.moderate {{
            background: #fef9e7;
        }}
        tr.moderate:hover {{
            background: #fdf3ce;
        }}
        
        .tag {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.75em;
            font-weight: bold;
            text-transform: uppercase;
        }}
        
        .tag.severe {{ background: var(--red); color: white; }}
        .tag.moderate {{ background: var(--orange); color: white; }}
        .tag.minor {{ background: #95a5a6; color: white; }}
        
        .key-finding {{
            background: #E8F4FC;
            border-left: 4px solid var(--sf-blue);
            padding: 15px 20px;
            margin: 20px 0;
            border-radius: 0 8px 8px 0;
        }}
        
        .key-finding strong {{
            color: var(--sf-dark-blue);
        }}
        
        .recommendation {{
            background: var(--sf-light-bg);
            border-left: 4px solid var(--sf-blue);
            padding: 15px 20px;
            margin: 15px 0;
            border-radius: 0 8px 8px 0;
        }}
        
        .recommendation strong {{
            color: var(--sf-dark-blue);
        }}
        
        .footer {{
            margin-top: 50px;
            padding-top: 20px;
            border-top: 1px solid #eee;
            font-size: 0.85em;
            color: var(--sf-gray);
        }}
        
        @media print {{
            body {{
                padding: 20px;
            }}
            .summary-cards {{
                grid-template-columns: repeat(3, 1fr);
            }}
        }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    <p class="subtitle">{subtitle}</p>
    
    <div class="meta">
        <p><strong>Date:</strong> {date}</p>
        <p><strong>Benchmark:</strong> {benchmark}</p>
        {run_metadata}
    </div>
    
    <h2>Executive Summary</h2>
    
    <div class="summary-cards">
        {summary_cards}
    </div>
    
    <div class="key-finding">
        <strong>Key Finding:</strong> {key_finding}
    </div>
    
    <h2>Gap Details</h2>
    
    <table>
        <thead>
            <tr>
                {table_headers}
            </tr>
        </thead>
        <tbody>
            {table_rows}
        </tbody>
    </table>
    
    <h2>Recommendations</h2>
    
    {recommendations}
    
    <div class="footer">
        <p>Generated by Benchmarking Team | TPC-DS Power Run Report Builder</p>
        <p>Data source: bench_store.publicdata (Snowhouse)</p>
        <p>&copy; {year} Snowflake Inc. All Rights Reserved | Confidential</p>
    </div>
</body>
</html>
"""


# =============================================================================
# REPORT GENERATION FUNCTIONS
# =============================================================================

def format_time(seconds: float) -> str:
    """Format seconds as human-readable time."""
    if seconds >= 60:
        mins = seconds / 60
        return f"{mins:.1f} min"
    return f"{seconds:.1f}s"


def format_ratio(ratio: float) -> str:
    """Format ratio with 'x' suffix."""
    return f"{ratio:.2f}x"


def format_severity(severity: str) -> str:
    """Format severity as colored tag."""
    return f'<span class="tag {severity}">{severity.upper()}</span>'


def calculate_severity(diff: float, ratio: float) -> str:
    """
    Calculate severity based on both absolute time impact AND ratio.
    
    Matrix:
                    | Ratio < 1.5x | Ratio 1.5-2.5x | Ratio > 2.5x |
    Time > 60s      | MODERATE     | SEVERE         | SEVERE       |
    Time 30-60s     | MINOR        | MODERATE       | SEVERE       |
    Time < 30s      | MINOR        | MINOR          | MODERATE     |
    
    High ratio indicates potential algorithmic/architectural issue.
    High absolute time indicates impact on total benchmark.
    """
    high_ratio = ratio > 2.5
    medium_ratio = 1.5 <= ratio <= 2.5
    
    high_time = diff > 60
    medium_time = 30 <= diff <= 60
    
    if high_ratio:
        if high_time or medium_time:
            return "severe"
        else:
            return "moderate"
    elif medium_ratio:
        if high_time:
            return "severe"
        elif medium_time:
            return "moderate"
        else:
            return "minor"
    else:  # low ratio
        if high_time:
            return "moderate"
        else:
            return "minor"


def generate_run_metadata(runs: list) -> str:
    """Generate run metadata HTML."""
    lines = []
    for i, run in enumerate(runs, 1):
        lines.append(f'<p><strong>{run["name"]} Run:</strong> {run["run_key"]} ({run["config"]})</p>')
    return "\n        ".join(lines)


def generate_summary_cards(cards: list) -> str:
    """Generate summary card HTML."""
    html_cards = []
    for card in cards:
        highlight_class = " highlight" if card.get("highlight") else ""
        html_cards.append(f'''<div class="card{highlight_class}">
            <span class="number">{card["value"]}</span>
            <span class="label">{card["label"]}</span>
        </div>''')
    return "\n        ".join(html_cards)


def generate_table_headers(columns: list) -> str:
    """Generate table header HTML."""
    headers = []
    for key, header, align, fmt in columns:
        align_class = f' class="{align}"' if align != "left" else ""
        headers.append(f"<th{align_class}>{header}</th>")
    return "\n                ".join(headers)


def generate_table_rows(data: list, columns: list) -> str:
    """Generate table row HTML."""
    rows = []
    for row in data:
        # Auto-calculate severity if not provided
        if "severity" not in row and "diff" in row and "ratio" in row:
            severity = calculate_severity(row["diff"], row["ratio"])
        else:
            severity = row.get("severity", "")
        
        row_class = f' class="{severity}"' if severity in ("severe", "moderate") else ""
        
        cells = []
        for key, header, align, fmt in columns:
            if key == "severity":
                value = severity
            else:
                value = row.get(key, "")
            
            # Apply formatting
            if fmt == "time" and isinstance(value, (int, float)):
                value = format_time(value)
            elif fmt == "ratio" and isinstance(value, (int, float)):
                value = format_ratio(value)
            elif fmt == "severity":
                value = format_severity(value)
            
            align_class = f' class="{align}"' if align != "left" else ""
            cells.append(f"<td{align_class}>{value}</td>")
        
        rows.append(f"<tr{row_class}>\n                {chr(10).join(cells)}\n            </tr>")
    
    return "\n            ".join(rows)


def generate_recommendations(recommendations: list) -> str:
    """Generate recommendation HTML."""
    recs = []
    for title, content in recommendations:
        recs.append(f'''<div class="recommendation">
        <strong>{title}:</strong> {content}
    </div>''')
    return "\n    ".join(recs)


def generate_report():
    """Generate the HTML report."""
    config = REPORT_CONFIG
    
    html = HTML_TEMPLATE.format(
        title=config["title"],
        subtitle=config["subtitle"],
        date=config["date"],
        benchmark=config["benchmark"],
        run_metadata=generate_run_metadata(config["runs"]),
        summary_cards=generate_summary_cards(config["summary_cards"]),
        key_finding=config["key_finding"],
        table_headers=generate_table_headers(COLUMNS),
        table_rows=generate_table_rows(QUERY_DATA, COLUMNS),
        recommendations=generate_recommendations(config["recommendations"]),
        year=datetime.now().year,
    )
    
    output_path = Path(config["output_file"])
    output_path.write_text(html)
    print(f"Report generated: {output_path.absolute()}")
    return output_path


if __name__ == "__main__":
    generate_report()
