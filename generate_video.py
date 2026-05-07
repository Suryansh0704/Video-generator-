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
from pathlib import Path

import requests
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


W, H = 1080, 1920
FPS = 30

VOICE = "en-GB-RyanNeural"
PITCH = "-2Hz"
RATE = "+15%"

INPUT_SCRIPT = Path("script.txt")
INPUT_AUDIO = Path("output_voice.wav")
AUDIO_MP3 = Path("output_raw.mp3")
OUTPUT_VIDEO = Path("raw_video.mp4")

ASSETS_DIR = Path("assets")
FONT_PATH = Path("Montserrat-Bold.ttf")
FONT_URL = "https://github.com/google/fonts/raw/main/ofl/montserrat/static/Montserrat-Bold.ttf"

WORDS_PER_PHRASE = 4
MIN_PHRASE_HOLD_SEC = 1.2
ANIM_IN_FRAMES = int(FPS * 0.22)
ANIM_OUT_FRAMES = int(FPS * 0.15)

LINGER_ALPHA = 0.20
LINGER_BLUR_R = 5
ACCENT_CHANCE = 0.35

SAFE_PAD = 40
POS_Y_MIN = int(H * 0.15)
POS_Y_MAX = int(H * 0.58)

STICKER_SIZE = 220
STICKER_BORDER = 10
STICKER_FLOAT_AMP = 12
STICKER_FLOAT_SPD = 0.08
STICKER_SCALE_FRAMES = int(FPS * 0.25)
MAX_STICKERS = 2
GIF_CACHE = {}

CORNER_ZONES = [
    ((40, 200), (60, 250)),
    ((W - 260, W - 60), (60, 250)),
    ((40, 200), (H - 300, H - 80)),
    ((W - 260, W - 60), (H - 300, H - 80)),
]

GRAIN_INTENSITY = 10
GRAIN_BLEND = 0.05
VIGNETTE_STR = 0.70
MOTION_BLUR_PX = 10

WAVE_Y_BASE = int(H * 0.82)
WAVE_HEIGHT = int(H * 0.13)
WAVE_POINTS = 200

CLIMAX_SECS = 5.0
SHAKE_AMP = 10
CHROMA_SHIFT = 8
CLIMAX_WAVE_MULT = 2.0
CLIMAX_BG_CYCLE = 8

KB_START = 1.0
KB_END = 1.12

FRUIT_PALETTES = [
    ((185, 175, 255), (140, 120, 200)),
    ((180, 180, 255), (130, 125, 205)),
    ((130, 210, 150), (80, 155, 90)),
    ((140, 200, 255), (90, 140, 210)),
    ((193, 182, 255), (150, 130, 210)),
    ((170, 140, 255), (120, 90, 200)),
    ((160, 130, 255), (110, 80, 195)),
    ((200, 170, 255), (150, 115, 205)),
    ((180, 160, 250), (130, 105, 190)),
    ((210, 190, 255), (165, 135, 215)),
    ((175, 120, 240), (125, 70, 180)),
    ((200, 182, 255), (155, 130, 215)),
    ((190, 150, 240), (140, 100, 185)),
    ((170, 160, 255), (120, 105, 195)),
]

CLIMAX_PAIRS = [
    (5, 6),
    (0, 4),
    (7, 8),
    (9, 10),
    (11, 12),
]

WORD_COLORS_BGR = [
    (25, 20, 100),
    (15, 40, 130),
    (10, 60, 120),
    (30, 20, 140),
    (50, 30, 110),
    (20, 80, 100),
    (40, 25, 120),
    (10, 50, 90),
]

ACCENT_COLORS_BGR = [
    (20, 10, 200),
    (10, 80, 220),
    (0, 150, 200),
    (80, 20, 180),
    (0, 100, 180),
    (40, 0, 160),
]

WAVE_COLORS_BGR = [
    (60, 30, 140),
    (20, 20, 180),
    (30, 80, 160),
    (10, 60, 120),
    (80, 20, 160),
]

KEYWORD_MAP = {
    "shocked": "shocked",
    "shock": "shocked",
    "fire": "fire",
    "hot": "fire",
    "cat": "cat",
    "aura": "aura",
    "money": "money",
    "rich": "money",
    "brain": "brain",
    "think": "brain",
    "win": "win",
    "victory": "win",
    "love": "love",
    "heart": "love",
    "star": "star",
    "amazing": "star",
    "ghost": "ghost",
    "scary": "ghost",
    "rocket": "rocket",
    "fast": "rocket",
    "crown": "crown",
    "king": "crown",
}


def ensure_font():
    if FONT_PATH.exists():
        return
    try:
        r = requests.get(FONT_URL, timeout=30)
        if r.status_code == 200:
            FONT_PATH.write_bytes(r.content)
            print("[FONT] Downloaded")
            return
    except Exception as e:
        print(f"[FONT] {e}")
    ttfs = glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)
    bold = [f for f in ttfs if "bold" in f.lower()]
    chosen = bold[0] if bold else (ttfs[0] if ttfs else None)
    if chosen:
        shutil.copy(chosen, str(FONT_PATH))
        print(f"[FONT] Using fallback: {chosen}")


def get_font(size: int):
    try:
        if FONT_PATH.exists():
            return ImageFont.truetype(str(FONT_PATH), size)
    except Exception:
        pass
    return ImageFont.load_default()


def download_audio():
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        if INPUT_AUDIO.exists():
            return
        sys.exit("[ERROR] GH_TOKEN not set and output_voice.wav missing")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    }

    res = requests.get(
        "https://api.github.com/repos/Suryansh0704/Audio-generator-/actions/artifacts",
        headers=headers,
        timeout=60
    )
    artifacts = res.json().get("artifacts", [])
    if not artifacts:
        sys.exit("[ERROR] No artifacts found")

    latest = artifacts[0]
    r = requests.get(latest["archive_download_url"], headers=headers, timeout=120)
    with open("audio.zip", "wb") as f:
        f.write(r.content)

    with zipfile.ZipFile("audio.zip") as z:
        z.extractall("audio_extracted")

    wavs = glob.glob("audio_extracted/**/*.wav", recursive=True) or glob.glob("audio_extracted/*.wav")
    if wavs:
        shutil.copy(wavs[0], str(INPUT_AUDIO))
        print(f"[AUDIO] {INPUT_AUDIO.stat().st_size // 1024}KB")
    else:
        sys.exit("[ERROR] No WAV found in artifact")


def clean_script(raw: str) -> str:
    text = re.sub(r'[.*?]', '', raw, flags=re.DOTALL)
    text = re.sub(r'-{2,}.*?-{2,}', '', text)
    text = re.sub(r'#w+', '', text)
    text = re.sub(r'https?://S+', '', text)
    text = text.encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[/\\@#$%^&*()[]{}|<>~`_+=]', ' ', text)
    text = re.sub(r's+', ' ', text)
    return text.strip()


def preload_gif(gif_path: str) -> list:
    if gif_path in GIF_CACHE:
        return GIF_CACHE[gif_path]

    try:
        gif = Image.open(gif_path)
    except Exception as e:
        print(f"[GIF] Could not open {gif_path}: {e}")
        return []

    frames = []
    target = STICKER_SIZE - STICKER_BORDER * 2

    try:
        while True:
            frame = gif.convert("RGBA").resize((target, target), Image.LANCZOS)
            bordered = Image.new("RGBA", (STICKER_SIZE, STICKER_SIZE), (255, 255, 255, 255))
            bordered.paste(frame, (STICKER_BORDER, STICKER_BORDER), frame)
            frames.append(np.array(bordered))
            gif.seek(gif.tell() + 1)
    except EOFError:
        pass

    if not frames:
        return []

    GIF_CACHE[gif_path] = frames
    print(f"[GIF] Cached {Path(gif_path).name}: {len(frames)} frames")
    return frames


def scan_keywords(text: str) -> list:
    lower = text.lower()
    matches = []
    seen = set()

    for keyword, gif_key in KEYWORD_MAP.items():
        if keyword in lower and gif_key not in seen:
            gif_path = ASSETS_DIR / f"{gif_key}.gif"
            if gif_path.exists():
                matches.append(gif_key)
                seen.add(gif_key)

    return matches[:MAX_STICKERS]


def find_sticker_data(script_text: str) -> list:
    ASSETS_DIR.mkdir(exist_ok=True)
    keys = scan_keywords(script_text)
    stickers = []
    used_corners = set()

    for gif_key in keys:
        gif_path = str(ASSETS_DIR / f"{gif_key}.gif")
        frames = preload_gif(gif_path)
        if not frames:
            continue

        available = [i for i in range(4) if i not in used_corners]
        if not available:
            available = list(range(4))

        corner_idx = random.choice(available)
        used_corners.add(corner_idx)

        xr, yr = CORNER_ZONES[corner_idx]
        sx = random.randint(xr[0], xr[1])
        sy = random.randint(yr[0], yr[1])

        stickers.append({
            "key": gif_key,
            "frames": frames,
            "sx": sx,
            "sy": sy,
            "corner": corner_idx,
            "phase_offset": random.uniform(0, math.pi * 2),
        })

    print(f"[GIF] {len(stickers)} sticker(s) ready")
    return stickers


def elastic_overshoot(t: float) -> float:
    if t <= 0:
        return 0.0
    if t >= 1:
        return 1.0
    return 0.5 + (1 + (2 ** (-10 * t)) * math.sin((t - 0.075) * 2 * math.pi / 0.3)) * 0.5


def render_sticker(canvas_bgr: np.ndarray, sticker: dict, frame_idx: int, start_frame: int) -> None:
    frames = sticker["frames"]
    n_gif = len(frames)
    sx = sticker["sx"]
    sy_base = sticker["sy"]
    phase = sticker["phase_offset"]
    f_since_start = frame_idx - start_frame

    if f_since_start < STICKER_SCALE_FRAMES:
        t = max(0.0, f_since_start / STICKER_SCALE_FRAMES)
        scale = elastic_overshoot(t)
    else:
        scale = 1.0

    float_y = int(STICKER_FLOAT_AMP * math.sin(frame_idx * STICKER_FLOAT_SPD + phase))
    sy = sy_base + float_y

    gif_frame_idx = (frame_idx // 2) % n_gif
    gif_arr = frames[gif_frame_idx]

    sz = max(1, int(STICKER_SIZE * scale))
    if sz != STICKER_SIZE:
        gif_pil = Image.fromarray(gif_arr).resize((sz, sz), Image.LANCZOS)
    else:
        gif_pil = Image.fromarray(gif_arr)

    px = max(0, min(W - sz, sx - sz // 2))
    py = max(0, min(H - sz, sy - sz // 2))

    canvas_rgb = cv2.cvtColor(canvas_bgr, cv2.COLOR_BGR2RGB)
    canvas_pil = Image.fromarray(canvas_rgb).convert("RGBA")
    canvas_pil.alpha_composite(gif_pil.convert("RGBA"), (px, py))
    result = cv2.cvtColor(np.array(canvas_pil.convert("RGB")), cv2.COLOR_RGB2BGR)
    np.copyto(canvas_bgr, result)


def build_radial_gradient(center_bgr: tuple, edge_bgr: tuple) -> np.ndarray:
    xs = np.linspace(-1, 1, W)
    ys = np.linspace(-1, 1, H)
    X, Y = np.meshgrid(xs, ys)
    dist = np.clip(np.sqrt(X ** 2 + Y ** 2) / math.sqrt(2), 0, 1)
    dist = dist.reshape(H, W, 1)

    c = np.array(center_bgr, dtype=np.float32)
    e = np.array(edge_bgr, dtype=np.float32)

    grad = (c * (1 - dist) + e * dist).clip(0, 255).astype(np.uint8)
    return grad


async def generate_tts_with_timing(text: str) -> list:
    communicate = edge_tts.Communicate(
        text=text,
        voice=VOICE,
        pitch=PITCH,
        rate=RATE
    )

    words = []
    audio_data = bytearray()

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            w = chunk["text"].strip()
            if w:
                words.append({
                    "word": w,
                    "start": chunk["offset"] / 10_000_000,
                    "duration": chunk["duration"] / 10_000_000,
                })

    AUDIO_MP3.write_bytes(bytes(audio_data))
    print(f"[TTS] {len(words)} timestamps")
    return words


def analyse_audio(path: str, n_frames: int) -> tuple:
    print("[AUDIO] Analysing...")
    y, sr = librosa.load(str(path), sr=None, mono=True)
    duration = len(y) / sr
    spf = len(y) / n_frames

    rms_arr = np.zeros(n_frames, dtype=np.float32)
    wave_arr = np.zeros((n_frames, WAVE_POINTS), dtype=np.float32)

    for i in range(n_frames):
        s = int(i * spf)
        e = min(int(s + spf), len(y))
        chunk = y[s:e]
        if not len(chunk):
            continue

        rms_arr[i] = float(np.sqrt(np.mean(chunk ** 2)))

        if len(chunk) >= WAVE_POINTS:
            idx = np.linspace(0, len(chunk) - 1, WAVE_POINTS).astype(int)
            wave_arr[i] = chunk[idx]
        else:
            wave_arr[i, :len(chunk)] = chunk[:WAVE_POINTS]

    mx = rms_arr.max()
    if mx > 0:
        rms_arr /= mx

    return rms_arr, wave_arr, duration


def group_into_phrases(word_timestamps: list, duration: float, accent_bgr: tuple) -> list:
    phrases = []
    climax_start = duration - CLIMAX_SECS
    entrances = ["fly_left", "fly_right", "fly_top", "fly_bottom"]

    n_total = max(1, math.ceil(len(word_timestamps) / WORDS_PER_PHRASE))
    accent_count = max(1, int(n_total * ACCENT_CHANCE))
    accent_set = set(random.sample(range(n_total), min(accent_count, n_total)))

    i = 0
    pi = 0

    while i < len(word_timestamps):
        group = word_timestamps[i:i + WORDS_PER_PHRASE]
        text = " ".join(w["word"] for w in group)
        clean = re.sub(r"[^a-zA-Z0-9'-!?.,”"s]", "", text).strip()

        if not clean:
            i += WORDS_PER_PHRASE
            pi += 1
            continue

        start_sec = group[0]["start"]
        end_sec = group[-1]["start"] + group[-1]["duration"]

        if end_sec - start_sec < MIN_PHRASE_HOLD_SEC:
            end_sec = start_sec + MIN_PHRASE_HOLD_SEC

        has_caps = bool(re.search(r"[A-Z]{2,}", text))
        has_quotes = '"' in text or "'" in text
        is_climax = start_sec >= climax_start
        use_accent = has_caps or has_quotes or (pi in accent_set)

        entrance = random.choice(entrances)
        rand_y = random.randint(POS_Y_MIN, POS_Y_MAX)
        phrase_color = accent_bgr if use_accent else random.choice(WORD_COLORS_BGR)

        phrases.append({
            "text": clean,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "has_caps": has_caps,
            "has_quotes": has_quotes,
            "is_climax": is_climax,
            "entrance": entrance,
            "rand_y": rand_y,
            "phrase_color": phrase_color,
            "use_accent": use_accent,
        })

        i += WORDS_PER_PHRASE
        pi += 1

    if phrases:
        phrases[-1]["is_climax"] = True

    print(f"[PHRASE] {len(phrases)} phrases")
    return phrases


def render_phrase_image(text: str, phrase_color: tuple, accent_bgr: tuple, use_accent: bool, is_climax: bool) -> Image.Image:
    words = text.split()
    N_SZ = 98
    C_SZ = 124
    LSP = 24
    PAD = 36

    word_data = []

    for w in words:
        is_cap = bool(re.search(r"[A-Z]{2,}", w))
        is_qot = w.startswith('"') or w.startswith("'")
        is_acc = is_cap or is_qot or use_accent
        size = int((C_SZ if is_cap else N_SZ) * (1.06 if is_climax else 1.0))
        color = accent_bgr if is_acc else phrase_color
        font = get_font(size)

        tmp = Image.new("RGBA", (1, 1))
        draw = ImageDraw.Draw(tmp)
        bbox = draw.textbbox((0, 0), w, font=font)

        word_data.append({
            "text": w,
            "font": font,
            "color": color,
            "w": max(1, bbox[2] - bbox[0]),
            "h": max(1, bbox[3] - bbox[1]),
            "is_acc": is_acc,
        })

    max_w = W - 120
    lines = []
    cur = []
    cw = 0

    for wd in word_data:
        add_w = wd["w"] + (18 if cur else 0)
        if cw + add_w > max_w and cur:
            lines.append(cur)
            cur = [wd]
            cw = wd["w"]
        else:
            cur.append(wd)
            cw += add_w
    if cur:
        lines.append(cur)

    lh_list = [max(wd["h"] for wd in line) for line in lines]
    tot_h = sum(lh_list) + LSP * (len(lines) - 1) + PAD * 2
    tot_w = W - 80

    img = Image.new("RGBA", (max(1, tot_w), max(1, tot_h)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    y = PAD
    for li, line in enumerate(lines):
        lw = sum(wd["w"] for wd in line) + 18 * (len(line) - 1)
        x = (tot_w - lw) // 2

        for wd in line:
            rgb = (wd["color"][2], wd["color"][1], wd["color"][0])

            if wd["is_acc"]:
                glow = tuple(min(255, int(c * 1.2)) for c in rgb)
                for gd, ga in [(7, 45), (4, 85), (2, 125)]:
                    for dx, dy in [(gd, 0), (-gd, 0), (0, gd), (0, -gd)]:
                        draw.text((x + dx, y + dy), wd["text"], font=wd["font"], fill=glow + (ga,))
                draw.line(
                    [(x, y + wd["h"] + 4), (x + wd["w"], y + wd["h"] + 4)],
                    fill=rgb + (200,),
                    width=3
                )
            else:
                draw.text((x + 2, y + 2), wd["text"], font=wd["font"], fill=(20, 20, 20, 90))

            draw.text((x, y), wd["text"], font=wd["font"], fill=rgb + (255,))
            x += wd["w"] + 18

        y += max(wd["h"] for wd in line) + LSP

    return img


def apply_motion_blur(img: Image.Image, entrance: str, t: float) -> Image.Image:
    if t > 0.5:
        return img

    blur_px = int(MOTION_BLUR_PX * (1 - t * 2))
    if blur_px < 2:
        return img

    arr = np.array(img, dtype=np.float32)

    if entrance in ("fly_left", "fly_right"):
        k = np.ones((1, blur_px), dtype=np.float32) / blur_px
    else:
        k = np.ones((blur_px, 1), dtype=np.float32) / blur_px

    blurred = np.zeros_like(arr)
    for c in range(arr.shape[2]):
        blurred[:, :, c] = cv2.filter2D(arr[:, :, c], -1, k)

    return Image.fromarray(blurred.astype(np.uint8))


def composite_phrase(canvas_bgr: np.ndarray,
                     phrase_img: Image.Image,
                     frame_in: int,
                     frame_out: int,
                     entrance: str,
                     rand_y: int,
                     alpha_override: float = None,
                     blur: bool = False) -> None:
    iw, ih = phrase_img.size
    ty = rand_y - ih // 2

    if frame_in < ANIM_IN_FRAMES:
        t = frame_in / ANIM_IN_FRAMES
        e = elastic_overshoot(t)
        scale = e
        alpha = min(1.0, t * 3.0)

        if entrance == "fly_left":
            xo, yo = int((1 - t) * (-iw - 80)), 0
        elif entrance == "fly_right":
            xo, yo = int((1 - t) * (W + 80)), 0
        elif entrance == "fly_top":
            xo, yo = 0, int((1 - t) * (-ih - 80))
        elif entrance == "fly_bottom":
            xo, yo = 0, int((1 - t) * (H + 80))
        else:
            xo = yo = 0

        phrase_img = apply_motion_blur(phrase_img, entrance, t)

    elif frame_out < ANIM_OUT_FRAMES:
        scale = 1.0
        alpha = frame_out / ANIM_OUT_FRAMES
        xo = yo = 0
    else:
        scale = 1.0
        alpha = 1.0
        xo = yo = 0

    if alpha_override is not None:
        alpha = alpha_override

    disp = phrase_img
    if abs(scale - 1.0) > 0.01:
        nw = max(1, int(iw * scale))
        nh = max(1, int(ih * scale))
        disp = phrase_img.resize((nw, nh), Image.LANCZOS)

    if blur and alpha_override is not None:
        disp = disp.filter(ImageFilter.GaussianBlur(LINGER_BLUR_R))

    px = W // 2 - disp.width // 2 + xo
    py = ty + yo

    px = max(SAFE_PAD, min(W - disp.width - SAFE_PAD, px))
    py = max(SAFE_PAD, min(H - disp.height - SAFE_PAD, py))

    canvas_rgb = cv2.cvtColor(canvas_bgr, cv2.COLOR_BGR2RGB)
    canvas_pil = Image.fromarray(canvas_rgb).convert("RGBA")

    r, g, b, a = disp.split()
    a = a.point(lambda v: int(v * max(0.0, min(1.0, alpha))))
    disp = Image.merge("RGBA", (r, g, b, a))

    canvas_pil.alpha_composite(disp, (max(0, px), max(0, py)))
    result = cv2.cvtColor(np.array(canvas_pil.convert("RGB")), cv2.COLOR_RGB2BGR)
    np.copyto(canvas_bgr, result)


def draw_gradient_waveform(canvas: np.ndarray,
                           wave: np.ndarray,
                           rms: float,
                           wave_bgr: tuple,
                           is_climax: bool) -> None:
    amp_m = CLIMAX_WAVE_MULT if is_climax else 1.0
    amp = WAVE_HEIGHT * (0.15 + rms * 0.85) * amp_m
    amp = min(amp, WAVE_HEIGHT * 1.8)

    xs = np.linspace(80, W - 80, WAVE_POINTS).astype(int)
    kern = np.ones(9) / 9
    ws = np.convolve(wave, kern, mode="same")
    ys = np.clip((WAVE_Y_BASE - ws * amp).astype(int), 10, H - 10)

    ci = WAVE_POINTS // 2
    for i in range(WAVE_POINTS - 1):
        brt = max(0.25, 1.0 - abs(i - ci) / ci * 0.70)
        c = tuple(int(v * brt) for v in wave_bgr)
        gc = tuple(max(0, int(v * brt * 0.5)) for v in wave_bgr)
        p1 = (int(xs[i]), int(ys[i]))
        p2 = (int(xs[i + 1]), int(ys[i + 1]))
        cv2.line(canvas, p1, p2, gc, 10, cv2.LINE_AA)
        cv2.line(canvas, p1, p2, c, 3, cv2.LINE_AA)

    pi = int(np.argmax(np.abs(ws)))
    cv2.circle(canvas, (int(xs[pi]), int(ys[pi])), 5, wave_bgr, -1)
    cv2.circle(canvas, (int(xs[pi]), int(ys[pi])), 9, wave_bgr, 2)


def apply_film_grain(canvas: np.ndarray, fi: int) -> np.ndarray:
    rng = np.random.RandomState(fi * 31 + 7)
    n = rng.randint(-GRAIN_INTENSITY, GRAIN_INTENSITY + 1, canvas.shape, dtype=np.int16)
    return np.clip(canvas.astype(np.int16) + (n * GRAIN_BLEND).astype(np.int16), 0, 255).astype(np.uint8)


def build_vignette() -> np.ndarray:
    xs = np.linspace(-1, 1, W)
    ys = np.linspace(-1, 1, H)
    X, Y = np.meshgrid(xs, ys)
    dist = np.sqrt(X ** 2 + Y ** 2)
    mask = 1.0 - np.clip(dist / dist.max() * VIGNETTE_STR, 0, 1)
    return mask.reshape(H, W, 1).astype(np.float32)


def apply_chroma(canvas: np.ndarray, fi: int) -> np.ndarray:
    rng = np.random.RandomState(fi * 13 + 5)
    sx = int(rng.randint(-CHROMA_SHIFT, CHROMA_SHIFT + 1))
    sy = int(rng.randint(-CHROMA_SHIFT // 2, CHROMA_SHIFT // 2 + 1))
    bx = -sx + int(rng.randint(-3, 4))
    by = -sy + int(rng.randint(-2, 3))

    b, g, r = cv2.split(canvas)
    Mr = np.float32([[1, 0, sx], [0, 1, sy]])
    Mb = np.float32([[1, 0, bx], [0, 1, by]])

    r = cv2.warpAffine(r, Mr, (W, H), borderMode=cv2.BORDER_REPLICATE)
    b = cv2.warpAffine(b, Mb, (W, H), borderMode=cv2.BORDER_REPLICATE)

    return cv2.merge([b, g, r])


def apply_shake(canvas: np.ndarray, fi: int) -> np.ndarray:
    rng = np.random.RandomState(fi * 7 + 13)
    sx = int(rng.randint(-SHAKE_AMP, SHAKE_AMP + 1))
    sy = int(rng.randint(-SHAKE_AMP // 2, SHAKE_AMP // 2 + 1))
    M = np.float32([[1, 0, sx], [0, 1, sy]])
    return cv2.warpAffine(canvas, M, (W, H), borderMode=cv2.BORDER_REPLICATE)


def apply_ken_burns(frame: np.ndarray, idx: int, total: int) -> np.ndarray:
    t = idx / max(1, total - 1)
    scale = KB_START + t * (KB_END - KB_START)
    if abs(scale - 1.0) < 0.002:
        return frame

    nw = int(W * scale)
    nh = int(H * scale)
    big = cv2.resize(frame, (nw, nh))
    ox = (nw - W) // 2
    oy = (nh - H) // 2
    return big[oy:oy + H, ox:ox + W]


def apply_caps_flash(canvas: np.ndarray, intensity: float, accent_bgr: tuple) -> np.ndarray:
    ov = np.full_like(canvas, accent_bgr, dtype=np.uint8)
    return cv2.addWeighted(canvas, 1 - intensity * 0.15, ov, intensity * 0.15, 0)


def render_video(phrases: list,
                 rms_arr: np.ndarray,
                 wave_arr: np.ndarray,
                 duration: float,
                 palette_idx: int,
                 accent_bgr: tuple,
                 wave_bgr: tuple,
                 stickers: list) -> None:
    n_frames = len(rms_arr)
    vignette = build_vignette()
    climax_start = int((duration - CLIMAX_SECS) * FPS)

    climax_pair = random.choice(CLIMAX_PAIRS)
    bg_a = build_radial_gradient(*FRUIT_PALETTES[climax_pair[0]])
    bg_b = build_radial_gradient(*FRUIT_PALETTES[climax_pair[1]])
    main_bg = build_radial_gradient(*FRUIT_PALETTES[palette_idx])

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    temp = "raw_temp.mp4"
    writer = cv2.VideoWriter(temp, fourcc, FPS, (W, H))
    if not writer.isOpened():
        sys.exit("[ERROR] VideoWriter failed")

    print(f"[RENDER] {n_frames} frames | {len(phrases)} phrases | {len(stickers)} stickers")

    for p in phrases:
        p["img"] = render_phrase_image(
            p["text"],
            p["phrase_color"],
            accent_bgr,
            p["use_accent"],
            p["is_climax"]
        )
        p["sf"] = int(p["start_sec"] * FPS)
        p["ef"] = min(int(p["end_sec"] * FPS), n_frames)

    frame_phrase = {}
    for pi, p in enumerate(phrases):
        p["pi"] = pi
        for f in range(p["sf"], p["ef"]):
            frame_phrase[f] = p

    sticker_start = 0
    caps_flash = 0
    prev_phrase = None
    log_step = max(1, n_frames // 20)

    for i in range(n_frames):
        is_climax = i >= climax_start

        if is_climax:
            cycle = (i - climax_start) // CLIMAX_BG_CYCLE
            canvas = bg_a.copy() if cycle % 2 == 0 else bg_b.copy()
        else:
            canvas = main_bg.copy()

        draw_gradient_waveform(canvas, wave_arr[i], rms_arr[i], wave_bgr, is_climax)

        cur = frame_phrase.get(i)

        if prev_phrase is not None and cur is not None and cur["pi"] != prev_phrase["pi"]:
            since_end = i - prev_phrase["ef"]
            if since_end < int(FPS * 0.3):
                la = LINGER_ALPHA * (1 - since_end / (FPS * 0.3))
                composite_phrase(
                    canvas,
                    prev_phrase["img"],
                    prev_phrase["ef"] - prev_phrase["sf"],
                    999,
                    prev_phrase["entrance"],
                    prev_phrase["rand_y"],
                    alpha_override=la,
                    blur=True
                )

        if cur is not None:
            fi = i - cur["sf"]
            fo = cur["ef"] - i

            if cur["has_caps"] and (prev_phrase is None or cur["pi"] != prev_phrase["pi"]):
                caps_flash = 2

            composite_phrase(canvas, cur["img"], fi, fo, cur["entrance"], cur["rand_y"])
            prev_phrase = cur

        if caps_flash > 0:
            canvas = apply_caps_flash(canvas, caps_flash / 2, accent_bgr)
            caps_flash -= 1

        for sticker in stickers:
            render_sticker(canvas, sticker, i, sticker_start)

        cf = canvas.astype(np.float32) / 255.0 * vignette
        canvas = (cf * 255).clip(0, 255).astype(np.uint8)

        canvas = apply_ken_burns(canvas, i, n_frames)
        canvas = apply_film_grain(canvas, i)

        if is_climax:
            canvas = apply_chroma(canvas, i)
            canvas = apply_shake(canvas, i)

        writer.write(canvas)

        if i % log_step == 0:
            print(f"  [RENDER] {int(i / n_frames * 100)}%")

    writer.release()

    cmd = [
        "ffmpeg", "-y",
        "-i", temp,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "17",
        "-pix_fmt", "yuv420p",
        "-an",
        str(OUTPUT_VIDEO)
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)

    if r.returncode != 0:
        print("[WARN] ffmpeg re-encode failed, using temp file")
        shutil.copy(temp, str(OUTPUT_VIDEO))
    else:
        Path(temp).unlink(missing_ok=True)

    mb = OUTPUT_VIDEO.stat().st_size / (1024 * 1024)
    print(f"[DONE] {OUTPUT_VIDEO} ({mb:.1f}MB)")


def main():
    ensure_font()

    if not INPUT_AUDIO.exists():
        download_audio()

    if not INPUT_SCRIPT.exists():
        sys.exit("[ERROR] script.txt not found")

    raw = INPUT_SCRIPT.read_text(encoding="utf-8")
    clean = clean_script(raw)

    if not clean:
        sys.exit("[ERROR] script.txt is empty after cleaning")

    stickers = find_sticker_data(clean)

    palette_idx = random.randint(0, len(FRUIT_PALETTES) - 1)
    accent_bgr = random.choice(ACCENT_COLORS_BGR)
    wave_bgr = random.choice(WAVE_COLORS_BGR)

    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(INPUT_AUDIO)
    ]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    if not out:
        sys.exit("[ERROR] Could not read audio duration")

    duration = float(out)
    n_frames = int(duration * FPS)

    word_timestamps = asyncio.run(generate_tts_with_timing(clean))

    if not word_timestamps:
        words = clean.split()
        d = duration / max(1, len(words))
        word_timestamps = [{"word": w, "start": i * d, "duration": d} for i, w in enumerate(words)]

    phrases = group_into_phrases(word_timestamps, duration, accent_bgr)
    rms_arr, wave_arr, _ = analyse_audio(str(INPUT_AUDIO), n_frames)

    render_video(
        phrases,
        rms_arr,
        wave_arr,
        duration,
        palette_idx,
        accent_bgr,
        wave_bgr,
        stickers
    )


if __name__ == "__main__":
    main()
