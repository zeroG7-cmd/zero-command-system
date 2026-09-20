#!/usr/bin/env python3
"""Rebuild static/data/zero_avatar_voxel.json from a pixel-art source image.

Run this again whenever you redraw the avatar art, most importantly once
you have a REAL back-view for the chibi character - right now the "back"
layer in the JSON is just a horizontally-mirrored copy of the front (see
the note in voxel_builder.js), which is a stand-in, not the real thing.

Usage (from the zero-command-system repo root):
    python scripts/build_avatar_voxels.py
    python scripts/build_avatar_voxels.py --front path/to/front.png --back path/to/back.png

With no arguments it looks for the chibi art at the path it currently
lives at in zeroGravity-rnd (a sibling folder to this repo):
    ../zeroGravity-rnd/zero_world/03_characters/zero/concept illustration/zero_pixel_mini_v2.png

Requires Pillow: pip install Pillow
"""
import argparse
import json
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("This script needs Pillow: pip install Pillow", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FRONT = (
    REPO_ROOT.parent
    / "zeroGravity-rnd" / "zero_world" / "03_characters" / "zero"
    / "concept illustration" / "zero_pixel_mini_v2.png"
)
OUTPUT_PATH = REPO_ROOT / "static" / "data" / "zero_avatar_voxel.json"

TARGET_WIDTH = 42   # voxel grid columns - matches static/js/voxel_builder.js expectations,
                     # but the builder reads w/h from the JSON so this can change freely
QUANTIZE_COLORS = 20
ALPHA_CUTOFF = 110   # pixels less opaque than this are treated as transparent


def build_grid(image_path: Path):
    im = Image.open(image_path).convert("RGBA")
    aspect = im.height / im.width
    target_h = round(TARGET_WIDTH * aspect)
    small = im.resize((TARGET_WIDTH, target_h), Image.Resampling.BOX)

    quantized = small.convert("RGB").quantize(
        colors=QUANTIZE_COLORS, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
    ).convert("RGB")
    alpha = small.split()[3]
    apx, qpx = alpha.load(), quantized.load()

    grid = []
    for y in range(target_h):
        row = []
        for x in range(TARGET_WIDTH):
            if apx[x, y] > ALPHA_CUTOFF:
                r, g, b = qpx[x, y]
                row.append("%02x%02x%02x" % (r, g, b))
            else:
                row.append(None)
        grid.append(row)
    return TARGET_WIDTH, target_h, grid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--front", type=Path, default=DEFAULT_FRONT, help="front-view pixel art PNG")
    parser.add_argument("--back", type=Path, default=None, help="real back-view pixel art PNG, if you have one")
    args = parser.parse_args()

    if not args.front.exists():
        print(f"Front image not found: {args.front}", file=sys.stderr)
        sys.exit(1)

    w, h, front = build_grid(args.front)

    if args.back and args.back.exists():
        back_w, back_h, back = build_grid(args.back)
        if (back_w, back_h) != (w, h):
            print(
                f"Warning: back image grid ({back_w}x{back_h}) doesn't match "
                f"front ({w}x{h}) - front and back should be the same canvas "
                f"size in your art tool for this to line up correctly.",
                file=sys.stderr,
            )
        source_note = f"{args.front.name} (front, real) + {args.back.name} (back, real)"
    else:
        back = [list(reversed(row)) for row in front]
        source_note = f"{args.front.name} (front real, back MIRRORED - no real back reference yet)"

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"w": w, "h": h, "front": front, "back": back, "source": source_note}))
    print(f"Wrote {OUTPUT_PATH} ({w}x{h} grid) - {source_note}")


if __name__ == "__main__":
    main()
