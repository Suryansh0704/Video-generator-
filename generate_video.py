"""
generate_voice.py — Kinetic Typography Engine v2
=================================================
Changes from v1:
  - 3-4 word phrase groups (not single words)
  - Minimum phrase hold time for readability
  - Pitch-black warm backgrounds (varies per video)
  - Word colors: warm cream / ivory / gold on dark
  - Fixed word rendering edge cases
  - Slower, more breathable pacing
"""

import os, re, sys, glob, math, random, shutil
import zipfile, asyncio, subprocess, requests
from pathlib import Path

import numpy as np
import cv2

try:
    from PIL import Image, ImageDraw, ImageFont
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
#  CONFIG
# ══════════════════════════════════════════════════════════════════

W, H         = 1080, 1920
FPS          = 30
VOICE        = "en-GB-RyanNeural"
PITCH        = "-2Hz"
RATE         = "+15%"

INPUT_SCRIPT = Path("script.txt")
INPUT_AUDIO  = Path("output_voice.wav")
AUDIO_MP3    = Path("output_raw.mp3")
OUTPUT_VIDEO = Path("raw_video.mp4")
FONT_PATH    = Path("Montserrat-Bold.ttf")
FONT_URL     = "https://github.com/google/fonts/raw/main/ofl/montserrat/static/Montserrat-Bold.ttf"

# ── Pitch-black backgrounds — warm undertones, varies each video ──
# Stored as BGR for OpenCV
BACKGROUNDS_BGR = [
    (5,  6,  8),    # Pure pitch — barely warm
    (8,  7,  10),   # Espresso black
    (6,  8,  9),    # Midnight black
    (7,  6,  11),   # Deep black with warmth
    (9,  8,  7),    # Charcoal black
]

# ── Word colors — warm tones readable on near-black ──
# BGR format (converted to RGB inside PIL render)
WORD_COLORS_BGR = [
    (210, 230, 245),   # Warm cream       → most common
    (220, 238, 255),   # Ivory white
    (200, 222, 240),   # Soft warm white
]

# Accent (ALL CAPS + 10% random) — gold/amber family
ACCENT_COLORS_BGR = [
    (60,  180, 255),   # Warm gold
    (80,  190, 240),   # Amber gold
    (50,  165, 220),   # Deep gold
    (90,  200, 255),   # Bright gold
]

# Waveform — neon that pops on dark (BGR)
WAVE_COLORS_BGR = [
    (180, 255, 50),    # Neon lime
    (255, 200, 0),     # Electric blue-white
    (200, 100, 255),   # Neon pink
    (0,   255, 200),   # Cyan
]

# ── Phrase grouping ───────────────────────────────────────────────
WORDS_PER_PHRASE    = 4       # Group 3-4 words together
MIN_PHRASE_HOLD_SEC = 1.2     # Min time a phrase stays on screen
PHRASE_GAP_FRAMES   = 8       # Blank frames between phrases

# ── Animation ────────────────────────────────────────────────────
ANIM_IN_FRAMES      = 8       # Entrance animation duration
ANIM_OUT_FRAMES     = 6       # Exit fade duration
PHRASE_Y_CENTER     = int(H * 0.38)   # Where phrases appear

# ── Waveform ─────────────────────────────────────────────────────
WAVE_Y_BASE         = int(H * 0.82)
WAVE_HEIGHT         = int(H * 0.14)
WAVE_POINTS         = 200

# ── Ken Burns ────────────────────────────────────────────────────
KB_START            = 1.0
KB_END              = 1.12

# ══════════════════════════════════════════════════════════════════
#  FONT
# ══════════════════════════════════════════════════════════════════

def ensure_font():
    if FONT_PATH.exists():
        return
    print("[FONT] Downloading Montserrat Bold...")
    try:
        r = requests.get(FONT_URL, timeout=30)
        if r.status_code == 200:
            FONT_PATH.write_bytes(r.content)
            print(f"[FONT] ✅ {FONT_PATH.stat().st_size//1024}KB")
            return
    except Exception as e:
        print(f"[FONT] Download failed: {e}")
    # System fallback
    ttfs = glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)
    bold = [f for f in ttfs if "bold" in f.lower() or "Bold" in f]
    chosen = bold[0] if bold else (ttfs[0] if ttfs else None)
    if chosen:
        shutil.copy(chosen, str(FONT_PATH))
        print(f"[FONT] System fallback: {chosen}")


def get_font(size: int):
    try:
        if FONT_PATH.exists():
            return ImageFont.truetype(str(FONT_PATH), size)
    except Exception:
        pass
    return ImageFont.load_default()


# ══════════════════════════════════════════════════════════════════
#  AUDIO DOWNLOAD
# ══════════════════════════════════════════════════════════════════

def download_audio():
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        if INPUT_AUDIO.exists():
            return
        sys.exit("[ERROR] GH_TOKEN not set")
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
        sys.exit("[ERROR] No artifacts found")
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
        print(f"[AUDIO] ✅ {INPUT_AUDIO.stat().st_size//1024}KB")
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


# ══════════════════════════════════════════════════════════════════
#  EDGE-TTS WITH WORD TIMESTAMPS
# ══════════════════════════════════════════════════════════════════

async def generate_tts_with_timing(text: str) -> list:
    communicate = edge_tts.Communicate(text=text, voice=VOICE,
                                       pitch=PITCH, rate=RATE)
    words      = []
    audio_data = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            w = chunk["text"].strip()
            if w:
                words.append({
                    "word":     w,
                    "start":    chunk["offset"] / 10_000_000,
                    "duration": chunk["duration"] / 10_000_000
                })
    AUDIO_MP3.write_bytes(bytes(audio_data))
    print(f"[TTS] {len(words)} word timestamps generated")
    return words


# ══════════════════════════════════════════════════════════════════
#  AUDIO ANALYSIS
# ══════════════════════════════════════════════════════════════════

def analyse_audio(path: str, n_frames: int) -> tuple:
    print("[AUDIO] Analysing...")
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
        rms_arr[i] = float(np.sqrt(np.mean(chunk**2)))
        if len(chunk) >= WAVE_POINTS:
            idx = np.linspace(0, len(chunk)-1, WAVE_POINTS).astype(int)
            wave_arr[i] = chunk[idx]
        else:
            wave_arr[i, :len(chunk)] = chunk
    mx = rms_arr.max()
    if mx > 0:
        rms_arr /= mx
    print(f"[AUDIO] Duration: {duration:.2f}s")
    return rms_arr, wave_arr, duration


# ══════════════════════════════════════════════════════════════════
#  PHRASE GROUPING — 3-4 words per phrase
# ══════════════════════════════════════════════════════════════════

def group_into_phrases(word_timestamps: list) -> list:
    """
    Group words into phrases of WORDS_PER_PHRASE.
    Each phrase has: text, start_sec, end_sec, has_caps
    Minimum hold time enforced.
    """
    phrases = []
    i = 0
    while i < len(word_timestamps):
        group = word_timestamps[i:i + WORDS_PER_PHRASE]
        text  = ' '.join(w["word"] for w in group)
        # Clean for display
        clean = re.sub(r'[^a-zA-Z0-9\'\-!?.,\s]', '', text).strip()
        if not clean:
            i += WORDS_PER_PHRASE
            continue

        start_sec = group[0]["start"]
        end_sec   = group[-1]["start"] + group[-1]["duration"]

        # Enforce minimum hold time
        if (end_sec - start_sec) < MIN_PHRASE_HOLD_SEC:
            end_sec = start_sec + MIN_PHRASE_HOLD_SEC

        has_caps = bool(re.search(r'[A-Z]{2,}', text))

        phrases.append({
            "text":      clean,
            "start_sec": start_sec,
            "end_sec":   end_sec,
            "has_caps":  has_caps,
            "raw_words": [w["word"] for w in group]
        })
        i += WORDS_PER_PHRASE

    print(f"[PHRASE] {len(phrases)} phrases from {len(word_timestamps)} words")
    return phrases


# ══════════════════════════════════════════════════════════════════
#  PHRASE IMAGE RENDERER
# ══════════════════════════════════════════════════════════════════

def render_phrase_image(text: str, has_caps: bool,
                        word_color: tuple,
                        accent_color: tuple) -> Image.Image:
    """
    Render a full phrase as a PIL RGBA image.
    ALL CAPS words rendered in accent color + larger.
    Other words in warm cream.
    Returns transparent image with the phrase text.
    """
    words        = text.split()
    NORMAL_SIZE  = 95
    CAPS_SIZE    = 118
    LINE_SPACING = 20
    PADDING      = 30

    # Pre-measure each word
    word_data = []
    for w in words:
        is_cap  = bool(re.search(r'[A-Z]{2,}', w))
        size    = CAPS_SIZE if is_cap else NORMAL_SIZE
        color   = accent_color if is_cap else word_color
        font    = get_font(size)
        # Use a dummy image to measure
        tmp_img = Image.new("RGBA", (1, 1))
        tmp_drw = ImageDraw.Draw(tmp_img)
        bbox    = tmp_drw.textbbox((0, 0), w, font=font)
        ww      = bbox[2] - bbox[0]
        wh      = bbox[3] - bbox[1]
        word_data.append({
            "text":  w,
            "font":  font,
            "color": color,
            "w":     ww,
            "h":     wh,
            "is_cap": is_cap
        })

    # Layout words into lines that fit within canvas width
    max_line_w = W - 120
    lines      = []
    cur_line   = []
    cur_w      = 0

    for wd in word_data:
        space_w = 18
        if cur_w + wd["w"] + space_w > max_line_w and cur_line:
            lines.append(cur_line)
            cur_line = [wd]
            cur_w    = wd["w"]
        else:
            cur_line.append(wd)
            cur_w += wd["w"] + space_w

    if cur_line:
        lines.append(cur_line)

    # Calculate total image size
    line_heights = [max(wd["h"] for wd in line) for line in lines]
    total_h = sum(line_heights) + LINE_SPACING * (len(lines) - 1) + PADDING * 2
    total_w = W - 60

    img  = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    y_off = PADDING
    for li, line in enumerate(lines):
        # Center this line
        line_w = sum(wd["w"] for wd in line) + 18 * (len(line) - 1)
        x_off  = (total_w - line_w) // 2
        lh     = line_heights[li]

        for wd in line:
            # Convert BGR → RGB for PIL
            rgb = (wd["color"][2], wd["color"][1], wd["color"][0])

            # Soft shadow
            draw.text((x_off + 3, y_off + 3), wd["text"],
                      font=wd["font"], fill=(0, 0, 0, 140))
            # Main word
            draw.text((x_off, y_off), wd["text"],
                      font=wd["font"], fill=rgb + (255,))

            # Gold underline for CAPS
            if wd["is_cap"]:
                ul_y = y_off + wd["h"] + 4
                acc_rgb = (accent_color[2], accent_color[1], accent_color[0])
                draw.line([(x_off, ul_y), (x_off + wd["w"], ul_y)],
                          fill=acc_rgb + (200,), width=3)

            x_off += wd["w"] + 18

        y_off += lh + LINE_SPACING

    return img


# ══════════════════════════════════════════════════════════════════
#  EASING
# ══════════════════════════════════════════════════════════════════

def elastic_out(t: float) -> float:
    if t <= 0: return 0.0
    if t >= 1: return 1.0
    return 1 + (2**(-10*t)) * math.sin((t - 0.075) * (2 * math.pi) / 0.3)


def ease_out_quad(t: float) -> float:
    return 1 - (1 - t)**2


# ══════════════════════════════════════════════════════════════════
#  WAVEFORM WITH GLOW
# ══════════════════════════════════════════════════════════════════

def draw_waveform(canvas: np.ndarray, wave: np.ndarray,
                  rms: float, wave_bgr: tuple) -> None:
    amp  = WAVE_HEIGHT * (0.15 + rms * 0.85)
    xs   = np.linspace(80, W-80, WAVE_POINTS).astype(int)
    kern = np.ones(9) / 9
    ws   = np.convolve(wave, kern, mode='same')
    ys   = np.clip((WAVE_Y_BASE - ws * amp).astype(int), 10, H-10)
    pts  = np.stack([xs, ys], axis=1).reshape(-1, 1, 2)

    # 4-pass glow
    glow = tuple(max(0, int(c * 0.35)) for c in wave_bgr)
    for thick, col, alpha in [
        (20, glow,     0.25),
        (12, glow,     0.45),
        (5,  wave_bgr, 0.80),
        (2,  (240, 245, 255), 1.0)
    ]:
        ov = canvas.copy()
        cv2.polylines(ov, [pts], False, col, thick, cv2.LINE_AA)
        cv2.addWeighted(ov, alpha, canvas, 1-alpha, 0, canvas)

    # Peak sparkle
    pi  = int(np.argmax(np.abs(ws)))
    px, py = int(xs[pi]), int(ys[pi])
    cv2.circle(canvas, (px, py), 5,  (255, 255, 255), -1)
    cv2.circle(canvas, (px, py), 10, wave_bgr, 2)


# ══════════════════════════════════════════════════════════════════
#  VIGNETTE
# ══════════════════════════════════════════════════════════════════

def build_vignette() -> np.ndarray:
    xs = np.linspace(-1, 1, W)
    ys = np.linspace(-1, 1, H)
    X, Y = np.meshgrid(xs, ys)
    dist = np.sqrt(X**2 + Y**2)
    mask = 1.0 - np.clip(dist / dist.max() * 0.6, 0, 1)
    return mask.reshape(H, W, 1).astype(np.float32)


# ══════════════════════════════════════════════════════════════════
#  KEN BURNS
# ══════════════════════════════════════════════════════════════════

def apply_ken_burns(frame: np.ndarray, idx: int,
                    total: int) -> np.ndarray:
    t     = idx / max(1, total-1)
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
#  COMPOSITE PHRASE ONTO CANVAS
# ══════════════════════════════════════════════════════════════════

def composite_phrase(canvas_bgr: np.ndarray,
                     phrase_img: Image.Image,
                     frame_in: int,       # frames since phrase started
                     frame_out: int,      # frames until phrase ends
                     total_frames: int) -> None:
    """
    Composite phrase image onto canvas with entrance/exit animation.
    Entrance: scale-up elastic (first ANIM_IN_FRAMES)
    Exit:     fade-out (last ANIM_OUT_FRAMES)
    Hold:     full opacity in between
    """
    iw, ih = phrase_img.size

    # Target position — centered horizontally, upper-mid vertically
    tx = (W - iw) // 2
    ty = PHRASE_Y_CENTER - ih // 2

    # Entrance animation
    if frame_in < ANIM_IN_FRAMES:
        t     = frame_in / ANIM_IN_FRAMES
        e     = elastic_out(t)
        scale = 0.3 + e * 0.7
        alpha = min(1.0, t * 2.5)
    # Exit fade
    elif frame_out < ANIM_OUT_FRAMES:
        scale = 1.0
        alpha = frame_out / ANIM_OUT_FRAMES
    else:
        scale = 1.0
        alpha = 1.0

    # Apply scale
    disp = phrase_img
    if abs(scale - 1.0) > 0.01:
        nw = max(1, int(iw * scale))
        nh = max(1, int(ih * scale))
        disp = phrase_img.resize((nw, nh), Image.LANCZOS)
        tx   = (W - nw) // 2
        ty   = PHRASE_Y_CENTER - nh // 2

    # Convert canvas to PIL
    canvas_rgb = cv2.cvtColor(canvas_bgr, cv2.COLOR_BGR2RGB)
    canvas_pil = Image.fromarray(canvas_rgb).convert("RGBA")

    # Apply alpha to phrase image
    r, g, b, a = disp.split()
    a = a.point(lambda px: int(px * alpha))
    disp_alpha = Image.merge("RGBA", (r, g, b, a))

    # Bounds-safe composite
    px = max(0, min(W - disp.width, tx))
    py = max(0, min(H - disp.height, ty))
    canvas_pil.alpha_composite(disp_alpha, (px, py))

    result = cv2.cvtColor(
        np.array(canvas_pil.convert("RGB")), cv2.COLOR_RGB2BGR
    )
    np.copyto(canvas_bgr, result)


# ══════════════════════════════════════════════════════════════════
#  CAPS FLASH
# ══════════════════════════════════════════════════════════════════

def apply_flash(canvas: np.ndarray, intensity: float,
                accent: tuple) -> np.ndarray:
    if intensity <= 0:
        return canvas
    ov = np.full_like(canvas, accent, dtype=np.uint8)
    return cv2.addWeighted(canvas, 1 - intensity * 0.12,
                           ov, intensity * 0.12, 0)


# ══════════════════════════════════════════════════════════════════
#  MAIN RENDER
# ══════════════════════════════════════════════════════════════════

def render_video(phrases: list, rms_arr: np.ndarray,
                 wave_arr: np.ndarray, duration: float,
                 bg_bgr: tuple, accent_bgr: tuple,
                 wave_bgr: tuple, word_bgr: tuple) -> None:

    n_frames  = len(rms_arr)
    vignette  = build_vignette()
    fourcc    = cv2.VideoWriter_fourcc(*'mp4v')
    temp      = "raw_temp.mp4"
    writer    = cv2.VideoWriter(temp, fourcc, FPS, (W, H))

    if not writer.isOpened():
        sys.exit("[ERROR] VideoWriter failed")

    print(f"[RENDER] {n_frames} frames | {len(phrases)} phrases")
    print(f"[RENDER] BG={bg_bgr} | Accent={accent_bgr}")

    # Pre-render all phrase images
    print("[RENDER] Pre-rendering phrase images...")
    for p in phrases:
        p["img"] = render_phrase_image(
            p["text"], p["has_caps"], word_bgr, accent_bgr
        )

    # Build frame → phrase index
    frame_phrase = {}
    for pi, p in enumerate(phrases):
        sf = int(p["start_sec"] * FPS)
        ef = int(p["end_sec"]   * FPS)
        ef = min(ef, n_frames)
        p["sf"] = sf
        p["ef"] = ef
        for f in range(sf, ef):
            frame_phrase[f] = pi

    flash_cnt  = 0
    last_pi    = -1
    log_step   = max(1, n_frames // 20)

    for i in range(n_frames):
        # Black background
        canvas = np.full((H, W, 3), bg_bgr, dtype=np.uint8)

        # Waveform
        draw_waveform(canvas, wave_arr[i], rms_arr[i], wave_bgr)

        # Active phrase
        pi = frame_phrase.get(i, -1)
        if pi >= 0:
            p         = phrases[pi]
            frame_in  = i - p["sf"]
            frame_out = p["ef"] - i
            composite_phrase(canvas, p["img"],
                             frame_in, frame_out, n_frames)

            # Trigger flash on new CAPS phrase
            if p["has_caps"] and pi != last_pi:
                flash_cnt = 5
            last_pi = pi

        # Flash
        if flash_cnt > 0:
            canvas = apply_flash(canvas, flash_cnt / 5, accent_bgr)
            flash_cnt -= 1

        # Vignette
        cf     = canvas.astype(np.float32) / 255.0 * vignette
        canvas = (cf * 255).clip(0, 255).astype(np.uint8)

        # Ken Burns
        canvas = apply_ken_burns(canvas, i, n_frames)

        writer.write(canvas)

        if i % log_step == 0:
            print(f"  [RENDER] {int(i/n_frames*100)}%")

    writer.release()
    print("[RENDER] Re-encoding...")

    cmd = [
        "ffmpeg", "-y", "-i", temp,
        "-c:v", "libx264", "-preset", "fast",
        "-crf", "17", "-pix_fmt", "yuv420p", "-an",
        str(OUTPUT_VIDEO)
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        shutil.copy(temp, str(OUTPUT_VIDEO))
    else:
        Path(temp).unlink(missing_ok=True)

    print(f"[✓] {OUTPUT_VIDEO} ({OUTPUT_VIDEO.stat().st_size//1024//1024}MB)")


# ══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════

def main():
    print("=" * 62)
    print("  Kinetic Typography Engine v2")
    print("  Phrase Groups · Warm Colors · Pitch Black")
    print("=" * 62)

    ensure_font()

    if not INPUT_AUDIO.exists():
        download_audio()

    if not INPUT_SCRIPT.exists():
        sys.exit("[ERROR] script.txt not found")
    raw   = INPUT_SCRIPT.read_text(encoding="utf-8")
    clean = clean_script(raw)
    print(f"[INFO] Script: {len(clean.split())} words")

    # Pick palette — new color combination every video
    bg_bgr     = random.choice(BACKGROUNDS_BGR)
    accent_bgr = random.choice(ACCENT_COLORS_BGR)
    wave_bgr   = random.choice(WAVE_COLORS_BGR)
    word_bgr   = random.choice(WORD_COLORS_BGR)

    print(f"[INFO] BG={bg_bgr} | Accent={accent_bgr} | Wave={wave_bgr}")

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

    # Word timestamps
    print("[TTS] Getting word timestamps...")
    word_timestamps = asyncio.run(generate_tts_with_timing(clean))

    if not word_timestamps:
        # Even fallback
        words = clean.split()
        d     = duration / len(words)
        word_timestamps = [
            {"word": w, "start": i*d, "duration": d}
            for i, w in enumerate(words)
        ]

    # Group into phrases
    phrases = group_into_phrases(word_timestamps)

    # Analyse audio
    rms_arr, wave_arr, _ = analyse_audio(str(INPUT_AUDIO), n_frames)

    # Render
    render_video(phrases, rms_arr, wave_arr, duration,
                 bg_bgr, accent_bgr, wave_bgr, word_bgr)

    print("\n" + "=" * 62)
    print("  [✓] DONE — raw_video.mp4 ready")
    print("=" * 62)


if __name__ == "__main__":
    main()
