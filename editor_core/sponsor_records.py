"""후원자 계약 세이브 레코드의 필드 접근."""

from __future__ import annotations

from .save_records import RecordTableLayout, read_value, write_value
from .resources import error_text


CONTRACT_STATE_OFFSET = 0x08
REMAINING_DAYS_OFFSET = 0x0E
CONTRACT_AUXILIARY_OFFSET = 0x14
WEALTH_OFFSET = 0x04
INTIMACY_OFFSET = 0x00
INTIMACY_MIN = 0
INTIMACY_MAX = 100
POWER_GRADES = ('E', 'D', 'C', 'B', 'A')


def power_grade(power: int) -> str:
    """게임의 ``(권력 - 1) / 20`` 표시식을 E~A 등급으로 변환한다."""
    value = max(0, int(power))
    grade_index = 0 if value == 0 else (value - 1) // 20
    return POWER_GRADES[min(grade_index, len(POWER_GRADES) - 1)]


def intimacy(buffer: bytes | bytearray, layout: RecordTableLayout, sponsor_id: int) -> int:
    """후원자별 친밀도(레코드 +0x00)를 반환한다."""
    if not layout.contains(buffer, sponsor_id):
        raise ValueError(error_text('sponsor_record_unavailable'))
    return read_value(buffer, layout.offset(sponsor_id) + INTIMACY_OFFSET, 'u32')


def write_intimacy(
    buffer: bytearray,
    layout: RecordTableLayout,
    sponsor_id: int,
    value: int,
) -> None:
    """후원자 친밀도를 게임의 0~100 범위로 보정해 기록한다."""
    if not layout.contains(buffer, sponsor_id):
        raise ValueError(error_text('sponsor_record_unavailable'))
    write_value(
        buffer, layout.offset(sponsor_id) + INTIMACY_OFFSET, 'u32',
        max(INTIMACY_MIN, min(INTIMACY_MAX, int(value))),
    )


def active_sponsor_id(
    buffer: bytes | bytearray,
    layout: RecordTableLayout,
    sponsor_ids,
    active_state: int,
) -> int | None:
    """계약 상태 필드가 활성값인 첫 후원자 ID를 반환한다."""
    for sponsor_id in sponsor_ids:
        sponsor_id = int(sponsor_id)
        if not layout.contains(buffer, sponsor_id):
            continue
        offset = layout.offset(sponsor_id)
        if read_value(buffer, offset + CONTRACT_STATE_OFFSET, 'u32') == int(active_state):
            return sponsor_id
    return None


def remaining_days(buffer: bytes | bytearray, layout: RecordTableLayout, sponsor_id: int) -> int:
    """후원자 계약의 남은 일수를 반환한다."""
    if not layout.contains(buffer, sponsor_id):
        raise ValueError(error_text('sponsor_record_unavailable'))
    return read_value(buffer, layout.offset(sponsor_id) + REMAINING_DAYS_OFFSET, 'u16')


def write_remaining_days(buffer: bytearray, layout: RecordTableLayout, sponsor_id: int, days: int) -> None:
    """후원자 계약의 남은 일수를 16비트 범위로 기록한다."""
    if not layout.contains(buffer, sponsor_id):
        raise ValueError(error_text('sponsor_record_unavailable'))
    write_value(buffer, layout.offset(sponsor_id) + REMAINING_DAYS_OFFSET, 'u16', days)


def clear_contract_fields(
    buffer: bytearray,
    layout: RecordTableLayout,
    sponsor_id: int,
    cancelled_state: int,
    auxiliary_value: int | None = None,
) -> None:
    """계약 상태·남은 일수·선택적 종료 보조값을 초기화한다."""
    if not layout.contains(buffer, sponsor_id):
        raise ValueError(error_text('sponsor_record_unavailable'))
    offset = layout.offset(sponsor_id)
    write_value(buffer, offset + CONTRACT_STATE_OFFSET, 'u32', cancelled_state)
    write_value(buffer, offset + REMAINING_DAYS_OFFSET, 'u16', 0)
    if auxiliary_value is not None:
        write_value(buffer, offset + CONTRACT_AUXILIARY_OFFSET, 'u32', auxiliary_value)
