"""
generate_video.py — Kinetic Physics Engine v3
==============================================
Physics-Based Typography + Climax Shake + Stagger + CAPS Flash
All headless — runs on GitHub Actions.
Output: raw_video.mp4 (1080x1920, 30fps, no audio)
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

# ── Pitch-black warm backgrounds ─────────────────────────────────
BACKGROUNDS_BGR = [
    (5,  6,  8),
    (8,  7,  10),
    (6,  8,  9),
    (7,  6,  11),
    (9,  8,  7),
]

# ── Word colors — warm cream/ivory family ────────────────────────
WORD_COLORS_BGR = [
    (210, 230, 245),
    (220, 238, 255),
    (200, 222, 240),
]

# ── Accent — gold/amber for CAPS ─────────────────────────────────
ACCENT_COLORS_BGR = [
    (60,  180, 255),
    (80,  190, 240),
    (50,  165, 220),
    (90,  200, 255),
]

# ── Waveform neon colors ─────────────────────────────────────────
WAVE_COLORS_BGR = [
    (180, 255, 50),
    (255, 200, 0),
    (200, 100, 255),
    (0,   255, 200),
]

# ── Phrase config ─────────────────────────────────────────────────
WORDS_PER_PHRASE     = 4
MIN_PHRASE_HOLD_SEC  = 1.2
PHRASE_GAP_FRAMES    = 6

# ── Physics / animation ───────────────────────────────────────────
ANIM_IN_FRAMES   = int(FPS * 0.20)   # 0.2 seconds entrance
ANIM_OUT_FRAMES  = int(FPS * 0.15)   # 0.15 seconds exit fade
PHRASE_Y_CENTER  = int(H * 0.38)

# Entrance vectors
ENTRANCE_TYPES  = ["fly_left", "fly_right", "fly_top", "vertical"]
VERTICAL_CHANCE = 0.15   # 15% of phrases get vertical rotation

# ── Stagger / linger ─────────────────────────────────────────────
LINGER_FRAMES    = int(FPS * 0.30)   # Previous phrase lingers 0.3s
LINGER_ALPHA     = 0.40              # At 40% opacity

# ── Climax (last 5 seconds) ───────────────────────────────────────
CLIMAX_SECS       = 5.0
SHAKE_AMPLITUDE   = 10               # ±10 pixels
SHAKE_FREQ        = 1                # Every frame (high-frequency)
CLIMAX_GLOW_MULT  = 2.2              # Waveform glow multiplier
CLIMAX_TEXT_BOOST = 1.08             # Text scale boost during climax

# ── CAPS flash ────────────────────────────────────────────────────
CAPS_FLASH_FRAMES = 2                # 2-frame flash
CAPS_PULSE_SCALE  = 1.18             # Pulse scale on CAPS words

# ── Waveform ─────────────────────────────────────────────────────
WAVE_Y_BASE  = int(H * 0.82)
WAVE_HEIGHT  = int(H * 0.14)
WAVE_POINTS  = 200

# ── Ken Burns ────────────────────────────────────────────────────
KB_START = 1.0
KB_END   = 1.12


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
            return
    except Exception as e:
        print(f"[FONT] Download failed: {e}")
    ttfs   = glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)
    bold   = [f for f in ttfs if "bold" in f.lower() or "Bold" in f]
    chosen = bold[0] if bold else (ttfs[0] if ttfs else None)
    if chosen:
        shutil.copy(chosen, str(FONT_PATH))


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
#  EDGE-TTS WORD TIMESTAMPS
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
    print(f"[TTS] {len(words)} word timestamps")
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
        if not len(chunk):
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
    return rms_arr, wave_arr, duration


# ══════════════════════════════════════════════════════════════════
#  PHRASE GROUPING
# ══════════════════════════════════════════════════════════════════

def group_into_phrases(word_timestamps: list, duration: float) -> list:
    phrases       = []
    climax_start  = duration - CLIMAX_SECS
    i = 0
    while i < len(word_timestamps):
        group = word_timestamps[i:i + WORDS_PER_PHRASE]
        text  = ' '.join(w["word"] for w in group)
        clean = re.sub(r'[^a-zA-Z0-9\'\-!?.,\s]', '', text).strip()
        if not clean:
            i += WORDS_PER_PHRASE
            continue

        start_sec = group[0]["start"]
        end_sec   = group[-1]["start"] + group[-1]["duration"]
        if end_sec - start_sec < MIN_PHRASE_HOLD_SEC:
            end_sec = start_sec + MIN_PHRASE_HOLD_SEC

        has_caps    = bool(re.search(r'[A-Z]{2,}', text))
        is_climax   = start_sec >= climax_start

        # Entrance type — 15% vertical, rest fly
        r = random.random()
        if r < VERTICAL_CHANCE:
            entrance = "vertical"
        elif r < 0.50:
            entrance = "fly_left"
        elif r < 0.80:
            entrance = "fly_right"
        else:
            entrance = "fly_top"

        phrases.append({
            "text":      clean,
            "start_sec": start_sec,
            "end_sec":   end_sec,
            "has_caps":  has_caps,
            "is_climax": is_climax,
            "entrance":  entrance,
        })
        i += WORDS_PER_PHRASE

    # Mark last phrase as climax too
    if phrases:
        phrases[-1]["is_climax"] = True

    print(f"[PHRASE] {len(phrases)} phrases | "
          f"{sum(p['is_climax'] for p in phrases)} climax")
    return phrases


# ══════════════════════════════════════════════════════════════════
#  EASING FUNCTIONS
# ══════════════════════════════════════════════════════════════════

def elastic_out(t: float) -> float:
    """0.4x → 1.1x → 1.0x spring."""
    if t <= 0: return 0.0
    if t >= 1: return 1.0
    return 1 + (2**(-10*t)) * math.sin((t - 0.075) * (2*math.pi) / 0.3)


def ease_out_quad(t: float) -> float:
    return 1 - (1-t)**2


# ══════════════════════════════════════════════════════════════════
#  PHRASE IMAGE RENDERER
# ══════════════════════════════════════════════════════════════════

def render_phrase_image(text: str, has_caps: bool,
                        word_bgr: tuple, accent_bgr: tuple,
                        scale_boost: float = 1.0,
                        is_climax: bool = False) -> Image.Image:
    words       = text.split()
    NORMAL_SIZE = int(95 * scale_boost)
    CAPS_SIZE   = int(118 * scale_boost * CAPS_PULSE_SCALE
                      if has_caps else 118 * scale_boost)
    LINE_SP     = 20
    PAD         = 30

    word_data = []
    for w in words:
        is_cap = bool(re.search(r'[A-Z]{2,}', w))
        size   = CAPS_SIZE if is_cap else NORMAL_SIZE
        # Climax words get a slight size boost
        if is_climax:
            size = int(size * CLIMAX_TEXT_BOOST)
        color  = accent_bgr if is_cap else word_bgr
        font   = get_font(size)
        tmp    = Image.new("RGBA", (1,1))
        draw   = ImageDraw.Draw(tmp)
        bbox   = draw.textbbox((0,0), w, font=font)
        word_data.append({
            "text":  w, "font": font, "color": color,
            "w": bbox[2]-bbox[0], "h": bbox[3]-bbox[1],
            "is_cap": is_cap
        })

    max_line_w = W - 120
    lines, cur_line, cur_w = [], [], 0
    for wd in word_data:
        if cur_w + wd["w"] + 18 > max_line_w and cur_line:
            lines.append(cur_line)
            cur_line, cur_w = [wd], wd["w"]
        else:
            cur_line.append(wd)
            cur_w += wd["w"] + 18
    if cur_line:
        lines.append(cur_line)

    lh_list = [max(wd["h"] for wd in l) for l in lines]
    tot_h   = sum(lh_list) + LINE_SP*(len(lines)-1) + PAD*2
    tot_w   = W - 60

    img  = Image.new("RGBA", (tot_w, tot_h), (0,0,0,0))
    draw = ImageDraw.Draw(img)

    y = PAD
    for li, line in enumerate(lines):
        lw  = sum(wd["w"] for wd in line) + 18*(len(line)-1)
        x   = (tot_w - lw) // 2
        lh  = lh_list[li]
        for wd in line:
            rgb = (wd["color"][2], wd["color"][1], wd["color"][0])
            draw.text((x+3, y+3), wd["text"], font=wd["font"],
                      fill=(0,0,0,140))
            draw.text((x, y), wd["text"], font=wd["font"],
                      fill=rgb+(255,))
            if wd["is_cap"]:
                acc_rgb = (accent_bgr[2], accent_bgr[1], accent_bgr[0])
                draw.line([(x, y+wd["h"]+4), (x+wd["w"], y+wd["h"]+4)],
                          fill=acc_rgb+(200,), width=3)
            x += wd["w"] + 18
        y += lh + LINE_SP

    return img


# ══════════════════════════════════════════════════════════════════
#  PHYSICS ENTRANCE — position offset per frame
# ══════════════════════════════════════════════════════════════════

def get_entrance_offset(entrance: str, frame_in: int,
                        total: int, iw: int, ih: int) -> tuple:
    """
    Returns (x_offset, y_offset, scale, alpha) for entrance frame.
    Elastic-out spring: 0.4x → 1.1x → 1.0x
    """
    t = min(1.0, frame_in / max(1, total-1))
    e = elastic_out(t)

    alpha = min(1.0, t * 3.0)

    # Scale: 0.4 at t=0, peaks ~1.1, settles 1.0 (elastic handles this)
    scale = 0.4 + e * 0.7   # 0.4 + elastic * 0.7

    if entrance == "fly_left":
        x_off = int((1-e) * (-iw - 80))
        y_off = 0
    elif entrance == "fly_right":
        x_off = int((1-e) * (W + 80))
        y_off = 0
    elif entrance == "fly_top":
        x_off = 0
        y_off = int((1-e) * (-ih - 80))
    elif entrance == "vertical":
        x_off = 0
        y_off = int((1-e) * (-ih - 80))
    else:
        x_off, y_off = 0, 0

    return x_off, y_off, scale, alpha


# ══════════════════════════════════════════════════════════════════
#  CLIMAX SHAKE — random pixel offset per frame
# ══════════════════════════════════════════════════════════════════

def get_shake_offset(frame_idx: int, is_climax: bool) -> tuple:
    """High-frequency per-frame shake during climax."""
    if not is_climax:
        return 0, 0
    # Deterministic but chaotic per frame
    rng  = np.random.RandomState(frame_idx * 7 + 13)
    sx   = int(rng.randint(-SHAKE_AMPLITUDE, SHAKE_AMPLITUDE+1))
    sy   = int(rng.randint(-SHAKE_AMPLITUDE//2, SHAKE_AMPLITUDE//2+1))
    return sx, sy


def apply_shake_to_canvas(canvas: np.ndarray,
                           sx: int, sy: int) -> np.ndarray:
    """Shift entire canvas by (sx, sy), fill edges with bg color."""
    if sx == 0 and sy == 0:
        return canvas
    M      = np.float32([[1, 0, sx], [0, 1, sy]])
    shaken = cv2.warpAffine(canvas, M, (W, H),
                            flags=cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_REPLICATE)
    return shaken


# ══════════════════════════════════════════════════════════════════
#  WAVEFORM WITH GLOW (climax boost)
# ══════════════════════════════════════════════════════════════════

def draw_waveform(canvas: np.ndarray, wave: np.ndarray,
                  rms: float, wave_bgr: tuple,
                  is_climax: bool = False) -> None:
    glow_mult = CLIMAX_GLOW_MULT if is_climax else 1.0
    amp  = WAVE_HEIGHT * (0.15 + rms * 0.85)
    xs   = np.linspace(80, W-80, WAVE_POINTS).astype(int)
    kern = np.ones(9) / 9
    ws   = np.convolve(wave, kern, mode='same')
    ys   = np.clip((WAVE_Y_BASE - ws * amp).astype(int), 10, H-10)
    pts  = np.stack([xs, ys], axis=1).reshape(-1, 1, 2)

    glow = tuple(max(0, int(c * 0.35)) for c in wave_bgr)
    passes = [
        (int(20 * glow_mult), glow,     0.25 * min(1.0, glow_mult * 0.6)),
        (int(12 * glow_mult), glow,     0.45 * min(1.0, glow_mult * 0.7)),
        (5,                   wave_bgr, 0.80),
        (2,                   (240, 245, 255), 1.0)
    ]
    for thick, col, alpha in passes:
        ov = canvas.copy()
        cv2.polylines(ov, [pts], False, col, max(1,thick), cv2.LINE_AA)
        cv2.addWeighted(ov, alpha, canvas, 1-alpha, 0, canvas)

    pi = int(np.argmax(np.abs(ws)))
    px, py = int(xs[pi]), int(ys[pi])
    r_size = 8 if not is_climax else 12
    cv2.circle(canvas, (px, py), r_size, (255,255,255), -1)
    cv2.circle(canvas, (px, py), r_size+5, wave_bgr, 2)


# ══════════════════════════════════════════════════════════════════
#  VIGNETTE + KEN BURNS
# ══════════════════════════════════════════════════════════════════

def build_vignette() -> np.ndarray:
    xs = np.linspace(-1, 1, W)
    ys = np.linspace(-1, 1, H)
    X, Y = np.meshgrid(xs, ys)
    dist = np.sqrt(X**2 + Y**2)
    mask = 1.0 - np.clip(dist / dist.max() * 0.6, 0, 1)
    return mask.reshape(H, W, 1).astype(np.float32)


def apply_ken_burns(frame: np.ndarray,
                    idx: int, total: int) -> np.ndarray:
    t     = idx / max(1, total-1)
    scale = KB_START + t * (KB_END - KB_START)
    if abs(scale - 1.0) < 0.002:
        return frame
    nw    = int(W * scale)
    nh    = int(H * scale)
    big   = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
    ox    = (nw - W) // 2
    oy    = (nh - H) // 2
    return big[oy:oy+H, ox:ox+W]


# ══════════════════════════════════════════════════════════════════
#  COMPOSITE PHRASE (with entrance physics)
# ══════════════════════════════════════════════════════════════════

def composite_phrase_on_canvas(canvas_bgr: np.ndarray,
                                phrase_img: Image.Image,
                                frame_in: int,
                                frame_out: int,
                                entrance: str,
                                alpha_override: float = None) -> None:
    iw, ih = phrase_img.size
    tx     = (W - iw) // 2
    ty     = PHRASE_Y_CENTER - ih // 2

    # Determine animation state
    if frame_in < ANIM_IN_FRAMES:
        # Entrance animation
        x_off, y_off, scale, alpha = get_entrance_offset(
            entrance, frame_in, ANIM_IN_FRAMES, iw, ih
        )
    elif frame_out < ANIM_OUT_FRAMES:
        # Exit fade
        x_off, y_off = 0, 0
        scale = 1.0
        alpha = frame_out / ANIM_OUT_FRAMES
    else:
        x_off, y_off = 0, 0
        scale = 1.0
        alpha = 1.0

    if alpha_override is not None:
        alpha = alpha_override

    # Scale image
    disp = phrase_img
    if abs(scale - 1.0) > 0.01:
        nw   = max(1, int(iw * scale))
        nh   = max(1, int(ih * scale))
        disp = phrase_img.resize((nw, nh), Image.LANCZOS)
        tx   = (W - nw) // 2
        ty   = PHRASE_Y_CENTER - nh // 2

    # Apply offsets
    px = max(-disp.width,  min(W, tx + x_off))
    py = max(-disp.height, min(H, ty + y_off))

    # Convert canvas to PIL RGBA
    canvas_rgb = cv2.cvtColor(canvas_bgr, cv2.COLOR_BGR2RGB)
    canvas_pil = Image.fromarray(canvas_rgb).convert("RGBA")

    # Apply alpha to phrase
    r, g, b, a = disp.split()
    a    = a.point(lambda v: int(v * min(1.0, max(0.0, alpha))))
    disp = Image.merge("RGBA", (r, g, b, a))

    canvas_pil.alpha_composite(disp, (max(0, px), max(0, py)))

    result = cv2.cvtColor(
        np.array(canvas_pil.convert("RGB")), cv2.COLOR_RGB2BGR
    )
    np.copyto(canvas_bgr, result)


# ══════════════════════════════════════════════════════════════════
#  CAPS FLASH — background lightening
# ══════════════════════════════════════════════════════════════════

def apply_caps_flash(canvas: np.ndarray, intensity: float,
                     bg_bgr: tuple) -> np.ndarray:
    if intensity <= 0:
        return canvas
    # Lighten background — add a warm white flash
    overlay = np.full_like(canvas, (200, 215, 230), dtype=np.uint8)
    return cv2.addWeighted(canvas, 1 - intensity * 0.18,
                           overlay, intensity * 0.18, 0)


# ══════════════════════════════════════════════════════════════════
#  MAIN RENDER
# ══════════════════════════════════════════════════════════════════

def render_video(phrases: list, rms_arr: np.ndarray,
                 wave_arr: np.ndarray, duration: float,
                 bg_bgr: tuple, accent_bgr: tuple,
                 wave_bgr: tuple, word_bgr: tuple) -> None:

    n_frames = len(rms_arr)
    vignette = build_vignette()
    fourcc   = cv2.VideoWriter_fourcc(*'mp4v')
    temp     = "raw_temp.mp4"
    writer   = cv2.VideoWriter(temp, fourcc, FPS, (W, H))

    if not writer.isOpened():
        sys.exit("[ERROR] VideoWriter failed")

    print(f"[RENDER] {n_frames} frames | {len(phrases)} phrases")

    # Pre-render phrase images
    print("[RENDER] Pre-rendering phrases...")
    for p in phrases:
        p["img"] = render_phrase_image(
            p["text"], p["has_caps"],
            word_bgr, accent_bgr,
            scale_boost=1.0,
            is_climax=p["is_climax"]
        )

    # Frame lookup
    for pi, p in enumerate(phrases):
        p["sf"] = int(p["start_sec"] * FPS)
        p["ef"] = min(int(p["end_sec"] * FPS), n_frames)
        p["pi"] = pi

    frame_phrase = {}
    for p in phrases:
        for f in range(p["sf"], p["ef"]):
            frame_phrase[f] = p

    caps_flash    = 0
    prev_phrase   = None
    log_step      = max(1, n_frames // 20)
    climax_start  = int((duration - CLIMAX_SECS) * FPS)

    for i in range(n_frames):
        is_climax = i >= climax_start

        # ── Background ───────────────────────────────────────────
        canvas = np.full((H, W, 3), bg_bgr, dtype=np.uint8)

        # ── Waveform ─────────────────────────────────────────────
        draw_waveform(canvas, wave_arr[i], rms_arr[i],
                      wave_bgr, is_climax)

        # ── Stagger: linger previous phrase at 40% opacity ────────
        cur_phrase = frame_phrase.get(i)

        if (prev_phrase is not None and
                cur_phrase is not None and
                cur_phrase["pi"] != prev_phrase["pi"]):
            frames_since_end = i - prev_phrase["ef"]
            if frames_since_end < LINGER_FRAMES:
                # Draw prev phrase at 40% opacity (fading)
                linger_alpha = LINGER_ALPHA * (
                    1 - frames_since_end / LINGER_FRAMES
                )
                lf_in  = prev_phrase["ef"] - prev_phrase["sf"]
                composite_phrase_on_canvas(
                    canvas, prev_phrase["img"],
                    lf_in, 999,
                    prev_phrase["entrance"],
                    alpha_override=linger_alpha
                )

        # ── Active phrase ─────────────────────────────────────────
        if cur_phrase is not None:
            frame_in  = i - cur_phrase["sf"]
            frame_out = cur_phrase["ef"] - i

            # CAPS flash trigger
            if (cur_phrase["has_caps"] and
                    (prev_phrase is None or
                     cur_phrase["pi"] != prev_phrase["pi"])):
                caps_flash = CAPS_FLASH_FRAMES

            composite_phrase_on_canvas(
                canvas, cur_phrase["img"],
                frame_in, frame_out,
                cur_phrase["entrance"]
            )
            prev_phrase = cur_phrase

        # ── CAPS flash (background lightening) ───────────────────
        if caps_flash > 0:
            intensity = caps_flash / CAPS_FLASH_FRAMES
            canvas    = apply_caps_flash(canvas, intensity, bg_bgr)
            caps_flash -= 1

        # ── Vignette ─────────────────────────────────────────────
        cf     = canvas.astype(np.float32) / 255.0 * vignette
        canvas = (cf * 255).clip(0, 255).astype(np.uint8)

        # ── Ken Burns ────────────────────────────────────────────
        canvas = apply_ken_burns(canvas, i, n_frames)

        # ── Climax shake — applied LAST so it shakes everything ──
        if is_climax:
            sx, sy = get_shake_offset(i, True)
            canvas = apply_shake_to_canvas(canvas, sx, sy)

        writer.write(canvas)

        if i % log_step == 0:
            print(f"  [RENDER] {int(i/n_frames*100)}% "
                  f"{'🔥 CLIMAX' if is_climax else ''}")

    writer.release()
    print("[RENDER] Re-encoding with ffmpeg...")

    cmd = [
        "ffmpeg", "-y", "-i", temp,
        "-c:v", "libx264", "-preset", "fast",
        "-crf", "17", "-pix_fmt", "yuv420p", "-an",
        str(OUTPUT_VIDEO)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        shutil.copy(temp, str(OUTPUT_VIDEO))
    else:
        Path(temp).unlink(missing_ok=True)

    mb = OUTPUT_VIDEO.stat().st_size / (1024*1024)
    print(f"[✓] {OUTPUT_VIDEO} ({mb:.1f}MB)")


# ══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════

def main():
    print("=" * 62)
    print("  Kinetic Physics Engine v3")
    print("  Elastic · Shake · Stagger · Flash · Climax")
    print("=" * 62)

    ensure_font()

    if not INPUT_AUDIO.exists():
        download_audio()

    if not INPUT_SCRIPT.exists():
        sys.exit("[ERROR] script.txt not found")

    raw   = INPUT_SCRIPT.read_text(encoding="utf-8")
    clean = clean_script(raw)
    print(f"[INFO] Script: {len(clean.split())} words")

    # Random palette
    bg_bgr     = random.choice(BACKGROUNDS_BGR)
    accent_bgr = random.choice(ACCENT_COLORS_BGR)
    wave_bgr   = random.choice(WAVE_COLORS_BGR)
    word_bgr   = random.choice(WORD_COLORS_BGR)

    # Audio duration
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(INPUT_AUDIO)
    ]
    duration = float(
        subprocess.run(cmd, capture_output=True,
                       text=True).stdout.strip()
    )
    n_frames = int(duration * FPS)
    print(f"[INFO] Duration: {duration:.2f}s | Frames: {n_frames}")

    # Word timestamps
    print("[TTS] Computing word timestamps...")
    word_timestamps = asyncio.run(generate_tts_with_timing(clean))

    if not word_timestamps:
        words = clean.split()
        d     = duration / max(1, len(words))
        word_timestamps = [
            {"word": w, "start": i*d, "duration": d}
            for i, w in enumerate(words)
        ]

    # Group into phrases
    phrases = group_into_phrases(word_timestamps, duration)

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
