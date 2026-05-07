"""
generate_video.py — Premium Scrapbook Engine v7
================================================
Safe-zone 150px · Radial gradient backgrounds
Elastic physics · GIF/PNG stickers with rotation
Filled area waveform · Climax shake + color oscillation
Paper grain texture · Continuous zoom 1.0→1.15x
100% headless — GitHub Actions
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
#  CANVAS & SAFE ZONE
# ══════════════════════════════════════════════════════════════════

W, H        = 1080, 1920
FPS         = 30
SAFE_PAD    = 150                   # 150px internal margin all sides
SAFE_X1     = SAFE_PAD
SAFE_X2     = W - SAFE_PAD
SAFE_Y1     = SAFE_PAD
SAFE_Y2     = H - SAFE_PAD
SAFE_W      = SAFE_X2 - SAFE_X1    # 780px usable width
SAFE_H      = SAFE_Y2 - SAFE_Y1    # 1620px usable height

# Center 60% positioning zone
POS_X_MIN   = SAFE_X1 + int(SAFE_W * 0.05)
POS_X_MAX   = SAFE_X2 - int(SAFE_W * 0.05)
POS_Y_MIN   = SAFE_Y1 + int(SAFE_H * 0.10)
POS_Y_MAX   = int(H * 0.60)

# ══════════════════════════════════════════════════════════════════
#  PATHS
# ══════════════════════════════════════════════════════════════════

VOICE        = "en-GB-RyanNeural"
PITCH        = "-2Hz"
RATE         = "+15%"

INPUT_SCRIPT = Path("script.txt")
INPUT_AUDIO  = Path("output_voice.wav")
AUDIO_MP3    = Path("output_raw.mp3")
OUTPUT_VIDEO = Path("raw_video.mp4")
ASSETS_DIR   = Path("assets")
FONT_PATH    = Path("Montserrat-Bold.ttf")
FONT_URL     = "https://github.com/google/fonts/raw/main/ofl/montserrat/static/Montserrat-Bold.ttf"

# ══════════════════════════════════════════════════════════════════
#  COLOUR PALETTE
# ══════════════════════════════════════════════════════════════════

# Radial gradients (center_BGR, edge_BGR)
PALETTES = [
    ((185,175,255),(120,105,195)),  # Peach
    ((193,182,255),(128,112,200)),  # Apricot
    ((200,180,255),(135,110,200)),  # Creamsicle
    ((180,160,250),(115, 90,195)),  # Papaya
    ((190,150,240),(120, 80,185)),  # Guava
    ((165,140,255),(100, 75,195)),  # Salmon
    ((155,125,255),(90,  60,195)),  # Coral
    ((170,120,240),(100, 55,180)),  # Terra Cotta
    ((200,170,255),(130,100,200)),  # Melon
    ((210,190,255),(140,120,205)),  # Shell Pink
    ((185,185,255),(115,115,205)),  # Pink
    ((130,215,150),(60, 145, 80)),  # Lime
    ((140,200,255),(70, 130,205)),  # Soft Orange
]

# Climax oscillation pairs (two warm tones)
CLIMAX_PAIRS = [
    (((165,140,255),(100,75,195)), ((155,125,255),(90,60,195))),
    (((200,180,255),(135,110,200)),((185,175,255),(120,105,195))),
    (((130,215,150),(60,145,80)), ((140,200,255),(70,130,205))),
    (((170,120,240),(100,55,180)),((190,150,240),(120,80,185))),
]

# Text — Dark Espresso / Deep Charcoal
TEXT_PRIMARY   = (29, 27, 45)    # BGR: Dark Espresso #2D1B1B
TEXT_SECONDARY = (40, 35, 55)    # BGR: Deep Charcoal
TEXT_ACCENT_OPTIONS = [
    (30,  10, 180),   # Deep crimson
    (10,  50, 200),   # Burnt sienna
    (50,  20, 160),   # Dark plum
    (20, 100, 190),   # Rich amber
    (0,   80, 170),   # Dark gold
]

# Waveform — tone-on-tone (slightly darker than bg center)
WAVE_DARKEN = 0.55   # How much darker than bg center

# ══════════════════════════════════════════════════════════════════
#  TYPOGRAPHY
# ══════════════════════════════════════════════════════════════════

FONT_SIZE_BASE  = 96
FONT_SIZE_MIN   = 58       # Shrink long lines to fit
FONT_SIZE_CAPS  = 118
LINE_SPACING    = 26
WORDS_PER_PHRASE = 4
MIN_PHRASE_SEC  = 1.2
ACCENT_CHANCE   = 0.30

# ══════════════════════════════════════════════════════════════════
#  ANIMATION
# ══════════════════════════════════════════════════════════════════

ANIM_IN  = int(FPS * 0.20)
ANIM_OUT = int(FPS * 0.15)
KB_START = 1.0
KB_END   = 1.15

# ══════════════════════════════════════════════════════════════════
#  STICKER
# ══════════════════════════════════════════════════════════════════

STICKER_SIZE        = 200
STICKER_BORDER      = 10
STICKER_SHADOW      = 8
STICKER_FLOAT_AMP   = 14
STICKER_FLOAT_SPEED = 0.07
STICKER_ANIM_FRAMES = int(FPS * 0.25)
STICKER_ROT_RANGE   = 15    # ±15 degrees

# Keywords → asset filenames (png or gif)
STICKER_KEYWORDS = {
    "shocked": ["shocked.gif","shocked.png"],
    "fire":    ["fire.gif",   "fire.png"],
    "cat":     ["cat.gif",    "cat.png"],
    "aura":    ["aura.gif",   "aura.png"],
    "win":     ["win.gif",    "win.png"],
    "love":    ["love.gif",   "love.png"],
    "brain":   ["brain.gif",  "brain.png"],
    "star":    ["star.gif",   "star.png"],
    "ghost":   ["ghost.gif",  "ghost.png"],
    "crown":   ["crown.gif",  "crown.png"],
    "money":   ["money.gif",  "money.png"],
    "rocket":  ["rocket.gif", "rocket.png"],
    "wow":     ["shocked.gif","shocked.png"],
    "amazing": ["star.gif",   "star.png"],
}

# Sticker safe corners — well away from text zone
STICKER_CORNERS = [
    (SAFE_X1 + 10, SAFE_Y1 + 10),
    (SAFE_X2 - STICKER_SIZE - 10, SAFE_Y1 + 10),
    (SAFE_X1 + 10, int(H*0.72)),
    (SAFE_X2 - STICKER_SIZE - 10, int(H*0.72)),
]

# ══════════════════════════════════════════════════════════════════
#  EFFECTS
# ══════════════════════════════════════════════════════════════════

GRAIN_STRENGTH  = 0.05
VIGNETTE_STR    = 0.60
CLIMAX_SECS     = 5.0
SHAKE_AMP       = 14
MOTION_BLUR_PX  = 10
WAVE_Y          = int(H * 0.82)
WAVE_H          = int(H * 0.13)
WAVE_POINTS     = 220


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
            print("[FONT] ✅ Downloaded")
            return
    except Exception as e:
        print(f"[FONT] Download failed: {e}")
    ttfs = glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)
    bold = [f for f in ttfs if "bold" in f.lower()]
    src  = bold[0] if bold else (ttfs[0] if ttfs else None)
    if src:
        shutil.copy(src, str(FONT_PATH))
        print(f"[FONT] System fallback: {src}")


def get_font(size: int) -> ImageFont.FreeTypeFont:
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
    hdrs = {"Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json"}
    res  = requests.get(
        "https://api.github.com/repos/Suryansh0704/Audio-generator-/actions/artifacts",
        headers=hdrs)
    arts = res.json().get("artifacts", [])
    if not arts:
        sys.exit("[ERROR] No audio artifacts")
    latest = arts[0]
    r = requests.get(latest["archive_download_url"], headers=hdrs)
    with open("audio.zip","wb") as f: f.write(r.content)
    with zipfile.ZipFile("audio.zip") as z: z.extractall("audio_extracted")
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
    text = text.encode('ascii','ignore').decode('ascii')
    text = re.sub(r'[\/\\@#\$%\^&\*\(\)\[\]\{\}\|<>~`_+=]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


# ══════════════════════════════════════════════════════════════════
#  EDGE-TTS TIMESTAMPS
# ══════════════════════════════════════════════════════════════════

async def generate_tts_with_timing(text: str) -> list:
    comm  = edge_tts.Communicate(text=text, voice=VOICE,
                                  pitch=PITCH, rate=RATE)
    words, audio = [], bytearray()
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            w = chunk["text"].strip()
            if w:
                words.append({"word": w,
                               "start":    chunk["offset"]/10_000_000,
                               "duration": chunk["duration"]/10_000_000})
    AUDIO_MP3.write_bytes(bytes(audio))
    print(f"[TTS] {len(words)} timestamps")
    return words


# ══════════════════════════════════════════════════════════════════
#  AUDIO ANALYSIS
# ══════════════════════════════════════════════════════════════════

def analyse_audio(path: str, n_frames: int) -> tuple:
    y, sr    = librosa.load(str(path), sr=None, mono=True)
    duration = len(y)/sr
    spf      = len(y)/n_frames
    rms_arr  = np.zeros(n_frames, dtype=np.float32)
    wave_arr = np.zeros((n_frames, WAVE_POINTS), dtype=np.float32)
    for i in range(n_frames):
        s = int(i*spf); e = min(int(s+spf), len(y))
        c = y[s:e]
        if not len(c): continue
        rms_arr[i] = float(np.sqrt(np.mean(c**2)))
        if len(c) >= WAVE_POINTS:
            idx = np.linspace(0,len(c)-1,WAVE_POINTS).astype(int)
            wave_arr[i] = c[idx]
        else:
            wave_arr[i,:len(c)] = c
    mx = rms_arr.max()
    if mx > 0: rms_arr /= mx
    print(f"[AUDIO] {duration:.2f}s analysed")
    return rms_arr, wave_arr, duration


# ══════════════════════════════════════════════════════════════════
#  PHRASE RENDERING — SAFE ZONE ENFORCED
# ══════════════════════════════════════════════════════════════════

def measure_text(text: str, font: ImageFont.FreeTypeFont) -> tuple:
    tmp  = Image.new("RGBA",(1,1))
    draw = ImageDraw.Draw(tmp)
    bbox = draw.textbbox((0,0), text, font=font)
    return bbox[2]-bbox[0], bbox[3]-bbox[1]


def fit_font_size(words_line: str, is_cap: bool) -> tuple:
    """
    Auto-decrease font size until the line fits within SAFE_W.
    Returns (font, actual_size).
    """
    base = FONT_SIZE_CAPS if is_cap else FONT_SIZE_BASE
    for size in range(base, FONT_SIZE_MIN-1, -4):
        font = get_font(size)
        tw, _ = measure_text(words_line, font)
        if tw <= SAFE_W:
            return font, size
    return get_font(FONT_SIZE_MIN), FONT_SIZE_MIN


def wrap_words(words: list, max_width: int) -> list:
    """
    Wrap a list of word-dicts into lines that fit max_width.
    Each word-dict: {text, font, w, h, color, is_acc}
    Returns list of lines (each line = list of word-dicts).
    """
    lines, cur, cw = [], [], 0
    GAP = 16
    for wd in words:
        needed = wd["w"] + (GAP if cur else 0)
        if cur and cw + needed > max_width:
            lines.append(cur)
            cur, cw = [wd], wd["w"]
        else:
            cur.append(wd)
            cw += needed
    if cur:
        lines.append(cur)
    return lines


def render_phrase_image(text: str,
                        has_caps: bool,
                        use_accent: bool,
                        text_color: tuple,
                        accent_color: tuple) -> Image.Image:
    """
    Render phrase as RGBA PIL image.
    Auto-wraps and auto-shrinks to fit SAFE_W.
    Applies neon glow to accent/CAPS words.
    """
    raw_words = text.split()
    PAD       = 20
    GAP_X     = 16
    LINE_SP   = LINE_SPACING
    MAX_W     = SAFE_W - PAD*2

    word_data = []
    for w in raw_words:
        is_cap = bool(re.search(r'[A-Z]{2,}', w))
        is_acc = is_cap or use_accent
        color  = accent_color if is_acc else text_color

        # Try to fit individual word
        font, sz = fit_font_size(w, is_cap)
        tw, th   = measure_text(w, font)

        word_data.append({
            "text":  w,
            "font":  font,
            "sz":    sz,
            "color": color,
            "w":     tw,
            "h":     th,
            "is_acc": is_acc,
            "is_cap": is_cap,
        })

    lines   = wrap_words(word_data, MAX_W)
    lh_list = [max(wd["h"] for wd in l) for l in lines]
    tot_h   = sum(lh_list) + LINE_SP*(len(lines)-1) + PAD*2
    tot_w   = min(SAFE_W, MAX_W + PAD*2)

    img  = Image.new("RGBA", (max(1,tot_w), max(1,tot_h)), (0,0,0,0))
    draw = ImageDraw.Draw(img)

    y = PAD
    for li, line in enumerate(lines):
        lw = sum(wd["w"] for wd in line) + GAP_X*(len(line)-1)
        x  = (tot_w - lw)//2   # center each line
        lh = lh_list[li]

        for wd in line:
            rgb = (wd["color"][2], wd["color"][1], wd["color"][0])

            if wd["is_acc"]:
                # Neon glow layers
                glow = tuple(min(255, int(c*1.4)) for c in rgb)
                for gd, ga in [(8,40),(5,75),(3,110)]:
                    for dx,dy in [(gd,0),(-gd,0),(0,gd),(0,-gd)]:
                        draw.text((x+dx, y+dy), wd["text"],
                                  font=wd["font"], fill=glow+(ga,))
                draw.line([(x, y+wd["h"]+5),(x+wd["w"], y+wd["h"]+5)],
                          fill=rgb+(220,), width=3)
            else:
                # Light shadow (dark on light bg)
                draw.text((x+2,y+2), wd["text"], font=wd["font"],
                          fill=(0,0,0,80))

            draw.text((x,y), wd["text"], font=wd["font"], fill=rgb+(255,))
            x += wd["w"] + GAP_X

        y += lh + LINE_SP

    return img


# ══════════════════════════════════════════════════════════════════
#  PHRASE GROUPING
# ══════════════════════════════════════════════════════════════════

def group_into_phrases(word_timestamps: list,
                       duration: float,
                       accent_color: tuple) -> list:
    phrases       = []
    climax_start  = duration - CLIMAX_SECS
    entrances     = ["fly_left","fly_right","fly_top","fly_bottom",
                     "fly_left","fly_right"]
    n_total       = max(1, len(word_timestamps)//WORDS_PER_PHRASE)
    accent_set    = set(random.sample(
        range(n_total), max(1, int(n_total*ACCENT_CHANCE))
    ))

    prev_y = None
    i = 0; pi = 0
    while i < len(word_timestamps):
        group = word_timestamps[i:i+WORDS_PER_PHRASE]
        text  = ' '.join(w["word"] for w in group)
        clean = re.sub(r'[^a-zA-Z0-9\'\-!?.,"\s]','',text).strip()
        if not clean:
            i += WORDS_PER_PHRASE; pi += 1; continue

        start_sec = group[0]["start"]
        end_sec   = group[-1]["start"] + group[-1]["duration"]
        if end_sec - start_sec < MIN_PHRASE_SEC:
            end_sec = start_sec + MIN_PHRASE_SEC

        has_caps   = bool(re.search(r'[A-Z]{2,}', text))
        is_climax  = start_sec >= climax_start
        use_accent = has_caps or (pi in accent_set)

        entrance   = random.choice(entrances)

        # Non-overlapping Y position
        rand_x = random.randint(POS_X_MIN, POS_X_MAX)
        for _ in range(10):
            rand_y = random.randint(POS_Y_MIN, POS_Y_MAX)
            if prev_y is None or abs(rand_y - prev_y) > 200:
                break
        prev_y = rand_y

        text_col   = TEXT_PRIMARY if not use_accent else TEXT_SECONDARY
        phrase_col = accent_color if use_accent else text_col

        phrases.append({
            "text":      clean,
            "start_sec": start_sec,
            "end_sec":   end_sec,
            "has_caps":  has_caps,
            "is_climax": is_climax,
            "entrance":  entrance,
            "rand_x":    rand_x,
            "rand_y":    rand_y,
            "text_color": text_col,
            "accent_color": accent_color,
            "use_accent": use_accent,
        })
        i += WORDS_PER_PHRASE; pi += 1

    if phrases:
        phrases[-1]["is_climax"] = True
    print(f"[PHRASE] {len(phrases)} phrases")
    return phrases


# ══════════════════════════════════════════════════════════════════
#  EASING
# ══════════════════════════════════════════════════════════════════

def elastic_out(t: float) -> float:
    if t <= 0: return 0.0
    if t >= 1: return 1.0
    return 1 + (2**(-10*t)) * math.sin((t-0.075)*2*math.pi/0.3)


# ══════════════════════════════════════════════════════════════════
#  MOTION BLUR
# ══════════════════════════════════════════════════════════════════

def motion_blur(img: Image.Image, entrance: str, t: float) -> Image.Image:
    if t > 0.5: return img
    px = int(MOTION_BLUR_PX*(1-t*2))
    if px < 2: return img
    arr = np.array(img, dtype=np.float32)
    k   = (np.ones((1,px),np.float32)/px
           if entrance in ("fly_left","fly_right")
           else np.ones((px,1),np.float32)/px)
    out = np.zeros_like(arr)
    for c in range(arr.shape[2]):
        out[:,:,c] = cv2.filter2D(arr[:,:,c],-1,k)
    return Image.fromarray(out.astype(np.uint8))


# ══════════════════════════════════════════════════════════════════
#  COMPOSITE PHRASE — safe zone enforced
# ══════════════════════════════════════════════════════════════════

def composite_phrase(canvas: np.ndarray,
                     img: Image.Image,
                     frame_in: int, frame_out: int,
                     entrance: str,
                     cx: int, cy: int,
                     alpha_override: float = None,
                     blur: bool = False) -> None:
    iw, ih = img.size

    if frame_in < ANIM_IN:
        t     = frame_in/ANIM_IN
        e     = elastic_out(t)
        scale = max(0.1, 0.5 + e*0.6)   # 0.5→1.1→1.0
        alpha = min(1.0, t*3.5)
        offsets = {
            "fly_left":   (int((1-t)*(-iw-80)), 0),
            "fly_right":  (int((1-t)*(W+80)), 0),
            "fly_top":    (0, int((1-t)*(-ih-80))),
            "fly_bottom": (0, int((1-t)*(H+80))),
        }
        xo, yo = offsets.get(entrance,(0,0))
        img = motion_blur(img, entrance, t)
    elif frame_out < ANIM_OUT:
        scale,alpha,xo,yo = 1.0, frame_out/ANIM_OUT, 0, 0
    else:
        scale,alpha,xo,yo = 1.0, 1.0, 0, 0

    if alpha_override is not None:
        alpha = alpha_override
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(radius=6))

    # Scale
    disp = img
    if abs(scale-1.0) > 0.01:
        nw,nh = max(1,int(iw*scale)), max(1,int(ih*scale))
        disp  = img.resize((nw,nh), Image.LANCZOS)

    # Position — center of disp at (cx+xo, cy+yo)
    px = cx - disp.width//2 + xo
    py = cy - disp.height//2 + yo

    # HARD CLAMP to safe zone
    px = max(SAFE_X1, min(SAFE_X2-disp.width,  px))
    py = max(SAFE_Y1, min(SAFE_Y2-disp.height, py))

    cr = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    cp = Image.fromarray(cr).convert("RGBA")
    r,g,b,a = disp.split()
    a = a.point(lambda v: int(v*max(0.0,min(1.0,alpha))))
    disp = Image.merge("RGBA",(r,g,b,a))
    cp.alpha_composite(disp,(max(0,px),max(0,py)))
    np.copyto(canvas, cv2.cvtColor(
        np.array(cp.convert("RGB")),cv2.COLOR_RGB2BGR))


# ══════════════════════════════════════════════════════════════════
#  STICKER ENGINE
# ══════════════════════════════════════════════════════════════════

def find_asset(keyword: str) -> Path | None:
    for fname in STICKER_KEYWORDS.get(keyword.lower(), []):
        p = ASSETS_DIR / fname
        if p.exists():
            return p
    return None


def scan_keywords(text: str) -> list:
    found = []
    lower = text.lower()
    for kw in STICKER_KEYWORDS:
        if kw in lower:
            p = find_asset(kw)
            if p:
                found.append((kw, p))
    return found[:2]


def load_asset_frames(path: Path, rotation: float) -> list:
    """
    Load PNG or GIF, apply white border + drop shadow + rotation.
    Returns list of RGBA numpy arrays (pre-baked).
    """
    frames = []
    size_inner = STICKER_SIZE - STICKER_BORDER*2

    def process_frame(fr: Image.Image) -> np.ndarray:
        fr    = fr.convert("RGBA").resize(
            (size_inner,size_inner), Image.LANCZOS)
        # Drop shadow
        shadow_size = STICKER_SIZE + STICKER_SHADOW*2
        shadow_img  = Image.new("RGBA",(shadow_size,shadow_size),(0,0,0,0))
        shadow_base = Image.new("RGBA",(size_inner,size_inner),(0,0,0,180))
        shadow_img.alpha_composite(shadow_base,
                                    (STICKER_BORDER+STICKER_SHADOW+3,
                                     STICKER_BORDER+STICKER_SHADOW+3))
        shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(radius=6))
        # White border frame
        bordered = Image.new("RGBA",(STICKER_SIZE,STICKER_SIZE),(255,255,255,255))
        bordered.alpha_composite(fr,(STICKER_BORDER,STICKER_BORDER))
        # Compose: shadow then bordered
        final = shadow_img.copy()
        final.alpha_composite(bordered,(0,0))
        # Rotate for scrapbook feel
        final = final.rotate(rotation, expand=True, resample=Image.BICUBIC)
        return np.array(final)

    try:
        asset = Image.open(str(path))
        if hasattr(asset,'n_frames') and asset.n_frames > 1:
            while True:
                frames.append(process_frame(asset.copy()))
                try:
                    asset.seek(asset.tell()+1)
                except EOFError:
                    break
        else:
            frames.append(process_frame(asset))
    except Exception as e:
        print(f"[STICKER] Load failed {path}: {e}")

    print(f"[STICKER] {path.name} — {len(frames)} frame(s), rot={rotation:.0f}°")
    return frames


def composite_sticker(canvas: np.ndarray,
                      frames: list,
                      frame_idx: int,
                      start_frame: int,
                      corner_x: int,
                      corner_y: int) -> None:
    if not frames:
        return
    since = frame_idx - start_frame
    # GIF frame cycling
    gif_i = (since//2) % len(frames)
    raw   = frames[gif_i]

    # Elastic entrance scale
    if since < STICKER_ANIM_FRAMES:
        t     = since/STICKER_ANIM_FRAMES
        e     = elastic_out(t)
        scale = max(0.05, e*1.1)    # 0→1.1→1.0
        alpha = min(1.0, t*4)
    else:
        scale = 1.0
        alpha = 1.0

    # Y-axis float (sine)
    float_y = int(STICKER_FLOAT_AMP*math.sin(since*STICKER_FLOAT_SPEED))

    sh, sw = raw.shape[:2]
    if abs(scale-1.0) > 0.01:
        nw,nh = max(1,int(sw*scale)), max(1,int(sh*scale))
        disp  = cv2.resize(raw,(nw,nh))
    else:
        disp  = raw
    dh,dw = disp.shape[:2]

    # Position — clamp to safe zone
    px = max(SAFE_X1, min(SAFE_X2-dw, corner_x))
    py = max(SAFE_Y1, min(SAFE_Y2-dh, corner_y+float_y))

    cr = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    cp = Image.fromarray(cr).convert("RGBA")
    si = Image.fromarray(disp)
    r,g,b,a = si.split()
    a  = a.point(lambda v: int(v*alpha))
    si = Image.merge("RGBA",(r,g,b,a))
    cp.alpha_composite(si,(max(0,px),max(0,py)))
    np.copyto(canvas, cv2.cvtColor(
        np.array(cp.convert("RGB")),cv2.COLOR_RGB2BGR))


# ══════════════════════════════════════════════════════════════════
#  RADIAL GRADIENT BACKGROUND
# ══════════════════════════════════════════════════════════════════

def build_gradient(center_bgr: tuple, edge_bgr: tuple) -> np.ndarray:
    xs = np.linspace(-1,1,W); ys = np.linspace(-1,1,H)
    X,Y  = np.meshgrid(xs,ys)
    dist = np.clip(np.sqrt(X**2+Y**2)/np.sqrt(2),0,1)
    bg   = np.zeros((H,W,3),dtype=np.uint8)
    for c in range(3):
        bg[:,:,c] = (center_bgr[c]*(1-dist)+edge_bgr[c]*dist).astype(np.uint8)
    return bg


# ══════════════════════════════════════════════════════════════════
#  PAPER GRAIN TEXTURE
# ══════════════════════════════════════════════════════════════════

def apply_grain(canvas: np.ndarray, frame_idx: int) -> np.ndarray:
    rng   = np.random.RandomState(frame_idx*17+3)
    noise = rng.randint(-20,21,(H,W,3),dtype=np.int16)
    out   = canvas.astype(np.int16)+(noise*GRAIN_STRENGTH).astype(np.int16)
    return np.clip(out,0,255).astype(np.uint8)


# ══════════════════════════════════════════════════════════════════
#  VIGNETTE
# ══════════════════════════════════════════════════════════════════

def build_vignette() -> np.ndarray:
    xs = np.linspace(-1,1,W); ys = np.linspace(-1,1,H)
    X,Y  = np.meshgrid(xs,ys)
    dist = np.sqrt(X**2+Y**2)
    mask = 1.0-np.clip(dist/dist.max()*VIGNETTE_STR,0,1)
    return mask.reshape(H,W,1).astype(np.float32)


# ══════════════════════════════════════════════════════════════════
#  FILLED AREA WAVEFORM (tone-on-tone)
# ══════════════════════════════════════════════════════════════════

def draw_filled_waveform(canvas: np.ndarray,
                         wave: np.ndarray,
                         rms: float,
                         bg_center: tuple,
                         is_climax: bool) -> None:
    mul  = 2.0 if is_climax else 1.0
    amp  = min(WAVE_H*1.8, WAVE_H*(0.12+rms*0.88)*mul)
    xs   = np.linspace(SAFE_X1, SAFE_X2, WAVE_POINTS).astype(int)
    kern = np.ones(11)/11
    ws   = np.convolve(wave, kern, mode='same')
    ys   = np.clip((WAVE_Y-ws*amp).astype(int), 10, H-10)

    # Tone-on-tone: slightly darker than background center
    wc = tuple(max(0, int(c*WAVE_DARKEN)) for c in bg_center)

    # Filled polygon: wave top + baseline bottom
    pts_top  = [(int(xs[i]),int(ys[i])) for i in range(WAVE_POINTS)]
    pts_base = [(int(xs[i]), WAVE_Y)    for i in range(WAVE_POINTS-1,-1,-1)]
    polygon  = np.array(pts_top + pts_base, dtype=np.int32)
    cv2.fillPoly(canvas, [polygon], wc)

    # Thin bright edge line on top
    edge_col = tuple(max(0,int(c*0.80)) for c in bg_center)
    pts_line = np.array(pts_top, dtype=np.int32).reshape(-1,1,2)
    cv2.polylines(canvas,[pts_line],False,edge_col,2,cv2.LINE_AA)


# ══════════════════════════════════════════════════════════════════
#  KEN BURNS
# ══════════════════════════════════════════════════════════════════

def ken_burns(frame: np.ndarray, idx: int, total: int) -> np.ndarray:
    t  = idx/max(1,total-1)
    s  = KB_START + t*(KB_END-KB_START)
    if abs(s-1.0)<0.002: return frame
    nw,nh = int(W*s),int(H*s)
    big   = cv2.resize(frame,(nw,nh))
    ox,oy = (nw-W)//2,(nh-H)//2
    return big[oy:oy+H, ox:ox+W]


# ══════════════════════════════════════════════════════════════════
#  CLIMAX SHAKE
# ══════════════════════════════════════════════════════════════════

def climax_shake(canvas: np.ndarray, frame_idx: int) -> np.ndarray:
    rng = np.random.RandomState(frame_idx*7+11)
    sx  = int(rng.randint(-SHAKE_AMP, SHAKE_AMP+1))
    sy  = int(rng.randint(-SHAKE_AMP//2, SHAKE_AMP//2+1))
    M   = np.float32([[1,0,sx],[0,1,sy]])
    return cv2.warpAffine(canvas,M,(W,H),borderMode=cv2.BORDER_REPLICATE)


# ══════════════════════════════════════════════════════════════════
#  CAPS FLASH
# ══════════════════════════════════════════════════════════════════

def apply_caps_flash(canvas: np.ndarray,
                     intensity: float,
                     accent: tuple) -> np.ndarray:
    ov = np.full_like(canvas, accent, dtype=np.uint8)
    return cv2.addWeighted(canvas,1-intensity*0.12,ov,intensity*0.12,0)


# ══════════════════════════════════════════════════════════════════
#  MAIN RENDER
# ══════════════════════════════════════════════════════════════════

def render_video(phrases: list,
                 rms_arr: np.ndarray,
                 wave_arr: np.ndarray,
                 duration: float,
                 palette: tuple,
                 climax_pair: tuple,
                 accent_bgr: tuple,
                 sticker_schedule: list) -> None:

    n_frames     = len(rms_arr)
    vignette     = build_vignette()
    climax_start = int((duration-CLIMAX_SECS)*FPS)

    # Pre-build backgrounds
    bg_main = build_gradient(palette[0], palette[1])
    bg_c1   = build_gradient(climax_pair[0][0], climax_pair[0][1])
    bg_c2   = build_gradient(climax_pair[1][0], climax_pair[1][1])

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    temp   = "raw_temp.mp4"
    writer = cv2.VideoWriter(temp,fourcc,FPS,(W,H))
    if not writer.isOpened():
        sys.exit("[ERROR] VideoWriter failed")

    print(f"[RENDER] {n_frames} frames | {len(phrases)} phrases | "
          f"{len(sticker_schedule)} stickers")

    # Pre-render phrase images
    for p in phrases:
        p["img"] = render_phrase_image(
            p["text"], p["has_caps"], p["use_accent"],
            p["text_color"], p["accent_color"]
        )
        p["sf"] = int(p["start_sec"]*FPS)
        p["ef"] = min(int(p["end_sec"]*FPS), n_frames)

    frame_phrase = {}
    for pi,p in enumerate(phrases):
        p["pi"] = pi
        for f in range(p["sf"],p["ef"]):
            frame_phrase[f] = p

    flash_cnt   = 0
    prev_phrase = None
    log_step    = max(1,n_frames//20)

    for i in range(n_frames):
        is_climax = i >= climax_start

        # Background — climax oscillates between two tones
        if is_climax:
            phase  = (i-climax_start)//5
            canvas = (bg_c1 if phase%2==0 else bg_c2).copy()
            bg_ctr = climax_pair[0][0] if phase%2==0 else climax_pair[1][0]
        else:
            canvas = bg_main.copy()
            bg_ctr = palette[0]

        # Filled area waveform
        draw_filled_waveform(canvas, wave_arr[i], rms_arr[i],
                             bg_ctr, is_climax)

        cur = frame_phrase.get(i)

        # Previous phrase — 20% opacity + blur
        if (prev_phrase is not None and cur is not None
                and cur["pi"] != prev_phrase["pi"]):
            since_end = i - prev_phrase["ef"]
            if since_end < int(FPS*0.4):
                la = 0.20*(1-since_end/int(FPS*0.4))
                composite_phrase(
                    canvas, prev_phrase["img"],
                    prev_phrase["ef"]-prev_phrase["sf"], 999,
                    prev_phrase["entrance"],
                    prev_phrase["rand_x"], prev_phrase["rand_y"],
                    alpha_override=la, blur=True
                )

        # Active phrase
        if cur is not None:
            fi = i-cur["sf"]; fo = cur["ef"]-i
            if (cur["has_caps"] and
                    (prev_phrase is None or cur["pi"]!=prev_phrase["pi"])):
                flash_cnt = 2
            composite_phrase(canvas, cur["img"],
                             fi, fo, cur["entrance"],
                             cur["rand_x"], cur["rand_y"])
            prev_phrase = cur

        # Stickers
        for (st_start, st_frames, sx, sy) in sticker_schedule:
            if i >= st_start:
                composite_sticker(canvas, st_frames,
                                  i, st_start, sx, sy)

        # CAPS flash
        if flash_cnt > 0:
            canvas = apply_caps_flash(canvas, flash_cnt/2, accent_bgr)
            flash_cnt -= 1

        # Vignette
        cf     = canvas.astype(np.float32)/255.0*vignette
        canvas = (cf*255).clip(0,255).astype(np.uint8)

        # Ken Burns
        canvas = ken_burns(canvas, i, n_frames)

        # Paper grain
        canvas = apply_grain(canvas, i)

        # Climax shake
        if is_climax:
            canvas = climax_shake(canvas, i)

        writer.write(canvas)
        if i % log_step == 0:
            print(f"  [RENDER] {int(i/n_frames*100)}%"
                  f"{'  🔥' if is_climax else ''}")

    writer.release()
    print("[RENDER] Re-encoding...")
    r = subprocess.run(
        ["ffmpeg","-y","-i",temp,"-c:v","libx264",
         "-preset","fast","-crf","17","-pix_fmt","yuv420p","-an",
         str(OUTPUT_VIDEO)],
        capture_output=True, text=True)
    if r.returncode!=0:
        shutil.copy(temp, str(OUTPUT_VIDEO))
    else:
        Path(temp).unlink(missing_ok=True)
    print(f"[✓] {OUTPUT_VIDEO} "
          f"({OUTPUT_VIDEO.stat().st_size//1024//1024}MB)")


# ══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════

def main():
    print("="*62)
    print("  Premium Scrapbook Engine v7")
    print("  Safe-Zone · Stickers · Radial Gradient · Elastic")
    print("="*62)

    ensure_font()
    ASSETS_DIR.mkdir(exist_ok=True)

    if not INPUT_AUDIO.exists():
        download_audio()
    if not INPUT_SCRIPT.exists():
        sys.exit("[ERROR] script.txt not found")

    raw   = INPUT_SCRIPT.read_text(encoding="utf-8")
    clean = clean_script(raw)
    print(f"[INFO] Script: {len(clean.split())} words")

    # Palette
    palette     = random.choice(PALETTES)
    climax_pair = random.choice(CLIMAX_PAIRS)
    accent_bgr  = random.choice(TEXT_ACCENT_OPTIONS)

    # Duration
    cmd      = ["ffprobe","-v","error","-show_entries","format=duration",
                "-of","default=noprint_wrappers=1:nokey=1",str(INPUT_AUDIO)]
    duration = float(subprocess.run(cmd,capture_output=True,
                                    text=True).stdout.strip())
    n_frames = int(duration*FPS)
    print(f"[INFO] Duration: {duration:.2f}s | BG: {palette[0]}")

    # Stickers
    kw_matches = scan_keywords(clean)
    sticker_schedule = []
    used_corners     = set()
    for idx,(kw,path) in enumerate(kw_matches):
        avail  = [c for c in range(len(STICKER_CORNERS)) if c not in used_corners]
        if not avail: break
        ci     = random.choice(avail)
        used_corners.add(ci)
        rot    = random.uniform(-STICKER_ROT_RANGE, STICKER_ROT_RANGE)
        frames = load_asset_frames(path, rot)
        if frames:
            sx,sy = STICKER_CORNERS[ci]
            st    = FPS*3 + idx*FPS*12
            sticker_schedule.append((st, frames, sx, sy))
    if not sticker_schedule:
        print("[STICKER] No matching assets — skipping")

    # TTS timestamps
    print("[TTS] Computing timestamps...")
    word_timestamps = asyncio.run(generate_tts_with_timing(clean))
    if not word_timestamps:
        words = clean.split()
        d     = duration/max(1,len(words))
        word_timestamps = [{"word":w,"start":i*d,"duration":d}
                           for i,w in enumerate(words)]

    phrases  = group_into_phrases(word_timestamps, duration, accent_bgr)
    rms_arr, wave_arr, _ = analyse_audio(str(INPUT_AUDIO), n_frames)

    render_video(phrases, rms_arr, wave_arr, duration,
                 palette, climax_pair, accent_bgr, sticker_schedule)

    print("\n"+"="*62)
    print("  [✓] DONE — raw_video.mp4 ready")
    print("="*62)


if __name__ == "__main__":
    main()
