"""후원자 계약 세이브 레코드의 필드 접근."""

from .resources import error_text
from .save_records import RecordTableLayout, read_value, write_value
CONTRACT_STATE_OFFSET = 8
REMAINING_DAYS_OFFSET = 14
CONTRACT_AUXILIARY_OFFSET = 20
WEALTH_OFFSET = 4

def active_sponsor_id(buffer, layout, sponsor_ids, active_state):
    """계약 상태 필드가 활성값인 첫 후원자 ID를 반환한다."""
    for sponsor_id in sponsor_ids:
        sponsor_id = int(sponsor_id)
        if not layout.contains(buffer, sponsor_id):
            continue
        offset = layout.offset(sponsor_id)
        if read_value(buffer, offset + CONTRACT_STATE_OFFSET, 'u32') == int(active_state):
            return sponsor_id
    return None

def remaining_days(buffer, layout, sponsor_id):
    """후원자 계약의 남은 일수를 반환한다."""
    if not layout.contains(buffer, sponsor_id):
        raise ValueError(error_text('sponsor_record_unavailable'))
    return read_value(buffer, layout.offset(sponsor_id) + REMAINING_DAYS_OFFSET, 'u16')

def write_remaining_days(buffer, layout, sponsor_id, days):
    """후원자 계약의 남은 일수를 16비트 범위로 기록한다."""
    if not layout.contains(buffer, sponsor_id):
        raise ValueError(error_text('sponsor_record_unavailable'))
    write_value(buffer, layout.offset(sponsor_id) + REMAINING_DAYS_OFFSET, 'u16', days)

def clear_contract_fields(buffer, layout, sponsor_id, cancelled_state, auxiliary_value=None):
    """계약 상태·남은 일수·선택적 종료 보조값을 초기화한다."""
    if not layout.contains(buffer, sponsor_id):
        raise ValueError(error_text('sponsor_record_unavailable'))
    offset = layout.offset(sponsor_id)
    write_value(buffer, offset + CONTRACT_STATE_OFFSET, 'u32', cancelled_state)
    write_value(buffer, offset + REMAINING_DAYS_OFFSET, 'u16', 0)
    if auxiliary_value is not None:
        write_value(buffer, offset + CONTRACT_AUXILIARY_OFFSET, 'u32', auxiliary_value)
