"""The shell commands: what they are and where they may reach."""

from pathlib import Path

from coderagent.tools import bash_policy


def test_a_command_is_split_into_the_parts_a_shell_runs():
    assert bash_policy.segments("ls && rm x | wc -l") == ["ls", "rm x", "wc -l"]


def test_the_parts_of_a_command_keep_their_quotes():
    assert bash_policy.segments('echo "a && b"') == ['echo "a && b"']


def test_a_command_that_only_looks_around_is_safe():
    assert bash_policy.classify("ls -la") == ("safe", "")
    assert bash_policy.classify("cat a.py | grep foo") == ("safe", "")
    assert bash_policy.classify("git status") == ("safe", "")


def test_a_command_that_sends_something_out_is_dangerous():
    kind, reason = bash_policy.classify("curl http://example.com")
    assert kind == "dangerous"
    assert "sends data out" in reason


def test_a_subcommand_of_git_is_judged_on_its_own():
    assert bash_policy.classify("git status") == ("safe", "")
    assert bash_policy.classify("git push origin main")[0] == "dangerous"


def test_a_command_that_is_not_known_is_unknown():
    assert bash_policy.classify("make build") == ("unknown", "")
    assert bash_policy.classify("./scripts/test.sh") == ("unknown", "")


def test_a_command_that_redirects_writes_something():
    assert bash_policy.classify("echo hello > out.txt") == ("unknown", "")
    assert bash_policy.classify("echo hello 2>/dev/null") == ("safe", "")


def test_a_path_outside_the_working_directory_is_found():
    cwd = Path("/tmp/work")
    assert bash_policy.outside_paths("cat /etc/passwd", cwd, []) == ["/etc/passwd"]
    assert bash_policy.outside_paths("cat ../secret", cwd, []) == ["../secret"]
    assert bash_policy.outside_paths("cat ~/.ssh/id_rsa", cwd, []) == ["~/.ssh/id_rsa"]
    assert bash_policy.outside_paths("grep -r secret /", cwd, []) == ["/"]


def test_a_path_inside_the_working_directory_is_left_alone():
    cwd = Path("/tmp/work")
    assert bash_policy.outside_paths("cat src/main.py", cwd, []) == []
    assert bash_policy.outside_paths("cat a/b.py", cwd, []) == []
    assert bash_policy.outside_paths("cd sub && cat x", cwd, []) == []


def test_a_path_that_is_quoted_inside_a_word_is_found():
    assert bash_policy.outside_paths("python -c \"open('/etc/passwd')\"", Path("/tmp/work"), []) == ["/etc/passwd"]


def test_a_program_of_the_system_may_be_named():
    assert bash_policy.outside_paths("/bin/ls", Path("/tmp/work"), []) == []


def test_a_directory_that_is_open_is_not_outside():
    cwd = Path("/tmp/work")
    assert bash_policy.outside_paths("cat /tmp/work/vendor/lib.py", cwd, [Path("/tmp/work/vendor")]) == []
