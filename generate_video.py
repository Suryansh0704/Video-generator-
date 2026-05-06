"""
generate_video.py — Kinetic Typography Audio-Reactive Engine
=============================================================
Professional viral reel generator — zero stock footage.
Every frame procedurally generated from audio + script.

Features:
  - Muted Luxury background palette
  - Audio-reactive oscilloscope waveform (librosa)
  - Word-level timing from edge-tts WordBoundary events
  - 5 kinetic entrance animations (fly-in, scale, rotate, etc.)
  - Smart accent colors + ALL CAPS emphasis
  - Global Ken Burns zoom 1.0x → 1.15x
  - Emoji keyword injection with pulse animation
  - Glow/bloom effect on waveform
  - 100% headless — runs on GitHub Actions

Output: raw_video.mp4 (1080x1920, 30fps, no audio)
"""

import os
import re
import sys
import glob
import math
import random
import shutil
import zipfile
import asyncio
import subprocess
import requests
from pathlib import Path

import numpy as np
import cv2

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except ImportError:
    sys.exit("[ERROR] Pillow not installed")

try:
    import librosa
except ImportError:
    sys.exit("[ERROR] librosa not installed")

try:
    import edge_tts
except ImportError:
    sys.exit("[ERROR] edge-tts not installed")

# ══════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════════════════════════

W, H            = 1080, 1920
FPS             = 30
VOICE           = "en-GB-RyanNeural"
PITCH           = "-2Hz"
RATE            = "+15%"

INPUT_SCRIPT    = Path("script.txt")
INPUT_AUDIO     = Path("output_voice.wav")
AUDIO_MP3       = Path("output_raw.mp3")
OUTPUT_VIDEO    = Path("raw_video.mp4")
FONT_PATH       = Path("Montserrat-Bold.ttf")
FONT_URL        = "https://github.com/google/fonts/raw/main/ofl/montserrat/static/Montserrat-Bold.ttf"

# Muted Luxury palette — (BG_BGR, ACCENT_BGR, WAVEFORM_BGR)
PALETTES = [
    ((9,  14, 22),   (50, 180, 255),  (0,  255, 180)),  # Espresso + Gold + Cyan
    ((30, 28, 28),   (80, 200, 255),  (0,  220, 160)),  # Charcoal + Amber + Teal
    ((20, 30, 15),   (0,  220, 255),  (100, 255, 80)),  # Forest + Yellow + Lime
    ((35, 15, 20),   (200, 100, 255), (180, 50,  255)), # Deep Purple + Pink + Violet
    ((15, 20, 30),   (50,  255, 200), (0,  180, 255)),  # Midnight + Mint + Blue
]

# Caption zones — vertical positions
CAP_Y_PRIMARY   = int(H * 0.22)     # Main word position
CAP_Y_SECONDARY = int(H * 0.32)

# Waveform zone — bottom 25%
WAVE_Y_BASE     = int(H * 0.80)
WAVE_HEIGHT     = int(H * 0.18)
WAVE_POINTS     = 220

# Typography
FONT_SIZE_NORMAL = 110
FONT_SIZE_CAPS   = 135
FONT_SIZE_SMALL  = 85

# Animation
ANIM_FRAMES     = 8      # 8 frames = ~267ms entrance
ELASTIC_K       = 2.8    # Elastic overshoot strength

# Ken Burns
KB_START        = 1.0
KB_END          = 1.15

# Emoji keywords
EMOJI_KEYWORDS = {
    "fire": "🔥", "love": "❤️", "star": "⭐",
    "cat": "🐱", "money": "💰", "brain": "🧠",
    "aura": "✨", "win": "🏆", "shock": "😱",
    "ghost": "👻", "crown": "👑", "rocket": "🚀"
}

# ══════════════════════════════════════════════════════════════════
#  FONT DOWNLOAD
# ══════════════════════════════════════════════════════════════════

def ensure_font():
    if FONT_PATH.exists():
        return
    print(f"[FONT] Downloading Montserrat Bold...")
    try:
        r = requests.get(FONT_URL, timeout=30)
        if r.status_code == 200:
            FONT_PATH.write_bytes(r.content)
            print(f"[FONT] Downloaded ({FONT_PATH.stat().st_size // 1024}KB)")
            return
    except Exception as e:
        print(f"[FONT] Download failed: {e}")

    # Fallback — find any system TTF
    fallbacks = glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)
    bold = [f for f in fallbacks if "bold" in f.lower() or "Bold" in f]
    chosen = bold[0] if bold else (fallbacks[0] if fallbacks else None)
    if chosen:
        shutil.copy(chosen, str(FONT_PATH))
        print(f"[FONT] Using system font: {chosen}")
    else:
        print("[WARN] No TTF found — using PIL default")


def get_font(size: int) -> ImageFont.FreeTypeFont:
    if FONT_PATH.exists():
        return ImageFont.truetype(str(FONT_PATH), size)
    return ImageFont.load_default()


# ══════════════════════════════════════════════════════════════════
#  AUDIO DOWNLOAD
# ══════════════════════════════════════════════════════════════════

def download_audio():
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        if INPUT_AUDIO.exists():
            return
        sys.exit("[ERROR] GH_TOKEN not set and no local audio")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    }
    res = requests.get(
        "https://api.github.com/repos/Suryansh0704/Audio-generator-/actions/artifacts",
        headers=headers
    )
    artifacts = res.json().get("artifacts", [])
    if not artifacts:
        sys.exit("[ERROR] No artifacts in Audio-generator-")

    latest = artifacts[0]
    print(f"[AUDIO] Downloading {latest['name']}...")
    r = requests.get(latest["archive_download_url"], headers=headers)
    with open("audio.zip", "wb") as f:
        f.write(r.content)
    with zipfile.ZipFile("audio.zip", "r") as z:
        z.extractall("audio_extracted")

    wavs = (glob.glob("audio_extracted/**/*.wav", recursive=True)
            or glob.glob("audio_extracted/*.wav"))
    if wavs:
        shutil.copy(wavs[0], str(INPUT_AUDIO))
        print(f"[AUDIO] Ready ({INPUT_AUDIO.stat().st_size // 1024}KB)")
    else:
        sys.exit("[ERROR] No WAV in artifact")


# ══════════════════════════════════════════════════════════════════
#  SCRIPT CLEANING
# ══════════════════════════════════════════════════════════════════

def clean_script(raw: str) -> str:
    text = re.sub(r'\[.*?\]', '', raw, flags=re.DOTALL)
    text = re.sub(r'-{2,}.*?-{2,}', '', text)
    text = re.sub(r'#\w+', '', text)
    text = re.sub(r'https?://\S+', '', text)
    text = text.encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[\/\\@#\$%\^&\*\(\)\[\]\{\}\|<>~`_+=]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def detect_emoji_keyword(text: str) -> tuple:
    """Return (keyword, emoji) if any emoji keyword found in text."""
    lower = text.lower()
    for kw, emoji in EMOJI_KEYWORDS.items():
        if kw in lower:
            return kw, emoji
    return None, None


# ══════════════════════════════════════════════════════════════════
#  EDGE-TTS WITH WORD TIMESTAMPS
# ══════════════════════════════════════════════════════════════════

async def generate_tts_with_timing(text: str) -> list:
    """
    Generate speech and capture word-level boundary events.
    Returns list of dicts: {word, start_sec, duration_sec}
    Saves audio to AUDIO_MP3.
    """
    communicate = edge_tts.Communicate(text=text, voice=VOICE,
                                        pitch=PITCH, rate=RATE)
    words       = []
    audio_data  = bytearray()

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            words.append({
                "word":     chunk["text"],
                "start":    chunk["offset"] / 10_000_000,      # 100ns → seconds
                "duration": chunk["duration"] / 10_000_000
            })

    AUDIO_MP3.write_bytes(bytes(audio_data))
    print(f"[TTS] Generated {len(words)} word timestamps | "
          f"Audio: {len(audio_data)//1024}KB")
    return words


def mp3_to_wav():
    """Convert MP3 output to WAV for librosa."""
    if INPUT_AUDIO.exists():
        return
    cmd = [
        "ffmpeg", "-y", "-i", str(AUDIO_MP3),
        "-ar", "24000", "-ac", "1", str(INPUT_AUDIO)
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    print(f"[TTS] WAV ready ({INPUT_AUDIO.stat().st_size // 1024}KB)")


# ══════════════════════════════════════════════════════════════════
#  AUDIO ANALYSIS
# ══════════════════════════════════════════════════════════════════

def analyse_audio(path: str, n_frames: int) -> tuple:
    """Returns (rms_per_frame, waveform_per_frame, duration)."""
    print("[AUDIO] Analysing waveform...")
    y, sr    = librosa.load(str(path), sr=None, mono=True)
    duration = len(y) / sr
    spf      = len(y) / n_frames

    rms_arr  = np.zeros(n_frames, dtype=np.float32)
    wave_arr = np.zeros((n_frames, WAVE_POINTS), dtype=np.float32)

    for i in range(n_frames):
        s = int(i * spf)
        e = min(int(s + spf), len(y))
        chunk = y[s:e]
        if len(chunk) == 0:
            continue
        rms_arr[i] = float(np.sqrt(np.mean(chunk ** 2)))
        if len(chunk) >= WAVE_POINTS:
            idx = np.linspace(0, len(chunk)-1, WAVE_POINTS).astype(int)
            wave_arr[i] = chunk[idx]
        else:
            wave_arr[i, :len(chunk)] = chunk

    mx = rms_arr.max()
    if mx > 0:
        rms_arr /= mx

    print(f"[AUDIO] Duration: {duration:.2f}s | Frames: {n_frames}")
    return rms_arr, wave_arr, duration


# ══════════════════════════════════════════════════════════════════
#  EASING FUNCTIONS
# ══════════════════════════════════════════════════════════════════

def elastic_out(t: float) -> float:
    """Elastic overshoot — snaps past target and settles."""
    if t <= 0: return 0.0
    if t >= 1: return 1.0
    return 1 + (2 ** (-10 * t)) * math.sin((t - 0.075) * (2 * math.pi) / 0.3)


def ease_out_back(t: float) -> float:
    """Overshoots and comes back — bouncy pop feel."""
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (t - 1)**3 + c1 * (t - 1)**2


def ease_out_quad(t: float) -> float:
    return 1 - (1 - t) ** 2


# ══════════════════════════════════════════════════════════════════
#  WORD RENDERING (PIL)
# ══════════════════════════════════════════════════════════════════

def render_word_image(word: str, font_size: int,
                      color: tuple) -> Image.Image:
    """Render a single word to a transparent PIL image."""
    font = get_font(font_size)
    # Measure
    tmp  = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(tmp)
    bbox = draw.textbbox((0, 0), word, font=font)
    tw   = bbox[2] - bbox[0] + 20
    th   = bbox[3] - bbox[1] + 20

    img  = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Shadow
    draw.text((4, 4), word, font=font, fill=(0, 0, 0, 160))
    # Main text (PIL uses RGB, convert BGR→RGB)
    rgb  = (color[2], color[1], color[0])
    draw.text((2, 2), word, font=font, fill=rgb + (255,))

    return img


# ══════════════════════════════════════════════════════════════════
#  5 KINETIC ENTRANCE ANIMATIONS
# ══════════════════════════════════════════════════════════════════

ANIM_TYPES = ["fly_left", "fly_right", "fly_top", "fly_bottom", "scale_up"]


def get_animated_state(anim_type: str, frame_in_anim: int,
                       total_anim: int, img_w: int, img_h: int,
                       target_x: int, target_y: int) -> tuple:
    """
    Returns (x, y, scale, alpha, angle) for this animation frame.
    frame_in_anim: 0..total_anim-1 (0=start, total_anim-1=settled)
    """
    t = min(1.0, frame_in_anim / max(1, total_anim - 1))

    if anim_type == "fly_left":
        e    = elastic_out(t)
        x    = int(-img_w + e * (target_x + img_w))
        return (x, target_y, 1.0, min(1.0, t * 3), 0)

    elif anim_type == "fly_right":
        e    = elastic_out(t)
        x    = int(W + (e - 1) * (W - target_x))
        return (x, target_y, 1.0, min(1.0, t * 3), 0)

    elif anim_type == "fly_top":
        e    = elastic_out(t)
        y    = int(-img_h + e * (target_y + img_h))
        return (target_x, y, 1.0, min(1.0, t * 3), 0)

    elif anim_type == "fly_bottom":
        e    = elastic_out(t)
        y    = int(H + (e - 1) * (H - target_y))
        return (target_x, y, 1.0, min(1.0, t * 3), 0)

    elif anim_type == "scale_up":
        e     = ease_out_back(t)
        scale = 0.2 + e * 0.9          # 0.2 → 1.1 → 1.0
        scale = max(0.1, min(1.15, scale))
        alpha = min(1.0, t * 4)
        return (target_x, target_y, scale, alpha, 0)

    # Fallback
    return (target_x, target_y, 1.0, 1.0, 0)


# ══════════════════════════════════════════════════════════════════
#  WAVEFORM RENDERER WITH GLOW
# ══════════════════════════════════════════════════════════════════

def draw_waveform_glow(canvas: np.ndarray, wave: np.ndarray,
                       rms: float, accent_bgr: tuple) -> None:
    """Draw oscilloscope with multi-pass glow effect."""
    amp   = WAVE_HEIGHT * (0.2 + rms * 0.8)
    xs    = np.linspace(60, W - 60, WAVE_POINTS).astype(int)
    kern  = np.ones(7) / 7
    ws    = np.convolve(wave, kern, mode='same')
    ys    = np.clip((WAVE_Y_BASE - ws * amp).astype(int), 10, H - 10)
    pts   = np.stack([xs, ys], axis=1).reshape(-1, 1, 2)

    # Glow passes — progressively thinner and brighter
    glow_color = tuple(max(0, int(c * 0.4)) for c in accent_bgr)
    for thickness, color, alpha in [
        (18, glow_color, 0.3),
        (10, glow_color, 0.5),
        (5,  accent_bgr, 0.8),
        (2,  (255, 255, 255), 1.0)
    ]:
        overlay = canvas.copy()
        cv2.polylines(overlay, [pts], False, color, thickness, cv2.LINE_AA)
        cv2.addWeighted(overlay, alpha, canvas, 1 - alpha, 0, canvas)

    # Peak dot
    peak_i = int(np.argmax(np.abs(ws)))
    cv2.circle(canvas, (int(xs[peak_i]), int(ys[peak_i])),
               8, (255, 255, 255), -1)
    cv2.circle(canvas, (int(xs[peak_i]), int(ys[peak_i])),
               14, accent_bgr, 2)


# ══════════════════════════════════════════════════════════════════
#  EMOJI PULSE
# ══════════════════════════════════════════════════════════════════

def render_emoji_text(emoji: str, frame: int,
                      canvas_pil: Image.Image) -> None:
    """Render emoji as unicode text with pulsing scale."""
    try:
        pulse = 1.0 + 0.08 * math.sin(frame * 0.15)
        size  = int(90 * pulse)
        font  = get_font(size)
        draw  = ImageDraw.Draw(canvas_pil)
        # Place in top-right corner
        x, y  = W - 140, 120
        draw.text((x, y), emoji, font=font, fill=(255, 255, 255, 200))
    except Exception:
        pass  # Skip emoji if font doesn't support it


# ══════════════════════════════════════════════════════════════════
#  VIGNETTE
# ══════════════════════════════════════════════════════════════════

def build_vignette() -> np.ndarray:
    xs = np.linspace(-1, 1, W)
    ys = np.linspace(-1, 1, H)
    X, Y = np.meshgrid(xs, ys)
    dist = np.sqrt(X**2 + Y**2)
    mask = 1.0 - np.clip(dist / dist.max() * 0.65, 0, 1)
    return mask.reshape(H, W, 1).astype(np.float32)


# ══════════════════════════════════════════════════════════════════
#  WORD TIMELINE BUILDER
# ══════════════════════════════════════════════════════════════════

def build_timeline(word_timestamps: list, duration: float,
                   fps: int, accent_bgr: tuple) -> list:
    """
    Build per-word rendering data:
    {word, start_frame, end_frame, anim_type, color, font_size,
     target_x, target_y, img (PIL)}
    """
    timeline = []
    total_frames = int(duration * fps)
    # Assign accent color to ~10% of words and all CAPS
    n = len(word_timestamps)
    accent_indices = set(random.sample(range(n), max(1, n // 10)))

    # Y positions alternate for visual rhythm
    y_positions = [CAP_Y_PRIMARY, CAP_Y_SECONDARY,
                   CAP_Y_PRIMARY - 80, CAP_Y_SECONDARY + 60]

    anim_cycle = ANIM_TYPES.copy()
    random.shuffle(anim_cycle)

    for i, wt in enumerate(word_timestamps):
        word     = re.sub(r'[^a-zA-Z0-9\'\-!?.,]', '', wt["word"])
        if not word:
            continue

        is_caps  = bool(re.search(r'[A-Z]{2,}', wt["word"]))
        use_acc  = is_caps or (i in accent_indices)

        # Color — BGR
        if use_acc:
            color = accent_bgr
        else:
            color = random.choice([
                (255, 255, 255),   # White
                (240, 240, 220),   # Cream
                (255, 255, 255),   # White (more common)
            ])

        font_size = FONT_SIZE_CAPS if is_caps else (
            FONT_SIZE_SMALL if len(word) > 10 else FONT_SIZE_NORMAL
        )

        anim_type = anim_cycle[i % len(anim_cycle)]

        # Pre-render word image
        img = render_word_image(word.upper() if is_caps else word,
                                font_size, color)

        # Center word horizontally, vary Y for rhythm
        tx = (W - img.width) // 2
        ty = y_positions[i % len(y_positions)]

        sf = int(wt["start"] * fps)
        ef = min(int((wt["start"] + wt["duration"]) * fps), total_frames)
        if ef <= sf:
            ef = sf + int(0.3 * fps)

        timeline.append({
            "word":       word,
            "is_caps":    is_caps,
            "start":      sf,
            "end":        ef,
            "anim":       anim_type,
            "color":      color,
            "font_size":  font_size,
            "tx":         tx,
            "ty":         ty,
            "img":        img,
        })

    return timeline


# ══════════════════════════════════════════════════════════════════
#  KEN BURNS
# ══════════════════════════════════════════════════════════════════

def apply_ken_burns(frame: np.ndarray, idx: int,
                    total: int) -> np.ndarray:
    t     = idx / max(1, total - 1)
    scale = KB_START + t * (KB_END - KB_START)
    if abs(scale - 1.0) < 0.002:
        return frame
    nw = int(W * scale)
    nh = int(H * scale)
    big = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
    ox  = (nw - W) // 2
    oy  = (nh - H) // 2
    return big[oy:oy+H, ox:ox+W]


# ══════════════════════════════════════════════════════════════════
#  COMPOSITE WORD ONTO CANVAS
# ══════════════════════════════════════════════════════════════════

def composite_word(canvas_bgr: np.ndarray, entry: dict,
                   frame_idx: int, emoji: str) -> None:
    """
    Compute animation state for this frame and composite word image.
    """
    sf    = entry["start"]
    ef    = entry["end"]
    img   = entry["img"]
    tx    = entry["tx"]
    ty    = entry["ty"]
    anim  = entry["anim"]

    if frame_idx < sf or frame_idx >= ef:
        return

    frame_in_anim = frame_idx - sf
    x, y, scale, alpha, angle = get_animated_state(
        anim, frame_in_anim, ANIM_FRAMES,
        img.width, img.height, tx, ty
    )

    # Scale the word image if needed
    if abs(scale - 1.0) > 0.01:
        nw = max(1, int(img.width * scale))
        nh = max(1, int(img.height * scale))
        disp = img.resize((nw, nh), Image.LANCZOS)
        # Re-center after scale
        x = tx + (img.width - nw) // 2
        y = ty + (img.height - nh) // 2
    else:
        disp = img

    alpha_val = int(alpha * 255)

    # Convert canvas to PIL for compositing
    canvas_rgb = cv2.cvtColor(canvas_bgr, cv2.COLOR_BGR2RGB)
    canvas_pil = Image.fromarray(canvas_rgb).convert("RGBA")

    # Adjust alpha channel of word image
    r, g, b, a = disp.split()
    a = a.point(lambda px: int(px * alpha_val / 255))
    disp = Image.merge("RGBA", (r, g, b, a))

    # Paste with bounds check
    px = max(-disp.width, min(W, x))
    py = max(-disp.height, min(H, y))
    canvas_pil.alpha_composite(disp, (px, py))

    # Emoji overlay (pulsing)
    if emoji and frame_idx == sf:  # Only check once
        render_emoji_text(emoji, frame_idx, canvas_pil)

    result = cv2.cvtColor(
        np.array(canvas_pil.convert("RGB")), cv2.COLOR_RGB2BGR
    )
    np.copyto(canvas_bgr, result)


# ══════════════════════════════════════════════════════════════════
#  CAPS FLASH
# ══════════════════════════════════════════════════════════════════

def apply_caps_flash(canvas: np.ndarray, intensity: float,
                     accent_bgr: tuple) -> np.ndarray:
    if intensity <= 0:
        return canvas
    overlay = np.full_like(canvas, accent_bgr, dtype=np.uint8)
    return cv2.addWeighted(canvas, 1.0 - intensity * 0.15,
                           overlay, intensity * 0.15, 0)


# ══════════════════════════════════════════════════════════════════
#  MAIN RENDER LOOP
# ══════════════════════════════════════════════════════════════════

def render_video(word_timeline: list, rms_arr: np.ndarray,
                 wave_arr: np.ndarray, duration: float,
                 palette: tuple, emoji: str) -> None:

    bg_bgr, accent_bgr, wave_bgr = palette
    n_frames  = len(rms_arr)
    vignette  = build_vignette()

    fourcc    = cv2.VideoWriter_fourcc(*'mp4v')
    temp_out  = "raw_temp.mp4"
    writer    = cv2.VideoWriter(temp_out, fourcc, FPS, (W, H))

    if not writer.isOpened():
        sys.exit("[ERROR] VideoWriter failed")

    print(f"[RENDER] {n_frames} frames | {duration:.1f}s | "
          f"BG={bg_bgr} | ACCENT={accent_bgr}")

    # Build frame→active_word lookup
    frame_words = {}
    for entry in word_timeline:
        for f in range(entry["start"], min(entry["end"], n_frames)):
            frame_words[f] = entry

    flash_cnt  = 0
    last_caps  = False
    log_step   = max(1, n_frames // 25)

    for i in range(n_frames):
        # Base background
        canvas = np.full((H, W, 3), bg_bgr, dtype=np.uint8)

        # Waveform with glow
        draw_waveform_glow(canvas, wave_arr[i], rms_arr[i], wave_bgr)

        # Subtle horizontal divider line above waveform
        div_y = WAVE_Y_BASE - 10
        cv2.line(canvas, (80, div_y), (W-80, div_y),
                 tuple(min(255, c+40) for c in bg_bgr), 1, cv2.LINE_AA)

        # Active word
        entry = frame_words.get(i)
        if entry:
            if entry["is_caps"] and not last_caps:
                flash_cnt = 6
            last_caps = entry["is_caps"] if entry else False
            composite_word(canvas, entry, i, emoji)
        else:
            last_caps = False

        # Flash on CAPS
        if flash_cnt > 0:
            intensity = flash_cnt / 6
            canvas = apply_caps_flash(canvas, intensity, accent_bgr)
            flash_cnt -= 1

        # Vignette
        cf = canvas.astype(np.float32) / 255.0 * vignette
        canvas = (cf * 255).clip(0, 255).astype(np.uint8)

        # Ken Burns
        canvas = apply_ken_burns(canvas, i, n_frames)

        writer.write(canvas)

        if i % log_step == 0:
            print(f"  [RENDER] {int(i/n_frames*100)}% ({i}/{n_frames})")

    writer.release()
    print("[RENDER] Done — re-encoding...")

    cmd = [
        "ffmpeg", "-y", "-i", temp_out,
        "-c:v", "libx264", "-preset", "fast",
        "-crf", "17", "-pix_fmt", "yuv420p", "-an",
        str(OUTPUT_VIDEO)
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[WARN] ffmpeg re-encode: {r.stderr[-200:]}")
        shutil.copy(temp_out, str(OUTPUT_VIDEO))
    else:
        Path(temp_out).unlink(missing_ok=True)

    size_mb = OUTPUT_VIDEO.stat().st_size / (1024*1024)
    print(f"[✓] Saved → {OUTPUT_VIDEO} ({size_mb:.1f}MB)")


# ══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════

def main():
    print("=" * 62)
    print("  Kinetic Typography Audio-Reactive Engine")
    print("  Procedural · Word-Sync · 5 Entrance Animations")
    print("=" * 62)

    ensure_font()

    # Download audio if needed
    if not INPUT_AUDIO.exists():
        download_audio()

    # Load script
    if not INPUT_SCRIPT.exists():
        sys.exit("[ERROR] script.txt not found")
    raw   = INPUT_SCRIPT.read_text(encoding="utf-8")
    clean = clean_script(raw)
    print(f"[INFO] Script: {len(clean.split())} words")

    # Detect emoji keyword
    _, emoji = detect_emoji_keyword(clean)
    if emoji:
        print(f"[INFO] Emoji detected: {emoji}")

    # Pick random palette
    palette = random.choice(PALETTES)
    print(f"[INFO] Palette: BG={palette[0]} ACCENT={palette[1]}")

    # Get audio duration
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(INPUT_AUDIO)
    ]
    duration = float(subprocess.run(cmd, capture_output=True,
                                    text=True).stdout.strip())
    n_frames = int(duration * FPS)
    print(f"[INFO] Duration: {duration:.2f}s | Frames: {n_frames}")

    # Generate TTS with word timestamps (if no audio yet)
    # If audio already exists from Audio-generator-, just parse timing from script
    print("[TTS] Computing word timestamps from script...")
    word_timestamps = asyncio.run(generate_tts_with_timing(clean))

    if not word_timestamps:
        # Fallback: evenly distribute words
        words = clean.split()
        dur_each = duration / len(words)
        word_timestamps = [
            {"word": w, "start": i*dur_each, "duration": dur_each}
            for i, w in enumerate(words)
        ]

    # Analyse audio
    rms_arr, wave_arr, _ = analyse_audio(str(INPUT_AUDIO), n_frames)

    # Build word timeline
    word_timeline = build_timeline(
        word_timestamps, duration, FPS, palette[1]
    )
    print(f"[INFO] Timeline: {len(word_timeline)} words | "
          f"Palette: {palette[0]}")

    # Render
    render_video(word_timeline, rms_arr, wave_arr,
                 duration, palette, emoji)

    print("\n" + "=" * 62)
    print("  [✓] DONE — raw_video.mp4 ready for editor")
    print("=" * 62)


if __name__ == "__main__":
    main()
