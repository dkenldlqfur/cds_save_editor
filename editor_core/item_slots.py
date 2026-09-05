"""소지품·보관함 16비트 아이템 슬롯 배열 처리."""

from .resources import error_text
EMPTY_ITEM_SLOT = 65535
POCKET_SLOT_OFFSET = 175
POCKET_SLOT_CAPACITY = 16
STORAGE_SLOT_OFFSET = 207
STORAGE_SLOT_CAPACITY = 99

def read_item_slots(buffer, offset, capacity):
    """빈 슬롯을 제외하고 저장 순서대로 아이템 ID를 읽는다."""
    offset, capacity = (int(offset), int(capacity))
    if offset < 0 or offset + capacity * 2 > len(buffer):
        raise ValueError(error_text('item_slots_buffer_too_small'))
    result = []
    for index in range(capacity):
        item_id = int.from_bytes(buffer[offset + index * 2:offset + index * 2 + 2], 'little')
        if item_id != EMPTY_ITEM_SLOT:
            result.append(item_id)
    return result

def write_item_slots(buffer, offset, capacity, item_ids):
    """아이템 ID 목록을 기록하고 남은 슬롯은 빈 값으로 채운다."""
    offset, capacity = (int(offset), int(capacity))
    if offset < 0 or offset + capacity * 2 > len(buffer):
        raise ValueError(error_text('item_slots_buffer_too_small'))
    values = [int(item_id) for item_id in item_ids]
    if len(values) > capacity:
        raise ValueError(error_text('item_capacity_exceeded'))
    for index in range(capacity):
        item_id = values[index] if index < len(values) else EMPTY_ITEM_SLOT
        buffer[offset + index * 2:offset + index * 2 + 2] = item_id.to_bytes(2, 'little', signed=False)
