"""
generate_video.py — Brainrot Anime Video Generator
====================================================
Uses Pollinations AI (free, no API key) to generate
anime-style images per scene, then animates them with
fast Ken Burns effect for maximum brainrot energy.
Output: raw_video.mp4 (no audio — merged by editor)
"""

import os
import re
import sys
import json
import time
import random
import subprocess
import requests
from pathlib import Path

# ══════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════

INPUT_SCRIPT    = Path("script.txt")
INPUT_AUDIO     = Path("output_voice.wav")
OUTPUT_VIDEO    = Path("raw_video.mp4")

VIDEO_W         = 1080
VIDEO_H         = 1920
FPS             = 30

# Image gen
IMG_W           = 1080
IMG_H           = 1920
IMAGES_DIR      = Path("ai_images")
SECONDS_PER_IMG = 3        # Fast cuts = brainrot energy
POLLINATIONS    = "https://image.pollinations.ai/prompt"

# Anime brainrot style suffix added to EVERY prompt
STYLE_SUFFIX    = (
    "anime style, vibrant neon colors, dynamic composition, "
    "high contrast, manga inspired, chaotic energy, "
    "ultra detailed, 4k, cinematic, dramatic lighting, "
    "no text, no watermark"
)

# Ken Burns variants — randomised per image for chaos
KB_EFFECTS = [
    # zoom in from center
    "zoompan=z='min(zoom+0.0015,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={d}:s={w}x{h}:fps={fps}",
    # zoom out
    "zoompan=z='if(lte(zoom,1.0),1.12,max(1.001,zoom-0.0015))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={d}:s={w}x{h}:fps={fps}",
    # pan left + zoom in
    "zoompan=z='min(zoom+0.001,1.08)':x='if(lte(on,1),0,x+1.2)':y='ih/2-(ih/zoom/2)':d={d}:s={w}x{h}:fps={fps}",
    # pan right + zoom in
    "zoompan=z='min(zoom+0.001,1.08)':x='if(lte(on,1),iw,max(iw/zoom/2,x-1.2))':y='ih/2-(ih/zoom/2)':d={d}:s={w}x{h}:fps={fps}",
    # pan up
    "zoompan=z='1.08':x='iw/2-(iw/zoom/2)':y='if(lte(on,1),0,min(y+0.8,ih/zoom))':d={d}:s={w}x{h}:fps={fps}",
]

# ══════════════════════════════════════════════════════════════════
#  AUDIO DURATION
# ══════════════════════════════════════════════════════════════════

def get_audio_duration(path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        duration = float(result.stdout.strip())
        print(f"[INFO] Audio duration: {duration:.2f}s")
        return duration
    except:
        sys.exit("[ERROR] Could not read audio duration")


# ══════════════════════════════════════════════════════════════════
#  SCENE EXTRACTION
# ══════════════════════════════════════════════════════════════════

def extract_scenes(text: str, n_images: int) -> list:
    """
    Split script into N scenes.
    Each scene gets a unique visual prompt.
    """
    # Clean stage directions
    clean = re.sub(r'\[.*?\]', '', text, flags=re.DOTALL)
    clean = re.sub(r'---.*?---', '', clean, flags=re.DOTALL)
    clean = re.sub(r'\n+', ' ', clean).strip()

    # Split into sentences
    sentences = re.split(r'(?<=[.!?])\s+', clean)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]

    if not sentences:
        sentences = [clean]

    # Group sentences into N scene chunks
    chunk_size = max(1, len(sentences) // n_images)
    scenes = []
    for i in range(0, len(sentences), chunk_size):
        chunk = ' '.join(sentences[i:i + chunk_size])
        scenes.append(chunk[:300])  # cap length

    # Ensure exactly n_images scenes
    while len(scenes) < n_images:
        scenes.append(scenes[-1])
    scenes = scenes[:n_images]

    print(f"[INFO] Extracted {len(scenes)} scenes from script")
    return scenes


def scene_to_prompt(scene: str, index: int, total: int) -> str:
    """
    Convert a scene description into a vivid anime visual prompt.
    Uses position in video to vary mood:
      - Opening: establish, dramatic
      - Middle: action, intense
      - End: reveal, emotional
    """
    position = index / max(1, total - 1)

    # Extract key nouns/verbs
    stopwords = {
        'the','a','an','and','or','but','in','on','at','to','for',
        'of','with','it','is','was','be','are','were','i','you',
        'he','she','they','we','my','your','just','that','this',
        'have','had','about','from','not','so','then','when','what'
    }
    words = re.findall(r'\b[a-zA-Z]{4,}\b', scene.lower())
    keywords = [w for w in words if w not in stopwords][:5]
    keyword_str = ', '.join(keywords) if keywords else 'mysterious scene'

    # Mood based on position
    if position < 0.2:
        mood = "epic establishing shot, wide angle, dramatic reveal"
    elif position < 0.5:
        mood = "intense close-up, dynamic action, emotional expression"
    elif position < 0.8:
        mood = "dramatic mid-shot, tension, vivid colors, chaos"
    else:
        mood = "powerful climax shot, glowing effects, cinematic resolution"

    # ALL CAPS words in scene = more intense prompt
    caps_words = re.findall(r'\b[A-Z]{3,}\b', scene)
    intensity = "extreme intensity, " if caps_words else ""

    prompt = (
        f"{intensity}{keyword_str}, {mood}, "
        f"anime character, {STYLE_SUFFIX}"
    )

    return prompt


# ══════════════════════════════════════════════════════════════════
#  AI IMAGE GENERATION
# ══════════════════════════════════════════════════════════════════

def generate_image(prompt: str, index: int, retries: int = 3) -> Path:
    """Call Pollinations API to generate one anime image."""
    out_path = IMAGES_DIR / f"scene_{index:03d}.jpg"

    # Encode prompt for URL
    encoded = requests.utils.quote(prompt)
    seed = random.randint(1000, 999999)
    url = (
        f"{POLLINATIONS}/{encoded}"
        f"?width={IMG_W}&height={IMG_H}"
        f"&model=flux"
        f"&seed={seed}"
        f"&nologo=true"
        f"&enhance=true"
    )

    for attempt in range(retries):
        try:
            print(f"  [AI {index+1}] Generating: {prompt[:60]}...")
            r = requests.get(url, timeout=60, stream=True)
            if r.status_code == 200 and len(r.content) > 10000:
                with open(out_path, "wb") as f:
                    f.write(r.content)
                size_kb = out_path.stat().st_size / 1024
                print(f"  [AI {index+1}] ✅ Generated ({size_kb:.0f} KB)")
                return out_path
            else:
                print(f"  [AI {index+1}] Attempt {attempt+1} failed (status {r.status_code}), retrying...")
                time.sleep(3)
        except Exception as e:
            print(f"  [AI {index+1}] Error: {e}, retrying...")
            time.sleep(3)

    # Fallback: generate a solid color frame
    print(f"  [AI {index+1}] ⚠️ Using fallback solid frame")
    colors = ["#1a0a2e", "#0d1b2a", "#1b1b2f", "#16213e", "#0f3460"]
    color = colors[index % len(colors)]
    fallback = IMAGES_DIR / f"fallback_{index:03d}.png"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        f"-i", f"color=c={color}:size={IMG_W}x{IMG_H}:rate=1",
        "-frames:v", "1", str(fallback)
    ], capture_output=True)
    return fallback


def generate_all_images(scenes: list) -> list:
    """Generate AI image for every scene."""
    IMAGES_DIR.mkdir(exist_ok=True)
    image_paths = []
    total = len(scenes)

    for i, scene in enumerate(scenes):
        prompt = scene_to_prompt(scene, i, total)
        img_path = generate_image(prompt, i)
        image_paths.append(str(img_path))
        # Small delay to avoid rate limiting
        time.sleep(1.5)

    print(f"[INFO] Generated {len(image_paths)} AI images")
    return image_paths


# ══════════════════════════════════════════════════════════════════
#  KEN BURNS ANIMATION
# ══════════════════════════════════════════════════════════════════

def animate_image(img_path: str, out_path: str, duration: float, kb_index: int):
    """
    Apply Ken Burns zoom/pan effect to a single image.
    Creates a short animated clip from a still image.
    """
    frames = int(duration * FPS)
    effect = KB_EFFECTS[kb_index % len(KB_EFFECTS)]
    zoompan = effect.format(d=frames, w=VIDEO_W, h=VIDEO_H, fps=FPS)

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", img_path,
        "-vf", (
            f"scale={VIDEO_W*2}:{VIDEO_H*2}:force_original_aspect_ratio=increase,"
            f"crop={VIDEO_W*2}:{VIDEO_H*2},"
            f"{zoompan},"
            f"scale={VIDEO_W}:{VIDEO_H},"
            f"setsar=1"
        ),
        "-t", str(duration),
        "-r", str(FPS),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-an",
        out_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Fallback: simple scale without zoompan
        cmd_fallback = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", img_path,
            "-vf", f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=increase,crop={VIDEO_W}:{VIDEO_H},setsar=1",
            "-t", str(duration),
            "-r", str(FPS),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-an",
            out_path
        ]
        subprocess.run(cmd_fallback, capture_output=True, check=True)


def animate_all_images(image_paths: list, audio_duration: float) -> list:
    """Animate every image with randomised Ken Burns effect."""
    animated_dir = Path("animated_clips")
    animated_dir.mkdir(exist_ok=True)
    animated_paths = []

    total = len(image_paths)
    # Distribute duration across images
    # Last image gets any remaining time
    base_duration = audio_duration / total

    print(f"[INFO] Animating {total} images @ ~{base_duration:.1f}s each...")

    kb_order = list(range(len(KB_EFFECTS)))
    random.shuffle(kb_order)  # Random Ken Burns order for chaos

    for i, img_path in enumerate(image_paths):
        out = str(animated_dir / f"anim_{i:03d}.mp4")
        dur = base_duration
        kb_idx = kb_order[i % len(kb_order)]

        try:
            animate_image(img_path, out, dur, kb_idx)
            animated_paths.append(out)
            print(f"  [ANIM {i+1}/{total}] ✅ {dur:.1f}s Ken Burns effect #{kb_idx}")
        except Exception as e:
            print(f"  [ANIM {i+1}/{total}] ⚠️ Failed: {e}")

    return animated_paths


# ══════════════════════════════════════════════════════════════════
#  CONCATENATE WITH CROSSFADE
# ══════════════════════════════════════════════════════════════════

def concat_with_crossfade(clip_paths: list, audio_duration: float) -> str:
    """
    Concatenate animated clips with a fast crossfade dissolve between them.
    Brainrot = fast transitions, no hard cuts.
    """
    if len(clip_paths) == 1:
        return clip_paths[0]

    # Write concat list
    concat_file = Path("concat_list.txt")
    with open(concat_file, "w") as f:
        for p in clip_paths:
            f.write(f"file '{p}'\n")

    concat_out = "concat_raw.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        concat_out
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    print(f"[INFO] Concatenated {len(clip_paths)} clips")
    return concat_out


# ══════════════════════════════════════════════════════════════════
#  FINAL TRIM
# ══════════════════════════════════════════════════════════════════

def trim_to_duration(video_path: str, duration: float, output: str):
    """Hard trim to exact audio duration. No audio track."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-an",
        output
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    size_mb = Path(output).stat().st_size / (1024 * 1024)
    print(f"[✓] Video trimmed to {duration:.2f}s → '{output}' ({size_mb:.1f} MB)")


# ══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════

def main():
    print("=" * 62)
    print("  Brainrot Anime Video Generator")
    print("  Pollinations AI + Ken Burns + Fast Cuts")
    print("=" * 62)

    # Load script
    if not INPUT_SCRIPT.exists():
        sys.exit("[ERROR] script.txt not found")
    script_text = INPUT_SCRIPT.read_text(encoding="utf-8")
    print(f"[INFO] Script loaded ({len(script_text)} chars)")

    # Load audio
    if not INPUT_AUDIO.exists():
        sys.exit("[ERROR] output_voice.wav not found")
    audio_duration = get_audio_duration(str(INPUT_AUDIO))

    # Calculate how many images needed
    n_images = max(4, int(audio_duration / SECONDS_PER_IMG))
    print(f"[INFO] Generating {n_images} AI images for {audio_duration:.1f}s video")

    # Step 1: Extract scenes
    print("\n[STEP 1] Extracting scenes from script...")
    scenes = extract_scenes(script_text, n_images)

    # Step 2: Generate AI images
    print("\n[STEP 2] Generating anime images via Pollinations AI...")
    image_paths = generate_all_images(scenes)

    # Step 3: Animate with Ken Burns
    print("\n[STEP 3] Animating images with Ken Burns effect...")
    animated_paths = animate_all_images(image_paths, audio_duration)

    if not animated_paths:
        sys.exit("[ERROR] No animated clips generated")

    # Step 4: Concatenate
    print("\n[STEP 4] Concatenating clips...")
    concat_video = concat_with_crossfade(animated_paths, audio_duration)

    # Step 5: Final trim to exact audio length
    print("\n[STEP 5] Trimming to exact audio duration...")
    trim_to_duration(concat_video, audio_duration, str(OUTPUT_VIDEO))

    print("\n" + "=" * 62)
    print("  [✓] DONE — raw_video.mp4 ready for editor")
    print("=" * 62)


if __name__ == "__main__":
    main()
