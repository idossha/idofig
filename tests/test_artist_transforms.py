"""Uniform artist geometry, read from the emitted SVG and independently applied to points."""
import json
import math

import pytest

from idofig import props as P
from idofig import spec as S
from test_group_moves import BY_HAND, _build, _el, _project


def manifest(project):
    return json.loads((project.panel_dir('fig-1', 'a') / 'manifest.json').read_text())


@pytest.mark.parametrize('kind', list(P.PROPS))
def test_every_kind_offers_common_finite_geometry(kind):
    assert P.validate(kind, {'dx_mm': 1000, 'dy_mm': -1000, 'rotate': 720, 'scale': 5}) == []
    assert P.validate(kind, {'scale': 0}) == ['scale must be positive']
    assert P.validate(kind, {'scale': float('inf')})
    for role in ('tick', 'ticks', 'legend-entry', 'legend-title'):
        assert P.validate(kind, {'dx_mm': 1, 'scale': 2}, role=role) == []


@pytest.mark.parametrize('selector', ['line', 'image', 'tick', 'legend-entry', 'spine', 'patch', 'axis', 'collection'])
def test_selected_artist_transform_moves_its_svg_and_manifest_only(tmp_path, monkeypatch, selector):
    project = _project(tmp_path, monkeypatch, BY_HAND.replace('    ax.set_xlabel("x")', '    ax.scatter([.25,.75], [.2,.8])\n    ax.set_xlabel("x")'))
    _build(project)
    plain = manifest(project)
    name = next(n for n, p in plain['parts'].items()
                if n.startswith('row.left') and not p.get('group') and p['bbox']
                and (p['role'] == selector if selector in ('tick', 'legend-entry') else p['kind'] == selector))
    old = plain['parts'][name]['bbox']
    S.update_style(project.panel_dir('fig-1', 'a') / 'style.json', name,
                   {'dx_mm': 3, 'dy_mm': -2, 'scale': 1.5, 'rotate': 90})
    root = _build(project)
    now = manifest(project)
    assert now['style']['invalid'] == []
    assert not now['warnings'], now['warnings']
    transform = _el(root, name).get('transform')
    assert transform and transform.startswith('matrix(')
    a, b, c, d, e, f = map(float, transform[7:-1].split())
    cx, cy = (old[0] + old[2]) / 2, (old[1] + old[3]) / 2
    assert (a * cx + c * cy + e, b * cx + d * cy + f) == pytest.approx((cx + 3 * 72 / 25.4, cy - 2 * 72 / 25.4), abs=.003)
    assert math.hypot(a, b) == pytest.approx(1.5)
    assert math.degrees(math.atan2(b, a)) == pytest.approx(90)
    pts = [(a*x+c*y+e,b*x+d*y+f) for x in old[::2] for y in old[1::2]]
    expected = [min(x for x,y in pts), min(y for x,y in pts), max(x for x,y in pts), max(y for x,y in pts)]
    assert now['parts'][name]['bbox'] == pytest.approx(expected, abs=.003)
    assert now['parts']['row.right']['bbox'] == plain['parts']['row.right']['bbox']
    # The artist's clip references stay within its transformed group, so its clipping follows it.
    if selector in ('line', 'image'):
        assert any(el.get('clip-path') for el in _el(root, name).iter())
    if selector == 'image':
        native = next(el for el in _el(root, name).iter() if el.tag.endswith('image'))
        assert native.get('transform').startswith('scale(1 -1)')
    assert now['parts'][name]['props']['scale'] == 1.5


def test_nested_axis_and_tick_transforms_follow_actual_svg_ancestry(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch, BY_HAND)
    _build(project)
    before = manifest(project)
    name = next(n for n,p in before['parts'].items() if n.startswith('row.left.xtick.') and not p.get('group') and p['bbox'])
    path = project.panel_dir('fig-1', 'a') / 'style.json'
    S.update_style(path, 'row.left.xaxis', {'rotate': 30, 'scale': 2})
    S.update_style(path, name, {'rotate': 10, 'dx_mm': 1})
    root = _build(project)
    after = manifest(project)['parts'][name]
    outer = list(map(float, _el(root, 'row.left.xaxis').get('transform')[7:-1].split()))
    own = list(map(float, _el(root, name).get('transform')[7:-1].split()))
    def apply(m, p):
        a,b,c,d,e,f=m; x,y=p
        return a*x+c*y+e,b*x+d*y+f
    box = before['parts'][name]['bbox']
    points = [apply(outer, apply(own, (x,y))) for x in box[::2] for y in box[1::2]]
    expected = [min(x for x,y in points),min(y for x,y in points),max(x for x,y in points),max(y for x,y in points)]
    assert after['bbox'] == pytest.approx(expected, abs=.003)
    assert after['effective_scale'] == 2


def test_clipped_text_uses_raw_frame_for_the_transform_pivot(tmp_path, monkeypatch):
    script = BY_HAND.replace('    ax.set_xlabel("x")', '    ax.text(.95, .5, "label extends beyond axes", clip_on=True, gid=f"{name}.clipped")\n    ax.set_xlabel("x")')
    project = _project(tmp_path, monkeypatch, script)
    _build(project)
    name = 'row.left.clipped'
    before = manifest(project)['parts'][name]
    assert before['frame'][2] > before['bbox'][2]
    S.update_style(project.panel_dir('fig-1', 'a') / 'style.json', name, {'scale': 1.4, 'rotate': 35})
    root = _build(project)
    a,b,c,d,e,f = map(float, _el(root, name).get('transform')[7:-1].split())
    frame = manifest(project)['parts'][name]['frame']
    cx,cy = (frame[0]+frame[2])/2, (frame[1]+frame[3])/2
    assert (a*cx+c*cy+e,b*cx+d*cy+f) == pytest.approx((cx,cy),abs=.001)
    assert any(el.get('clip-path') for el in _el(root,name).iter())
