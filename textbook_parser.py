"""
Korean Textbook OCR
===================

Convert a folder of photographed/scanned textbook pages into one UTF-8 text
file using Tesseract OCR.

INSTALLATION — Ubuntu/Debian/Linux Mint
---------------------------------------

1. Install Tesseract and its Korean language model:

    sudo apt update
    sudo apt install tesseract-ocr tesseract-ocr-kor

2. Verify that Korean is installed:

    tesseract --list-langs

You should see:

    kor

3. This script uses Pillow for optional image preprocessing.

    python3 -m pip install --user pillow

If your Linux distribution blocks system pip installations, use a virtual
environment:

    python3 -m venv .venv
    source .venv/bin/activate
    pip install pillow


NO pytesseract package is required. This script calls the Tesseract program
directly.


BASIC USAGE
-----------

Put your textbook pages into a directory:

    textbook/
        page001.jpg
        page002.jpg
        page003.jpg
        ...


Then run:

    python3 korean_ocr.py textbook/ chapter1.txt


The resulting chapter1.txt will contain something like:

    ============================================================
    PAGE 1: page001.jpg
    ============================================================

    안녕하세요?
    오늘은 무엇을 합니까?

    ============================================================
    PAGE 2: page002.jpg
    ============================================================

    ...


KOREAN + ENGLISH
----------------

By default, the script recognizes both Korean and English:

    -l kor+eng

If the textbook is almost entirely Korean, you can use:

    python3 korean_ocr.py textbook/ chapter1.txt --lang kor


PREPROCESSING
-------------

Phone photographs can benefit from basic preprocessing.

Try:

    python3 korean_ocr.py textbook/ chapter1.txt --preprocess

This will:

    * convert the image to grayscale
    * increase contrast
    * upscale the image 2x
    * perform mild contrast enhancement

The original images are never modified.


PAGE SEGMENTATION
-----------------

The default Tesseract page segmentation mode is 3, which automatically
analyzes the page layout.

For a page that is mostly one block of text, you can try:

    python3 korean_ocr.py textbook/ chapter1.txt --psm 6


RECURSIVE DIRECTORIES
---------------------

If your pages are divided into subdirectories:

    textbook/
        lesson1/
            page001.jpg
            page002.jpg
        lesson2/
            page001.jpg
            page002.jpg

Use:

    python3 korean_ocr.py textbook/ textbook.txt --recursive


SUPPORTED IMAGE FORMATS
-----------------------

.jpg
.jpeg
.png
.tif
.tiff
.bmp
.webp


IMPORTANT
---------

OCR is performed entirely on your computer. The images are not uploaded
anywhere by this script.

The purpose here isn't to perfectly reproduce the textbook's visual layout.
For our eventual use — giving the textbook content to an AI to create
additional Korean study material — getting the actual Korean sentences,
vocabulary, questions, and instructions accurately is much more important.

Keep your original photographs. We can improve the preprocessing later if
the first OCR results aren't good enough.


TROUBLESHOOTING
---------------

If you get an error involving "kor.traineddata":

    sudo apt install tesseract-ocr-kor


If Tesseract isn't found:

    which tesseract
    tesseract --version


If the OCR quality is poor, first try:

    --preprocess

and/or:

    --psm 6

"""


import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image, ImageOps, ImageEnhance
except ImportError:
    print("ERROR: Pillow is not installed.")
    print()
    print("Install it with:")
    print("    python3 -m pip install --user pillow")
    sys.exit(1)


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
}


def natural_sort_key(path):
    """
    Sort files naturally.

    For example:

        page1.jpg
        page2.jpg
        page10.jpg

    instead of:

        page1.jpg
        page10.jpg
        page2.jpg
    """

    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", path.name)
    ]


def find_images(directory, recursive=False):
    """Find supported image files in the input directory."""

    if recursive:
        pattern = "**/*"
    else:
        pattern = "*"

    images = [
        path
        for path in directory.glob(pattern)
        if path.is_file()
        and path.suffix.lower() in IMAGE_EXTENSIONS
    ]

    return sorted(images, key=natural_sort_key)


def preprocess_image(input_path, output_path):
    """
    Basic preprocessing for photographed textbook pages.

    Steps:
        1. grayscale
        2. automatic contrast
        3. 2x upscale
        4. mild contrast enhancement
    """

    with Image.open(input_path) as image:

        # Convert to grayscale.
        image = image.convert("L")

        # Improve black/white separation.
        image = ImageOps.autocontrast(image)

        # Upscale the text.
        image = image.resize(
            (
                image.width * 2,
                image.height * 2,
            ),
            Image.Resampling.LANCZOS,
        )

        # Mild additional contrast enhancement.
        image = ImageEnhance.Contrast(image).enhance(1.15)

        image.save(output_path)


def run_tesseract(image_path, language, psm):
    """Run Tesseract and return its recognized text."""

    command = [
        "tesseract",
        str(image_path),
        "stdout",
        "--oem",
        "1",
        "--psm",
        str(psm),
        "-l",
        language,
        "quiet",
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Tesseract failed for {image_path.name}:\n"
            f"{result.stderr.strip()}"
        )

    return result.stdout.strip()


def main():

    parser = argparse.ArgumentParser(
        description="OCR Korean textbook images into one UTF-8 text file."
    )

    parser.add_argument(
        "input_dir",
        type=Path,
        help="Directory containing textbook page images.",
    )

    parser.add_argument(
        "output_file",
        type=Path,
        help="Output UTF-8 text file.",
    )

    parser.add_argument(
        "--lang",
        default="kor+eng",
        help="Tesseract language(s). Default: kor+eng",
    )

    parser.add_argument(
        "--psm",
        type=int,
        default=3,
        help="Tesseract page segmentation mode. Default: 3",
    )

    parser.add_argument(
        "--preprocess",
        action="store_true",
        help="Preprocess and upscale images before OCR.",
    )

    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Search subdirectories for images.",
    )

    parser.add_argument(
        "--keep-empty",
        action="store_true",
        help="Include pages where no text was detected.",
    )

    args = parser.parse_args()

    # Make sure Tesseract exists.
    if shutil.which("tesseract") is None:

        print("ERROR: Tesseract was not found.")
        print()
        print("Install it with:")
        print("    sudo apt install tesseract-ocr tesseract-ocr-kor")

        sys.exit(1)

    # Check input directory.
    if not args.input_dir.is_dir():

        print(
            f"ERROR: Input directory does not exist: "
            f"{args.input_dir}"
        )

        sys.exit(1)

    # Find images.
    images = find_images(
        args.input_dir,
        args.recursive,
    )

    if not images:

        print(
            f"No supported images found in: "
            f"{args.input_dir}"
        )

        sys.exit(1)

    print(f"Found {len(images)} image(s).")
    print(f"Language: {args.lang}")
    print(f"PSM: {args.psm}")
    print(
        "Preprocessing:",
        "yes" if args.preprocess else "no",
    )
    print()

    # Make sure output directory exists.
    args.output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Temporary directory for processed images.
    with tempfile.TemporaryDirectory(
        prefix="korean_ocr_"
    ) as temp_dir:

        temp_dir = Path(temp_dir)

        with args.output_file.open(
            "w",
            encoding="utf-8",
        ) as output:

            for number, image_path in enumerate(
                images,
                start=1,
            ):

                print(
                    f"[{number}/{len(images)}] "
                    f"{image_path.name}"
                )

                ocr_image = image_path

                # Optionally preprocess.
                if args.preprocess:

                    processed_path = (
                        temp_dir
                        / f"page_{number:05d}.png"
                    )

                    preprocess_image(
                        image_path,
                        processed_path,
                    )

                    ocr_image = processed_path

                try:

                    text = run_tesseract(
                        ocr_image,
                        args.lang,
                        args.psm,
                    )

                except Exception as error:

                    print(
                        f"  ERROR: {error}"
                    )

                    continue

                if not text and not args.keep_empty:

                    print(
                        "  No text detected; skipping."
                    )

                    continue

                # Write page separator.
                output.write(
                    "=" * 60 + "\n"
                )

                output.write(
                    f"PAGE {number}: "
                    f"{image_path.name}\n"
                )

                output.write(
                    "=" * 60 + "\n\n"
                )

                if text:

                    output.write(text)
                    output.write("\n")

                output.write("\n")

    print()
    print(
        f"Done. OCR text written to: "
        f"{args.output_file}"
    )


if __name__ == "__main__":
    main()