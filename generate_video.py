"""
generate_video.py — Automated Video Generator
==============================================
Fetches Pexels stock footage based on script keywords,
assembles clips, syncs length to audio.
Outputs: raw_video.mp4 (NO audio track — merged later by editor)
"""

import os
import re
import sys
import json
import requests
import subprocess
from pathlib import Path

# ══════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════════════════════════

PEXELS_API_KEY  = os.environ.get("PEXELS_API_KEY", "")
INPUT_SCRIPT    = Path("script.txt")
INPUT_AUDIO     = Path("output_voice.wav")
OUTPUT_VIDEO    = Path("raw_video.mp4")

VIDEO_WIDTH     = 1080
VIDEO_HEIGHT    = 1920   # 9:16 vertical (Shorts/Reels)
FPS             = 30
FONT_SIZE       = 68
FONT_COLOR      = "white"
STROKE_COLOR    = "black"
STROKE_WIDTH    = 3
MAX_CLIPS       = 8      # Max stock clips to fetch
CLIP_DURATION   = 4      # Seconds per clip

# ══════════════════════════════════════════════════════════════════
#  KEYWORD EXTRACTION
# ══════════════════════════════════════════════════════════════════

def extract_keywords(text: str) -> list:
    """Pull meaningful nouns/verbs from script for Pexels search."""
    clean = re.sub(r'\[.*?\]', '', text)
    clean = re.sub(r'--- .*? ---', '', clean)

    stopwords = {
        'the','a','an','and','or','but','in','on','at','to','for',
        'of','with','it','is','was','be','are','were','i','you',
        'he','she','they','we','my','your','his','her','just','like',
        'that','this','what','when','where','how','who','from','not',
        'no','so','then','have','had','has','did','do','about','out',
        'up','one','me','her','him','us','its','been','would','could',
        'said','told','thought','knew','felt','got','went','came'
    }

    words = re.findall(r'\b[a-z]{4,}\b', clean.lower())
    keywords = [w for w in words if w not in stopwords]

    freq = {}
    for w in keywords:
        freq[w] = freq.get(w, 0) + 1
    sorted_kw = sorted(freq, key=freq.get, reverse=True)

    fallbacks = ['cinematic', 'dramatic', 'emotion', 'person', 'life']
    final = sorted_kw[:5] + fallbacks
    print(f"[INFO] Keywords extracted: {final[:8]}")
    return final[:8]


# ══════════════════════════════════════════════════════════════════
#  AUDIO DURATION
# ══════════════════════════════════════════════════════════════════

def get_audio_duration(audio_path: str) -> float:
    """Get audio duration using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", audio_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)
    duration = float(data["format"]["duration"])
    print(f"[INFO] Audio duration: {duration:.2f}s")
    return duration


# ══════════════════════════════════════════════════════════════════
#  PEXELS VIDEO FETCHER
# ══════════════════════════════════════════════════════════════════

def fetch_pexels_videos(keywords: list, count: int = MAX_CLIPS) -> list:
    """Search Pexels for vertical video clips matching keywords."""
    if not PEXELS_API_KEY:
        sys.exit("[ERROR] PEXELS_API_KEY not set in environment secrets.")

    headers = {"Authorization": PEXELS_API_KEY}
    video_urls = []

    for keyword in keywords:
        if len(video_urls) >= count:
            break

        url = (f"https://api.pexels.com/videos/search"
               f"?query={keyword}&orientation=portrait&per_page=3&size=medium")

        try:
            res = requests.get(url, headers=headers, timeout=10)
            data = res.json()

            for video in data.get("videos", []):
                if len(video_urls) >= count:
                    break
                files = video.get("video_files", [])
                portrait_files = [
                    f for f in files
                    if f.get("width", 0) <= 1080 and f.get("height", 0) >= f.get("width", 1)
                ]
                if not portrait_files:
                    portrait_files = files

                if portrait_files:
                    chosen = sorted(portrait_files, key=lambda x: x.get("width", 0))[-1]
                    video_urls.append({
                        "url": chosen["link"],
                        "keyword": keyword,
                        "width": chosen.get("width"),
                        "height": chosen.get("height")
                    })
                    print(f"  [PEXELS] Found clip for '{keyword}': "
                          f"{chosen.get('width')}x{chosen.get('height')}")

        except Exception as e:
            print(f"  [WARN] Pexels search failed for '{keyword}': {e}")
            continue

    if not video_urls:
        sys.exit("[ERROR] No video clips fetched from Pexels. Check API key.")

    print(f"[INFO] Total clips fetched: {len(video_urls)}")
    return video_urls


def download_clips(video_list: list) -> list:
    """Download video clips to local disk."""
    clip_paths = []
    clips_dir = Path("clips")
    clips_dir.mkdir(exist_ok=True)

    for i, video in enumerate(video_list):
        out_path = clips_dir / f"clip_{i:02d}.mp4"
        print(f"  [DOWNLOAD] Clip {i+1}/{len(video_list)} → {out_path}")

        try:
            r = requests.get(video["url"], stream=True, timeout=30)
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            clip_paths.append(str(out_path))
        except Exception as e:
            print(f"  [WARN] Failed to download clip {i}: {e}")

    return clip_paths


# ══════════════════════════════════════════════════════════════════
#  VIDEO ASSEMBLY VIA FFMPEG
# ══════════════════════════════════════════════════════════════════

def trim_and_scale_clip(input_path: str, output_path: str, duration: float):
    """Trim clip to duration and scale to 1080x1920."""
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-t", str(duration),
        "-vf", (f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:"
                f"force_original_aspect_ratio=increase,"
                f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},"
                f"setsar=1"),
        "-r", str(FPS),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-an",
        output_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)


def create_concat_video(clip_paths: list, audio_duration: float) -> str:
    """
    Loop clips to fill audio duration, concatenate into one video.
    """
    processed_dir = Path("processed_clips")
    processed_dir.mkdir(exist_ok=True)
    processed_paths = []

    # +2 ensures we always have more footage than needed
    clips_needed = max(1, int(audio_duration / CLIP_DURATION) + 2)
    source_clips = (clip_paths * (clips_needed // len(clip_paths) + 1))[:clips_needed]

    print(f"[INFO] Processing {len(source_clips)} clip segments...")

    for i, clip in enumerate(source_clips):
        out = str(processed_dir / f"proc_{i:03d}.mp4")
        try:
            trim_and_scale_clip(clip, out, CLIP_DURATION)
            processed_paths.append(out)
            print(f"  [PROCESS] Clip {i+1}/{len(source_clips)} done")
        except Exception as e:
            print(f"  [WARN] Skipping clip {i}: {e}")

    if not processed_paths:
        sys.exit("[ERROR] No clips processed successfully.")

    concat_file = Path("concat_list.txt")
    with open(concat_file, "w") as f:
        for p in processed_paths:
            f.write(f"file '{p}'\n")

    concat_output = "concat_raw.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        concat_output
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    print(f"[INFO] Concatenation complete → {concat_output}")
    return concat_output


def add_captions(video_path: str, script_text: str, audio_duration: float) -> str:
    """
    Add dynamic word-by-word style captions using ffmpeg drawtext.
    Splits script into chunks of 4 words, times them evenly.
    """
    clean = re.sub(r'\[.*?\]', '', script_text)
    clean = re.sub(r'--- .*? ---', '', clean, flags=re.DOTALL)
    clean = re.sub(r'\n+', ' ', clean).strip()

    words = clean.split()
    chunk_size = 4
    chunks = [' '.join(words[i:i+chunk_size]) for i in range(0, len(words), chunk_size)]

    if not chunks:
        return video_path

    time_per_chunk = audio_duration / len(chunks)

    filters = []
    for i, chunk in enumerate(chunks):
        start_t = i * time_per_chunk
        end_t   = start_t + time_per_chunk
        safe_text = chunk.replace("'", "\\'").replace(":", "\\:").replace(",", "\\,")

        filters.append(
            f"drawtext=text='{safe_text}'"
            f":fontsize={FONT_SIZE}"
            f":fontcolor={FONT_COLOR}"
            f":bordercolor={STROKE_COLOR}"
            f":borderw={STROKE_WIDTH}"
            f":x=(w-text_w)/2"
            f":y=h-text_h-120"
            f":enable='between(t,{start_t:.2f},{end_t:.2f})'"
        )

    filter_str = ','.join(filters)
    captioned_output = "captioned_video.mp4"

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", filter_str,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-an",
        captioned_output
    ]

    print("[INFO] Adding captions...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"[WARN] Caption step failed, using uncaptioned video.")
        return video_path

    print("[INFO] Captions added.")
    return captioned_output


def trim_to_audio_duration(video_path: str, audio_path: str, output_path: str):
    """
    Trim video to exact audio duration.
    NO audio track — will be merged later by the editor repo.
    """
    audio_duration = get_audio_duration(audio_path)
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-t", str(audio_duration),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-an",                  # No audio track
        output_path
    ]
    print(f"[INFO] Trimming video to exact length: {audio_duration:.2f}s (no audio)...")
    subprocess.run(cmd, capture_output=True, check=True)
    size_mb = Path(output_path).stat().st_size / (1024 * 1024)
    print(f"[✓] Video saved → '{output_path}'  ({size_mb:.1f} MB, no audio track)")


# ══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  Automated Video Generator  |  Shorts/Reels Edition")
    print("  Output: raw_video.mp4 (no audio — merged by editor)")
    print("=" * 60)

    if not INPUT_SCRIPT.exists():
        sys.exit("[ERROR] script.txt not found.")
    script_text = INPUT_SCRIPT.read_text(encoding="utf-8")
    print(f"[INFO] Script loaded ({len(script_text)} chars)")

    if not INPUT_AUDIO.exists():
        sys.exit("[ERROR] output_voice.wav not found.")

    audio_duration = get_audio_duration(str(INPUT_AUDIO))

    keywords   = extract_keywords(script_text)
    video_list = fetch_pexels_videos(keywords)
    clip_paths = download_clips(video_list)

    concat_video = create_concat_video(clip_paths, audio_duration)
    captioned    = add_captions(concat_video, script_text, audio_duration)
    trim_to_audio_duration(captioned, str(INPUT_AUDIO), str(OUTPUT_VIDEO))

    print("\n[✓] Done. Download raw_video.mp4 from GitHub Artifacts.")


if __name__ == "__main__":
    main()
