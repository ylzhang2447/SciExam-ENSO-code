"""The reference paper check: the formal PDF, or a download of it with the publisher's stamp."""
from sciexam.prepare import paper as P


def test_a_stamped_download_is_the_same_article(tmp_path, monkeypatch):
    pdf = tmp_path / "atsc-download.pdf"
    pdf.write_bytes(b"%PDF stamped")             # other bytes than the formal file
    monkeypatch.setattr(P, "text_sha256", lambda p: P.TEXT_SHA256)
    assert P.same_article(pdf)
    log = []
    assert P.install(pdf, tmp_path / "task", log=log.append) == 0
    assert "only the publisher's download stamp differs" in log[0]
    assert (tmp_path / "task" / P.REL_DEST).exists()


def test_another_article_is_refused_unless_accepted(tmp_path, monkeypatch):
    pdf = tmp_path / "other.pdf"
    pdf.write_bytes(b"%PDF other")
    monkeypatch.setattr(P, "text_sha256", lambda p: "0" * 64)
    assert not P.same_article(pdf)
    assert P.install(pdf, tmp_path / "task", log=lambda m: None) == 1
    assert P.install(pdf, tmp_path / "task", accept_different=True, log=lambda m: None) == 0


def test_the_stamp_lines_are_what_is_removed():
    assert P.STAMP.search("Unauthenticated | Downloaded 10/24/26 07:15 PM UTC")
    assert not P.STAMP.search("A new conceptual model for ENSO has been constructed")


def test_a_file_that_is_not_a_pdf_has_no_fingerprint(tmp_path):
    f = tmp_path / "x.pdf"
    f.write_bytes(b"not a pdf")
    assert P.text_sha256(f) is None
