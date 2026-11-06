import pytest

from coderagent.testing.factory import build_context
from coderagent.tools.builtin.search import GlobTool, GrepTool, LsTool


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "core.py").write_text("def main():\n    return 42\n", encoding="utf-8")
    (tmp_path / "pkg" / "util.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Title\nvalue here\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.py").write_text("ignored = True\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def ctx(tree):
    return build_context(tree)


def test_glob_matches_across_directories(ctx, tree):
    result = GlobTool().run({"pattern": "**/*.py"}, ctx)
    assert result.content.splitlines() == ["pkg/core.py", "pkg/util.py"]


def test_glob_does_not_cross_directories_with_a_single_star(ctx):
    assert "No files matched" in GlobTool().run({"pattern": "*.py"}, ctx).content


def test_glob_skips_ignored_directories(ctx):
    assert "node_modules" not in GlobTool().run({"pattern": "**/*.py"}, ctx).content


def test_glob_reports_when_nothing_matches(ctx):
    assert "No files matched" in GlobTool().run({"pattern": "**/*.rs"}, ctx).content


def test_glob_truncates_long_result_lists(ctx, tree):
    for index in range(250):
        (tree / f"file{index}.txt").write_text("x", encoding="utf-8")
    result = GlobTool().run({"pattern": "*.txt"}, ctx)
    assert "more matches not shown" in result.content
    assert len(result.content.splitlines()) == 201


def test_grep_returns_matching_lines(ctx):
    result = GrepTool().run({"pattern": "value"}, ctx)
    assert result.content == "README.md:2:value here"


def test_grep_can_list_the_matching_files(ctx):
    result = GrepTool().run({"pattern": "VALUE", "output_mode": "files_with_matches"}, ctx)
    assert result.content == "pkg/util.py"


def test_grep_can_count_the_matches_per_file(ctx):
    result = GrepTool().run({"pattern": "e", "output_mode": "count"}, ctx)
    assert result.content == "README.md:2\npkg/core.py:2"


def test_grep_is_case_insensitive_on_demand(ctx):
    assert "No matches" in GrepTool().run({"pattern": "title"}, ctx).content
    assert GrepTool().run({"pattern": "title", "-i": True}, ctx).content == "README.md:1:# Title"


def test_grep_can_limit_the_files_it_looks_at(ctx):
    result = GrepTool().run({"pattern": "value", "glob": "**/*.md"}, ctx)
    assert result.content == "README.md:2:value here"
    assert "No matches" in GrepTool().run({"pattern": "value", "glob": "**/*.py"}, ctx).content


def test_grep_rejects_bad_input(ctx):
    assert "invalid regular expression" in GrepTool().run({"pattern": "["}, ctx).content
    assert "output_mode" in GrepTool().run({"pattern": "x", "output_mode": "nope"}, ctx).content
    assert GrepTool().run({}, ctx).is_error


def test_grep_skips_binary_files(ctx, tree):
    (tree / "blob.bin").write_bytes(b"\x00value\x00")
    assert GrepTool().run({"pattern": "value"}, ctx).content == "README.md:2:value here"


def test_ls_lists_directories_and_files(ctx, tree):
    result = LsTool().run({"path": "."}, ctx)
    assert result.content.splitlines() == ["README.md (19 B)", "pkg/"]


def test_ls_can_recurse(ctx, tree):
    result = LsTool().run({"path": ".", "depth": -1}, ctx)
    assert "pkg/core.py (26 B)" in result.content.splitlines()


def test_ls_rejects_missing_paths(ctx):
    assert LsTool().run({"path": "nope"}, ctx).is_error
    assert LsTool().run({"path": "README.md"}, ctx).is_error
