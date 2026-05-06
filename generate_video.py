"""
generate_video.py — Cinematic Kinetic Engine v4
================================================
Maximum retention · Atmospheric · Cinematic Masterpiece
- Film grain (per frame)
- Vignette 60%
- Dynamic text positioning (center 60%)
- Elastic overshoot 0.5→1.15→1.0
- Neon glow on CAPS/quotes (Electric Crimson)
- Chromatic aberration shake in climax
- Motion blur on fly-in words
- Gradient waveform (center bright → edges taper)
- Climax waveform color shift + 2x amplitude
Output: raw_video.mp4 (1080×1920, 30fps, no audio)
"""

import os, re, sys, glob, math, random, shutil
import zipfile, asyncio, subprocess, requests
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

# ── Backgrounds — near-black warm ────────────────────────────────
BACKGROUNDS_BGR = [
    (5,  6,  8), (8, 7, 10), (6, 8, 9), (7, 6, 11), (9, 8, 7),
]

# ── Word colors — warm cream/ivory ───────────────────────────────
WORD_COLORS_BGR = [
    (210, 230, 245), (220, 238, 255), (200, 222, 240),
]

# ── Electric Crimson accent (neon glow for CAPS/quotes) ──────────
CRIMSON_BGR       = (60,  30, 220)   # BGR: Electric Crimson
CRIMSON_GLOW_BGR  = (40,  10, 160)   # Darker glow layer

# ── Waveform base color (transitions to crimson in climax) ───────
WAVE_BASE_BGR     = (180, 255, 50)   # Neon lime base

# ── Typography ───────────────────────────────────────────────────
WORDS_PER_PHRASE    = 4
MIN_PHRASE_HOLD_SEC = 1.2
ANIM_IN_FRAMES      = int(FPS * 0.22)
ANIM_OUT_FRAMES     = int(FPS * 0.15)
LINGER_FRAMES       = int(FPS * 0.30)
LINGER_ALPHA        = 0.40
VERTICAL_CHANCE     = 0.12

# Dynamic positioning — center 60% of screen
POS_X_MIN = int(W * 0.20)
POS_X_MAX = int(W * 0.80)
POS_Y_MIN = int(H * 0.22)
POS_Y_MAX = int(H * 0.62)

# Elastic overshoot config
ELASTIC_START_SCALE = 0.5
ELASTIC_PEAK_SCALE  = 1.15
ELASTIC_END_SCALE   = 1.0

# ── Film grain ───────────────────────────────────────────────────
GRAIN_INTENSITY  = 18    # 0-255, how strong the grain is
GRAIN_BLEND      = 0.06  # How much grain blends into frame

# ── Vignette ─────────────────────────────────────────────────────
VIGNETTE_STRENGTH = 0.60

# ── Motion blur ──────────────────────────────────────────────────
MOTION_BLUR_PX   = 10    # Pixels of blur during fly-in

# ── Climax ───────────────────────────────────────────────────────
CLIMAX_SECS       = 5.0
SHAKE_AMP         = 10
CHROMA_SHIFT      = 8    # Pixels to shift R/B channels
CLIMAX_WAVE_MULT  = 2.0  # Amplitude multiplier

# ── Ken Burns ────────────────────────────────────────────────────
KB_START = 1.0
KB_END   = 1.10

# ══════════════════════════════════════════════════════════════════
#  FONT
# ══════════════════════════════════════════════════════════════════

def ensure_font():
    if FONT_PATH.exists():
        return
    try:
        r = requests.get(FONT_URL, timeout=30)
        if r.status_code == 200:
            FONT_PATH.write_bytes(r.content)
            print(f"[FONT] ✅ Downloaded")
            return
    except Exception as e:
        print(f"[FONT] Download failed: {e}")
    ttfs   = glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)
    bold   = [f for f in ttfs if "bold" in f.lower()]
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
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github+json"}
    res = requests.get(
        "https://api.github.com/repos/Suryansh0704/Audio-generator-/actions/artifacts",
        headers=headers)
    artifacts = res.json().get("artifacts", [])
    if not artifacts:
        sys.exit("[ERROR] No artifacts")
    latest = artifacts[0]
    r = requests.get(latest["archive_download_url"], headers=headers)
    with open("audio.zip", "wb") as f:
        f.write(r.content)
    with zipfile.ZipFile("audio.zip") as z:
        z.extractall("audio_extracted")
    wavs = (glob.glob("audio_extracted/**/*.wav", recursive=True)
            or glob.glob("audio_extracted/*.wav"))
    if wavs:
        shutil.copy(wavs[0], str(INPUT_AUDIO))
        print(f"[AUDIO] ✅ {INPUT_AUDIO.stat().st_size//1024}KB")
    else:
        sys.exit("[ERROR] No WAV found")


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
#  EDGE-TTS TIMESTAMPS
# ══════════════════════════════════════════════════════════════════

async def generate_tts_with_timing(text: str) -> list:
    communicate = edge_tts.Communicate(
        text=text, voice=VOICE, pitch=PITCH, rate=RATE)
    words, audio_data = [], bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            w = chunk["text"].strip()
            if w:
                words.append({
                    "word":     w,
                    "start":    chunk["offset"] / 10_000_000,
                    "duration": chunk["duration"] / 10_000_000,
                })
    AUDIO_MP3.write_bytes(bytes(audio_data))
    print(f"[TTS] {len(words)} timestamps")
    return words


# ══════════════════════════════════════════════════════════════════
#  AUDIO ANALYSIS
# ══════════════════════════════════════════════════════════════════

def analyse_audio(path: str, n_frames: int) -> tuple:
    y, sr    = librosa.load(str(path), sr=None, mono=True)
    duration = len(y) / sr
    spf      = len(y) / n_frames
    rms_arr  = np.zeros(n_frames, dtype=np.float32)
    wave_arr = np.zeros((n_frames, 200), dtype=np.float32)
    for i in range(n_frames):
        s = int(i * spf); e = min(int(s+spf), len(y))
        chunk = y[s:e]
        if not len(chunk): continue
        rms_arr[i] = float(np.sqrt(np.mean(chunk**2)))
        if len(chunk) >= 200:
            idx = np.linspace(0, len(chunk)-1, 200).astype(int)
            wave_arr[i] = chunk[idx]
        else:
            wave_arr[i, :len(chunk)] = chunk
    mx = rms_arr.max()
    if mx > 0: rms_arr /= mx
    print(f"[AUDIO] {duration:.2f}s analysed")
    return rms_arr, wave_arr, duration


# ══════════════════════════════════════════════════════════════════
#  PHRASE GROUPING
# ══════════════════════════════════════════════════════════════════

def group_into_phrases(word_timestamps: list, duration: float) -> list:
    phrases      = []
    climax_start = duration - CLIMAX_SECS
    entrances    = ["fly_left", "fly_right", "fly_top",
                    "fly_left", "fly_right"]  # weighted toward horizontal

    i = 0
    while i < len(word_timestamps):
        group = word_timestamps[i:i + WORDS_PER_PHRASE]
        text  = ' '.join(w["word"] for w in group)
        clean = re.sub(r'[^a-zA-Z0-9\'\-!?.,"\s]', '', text).strip()
        if not clean:
            i += WORDS_PER_PHRASE
            continue

        start_sec  = group[0]["start"]
        end_sec    = group[-1]["start"] + group[-1]["duration"]
        if end_sec - start_sec < MIN_PHRASE_HOLD_SEC:
            end_sec = start_sec + MIN_PHRASE_HOLD_SEC

        has_caps   = bool(re.search(r'[A-Z]{2,}', text))
        has_quotes = '"' in text or "'" in text
        is_climax  = start_sec >= climax_start

        # Entrance type
        if random.random() < VERTICAL_CHANCE:
            entrance = "vertical"
        else:
            entrance = random.choice(entrances)

        # Dynamic position — within center 60% of screen
        rand_x = random.randint(POS_X_MIN, POS_X_MAX)
        rand_y = random.randint(POS_Y_MIN, POS_Y_MAX)

        phrases.append({
            "text":       clean,
            "start_sec":  start_sec,
            "end_sec":    end_sec,
            "has_caps":   has_caps,
            "has_quotes": has_quotes,
            "is_climax":  is_climax,
            "entrance":   entrance,
            "rand_x":     rand_x,
            "rand_y":     rand_y,
        })
        i += WORDS_PER_PHRASE

    if phrases:
        phrases[-1]["is_climax"] = True

    print(f"[PHRASE] {len(phrases)} phrases")
    return phrases


# ══════════════════════════════════════════════════════════════════
#  EASING — Elastic Overshoot 0.5→1.15→1.0
# ══════════════════════════════════════════════════════════════════

def elastic_overshoot(t: float) -> float:
    """Scale: 0.5 at t=0, peaks ~1.15, settles 1.0."""
    if t <= 0: return 0.0
    if t >= 1: return 1.0
    # Elastic out with overshoot
    raw = 1 + (2**(-10*t)) * math.sin((t - 0.075) * 2*math.pi / 0.3)
    # Remap so start = ELASTIC_START_SCALE
    return ELASTIC_START_SCALE + raw * (1.0 - ELASTIC_START_SCALE)


# ══════════════════════════════════════════════════════════════════
#  MOTION BLUR
# ══════════════════════════════════════════════════════════════════

def apply_motion_blur(img: Image.Image,
                      entrance: str, t: float) -> Image.Image:
    """Apply directional motion blur during entrance."""
    if t > 0.5 or entrance == "vertical":
        return img
    blur_px = int(MOTION_BLUR_PX * (1 - t * 2))
    if blur_px < 2:
        return img

    arr = np.array(img, dtype=np.float32)
    if entrance in ("fly_left", "fly_right"):
        kernel = np.zeros((1, blur_px), dtype=np.float32)
        kernel[0, :] = 1.0 / blur_px
    else:  # fly_top
        kernel = np.zeros((blur_px, 1), dtype=np.float32)
        kernel[:, 0] = 1.0 / blur_px

    blurred = np.zeros_like(arr)
    for c in range(arr.shape[2]):
        blurred[:,:,c] = cv2.filter2D(arr[:,:,c], -1, kernel)

    return Image.fromarray(blurred.astype(np.uint8))


# ══════════════════════════════════════════════════════════════════
#  NEON GLOW TEXT RENDERER
# ══════════════════════════════════════════════════════════════════

def render_phrase_image(text: str,
                        has_caps: bool,
                        has_quotes: bool,
                        word_bgr: tuple,
                        is_climax: bool = False) -> Image.Image:
    words       = text.split()
    NORMAL_SIZE = 95
    CAPS_SIZE   = 122
    LINE_SP     = 22
    PAD         = 32

    use_accent  = has_caps or has_quotes

    word_data = []
    for w in words:
        is_cap = bool(re.search(r'[A-Z]{2,}', w))
        is_qot = w.startswith('"') or w.startswith("'")
        is_acc = is_cap or is_qot
        size   = CAPS_SIZE if is_acc else NORMAL_SIZE
        if is_climax: size = int(size * 1.06)
        color  = CRIMSON_BGR if is_acc else word_bgr
        font   = get_font(size)
        tmp    = Image.new("RGBA", (1,1))
        draw   = ImageDraw.Draw(tmp)
        bbox   = draw.textbbox((0,0), w, font=font)
        word_data.append({
            "text":  w,
            "font":  font,
            "color": color,
            "w":     max(1, bbox[2]-bbox[0]),
            "h":     max(1, bbox[3]-bbox[1]),
            "is_acc": is_acc,
        })

    # Line wrapping
    max_w  = W - 160
    lines, cur, cw = [], [], 0
    for wd in word_data:
        if cw + wd["w"] + 18 > max_w and cur:
            lines.append(cur); cur, cw = [wd], wd["w"]
        else:
            cur.append(wd); cw += wd["w"] + 18
    if cur: lines.append(cur)

    lh_list = [max(wd["h"] for wd in l) for l in lines]
    tot_h   = sum(lh_list) + LINE_SP*(len(lines)-1) + PAD*2
    tot_w   = W - 60

    img  = Image.new("RGBA", (max(1, tot_w), max(1, tot_h)), (0,0,0,0))
    draw = ImageDraw.Draw(img)

    y = PAD
    for li, line in enumerate(lines):
        lw = sum(wd["w"] for wd in line) + 18*(len(line)-1)
        x  = (tot_w - lw) // 2
        lh = lh_list[li]

        for wd in line:
            rgb = (wd["color"][2], wd["color"][1], wd["color"][0])

            if wd["is_acc"]:
                # Multi-pass neon glow (Electric Crimson)
                glow_rgb = (CRIMSON_GLOW_BGR[2],
                            CRIMSON_GLOW_BGR[1],
                            CRIMSON_GLOW_BGR[0])
                for gd, ga in [(8, 60), (5, 100), (3, 140)]:
                    draw.text((x+gd,  y),    wd["text"], font=wd["font"],
                              fill=glow_rgb+(ga,))
                    draw.text((x-gd,  y),    wd["text"], font=wd["font"],
                              fill=glow_rgb+(ga,))
                    draw.text((x,     y+gd), wd["text"], font=wd["font"],
                              fill=glow_rgb+(ga,))
                    draw.text((x,     y-gd), wd["text"], font=wd["font"],
                              fill=glow_rgb+(ga,))
                # Underline
                ul_y = y + wd["h"] + 5
                draw.line([(x, ul_y), (x+wd["w"], ul_y)],
                          fill=rgb+(220,), width=3)
            else:
                # Soft shadow
                draw.text((x+3, y+3), wd["text"], font=wd["font"],
                          fill=(0,0,0,130))

            draw.text((x, y), wd["text"], font=wd["font"],
                      fill=rgb+(255,))
            x += wd["w"] + 18

        y += lh + LINE_SP

    return img


# ══════════════════════════════════════════════════════════════════
#  GRADIENT WAVEFORM
# ══════════════════════════════════════════════════════════════════

def draw_gradient_waveform(canvas: np.ndarray,
                           wave: np.ndarray,
                           rms: float,
                           is_climax: bool) -> None:
    """
    Gradient waveform: brightest at center, tapers to edges.
    In climax: transitions to Crimson and doubles amplitude.
    """
    NPTS      = 200
    amp_mult  = CLIMAX_WAVE_MULT if is_climax else 1.0
    base_ht   = int(H * 0.14)
    amp       = base_ht * (0.15 + rms * 0.85) * amp_mult
    amp       = min(amp, base_ht * 1.8)

    xs        = np.linspace(80, W-80, NPTS).astype(int)
    kern      = np.ones(9) / 9
    ws        = np.convolve(wave, kern, mode='same')
    ys        = np.clip((WAVE_Y_BASE - ws * amp).astype(int), 10, H-10)

    # Color transition: lime → crimson in climax
    if is_climax:
        base_col = CRIMSON_BGR
        glow_col = CRIMSON_GLOW_BGR
    else:
        base_col = WAVE_BASE_BGR
        glow_col = tuple(max(0, int(c*0.35)) for c in WAVE_BASE_BGR)

    # Gradient brightness: center segment = full brightness
    center_idx = NPTS // 2
    for i in range(NPTS - 1):
        dist_from_center = abs(i - center_idx) / center_idx
        brightness       = 1.0 - dist_from_center * 0.75
        brightness       = max(0.25, brightness)

        col = tuple(int(c * brightness) for c in base_col)
        pt1 = (int(xs[i]),   int(ys[i]))
        pt2 = (int(xs[i+1]), int(ys[i+1]))

        # Glow pass
        gcol = tuple(int(c * brightness * 0.4) for c in base_col)
        cv2.line(canvas, pt1, pt2, gcol, 12, cv2.LINE_AA)
        cv2.line(canvas, pt1, pt2, gcol, 7,  cv2.LINE_AA)
        # Bright core
        cv2.line(canvas, pt1, pt2, col,  2,  cv2.LINE_AA)

    # Peak sparkle
    pi  = int(np.argmax(np.abs(ws)))
    px, py = int(xs[pi]), int(ys[pi])
    cv2.circle(canvas, (px, py), 6,  (255,255,255), -1)
    cv2.circle(canvas, (px, py), 11, base_col, 2)

    # Waveform Y baseline
    WAVE_Y_BASE_local = int(H * 0.82)


WAVE_Y_BASE = int(H * 0.82)


# ══════════════════════════════════════════════════════════════════
#  FILM GRAIN
# ══════════════════════════════════════════════════════════════════

def apply_film_grain(canvas: np.ndarray, frame_idx: int) -> np.ndarray:
    """Add high-frequency noise that changes every frame."""
    rng   = np.random.RandomState(frame_idx * 31 + 7)
    noise = rng.randint(-GRAIN_INTENSITY, GRAIN_INTENSITY+1,
                        canvas.shape, dtype=np.int16)
    out   = canvas.astype(np.int16) + (noise * GRAIN_BLEND).astype(np.int16)
    return np.clip(out, 0, 255).astype(np.uint8)


# ══════════════════════════════════════════════════════════════════
#  VIGNETTE
# ══════════════════════════════════════════════════════════════════

def build_vignette() -> np.ndarray:
    xs = np.linspace(-1, 1, W)
    ys = np.linspace(-1, 1, H)
    X, Y  = np.meshgrid(xs, ys)
    dist  = np.sqrt(X**2 + Y**2)
    mask  = 1.0 - np.clip(dist / dist.max() * VIGNETTE_STRENGTH, 0, 1)
    return mask.reshape(H, W, 1).astype(np.float32)


# ══════════════════════════════════════════════════════════════════
#  CHROMATIC ABERRATION SHAKE
# ══════════════════════════════════════════════════════════════════

def apply_chromatic_aberration(canvas: np.ndarray,
                               frame_idx: int) -> np.ndarray:
    """
    Split R and B channels, shift them by different random amounts.
    Creates a glitchy RGB split effect.
    """
    rng  = np.random.RandomState(frame_idx * 13 + 5)
    sr_x = int(rng.randint(-CHROMA_SHIFT, CHROMA_SHIFT+1))
    sr_y = int(rng.randint(-CHROMA_SHIFT//2, CHROMA_SHIFT//2+1))
    sb_x = -sr_x + int(rng.randint(-3, 4))
    sb_y = -sr_y + int(rng.randint(-2, 3))

    b, g, r = cv2.split(canvas)

    Mr = np.float32([[1, 0, sr_x], [0, 1, sr_y]])
    Mb = np.float32([[1, 0, sb_x], [0, 1, sb_y]])

    r_shifted = cv2.warpAffine(r, Mr, (W, H),
                                borderMode=cv2.BORDER_REPLICATE)
    b_shifted = cv2.warpAffine(b, Mb, (W, H),
                                borderMode=cv2.BORDER_REPLICATE)

    return cv2.merge([b_shifted, g, r_shifted])


def apply_shake(canvas: np.ndarray, frame_idx: int) -> np.ndarray:
    rng = np.random.RandomState(frame_idx * 7 + 13)
    sx  = int(rng.randint(-SHAKE_AMP, SHAKE_AMP+1))
    sy  = int(rng.randint(-SHAKE_AMP//2, SHAKE_AMP//2+1))
    M   = np.float32([[1, 0, sx], [0, 1, sy]])
    return cv2.warpAffine(canvas, M, (W, H),
                          borderMode=cv2.BORDER_REPLICATE)


# ══════════════════════════════════════════════════════════════════
#  KEN BURNS
# ══════════════════════════════════════════════════════════════════

def apply_ken_burns(frame: np.ndarray,
                    idx: int, total: int) -> np.ndarray:
    t     = idx / max(1, total-1)
    scale = KB_START + t * (KB_END - KB_START)
    if abs(scale-1.0) < 0.002:
        return frame
    nw  = int(W * scale); nh = int(H * scale)
    big = cv2.resize(frame, (nw, nh))
    ox  = (nw-W)//2; oy = (nh-H)//2
    return big[oy:oy+H, ox:ox+W]


# ══════════════════════════════════════════════════════════════════
#  COMPOSITE PHRASE
# ══════════════════════════════════════════════════════════════════

def composite_phrase(canvas_bgr: np.ndarray,
                     phrase_img: Image.Image,
                     frame_in: int,
                     frame_out: int,
                     entrance: str,
                     pos_x: int,
                     pos_y: int,
                     alpha_override: float = None) -> None:
    iw, ih = phrase_img.size

    if frame_in < ANIM_IN_FRAMES:
        t      = frame_in / ANIM_IN_FRAMES
        e      = elastic_overshoot(t)
        scale  = e
        alpha  = min(1.0, t * 3.0)

        # Position offset during entrance
        if entrance == "fly_left":
            x_off = int((1-t) * (-iw - 80))
            y_off = 0
        elif entrance == "fly_right":
            x_off = int((1-t) * (W + 80))
            y_off = 0
        elif entrance in ("fly_top", "vertical"):
            x_off = 0
            y_off = int((1-t) * (-ih - 80))
        else:
            x_off = y_off = 0

        # Apply motion blur during entrance
        if entrance in ("fly_left", "fly_right", "fly_top"):
            phrase_img = apply_motion_blur(phrase_img, entrance, t)

    elif frame_out < ANIM_OUT_FRAMES:
        scale = 1.0
        alpha = frame_out / ANIM_OUT_FRAMES
        x_off = y_off = 0
    else:
        scale = 1.0
        alpha = 1.0
        x_off = y_off = 0

    if alpha_override is not None:
        alpha = alpha_override

    # Apply scale
    disp = phrase_img
    if abs(scale - 1.0) > 0.01:
        nw   = max(1, int(iw * scale))
        nh   = max(1, int(ih * scale))
        disp = phrase_img.resize((nw, nh), Image.LANCZOS)

    # Dynamic position
    px = pos_x - disp.width  // 2 + x_off
    py = pos_y - disp.height // 2 + y_off
    px = max(-disp.width,  min(W, px))
    py = max(-disp.height, min(H, py))

    # Convert and composite
    canvas_rgb = cv2.cvtColor(canvas_bgr, cv2.COLOR_BGR2RGB)
    canvas_pil = Image.fromarray(canvas_rgb).convert("RGBA")

    r, g, b, a = disp.split()
    a    = a.point(lambda v: int(v * max(0.0, min(1.0, alpha))))
    disp = Image.merge("RGBA", (r, g, b, a))

    canvas_pil.alpha_composite(disp, (max(0, px), max(0, py)))
    result = cv2.cvtColor(
        np.array(canvas_pil.convert("RGB")), cv2.COLOR_RGB2BGR
    )
    np.copyto(canvas_bgr, result)


# ══════════════════════════════════════════════════════════════════
#  CAPS FLASH
# ══════════════════════════════════════════════════════════════════

def apply_caps_flash(canvas: np.ndarray,
                     intensity: float) -> np.ndarray:
    overlay = np.full_like(canvas, (60, 30, 180), dtype=np.uint8)
    return cv2.addWeighted(canvas, 1-intensity*0.20,
                           overlay, intensity*0.20, 0)


# ══════════════════════════════════════════════════════════════════
#  MAIN RENDER
# ══════════════════════════════════════════════════════════════════

def render_video(phrases: list,
                 rms_arr: np.ndarray,
                 wave_arr: np.ndarray,
                 duration: float,
                 bg_bgr: tuple,
                 word_bgr: tuple) -> None:

    n_frames     = len(rms_arr)
    vignette     = build_vignette()
    climax_start = int((duration - CLIMAX_SECS) * FPS)

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    temp   = "raw_temp.mp4"
    writer = cv2.VideoWriter(temp, fourcc, FPS, (W, H))
    if not writer.isOpened():
        sys.exit("[ERROR] VideoWriter failed")

    print(f"[RENDER] {n_frames} frames | {len(phrases)} phrases")

    # Pre-render phrase images
    for p in phrases:
        p["img"] = render_phrase_image(
            p["text"], p["has_caps"], p["has_quotes"],
            word_bgr, p["is_climax"]
        )
        p["sf"] = int(p["start_sec"] * FPS)
        p["ef"] = min(int(p["end_sec"] * FPS), n_frames)

    frame_phrase = {}
    for pi, p in enumerate(phrases):
        p["pi"] = pi
        for f in range(p["sf"], p["ef"]):
            frame_phrase[f] = p

    caps_flash   = 0
    prev_phrase  = None
    log_step     = max(1, n_frames // 20)

    for i in range(n_frames):
        is_climax = i >= climax_start

        # ── Background ───────────────────────────────────────────
        canvas = np.full((H, W, 3), bg_bgr, dtype=np.uint8)

        # ── Gradient Waveform ────────────────────────────────────
        draw_gradient_waveform(canvas, wave_arr[i],
                               rms_arr[i], is_climax)

        # ── Stagger: previous phrase lingers ─────────────────────
        cur = frame_phrase.get(i)
        if (prev_phrase is not None and cur is not None
                and cur["pi"] != prev_phrase["pi"]):
            since_end = i - prev_phrase["ef"]
            if since_end < LINGER_FRAMES:
                la = LINGER_ALPHA * (1 - since_end/LINGER_FRAMES)
                composite_phrase(
                    canvas, prev_phrase["img"],
                    prev_phrase["ef"]-prev_phrase["sf"], 999,
                    prev_phrase["entrance"],
                    prev_phrase["rand_x"], prev_phrase["rand_y"],
                    alpha_override=la
                )

        # ── Active phrase ─────────────────────────────────────────
        if cur is not None:
            fi = i - cur["sf"]
            fo = cur["ef"] - i
            if (cur["has_caps"] and
                    (prev_phrase is None
                     or cur["pi"] != prev_phrase["pi"])):
                caps_flash = 2
            composite_phrase(canvas, cur["img"],
                             fi, fo, cur["entrance"],
                             cur["rand_x"], cur["rand_y"])
            prev_phrase = cur

        # ── CAPS flash ────────────────────────────────────────────
        if caps_flash > 0:
            canvas = apply_caps_flash(canvas, caps_flash/2)
            caps_flash -= 1

        # ── Vignette ─────────────────────────────────────────────
        cf     = canvas.astype(np.float32)/255.0 * vignette
        canvas = (cf*255).clip(0,255).astype(np.uint8)

        # ── Ken Burns ────────────────────────────────────────────
        canvas = apply_ken_burns(canvas, i, n_frames)

        # ── Film Grain ───────────────────────────────────────────
        canvas = apply_film_grain(canvas, i)

        # ── Climax: chromatic aberration + shake ─────────────────
        if is_climax:
            canvas = apply_chromatic_aberration(canvas, i)
            canvas = apply_shake(canvas, i)

        writer.write(canvas)
        if i % log_step == 0:
            pct = int(i/n_frames*100)
            tag = "🔥" if is_climax else ""
            print(f"  [RENDER] {pct}% {tag}")

    writer.release()
    print("[RENDER] Re-encoding...")

    cmd = ["ffmpeg", "-y", "-i", temp,
           "-c:v", "libx264", "-preset", "fast",
           "-crf", "17", "-pix_fmt", "yuv420p", "-an",
           str(OUTPUT_VIDEO)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
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
    print("  Cinematic Kinetic Engine v4")
    print("  Grain · Chroma · Gradient Wave · Elastic · Glow")
    print("=" * 62)

    ensure_font()

    if not INPUT_AUDIO.exists():
        download_audio()

    if not INPUT_SCRIPT.exists():
        sys.exit("[ERROR] script.txt not found")
    raw   = INPUT_SCRIPT.read_text(encoding="utf-8")
    clean = clean_script(raw)
    print(f"[INFO] Script: {len(clean.split())} words")

    bg_bgr   = random.choice(BACKGROUNDS_BGR)
    word_bgr = random.choice(WORD_COLORS_BGR)

    cmd = ["ffprobe", "-v", "error",
           "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1",
           str(INPUT_AUDIO)]
    duration = float(subprocess.run(
        cmd, capture_output=True, text=True).stdout.strip())
    n_frames = int(duration * FPS)
    print(f"[INFO] Duration: {duration:.2f}s | Frames: {n_frames}")

    print("[TTS] Computing word timestamps...")
    word_timestamps = asyncio.run(generate_tts_with_timing(clean))

    if not word_timestamps:
        words = clean.split()
        d     = duration / max(1, len(words))
        word_timestamps = [
            {"word": w, "start": i*d, "duration": d}
            for i, w in enumerate(words)
        ]

    phrases  = group_into_phrases(word_timestamps, duration)
    rms_arr, wave_arr, _ = analyse_audio(str(INPUT_AUDIO), n_frames)

    render_video(phrases, rms_arr, wave_arr, duration,
                 bg_bgr, word_bgr)

    print("\n" + "=" * 62)
    print("  [✓] DONE — raw_video.mp4 ready")
    print("=" * 62)


if __name__ == "__main__":
    main()
