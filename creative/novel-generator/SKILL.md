---
name: novel-generator
description: "Generate full novels using a multi-agent pipeline (Orchestrator, Storyteller/DM, Character Agents, Lore Auditor, Prose Stylist). Scene Sandbox model: characters generate independent strategies, Storyteller weaves them into prose, then voice-check pass. Targeted revision, state accumulation with versioned validation. Repeatable — archive old novels and start fresh."
version: 2.2.0
author: rwcrosk-arch
license: MIT
dependencies: []
metadata:
  hermes:
    tags: [novel, fiction, multi-agent, creative-writing, generation]
    related_skills: []

---

# Novel Generator — Multi-Agent Novel Generation System

Generates full novels using a multi-agent pipeline. Each agent (Orchestrator, Storyteller/DM, Character Agents, Lore Auditor, Prose Stylist) is a specialized LLM call coordinated through a Python script with file-based state.

## Architecture Philosophy

**Build the loop first. Fancy infrastructure second.** A working novel comes from agents that produce readable text in a coherent pipeline, not from message queues and web dashboards.

The core loop is: Orchestrator plans → Storyteller writes scene briefs → Character agents generate independent scene strategies (each plans what they'd do/say in isolation) → Storyteller weaves all strategies into full scene prose → Character agents review their own lines for voice authenticity → Lore Auditor checks continuity and quality → Storyteller revises flagged passages only → Prose Stylist polishes → Orchestrator updates state. Characters are active participants, not passive reviewers.

## Quick Start

```
Generate a novel with the seed: "A retired spy mentors a teenage hacker while being hunted by her former agency"

# Or with specific options:
Generate a novel — seed: "A retired spy mentors a teenage hacker", genre: "thriller", chapters: 5, target: novella
```

The user provides a seed concept. From there, the system runs the full pipeline autonomously.

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `seed` | (required) | Novel concept/premise — the one-line idea that drives everything |
| `genre` | auto-detected | Genre: thriller, fantasy, scifi, romance, literary, horror, mystery, etc. |
| `chapters` | 10 | Number of chapters to generate |
| `target` | short_novel | Length target (see table below) |

## Length Targets (paperback pages at ~275 words/page)

| Target | Words | Pages | Chapters | Scenes/Ch |
|--------|-------|-------|----------|-----------|
| novella | 30,000 | ~110 | 5-7 | 2-3 |
| short_novel | 60,000 | ~220 | 8-12 | 3-4 |
| novel | 80,000 | ~290 | 12-15 | 3-5 |
| epic | 100,000+ | ~365+ | 15-20 | 4-6 |

## Time Estimates

| Target | Agent Calls | Estimated Time |
|--------|-------------|----------------|
| novella | ~100-160 | 45min - 2hr |
| short_novel | ~250-400 | 2 - 5hr |
| novel | ~400-600 | 4 - 10hr |
| epic | ~600-900 | 6 - 16hr |

Estimates assume ~30-60s per agent call. The Scene Sandbox model uses ~10 calls per multi-character scene (brief + strategies + weave + voice-check + audit + style + state) vs ~5 for single-character scenes. This is still ~45% fewer calls than turn-based dialogue (~18 per scene) while preserving character agency.

## Pipeline Steps

For each scene (~10 agent calls each with Scene Sandbox, ~5 for single-character scenes):

1. **Orchestrator** → novel outline from seed, then self-check for arc completeness, character balance, plausibility
2. Per chapter:
   - **Orchestrator** → scene list with narrative roles
   - Per scene:
     - **Storyteller** → scene brief with beat structure and character goals
     - **Storyteller** → brief validation (self-check against chapter plan, world state, character knowledge boundaries). If fails twice: flag scene, skip.
     - **Character Agents** → Scene Strategy generation: each agent receives the full brief + their profile + what they know about others. Each plans their beat-by-beat actions, dialogue, and intentions in ISOLATION — they do NOT see other characters' strategies. (Skip for single-character scenes)
     - **Storyteller** → receives ALL strategies and weaves them into full scene prose, handling conflicts, overlaps, interruptions, and environmental beats. Characters supply the "what"; Storyteller supplies the "how."
     - **Character Agents** → voice-check pass: each reviews their own dialogue/actions in the woven draft. Flags voice violations, behavioral breaks, knowledge leaks.
     - **Storyteller** → revise ONLY flagged lines. Untouched lines remain verbatim.
     - **Lore Auditor** → consistency check (continuity, character voice, world rules, knowledge leaks, pacing, theme). Quotes specific passages. Max 3 revision rounds with targeted revision only.
     - **Prose Stylist** → prose polish (content boundary enforced: prose quality ONLY, never narrative content)
     - **Orchestrator** → state update (facts, relationships, growth, timeline). Validates update before writing.
   - **Storyteller** → chapter assembly with scene transitions
   - **Orchestrator** → cross-scene continuity review
   - **Lore Auditor** → final chapter-level continuity check
   - **Snapshot** state (with version increment)

## Dashboard

The web dashboard (`scripts/dashboard.py`) shows live progress and serves on port 8420:

```bash
python3 scripts/dashboard.py           # Live server on :8420
python3 scripts/dashboard.py --static  # Generate dashboard.html
```

Features:
- **Scene links**: Each completed scene links to its draft file (`/files/scenes/chXX_sYY_draft.md`). Click to read the raw prose.
- **Chapter links**: Each chapter header links to the assembled chapter (`/files/chapters/chapter_XX.md`).
- **EPUB download**: "Download EPUB" button appears when the EPUB exists.
- **Cover thumbnail**: Shows the generated cover image.
- **Auto-refresh**: Polls `/api/status` every 10 seconds.
- **Completion celebration**: When `meta.status == "complete"`, shows ✨ COMPLETE ✨ with green progress bars.

The dashboard also serves files via `/files/<path>` — scenes, chapters, cover images, and EPUB are all directly accessible.

## Archiving / Starting a New Novel

**CRITICAL: The pipeline WILL NOT start if existing work is detected.** Before generating any novel, `check_existing_novel()` scans for:
- `chapters/chapter_*.md` files
- `output/*.epub` files
- `novel_state.yaml` with a title set
- `scenes/ch*_s*_final.md` files (more than 2)

If ANY of these are found, generation is **ABORTED** with an explicit message demanding archive. This prevents accidentally overwriting completed work.

To archive the current novel and start fresh:

```bash
cd novel_project
python3 scripts/main.py --clean    # Archives to novel_archive/, then resets project
python3 scripts/main.py --archive  # Archives only (keeps current project intact)
```

`--clean` archives `novel_project/` to `novel_archive/<title>_<timestamp>/` preserving all state, scenes, and output. Then resets:
- **Removed**: scenes/, chapters/, .snapshots/, output/, cover images (publish/*.png, *.jpg), dashboard.html
- **Preserved**: scripts/, prompts/, tools/, fonts (publish/*.ttf), novel_state.yaml (reset to empty template)
- **Excluded from archive**: tools/ (ComfyUI + 6.5GB model), .backups/, __pycache__/, node_modules/, .git/
- **Created fresh**: empty scenes/, chapters/, .snapshots/, output/ directories; PROGRESS.md with zero state

After `--clean`, run a new novel with:
```bash
python3 scripts/main.py --seed "Your new concept" --target short_novel
```

### Why This Safety Check Exists

In production, a completed 182,519-word novel (`The_Hollow_Stars.epub`, 20 chapters) was nearly destroyed when a new generation started without archiving. The `novel_state.yaml` was overwritten, scenes were partially clobbered, and only the `chapters/` directory and EPUB survived because they were in separate directories. **Always archive before starting a new novel. The safety check enforces this.**

## File Structure

```
novel_project/
  novel_state.yaml         ← Single source of truth (living state)
  PROGRESS.md              ← Live progress dashboard
  scenes/
    ch01_s01_draft.md      ← Raw scene drafts (Ch1 uses ch01_draft.md — no scene number)
    ch01_s01_audited.md    ← Post-audit revisions
    ch01_s01_final.md      ← Polished scene prose
  .snapshots/
    chapter_001.yaml       ← State snapshot after each chapter
  chapters/
    chapter_01.md          ← Assembled chapters (linked in dashboard)
    chapter_01_polished.md ← Post-stylist polished versions
  publish/
    cover_raw.png          ← AI-generated cover (no text)
    cover_final.png        ← Cover with title/author overlay
    cover_final.jpg        ← Cover JPEG (embedded in EPUB)
  output/
    The_Apothecarys_Second_Life.epub  ← Published EPUB with cover + all chapters
  prompts/
    orchestrator.md         ← Agent role prompts
    storyteller.md
    character_agent.md
    lore_auditor.md
    orchestrator_auditor.md
    prose_stylist.md
  scripts/
    main.py                ← Orchestration loop + all agent functions
    progress.py            ← Progress tracking + archive utilities
    dashboard.py           ← Web dashboard (live :8420 or --static HTML)
    generate_cover.py      ← AI cover generation via diffusers (not ComfyUI)
    publish.py             ← Title overlay + EPUB assembly (--all / --epub-only / --overlay-only)
  tools/comfyui/
    models/checkpoints/animagine-xl-3.1.safetensors  ← SDXL anime model
```

## Key Design Decisions

- **Scene Sandbox Model:** Character agents generate independent scene strategies BEFORE the Storyteller writes prose. Each character plans their beat-by-beat actions, dialogue, and intentions in isolation — they don't see other characters' plans. The Storyteller receives all strategies and weaves them into prose, handling conflicts, overlaps, interruptions, and environmental beats. Characters supply the "what"; the Storyteller supplies the "how." This preserves independent agency (characters can surprise the Storyteller) while keeping prose natural. Character agents then do a voice-check pass on the woven draft. ~10 calls per scene vs ~18 for turn-based.
- **Character voice-check pass:** After the Storyteller weaves strategies into prose, character agents review their own dialogue/actions in the draft. Flags voice violations, behavioral breaks, or knowledge leaks. They do NOT generate their own dialogue during the strategy phase — the strategy phase is planning only.
- **Targeted revision:** When the auditor flags issues, only flagged passages are revised — not the whole scene. Prevents re-introducing bugs in good prose.
- **Narrow re-pass after revision:** After targeted revision cycles, the Prose Stylist re-examines ONLY the revised passages plus ±1 paragraph of context, plus its own first-pass notes. Re-polishing the entire scene after a revision risked degrading already-approved prose.
- **Scene brief validation:** Briefs are self-checked before characters generate strategies. Bad briefs don't cascade. If validation fails twice, the scene is flagged and skipped.
- **State accumulation with versioned validation:** After every scene, the Orchestrator updates world facts, relationships, character growth, and timeline. The update increments `meta.state_version`, validates for contradictions and old_value mismatches, and aborts on failure.
- **Content boundary for stylist:** The Prose Stylist may ONLY modify prose quality. Never narrative content.
- **Characters can enter/exit mid-scene:** The `characters_entering` and `characters_exiting` fields support mid-scene arrivals and departures.
- **Context overflow guardrail:** Before spawning any agent, estimate context size. If over ~6K tokens: truncate profiles, drop voice examples, drop world rules, flag for human review.
- **No Orchestrator Auditor role:** Previously a 6th role with subjective ratings and no enforcement. Its functions merged into Orchestrator and Lore Auditor. Five roles instead of six.
- **Overwrite safety check (CRITICAL):** Before ANY generation starts, `check_existing_novel()` scans the project for existing work. If found, generation aborts with a clear message. This runs in BOTH `run_full_loop()` (the orchestrated path) and `__main__` (the CLI path). The check looks at: chapter files, EPUB files, state file title, and completed scene files. Without this, completed novels can be silently destroyed when a new seed is processed.

  **Implementation pattern (in `scripts/main.py`):**
  ```python
  def check_existing_novel():
      existing = []
      if CHAPTERS_DIR.exists() and list(CHAPTERS_DIR.glob("chapter_*.md")):
          existing.append("chapter files")
      if OUTPUT_DIR.exists() and list(OUTPUT_DIR.glob("*.epub")):
          existing.append("EPUB files")
      if STATE_FILE.exists():
          state = yaml.safe_load(STATE_FILE.read_text()) or {}
          if state.get('meta', {}).get('title'):
              existing.append(f"state file: '{state['meta']['title']}'")
      if SCENES_DIR.exists() and len(list(SCENES_DIR.glob("ch*_s*_final.md"))) > 2:
          existing.append("completed scene files")
      if existing:
          print("EXISTS:", existing)
          return False
      return True
  
  # In run_full_loop() and __main__:
  if not check_existing_novel():
      sys.exit("Archive existing novel first: python scripts/main.py --archive")
  ```
- **No em-dashes — triple-gate enforcement:** Emdashes are banned in all narrative prose. Enforced at three gates: (1) Storyteller prompt has a hard "NO em-dashes" constraint at write-time, (2) Prose Stylist actively removes any that slipped through at polish-time (check #8 + sanity check), (3) Lore Auditor scans for em-dashes and flags them as `character_voice|minor` at audit-time. This pattern works for any style constraint that must survive multiple agent handoffs.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Agent produces garbage | Retry (max 2). If still broken, flag scene and continue. |
| **Existing novel overwritten** | **Never start a new novel without archiving.** The safety check blocks this, but if bypassed: restore from `novel_archive/<title>_<timestamp>/`. The `chapters/` and `output/` dirs survive overwrites because they're in separate directories from `scenes/` and `novel_state.yaml`. |
| Auditor + Storyteller deadlock | After 3 revisions, save with `ISSUES:` header. Orchestrator decides. |
| Character goes off-rails | Discard response. Re-run with stronger constraints + negative example. |
| Context overflow | Profiles are truncated; chapters >2 back use summaries only. ~4.5K token budget. |
| State corruption | Restore from latest `.snapshots/` backup. |
| Prose Stylist changes plot | Discard stylist's version. Use pre-stylist draft. Flag in `stylist_notes` with type `narrative_issue` for Storyteller to address. |
| Brief validation fails twice | Escalate to Orchestrator to restructure or merge scene. |
| Chapter flagged | Orchestrator runs immediate review. Three triggers: revision stalemate (3 rounds), cross-scene continuity problems, state contradictions (character in two places, timeline gap). |
| Dashboard shows "Untitled" / empty data | `pip install pyyaml` — the dashboard/progress scripts silently return empty dicts without it |
| Character KeyError on `growth` | Not all characters have all expected fields. Always use `.get()` with defaults when accessing character YAML, especially `growth`, `chapters`, `key_moments` |
| Lore audit critical issues | Take them seriously. 3 of 10 issues in Ch2 were critical (wrong cause of death, class assigned too early, contradictory wound origin). Targeted revision worked perfectly. |
| Word count shows 0 | Counter must scan `scenes/`, `chapters/`, AND `output/` dirs, deduplicating per chapter number (prefer `_polished` over plain filenames) |

### Sequential Chapter Generation via delegate_task (For Long Novels)

For novels longer than ~5 chapters, the per-scene Scene Sandbox pipeline becomes computationally expensive. A proven alternative is **sequential chapter delegation**:

**Pattern:** One `delegate_task` call per chapter, with ALL necessary context provided inline in the initial prompt. The subagent writes the full chapter and saves it to disk. No file reads by the subagent. No per-scene agent calls.

**Why this works:**
- By chapter 10+, a subagent reading previous chapters from disk can consume 300K-500K input tokens per chapter
- Providing inline summaries keeps each call to ~20K-40K tokens
- The subagent has full creative freedom within the chapter boundaries
- State updates happen at the orchestrator level between chapters

**Context block to provide inline (every single chapter):**
```
## PREVIOUS CHAPTERS SUMMARY
Ch1: [2-3 sentence summary]
Ch2: [2-3 sentence summary]
... (all previous chapters)

## THIS CHAPTER PLAN
Title: [title]
Summary: [1-2 sentences]
Scenes: [scene list with summaries]
Characters present: [who appears]

## CHARACTER PROFILES (current state)
[Name]: Age [X], current physical/mental state, key motivations right now
[Name]: Age [X], current state, what they want in this chapter

## WORLD STATE (what's true now)
- Time: [how much time has passed]
- Location: [where are they]
- Key facts: [what characters know]
- Pending threats: [what's coming]

## STYLE RULES
- [genre] tone
- [specific constraints, e.g. NO em-dashes]
- Target: [word count] words

## OUTPUT
Write complete chapter with scene breaks (***). Save to [path].
```

**Critical rules:**
1. **Explicit ages and time**: For novels spanning years or centuries, state every character's exact age in every chapter's context. The subagent will drift otherwise (e.g., Kira was "6-7" in Ch3 and "16" in Ch5 — without explicit tracking, later chapters may contradict this).
2. **No file reads**: Tell the subagent: "Do NOT read any files. All context is provided above." If the subagent tries to `read_file` or `search_files`, it will explode token usage.
3. **Verify after each chapter**: Check word count and em-dash count before updating state.
4. **Update state before next chapter**: The orchestrator (main agent) updates `novel_state.yaml` with the chapter summary, character state changes, and world changes. This becomes the source of truth for the next chapter's context block.

**Trade-off:** You lose the Scene Sandbox's independent character agency. The subagent acts as a combined Storyteller+Character Agent. For many novels, this is acceptable. For novels where character-driven surprise is essential, use Scene Sandbox for key multi-character scenes and sequential delegation for transitional/solo chapters.

**Token budget reality:**
| Chapter | Inline context | File-reading subagent |
|---------|---------------|----------------------|
| 1-5 | ~15K tokens | ~20K tokens |
| 10 | ~25K tokens | ~150K tokens |
| 16-20 | ~35K tokens | ~400K+ tokens |

The inline approach scales linearly. The file-reading approach scales exponentially.

### Practical Generation Flow (What Actually Happens)

The pipeline described above is the ideal flow. In practice, here's what works:

### M0: Outline Generation
1. **Generate the outline yourself** (in the main agent) — delegate_task agents can't reliably write YAML state files. Build the full `novel_state.yaml` with all characters, world, locations, and chapter plans.
2. **Immediately audit** via delegate_task with the Orchestrator Auditor prompt. Pass the outline and ask for: arc completeness, character balance, pacing, theme presence, plausibility.
3. **Revise the outline** based on auditor feedback. Common issues: missing chapters for resolution, characters who disappear for 3+ chapters, dropped plot threads (e.g., a rebalancing event that never resolves), romantic/found-family beats that are missing.
4. **Validate YAML** after every edit to `novel_state.yaml`. Use `yaml.safe_load()` — the patch tool strips leading whitespace on deeply-nested items, and `|` block scalars eat sibling keys if indented wrong.

### M1+: Chapter Generation (per chapter)
For each chapter, run these steps in order:

1. **Storyteller** → Generate scene briefs via delegate_task
   - Pass: the chapter outline, character profiles for all characters in the chapter, world rules
   - Each brief covers: setting, conflict, characters present, intended outcome, beat structure, character goals
   - Target: 3-5 beats per scene, narrative role annotated (climactic/standard/transitional/reaction)

2. **Storyteller** → Self-validate each brief
   - Check against chapter plan, world state, character knowledge boundaries
   - If fails: revise once. If still fails: flag scene, skip.

3. **Character Agents** → Scene Strategy generation via delegate_task (one call per character, or batched)
   - Pass: full scene brief + character profile + what they know about other present characters
   - Each agent outputs a beat-by-beat plan: action, dialogue, internal reaction, intention
   - Agents do NOT see each other's strategies. They plan in isolation.
   - **Skip this step for single-character scenes.**

4. **Storyteller** → Weave all strategies into full scene prose via delegate_task
   - Pass: the scene brief + ALL character strategies + character voice profiles
   - Storyteller is the director: decides when characters interrupt, speak over each other, act simultaneously
   - Resolves conflicts according to dramatic logic (who has more at stake, whose arc needs the win)
   - Adds environmental beats, sensory details, pacing
   - Target: ~1500-2000 words per scene

5. **Character Agents** → Voice-check pass via delegate_task
   - Pass: the scene draft + each character's full profile
   - Each agent reviews their own lines and flags violations
   - If >50% of a character's lines are flagged: the persona is underspecified. PAUSE and improve the profile.

6. **Storyteller** → Revise flagged lines only
   - Untouched text must remain verbatim
   - If no flags: skip this step

7. **Lore Auditor** → Consistency check via delegate_task
   - Pass: the scene draft, the novel state (characters, world rules, timeline)
   - Ask for: continuity errors, character voice violations, world rule breaks, knowledge leaks, pacing issues, theme absence, **em-dashes in prose**
   - Each issue must include: type, severity, exact passage quote, suggested fix
   - If AUDIT_PASS, move on. If issues found: targeted revision (only flagged passages), max 3 rounds

8. **Prose Stylist** → Polish pass via delegate_task
   - Pass: the scene draft, character voice profiles, genre
   - Content boundary: prose quality ONLY, never narrative content
   - After revision cycles: narrow re-pass on revised passages only
   - **Remove any em-dashes** (`—` or `--`) found in the prose. Use commas, periods, or separate sentences.
   - Output: polished scene file + stylist_notes

9. **State Update** → Update `novel_state.yaml`
   - Increment `meta.state_version`
   - Apply append-only rules for timeline and audit_log
   - Update character relationships with explicit old_value/new_value
   - Validate: check for duplicate timeline events, old_value mismatches, missing required fields
   - If validation fails: restore from snapshot, flag scene, PAUSE for human review
   - Add chapter to `chapters` list with scene word counts and status
   - Update `meta.current_chapter` and `meta.current_scene`
   - Add chapter summary to `summaries.chapter_summaries`
   - Update character `growth.current_state` and `growth.chapters`
   - Update `summaries.character_arcs_so_far`

10. **Dashboard & Progress** → Update tracking
    - Run `progress.py update_progress()`
    - Run `dashboard.py --static`
    - Save chapter to `output/chapter_XX.md`
    - Snapshot state to `.snapshots/`

### Novel Completion

When the last chapter is generated, three things must happen that are easy to forget:

1. **Assemble the final chapter** — scene drafts exist in `scenes/chXX_sYY_draft.md` but the assembled `chapters/chapter_XX.md` may not have been created yet. Check and assemble if missing.
2. **Add the chapter to `novel_state.yaml`** — the `chapters` list must include the final chapter with status `complete` and per-scene word counts. Set `meta.current_chapter` and `meta.current_scene` to the final values. Add `meta.status: complete` — this is the "novel is done" flag that the dashboard reads.
3. **Create the final snapshot** — `.snapshots/chapter_XXX.yaml` for the last chapter.

Without these, the dashboard won't show completion and may not show the last chapter at all.

### Dashboard Before Any Prose Exists

The dashboard reads from `chapters` array in novel_state.yaml, which is empty before generation starts. To show planned chapters, the dashboard's `get_progress_data()` function has a fallback: if `chapters` is empty, it reads from `outline.chapter_plan` and shows all scenes as "planned" status. This was added after the dashboard showed "No chapters generated yet" despite having a full 12-chapter outline. If you regenerate the dashboard, make sure this fallback is in place.

### Dashboard Completion Flag

The dashboard checks `meta.status` in the state file. When set to `"complete"`, it renders:
- Title: `"Title ✨ COMPLETE ✨"`
- Subtitle: shows total words, pages, and "ALL N CHAPTERS DONE"
- Word/scene progress bars: 100%, green fill, celebration labels (🎉 Target achieved!, 🎉 ALL DONE!)
- Page label: `"N pages ✨"` instead of `"of ~N target"`

The `get_progress_data()` function computes `novel_status` as `"complete"` only when ALL chapters are `status: complete` AND `meta.status == "complete"`. Both must be true.

### YAML Editing Pitfalls (LEARNED THE HARD WAY)

1. **Literal block scalars eat sibling keys**: If `narrative_arc: |` is at 2-space indent under `outline:`, then `chapter_plan:` must also be at 2-space indent — NOT inside the `|` block. The block ends when indentation returns to the key level.

2. **Patch tool strips leading whitespace**: When patching deeply-nested YAML list items (e.g., `        - "some string"`), the patch tool may produce `- "some string"` at column 0 instead. Always verify indentation after patching YAML. Fall back to `execute_code` with line-level fixes if patch mangles indent.

3. **Always validate after editing**: Run `yaml.safe_load()` after any edit to `novel_state.yaml`. A single mis-indented line can corrupt the entire state file.

4. **Quote escaping in YAML**: Double quotes inside double-quoted strings must be escaped (`\"`), or use single quotes for the outer wrapper. The string `"He's been worsening her condition through her \"medicine\""` will fail — use `'He\'s been worsening her condition through her "medicine"'` or swap to single quotes inside.

### Character Voice Profile Pattern

When delegating to the Storyteller or Character Agent, always pass the FULL voice profile, not just the name:
- `voice_description` (paragraph describing how they speak)
- `voice_examples` (5 situations: greeting, stress, reflection, anger, dishonesty)
- `behavioral_constraints` ('would NEVER' and 'always' rules)
- `motivations`, `fears`, `secrets`
- `knowledge.learned_facts` (what they know so far)
- `knowledge.knowledge_boundaries` (what they DON'T know)
- `knowledge.misbeliefs` (what they believe wrongly)

For single-character chapters (like Ch1 where only Marcus appears), the Character Agent step can be simplified — the Storyteller handles internal monologue directly.

### Single-Character Chapter Shortcut

When only ONE character appears in every scene of a chapter (e.g., Ch1 with only Marcus), you can skip the Character Agent delegation step. The Storyteller generates the entire chapter as narrative prose with the character's internal voice. This saved ~3 agent calls per scene in Ch1.

## State File Architecture

The state file (`novel_state.yaml`) tracks metadata and summaries — NOT full prose. Prose lives in separate files:

- Scene drafts → `scenes/chXX_sYY_draft.md`
- Scene finals → `scenes/chXX_sYY_final.md`  
- Character turns → `scenes/chXX_sYY_turns.json`
- Assembled chapters → `chapters/chapter_XX.md`
- Snapshots → `.snapshots/chapter_XXX.yaml` after each chapter

Inline in state: brief, validation status, audit results, stylist notes, adjudications, revision counts. NOT inline: draft prose, final prose, character turn responses. Storing prose inline bloats the YAML past what any agent can read by chapter 5.

## Publishing Pipeline (After Novel Completion)

Once the novel is marked `meta.status: "complete"`, run the publishing pipeline to generate a cover image and EPUB:

## Cover Generation (Dynamic — Reads from State)

The cover generator (`scripts/generate_cover.py`) reads `novel_state.yaml` to determine the genre and themes, then builds an appropriate prompt automatically. **No hardcoded prompts.**

- Sci-fi novels get: seedship, EVAC suits, AI spheres, shattered planets, deep space
- Fantasy novels get: medieval settings, magical elements, adventurers
- The prompt is built from `meta.genre` and `meta.seed` fields in the state file

```bash
cd novel_project
python3 scripts/generate_cover.py --seed 42
```

- Uses AnimagineXL 3.1 (SDXL anime model) via `diffusers` directly
- Output: `publish/cover_raw.png` (1024×1536, 2:3 light novel ratio)
- RTX 3070 Ti: ~48 seconds with sequential CPU offloading
- Options: `--seed N`, `--prompt "custom prompt"`, `--output PATH`
- **Must kill ComfyUI before generating** (`pkill -f comfyui`) — it holds 6+ GB VRAM

### Publishing Pipeline (Dynamic Metadata)

The publishing pipeline (`scripts/publish.py`) reads title, author, and genre from `novel_state.yaml`. **No hardcoded defaults.**

```bash
python3 scripts/publish.py --all     # Full pipeline: cover → title overlay → EPUB
python3 scripts/publish.py --overlay-only   # Just overlay title on existing cover
python3 scripts/publish.py --epub-only      # Just assemble EPUB from chapters
```

- Title and author are loaded from `novel_state.yaml` automatically
- EPUB filename is derived from `meta.title` (e.g., `The_Hollow_Stars.epub`)
- Cover embeds the correct title from state
- To override: `--title "Custom Title" --author "Name"`

### 4. Full Pipeline (All Steps)

```bash
python3 scripts/publish.py --all
```

### 5. Dashboard Integration

The dashboard automatically detects published assets:
- **EPUB download button** at `/download/epub` — appears as a prominent blue "Download EPUB" card
- **Cover thumbnail** displayed alongside the download card
- Both served via the `/files/publish/` and `/download/epub` routes
- Regenerate static dashboard after publishing: `python3 scripts/dashboard.py --static`

### Publishing Troubleshooting

| Problem | Solution |
|---------|----------|
| 0-byte chapters in EPUB | `EpubHtml.content` must be body HTML only, NOT a full XHTML document. ebooklib wraps content itself. Double-wrapping produces empty chapters. |
| `re.PatternError: bad escape \u` | Use lambda-based replacement for dialogue formatting, not raw string escapes. Python 3.13+ rejects `\u` in regex replacements. |
| CUDA OOM | Kill ComfyUI (`pkill -f comfyui`) to free VRAM; script uses sequential CPU offloading |
| BrokenPipeError in ComfyUI | Don't use ComfyUI API. Use `generate_cover.py` (diffusers) instead |
| CLIP token truncation warning | Normal for long prompts; first 77 tokens used |
| `total_mem` AttributeError | Use `total_memory` instead (already patched in script) |
| Fonts not found | `sudo dnf install dejavu-sans-fonts dejavu-serif-fonts` |
| EPUB missing chapters | Ensure all `chapters/chapter_01.md` through `chapter_12.md` exist |
| Duplicate stylesheet UIDs | Create `EpubItem(uid="stylesheet")` ONCE, add via `chapter.add_item(style_item)` |
| Cover not showing as Page 1 | Create manual `EpubHtml` cover page + add as FIRST item in `book.spine`. `set_cover(create_page=True)` does NOT add to spine |
| Duplicate cover image warning | `set_cover()` already adds the image file; don't add a separate `EpubItem` for it |
| Dashboard shows 2x word count | `count_total_words()` was counting both `scenes/` and `chapters/`. Only count `chapters/` (assembled prose), not intermediate scene drafts |

### Prerequisites

```bash
pip install ebooklib Pillow diffusers accelerate torch
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124  # CUDA support
sudo dnf install dejavu-sans-fonts dejavu-serif-fonts  # Fonts for cover overlay
```

## Full Plan

The complete system specification (state schema, agent prompts, failure modes, milestones) lives in `multi_agent_novel_plan.md` in the root directory alongside this skill. Read it for the full architectural details.

## Distributing This Skill to Other Hermes Users

This skill is already installed at `~/.hermes/skills/creative/novel-generator/`. To share it with other Hermes users:

### Option 1: GitHub Repo (Recommended)

A complete GitHub repo is staged at `/tmp/hermes-novel-generator/` with README, LICENSE, SKILL.md, prompts, scripts, and references. To push it:

1. Create empty public repo `hermes-novel-generator` at https://github.com/new
2. Run:
   ```bash
   cd /tmp/hermes-novel-generator
   git branch -m main
   git remote add origin https://github.com/rwcrosk-arch/hermes-novel-generator.git
   git push -u origin main
   ```
3. Users install with: `hermes skills install rwcrosk-arch/hermes-novel-generator/creative/novel-generator`

Hermes fetches via the GitHub Contents API, scans for security issues, quarantines, then installs to `~/.hermes/skills/`.

### Option 2: skills.sh (Vercel Directory)

Submit to [skills.sh](https://skills.sh). Users search and install:
```bash
hermes skills search novel --source skills-sh
hermes skills install skills-sh/yourorg/novel-generator
```

### Option 3: Well-Known Endpoint

Host `/.well-known/skills/index.json` on your site:
```json
{
  "skills": [
    {
      "name": "novel-generator",
      "description": "Multi-agent novel generation pipeline",
      "files": ["SKILL.md", "prompts/orchestrator.md", ...]
    }
  ]
}
```

Users install:
```bash
hermes skills install well-known:https://yoursite.com/.well-known/skills/novel-generator
```

### Trust Levels

| Level | How to Achieve | User Experience |
|-------|---------------|-----------------|
| `official` | Get merged into NousResearch/hermes-agent `optional-skills/` | Builtin trust, no warnings |
| `trusted` | Host in `openai/skills`, `anthropics/skills`, or similar known repo | More permissive policy |
| `community` | Any other GitHub repo or well-known endpoint | Third-party warning, `--force` may be needed |

### Important: `delegate_task` is Assistant-Native

This skill is a **procedural guide** for the assistant. `delegate_task` cannot be called from Python scripts or `execute_code`. Other Hermes users load the skill, and their assistant follows the step-by-step instructions in SKILL.md, calling `delegate_task` directly at the assistant level.

Scripts (`dashboard.py`, `progress.py`, `publish.py`) CAN be run via `terminal()` or `execute_code()` and should be included as linked files.

## Lessons from Production Incidents

### The "Hermes Tools Not Installed" Trap

When running the pipeline via `terminal()` or `execute_code()`, you may see:
```
WARNING: hermes_tools not available. Running in dry-run mode.
```

**This is correct and expected.** `delegate_task`, `read_file`, `write_file`, etc. are **assistant-level tools**, not Python imports. They cannot be used inside subprocess Python scripts. The pipeline script (`main.py`) has a fallback that prints this warning and skips agent calls — the actual agent orchestration happens at the assistant level, not in a subprocess.

**Never try to `import delegate_task` in Python.** It will fail. The assistant calls `delegate_task` directly as a tool invocation.

### The Overwrite Incident (The Hollow Stars)

A completed 182,519-word novel with 20 chapters and a published EPUB was nearly destroyed because:
1. A new generation was started without archiving
2. `novel_state.yaml` was overwritten directly via `write_file`
3. Scene files in `scenes/` were partially clobbered
4. Only `chapters/` and `output/` survived because they were in separate directories

**Recovery pattern:**
```bash
# Check what survived
find novel_project/chapters -name "*.md" | wc -l   # chapters/ usually survives
find novel_project/output -name "*.epub"           # EPUB usually survives
find novel_project/scenes -name "*.md" | wc -l     # scenes/ often partially lost

# Emergency archive
cp -r novel_project novel_archive/<title>_<timestamp>/

# Reconstruct state from chapters
# Read chapter files to extract: title, characters, plot points
# Rebuild novel_state.yaml with recovered metadata
# Rebuild PROGRESS.md with chapter word counts
```

**Why chapters/ survives:** The pipeline writes to `scenes/` during generation, then assembles to `chapters/` at chapter-end. If a new run starts mid-novel, it overwrites `scenes/` and `novel_state.yaml` but leaves `chapters/` untouched until the new run reaches assembly.

### Verify Before Destructive Operations

Before ANY write to `novel_state.yaml`, `scenes/`, or destructive action:
1. Check if existing work exists (`check_existing_novel()`)
2. If the user says "generate a novel" and work already exists, ASK: "You have a completed novel 'Title' with N chapters. Archive it first?"
3. Never assume "generate a novel" means "start fresh" — the user may mean "continue" or "regenerate cover"

### When the User Says a Novel Is Already Done

If the user says "wasn't this novel already done?" or "the exported EPUB is still there":
1. **STOP all generation immediately**
2. Check `novel_project/chapters/` for existing chapter files
3. Check `novel_project/output/` for existing EPUB
4. Check `novel_project/novel_state.yaml` for `meta.title`
5. Archive before any new work
6. Do not overwrite until explicitly confirmed by user