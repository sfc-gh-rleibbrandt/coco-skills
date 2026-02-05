# Content Builder Skill for Cortex Code

Create professional Snowflake-branded presentations (Marp/PPTX) and TPC-DS benchmark reports.

## Installation

Clone this repo into your Cortex Code skills directory:

```bash
# Create skills directory if it doesn't exist
mkdir -p ~/.claude/skills

# Clone the skill
cd ~/.claude/skills
git clone git@git.snowflakecomputing.com:rleibbrandt/content-builder-skill.git content-builder
```

## Verify Installation

Restart Cortex Code and the skill will appear in your available skills. Invoke with:

```
/content-builder
```

Or ask naturally: "Create a presentation about X"

## Features

- **Marp presentations**: Markdown-based slides with HTML/PDF export
- **PPTX presentations**: Native PowerPoint with Snowflake branding
- **TPC-DS reports**: Benchmark comparison HTML reports

## Dependencies

The skill uses `uv` for Python dependencies (automatically installed):
- `python-pptx` for PPTX generation

For Marp, it uses `npx` (Node.js required):
- `@marp-team/marp-cli` for HTML/PDF generation

## Files

```
content-builder/
├── SKILL.md           # Main skill instructions
├── pyproject.toml     # Python dependencies
├── assets/
│   ├── marp_base.md       # Marp template
│   ├── pptx_base.py       # PPTX generator template
│   └── tpcds_report_base.py  # TPC-DS report template
└── references/
    └── style_guide.md     # Snowflake brand guidelines
```

## Updating

```bash
cd ~/.claude/skills/content-builder
git pull
```
