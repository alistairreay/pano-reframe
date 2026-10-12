# Geometry and calibration reference

## Projection

Supported input is an equirectangular sphere or a rectangular crop of one. Source
pixel coordinates are measured from image boundaries: x right, y down, with pixel
centres at half-integers. The full canvas represents 360° longitude × 180° latitude.
Its centre is longitude 0 / latitude 0; left/right meet at ±180°.

Each output pixel defines a pinhole ray from the sphere centre. Horizontal focal
length in pixels is `W / (2 tan(horizontal_FoV/2))`; vertical FoV follows the output
aspect ratio. Rotate the ray, convert to longitude/latitude, and bilinearly sample
the source. Longitude wraps only for full-width coverage; a partial crop exposes
missing rays as transparent/black. Rows are processed in chunks to bound temporary
memory. Output is limited to 40 million pixels, FoV to (0,175) degrees.

Working coordinates are X east/right, Y north/forward, Z up. Relative yaw has no
geographic meaning until a bearing is calibrated. GPano pose uses the standard
rotation composition `Rz(-heading) Rx(pitch) Ry(roll)`, with heading clockwise from
north. Source pitch/roll are inverted before sampling to present a level world.
Output roll is independently selectable. Rendering changes orientation, not camera
position; there is no geometric sphere radius or real-world scale parameter.

## Metadata

The helper reads standard GPano XMP attributes/elements and camera make/model. It
does not expose GPS latitude/longitude. Pillow exposes standard JPEG APP1 XMP and
PNG XMP text; extended/split XMP, arbitrary vendor MakerNotes and DJI Fly databases
are not reconstructed by this version. Malformed XMP is reported; entity-bearing
XML is rejected. Missing heading stays unknown. Never substitute InitialViewHeading
for PoseHeading: the former is a preferred view, not the sphere's reference pose.

GPano full dimensions, crop dimensions and offsets locate cropped angular coverage.
Uniformly resized images scale all crop coordinates; nonuniform resizing is
rejected. Some exporters omit metadata entirely. `--full-sphere` is the user's
explicit assertion of full spherical coverage, not automatic detection from shape.

A DJI Flip's camera is listed as 24 mm equivalent, f/1.7, 82.1° FoV. These describe
individual captures and do not set the extraction FoV of a stitched sphere. Lens
calibration would matter for a future source-frame stitching workflow, which is
outside this tool. Level DJI/gimbal captures are useful context; verify the stitched
horizon and its origin before assigning bearings.

## Wall estimation

Plan mode uses the segment's perpendicular and chooses the facing sign based on
which side contains the camera. Coordinates may use any consistent length unit.
The result may point outside the finite wall segment when the camera's perpendicular
foot is beyond an endpoint; narrow or offset walls need manual framing.

Image mode interprets a marked rectangle's top/bottom edges as parallel horizontal
3D lines. Their great-circle planes intersect at a horizontal vanishing direction.
A vertical wall's normal is perpendicular to that direction and global up. Side
edges check consistency with vertical lines. The visible-facing sign is selected
from the marked rays. Default angular tolerance is 5°; this is a rejection threshold,
not an accuracy guarantee. True wall normals cannot be inferred from a single pixel
or an arbitrary four-point outline. Correct rectangle/pose assumptions are required.

Yaw estimates from windows or frames apply to their plane. A projecting bay or
angled fixture may differ from the surrounding wall. Curved/nonvertical walls need
a different model. This method does not rectify a plane from a different viewpoint
or recover its dimensions.

## Calibration JSON

```json
{
  "version": 1,
  "heading_zero": 25,
  "pose_pitch": 0,
  "pose_roll": 0,
  "walls": {
    "fireplace": {"yaw": 90}
  }
}
```

Angles are degrees. `heading_zero` is the compass bearing of relative yaw zero
in the leveled full sphere. It can be derived from a known reference:
`(known_bearing - relative_yaw) modulo 360`. Metadata/manual bearings should use the
same true/magnetic north convention; no magnetic declination conversion is done.
Saved profiles additionally include `source_sha256` and estimation details. Hash
binding prevents applying named wall views to another panorama. Manual profiles
without a hash require the caller to verify the intended source.

Pose overrides take precedence over calibration, which takes precedence over GPano.
The helper does not query the DJI app, fly logs or remote services. Per-frame gimbal
orientation can assist calibration but does not establish the stitcher's seam/origin.

## Authoritative references

- [GPano projection, crop and Euler conventions](https://developers.google.com/streetview/spherical-metadata)
- [DJI Flip camera specifications](https://www.dji.com/flip/specs)
- [DJI Flip panorama modes](https://www.dji.com/flip)
