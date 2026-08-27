"""주인공 배우자 슬롯의 여급 ID 변환과 읽기·쓰기."""

from __future__ import annotations


SPOUSE_SLOT_OFFSET = 173
EMPTY_SPOUSE_SLOT = 0xFFFF
SPOUSE_PREFIX = 0x2000
SPOUSE_PREFIX_MASK = 0xFF00
SPOUSE_ID_MASK = 0x007F


def spouse_slot_code(barmaid_id: int) -> int:
    """여급 ID를 세이브의 배우자 슬롯 코드로 변환한다."""
    barmaid_id = int(barmaid_id)
    if not 0 <= barmaid_id <= SPOUSE_ID_MASK:
        raise ValueError('barmaid ID does not fit in spouse slot')
    return SPOUSE_PREFIX | barmaid_id


def spouse_barmaid_id(slot_code: int) -> int | None:
    """배우자 슬롯 코드에서 여급 ID를 읽고 빈/비배우자 값은 None으로 반환한다."""
    slot_code = int(slot_code) & 0xFFFF
    return slot_code & SPOUSE_ID_MASK if slot_code & SPOUSE_PREFIX_MASK == SPOUSE_PREFIX else None


def read_spouse_barmaid_id(buffer: bytes | bytearray) -> int | None:
    """세이브 버퍼의 배우자 슬롯에서 여급 ID를 읽는다."""
    if SPOUSE_SLOT_OFFSET + 2 > len(buffer):
        return None
    return spouse_barmaid_id(int.from_bytes(buffer[SPOUSE_SLOT_OFFSET:SPOUSE_SLOT_OFFSET + 2], 'little'))


def write_spouse_barmaid_id(buffer: bytearray, barmaid_id: int | None) -> None:
    """배우자 슬롯에 여급 ID 또는 배우자 없음 값을 기록한다."""
    if SPOUSE_SLOT_OFFSET + 2 > len(buffer):
        raise ValueError('save buffer is too small for spouse slot')
    value = EMPTY_SPOUSE_SLOT if barmaid_id is None else spouse_slot_code(barmaid_id)
    buffer[SPOUSE_SLOT_OFFSET:SPOUSE_SLOT_OFFSET + 2] = value.to_bytes(2, 'little')
