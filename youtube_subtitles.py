"""
YouTube Subtitle Downloader
===========================

Download subtitles/captions from a YouTube video and save them as a
timestamped plain-text file.

The script:
    - Downloads NO video or audio.
    - Prefers manually created subtitles.
    - Falls back to automatically generated subtitles.
    - Converts VTT subtitles into a simple TXT file.
    - Uses the YouTube video title as the output filename.

INSTALLATION (Ubuntu/Debian)
----------------------------

    sudo apt update
    sudo apt install python3 yt-dlp

Check that yt-dlp works:

    yt-dlp --version


USAGE
-----

    python3 youtube_subtitles.py "YOUTUBE_URL" LANGUAGE

Examples:

    python3 youtube_subtitles.py "https://www.youtube.com/watch?v=..." ko

    python3 youtube_subtitles.py "https://www.youtube.com/watch?v=..." en

    python3 youtube_subtitles.py "https://www.youtube.com/watch?v=..." de


LANGUAGE CODES
--------------

Common examples:

    en    English
    ko    Korean
    ja    Japanese
    zh    Chinese
    de    German
    fr    French
    es    Spanish

You can check what subtitle languages a video has with:

    yt-dlp --list-subs "YOUTUBE_URL"


OUTPUT
------

For a video titled:

    한국어 공부 - 초급 회화

The script will produce:

    한국어 공부 - 초급 회화.txt

with contents similar to:

    [00:00:02] 안녕하세요 여러분.
    [00:00:05] 오늘은 한국어를 공부해 보겠습니다.
    [00:00:09] 먼저 이 문장을 살펴볼게요.

If a subtitle line remains on screen across multiple VTT entries,
duplicate text is automatically removed.

"""

import argparse
import html
import re
import sys
import urllib.request
from pathlib import Path

import yt_dlp


def sanitize_filename(title):
    """
    Make a YouTube title safe to use as a Linux filename.
    """
    title = html.unescape(title)

    # Remove characters that are problematic on most filesystems.
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', title)

    # Collapse repeated whitespace.
    title = re.sub(r'\s+', ' ', title).strip()

    # Avoid a filename ending in a period or space.
    title = title.rstrip('. ')

    if not title:
        title = "youtube_subtitles"

    return title


def timestamp_to_seconds(timestamp):
    """
    Convert a VTT timestamp such as:

        00:01:23.456

    into seconds.

    This function is only used internally if needed.
    """
    timestamp = timestamp.replace(',', '.')

    parts = timestamp.split(':')

    if len(parts) == 3:
        hours, minutes, seconds = parts
        return (
            int(hours) * 3600
            + int(minutes) * 60
            + float(seconds)
        )

    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)

    return float(parts[0])


def format_timestamp(timestamp):
    """
    Convert a VTT timestamp to HH:MM:SS.

    Example:
        00:01:23.456 -> 00:01:23
    """
    timestamp = timestamp.replace(',', '.')
    seconds = int(timestamp_to_seconds(timestamp))

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60

    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def clean_caption_text(text):
    """
    Remove VTT/HTML formatting from a subtitle line.
    """
    # Remove HTML tags such as <c>, <i>, <b>, etc.
    text = re.sub(r"<[^>]+>", "", text)

    # Decode entities such as &amp;
    text = html.unescape(text)

    # Normalize whitespace.
    text = re.sub(r"\s+", " ", text).strip()

    return text


def parse_vtt(vtt_text):
    """
    Convert VTT subtitle data into:

        (timestamp, text)

    pairs.

    Duplicate consecutive subtitle text is removed.
    """

    lines = vtt_text.splitlines()

    entries = []

    timestamp_pattern = re.compile(
        r"(\d{2}:\d{2}:\d{2}[.,]\d{3})\s+-->"
    )

    current_timestamp = None
    current_text = []

    def save_current():
        nonlocal current_timestamp, current_text

        if current_timestamp is None:
            return

        text = " ".join(current_text)
        text = clean_caption_text(text)

        if text:
            entries.append((current_timestamp, text))

        current_timestamp = None
        current_text = []

    for line in lines:
        line = line.strip()

        # Skip VTT headers and metadata.
        if line.startswith("WEBVTT"):
            continue

        # Look for the beginning timestamp of a subtitle cue.
        match = timestamp_pattern.search(line)

        if match:
            # Save the previous subtitle first.
            save_current()

            current_timestamp = match.group(1)
            current_text = []
            continue

        # Ignore blank lines.
        if not line:
            save_current()
            continue

        # Ignore cue identifiers/numbers.
        if current_timestamp is None:
            continue

        current_text.append(line)

    save_current()

    # Remove consecutive duplicate captions.
    result = []
    previous_text = None

    for timestamp, text in entries:
        if text == previous_text:
            continue

        result.append((timestamp, text))
        previous_text = text

    return result


def find_subtitle(info, language):
    """
    Find a subtitle track for the requested language.

    Manual subtitles are preferred over automatic captions.

    Returns:
        (subtitle_info, is_automatic)
    """

    manual = info.get("subtitles", {})
    automatic = info.get("automatic_captions", {})

    if language in manual:
        return manual[language], False

    if language in automatic:
        return automatic[language], True

    # Sometimes YouTube provides language variants such as:
    # en-US, en-GB, etc.
    for lang, subtitles in manual.items():
        if lang.lower().startswith(language.lower() + "-"):
            return subtitles, False

    for lang, subtitles in automatic.items():
        if lang.lower().startswith(language.lower() + "-"):
            return subtitles, True

    return None, False


def choose_vtt_format(formats):
    """
    Prefer VTT, since it contains timestamps and is easy to parse.
    """

    for fmt in formats:
        if fmt.get("ext") == "vtt":
            return fmt

    # Fall back to the first available subtitle format.
    if formats:
        return formats[0]

    return None


def download_subtitle(subtitle_format):
    """
    Download the subtitle data directly from YouTube.
    """

    url = subtitle_format.get("url")

    if not url:
        raise RuntimeError("Subtitle track does not contain a download URL.")

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    with urllib.request.urlopen(request) as response:
        data = response.read()

    return data.decode("utf-8-sig")


def main():
    parser = argparse.ArgumentParser(
        description="Download YouTube subtitles as a timestamped TXT file."
    )

    parser.add_argument(
        "url",
        help="YouTube video URL"
    )

    parser.add_argument(
        "language",
        help="Subtitle language code, e.g. en, ko, de, ja"
    )

    args = parser.parse_args()

    # Don't download the video.
    ydl_options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

    print("Getting video information...")

    try:
        with yt_dlp.YoutubeDL(ydl_options) as ydl:
            info = ydl.extract_info(args.url, download=False)

    except Exception as e:
        print(f"ERROR: Could not retrieve video information.")
        print(f"       {e}")
        sys.exit(1)

    title = info.get("title", "youtube_subtitles")
    safe_title = sanitize_filename(title)

    subtitle_formats, is_automatic = find_subtitle(
        info,
        args.language
    )

    if subtitle_formats is None:
        print()
        print(f"No subtitles found for language: {args.language}")
        print()
        print("Available manual subtitle languages:")

        manual = info.get("subtitles", {})

        if manual:
            print("  " + ", ".join(sorted(manual.keys())))
        else:
            print("  None")

        print()
        print("Available automatic subtitle languages:")

        automatic = info.get("automatic_captions", {})

        if automatic:
            print("  " + ", ".join(sorted(automatic.keys())))
        else:
            print("  None")

        sys.exit(1)

    subtitle_format = choose_vtt_format(subtitle_formats)

    if subtitle_format is None:
        print("ERROR: A subtitle track was found, but it has no usable format.")
        sys.exit(1)

    if is_automatic:
        print("Using automatically generated subtitles.")
    else:
        print("Using manually provided subtitles.")

    print(f"Language: {args.language}")
    print(f"Title:    {title}")
    print("Downloading subtitles...")

    try:
        vtt_text = download_subtitle(subtitle_format)

    except Exception as e:
        print(f"ERROR: Could not download subtitles.")
        print(f"       {e}")
        sys.exit(1)

    subtitles = parse_vtt(vtt_text)

    if not subtitles:
        print("ERROR: The subtitle file contained no usable text.")
        sys.exit(1)

    output_file = Path(f"{safe_title}.txt")

    try:
        with output_file.open("w", encoding="utf-8") as f:
            for timestamp, text in subtitles:
                f.write(f"[{format_timestamp(timestamp)}] {text}\n")

    except OSError as e:
        print(f"ERROR: Could not write output file.")
        print(f"       {e}")
        sys.exit(1)

    print()
    print(f"Done!")
    print(f"Output: {output_file}")
    print(f"Lines:  {len(subtitles)}")


if __name__ == "__main__":
    main()
