"""
generate_video.py — Brainrot Anime Story Engine
=================================================
Generates a visually coherent anime story from script.
Each image flows into the next like a storyboard.
No AI feel — images follow the narrative arc.
Output: raw_video.mp4 (no audio)
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

SECONDS_PER_IMG = 8
MAX_IMAGES      = 40
POLLINATIONS    = "https://image.pollinations.ai/prompt"

# Core anime style — consistent across ALL images so they feel like one story
STYLE_CORE = (
    "anime style, Studio Ghibli inspired, highly detailed illustration, "
    "cinematic composition, vibrant but coherent color palette, "
    "professional manga art, no text, no watermark, no UI elements, "
    "4k resolution, dramatic lighting"
)

# Ken Burns effects — ordered so each leads naturally into the next
KB_SEQUENCE = [
    # Pull back to reveal
    "zoompan=z='if(lte(zoom,1.0),1.15,max(1.001,zoom-0.002))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={d}:s={w}x{h}:fps={fps}",
    # Push in for intensity
    "zoompan=z='min(zoom+0.002,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={d}:s={w}x{h}:fps={fps}",
    # Pan left — like a camera following action
    "zoompan=z='1.08':x='if(lte(on,1),iw*0.1,min(iw*0.2,x+0.8))':y='ih/2-(ih/zoom/2)':d={d}:s={w}x{h}:fps={fps}",
    # Pan right — continuation of movement
    "zoompan=z='1.08':x='if(lte(on,1),iw*0.2,max(0,x-0.8))':y='ih/2-(ih/zoom/2)':d={d}:s={w}x{h}:fps={fps}",
    # Tilt up — building to climax
    "zoompan=z='1.08':x='iw/2-(iw/zoom/2)':y='if(lte(on,1),ih*0.2,max(0,y-0.6))':d={d}:s={w}x{h}:fps={fps}",
    # Tilt down — aftermath, resolution
    "zoompan=z='1.08':x='iw/2-(iw/zoom/2)':y='if(lte(on,1),0,min(ih*0.15,y+0.6))':d={d}:s={w}x{h}:fps={fps}",
]

# ══════════════════════════════════════════════════════════════════
#  AUDIO
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
#  STORY ANALYSIS — Extract narrative arc from script
# ══════════════════════════════════════════════════════════════════

def clean_script(text: str) -> str:
    """Remove stage directions, keep only spoken words."""
    text = re.sub(r'\[.*?\]', '', text, flags=re.DOTALL)
    text = re.sub(r'---.*?---', '', text, flags=re.DOTALL)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def extract_story_beats(text: str, n: int) -> list:
    """
    Split script into N story beats.
    Each beat captures the emotional/visual moment of that part.
    Returns list of dicts with: text, position, emotion, setting
    """
    clean = clean_script(text)
    sentences = re.split(r'(?<=[.!?])\s+', clean)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 8]

    if not sentences:
        sentences = [clean]

    # Group into N chunks
    chunk_size = max(1, len(sentences) // n)
    chunks = []
    for i in range(0, len(sentences), chunk_size):
        chunks.append(' '.join(sentences[i:i+chunk_size])[:400])

    while len(chunks) < n:
        chunks.append(chunks[-1] if chunks else "dramatic scene")
    chunks = chunks[:n]

    # Assign narrative position and emotion to each beat
    beats = []
    for i, chunk in enumerate(chunks):
        position = i / max(1, n - 1)  # 0.0 to 1.0

        # Narrative arc: setup → conflict → climax → resolution
        if position < 0.15:
            arc = "opening"
            emotion = "curiosity, wonder, calm"
            camera = "wide establishing shot"
        elif position < 0.35:
            arc = "setup"
            emotion = "intrigue, unease building"
            camera = "medium shot, observational"
        elif position < 0.55:
            arc = "rising tension"
            emotion = "anxiety, urgency, chaos"
            camera = "close-up, intense"
        elif position < 0.75:
            arc = "climax"
            emotion = "shock, revelation, peak drama"
            camera = "dramatic angle, extreme close-up"
        elif position < 0.90:
            arc = "falling action"
            emotion = "aftermath, reflection, emotion"
            camera = "medium wide, atmospheric"
        else:
            arc = "resolution"
            emotion = "conclusion, bittersweet, lingering"
            camera = "wide shot, fading out"

        # Extract visual keywords from this chunk
        stopwords = {
            'the','a','an','and','or','but','in','on','at','to','for',
            'of','with','it','is','was','be','are','were','i','you',
            'he','she','they','we','my','your','just','that','this',
            'have','had','about','from','not','so','then','when','what',
            'said','like','all','me','us','its','been','fam','gonna'
        }
        words = re.findall(r'\b[a-zA-Z]{4,}\b', chunk.lower())
        keywords = [w for w in words if w not in stopwords]

        # Frequency count
        freq = {}
        for w in keywords:
            freq[w] = freq.get(w, 0) + 1
        top_keywords = sorted(freq, key=freq.get, reverse=True)[:4]

        # Check for ALL CAPS words — these are emotional peaks
        caps_words = re.findall(r'\b[A-Z]{3,}\b', chunk)
        has_peak = len(caps_words) > 0

        beats.append({
            "text": chunk,
            "position": position,
            "arc": arc,
            "emotion": emotion,
            "camera": camera,
            "keywords": top_keywords,
            "has_peak": has_peak,
            "index": i,
            "total": n
        })

    print(f"[INFO] Extracted {len(beats)} story beats")
    return beats


# ══════════════════════════════════════════════════════════════════
#  PROMPT BUILDER — Coherent visual story
# ══════════════════════════════════════════════════════════════════

def build_story_prompt(beat: dict, prev_beat: dict = None) -> str:
    """
    Build a Pollinations prompt that:
    1. Matches the current story moment
    2. Visually continues from the previous image
    3. Maintains consistent art style throughout
    """
    keywords = ', '.join(beat['keywords']) if beat['keywords'] else 'dramatic scene'
    arc      = beat['arc']
    emotion  = beat['emotion']
    camera   = beat['camera']
    position = beat['position']
    has_peak = beat['has_peak']

    # Build continuity cue from previous beat
    continuity = ""
    if prev_beat and prev_beat['keywords']:
        prev_kw = prev_beat['keywords'][0] if prev_beat['keywords'] else ""
        if prev_kw:
            continuity = f"continuation from previous scene showing {prev_kw}, "

    # Intensity modifier
    intensity = "extreme dramatic intensity, " if has_peak else ""

    # Lighting based on arc position
    if position < 0.2:
        lighting = "soft morning light, hopeful atmosphere"
    elif position < 0.5:
        lighting = "dramatic side lighting, tension in the air"
    elif position < 0.75:
        lighting = "harsh contrast lighting, neon highlights, chaos"
    else:
        lighting = "golden hour light, emotional depth, cinematic glow"

    # Scene subject based on keywords
    subject = f"anime character in a scene about {keywords}"

    prompt = (
        f"{intensity}{continuity}"
        f"{subject}, "
        f"{arc} moment, "
        f"emotion: {emotion}, "
        f"{camera}, "
        f"{lighting}, "
        f"{STYLE_CORE}"
    )

    return prompt


# ══════════════════════════════════════════════════════════════════
#  IMAGE GENERATION
# ══════════════════════════════════════════════════════════════════

def generate_image(prompt: str, index: int, retries: int = 3) -> Path:
    """Generate one image from Pollinations."""
    out_dir = Path("ai_images")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"scene_{index:03d}.jpg"

    encoded = requests.utils.quote(prompt)
    # Use consistent seed offset per scene for style coherence
    seed = 42000 + (index * 137)  # Deterministic but varied

    url = (
        f"{POLLINATIONS}/{encoded}"
        f"?width={VIDEO_W}&height={VIDEO_H}"
        f"&model=flux"
        f"&seed={seed}"
        f"&nologo=true"
        f"&enhance=true"
    )

    for attempt in range(retries):
        try:
            print(f"  [IMG {index+1}] Generating scene ({beat_label(index)})...")
            r = requests.get(url, timeout=90, stream=True)
            if r.status_code == 200 and len(r.content) > 5000:
                with open(out_path, "wb") as f:
                    f.write(r.content)
                size_kb = out_path.stat().st_size / 1024
                print(f"  [IMG {index+1}] ✅ {size_kb:.0f}KB")
                return out_path
            else:
                print(f"  [IMG {index+1}] Attempt {attempt+1} failed (status {r.status_code})")
                time.sleep(4)
        except Exception as e:
            print(f"  [IMG {index+1}] Error: {e}")
            time.sleep(4)

    # Fallback solid frame
    print(f"  [IMG {index+1}] ⚠️ Using fallback frame")
    fallback_colors = ["#1a0a2e", "#0d1b2a", "#1b1b2f", "#16213e", "#0f3460"]
    color = fallback_colors[index % len(fallback_colors)]
    fallback = out_dir / f"fallback_{index:03d}.png"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"color=c={color}:size={VIDEO_W}x{VIDEO_H}:rate=1",
        "-frames:v", "1", str(fallback)
    ], capture_output=True)
    return fallback


def beat_label(i: int) -> str:
    labels = ["opening", "setup", "tension", "climax", "aftermath", "resolution"]
    return labels[i % len(labels)]


def generate_all_images(beats: list) -> list:
    """Generate all images maintaining story continuity."""
    image_paths = []
    prev_beat = None

    for i, beat in enumerate(beats):
        prompt = build_story_prompt(beat, prev_beat)
        img_path = generate_image(prompt, i)
        image_paths.append(str(img_path))
        prev_beat = beat
        time.sleep(2)  # Avoid rate limiting

    print(f"[INFO] Generated {len(image_paths)} story images")
    return image_paths


# ══════════════════════════════════════════════════════════════════
#  ANIMATION — Sequential Ken Burns that tells a story
# ══════════════════════════════════════════════════════════════════

def animate_image(img_path: str, out_path: str, duration: float, seq_index: int):
    """
    Animate image with Ken Burns effect.
    seq_index determines which effect — they follow a narrative sequence
    so the camera movement feels intentional, not random.
    """
    frames = int(duration * FPS)
    effect = KB_SEQUENCE[seq_index % len(KB_SEQUENCE)]
    zoompan = effect.format(d=frames, w=VIDEO_W, h=VIDEO_H, fps=FPS)

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", img_path,
        "-vf", (
            f"scale={VIDEO_W*2}:{VIDEO_H*2}:"
            f"force_original_aspect_ratio=increase,"
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
        # Simple fallback
        cmd2 = [
            "ffmpeg", "-y", "-loop", "1", "-i", img_path,
            "-vf", f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=increase,crop={VIDEO_W}:{VIDEO_H},setsar=1",
            "-t", str(duration), "-r", str(FPS),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-an", out_path
        ]
        subprocess.run(cmd2, capture_output=True, check=True)


def animate_all(image_paths: list, audio_duration: float) -> list:
    """
    Animate all images. Camera movements follow narrative sequence —
    pull back → push in → pan left → pan right → tilt up → tilt down
    This creates a sense of visual progression matching the story.
    """
    anim_dir = Path("animated_clips")
    anim_dir.mkdir(exist_ok=True)
    animated = []

    n = len(image_paths)
    dur_per_img = audio_duration / n

    print(f"[INFO] Animating {n} images @ {dur_per_img:.1f}s each...")
    print("[INFO] Camera sequence: pull-back → push-in → pan-left → pan-right → tilt-up → tilt-down")

    for i, img_path in enumerate(image_paths):
        out = str(anim_dir / f"anim_{i:03d}.mp4")
        try:
            animate_image(img_path, out, dur_per_img, i)
            animated.append(out)
            effect_name = ["pull-back", "push-in", "pan-left", "pan-right", "tilt-up", "tilt-down"]
            print(f"  [ANIM {i+1}/{n}] ✅ {effect_name[i % 6]} effect")
        except Exception as e:
            print(f"  [ANIM {i+1}/{n}] ⚠️ Failed: {e}")

    return animated


# ══════════════════════════════════════════════════════════════════
#  CROSSFADE CONCAT — Smooth dissolve between scenes
# ══════════════════════════════════════════════════════════════════

def concat_with_crossfade(clip_paths: list, dur_per_clip: float) -> str:
    """
    Concatenate clips with crossfade dissolve.
    0.5s crossfade between each clip — feels like a real film cut.
    """
    if len(clip_paths) == 1:
        return clip_paths[0]

    crossfade = 0.5  # seconds
    output = "story_video.mp4"

    # Build complex filtergraph for crossfade between all clips
    n = len(clip_paths)

    # For simplicity and reliability, use concat with xfade filter
    # Build input args
    input_args = []
    for p in clip_paths:
        input_args += ["-i", p]

    # Build xfade filter chain
    filter_parts = []
    offset = dur_per_clip - crossfade

    # First xfade: [0][1]
    filter_parts.append(
        f"[0:v][1:v]xfade=transition=dissolve:duration={crossfade}:offset={offset:.3f}[v01]"
    )

    for i in range(2, n):
        prev_label = f"v{str(i-1).zfill(2)}{str(i).zfill(2)}" if i > 2 else "v01"
        if i == 2:
            prev_label = "v01"
        next_offset = offset + (i - 1) * (dur_per_clip - crossfade)
        curr_label = f"vout{i}"
        filter_parts.append(
            f"[{prev_label}][{i}:v]xfade=transition=dissolve:duration={crossfade}:offset={next_offset:.3f}[{curr_label}]"
        )

    if n == 2:
        final_label = "v01"
    else:
        final_label = f"vout{n-1}"

    filter_str = ";".join(filter_parts)

    cmd = (
        ["ffmpeg", "-y"]
        + input_args
        + [
            "-filter_complex", filter_str,
            "-map", f"[{final_label}]",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-an",
            output
        ]
    )

    print("[INFO] Applying crossfade dissolves between scenes...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print("[WARN] Crossfade failed, using simple concat...")
        # Fallback: simple concat
        concat_file = Path("concat_list.txt")
        with open(concat_file, "w") as f:
            for p in clip_paths:
                f.write(f"file '{p}'\n")
        cmd2 = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_file), "-c", "copy", output
        ]
        subprocess.run(cmd2, capture_output=True, check=True)

    print(f"[INFO] Story video assembled → {output}")
    return output


# ══════════════════════════════════════════════════════════════════
#  FINAL TRIM
# ══════════════════════════════════════════════════════════════════

def trim_to_duration(video_path: str, duration: float, output: str):
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
    print(f"[✓] Final video → '{output}' ({size_mb:.1f} MB, {duration:.1f}s)")


# ══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════

def main():
    print("=" * 62)
    print("  Brainrot Anime Story Engine")
    print("  Coherent narrative visuals · Smooth transitions")
    print("=" * 62)

    if not INPUT_SCRIPT.exists():
        sys.exit("[ERROR] script.txt not found")
    script_text = INPUT_SCRIPT.read_text(encoding="utf-8")
    print(f"[INFO] Script loaded ({len(script_text)} chars)")

    if not INPUT_AUDIO.exists():
        sys.exit("[ERROR] output_voice.wav not found")
    audio_duration = get_audio_duration(str(INPUT_AUDIO))

    # Calculate images needed
    n_images = min(MAX_IMAGES, max(4, int(audio_duration / SECONDS_PER_IMG)))
    dur_per_img = audio_duration / n_images
    print(f"[INFO] Generating {n_images} story images @ {dur_per_img:.1f}s each")

    # Step 1: Analyse story
    print("\n[STEP 1] Analysing narrative arc...")
    beats = extract_story_beats(script_text, n_images)

    # Step 2: Generate images
    print("\n[STEP 2] Generating coherent story images...")
    image_paths = generate_all_images(beats)

    # Step 3: Animate
    print("\n[STEP 3] Animating with narrative camera sequence...")
    animated = animate_all(image_paths, audio_duration)

    if not animated:
        sys.exit("[ERROR] No animated clips")

    # Step 4: Crossfade concat
    print("\n[STEP 4] Assembling story with crossfade dissolves...")
    story_video = concat_with_crossfade(animated, dur_per_img)

    # Step 5: Trim
    print("\n[STEP 5] Final trim to exact audio length...")
    trim_to_duration(story_video, audio_duration, str(OUTPUT_VIDEO))

    print("\n" + "=" * 62)
    print("  [✓] DONE — raw_video.mp4 ready")
    print("=" * 62)


if __name__ == "__main__":
    main()
