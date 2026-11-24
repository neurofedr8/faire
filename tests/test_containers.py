import subprocess
from pathlib import Path

from datalad.api import create

from faire.containers import Collection, install


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.org", *args],
                          cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def test_install_detaches_at_branch_that_exists_only_on_remote(tmp_path):
    src = tmp_path / "collection"
    src.mkdir()
    git(src, "init", "-q", "-b", "main")
    (src / "a").write_text("a")
    git(src, "add", "a")
    git(src, "commit", "-q", "-m", "main")
    git(src, "checkout", "-q", "-b", "dev")
    (src / "b").write_text("b")
    git(src, "add", "b")
    git(src, "commit", "-q", "-m", "dev")
    dev = git(src, "rev-parse", "dev")
    git(src, "checkout", "-q", "main")

    ds = create(path=str(tmp_path / "ds"), result_renderer="disabled")
    install(ds, Collection("tools", str(src), "tools", "dev"))

    sub = Path(ds.path) / "tools"
    assert git(sub, "rev-parse", "HEAD") == dev
    assert git(sub, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"  # detached
