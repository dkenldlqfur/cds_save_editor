"""발견물 상태 마커와 힌트 상태 비트 처리."""

from __future__ import annotations


DISCOVERY_UNSPAWNED = 0
DISCOVERY_UNDISCOVERED = 1
DISCOVERY_DISCOVERED = 2
DISCOVERY_REPORTED = 3

STATE_MARKERS = {
    DISCOVERY_UNSPAWNED: 0x00,
    DISCOVERY_UNDISCOVERED: 0x0C,
    DISCOVERY_DISCOVERED: 0x4C,
    DISCOVERY_REPORTED: 0xCC,
}

# 힌트의 bit0은 획득, bit2는 계약 연결이며 둘을 함께 다룬다.
HINT_ACQUIRED_AND_CONTRACT_BITS = 0x05


def state_from_marker(marker: int) -> int:
    """세이브 상태 마커를 화면용 0~3 상태값으로 변환한다."""
    marker = int(marker) & 0xFF
    if marker & 0xC0 == 0xC0:
        return DISCOVERY_REPORTED
    if marker & 0x40:
        return DISCOVERY_DISCOVERED
    return DISCOVERY_UNDISCOVERED if marker else DISCOVERY_UNSPAWNED


def marker_for_state(state: int) -> int:
    """화면용 0~3 상태값에 대응하는 세이브 상태 마커를 반환한다."""
    return STATE_MARKERS.get(int(state), STATE_MARKERS[DISCOVERY_UNSPAWNED])


def hint_is_acquired_and_contract_linked(value: int) -> bool:
    """힌트가 획득되어 현재 계약과 연결된 상태인지 반환한다."""
    return int(value) & HINT_ACQUIRED_AND_CONTRACT_BITS == HINT_ACQUIRED_AND_CONTRACT_BITS


def set_hint_acquired(value: int, acquired: bool) -> int:
    """발견 완료 비트 등 다른 힌트 상태는 보존하고 획득/계약 비트만 설정한다."""
    return (int(value) | HINT_ACQUIRED_AND_CONTRACT_BITS if acquired
            else int(value) & ~HINT_ACQUIRED_AND_CONTRACT_BITS)
