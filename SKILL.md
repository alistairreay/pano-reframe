---
name: pano-reframe
description: Inspect stitched spherical drone or gimbal panoramas and extract normal perspective views by yaw, pitch, FoV, compass reference or wall alignment. Use for panorama interpretation and building/photo reference work; ordinary lens correction and stitching individual photos are outside this skill.
license: MIT
---

# Panorama Reframe

Use the deterministic helper to convert a stitched equirectangular panorama into
rectilinear camera views. It samples the original pixels mathematically, preserves
the source and produces a JSON manifest with orientation, scale conventions,
source hash and missing coverage. It does not generate image content.

These instructions are harness-neutral. Use the host's file-reading, shell/Python
execution and image-viewing tools. Resolve paths from this skill's actual location;
no particular tool name, agent SDK or provider-specific environment variable is
required. `agents/openai.yaml` is optional UI metadata for Codex and can be ignored
by other harnesses. Read the README's harness setup section only when installing.

## Run the helper

Requires Python 3.10 or newer with NumPy and Pillow, plus local file access. The
skill root is the folder containing this file. Prefer its `.venv/bin/python`
when available; otherwise use a compatible Python. The portable entrypoint
is `<skill-root>/scripts/pano_reframe.py`. It works from any directory. If dependencies
are missing, create a project-local venv and install the two packages; do not alter
an unrelated/global Python environment. The project also installs a `pano-reframe`
console command through `pip install -e <skill-root>`.

Inspect first:

```sh
python <skill-root>/scripts/pano_reframe.py inspect /path/to/panorama.jpg
```

Choose useful directions and render:

```sh
python <skill-root>/scripts/pano_reframe.py view /path/to/panorama.jpg \
  --full-sphere --yaw 90 --elevation 10 --hfov 70 --output /path/to/view.png
```

Use `--full-sphere` only when the source is known to be a full 360° × 180°
equirectangular sphere. A 2:1 aspect ratio alone is insufficient evidence. Without
that explicit declaration, the helper requires usable GPano crop metadata. It
rescales metadata for uniform resizing and rejects incompatible aspect changes.
It rejects cylindrical projections, ordinary wide-angle photos and non-normalized
EXIF orientation. An explicit full-sphere declaration overrides projection/crop
metadata, so inspect the source before using it.

Yaw zero is the full spherical canvas's centre direction after pitch/roll leveling;
yaw increases to the right. Elevation/pitch is an angle above the horizon, not camera
altitude. FoV is horizontal, independent of source-camera focal length or aperture.
Roll follows GPano: increasing roll rotates the apparent horizon counterclockwise.
Source pitch/roll come from manual overrides, calibration, or GPano pose, in that
order; missing values are assumed zero. Verify the horizon visually. Gimbal
stabilization is supporting context, not proof every panorama is perfectly level.

For compass headings, use `--heading` with GPano PoseHeadingDegrees or an explicit
`--heading-zero` / calibration `heading_zero`. Do not treat a raw DJI aircraft yaw,
per-frame gimbal yaw or EXIF image direction as the stitched sphere's heading
without verifying the reference. DJI Fly/original captures may provide calibration
information; availability is not guaranteed. Ask for one known bearing if needed.

## Face a wall

Choose the method supported by the evidence:

- **Plan:** a wall segment, camera position and known relation between plan north
  and relative panorama yaw. `--north-yaw` is required, including an explicit zero.
- **Image:** four original-pixel corners of a genuinely rectangular feature in a
  vertical wall (window/frame), in TL, TR, BR, BL order. Horizontal top/bottom edges
  establish a vanishing direction; vertical sides check the level-wall assumption.
- **Aim only:** `view --point x y` points at a pixel. Label it as aiming, not a
  recovered perpendicular wall orientation.

```sh
python <skill-root>/scripts/pano_reframe.py wall /path/to/panorama.jpg \
  --full-sphere --segment 0 4 5 4 --camera 2 0 --north-yaw 30 \
  --output /path/to/wall.png --name fireplace --save-wall /path/to/calibration.json
```

Image mode uses `--corners TLx TLy TRx TRy BRx BRy BLx BLy` instead of segment,
camera and north yaw. Coordinates are in the original image, not its resized tool
preview. Convert preview coordinates back to source resolution. Panorama edges
may curve; use geometric endpoints, not a straight-line crop of the flattened image.
Avoid stitched duplicates, moving objects, irregular stone edges and nonrectangular
fixtures. The helper rejects degenerate or inconsistent markings. A passing fit
is still an estimate; inspect the output and refine points or level calibration
when needed. A wall viewed edge-on or under heavy stitching distortion may not
support reliable snapping.

Save named wall references and reuse with `view --calibration profile.json --wall
fireplace`. Profiles saved by the helper are bound to the source hash; do not reuse
across another panorama. Extend an existing profile with `--calibration` and
`--save-wall` targeting the same file plus deliberate `--overwrite`. Compass
calibration can be stored as `heading_zero = known_bearing - relative_yaw` modulo
360. Read [references/geometry.md](references/geometry.md) for pose/crop conventions,
wall assumptions, calibration schema and limitations when implementing or debugging.

## Verify and deliver

Choose FoV to show the feature clearly (70° is the helper default); make additional
overlapping views when useful. Show the derived views with their orientation/FoV
and keep the original source available. Check straight edges, the horizon, seam
continuity, missing coverage and visible stitching artifacts. PNG exposes missing
rays as transparency; JPEG uses black. A source's filled/synthetic regions cannot
be identified reliably from metadata alone.

Reprojection cannot repair stitching/parallax, restore missing detail, infer
metric lengths, or create a new physical viewpoint. Mark assumptions and wall
estimates accordingly. Keep private source photos and outputs in the user's
chosen private workspace; public examples/tests use synthetic images. No network
upload is needed for processing. Existing outputs require `--overwrite`; originals
cannot be overwritten even with that flag.
