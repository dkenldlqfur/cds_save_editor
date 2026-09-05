"""발견물 상태 마커와 힌트 상태 비트 처리."""
DISCOVERY_UNSPAWNED = 0
DISCOVERY_UNDISCOVERED = 1
DISCOVERY_DISCOVERED = 2
DISCOVERY_REPORTED = 3
STATE_MARKERS = {DISCOVERY_UNSPAWNED: 0, DISCOVERY_UNDISCOVERED: 12, DISCOVERY_DISCOVERED: 76, DISCOVERY_REPORTED: 204}
HINT_ACQUIRED_AND_CONTRACT_BITS = 5

def state_from_marker(marker):
    """세이브 상태 마커를 화면용 0~3 상태값으로 변환한다."""
    marker = int(marker) & 255
    if marker & 192 == 192:
        return DISCOVERY_REPORTED
    if marker & 64:
        return DISCOVERY_DISCOVERED
    return DISCOVERY_UNDISCOVERED if marker else DISCOVERY_UNSPAWNED

def marker_for_state(state):
    """화면용 0~3 상태값에 대응하는 세이브 상태 마커를 반환한다."""
    return STATE_MARKERS.get(int(state), STATE_MARKERS[DISCOVERY_UNSPAWNED])

def hint_is_acquired_and_contract_linked(value):
    """힌트가 획득되어 현재 계약과 연결된 상태인지 반환한다."""
    return int(value) & HINT_ACQUIRED_AND_CONTRACT_BITS == HINT_ACQUIRED_AND_CONTRACT_BITS

def set_hint_acquired(value, acquired):
    """발견 완료 비트 등 다른 힌트 상태는 보존하고 획득/계약 비트만 설정한다."""
    return int(value) | HINT_ACQUIRED_AND_CONTRACT_BITS if acquired else int(value) & ~HINT_ACQUIRED_AND_CONTRACT_BITS
