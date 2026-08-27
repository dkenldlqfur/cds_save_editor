"""탭 화면이 공유하는 Tkinter 레이아웃 보조 함수."""


def configure_equal_columns(parent, count: int, uniform_name: str) -> None:
    """탭의 가로 영역을 같은 비율의 열로 설정한다."""
    for column in range(count):
        parent.columnconfigure(column, weight=1, uniform=uniform_name)
    parent.rowconfigure(0, weight=1)
