"""
generate_video.py — Pop-Art Kinetic Engine v6
==============================================
GIF sticker overlays · Radial gradient backgrounds
Elastic entrances · Phrase persistence blur
Climax shake + color cycle + double waveform
Headless — GitHub Actions compatible
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
ASSETS_DIR   = Path("assets")
FONT_PATH    = Path("Montserrat-Bold.ttf")
FONT_URL     = "https://github.com/google/fonts/raw/main/ofl/montserrat/static/Montserrat-Bold.ttf"

# ── Fruit palette — (center_BGR, edge_BGR) for radial gradient ───
PALETTES = [
    ((185,175,255), (140,120,200)),  # Peach
    ((210,180,255), (160,130,210)),  # Apricot
    ((170,160,255), (120,100,200)),  # Nectarine
    ((200,185,255), (150,130,210)),  # Creamsicle
    ((180,165,255), (130,110,200)),  # Papaya
    ((185,155,245), (130,100,190)),  # Guava
    ((165,140,255), (115, 90,200)),  # Salmon
    ((155,125,255), (105, 75,200)),  # Coral
    ((170,120,240), (115, 70,185)),  # Terra Cotta
    ((195,170,255), (145,120,205)),  # Melon
    ((210,190,255), (160,140,210)),  # Shell Pink
    ((185,185,255), (130,130,210)),  # Pink
    ((130,215,150), ( 80,165,100)),  # Lime
    ((140,200,255), ( 90,145,205)),  # Soft Orange
]

# Complementary pairs for climax color cycle
CLIMAX_PAIRS = [
    ((165,140,255),(155,125,255)),  # Salmon ↔ Coral
    ((200,185,255),(185,175,255)),  # Creamsicle ↔ Peach
    ((130,215,150),(140,200,255)),  # Lime ↔ Orange
    ((170,120,240),(185,155,245)),  # Terra Cotta ↔ Guava
]

# ── Word / accent colors (dark for light bg) ──────────────────────
WORD_COLORS_BGR = [
    (30, 20,100),(15,40,130),(10,60,120),
    (30,20,140),(50,30,110),(20,80,100),
    (40,25,120),(10,50, 90),
]
ACCENT_COLORS_BGR = [
    (20,10,200),(10,80,220),(0,150,200),
    (80,20,180),(0,100,180),(40,0,160),
]
WAVE_COLORS_BGR = [
    (60,30,140),(20,20,180),(30,80,160),
    (10,60,120),(80,20,160),
]

# ── Typography ────────────────────────────────────────────────────
WORDS_PER_PHRASE    = 4
MIN_PHRASE_HOLD_SEC = 1.2
ANIM_IN_FRAMES      = int(FPS * 0.22)
ANIM_OUT_FRAMES     = int(FPS * 0.15)
PERSIST_ALPHA       = 0.20          # Previous phrase: 20% opacity
PERSIST_BLUR_R      = 5             # Blur radius in pixels
SAFE_PAD            = 45
POS_X_MIN           = int(W * 0.08)
POS_X_MAX           = int(W * 0.92)
POS_Y_MIN           = int(H * 0.18)
POS_Y_MAX           = int(H * 0.60)
ACCENT_CHANCE       = 0.35

# ── GIF sticker ───────────────────────────────────────────────────
STICKER_SIZE        = 220           # px — target size
STICKER_BORDER      = 10            # White border width
STICKER_FLOAT_AMP   = 12            # Y-float sine amplitude (px)
STICKER_FLOAT_SPEED = 0.08          # Sine speed per frame
STICKER_ANIM_FRAMES = int(FPS * 0.25)

# GIF keyword → filename mapping
GIF_KEYWORDS = {
    "shocked": "shocked.gif", "fire": "fire.gif",
    "cat": "cat.gif", "aura": "aura.gif",
    "win": "win.gif", "love": "love.gif",
    "brain": "brain.gif", "star": "star.gif",
    "ghost": "ghost.gif", "crown": "crown.gif",
    "money": "money.gif", "rocket": "rocket.gif",
    "wow": "shocked.gif", "amazing": "star.gif",
    "incredible": "aura.gif",
}

# Safe corners for sticker placement (x_anchor, y_anchor)
# Avoid center zone (0.3–0.7 x, 0.2–0.7 y)
STICKER_CORNERS = [
    (60, 120),                  # Top-left
    (W - STICKER_SIZE - 60, 120),     # Top-right
    (60, H - STICKER_SIZE - 300),     # Bottom-left
    (W - STICKER_SIZE - 60, H - STICKER_SIZE - 300),  # Bottom-right
]

# ── Effects ────────────────────────────────────────────────────────
GRAIN_INTENSITY  = 10
GRAIN_BLEND      = 0.05
VIGNETTE_STR     = 0.70
MOTION_BLUR_PX   = 10
KB_START         = 1.0
KB_END           = 1.12

# ── Waveform ─────────────────────────────────────────────────────
WAVE_Y_BASE = int(H * 0.82)
WAVE_HEIGHT = int(H * 0.13)
WAVE_POINTS = 200

# ── Climax ───────────────────────────────────────────────────────
CLIMAX_SECS  = 5.0
SHAKE_AMP    = 12
CHROMA_SHIFT = 8
CLIMAX_WAVE_MULT = 2.0


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
            return
    except Exception:
        pass
    ttfs = glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)
    bold = [f for f in ttfs if "bold" in f.lower()]
    src  = bold[0] if bold else (ttfs[0] if ttfs else None)
    if src:
        shutil.copy(src, str(FONT_PATH))

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
    hdrs = {"Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json"}
    res  = requests.get(
        "https://api.github.com/repos/Suryansh0704/Audio-generator-/actions/artifacts",
        headers=hdrs)
    arts = res.json().get("artifacts", [])
    if not arts:
        sys.exit("[ERROR] No artifacts")
    latest = arts[0]
    r = requests.get(latest["archive_download_url"], headers=hdrs)
    with open("audio.zip","wb") as f: f.write(r.content)
    with zipfile.ZipFile("audio.zip") as z: z.extractall("audio_extracted")
    wavs = (glob.glob("audio_extracted/**/*.wav", recursive=True)
            or glob.glob("audio_extracted/*.wav"))
    if wavs:
        shutil.copy(wavs[0], str(INPUT_AUDIO))
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
#  EDGE-TTS
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
    rms      = np.zeros(n_frames, dtype=np.float32)
    wave     = np.zeros((n_frames, WAVE_POINTS), dtype=np.float32)
    for i in range(n_frames):
        s = int(i*spf); e = min(int(s+spf), len(y))
        c = y[s:e]
        if not len(c): continue
        rms[i] = float(np.sqrt(np.mean(c**2)))
        if len(c) >= WAVE_POINTS:
            idx = np.linspace(0,len(c)-1,WAVE_POINTS).astype(int)
            wave[i] = c[idx]
        else:
            wave[i,:len(c)] = c
    mx = rms.max()
    if mx > 0: rms /= mx
    print(f"[AUDIO] {duration:.2f}s analysed")
    return rms, wave, duration


# ══════════════════════════════════════════════════════════════════
#  GIF STICKER ENGINE
# ══════════════════════════════════════════════════════════════════

def scan_keywords(text: str) -> list:
    """Return list of matching GIF filenames found in script."""
    found = []
    lower = text.lower()
    for kw, fname in GIF_KEYWORDS.items():
        if kw in lower:
            gif_path = ASSETS_DIR / fname
            if gif_path.exists():
                found.append((kw, str(gif_path)))
    return found[:2]  # Max 2 stickers per video


def preload_gif(gif_path: str) -> list:
    """
    Load all frames of a GIF, resize to STICKER_SIZE,
    add white border (sticker effect).
    Returns list of RGBA numpy arrays — pre-baked for speed.
    """
    frames = []
    try:
        gif = Image.open(gif_path)
        size_inner = STICKER_SIZE - STICKER_BORDER * 2
        while True:
            frame = gif.convert("RGBA").resize(
                (size_inner, size_inner), Image.LANCZOS
            )
            # Add white border
            bordered = Image.new(
                "RGBA",
                (STICKER_SIZE, STICKER_SIZE),
                (255, 255, 255, 255)
            )
            bordered.alpha_composite(frame, (STICKER_BORDER, STICKER_BORDER))
            frames.append(np.array(bordered))
            try:
                gif.seek(gif.tell() + 1)
            except EOFError:
                break
    except Exception as e:
        print(f"[GIF] Failed to load {gif_path}: {e}")
        return []
    print(f"[GIF] Loaded {gif_path} — {len(frames)} frames")
    return frames


def get_sticker_state(frame_idx: int,
                      sticker_start: int,
                      corner: tuple) -> tuple:
    """
    Returns (x, y, scale, alpha, gif_frame_idx).
    Elastic entrance + sine float.
    """
    frames_since_start = frame_idx - sticker_start
    base_x, base_y = corner

    # Entrance animation
    if frames_since_start < STICKER_ANIM_FRAMES:
        t     = frames_since_start / STICKER_ANIM_FRAMES
        raw   = 1 + (2**(-10*t)) * math.sin((t-0.075)*2*math.pi/0.3)
        scale = max(0.1, raw * 1.0)
        alpha = min(1.0, t * 4)
    else:
        scale = 1.0
        alpha = 1.0

    # Y-axis float (sine wave)
    float_offset = int(
        STICKER_FLOAT_AMP *
        math.sin(frames_since_start * STICKER_FLOAT_SPEED)
    )

    x = base_x
    y = base_y + float_offset

    # GIF frame cycling
    gif_f = frames_since_start % max(1, 1)  # updated per call

    return x, y, scale, alpha, gif_f


def composite_sticker(canvas_bgr: np.ndarray,
                      gif_frames: list,
                      frame_idx: int,
                      sticker_start: int,
                      corner: tuple) -> None:
    if not gif_frames:
        return

    frames_since = frame_idx - sticker_start
    x, y, scale, alpha, _ = get_sticker_state(
        frame_idx, sticker_start, corner
    )

    # Cycle through GIF frames
    gif_f_idx = (frames_since // 2) % len(gif_frames)
    raw_arr   = gif_frames[gif_f_idx]

    # Scale the sticker
    if abs(scale - 1.0) > 0.01:
        sw = max(1, int(STICKER_SIZE * scale))
        sh = max(1, int(STICKER_SIZE * scale))
        raw_arr = cv2.resize(raw_arr, (sw, sh))

    sh, sw = raw_arr.shape[:2]

    # Clamp to canvas
    cx = max(0, min(W - sw, x))
    cy = max(0, min(H - sh, y))

    # Composite onto canvas
    canvas_rgb = cv2.cvtColor(canvas_bgr, cv2.COLOR_BGR2RGB)
    c_pil      = Image.fromarray(canvas_rgb).convert("RGBA")
    s_pil      = Image.fromarray(raw_arr)

    # Apply alpha
    r, g, b, a = s_pil.split()
    a = a.point(lambda v: int(v * alpha))
    s_pil = Image.merge("RGBA", (r, g, b, a))

    c_pil.alpha_composite(s_pil, (cx, cy))
    result = cv2.cvtColor(
        np.array(c_pil.convert("RGB")), cv2.COLOR_RGB2BGR
    )
    np.copyto(canvas_bgr, result)


# ══════════════════════════════════════════════════════════════════
#  RADIAL GRADIENT BACKGROUND
# ══════════════════════════════════════════════════════════════════

def build_radial_gradient(center_bgr: tuple,
                           edge_bgr: tuple) -> np.ndarray:
    """
    Build a 1080×1920 radial gradient image.
    Center = center_bgr, edges fade to edge_bgr.
    Pre-computed once — reused every frame.
    """
    xs = np.linspace(-1, 1, W)
    ys = np.linspace(-1, 1, H)
    X, Y  = np.meshgrid(xs, ys)
    dist  = np.sqrt(X**2 + Y**2)
    dist  = np.clip(dist / dist.max(), 0, 1)

    bg = np.zeros((H, W, 3), dtype=np.uint8)
    for c in range(3):
        bg[:,:,c] = (
            center_bgr[c] * (1 - dist) + edge_bgr[c] * dist
        ).astype(np.uint8)

    return bg


# ══════════════════════════════════════════════════════════════════
#  PHRASE GROUPING
# ══════════════════════════════════════════════════════════════════

def group_into_phrases(word_timestamps: list,
                       duration: float,
                       accent_bgr: tuple) -> list:
    phrases       = []
    climax_start  = duration - CLIMAX_SECS
    entrances     = ["fly_left","fly_right","fly_top","fly_bottom",
                     "fly_left","fly_right"]
    n_total       = max(1, len(word_timestamps)//WORDS_PER_PHRASE)
    accent_set    = set(random.sample(
        range(n_total), max(1, int(n_total * ACCENT_CHANCE))
    ))

    i = 0; pi = 0
    while i < len(word_timestamps):
        group = word_timestamps[i:i+WORDS_PER_PHRASE]
        text  = ' '.join(w["word"] for w in group)
        clean = re.sub(r'[^a-zA-Z0-9\'\-!?.,"\s]','',text).strip()
        if not clean:
            i += WORDS_PER_PHRASE; pi += 1; continue

        start_sec = group[0]["start"]
        end_sec   = group[-1]["start"] + group[-1]["duration"]
        if end_sec - start_sec < MIN_PHRASE_HOLD_SEC:
            end_sec = start_sec + MIN_PHRASE_HOLD_SEC

        has_caps   = bool(re.search(r'[A-Z]{2,}', text))
        has_quotes = '"' in text
        is_climax  = start_sec >= climax_start
        use_accent = has_caps or has_quotes or (pi in accent_set)

        entrance   = random.choice(entrances)
        rand_x     = random.randint(POS_X_MIN, POS_X_MAX)
        rand_y     = random.randint(POS_Y_MIN, POS_Y_MAX)
        phrase_col = accent_bgr if use_accent else random.choice(WORD_COLORS_BGR)

        phrases.append({
            "text": clean, "start_sec": start_sec, "end_sec": end_sec,
            "has_caps": has_caps, "has_quotes": has_quotes,
            "is_climax": is_climax, "entrance": entrance,
            "rand_x": rand_x, "rand_y": rand_y,
            "phrase_color": phrase_col, "use_accent": use_accent,
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
#  PHRASE IMAGE RENDERER
# ══════════════════════════════════════════════════════════════════

def render_phrase_image(text: str, has_caps: bool, has_quotes: bool,
                        phrase_color: tuple, accent_bgr: tuple,
                        use_accent: bool,
                        is_climax: bool = False) -> Image.Image:
    words = text.split()
    NS, CS = 98, 124
    LS, PAD = 24, 36

    wdata = []
    for w in words:
        is_cap = bool(re.search(r'[A-Z]{2,}', w))
        is_acc = is_cap or has_quotes or use_accent
        size   = CS if is_cap else NS
        if is_climax: size = int(size*1.06)
        color  = accent_bgr if is_acc else phrase_color
        font   = get_font(size)
        tmp    = Image.new("RGBA",(1,1))
        d      = ImageDraw.Draw(tmp)
        bbox   = d.textbbox((0,0), w, font=font)
        wdata.append({
            "text":w,"font":font,"color":color,
            "w":max(1,bbox[2]-bbox[0]),
            "h":max(1,bbox[3]-bbox[1]),
            "is_acc":is_acc
        })

    max_w = W-120
    lines, cur, cw = [], [], 0
    for wd in wdata:
        if cw+wd["w"]+18>max_w and cur:
            lines.append(cur); cur,cw=[wd],wd["w"]
        else:
            cur.append(wd); cw+=wd["w"]+18
    if cur: lines.append(cur)

    lhs  = [max(wd["h"] for wd in l) for l in lines]
    th   = sum(lhs)+LS*(len(lines)-1)+PAD*2
    tw   = W-80

    img  = Image.new("RGBA",(max(1,tw),max(1,th)),(0,0,0,0))
    draw = ImageDraw.Draw(img)
    y    = PAD

    for li, line in enumerate(lines):
        lw = sum(wd["w"] for wd in line)+18*(len(line)-1)
        x  = (tw-lw)//2
        lh = lhs[li]
        for wd in line:
            rgb = (wd["color"][2],wd["color"][1],wd["color"][0])
            if wd["is_acc"]:
                gr = tuple(min(255,int(c*1.3)) for c in rgb)
                for gd,ga in [(7,50),(4,90),(2,130)]:
                    for dx,dy in [(gd,0),(-gd,0),(0,gd),(0,-gd)]:
                        draw.text((x+dx,y+dy),wd["text"],
                                  font=wd["font"],fill=gr+(ga,))
                draw.line([(x,y+wd["h"]+4),(x+wd["w"],y+wd["h"]+4)],
                          fill=rgb+(200,),width=3)
            else:
                draw.text((x+2,y+2),wd["text"],font=wd["font"],
                          fill=(20,20,20,100))
            draw.text((x,y),wd["text"],font=wd["font"],fill=rgb+(255,))
            x += wd["w"]+18
        y += lh+LS

    return img


# ══════════════════════════════════════════════════════════════════
#  MOTION BLUR
# ══════════════════════════════════════════════════════════════════

def apply_motion_blur(img: Image.Image,
                      entrance: str, t: float) -> Image.Image:
    if t > 0.5: return img
    px = int(MOTION_BLUR_PX*(1-t*2))
    if px < 2: return img
    arr = np.array(img, dtype=np.float32)
    if entrance in ("fly_left","fly_right"):
        k = np.ones((1,px),np.float32)/px
    else:
        k = np.ones((px,1),np.float32)/px
    out = np.zeros_like(arr)
    for c in range(arr.shape[2]):
        out[:,:,c] = cv2.filter2D(arr[:,:,c],-1,k)
    return Image.fromarray(out.astype(np.uint8))


# ══════════════════════════════════════════════════════════════════
#  PHRASE COMPOSITE (elastic + persist blur)
# ══════════════════════════════════════════════════════════════════

def composite_phrase(canvas_bgr: np.ndarray,
                     phrase_img: Image.Image,
                     frame_in: int, frame_out: int,
                     entrance: str,
                     pos_x: int, pos_y: int,
                     alpha_override: float = None,
                     blur: bool = False) -> None:
    iw, ih = phrase_img.size

    if frame_in < ANIM_IN_FRAMES:
        t     = frame_in/ANIM_IN_FRAMES
        e     = 0.5 + elastic_out(t)*0.5
        scale = max(0.1, e)
        alpha = min(1.0, t*3.0)
        offsets = {
            "fly_left":   (int((1-t)*(-iw-80)), 0),
            "fly_right":  (int((1-t)*(W+80)), 0),
            "fly_top":    (0, int((1-t)*(-ih-80))),
            "fly_bottom": (0, int((1-t)*(H+80))),
        }
        xo, yo = offsets.get(entrance,(0,0))
        if entrance in ("fly_left","fly_right","fly_top","fly_bottom"):
            phrase_img = apply_motion_blur(phrase_img, entrance, t)
    elif frame_out < ANIM_OUT_FRAMES:
        scale,alpha,xo,yo = 1.0,frame_out/ANIM_OUT_FRAMES,0,0
    else:
        scale,alpha,xo,yo = 1.0,1.0,0,0

    if alpha_override is not None:
        alpha = alpha_override

    disp = phrase_img
    if abs(scale-1.0) > 0.01:
        nw,nh = max(1,int(iw*scale)),max(1,int(ih*scale))
        disp  = phrase_img.resize((nw,nh),Image.LANCZOS)

    # Optional blur for persistence
    if blur:
        disp = disp.filter(ImageFilter.GaussianBlur(radius=PERSIST_BLUR_R))

    px = max(SAFE_PAD, min(W-disp.width-SAFE_PAD,  pos_x-disp.width//2+xo))
    py = max(SAFE_PAD, min(H-disp.height-SAFE_PAD, pos_y-disp.height//2+yo))

    cr = cv2.cvtColor(canvas_bgr, cv2.COLOR_BGR2RGB)
    cp = Image.fromarray(cr).convert("RGBA")
    r,g,b,a = disp.split()
    a = a.point(lambda v: int(v*max(0.0,min(1.0,alpha))))
    disp = Image.merge("RGBA",(r,g,b,a))
    cp.alpha_composite(disp,(max(0,px),max(0,py)))
    np.copyto(canvas_bgr, cv2.cvtColor(
        np.array(cp.convert("RGB")),cv2.COLOR_RGB2BGR))


# ══════════════════════════════════════════════════════════════════
#  WAVEFORM (gradient, climax doubles)
# ══════════════════════════════════════════════════════════════════

def draw_waveform(canvas: np.ndarray, wave: np.ndarray,
                  rms: float, wave_col: tuple, accent: tuple,
                  is_climax: bool) -> None:
    mul  = CLIMAX_WAVE_MULT if is_climax else 1.0
    amp  = min(WAVE_HEIGHT*1.8, WAVE_HEIGHT*(0.15+rms*0.85)*mul)
    col  = accent if is_climax else wave_col
    xs   = np.linspace(80,W-80,WAVE_POINTS).astype(int)
    ws   = np.convolve(wave,np.ones(9)/9,mode='same')
    ys   = np.clip((WAVE_Y_BASE-ws*amp).astype(int),10,H-10)
    ci   = WAVE_POINTS//2
    for i in range(WAVE_POINTS-1):
        brt  = max(0.25, 1.0-abs(i-ci)/ci*0.70)
        c    = tuple(int(v*brt) for v in col)
        gc   = tuple(max(0,int(v*brt*0.4)) for v in col)
        p1   = (int(xs[i]),int(ys[i]))
        p2   = (int(xs[i+1]),int(ys[i+1]))
        cv2.line(canvas,p1,p2,gc,10,cv2.LINE_AA)
        cv2.line(canvas,p1,p2,c, 3, cv2.LINE_AA)
    pi2 = int(np.argmax(np.abs(ws)))
    cv2.circle(canvas,(int(xs[pi2]),int(ys[pi2])),5,col,-1)
    cv2.circle(canvas,(int(xs[pi2]),int(ys[pi2])),9,col,2)


# ══════════════════════════════════════════════════════════════════
#  ATMOSPHERIC EFFECTS
# ══════════════════════════════════════════════════════════════════

def build_vignette() -> np.ndarray:
    xs = np.linspace(-1,1,W); ys = np.linspace(-1,1,H)
    X,Y = np.meshgrid(xs,ys)
    d   = np.sqrt(X**2+Y**2)
    m   = 1.0 - np.clip(d/d.max()*VIGNETTE_STR,0,1)
    return m.reshape(H,W,1).astype(np.float32)


def film_grain(canvas: np.ndarray, frame_idx: int) -> np.ndarray:
    rng   = np.random.RandomState(frame_idx*31+7)
    noise = rng.randint(-GRAIN_INTENSITY,GRAIN_INTENSITY+1,
                        canvas.shape,dtype=np.int16)
    out   = canvas.astype(np.int16)+(noise*GRAIN_BLEND).astype(np.int16)
    return np.clip(out,0,255).astype(np.uint8)


def ken_burns(frame: np.ndarray, idx: int, total: int) -> np.ndarray:
    t  = idx/max(1,total-1)
    s  = KB_START+t*(KB_END-KB_START)
    if abs(s-1.0)<0.002: return frame
    nw,nh = int(W*s),int(H*s)
    big   = cv2.resize(frame,(nw,nh))
    ox,oy = (nw-W)//2,(nh-H)//2
    return big[oy:oy+H,ox:ox+W]


def chroma_shake(canvas: np.ndarray, frame_idx: int) -> np.ndarray:
    rng  = np.random.RandomState(frame_idx*13+5)
    sx   = int(rng.randint(-CHROMA_SHIFT,CHROMA_SHIFT+1))
    sy   = int(rng.randint(-CHROMA_SHIFT//2,CHROMA_SHIFT//2+1))
    b,g,r = cv2.split(canvas)
    Mr = np.float32([[1,0,sx],[0,1,sy]])
    Mb = np.float32([[1,0,-sx],[0,1,-sy]])
    r  = cv2.warpAffine(r,Mr,(W,H),borderMode=cv2.BORDER_REPLICATE)
    b  = cv2.warpAffine(b,Mb,(W,H),borderMode=cv2.BORDER_REPLICATE)
    canvas = cv2.merge([b,g,r])
    rng2  = np.random.RandomState(frame_idx*7+13)
    shx   = int(rng2.randint(-SHAKE_AMP,SHAKE_AMP+1))
    shy   = int(rng2.randint(-SHAKE_AMP//2,SHAKE_AMP//2+1))
    M     = np.float32([[1,0,shx],[0,1,shy]])
    return cv2.warpAffine(canvas,M,(W,H),borderMode=cv2.BORDER_REPLICATE)


def caps_flash(canvas: np.ndarray,
               intensity: float, acc: tuple) -> np.ndarray:
    ov = np.full_like(canvas, acc, dtype=np.uint8)
    return cv2.addWeighted(canvas,1-intensity*0.15,ov,intensity*0.15,0)


# ══════════════════════════════════════════════════════════════════
#  MAIN RENDER
# ══════════════════════════════════════════════════════════════════

def render_video(phrases: list, rms_arr: np.ndarray,
                 wave_arr: np.ndarray, duration: float,
                 palette: tuple, climax_pair: tuple,
                 accent_bgr: tuple, wave_bgr: tuple,
                 stickers: list) -> None:

    n_frames     = len(rms_arr)
    vignette     = build_vignette()
    climax_start = int((duration-CLIMAX_SECS)*FPS)

    # Pre-build gradient background
    ctr,edg  = palette
    bg_base  = build_radial_gradient(ctr, edg)
    bg_c1    = build_radial_gradient(climax_pair[0],
                                     tuple(max(0,c-40) for c in climax_pair[0]))
    bg_c2    = build_radial_gradient(climax_pair[1],
                                     tuple(max(0,c-40) for c in climax_pair[1]))

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    temp   = "raw_temp.mp4"
    writer = cv2.VideoWriter(temp, fourcc, FPS, (W,H))
    if not writer.isOpened():
        sys.exit("[ERROR] VideoWriter failed")

    print(f"[RENDER] {n_frames} frames | {len(phrases)} phrases | "
          f"{len(stickers)} stickers")

    # Pre-render phrase images
    for p in phrases:
        p["img"] = render_phrase_image(
            p["text"], p["has_caps"], p["has_quotes"],
            p["phrase_color"], accent_bgr,
            p["use_accent"], p["is_climax"]
        )
        p["sf"] = int(p["start_sec"]*FPS)
        p["ef"] = min(int(p["end_sec"]*FPS), n_frames)

    frame_phrase = {}
    for pi, p in enumerate(phrases):
        p["pi"] = pi
        for f in range(p["sf"],p["ef"]):
            frame_phrase[f] = p

    # Sticker schedule — appear after first 2 seconds
    sticker_schedule = []
    for si, (_, gif_path, gif_frames) in enumerate(stickers):
        start_f  = FPS*2 + si*FPS*15   # Stagger each sticker
        corner   = STICKER_CORNERS[si % len(STICKER_CORNERS)]
        sticker_schedule.append((start_f, gif_frames, corner))

    flash_cnt   = 0
    prev_phrase = None
    log_step    = max(1, n_frames//20)

    for i in range(n_frames):
        is_climax = i >= climax_start

        # Background
        if is_climax:
            phase = (i - climax_start) // 4  # Cycle every 4 frames
            canvas = (bg_c1 if phase % 2 == 0 else bg_c2).copy()
        else:
            canvas = bg_base.copy()

        # Waveform
        draw_waveform(canvas, wave_arr[i], rms_arr[i],
                      wave_bgr, accent_bgr, is_climax)

        # Previous phrase — 20% opacity + blur
        cur = frame_phrase.get(i)
        if (prev_phrase is not None and cur is not None
                and cur["pi"] != prev_phrase["pi"]):
            since_end = i - prev_phrase["ef"]
            if since_end < int(FPS*0.4):
                la = PERSIST_ALPHA*(1-since_end/int(FPS*0.4))
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

        # Sticker overlays
        for (st_start, gif_frames, corner) in sticker_schedule:
            if i >= st_start and gif_frames:
                composite_sticker(canvas, gif_frames,
                                  i, st_start, corner)

        # CAPS flash
        if flash_cnt > 0:
            canvas = caps_flash(canvas, flash_cnt/2, accent_bgr)
            flash_cnt -= 1

        # Vignette
        cf     = canvas.astype(np.float32)/255.0*vignette
        canvas = (cf*255).clip(0,255).astype(np.uint8)

        # Ken Burns
        canvas = ken_burns(canvas, i, n_frames)

        # Film grain
        canvas = film_grain(canvas, i)

        # Climax: chroma aberration + shake
        if is_climax:
            canvas = chroma_shake(canvas, i)

        writer.write(canvas)
        if i % log_step == 0:
            print(f"  [RENDER] {int(i/n_frames*100)}%"
                  f"{'  🔥' if is_climax else ''}")

    writer.release()
    print("[RENDER] Re-encoding...")
    cmd = ["ffmpeg","-y","-i",temp,"-c:v","libx264",
           "-preset","fast","-crf","17","-pix_fmt","yuv420p","-an",
           str(OUTPUT_VIDEO)]
    r = subprocess.run(cmd,capture_output=True,text=True)
    if r.returncode != 0:
        shutil.copy(temp, str(OUTPUT_VIDEO))
    else:
        Path(temp).unlink(missing_ok=True)
    print(f"[✓] {OUTPUT_VIDEO} ({OUTPUT_VIDEO.stat().st_size//1024//1024}MB)")


# ══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════

def main():
    print("="*62)
    print("  Pop-Art Kinetic Engine v6")
    print("  GIF Stickers · Radial Gradient · Elastic · Climax")
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

    # Pick palette
    palette      = random.choice(PALETTES)
    climax_pair  = random.choice(CLIMAX_PAIRS)
    accent_bgr   = random.choice(ACCENT_COLORS_BGR)
    wave_bgr     = random.choice(WAVE_COLORS_BGR)

    # Audio duration
    cmd = ["ffprobe","-v","error","-show_entries","format=duration",
           "-of","default=noprint_wrappers=1:nokey=1",str(INPUT_AUDIO)]
    duration = float(subprocess.run(
        cmd,capture_output=True,text=True).stdout.strip())
    n_frames = int(duration*FPS)
    print(f"[INFO] Duration: {duration:.2f}s")

    # Scan for GIF stickers
    keyword_matches = scan_keywords(clean)
    stickers = []
    for (kw, gif_path) in keyword_matches:
        frames = preload_gif(gif_path)
        if frames:
            stickers.append((kw, gif_path, frames))
    if not stickers:
        print("[GIF] No matching GIFs found in /assets — skipping stickers")

    # Word timestamps
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
                 palette, climax_pair, accent_bgr, wave_bgr, stickers)

    print("\n"+"="*62)
    print("  [✓] DONE — raw_video.mp4 ready")
    print("="*62)


if __name__ == "__main__":
    main()
