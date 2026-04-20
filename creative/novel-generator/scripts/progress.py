#!/usr/bin/env python3
"""Progress tracker for the multi-agent novel generator.
Updates PROGRESS.md after every scene completion.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

PROJECT_ROOT = Path(__file__).parent.parent

# Length targets in words
LENGTH_TARGETS = {
    "novella": 30000,
    "short_novel": 60000,
    "novel": 80000,
    "epic": 100000,
}

def count_words_in_file(filepath):
    """Count words in a markdown file."""
    if not os.path.exists(filepath):
        return 0
    with open(filepath, 'r', encoding='utf-8') as f:
        return len(f.read().split())

def count_total_words():
    """Count total words from assembled chapter files only.
    
    We count chapters/ (the final assembled prose), NOT scenes/ (intermediate drafts).
    Counting both would double-count since scenes are assembled into chapters.
    """
    total = 0
    import re
    chapters_dir = PROJECT_ROOT / "chapters"
    if chapters_dir.exists():
        # Prefer _polished over plain chapter file, count each chapter only once
        counted = set()
        for f in sorted(chapters_dir.iterdir(), reverse=True):
            if f.suffix == '.md':
                match = re.search(r'ch(?:apter)?_?(\d+)', f.name)
                ch_key = match.group(1) if match else f.name
                if ch_key not in counted:
                    total += count_words_in_file(str(f))
                    counted.add(ch_key)
    return total

def get_progress_bar(pct, width=20):
    """Generate a text progress bar."""
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {pct*100:.0f}%"

def load_chapter_status():
    """Load chapter/scene status from novel_state.yaml."""
    state_file = PROJECT_ROOT / "novel_state.yaml"
    if not state_file.exists() or yaml is None:
        return [], 0, 0
    
    with open(state_file, 'r', encoding='utf-8') as f:
        state = yaml.safe_load(f) or {}
    
    chapters = state.get('chapters', [])
    total_chapters = len(state.get('outline', {}).get('chapter_plan', []))
    return chapters, total_chapters, state

def update_progress(current_chapter=0, current_scene=0, stage="idle", 
                    target="short_novel", message="", issues=None):
    """Update the PROGRESS.md file with current status."""
    target_words = LENGTH_TARGETS.get(target, 60000)
    current_words = count_total_words()
    chapters, total_chapters, state = load_chapter_status()
    
    # Calculate scene completion
    total_scenes = 0
    completed_scenes = 0
    scene_statuses = []
    
    for ch in chapters:
        scenes = ch.get('scenes', [])
        total_scenes += len(scenes)
        for sc in scenes:
            status = sc.get('status', 'unknown')
            scene_statuses.append(f"  Ch{ch.get('number', '?')} Sc{sc.get('number', '?')}: {status}")
            if status == 'complete':
                completed_scenes += 1
    
    word_pct = min(current_words / target_words, 1.0) if target_words > 0 else 0
    scene_pct = completed_scenes / total_scenes if total_scenes > 0 else 0
    
    # Build progress report
    progress = f"""# Novel Generation Progress

> Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

## Overview

| Metric | Value |
|--------|-------|
| **Current Stage** | {stage} |
| **Chapter** | {current_chapter} / {total_chapters} |
| **Total Scenes** | {total_scenes} |
| **Completed Scenes** | {completed_scenes} |
| **Word Count** | {current_words:,} / {target_words:,} |
| **Target Length** | {target} |

## Word Count Progress

{get_progress_bar(word_pct)}  ({current_words:,} / {target_words:,} words)

## Scene Completion

{get_progress_bar(scene_pct)}  ({completed_scenes} / {total_scenes} scenes)

## Scene Status

"""
    
    if scene_statuses:
        progress += "\n".join(scene_statuses)
    else:
        progress += "No scenes generated yet."

    # Issues section
    if issues:
        progress += f"\n\n## Flagged Issues\n\n"
        for issue in issues:
            progress += f"- {issue}\n"
    
    # Title and genre from state
    if state:
        title = state.get('meta', {}).get('title', 'Untitled')
        genre = state.get('meta', {}).get('genre', 'Unknown')
        progress = progress.replace("# Novel Generation Progress", 
                                    f"# Novel Generation Progress: {title}")
    
    # Write progress file
    progress_file = PROJECT_ROOT / "PROGRESS.md"
    with open(progress_file, 'w', encoding='utf-8') as f:
        f.write(progress)
    
    return progress

def archive_novel():
    """Archive the current novel project and reset for a new one."""
    import shutil
    
    state_file = PROJECT_ROOT / "novel_state.yaml"
    
    # Get title for archive name
    title = "untitled"
    if state_file.exists() and yaml:
        with open(state_file, 'r', encoding='utf-8') as f:
            state = yaml.safe_load(f) or {}
        title = state.get('meta', {}).get('title', 'untitled').lower().replace(' ', '_')
    
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    archive_name = f"{title}_{timestamp}"
    
    # Create archive directory
    archive_base = PROJECT_ROOT.parent / "novel_archive"
    archive_base.mkdir(exist_ok=True)
    archive_path = archive_base / archive_name
    
    # Copy current project to archive, excluding large/unchanged dirs
    ignore = shutil.ignore_patterns(
        'tools',          # ComfyUI + models (6.5+ GB, unchanged between novels)
        '.backups',       # Internal snapshots (not needed in archive)
        '__pycache__',    # Python cache
        'node_modules',   # ComfyUI deps
        '.git',           # Git data
    )
    shutil.copytree(PROJECT_ROOT, archive_path, ignore=ignore)
    
    # Clean out archive's snapshot locks and progress (keep the data)
    # No need — archive preserves everything
    
    # Reset current project for new novel
    _reset_project()
    
    return str(archive_path)

def _reset_project():
    """Reset novel_project/ to a fresh state, keeping prompts and scripts.
    
    Removes all generated content (scenes, chapters, output, publish assets,
    snapshots, dashboard, progress), but preserves scripts/, prompts/, and tools/.
    """
    import shutil
    
    # Generated content directories — remove entirely
    dirs_to_remove = ["scenes", "chapters", ".snapshots", "output"]
    for d in dirs_to_remove:
        dir_path = PROJECT_ROOT / d
        if dir_path.exists():
            shutil.rmtree(dir_path)
    
    # Publish directory — remove generated images, keep fonts
    publish_dir = PROJECT_ROOT / "publish"
    if publish_dir.exists():
        for f in list(publish_dir.iterdir()):
            if f.is_file() and not f.suffix == '.ttf':
                f.unlink()  # Remove cover_*.png, cover_*.jpg, etc.
    
    # Generated single files
    generated_files = ["PROGRESS.md", "dashboard.html"]
    for fname in generated_files:
        fpath = PROJECT_ROOT / fname
        if fpath.exists():
            fpath.unlink()
    
    # Recreate empty directories so scripts don't error
    for d in dirs_to_remove:
        (PROJECT_ROOT / d).mkdir(exist_ok=True)
    
    # Reset state file
    _write_fresh_state()
    
    # Reset progress
    update_progress(stage="waiting_for_seed", message="Ready for a new novel seed")

def _write_fresh_state():
    """Write a fresh novel_state.yaml template."""
    state_file = PROJECT_ROOT / "novel_state.yaml"
    
    template = """# === novel_state.yaml ===
# THE single source of truth for the entire novel
# Populated by the Orchestrator from the user's seed

meta:
  title: ""
  genre: ""
  seed: ""
  created: ""
  last_modified: ""
  current_chapter: 1
  current_scene: 1

outline:
  premise: ""
  themes: []
  narrative_arc: ""
  chapter_plan: []

world:
  rules: ""
  locations: []
  history: ""
  timeline: []

characters: []

summaries:
  chapter_summaries: []
  character_arcs_so_far: {}

chapters: []

audit_log: []

orchestrator_audits: []
"""
    
    with open(state_file, 'w', encoding='utf-8') as f:
        f.write(template)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == "archive":
            path = archive_novel()
            print(f"Novel archived to: {path}")
            print("Project reset. Ready for a new novel seed.")
        elif sys.argv[1] == "status":
            print(update_progress())
    else:
        print("Usage: python progress.py [archive|status]")