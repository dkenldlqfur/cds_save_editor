"""Treeview 갱신에 공통으로 쓰는 UI 비즈니스 로직 없는 도구."""


def clear_rows(*trees) -> None:
    """전달된 트리 목록의 기존 행을 안전하게 비운다."""
    for tree in trees:
        if tree is not None:
            tree.delete(*tree.get_children())
