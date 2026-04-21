# Multi-Agent Novel Generator — Main Orchestration Script
# This is the core loop that drives the entire novel generation process.
# Run via: python scripts/main.py --seed "Your novel concept here"

import json
import yaml
import os
import sys
import copy
from datetime import datetime, timezone
from pathlib import Path

try:
    from hermes_tools import delegate_task, read_file, write_file, terminal
except ImportError:
    # If running standalone, delegate_task won't work
    print("WARNING: hermes_tools not available. Running in dry-run mode.")
    delegate_task = None

# Import progress tracker
try:
    from progress import update_progress, count_total_words, LENGTH_TARGETS
except ImportError:
    from scripts.progress import update_progress, count_total_words, LENGTH_TARGETS

PROJECT_ROOT = Path(__file__).parent.parent
STATE_FILE = PROJECT_ROOT / "novel_state.yaml"
SCENES_DIR = PROJECT_ROOT / "scenes"
SNAPSHOTS_DIR = PROJECT_ROOT / ".snapshots"
CHAPTERS_DIR = PROJECT_ROOT / "chapters"
OUTPUT_DIR = PROJECT_ROOT / "output"

# ============================================================
# SAFETY CHECK — PREVENT OVERWRITING EXISTING NOVELS
# ============================================================

def check_existing_novel():
    """Check if a completed or in-progress novel already exists.
    
    This is a CRITICAL safety check. If a novel exists in the project,
    we MUST archive it before starting a new one. Otherwise we risk
    destroying completed work.
    
    Returns True if safe to proceed, False if a novel exists.
    """
    existing = []
    
    # Check for chapter files
    if CHAPTERS_DIR.exists():
        chapter_files = list(CHAPTERS_DIR.glob("chapter_*.md"))
        if chapter_files:
            existing.append(f"{len(chapter_files)} chapter files in chapters/")
    
    # Check for EPUB
    if OUTPUT_DIR.exists():
        epub_files = list(OUTPUT_DIR.glob("*.epub"))
        if epub_files:
            existing.append(f"EPUB: {', '.join(f.name for f in epub_files)}")
    
    # Check state file for a title
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                state = yaml.safe_load(f) or {}
            title = state.get('meta', {}).get('title', '')
            if title:
                existing.append(f"novel_state.yaml has title: '{title}'")
        except Exception:
            pass
    
    # Check for scene files
    if SCENES_DIR.exists():
        scene_files = list(SCENES_DIR.glob("ch*_s*_final.md"))
        if len(scene_files) > 2:  # Allow a couple scenes from setup
            existing.append(f"{len(scene_files)} completed scene files")
    
    if existing:
        print("\n" + "="*60)
        print("  ⚠️  EXISTING NOVEL DETECTED")
        print("="*60)
        print("\nThe following existing work was found:")
        for item in existing:
            print(f"  • {item}")
        print("\nYou MUST archive this novel before starting a new one.")
        print("\nRun one of these commands first:")
        print("  python scripts/main.py --archive    # Archive only, keep project")
        print("  python scripts/main.py --clean      # Archive and reset for new novel")
        print("\nOr run:  python scripts/progress.py archive")
        print("="*60 + "\n")
        return False
    
    return True

# ============================================================
# STATE MANAGEMENT
# ============================================================

def load_state():
    """Load novel_state.yaml from disk."""
    with open(STATE_FILE, 'r') as f:
        return yaml.safe_load(f)

def save_state(state):
    """Save novel_state.yaml to disk, creating a backup first."""
    # Backup current state before overwriting
    if STATE_FILE.exists():
        backup = STATE_FILE.with_suffix('.yaml.bak')
        with open(STATE_FILE, 'r') as f:
            backup.write_text(f.read(), encoding='utf-8')
    
    state['meta']['last_modified'] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, 'w') as f:
        yaml.dump(state, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

def snapshot_state(state, chapter_num):
    """Snapshot state after a completed chapter."""
    snap_path = SNAPSHOTS_DIR / f"chapter_{chapter_num:03d}.yaml"
    with open(snap_path, 'w') as f:
        yaml.dump(state, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    print(f"  Snapshot saved: {snap_path}")

def save_scene_prose(chapter_num, scene_num, prose, stage="final"):
    """Save scene prose to a separate file."""
    filename = f"ch{chapter_num:02d}_s{scene_num:02d}_{stage}.md"
    filepath = SCENES_DIR / filename
    filepath.write_text(prose, encoding='utf-8')
    print(f"  Scene prose saved: {filepath}")
    return str(filepath)

# ============================================================
# CONTEXT BUILDER
# ============================================================

def truncate_character_profile(state, char_id):
    """Truncate a character profile to essentials for context budget.
    
    Always include: id, name, role, voice_description, behavioral_constraints,
    knowledge_boundaries, misbeliefs, current relationships status, current growth state.
    Include if in scene: voice_examples, relevant learned_facts.
    Truncate: growth.arc (one line), growth.chapters (current + previous only),
    relationship.key_moments (recent only).
    """
    char = get_char_by_id(state, char_id)
    if not char:
        return {}
    
    return {
        'id': char['id'],
        'name': char['name'],
        'role': char.get('role', ''),
        'voice_description': char.get('persona', {}).get('voice_description', ''),
        'behavioral_constraints': char.get('persona', {}).get('behavioral_constraints', []),
        'knowledge_boundaries': char.get('knowledge', {}).get('knowledge_boundaries', ''),
        'misbeliefs': char.get('knowledge', {}).get('misbeliefs', []),
        'relationships': [
            {'with': r['with'], 'type': r['type'], 'status': r['status']}
            for r in char.get('relationships', [])
        ],
        'current_state': char.get('growth', {}).get('current_state', ''),
        'voice_examples': char.get('persona', {}).get('voice_examples', []),
        'relevant_facts': char.get('knowledge', {}).get('learned_facts', []),
        # Omitted: full growth.arc, growth.chapters history, key_moments details
    }

def get_char_by_id(state, char_id):
    """Look up a character by ID in state."""
    for char in state.get('characters', []):
        if char['id'] == char_id:
            return char
    return None

def get_active_characters(initial_chars, entering, exiting, beat_idx):
    """Determine which characters are present at a given beat.
    
    Characters in 'entering' join starting from their specified beat.
    Characters in 'exiting' leave after their specified beat.
    """
    active = list(initial_chars)
    for entry in (entering or []):
        if entry.get('beat', 0) <= beat_idx:
            if entry['character_id'] not in active:
                active.append(entry['character_id'])
    for exit_spec in (exiting or []):
        if exit_spec.get('beat', float('inf')) <= beat_idx:
            active = [c for c in active if c != exit_spec['character_id']]
    return active

def estimate_tokens(text):
    """Rough token estimate: ~4 chars per token for English text."""
    if isinstance(text, dict):
        text = yaml.dump(text, default_flow_style=False)
    return len(str(text)) // 4

CONTEXT_TOKEN_BUDGET = 6000  # Conservative budget for agent context

def trim_for_context(context, budget=CONTEXT_TOKEN_BUDGET):
    """Trim context payload to stay within token budget.
    
    Escalation order (in order of least to most impactful):
    1. Drop voice_examples from character profiles
    2. Drop learned_facts from character knowledge
    3. Drop older chapter summaries (keep last 1 only)
    4. Drop world rules entirely
    5. Drop character_arcs summary
    """
    current = estimate_tokens(context)
    if current <= budget:
        return context, []  # No trimming needed
    
    trim_log = []
    
    # Level 1: Drop voice_examples from characters
    if 'characters' in context:
        for char in context['characters']:
            if 'voice_examples' in char:
                del char['voice_examples']
        current = estimate_tokens(context)
        trim_log.append("dropped voice_examples")
        if current <= budget:
            return context, trim_log
    
    # Level 2: Drop learned_facts
    if 'characters' in context:
        for char in context['characters']:
            if 'relevant_facts' in char:
                del char['relevant_facts']
        current = estimate_tokens(context)
        trim_log.append("dropped learned_facts")
        if current <= budget:
            return context, trim_log
    
    # Level 3: Keep only the most recent chapter summary
    summary_keys = [k for k in list(context.keys()) if k.startswith('ch') and k.endswith('_summary')]
    if len(summary_keys) > 1:
        # Find the summary closest to the current chapter
        best_key = None
        best_ch = -1
        for k in summary_keys:
            try:
                ch_num = int(k.replace('ch', '').replace('_summary', ''))
                if ch_num > best_ch:
                    best_ch = ch_num
                    best_key = k
            except ValueError:
                continue
        # Delete all except the most recent
        for k in summary_keys:
            if k != best_key:
                del context[k]
        current = estimate_tokens(context)
        trim_log.append(f"kept only ch{best_ch}_summary, dropped {len(summary_keys)-1} older summaries")
        if current <= budget:
            return context, trim_log
    
    # Level 4: Drop world rules
    if 'world_rules' in context:
        del context['world_rules']
        trim_log.append("dropped world_rules")
        current = estimate_tokens(context)
        if current <= budget:
            return context, trim_log
    
    # Level 5: Drop character arcs summary
    if 'character_arcs' in context:
        del context['character_arcs']
        trim_log.append("dropped character_arcs")
    
    return context, trim_log


def build_agent_context(state, chapter_num, scene_num, agent_role):
    """Build a context payload that stays within token budget.
    
    Checks context size before returning. If over budget, applies
    progressive trimming and logs what was dropped.
    """
    context = {}
    
    # Always include: meta, world rules, current chapter outline
    context['meta'] = state.get('meta', {})
    context['world_rules'] = state.get('world', {}).get('rules', '')
    context['current_chapter_plan'] = state.get('outline', {}).get('chapter_plan', [{}])[chapter_num - 1] if chapter_num <= len(state.get('outline', {}).get('chapter_plan', [])) else {}
    
    # Recent chapter summaries (last 2 full, older arc summaries only)
    for summary in state.get('summaries', {}).get('chapter_summaries', []):
        if chapter_num - summary.get('chapter', 999) <= 2:
            context[f'ch{summary["chapter"]}_summary'] = summary
    context['character_arcs'] = state.get('summaries', {}).get('character_arcs_so_far', {})
    
    # Current scene full detail
    chapters = state.get('chapters', [])
    if chapter_num <= len(chapters):
        scenes = chapters[chapter_num - 1].get('scenes', [])
        if scene_num <= len(scenes):
            context['current_scene'] = scenes[scene_num - 1]
    
    # Only relevant character profiles (characters in this scene)
    scene = context.get('current_scene', {})
    brief = scene.get('brief', {}) if isinstance(scene, dict) else {}
    chars_present = brief.get('characters_present', [])
    context['characters'] = [
        truncate_character_profile(state, cid)
        for cid in chars_present
    ]
    
    # Apply context overflow guardrail
    context, trim_log = trim_for_context(context)
    if trim_log:
        print(f"  Context trimmed: {', '.join(trim_log)}")
    
    return context

# ============================================================
# GENERATION LOOP STEPS
# ============================================================

def generate_outline(seed, author, publisher=None, year=None, location=None, copyright_text=None, target="short_novel"):
    """M0: Orchestrator produces outline from seed."""
    print("\n=== M0: Generating Outline ===")
    
    target_words = LENGTH_TARGETS.get(target, 60000)
    target_labels = {
        "novella": "novella, ~110 paperback pages",
        "short_novel": "short novel, ~220 paperback pages", 
        "novel": "standard novel, ~290 paperback pages",
        "epic": "epic novel, ~365+ paperback pages",
    }
    target_length_label = target_labels.get(target, target_labels["short_novel"])
    
    if delegate_task is None:
        print("ERROR: hermes_tools not available. Cannot generate outline.")
        return None
    
    # Build publishing metadata block
    publishing_meta = f"""author: \"{author}\""
"""
    if publisher:
        publishing_meta += f"  publisher: \"{publisher}\"\n"
    if year:
        publishing_meta += f"  year: \"{year}\"\n"
    if location:
        publishing_meta += f"  location: \"{location}\"\n"
    if copyright_text:
        publishing_meta += f"  copyright: \"{copyright_text}\"\n"
    
    result = delegate_task(
        goal="Generate a complete novel outline from the user's seed concept",
        context=f"""
You are the ORCHESTRATOR agent for a multi-agent novel generation system.

Create a detailed novel outline for this concept:

SEED: {seed}

PUBLISHING METADATA (include in meta section):
{publishing_meta}

Output a YAML structure with ALL of the following sections:

1. **meta**: title, genre, the seed itself, author (MANDATORY), and optional publishing fields (publisher, year, location, copyright). Include created timestamp.

2. **outline**:
   - premise (one-line story premise)
   - themes (list of 2-3 core themes)
   - narrative_arc (Act I/II/III structure with descriptions)
   - chapter_plan: at least 10 chapters, each with:
     - number, title, summary, key_events, characters_involved
     - scene_list: each scene with number, narrative_role (climactic/standard/transitional/reaction), summary, characters_present

3. **world**: 
   - rules (established rules of this world)
   - locations (at least 3 key locations with id, name, description)
   - history (key events before the story)
   - timeline (can start empty, will be populated during generation)

4. **characters**: at least 3 major characters, each with:
   - id, name, role (protagonist/antagonist/supporting)
   - persona with:
     - voice_description (how they speak - vocabulary, sentence length, tics, emotional register)
     - voice_examples (at least 5 situations with dialogue: greeting stranger, under stress, reflecting, angry, being dishonest)
     - behavioral_constraints (things they'd NEVER do, things they always do)
     - motivations, fears, secrets
   - relationships (with other characters: type, status, key_moments)
   - knowledge (learned_facts that start empty, knowledge_boundaries, misbeliefs)
   - growth (arc description, current_state)

Be SPECIFIC. Vague characters produce vague dialogue. The more specific the voice_description and behavioral_constraints, the more distinct each character will sound.

LENGTH TARGET: This novel should target approximately {target_words:,} words ({target_length_label}). 
- Average scene: ~2,000-3,000 words
- Average chapter: ~6,000-10,000 words  
- Plan the chapter count and scene count accordingly
- A paperback page is approximately 275 words

Save the complete YAML to: novel_project/novel_state.yaml
""",
        toolsets=['terminal', 'file']
    )
    
    return result

def review_outline(state):
    """Orchestrator Auditor reviews outline before any chapters are written."""
    print("\n=== Outline Review ===")
    
    if delegate_task is None:
        print("WARNING: Cannot run auditor review without hermes_tools.")
        return {"approved": True, "suggestions": []}
    
    result = delegate_task(
        goal="Review the novel outline for structural problems",
        context=f"""
You are the ORCHESTRATOR AUDITOR. Review this novel outline for problems
BEFORE any chapters are written.

Read the outline from: novel_project/novel_state.yaml

Check for:
1. **Arc completeness**: Does the outline have a clear beginning, middle, and end?
2. **Character balance**: Are all major characters involved in enough chapters to justify their presence?
3. **Pacing plan**: Is event density appropriate — not too many events in early chapters, not too few in the climax?
4. **Theme presence**: Are the declared themes actually represented in the chapter events?
5. **Plausibility**: Are there obvious plot holes or character motivation gaps in the outline?

Output YAML with:
- approved: true/false
- issues: list of specific problems found
- suggestions: list of actionable improvements with priority (high/medium/low)

If the outline is fundamentally sound with only minor suggestions, approve it.
Only reject if there are structural problems that would make the novel incoherent.
""",
        toolsets=['terminal', 'file']
    )
    
    return result

def generate_scene_brief(chapter_num, scene_num, state):
    """M1: Storyteller produces scene brief from chapter plan."""
    print(f"\n=== Generating Scene Brief: Ch{chapter_num} Sc{scene_num} ===")
    
    chapter = state['chapters'][chapter_num - 1]
    scene_info = chapter['scenes'][scene_num - 1] if scene_num <= len(chapter.get('scenes', [])) else None
    
    # Get the scene info from the outline's chapter plan
    chapter_plan = state['outline']['chapter_plan'][chapter_num - 1]
    
    result = delegate_task(
        goal=f"Write a detailed scene brief for Chapter {chapter_num}, Scene {scene_num}",
        context=f"""
You are the STORYTELLER/DM. Write a scene brief for this scene.

CHAPTER PLAN:
Title: {chapter_plan.get('title', '')}
Summary: {chapter_plan.get('summary', '')}
Key Events: {chapter_plan.get('key_events', [])}
Characters Involved: {chapter_plan.get('characters_involved', [])}

SCENE INFO (from outline):
{narrative_role if scene_info else 'standard'} scene
{scene_info.get('summary', '') if scene_info else ''}

WORLD RULES:
{state.get('world', {}).get('rules', '')}

CHARACTER PROFILES (relevant to this scene):
{yaml.dump([truncate_character_profile(state, cid) for cid in (scene_info.get('characters_present', []) if scene_info else chapter_plan.get('characters_involved', []))], default_flow_style=False)}

Create a scene brief in YAML with:
- setting: Where and when this scene takes place
- conflict: What tension drives this scene
- characters_present: list of character IDs
- characters_entering: list of {{character_id, beat}} for characters who arrive mid-scene (leave empty if none)
- characters_exiting: list of {{character_id, beat}} for characters who leave mid-scene (leave empty if none)
- intended_outcome: What should change by scene end
- narrative_role: climactic/standard/transitional/reaction
- beat_structure: list of beats (2-8 depending on role), each with:
  - beat: short name (e.g., "opening_hook", "rising_1", "turning_point", "resolution")
  - description: what happens in this beat
- character_goals: dict mapping character IDs to their goals for this scene

Save the brief as YAML. Include ONLY the brief section, not the full state.
""",
        toolsets=['terminal', 'file']
    )
    
    return result

def validate_scene_brief(scene_brief, state, chapter_num):
    """M2: Storyteller validates scene brief before character agents see it."""
    print("  Validating scene brief...")
    
    result = delegate_task(
        goal="Validate this scene brief for consistency problems",
        context=f"""
You are a Storyteller checking your own scene brief for problems
before it goes to character agents.

SCENE BRIEF:
{yaml.dump(scene_brief, default_flow_style=False)}

CHAPTER PLAN:
{yaml.dump(state['outline']['chapter_plan'][chapter_num - 1], default_flow_style=False)}

WORLD STATE:
{yaml.dump(state.get('world', {}), default_flow_style=False)}

CHARACTER KNOWLEDGE BOUNDARIES:
{chr(10).join(f"{c['name']}: doesn't know {c.get('knowledge', {}).get('knowledge_boundaries', 'N/A')}" for c in state.get('characters', []) if c['id'] in scene_brief.get('characters_present', []))}

Check for:
1. Character placement: Is each character somewhere they can actually be?
2. Knowledge leaks: Does this brief assume characters know things they haven't learned yet?
3. Goal alignment: Do character goals match their stated motivations?
4. Beat structure: Does the beat structure serve the intended outcome?
5. World consistency: Does this scene respect established world rules?

If you find problems, list them with specific fixes.
If the brief is sound, respond: BRIEF_VALID
""",
        toolsets=['terminal', 'file']
    )
    
    return result

def generate_character_turns(chapter_num, scene_num, state):
    """M3-M4: Turn-based character dialogue within a scene."""
    scene = state['chapters'][chapter_num-1]['scenes'][scene_num-1]
    brief = scene['brief']
    beats = brief['beat_structure']
    
    character_turns = []
    
    for beat_idx, beat in enumerate(beats):
        print(f"  Beat {beat_idx+1}/{len(beats)}: {beat['beat']}")
        
        # Track who's present at this beat
        active = get_active_characters(
            brief['characters_present'],
            brief.get('characters_entering', []),
            brief.get('characters_exiting', []),
            beat_idx
        )
        
        # Storyteller narrates beat setup
        beat_setup = delegate_task(
            goal=f"Narrate beat setup for {beat['beat']}",
            context=f"""
You are the Storyteller/DM. Narrate the setup for this beat:

Beat: {beat['beat']} - {beat['description']}
Scene: Chapter {chapter_num}, Scene {scene_num}
Setting: {brief['setting']}

Previous turns in this scene so far:
{yaml.dump(character_turns[-5:] if len(character_turns) > 5 else character_turns, default_flow_style=False)}

Describe the situation in 2-3 sentences. End with something that demands a character response.
Do NOT write dialogue for the characters — set up the situation for them to react to.
""",
            toolsets=['terminal', 'file']
        )
        
        # Each character reacts, round-robin
        for char_id in active:
            char = get_char_by_id(state, char_id)
            other_turns = [t for t in character_turns if t['character'] != char_id]
            
            result = delegate_task(
                goal=f"Respond as {char['name']} in the current scene beat",
                context=f"""
# You ARE {char['name']}

You are not narrating — you ARE this person. Respond only as {char['name']} would respond.

## Voice
{char['persona']['voice_description']}

### Speech Examples
{chr(10).join(f'- When {ex["situation"]}: "{ex["dialogue"]}"' for ex in char['persona']['voice_examples'])}

## Identity
- Role: {char['role']}
- Core motivation: {char['persona'].get('motivations', ['unknown'])[0]}
- Deepest fear: {char['persona'].get('fears', ['unknown'])[0]}
- Secret: {char['persona'].get('secrets', ['unknown'])[0]}

## Behavioral absolutes
You would NEVER: {', '.join(char['persona'].get('behavioral_constraints', [])[:2])}
You always: {', '.join(char['persona'].get('behavioral_constraints', [])[:2])}

## Current state
- Emotional state: {char.get('growth', {}).get('current_state', 'unknown')}
- What you know right now: {', '.join(char.get('knowledge', {}).get('learned_facts', []))}
- What you DON'T know: {char.get('knowledge', {}).get('knowledge_boundaries', 'unknown')}
- Misbeliefs you hold: {', '.join(char.get('knowledge', {}).get('misbeliefs', []))}

## Relationships right now
{yaml.dump([{r['with']: f"{r['type']}, {r['status']}"} for r in char.get('relationships', [])], default_flow_style=False)}

## Scene context
- Setting: {brief['setting']}
- Beat: {beat['description']} (beat {beat_idx+1} of {len(beats)})
- Your goal for this scene: {brief['character_goals'].get(char_id, 'unknown')}

## What just happened
{beat_setup}

## What other characters have said/done
{yaml.dump(other_turns[-3:], default_flow_style=False) if other_turns else 'No other character actions yet this beat.'}

## Rules
1. Stay in character. Always. No narrative asides.
2. Do not reveal information your character doesn't know.
3. React authentically — if something would upset your character, show it.
4. React to OTHER characters, not just the situation.
5. Don't resolve conflicts that aren't yours to resolve.
6. If you're unsure what your character would do, lean into their flaws.
7. Keep responses concise — dialogue and brief action beats, not monologues.
""",
                toolsets=['terminal', 'file']
            )
            
            character_turns.append({
                'beat': beat['beat'],
                'character': char_id,
                'response': result
            })
    
    return character_turns

def weave_scene(chapter_num, scene_num, state, character_turns):
    """M5: Storyteller weaves character turns into narrative prose."""
    scene = state['chapters'][chapter_num-1]['scenes'][scene_num-1]
    brief = scene['brief']
    
    result = delegate_task(
        goal=f"Weave character turns into narrative prose for Ch{chapter_num} Sc{scene_num}",
        context=f"""
You are the Storyteller. Transform these character turns into
flowing narrative prose for a novel scene.

SCENE BRIEF:
{yaml.dump(brief, default_flow_style=False)}

CHARACTER TURNS:
{yaml.dump(character_turns, default_flow_style=False)}

DO NOT just concatenate dialogue. Transform into a novel scene with:
- Action beats between dialogue
- Internal thoughts where appropriate
- Sensory details
- Proper scene structure matching the beat structure
- Natural dialogue flow — characters should feel like they're really talking

Write the complete scene. This is the RAW DRAFT — it will be checked by an auditor
and then polished by a stylist. Focus on getting the story right.
""",
        toolsets=['terminal', 'file']
    )
    
    return result

def audit_scene(chapter_num, scene_num, state):
    """M6: Lore Auditor checks scene for consistency violations."""
    scene = state['chapters'][chapter_num-1]['scenes'][scene_num-1]
    
    result = delegate_task(
        goal=f"Audit scene Ch{chapter_num} Sc{scene_num} for lore consistency violations",
        context=f"""
Read novel_project/novel_state.yaml for full world state and character definitions.
Read the current scene draft from: novel_project/scenes/ch{chapter_num:02d}_s{scene_num:02d}_draft.md

Check for:
1. Continuity errors (character locations, timeline, event references)
2. Character voice violations (dialogue that doesn't match persona)
3. World rule violations (magic/technology/social rules broken)
4. Knowledge leaks (character acts on info they shouldn't have)

For EACH issue found, specify:
- Type: continuity|character_voice|world_rule|knowledge_leak
- Severity: critical|important|minor
- Description: what's wrong
- Passage: quote the specific text that's problematic
- Suggested fix: how to resolve it

If no issues found, respond: AUDIT_PASS
""",
        toolsets=['terminal', 'file']
    )
    
    return result

def targeted_revision(chapter_num, scene_num, state, audit_issues):
    """M7: Storyteller revises ONLY flagged passages."""
    scene = state['chapters'][chapter_num-1]['scenes'][scene_num-1]
    
    result = delegate_task(
        goal=f"Perform targeted revision on flagged passages in Ch{chapter_num} Sc{scene_num}",
        context=f"""
You are the Storyteller. The Lore Auditor found issues in your scene draft.
Revise ONLY the flagged passages. Do NOT rewrite the entire scene.

Read the original draft from: novel_project/scenes/ch{chapter_num:02d}_s{scene_num:02d}_draft.md

AUDIT ISSUES:
{yaml.dump(audit_issues, default_flow_style=False)}

For each issue:
- Find the quoted passage in the original
- Revise ONLY that passage (and immediate context if needed)
- Leave all other text VERBATIM — do not change anything else
- If you disagree with an issue, note your disagreement but still attempt a fix

Output the complete revised scene with all corrections applied.
Untouched passages MUST remain identical to the original.
""",
        toolsets=['terminal', 'file']
    )
    
    return result

def polish_scene(chapter_num, scene_num, state, revised_sections=None):
    """M8: Prose Stylist polishes the scene.
    
    If revised_sections is provided, the stylist focuses on those passages
    plus ±1 paragraph of context. This prevents re-polishing already-vetted
    prose, which can cause quality drift over multiple revision cycles.
    """
    genre = state.get('meta', {}).get('genre', '')
    scene = state['chapters'][chapter_num-1]['scenes'][scene_num-1]
    
    if revised_sections:
        # Narrow re-pass: only polish the revised passages + context
        focus_instruction = f"""
SPECIAL INSTRUCTION: This scene has undergone {len(revised_sections)} revision(s) by the auditor.
Focus your polish on these revised passages and their immediate context (±1 paragraph).
Leave ALL other prose UNTOUCHED — it has already been vetted and polished.

REVISED PASSAGES TO FOCUS ON:
{chr(10).join(f'--- Revised Passage {i+1} ---{chr(10)}{s}' for i, s in enumerate(revised_sections))}

Only polish these passages and their immediate context. Copy all other text verbatim.
"""
    else:
        # Full-pass: polish the entire scene (first time through, no revisions)
        focus_instruction = ""
    
    result = delegate_task(
        goal=f"Polish prose quality for Ch{chapter_num} Sc{scene_num}",
        context=f"""
Read the scene draft from: novel_project/scenes/ch{chapter_num:02d}_s{scene_num:02d}_audited.md

Also read character voice profiles from novel_project/novel_state.yaml.

Improve the prose quality:
1. Voice differentiation — can you tell who's talking without attribution?
2. Prose rhythm — vary sentence length, avoid repetitive structures
3. Stitching artifacts — remove obvious joins between character contributions
4. Show don't tell — replace stated emotions with demonstrated ones
5. Genre tone — ensure prose matches the genre: {genre}

HARD RULE: You may ONLY modify prose quality. Do NOT change narrative content,
plot events, or character decisions. If narrative content needs changing,
note it in your output but do not change it yourself.
{focus_instruction}
Genre: {genre}

Output TWO things:
1. The polished scene prose
2. A list of stylist_notes describing what you changed and why

Save the polished prose to: novel_project/scenes/ch{chapter_num:02d}_s{scene_num:02d}_final.md
""",
        toolsets=['terminal', 'file']
    )
    
    return result

def update_state_after_scene(state, chapter_num, scene_num, scene_final, audit_result):
    """Orchestrator updates novel_state.yaml after a scene completes."""
    print(f"  Updating state after Ch{chapter_num} Sc{scene_num}...")
    
    result = delegate_task(
        goal=f"Update the novel state after completing Ch{chapter_num} Sc{scene_num}",
        context=f"""
You are the Orchestrator. A scene has just been completed.
Read the scene's final prose from: novel_project/scenes/ch{chapter_num:02d}_s{scene_num:02d}_final.md
Read the current state from: novel_project/novel_state.yaml

Produce a YAML update with the following sections:

1. **world.timeline**: Add new events from this scene
   - event: "description of what happened"
   - chapter: {chapter_num}
   - scene: {scene_num}
   - date_in_story: "if applicable"

2. **characters[].relationships[]**: Update any relationship changes
   - Update status and add to key_moments for shifted relationships

3. **characters[].growth.chapters[]**: Add chapter entry for each character who appeared
   - state_before: "emotional state entering the scene"
   - state_after: "emotional state after the scene"
   - key_realization: "what happened to them"

4. **summaries.chapter_summaries**: Update or create current chapter summary
   - summary: "2-3 sentence plot summary"
   - key_revelations: ["what was revealed"]
   - relationship_changes: ["what shifted between whom"]
   - world_changes: ["new facts about the world"]

5. **summaries.character_arcs_so_far**: Update one-liner arcs for characters who appeared

6. **Scene status**: Set to "complete"

Save the updated novel_state.yaml.
""",
        toolsets=['terminal', 'file']
    )
    
    return result

def assemble_chapter(state, chapter_num):
    """Storyteller assembles scenes into a coherent chapter with transitions."""
    result = delegate_task(
        goal=f"Assemble scenes for Chapter {chapter_num} into a coherent chapter with transitions",
        context=f"""
You are the Storyteller. The scenes for chapter {chapter_num} are complete.
Assemble them into a coherent chapter.

Read each scene's final prose from the scenes/ directory (ch{chapter_num:02d}_s*_final.md).

Your job:
1. Review all scenes in order
2. Write transitions BETWEEN scenes (scene breaks, time jumps, connecting narration)
3. Ensure pacing flows across the whole chapter
4. Do NOT rewrite scene content — only add connective tissue

Output the complete chapter with scene transitions.
Save to: novel_project/output/chapter_{chapter_num:02d}.md
Also update the chapter_transition_prose field in state.
""",
        toolsets=['terminal', 'file']
    )
    
    return result

def orchestrator_review_chapter(state, chapter_num):
    """Orchestrator reviews completed chapter for cross-scene continuity."""
    result = delegate_task(
        goal=f"Review Chapter {chapter_num} for cross-scene continuity and pacing",
        context=f"""
You are the Orchestrator. Review the completed Chapter {chapter_num} for problems.

Read all scene finals from: novel_project/scenes/ (ch{chapter_num:02d}_s*_final.md)
Read the chapter plan from: novel_project/novel_state.yaml

Check for:
1. Cross-scene continuity: Does scene 2 logically follow scene 1? Are locations, times, and character positions consistent?
2. Pacing: Does the chapter flow well? Are there slow spots? Rushed sections?
3. Character consistency across scenes: Do characters act consistently?
4. Unresolved threads: Are there plot threads raised and never resolved within the chapter?

If issues are found, specify WHICH SCENE has the problem and WHAT needs to change.
If the chapter is solid, respond: CHAPTER_REVIEW_PASS
""",
        toolsets=['terminal', 'file']
    )
    
    return result

# ============================================================
# MAIN GENERATION LOOP
# ============================================================

def run_full_loop(seed, author, publisher=None, year=None, location=None, copyright_text=None, max_chapters=None, target="short_novel"):
    """Run the complete novel generation loop.
    
    Args:
        seed: Novel concept/premise
        author: Author name (mandatory)
        publisher: Publisher name (optional)
        year: Publication year (optional)
        location: Publication location (optional)
        copyright_text: Custom copyright notice (optional)
        max_chapters: Max chapters to generate (None = use outline)
        target: Length target - novella(30k), short_novel(60k), novel(80k), epic(100k+)
    """
    # CRITICAL: Check for existing novel before doing ANYTHING
    if not check_existing_novel():
        print("GENERATION ABORTED: Existing novel must be archived first.")
        return
    
    target_words = LENGTH_TARGETS.get(target, 60000)
    print(f"Starting novel generation with seed: {seed}")
    print(f"Author: {author}")
    if publisher:
        print(f"Publisher: {publisher}")
    print(f"Target length: {target} (~{target_words:,} words, ~{target_words // 275} paperback pages)")
    
    update_progress(stage="generating_outline", target=target)
    
    # M0: Generate outline
    result = generate_outline(seed, author, publisher, year, location, copyright_text, target)
    if result is None:
        print("FATAL: Could not generate outline. Aborting.")
        return
    
    # Reload state after outline generation
    state = load_state()
    print(f"Outline generated: {state.get('meta', {}).get('title', 'Untitled')}")
    
    # Outline review
    audit = review_outline(state)
    # TODO: Parse audit result and potentially revise outline
    # For M0, we proceed even if suggestions exist
    
    # Determine chapter count
    chapter_plan = state.get('outline', {}).get('chapter_plan', [])
    total_chapters = len(chapter_plan)
    if max_chapters:
        total_chapters = min(total_chapters, max_chapters)
    
    print(f"\nGenerating {total_chapters} chapters...")
    
    for chapter_num in range(1, total_chapters + 1):
        print(f"\n{'='*60}")
        print(f"CHAPTER {chapter_num}")
        print(f"{'='*60}")
        
        chapter_data = state['chapters'][chapter_num - 1] if chapter_num <= len(state.get('chapters', [])) else None
        scenes = chapter_data.get('scenes', []) if chapter_data else []
        
        for scene_num in range(1, len(scenes) + 1):
            print(f"\n--- Scene {scene_num}/{len(scenes)} ---")
            update_progress(current_chapter=chapter_num, current_scene=scene_num, 
                          stage=f"ch{chapter_num}_s{scene_num}_briefing", target=target)
            
            # Step 1: Generate scene brief
            brief = generate_scene_brief(chapter_num, scene_num, state)
            
            # Step 2: Validate brief
            update_progress(current_chapter=chapter_num, current_scene=scene_num,
                          stage=f"ch{chapter_num}_s{scene_num}_brief_validation", target=target)
            validation = validate_scene_brief(brief, state, chapter_num)
            if validation and 'BRIEF_VALID' not in str(validation):
                print("  Brief had issues, revising...")
                brief = generate_scene_brief(chapter_num, scene_num, state)
                # One more validation
                validation = validate_scene_brief(brief, state, chapter_num)
                if validation and 'BRIEF_VALID' not in str(validation):
                    print("  Brief still has issues. Flagging for Orchestrator.")
                    update_progress(current_chapter=chapter_num, current_scene=scene_num,
                                  stage=f"ch{chapter_num}_s{scene_num}_flagged",
                                  target=target, issues=["Brief validation failed twice"])
                    # Mark scene as flagged and continue
            
            # Step 3: Turn-based character dialogue
            update_progress(current_chapter=chapter_num, current_scene=scene_num,
                          stage=f"ch{chapter_num}_s{scene_num}_character_turns", target=target)
            character_turns = generate_character_turns(chapter_num, scene_num, state)
            
            # Step 4: Storyteller weaves into prose
            update_progress(current_chapter=chapter_num, current_scene=scene_num,
                          stage=f"ch{chapter_num}_s{scene_num}_weaving", target=target)
            draft = weave_scene(chapter_num, scene_num, state, character_turns)
            save_scene_prose(chapter_num, scene_num, draft, stage="draft")
            
            # Step 5: Lore Auditor
            update_progress(current_chapter=chapter_num, current_scene=scene_num,
                          stage=f"ch{chapter_num}_s{scene_num}_auditing", target=target)
            audit_result = audit_scene(chapter_num, scene_num, state)
            
            # Step 6: Targeted revision if needed
            audit_issues_text = None  # Track revised passages for stylist
            revision_count = 0
            while revision_count < 3:
                if 'AUDIT_PASS' in str(audit_result):
                    print("  Audit passed!")
                    break
                
                print(f"  Revision round {revision_count + 1}...")
                update_progress(current_chapter=chapter_num, current_scene=scene_num,
                              stage=f"ch{chapter_num}_s{scene_num}_revision_r{revision_count+1}", target=target)
                revised = targeted_revision(chapter_num, scene_num, state, audit_result)
                save_scene_prose(chapter_num, scene_num, revised, stage="audited")
                
                # Save the audit issues as revised sections for the stylist
                audit_issues_text = str(audit_result)
                
                # Re-audit
                audit_result = audit_scene(chapter_num, scene_num, state)
                revision_count += 1
            
            if revision_count >= 3 and 'AUDIT_PASS' not in str(audit_result):
                print("  Max revisions reached. Saving with ISSUES header.")
                update_progress(current_chapter=chapter_num, current_scene=scene_num,
                              stage=f"ch{chapter_num}_s{scene_num}_flagged",
                              target=target, issues=["Max revisions reached, scene saved with ISSUES"])
                # Mark scene with issues
                if chapter_data:
                    scenes[scene_num-1]['issues_header'] = 'Unresolved audit issues'
                    scenes[scene_num-1]['revision_count'] = revision_count
            
            # Step 7: Prose Stylist
            # If revisions were made, tell the stylist to focus on revised passages only
            update_progress(current_chapter=chapter_num, current_scene=scene_num,
                          stage=f"ch{chapter_num}_s{scene_num}_polishing", target=target)
            polished = polish_scene(chapter_num, scene_num, state, 
                                     revised_sections=[audit_issues_text] if audit_issues_text else None)
            
            # Step 8: State update
            update_progress(current_chapter=chapter_num, current_scene=scene_num,
                          stage=f"ch{chapter_num}_s{scene_num}_state_update", target=target)
            state = load_state()  # Reload after agent writes
            update_state_after_scene(state, chapter_num, scene_num, polished, audit_result)
            state = load_state()  # Reload after update
            
            # Scene complete — update progress with word count
            update_progress(current_chapter=chapter_num, current_scene=scene_num,
                          stage=f"ch{chapter_num}_s{scene_num}_complete", target=target)
        
        # Chapter assembly
        update_progress(current_chapter=chapter_num, stage=f"ch{chapter_num}_assembly", target=target)
        assemble_chapter(state, chapter_num)
        
        # Cross-scene continuity review
        update_progress(current_chapter=chapter_num, stage=f"ch{chapter_num}_review", target=target)
        orchestrator_review_chapter(state, chapter_num)
        
        # State snapshot after each chapter
        state = load_state()
        snapshot_state(state, chapter_num)
        
        print(f"\nChapter {chapter_num} complete!")
    
    # Final progress
    update_progress(stage="complete", target=target)
    final_words = count_total_words()
    
    print(f"\n{'='*60}")
    print(f"NOVEL GENERATION COMPLETE")
    print(f"{'='*60}")
    print(f"Total words: {final_words:,}")
    print(f"Target: {target_words:,}")
    print(f"Paperback pages (~275 words/page): ~{final_words // 275}")
    print(f"Progress file: novel_project/PROGRESS.md")
    print(f"Output chapters: novel_project/output/")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/main.py --seed \"Your concept\" [--max-chapters N] [--target novella|short_novel|novel|epic]")
        print("       python scripts/main.py --clean")
        print("       python scripts/main.py --archive")
        print("\nLength targets:")
        print("  novella      ~30,000 words  (~110 pages)")
        print("  short_novel  ~60,000 words  (~220 pages)  [default]")
        print("  novel        ~80,000 words  (~290 pages)")
        print("  epic         ~100,000 words (~365+ pages)")
        print("\nManagement commands:")
        print("  --clean      Archive current novel, then reset project for a new one")
        print("  --archive    Archive current novel without resetting")
        sys.exit(1)
    
    # Management commands
    if '--clean' in sys.argv:
        from progress import archive_novel, _reset_project
        print("Archiving current novel...")
        archive_path = archive_novel()
        print(f"Novel archived to: {archive_path}")
        print("Project reset. Ready for a new novel seed.")
        sys.exit(0)
    
    if '--archive' in sys.argv:
        from progress import archive_novel
        print("Archiving current novel...")
        archive_path = archive_novel()
        print(f"Novel archived to: {archive_path}")
        print("Original project files remain in place.")
        sys.exit(0)
    
    seed = None
    author = None
    publisher = None
    year = None
    location = None
    copyright_text = None
    max_chapters = None
    target = "short_novel"
    
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == '--seed':
            seed = sys.argv[i+1]
            i += 2
        elif sys.argv[i] == '--author':
            author = sys.argv[i+1]
            i += 2
        elif sys.argv[i] == '--publisher':
            publisher = sys.argv[i+1]
            i += 2
        elif sys.argv[i] == '--year':
            year = sys.argv[i+1]
            i += 2
        elif sys.argv[i] == '--location':
            location = sys.argv[i+1]
            i += 2
        elif sys.argv[i] == '--copyright':
            copyright_text = sys.argv[i+1]
            i += 2
        elif sys.argv[i] == '--max-chapters':
            max_chapters = int(sys.argv[i+1])
            i += 2
        elif sys.argv[i] == '--target':
            target = sys.argv[i+1]
            i += 2
        else:
            i += 1
    
    if not seed:
        print("ERROR: --seed is required")
        print("Usage: python scripts/main.py --seed \"Your novel concept\" --author \"Your Name\" [options...]")
        sys.exit(1)
    
    if not author:
        print("ERROR: --author is required (author name)")
        print("Usage: python scripts/main.py --seed \"Your novel concept\" --author \"Your Name\" [options...]")
        print("Optional: --publisher, --year, --location, --copyright")
        sys.exit(1)
    
    # CRITICAL: Check for existing novel before generation
    if not check_existing_novel():
        print("\nABORTING: Please archive the existing novel first.")
        sys.exit(1)
    
    if target not in LENGTH_TARGETS:
        print(f"ERROR: Unknown target '{target}'. Choose from: {', '.join(LENGTH_TARGETS.keys())}")
        sys.exit(1)
    
    run_full_loop(seed, author, publisher, year, location, copyright_text, max_chapters, target)