"""Long tool output is trimmed by tokens, and the trim is recorded."""

from coderagent.config.schema import ToolConfig
from coderagent.core.session import Session
from coderagent.testing.factory import build_context, build_executor
from coderagent.tools.builtin.fs import ReadTool


def _big_file(tmp_path, lines: int = 5000) -> None:
    (tmp_path / "big.py").write_text("\n".join(f"line {index}" for index in range(lines)), encoding="utf-8")


def test_a_long_file_is_trimmed_by_tokens(tmp_path):
    _big_file(tmp_path)
    ctx = build_context(tmp_path, config=ToolConfig(max_output_tokens=100))
    result = ReadTool().run({"path": "big.py"}, ctx)
    assert "lines elided" in result.content
    assert result.metadata["truncated"]["elided_lines"] > 0
    assert result.metadata["truncated"]["start_line"] < result.metadata["truncated"]["end_line"]


def test_the_line_numbers_stay_right_after_the_elision(tmp_path):
    _big_file(tmp_path)
    ctx = build_context(tmp_path, config=ToolConfig(max_output_tokens=100))
    result = ReadTool().run({"path": "big.py"}, ctx)
    lines = result.content.splitlines()
    numbers = [line.split("\t")[0].strip() for line in lines if "\t" in line]
    assert numbers == sorted(numbers, key=int)
    assert "line 1999" in lines[-2]


def test_the_elided_region_can_be_read_again(tmp_path):
    _big_file(tmp_path)
    ctx = build_context(tmp_path, config=ToolConfig(max_output_tokens=100))
    result = ReadTool().run({"path": "big.py"}, ctx)
    start = result.metadata["truncated"]["start_line"]
    again = ReadTool().run({"path": "big.py", "offset": start, "limit": 5}, ctx)
    assert again.content.splitlines()[0].endswith(f"line {start - 1}")


def test_a_short_file_is_not_trimmed(tmp_path):
    (tmp_path / "small.py").write_text("one\ntwo\n", encoding="utf-8")
    ctx = build_context(tmp_path, config=ToolConfig(max_output_tokens=100))
    result = ReadTool().run({"path": "small.py"}, ctx)
    assert "truncated" not in result.metadata


def test_the_trim_is_recorded_in_the_session(tmp_path):
    _big_file(tmp_path)
    session = Session(id="test", cwd=tmp_path, created_at=0.0, updated_at=0.0)
    ctx = build_context(tmp_path, session=session, config=ToolConfig(max_output_tokens=100))
    executor = build_executor(tmp_path, context=ctx)
    executor.execute(executor.plan([{"id": "c1", "function": {"name": "read", "arguments": '{"path": "big.py"}'}}]))
    assert session.metadata["truncated_outputs"][0]["path"] == "big.py"
    assert session.metadata["truncated_outputs"][0]["elided_lines"] > 0
