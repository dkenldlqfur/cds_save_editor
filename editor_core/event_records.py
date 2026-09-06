"""이벤트 세이브 레코드의 완료 상태 읽기·쓰기."""

from __future__ import annotations


EVENT_RECORD_SIZE = 164
# save_offset은 마커 다음 바이트를 가리킨다. 다음 save_offset과의 간격은
# 164바이트이므로 현재 레코드에서 쓸 수 있는 payload는 163바이트뿐이다.
EVENT_RECORD_PAYLOAD_SIZE = EVENT_RECORD_SIZE - 1
EVENT_ACTIVE_MARKER = 0x08
EVENT_COMPLETED_OFFSET = 0x00
EVENT_DISCOVERER_OFFSET = 0x01
EVENT_DISCOVERER_SIZE = 18
EVENT_COMPLETED_AUX_OFFSET = 0x58
EVENT_EMPTY_FF_RANGES = ((0x28, 8), (0x57, 8), (0x86, 8))


def event_is_completed(buffer: bytes | bytearray, offset: int) -> bool:
    """이벤트 레코드의 완료 여부를 원본 두 상태 바이트 기준으로 반환한다."""
    offset = int(offset)
    if offset < 0 or offset + 2 > len(buffer):
        return False
    return buffer[offset + EVENT_COMPLETED_OFFSET] != 0 or buffer[offset + EVENT_DISCOVERER_OFFSET] != 0


def write_event_completion(buffer: bytearray, offset: int, completed: bool,
                           discoverer: bytes = b'') -> None:
    """이벤트 완료 상태를 기록하되 다음 레코드의 마커를 보존한다."""
    offset = int(offset)
    if offset < 1 or offset + EVENT_RECORD_PAYLOAD_SIZE > len(buffer):
        raise IndexError('event record offset is outside the save buffer')

    buffer[offset - 1] = EVENT_ACTIVE_MARKER
    if completed:
        buffer[offset + EVENT_COMPLETED_OFFSET] = 1
        start = offset + EVENT_DISCOVERER_OFFSET
        buffer[start:start + EVENT_DISCOVERER_SIZE] = b'\x00' * EVENT_DISCOVERER_SIZE
        buffer[start:start + min(len(discoverer), EVENT_DISCOVERER_SIZE)] = discoverer[:EVENT_DISCOVERER_SIZE]
        buffer[offset + EVENT_COMPLETED_AUX_OFFSET] = 0xFF
        return

    # 게임이 만드는 미완료 이벤트의 빈 payload 형식을 복원한다.
    buffer[offset:offset + EVENT_RECORD_PAYLOAD_SIZE] = b'\x00' * EVENT_RECORD_PAYLOAD_SIZE
    for relative_offset, size in EVENT_EMPTY_FF_RANGES:
        start = offset + relative_offset
        buffer[start:start + size] = b'\xFF' * size


def sync_event_completion(buffer: bytearray, offset: int, completed: bool,
                          discoverer: bytes = b'') -> bool:
    """요청 상태가 다를 때만 이벤트 레코드를 쓰고 변경 여부를 반환한다."""
    completed = bool(completed)
    if completed == event_is_completed(buffer, offset):
        return False
    write_event_completion(buffer, offset, completed, discoverer)
    return True
