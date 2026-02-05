# Cortex Code Skills

Shared skills for Cortex Code (CoCo).

## Available Skills

| Skill | Description |
|-------|-------------|
| [content-builder](./content-builder/) | Create Snowflake-branded presentations (Marp/PPTX) and TPC-DS reports |

## Installation

Clone this repo and symlink skills to your Cortex Code skills directory:

```bash
# Clone the repo
git clone https://github.com/sfc-gh-rleibbrandt/coco-skills.git ~/coco-skills

# Create skills directory if needed
mkdir -p ~/.claude/skills

# Symlink a skill
ln -s ~/coco-skills/content-builder ~/.claude/skills/content-builder
```

Or copy a skill directly:

```bash
cp -r ~/coco-skills/content-builder ~/.claude/skills/
```

Restart Cortex Code to pick up the new skill.

## Contributing

To add a new skill:

1. Create a directory with your skill name
2. Add a `SKILL.md` file (required) - this contains the skill instructions
3. Add any assets, templates, or references
4. Submit a PR

## Skill Structure

```
skill-name/
├── SKILL.md           # Required: Main skill instructions (with frontmatter)
├── pyproject.toml     # Optional: Python dependencies
├── assets/            # Optional: Templates, base files
└── references/        # Optional: Style guides, docs
```
