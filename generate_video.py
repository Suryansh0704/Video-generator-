"""
generate_video.py — Cinematic Kinetic Engine v5
================================================
Warm fruit-tone backgrounds: Peach, Pink, Coral, Apricot etc.
Dark rich word colors for contrast on light backgrounds.
Text fully clamped to screen — never goes off edge.
Colorful 35% random accent words + ALL CAPS neon glow.
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

# ══════════════════════════════════════════════════════════════════
#  COLOUR PALETTE
# ══════════════════════════════════════════════════════════════════

# Warm fruit-tone backgrounds — BGR format
BACKGROUNDS_BGR = [
    (185, 175, 255),   # Peach
    (193, 182, 255),   # Apricot
    (170, 160, 255),   # Nectarine
    (200, 182, 255),   # Creamsicle
    (180, 160, 250),   # Papaya
    (190, 150, 240),   # Guava
    (170, 140, 255),   # Salmon
    (160, 130, 255),   # Coral
    (175, 120, 240),   # Terra Cotta
    (200, 170, 255),   # Melon
    (210, 190, 255),   # Shell Pink
    (180, 180, 255),   # Pink (warm)
    (130, 210, 150),   # Lime
    (140, 200, 255),   # Soft Orange
]

# Dark word colors — rich and readable on warm light backgrounds
WORD_COLORS_BGR = [
    (25,  20,  100),   # Deep burgundy
    (15,  40,  130),   # Deep brown-red
    (10,  60,  120),   # Chocolate
    (30,  20,  140),   # Dark crimson
    (50,  30,  110),   # Deep plum
    (20,  80,  100),   # Dark burnt orange
    (40,  25,  120),   # Rich maroon
    (10,  50,  90),    # Mahogany
]

# Accent colors — vivid, pop on warm backgrounds
ACCENT_COLORS_BGR = [
    (20,  10,  200),   # Deep red
    (10,  80,  220),   # Bright orange
    (0,   150, 200),   # Deep gold
    (80,  20,  180),   # Purple-red
    (0,   100, 180),   # Burnt amber
    (40,  0,   160),   # Dark crimson accent
    (100, 40,  200),   # Violet-red
]

# Waveform — dark so it shows on light background
WAVE_COLORS_BGR = [
    (60,  30,  140),   # Deep purple
    (20,  20,  180),   # Deep crimson
    (30,  80,  160),   # Dark burnt orange
    (10,  60,  120),   # Dark chocolate
    (80,  20,  160),   # Deep plum
]

# ── Typography ───────────────────────────────────────────────────
WORDS_PER_PHRASE    = 4
MIN_PHRASE_HOLD_SEC = 1.2
ANIM_IN_FRAMES      = int(FPS * 0.22)
ANIM_OUT_FRAMES     = int(FPS * 0.15)
LINGER_FRAMES       = int(FPS * 0.30)
LINGER_ALPHA        = 0.40
VERTICAL_CHANCE     = 0.12
ACCENT_WORD_CHANCE  = 0.35   # 35% random words get accent color

# Safe zone — text always inside these bounds
SAFE_PAD = 40
POS_X_MIN = int(W * 0.08)
POS_X_MAX = int(W * 0.92)
POS_Y_MIN = int(H * 0.18)
POS_Y_MAX = int(H * 0.60)

# ── Physics ───────────────────────────────────────────────────────
ELASTIC_START = 0.5
ELASTIC_PEAK  = 1.15

# ── Effects ───────────────────────────────────────────────────────
GRAIN_INTENSITY = 12
GRAIN_BLEND     = 0.04
VIGNETTE_STR    = 0.45
MOTION_BLUR_PX  = 10

# ── Waveform ─────────────────────────────────────────────────────
WAVE_Y_BASE  = int(H * 0.82)
WAVE_HEIGHT  = int(H * 0.13)
WAVE_POINTS  = 200

# ── Climax ───────────────────────────────────────────────────────
CLIMAX_SECS   = 5.0
SHAKE_AMP     = 10
CHROMA_SHIFT  = 8
CLIMAX_WAVE_MULT = 2.0

# ── Ken Burns ────────────────────────────────────────────────────
KB_START = 1.0
KB_END   = 1.10


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
            print("[FONT] ✅ Downloaded")
            return
    except Exception as e:
        print(f"[FONT] Download failed: {e}")
    ttfs   = glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)
    bold   = [f for f in ttfs if "bold" in f.lower()]
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
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github+json"}
    res = requests.get(
        "https://api.github.com/repos/Suryansh0704/Audio-generator-/actions/artifacts",
        headers=headers)
    artifacts = res.json().get("artifacts", [])
    if not artifacts:
        sys.exit("[ERROR] No artifacts found")
    latest = artifacts[0]
    print(f"[AUDIO] Downloading {latest['name']}...")
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
        s = int(i * spf); e = min(int(s+spf), len(y))
        chunk = y[s:e]
        if not len(chunk): continue
        rms_arr[i] = float(np.sqrt(np.mean(chunk**2)))
        if len(chunk) >= WAVE_POINTS:
            idx = np.linspace(0, len(chunk)-1, WAVE_POINTS).astype(int)
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

def group_into_phrases(word_timestamps: list,
                       duration: float,
                       accent_bgr: tuple) -> list:
    phrases      = []
    climax_start = duration - CLIMAX_SECS
    entrances    = ["fly_left", "fly_right", "fly_top",
                    "fly_left", "fly_right"]

    # Pre-assign accent to 35% of phrase indices
    n_total       = max(1, len(word_timestamps) // WORDS_PER_PHRASE)
    accent_set    = set(random.sample(
        range(n_total), max(1, int(n_total * ACCENT_WORD_CHANCE))
    ))

    i = 0
    pi = 0
    while i < len(word_timestamps):
        group = word_timestamps[i:i + WORDS_PER_PHRASE]
        text  = ' '.join(w["word"] for w in group)
        clean = re.sub(r'[^a-zA-Z0-9\'\-!?.,"\s]', '', text).strip()
        if not clean:
            i += WORDS_PER_PHRASE
            pi += 1
            continue

        start_sec = group[0]["start"]
        end_sec   = group[-1]["start"] + group[-1]["duration"]
        if end_sec - start_sec < MIN_PHRASE_HOLD_SEC:
            end_sec = start_sec + MIN_PHRASE_HOLD_SEC

        has_caps   = bool(re.search(r'[A-Z]{2,}', text))
        has_quotes = '"' in text
        is_climax  = start_sec >= climax_start
        use_accent = has_caps or has_quotes or (pi in accent_set)

        entrance = "vertical" if random.random() < VERTICAL_CHANCE \
                   else random.choice(entrances)

        # Safe random position — anchor point for centering
        rand_x = random.randint(POS_X_MIN, POS_X_MAX)
        rand_y = random.randint(POS_Y_MIN, POS_Y_MAX)

        # Pick word color for this phrase
        if use_accent:
            phrase_color = accent_bgr
        else:
            phrase_color = random.choice(WORD_COLORS_BGR)

        phrases.append({
            "text":         clean,
            "start_sec":    start_sec,
            "end_sec":      end_sec,
            "has_caps":     has_caps,
            "has_quotes":   has_quotes,
            "is_climax":    is_climax,
            "entrance":     entrance,
            "rand_x":       rand_x,
            "rand_y":       rand_y,
            "phrase_color": phrase_color,
            "use_accent":   use_accent,
        })
        i  += WORDS_PER_PHRASE
        pi += 1

    if phrases:
        phrases[-1]["is_climax"] = True

    print(f"[PHRASE] {len(phrases)} phrases | "
          f"{sum(1 for p in phrases if p['use_accent'])} accented")
    return phrases


# ══════════════════════════════════════════════════════════════════
#  EASING
# ══════════════════════════════════════════════════════════════════

def elastic_overshoot(t: float) -> float:
    if t <= 0: return 0.0
    if t >= 1: return 1.0
    raw = 1 + (2**(-10*t)) * math.sin((t-0.075)*2*math.pi/0.3)
    return ELASTIC_START + raw * (1.0 - ELASTIC_START)


# ══════════════════════════════════════════════════════════════════
#  MOTION BLUR
# ══════════════════════════════════════════════════════════════════

def apply_motion_blur(img: Image.Image,
                      entrance: str, t: float) -> Image.Image:
    if t > 0.5 or entrance == "vertical":
        return img
    blur_px = int(MOTION_BLUR_PX * (1 - t * 2))
    if blur_px < 2:
        return img
    arr = np.array(img, dtype=np.float32)
    if entrance in ("fly_left", "fly_right"):
        kernel = np.ones((1, blur_px), dtype=np.float32) / blur_px
    else:
        kernel = np.ones((blur_px, 1), dtype=np.float32) / blur_px
    blurred = np.zeros_like(arr)
    for c in range(arr.shape[2]):
        blurred[:,:,c] = cv2.filter2D(arr[:,:,c], -1, kernel)
    return Image.fromarray(blurred.astype(np.uint8))


# ══════════════════════════════════════════════════════════════════
#  PHRASE IMAGE RENDERER
# ══════════════════════════════════════════════════════════════════

def render_phrase_image(text: str,
                        has_caps: bool,
                        has_quotes: bool,
                        phrase_color: tuple,
                        accent_bgr: tuple,
                        use_accent: bool,
                        is_climax: bool = False) -> Image.Image:
    words       = text.split()
    NORMAL_SIZE = 98
    CAPS_SIZE   = 124
    LINE_SP     = 24
    PAD         = 36

    word_data = []
    for w in words:
        is_cap = bool(re.search(r'[A-Z]{2,}', w))
        is_qot = w.startswith('"') or w.startswith("'")
        is_acc = is_cap or is_qot or use_accent
        size   = CAPS_SIZE if is_cap else NORMAL_SIZE
        if is_climax:
            size = int(size * 1.06)
        # Each word gets phrase_color — accent words get accent
        color  = accent_bgr if is_acc else phrase_color
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

    # Line wrapping — max width is canvas width minus safe margins
    max_w  = W - 120
    lines, cur, cw = [], [], 0
    for wd in word_data:
        if cw + wd["w"] + 18 > max_w and cur:
            lines.append(cur); cur, cw = [wd], wd["w"]
        else:
            cur.append(wd); cw += wd["w"] + 18
    if cur:
        lines.append(cur)

    lh_list = [max(wd["h"] for wd in l) for l in lines]
    tot_h   = sum(lh_list) + LINE_SP*(len(lines)-1) + PAD*2
    tot_w   = W - 80

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
                # Neon glow passes for accented words
                glow_rgb = tuple(min(255, int(c*1.3)) for c in rgb)
                for gd, ga in [(7, 50), (4, 90), (2, 130)]:
                    draw.text((x+gd, y),   wd["text"],
                              font=wd["font"], fill=glow_rgb+(ga,))
                    draw.text((x-gd, y),   wd["text"],
                              font=wd["font"], fill=glow_rgb+(ga,))
                    draw.text((x, y+gd),   wd["text"],
                              font=wd["font"], fill=glow_rgb+(ga,))
                    draw.text((x, y-gd),   wd["text"],
                              font=wd["font"], fill=glow_rgb+(ga,))
                # Underline
                ul_y = y + wd["h"] + 4
                draw.line([(x, ul_y), (x+wd["w"], ul_y)],
                          fill=rgb+(210,), width=3)
            else:
                # Light shadow on light background — use dark tone
                draw.text((x+2, y+2), wd["text"], font=wd["font"],
                          fill=(20,20,20,100))

            draw.text((x, y), wd["text"],
                      font=wd["font"], fill=rgb+(255,))
            x += wd["w"] + 18

        y += lh + LINE_SP

    return img


# ══════════════════════════════════════════════════════════════════
#  GRADIENT WAVEFORM (dark on light background)
# ══════════════════════════════════════════════════════════════════

def draw_gradient_waveform(canvas: np.ndarray,
                           wave: np.ndarray,
                           rms: float,
                           wave_bgr: tuple,
                           accent_bgr: tuple,
                           is_climax: bool) -> None:
    amp_mult  = CLIMAX_WAVE_MULT if is_climax else 1.0
    base_ht   = WAVE_HEIGHT
    amp       = base_ht * (0.15 + rms * 0.85) * amp_mult
    amp       = min(amp, base_ht * 1.8)

    xs   = np.linspace(80, W-80, WAVE_POINTS).astype(int)
    kern = np.ones(9) / 9
    ws   = np.convolve(wave, kern, mode='same')
    ys   = np.clip((WAVE_Y_BASE - ws * amp).astype(int), 10, H-10)

    col      = accent_bgr if is_climax else wave_bgr
    center_i = WAVE_POINTS // 2

    for i in range(WAVE_POINTS - 1):
        dist       = abs(i - center_i) / center_i
        brightness = max(0.25, 1.0 - dist * 0.70)
        c          = tuple(int(v * brightness) for v in col)
        glow_c     = tuple(max(0, int(v * brightness * 0.5)) for v in col)
        pt1        = (int(xs[i]),   int(ys[i]))
        pt2        = (int(xs[i+1]), int(ys[i+1]))
        cv2.line(canvas, pt1, pt2, glow_c, 10, cv2.LINE_AA)
        cv2.line(canvas, pt1, pt2, c,       3, cv2.LINE_AA)

    pi  = int(np.argmax(np.abs(ws)))
    px, py = int(xs[pi]), int(ys[pi])
    cv2.circle(canvas, (px, py), 5, col, -1)
    cv2.circle(canvas, (px, py), 9, col,  2)


# ══════════════════════════════════════════════════════════════════
#  FILM GRAIN
# ══════════════════════════════════════════════════════════════════

def apply_film_grain(canvas: np.ndarray, frame_idx: int) -> np.ndarray:
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
    mask  = 1.0 - np.clip(dist / dist.max() * VIGNETTE_STR, 0, 1)
    return mask.reshape(H, W, 1).astype(np.float32)


# ══════════════════════════════════════════════════════════════════
#  CHROMATIC ABERRATION + SHAKE
# ══════════════════════════════════════════════════════════════════

def apply_chromatic_aberration(canvas: np.ndarray,
                               frame_idx: int) -> np.ndarray:
    rng  = np.random.RandomState(frame_idx * 13 + 5)
    sr_x = int(rng.randint(-CHROMA_SHIFT, CHROMA_SHIFT+1))
    sr_y = int(rng.randint(-CHROMA_SHIFT//2, CHROMA_SHIFT//2+1))
    sb_x, sb_y = -sr_x + int(rng.randint(-3,4)), -sr_y + int(rng.randint(-2,3))
    b, g, r = cv2.split(canvas)
    Mr = np.float32([[1,0,sr_x],[0,1,sr_y]])
    Mb = np.float32([[1,0,sb_x],[0,1,sb_y]])
    r  = cv2.warpAffine(r, Mr, (W,H), borderMode=cv2.BORDER_REPLICATE)
    b  = cv2.warpAffine(b, Mb, (W,H), borderMode=cv2.BORDER_REPLICATE)
    return cv2.merge([b, g, r])


def apply_shake(canvas: np.ndarray, frame_idx: int) -> np.ndarray:
    rng = np.random.RandomState(frame_idx * 7 + 13)
    sx  = int(rng.randint(-SHAKE_AMP, SHAKE_AMP+1))
    sy  = int(rng.randint(-SHAKE_AMP//2, SHAKE_AMP//2+1))
    M   = np.float32([[1,0,sx],[0,1,sy]])
    return cv2.warpAffine(canvas, M, (W,H),
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
    nw  = int(W*scale); nh = int(H*scale)
    big = cv2.resize(frame, (nw, nh))
    ox  = (nw-W)//2; oy = (nh-H)//2
    return big[oy:oy+H, ox:ox+W]


# ══════════════════════════════════════════════════════════════════
#  COMPOSITE PHRASE — fully clamped to screen
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
        t     = frame_in / ANIM_IN_FRAMES
        e     = elastic_overshoot(t)
        scale = e
        alpha = min(1.0, t * 3.0)
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

    disp = phrase_img
    if abs(scale - 1.0) > 0.01:
        nw   = max(1, int(iw * scale))
        nh   = max(1, int(ih * scale))
        disp = phrase_img.resize((nw, nh), Image.LANCZOS)

    # Anchor to center of phrase
    px = pos_x - disp.width  // 2 + x_off
    py = pos_y - disp.height // 2 + y_off

    # HARD CLAMP — never go off any edge
    px = max(SAFE_PAD, min(W - disp.width  - SAFE_PAD, px))
    py = max(SAFE_PAD, min(H - disp.height - SAFE_PAD, py))

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
                     intensity: float,
                     accent_bgr: tuple) -> np.ndarray:
    overlay = np.full_like(canvas, accent_bgr, dtype=np.uint8)
    return cv2.addWeighted(canvas, 1-intensity*0.15,
                           overlay, intensity*0.15, 0)


# ══════════════════════════════════════════════════════════════════
#  MAIN RENDER
# ══════════════════════════════════════════════════════════════════

def render_video(phrases: list,
                 rms_arr: np.ndarray,
                 wave_arr: np.ndarray,
                 duration: float,
                 bg_bgr: tuple,
                 accent_bgr: tuple,
                 wave_bgr: tuple) -> None:

    n_frames     = len(rms_arr)
    vignette     = build_vignette()
    climax_start = int((duration - CLIMAX_SECS) * FPS)

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    temp   = "raw_temp.mp4"
    writer = cv2.VideoWriter(temp, fourcc, FPS, (W, H))
    if not writer.isOpened():
        sys.exit("[ERROR] VideoWriter failed")

    print(f"[RENDER] {n_frames} frames | {len(phrases)} phrases")
    print(f"[RENDER] BG={bg_bgr} | Accent={accent_bgr}")

    # Pre-render phrase images
    print("[RENDER] Pre-rendering phrases...")
    for p in phrases:
        p["img"] = render_phrase_image(
            p["text"], p["has_caps"], p["has_quotes"],
            p["phrase_color"], accent_bgr,
            p["use_accent"], p["is_climax"]
        )
        p["sf"] = int(p["start_sec"] * FPS)
        p["ef"] = min(int(p["end_sec"] * FPS), n_frames)

    frame_phrase = {}
    for pi, p in enumerate(phrases):
        p["pi"] = pi
        for f in range(p["sf"], p["ef"]):
            frame_phrase[f] = p

    caps_flash  = 0
    prev_phrase = None
    log_step    = max(1, n_frames // 20)

    for i in range(n_frames):
        is_climax = i >= climax_start

        # Background
        canvas = np.full((H, W, 3), bg_bgr, dtype=np.uint8)

        # Waveform
        draw_gradient_waveform(canvas, wave_arr[i], rms_arr[i],
                               wave_bgr, accent_bgr, is_climax)

        cur = frame_phrase.get(i)

        # Stagger linger
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

        # Active phrase
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

        # CAPS flash
        if caps_flash > 0:
            canvas = apply_caps_flash(canvas, caps_flash/2, accent_bgr)
            caps_flash -= 1

        # Vignette
        cf     = canvas.astype(np.float32)/255.0 * vignette
        canvas = (cf*255).clip(0,255).astype(np.uint8)

        # Ken Burns
        canvas = apply_ken_burns(canvas, i, n_frames)

        # Film grain
        canvas = apply_film_grain(canvas, i)

        # Climax effects
        if is_climax:
            canvas = apply_chromatic_aberration(canvas, i)
            canvas = apply_shake(canvas, i)

        writer.write(canvas)
        if i % log_step == 0:
            print(f"  [RENDER] {int(i/n_frames*100)}%"
                  f"{'  🔥 CLIMAX' if is_climax else ''}")

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
    print("  Cinematic Kinetic Engine v5")
    print("  Warm Fruit Tones · Dark Words · Fully Bounded")
    print("=" * 62)

    ensure_font()

    if not INPUT_AUDIO.exists():
        download_audio()

    if not INPUT_SCRIPT.exists():
        sys.exit("[ERROR] script.txt not found")
    raw   = INPUT_SCRIPT.read_text(encoding="utf-8")
    clean = clean_script(raw)
    print(f"[INFO] Script: {len(clean.split())} words")

    bg_bgr     = random.choice(BACKGROUNDS_BGR)
    accent_bgr = random.choice(ACCENT_COLORS_BGR)
    wave_bgr   = random.choice(WAVE_COLORS_BGR)

    cmd = ["ffprobe", "-v", "error",
           "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1",
           str(INPUT_AUDIO)]
    duration = float(subprocess.run(
        cmd, capture_output=True, text=True).stdout.strip())
    n_frames = int(duration * FPS)
    print(f"[INFO] Duration: {duration:.2f}s | BG: {bg_bgr}")

    print("[TTS] Computing word timestamps...")
    word_timestamps = asyncio.run(generate_tts_with_timing(clean))

    if not word_timestamps:
        words = clean.split()
        d     = duration / max(1, len(words))
        word_timestamps = [
            {"word": w, "start": i*d, "duration": d}
            for i, w in enumerate(words)
        ]

    phrases  = group_into_phrases(word_timestamps, duration, accent_bgr)
    rms_arr, wave_arr, _ = analyse_audio(str(INPUT_AUDIO), n_frames)

    render_video(phrases, rms_arr, wave_arr, duration,
                 bg_bgr, accent_bgr, wave_bgr)

    print("\n" + "=" * 62)
    print("  [✓] DONE — raw_video.mp4 ready")
    print("=" * 62)


if __name__ == "__main__":
    main()
