"""세이브 바이너리 레코드의 공용 읽기·쓰기 도구.

Tkinter나 게임 데이터 JSON에 의존하지 않아, 저장 구조를 다루는 코드를 UI와
분리해서 테스트·재사용할 수 있다.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


VALUE_FORMATS = {
    'u8': '<B',
    'u16': '<H',
    'u32': '<I',
    'i16': '<h',
    'i32': '<i',
}

VALUE_LIMITS = {
    'u8': (0, 0xFF),
    'u16': (0, 0xFFFF),
    'u32': (0, 0xFFFFFFFF),
    'i16': (-0x8000, 0x7FFF),
    'i32': (-0x80000000, 0x7FFFFFFF),
}


@dataclass(frozen=True)
class RecordTableLayout:
    """세이브 파일 안에 연속 저장된 고정 길이 레코드 배열의 레이아웃."""

    base_offset: int
    record_size: int
    record_count: int

    def offset(self, record_index: int) -> int:
        """레코드 순번에 대응하는 시작 오프셋을 반환한다."""
        return record_offset(self.base_offset, self.record_size, record_index)

    @property
    def end_offset(self) -> int:
        """마지막 레코드 바로 다음의 오프셋을 반환한다."""
        return self.base_offset + self.record_size * self.record_count

    def contains(self, buffer: bytes | bytearray, record_index: int) -> bool:
        """지정한 전체 레코드가 버퍼 안에 존재하는지 확인한다."""
        offset = self.offset(record_index)
        return 0 <= record_index < self.record_count and offset + self.record_size <= len(buffer)

    def can_reset(self, buffer: bytes | bytearray, original_buffer: bytes | bytearray) -> bool:
        """전체 테이블을 원본 버퍼로 되돌릴 수 있는지 확인한다."""
        return self.end_offset <= len(buffer) and self.end_offset <= len(original_buffer)

    def is_changed(self, buffer: bytes | bytearray, original_buffer: bytes | bytearray) -> bool:
        """테이블이 최초 로드 상태와 다른지 반환한다."""
        return self.can_reset(buffer, original_buffer) and (
            buffer[self.base_offset:self.end_offset] != original_buffer[self.base_offset:self.end_offset]
        )

    def reset(self, buffer: bytearray, original_buffer: bytes | bytearray) -> bool:
        """테이블 전체를 최초 로드 상태로 복원한다."""
        if not self.can_reset(buffer, original_buffer):
            return False
        buffer[self.base_offset:self.end_offset] = original_buffer[self.base_offset:self.end_offset]
        return True


def record_offset(base_offset: int, record_size: int, index: int) -> int:
    """고정 길이 레코드 배열의 지정 인덱스 오프셋을 반환한다."""
    return int(base_offset) + int(index) * int(record_size)


def read_value(buffer: bytes | bytearray, offset: int, kind: str) -> int:
    """지정한 정수 형식으로 세이브 버퍼에서 값을 읽는다."""
    return struct.unpack_from(VALUE_FORMATS[kind], buffer, offset)[0]


def write_value(buffer: bytearray, offset: int, kind: str, value: int) -> None:
    """형식별 범위 안으로 보정한 값을 세이브 버퍼에 기록한다."""
    low, high = VALUE_LIMITS[kind]
    struct.pack_into(VALUE_FORMATS[kind], buffer, offset, max(low, min(high, int(value))))


def read_character_name(
    buffer: bytes | bytearray,
    record_offset: int,
    fallback: str,
    *,
    encoding: str = 'cp949',
) -> str:
    """인물 레코드의 성·이름 필드를 안전하게 조합한다."""
    first_name = buffer[record_offset + 0x32:record_offset + 0x32 + 20]
    last_name = buffer[record_offset + 0x45:record_offset + 0x45 + 19]
    first_name = first_name.split(b'\0')[0].decode(encoding, errors='ignore').strip()
    last_name = last_name.split(b'\0')[0].decode(encoding, errors='ignore').strip()
    return ' '.join(part for part in (first_name, last_name) if part) or fallback


def read_character_stat_values(
    buffer: bytes | bytearray,
    record_offset: int,
    special_stat_offset: int,
) -> tuple[int, ...]:
    """인물 공통 능력치 8개를 저장 순서대로 반환한다."""
    return (
        buffer[record_offset + 0x00], buffer[record_offset + 0x01],
        buffer[record_offset + 0x02], buffer[record_offset + 0x03],
        buffer[record_offset + 0x04], buffer[record_offset + 0x05],
        buffer[record_offset + 0x66],
        struct.unpack_from('<I', buffer, record_offset + special_stat_offset)[0],
    )
