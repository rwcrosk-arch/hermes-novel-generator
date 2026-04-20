# Hermes Novel Generator Skill

A multi-agent novel generation system for [Hermes Agent](https://hermes-agent.nousresearch.com). Generate full novels — from seed concept to published EPUB — using a pipeline of specialized AI agents.

## What It Does

- **Orchestrator** → Plans the novel outline, tracks progress, manages state
- **Storyteller/DM** → Writes scene briefs, weaves character strategies into prose
- **Character Agents** → Generate independent scene strategies (what they'd do/say), then review woven prose for authenticity
- **Lore Auditor** → Checks continuity, world rules, knowledge leaks, pacing, themes
- **Prose Stylist** → Polishes prose without changing narrative content

### The Scene Sandbox Model

Characters are active participants, not passive reviewers:

1. Storyteller writes the scene brief
2. **Each character agent plans their strategy in isolation** — they don't see other characters' plans
3. Storyteller receives all strategies and weaves them into prose
4. Character agents do a voice-check pass on the woven draft

This preserves independent agency (characters can surprise the Storyteller) while keeping prose natural.

## Install

```bash
hermes skills install rwcrosk-arch/hermes-novel-generator/creative/novel-generator
```

Or browse the Skills Hub:
```bash
hermes skills search novel-generator
hermes skills install novel-generator
```

## Quick Start

Once installed, tell your Hermes agent:

```
Generate a novel with the seed: "A lone astronaut discovers an ancient machine on Mars"
```

Or with options:
```
Generate a novel — seed: "A lone astronaut discovers an ancient machine on Mars",
genre: scifi, target: short_novel, chapters: 10
```

## Length Targets

| Target | Words | Paperback Pages | Chapters | Scenes/Ch |
|--------|-------|-----------------|----------|-----------|
| novella | 30,000 | ~110 | 5-7 | 2-3 |
| short_novel | 60,000 | ~220 | 8-12 | 3-4 |
| novel | 80,000 | ~290 | 12-15 | 3-5 |
| epic | 100,000+ | ~365+ | 15-20 | 4-6 |

Default: `short_novel` (~60k words, ~220 pages).

## File Structure

```
creative/novel-generator/
  SKILL.md                          → Main skill document (procedural guide)
  prompts/
    orchestrator.md                 → Orchestrator agent prompt
    storyteller.md                  → Storyteller agent prompt
    character_agent.md              → Character agent prompt (strategy + voice-check)
    lore_auditor.md                 → Lore Auditor agent prompt
    prose_stylist.md                → Prose Stylist agent prompt
  scripts/
    dashboard.py                    → Live/static progress dashboard
    progress.py                     → Progress tracking + archive utilities
    publish.py                      → Cover overlay + EPUB assembly
    generate_cover.py               → AI cover generation via diffusers
  references/
    multi_agent_novel_plan.md       → Full architectural specification
```

## How It Works

The skill is a **procedural guide** for the Hermes assistant. The assistant follows the steps in `SKILL.md`, spawning specialized sub-agents via `delegate_task` at each stage:

1. **Outline** → Assistant generates `novel_state.yaml` with full outline, characters, world
2. **Per Chapter** → Delegate to Storyteller for scene briefs
3. **Per Scene** → Delegate to Character Agents for strategies → Delegate to Storyteller for weaving → Delegate to Character Agents for voice-check → Delegate to Lore Auditor → Delegate to Prose Stylist
4. **State Update** → Assistant updates `novel_state.yaml` with versioned validation
5. **Dashboard** → Scripts regenerate progress tracking

**Note:** `delegate_task` is an assistant-native tool. It cannot be imported in Python scripts. The assistant orchestrates the pipeline manually using the skill as a guide.

## Prerequisites

The supporting scripts need:
```bash
pip install pyyaml ebooklib Pillow
# Optional (for cover generation):
pip install diffusers accelerate torch
```

## Publishing Pipeline

After the novel is complete:
```bash
cd novel_project
python3 scripts/generate_cover.py --seed 42    # AI cover
python3 scripts/publish.py --all               # Title overlay + EPUB
```

Output: `output/Your_Novel_Title.epub` with embedded cover and styled chapters.

## License

MIT — see [LICENSE](LICENSE).

## Links

- [Hermes Agent](https://hermes-agent.nousresearch.com)
- [Agent Skills Specification](https://agentskills.io/specification)
- [Nous Research](https://nousresearch.com)
