"""
generate_video.py — Dark Minimalism Audio-Reactive Engine
==========================================================
Procedural generation — zero stock footage, zero external assets.
Every frame is drawn from scratch based on the audio waveform.

Visual Stack:
  - Pitch black background
  - Neon glowing oscilloscope waveform (audio-reactive)
  - Centered serif-style captions (word by word)
  - ALL CAPS = gold color + size pop + screen flash
  - Constant subtle Ken Burns zoom on the canvas
  - Cinematic vignette overlay

Output: raw_video.mp4 (1080x1920, no audio track)
"""

import os
import re
import sys
import glob
import shutil
import zipfile
import requests
import subprocess
import numpy as np
from pathlib import Path

# ── Optional imports with clear error messages ─────────────────
try:
    import cv2
except ImportError:
    sys.exit("[ERROR] opencv-python not installed. Add to requirements.txt")

try:
    import librosa
except ImportError:
    sys.exit("[ERROR] librosa not installed. Add to requirements.txt")

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("[WARN] Pillow not found — using OpenCV text rendering")

# ══════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════════════════════════

INPUT_SCRIPT    = Path("script.txt")
INPUT_AUDIO     = Path("output_voice.wav")
OUTPUT_VIDEO    = Path("raw_video.mp4")

# Canvas
W               = 1080
H               = 1920
FPS             = 30

# Waveform
WAVE_COLOR      = (0, 255, 180)      # Neon cyan-green (BGR)
WAVE_GLOW       = (0, 120, 80)       # Darker glow layer (BGR)
WAVE_THICKNESS  = 3
GLOW_THICKNESS  = 8
WAVE_HEIGHT     = 400                # Max amplitude in pixels
WAVE_Y_CENTER   = H // 2 + 200      # Slightly below center
WAVE_POINTS     = 200                # Smoothness of wave

# Caption
CAPTION_Y       = int(H * 0.28)     # Upper third
CAPTION_COLOR   = (255, 255, 255)   # White
CAPS_COLOR      = (0, 215, 255)     # Gold (BGR)
FONT_SCALE      = 2.8
CAPS_FONT_SCALE = 3.8
FONT_THICKNESS  = 5
CAPS_THICKNESS  = 7

# Ken Burns — very subtle zoom
KB_START_SCALE  = 1.0
KB_END_SCALE    = 1.04              # 4% zoom over full video

# Flash effect
FLASH_FRAMES    = 4                 # Frames a flash lasts
FLASH_ALPHA     = 0.18              # Flash intensity

# Vignette strength
VIGNETTE_STR    = 0.7

# ══════════════════════════════════════════════════════════════════
#  AUDIO DOWNLOAD (from Audio-generator- artifact)
# ══════════════════════════════════════════════════════════════════

def download_audio():
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        if INPUT_AUDIO.exists():
            print(f"[INFO] Using existing {INPUT_AUDIO}")
            return
        sys.exit("[ERROR] GH_TOKEN not set and no local audio file")

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
        sys.exit("[ERROR] No artifacts found in Audio-generator-")

    latest = artifacts[0]
    print(f"[INFO] Downloading audio: {latest['name']} ({latest['size_in_bytes']} bytes)")

    r = requests.get(latest["archive_download_url"], headers=headers)
    with open("audio.zip", "wb") as f:
        f.write(r.content)

    with zipfile.ZipFile("audio.zip", "r") as z:
        z.extractall("audio_extracted")

    wavs = (glob.glob("audio_extracted/**/*.wav", recursive=True)
            or glob.glob("audio_extracted/*.wav"))
    if not wavs:
        sys.exit("[ERROR] No WAV in artifact")

    shutil.copy(wavs[0], str(INPUT_AUDIO))
    print(f"[INFO] Audio ready ({INPUT_AUDIO.stat().st_size} bytes)")


# ══════════════════════════════════════════════════════════════════
#  AUDIO ANALYSIS
# ══════════════════════════════════════════════════════════════════

def analyse_audio(path: str, fps: int) -> tuple:
    """
    Load audio and extract per-frame RMS energy + raw waveform.
    Returns:
      rms_frames  : np.array of energy per video frame (0.0 - 1.0)
      wave_frames : np.array of shape (n_frames, WAVE_POINTS) — waveform per frame
      duration    : float seconds
    """
    print("[AUDIO] Loading and analysing audio...")
    y, sr = librosa.load(str(path), sr=None, mono=True)
    duration = len(y) / sr
    n_frames = int(duration * fps)

    print(f"[AUDIO] Duration: {duration:.2f}s | Frames: {n_frames} | SR: {sr}Hz")

    # Samples per video frame
    spf = len(y) / n_frames

    rms_frames  = np.zeros(n_frames, dtype=np.float32)
    wave_frames = np.zeros((n_frames, WAVE_POINTS), dtype=np.float32)

    for i in range(n_frames):
        start = int(i * spf)
        end   = int(start + spf)
        end   = min(end, len(y))
        chunk = y[start:end]

        if len(chunk) == 0:
            continue

        # RMS energy
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        rms_frames[i] = rms

        # Downsample chunk to WAVE_POINTS for waveform display
        if len(chunk) >= WAVE_POINTS:
            indices = np.linspace(0, len(chunk) - 1, WAVE_POINTS).astype(int)
            wave_frames[i] = chunk[indices]
        else:
            wave_frames[i, :len(chunk)] = chunk

    # Normalise RMS to 0-1
    mx = rms_frames.max()
    if mx > 0:
        rms_frames /= mx

    print("[AUDIO] Analysis complete")
    return rms_frames, wave_frames, duration


# ══════════════════════════════════════════════════════════════════
#  SCRIPT PARSING
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


def build_word_timeline(text: str, duration: float, fps: int) -> list:
    """
    Build a list of (word, start_frame, end_frame, is_caps) tuples.
    Each word is shown for an equal slice of the total duration.
    """
    words = text.split()
    if not words:
        return []

    n_frames    = int(duration * fps)
    frames_per  = n_frames / len(words)
    timeline    = []

    for i, word in enumerate(words):
        start = int(i * frames_per)
        end   = int((i + 1) * frames_per)
        is_caps = bool(re.search(r'[A-Z]{2,}', word))
        # Clean word for display
        display = re.sub(r'[^a-zA-Z0-9\'\-]', '', word)
        timeline.append((display, start, end, is_caps))

    return timeline


# ══════════════════════════════════════════════════════════════════
#  VIGNETTE OVERLAY
# ══════════════════════════════════════════════════════════════════

def build_vignette(w: int, h: int, strength: float = VIGNETTE_STR) -> np.ndarray:
    """Build a static vignette mask (dark edges)."""
    rows = np.linspace(-1, 1, h)
    cols = np.linspace(-1, 1, w)
    X, Y = np.meshgrid(cols, rows)
    dist = np.sqrt(X**2 + Y**2)
    # Normalise and invert — center is bright, edges are dark
    mask = 1.0 - np.clip(dist / dist.max() * strength, 0, 1)
    mask = mask.reshape(h, w, 1).astype(np.float32)
    return mask


# ══════════════════════════════════════════════════════════════════
#  FRAME RENDERER
# ══════════════════════════════════════════════════════════════════

def draw_waveform(canvas: np.ndarray, wave: np.ndarray, rms: float) -> None:
    """
    Draw glowing neon oscilloscope waveform on canvas.
    Two layers: thick glow + thin bright line on top.
    """
    amplitude = WAVE_HEIGHT * (0.3 + rms * 0.7)  # Min 30% height even in silence
    x_coords  = np.linspace(80, W - 80, WAVE_POINTS).astype(int)

    # Smooth the waveform
    kernel = np.ones(5) / 5
    wave_smooth = np.convolve(wave, kernel, mode='same')

    # Scale to pixels
    y_coords = (WAVE_Y_CENTER - wave_smooth * amplitude).astype(int)
    y_coords = np.clip(y_coords, 50, H - 50)

    pts = np.stack([x_coords, y_coords], axis=1).reshape(-1, 1, 2)

    # Glow layer (thick, darker)
    cv2.polylines(canvas, [pts], False, WAVE_GLOW, GLOW_THICKNESS, cv2.LINE_AA)
    # Bright core line
    cv2.polylines(canvas, [pts], False, WAVE_COLOR, WAVE_THICKNESS, cv2.LINE_AA)

    # Add bright dot at wave peaks
    peak_idx = np.argmax(np.abs(wave_smooth))
    peak_x   = int(x_coords[peak_idx])
    peak_y   = int(y_coords[peak_idx])
    cv2.circle(canvas, (peak_x, peak_y), 6, (255, 255, 255), -1)
    cv2.circle(canvas, (peak_x, peak_y), 10, WAVE_COLOR, 2)


def draw_caption(canvas: np.ndarray, word: str, is_caps: bool) -> None:
    """Draw centered word caption on canvas."""
    if not word:
        return

    color      = CAPS_COLOR if is_caps else CAPTION_COLOR
    scale      = CAPS_FONT_SCALE if is_caps else FONT_SCALE
    thickness  = CAPS_THICKNESS if is_caps else FONT_THICKNESS
    font       = cv2.FONT_HERSHEY_DUPLEX

    # Measure text size for centering
    (tw, th), baseline = cv2.getTextSize(word, font, scale, thickness)
    x = (W - tw) // 2
    y = CAPTION_Y + th

    # Shadow for depth
    cv2.putText(canvas, word, (x + 3, y + 3),
                font, scale, (0, 0, 0), thickness + 2, cv2.LINE_AA)
    # Main text
    cv2.putText(canvas, word, (x, y),
                font, scale, color, thickness, cv2.LINE_AA)

    # Gold underline for CAPS
    if is_caps:
        line_y = y + baseline + 8
        cv2.line(canvas, (x, line_y), (x + tw, line_y),
                 CAPS_COLOR, 3, cv2.LINE_AA)


def apply_ken_burns(canvas: np.ndarray, frame_idx: int,
                    total_frames: int) -> np.ndarray:
    """Apply subtle Ken Burns zoom-in to entire canvas."""
    t     = frame_idx / max(1, total_frames - 1)
    scale = KB_START_SCALE + t * (KB_END_SCALE - KB_START_SCALE)

    if abs(scale - 1.0) < 0.001:
        return canvas

    new_w = int(W * scale)
    new_h = int(H * scale)

    # Scale up
    scaled = cv2.resize(canvas, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

    # Crop center back to original size
    x_off = (new_w - W) // 2
    y_off = (new_h - H) // 2
    return scaled[y_off:y_off + H, x_off:x_off + W]


def apply_flash(canvas: np.ndarray, intensity: float) -> np.ndarray:
    """Apply white flash overlay for CAPS emphasis."""
    if intensity <= 0:
        return canvas
    overlay = np.ones_like(canvas, dtype=np.float32) * 255
    canvas_f = canvas.astype(np.float32)
    blended = cv2.addWeighted(canvas_f, 1.0 - intensity,
                              overlay, intensity, 0)
    return blended.astype(np.uint8)


def render_frame(frame_idx: int, total_frames: int,
                 rms: float, wave: np.ndarray,
                 word: str, is_caps: bool,
                 flash_intensity: float,
                 vignette: np.ndarray) -> np.ndarray:
    """Render a single frame — pure procedural, no external assets."""

    # Black canvas
    canvas = np.zeros((H, W, 3), dtype=np.uint8)

    # Draw waveform
    draw_waveform(canvas, wave, rms)

    # Draw caption
    draw_caption(canvas, word, is_caps)

    # Subtle horizontal scan line at wave center (cinematic detail)
    cv2.line(canvas, (0, WAVE_Y_CENTER), (W, WAVE_Y_CENTER),
             (20, 20, 20), 1, cv2.LINE_AA)

    # Apply vignette
    canvas_f = canvas.astype(np.float32) / 255.0
    canvas_f = canvas_f * vignette
    canvas   = (canvas_f * 255).clip(0, 255).astype(np.uint8)

    # Apply Ken Burns zoom
    canvas = apply_ken_burns(canvas, frame_idx, total_frames)

    # Flash on CAPS words
    if flash_intensity > 0:
        canvas = apply_flash(canvas, flash_intensity)

    return canvas


# ══════════════════════════════════════════════════════════════════
#  VIDEO WRITER
# ══════════════════════════════════════════════════════════════════

def write_video(rms_frames: np.ndarray, wave_frames: np.ndarray,
                word_timeline: list, duration: float) -> None:
    """
    Render all frames and write to MP4 using OpenCV VideoWriter.
    No audio track — added by editor repo.
    """
    n_frames   = len(rms_frames)
    vignette   = build_vignette(W, H)
    fourcc     = cv2.VideoWriter_fourcc(*'mp4v')
    temp_out   = "raw_video_temp.mp4"
    writer     = cv2.VideoWriter(temp_out, fourcc, FPS, (W, H))

    if not writer.isOpened():
        sys.exit("[ERROR] VideoWriter failed to open")

    print(f"[RENDER] Rendering {n_frames} frames @ {FPS}fps...")
    print(f"[RENDER] Resolution: {W}x{H} | Duration: {duration:.2f}s")

    # Build word lookup: frame → (word, is_caps)
    frame_word = {}
    for (word, start, end, is_caps) in word_timeline:
        for f in range(start, end):
            frame_word[f] = (word, is_caps)

    # Flash state
    flash_counter  = 0
    last_was_caps  = False
    log_every      = max(1, n_frames // 20)

    for i in range(n_frames):
        rms  = float(rms_frames[i])
        wave = wave_frames[i]

        word, is_caps = frame_word.get(i, ("", False))

        # Trigger flash on new CAPS word
        if is_caps and not last_was_caps:
            flash_counter = FLASH_FRAMES
        last_was_caps = is_caps

        flash_intensity = (flash_counter / FLASH_FRAMES) * FLASH_ALPHA
        if flash_counter > 0:
            flash_counter -= 1

        frame = render_frame(
            i, n_frames, rms, wave,
            word, is_caps, flash_intensity, vignette
        )
        writer.write(frame)

        if i % log_every == 0:
            pct = int((i / n_frames) * 100)
            print(f"  [RENDER] {pct}% ({i}/{n_frames})")

    writer.release()
    print("[RENDER] Frames complete")

    # Re-encode with ffmpeg for proper MP4 compatibility
    print("[ENCODE] Re-encoding with ffmpeg...")
    cmd = [
        "ffmpeg", "-y",
        "-i", temp_out,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-an",
        str(OUTPUT_VIDEO)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[WARN] ffmpeg re-encode failed: {result.stderr[-300:]}")
        shutil.copy(temp_out, str(OUTPUT_VIDEO))
    else:
        Path(temp_out).unlink(missing_ok=True)

    size_mb = OUTPUT_VIDEO.stat().st_size / (1024 * 1024)
    print(f"[✓] Video saved → '{OUTPUT_VIDEO}' ({size_mb:.1f} MB)")


# ══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════

def main():
    print("=" * 62)
    print("  Dark Minimalism Audio-Reactive Engine")
    print("  Procedural · No Stock Footage · No External Assets")
    print("=" * 62)

    # Download audio if needed
    if not INPUT_AUDIO.exists():
        print("[INFO] Downloading audio artifact...")
        download_audio()

    # Load and clean script
    if not INPUT_SCRIPT.exists():
        sys.exit("[ERROR] script.txt not found")
    raw         = INPUT_SCRIPT.read_text(encoding="utf-8")
    clean       = clean_script(raw)
    print(f"[INFO] Script: {len(clean.split())} words")

    # Analyse audio
    rms_frames, wave_frames, duration = analyse_audio(str(INPUT_AUDIO), FPS)
    n_frames = len(rms_frames)

    # Build word timeline
    word_timeline = build_word_timeline(clean, duration, FPS)
    caps_count    = sum(1 for _, _, _, c in word_timeline if c)
    print(f"[INFO] {len(word_timeline)} words | {caps_count} CAPS triggers")

    # Render
    write_video(rms_frames, wave_frames, word_timeline, duration)

    print("\n" + "=" * 62)
    print("  [✓] DONE — raw_video.mp4 ready for editor")
    print("=" * 62)


if __name__ == "__main__":
    main()
