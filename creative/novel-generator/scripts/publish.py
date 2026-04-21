#!/usr/bin/env python3
"""Novel Publishing Pipeline — Cover generation, title overlay, and EPUB assembly.

Usage:
  python scripts/publish.py --cover-only      # Generate cover image via diffusers
  python scripts/publish.py --overlay-only    # Overlay title on existing cover
  python scripts/publish.py --epub-only       # Assemble EPUB from chapters + cover
  python scripts/publish.py --all              # Run full pipeline
  python scripts/publish.py --cover-prompt "custom prompt"  # Custom cover prompt
"""

import argparse
import os
import re
import sys
import textwrap
from pathlib import Path

try:
    from ebooklib import epub
    from PIL import Image, ImageDraw, ImageFont
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Install with: pip install ebooklib Pillow")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).parent.parent
COVER_DIR = PROJECT_ROOT / "publish"
OUTPUT_DIR = PROJECT_ROOT / "output"
CHAPTERS_DIR = PROJECT_ROOT / "chapters"

# Novel metadata — loaded from novel_state.yaml, NOT hardcoded
def get_novel_metadata():
    """Load title, author, genre from novel_state.yaml.
    Falls back to defaults only if state file is missing.
    """
    state = load_novel_state()
    meta = state.get("meta", {})
    return {
        "title": meta.get("title", "Untitled Novel"),
        "author": meta.get("author", ""),
        "genre": meta.get("genre", "Fiction"),
        "seed": meta.get("seed", ""),
    }

# Cover generation settings
COMFYUI_PORT = 8189
COMFYUI_DIR = PROJECT_ROOT / "tools" / "comfyui"
MODEL_NAME = "animagine-xl-3.1.safetensors"
COVER_WIDTH = 1024
COVER_HEIGHT = 1536  # 2:3 ratio (standard light novel cover)

NEGATIVE_PROMPT = (
    "low quality, worst quality, bad anatomy, bad hands, missing fingers, "
    "extra digits, cropped, watermark, text, signature, blurry, deformed, "
    "ugly, duplicate, morbid, mutilated"
)


def load_novel_state():
    """Load novel state from YAML."""
    try:
        import yaml
        state_file = PROJECT_ROOT / "novel_state.yaml"
        if state_file.exists():
            with open(state_file, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
    except ImportError:
        pass
    return {}


# ─── Cover Generation ────────────────────────────────────────────────────

def generate_cover_diffusers(prompt=None, neg_prompt=None, seed=42, output_path=None):
    """Generate cover image using diffusers directly (bypasses ComfyUI API issues)."""
    import torch
    from diffusers import StableDiffusionXLPipeline

    if output_path is None:
        output_path = COVER_DIR / "cover_raw.png"
    COVER_DIR.mkdir(parents=True, exist_ok=True)

    # Build prompt from novel state if not provided
    if prompt is None:
        state = load_novel_state()
        meta = state.get("meta", {})
        genre = meta.get("genre", "fiction").lower()
        seed_desc = meta.get("seed", "")
        
        if "sci-fi" in genre or "science fiction" in genre:
            prompt = (
                "science fiction book cover illustration, cinematic, dramatic lighting, "
                "deep space background with distant stars and nebulae, "
                "a massive cylindrical seedship drifting through the void, "
                "small human figure in EVAC suit for scale, "
                "translucent glowing AI sphere floating nearby, "
                "shattered planet debris in the distance, "
                "ominous blue-white holographic glow, "
                "detailed sci-fi art style, cinematic composition, "
                "high contrast, cold blue and warm amber color palette, "
                "high quality, masterpiece, book cover composition"
            )
        else:
            prompt = (
                "book cover illustration, dramatic, cinematic lighting, "
                "detailed art style, high quality, masterpiece, book cover composition"
            )
    
    neg_prompt = neg_prompt or NEGATIVE_PROMPT

    model_dir = COMFYUI_DIR / "models" / "checkpoints"
    # Find the safetensors model
    model_path = None
    for f in model_dir.glob("*.safetensors"):
        model_path = str(f)
        break
    if not model_path:
        print(f"ERROR: No safetensors model found in {model_dir}")
        return None

    print(f"Loading {os.path.basename(model_path)}...")
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)}")

    pipe = StableDiffusionXLPipeline.from_single_file(
        model_path,
        torch_dtype=torch.float16,
        use_safetensors=True,
    )

    if torch.cuda.is_available():
        pipe = pipe.to("cuda")
        pipe.enable_sequential_cpu_offload()
        print("Sequential CPU offloading enabled")
    else:
        pipe = pipe.to("cpu")
        pipe.enable_attention_slicing()

    print(f"Generating cover... (seed={seed})")
    image = pipe(
        prompt=prompt,
        negative_prompt=neg_prompt,
        width=COVER_WIDTH,
        height=COVER_HEIGHT,
        num_inference_steps=25,
        guidance_scale=7.0,
        generator=torch.Generator(device="cpu").manual_seed(seed),
    ).images[0]

    image.save(str(output_path))
    print(f"Cover saved: {output_path} ({image.size})")

    del pipe
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return str(output_path)


def generate_cover_comfyui(prompt=None, neg_prompt=None, seed=None):
    """Generate cover image using ComfyUI API. DEPRECATED — use generate_cover_diffusers instead."""
    import json
    import time
    import urllib.request

    prompt = prompt or DEFAULT_COVER_PROMPT
    neg_prompt = neg_prompt or NEGATIVE_PROMPT
    seed = seed or 42

    COVER_DIR.mkdir(parents=True, exist_ok=True)

    # Check if ComfyUI is running
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{COMFYUI_PORT}/system_stats", timeout=5)
    except Exception:
        print("ComfyUI is not running. Start it separately or use generate_cover_diffusers().")
        return None

    workflow = {
        "3": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": 25, "cfg": 7.0, "sampler_name": "euler_ancestral", "scheduler": "normal", "denoise": 1.0, "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": MODEL_NAME}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": COVER_WIDTH, "height": COVER_HEIGHT, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": neg_prompt, "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "novel_cover", "images": ["8", 0]}},
    }

    payload = {"prompt": workflow}
    req = urllib.request.Request(
        f"http://127.0.0.1:{COMFYUI_PORT}/prompt",
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
    )

    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        prompt_id = result.get('prompt_id')
        print(f"Queued: {prompt_id}")
    except Exception as e:
        print(f"ERROR: {e}")
        return None

    print("Waiting for generation...")
    for _ in range(120):
        time.sleep(2)
        try:
            hist = urllib.request.urlopen(f"http://127.0.0.1:{COMFYUI_PORT}/history/{prompt_id}", timeout=5)
            hist_data = json.loads(hist.read())
            if prompt_id in hist_data:
                outputs = hist_data[prompt_id].get('outputs', {})
                if '9' in outputs:
                    images = outputs['9'].get('images', [])
                    if images:
                        filename = images[0]['filename']
                        subfolder = images[0].get('subfolder', '')
                        output_path = COMFYUI_DIR / "output" / subfolder / filename
                        if output_path.exists():
                            import shutil
                            final_path = COVER_DIR / "cover_raw.png"
                            shutil.copy2(output_path, final_path)
                            print(f"Cover generated: {final_path}")
                            return str(final_path)
        except Exception:
            pass

    print("ERROR: Generation timed out")
    return None


# ─── Title Overlay ────────────────────────────────────────────────────────

def overlay_title_on_cover(cover_path=None, title=None, author=None):
    """Overlay title and author text onto the cover image."""
    cover_path = Path(cover_path) if cover_path else COVER_DIR / "cover_raw.png"
    
    # Load metadata from state if not provided
    meta = get_novel_metadata()
    title = title or meta["title"]
    author = author or meta["author"]

    if not cover_path.exists():
        print(f"ERROR: Cover image not found at {cover_path}")
        return None

    COVER_DIR.mkdir(parents=True, exist_ok=True)

    img = Image.open(cover_path).convert("RGBA")
    w, h = img.size

    # Create overlay layer
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Top gradient (for title area)
    gradient_height_top = int(h * 0.45)
    for y in range(gradient_height_top):
        alpha = int(180 * (1 - y / gradient_height_top) ** 1.5)
        draw.line([(0, y), (w, y)], fill=(10, 10, 30, alpha))

    # Bottom gradient (for author area)
    gradient_height_bottom = int(h * 0.25)
    for y in range(gradient_height_bottom):
        alpha = int(160 * (y / gradient_height_bottom) ** 1.5)
        draw_y = h - gradient_height_bottom + y
        draw.line([(0, draw_y), (w, draw_y)], fill=(10, 10, 30, alpha))

    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)

    # Find a good font
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/google-noto-vf/NotoSans[wght].ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]

    title_font = None
    author_font = None
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                title_size = max(int(w * 0.07), 48)
                title_font = ImageFont.truetype(fp, title_size)
                author_size = max(int(w * 0.04), 28)
                author_font = ImageFont.truetype(fp, author_size)
                break
            except Exception:
                continue

    if title_font is None:
        print("WARNING: No TrueType font found, using default bitmap font")
        title_font = ImageFont.load_default()
        author_font = ImageFont.load_default()

    # Render title with shadow
    title_lines = textwrap.wrap(title, width=20)
    line_height = title_font.size + int(title_font.size * 0.15)
    title_y_start = int(h * 0.12)

    for i, line in enumerate(title_lines):
        y = title_y_start + i * line_height
        draw.text((w // 2 + 3, y + 3), line, fill=(0, 0, 0, 200), font=title_font, anchor="mt")
        draw.text((w // 2, y), line, fill=(255, 255, 255, 240), font=title_font, anchor="mt")

    # Render author
    author_text = f"by {author}"
    author_y = int(h * 0.88)
    draw.text((w // 2 + 2, author_y + 2), author_text, fill=(0, 0, 0, 180), font=author_font, anchor="mt")
    draw.text((w // 2, author_y), author_text, fill=(220, 220, 255, 230), font=author_font, anchor="mt")

    # Save
    output_path = COVER_DIR / "cover_final.png"
    rgb_img = Image.new("RGB", img.size, (255, 255, 255))
    rgb_img.paste(img, mask=img.split()[3])
    rgb_img.save(str(output_path), "PNG")

    jpeg_path = COVER_DIR / "cover_final.jpg"
    rgb_img.save(str(jpeg_path), "JPEG", quality=90)

    print(f"Cover with title saved:")
    print(f"  PNG: {output_path}")
    print(f"  JPEG: {jpeg_path}")
    print(f"  Size: {rgb_img.size}")

    return str(output_path)


# ─── EPUB Assembly ────────────────────────────────────────────────────────

EPUB_CSS = """\
@charset "UTF-8";
@namespace epub "http://www.idpf.org/2007/ops";

body {
    font-family: "Libertinus Serif", "Literata", "Crimson Text", Georgia, "Times New Roman", serif;
    font-size: 1.0em;
    line-height: 1.6;
    margin: 0;
    padding: 0;
    color: #1a1a1a;
}

h1 {
    font-size: 1.5em;
    font-weight: bold;
    text-align: center;
    margin-top: 1em;
    margin-bottom: 1em;
    page-break-before: always;
}

h2 {
    font-size: 1.3em;
    font-weight: bold;
    margin-top: 1.5em;
    margin-bottom: 0.5em;
}

h3 {
    font-size: 1.1em;
    font-weight: bold;
    margin-top: 1.2em;
    margin-bottom: 0.4em;
}

p {
    margin-top: 0;
    margin-bottom: 0.6em;
    text-indent: 1.5em;
    text-align: justify;
    widows: 2;
    orphans: 2;
}

/* First paragraph after heading or scene break has no indent */
h1 + p, h2 + p, h3 + p,
.scene-break + p {
    text-indent: 0;
}

/* Dialogue styling */
.dialogue {
    /* Curly quotes are already rendered in the text */
}

/* Scene break */
.scene-break {
    text-align: center;
    margin: 2em 0;
    font-style: italic;
    letter-spacing: 0.3em;
    color: #666;
}

strong { font-weight: bold; }
em { font-style: italic; }

/* Suppress indent on first paragraph of chapter */
.first-para {
    text-indent: 0;
}
"""


def markdown_to_html(text):
    """Convert markdown text to XHTML body content for EPUB.

    Returns ONLY the inner body markup — no <html>, <head>, or <body> tags.
    ebooklib handles the document wrapper.

    Handles: headings, paragraphs, emphasis, bold, dialogue, scene breaks.
    """
    lines = text.split("\n")
    parts = []

    in_paragraph = False

    for line in lines:
        stripped = line.strip()

        # Empty line = paragraph break
        if not stripped:
            if in_paragraph:
                parts.append("</p>")
                in_paragraph = False
            continue

        # Scene break: ---, ***, - - -, etc.
        if re.match(r'^[*\-]{3,}$', stripped) or stripped in ("---", "***", "- - -"):
            if in_paragraph:
                parts.append("</p>")
                in_paragraph = False
            parts.append('<div class="scene-break">* * *</div>')
            continue

        # Heading level 3
        if stripped.startswith("### "):
            if in_paragraph:
                parts.append("</p>")
                in_paragraph = False
            parts.append(f"<h3>{html_escape(stripped[4:])}</h3>")
            continue

        # Heading level 2
        if stripped.startswith("## "):
            if in_paragraph:
                parts.append("</p>")
                in_paragraph = False
            parts.append(f"<h2>{html_escape(stripped[3:])}</h2>")
            continue

        # Heading level 1
        if stripped.startswith("# "):
            if in_paragraph:
                parts.append("</p>")
                in_paragraph = False
            parts.append(f"<h1>{html_escape(stripped[2:])}</h1>")
            continue

        # Regular text line — process inline formatting
        processed = inline_format(stripped)

        if not in_paragraph:
            parts.append(f"<p>{processed}")
            in_paragraph = True
        else:
            # Continuation of same paragraph — join with space
            parts.append(f" {processed}")

    # Close any open paragraph
    if in_paragraph:
        parts.append("</p>")

    return "\n".join(parts)


def _replace_dialogue(match):
    """Replace "text" with curly-quoted dialogue span."""
    inner = match.group(1)
    return f'\u201c{inner}\u201d'


def inline_format(text):
    """Process inline markdown formatting: bold, italic, dialogue."""
    # Dialogue: "text" → <span class="dialogue">"text"</span> (with curly quotes)
    text = re.sub(r'"(.+?)"', lambda m: f'<span class="dialogue">\u201c{m.group(1)}\u201d</span>', text)

    # Bold: **text** → <strong>text</strong>
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)

    # Italic: *text* → <em>text</em>
    # Only match single * not preceded/followed by * (to avoid matching bold)
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<em>\1</em>', text)

    return text


def html_escape(text):
    """Escape HTML special characters."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("\u2014", "&mdash;")   # em dash
            .replace("\u2013", "&ndash;"))   # en dash


def assemble_epub(cover_path=None, title=None, author=None):
    """Assemble all chapters into a properly formatted EPUB with cover image.

    ebooklib EpubHtml.content should contain ONLY the inner body HTML.
    The library wraps it in the proper XHTML document structure.
    """
    # Load metadata from state if not provided
    meta = get_novel_metadata()
    title = title or meta["title"]
    author = author or meta["author"]
    cover_path = Path(cover_path) if cover_path else COVER_DIR / "cover_final.jpg"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load state for metadata
    state = load_novel_state()
    state_meta = state.get("meta", {})
    genre = state_meta.get("genre", "Fiction")
    seed = state_meta.get("seed", "")

    # ── Create book ──────────────────────────────────────────────────────
    book = epub.EpubBook()
    book.set_identifier(title.lower().replace(" ", "-").replace("'", ""))
    book.set_title(title)
    book.set_language("en")
    book.add_author(author)

    if seed:
        book.add_metadata("DC", "description", seed)
    book.add_metadata("DC", "subject", genre)
    book.add_metadata("DC", "publisher", "Self-Published")
    book.add_metadata("DC", "rights", "Copyright 2026. All rights reserved.")

    # ── Add cover ────────────────────────────────────────────────────────
    cover_page = None
    if cover_path and cover_path.exists():
        with open(cover_path, "rb") as f:
            cover_data = f.read()
        ext = cover_path.suffix.lower()
        media_type = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"

        # Create a proper cover page that appears as Page 1 in readers.
        # We use set_cover(create_page=False) for the metadata/thumbnail only,
        # then build our own XHTML cover page that goes in the spine.
        cover_html = (
            '<div style="text-align: center; page-break-after: always;">'
            f'<img src="cover{ext}" alt="Cover" style="max-width: 100%; max-height: 100%;"/>'
            '</div>'
        )

        cover_page = epub.EpubHtml(
            title="Cover",
            file_name="cover_page.xhtml",
            lang="en",
        )
        cover_page.content = cover_html.encode("utf-8")
        book.add_item(cover_page)

        # Set cover metadata for library thumbnails. This also adds the image file
        # to the EPUB manifest, so we do NOT add a separate EpubItem for the image.
        book.set_cover(f"cover{ext}", cover_data, create_page=False)

        print(f"Cover image added: {cover_path.name} ({len(cover_data):,} bytes)")
    else:
        print(f"WARNING: No cover at {cover_path}, continuing without it")

    # ── Add stylesheet (ONCE) ───────────────────────────────────────────
    style_item = epub.EpubItem(
        uid="stylesheet",
        file_name="stylesheet.css",
        media_type="text/css",
        content=EPUB_CSS.encode("utf-8"),
    )
    book.add_item(style_item)

    # ── Read and add chapters ────────────────────────────────────────────
    chapter_files = sorted(
        [f for f in CHAPTERS_DIR.glob("chapter_*.md") if "_polished" not in f.name],
        key=lambda f: int(re.search(r'(\d+)', f.name).group(1))
    )

    # Deduplicate: prefer base version over polished
    seen_nums = set()
    unique_chapters = []
    for f in chapter_files:
        num = int(re.search(r'(\d+)', f.name).group(1))
        if num not in seen_nums:
            seen_nums.add(num)
            unique_chapters.append(f)
    chapter_files = unique_chapters

    print(f"\nAssembling {len(chapter_files)} chapters into EPUB...")

    spine_items = []
    toc_items = []
    total_words = 0

    for i, chapter_file in enumerate(chapter_files):
        with open(chapter_file, "r", encoding="utf-8") as f:
            content = f.read()

        # Extract chapter number and title
        num_match = re.search(r'(\d+)', chapter_file.name)
        ch_num = int(num_match.group(1)) if num_match else i + 1

        # Extract title from first line (# Title)
        lines = content.strip().split("\n")
        ch_title = f"Chapter {ch_num}"
        if lines and lines[0].startswith("#"):
            ch_title = lines[0].lstrip("#").strip()
            content = "\n".join(lines[1:]).strip()

        # Convert markdown to XHTML body content
        html_body = markdown_to_html(content)
        
        # Prepend chapter title as <h1> — the EpubHtml title is metadata only;
        # readers need the visible heading in the body content too
        html_body = f"<h1>{html_escape(ch_title)}</h1>\n" + html_body
        
        total_words += len(content.split())

        # Create EPUB chapter — content is BODY HTML only
        chapter = epub.EpubHtml(
            title=ch_title,
            file_name=f"chapter_{ch_num:02d}.xhtml",
            lang="en",
        )
        # Set the content — just the body HTML, ebooklib wraps it
        chapter.content = html_body.encode("utf-8")
        chapter.add_item(style_item)

        book.add_item(chapter)
        spine_items.append(chapter)
        toc_items.append(chapter)

        word_count = len(content.split())
        print(f"  Ch {ch_num}: {ch_title} ({word_count:,} words)")

    # ── Add navigation ──────────────────────────────────────────────────
    book.toc = toc_items

    # Add navigation files (required for EPUB 3)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # ── Set spine ────────────────────────────────────────────────────────
    # Spine order: cover page → nav → chapters
    spine = []
    if cover_page:
        spine.append(cover_page)
    spine.append("nav")  # TOC navigation
    spine.extend(spine_items)
    book.spine = spine

    # ── Write EPUB ──────────────────────────────────────────────────────
    safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')
    epub_path = OUTPUT_DIR / f"{safe_title}.epub"
    epub.write_epub(str(epub_path), book)

    print(f"\n{'='*50}")
    print(f"  EPUB published: {epub_path}")
    print(f"  {len(chapter_files)} chapters, {total_words:,} words")
    print(f"  Cover: {cover_path.name if cover_path and cover_path.exists() else 'none'}")
    print(f"  File size: {epub_path.stat().st_size / 1024:.0f} KB")
    print(f"{'='*50}")

    return epub_path


# ─── Validation ────────────────────────────────────────────────────────────

def validate_epub(epub_path):
    """Basic validation: check EPUB structure and chapter content."""
    import zipfile

    epub_path = Path(epub_path)
    if not epub_path.exists():
        print(f"ERROR: EPUB not found at {epub_path}")
        return False

    print(f"\nValidating EPUB: {epub_path.name}")
    print(f"  File size: {epub_path.stat().st_size / 1024:.0f} KB")

    with zipfile.ZipFile(epub_path, 'r') as z:
        names = z.namelist()

        # Check required files
        has_mimetype = "mimetype" in names
        has_container = "META-INF/container.xml" in names
        has_opf = any(n.endswith('.opf') for n in names)
        print(f"  mimetype: {'OK' if has_mimetype else 'MISSING'}")
        print(f"  container.xml: {'OK' if has_container else 'MISSING'}")
        print(f"  OPF manifest: {'OK' if has_opf else 'MISSING'}")

        # Check chapters have content
        chapter_files = [n for n in names if re.match(r'.*chapter_\d+\.xhtml', n)]
        print(f"  Chapters: {len(chapter_files)}")

        all_ok = True
        for cf in sorted(chapter_files):
            data = z.read(cf)
            size = len(data)
            # Check that chapter has actual content (not just empty tags)
            has_body = b"<p>" in data or b"<h1>" in data or b"<h2>" in data
            has_paragraphs = data.count(b"<p>") > 1
            status = "OK" if has_paragraphs else "EMPTY/WARN"
            print(f"    {cf}: {size:,} bytes, {data.count(b'<p>')} paragraphs [{status}]")
            if not has_paragraphs:
                all_ok = False

        # Check cover
        has_cover = any("cover" in n.lower() for n in names if n.endswith(('.jpg', '.jpeg', '.png')))
        print(f"  Cover image: {'OK' if has_cover else 'MISSING'}")

        # Check stylesheet
        has_css = any(n.endswith('.css') for n in names)
        print(f"  Stylesheet: {'OK' if has_css else 'MISSING'}")

    if all_ok:
        print("\n  ✓ EPUB validation passed")
    else:
        print("\n  ✗ EPUB has issues — some chapters may be empty")

    return all_ok


# ─── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Novel Publishing Pipeline")
    parser.add_argument("--cover-only", action="store_true", help="Generate cover image only")
    parser.add_argument("--overlay-only", action="store_true", help="Overlay title on existing cover only")
    parser.add_argument("--epub-only", action="store_true", help="Assemble EPUB only")
    parser.add_argument("--all", action="store_true", help="Run full pipeline (default if no action specified)")
    parser.add_argument("--cover-prompt", type=str, default=None, help="Custom cover generation prompt")
    parser.add_argument("--title", type=str, default=None, help="Novel title (default: from novel_state.yaml)")
    parser.add_argument("--author", type=str, default=None, help="Author name (default: from novel_state.yaml)")
    parser.add_argument("--cover-input", type=str, default=None, help="Path to existing cover image (skip generation)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for cover generation")
    parser.add_argument("--validate", action="store_true", help="Validate EPUB after assembly")
    args = parser.parse_args()

    # Load metadata defaults from state
    meta = get_novel_metadata()
    if args.title is None:
        args.title = meta["title"]
    if args.author is None:
        args.author = meta["author"]

    # Default to --all if no specific action
    if not any([args.cover_only, args.overlay_only, args.epub_only]):
        args.all = True

    cover_path = COVER_DIR / "cover_raw.png" if args.cover_input is None else Path(args.cover_input)

    if args.all or args.cover_only:
        if args.cover_input:
            print(f"Using existing cover: {cover_path}")
        else:
            print("=" * 50)
            print("  COVER IMAGE GENERATION")
            print("=" * 50)
            result = generate_cover_diffusers(
                prompt=args.cover_prompt,
                seed=args.seed,
            )
            if result:
                cover_path = Path(result)
                print(f"\n✓ Cover generated: {cover_path}")
            else:
                print("\n✗ Cover generation failed, continuing without cover")

    if args.all or args.overlay_only:
        print("\n" + "=" * 50)
        print("  TITLE OVERLAY")
        print("=" * 50)
        result = overlay_title_on_cover(
            cover_path=cover_path if cover_path.exists() else None,
            title=args.title,
            author=args.author,
        )
        if result:
            print(f"\n✓ Title overlay complete: {result}")
        else:
            print("\n✗ Title overlay failed")
            if not args.epub_only:
                sys.exit(1)

    if args.all or args.epub_only:
        print("\n" + "=" * 50)
        print("  EPUB ASSEMBLY")
        print("=" * 50)
        epub_path = assemble_epub(
            cover_path=COVER_DIR / "cover_final.jpg",
            title=args.title,
            author=args.author,
        )
        if epub_path and args.validate:
            validate_epub(epub_path)
        if epub_path:
            print(f"\n✓ EPUB published: {epub_path}")
        else:
            print("\n✗ EPUB assembly failed")
            sys.exit(1)

    print("\n" + "=" * 50)
    print("  PUBLISHING COMPLETE!")
    print("=" * 50)


if __name__ == "__main__":
    main()