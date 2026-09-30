"""
Pictures uploaded through the editor: saved in an assets folder beside the scene file, under a
safe name, with a path the document can use; refused when they aren't pictures, are too big,
or would land anywhere else.
"""
from __future__ import annotations

import os
import struct
import sys
import zlib

import pytest

from manim_verbose.editor.assets import AssetError, parse_upload, safe_stem, save_asset, sniff
from manim_verbose.editor.limits import Limits


def png(width: int = 2, height: int = 2, shade: int = 0) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes([shade, shade, shade]) * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\x00" * 32 + b"\xff\xd9"
GIF = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
WEBP = b"RIFF\x1a\x00\x00\x00WEBPVP8L\x0d\x00\x00\x00/\x00\x00\x00\x10\x07\x10\x11\x11\x88\x88\xfe\x07\x00"
SVG = b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><circle r="4" cx="5" cy="5"/></svg>'
BARE_SVG = b'<svg viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'


def upload(client, data: bytes, filename: str = "cat.png", content_type: str = "image/png", field: str = "file"):
    return client.post("/api/assets", files={field: (filename, data, content_type)})


# Accepted

def test_a_picture_is_saved_beside_the_scene_file(client, scene_file):
    data = png()
    r = upload(client, data)
    assert r.status_code == 200, r.text
    assert r.json() == {"path": "assets/cat.png", "kind": "png"}
    assert (scene_file.parent / "assets" / "cat.png").read_bytes() == data


@pytest.mark.parametrize("data, kind", [(png(), "png"), (JPEG, "jpg"), (GIF, "gif"), (WEBP, "webp"), (SVG, "svg"), (BARE_SVG, "svg")])
def test_every_kind_of_picture_is_accepted(client, scene_file, data, kind):
    r = upload(client, data, filename="picture.bin", content_type="application/octet-stream")
    assert r.status_code == 200, r.text
    assert r.json()["path"] == f"assets/picture.{kind}"
    assert (scene_file.parent / "assets" / f"picture.{kind}").read_bytes() == data


def test_the_extension_follows_the_content_not_the_name(client, scene_file):
    assert upload(client, png(), filename="photo.jpg").json()["path"] == "assets/photo.png"
    assert upload(client, JPEG, filename="drawing.svg").json()["path"] == "assets/drawing.jpg"


def test_the_same_picture_twice_keeps_its_name_and_another_gets_a_new_one(client, scene_file):
    first = upload(client, png(shade=0)).json()["path"]
    again = upload(client, png(shade=0)).json()["path"]
    other = upload(client, png(shade=200)).json()["path"]
    third = upload(client, png(shade=100)).json()["path"]
    assert (first, again, other, third) == ("assets/cat.png", "assets/cat.png", "assets/cat-2.png", "assets/cat-3.png")
    assert len(list((scene_file.parent / "assets").iterdir())) == 3


def test_a_saved_picture_can_be_used_in_the_document(client, sample):
    path = upload(client, png()).json()["path"]
    sample["scenes"][0]["objects"].append({"id": "pic", "type": "image", "path": path})
    sample["scenes"][0]["steps"].append({"do": "show", "target": "pic"})
    problems = client.post("/api/validate", json={"document": sample}).json()["problems"]
    assert [p for p in problems if p["item_id"] == "pic"] == []


def test_a_bigger_upload_than_a_document_is_allowed(make_client, scene_file):
    client = make_client(scene_file, limits=Limits(max_body_bytes=2000, max_asset_bytes=50_000, worker_start_timeout=30))
    data = png(40, 40, shade=7) + b"\x00" * 6000  # trailing bytes after IEND are harmless
    r = upload(client, data)
    assert r.status_code == 200, r.text
    # Documents still have their own limit
    big = {"document": {"scenes": [{"id": "s", "title": "x" * 5000}]}}
    assert client.post("/api/validate", json=big).status_code == 413


# Names

@pytest.mark.parametrize("filename, stem", [
    ("../../evil.png", "evil"),
    ("..\\..\\evil.png", "evil"),
    ("/etc/passwd", "passwd"),
    ("C:\\Windows\\System32\\cat.png", "cat"),
    ("%2e%2e%2fevil.png", "2e-2e-2fevil"),
    ("..", "picture"),
    (".", "picture"),
    ("", "picture"),
    (".hidden", "hidden"),
    ("a b\tc.png", "a-b-c"),
    ("café 🐱.png", "caf"),
    ("x" * 300 + ".png", "x" * 48),
    ("report.final.png", "report-final"),
    ("-_-.png", "picture"),
    ("con.png", "con"),
])
def test_names_are_made_safe(filename, stem):
    assert safe_stem(filename) == stem


@pytest.mark.parametrize("filename", ["../../evil.png", "..\\..\\evil.png", "/tmp/evil.png", "../assets/../../evil.png", "..", "sub/dir/evil.png"])
def test_nothing_is_written_outside_the_assets_folder(client, scene_file, tmp_path, filename):
    before = {p for p in tmp_path.rglob("*")}
    r = upload(client, png(), filename=filename)
    assert r.status_code == 200, r.text
    path = r.json()["path"]
    assert path.startswith("assets/") and path.count("/") == 1 and ".." not in path
    written = {p for p in tmp_path.rglob("*")} - before
    assets = scene_file.parent / "assets"
    assert written and all(p == assets or p.parent == assets for p in written), written


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_an_assets_folder_leading_elsewhere_is_refused(client, scene_file, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.symlink(elsewhere, scene_file.parent / "assets")
    r = upload(client, png())
    assert r.status_code == 500
    assert "assets" in r.json()["problems"][0]["message"]
    assert list(elsewhere.iterdir()) == []


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_a_symlinked_file_of_the_same_name_is_not_reused(client, scene_file, tmp_path):
    secret = tmp_path / "secret.png"
    secret.write_bytes(png())
    (scene_file.parent / "assets").mkdir()
    os.symlink(secret, scene_file.parent / "assets" / "cat.png")
    r = upload(client, png())
    assert r.json()["path"] == "assets/cat-2.png"


# Refused

NOT_PICTURES = [
    b"just some text",
    b"<html><body>hello</body></html>",
    b"%PDF-1.4\n",
    b"MZ\x90\x00\x03\x00\x00\x00",
    b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "aaaa">]><svg xmlns="http://www.w3.org/2000/svg">&a;</svg>',
    b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd"><svg/>',
    b"<svg><unclosed></svg>",
    b"<notsvg></notsvg>",
    b"GIF",
    b"RIFF\x00\x00\x00\x00WAVEfmt ",
    b"\xff\xfe<\x00s\x00v\x00g\x00",
]


@pytest.mark.parametrize("data", NOT_PICTURES)
def test_what_isnt_a_picture_is_refused(client, scene_file, data):
    r = upload(client, data, filename="sneaky.png")
    assert r.status_code == 415, r.text
    [problem] = r.json()["problems"]
    assert "PNG, JPEG, GIF, WebP or SVG" in problem["message"]
    assert problem["loc"] == ["file"]
    assert not (scene_file.parent / "assets" / "sneaky.png").exists()


def test_too_big_a_picture_is_refused(make_client, scene_file):
    client = make_client(scene_file, limits=Limits(max_asset_bytes=2000, worker_start_timeout=30))
    r = upload(client, png() + b"\x00" * 3000)
    assert r.status_code == 413
    assert "at most" in r.json()["problems"][0]["message"]
    r = upload(client, png() + b"\x00" * 200_000)
    assert r.status_code == 413, "refused by the body limit before it is read"
    assert not (scene_file.parent / "assets").exists() or list((scene_file.parent / "assets").iterdir()) == []


def test_an_empty_file_is_refused(client):
    r = upload(client, b"")
    assert r.status_code == 422
    assert "empty" in r.json()["problems"][0]["message"]


def test_an_upload_with_no_file_is_refused(client):
    r = client.post("/api/assets", data={"note": "no file here"}, files={"other": ("", b"", "text/plain")})
    assert r.status_code == 422
    r = client.post("/api/assets", json={"path": "cat.png"})
    assert r.status_code == 415
    r = client.post("/api/assets", content=b"--nothing--", headers={"Content-Type": "multipart/form-data; boundary=zzz"})
    assert r.status_code == 422


def test_the_part_called_file_is_the_one_taken(client, scene_file):
    r = client.post("/api/assets", files=[("other", ("a.png", png(shade=1), "image/png")), ("file", ("b.png", png(shade=2), "image/png"))])
    assert r.json()["path"] == "assets/b.png"


def test_only_post_is_answered(client):
    assert client.get("/api/assets").status_code in (404, 405)


# The pieces on their own

def test_sniffing():
    assert [sniff(d) for d in (png(), JPEG, GIF, WEBP, SVG, BARE_SVG)] == ["png", "jpg", "gif", "webp", "svg", "svg"]
    assert sniff(b"\xef\xbb\xbf" + BARE_SVG) == "svg", "a byte order mark is fine"
    assert all(sniff(d) is None for d in NOT_PICTURES)


def test_save_asset_directly(tmp_path):
    assert save_asset(tmp_path, "x.png", png(), 10_000) == "assets/x.png"
    with pytest.raises(AssetError) as err:
        save_asset(tmp_path, "y.png", png(), 10)
    assert err.value.status == 413


def test_parse_upload_reads_names_with_quotes_and_unicode():
    body = (
        b"--B\r\nContent-Disposition: form-data; name=\"file\"; filename=\"my \\\"cat\\\".png\"\r\n"
        b"Content-Type: image/png\r\n\r\n" + png() + b"\r\n--B--\r\n"
    )
    upload = parse_upload(body, "multipart/form-data; boundary=B")
    assert upload.data == png()
    assert "cat" in upload.filename
