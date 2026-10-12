import json
import runpy
import sys
from pathlib import Path
import pytest
from PIL import Image, PngImagePlugin
from pano_reframe.cli import entrypoint, ensure_output, heading_zero, load_profile, main, pose
from pano_reframe.core import GPANO, rotation
from conftest import spherical_pixels


def invoke(image_path, output, *args):
    return main(['view',str(image_path),'--full-sphere','-o',str(output),'--width','31','--height','23',*args])


def test_inspect_and_view(image_path,tmp_path,capsys):
    assert main(['inspect',str(image_path)]) == 0
    assert json.loads(capsys.readouterr().out)['width'] == 720
    out = tmp_path/'view.png'
    assert invoke(image_path,out) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['coverage']['valid_fraction'] == 1
    assert Image.open(out).size == (31,23)
    report = json.loads(Path(str(out)+'.json').read_text())
    assert report['view']['yaw'] == 0 and len(report['source_sha256']) == 64
    assert 'source_name' in report and 'source_path' not in report
    assert invoke(image_path,out,'--yaw','45','--overwrite') == 0
    assert json.loads(Path(str(out)+'.json').read_text())['view']['yaw'] == 45
    assert invoke(image_path,tmp_path/'view.jpg','--elevation','10') == 0
    assert Image.open(tmp_path/'view.jpg').mode == 'RGB'


def test_heading_profile_and_overrides(image_path,tmp_path):
    out = tmp_path/'heading.png'
    assert invoke(image_path,out,'--heading','90','--heading-zero','25') == 0
    report = json.loads(Path(str(out)+'.json').read_text());assert report['view']['yaw'] == 65
    profile = tmp_path/'cal.json';profile.write_text(json.dumps({'heading_zero':10,'pose_pitch':5,'pose_roll':2,'walls':{'desk':{'yaw':50}}}))
    assert invoke(image_path,out,'--calibration',str(profile),'--heading','70','--overwrite') == 0
    report = json.loads(Path(str(out)+'.json').read_text());assert report['view']['yaw'] == 60
    assert report['source_pose'] == {'pitch':5,'roll':2}
    assert invoke(image_path,out,'--calibration',str(profile),'--wall','desk','--source-pitch','1','--source-roll','-1','--overwrite') == 0
    report = json.loads(Path(str(out)+'.json').read_text());assert report['view']['yaw'] == 50
    assert report['source_pose'] == {'pitch':1,'roll':-1}


def test_xmp_pose_and_heading(tmp_path,sphere):
    im,g = sphere;p=tmp_path/'meta.png';out=tmp_path/'render.png'
    attrs = dict(FullPanoWidthPixels=720,FullPanoHeightPixels=360,
                 CroppedAreaImageWidthPixels=720,CroppedAreaImageHeightPixels=360,
                 CroppedAreaLeftPixels=0,CroppedAreaTopPixels=0,PoseHeadingDegrees=15,
                 PosePitchDegrees=2,PoseRollDegrees=-1,ProjectionType='equirectangular')
    fields=' '.join(f'g:{k}="{v}"' for k,v in attrs.items())
    info=PngImagePlugin.PngInfo();info.add_itxt('XML:com.adobe.xmp',f'<r xmlns:g="{GPANO}" {fields}/>')
    im.save(p,pnginfo=info)
    assert main(['view',str(p),'-o',str(out),'--width','15','--height','15','--heading','95']) == 0
    r=json.loads(Path(str(out)+'.json').read_text());assert r['view']['yaw']==80
    assert r['source_pose']=={'pitch':2,'roll':-1}


def test_wall_commands_and_reuse(image_path,tmp_path,sphere):
    out=tmp_path/'wall.png';profile=tmp_path/'profile.json'
    _,g=sphere
    corners=spherical_pixels([[-1,4,1],[1,4,1],[1,4,-1],[-1,4,-1]],g).ravel()
    common=['wall',str(image_path),'--full-sphere','-o',str(out),'--width','25','--height','25']
    assert main([*common,'--corners',*map(str,corners),'--save-wall',str(profile),'--name','fireplace','--heading-zero','15'])==0
    p=json.loads(profile.read_text());assert p['version']==1 and p['heading_zero']==15
    assert p['walls']['fireplace']['yaw']==pytest.approx(0)
    assert invoke(image_path,tmp_path/'reused.png','--calibration',str(profile),'--wall','fireplace')==0
    assert main([*common,'--segment','-1','4','1','4','--camera','0','0','--north-yaw','30','--calibration',str(profile),'--save-wall',str(profile),'--name','other','--overwrite'])==0
    p=json.loads(profile.read_text());assert len(p['walls'])==2 and p['walls']['other']['yaw']==30
    assert main([*common,'--segment','-1','4','1','4','--camera','0','0','--north-yaw','0','--overwrite'])==0


def test_partial_cli_output(tmp_path,sphere):
    im,g=sphere;p=tmp_path/'crop.png';out=tmp_path/'missing.png'
    info=PngImagePlugin.PngInfo()
    info.add_itxt('XML:com.adobe.xmp',f'<r xmlns:g="{GPANO}" g:FullPanoWidthPixels="720" g:FullPanoHeightPixels="360" g:CroppedAreaImageWidthPixels="360" g:CroppedAreaImageHeightPixels="180" g:CroppedAreaLeftPixels="180" g:CroppedAreaTopPixels="90"/>')
    im.crop((180,90,540,270)).save(p,pnginfo=info)
    assert main(['view',str(p),'-o',str(out),'--yaw','180','--width','11','--height','11'])==0
    r=json.loads(Path(str(out)+'.json').read_text());assert r['coverage']['valid_fraction']==0
    assert any('lack source coverage' in x for x in r['warnings'])
    assert Image.open(out).getpixel((5,5))==(0,0,0,0)


@pytest.mark.parametrize('payload',[[],{'version':2},{'walls':[]},{'walls':{'x':3}},{'walls':{'x':{}}},{'pose_pitch':'nan'},{'walls':{'x':{'yaw':'nan'}}}])
def test_bad_profiles(tmp_path,payload):
    p=tmp_path/'bad.json';p.write_text(json.dumps(payload))
    with pytest.raises(ValueError):load_profile(p)


def test_helpers_rejections(tmp_path,image_path):
    from argparse import Namespace
    with pytest.raises(ValueError):pose({'gpano':{}},Namespace(source_pitch=91,source_roll=0),{})
    with pytest.raises(ValueError):pose({'gpano':{}},Namespace(source_pitch=0,source_roll=181),{})
    with pytest.raises(ValueError):heading_zero({'gpano':{}},Namespace(heading_zero=None),{})
    with pytest.raises(ValueError):ensure_output(image_path,image_path,True)
    with pytest.raises(ValueError):ensure_output(image_path,tmp_path/'other',False)
    with pytest.raises(ValueError):load_profile(image_path)


@pytest.mark.parametrize('args,match',[
    (['--heading','90'],'No compass'),
    (['--wall','missing'],'Unknown named wall'),
    (['--hfov','180'],'FoV'),
    (['--yaw','nan'],'finite')])
def test_cli_validation(image_path,tmp_path,capsys,args,match):
    assert invoke(image_path,tmp_path/'out.png',*args)==2
    assert match in capsys.readouterr().err
    assert not (tmp_path/'out.png').exists()


def test_cli_output_conflicts(image_path,tmp_path,capsys):
    assert invoke(image_path,tmp_path/'wrong.gif')==2
    assert 'PNG or JPEG' in capsys.readouterr().err
    assert main(['view',str(image_path),'-o',str(tmp_path/'new.png')])==2
    assert 'Missing' in capsys.readouterr().err
    profile=tmp_path/'mismatch.json';profile.write_text('{"source_sha256":"wrong"}')
    assert invoke(image_path,tmp_path/'new.png','--calibration',str(profile))==2
    common=['wall',str(image_path),'--full-sphere','-o',str(tmp_path/'wall.png'),'--segment','-1','4','1','4']
    assert main(common)==2
    assert main([*common,'--camera','0','0'])==2
    assert main([*common,'--camera','0','0','--north-yaw','0','--save-wall',str(tmp_path/'wall.png')])==2
    assert main([*common,'--camera','0','0','--north-yaw','0','--save-wall',str(tmp_path/'wall.png.json')])==2
    assert main(['inspect',str(tmp_path/'not-found.jpg')])==2
    assert 'No such file' in capsys.readouterr().err


def test_entrypoints(image_path,monkeypatch,capsys):
    monkeypatch.setattr(sys,'argv',['pano-reframe','inspect',str(image_path)])
    with pytest.raises(SystemExit) as e: entrypoint()
    assert e.value.code==0
    with pytest.raises(SystemExit) as e: runpy.run_module('pano_reframe',run_name='__main__')
    assert e.value.code==0
    with pytest.raises(SystemExit) as e: runpy.run_path(str(Path(__file__).parents[1]/'scripts/pano_reframe.py'),run_name='__main__')
    assert e.value.code==0
    with pytest.raises(SystemExit) as e: main(['view',str(image_path),'-o','out.png','--yaw','0','--heading','90'])
    assert e.value.code==2


def test_point_aiming(image_path,tmp_path):
    out=tmp_path/'point.png'
    assert invoke(image_path,out,'--point','540','120')==0
    r=json.loads(Path(str(out)+'.json').read_text())
    assert r['view']['yaw']==pytest.approx(90)
    assert r['view']['pitch']==pytest.approx(30)
    assert invoke(image_path,out,'--point','540','120','--elevation','0','--overwrite')==0
    r=json.loads(Path(str(out)+'.json').read_text());assert r['view']['pitch']==0
