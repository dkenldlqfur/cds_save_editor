"""Read verified static master data from a CDS III Windows executable."""

from dataclasses import dataclass
from pathlib import Path
import struct
from typing import Callable

from .game_data_profile import GameDataProfile


CHARACTER_TABLE_FILE_OFFSET = 0x0DD9F0
CHARACTER_RECORD_SIZE = 0xCC
CHARACTER_RECORD_COUNT = 205

BARMAID_TABLE_VA = 0x517AF8
BARMAID_RECORD_SIZE = 0x28
BARMAID_RECORD_COUNT = 127
BARMAID_APPEARANCE_YEAR_REFERENCE = 1495
BARMAID_CHILD_APTITUDE_TABLE_VA = 0x51B0A0
BARMAID_CHILD_APTITUDE_RECORD_SIZE = 0x20

SPONSOR_TABLE_VA = 0x5228BC
SPONSOR_RECORD_SIZE = 0x3C
SPONSOR_RECORD_COUNT = 81
# The documented table address points at ``face_code``.  Each sponsor's name
# pointer is the DWORD immediately before that numeric record.  Reading +0x38
# instead reads the next sponsor's name pointer and shifts every displayed name.
SPONSOR_NAME_POINTER_OFFSET = -0x04

CITY_TABLE_VA = 0x4D14B0
CITY_RECORD_SIZE = 0x88
CITY_RECORD_COUNT = 226
CITY_GOODS_SUPPLY_BY_SIZE = (20, 50, 100, 200, 350, 500, 700, 1000)
CITY_TRADE_REGION_MAX = 26
CITY_SPECIALTY_ID_MAX = 69
DISCOVERY_TABLE_VA = 0x51C584
DISCOVERY_RECORD_SIZE = 0x5C
DISCOVERY_RECORD_COUNT = 231
DISCOVERY_CONTIGUOUS_RECORD_COUNT = 230
DISCOVERY_FINAL_COORDINATE_RECORD_VA = 0x5227A0

TRADE_GOOD_TABLE_VA = 0x4DCBBC
TRADE_GOOD_RECORD_SIZE = 0x88
TRADE_GOOD_RECORD_COUNT = 70
TRADE_GOOD_NAME_POINTER_OFFSET = 0x7C
TRADE_GOOD_NAME_RECORD_SHIFT = -1
TRADE_REGION_GOODS_TABLE_VA = 0x4DF0E0
TRADE_REGION_COUNT = CITY_TRADE_REGION_MAX + 1
TRADE_REGION_GOODS_PER_REGION = 5

SHIP_TYPE_TABLE_VA = 0x4FC1E0
SHIP_TYPE_RECORD_COUNT = 8
SHIP_TYPE_RECORD_SIZE = 0x40
SHIP_TYPE_MIN_CREW_DISPLAY_OFFSET = 10

ITEM_TABLE_VA = 0x4FD558
ITEM_RECORD_COUNT = 286
ITEM_RECORD_SIZE = 0x1C
ITEM_NO_IMAGE_ID = 0xFFFFFFFF
ITEM_PRICE_MAX = 99_999_999
ITEM_EFFECT_MAX = 255

FIGUREHEAD_EFFECT_MAGIC = b'CDSFHE1\0'
FIGUREHEAD_EFFECT_VERSION = 1
FIGUREHEAD_EFFECT_CONFIG_OFFSET = 0x0C
FIGUREHEAD_EFFECT_KEYS = (
    'disaster_grade1_chance',
    'disaster_grade2_chance',
    'disaster_grade3_chance',
    'cannon_damage_reduction',
    'shooting_damage_reduction',
    'melee_damage_reduction',
    'cannon_attack_percent',
    'shooting_attack_percent',
    'melee_attack_percent',
    'hull_recovery',
    'movement_bonus',
    'movement_maximum',
    'special_cannon_attack_percent',
    'all_attack_percent',
)
FIGUREHEAD_EFFECT_DEFAULT_VALUES = (
    11, 41, 71, 20, 50, 70, 120, 150, 200, 5, 1, 6, 200, 150,
)
FIGUREHEAD_EFFECT_HOOK_TARGETS = (
    (0x434C38, 0x080, 0xE9),
    (0x4366AD, 0x100, 0xE9),
    (0x43674F, 0x180, 0xE9),
    (0x437065, 0x200, 0xE9),
    (0x43D884, 0x300, 0xE9),
    (0x439E13, 0x380, 0xE9),
    (0x47473C, 0x480, 0xE8),
    (0x4748B8, 0x480, 0xE8),
    (0x474A64, 0x480, 0xE8),
    (0x474B95, 0x480, 0xE8),
    (0x474C7F, 0x480, 0xE8),
)

LIMIT_OPERANDS = {
    'cash': (
        (0x4059B5, b'\x3D'), (0x4059D0, b'\xB8'),
        (0x460B61, b'\x81\xFE'), (0x460B6A, b'\xB8'),
        (0x47CBC8, b'\x68'), (0x48252A, b'\x3D'),
        (0x482541, b'\xC7\x81\xA8\x00\x00\x00'),
    ),
    'deposit': (
        (0x460ACB, b'\x81\xFF'), (0x460AD4, b'\xB8'),
        (0x47CC08, b'\x68'),
    ),
}

# Fame and infamy share a clamp at 0x4800E0; the operand at 0x474188 is the
# voyage-food limit, not a reputation limit.  The patcher optionally replaces
# the shared PUSH with a verified per-field wrapper in its .patch section.
PLAYER_FAME_LIMIT_HOOK_VA = 0x4800E5
PLAYER_FAME_LIMIT_HOOK_END_VA = PLAYER_FAME_LIMIT_HOOK_VA + 5
PLAYER_FAME_LIMIT_CODE_OFFSET = 0x20
PLAYER_FAME_LIMIT_SLOT_SIZE = 0x100
PLAYER_FAME_LIMIT_MAGIC = b'FAMELIM1'
FAME_INFAMY_LIMIT_MIN = 1
FAME_INFAMY_LIMIT_MAX = 99_999_999

# ``cds_exe_patcher`` replaces the shared six-ability clamp when its value is
# changed.  These signatures accept both the original executable and that
# verified replacement, so the save editor follows the exact gameplay cap.
PERSON_ABILITY_LIMIT_VA = 0x432C50
PERSON_ABILITY_LIMIT_BLOCK_SIZE = 0x30
PERSON_VITALITY_LIMIT_VA = 0x432C87
PERSON_ABILITY_MAX = 255
PERSON_VITALITY_MAX = 9999
PERSON_ABILITY_ORIGINAL_CODE = bytes.fromhex(
    '8b 44 24 04 56 6a 64 6a 01 8d 34 81 8b 4c 24 14 51 '
    '8b 06 40 50 e8 f6 b8 06 00 83 c4 10 48 89 06 5e c2 08 00'
).ljust(PERSON_ABILITY_LIMIT_BLOCK_SIZE, b'\xCC')
PERSON_VITALITY_ORIGINAL_PREFIX = bytes.fromhex('8b 44 24 04 56 8b f1 68')
PERSON_VITALITY_ORIGINAL_SUFFIX = bytes.fromhex(
    '6a 00 50 8b 4e 18 51 e8 c8 b8 06 00 83 c4 10 89 46 18 5e c2 04 00')


class ExecutableFormatError(ValueError):
    pass


class PEImage:
    """Minimal read-only PE32 address mapper; no external dependency needed."""

    def __init__(self, data: bytes):
        self.data = data
        try:
            if data[:2] != b'MZ':
                raise ExecutableFormatError('DOS MZ 헤더가 없습니다.')
            pe_offset = struct.unpack_from('<I', data, 0x3C)[0]
            if data[pe_offset:pe_offset + 4] != b'PE\0\0':
                raise ExecutableFormatError('PE 헤더가 없습니다.')
            machine, section_count = struct.unpack_from('<HH', data, pe_offset + 4)
            optional_size = struct.unpack_from('<H', data, pe_offset + 20)[0]
            optional_offset = pe_offset + 24
            if machine != 0x14C or struct.unpack_from('<H', data, optional_offset)[0] != 0x10B:
                raise ExecutableFormatError('지원하는 32비트 실행 파일이 아닙니다.')
            self.image_base = struct.unpack_from('<I', data, optional_offset + 28)[0]
            if self.image_base != 0x400000:
                raise ExecutableFormatError('지원하는 CDS III 실행 파일 기준 주소가 아닙니다.')
            self.size_of_headers = struct.unpack_from('<I', data, optional_offset + 60)[0]
            section_offset = optional_offset + optional_size
            self.sections = []
            for index in range(section_count):
                offset = section_offset + index * 40
                virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
                    '<IIII', data, offset + 8)
                self.sections.append((virtual_address, max(virtual_size, raw_size), raw_offset, raw_size))
        except (IndexError, struct.error) as error:
            raise ExecutableFormatError('PE 헤더가 손상되었습니다.') from error

    def va_to_offset(self, va: int) -> int:
        rva = int(va) - self.image_base
        if 0 <= rva < self.size_of_headers:
            return rva
        for virtual_address, span, raw_offset, raw_size in self.sections:
            if virtual_address <= rva < virtual_address + span:
                relative = rva - virtual_address
                if relative >= raw_size:
                    break
                offset = raw_offset + relative
                if 0 <= offset < len(self.data):
                    return offset
        raise ExecutableFormatError(f'EXE 주소 0x{va:X}을 파일 위치로 변환할 수 없습니다.')

    def offset_to_va(self, offset: int) -> int:
        """Map a raw file offset back to its loaded virtual address."""
        offset = int(offset)
        if 0 <= offset < self.size_of_headers:
            return self.image_base + offset
        for virtual_address, _span, raw_offset, raw_size in self.sections:
            relative = offset - raw_offset
            if 0 <= relative < raw_size:
                return self.image_base + virtual_address + relative
        raise ExecutableFormatError(
            f'파일 위치 0x{offset:X}를 EXE 주소로 변환할 수 없습니다.')

    def c_string(self, va: int, fallback: str = '', max_bytes: int = 128) -> str:
        if va == 0:
            return fallback
        offset = self.va_to_offset(va)
        end = self.data.find(b'\0', offset, min(len(self.data), offset + max_bytes))
        if end < 0:
            raise ExecutableFormatError(f'문자열 주소 0x{va:X}의 끝을 찾지 못했습니다.')
        try:
            value = self.data[offset:end].decode('cp949')
        except UnicodeDecodeError as error:
            raise ExecutableFormatError(f'문자열 주소 0x{va:X}을 CP949로 읽지 못했습니다.') from error
        if not value or any(ord(character) < 0x20 for character in value):
            raise ExecutableFormatError(f'문자열 주소 0x{va:X}의 내용이 올바르지 않습니다.')
        return value


@dataclass(frozen=True)
class ExecutableProfileResult:
    profile: GameDataProfile
    loaded_sections: tuple[str, ...]
    warnings: tuple[str, ...]
    limits: dict[str, int]


def _read_characters(image: PEImage) -> list[dict]:
    data = image.data
    table_end = CHARACTER_TABLE_FILE_OFFSET + CHARACTER_RECORD_SIZE * CHARACTER_RECORD_COUNT
    if table_end > len(data):
        raise ExecutableFormatError('인물 마스터 테이블 범위가 파일 밖입니다.')
    records = []
    for identifier in range(CHARACTER_RECORD_COUNT):
        offset = CHARACTER_TABLE_FILE_OFFSET + identifier * CHARACTER_RECORD_SIZE
        raw = list(struct.unpack_from('<51I', data, offset))
        first_name = image.c_string(raw[0])
        last_name = image.c_string(raw[1])
        signed = lambda index: struct.unpack_from('<i', data, offset + index * 4)[0]
        if raw[3] not in (0, 1) or not -1 <= signed(12) < CITY_RECORD_COUNT:
            raise ExecutableFormatError(f'인물 {identifier}번의 성별 또는 초기 도시가 올바르지 않습니다.')
        records.append({
            'id': identifier,
            'name': f'{first_name} {last_name}'.strip(),
            'first_name': first_name,
            'last_name': last_name,
            'face_code': raw[2],
            'gender': raw[3],
            'age_at_1480': signed(4),
            'unknown_0x14': raw[5],
            'nation_id': signed(6),
            'job_id': signed(7),
            'unknown_0x20': raw[8],
            'fame': raw[9],
            'infamy': raw[10],
            'hire_state': signed(11),
            'city_id': signed(12),
            'building_id': signed(13),
            'blood_id': signed(14),
            'hire_cost_coefficient': raw[15],
            'abilities': raw[16:21],
            'faith': raw[21],
            'vitality': raw[22],
            'appearance_state': raw[23],
            'skills': raw[24:51],
            'raw_dwords': raw,
        })
    return records


def _read_barmaids(image: PEImage, fallback: GameDataProfile) -> tuple[list[dict], list[list[int]]]:
    data = image.data
    table_offset = image.va_to_offset(BARMAID_TABLE_VA)
    aptitude_offset = image.va_to_offset(BARMAID_CHILD_APTITUDE_TABLE_VA)
    fallback_rows = fallback.resource('spouse_aptitudes')['records']
    records = []
    aptitude_rows = []
    for identifier in range(BARMAID_RECORD_COUNT):
        offset = table_offset + identifier * BARMAID_RECORD_SIZE
        name_pointer, face_code = struct.unpack_from('<II', data, offset)
        year_delta = struct.unpack_from('<i', data, offset + 0x08)[0]
        personality_id = struct.unpack_from('<I', data, offset + 0x18)[0]
        language_flags = struct.unpack_from('<I', data, offset + 0x20)[0]
        city_id = struct.unpack_from('<I', data, offset + 0x24)[0]
        if not 0 <= face_code <= 143 or not 0 <= personality_id < 8 or not 0 <= city_id < CITY_RECORD_COUNT:
            raise ExecutableFormatError(f'여급 {identifier}번 마스터 값이 올바르지 않습니다.')
        if language_flags & ~((1 << 14) - 1):
            raise ExecutableFormatError(f'여급 {identifier}번 언어 비트가 올바르지 않습니다.')
        records.append({
            'id': identifier,
            'name': image.c_string(name_pointer),
            'face_code': face_code,
            'year': max(1480, BARMAID_APPEARANCE_YEAR_REFERENCE - year_delta),
            'city_id': city_id,
            'personality_ids': [personality_id],
            'language_flags': language_flags,
        })
        modifier_offset = aptitude_offset + face_code * BARMAID_CHILD_APTITUDE_RECORD_SIZE
        modifiers = list(struct.unpack_from('<6i', data, modifier_offset))
        if any(not -255 <= value <= 255 for value in modifiers):
            raise ExecutableFormatError(f'여급 {identifier}번 자녀 적성값이 올바르지 않습니다.')
        trailing = list(fallback_rows[identifier][-2:]) if len(fallback_rows[identifier]) >= 9 else [0, 0]
        aptitude_rows.append([face_code, *modifiers, *trailing])
    return records, aptitude_rows


def _read_sponsors(image: PEImage, fallback: GameDataProfile) -> list[dict]:
    data = image.data
    table_offset = image.va_to_offset(SPONSOR_TABLE_VA)
    fallback_by_id = fallback.sponsor_by_id
    records = []
    for identifier in range(SPONSOR_RECORD_COUNT):
        offset = table_offset + identifier * SPONSOR_RECORD_SIZE
        values = list(struct.unpack_from('<14I', data, offset))
        signed = lambda index: struct.unpack_from('<i', data, offset + index * 4)[0]
        packed_flags = values[13]
        fallback_record = fallback_by_id[identifier]
        name_pointer = struct.unpack_from(
            '<I', data, offset + SPONSOR_NAME_POINTER_OFFSET)[0]
        name = image.c_string(name_pointer, fallback=str(fallback_record['name']))
        appearance_year = 1480 + signed(4)
        if values[1] not in (0, 1) or not 0 <= signed(8) < CITY_RECORD_COUNT or not 0 <= signed(9) <= 15:
            raise ExecutableFormatError(f'후원자 {identifier}번 마스터 값이 올바르지 않습니다.')
        records.append({
            'id': identifier,
            'name': name,
            'face_code': values[0],
            'gender': values[1],
            'nation_id': signed(2),
            'job_id': signed(3),
            'appearance_year': appearance_year,
            'appearance_year_offset': signed(4),
            'unknown_0x14': values[5],
            'unknown_0x18': values[6],
            'power': values[7],
            'city_id': signed(8),
            'building_id': signed(9),
            'wealth_factor': values[10],
            'appraisal': values[11],
            'unknown_0x30': values[12],
            'preference_flags_exe': packed_flags & 0xFF,
            'language_flags': (packed_flags >> 16) & ((1 << 14) - 1),
            'name_pointer': name_pointer,
            'raw_dwords': [name_pointer] + values,
        })
    return records


def _read_trade_goods(image: PEImage) -> list[dict]:
    table_offset = image.va_to_offset(TRADE_GOOD_TABLE_VA)
    records = []
    for identifier in range(TRADE_GOOD_RECORD_COUNT):
        offset = table_offset + (identifier + TRADE_GOOD_NAME_RECORD_SHIFT) * TRADE_GOOD_RECORD_SIZE
        name_pointer = struct.unpack_from('<I', image.data, offset + TRADE_GOOD_NAME_POINTER_OFFSET)[0]
        records.append({'id': identifier, 'name': image.c_string(name_pointer)})
    return records


def _read_trade_regions(image: PEImage) -> list[dict]:
    """Read all common goods and their base prices for the 27 trade regions."""
    data = image.data
    goods_table_offset = image.va_to_offset(TRADE_REGION_GOODS_TABLE_VA)
    price_table_offset = image.va_to_offset(TRADE_GOOD_TABLE_VA)
    regions = []
    for region_id in range(TRADE_REGION_COUNT):
        goods = list(struct.unpack_from(
            f'<{TRADE_REGION_GOODS_PER_REGION}i', data,
            goods_table_offset + region_id * TRADE_REGION_GOODS_PER_REGION * 4,
        ))
        if any(not -1 <= good_id < TRADE_GOOD_RECORD_COUNT for good_id in goods):
            raise ExecutableFormatError(
                f'교역권 {region_id}번의 공통 교역품이 올바르지 않습니다.')
        base_prices = []
        for good_id in goods:
            if good_id < 0:
                base_prices.append(-1)
                continue
            price = struct.unpack_from(
                '<i', data,
                price_table_offset + good_id * TRADE_GOOD_RECORD_SIZE + region_id * 4,
            )[0]
            if not 0 <= price <= ITEM_PRICE_MAX:
                raise ExecutableFormatError(
                    f'교역권 {region_id}번, 교역품 {good_id}번의 기준가가 올바르지 않습니다.')
            base_prices.append(price)
        regions.append({
            'region_id': region_id,
            'goods': goods,
            'base_prices': base_prices,
        })
    return regions


def _read_ship_types(image: PEImage) -> dict[str, dict]:
    """Read the eight ship-type definitions used to create and limit ships."""
    data = image.data
    table_offset = image.va_to_offset(SHIP_TYPE_TABLE_VA)
    names = {}
    raw_table = {}
    default_masts = {}
    default_min_crew = {}
    for identifier in range(SHIP_TYPE_RECORD_COUNT):
        offset = table_offset + identifier * SHIP_TYPE_RECORD_SIZE
        values = list(struct.unpack_from('<16I', data, offset))
        name = image.c_string(values[0])
        (_, _, shipyard_requirement, base_power, power_limit, base_durability,
         durability_limit, base_weight, weight_limit, base_capacity,
         capacity_limit, base_cannons, cannon_limit, min_crew_stored,
         _unknown_0x38, mast_bits) = values
        min_crew = min_crew_stored + SHIP_TYPE_MIN_CREW_DISPLAY_OFFSET
        if (shipyard_requirement > 127 or base_power > power_limit or power_limit > 255
                or base_durability > durability_limit or base_cannons > cannon_limit
                or cannon_limit > 255 or base_weight > weight_limit
                or base_capacity > capacity_limit or min_crew > 265):
            raise ExecutableFormatError(
                f'선종 {identifier}번 마스터 값이 올바르지 않습니다.')
        key = str(identifier)
        names[key] = name
        raw_table[key] = values
        default_masts[key] = mast_bits
        default_min_crew[key] = min_crew
    return {
        'ship_types': names,
        'ship_raw_table': raw_table,
        'default_mast_values': default_masts,
        'default_min_crew': default_min_crew,
    }


def _item_display_category(identifier: int, executable_category: int) -> int:
    """Convert the EXE's final three category IDs to the editor display order."""
    # EXE: 6=선두상, 7=서적, 8=동물 / 에디터: 6=서적, 7=동물, 8=선두상.
    return {6: 8, 7: 6, 8: 7}.get(int(executable_category), int(executable_category))


def _read_items(image: PEImage) -> tuple[list[list], dict[str, dict]]:
    """Read item names, prices, effects, categories and resource image IDs."""
    data = image.data
    table_offset = image.va_to_offset(ITEM_TABLE_VA)
    master_rows = []
    stats = {}
    for identifier in range(ITEM_RECORD_COUNT):
        offset = table_offset + identifier * ITEM_RECORD_SIZE
        name_pointer, image_raw, buy_price, sell_price, effect_value, category_id, _ = (
            struct.unpack_from('<7I', data, offset))
        name = image.c_string(name_pointer, max_bytes=96)
        if (not 0 <= buy_price <= ITEM_PRICE_MAX
                or not 0 <= sell_price <= ITEM_PRICE_MAX
                or not 0 <= effect_value <= ITEM_EFFECT_MAX
                or not 0 <= category_id <= 8):
            raise ExecutableFormatError(
                f'아이템 {identifier}번 마스터 값이 올바르지 않습니다.')
        display_category = _item_display_category(identifier, category_id)
        master_rows.append([
            identifier, name, display_category, sell_price, buy_price,
        ])
        stats[str(identifier)] = {
            'buy_price': buy_price,
            'sell_price': sell_price,
            'stat': effect_value,
            'cat_code': category_id,
            'image_id': None if image_raw == ITEM_NO_IMAGE_ID else image_raw,
        }
    return master_rows, stats


def _validate_figurehead_effect_values(values: tuple[int, ...]) -> None:
    if len(values) != len(FIGUREHEAD_EFFECT_KEYS):
        raise ExecutableFormatError('선수상 효과 설정 개수가 올바르지 않습니다.')
    if any(not 0 <= value <= 100 for value in values[:6]):
        raise ExecutableFormatError('선수상 방지율 또는 피해 감소율이 올바르지 않습니다.')
    if any(not 0 <= values[index] <= 1000 for index in (6, 7, 8, 12, 13)):
        raise ExecutableFormatError('선수상 공격 배율이 올바르지 않습니다.')
    if not 0 <= values[9] <= 9999:
        raise ExecutableFormatError('선수상 내구 회복량이 올바르지 않습니다.')
    if not 0 <= values[10] <= 127 or not 1 <= values[11] <= 127:
        raise ExecutableFormatError('선수상 이동 효과가 올바르지 않습니다.')


def _read_figurehead_effects(image: PEImage) -> dict[str, int]:
    """Read original strengths or the executable patcher's editable settings."""
    data = image.data
    positions = []
    start = 0
    while True:
        position = data.find(FIGUREHEAD_EFFECT_MAGIC, start)
        if position < 0:
            break
        positions.append(position)
        start = position + 1
    if not positions:
        values = FIGUREHEAD_EFFECT_DEFAULT_VALUES
    else:
        if len(positions) != 1:
            raise ExecutableFormatError('선수상 효과 설정 블록이 중복되어 있습니다.')
        offset = positions[0]
        try:
            version = struct.unpack_from('<I', data, offset + 8)[0]
            if version != FIGUREHEAD_EFFECT_VERSION:
                raise ExecutableFormatError(
                    f'지원하지 않는 선수상 효과 설정 버전입니다: {version}')
            values = struct.unpack_from(
                f'<{len(FIGUREHEAD_EFFECT_KEYS)}I', data,
                offset + FIGUREHEAD_EFFECT_CONFIG_OFFSET,
            )
        except struct.error as error:
            raise ExecutableFormatError('선수상 효과 설정 블록이 손상되었습니다.') from error
        slot_va = image.offset_to_va(offset)
        for hook_va, stub_offset, opcode in FIGUREHEAD_EFFECT_HOOK_TARGETS:
            hook_offset = image.va_to_offset(hook_va)
            try:
                actual_opcode = data[hook_offset]
                relative = struct.unpack_from('<i', data, hook_offset + 1)[0]
            except (IndexError, struct.error) as error:
                raise ExecutableFormatError(
                    f'선수상 효과 연결 위치 0x{hook_va:X}가 손상되었습니다.') from error
            target_va = hook_va + 5 + relative
            if actual_opcode != opcode or target_va != slot_va + stub_offset:
                raise ExecutableFormatError(
                    f'선수상 효과 연결 위치 0x{hook_va:X}를 검증하지 못했습니다.')
    _validate_figurehead_effect_values(values)
    return dict(zip(FIGUREHEAD_EFFECT_KEYS, values))


def _read_cities(image: PEImage) -> list[dict]:
    """Read verified city defaults whose IDs are shared with save records."""
    data = image.data
    table_offset = image.va_to_offset(CITY_TABLE_VA)
    records = []
    for identifier in range(CITY_RECORD_COUNT):
        offset = table_offset + identifier * CITY_RECORD_SIZE
        values = list(struct.unpack_from('<34i', data, offset))
        name_pointer = values[0] & 0xFFFFFFFF
        world_x, world_y = values[1:3]
        inland_connection_ids = values[4:6]
        ship_candidate_mask = values[6]
        trade_region_id = values[7]
        culture_id = values[8]
        nation_id = values[9]
        shipyard_level = values[10]
        update_counter = values[11]
        specialty_id = values[12]
        specialty_price = values[13]
        specialty_supply_index = values[14]
        default_goods = values[15:23]
        city_status = values[23]
        packed_facilities = values[24] & 0xFFFFFFFF
        facility_flags = packed_facilities & 0xFFFF
        default_flags = packed_facilities >> 16
        if (not 0 <= world_x <= 2500 or not 0 <= world_y <= 1250
                or any(not -1 <= city_id < CITY_RECORD_COUNT
                       for city_id in inland_connection_ids)
                or not 0 <= ship_candidate_mask <= 0xFF
                or not 0 <= trade_region_id <= CITY_TRADE_REGION_MAX
                or not 0 <= culture_id <= 15 or not 0 <= nation_id <= 0xFF
                or not 0 <= shipyard_level < len(CITY_GOODS_SUPPLY_BY_SIZE)
                or not 0 <= update_counter <= 0xFF
                or not -1 <= specialty_id <= CITY_SPECIALTY_ID_MAX
                or not 0 <= specialty_price <= ITEM_PRICE_MAX
                or not 0 <= specialty_supply_index < len(CITY_GOODS_SUPPLY_BY_SIZE)
                or any(not -1 <= good_id < ITEM_RECORD_COUNT
                       for good_id in default_goods)
                or not 0 <= city_status <= 13):
            raise ExecutableFormatError(
                f'도시 {identifier}번 마스터 값이 올바르지 않습니다.')
        city_supply = CITY_GOODS_SUPPLY_BY_SIZE[shipyard_level]
        records.append({
            'index': identifier,
            'name': image.c_string(name_pointer),
            'world_x': world_x,
            'world_y': world_y,
            'inland_connection_ids': inland_connection_ids,
            'ship_candidate_mask': ship_candidate_mask,
            'trade_region_id': trade_region_id,
            'specialty_supply_index': specialty_supply_index,
            'default_state': nation_id,
            'default_flags': default_flags,
            'shipyard_level': shipyard_level,
            'default_update_counter': update_counter,
            'default_value_a': specialty_id,
            'default_value_b': specialty_price,
            'default_value_c': city_supply,
            'facility_flags': facility_flags,
            'default_goods': default_goods,
            'default_city_value': city_status,
            'default_economy_values': [city_supply] * 5,
            'default_link_value': culture_id,
        })
    return records


def _city_profile_mappings(records: list[dict]) -> dict[str, object]:
    """Build the top-level city lookups consumed by the editor UI."""
    candidate_runs = []
    for record in records:
        mask = int(record['ship_candidate_mask'])
        if candidate_runs and candidate_runs[-1][0] == mask:
            candidate_runs[-1][1] += 1
        else:
            candidate_runs.append([mask, 1])
    return {
        'default_specialty_supplies': [
            CITY_GOODS_SUPPLY_BY_SIZE[int(record['specialty_supply_index'])]
            for record in records
        ],
        'ship_candidate_mask_runs': candidate_runs,
        'inland_city_connections': {
            str(record['index']): list(record['inland_connection_ids'])
            for record in records
            if any(city_id >= 0 for city_id in record['inland_connection_ids'])
        },
        'trade_region_ids': [int(record['trade_region_id']) for record in records],
    }


def _read_map_locations(image: PEImage) -> tuple[list[dict], list[dict]]:
    data = image.data
    city_offset = image.va_to_offset(CITY_TABLE_VA)
    cities = []
    for identifier in range(CITY_RECORD_COUNT):
        offset = city_offset + identifier * CITY_RECORD_SIZE
        world_x, world_y = struct.unpack_from('<ii', data, offset + 0x04)
        if not 0 <= world_x <= 2500 or not 0 <= world_y <= 1250:
            raise ExecutableFormatError(f'도시 {identifier}번 좌표가 올바르지 않습니다.')
        cities.append({'id': identifier, 'world_x': world_x, 'world_y': world_y})

    discovery_offset = image.va_to_offset(DISCOVERY_TABLE_VA)
    final_discovery_offset = image.va_to_offset(DISCOVERY_FINAL_COORDINATE_RECORD_VA)
    discoveries = []
    for identifier in range(DISCOVERY_RECORD_COUNT):
        # 마지막 항목(불국사, 게임 ID 527)은 연속 좌표표 바깥의 별도 행이다.
        offset = (discovery_offset + identifier * DISCOVERY_RECORD_SIZE
                  if identifier < DISCOVERY_CONTIGUOUS_RECORD_COUNT
                  else final_discovery_offset)
        min_x, min_y, max_x, max_y = struct.unpack_from('<iiii', data, offset)
        if not all(-1 <= value <= 2500 for value in (min_x, max_x)) or not all(
                -1 <= value <= 1250 for value in (min_y, max_y)):
            raise ExecutableFormatError(f'발견물 {identifier}번 좌표가 올바르지 않습니다.')
        discoveries.append({
            'id': identifier, 'min_x': min_x, 'min_y': min_y,
            'max_x': max_x, 'max_y': max_y,
        })
    return cities, discoveries


def _read_limits(image: PEImage) -> tuple[dict[str, int], list[str]]:
    """Read each gameplay cap using the patcher's canonical operand.

    ``cds_exe_patcher`` displays the first operand as the current setting and
    writes the selected value to every duplicated code path when applying a
    patch.  Use the same rule here so both tools report an identical profile.
    """
    limits = {}
    warnings = []
    for name, operands in LIMIT_OPERANDS.items():
        values = []
        try:
            for value_va, prefix in operands:
                value_offset = image.va_to_offset(value_va)
                if image.data[value_offset - len(prefix):value_offset] != prefix:
                    raise ExecutableFormatError(
                        f'{name} 상한 명령 위치를 검증하지 못했습니다.')
                value = struct.unpack_from('<I', image.data, value_offset)[0]
                if not 1 <= value <= 0x7FFFFFFF:
                    raise ExecutableFormatError(f'{name} 상한값이 올바르지 않습니다.')
                values.append(value)
        except (ExecutableFormatError, IndexError, struct.error) as error:
            warnings.append(str(error))
            continue
        limits[name] = values[0]
    return limits, warnings


def _player_fame_limit_payload(slot_va: int, fame_limit: int, infamy_limit: int) -> bytes:
    """Return the exact independent-limit wrapper written by the patcher."""
    payload = bytearray(PLAYER_FAME_LIMIT_SLOT_SIZE)
    payload[:len(PLAYER_FAME_LIMIT_MAGIC)] = PLAYER_FAME_LIMIT_MAGIC
    struct.pack_into('<II', payload, 8, fame_limit, infamy_limit)
    code_va = slot_va + PLAYER_FAME_LIMIT_CODE_OFFSET
    code = bytearray(b'\x85\xC0\x75\x07\x68')
    code += struct.pack('<I', fame_limit)
    code += b'\xEB\x05\x68' + struct.pack('<I', infamy_limit)
    code += b'\xE9' + struct.pack('<i', PLAYER_FAME_LIMIT_HOOK_END_VA - (code_va + 21))
    payload[PLAYER_FAME_LIMIT_CODE_OFFSET:PLAYER_FAME_LIMIT_CODE_OFFSET + len(code)] = code
    return bytes(payload)


def _read_player_fame_limits(image: PEImage) -> tuple[int, int]:
    """Read the common or patcher-split player fame/infamy cap."""
    hook_offset = image.va_to_offset(PLAYER_FAME_LIMIT_HOOK_VA)
    if (image.data[hook_offset - 5:hook_offset] != b'\x8B\x44\x24\x04\x56'
            or image.data[hook_offset + 5:hook_offset + 14]
            != b'\x6A\x00\x8D\xB4\x81\xAC\x00\x00\x00'):
        raise ExecutableFormatError('주인공 명성·악명 상한 함수 위치를 검증하지 못했습니다.')
    hook = bytes(image.data[hook_offset:hook_offset + 5])
    if hook[0] == 0x68:
        fame_limit = infamy_limit = struct.unpack_from('<I', hook, 1)[0]
    elif hook[0] == 0xE9:
        code_va = PLAYER_FAME_LIMIT_HOOK_END_VA + struct.unpack_from('<i', hook, 1)[0]
        slot_va = code_va - PLAYER_FAME_LIMIT_CODE_OFFSET
        slot_offset = image.va_to_offset(slot_va)
        payload = bytes(image.data[slot_offset:slot_offset + PLAYER_FAME_LIMIT_SLOT_SIZE])
        if payload[:len(PLAYER_FAME_LIMIT_MAGIC)] != PLAYER_FAME_LIMIT_MAGIC:
            raise ExecutableFormatError('명성·악명 분기 코드의 식별자를 검증하지 못했습니다.')
        fame_limit, infamy_limit = struct.unpack_from('<II', payload, 8)
        expected_hook = b'\xE9' + struct.pack(
            '<i', code_va - PLAYER_FAME_LIMIT_HOOK_END_VA)
        if (hook != expected_hook
                or payload != _player_fame_limit_payload(slot_va, fame_limit, infamy_limit)):
            raise ExecutableFormatError('명성·악명 분기 코드가 검증한 형식과 다릅니다.')
    else:
        raise ExecutableFormatError('주인공 명성·악명 상한 명령이 예상한 형식이 아닙니다.')
    if not (FAME_INFAMY_LIMIT_MIN <= fame_limit <= FAME_INFAMY_LIMIT_MAX
            and FAME_INFAMY_LIMIT_MIN <= infamy_limit <= FAME_INFAMY_LIMIT_MAX):
        raise ExecutableFormatError('주인공 명성·악명 상한값이 올바르지 않습니다.')
    return fame_limit, infamy_limit


def _person_ability_limit_code(limit: int) -> bytes:
    """Return the patcher's verified replacement for the shared ability cap."""
    code = bytearray(bytes.fromhex('8b 44 24 04 56 68'))
    code += struct.pack('<I', limit)
    code += bytes.fromhex('6a 00 8d 34 81 8b 4c 24 14 51 8b 06 40 50')
    call_va = PERSON_ABILITY_LIMIT_VA + len(code)
    code += b'\xE8' + struct.pack('<i', 0x49E560 - (call_va + 5))
    code += bytes.fromhex('83 c4 10 48 89 06 5e c2 08 00')
    return bytes(code).ljust(PERSON_ABILITY_LIMIT_BLOCK_SIZE, b'\xCC')


def _read_person_stat_limits(image: PEImage) -> tuple[int, int]:
    """Read the shared player/NPC ability and vitality clamps from the EXE."""
    ability_offset = image.va_to_offset(PERSON_ABILITY_LIMIT_VA)
    ability_code = bytes(image.data[
        ability_offset:ability_offset + PERSON_ABILITY_LIMIT_BLOCK_SIZE])
    if ability_code == PERSON_ABILITY_ORIGINAL_CODE:
        ability_limit = 100
    elif ability_code[:6] == bytes.fromhex('8b 44 24 04 56 68'):
        ability_limit = struct.unpack_from('<I', ability_code, 6)[0]
        if (ability_limit > PERSON_ABILITY_MAX
                or ability_code != _person_ability_limit_code(ability_limit)):
            raise ExecutableFormatError('능력치 상한 함수의 코드를 검증하지 못했습니다.')
    else:
        raise ExecutableFormatError('능력치 상한 함수의 코드를 검증하지 못했습니다.')

    vitality_offset = image.va_to_offset(PERSON_VITALITY_LIMIT_VA)
    if (image.data[vitality_offset - 7:vitality_offset + 1] != PERSON_VITALITY_ORIGINAL_PREFIX
            or image.data[vitality_offset + 5:vitality_offset + 5 + len(PERSON_VITALITY_ORIGINAL_SUFFIX)]
            != PERSON_VITALITY_ORIGINAL_SUFFIX):
        raise ExecutableFormatError('생명력 상한 함수의 코드를 검증하지 못했습니다.')
    vitality_limit = struct.unpack_from('<I', image.data, vitality_offset + 1)[0]
    if vitality_limit > PERSON_VITALITY_MAX:
        raise ExecutableFormatError('생명력 상한값이 0~9999 범위를 벗어납니다.')
    return ability_limit, vitality_limit


def load_executable_profile(path: str | Path, fallback: GameDataProfile) -> ExecutableProfileResult:
    """Overlay every currently verified EXE domain on a fallback profile."""
    target = Path(path).resolve(strict=True)
    image = PEImage(target.read_bytes())
    profile = fallback.fork('executable', str(target))
    loaded = []
    warnings = []
    limits: dict[str, int] = {}

    def attempt(label: str, loader: Callable[[], None]) -> None:
        try:
            loader()
            loaded.append(label)
        except (ExecutableFormatError, KeyError, IndexError, TypeError, ValueError, struct.error) as error:
            warnings.append(f'{label}: {error}')

    def characters() -> None:
        profile.overlay_records('characters', _read_characters(image), str(target))

    def barmaids() -> None:
        records, aptitude_rows = _read_barmaids(image, fallback)
        profile.overlay_records(
            'master_data', records, str(target), collection_name='barmaid_database')
        profile.overlay_mapping('spouse_aptitudes', {'records': aptitude_rows}, str(target))

    def sponsors() -> None:
        profile.overlay_records('sponsors', _read_sponsors(image, fallback), str(target))

    def trade_goods() -> None:
        profile.overlay_records('trade_goods', _read_trade_goods(image), str(target))

    def trade_regions() -> None:
        profile.overlay_mapping(
            'cities', {'trade_regions': _read_trade_regions(image)}, str(target))

    def ship_types() -> None:
        profile.overlay_mapping('fleet', _read_ship_types(image), str(target))

    def items() -> None:
        master_rows, item_stats = _read_items(image)
        profile.overlay_mapping('master_data', {
            'item_master_db': master_rows,
            'item_stats_table': item_stats,
        }, str(target))

    def figurehead_effects() -> None:
        profile.overlay_mapping(
            'fleet', {'figurehead_effects': _read_figurehead_effects(image)}, str(target))

    def cities() -> None:
        records = _read_cities(image)
        profile.overlay_records('cities', records, str(target), id_key='index')
        profile.overlay_mapping('cities', _city_profile_mappings(records), str(target))

    def map_locations() -> None:
        city_points, discovery_regions = _read_map_locations(image)
        profile.overlay_mapping('map_locations', {
            'city_points': city_points,
            'discovery_regions': discovery_regions,
        }, str(target))

    def money_limits() -> None:
        nonlocal limits
        limits, limit_warnings = _read_limits(image)
        warnings.extend(f'자금 상한: {warning}' for warning in limit_warnings)
        if not limits:
            raise ExecutableFormatError('검증된 자금 상한이 없습니다.')
        profile.overlay_mapping('limits', {
            'player': {
                **profile.limits['player'],
                **{key: min(99_999_999, value) for key, value in limits.items()},
            },
        }, str(target))

    def player_reputation_limits() -> None:
        fame_limit, infamy_limit = _read_player_fame_limits(image)
        limits.update({'fame': fame_limit, 'infamy': infamy_limit})
        profile.overlay_mapping('limits', {
            'player': {
                **profile.limits['player'],
                'fame': fame_limit,
                'infamy': infamy_limit,
            },
        }, str(target))

    def person_stat_limits() -> None:
        ability_limit, vitality_limit = _read_person_stat_limits(image)
        limits.update({'ability': ability_limit, 'vitality': vitality_limit})
        profile.overlay_mapping('limits', {
            'player': {
                **profile.limits['player'],
                'ability': ability_limit,
                'vitality': vitality_limit,
            },
            'person': {
                **profile.limits['person'],
                'ability': ability_limit,
                'vitality': vitality_limit,
            },
        }, str(target))

    attempt('인물', characters)
    attempt('여급·자녀 적성', barmaids)
    attempt('후원자', sponsors)
    attempt('교역품 이름', trade_goods)
    attempt('교역권 교역품·가격', trade_regions)
    attempt('함선', ship_types)
    attempt('아이템', items)
    attempt('선수상 효과', figurehead_effects)
    attempt('도시 기본정보', cities)
    attempt('도시·발견물 좌표', map_locations)
    attempt('자금 상한', money_limits)
    attempt('명성·악명 상한', player_reputation_limits)
    attempt('인물 능력치·생명력 상한', person_stat_limits)
    if not loaded:
        detail = warnings[0] if warnings else '지원되는 정적 테이블이 없습니다.'
        raise ExecutableFormatError(f'CDS III 실행 파일로 확인하지 못했습니다. {detail}')
    return ExecutableProfileResult(profile, tuple(loaded), tuple(warnings), limits)
