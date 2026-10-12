import math
import numpy as np
import pytest
from PIL import Image, PngImagePlugin
from pano_reframe.core import (GPANO, Geometry, finite, geometry_from, inspect_image,
                               parse_xmp, render, rotation, snap_plan, snap_rectangle, source_hash, unit)
from conftest import spherical_pixels


def metadata(w=400, h=200, **updates):
    p = dict(FullPanoWidthPixels='400', FullPanoHeightPixels='200',
             CroppedAreaImageWidthPixels='400', CroppedAreaImageHeightPixels='200',
             CroppedAreaLeftPixels='0', CroppedAreaTopPixels='0')
    p.update(updates)
    return dict(width=w, height=h, exif_orientation=1, gpano=p)


def test_xmp_and_metadata(tmp_path):
    xml = f'<root xmlns:p="{GPANO}" p:PoseHeadingDegrees="42" unrelated="ignore"><p:ProjectionType>equirectangular</p:ProjectionType><p:Empty/><unrelated>ignore</unrelated></root>'
    assert parse_xmp(xml) == {'PoseHeadingDegrees': '42', 'ProjectionType': 'equirectangular'}
    assert parse_xmp(xml.encode()) == parse_xmp(xml)
    p = tmp_path / 'meta.png'; info = PngImagePlugin.PngInfo(); info.add_itxt('XML:com.adobe.xmp', xml)
    Image.new('RGB', (400, 200)).save(p, pnginfo=info)
    assert inspect_image(p)['gpano']['PoseHeadingDegrees'] == '42'
    info = PngImagePlugin.PngInfo(); info.add_itxt('XML:com.adobe.xmp', '<broken')
    Image.new('RGB', (400, 200)).save(p, pnginfo=info)
    assert inspect_image(p)['warnings'][0].startswith('Unreadable XMP')
    exif = Image.Exif(); exif[271] = 'DJI'; exif[272] = 'Test'; exif[274] = 6
    Image.new('RGB', (400, 200)).save(p, exif=exif)
    result = inspect_image(p)
    assert result['camera'] == {'make': 'DJI', 'model': 'Test'}
    assert any('orientation' in x for x in result['warnings'])
    with pytest.raises(ValueError, match='orientation'):
        geometry_from(result, True)
    for xml in [b'<!DOCTYPE root><root/>', b'<!ENTITY thing "secret"><root/>']:
        with pytest.raises(ValueError, match='unsupported'):
            parse_xmp(xml)


def test_jpeg_app1_xmp(tmp_path):
    p = tmp_path / 'meta.jpg'; Image.new('RGB', (400, 200)).save(p)
    payload = b'http://ns.adobe.com/xap/1.0/\x00' + f'<r xmlns:g="{GPANO}" g:PosePitchDegrees="12"/>'.encode()
    data = p.read_bytes(); p.write_bytes(data[:2] + b'\xff\xe1' + (len(payload)+2).to_bytes(2, 'big') + payload + data[2:])
    assert inspect_image(p)['gpano'] == {'PosePitchDegrees': '12'}


def test_geometry_and_scaling():
    g = geometry_from(metadata())
    assert g.wraps and g.basis == 'metadata'
    crop = geometry_from(metadata(100, 50, CroppedAreaImageWidthPixels='200', CroppedAreaImageHeightPixels='100', CroppedAreaLeftPixels='100', CroppedAreaTopPixels='50'))
    assert crop == Geometry(100, 50, 200, 100, 50, 25)
    assert not crop.wraps
    assert geometry_from(dict(width=400,height=200,exif_orientation=1,gpano={}), True).basis.startswith('user')
    np.testing.assert_allclose(g.rays([[200,100],[300,100],[200,0],[0,100]]), [[0,1,0],[1,0,0],[0,0,1],[0,-1,0]], atol=1e-12)
    cases = [metadata(400,201), metadata(ProjectionType='cylindrical'),
             metadata(FullPanoWidthPixels='0'), metadata(CroppedAreaLeftPixels='-1'),
             metadata(FullPanoHeightPixels='300'), metadata(CroppedAreaLeftPixels='1'),
             metadata(CroppedAreaTopPixels='1'), metadata(FullPanoWidthPixels='nan')]
    for m in cases:
        with pytest.raises(ValueError): geometry_from(m)
    with pytest.raises(ValueError, match='2:1'): geometry_from(dict(width=400,height=100,exif_orientation=1,gpano={}), True)
    with pytest.raises(ValueError, match='Missing'): geometry_from(dict(width=400,height=200,exif_orientation=1,gpano={}))
    for pts in [[[1,2,3]], [[math.nan,1]], [[-1,0]], [[401,1]], [[1,201]]]:
        with pytest.raises(ValueError): g.rays(pts)
    with pytest.raises(ValueError): finite(math.inf,'test')
    with pytest.raises(ValueError): unit(np.zeros(3))


@pytest.mark.parametrize('yaw,pitch,expected', [(0,0,[0,1,0]),(90,0,[1,0,0]),(180,0,[0,-1,0]),(270,0,[-1,0,0]),(0,90,[0,0,1]),(0,-90,[0,0,-1])])
def test_rotation_and_view_axes(sphere,yaw,pitch,expected):
    im,g = sphere
    np.testing.assert_allclose(rotation(yaw,pitch) @ [0,1,0], expected, atol=1e-12)
    view,stats = render(im,g,yaw,pitch,width=1,height=1)
    np.testing.assert_allclose(np.asarray(view)[0,0,:3], (np.array(expected)+1)*127.5, atol=1)
    assert stats['valid_fraction'] == 1
    assert np.asarray(view)[0,0,3] == 255


def test_rotations_roll_order():
    np.testing.assert_allclose(rotation(0,0,90) @ [1,0,0], [0,0,-1], atol=1e-12)
    r = rotation(43,12,-27)
    np.testing.assert_allclose(r.T @ r,np.eye(3),atol=1e-12)
    assert np.linalg.det(r) == pytest.approx(1)


def test_pixel_rays_fov_seams_and_chunks(sphere):
    im,g = sphere
    original = np.asarray(im).copy()
    view,stats = render(im,g,hfov=90,width=5,height=5)
    # Independent pinhole rays at the image corners, normalized into RGB.
    rays = np.array([[-.8,1,.8],[.8,1,-.8]])
    rays /= np.linalg.norm(rays,axis=1)[:,None]
    np.testing.assert_allclose(np.asarray(view)[[0,4],[0,4],:3], (rays+1)*127.5, atol=1)
    assert stats['vertical_fov'] == pytest.approx(90)
    a,_ = render(im,g,179.9,width=33,height=257)
    b,_ = render(im,g,-180.1,width=33,height=257)
    np.testing.assert_array_equal(a,b)
    assert np.asarray(a)[...,3].min() == 255
    assert np.max(np.abs(np.diff(np.asarray(a)[128,:,:3].astype(int),axis=0))) < 8
    np.testing.assert_array_equal(original,np.asarray(im))
    posed,_ = render(im,g,yaw=35,pitch=21,roll=-8,pose_pitch=21,pose_roll=-8,width=1,height=1)
    # Pose inverse is ordered; separately verify same pose at yaw zero cancels exactly.
    posed,_ = render(im,g,pitch=21,roll=-8,pose_pitch=21,pose_roll=-8,width=1,height=1)
    np.testing.assert_allclose(np.asarray(posed)[0,0,:3],[127.5,255,127.5],atol=1)


def test_partial_coverage(sphere):
    im,g = sphere
    crop = im.crop((180,90,540,270)); cg = Geometry(360,180,720,360,180,90)
    view,stats = render(crop,cg,width=51,height=51)
    assert stats['valid_fraction'] == 1
    missing,stats = render(crop,cg,yaw=180,width=51,height=51)
    assert stats['valid_fraction'] == 0
    assert np.asarray(missing).max() == 0
    mixed,stats = render(crop,cg,yaw=90,width=51,height=51)
    assert 0 < stats['valid_fraction'] < 1
    # Full width cropped vertically still wraps across the longitude seam.
    strip = im.crop((0,90,720,270)); sg = Geometry(720,180,720,360,0,90)
    _,stats = render(strip,sg,yaw=180,pitch=70,hfov=20,width=33,height=33)
    assert stats['valid_fraction'] == 0


@pytest.mark.parametrize('kwargs',[dict(hfov=0),dict(hfov=175),dict(pitch=91),dict(width=0),dict(height=-1),dict(width=10000,height=10000),dict(yaw=float('nan'))])
def test_render_rejects_bad_parameters(sphere,kwargs):
    with pytest.raises(ValueError): render(*sphere,**kwargs)


def test_dimension_mismatch(sphere):
    with pytest.raises(ValueError,match='disagree'): render(sphere[0],Geometry(2,1,2,1))


@pytest.mark.parametrize('yaw', [0,27,90,180,250])
@pytest.mark.parametrize('pose', [(0,0),(14,-7)])
def test_wall_geometry_ground_truth(sphere,yaw,pose):
    _,g = sphere
    # An actual 2x1.5 rectangle on a vertical wall 4 units away, off-centre camera.
    world = np.array([[-1,4,1.25],[1,4,1.25],[1,4,-.25],[-1,4,-.25]]) @ rotation(yaw).T
    pp,pr = pose
    pixels = spherical_pixels(world,g,rotation(0,pp,pr))
    result = snap_rectangle(g,pixels,pp,pr)
    delta = (result['yaw']-yaw+180)%360-180
    assert delta == pytest.approx(0,abs=1e-10)
    assert result['pitch'] == 0
    assert result['vanishing_elevation_error_degrees'] < 1e-8
    # Floorplan normal matches the same independent expected yaw.
    n = rotation(yaw) @ [0,1,0]; tangent = rotation(yaw) @ [1,0,0]
    a,b = n[:2]*4-tangent[:2],n[:2]*4+tangent[:2]
    result = snap_plan([*a,*b],[0,0],0)
    assert (result['yaw']-yaw+180)%360-180 == pytest.approx(0,abs=1e-10)


def test_wall_failures(sphere):
    _,g = sphere
    for segment,camera in [([0,0,0,0],[1,1]),([0,0,1,0],[0,0]),([0,0,math.nan,1],[1,1])]:
        with pytest.raises(ValueError): snap_plan(segment,camera,0)
    with pytest.raises(ValueError): snap_rectangle(g,[[1,1]]*4)
    # A tilted rectangle violates the horizontal/vertical wall assumptions.
    world = np.array([[-1,4,1],[1,4,1],[1,4,-1],[-1,4,-1]])
    tilted = world @ rotation(0,0,35).T
    with pytest.raises(ValueError,match='horizontal'): snap_rectangle(g,spherical_pixels(tilted,g))
    slanted = world.copy().astype(float); slanted[2,0]+=1; slanted[3,0]+=1
    with pytest.raises(ValueError,match='side edges'): snap_rectangle(g,spherical_pixels(slanted,g))
    opposite = [[-1,4,1],[1,4,1],[-1,-4,1],[1,-4,1]]
    with pytest.raises(ValueError,match='ambiguous'): snap_rectangle(g,spherical_pixels(opposite,g))


def test_hash(image_path):
    assert len(source_hash(image_path)) == 64


def test_wall_normal_sign_and_segment_order(sphere):
    _,g=sphere
    world=[[-1,4,1],[1,4,1],[1,4,-1],[-1,4,-1]]
    corners=spherical_pixels(world,g)
    # Reversing top/bottom edge assignment still selects the visible normal,
    # rather than returning the antipodal/back-facing direction.
    assert snap_rectangle(g,corners[[3,2,1,0]])['yaw']==pytest.approx(0)
    assert snap_plan([1,4,-1,4],[0,0],0)['yaw']==pytest.approx(0)
