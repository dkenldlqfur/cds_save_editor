"""Treeview 갱신에 공통으로 쓰는 UI 비즈니스 로직 없는 도구."""


def clear_rows(*trees) -> None:
    """전달된 트리 목록의 기존 행을 안전하게 비운다."""
    for tree in trees:
        if tree is not None:
            tree.delete(*tree.get_children())


READONLY_ROW_TAG = 'readonly_row'
EDITABLE_ROW_TAG = 'editable_row'


def mixed_editability_tags(editable_flags):
    """Return an explicit editability tag for every row.

    The historical function name is kept because callers already use it, but
    fully read-only lists are no longer exempt from visual marking.
    """
    flags = tuple(bool(flag) for flag in editable_flags)
    return tuple(
        (EDITABLE_ROW_TAG,) if editable else (READONLY_ROW_TAG,)
        for editable in flags
    )
