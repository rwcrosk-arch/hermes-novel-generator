#!/usr/bin/env python3
"""Novel Generation Dashboard Server.
Serves a live web dashboard showing progress, scene status, word counts, and characters.
Auto-refreshes every 10 seconds.

Usage:
  python scripts/dashboard.py           # Serve on http://localhost:8420
  python scripts/dashboard.py --port 9999  # Custom port
  python scripts/dashboard.py --static    # Generate static HTML file only (no server)
"""

import json
import os
import sys
import time
import math
import re
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from datetime import datetime

try:
    import yaml
except ImportError:
    yaml = None

PROJECT_ROOT = Path(__file__).parent.parent

LENGTH_TARGETS = {
    "novella": {"words": 30000, "pages": 110, "chapters": "5-7", "label": "Novella"},
    "short_novel": {"words": 60000, "pages": 220, "chapters": "8-12", "label": "Short Novel"},
    "novel": {"words": 80000, "pages": 290, "chapters": "12-15", "label": "Novel"},
    "epic": {"words": 100000, "pages": 365, "chapters": "15-20", "label": "Epic"},
}

def load_state():
    state_file = PROJECT_ROOT / "novel_state.yaml"
    if not state_file.exists() or yaml is None:
        return {}
    with open(state_file, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}

def count_scene_words(chapter_num, scene_num, stage="final"):
    # Try specific scene file first (chXX_sYY_stage.md)
    filepath = PROJECT_ROOT / "scenes" / f"ch{chapter_num:02d}_s{scene_num:02d}_{stage}.md"
    if filepath.exists():
        with open(filepath, 'r', encoding='utf-8') as f:
            return len(f.read().split())
    # Fallback: single-chapter file format (chXX_stage.md, e.g. Ch.1 has ch01_draft.md)
    filepath = PROJECT_ROOT / "scenes" / f"ch{chapter_num:02d}_{stage}.md"
    if filepath.exists():
        with open(filepath, 'r', encoding='utf-8') as f:
            return len(f.read().split())
    return 0

def count_total_words():
    """Count total words from the assembled chapter files only.

    We count chapters/ (the final assembled prose), NOT scenes/ (intermediate drafts).
    Counting both would double-count since scenes are assembled into chapters.
    """
    import re
    total = 0
    chapters_dir = PROJECT_ROOT / "chapters"
    if chapters_dir.exists():
        # Prefer _polished over plain chapter file, but count each chapter only once
        counted = set()
        for f in sorted(chapters_dir.iterdir(), reverse=True):  # polished first
            if f.suffix == '.md':
                match = re.search(r'ch(?:apter)?_?(\d+)', f.name)
                ch_key = match.group(1) if match else f.name
                if ch_key not in counted:
                    with open(f, 'r', encoding='utf-8') as fh:
                        total += len(fh.read().split())
                    counted.add(ch_key)
    return total

def get_progress_data():
    state = load_state()
    total_words = count_total_words()
    
    # Determine target
    meta = state.get("meta", {})
    target_key = "short_novel"  # default
    target_info = LENGTH_TARGETS[target_key]
    target_words = target_info["words"]
    
    # Compute scene stats from written chapters
    chapters_data = []
    total_scenes = 0
    completed_scenes = 0
    total_draft_words = 0
    flagged_issues = []
    
    for ch in state.get("chapters", []):
        ch_num = ch.get("number", 0)
        ch_title = ch.get("title", "?")
        ch_status = ch.get("status", "planned")
        scenes = ch.get("scenes", [])
        scenes_data = []
        
        for sc in scenes:
            sc_num = sc.get("number", 0)
            sc_status = sc.get("status", "planned")
            sc_brief = sc.get("brief", {})
            sc_conflict = sc_brief.get("conflict", "") if isinstance(sc_brief, dict) else ""
            sc_chars = sc_brief.get("characters_present", []) if isinstance(sc_brief, dict) else sc.get("characters_present", [])
            sc_words = count_scene_words(ch_num, sc_num, "final") or count_scene_words(ch_num, sc_num, "draft")
            
            total_scenes += 1
            if sc_status == "complete":
                completed_scenes += 1
            
            if sc.get("issues_header"):
                flagged_issues.append(f"Ch{ch_num} Sc{sc_num}: {sc['issues_header']}")
            
            draft_words = count_scene_words(ch_num, sc_num, "draft")
            final_words = count_scene_words(ch_num, sc_num, "final")
            # Fallback to word_count from state if files don't exist
            if draft_words == 0 and final_words == 0:
                final_words = sc.get("word_count", 0)
            total_draft_words += draft_words + final_words
            
            # Build file URL for scene draft
            # Try specific scene file first, then single-chapter file
            scene_file_specific = f"scenes/ch{ch_num:02d}_s{sc_num:02d}_draft.md"
            scene_file_chapter = f"scenes/ch{ch_num:02d}_draft.md"
            scene_file_exists = (PROJECT_ROOT / scene_file_specific).exists()
            scene_file_url = f"/files/{scene_file_specific}" if scene_file_exists else None
            if not scene_file_url and (PROJECT_ROOT / scene_file_chapter).exists():
                scene_file_url = f"/files/{scene_file_chapter}"
            
            scenes_data.append({
                "number": sc_num,
                "status": sc_status,
                "conflict": sc_conflict[:60] + "..." if len(sc_conflict) > 60 else sc_conflict,
                "characters": sc_chars,
                "words_draft": draft_words,
                "words_final": final_words,
                "revision_count": sc.get("revision_count", 0),
                "audit_result": sc.get("audit_result", ""),
                "issues": sc.get("issues_header", ""),
                "file_url": scene_file_url,
            })
        
        # Build file URL for chapter assembled file
        chapter_file = f"chapters/chapter_{ch_num:02d}.md"
        chapter_file_exists = (PROJECT_ROOT / chapter_file).exists()
        
        chapters_data.append({
            "number": ch_num,
            "title": ch_title,
            "status": ch_status,
            "scenes": scenes_data,
            "file_url": f"/files/{chapter_file}" if chapter_file_exists else None,
        })
    
    # If no written chapters yet, show planned chapters from outline
    if not chapters_data:
        for ch_plan in state.get("outline", {}).get("chapter_plan", []):
            scenes_data = []
            for sc in ch_plan.get("scene_list", []):
                scenes_data.append({
                    "number": sc.get("number", 0),
                    "status": "planned",
                    "conflict": sc.get("summary", "")[:60] + "..." if len(sc.get("summary", "")) > 60 else sc.get("summary", ""),
                    "characters": sc.get("characters_present", []),
                    "words_draft": 0,
                    "words_final": 0,
                    "revision_count": 0,
                    "audit_result": "",
                    "issues": "",
                })
                total_scenes += 1
            chapters_data.append({
                "number": ch_plan.get("number", 0),
                "title": ch_plan.get("title", "?"),
                "status": "planned",
                "scenes": scenes_data,
            })
    
    # Character info
    characters_data = []
    for char in state.get("characters", []):
        characters_data.append({
            "id": char.get("id", ""),
            "name": char.get("name", ""),
            "role": char.get("role", ""),
            "arc": char.get("growth", {}).get("arc", ""),
            "current_state": char.get("growth", {}).get("current_state", ""),
        })
    
    # Audit log summary
    audit_summary = {"total": 0, "critical": 0, "important": 0, "minor": 0, "resolved": 0}
    for entry in state.get("audit_log", []):
        for issue in entry.get("issues_found", []):
            audit_summary["total"] += 1
            sev = issue.get("severity", "minor")
            if sev in audit_summary:
                audit_summary[sev] += 1
            if issue.get("resolved", False):
                audit_summary["resolved"] += 1
    
    # Word count
    actual_words = count_total_words()
    word_pct = min(actual_words / target_words, 1.0) if target_words > 0 else 0
    scene_pct = completed_scenes / total_scenes if total_scenes > 0 else 0
    
    # Completion check: novel is complete if all chapters are marked complete
    all_chapters_complete = (
        len(state.get("chapters", [])) > 0 and
        all(ch.get("status") == "complete" for ch in state.get("chapters", [])) and
        meta.get("status") == "complete"
    )
    
    # Published assets (EPUB, cover)
    published = {}
    # Derive EPUB filename from title
    safe_title = re.sub(r'[^\w\s-]', '', meta.get("title", "Novel")).strip().replace(' ', '_')
    epub_path = PROJECT_ROOT / "output" / f"{safe_title}.epub"
    cover_jpg = PROJECT_ROOT / "publish" / "cover_final.jpg"
    cover_png = PROJECT_ROOT / "publish" / "cover_final.png"
    cover_raw = PROJECT_ROOT / "publish" / "cover_raw.png"
    if epub_path.exists():
        published["epub_url"] = "/download/epub"
        published["epub_size"] = epub_path.stat().st_size
    if cover_jpg.exists():
        published["cover_url"] = "/files/publish/cover_final.jpg"
    elif cover_png.exists():
        published["cover_url"] = "/files/publish/cover_final.png"
    elif cover_raw.exists():
        published["cover_url"] = f"/files/publish/cover_raw.png"
    
    # Last modified
    last_modified = meta.get("last_modified", "Not started")
    
    return {
        "meta": {
            "title": meta.get("title", "Untitled"),
            "genre": meta.get("genre", ""),
            "seed": meta.get("seed", ""),
            "last_modified": last_modified,
            "novel_status": "complete" if all_chapters_complete else "in_progress",
        },
        "published": published,
        "target": {
            "key": target_key,
            "label": target_info["label"],
            "words": target_words,
            "pages": target_info["pages"],
        },
        "progress": {
            "word_count": actual_words,
            "word_target": target_words,
            "word_pct": round(word_pct * 100, 1),
            "current_pages": actual_words // 275,
            "target_pages": target_info["pages"],
            "total_chapters": len([ch for ch in state.get("chapters", [])]),
            "completed_chapters": len([ch for ch in state.get("chapters", []) if ch.get("status") == "complete"]),
            "total_scenes": total_scenes,
            "completed_scenes": completed_scenes,
            "scene_pct": round(scene_pct * 100, 1),
        },
        "chapters": chapters_data,
        "characters": characters_data,
        "audit_summary": audit_summary,
        "flagged_issues": flagged_issues,
        "timestamp": datetime.now().isoformat(),
    }

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Novel Dashboard</title>
<style>
  :root {
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #e6edf3; --text-dim: #8b949e; --accent: #58a6ff;
    --green: #3fb950; --yellow: #d29922; --red: #f85149;
    --purple: #bc8cff; --orange: #f0883e;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', monospace;
         background: var(--bg); color: var(--text); padding: 20px; max-width: 1200px; margin: 0 auto; }
  h1 { font-size: 1.5em; margin-bottom: 4px; }
  h2 { font-size: 1.1em; color: var(--accent); margin: 20px 0 10px; font-weight: 600; }
  .subtitle { color: var(--text-dim); font-size: 0.85em; margin-bottom: 20px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-bottom: 20px; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
  .card-title { font-size: 0.75em; text-transform: uppercase; color: var(--text-dim); letter-spacing: 1px; margin-bottom: 8px; }
  .big-number { font-size: 2em; font-weight: 700; line-height: 1; }
  .stat-label { font-size: 0.85em; color: var(--text-dim); margin-top: 2px; }
  .progress-bar { width: 100%; height: 8px; background: var(--border); border-radius: 4px; overflow: hidden; margin: 8px 0; }
  .progress-fill { height: 100%; border-radius: 4px; transition: width 0.5s ease; }
  .progress-fill.green { background: var(--green); }
  .progress-fill.blue { background: var(--accent); }
  .progress-fill.yellow { background: var(--yellow); }
  .progress-fill.red { background: var(--red); }
  .chapter-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 16px; overflow: hidden; }
  .chapter-header { padding: 12px 16px; background: rgba(88,166,255,0.1); border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
  .chapter-title { font-weight: 600; }
  .scene-list { padding: 0; }
  .scene-row { display: flex; align-items: center; padding: 8px 16px; border-bottom: 1px solid var(--border); font-size: 0.85em; }
  .scene-row:last-child { border-bottom: none; }
  .status-dot { width: 10px; height: 10px; border-radius: 50%; margin-right: 10px; flex-shrink: 0; }
  .status-dot.complete { background: var(--green); }
  .status-dot.drafting, .status-dot.weaving, .status-dot.polishing { background: var(--yellow); }
  .status-dot.auditing, .status-dot.revision { background: var(--orange); }
  .status-dot.flagged { background: var(--red); }
  .status-dot.planned, .status-dot.briefing { background: var(--text-dim); }
  .scene-info { flex: 1; }
  .scene-conflict { color: var(--text-dim); font-size: 0.8em; }
  .scene-words { color: var(--text-dim); width: 60px; text-align: right; }
  .char-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 8px; }
  .char-card { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 10px; }
  .char-name { font-weight: 600; }
  .char-role { font-size: 0.75em; color: var(--text-dim); text-transform: uppercase; }
  .char-state { font-size: 0.8em; color: var(--text-dim); margin-top: 4px; }
  .role-protagonist { color: var(--green); }
  .role-antagonist { color: var(--red); }
  .role-supporting { color: var(--accent); }
  .role-minor { color: var(--text-dim); }
  .issue-card { background: rgba(248,81,73,0.1); border: 1px solid var(--red); border-radius: 6px; padding: 8px 12px; margin-bottom: 8px; font-size: 0.85em; }
  .audit-bar { display: flex; gap: 8px; align-items: center; }
  .audit-seg { height: 8px; border-radius: 2px; }
  .footer { text-align: center; color: var(--text-dim); font-size: 0.75em; margin-top: 30px; padding-top: 20px; border-top: 1px solid var(--border); }
  .pulse { animation: pulse 2s ease-in-out infinite; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
  .na { color: var(--text-dim); opacity: 0.5; }
  .download-btn { display: inline-block; background: var(--accent); color: var(--bg); padding: 10px 24px;
    border-radius: 6px; text-decoration: none; font-weight: 700; font-size: 1em; margin-top: 8px;
    transition: background 0.2s; }
  .download-btn:hover { background: #79c0ff; }
  .cover-thumb { max-width: 200px; border-radius: 6px; border: 1px solid var(--border); }
</style>
</head>
<body>
<h1><span id="title">Novel Dashboard</span></h1>
<div class="subtitle" id="subtitle">Loading...</div>

<div class="grid" id="stats">
  <div class="card">
    <div class="card-title">Words</div>
    <div class="big-number" id="word-count">0</div>
    <div class="stat-label" id="word-label">of 60,000 target</div>
    <div class="progress-bar"><div class="progress-fill blue" id="word-bar" style="width: 0%"></div></div>
  </div>
  <div class="card">
    <div class="card-title">Chapters</div>
    <div class="big-number" id="chapter-count">0<span class="na"> / 0</span></div>
    <div class="stat-label" id="chapter-label">0% complete</div>
    <div class="progress-bar"><div class="progress-fill purple" id="chapter-bar" style="width: 0%"></div></div>
  </div>
  <div class="card">
    <div class="card-title">Paperback Pages</div>
    <div class="big-number" id="page-count">0</div>
    <div class="stat-label" id="page-label">of ~220 target</div>
  </div>
  <div class="card">
    <div class="card-title">Scenes Complete</div>
    <div class="big-number" id="scene-count">0<span class="na"> / 0</span></div>
    <div class="stat-label" id="scene-label">0% complete</div>
    <div class="progress-bar"><div class="progress-fill green" id="scene-bar" style="width: 0%"></div></div>
  </div>
  <div class="card">
    <div class="card-title">Audit Issues</div>
    <div class="big-number" id="audit-total">0</div>
    <div class="stat-label" id="audit-label">0 resolved</div>
    <div class="audit-bar" id="audit-bar"></div>
  </div>
</div>

<div id="published-section" style="display:none;">
  <h2>📖 Published</h2>
  <div class="grid" id="published-grid"></div>
</div>

<h2>Chapters & Scenes</h2>
<div id="chapters">
  <div class="card" style="text-align: center; color: var(--text-dim); padding: 40px;">
    No chapters generated yet. Start the pipeline to see progress here.
  </div>
</div>

<h2>Characters</h2>
<div class="char-grid" id="characters">
  <div class="card" style="text-align: center; color: var(--text-dim); padding: 20px; grid-column: 1 / -1;">
    No characters defined yet.
  </div>
</div>

<div id="issues-section" style="display:none;">
  <h2>⚠️ Flagged Issues</h2>
  <div id="issues"></div>
</div>

<div class="footer">
  <span id="timestamp"></span> · Auto-refreshes every 10s
</div>

<script>
const STATUS_LABELS = {
  planned: 'Planned', briefing: 'Briefing', brief_validation: 'Validating',
  character_turns: 'Characters Acting', weaving: 'Weaving Prose',
  auditing: 'Auditing', revision: 'Revising', polishing: 'Polishing',
  complete: 'Complete ✓', flagged: 'Flagged ⚠'
};

function render(data) {
  const p = data.progress;
  const isComplete = data.meta.novel_status === 'complete';
  
  // Title and subtitle
  if (isComplete) {
    document.getElementById('title').textContent = (data.meta.title || 'Novel Dashboard') + ' ✨ COMPLETE ✨';
    document.getElementById('subtitle').textContent =
      data.meta.genre + ' · ' + p.word_count.toLocaleString() + ' words · ' + p.current_pages + ' pages · ' + p.completed_chapters + '/' + p.total_chapters + ' chapters · ALL ' + data.chapters.length + ' CHAPTERS DONE';
  } else {
    document.getElementById('title').textContent = (data.meta.title || 'Novel Dashboard');
    document.getElementById('subtitle').textContent =
      data.meta.genre + (data.meta.seed ? ' — ' + data.meta.seed.substring(0, 80) : '');
    if (data.meta.genre === '' && data.meta.seed === '') document.getElementById('subtitle').textContent = 'Waiting for novel seed...';
  }
  // Progress bars — green and full when complete
  const wordBarPct = isComplete ? 100 : p.word_pct;
  const sceneBarPct = isComplete ? 100 : p.scene_pct;
  const wordBarClass = isComplete ? 'progress-fill green' : 'progress-fill blue';
  const sceneBarClass = isComplete ? 'progress-fill green' : 'progress-fill green';
  document.getElementById('word-count').textContent = p.word_count.toLocaleString();
  document.getElementById('word-label').textContent = isComplete ? '🎉 Target achieved!' : 'of ' + p.word_target.toLocaleString() + ' target (' + data.target.label + ')';
  document.getElementById('word-bar').style.width = wordBarPct + '%';
  document.getElementById('word-bar').className = wordBarClass;
document.getElementById('page-count').textContent = p.current_pages;
  document.getElementById('page-label').textContent = isComplete ? p.current_pages + ' pages ✨' : 'of ~' + data.target.pages + ' target';
  const chapterPct = p.total_chapters > 0 ? Math.round(p.completed_chapters / p.total_chapters * 100) : 0;
  const chapterBarPct = isComplete ? 100 : chapterPct;
  const chapterBarClass = isComplete ? 'progress-fill green' : 'progress-fill purple';
  document.getElementById('chapter-count').innerHTML = p.completed_chapters + ' <span class="na">/ ' + p.total_chapters + '</span>';
  document.getElementById('chapter-label').textContent = isComplete ? '🎉 ' + chapterPct + '% — ALL DONE!' : chapterPct + '% complete';
  document.getElementById('chapter-bar').style.width = chapterBarPct + '%';
  document.getElementById('chapter-bar').className = chapterBarClass;
  document.getElementById('scene-count').innerHTML = p.completed_scenes + ' <span class="na">/ ' + p.total_scenes + '</span>';
  document.getElementById('scene-label').textContent = isComplete ? '🎉 ' + p.scene_pct + '% — ALL DONE!' : p.scene_pct + '% complete';
  document.getElementById('scene-bar').style.width = sceneBarPct + '%';
  document.getElementById('scene-bar').className = sceneBarClass;

  const a = data.audit_summary;
  document.getElementById('audit-total').textContent = a.total;
  document.getElementById('audit-label').textContent = a.resolved + ' resolved';
  const barHtml = (a.critical ? '<div class="audit-seg" style="width:' + (a.critical/a.total*100) + '%;background:var(--red)"></div>' : '') +
                  (a.important ? '<div class="audit-seg" style="width:' + (a.important/a.total*100) + '%;background:var(--orange)"></div>' : '') +
                  (a.minor ? '<div class="audit-seg" style="width:' + (a.minor/a.total*100) + '%;background:var(--yellow)"></div>' : '');
  document.getElementById('audit-bar').innerHTML = barHtml;

  // Chapters
  let chHtml = '';
  if (data.chapters.length === 0) {
    chHtml = '<div class="card" style="text-align:center;color:var(--text-dim);padding:40px;">No chapters generated yet.</div>';
  } else {
    for (const ch of data.chapters) {
      const sceneRows = ch.scenes.map(s => {
        const words = s.words_final || s.words_draft || 0;
        const statusClass = s.status === 'complete' ? 'complete' :
                           ['drafting','weaving','polishing'].includes(s.status) ? 'drafting' :
                           ['auditing','revision','brief_validation'].includes(s.status) ? 'auditing' :
                           s.status === 'flagged' ? 'flagged' : 'planned';
        const sceneLabel = s.file_url
          ? `<a href="${s.file_url}" target="_blank" style="color:var(--accent);text-decoration:none;">Sc ${s.number}</a>`
          : `Sc ${s.number}`;
        return `<div class="scene-row">
          <div class="status-dot ${statusClass}"></div>
          <div class="scene-info">${sceneLabel}: <strong>${STATUS_LABELS[s.status] || s.status}</strong>
            ${s.conflict ? '<br><span class="scene-conflict">' + s.conflict + '</span>' : ''}
            ${s.issues ? '<br><span style="color:var(--red)">⚠ ' + s.issues + '</span>' : ''}
          </div>
          <div class="scene-words">${words > 0 ? words.toLocaleString() + 'w' : '—'}</div>
        </div>`;
      }).join('');

      const completed = ch.scenes.filter(s => s.status === 'complete').length;
      const pct = ch.scenes.length > 0 ? Math.round(completed / ch.scenes.length * 100) : 0;
      const chTitle = ch.file_url
        ? `<a href="${ch.file_url}" target="_blank" style="color:var(--text);text-decoration:none;">Ch ${ch.number}: ${ch.title || 'Untitled'}</a>`
        : `Ch ${ch.number}: ${ch.title || 'Untitled'}`;

      chHtml += `<div class="chapter-card">
        <div class="chapter-header">
          <div><span class="chapter-title">${chTitle}</span></div>
          <div style="font-size:0.85em;color:var(--text-dim)">${completed}/${ch.scenes.length} scenes · ${pct}%</div>
        </div>
        <div style="padding:0 0 0 0;">
          <div class="progress-bar" style="margin:0;border-radius:0;height:4px;">
            <div class="progress-fill green" style="width:${pct}%;border-radius:0;height:100%"></div>
          </div>
        </div>
        <div class="scene-list">${sceneRows}</div>
      </div>`;
    }
  }
  document.getElementById('chapters').innerHTML = chHtml;

  // Characters
  let charHtml = '';
  if (data.characters.length === 0) {
    charHtml = '<div class="card" style="text-align:center;color:var(--text-dim);padding:20px;grid-column:1/-1;">No characters defined yet.</div>';
  } else {
    for (const c of data.characters) {
      const roleClass = 'role-' + (c.role || 'minor');
      charHtml += `<div class="char-card">
        <div class="char-name ${roleClass}">${c.name}</div>
        <div class="char-role">${c.role || 'unknown'}</div>
        ${c.current_state ? '<div class="char-state">' + c.current_state.substring(0, 80) + '</div>' : ''}
      </div>`;
    }
  }
  document.getElementById('characters').innerHTML = charHtml;

  // Issues
  if (data.flagged_issues.length > 0) {
    document.getElementById('issues-section').style.display = 'block';
    document.getElementById('issues').innerHTML = data.flagged_issues.map(i =>
      `<div class="issue-card">${i}</div>`).join('');
  } else {
    document.getElementById('issues-section').style.display = 'none';
  }

  // Published section (EPUB download + cover)
  const pub = data.published || {};
  const pubSection = document.getElementById('published-section');
  const pubGrid = document.getElementById('published-grid');
  if (pub.epub_url || pub.cover_url) {
    pubSection.style.display = 'block';
    let pubHtml = '';
    if (pub.cover_url) {
      pubHtml += '<div class="card" style="text-align:center;">' +
        '<div class="card-title">Cover</div>' +
        '<img src="' + pub.cover_url + '" class="cover-thumb" alt="Novel Cover">' +
        '</div>';
    }
    if (pub.epub_url) {
      const sizeMB = (pub.epub_size / 1024 / 1024).toFixed(1);
      pubHtml += '<div class="card" style="text-align:center;">' +
        '<div class="card-title">EPUB</div>' +
        '<div class="big-number" style="font-size:1.5em;">📚</div>' +
        '<div class="stat-label">' + sizeMB + ' MB</div>' +
        '<a href="' + pub.epub_url + '" class="download-btn">Download EPUB</a>' +
        '</div>';
    }
    if (!pub.epub_url && !pub.cover_url) {
      pubSection.style.display = 'none';
    } else {
      pubGrid.innerHTML = pubHtml;
    }
  } else {
    pubSection.style.display = 'none';
  }

  document.getElementById('timestamp').textContent = 'Last updated: ' + new Date(data.timestamp).toLocaleString();
}

async function refresh() {
  try {
    const r = await fetch('/api/status');
    const data = await r.json();
    render(data);
  } catch(e) {
    console.error('Refresh failed:', e);
  }
}

refresh();
setInterval(refresh, 10000);
</script>
</body>
</html>"""


class DashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path == '/dashboard':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode('utf-8'))
        elif self.path == '/api/status':
            data = get_progress_data()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(data, indent=2).encode('utf-8'))
        elif self.path.startswith('/files/'):
            # Serve scene/chapter/publish files from the project directory
            rel_path = self.path[len('/files/'):]
            file_path = PROJECT_ROOT / rel_path
            if file_path.exists() and file_path.is_file():
                # Security: ensure path stays within project
                try:
                    file_path.resolve().relative_to(PROJECT_ROOT.resolve())
                except ValueError:
                    self.send_response(403)
                    self.end_headers()
                    self.wfile.write(b'Access denied')
                    return
                self.send_response(200)
                if file_path.suffix == '.md':
                    self.send_header('Content-Type', 'text/markdown; charset=utf-8')
                elif file_path.suffix == '.epub':
                    self.send_header('Content-Type', 'application/epub+zip')
                elif file_path.suffix == '.png':
                    self.send_header('Content-Type', 'image/png')
                elif file_path.suffix in ('.jpg', '.jpeg'):
                    self.send_header('Content-Type', 'image/jpeg')
                else:
                    import mimetypes
                    ct, _ = mimetypes.guess_type(str(file_path))
                    self.send_header('Content-Type', ct or 'application/octet-stream')
                self.end_headers()
                with open(file_path, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'File not found')
        elif self.path == '/download/epub' or self.path == '/download/epub/':
            # EPUB download with proper headers
            state = load_state()
            meta = state.get("meta", {})
            safe_title = re.sub(r'[^\w\s-]', '', meta.get("title", "Novel")).strip().replace(' ', '_')
            epub_path = PROJECT_ROOT / 'output' / f'{safe_title}.epub'
            if epub_path.exists():
                self.send_response(200)
                self.send_header('Content-Type', 'application/epub+zip')
                self.send_header('Content-Disposition',
                    f'attachment; filename="{epub_path.name}"')
                self.send_header('Content-Length', str(epub_path.stat().st_size))
                self.end_headers()
                with open(epub_path, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'EPUB not found')

    def log_message(self, format, *args):
        # Quieter logging
        pass


def generate_static():
    """Generate a static dashboard HTML file with embedded data."""
    data = get_progress_data()
    data_json = json.dumps(data, ensure_ascii=False).replace('</script>', r'<\/script>')
    
    html = DASHBOARD_HTML
    
    # Replace the fetch-based refresh with static data from embedded JSON
    static_refresh = (
        "async function refresh() {\n"
        "  const data = JSON.parse("
        "document.getElementById('static-data').textContent);\n"
        "  render(data);\n"
        "}"
    )
    # Find and replace the original fetch-based refresh function
    old_refresh_start = "async function refresh() {"
    old_refresh_end = "}"  
    # Replace everything between the refresh function markers
    start_idx = html.find(old_refresh_start)
    if start_idx != -1:
        # Find the matching closing brace (simple approach: find next function boundary)
        end_search = html.find("\n\nrefresh();", start_idx)
        if end_search != -1:
            html = html[:start_idx] + static_refresh + html[end_search:]
    
    # Inject data as a JSON script tag before the main script
    json_tag = '<script id="static-data" type="application/json">' + data_json + '</script>\n'
    html = html.replace('<script>\nconst STATUS_LABELS', json_tag + '<script>\nconst STATUS_LABELS')
    
    output_path = PROJECT_ROOT / "dashboard.html"
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"Static dashboard generated: {output_path}")
    print(f"Open in browser to view current progress.")


def serve_dashboard(port=8420):
    """Start the dashboard web server."""
    os.chdir(PROJECT_ROOT)
    server = HTTPServer(('localhost', port), DashboardHandler)
    print(f"""
  ╱╲
 ╱    ╲  Novel Dashboard
╱      ╲
╱   N   ╲  Serving at: http://localhost:{port}
╱   E    ╲  
╱   K     ╲  Auto-refreshes every 10 seconds
╱   O      ╲ 
╱_________╲  Press Ctrl+C to stop

""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
        server.server_close()


if __name__ == "__main__":
    if '--static' in sys.argv:
        generate_static()
    elif '--help' in sys.argv or '-h' in sys.argv:
        print(__doc__)
    else:
        port = 8420
        for i, arg in enumerate(sys.argv):
            if arg == '--port' and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])
        serve_dashboard(port)