"""함선 세이브 레코드에서 UI와 독립적인 주소·비트 필드 계산."""


MAST_SLOT_COUNT = 3
MAST_SLOT_BITS = 2
FLEET_POOL_OFFSET = 0x499A
FLEET_RECORD_SIZE = 0x5D
FLEET_POOL_CAPACITY = 200
FLEET_FLAGSHIP_OFFSET = 0x48D9
FLEET_ACTIVE_SLOTS_OFFSET = 0x48DD
FLEET_ACTIVE_SLOT_COUNT = 8
UNUSED_FLEET_SLOT = 0xFFFF


def mast_count(value: int) -> int:
    """3개의 2비트 마스트 슬롯 중 설치된 마스트 수를 센다."""
    return sum(
        1 for index in range(MAST_SLOT_COUNT)
        if ((int(value) >> (index * MAST_SLOT_BITS)) & 0x03) != 0
    )


def pack_mast_slots(slot_codes) -> int:
    """메인·세브·선미 마스트 코드를 세이브의 1바이트 비트값으로 조합한다."""
    return sum((int(code) & 0x03) << (index * MAST_SLOT_BITS)
               for index, code in enumerate(slot_codes))


def fleet_slot_offset(ship_index: int) -> int:
    """선박 풀 인덱스에 대응하는 세이브 레코드 시작 오프셋을 반환한다."""
    return FLEET_POOL_OFFSET + int(ship_index) * FLEET_RECORD_SIZE


def active_ship_indices(buffer: bytes | bytearray) -> list[int]:
    """활성 함대 8칸에서 유효한 선박 풀 인덱스만 순서대로 읽는다."""
    required_size = FLEET_ACTIVE_SLOTS_OFFSET + FLEET_ACTIVE_SLOT_COUNT * 2
    if len(buffer) < required_size:
        return []
    indices = []
    for position in range(FLEET_ACTIVE_SLOT_COUNT):
        offset = FLEET_ACTIVE_SLOTS_OFFSET + position * 2
        ship_index = int.from_bytes(buffer[offset:offset + 2], 'little')
        if ship_index == UNUSED_FLEET_SLOT:
            continue
        if 0 <= ship_index < FLEET_POOL_CAPACITY and fleet_slot_offset(ship_index) + FLEET_RECORD_SIZE + 7 <= len(buffer):
            indices.append(ship_index)
    return indices


def flagship_position(buffer: bytes | bytearray) -> int | None:
    """기함으로 지정된 활성 함대 슬롯 위치를 반환한다."""
    if len(buffer) < FLEET_FLAGSHIP_OFFSET + 4:
        return None
    position = int.from_bytes(buffer[FLEET_FLAGSHIP_OFFSET:FLEET_FLAGSHIP_OFFSET + 4], 'little')
    return position if position < FLEET_ACTIVE_SLOT_COUNT else None


def write_active_ship_indices(buffer: bytearray, ship_indices) -> None:
    """활성 함대 슬롯을 주어진 순서로 기록하고 남은 칸은 미사용으로 초기화한다."""
    indices = [int(index) for index in ship_indices]
    if len(indices) > FLEET_ACTIVE_SLOT_COUNT:
        raise ValueError('active fleet slot count exceeds capacity')
    required_size = FLEET_ACTIVE_SLOTS_OFFSET + FLEET_ACTIVE_SLOT_COUNT * 2
    if len(buffer) < required_size:
        raise ValueError('save buffer is too small for active fleet slots')
    for position in range(FLEET_ACTIVE_SLOT_COUNT):
        value = indices[position] if position < len(indices) else UNUSED_FLEET_SLOT
        offset = FLEET_ACTIVE_SLOTS_OFFSET + position * 2
        buffer[offset:offset + 2] = value.to_bytes(2, 'little', signed=False)


def write_flagship_position(buffer: bytearray, position: int | None) -> None:
    """기함 슬롯을 기록하며 None은 기함 없음(FFFFFFFF)으로 저장한다."""
    if len(buffer) < FLEET_FLAGSHIP_OFFSET + 4:
        raise ValueError('save buffer is too small for flagship position')
    value = 0xFFFFFFFF if position is None else int(position)
    buffer[FLEET_FLAGSHIP_OFFSET:FLEET_FLAGSHIP_OFFSET + 4] = value.to_bytes(4, 'little', signed=False)
