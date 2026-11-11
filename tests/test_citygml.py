"""Normalising LoD2: geometry comes through, addresses and closure surfaces do not."""

import numpy as np

from isometric_bonn import citygml

GML = """<?xml version="1.0" encoding="UTF-8"?>
<core:CityModel xmlns:core="http://www.opengis.net/citygml/1.0"
  xmlns:bldg="http://www.opengis.net/citygml/building/1.0" xmlns:gml="http://www.opengis.net/gml"
  xmlns:xal="urn:oasis:names:tc:ciq:xsdschema:xAL:2.0">
 <core:cityObjectMember>
  <bldg:Building gml:id="DENW00TEST000001">
   <bldg:function>31001_1000</bldg:function>
   <bldg:roofType>1000</bldg:roofType>
   <bldg:measuredHeight uom="urn:adv:uom:m">10</bldg:measuredHeight>
   <bldg:boundedBy><bldg:RoofSurface><bldg:lod2MultiSurface><gml:MultiSurface><gml:surfaceMember>
    <gml:Polygon><gml:exterior><gml:LinearRing><gml:posList srsDimension="3">
     365000 5620000 70 365010 5620000 70 365010 5620010 70 365000 5620010 70 365000 5620000 70
    </gml:posList></gml:LinearRing></gml:exterior>
    <gml:interior><gml:LinearRing><gml:posList srsDimension="3">
     365004 5620004 70 365004 5620006 70 365006 5620006 70 365006 5620004 70 365004 5620004 70
    </gml:posList></gml:LinearRing></gml:interior></gml:Polygon>
   </gml:surfaceMember></gml:MultiSurface></bldg:lod2MultiSurface></bldg:RoofSurface></bldg:boundedBy>
   <bldg:boundedBy><bldg:WallSurface><bldg:lod2MultiSurface><gml:MultiSurface><gml:surfaceMember>
    <gml:Polygon><gml:exterior><gml:LinearRing><gml:posList srsDimension="3">
     365000 5620000 60 365010 5620000 60 365010 5620000 70 365000 5620000 70 365000 5620000 60
    </gml:posList></gml:LinearRing></gml:exterior></gml:Polygon>
   </gml:surfaceMember></gml:MultiSurface></bldg:lod2MultiSurface></bldg:WallSurface></bldg:boundedBy>
   <bldg:boundedBy><bldg:ClosureSurface><bldg:lod2MultiSurface><gml:MultiSurface><gml:surfaceMember>
    <gml:Polygon><gml:exterior><gml:LinearRing><gml:posList srsDimension="3">
     365000 5620010 60 365010 5620010 60 365010 5620010 70 365000 5620010 70 365000 5620010 60
    </gml:posList></gml:LinearRing></gml:exterior></gml:Polygon>
   </gml:surfaceMember></gml:MultiSurface></bldg:lod2MultiSurface></bldg:ClosureSurface></bldg:boundedBy>
   <bldg:address><core:Address><core:xalAddress><xal:AddressDetails><xal:Country>
    <xal:CountryName>Germany</xal:CountryName><xal:Locality><xal:LocalityName>Bonn</xal:LocalityName>
    <xal:Thoroughfare><xal:ThoroughfareName>Musterstrasse</xal:ThoroughfareName>
    <xal:ThoroughfareNumber>42</xal:ThoroughfareNumber></xal:Thoroughfare></xal:Locality>
   </xal:Country></xal:AddressDetails></core:xalAddress></core:Address></bldg:address>
  </bldg:Building>
 </core:cityObjectMember>
</core:CityModel>
"""


def _area(t):
    return 0.5 * np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum()


def test_geometry_and_no_addresses(tmp_path):
    path = tmp_path / "LoD2_32_365_5620_1_NW.gml"
    path.write_text(GML)
    r = citygml.normalise(path)
    roof = r["tri"][r["tri_kind"] == citygml.KIND_ROOF]
    wall = r["tri"][r["tri_kind"] == citygml.KIND_WALL]
    assert abs(_area(roof) - (100 - 4)) < 1e-6  # the courtyard hole is respected
    assert abs(_area(wall) - 100) < 1e-6
    assert len(r["tri"]) == len(roof) + len(wall)  # the closure surface is dropped
    assert r["bld_function"].tolist() == ["31001_1000"]
    text = " ".join(str(v) for k in r for v in np.ravel(r[k]) if r[k].dtype.kind in "US")
    for word in ("Musterstrasse", "42", "Bonn", "Germany"):
        assert word not in text.split(), f"{word!r} leaked into normalised data"


def test_tile_without_buildings(tmp_path):
    path = tmp_path / "LoD2_32_366_5615_1_NW.gml"
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<core:CityModel xmlns:core="http://www.opengis.net/citygml/1.0"/>\n')
    r = citygml.normalise(path)
    assert r["tri"].shape == (0, 3, 3) and len(r["bld_gmlid"]) == 0
