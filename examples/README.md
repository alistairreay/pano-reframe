# Synthetic room example

A ray-cast cuboid with half-extents 3, 4 and 2 arbitrary units, viewed from its
centre. The room is rotated 35 degrees clockwise relative to the spherical
canvas centre. A red rectangular frame on one wall provides four known corners.
This is fabricated geometry with no relation to a real property.

The source is a full 1440 x 720 equirectangular sphere. Reproduce the 900 x 675
perspective view from the repository root:

```sh
.venv/bin/pano-reframe wall examples/room-sphere.png --full-sphere \
  --corners 753.739795292 285.832088144 966.260204708 285.832088144 966.260204708 434.167911856 753.739795292 434.167911856 \
  --width 900 --height 675 --hfov 70 --output examples/room-facing.png
```

Use `--overwrite` if the committed output already exists. The expected recovered
yaw is 35 degrees; its detailed manifest is `room-facing.png.json`. Pixel
coordinates in `corners.json` use the original source resolution.
