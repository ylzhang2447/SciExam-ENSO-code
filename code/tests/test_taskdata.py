"""The task data archive: downloaded, checked against the recorded sha256, never half-written."""
import hashlib
import io
import tarfile

from sciexam.agent.provenance import DATA_FILES
from sciexam.prepare import taskdata as TD


def archive(tmp_path, contents):
    p = tmp_path / "a.tar.gz"
    with tarfile.open(p, "w:gz") as tar:
        for name, data in contents.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return p


def sha(b):
    return hashlib.sha256(b).hexdigest()


def test_fetch_checks_every_file(tmp_path, monkeypatch):
    files = {n: n.encode() * 10 for n in DATA_FILES}
    a = archive(tmp_path, files)
    monkeypatch.setattr(TD, "TASK_FILES_SHA256", {"data/" + n: sha(b) for n, b in files.items()})
    monkeypatch.setattr(TD, "ARCHIVE_SHA256", sha(a.read_bytes()))
    log = []
    assert TD.fetch(tmp_path / "raw", url=a.as_uri(), log=log.append)
    assert sorted(p.name for p in (tmp_path / "raw").iterdir()) == sorted(DATA_FILES)
    assert TD.present(tmp_path / "raw")


def test_a_wrong_archive_leaves_nothing(tmp_path, monkeypatch):
    files = {n: b"x" for n in DATA_FILES}
    a = archive(tmp_path, files)
    monkeypatch.setattr(TD, "ARCHIVE_SHA256", sha(a.read_bytes()))
    log = []                                     # the archive is fine, the files are not recorded ones
    assert not TD.fetch(tmp_path / "raw", url=a.as_uri(), log=log.append)
    assert list((tmp_path / "raw").iterdir()) == [] and "recorded sha256" in log[-1]
    monkeypatch.setattr(TD, "ARCHIVE_SHA256", "0" * 64)
    assert not TD.fetch(tmp_path / "raw", url=a.as_uri(), log=log.append)
    assert list((tmp_path / "raw").iterdir()) == []
