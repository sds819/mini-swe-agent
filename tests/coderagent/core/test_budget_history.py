import pytest

from coderagent.core.budget import BudgetGuard
from coderagent.core.history import History


def test_the_budget_leaves_room_for_the_answer():
    guard = BudgetGuard(context_window=100_000, reserved_output=8_000)
    assert guard.limit() == 92_000


def test_a_small_window_cannot_reserve_more_than_it_has():
    assert BudgetGuard(context_window=4_000, reserved_output=8_000).limit() == 0


@pytest.mark.parametrize(
    ("estimated", "expected"),
    [(100_000, False), (160_001, True)],
)
def test_compaction_starts_at_the_threshold(estimated, expected):
    assert BudgetGuard(context_window=200_000, reserved_output=8_000).should_compact(estimated) is expected


def test_the_hard_limit_wins_when_the_reserved_output_is_large():
    guard = BudgetGuard(context_window=32_000, reserved_output=8_000, compact_threshold=0.95)
    assert guard.should_compact(25_000) is True
    assert guard.should_compact(20_000) is False


def test_a_history_splits_into_turns():
    history = History(
        [
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
            {"role": "tool", "tool_call_id": "1", "content": "ok"},
            {"role": "assistant", "content": "done"},
            {"role": "user", "content": "next task"},
            {"role": "assistant", "content": "done"},
        ]
    )
    assert history.turn_count() == 2
    assert history.turn_starts() == [0, 4]


def test_recent_turns_keeps_the_whole_last_turn():
    history = History(
        [
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "a"},
            {"role": "user", "content": "two"},
            {"role": "assistant", "content": "b"},
            {"role": "assistant", "content": "c", "tool_calls": [{"id": "1"}]},
            {"role": "tool", "tool_call_id": "1", "content": "ok"},
        ]
    )
    assert history.recent_turns(1) == [
        {"role": "user", "content": "two"},
        {"role": "assistant", "content": "b"},
        {"role": "assistant", "content": "c", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "tool_call_id": "1", "content": "ok"},
    ]
    assert len(history.recent_turns(2)) == 6


def test_recent_turns_of_a_history_without_a_user_message():
    assert History([{"role": "assistant", "content": "x"}]).recent_turns(3) == [{"role": "assistant", "content": "x"}]
    assert History([{"role": "assistant", "content": "x"}]).recent_turns(0) == []


def test_splitting_a_history_round_trips():
    history = History([{"role": "user", "content": str(i)} for i in range(5)])
    older, newer = history.split_at(2)
    assert older + newer == history.messages
    assert len(older) == 2 and len(newer) == 3


def test_the_token_count_grows_with_the_history():
    history = History([{"role": "user", "content": "x" * 1000}])
    assert history.token_count() > 0
