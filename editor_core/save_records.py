"""세이브 바이너리 레코드의 공용 읽기·쓰기 도구.

Tkinter나 게임 데이터 JSON에 의존하지 않아, 저장 구조를 다루는 코드를 UI와
분리해서 테스트·재사용할 수 있다.
"""
import struct
VALUE_FORMATS = {'u8': '<B', 'u16': '<H', 'u32': '<I', 'i16': '<h', 'i32': '<i'}
VALUE_LIMITS = {'u8': (0, 255), 'u16': (0, 65535), 'u32': (0, 4294967295), 'i16': (-32768, 32767), 'i32': (-2147483648, 2147483647)}

class RecordTableLayout:
    """세이브 파일 안에 연속 저장된 고정 길이 레코드 배열의 레이아웃."""

    def __init__(self, base_offset, record_size, record_count):
        self.base_offset = int(base_offset)
        self.record_size = int(record_size)
        self.record_count = int(record_count)

    def offset(self, record_index):
        """레코드 순번에 대응하는 시작 오프셋을 반환한다."""
        return record_offset(self.base_offset, self.record_size, record_index)

    @property
    def end_offset(self):
        """마지막 레코드 바로 다음의 오프셋을 반환한다."""
        return self.base_offset + self.record_size * self.record_count

    def contains(self, buffer, record_index):
        """지정한 전체 레코드가 버퍼 안에 존재하는지 확인한다."""
        offset = self.offset(record_index)
        return 0 <= record_index < self.record_count and offset + self.record_size <= len(buffer)

    def can_reset(self, buffer, original_buffer):
        """전체 테이블을 원본 버퍼로 되돌릴 수 있는지 확인한다."""
        return self.end_offset <= len(buffer) and self.end_offset <= len(original_buffer)

    def is_changed(self, buffer, original_buffer):
        """테이블이 최초 로드 상태와 다른지 반환한다."""
        return self.can_reset(buffer, original_buffer) and buffer[self.base_offset:self.end_offset] != original_buffer[self.base_offset:self.end_offset]

    def reset(self, buffer, original_buffer):
        """테이블 전체를 최초 로드 상태로 복원한다."""
        if not self.can_reset(buffer, original_buffer):
            return False
        buffer[self.base_offset:self.end_offset] = original_buffer[self.base_offset:self.end_offset]
        return True

def record_offset(base_offset, record_size, index):
    """고정 길이 레코드 배열의 지정 인덱스 오프셋을 반환한다."""
    return int(base_offset) + int(index) * int(record_size)

def read_value(buffer, offset, kind):
    """지정한 정수 형식으로 세이브 버퍼에서 값을 읽는다."""
    return struct.unpack_from(VALUE_FORMATS[kind], buffer, offset)[0]

def write_value(buffer, offset, kind, value):
    """형식별 범위 안으로 보정한 값을 세이브 버퍼에 기록한다."""
    low, high = VALUE_LIMITS[kind]
    struct.pack_into(VALUE_FORMATS[kind], buffer, offset, max(low, min(high, int(value))))

def read_character_name(buffer, record_offset, fallback, encoding='cp949'):
    """인물 레코드의 성·이름 필드를 안전하게 조합한다."""
    first_name = buffer[record_offset + 50:record_offset + 50 + 20]
    last_name = buffer[record_offset + 69:record_offset + 69 + 19]
    first_name = first_name.split(b'\x00')[0].decode(encoding, errors='ignore').strip()
    last_name = last_name.split(b'\x00')[0].decode(encoding, errors='ignore').strip()
    return ' '.join((part for part in (first_name, last_name) if part)) or fallback

def read_character_stat_values(buffer, record_offset, special_stat_offset):
    """인물 공통 능력치 8개를 저장 순서대로 반환한다."""
    return (buffer[record_offset + 0], buffer[record_offset + 1], buffer[record_offset + 2], buffer[record_offset + 3], buffer[record_offset + 4], buffer[record_offset + 5], buffer[record_offset + 102], struct.unpack_from('<I', buffer, record_offset + special_stat_offset)[0])
