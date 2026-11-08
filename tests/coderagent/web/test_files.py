"""The files of the working directory, seen from the browser."""

import pytest

pytest.importorskip("fastapi")


@pytest.fixture
def project(make_client, tmp_path):
    """A web interface with a small project in the working directory."""
    (tmp_path / "hello.txt").write_text("hi there\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "nested.txt").write_text("nested\n", encoding="utf-8")
    return make_client()


def test_the_directory_is_listed(project):
    response = project.get("/api/files", params={"path": "", "depth": 1})

    assert response.status_code == 200
    names = [entry["name"] for entry in response.json()["entries"]]
    assert "hello.txt" in names
    assert "sub" in names
    assert [entry for entry in response.json()["entries"] if entry["name"] == "hello.txt"][0]["size"] == 9


def test_the_tree_is_listed_to_the_depth_that_is_asked_for(project):
    entries = project.get("/api/files", params={"path": "", "depth": -1}).json()["entries"]

    assert "sub/nested.txt" in [entry["path"] for entry in entries]


def test_a_file_is_read(project):
    response = project.get("/api/file", params={"path": "hello.txt"})

    assert response.status_code == 200
    assert "hi there" in response.json()["content"]
    assert response.json()["is_error"] is False


def test_a_file_that_is_outside_the_working_directory_is_refused(project):
    assert project.get("/api/file", params={"path": "../../etc/passwd"}).status_code == 403
    assert project.get("/api/file", params={"path": "/etc/passwd"}).status_code == 403
    assert project.get("/api/files", params={"path": ".."}).status_code == 403
    assert project.get("/api/diff", params={"path": "/etc/passwd"}).status_code == 403


def test_a_path_that_is_not_a_directory_is_refused(project):
    assert project.get("/api/files", params={"path": "hello.txt"}).status_code == 400


def test_the_diff_of_the_working_tree_is_answered(project):
    response = project.get("/api/diff", params={"path": "hello.txt"})

    assert response.status_code == 200
    assert "diff" in response.json()
    """Outside of a repository the answer is the error of git, not a crash."""
