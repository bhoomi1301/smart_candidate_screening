"""Build small, real PDF files for tests (no fixtures on disk)."""

import io

from pypdf import PdfWriter


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text_pdf(pages: list[list[str]] | list[str]) -> bytes:
    """A valid PDF whose pages contain the given lines as real (extractable) text."""
    if pages and isinstance(pages[0], str):
        pages = [pages]  # type: ignore[list-item]
    objects: list[bytes] = []
    page_ids = []
    font_id = 3 + 2 * len(pages)
    for index, lines in enumerate(pages):
        page_id, content_id = 3 + 2 * index, 4 + 2 * index
        page_ids.append(page_id)
        body = "BT /F1 11 Tf 50 760 Td 14 TL " + " ".join(f"({_escape(line)}) Tj T*" for line in lines) + " ET"
        stream = body.encode("latin-1")
        objects.append(f"{page_id} 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >> endobj\n".encode())
        objects.append(f"{content_id} 0 obj << /Length {len(stream)} >> stream\n".encode() + stream + b"\nendstream endobj\n")
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    head = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        f"2 0 obj << /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >> endobj\n".encode(),
    ]
    tail = [f"{font_id} 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n".encode()]
    ordered = head + objects + tail
    output = io.BytesIO()
    output.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for obj in ordered:
        offsets.append(output.tell())
        output.write(obj)
    xref = output.tell()
    output.write(f"xref\n0 {len(ordered) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        output.write(f"{offset:010d} 00000 n \n".encode())
    output.write(f"trailer << /Size {len(ordered) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return output.getvalue()


def blank_pdf(pages: int = 1) -> bytes:
    """Pages with no text layer, like a scanned or image-only resume."""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def encrypted_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt(user_password="secret", owner_password="owner", algorithm="RC4-128")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


SAMPLE_RESUME_LINES = [
    "Priya Natarajan",
    "Backend Engineer | priya.n@example.com | +1 (555) 014-2233",
    "Backend engineer with 6+ years of professional experience building APIs.",
    "Experience",
    "Acme Corp, Senior Engineer, Jan 2021 - Present",
    "Education",
    "B.Sc. in Computer Science, University of Toronto, 2017",
    "Skills",
    "Python, PostgreSQL, Docker, Kubernetes, AWS, Go",
]
