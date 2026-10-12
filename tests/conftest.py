import numpy as np
import pytest
from PIL import Image
from pano_reframe.core import Geometry


@pytest.fixture
def sphere():
    """Encode direction as RGB, independently of the renderer's camera model."""
    w, h = 720, 360
    longitude = (np.arange(w) + .5) * (2 * np.pi / w) - np.pi
    latitude = np.pi / 2 - (np.arange(h) + .5) * (np.pi / h)
    lon, lat = np.meshgrid(longitude, latitude)
    directions = np.stack((np.sin(lon) * np.cos(lat),
                           np.cos(lon) * np.cos(lat), np.sin(lat)), axis=-1)
    image = Image.fromarray(np.rint((directions + 1) * 127.5).astype(np.uint8))
    return image, Geometry(w, h, w, h)


@pytest.fixture
def image_path(tmp_path, sphere):
    p = tmp_path / 'sphere.png'
    sphere[0].save(p)
    return p


def spherical_pixels(world, geometry, pose=None):
    rays = np.asarray(world, dtype=float)
    if pose is not None:
        rays = rays @ pose
    lon = np.arctan2(rays[:, 0], rays[:, 1])
    lat = np.arctan2(rays[:, 2], np.hypot(rays[:, 0], rays[:, 1]))
    return np.column_stack(((lon / (2 * np.pi) + .5) * geometry.full_width - geometry.left,
                            (.5 - lat / np.pi) * geometry.full_height - geometry.top))
