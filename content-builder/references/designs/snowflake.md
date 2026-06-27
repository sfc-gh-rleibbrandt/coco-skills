# Content Builder Style Guide

Complete documentation of Snowflake presentation styling, patterns, and best practices.

## Table of Contents
1. [Brand Colors](#brand-colors)
2. [Typography](#typography)
3. [Layout Principles](#layout-principles)
4. [Slide Types](#slide-types)
5. [Content Patterns](#content-patterns)
6. [Code Blocks](#code-blocks)
7. [Tables](#tables)
8. [Badges](#badges)
9. [Multi-Format Sync](#multi-format-sync)

---

## Brand Colors

### Primary Colors
| Name | Hex | RGB | Usage |
|------|-----|-----|-------|
| SF Blue | `#29B5E8` | `41, 181, 232` | Accent bar, links, highlights |
| SF Dark Blue | `#11567F` | `17, 86, 127` | Titles, headers, title slide bg |
| SF Navy | `#0D2C54` | `13, 44, 84` | Table headers (gradient) |
| SF Light BG | `#F4FAFF` | `244, 250, 255` | Light backgrounds |
| SF Gray | `#6E7681` | `110, 118, 129` | Subtitles, secondary text |

### Semantic Colors
| Name | Hex | Usage |
|------|-----|-------|
| Success/After | `#32963C` / `#4CAF50` | "After" examples, checkmarks |
| Warning/Preview | `#FF9800` | Preview badges |
| Error/Before | `#B43232` | "Before" examples, x marks |
| Filled Value | `#27AE60` | Highlight filled/interpolated values |

### Background Colors
| Slide Type | Background |
|------------|------------|
| Title/Section slides | `#11567F` (Dark Blue) |
| Content slides | `#FFFFFF` (White) |
| Code blocks | `#EDF5FB` (Light blue tint) |
| Inline code | `#E8F4FC` |
| Blockquotes | `#E8F4FC` |

---

## Typography

### Fonts
| Usage | Font Stack | Fallback |
|-------|------------|----------|
| Body | Nunito Sans | Segoe UI, Helvetica Neue, Arial |
| Code | Courier New | monospace |

### Font Sizes (Marp)
| Element | Size |
|---------|------|
| Title slide H1 | 2.2em |
| Content slide H1 | 1.4em |
| Subtitle (H2) | 0.95em |
| Body text | 20px (base) |
| Lists | 0.88em |
| Tables | 0.72em |
| Code blocks | 0.65em |
| Doc links | 0.52em |
| Footer | 9px |

### Font Sizes (PPTX)
| Element | Size |
|---------|------|
| Title slide title | 44pt |
| Title slide subtitle | 24pt |
| Content slide title | 28pt |
| Content slide subtitle | 16pt |
| Body text | 14pt |
| Table cells | 11-12pt |
| Code | 9-12pt |
| Doc links | 12pt |
| Footer | 9pt |

---

## Layout Principles

### Fixed Header Positioning
Headers are positioned at fixed absolute positions to ensure consistency:

**Content Slides (Marp CSS)**:
```css
h1 {
  position: absolute;
  top: 35px;
    left: calc(50% - 500px);    /* Centered with 1000px max-width */
}
h2 {
    position: absolute;
    top: 68px;
  left: calc(50% - 500px);
}
```

**Blue Accent Bar**:
```css
section::before {
  position: absolute;
  top: 35px;
    left: calc(50% - 500px - 25px);  /* 25px left of header */
  width: 5px;
  height: 55px;
    background: #29B5E8;
}
```

### Centered Content
All content is centered horizontally with max-width:
```css
section > * {
    max-width: 1000px;
    margin-left: auto;
    margin-right: auto;
}
```

### Padding
- Content slides: `110px 80px 60px 80px` (top right bottom left)
- Title slides: `50px` all around

### Footer Position
Copyright footer:
- Position: Bottom-left
- Size: 9px
- Content: `© 2026 Snowflake Inc. All Rights Reserved | Confidential`
- Light color on dark slides: `rgba(255,255,255,0.5)`
- Dark color on light slides: `#999999`

---

## Slide Types

### 1. Title Slide
**Use for**: Presentation title, section dividers

**Styling**:
- Dark blue background (`#11567F`)
- Centered content
- White/light blue text
- No blue accent bar
- Light footer

**Marp**:
```markdown
<!-- _class: title -->

# Title Here
## Subtitle Here

**Event/Customer Name**

Date | Presenter
```

### 2. Content Slide
**Use for**: Main content, features, explanations

**Styling**:
- White background
- Blue accent bar (5px, left of title)
- Fixed header position
- Dark footer

**Marp**:
```markdown
# Slide Title
## Optional Subtitle

Content here...

<div class="docs-link">📚 <a href="URL">URL</a></div>
```

### 3. Before/After Comparison
**Use for**: Showing value of new features

**Layout**:
- Left side: "Before" (red label, smaller code)
- Right side: "After" (green label, cleaner code)
- Comparison table (optional, right side)
- Customer quote (optional, bottom)

### 4. Value Proposition Slide
**Use for**: Feature overview with business value

**Layout**:
- Feature table (top)
- Struggles we solve (bottom-left)
- Value delivered (bottom-right)
- Customer quote (optional, bottom)

### 5. Roadmap Slide
**Use for**: Upcoming features

**Layout**:
- Customer pain point quote (top)
- Current behavior description
- Timeline table
- Planned syntax (optional)

---

## Content Patterns

### Problem Statement
Always include a clear problem statement:
```markdown
**Problem:** [One-sentence problem description]
```

### Customer Proof Points
Format customer quotes with trophy emoji:
```markdown
> 🏆 "Quote here" — Customer Name
```

### Status Badges
Use consistent badges:
- `✅ GA` - Generally Available
- `🟡 Public Preview` - Preview
- `🔜 Coming Soon` - Roadmap

### Documentation Links
Every slide should have a doc link:
```markdown
<div class="docs-link">📚 <a href="https://docs.snowflake.com/path">docs.snowflake.com/path</a></div>
```

---

## Code Blocks

### Marp Styling
```css
pre {
    background: #EDF5FB;
    border-left: 4px solid #29B5E8;
    border-radius: 8px;
    padding: 12px;
    font-size: 0.65em;
}
```

### Inline Code
```css
code {
    background: #E8F4FC;
    color: #0D2C54;
    border-radius: 4px;
    padding: 2px 6px;
}
```

### Before/After Code Sizing
- "Before" code: Smaller font (9pt) to fit complexity
- "After" code: Larger font (11pt) to show clarity

---

## Tables

### Header Row
- Background: Gradient from `#11567F` to `#0D2C54`
- Text: White, bold
- Padding: 8px 10px

### Data Rows
- Background: Alternating `#F8FCFE` / `#EDF5FB`
- Text: `#1a1a1a`
- Border: 1px solid `#D0E8F5`

### Column Widths
Adjust based on content. Example:
```python
table.columns[0].width = Inches(3)   # Feature name
table.columns[1].width = Inches(1.5) # Status
table.columns[2].width = Inches(7.5) # Description
```

---

## Badges

### GA Badge (Green)
```css
.ga-badge {
    background: linear-gradient(135deg, #4CAF50 0%, #388E3C 100%);
    color: white;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.65em;
    font-weight: bold;
}
```

### Preview Badge (Orange)
```css
.preview-badge {
    background: linear-gradient(135deg, #FF9800 0%, #F57C00 100%);
    color: white;
    padding: 3px 10px;
    border-radius: 12px;
    font-size: 0.65em;
    font-weight: bold;
    text-transform: uppercase;
}
```

Usage in Marp:
```markdown
# Feature Name <span class="preview-badge">PUBLIC PREVIEW</span>
```

---

## Multi-Format Sync

### Workflow
1. **Edit Marp source** (`.md` file) - single source of truth for content
2. **Generate HTML/PDF**: 
   ```bash
   npx --yes @marp-team/marp-cli source.md -o output.html
   npx --yes @marp-team/marp-cli source.md -o output.pdf --allow-local-files
   ```
3. **Generate PPTX**: Run Python script (separate file)
   ```bash
   python3 create_presentation.py
   ```

### Content Sync Rules
- Slide count should match across formats
- Slide titles must match exactly
- Tables should have same data
- Code examples should be identical
- Doc URLs must be accurate in all formats

### Differences by Format
| Feature | Marp HTML/PDF | PPTX |
|---------|---------------|------|
| Animations | CSS-based | Native |
| Template | CSS in frontmatter | python-pptx |
| Tables | Markdown | python-pptx tables |
| Clickable links | Yes | Manual |

---

## Commands Reference

### Generate All Formats
```bash
cd /path/to/presentation

# HTML
npx --yes @marp-team/marp-cli source.md -o output.html

# PDF
npx --yes @marp-team/marp-cli source.md -o output.pdf --allow-local-files

# PPTX
python3 create_presentation.py

# Open HTML
open output.html
```

### Dependencies
```bash
# Marp CLI
npm install -g @marp-team/marp-cli
# or use npx (no install needed)

# Python PPTX
pip install python-pptx
```

---

## Utility Classes

### Text Colors
| Class | Color | Usage |
|-------|-------|-------|
| `.green-text` | `#32963C` | Success, positive numbers |
| `.red-text` | `#B43232` | Error, negative/warning |
| `.blue-text` | `#29B5E8` | Accent, links |

### Layout Helpers
| Class | Description |
|-------|-------------|
| `.columns` | Two-column flex layout with 30px gap |
| `.metric-grid` | Centered flex container for metric boxes |
| `.metric-box` | Styled box with border for KPIs |
| `.metric-value` | Large bold number inside metric-box |
| `.metric-label` | Small gray label inside metric-box |

### Callout Boxes
| Class | Background | Border | Usage |
|-------|------------|--------|-------|
| `.callout` | Orange tint | Orange | Warnings, notes |
| `.callout-success` | Green tint | Green | Success, recommendations |
| `.callout-danger` | Red tint | Red | Errors, problems |

### Table Variants
| Class | Effect |
|-------|--------|
| `section.compact` | Smaller table font (0.60em) and padding |

### Flow Diagrams
| Class | Description |
|-------|-------------|
| `.flow-diagram` | Flex container for horizontal flow diagrams |
| `.flow-box` | Rounded box for flow diagram nodes |
| `.flow-arrow` | Large gray arrow between flow boxes |

### Example Usage
```html
<div class="metric-grid">
  <div class="metric-box">
    <div class="metric-value">5,520</div>
    <div class="metric-label">Total Items</div>
  </div>
</div>

<div class="columns">
  <div>Left column content</div>
  <div>Right column content</div>
</div>

<div class="callout-success">
  <strong>Recommendation:</strong> Do this thing.
</div>

<div class="flow-diagram">
  <div class="flow-box" style="background: #E8F4FC;">Input</div>
  <div class="flow-arrow">→</div>
  <div class="flow-box" style="background: #E8F5E9;">Output</div>
</div>
```

---

## Key Design Decisions

1. **Fixed headers**: Ensures visual consistency across slides
2. **Centered content**: Professional, balanced appearance
3. **White backgrounds**: Better readability and print quality
4. **Blue accent bar**: Subtle Snowflake branding without overwhelming
5. **Small footer**: Unobtrusive but present
6. **Before/after pattern**: Shows real value, not simplified examples
7. **Clickable doc links**: Enable immediate follow-up

---

## Anti-Patterns to Avoid

❌ **Simplified "before" examples**
- Show REAL complexity (15+ lines) to demonstrate value

❌ **Generic fonts (Inter, Roboto)**
- Use Nunito Sans or system fonts

❌ **Purple gradients**
- Stick to Snowflake blue palette

❌ **Floating headers**
- Keep headers at fixed positions

❌ **Missing doc links**
- Every feature slide needs a documentation URL

❌ **Inconsistent badge colors**
- Use green for GA, orange for Preview only
