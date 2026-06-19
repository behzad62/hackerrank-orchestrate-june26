import base64
import csv

from data import load_claim_rows, load_evidence_requirements, load_user_history, write_output_rows
from images import (
    detect_mime_type,
    extract_image_id,
    prepare_image,
    prepare_images,
    resolve_image_path,
)
from schemas import OUTPUT_COLUMNS


def test_load_claim_rows_preserves_strings(tmp_path):
    path = tmp_path / "claims.csv"
    path.write_text(
        "user_id,image_paths,user_claim,claim_object\n"
        "u1,images/test/case_001/img_1.jpg,hello,car\n",
        encoding="utf-8",
    )
    rows = load_claim_rows(path)
    assert rows == [
        {
            "user_id": "u1",
            "image_paths": "images/test/case_001/img_1.jpg",
            "user_claim": "hello",
            "claim_object": "car",
        }
    ]


def test_load_claim_rows_handles_utf8_sig(tmp_path):
    path = tmp_path / "claims.csv"
    path.write_text(
        "\ufeffuser_id,image_paths,user_claim,claim_object\n"
        "u1,img.jpg,claim with unicode cafe,car\n",
        encoding="utf-8",
    )
    rows = load_claim_rows(path)
    assert rows[0]["user_id"] == "u1"
    assert "user_id" in rows[0]


def test_load_user_history_by_user_id(tmp_path):
    path = tmp_path / "user_history.csv"
    path.write_text(
        "user_id,past_claim_count,history_flags,history_summary\n"
        "u1,3,user_history_risk,Prior claims needed review\n",
        encoding="utf-8",
    )
    history = load_user_history(path)
    assert history["u1"]["history_flags"] == "user_history_risk"


def test_load_evidence_requirements_filters_by_object(tmp_path):
    path = tmp_path / "evidence_requirements.csv"
    path.write_text(
        "requirement_id,claim_object,applies_to,minimum_image_evidence\n"
        "REQ_ALL,all,general,Any relevant part must be visible\n"
        "REQ_CAR,car,dent,Car panel visible\n",
        encoding="utf-8",
    )
    reqs = load_evidence_requirements(path)
    selected = load_evidence_requirements(path, claim_object="car")
    assert len(reqs) == 2
    assert {row["requirement_id"] for row in selected} == {"REQ_ALL", "REQ_CAR"}


def test_write_output_rows_uses_exact_column_order(tmp_path):
    output = tmp_path / "output.csv"
    row = {column: "" for column in OUTPUT_COLUMNS}
    row.update(
        {
            "user_id": "u1",
            "image_paths": "img",
            "user_claim": "claim",
            "claim_object": "car",
            "evidence_standard_met": "false",
            "risk_flags": "none",
            "issue_type": "unknown",
            "object_part": "unknown",
            "claim_status": "not_enough_information",
            "supporting_image_ids": "none",
            "valid_image": "false",
            "severity": "unknown",
        }
    )
    write_output_rows(output, [row])
    with output.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        assert next(reader) == OUTPUT_COLUMNS


def test_detect_mime_type_from_bytes():
    assert detect_mime_type(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert detect_mime_type(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert detect_mime_type(b"RIFFxxxxWEBPrest") == "image/webp"
    assert detect_mime_type(b"\x00\x00\x00 ftypavifrest") == "image/avif"
    assert detect_mime_type(b"not-an-image") == "application/octet-stream"


def test_extract_image_id_from_path():
    assert extract_image_id("images/test/case_001/img_2.jpg") == "img_2"


def test_resolve_image_path_supports_dataset_relative_paths(tmp_path):
    repo_root = tmp_path
    image = repo_root / "dataset" / "images" / "test" / "case_001" / "img_1.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"\xff\xd8\xff\xe0jpeg")
    resolved = resolve_image_path(repo_root, "images/test/case_001/img_1.jpg")
    assert resolved == image


def test_prepare_image_returns_base64_and_hash(tmp_path):
    image = tmp_path / "img_1.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0jpeg")
    prepared = prepare_image(tmp_path, "img_1.jpg")
    assert prepared.image_id == "img_1"
    assert prepared.mime_type == "image/jpeg"
    assert prepared.size_bytes == len(b"\xff\xd8\xff\xe0jpeg")
    assert base64.b64decode(prepared.data_base64) == b"\xff\xd8\xff\xe0jpeg"
    assert len(prepared.sha256) == 64


def test_prepare_images_handles_semicolon_lists(tmp_path):
    (tmp_path / "img_1.jpg").write_bytes(b"\xff\xd8\xff\xe0jpeg")
    (tmp_path / "img_2.png").write_bytes(b"\x89PNG\r\n\x1a\npng")
    prepared = prepare_images(tmp_path, "img_1.jpg; img_2.png; ")
    assert [image.image_id for image in prepared] == ["img_1", "img_2"]
    assert [image.mime_type for image in prepared] == ["image/jpeg", "image/png"]


def test_prepare_image_marks_unsupported_avif_unreadable_without_bytes(tmp_path, monkeypatch):
    import images

    image = tmp_path / "img_1.avif"
    original_bytes = b"\x00\x00\x00 ftypavifrest"
    image.write_bytes(original_bytes)
    monkeypatch.setattr(images, "_convert_avif_to_png_bytes", lambda path: None)
    prepared = prepare_image(tmp_path, "img_1.avif")
    assert prepared.readable is False
    assert prepared.mime_type == "image/avif"
    assert prepared.data_base64 == ""
    assert "AVIF" in prepared.error
    assert len(prepared.sha256) == 64
