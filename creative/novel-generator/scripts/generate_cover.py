#!/usr/bin/env python3
"""Generate cover image using diffusers directly (bypasses ComfyUI).

Usage:
  python scripts/generate_cover.py [--seed N] [--output OUTPUT_PATH] [--prompt PROMPT]

Uses AnimagineXL 3.1 model with CUDA acceleration.
"""

import argparse
import os
import sys

def load_state():
    """Load novel state from YAML to get title, genre, themes."""
    try:
        import yaml
        state_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "novel_state.yaml")
        if os.path.exists(state_file):
            with open(state_file, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
    except ImportError:
        pass
    return {}


def build_cover_prompt_from_state(state):
    """Build a cover generation prompt from the novel's actual metadata.
    
    This ensures the cover matches the CURRENT story, not a hardcoded default.
    """
    meta = state.get("meta", {})
    title = meta.get("title", "Untitled Novel")
    genre = meta.get("genre", "fiction").lower()
    seed = meta.get("seed", "")
    
    # Determine genre-specific art direction
    if "sci-fi" in genre or "science fiction" in genre or "scifi" in genre:
        base = (
            "science fiction book cover illustration, cinematic, dramatic lighting, "
            "deep space background with distant stars and nebulae, "
        )
        # Parse seed for specific imagery
        if "seedship" in seed.lower() or "arkadia" in seed.lower() or "sanctuary" in seed.lower():
            base += (
                "a massive cylindrical seedship drifting through the void, "
                "small human figure in EVAC suit for scale, "
                "translucent glowing AI sphere floating nearby, "
                "hull covered in ice and radiation scoring, "
            )
        if "destroy" in seed.lower() or "apocalypse" in seed.lower():
            base += "shattered planet debris in the distance, "
        if "ai" in seed.lower() or "artificial intelligence" in seed.lower():
            base += "ominous blue-white holographic glow suggesting AI presence, "
        base += (
            "detailed sci-fi art style, cinematic composition, "
            "high contrast, cold blue and warm amber color palette, "
            "high quality, masterpiece, book cover composition"
        )
    elif "fantasy" in genre or "isekai" in genre:
        base = (
            "fantasy light novel cover illustration, a young adventurer, "
            "medieval fantasy setting with magical elements, "
            "detailed anime art style, vibrant colors, dramatic lighting, "
            "high quality, masterpiece, light novel cover composition"
        )
    else:
        base = (
            "book cover illustration, dramatic, cinematic lighting, "
            "detailed art style, high quality, masterpiece, book cover composition"
        )
    
    return base


def generate_cover(seed=42, output_path=None, custom_prompt=None):
    import torch
    from diffusers import StableDiffusionXLPipeline
    from PIL import Image, ImageDraw, ImageFont

    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    MODEL_DIR = os.path.join(PROJECT_ROOT, "tools", "comfyui", "models", "checkpoints")
    
    if output_path is None:
        output_path = os.path.join(PROJECT_ROOT, "publish", "cover_raw.png")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Load state and build prompt from actual novel metadata
    state = load_state()
    prompt = custom_prompt or build_cover_prompt_from_state(state)

    neg_prompt = (
        "low quality, worst quality, bad anatomy, bad hands, missing fingers, "
        "extra digits, cropped, watermark, text, signature, blurry, deformed, "
        "ugly, duplicate, morbid, mutilated, out of frame"
    )

    # Load model from safetensors checkpoint
    # AnimagineXL 3.1 is an SDXL model
    ckpt_path = os.path.join(MODEL_DIR, "animagine-xl-3.1.safetensors")
    
    if not os.path.exists(ckpt_path):
        print(f"ERROR: Model not found at {ckpt_path}")
        print("Download it first with:")
        print("  wget -c https://huggingface.co/cagliostrolab/animagine-xl-3.1/resolve/main/animagine-xl-3.1.safetensors")
        print(f"  Place it in: {MODEL_DIR}")
        return None

    print(f"Loading AnimagineXL 3.1 from {ckpt_path}...")
    print(f"CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")

    pipe = StableDiffusionXLPipeline.from_single_file(
        ckpt_path,
        torch_dtype=torch.float16,
        use_safetensors=True,
    )
    
    if torch.cuda.is_available():
        pipe = pipe.to("cuda")
        # Sequential CPU offloading for limited VRAM — loads each component to GPU only when needed
        pipe.enable_sequential_cpu_offload()
        print("Sequential CPU offloading enabled (saves VRAM)")
    else:
        pipe = pipe.to("cpu")
        pipe.enable_attention_slicing()

    print(f"\nGenerating cover image...")
    print(f"  Prompt: {prompt[:80]}...")
    print(f"  Size: 1024x1536 (2:3 light novel ratio)")
    print(f"  Steps: 25, CFG: 7.0, Seed: {seed}")

    image = pipe(
        prompt=prompt,
        negative_prompt=neg_prompt,
        width=1024,
        height=1536,
        num_inference_steps=25,
        guidance_scale=7.0,
        generator=torch.Generator(device="cpu").manual_seed(seed),
    ).images[0]

    # Save raw cover
    image.save(output_path)
    print(f"\n✓ Cover image generated: {output_path}")
    print(f"  Size: {image.size}")

    # Clean up GPU memory
    del pipe
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate novel cover image")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--output", type=str, default=None, help="Output path")
    parser.add_argument("--prompt", type=str, default=None, help="Custom prompt")
    args = parser.parse_args()
    
    result = generate_cover(seed=args.seed, output_path=args.output, custom_prompt=args.prompt)
    if result is None:
        sys.exit(1)