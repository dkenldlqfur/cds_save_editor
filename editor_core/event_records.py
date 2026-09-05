"""이벤트 세이브 레코드의 완료 상태 읽기·쓰기."""
EVENT_RECORD_SIZE = 164
EVENT_COMPLETED_OFFSET = 0
EVENT_DISCOVERER_OFFSET = 1

def event_is_completed(buffer, offset):
    """이벤트 레코드의 완료 여부를 원본 두 상태 바이트 기준으로 반환한다."""
    offset = int(offset)
    if offset < 0 or offset + 2 > len(buffer):
        return False
    return buffer[offset + EVENT_COMPLETED_OFFSET] != 0 or buffer[offset + EVENT_DISCOVERER_OFFSET] != 0
