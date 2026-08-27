"""소지품·보관함 16비트 아이템 슬롯 배열 처리."""

from __future__ import annotations


EMPTY_ITEM_SLOT = 0xFFFF
POCKET_SLOT_OFFSET = 175
POCKET_SLOT_CAPACITY = 16
STORAGE_SLOT_OFFSET = 207
STORAGE_SLOT_CAPACITY = 99


def read_item_slots(buffer: bytes | bytearray, offset: int, capacity: int) -> list[int]:
    """빈 슬롯을 제외하고 저장 순서대로 아이템 ID를 읽는다."""
    offset, capacity = int(offset), int(capacity)
    if offset < 0 or offset + capacity * 2 > len(buffer):
        raise ValueError('save buffer is too small for item slots')
    return [
        item_id for index in range(capacity)
        if (item_id := int.from_bytes(buffer[offset + index * 2:offset + index * 2 + 2], 'little'))
        != EMPTY_ITEM_SLOT
    ]


def write_item_slots(buffer: bytearray, offset: int, capacity: int, item_ids) -> None:
    """아이템 ID 목록을 기록하고 남은 슬롯은 빈 값으로 채운다."""
    offset, capacity = int(offset), int(capacity)
    if offset < 0 or offset + capacity * 2 > len(buffer):
        raise ValueError('save buffer is too small for item slots')
    values = [int(item_id) for item_id in item_ids]
    if len(values) > capacity:
        raise ValueError('item count exceeds slot capacity')
    for index in range(capacity):
        item_id = values[index] if index < len(values) else EMPTY_ITEM_SLOT
        buffer[offset + index * 2:offset + index * 2 + 2] = item_id.to_bytes(2, 'little', signed=False)
