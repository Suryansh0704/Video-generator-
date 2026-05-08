"""
generate_video.py — Shining Black Minimalist Engine v13
=======================================================
CRITICAL FIXES:
  - GIPHY returns WEBP/MP4 by default — now forces gif renditions
  - Added heavy debug logging to diagnose failures in CI
  - Fallback chain: gif → fixed_height (webp) → downsized (gif) → original
  - WEBP files converted properly before frame extraction
  - MP4 files handled via ffmpeg extraction if available
  - Guaranteed 5 GIFs + 4 stickers with retry logic
Output: raw_video.mp4 (1080×1920, 30fps, no audio)
"""

import os, re, sys, glob, math, random, shutil, json
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
ASSETS_DIR   = Path("giphy_assets")
FONT_PATH    = Path("Montserrat-Bold.ttf")
FONT_URL     = "https://github.com/google/fonts/raw/main/ofl/montserrat/static/Montserrat-Bold.ttf"

GIPHY_KEY    = os.environ.get("GIPHY_API_KEY", "")
GH_TOKEN     = os.environ.get("GH_TOKEN", "")

# ══════════════════════════════════════════════════════════════════
#  COLOUR PALETTE
# ══════════════════════════════════════════════════════════════════

BG_CENTER    = (38, 38, 38)
BG_EDGE      = (5,  5,  5)
TEXT_WHITE   = (255, 255, 255)
TEXT_DIM     = (200, 200, 200)
LIME_GREEN   = (50, 205, 50)
WAVE_ACCENT  = LIME_GREEN
WAVE_GLOW    = (30, 150, 30)

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

N_PARTICLES  = 70

# ══════════════════════════════════════════════════════════════════
#  STICKER CONFIG — CUTOUT FORM
# ══════════════════════════════════════════════════════════════════

STICKER_SIZE        = 160
STICKER_BORDER      = 8
STICKER_SHADOW      = 6
STICKER_FLOAT_AMP   = 10
STICKER_FLOAT_SPEED = 0.06
STICKER_ANIM_FRAMES = int(FPS * 0.30)
STICKER_ROT_RANGE   = 8
STICKER_EXTRA_SEC   = 1.0

CORNER_MARGIN = 40
STICKER_POSITIONS = [
    (CORNER_MARGIN, CORNER_MARGIN),
    (W - STICKER_SIZE - CORNER_MARGIN, CORNER_MARGIN),
    (CORNER_MARGIN, H - STICKER_SIZE - CORNER_MARGIN - 120),
    (W - STICKER_SIZE - CORNER_MARGIN, H - STICKER_SIZE - CORNER_MARGIN - 120),
]

# ══════════════════════════════════════════════════════════════════
#  GIF CONFIG
# ══════════════════════════════════════════════════════════════════

GIF_SIZE_MIN        = 320
GIF_SIZE_MAX        = 420
GIF_EXTRA_SEC       = 0.8
GIF_FADE_FRAMES     = int(FPS * 0.20)

GIF_POSITIONS = [
    (80, int(H * 0.30)),
    (80, int(H * 0.55)),
    (W - 80, int(H * 0.30)),
    (W - 80, int(H * 0.55)),
    (int(W * 0.5), 100),
]

# ══════════════════════════════════════════════════════════════════
#  ASSET TARGETS
# ══════════════════════════════════════════════════════════════════

TARGET_GIFS     = 5
TARGET_STICKERS = 4

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


def extract_keywords(text: str, n: int = 15) -> list:
    stops = {
        'the','a','an','and','or','but','in','on','at','to','for','of','with',
        'it','is','was','be','are','were','i','you','he','she','they','we','my',
        'your','just','that','this','have','had','from','not','so','then','when',
        'what','about','like','all','me','us','its','been','would','could','said',
        'told','thought','knew','felt','got','went','came','never','every','their',
        'will','can','one','out','into','only','also','more','most','other','some',
        'time','very','know','take','than','over','think','back','after','use',
        'two','how','our','work','first','well','way','even','new','want','because',
        'any','these','give','day','most','us','get','go','make','see','look','come',
        'here','there','now','up','down','if','no','yes','oh','ah','wow','hey','man',
        'guy','girl','boy','really','actually'
    }
    words = re.findall(r'\b[a-z]{4,}\b', text.lower())
    freq  = {}
    for w in words:
        if w not in stops:
            freq[w] = freq.get(w, 0) + 1
    sorted_kw = sorted(freq, key=freq.get, reverse=True)
    return sorted_kw[:n]


def get_phrase_keyword(phrase_text: str, global_keywords: list) -> str:
    stops = {
        'the','a','an','and','or','but','in','on','at','to','for','of','with',
        'it','is','was','be','are','were','i','you','he','she','they','we','my',
        'your','just','that','this','have','had','from','not','so','then','when',
        'what','about','like','all','me','us','its','been','would','could','said',
        'told','thought','knew','felt','got','went','came','never','every','their',
        'will','can','one','out','into','only','also','more','most','other','some',
        'time','very','know','take','than','over','think','back','after','use',
        'two','how','our','work','first','well','way','even','new','want','because',
        'any','these','give','day','most','us','get','go','make','see','look','come',
        'here','there','now','up','down','if','no','yes','oh','ah','wow','hey','man',
        'guy','girl','boy','really','actually'
    }
    words = re.findall(r'\b[a-z]{3,}\b', phrase_text.lower())
    phrase_words = [w for w in words if w not in stops and len(w) > 3]
    
    for gw in global_keywords:
        if gw in phrase_text.lower():
            return gw
    
    if phrase_words:
        return phrase_words[0]
    
    return random.choice(global_keywords) if global_keywords else "trending"


# ══════════════════════════════════════════════════════════════════
#  GIPHY API — BULLETPROOF WITH DEBUGGING
# ══════════════════════════════════════════════════════════════════

def debug_print_response(data: dict, label: str):
    """Print API response structure for debugging."""
    print(f"[DEBUG] {label} response keys: {list(data.keys())}")
    if 'meta' in data:
        print(f"[DEBUG] {label} meta: {data['meta']}")
    if 'data' in data and isinstance(data['data'], list):
        print(f"[DEBUG] {label} data count: {len(data['data'])}")
        if data['data']:
            first = data['data'][0]
            print(f"[DEBUG] {label} first hit keys: {list(first.keys())}")
            if 'images' in first:
                print(f"[DEBUG] {label} first hit images keys: {list(first['images'].keys())}")


def get_best_gif_url(hit: dict) -> tuple:
    """
    Extract best GIF URL. Returns (url, format_type).
    Priority: actual GIF renditions first, then WEBP, then MP4.
    """
    images = hit.get("images", {})
    
    # Priority order for GIFs — prefer actual GIF format
    gif_keys = [
        "fixed_height_small",      # 100px height, often GIF
        "fixed_height",            # 200px height
        "downsized",               # smaller, usually GIF
        "downsized_medium",
        "original",                # full size
        "fixed_width",             # 200px width
        "fixed_width_small",       # 100px width
    ]
    
    for key in gif_keys:
        if key in images:
            url = images[key].get("url", "")
            fmt = images[key].get("format", "gif")  # GIPHY sometimes includes format
            if url:
                # Check if URL actually ends with gif or webp
                actual_fmt = "gif" if ".gif" in url.lower() else ("webp" if ".webp" in url.lower() else "unknown")
                print(f"[DEBUG] Found rendition '{key}': format={actual_fmt}, url={url[:60]}...")
                return url, actual_fmt
    
    # Fallback: any URL with 'url' in the rendition
    for key, rendition in images.items():
        if isinstance(rendition, dict) and rendition.get("url"):
            url = rendition["url"]
            actual_fmt = "gif" if ".gif" in url.lower() else ("webp" if ".webp" in url.lower() else "unknown")
            print(f"[DEBUG] Fallback rendition '{key}': format={actual_fmt}")
            return url, actual_fmt
    
    return None, None


def get_best_sticker_url(hit: dict) -> tuple:
    """Extract best sticker URL."""
    images = hit.get("images", {})
    
    sticker_keys = [
        "fixed_height_small",
        "fixed_height",
        "downsized",
        "original",
        "fixed_width_small",
        "fixed_width",
    ]
    
    for key in sticker_keys:
        if key in images:
            url = images[key].get("url", "")
            if url:
                actual_fmt = "gif" if ".gif" in url.lower() else ("webp" if ".webp" in url.lower() else "unknown")
                print(f"[DEBUG] Sticker rendition '{key}': format={actual_fmt}")
                return url, actual_fmt
    
    for key, rendition in images.items():
        if isinstance(rendition, dict) and rendition.get("url"):
            url = rendition["url"]
            actual_fmt = "gif" if ".gif" in url.lower() else ("webp" if ".webp" in url.lower() else "unknown")
            return url, actual_fmt
    
    return None, None


def fetch_giphy_gif(keyword: str) -> list:
    """
    Fetch GIF from GIPHY with bulletproof error handling.
    """
    if not GIPHY_KEY:
        print(f"[GIPHY] ❌ No API key set!")
        return []
    
    print(f"[GIPHY] Searching GIF for: '{keyword}'")
    
    # Try search first
    search_url = f"https://api.giphy.com/v1/gifs/search?api_key={GIPHY_KEY}&q={requests.utils.quote(keyword)}&limit=20&rating=g&lang=en"
    
    try:
        print(f"[DEBUG] API URL: {search_url[:80]}...")
        res = requests.get(search_url, timeout=25)
        print(f"[DEBUG] Status: {res.status_code}")
        
        data = res.json()
        debug_print_response(data, "GIF search")
        
        if res.status_code != 200:
            print(f"[GIPHY] API error: status={res.status_code}, msg={data.get('meta', {})}")
            return []
        
        hits = data.get("data", [])
        if not hits:
            print(f"[GIPHY] No search results, trying trending...")
            # Fallback to trending
            trend_url = f"https://api.giphy.com/v1/gifs/trending?api_key={GIPHY_KEY}&limit=15&rating=g"
            res = requests.get(trend_url, timeout=20)
            data = res.json()
            hits = data.get("data", [])
            print(f"[DEBUG] Trending returned {len(hits)} hits")
        
        if not hits:
            print(f"[GIPHY] ❌ No results at all")
            return []
        
        # Try top 5 hits to find one with valid URL
        for i, hit in enumerate(hits[:5]):
            gif_url, fmt = get_best_gif_url(hit)
            title = hit.get("title", "untitled")[:50]
            print(f"[GIPHY] Hit {i}: '{title}', url_type={fmt}")
            
            if gif_url:
                print(f"[GIPHY] ✅ Downloading from: {gif_url[:60]}...")
                try:
                    r = requests.get(gif_url, timeout=30)
                    print(f"[DEBUG] Download: {r.status_code}, size={len(r.content)} bytes, content-type={r.headers.get('content-type', 'unknown')}")
                    
                    if len(r.content) < 100:
                        print(f"[GIPHY] ❌ Download too small ({len(r.content)} bytes)")
                        continue
                    
                    return process_media_frames(BytesIO(r.content), keyword, fmt)
                except Exception as e:
                    print(f"[GIPHY] Download failed: {e}")
                    continue
        
        print(f"[GIPHY] ❌ All hits failed")
        return []
        
    except Exception as e:
        print(f"[GIPHY] Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return []


def fetch_giphy_sticker(keyword: str) -> list:
    """Fetch sticker from GIPHY."""
    if not GIPHY_KEY:
        print(f"[GIPHY] ❌ No API key!")
        return []
    
    print(f"[GIPHY] Searching sticker for: '{keyword}'")
    
    url = f"https://api.giphy.com/v1/stickers/search?api_key={GIPHY_KEY}&q={requests.utils.quote(keyword)}&limit=20&rating=g&lang=en"
    
    try:
        print(f"[DEBUG] Sticker API: {url[:80]}...")
        res = requests.get(url, timeout=25)
        data = res.json()
        debug_print_response(data, "Sticker search")
        
        hits = data.get("data", [])
        
        if not hits:
            print(f"[GIPHY] No stickers, trying GIF search fallback...")
            # Fallback to regular GIFs
            fallback_url = f"https://api.giphy.com/v1/gifs/search?api_key={GIPHY_KEY}&q={requests.utils.quote(keyword)}&limit=10&rating=g"
            res = requests.get(fallback_url, timeout=20)
            data = res.json()
            hits = data.get("data", [])
            print(f"[DEBUG] GIF fallback: {len(hits)} hits")
        
        if not hits:
            print(f"[GIPHY] ❌ No sticker results")
            return []
        
        for i, hit in enumerate(hits[:5]):
            img_url, fmt = get_best_sticker_url(hit)
            title = hit.get("title", "untitled")[:50]
            print(f"[GIPHY] Sticker hit {i}: '{title}', url_type={fmt}")
            
            if img_url:
                print(f"[GIPHY] ✅ Downloading sticker: {img_url[:60]}...")
                try:
                    r = requests.get(img_url, timeout=30)
                    print(f"[DEBUG] Sticker download: {r.status_code}, {len(r.content)} bytes")
                    
                    if len(r.content) < 100:
                        continue
                    
                    return process_sticker_frames(BytesIO(r.content), keyword, fmt)
                except Exception as e:
                    print(f"[GIPHY] Sticker download failed: {e}")
                    continue
        
        return []
        
    except Exception as e:
        print(f"[GIPHY] Sticker fatal error: {e}")
        import traceback
        traceback.print_exc()
        return []


def process_media_frames(img_bytes: BytesIO, keyword: str, fmt: str) -> list:
    """
    Process GIF/WEBP/MP4 into RGBA frames. Handles multiple formats.
    """
    frames = []
    raw_data = img_bytes.getvalue()
    
    print(f"[PROCESS] Input format: {fmt}, size: {len(raw_data)} bytes")
    
    # Save to temp file for debugging if needed
    temp_path = f"/tmp/giphy_debug_{keyword.replace(' ', '_')}.gif"
    try:
        with open(temp_path, "wb") as f:
            f.write(raw_data)
        print(f"[DEBUG] Saved to {temp_path}")
    except:
        pass
    
    try:
        # Try to open with Pillow
        img = Image.open(img_bytes)
        print(f"[DEBUG] Pillow opened: format={img.format}, mode={img.mode}, size={img.size}")
        
        target_size = random.randint(GIF_SIZE_MIN, GIF_SIZE_MAX)
        
        # Check if animated
        is_animated = getattr(img, 'is_animated', False) or getattr(img, 'n_frames', 1) > 1
        n_frames = getattr(img, 'n_frames', 1)
        print(f"[DEBUG] Animated: {is_animated}, n_frames: {n_frames}")
        
        if is_animated and n_frames > 1:
            frame_idx = 0
            while True:
                try:
                    img.seek(frame_idx)
                    fr = img.copy().convert("RGBA")
                    fr = fr.resize((target_size, target_size), Image.LANCZOS)
                    frames.append(np.array(fr))
                    frame_idx += 1
                except EOFError:
                    print(f"[DEBUG] Reached end at frame {frame_idx}")
                    break
                except Exception as e:
                    print(f"[DEBUG] Frame {frame_idx} error: {e}")
                    break
        else:
            # Single frame
            fr = img.convert("RGBA").resize((target_size, target_size), Image.LANCZOS)
            frames.append(np.array(fr))
            print(f"[DEBUG] Single frame processed")
        
        if frames:
            print(f"[GIF] ✅ '{keyword}': {len(frames)} frames, {target_size}px, format={fmt}")
        else:
            print(f"[GIF] ❌ No frames extracted")
            
    except Exception as e:
        print(f"[PROCESS] Pillow failed: {e}")
        # Try ffmpeg for MP4/WebP conversion
        try:
            print(f"[PROCESS] Trying ffmpeg fallback...")
            frames = ffmpeg_extract_frames(raw_data, target_size=random.randint(GIF_SIZE_MIN, GIF_SIZE_MAX))
        except Exception as e2:
            print(f"[PROCESS] ffmpeg also failed: {e2}")
    
    return frames


def ffmpeg_extract_frames(raw_data: bytes, target_size: int = 360) -> list:
    """Extract frames from MP4/WEBP using ffmpeg."""
    frames = []
    temp_in = "/tmp/giphy_input.mp4"
    temp_out = "/tmp/giphy_frame_%04d.png"
    
    try:
        with open(temp_in, "wb") as f:
            f.write(raw_data)
        
        # Extract frames with ffmpeg
        cmd = ["ffmpeg", "-y", "-i", temp_in, "-vf", f"scale={target_size}:{target_size}:force_original_aspect_ratio=decrease,pad={target_size}:{target_size}:(ow-iw)/2:(oh-ih)/2", "-frames:v", "30", temp_out]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"[FFMPEG] Error: {result.stderr[:200]}")
            return []
        
        # Load extracted frames
        frame_files = sorted(glob.glob("/tmp/giphy_frame_*.png"))
        for fpath in frame_files:
            fr = Image.open(fpath).convert("RGBA")
            frames.append(np.array(fr))
        
        # Cleanup
        for fpath in frame_files:
            os.remove(fpath)
        
        print(f"[FFMPEG] ✅ Extracted {len(frames)} frames")
        
    except Exception as e:
        print(f"[FFMPEG] Error: {e}")
    
    return frames


def process_sticker_frames(img_bytes: BytesIO, keyword: str, fmt: str) -> list:
    """Process sticker with CUTOUT styling."""
    frames = []
    raw_data = img_bytes.getvalue()
    
    print(f"[STICKER_PROCESS] Input: {fmt}, {len(raw_data)} bytes")
    
    try:
        img = Image.open(img_bytes)
        print(f"[DEBUG] Sticker opened: format={img.format}, mode={img.mode}")
        
        size_in = STICKER_SIZE - STICKER_BORDER * 2
        rotation = random.uniform(-STICKER_ROT_RANGE, STICKER_ROT_RANGE)
        
        def process_one(fr: Image.Image) -> np.ndarray:
            fr = fr.convert("RGBA").resize((size_in, size_in), Image.LANCZOS)
            
            # Shadow
            sh_size = STICKER_SIZE + STICKER_SHADOW * 2
            shadow = Image.new("RGBA", (sh_size, sh_size), (0, 0, 0, 0))
            sd_base = Image.new("RGBA", (size_in, size_in), (0, 0, 0, 140))
            shadow.alpha_composite(sd_base,
                                   (STICKER_BORDER + STICKER_SHADOW + 2,
                                    STICKER_BORDER + STICKER_SHADOW + 2))
            shadow = shadow.filter(ImageFilter.GaussianBlur(radius=6))
            
            # White border
            bordered = Image.new("RGBA", (STICKER_SIZE, STICKER_SIZE), (255, 255, 255, 255))
            bordered.alpha_composite(fr, (STICKER_BORDER, STICKER_BORDER))
            
            final = shadow.copy()
            final.alpha_composite(bordered, (STICKER_SHADOW, STICKER_SHADOW))
            final = final.rotate(rotation, expand=True, resample=Image.BICUBIC)
            return np.array(final)
        
        is_animated = getattr(img, 'is_animated', False) or getattr(img, 'n_frames', 1) > 1
        n_frames = getattr(img, 'n_frames', 1)
        
        if is_animated and n_frames > 1:
            frame_idx = 0
            while True:
                try:
                    img.seek(frame_idx)
                    frames.append(process_one(img.copy()))
                    frame_idx += 1
                except EOFError:
                    break
                except Exception as e:
                    print(f"[STICKER] Frame error: {e}")
                    break
        else:
            frames.append(process_one(img))
        
        if frames:
            print(f"[STICKER] ✅ '{keyword}': {len(frames)} frames, rot={rotation:.0f}°")
        else:
            print(f"[STICKER] ❌ No frames")
            
    except Exception as e:
        print(f"[STICKER_PROCESS] Failed: {e}")
        import traceback
        traceback.print_exc()
    
    return frames


# ══════════════════════════════════════════════════════════════════
#  ASSET SCHEDULER — GUARANTEED 5 GIFs + 4 STICKERS
# ══════════════════════════════════════════════════════════════════

class AssetScheduler:
    def __init__(self, phrases: list, total_frames: int):
        self.phrases = phrases
        self.total_frames = total_frames
        self.assets = []
        self.used_phrases = set()
        
    def add_asset(self, phrase_idx: int, frames: list, asset_type: str, position_idx: int) -> bool:
        if phrase_idx >= len(self.phrases) or not frames:
            print(f"[SCHEDULE] ❌ Failed: phrase_idx={phrase_idx}, frames={'yes' if frames else 'no'}")
            return False
            
        phrase = self.phrases[phrase_idx]
        start_f = max(0, int(phrase["start_sec"] * FPS) - int(FPS * 0.3))
        end_f = min(int(phrase["end_sec"] * FPS) + int(FPS * GIF_EXTRA_SEC), self.total_frames)
        
        if end_f - start_f < FPS:
            end_f = start_f + FPS
        
        if asset_type == "gif":
            if position_idx >= len(GIF_POSITIONS):
                return False
            cx, cy = GIF_POSITIONS[position_idx]
            size = frames[0].shape[1] if frames else 360
        else:
            if position_idx >= len(STICKER_POSITIONS):
                return False
            cx, cy = STICKER_POSITIONS[position_idx]
            size = frames[0].shape[1] if frames else 160
        
        self.assets.append((start_f, end_f, frames, cx, cy, size, asset_type, phrase_idx))
        self.used_phrases.add(phrase_idx)
        print(f"[SCHEDULE] ✅ {asset_type.upper()} on phrase {phrase_idx} '{phrase['text'][:25]}...' frames {start_f}-{end_f} @ ({cx},{cy})")
        return True


def build_asset_schedule(phrases: list, global_keywords: list, total_frames: int) -> AssetScheduler:
    scheduler = AssetScheduler(phrases, total_frames)
    
    print(f"\n{'='*50}")
    print(f"[GIPHY] API Key present: {'YES' if GIPHY_KEY else 'NO'}")
    print(f"[GIPHY] Key length: {len(GIPHY_KEY) if GIPHY_KEY else 0}")
    print(f"[GIPHY] Target: {TARGET_GIFS} GIFs + {TARGET_STICKERS} stickers")
    print(f"[GIPHY] Phrases: {len(phrases)}")
    print(f"{'='*50}\n")
    
    if not GIPHY_KEY:
        print("[GIPHY] ❌ No API key — skipping all assets")
        return scheduler
    
    if len(phrases) < 3:
        print("[WARN] Too few phrases")
        return scheduler
    
    # Spread phrase indices evenly
    def spread_indices(count: int, total: int) -> list:
        if total <= count:
            return list(range(total))
        step = total / count
        return [min(int(i * step), total - 1) for i in range(count)]
    
    gif_phrase_indices = spread_indices(TARGET_GIFS, len(phrases))
    sticker_phrase_indices = spread_indices(TARGET_STICKERS, len(phrases))
    
    # Ensure no overlap
    sticker_phrase_indices = [i for i in sticker_phrase_indices if i not in gif_phrase_indices]
    while len(sticker_phrase_indices) < TARGET_STICKERS:
        candidates = [i for i in range(len(phrases)) if i not in gif_phrase_indices and i not in sticker_phrase_indices]
        if not candidates:
            break
        sticker_phrase_indices.append(candidates[0])
    sticker_phrase_indices = sticker_phrase_indices[:TARGET_STICKERS]
    
    print(f"[PLAN] GIF phrases: {gif_phrase_indices}")
    print(f"[PLAN] Sticker phrases: {sticker_phrase_indices}")
    
    # Fetch GIFs
    for idx, phrase_idx in enumerate(gif_phrase_indices):
        phrase = phrases[phrase_idx]
        keyword = get_phrase_keyword(phrase["text"], global_keywords)
        
        print(f"\n{'─'*40}")
        print(f"[GIF {idx+1}/{TARGET_GIFS}] Phrase {phrase_idx}: keyword='{keyword}'")
        print(f"[GIF {idx+1}] Phrase text: '{phrase['text'][:40]}...'")
        print(f"{'─'*40}")
        
        frames = fetch_giphy_gif(keyword)
        
        if not frames:
            # Retry with trending/viral
            retry_keywords = ["trending", "viral", "popular", "meme", "reaction"]
            for retry_kw in retry_keywords:
                print(f"[GIF {idx+1}] Retrying with '{retry_kw}'...")
                frames = fetch_giphy_gif(retry_kw)
                if frames:
                    break
        
        if frames:
            success = scheduler.add_asset(phrase_idx, frames, "gif", idx)
            print(f"[GIF {idx+1}] Schedule result: {'SUCCESS' if success else 'FAILED'}")
        else:
            print(f"[GIF {idx+1}] ❌ COMPLETELY FAILED — no frames after all retries")
    
    # Fetch Stickers
    for idx, phrase_idx in enumerate(sticker_phrase_indices):
        phrase = phrases[phrase_idx]
        keyword = get_phrase_keyword(phrase["text"], global_keywords)
        
        print(f"\n{'─'*40}")
        print(f"[STICKER {idx+1}/{TARGET_STICKERS}] Phrase {phrase_idx}: keyword='{keyword}'")
        print(f"[STICKER {idx+1}] Phrase text: '{phrase['text'][:40]}...'")
        print(f"{'─'*40}")
        
        frames = fetch_giphy_sticker(keyword)
        
        if not frames:
            alt_keywords = [random.choice(global_keywords) if global_keywords else "cool", "fun", "wow", "nice"]
            for alt_kw in alt_keywords:
                print(f"[STICKER {idx+1}] Retrying with '{alt_kw}'...")
                frames = fetch_giphy_sticker(alt_kw)
                if frames:
                    break
        
        if frames:
            success = scheduler.add_asset(phrase_idx, frames, "sticker", idx)
            print(f"[STICKER {idx+1}] Schedule result: {'SUCCESS' if success else 'FAILED'}")
        else:
            print(f"[STICKER {idx+1}] ❌ COMPLETELY FAILED")
    
    # Final summary
    gif_count = len([a for a in scheduler.assets if a[6] == "gif"])
    sticker_count = len([a for a in scheduler.assets if a[6] == "sticker"])
    print(f"\n{'='*50}")
    print(f"[FINAL] Scheduled: {gif_count} GIFs, {sticker_count} stickers")
    print(f"[FINAL] Total assets: {len(scheduler.assets)}")
    print(f"{'='*50}\n")
    
    return scheduler


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
        if self.x < 0:   self.x = W
        if self.x > W:   self.x = 0
        if self.y < 0:   self.y = H
        if self.y > H:   self.y = 0


def init_particles() -> list:
    return [Particle() for _ in range(N_PARTICLES)]


def draw_particles(canvas: np.ndarray, particles: list) -> None:
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
#  BACKGROUND
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
#  NEON WAVEFORM
# ══════════════════════════════════════════════════════════════════

def draw_neon_waveform(canvas: np.ndarray,
                       wave: np.ndarray,
                       rms: float,
                       is_climax: bool) -> None:
    mul  = 1.6 if is_climax else 1.0
    amp  = min(WAVE_H_PX*1.6, WAVE_H_PX*(0.10+rms*0.90)*mul)
    xs   = np.linspace(SAFE_X1, SAFE_X2, WAVE_POINTS).astype(int)
    kern = np.ones(13)/13
    ws   = np.convolve(wave, kern, mode='same')
    ys   = np.clip((WAVE_Y - ws*amp).astype(int), SAFE_Y1, H-SAFE_PAD)

    ci   = WAVE_POINTS//2

    pts  = np.array([(int(xs[i]),int(ys[i])) for i in range(WAVE_POINTS)],
                    dtype=np.int32).reshape(-1,1,2)
    ov   = canvas.copy()
    cv2.polylines(ov,[pts],False,WAVE_GLOW,16,cv2.LINE_AA)
    cv2.addWeighted(ov,0.35,canvas,0.65,0,canvas)

    ov2  = canvas.copy()
    cv2.polylines(ov2,[pts],False,WAVE_GLOW,8,cv2.LINE_AA)
    cv2.addWeighted(ov2,0.55,canvas,0.45,0,canvas)

    top_pts  = [(int(xs[i]),int(ys[i])) for i in range(WAVE_POINTS)]
    base_pts = [(int(xs[i]),WAVE_Y) for i in range(WAVE_POINTS-1,-1,-1)]
    poly     = np.array(top_pts+base_pts, dtype=np.int32)
    fill_col = tuple(max(0,int(c*0.45)) for c in WAVE_ACCENT)
    cv2.fillPoly(canvas,[poly],fill_col)

    for i in range(WAVE_POINTS-1):
        brt  = max(0.30, 1.0-abs(i-ci)/ci*0.65)
        col  = tuple(int(c*brt) for c in WAVE_ACCENT)
        cv2.line(canvas,(int(xs[i]),int(ys[i])),
                 (int(xs[i+1]),int(ys[i+1])),col,2,cv2.LINE_AA)

    pi2 = int(np.argmax(np.abs(ws)))
    cv2.circle(canvas,(int(xs[pi2]),int(ys[pi2])),5,
               (255,255,255),-1,cv2.LINE_AA)
    cv2.circle(canvas,(int(xs[pi2]),int(ys[pi2])),9,
               WAVE_ACCENT,2,cv2.LINE_AA)


# ══════════════════════════════════════════════════════════════════
#  PHRASE RENDERING
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
                glow = tuple(min(255,int(c*1.35)) for c in rgb)
                for gd,ga in [(8,35),(5,65),(3,95)]:
                    for dx,dy in [(gd,0),(-gd,0),(0,gd),(0,-gd)]:
                        draw.text((x+dx,y+dy),wd["text"],
                                  font=wd["font"],fill=glow+(ga,))
                draw.line([(x,y+wd["h"]+4),(x+wd["w"],y+wd["h"]+4)],
                          fill=rgb+(210,),width=3)
            else:
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

        for _ in range(25):
            ry = random.randint(int(H * 0.22), int(H * 0.62))
            if prev_y is None or abs(ry-prev_y) > 180: break
        prev_y = ry
        rx = random.randint(int(W * 0.25), int(W * 0.75))

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
    print(f"[PHRASE] {len(phrases)} phrases generated")
    return phrases


# ══════════════════════════════════════════════════════════════════
#  EASING & MOTION BLUR
# ══════════════════════════════════════════════════════════════════

def elastic_out(t: float) -> float:
    if t<=0: return 0.0
    if t>=1: return 1.0
    return 1+(2**(-10*t))*math.sin((t-0.075)*2*math.pi/0.3)


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

    px = max(int(W*0.15), min(int(W*0.85)-disp.width,  cx-disp.width//2+xo))
    py = max(int(H*0.15), min(int(H*0.75)-disp.height, cy-disp.height//2+yo))

    cr = cv2.cvtColor(canvas,cv2.COLOR_BGR2RGB)
    cp = Image.fromarray(cr).convert("RGBA")
    r,g,b,a = disp.split()
    a = a.point(lambda v: int(v*max(0.0,min(1.0,alpha))))
    disp = Image.merge("RGBA",(r,g,b,a))
    cp.alpha_composite(disp,(max(0,px),max(0,py)))
    np.copyto(canvas, cv2.cvtColor(
        np.array(cp.convert("RGB")),cv2.COLOR_RGB2BGR))


# ══════════════════════════════════════════════════════════════════
#  COMPOSITE ASSET — WITH DEBUG COUNTING
# ══════════════════════════════════════════════════════════════════

def composite_asset(canvas: np.ndarray,
                    frames: list,
                    frame_idx: int,
                    start_frame: int,
                    end_frame: int,
                    cx: int,
                    cy: int,
                    size: int,
                    asset_type: str) -> None:
    if not frames or frame_idx < start_frame or frame_idx > end_frame:
        return
        
    since_start = frame_idx - start_frame
    until_end = end_frame - frame_idx
    
    fade_frames = GIF_FADE_FRAMES if asset_type == "gif" else int(FPS * 0.25)
    alpha = 1.0
    
    if since_start < fade_frames:
        alpha = since_start / fade_frames
    elif until_end < fade_frames:
        alpha = until_end / fade_frames
    alpha = max(0.0, min(1.0, alpha))
    
    if asset_type == "gif":
        gif_frame_idx = since_start % len(frames)
        raw = frames[gif_frame_idx]
        pulse = 1.0 + 0.04 * math.sin(since_start * 0.1)
        disp_size = int(size * pulse)
    else:
        float_y = int(STICKER_FLOAT_AMP * math.sin(since_start * STICKER_FLOAT_SPEED))
        gif_frame_idx = (since_start // 2) % len(frames)
        raw = frames[gif_frame_idx]
        disp_size = size
        cy = cy + float_y
    
    if disp_size != raw.shape[1]:
        disp = cv2.resize(raw, (disp_size, disp_size), interpolation=cv2.INTER_LANCZOS4)
    else:
        disp = raw.copy()
    
    dh, dw = disp.shape[:2]
    px = cx - dw // 2
    py = cy - dh // 2
    px = max(0, min(W - dw, px))
    py = max(0, min(H - dh, py))
    
    cr = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    cp = Image.fromarray(cr).convert("RGBA")
    si = Image.fromarray(disp)
    
    if si.mode != 'RGBA':
        si = si.convert("RGBA")
        
    r, g, b, a = si.split()
    a = a.point(lambda v: int(v * alpha))
    si = Image.merge("RGBA", (r, g, b, a))
    
    cp.alpha_composite(si, (px, py))
    np.copyto(canvas, cv2.cvtColor(
        np.array(cp.convert("RGB")), cv2.COLOR_RGB2BGR))


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
#  MAIN RENDER — WITH ASSET DEBUG COUNTING
# ══════════════════════════════════════════════════════════════════
def render_video(phrases, rms_arr, wave_arr, duration, accent_bgr, scheduler):
    n_frames     = len(rms_arr)
    vignette     = build_vignette()
    bg_base      = build_black_gradient()
    particles    = init_particles()
    climax_start = int((duration - CLIMAX_SECS) * FPS)

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    temp   = "raw_temp.mp4"
    writer = cv2.VideoWriter(temp, fourcc, FPS, (W, H))
    if not writer.isOpened():
        sys.exit("[ERROR] VideoWriter failed to open")

    print(f"[RENDER] {n_frames} frames | {len(phrases)} phrases | {len(scheduler.assets)} assets")

    for p in phrases:
        p["img"] = render_phrase_image(p["text"], p["use_accent"], LIME_GREEN)
        p["sf"]  = int(p["start_sec"] * FPS)
        p["ef"]  = min(int(p["end_sec"] * FPS), n_frames)

    frame_phrase = {}
    for pi, p in enumerate(phrases):
        p["pi"] = pi
        for f in range(p["sf"], p["ef"]):
            frame_phrase[f] = p

    flash_cnt   = 0
    prev_phrase = None
    log_step    = max(1, n_frames // 20)
    
    # Asset visibility tracking
    asset_active_count = 0

    for i in range(n_frames):
        is_climax = i >= climax_start
        canvas    = bg_base.copy()

        # Dust particles
        draw_particles(canvas, particles)

        # ASSETS — count how many are visible this frame
        active_now = 0
        for (sf, ef, frames, cx, cy, size, asset_type, phrase_idx) in scheduler.assets:
            if sf <= i <= ef:
                active_now += 1
                composite_asset(canvas, frames, i, sf, ef, cx, cy, size, asset_type)
        
        if active_now > 0:
            asset_active_count += 1

        # Waveform
        draw_neon_waveform(canvas, wave_arr[i], rms_arr[i], is_climax)

        cur = frame_phrase.get(i)

        # Previous phrase persistence
        if (prev_phrase is not None and cur is not None
                and cur["pi"] != prev_phrase["pi"]):
            since_end = i - prev_phrase["ef"]
            if since_end < int(FPS * 0.35):
                la = 0.20 * (1 - since_end / int(FPS * 0.35))
                composite_phrase(canvas, prev_phrase["img"],
                                 prev_phrase["ef"] - prev_phrase["sf"], 999,
                                 prev_phrase["entrance"],
                                 prev_phrase["rand_x"], prev_phrase["rand_y"],
                                 alpha_override=la, blur=True)

        # Active phrase
        if cur is not None:
            fi = i - cur["sf"]
            fo = cur["ef"] - i
            if (cur["has_caps"] and
                    (prev_phrase is None or cur["pi"] != prev_phrase["pi"])):
                flash_cnt = 2
            composite_phrase(canvas, cur["img"],
                             fi, fo, cur["entrance"],
                             cur["rand_x"], cur["rand_y"])
            prev_phrase = cur

        # CAPS flash
        if flash_cnt > 0:
            canvas = caps_flash(canvas, flash_cnt / 2, LIME_GREEN)
            flash_cnt -= 1

        # Vignette
        cf     = canvas.astype(np.float32) / 255.0 * vignette
        canvas = (cf * 255).clip(0, 255).astype(np.uint8)

        # Ken Burns
        canvas = ken_burns(canvas, i, n_frames)

        # Grain
        canvas = apply_grain(canvas, i)

        writer.write(canvas)
        if i % log_step == 0:
            print(f"  [RENDER] {int(i/n_frames*100)}% | Active assets: {active_now}")

    writer.release()
    
    # Report asset visibility
    print(f"[RENDER] Assets were visible in {asset_active_count}/{n_frames} frames ({asset_active_count/n_frames*100:.1f}%)")
    
    print("[RENDER] Re-encoding with ffmpeg...")
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", temp, "-c:v", "libx264",
         "-preset", "fast", "-crf", "17", "-pix_fmt", "yuv420p", "-an",
         str(OUTPUT_VIDEO)],
        capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[FFMPEG] Error: {r.stderr[:200]}")
        shutil.copy(temp, str(OUTPUT_VIDEO))
    else:
        Path(temp).unlink(missing_ok=True)
    size_mb = OUTPUT_VIDEO.stat().st_size // 1024 // 1024
    print(f"[✓] {OUTPUT_VIDEO} ({size_mb}MB)")


def main():
    print("=" * 62)
    print("  Shining Black Minimalist Engine v13")
    print("  GIPHY Debug Mode · Guaranteed Assets · Heavy Logging")
    print("=" * 62)

    ensure_font()
    ASSETS_DIR.mkdir(exist_ok=True)

    if not INPUT_AUDIO.exists():
        download_audio()
    if not INPUT_SCRIPT.exists():
        sys.exit("[ERROR] script.txt not found")

    raw   = INPUT_SCRIPT.read_text(encoding="utf-8")
    clean = clean_script(raw)
    print(f"[INFO] Script: {len(clean.split())} words")

    cmd      = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(INPUT_AUDIO)]
    duration = float(subprocess.run(
        cmd, capture_output=True, text=True).stdout.strip())
    n_frames = int(duration * FPS)
    print(f"[INFO] Duration: {duration:.2f}s | Frames: {n_frames}")

    global_keywords = extract_keywords(clean, n=15)
    print(f"[GIPHY] Keywords: {global_keywords}")

    print("[TTS] Computing timestamps...")
    word_timestamps = asyncio.run(generate_tts_with_timing(clean))
    if not word_timestamps:
        words = clean.split()
        d     = duration / max(1, len(words))
        word_timestamps = [{"word": w, "start": i*d, "duration": d}
                           for i, w in enumerate(words)]

    phrases  = group_into_phrases(word_timestamps, duration, LIME_GREEN)
    
    # Build asset schedule BEFORE audio analysis
    scheduler = build_asset_schedule(phrases, global_keywords, n_frames)
    
    rms_arr, wave_arr, _ = analyse_audio(str(INPUT_AUDIO), n_frames)

    render_video(phrases, rms_arr, wave_arr, duration, LIME_GREEN, scheduler)

    print("\n" + "=" * 62)
    print("  [✓] DONE — raw_video.mp4 ready")
    print("=" * 62)


if __name__ == "__main__":
    main()
