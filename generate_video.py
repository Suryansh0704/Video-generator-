"""
generate_video.py — Shining Black Minimalist Engine v8
=======================================================
Matrix/Cinematic aesthetic:
  - Deep black radial gradient background
  - Dust particle overlay (60-80 particles)
  - Pixabay GIF + vector sticker assets
  - Pure white elastic typography
  - Neon glow filled area waveform
  - Slow cinematic zoom 1.0→1.1x
  - NO shake — clean cinematic finish
  - 150px safe zone enforced everywhere
  - Headless GitHub Actions compatible
Output: raw_video.mp4 (1080×1920, 30fps, no audio)
"""

import os, re, sys, glob, math, random, shutil
import zipfile, asyncio, subprocess, requests, urllib.request
from pathlib import Path
from io import BytesIO

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
SAFE_PAD    = 150
SAFE_X1     = SAFE_PAD
SAFE_X2     = W - SAFE_PAD
SAFE_Y1     = SAFE_PAD
SAFE_Y2     = H - SAFE_PAD
SAFE_W      = SAFE_X2 - SAFE_X1        # 780px
SAFE_H      = SAFE_Y2 - SAFE_Y1        # 1620px

# ══════════════════════════════════════════════════════════════════
#  PATHS & SECRETS
# ══════════════════════════════════════════════════════════════════

VOICE        = "en-GB-RyanNeural"
PITCH        = "-2Hz"
RATE         = "+15%"

INPUT_SCRIPT = Path("script.txt")
INPUT_AUDIO  = Path("output_voice.wav")
AUDIO_MP3    = Path("output_raw.mp3")
OUTPUT_VIDEO = Path("raw_video.mp4")
ASSETS_DIR   = Path("pixabay_assets")
FONT_PATH    = Path("Montserrat-Bold.ttf")
FONT_URL     = "https://github.com/google/fonts/raw/main/ofl/montserrat/static/Montserrat-Bold.ttf"

PIXABAY_KEY  = os.environ.get("PIXABAY_API_KEY", "")
GH_TOKEN     = os.environ.get("GH_TOKEN", "")

# ══════════════════════════════════════════════════════════════════
#  COLOUR PALETTE — Shining Black
# ══════════════════════════════════════════════════════════════════

BG_CENTER    = (38, 38, 38)         # BGR: Dark Charcoal center
BG_EDGE      = (5,  5,  5)          # BGR: Pure black edge
TEXT_WHITE   = (255, 255, 255)      # Primary text
TEXT_DIM     = (200, 200, 200)      # Secondary text

# Accent options — neon tones that pop on black
ACCENT_OPTIONS = [
    (0,   255, 180),   # Neon cyan-green
    (255, 200,   0),   # Electric yellow
    (200,  80, 255),   # Neon purple
    (0,   200, 255),   # Electric blue
    (80,  255, 120),   # Lime green
    (255,  80, 160),   # Hot pink
]

# Waveform neon glow
WAVE_ACCENT  = (120, 255, 60)       # Lime green fill
WAVE_GLOW    = (60,  180, 30)       # Glow layer

# ══════════════════════════════════════════════════════════════════
#  TYPOGRAPHY
# ══════════════════════════════════════════════════════════════════

FONT_SIZE_BASE  = 92
FONT_SIZE_MIN   = 52
FONT_SIZE_CAPS  = 115
LINE_SPACING    = 24
WORDS_PER_PHRASE = 4
MIN_PHRASE_SEC  = 1.2
ACCENT_CHANCE   = 0.25

# ══════════════════════════════════════════════════════════════════
#  ANIMATION
# ══════════════════════════════════════════════════════════════════

ANIM_IN      = int(FPS * 0.20)
ANIM_OUT     = int(FPS * 0.15)
KB_START     = 1.0
KB_END       = 1.10

# ══════════════════════════════════════════════════════════════════
#  DUST PARTICLES
# ══════════════════════════════════════════════════════════════════

N_PARTICLES  = 70   # 60-80 particles

# ══════════════════════════════════════════════════════════════════
#  STICKER CONFIG
# ══════════════════════════════════════════════════════════════════

STICKER_SIZE        = 190
STICKER_BORDER      = 10
STICKER_SHADOW      = 8
STICKER_FLOAT_AMP   = 12
STICKER_FLOAT_SPEED = 0.06
STICKER_ANIM_FRAMES = int(FPS * 0.22)
STICKER_ROT_RANGE   = 12        # ±12 degrees

# Pixabay keyword extraction — how many to search
MAX_GIF_KEYWORDS    = 4
MAX_VECTOR_KEYWORDS = 3

# Sticker corner positions (well inside safe zone)
STICKER_CORNERS = [
    (SAFE_X1 + 20, SAFE_Y1 + 20),
    (SAFE_X2 - STICKER_SIZE - 20, SAFE_Y1 + 20),
    (SAFE_X1 + 20, int(H*0.73)),
    (SAFE_X2 - STICKER_SIZE - 20, int(H*0.73)),
    (int(W*0.5 - STICKER_SIZE//2), SAFE_Y1 + 20),
]

# ══════════════════════════════════════════════════════════════════
#  WAVEFORM
# ══════════════════════════════════════════════════════════════════

WAVE_Y       = int(H * 0.84)
WAVE_H_PX    = int(H * 0.12)
WAVE_POINTS  = 220

# ══════════════════════════════════════════════════════════════════
#  EFFECTS
# ══════════════════════════════════════════════════════════════════

GRAIN_STRENGTH = 0.025
VIGNETTE_STR   = 0.65
CLIMAX_SECS    = 5.0
MOTION_BLUR_PX = 10


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
            print("[FONT] ✅ Montserrat Bold downloaded")
            return
    except Exception as e:
        print(f"[FONT] Download failed: {e}")
    ttfs = glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)
    bold = [f for f in ttfs if "bold" in f.lower()]
    src  = bold[0] if bold else (ttfs[0] if ttfs else None)
    if src:
        shutil.copy(src, str(FONT_PATH))


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
    if not GH_TOKEN:
        if INPUT_AUDIO.exists():
            return
        sys.exit("[ERROR] GH_TOKEN not set")
    hdrs = {"Authorization": f"Bearer {GH_TOKEN}",
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


def extract_keywords(text: str, n: int = 6) -> list:
    """Extract top N meaningful keywords from script."""
    stops = {
        'the','a','an','and','or','but','in','on','at','to','for',
        'of','with','it','is','was','be','are','were','i','you',
        'he','she','they','we','my','your','just','that','this',
        'have','had','from','not','so','then','when','what','about',
        'like','all','me','us','its','been','would','could','said',
        'told','thought','knew','felt','got','went','came','never',
        'every','their','will','can','one','out','into','only','also'
    }
    words = re.findall(r'\b[a-z]{4,}\b', text.lower())
    freq  = {}
    for w in words:
        if w not in stops:
            freq[w] = freq.get(w, 0) + 1
    sorted_kw = sorted(freq, key=freq.get, reverse=True)
    return sorted_kw[:n]


# ══════════════════════════════════════════════════════════════════
#  PIXABAY API
# ══════════════════════════════════════════════════════════════════

def fetch_pixabay_gif(keyword: str) -> list:
    """
    Fetch animated GIF from Pixabay using keyword.
    Returns list of PIL RGBA frames (pre-processed with border+shadow).
    """
    if not PIXABAY_KEY:
        return []
    try:
        url = (f"https://pixabay.com/api/?key={PIXABAY_KEY}"
               f"&q={requests.utils.quote(keyword)}"
               f"&image_type=animation"
               f"&per_page=5&safesearch=true")
        res  = requests.get(url, timeout=15)
        data = res.json()
        hits = data.get("hits", [])
        if not hits:
            return []
        # Pick the first hit
        hit     = hits[0]
        gif_url = hit.get("previewURL") or hit.get("webformatURL","")
        if not gif_url:
            return []
        r = requests.get(gif_url, timeout=20)
        img_bytes = BytesIO(r.content)
        return process_asset_frames(img_bytes, keyword, "gif")
    except Exception as e:
        print(f"[PIXABAY] GIF fetch failed for '{keyword}': {e}")
        return []


def fetch_pixabay_vector(keyword: str) -> list:
    """
    Fetch transparent PNG/vector sticker from Pixabay.
    Returns list of PIL RGBA frames.
    """
    if not PIXABAY_KEY:
        return []
    try:
        url = (f"https://pixabay.com/api/?key={PIXABAY_KEY}"
               f"&q={requests.utils.quote(keyword)}"
               f"&image_type=vector"
               f"&per_page=5&safesearch=true")
        res  = requests.get(url, timeout=15)
        data = res.json()
        hits = data.get("hits", [])
        if not hits:
            # Fallback: any transparent image
            url2 = (f"https://pixabay.com/api/?key={PIXABAY_KEY}"
                    f"&q={requests.utils.quote(keyword)}+sticker"
                    f"&per_page=5&safesearch=true")
            res   = requests.get(url2, timeout=15)
            hits  = res.json().get("hits", [])
        if not hits:
            return []
        hit     = hits[0]
        img_url = hit.get("previewURL") or hit.get("webformatURL","")
        if not img_url:
            return []
        r = requests.get(img_url, timeout=20)
        return process_asset_frames(BytesIO(r.content), keyword, "vector")
    except Exception as e:
        print(f"[PIXABAY] Vector fetch failed for '{keyword}': {e}")
        return []


def process_asset_frames(img_bytes: BytesIO,
                          keyword: str,
                          asset_type: str) -> list:
    """
    Process image bytes into list of RGBA numpy arrays.
    Applies: resize → white border → drop shadow → rotation.
    """
    rotation = random.uniform(-STICKER_ROT_RANGE, STICKER_ROT_RANGE)
    size_in  = STICKER_SIZE - STICKER_BORDER*2
    frames   = []

    def process_one(fr: Image.Image) -> np.ndarray:
        fr = fr.convert("RGBA").resize((size_in, size_in), Image.LANCZOS)

        # Shadow layer
        sh_size = STICKER_SIZE + STICKER_SHADOW*2
        shadow  = Image.new("RGBA", (sh_size, sh_size), (0,0,0,0))
        sd_base = Image.new("RGBA", (size_in, size_in), (0,0,0,160))
        shadow.alpha_composite(sd_base,
                               (STICKER_BORDER+STICKER_SHADOW+4,
                                STICKER_BORDER+STICKER_SHADOW+4))
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=7))

        # White border
        bordered = Image.new("RGBA", (STICKER_SIZE, STICKER_SIZE),
                             (255,255,255,255))
        bordered.alpha_composite(fr, (STICKER_BORDER, STICKER_BORDER))

        # Composite: shadow + bordered
        final = shadow.copy()
        final.alpha_composite(bordered, (0,0))

        # Rotate
        final = final.rotate(rotation, expand=True,
                              resample=Image.BICUBIC)
        return np.array(final)

    try:
        img = Image.open(img_bytes)
        if hasattr(img, 'n_frames') and img.n_frames > 1:
            while True:
                frames.append(process_one(img.copy()))
                try:
                    img.seek(img.tell()+1)
                except EOFError:
                    break
        else:
            frames.append(process_one(img))
    except Exception as e:
        print(f"[ASSET] Process failed: {e}")

    if frames:
        print(f"[PIXABAY] ✅ '{keyword}' ({asset_type}): "
              f"{len(frames)} frame(s), rot={rotation:.0f}°")
    return frames


def build_sticker_schedule(keywords: list,
                            duration: float) -> list:
    """
    Fetch 4-5 GIFs and 2-3 vectors from Pixabay.
    Returns schedule: [(start_frame, frames, corner_x, corner_y)]
    """
    if not PIXABAY_KEY:
        print("[PIXABAY] No API key — skipping assets")
        return []

    schedule    = []
    gif_kws     = keywords[:MAX_GIF_KEYWORDS]
    vector_kws  = keywords[MAX_GIF_KEYWORDS:MAX_GIF_KEYWORDS+MAX_VECTOR_KEYWORDS]
    used_corners = []

    def pick_corner():
        avail = [c for c in STICKER_CORNERS if c not in used_corners]
        if not avail:
            avail = STICKER_CORNERS
        c = random.choice(avail)
        used_corners.append(c)
        return c

    stagger_base = int(FPS * 2)
    stagger_gap  = int(FPS * 10)

    # Fetch GIFs
    for idx, kw in enumerate(gif_kws):
        frames = fetch_pixabay_gif(kw)
        if frames:
            corner = pick_corner()
            start  = stagger_base + idx * stagger_gap
            if start < int(duration * FPS):
                schedule.append((start, frames, corner[0], corner[1]))

    # Fetch Vectors
    for idx, kw in enumerate(vector_kws):
        frames = fetch_pixabay_vector(kw)
        if frames:
            corner = pick_corner()
            start  = stagger_base + (len(gif_kws)+idx) * stagger_gap
            if start < int(duration * FPS):
                schedule.append((start, frames, corner[0], corner[1]))

    print(f"[PIXABAY] {len(schedule)} assets scheduled")
    return schedule


# ══════════════════════════════════════════════════════════════════
#  DUST PARTICLES
# ══════════════════════════════════════════════════════════════════

class Particle:
    __slots__ = ['x','y','vx','vy','size','alpha']
    def __init__(self):
        self.reset()

    def reset(self):
        self.x     = random.uniform(0, W)
        self.y     = random.uniform(0, H)
        self.vx    = random.uniform(-0.4, 0.4)
        self.vy    = random.uniform(-0.3, 0.5)
        self.size  = random.randint(1, 3)
        self.alpha = random.randint(20, 90)

    def update(self):
        self.x += self.vx
        self.y += self.vy
        # Wrap around edges
        if self.x < 0:   self.x = W
        if self.x > W:   self.x = 0
        if self.y < 0:   self.y = H
        if self.y > H:   self.y = 0


def init_particles() -> list:
    return [Particle() for _ in range(N_PARTICLES)]


def draw_particles(canvas: np.ndarray,
                   particles: list) -> None:
    for p in particles:
        px, py = int(p.x), int(p.y)
        if 0 <= px < W and 0 <= py < H:
            col = (p.alpha, p.alpha, p.alpha)
            cv2.circle(canvas, (px, py), p.size, col, -1, cv2.LINE_AA)
        p.update()


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
                words.append({"word":w,
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
        s = int(i*spf); e = min(int(s+spf),len(y))
        c = y[s:e]
        if not len(c): continue
        rms_arr[i] = float(np.sqrt(np.mean(c**2)))
        if len(c)>=WAVE_POINTS:
            idx=np.linspace(0,len(c)-1,WAVE_POINTS).astype(int)
            wave_arr[i]=c[idx]
        else:
            wave_arr[i,:len(c)]=c
    mx = rms_arr.max()
    if mx>0: rms_arr/=mx
    print(f"[AUDIO] {duration:.2f}s analysed")
    return rms_arr, wave_arr, duration


# ══════════════════════════════════════════════════════════════════
#  BACKGROUND — Shining Black Radial Gradient
# ══════════════════════════════════════════════════════════════════

def build_black_gradient() -> np.ndarray:
    xs = np.linspace(-1,1,W); ys = np.linspace(-1,1,H)
    X,Y  = np.meshgrid(xs,ys)
    dist = np.clip(np.sqrt(X**2+Y**2)/np.sqrt(2),0,1)
    bg   = np.zeros((H,W,3),dtype=np.uint8)
    for c in range(3):
        bg[:,:,c] = (BG_CENTER[c]*(1-dist)+BG_EDGE[c]*dist).astype(np.uint8)
    return bg


# ══════════════════════════════════════════════════════════════════
#  NEON GLOW FILLED AREA WAVEFORM
# ══════════════════════════════════════════════════════════════════

def draw_neon_waveform(canvas: np.ndarray,
                       wave: np.ndarray,
                       rms: float,
                       is_climax: bool) -> None:
    mul  = 1.6 if is_climax else 1.0
    amp  = min(WAVE_H_PX*1.6, WAVE_H_PX*(0.10+rms*0.90)*mul)
    xs   = np.linspace(SAFE_X1, SAFE_X2, WAVE_POINTS).astype(int)
    kern = np.ones(13)/13   # Smooth kernel for cinematic look
    ws   = np.convolve(wave, kern, mode='same')
    ys   = np.clip((WAVE_Y - ws*amp).astype(int), SAFE_Y1, H-SAFE_PAD)

    # Gradient brightness center-to-edge
    ci   = WAVE_POINTS//2

    # ── Pass 1: wide glow ────────────────────────────────────────
    pts  = np.array([(int(xs[i]),int(ys[i])) for i in range(WAVE_POINTS)],
                    dtype=np.int32).reshape(-1,1,2)
    ov   = canvas.copy()
    cv2.polylines(ov,[pts],False,WAVE_GLOW,16,cv2.LINE_AA)
    cv2.addWeighted(ov,0.35,canvas,0.65,0,canvas)

    # ── Pass 2: medium glow ───────────────────────────────────────
    ov2  = canvas.copy()
    cv2.polylines(ov2,[pts],False,WAVE_GLOW,8,cv2.LINE_AA)
    cv2.addWeighted(ov2,0.55,canvas,0.45,0,canvas)

    # ── Pass 3: filled polygon ────────────────────────────────────
    top_pts  = [(int(xs[i]),int(ys[i])) for i in range(WAVE_POINTS)]
    base_pts = [(int(xs[i]),WAVE_Y) for i in range(WAVE_POINTS-1,-1,-1)]
    poly     = np.array(top_pts+base_pts, dtype=np.int32)
    fill_col = tuple(max(0,int(c*0.45)) for c in WAVE_ACCENT)
    cv2.fillPoly(canvas,[poly],fill_col)

    # ── Pass 4: bright top edge line ─────────────────────────────
    for i in range(WAVE_POINTS-1):
        brt  = max(0.30, 1.0-abs(i-ci)/ci*0.65)
        col  = tuple(int(c*brt) for c in WAVE_ACCENT)
        cv2.line(canvas,(int(xs[i]),int(ys[i])),
                 (int(xs[i+1]),int(ys[i+1])),col,2,cv2.LINE_AA)

    # ── Peak sparkle ─────────────────────────────────────────────
    pi2 = int(np.argmax(np.abs(ws)))
    cv2.circle(canvas,(int(xs[pi2]),int(ys[pi2])),5,
               (255,255,255),-1,cv2.LINE_AA)
    cv2.circle(canvas,(int(xs[pi2]),int(ys[pi2])),9,
               WAVE_ACCENT,2,cv2.LINE_AA)


# ══════════════════════════════════════════════════════════════════
#  PHRASE RENDERING — WHITE TEXT ON BLACK
# ══════════════════════════════════════════════════════════════════

def measure_text(text: str, font: ImageFont.FreeTypeFont) -> tuple:
    tmp  = Image.new("RGBA",(1,1))
    draw = ImageDraw.Draw(tmp)
    bbox = draw.textbbox((0,0),text,font=font)
    return bbox[2]-bbox[0], bbox[3]-bbox[1]


def fit_font_size(word: str, is_cap: bool) -> tuple:
    base = FONT_SIZE_CAPS if is_cap else FONT_SIZE_BASE
    for size in range(base, FONT_SIZE_MIN-1, -4):
        font    = get_font(size)
        tw, _   = measure_text(word, font)
        if tw <= SAFE_W - 40:
            return font, size
    return get_font(FONT_SIZE_MIN), FONT_SIZE_MIN


def wrap_words(word_data: list, max_w: int) -> list:
    lines, cur, cw = [], [], 0
    GAP = 16
    for wd in word_data:
        needed = wd["w"] + (GAP if cur else 0)
        if cur and cw+needed > max_w:
            lines.append(cur); cur,cw = [wd], wd["w"]
        else:
            cur.append(wd); cw += needed
    if cur: lines.append(cur)
    return lines


def render_phrase_image(text: str,
                        use_accent: bool,
                        accent_col: tuple) -> Image.Image:
    """
    White text on transparent background.
    Accent words get neon glow + underline.
    Safe-zone width enforced with auto-wrap + auto-shrink.
    """
    raw_words = text.split()
    PAD       = 20
    GAP_X     = 16
    MAX_W     = SAFE_W - PAD*2 - 20

    word_data = []
    for w in raw_words:
        is_cap = bool(re.search(r'[A-Z]{2,}', w))
        is_acc = is_cap or use_accent
        color  = accent_col if is_acc else TEXT_WHITE
        font, sz = fit_font_size(w, is_cap)
        tw, th   = measure_text(w, font)
        word_data.append({
            "text":w,"font":font,"sz":sz,"color":color,
            "w":tw,"h":th,"is_acc":is_acc,"is_cap":is_cap
        })

    lines   = wrap_words(word_data, MAX_W)
    lh_list = [max(wd["h"] for wd in l) for l in lines]
    tot_h   = sum(lh_list) + LINE_SPACING*(len(lines)-1) + PAD*2
    tot_w   = min(SAFE_W, MAX_W + PAD*2)

    img  = Image.new("RGBA",(max(1,tot_w),max(1,tot_h)),(0,0,0,0))
    draw = ImageDraw.Draw(img)
    y    = PAD

    for li, line in enumerate(lines):
        lw = sum(wd["w"] for wd in line)+GAP_X*(len(line)-1)
        x  = (tot_w-lw)//2
        lh = lh_list[li]
        for wd in line:
            rgb = (wd["color"][2],wd["color"][1],wd["color"][0])
            if wd["is_acc"]:
                # Neon glow
                glow = tuple(min(255,int(c*1.35)) for c in rgb)
                for gd,ga in [(8,35),(5,65),(3,95)]:
                    for dx,dy in [(gd,0),(-gd,0),(0,gd),(0,-gd)]:
                        draw.text((x+dx,y+dy),wd["text"],
                                  font=wd["font"],fill=glow+(ga,))
                draw.line([(x,y+wd["h"]+4),(x+wd["w"],y+wd["h"]+4)],
                          fill=rgb+(210,),width=3)
            else:
                # Subtle glow on white text
                draw.text((x+1,y+1),wd["text"],font=wd["font"],
                          fill=(255,255,255,50))
            draw.text((x,y),wd["text"],font=wd["font"],fill=rgb+(255,))
            x += wd["w"]+GAP_X
        y += lh+LINE_SPACING

    return img


# ══════════════════════════════════════════════════════════════════
#  PHRASE GROUPING
# ══════════════════════════════════════════════════════════════════

def group_into_phrases(word_timestamps: list,
                       duration: float,
                       accent_col: tuple) -> list:
    phrases       = []
    climax_start  = duration - CLIMAX_SECS
    entrances     = ["fly_left","fly_right","fly_bottom",
                     "fly_left","fly_right","fly_bottom"]
    n_total       = max(1, len(word_timestamps)//WORDS_PER_PHRASE)
    accent_set    = set(random.sample(
        range(n_total), max(1, int(n_total*ACCENT_CHANCE))
    ))

    prev_y = None; i = 0; pi = 0
    while i < len(word_timestamps):
        group = word_timestamps[i:i+WORDS_PER_PHRASE]
        text  = ' '.join(w["word"] for w in group)
        clean = re.sub(r'[^a-zA-Z0-9\'\-!?.,"\s]','',text).strip()
        if not clean:
            i += WORDS_PER_PHRASE; pi += 1; continue

        start_sec = group[0]["start"]
        end_sec   = group[-1]["start"]+group[-1]["duration"]
        if end_sec-start_sec < MIN_PHRASE_SEC:
            end_sec = start_sec+MIN_PHRASE_SEC

        has_caps  = bool(re.search(r'[A-Z]{2,}', text))
        is_climax = start_sec >= climax_start
        use_acc   = has_caps or (pi in accent_set)
        entrance  = random.choice(entrances)

        # Non-overlapping Y
        for _ in range(12):
            ry = random.randint(int(H*0.20), int(H*0.60))
            if prev_y is None or abs(ry-prev_y) > 180: break
        prev_y = ry
        rx = random.randint(SAFE_X1+60, SAFE_X2-60)

        phrases.append({
            "text": clean, "start_sec": start_sec,
            "end_sec": end_sec, "has_caps": has_caps,
            "is_climax": is_climax, "entrance": entrance,
            "rand_x": rx, "rand_y": ry,
            "use_accent": use_acc,
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
    if t<=0: return 0.0
    if t>=1: return 1.0
    return 1+(2**(-10*t))*math.sin((t-0.075)*2*math.pi/0.3)


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
#  COMPOSITE PHRASE
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
        scale = max(0.1, 0.5+e*0.6)
        alpha = min(1.0, t*3.5)
        offsets = {
            "fly_left":   (int((1-t)*(-iw-80)),0),
            "fly_right":  (int((1-t)*(W+80)),0),
            "fly_top":    (0,int((1-t)*(-ih-80))),
            "fly_bottom": (0,int((1-t)*(H+80))),
        }
        xo,yo = offsets.get(entrance,(0,0))
        img   = motion_blur(img, entrance, t)
    elif frame_out < ANIM_OUT:
        scale,alpha,xo,yo = 1.0,frame_out/ANIM_OUT,0,0
    else:
        scale,alpha,xo,yo = 1.0,1.0,0,0

    if alpha_override is not None:
        alpha = alpha_override
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(radius=5))

    disp = img
    if abs(scale-1.0)>0.01:
        nw,nh = max(1,int(iw*scale)),max(1,int(ih*scale))
        disp  = img.resize((nw,nh),Image.LANCZOS)

    # Safe-zone clamped position
    px = max(SAFE_X1, min(SAFE_X2-disp.width,  cx-disp.width//2+xo))
    py = max(SAFE_Y1, min(SAFE_Y2-disp.height, cy-disp.height//2+yo))

    cr = cv2.cvtColor(canvas,cv2.COLOR_BGR2RGB)
    cp = Image.fromarray(cr).convert("RGBA")
    r,g,b,a = disp.split()
    a = a.point(lambda v: int(v*max(0.0,min(1.0,alpha))))
    disp = Image.merge("RGBA",(r,g,b,a))
    cp.alpha_composite(disp,(max(0,px),max(0,py)))
    np.copyto(canvas, cv2.cvtColor(
        np.array(cp.convert("RGB")),cv2.COLOR_RGB2BGR))


# ══════════════════════════════════════════════════════════════════
#  COMPOSITE STICKER
# ══════════════════════════════════════════════════════════════════

def composite_sticker(canvas: np.ndarray,
                      frames: list,
                      frame_idx: int,
                      start_frame: int,
                      corner_x: int,
                      corner_y: int) -> None:
    if not frames: return
    since  = frame_idx - start_frame
    gif_i  = (since//2) % len(frames)
    raw    = frames[gif_i]

    if since < STICKER_ANIM_FRAMES:
        t     = since/STICKER_ANIM_FRAMES
        scale = max(0.05, elastic_out(t)*1.1)
        alpha = min(1.0, t*4)
    else:
        scale = 1.0; alpha = 1.0

    float_y = int(STICKER_FLOAT_AMP*math.sin(since*STICKER_FLOAT_SPEED))

    sh,sw = raw.shape[:2]
    if abs(scale-1.0)>0.01:
        nw,nh = max(1,int(sw*scale)),max(1,int(sh*scale))
        disp  = cv2.resize(raw,(nw,nh))
    else:
        disp = raw
    dh,dw = disp.shape[:2]

    # Clamp to safe zone
    px = max(SAFE_X1, min(SAFE_X2-dw, corner_x))
    py = max(SAFE_Y1, min(SAFE_Y2-dh, corner_y+float_y))

    cr = cv2.cvtColor(canvas,cv2.COLOR_BGR2RGB)
    cp = Image.fromarray(cr).convert("RGBA")
    si = Image.fromarray(disp)
    r,g,b,a = si.split()
    a  = a.point(lambda v: int(v*alpha))
    si = Image.merge("RGBA",(r,g,b,a))
    cp.alpha_composite(si,(max(0,px),max(0,py)))
    np.copyto(canvas, cv2.cvtColor(
        np.array(cp.convert("RGB")),cv2.COLOR_RGB2BGR))


# ══════════════════════════════════════════════════════════════════
#  ATMOSPHERIC LAYERS
# ══════════════════════════════════════════════════════════════════

def build_vignette() -> np.ndarray:
    xs = np.linspace(-1,1,W); ys = np.linspace(-1,1,H)
    X,Y  = np.meshgrid(xs,ys)
    dist = np.sqrt(X**2+Y**2)
    mask = 1.0-np.clip(dist/dist.max()*VIGNETTE_STR,0,1)
    return mask.reshape(H,W,1).astype(np.float32)


def apply_grain(canvas: np.ndarray, frame_idx: int) -> np.ndarray:
    rng   = np.random.RandomState(frame_idx*17+3)
    noise = rng.randint(-15,16,(H,W,3),dtype=np.int16)
    out   = canvas.astype(np.int16)+(noise*GRAIN_STRENGTH).astype(np.int16)
    return np.clip(out,0,255).astype(np.uint8)


def ken_burns(frame: np.ndarray, idx: int, total: int) -> np.ndarray:
    t  = idx/max(1,total-1)
    s  = KB_START+t*(KB_END-KB_START)
    if abs(s-1.0)<0.002: return frame
    nw,nh = int(W*s),int(H*s)
    big   = cv2.resize(frame,(nw,nh))
    ox,oy = (nw-W)//2,(nh-H)//2
    return big[oy:oy+H,ox:ox+W]


def caps_flash(canvas: np.ndarray,
               intensity: float, accent: tuple) -> np.ndarray:
    ov = np.full_like(canvas, accent, dtype=np.uint8)
    return cv2.addWeighted(canvas,1-intensity*0.10,ov,intensity*0.10,0)


# ══════════════════════════════════════════════════════════════════
#  MAIN RENDER
# ══════════════════════════════════════════════════════════════════

def render_video(phrases: list,
                 rms_arr: np.ndarray,
                 wave_arr: np.ndarray,
                 duration: float,
                 accent_bgr: tuple,
                 sticker_schedule: list) -> None:

    n_frames     = len(rms_arr)
    vignette     = build_vignette()
    bg_base      = build_black_gradient()
    particles    = init_particles()
    climax_start = int((duration-CLIMAX_SECS)*FPS)

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    temp   = "raw_temp.mp4"
    writer = cv2.VideoWriter(temp,fourcc,FPS,(W,H))
    if not writer.isOpened():
        sys.exit("[ERROR] VideoWriter failed")

    print(f"[RENDER] {n_frames} frames | {len(phrases)} phrases | "
          f"{len(sticker_schedule)} sticker(s)")

    # Pre-render phrase images
    for p in phrases:
        p["img"] = render_phrase_image(
            p["text"], p["use_accent"], accent_bgr)
        p["sf"] = int(p["start_sec"]*FPS)
        p["ef"] = min(int(p["end_sec"]*FPS), n_frames)

    frame_phrase = {}
    for pi,p in enumerate(phrases):
        p["pi"] = pi
        for f in range(p["sf"],p["ef"]):
            frame_phrase[f] = p

    flash_cnt   = 0
    prev_phrase = None
    log_step    = max(1, n_frames//20)

    for i in range(n_frames):
        is_climax = i >= climax_start

        # Shining black background
        canvas = bg_base.copy()

        # Dust particles
        draw_particles(canvas, particles)

        # Neon waveform
        draw_neon_waveform(canvas, wave_arr[i], rms_arr[i], is_climax)

        cur = frame_phrase.get(i)

        # Previous phrase at 20% + blur (persistence)
        if (prev_phrase is not None and cur is not None
                and cur["pi"] != prev_phrase["pi"]):
            since_end = i-prev_phrase["ef"]
            if since_end < int(FPS*0.35):
                la = 0.20*(1-since_end/int(FPS*0.35))
                composite_phrase(canvas, prev_phrase["img"],
                                 prev_phrase["ef"]-prev_phrase["sf"],999,
                                 prev_phrase["entrance"],
                                 prev_phrase["rand_x"],prev_phrase["rand_y"],
                                 alpha_override=la, blur=True)

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
        for (st_start, st_frames, sx, sy) in sticker_schedule:
            if i >= st_start:
                composite_sticker(canvas, st_frames, i, st_start, sx, sy)

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
        canvas = apply_grain(canvas, i)

        # NO SHAKE — clean cinematic finish

        writer.write(canvas)
        if i % log_step == 0:
            print(f"  [RENDER] {int(i/n_frames*100)}%"
                  f"{'  ✨' if is_climax else ''}")

    writer.release()
    print("[RENDER] Re-encoding...")
    r = subprocess.run(
        ["ffmpeg","-y","-i",temp,"-c:v","libx264",
         "-preset","fast","-crf","17","-pix_fmt","yuv420p","-an",
         str(OUTPUT_VIDEO)],
        capture_output=True, text=True)
    if r.returncode != 0:
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
    print("  Shining Black Minimalist Engine v8")
    print("  Matrix · Dust Particles · Pixabay · Neon Waveform")
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

    accent_bgr = random.choice(ACCENT_OPTIONS)

    # Audio duration
    cmd = ["ffprobe","-v","error","-show_entries","format=duration",
           "-of","default=noprint_wrappers=1:nokey=1",str(INPUT_AUDIO)]
    duration = float(subprocess.run(
        cmd,capture_output=True,text=True).stdout.strip())
    n_frames = int(duration*FPS)
    print(f"[INFO] Duration: {duration:.2f}s")

    # Pixabay assets
    keywords = extract_keywords(clean, n=MAX_GIF_KEYWORDS+MAX_VECTOR_KEYWORDS)
    print(f"[PIXABAY] Keywords: {keywords}")
    sticker_schedule = build_sticker_schedule(keywords, duration)

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
                 accent_bgr, sticker_schedule)

    print("\n"+"="*62)
    print("  [✓] DONE — raw_video.mp4 ready")
    print("="*62)


if __name__ == "__main__":
    main()
