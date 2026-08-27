"""도시 세이브 레코드 배열의 주소·범위 처리.

도시 탭의 UI와 무관한 레코드 경계 계산 및 원본 대비 복원 판단을 한곳에 둔다.
"""

from __future__ import annotations

from .save_records import RecordTableLayout


class CityRecordLayout(RecordTableLayout):
    """세이브 파일 안에 연속 저장된 도시 레코드 배열의 레이아웃."""

    pass


def refreshed_ship_mask(
    base_mask: int,
    candidate_mask: int,
    city_scale: int,
    base_year: int,
    target_year: int,
    release_coefficients,
) -> int:
    """도시 조선소의 연도별 판매 후보 마스크를 계산한다.

    게임은 각 연도에 도시 후보 선박 중 출시 조건을 충족한 번호가 가장 높은 한 종을
    추가한다. 날짜를 앞으로 건너뛴 편집에서도 원본 연도부터 누적해 같은 결과를 낸다.
    """
    result = int(base_mask) & 0xFFFF
    candidates = int(candidate_mask) & 0xFFFF
    scale = int(city_scale)
    coefficients = tuple(int(value) for value in release_coefficients)
    for year in range(int(base_year), int(target_year) + 1):
        threshold = year + scale * 5 - 1475
        candidate = max(
            (ship_code for ship_code, coefficient in enumerate(coefficients)
             if candidates & (1 << ship_code) and coefficient < threshold),
            default=-1,
        )
        if candidate >= 0:
            result |= 1 << candidate
    return result
