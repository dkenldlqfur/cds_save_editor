"""일반 인물의 부관·항해사·측량사·통역사 역할 슬롯 처리."""

from __future__ import annotations

from .resources import error_text

EMPTY_ROLE_SLOT = 0xFFFF
ROLE_CHARACTER_PREFIX = 0x1000
ROLE_CHARACTER_MASK = 0xFF00


def role_slot_code(character_id: int) -> int:
    """인물 ID를 세이브의 역할 슬롯 16비트 코드로 변환한다."""
    character_id = int(character_id)
    if not 0 <= character_id <= 0xFF:
        raise ValueError(error_text('role_character_id_out_of_range'))
    return ROLE_CHARACTER_PREFIX | character_id


def role_character_id(slot_code: int) -> int | None:
    """역할 슬롯 코드에서 인물 ID를 읽고 빈/비인물 코드는 None으로 반환한다."""
    slot_code = int(slot_code) & 0xFFFF
    return slot_code & 0xFF if slot_code & ROLE_CHARACTER_MASK == ROLE_CHARACTER_PREFIX else None


def read_role_character_id(buffer: bytes | bytearray, offset: int) -> int | None:
    """세이브 버퍼의 역할 슬롯에서 인물 ID를 읽는다."""
    offset = int(offset)
    if offset < 0 or offset + 2 > len(buffer):
        return None
    return role_character_id(int.from_bytes(buffer[offset:offset + 2], 'little'))


def write_role_character_id(buffer: bytearray, offset: int, character_id: int | None) -> None:
    """역할 슬롯에 인물 ID 또는 빈 슬롯을 기록한다."""
    offset = int(offset)
    if offset < 0 or offset + 2 > len(buffer):
        raise ValueError(error_text('role_slot_buffer_too_small'))
    value = EMPTY_ROLE_SLOT if character_id is None else role_slot_code(character_id)
    buffer[offset:offset + 2] = value.to_bytes(2, 'little')


def active_role_character_ids(buffer: bytes | bytearray, role_offsets) -> frozenset[int]:
    """여러 역할 슬롯에서 현재 배정된 인물 ID 집합을 반환한다."""
    return frozenset(
        character_id
        for offset in role_offsets
        for character_id in (read_role_character_id(buffer, offset),)
        if character_id is not None
    )
