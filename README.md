# Cortex Code Skills

Shared skills for Cortex Code (CoCo).

## Available Skills

| Skill | Description |
|-------|-------------|
| [content-builder](./content-builder/) | Create Snowflake-branded presentations (Marp/PPTX) and TPC-DS reports |

## Installation

### Step 1: Clone this repository

```bash
git clone https://github.com/sfc-gh-rleibbrandt/coco-skills.git ~/coco-skills
```

### Step 2: Create the skills directory (if it doesn't exist)

```bash
mkdir -p ~/.claude/skills
```

### Step 3: Symlink the skill(s) you want

```bash
ln -s ~/coco-skills/content-builder ~/.claude/skills/content-builder
```

### Step 4: Restart Cortex Code

Quit and reopen Cortex Code to load the new skill.

### Step 5: Verify installation

Run `/content-builder` or ask "create a presentation" to confirm the skill is available.

## Updating Skills

When new skills are added or existing ones are updated:

```bash
cd ~/coco-skills
git pull
```

No restart needed for updates to existing skills.

## Contributing

### Adding a new skill

1. Fork this repo
2. Create a directory with your skill name (e.g., `my-skill/`)
3. Add a `SKILL.md` file (required) with frontmatter containing `name` and `description`
4. Add any supporting files (assets, templates, references)
5. Submit a PR

### Skill structure

```
skill-name/
├── SKILL.md           # Required: Skill instructions with frontmatter
├── pyproject.toml     # Optional: Python dependencies  
├── assets/            # Optional: Templates, base files
└── references/        # Optional: Style guides, docs
```

### SKILL.md frontmatter example

```yaml
---
name: my-skill
description: "Brief description of what the skill does. Include trigger words."
---

# My Skill

Instructions for the skill...
```
