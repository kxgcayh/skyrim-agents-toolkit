"""tools/tri-topology.py against synthetic SSE NIFs and FaceGen .tri files built byte by byte here."""
import hashlib
import importlib.util
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("tri_topology", ROOT / "tools" / "tri-topology.py")
tt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tt)

QUAD = [(0, 1, 2), (0, 2, 3)]                                    # 4 vertices, 2 triangles


def tri_bytes(nverts, tris, added=0, magic=b"FRTRI003"):
    head = magic + struct.pack("<3i", nverts, len(tris), 0) + bytes(24) + struct.pack("<i", added) + bytes(16)
    return head + bytes(12 * (nverts + added)) + b"".join(struct.pack("<3i", *t) for t in tris)


def partition(nverts, tris, vsize=12):
    body = struct.pack("<IIIQ", 1, nverts * vsize, vsize, 0) + bytes(nverts * vsize)
    body += struct.pack("<5H", nverts, len(tris), 1, 0, 1) + struct.pack("<H", 0)     # one bone
    body += b"\x01" + struct.pack("<%dH" % nverts, *range(nverts))                     # vertex map
    body += b"\x01" + struct.pack("<%df" % nverts, *([1.0] * nverts))                  # weights
    body += b"\x01" + b"".join(struct.pack("<3H", *t) for t in tris)                    # faces
    body += b"\x01" + bytes(nverts)                                                     # bone indices
    body += struct.pack("<H", 0) + struct.pack("<Q", 0)                                 # LOD level, vertex desc
    return body + b"".join(struct.pack("<3H", *t) for t in tris)                        # triangles copy


def shape_block(name_index, skin_ref):
    b = struct.pack("<iIi", name_index, 0, -1) + struct.pack("<I", 14) + bytes(12 + 36) + struct.pack("<f", 1.0)
    b += struct.pack("<i", -1) + bytes(16) + struct.pack("<i", skin_ref)
    return b + struct.pack("<ii", -1, -1) + bytes(8 + 4 + 2 + 4)                         # shader, alpha, desc, counts


def nif_bytes(nverts=4, tris=QUAD, bsver=100, skinned=True, name="Head", trailing=b""):
    blocks = [("BSTriShape", shape_block(0, 1 if skinned else -1))]
    if skinned:
        blocks += [("BSDismemberSkinInstance", struct.pack("<iii", -1, 2, -1) + bytes(8)),
                   ("NiSkinPartition", partition(nverts, tris))]
    types = sorted({t for t, _ in blocks})
    h = b"Gamebryo File Format, Version 20.2.0.7\n" + struct.pack("<I", 0x14020007) + b"\x01"
    h += struct.pack("<III", 12, len(blocks), bsver) + b"\x00\x00\x00"
    h += struct.pack("<H", len(types)) + b"".join(struct.pack("<I", len(t)) + t.encode() for t in types)
    h += b"".join(struct.pack("<H", types.index(t)) for t, _ in blocks)
    h += b"".join(struct.pack("<I", len(b)) for _, b in blocks)
    h += struct.pack("<II", 1, len(name)) + struct.pack("<I", len(name)) + name.encode() + struct.pack("<I", 0)
    return h + b"".join(b for _, b in blocks) + struct.pack("<Ii", 1, 0) + trailing


def run(tmp_path, tri, nifs, *extra):
    t = tmp_path / "x.tri"
    t.write_bytes(tri)
    paths = []
    for k, n in enumerate(nifs):
        p = tmp_path / ("m%d.nif" % k)
        p.write_bytes(n)
        paths.append(str(p))
    return tt.main([str(t), *paths, *extra])


def test_the_same_mesh_matches_and_exits_0(tmp_path, capsys):
    assert run(tmp_path, tri_bytes(4, QUAD), [nif_bytes()]) == 0
    assert "[Head]: MATCH" in capsys.readouterr().out


def test_winding_order_and_duplicate_triangles_do_not_matter(tmp_path):
    assert run(tmp_path, tri_bytes(4, [(2, 0, 1), (3, 2, 0), (3, 2, 0)]), [nif_bytes()]) == 0


def test_a_vertex_count_difference_is_a_finding(tmp_path, capsys):
    assert run(tmp_path, tri_bytes(5, QUAD), [nif_bytes()]) == 1
    assert "VERTEX-COUNT" in capsys.readouterr().out


def test_a_different_triangle_with_the_same_count_is_a_finding_with_its_share(tmp_path):
    t = tmp_path / "x.tri"
    t.write_bytes(tri_bytes(4, [(0, 1, 2), (1, 2, 3)]))
    n = tmp_path / "m.nif"
    n.write_bytes(nif_bytes())
    [mesh] = tt.check(t, [n])["meshes"]
    [s] = mesh["shapes"]
    assert s["status"] == "triangles-differ" and s["triangles"]["differ_percent"] == 50.0


def test_added_vertices_are_skipped_to_reach_the_triangles(tmp_path):
    assert run(tmp_path, tri_bytes(4, QUAD, added=3), [nif_bytes()]) == 0


def test_a_bodyslide_tri_is_named_and_never_compared(tmp_path, capsys):
    assert run(tmp_path, b"PIRT" + bytes(60), [nif_bytes()]) == 2
    assert "BodySlide" in capsys.readouterr().err


def test_an_le_mesh_is_could_not_check_never_a_match(tmp_path, capsys):
    assert run(tmp_path, tri_bytes(4, QUAD), [nif_bytes(bsver=83)]) == 2
    assert "BSVersion 83" in capsys.readouterr().out


def test_an_unskinned_shape_is_unsupported_and_alone_exits_2(tmp_path, capsys):
    assert run(tmp_path, tri_bytes(4, QUAD), [nif_bytes(skinned=False)]) == 2
    assert "UNSUPPORTED" in capsys.readouterr().out


def test_a_file_whose_blocks_do_not_fill_it_is_could_not_check(tmp_path):
    assert run(tmp_path, tri_bytes(4, QUAD), [nif_bytes(trailing=b"junk")]) == 2


def test_a_mismatch_in_one_mesh_outweighs_a_match_in_another(tmp_path):
    assert run(tmp_path, tri_bytes(4, QUAD), [nif_bytes(), nif_bytes(nverts=5)]) == 1


def test_shape_filter_checks_only_the_named_shape(tmp_path, capsys):
    assert run(tmp_path, tri_bytes(4, QUAD), [nif_bytes()], "--shape", "Other") == 2
    assert "no BSDynamicTriShape/BSTriShape shape named Other" in capsys.readouterr().out


def test_the_check_writes_nothing(tmp_path):
    run(tmp_path, tri_bytes(4, QUAD), [nif_bytes()])
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.iterdir()}
    run(tmp_path, tri_bytes(4, QUAD), [nif_bytes()])
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.iterdir()} == before


@pytest.mark.parametrize("cut", [10, 60, 200])
def test_a_truncated_nif_is_could_not_check(tmp_path, cut):
    assert run(tmp_path, tri_bytes(4, QUAD), [nif_bytes()[:cut]]) == 2
