from shimeji_dl.core.error_description import describe_error


def test_describe_error_renders_a_plain_leaf() -> None:
    assert describe_error(ValueError("boom")) == "ValueError: boom"


def test_describe_error_unpacks_a_single_level_group() -> None:
    group = ExceptionGroup("group", [ValueError("boom"), RuntimeError("bang")])
    assert describe_error(group) == "ValueError: boom; RuntimeError: bang"


def test_describe_error_unpacks_two_nested_levels() -> None:
    """Reproduces the shape asyncio.TaskGroup produces when a source's own
    TaskGroup failure is re-wrapped by an outer TaskGroup: rendering the
    outer group directly collapses to "... (1 sub-exception)", losing the
    real message.
    """
    inner = ExceptionGroup("inner", [ValueError("real message")])
    outer = ExceptionGroup("outer", [inner])

    assert str(outer.exceptions[0]) == "inner (1 sub-exception)"
    assert describe_error(outer) == "ValueError: real message"
