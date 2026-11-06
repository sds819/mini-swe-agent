import pytest

from coderagent.testing.factory import build_context
from coderagent.tools.builtin.fs import EditTool, MultiEditTool, ReadTool, WriteTool


@pytest.fixture
def ctx(tmp_path):
    return build_context(tmp_path)


def test_read_returns_numbered_lines(ctx, tmp_path):
    (tmp_path / "a.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    result = ReadTool().run({"path": "a.py"}, ctx)
    assert result.content == "1\tone\n2\ttwo\n3\tthree"
    assert result.metadata["lines"] == 3


def test_read_honours_offset_and_limit(ctx, tmp_path):
    (tmp_path / "a.py").write_text("\n".join(f"line{i}" for i in range(10)), encoding="utf-8")
    result = ReadTool().run({"path": "a.py", "offset": 3, "limit": 2}, ctx)
    assert result.content.startswith("3\tline2\n4\tline3")
    assert "showing lines 3-4 of 10" in result.content


def test_read_truncates_very_long_lines(ctx, tmp_path):
    (tmp_path / "a.py").write_text("x" * 5000, encoding="utf-8")
    result = ReadTool().run({"path": "a.py"}, ctx)
    assert "line truncated" in result.content
    assert len(result.content) < 5000


def test_read_rejects_missing_files_directories_and_binaries(ctx, tmp_path):
    (tmp_path / "bin").write_bytes(b"\x00\x01\x02")
    assert "file not found" in ReadTool().run({"path": "nope.py"}, ctx).content
    assert "is a directory" in ReadTool().run({"path": "."}, ctx).content
    assert "binary file" in ReadTool().run({"path": "bin"}, ctx).content
    assert ReadTool().run({"path": "nope.py"}, ctx).is_error


def test_write_creates_parent_directories_and_records_the_old_content(ctx, tmp_path):
    result = WriteTool().run({"path": "nested/dir/a.txt", "content": "hello\n"}, ctx)
    assert result.content.startswith("Created")
    assert (tmp_path / "nested/dir/a.txt").read_text(encoding="utf-8") == "hello\n"
    assert result.metadata["old_content"] is None

    again = WriteTool().run({"path": "nested/dir/a.txt", "content": "bye"}, ctx)
    assert again.content.startswith("Updated")
    assert again.metadata["old_content"] == "hello\n"


def test_edit_replaces_a_unique_string(ctx, tmp_path):
    (tmp_path / "a.py").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    result = EditTool().run({"path": "a.py", "old_string": "beta", "new_string": "delta"}, ctx)
    assert result.content == "Replaced 1 occurrence(s) in a.py"
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "alpha\ndelta\ngamma\n"
    assert "-beta" in result.metadata["diff"]


def test_edit_reports_a_missing_string(ctx, tmp_path):
    (tmp_path / "a.py").write_text("alpha\n", encoding="utf-8")
    result = EditTool().run({"path": "a.py", "old_string": "missing", "new_string": "x"}, ctx)
    assert result.is_error
    assert "not found" in result.content
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "alpha\n"


def test_edit_reports_an_ambiguous_string_with_the_line_numbers(ctx, tmp_path):
    (tmp_path / "a.py").write_text("foo\nbar\nfoo\n", encoding="utf-8")
    result = EditTool().run({"path": "a.py", "old_string": "foo", "new_string": "x"}, ctx)
    assert result.is_error
    assert "appears 2 times" in result.content
    assert "lines 1, 3" in result.content
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "foo\nbar\nfoo\n"


def test_edit_can_replace_every_occurrence(ctx, tmp_path):
    (tmp_path / "a.py").write_text("foo\nbar\nfoo\n", encoding="utf-8")
    result = EditTool().run({"path": "a.py", "old_string": "foo", "new_string": "x", "replace_all": True}, ctx)
    assert result.content == "Replaced 2 occurrence(s) in a.py"
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x\nbar\nx\n"


def test_edit_matches_crlf_files(ctx, tmp_path):
    (tmp_path / "a.py").write_bytes(b"alpha\r\nbeta\r\n")
    result = EditTool().run({"path": "a.py", "old_string": "beta", "new_string": "gamma"}, ctx)
    assert not result.is_error
    assert (tmp_path / "a.py").read_bytes() == b"alpha\r\ngamma\r\n"


def test_multi_edit_applies_every_change(ctx, tmp_path):
    (tmp_path / "a.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    result = MultiEditTool().run(
        {
            "path": "a.py",
            "edits": [{"old_string": "one", "new_string": "1"}, {"old_string": "three", "new_string": "3"}],
        },
        ctx,
    )
    assert not result.is_error
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "1\ntwo\n3\n"


def test_multi_edit_is_atomic(ctx, tmp_path):
    (tmp_path / "a.py").write_text("one\ntwo\n", encoding="utf-8")
    result = MultiEditTool().run(
        {
            "path": "a.py",
            "edits": [{"old_string": "one", "new_string": "1"}, {"old_string": "missing", "new_string": "x"}],
        },
        ctx,
    )
    assert result.is_error
    assert "no changes were written" in result.content
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "one\ntwo\n"


def test_multi_edit_validates_its_arguments(ctx, tmp_path):
    (tmp_path / "a.py").write_text("one\n", encoding="utf-8")
    assert MultiEditTool().run({"path": "a.py", "edits": []}, ctx).is_error
    assert MultiEditTool().run({"path": "a.py", "edits": [{"new_string": "x"}]}, ctx).is_error
    assert MultiEditTool().run({"path": "a.py", "edits": ["nope"]}, ctx).is_error


def test_write_validates_its_arguments(ctx):
    assert WriteTool().run({"path": "a.txt"}, ctx).is_error
    assert WriteTool().run({"content": "x"}, ctx).is_error
    assert ReadTool().run({}, ctx).is_error
