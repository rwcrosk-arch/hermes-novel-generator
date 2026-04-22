---
name: novel-epub-fixes
description: "Bug fixes and process improvements for the novel EPUB publishing pipeline: TOC title extraction, ASCII art preservation (all box styles), and paragraph edge-case handling."
version: 2.0.0
author: rwcrosk-arch

---

# EPUB Publishing Pipeline Fixes

## Bug 1: Missing Chapter Titles in TOC

**Root cause:** The `publish.py` script extracted chapter titles by checking only `lines[0].startswith("#")`. If a chapter file started with plain text "Chapter 5: Title" instead of "# Chapter 5: Title", the TOC fallback name "Chapter 5" was used.

**Fixes applied:**
1. **Chapter generation:** Subagents now ALWAYS write chapter titles starting with `# Chapter N: Title`
2. **publish.py title extraction:** Now scans for the first non-empty line, accepts both:
   - `# Title` (markdown heading)
   - `Chapter N: Title` (plain text heading, case-insensitive match)
3. Strips the title line from content before converting to avoid duplication.

**Verification command:**
```bash
for f in chapters/chapter_*.md; do echo "$(basename $f): $(head -1 $f)"; done
```

## Bug 2: ASCII Art Stat Boxes Warped in EPUB — COMPREHENSIVE FIX

**Root cause:** `markdown_to_html()` was line-by-line. RPG stat art used MULTIPLE DIFFERENT box styles depending on the chapter:

**Box Style A (Chapters 1-2):** Unicode box-drawing characters
```
╔════════════════╗
║ System Alert   ║
╚════════════════╝
```

**Box Style B (Chapters 3-11):** ASCII pipe tables
```
+----------------------------------+
|  COMBAT STATUS: HERMES           |
|  Class: Prototype Guardian       |
+----------------------------------+
```

**Box Style C (Chapter 12):** Separator bars with bracket headers
```
=========================================
    [ PROJECT HERMES: FINAL CONFIG ]
=========================================
    Name:     Hermes
    Form:     MK-II Guardian Chassis
    Level:    52+ (UNCAPPED)
=========================================
```

The original fix only detected Style A. Styles B and C were split into individual `<p>` tags, breaking the art.

### Comprehensive Fix Applied (publish.py)

**1. Added three detection helpers:**
```python
BOX_DRAWING_RE = re.compile(
    r'[\u2500-\u257F'          # Box Drawing
    r'\u2580-\u259F'           # Block Elements
    r'╔╗╚╝═║╠╣╦╩'             # Double-line box chars
    r']'
)
ASCII_TABLE_BORDER_RE = re.compile(r'^(\+[\-+]+\+)$')      # +------+
ASCII_TABLE_PIPE_RE = re.compile(r'^(\|.*\|)$')          # | text |
```

**2. Added separator line detection for Style C:**
```python
def _is_uniform_symbol_line(s):
    """A line of 10+ chars that is 80%+ the same symbol (= - * # ~)."""
    if len(s) < 10:
        return False
    for ch in ('=', '-', '*', '#', '~'):
        ratio = s.count(ch) / len(s)
        if ratio >= 0.8:
            return True
    return False
```

**3. Unified art-line checker:**
```python
def _is_any_art_line(text, idx):
    s = text.strip()
    if not s:
        return False
    return bool(
        BOX_DRAWING_RE.search(s)                          # ╔══╗ style
        or ASCII_TABLE_BORDER_RE.match(s)                 # +----+ style
        or ASCII_TABLE_PIPE_RE.match(s)                   # | ... | style
        or _is_uniform_symbol_line(s)                     # ==== style
        or (s == '+' and idx + 1 < len(lines)
            and (ASCII_TABLE_BORDER_RE.match(lines[idx+1].strip())
                 or _is_uniform_symbol_line(lines[idx+1].strip())))  # Ch9 '+' prefix
    )
```

**4. Smart block consumer for mixed-style blocks:**
After detecting an art-start line, the consumer determines block style and consumes associated content lines:

- **Table-style blocks** (`+-----+` start): consumes `+-----+` borders, `| content |` lines, and standalone `+` prefix lines
- **Separator-style blocks** (`=====` start): consumes `=====` bars, `[ HEADERS ]`, `- list items`, and `Label: value` lines at the same indentation level

**5. Added EPUB CSS for all styles:**
```css
.ascii-art {
    font-family: "DejaVu Sans Mono", "Libertinus Mono", "Courier New", monospace;
    white-space: pre;
    text-align: center;
    padding: 0.5em;
    border: 1px solid #ccc;
    background: #f8f8f8;
    margin: 1em auto;
    max-width: 95%;
}
```

## Verification Script (All 12 Chapters)

```python
import zipfile, re

path = 'output/Your_Novel.epub'
with zipfile.ZipFile(path, 'r') as z:
    for name in sorted(z.namelist()):
        if name.endswith('.xhtml') and 'chapter_' in name:
            html = z.read(name).decode('utf-8')
            count = html.count('ascii-art')
            ch_num = name.split('_')[1].split('.')[0]
            print(f'  Ch {ch_num}: {count:2d} ascii-art blocks')
            # All chapters with art should show >0
            # Prose chapters (4, 11) may show 0 (correct — no stat boxes)
```

## Process Improvements for Future Novels

1. **Enforce chapter title format in subagent prompts:**
   ```
   Always start the chapter file with:
   # Chapter N: The Title Here
   Never use plain text without the # prefix.
   ```

2. **Use one unified box style across all chapters (recommended):**
   To avoid detection complexity, have subagents use a SINGLE consistent style for stat boxes. The recommended style is the **ASCII pipe table** (Style B — `+----+ | text |`) because:
   - It renders correctly in all markdown viewers
   - It's easy to type and read
   - The converter detects it reliably
   ```
   +--------------------------------+
   |  SYSTEM STATUS                 |
   |  Level: 42                     |
   +--------------------------------+
   ```

3. **Or use code fences for stat blocks (most reliable):**
   ```
   ```stat
   +--------------------------------+
   |  SYSTEM STATUS                 |
   |  Level: 42                     |
   +--------------------------------+
   ```
   ```
   Code fences are universally recognized and skip all paragraph processing.

4. **After every generation batch, verify art blocks exist:**
   ```python
   import os, re
   for f in sorted(os.listdir('chapters')):
       if f.endswith('.md'):
           text = open(f'chapters/{f}').read()
           boxes = len(re.findall(r'^[+╚╔|┌┏].*$', text, re.M))
           print(f"{f}: ~{boxes} potential box lines")
   ```

5. **The `markdown_to_html()` converter is now robust to:**
   - All three box styles (A/B/C) and mixtures
   - Prose paragraphs (joined with spaces)
   - Code fences (preserved as `<pre><code>`)
   - Scene breaks (`***` → `<div class="scene-break">`)
   - Dialogue formatting with curly quotes
   - Bold and italic inline markdown
   - Tables with `|` pipes inside prose (only detected as art if `+` borders present)

## Files Modified
- `scripts/publish.py` — title extraction, markdown_to_html, comprehensive ASCII art detection (Unicode + ASCII table + separator styles), smart block consumer, EPUB CSS
- `chapters/chapter_05.md` — added `# ` prefix to title
- `chapters/chapter_11.md` — added `# ` prefix to title
