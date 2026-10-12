# Working on pano-reframe

This repository is the source of the discoverable `pano-reframe` Codex skill.
SKILL.md is its entrypoint. Core numerical operations are in pano_reframe/core.py;
CLI/profile/output handling is in pano_reframe/cli.py. The skill wrapper is
scripts/pano_reframe.py. Keep the wrapper runnable from unrelated working directories.

Preserve original panorama files. Keep examples and test fixtures synthetic; no
private source photos, home geometry, credentials or local photo paths belong in
this public repository. Analytical projections are permitted; don't substitute
AI-generated imagery for deterministic sampling.

Maintain the ENU/GPano rotation convention, half-integer pixel centres, full-width
seam wrapping and explicit handling of missing cropped coverage. A 2:1 image is
not proof of full spherical coverage. Source-camera lens parameters must not be
reapplied to a stitched equirectangular sphere.

Wall snapping needs plan/camera calibration or a valid marked vertical rectangle.
A pixel aim is not a wall-normal estimate. Preserve source-hash binding for saved
wall profiles and label uncertain geometry. Don't add automated DJI-app access,
source stitching or guessed compass headings without a concrete requested scope.

Install development dependencies with `python -m pip install -e '.[test]'` in a
project-local venv. Run `python -m pytest`; pyproject.toml requires 100% statement
and branch coverage for the package and skill wrapper. Keep that threshold and
add meaningful tests for numerical invariants, failure cases and CLI flows rather
than excluding code to achieve it. Test data should be generated locally.

Run the skill-creator quick validator when changing SKILL.md/frontmatter. Preserve
normal automatic skill discovery. Public documentation must explain calibration
assumptions and reproducible CLI examples. Generated local previews and coverage
reports belong under ignored paths. Never modify unrelated floorplan projects.
