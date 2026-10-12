"""Deterministic geometry. ENU axes: X right/east, Y forward/north, Z up.

Pose rotation follows GPano conventions documented at
https://developers.google.com/streetview/spherical-metadata .
"""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import math
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image

GPANO = "http://ns.google.com/photos/1.0/panorama/"
CROP_KEYS = ("FullPanoWidthPixels", "FullPanoHeightPixels",
             "CroppedAreaImageWidthPixels", "CroppedAreaImageHeightPixels",
             "CroppedAreaLeftPixels", "CroppedAreaTopPixels")


def finite(value, label):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    return value


def parse_xmp(packet):
    """Read GPano fields only; ignore location and unrelated namespaces."""
    if isinstance(packet, str):
        packet = packet.encode()
    if b"<!DOCTYPE" in packet.upper() or b"<!ENTITY" in packet.upper():
        raise ValueError("XMP entities/DOCTYPE are unsupported")
    root = ET.fromstring(packet)
    result = {}
    for node in root.iter():
        if node.tag.startswith("{" + GPANO + "}") and node.text:
            result[node.tag.split("}", 1)[1]] = node.text.strip()
        for key, value in node.attrib.items():
            if key.startswith("{" + GPANO + "}"):
                result[key.split("}", 1)[1]] = value
    return result


def inspect_image(path):
    warnings = []
    with Image.open(path) as im:
        exif = im.getexif()
        info = dict(im.info)
        width, height = im.size
        camera = {"make": exif.get(271), "model": exif.get(272)}
        orientation = exif.get(274, 1)
    gpano = {}
    packet = info.get("xmp") or info.get("XML:com.adobe.xmp")
    if packet:
        try:
            gpano = parse_xmp(packet)
        except (ET.ParseError, ValueError) as exc:
            warnings.append(f"Unreadable XMP: {exc}")
    if orientation != 1:
        warnings.append("EXIF orientation is not 1; spherical coordinates use stored pixels")
    if not gpano:
        warnings.append("No GPano metadata: projection/coverage and compass heading are unverified")
    return {"width": width, "height": height, "camera": camera,
            "exif_orientation": orientation, "gpano": gpano,
            "warnings": warnings}


@dataclass(frozen=True)
class Geometry:
    width: int
    height: int
    full_width: float
    full_height: float
    left: float = 0
    top: float = 0
    basis: str = "metadata"

    @property
    def wraps(self):
        return math.isclose(self.width, self.full_width)

    def rays(self, points):
        points = np.asarray(points, dtype=float)
        if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
            raise ValueError("Points must be finite x,y pairs in source pixel coordinates")
        if np.any(points < 0) or np.any(points[:, 0] > self.width) or np.any(points[:, 1] > self.height):
            raise ValueError("Point outside source image")
        lon = 2 * np.pi * ((points[:, 0] + self.left) / self.full_width - .5)
        lat = np.pi * (.5 - (points[:, 1] + self.top) / self.full_height)
        return np.column_stack((np.cos(lat) * np.sin(lon),
                                np.cos(lat) * np.cos(lon), np.sin(lat)))


def geometry_from(meta, full_sphere=False):
    w, h = meta["width"], meta["height"]
    p = meta["gpano"]
    if meta["exif_orientation"] != 1:
        raise ValueError("Normalize EXIF orientation and update spherical metadata before rendering")
    if full_sphere:
        if not math.isclose(w / h, 2, rel_tol=.001):
            raise ValueError("Explicit full sphere requires a 2:1 image")
        return Geometry(w, h, w, h, basis="user-declared full sphere")
    if p.get("ProjectionType", "equirectangular") != "equirectangular":
        raise ValueError("Only equirectangular spherical images are supported")
    if not all(k in p for k in CROP_KEYS):
        raise ValueError("Missing spherical coverage metadata; use --full-sphere only for a known 360x180 image")
    fw, fh, cw, ch, left, top = [finite(p[k], k) for k in CROP_KEYS]
    if min(fw, fh, cw, ch) <= 0 or min(left, top) < 0:
        raise ValueError("Invalid GPano crop dimensions/offsets")
    if not math.isclose(fw / fh, 2, rel_tol=.001):
        raise ValueError("Full spherical canvas must have 2:1 aspect ratio")
    sx, sy = w / cw, h / ch
    if not math.isclose(sx, sy, rel_tol=.001):
        raise ValueError("Image was resized nonuniformly relative to GPano crop metadata")
    if left + cw > fw + 1e-6 or top + ch > fh + 1e-6:
        raise ValueError("GPano crop extends outside the full spherical canvas")
    return Geometry(w, h, fw * sx, fh * sy, left * sx, top * sy)


def rotation(yaw=0, pitch=0, roll=0):
    """GPano rotation Rz(-yaw) Rx(pitch) Ry(roll); degrees."""
    a, b, c = [math.radians(finite(v, "angle")) for v in (yaw, pitch, roll)]
    ca, sa, cb, sb, cc, sc = math.cos(a), math.sin(a), math.cos(b), math.sin(b), math.cos(c), math.sin(c)
    rz = np.array([[ca, sa, 0], [-sa, ca, 0], [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, cb, -sb], [0, sb, cb]])
    ry = np.array([[cc, 0, sc], [0, 1, 0], [-sc, 0, cc]])
    return rz @ rx @ ry


def unit(v):
    n = np.linalg.norm(v)
    if n < 1e-8:
        raise ValueError("Degenerate geometry: insufficient angular separation")
    return v / n


def snap_rectangle(geometry, corners, pose_pitch=0, pose_roll=0, tolerance=5):
    """TL,TR,BR,BL of a vertical rectangle, using top/bottom vanishing direction.

    Does not assume the rectangle is a square or infer any physical length.
    """
    r = geometry.rays(np.asarray(corners).reshape(4, 2)) @ rotation(0, pose_pitch, pose_roll).T
    top, bottom = unit(np.cross(r[0], r[1])), unit(np.cross(r[3], r[2]))
    vp = unit(np.cross(top, bottom))
    if abs(vp[2]) > math.sin(math.radians(tolerance)):
        raise ValueError("Marked top/bottom do not support a horizontal vanishing direction")
    for a, b in ((0, 3), (1, 2)):
        vertical_plane = unit(np.cross(r[a], r[b]))
        if abs(vertical_plane[2]) > math.sin(math.radians(tolerance)):
            raise ValueError("Marked side edges do not support a level, vertical wall")
    vp[2] = 0
    normal = unit(np.cross(vp, [0, 0, 1]))
    toward = r.mean(axis=0)
    dot = float(normal @ toward)
    if abs(dot) < 1e-6:
        raise ValueError("Wall normal is ambiguous from these markings")
    if dot < 0:
        normal = -normal
    yaw = math.degrees(math.atan2(normal[0], normal[1])) % 360
    return {"yaw": yaw, "pitch": 0., "method": "marked vertical rectangle",
            "corners_source_pixels": np.asarray(corners).reshape(4, 2).tolist(),
            "vanishing_elevation_error_degrees": math.degrees(math.asin(abs(float(unit(np.cross(top, bottom))[2])))),
            "confidence": "estimated; depends on correct edges, level pose and stitching"}


def snap_plan(segment, camera, north_yaw):
    """Plan X east, Y north; choose the perpendicular pointing toward the wall."""
    a, b = np.asarray(segment, dtype=float).reshape(2, 2)
    camera = np.asarray(camera, dtype=float)
    if not np.isfinite([*a, *b, *camera]).all():
        raise ValueError("Plan coordinates must be finite")
    d = b - a
    normal = unit(np.array([-d[1], d[0]]))
    dot = float(normal @ ((a + b) / 2 - camera))
    if abs(dot) < 1e-8:
        raise ValueError("Camera lies on the wall line; facing side is ambiguous")
    if dot < 0:
        normal = -normal
    yaw = (math.degrees(math.atan2(normal[0], normal[1])) + finite(north_yaw, "north yaw")) % 360
    return {"yaw": yaw, "pitch": 0., "method": "plan wall normal",
            "segment": [a.tolist(), b.tolist()], "camera_plan": camera.tolist(),
            "plan_north_yaw": north_yaw,
            "confidence": "depends on plan geometry, camera position and panorama alignment"}


def render(image, geometry, yaw=0, pitch=0, roll=0, hfov=70, width=1200, height=900,
           pose_pitch=0, pose_roll=0):
    hfov, pitch = finite(hfov, "horizontal FoV"), finite(pitch, "pitch")
    if not 0 < hfov < 175:
        raise ValueError("Horizontal FoV must be between 0 and 175 degrees")
    if not -90 <= pitch <= 90:
        raise ValueError("Pitch/elevation must be between -90 and 90 degrees")
    if width < 1 or height < 1 or width * height > 40_000_000:
        raise ValueError("Output must have positive dimensions and at most 40 million pixels")
    if image.size != (geometry.width, geometry.height):
        raise ValueError("Image and spherical geometry dimensions disagree")
    pixels = np.asarray(image.convert("RGB"))
    out = np.empty((height, width, 4), dtype=np.uint8)
    focal = width / (2 * math.tan(math.radians(hfov / 2)))
    transform = rotation(yaw, pitch, roll).T @ rotation(0, pose_pitch, pose_roll)
    # Row chunks avoid allocating full-resolution ray and sample grids at once.
    x = (np.arange(width) + .5 - width / 2) / focal
    for row in range(0, height, 128):
        end = min(row + 128, height)
        z = (height / 2 - np.arange(row, end) - .5) / focal
        xx, zz = np.meshgrid(x, z)
        rays = np.stack((xx, np.ones_like(xx), zz), axis=-1) @ transform
        lon = np.arctan2(rays[..., 0], rays[..., 1])
        lat = np.arctan2(rays[..., 2], np.hypot(rays[..., 0], rays[..., 1]))
        u = (lon / (2 * np.pi) + .5) * geometry.full_width - geometry.left - .5
        v = (.5 - lat / np.pi) * geometry.full_height - geometry.top - .5
        valid = (v >= -.5 - 1e-7) & (v <= geometry.height - .5 + 1e-7)
        if geometry.wraps:
            u = u % geometry.width
        else:
            valid &= (u >= -.5) & (u <= geometry.width - .5)
            u = np.clip(u, 0, geometry.width - 1)
        v = np.clip(v, 0, geometry.height - 1)
        x0, y0 = np.floor(u).astype(int), np.floor(v).astype(int)
        x1 = (x0 + 1) % geometry.width if geometry.wraps else np.minimum(x0 + 1, geometry.width - 1)
        y1 = np.minimum(y0 + 1, geometry.height - 1)
        dx, dy = (u - x0)[..., None], (v - y0)[..., None]
        color = ((1 - dy) * ((1 - dx) * pixels[y0, x0] + dx * pixels[y0, x1])
                 + dy * ((1 - dx) * pixels[y1, x0] + dx * pixels[y1, x1]))
        out[row:end, :, :3] = np.where(valid[..., None], np.rint(color), 0).astype(np.uint8)
        out[row:end, :, 3] = valid * 255
    return Image.fromarray(out), {"valid_fraction": float(np.mean(out[..., 3] == 255)),
                                  "vertical_fov": math.degrees(2 * math.atan(height / (2 * focal)))}


def source_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
