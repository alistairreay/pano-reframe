"""CLI and reproducible output manifests; originals are never overwritten."""
import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import sys

import numpy as np

from PIL import Image

from .core import finite, geometry_from, inspect_image, render, rotation, snap_plan, snap_rectangle, source_hash


def load_profile(path):
    if path is None:
        return {"version": 1, "walls": {}}
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict) or value.get("version", 1) != 1 or not isinstance(value.get("walls", {}), dict):
        raise ValueError("Calibration must be a version-1 JSON object with a walls object")
    for key in ("heading_zero", "pose_pitch", "pose_roll"):
        if key in value:
            finite(value[key], key)
    for wall in value.get("walls", {}).values():
        if not isinstance(wall, dict) or "yaw" not in wall:
            raise ValueError("Named walls must contain yaw")
        finite(wall["yaw"], "wall yaw")
    value.setdefault("version", 1)
    value.setdefault("walls", {})
    return value


def pose(meta, args, profile):
    p = meta["gpano"]
    pitch = args.source_pitch if args.source_pitch is not None else profile.get("pose_pitch", p.get("PosePitchDegrees", 0))
    roll = args.source_roll if args.source_roll is not None else profile.get("pose_roll", p.get("PoseRollDegrees", 0))
    pitch, roll = finite(pitch, "source pitch"), finite(roll, "source roll")
    if not -90 <= pitch <= 90 or not -180 <= roll <= 180:
        raise ValueError("Source pitch/roll outside spherical pose range")
    return pitch, roll


def heading_zero(meta, args, profile):
    if args.heading_zero is not None:
        return finite(args.heading_zero, "heading zero")
    if "heading_zero" in profile:
        return finite(profile["heading_zero"], "heading zero")
    if "PoseHeadingDegrees" in meta["gpano"]:
        return finite(meta["gpano"]["PoseHeadingDegrees"], "pose heading")
    raise ValueError("No compass reference; supply --heading-zero or a calibrated profile")


def ensure_output(path, original, overwrite):
    path = Path(path)
    if path.resolve() == Path(original).resolve():
        raise ValueError("Output cannot overwrite the original panorama")
    if path.exists() and not overwrite:
        raise ValueError(f"Output already exists: {path}; use --overwrite deliberately")
    return path


def parser():
    p = argparse.ArgumentParser(description="Reframe stitched spherical panoramas into rectilinear camera views")
    sub = p.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect", help="Read projection, crop and pose metadata without exposing GPS location")
    inspect.add_argument("image", type=Path)
    for name in ("view", "wall"):
        s = sub.add_parser(name)
        s.add_argument("image", type=Path)
        s.add_argument("--output", "-o", type=Path, required=True)
        s.add_argument("--full-sphere", action="store_true", help="Declare a known full 360x180, 2:1 equirectangular input")
        s.add_argument("--hfov", type=float, default=70, help="Output horizontal field of view in degrees")
        s.add_argument("--width", type=int, default=1200)
        s.add_argument("--height", type=int, default=900)
        s.add_argument("--pitch", "--elevation", type=float, default=None)
        s.add_argument("--roll", type=float, default=0)
        s.add_argument("--source-pitch", type=float, help="Panorama pose, overriding profile/XMP")
        s.add_argument("--source-roll", type=float, help="Panorama pose, overriding profile/XMP")
        s.add_argument("--heading-zero", type=float, help="Compass bearing of relative yaw zero; clockwise from north")
        s.add_argument("--calibration", type=Path)
        s.add_argument("--overwrite", action="store_true")
        if name == "view":
            direction = s.add_mutually_exclusive_group()
            direction.add_argument("--yaw", type=float, default=None)
            direction.add_argument("--heading", type=float)
            direction.add_argument("--wall", help="Named wall in calibration JSON")
            direction.add_argument("--point", type=float, nargs=2, metavar="PX", help="Aim at a source x,y pixel; does not estimate a wall normal")
        else:
            mode = s.add_mutually_exclusive_group(required=True)
            mode.add_argument("--corners", type=float, nargs=8, metavar="PX", help="Source pixels: TLx TLy TRx TRy BRx BRy BLx BLy")
            mode.add_argument("--segment", type=float, nargs=4, metavar="XY", help="Plan X east/Y north: x1 y1 x2 y2")
            s.add_argument("--camera", type=float, nargs=2, metavar="XY")
            s.add_argument("--north-yaw", type=float, help="Relative panorama yaw corresponding to plan north")
            s.add_argument("--save-wall", type=Path, help="Save a named wall to a reusable calibration profile")
            s.add_argument("--name", default="wall")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        meta = inspect_image(args.image)
        if args.command == "inspect":
            print(json.dumps(meta, indent=2))
            return 0
        profile = load_profile(args.calibration)
        digest = source_hash(args.image)
        if "source_sha256" in profile and profile["source_sha256"] != digest:
            raise ValueError("Calibration belongs to a different panorama")
        geometry = geometry_from(meta, args.full_sphere)
        pp, pr = pose(meta, args, profile)
        wall = None
        target_pitch = 0.
        if args.command == "wall":
            if args.corners:
                wall = snap_rectangle(geometry, args.corners, pp, pr)
            else:
                if args.camera is None or args.north_yaw is None:
                    raise ValueError("Plan wall snap requires --camera and --north-yaw")
                wall = snap_plan(args.segment, args.camera, args.north_yaw)
            yaw = wall["yaw"]
        elif args.wall:
            if args.wall not in profile["walls"]:
                raise ValueError(f"Unknown named wall: {args.wall}")
            wall = profile["walls"][args.wall]
            yaw = finite(wall["yaw"], "wall yaw")
        elif args.point is not None:
            ray = geometry.rays([args.point])[0] @ rotation(0, pp, pr).T
            yaw = math.degrees(math.atan2(ray[0], ray[1]))
            target_pitch = math.degrees(math.atan2(ray[2], np.hypot(ray[0], ray[1])))
        elif args.heading is not None:
            yaw = finite(args.heading, "heading") - heading_zero(meta, args, profile)
        else:
            yaw = finite(0 if args.yaw is None else args.yaw, "yaw")
        target_pitch = target_pitch if args.pitch is None else args.pitch
        output = ensure_output(args.output, args.image, args.overwrite)
        if output.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            raise ValueError("Output must be PNG or JPEG")
        sidecar = ensure_output(output.with_suffix(output.suffix + ".json"), args.image, args.overwrite)
        save_wall = None
        if args.command == "wall" and args.save_wall:
            save_wall = ensure_output(args.save_wall, args.image, args.overwrite)
            if save_wall.resolve() in (output.resolve(), sidecar.resolve()):
                raise ValueError("Calibration output must be separate from image and manifest")
        with Image.open(args.image) as source:
            view, stats = render(source, geometry, yaw, target_pitch, args.roll,
                                 args.hfov, args.width, args.height, pp, pr)
        warnings = list(meta["warnings"])
        if stats["valid_fraction"] < 1:
            warnings.append("Some output rays lack source coverage; PNG uses transparency, JPEG uses black")
        report = {"version": 1, "source_name": args.image.name,
                  "source_sha256": digest, "geometry": asdict(geometry),
                  "view": {"yaw": yaw % 360, "pitch": target_pitch, "roll": args.roll,
                           "horizontal_fov": args.hfov, "width": args.width, "height": args.height},
                  "source_pose": {"pitch": pp, "roll": pr}, "coverage": stats,
                  "wall": wall, "warnings": warnings,
                  "limits": "Rotation only: no depth, new viewpoint, metric scale or stitching repair"}
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.suffix.lower() in (".jpg", ".jpeg"):
            view = view.convert("RGB")
        view.save(output)
        sidecar.write_text(json.dumps(report, indent=2) + "\n")
        if save_wall:
            profile["walls"][args.name] = wall
            profile["source_sha256"] = report["source_sha256"]
            if args.heading_zero is not None:
                profile["heading_zero"] = finite(args.heading_zero, "heading zero")
            profile["pose_pitch"], profile["pose_roll"] = pp, pr
            save_wall.parent.mkdir(parents=True, exist_ok=True)
            save_wall.write_text(json.dumps(profile, indent=2) + "\n")
        print(json.dumps({"output": str(output), "manifest": str(sidecar),
                          "view": report["view"], "coverage": stats, "warnings": warnings}, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(f"pano-reframe: {exc}", file=sys.stderr)
        return 2


def entrypoint():
    raise SystemExit(main())
