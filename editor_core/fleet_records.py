"""함선 세이브 레코드에서 UI와 독립적인 비트 필드 계산."""


MAST_SLOT_COUNT = 3
MAST_SLOT_BITS = 2


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
