"""Story 3.2 — minimal PDF fixture 빌더 (1회용 — reportlab 없이 한글 ASCII 음역으로 fixture 생성).

실행: ``cd api && uv run python tests/fixtures/_build_pdf_fixture.py``

생성물: ``tests/fixtures/sample-guideline.pdf`` (2 페이지, Type1 Helvetica 폰트).

한글은 Type1 Helvetica가 미지원 → ASCII 영문 + 음역 텍스트로 chunking 정합 검증만.
운영 PDF는 D1 운영자 SOP — Word/Pages export로 commit.

본 스크립트가 fixture를 생성한 후 결과는 commit. 본 스크립트 자체는 dev 도구.
"""

from __future__ import annotations

from pathlib import Path


def _build_obj(num: int, body: bytes) -> bytes:
    return f"{num} 0 obj\n".encode() + body + b"\nendobj\n"


def _build_stream_obj(num: int, content: bytes) -> bytes:
    body = f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream"
    return _build_obj(num, body)


def build_minimal_pdf() -> bytes:
    """2페이지 Type1 Helvetica PDF — 영문 가이드라인 풍 텍스트.

    Returns:
        bytes — valid PDF 1.4 (xref + trailer 포함).
    """
    page1_stream = (
        b"BT\n/F1 12 Tf\n50 750 Td\n"
        b"(Korean DRIs 2020 - AMDR macronutrient ratios) Tj\n"
        b"0 -20 Td\n"
        b"(Carbohydrates 55 to 65 percent of total energy) Tj\n"
        b"0 -20 Td\n"
        b"(Protein 7 to 20 percent fat 15 to 30 percent) Tj\n"
        b"ET"
    )
    page2_stream = (
        b"BT\n/F1 12 Tf\n50 750 Td\n"
        b"(KSSO 2024 weight loss guideline page 2) Tj\n"
        b"0 -20 Td\n"
        b"(Reduce calories by 500 kcal raise protein to 25 percent) Tj\n"
        b"ET"
    )

    objects: list[bytes] = []
    # 1: Catalog
    objects.append(_build_obj(1, b"<< /Type /Catalog /Pages 2 0 R >>"))
    # 2: Pages
    objects.append(_build_obj(2, b"<< /Type /Pages /Count 2 /Kids [3 0 R 5 0 R] >>"))
    # 3: Page 1
    objects.append(
        _build_obj(
            3,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 7 0 R >> >> /Contents 4 0 R >>",
        )
    )
    # 4: Page 1 stream
    objects.append(_build_stream_obj(4, page1_stream))
    # 5: Page 2
    objects.append(
        _build_obj(
            5,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 7 0 R >> >> /Contents 6 0 R >>",
        )
    )
    # 6: Page 2 stream
    objects.append(_build_stream_obj(6, page2_stream))
    # 7: Font
    objects.append(
        _build_obj(
            7, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
        )
    )

    # Header.
    pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets: list[int] = []
    for obj in objects:
        offsets.append(len(pdf))
        pdf += obj

    # xref.
    xref_offset = len(pdf)
    xref = f"xref\n0 {len(objects) + 1}\n".encode()
    xref += b"0000000000 65535 f \n"
    for off in offsets:
        xref += f"{off:010d} 00000 n \n".encode()
    pdf += xref

    # trailer.
    trailer = (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
    ).encode()
    pdf += trailer
    return pdf


if __name__ == "__main__":
    out_path = Path(__file__).resolve().parent / "sample-guideline.pdf"
    out_path.write_bytes(build_minimal_pdf())
    print(f"Generated: {out_path} ({out_path.stat().st_size} bytes)")
