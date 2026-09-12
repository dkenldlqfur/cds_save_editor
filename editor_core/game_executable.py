"""Read verified static master data from a CDS III Windows executable."""
from pathlib import Path
import struct
from .game_data_profile import GameDataProfile
CHARACTER_TABLE_FILE_OFFSET = 907760
CHARACTER_RECORD_SIZE = 204
CHARACTER_RECORD_COUNT = 205
BARMAID_TABLE_VA = 5339896
BARMAID_RECORD_SIZE = 40
BARMAID_RECORD_COUNT = 127
BARMAID_APPEARANCE_YEAR_REFERENCE = 1495
BARMAID_CHILD_APTITUDE_TABLE_VA = 5353632
BARMAID_CHILD_APTITUDE_RECORD_SIZE = 32
SPONSOR_TABLE_VA = 5384380
SPONSOR_RECORD_SIZE = 60
SPONSOR_RECORD_COUNT = 81
SPONSOR_NAME_POINTER_OFFSET = -4
CITY_TABLE_VA = 5051568
CITY_RECORD_SIZE = 136
CITY_RECORD_COUNT = 226
CITY_GOODS_SUPPLY_BY_SIZE = (20, 50, 100, 200, 350, 500, 700, 1000)
CITY_TRADE_REGION_MAX = 26
CITY_SPECIALTY_ID_MAX = 69
DISCOVERY_TABLE_VA = 5358980
DISCOVERY_RECORD_SIZE = 92
DISCOVERY_RECORD_COUNT = 231
TRADE_GOOD_TABLE_VA = 5098428
TRADE_GOOD_RECORD_SIZE = 136
TRADE_GOOD_RECORD_COUNT = 70
TRADE_GOOD_NAME_POINTER_OFFSET = 124
TRADE_GOOD_NAME_RECORD_SHIFT = -1
TRADE_REGION_GOODS_TABLE_VA = 5107936
TRADE_REGION_COUNT = CITY_TRADE_REGION_MAX + 1
TRADE_REGION_GOODS_PER_REGION = 5
SHIP_TYPE_TABLE_VA = 5226976
SHIP_TYPE_RECORD_COUNT = 8
SHIP_TYPE_RECORD_SIZE = 64
SHIP_TYPE_MIN_CREW_DISPLAY_OFFSET = 10
ITEM_TABLE_VA = 5231960
ITEM_RECORD_COUNT = 286
ITEM_RECORD_SIZE = 28
ITEM_NO_IMAGE_ID = 4294967295
ITEM_PRICE_MAX = 99999999
ITEM_EFFECT_MAX = 255
FIGUREHEAD_EFFECT_MAGIC = b'CDSFHE1\x00'
FIGUREHEAD_EFFECT_VERSION = 1
FIGUREHEAD_EFFECT_CONFIG_OFFSET = 12
FIGUREHEAD_EFFECT_KEYS = ('disaster_grade1_chance', 'disaster_grade2_chance', 'disaster_grade3_chance', 'cannon_damage_reduction', 'shooting_damage_reduction', 'melee_damage_reduction', 'cannon_attack_percent', 'shooting_attack_percent', 'melee_attack_percent', 'hull_recovery', 'movement_bonus', 'movement_maximum', 'special_cannon_attack_percent', 'all_attack_percent')
FIGUREHEAD_EFFECT_DEFAULT_VALUES = (11, 41, 71, 20, 50, 70, 120, 150, 200, 5, 1, 6, 200, 150)
FIGUREHEAD_EFFECT_HOOK_TARGETS = ((4410424, 128, 233), (4417197, 256, 233), (4417359, 384, 233), (4419685, 512, 233), (4446340, 768, 233), (4431379, 896, 233), (4671292, 1152, 232), (4671672, 1152, 232), (4672100, 1152, 232), (4672405, 1152, 232), (4672639, 1152, 232))
LIMIT_OPERANDS = {'cash': ((4217269, b'='), (4217296, b'\xb8'), (4590433, b'\x81\xfe'), (4590442, b'\xb8'), (4705224, b'h'), (4728106, b'='), (4728129, b'\xc7\x81\xa8\x00\x00\x00')), 'deposit': ((4590283, b'\x81\xff'), (4590292, b'\xb8'), (4705288, b'h')), 'fame': ((4669832, b'h'),), 'infamy': ((4669896, b'h'),)}

class ExecutableFormatError(ValueError):
    pass

class PEImage:
    """Minimal read-only PE32 address mapper; no external dependency needed."""

    def __init__(self, data):
        self.data = data
        try:
            if data[:2] != b'MZ':
                raise ExecutableFormatError('DOS MZ 헤더가 없습니다.')
            pe_offset = struct.unpack_from('<I', data, 60)[0]
            if data[pe_offset:pe_offset + 4] != b'PE\x00\x00':
                raise ExecutableFormatError('PE 헤더가 없습니다.')
            machine, section_count = struct.unpack_from('<HH', data, pe_offset + 4)
            optional_size = struct.unpack_from('<H', data, pe_offset + 20)[0]
            optional_offset = pe_offset + 24
            if machine != 332 or struct.unpack_from('<H', data, optional_offset)[0] != 267:
                raise ExecutableFormatError('지원하는 32비트 실행 파일이 아닙니다.')
            self.image_base = struct.unpack_from('<I', data, optional_offset + 28)[0]
            if self.image_base != 4194304:
                raise ExecutableFormatError('지원하는 CDS III 실행 파일 기준 주소가 아닙니다.')
            self.size_of_headers = struct.unpack_from('<I', data, optional_offset + 60)[0]
            section_offset = optional_offset + optional_size
            self.sections = []
            for index in range(section_count):
                offset = section_offset + index * 40
                virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from('<IIII', data, offset + 8)
                self.sections.append((virtual_address, max(virtual_size, raw_size), raw_offset, raw_size))
        except (IndexError, struct.error) as error:
            raise ExecutableFormatError('PE 헤더가 손상되었습니다.') from error

    def va_to_offset(self, va):
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
        raise ExecutableFormatError('EXE 주소 0x{0:X}을 파일 위치로 변환할 수 없습니다.'.format(va))

    def offset_to_va(self, offset):
        """Map a raw file offset back to its loaded virtual address."""
        offset = int(offset)
        if 0 <= offset < self.size_of_headers:
            return self.image_base + offset
        for virtual_address, _span, raw_offset, raw_size in self.sections:
            relative = offset - raw_offset
            if 0 <= relative < raw_size:
                return self.image_base + virtual_address + relative
        raise ExecutableFormatError('파일 위치 0x{0:X}를 EXE 주소로 변환할 수 없습니다.'.format(offset))

    def c_string(self, va, fallback='', max_bytes=128):
        if va == 0:
            return fallback
        offset = self.va_to_offset(va)
        end = self.data.find(b'\x00', offset, min(len(self.data), offset + max_bytes))
        if end < 0:
            raise ExecutableFormatError('문자열 주소 0x{0:X}의 끝을 찾지 못했습니다.'.format(va))
        try:
            value = self.data[offset:end].decode('cp949')
        except UnicodeDecodeError as error:
            raise ExecutableFormatError('문자열 주소 0x{0:X}을 CP949로 읽지 못했습니다.'.format(va)) from error
        if not value or any((ord(character) < 32 for character in value)):
            raise ExecutableFormatError('문자열 주소 0x{0:X}의 내용이 올바르지 않습니다.'.format(va))
        return value

class ExecutableProfileResult:
    def __init__(self, profile, loaded_sections, warnings, limits):
        self.profile = profile
        self.loaded_sections = loaded_sections
        self.warnings = warnings
        self.limits = limits

def _read_characters(image):
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
            raise ExecutableFormatError('인물 {0}번의 성별 또는 초기 도시가 올바르지 않습니다.'.format(identifier))
        records.append({'id': identifier, 'name': '{0} {1}'.format(first_name, last_name).strip(), 'first_name': first_name, 'last_name': last_name, 'face_code': raw[2], 'gender': raw[3], 'age_at_1480': signed(4), 'unknown_0x14': raw[5], 'nation_id': signed(6), 'job_id': signed(7), 'unknown_0x20': raw[8], 'fame': raw[9], 'infamy': raw[10], 'hire_state': signed(11), 'city_id': signed(12), 'building_id': signed(13), 'blood_id': signed(14), 'vitality': raw[15], 'abilities': raw[16:21], 'faith': raw[21], 'liquor_capacity': raw[22], 'appearance_state': raw[23], 'skills': raw[24:51], 'raw_dwords': raw})
    return records

def _read_barmaids(image, fallback):
    data = image.data
    table_offset = image.va_to_offset(BARMAID_TABLE_VA)
    aptitude_offset = image.va_to_offset(BARMAID_CHILD_APTITUDE_TABLE_VA)
    fallback_rows = fallback.resource('spouse_aptitudes')['records']
    records = []
    aptitude_rows = []
    for identifier in range(BARMAID_RECORD_COUNT):
        offset = table_offset + identifier * BARMAID_RECORD_SIZE
        name_pointer, face_code = struct.unpack_from('<II', data, offset)
        year_delta = struct.unpack_from('<i', data, offset + 8)[0]
        personality_id = struct.unpack_from('<I', data, offset + 24)[0]
        language_flags = struct.unpack_from('<I', data, offset + 32)[0]
        city_id = struct.unpack_from('<I', data, offset + 36)[0]
        if not 0 <= face_code <= 143 or not 0 <= personality_id < 8 or (not 0 <= city_id < CITY_RECORD_COUNT):
            raise ExecutableFormatError('여급 {0}번 마스터 값이 올바르지 않습니다.'.format(identifier))
        if language_flags & ~((1 << 14) - 1):
            raise ExecutableFormatError('여급 {0}번 언어 비트가 올바르지 않습니다.'.format(identifier))
        records.append({'id': identifier, 'name': image.c_string(name_pointer), 'face_code': face_code, 'year': max(1480, BARMAID_APPEARANCE_YEAR_REFERENCE - year_delta), 'city_id': city_id, 'personality_ids': [personality_id], 'language_flags': language_flags})
        modifier_offset = aptitude_offset + face_code * BARMAID_CHILD_APTITUDE_RECORD_SIZE
        modifiers = list(struct.unpack_from('<6i', data, modifier_offset))
        if any((not -255 <= value <= 255 for value in modifiers)):
            raise ExecutableFormatError('여급 {0}번 자녀 적성값이 올바르지 않습니다.'.format(identifier))
        trailing = list(fallback_rows[identifier][-2:]) if len(fallback_rows[identifier]) >= 9 else [0, 0]
        aptitude_rows.append([face_code] + list(modifiers) + list(trailing))
    return (records, aptitude_rows)

def _read_sponsors(image, fallback):
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
        name_pointer = struct.unpack_from('<I', data, offset + SPONSOR_NAME_POINTER_OFFSET)[0]
        name = image.c_string(name_pointer, fallback=str(fallback_record['name']))
        appearance_year = 1480 + signed(4)
        if values[1] not in (0, 1) or not 0 <= signed(8) < CITY_RECORD_COUNT or (not 0 <= signed(9) <= 15):
            raise ExecutableFormatError('후원자 {0}번 마스터 값이 올바르지 않습니다.'.format(identifier))
        records.append({'id': identifier, 'name': name, 'face_code': values[0], 'gender': values[1], 'nation_id': signed(2), 'job_id': signed(3), 'appearance_year': appearance_year, 'appearance_year_offset': signed(4), 'unknown_0x14': values[5], 'unknown_0x18': values[6], 'power': values[7], 'city_id': signed(8), 'building_id': signed(9), 'wealth_factor': values[10], 'appraisal': values[11], 'unknown_0x30': values[12], 'preference_flags_exe': packed_flags & 255, 'language_flags': packed_flags >> 16 & (1 << 14) - 1, 'name_pointer': name_pointer, 'raw_dwords': [name_pointer] + values})
    return records

def _read_trade_goods(image):
    table_offset = image.va_to_offset(TRADE_GOOD_TABLE_VA)
    records = []
    for identifier in range(TRADE_GOOD_RECORD_COUNT):
        offset = table_offset + (identifier + TRADE_GOOD_NAME_RECORD_SHIFT) * TRADE_GOOD_RECORD_SIZE
        name_pointer = struct.unpack_from('<I', image.data, offset + TRADE_GOOD_NAME_POINTER_OFFSET)[0]
        records.append({'id': identifier, 'name': image.c_string(name_pointer)})
    return records

def _read_trade_regions(image):
    """Read all common goods and their base prices for the 27 trade regions."""
    data = image.data
    goods_table_offset = image.va_to_offset(TRADE_REGION_GOODS_TABLE_VA)
    price_table_offset = image.va_to_offset(TRADE_GOOD_TABLE_VA)
    regions = []
    for region_id in range(TRADE_REGION_COUNT):
        goods = list(struct.unpack_from('<{0}i'.format(TRADE_REGION_GOODS_PER_REGION), data, goods_table_offset + region_id * TRADE_REGION_GOODS_PER_REGION * 4))
        if any((not -1 <= good_id < TRADE_GOOD_RECORD_COUNT for good_id in goods)):
            raise ExecutableFormatError('교역권 {0}번의 공통 교역품이 올바르지 않습니다.'.format(region_id))
        base_prices = []
        for good_id in goods:
            if good_id < 0:
                base_prices.append(-1)
                continue
            price = struct.unpack_from('<i', data, price_table_offset + good_id * TRADE_GOOD_RECORD_SIZE + region_id * 4)[0]
            if not 0 <= price <= ITEM_PRICE_MAX:
                raise ExecutableFormatError('교역권 {0}번, 교역품 {1}번의 기준가가 올바르지 않습니다.'.format(region_id, good_id))
            base_prices.append(price)
        regions.append({'region_id': region_id, 'goods': goods, 'base_prices': base_prices})
    return regions

def _read_ship_types(image):
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
        _, _, shipyard_requirement, base_power, power_limit, base_durability, durability_limit, base_weight, weight_limit, base_capacity, capacity_limit, base_cannons, cannon_limit, min_crew_stored, _unknown_0x38, mast_bits = values
        min_crew = min_crew_stored + SHIP_TYPE_MIN_CREW_DISPLAY_OFFSET
        if shipyard_requirement > 127 or base_power > power_limit or power_limit > 255 or (base_durability > durability_limit) or (base_cannons > cannon_limit) or (cannon_limit > 255) or (base_weight > weight_limit) or (base_capacity > capacity_limit) or (min_crew > 265):
            raise ExecutableFormatError('선종 {0}번 마스터 값이 올바르지 않습니다.'.format(identifier))
        key = str(identifier)
        names[key] = name
        raw_table[key] = values
        default_masts[key] = mast_bits
        default_min_crew[key] = min_crew
    return {'ship_types': names, 'ship_raw_table': raw_table, 'default_mast_values': default_masts, 'default_min_crew': default_min_crew}

def _item_display_category(identifier, executable_category):
    """Convert the EXE's final three category IDs to the editor display order."""
    return {6: 8, 7: 6, 8: 7}.get(int(executable_category), int(executable_category))

def _read_items(image):
    """Read item names, prices, effects, categories and resource image IDs."""
    data = image.data
    table_offset = image.va_to_offset(ITEM_TABLE_VA)
    master_rows = []
    stats = {}
    for identifier in range(ITEM_RECORD_COUNT):
        offset = table_offset + identifier * ITEM_RECORD_SIZE
        name_pointer, image_raw, buy_price, sell_price, effect_value, category_id, _ = struct.unpack_from('<7I', data, offset)
        name = image.c_string(name_pointer, max_bytes=96)
        if not 0 <= buy_price <= ITEM_PRICE_MAX or not 0 <= sell_price <= ITEM_PRICE_MAX or (not 0 <= effect_value <= ITEM_EFFECT_MAX) or (not 0 <= category_id <= 8):
            raise ExecutableFormatError('아이템 {0}번 마스터 값이 올바르지 않습니다.'.format(identifier))
        display_category = _item_display_category(identifier, category_id)
        master_rows.append([identifier, name, display_category, sell_price, buy_price])
        stats[str(identifier)] = {'buy_price': buy_price, 'sell_price': sell_price, 'stat': effect_value, 'cat_code': category_id, 'image_id': None if image_raw == ITEM_NO_IMAGE_ID else image_raw}
    return (master_rows, stats)

def _validate_figurehead_effect_values(values):
    if len(values) != len(FIGUREHEAD_EFFECT_KEYS):
        raise ExecutableFormatError('선수상 효과 설정 개수가 올바르지 않습니다.')
    if any((not 0 <= value <= 100 for value in values[:6])):
        raise ExecutableFormatError('선수상 방지율 또는 피해 감소율이 올바르지 않습니다.')
    if any((not 0 <= values[index] <= 1000 for index in (6, 7, 8, 12, 13))):
        raise ExecutableFormatError('선수상 공격 배율이 올바르지 않습니다.')
    if not 0 <= values[9] <= 9999:
        raise ExecutableFormatError('선수상 내구 회복량이 올바르지 않습니다.')
    if not 0 <= values[10] <= 127 or not 1 <= values[11] <= 127:
        raise ExecutableFormatError('선수상 이동 효과가 올바르지 않습니다.')

def _read_figurehead_effects(image):
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
                raise ExecutableFormatError('지원하지 않는 선수상 효과 설정 버전입니다: {0}'.format(version))
            values = struct.unpack_from('<{0}I'.format(len(FIGUREHEAD_EFFECT_KEYS)), data, offset + FIGUREHEAD_EFFECT_CONFIG_OFFSET)
        except struct.error as error:
            raise ExecutableFormatError('선수상 효과 설정 블록이 손상되었습니다.') from error
        slot_va = image.offset_to_va(offset)
        for hook_va, stub_offset, opcode in FIGUREHEAD_EFFECT_HOOK_TARGETS:
            hook_offset = image.va_to_offset(hook_va)
            try:
                actual_opcode = data[hook_offset]
                relative = struct.unpack_from('<i', data, hook_offset + 1)[0]
            except (IndexError, struct.error) as error:
                raise ExecutableFormatError('선수상 효과 연결 위치 0x{0:X}가 손상되었습니다.'.format(hook_va)) from error
            target_va = hook_va + 5 + relative
            if actual_opcode != opcode or target_va != slot_va + stub_offset:
                raise ExecutableFormatError('선수상 효과 연결 위치 0x{0:X}를 검증하지 못했습니다.'.format(hook_va))
    _validate_figurehead_effect_values(values)
    return dict(zip(FIGUREHEAD_EFFECT_KEYS, values))

def _read_cities(image):
    """Read verified city defaults whose IDs are shared with save records."""
    data = image.data
    table_offset = image.va_to_offset(CITY_TABLE_VA)
    records = []
    for identifier in range(CITY_RECORD_COUNT):
        offset = table_offset + identifier * CITY_RECORD_SIZE
        values = list(struct.unpack_from('<34i', data, offset))
        name_pointer = values[0] & 4294967295
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
        packed_facilities = values[24] & 4294967295
        facility_flags = packed_facilities & 65535
        default_flags = packed_facilities >> 16
        if not 0 <= world_x <= 2500 or not 0 <= world_y <= 1250 or any((not -1 <= city_id < CITY_RECORD_COUNT for city_id in inland_connection_ids)) or (not 0 <= ship_candidate_mask <= 255) or (not 0 <= trade_region_id <= CITY_TRADE_REGION_MAX) or (not 0 <= culture_id <= 15) or (not 0 <= nation_id <= 255) or (not 0 <= shipyard_level < len(CITY_GOODS_SUPPLY_BY_SIZE)) or (not 0 <= update_counter <= 255) or (not -1 <= specialty_id <= CITY_SPECIALTY_ID_MAX) or (not 0 <= specialty_price <= ITEM_PRICE_MAX) or (not 0 <= specialty_supply_index < len(CITY_GOODS_SUPPLY_BY_SIZE)) or any((not -1 <= good_id < ITEM_RECORD_COUNT for good_id in default_goods)) or (not 0 <= city_status <= 13):
            raise ExecutableFormatError('도시 {0}번 마스터 값이 올바르지 않습니다.'.format(identifier))
        city_supply = CITY_GOODS_SUPPLY_BY_SIZE[shipyard_level]
        records.append({'index': identifier, 'name': image.c_string(name_pointer), 'world_x': world_x, 'world_y': world_y, 'inland_connection_ids': inland_connection_ids, 'ship_candidate_mask': ship_candidate_mask, 'trade_region_id': trade_region_id, 'specialty_supply_index': specialty_supply_index, 'default_state': nation_id, 'default_flags': default_flags, 'shipyard_level': shipyard_level, 'default_update_counter': update_counter, 'default_value_a': specialty_id, 'default_value_b': specialty_price, 'default_value_c': city_supply, 'facility_flags': facility_flags, 'default_goods': default_goods, 'default_city_value': city_status, 'default_economy_values': [city_supply] * 5, 'default_link_value': culture_id})
    return records

def _city_profile_mappings(records):
    """Build the top-level city lookups consumed by the editor UI."""
    candidate_runs = []
    for record in records:
        mask = int(record['ship_candidate_mask'])
        if candidate_runs and candidate_runs[-1][0] == mask:
            candidate_runs[-1][1] += 1
        else:
            candidate_runs.append([mask, 1])
    return {'default_specialty_supplies': [CITY_GOODS_SUPPLY_BY_SIZE[int(record['specialty_supply_index'])] for record in records], 'ship_candidate_mask_runs': candidate_runs, 'inland_city_connections': {str(record['index']): list(record['inland_connection_ids']) for record in records if any((city_id >= 0 for city_id in record['inland_connection_ids']))}, 'trade_region_ids': [int(record['trade_region_id']) for record in records]}

def _read_map_locations(image):
    data = image.data
    city_offset = image.va_to_offset(CITY_TABLE_VA)
    cities = []
    for identifier in range(CITY_RECORD_COUNT):
        offset = city_offset + identifier * CITY_RECORD_SIZE
        world_x, world_y = struct.unpack_from('<ii', data, offset + 4)
        if not 0 <= world_x <= 2500 or not 0 <= world_y <= 1250:
            raise ExecutableFormatError('도시 {0}번 좌표가 올바르지 않습니다.'.format(identifier))
        cities.append({'id': identifier, 'world_x': world_x, 'world_y': world_y})
    discovery_offset = image.va_to_offset(DISCOVERY_TABLE_VA)
    discoveries = []
    for identifier in range(DISCOVERY_RECORD_COUNT):
        offset = discovery_offset + identifier * DISCOVERY_RECORD_SIZE
        min_x, min_y, max_x, max_y = struct.unpack_from('<iiii', data, offset)
        if not all((-1 <= value <= 2500 for value in (min_x, max_x))) or not all((-1 <= value <= 1250 for value in (min_y, max_y))):
            raise ExecutableFormatError('발견물 {0}번 좌표가 올바르지 않습니다.'.format(identifier))
        discoveries.append({'id': identifier, 'min_x': min_x, 'min_y': min_y, 'max_x': max_x, 'max_y': max_y})
    return (cities, discoveries)

def _read_limits(image):
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
                    raise ExecutableFormatError('{0} 상한 명령 위치를 검증하지 못했습니다.'.format(name))
                value = struct.unpack_from('<I', image.data, value_offset)[0]
                if not 1 <= value <= 2147483647:
                    raise ExecutableFormatError('{0} 상한값이 올바르지 않습니다.'.format(name))
                values.append(value)
        except (ExecutableFormatError, IndexError, struct.error) as error:
            warnings.append(str(error))
            continue
        limits[name] = values[0]
    return (limits, warnings)

def load_executable_profile(path, fallback):
    """Overlay every currently verified EXE domain on a fallback profile."""
    target = Path(path).resolve()
    with open(str(target), 'rb') as executable_file:
        image = PEImage(executable_file.read())
    profile = fallback.fork('executable', str(target))
    loaded = []
    warnings = []
    limits = {}

    def attempt(label, loader):
        try:
            loader()
            loaded.append(label)
        except (ExecutableFormatError, KeyError, IndexError, TypeError, ValueError, struct.error) as error:
            warnings.append('{0}: {1}'.format(label, error))

    def characters():
        profile.overlay_records('characters', _read_characters(image), str(target))

    def barmaids():
        records, aptitude_rows = _read_barmaids(image, fallback)
        profile.overlay_records('master_data', records, str(target), collection_name='barmaid_database')
        profile.overlay_mapping('spouse_aptitudes', {'records': aptitude_rows}, str(target))

    def sponsors():
        profile.overlay_records('sponsors', _read_sponsors(image, fallback), str(target))

    def trade_goods():
        profile.overlay_records('trade_goods', _read_trade_goods(image), str(target))

    def trade_regions():
        profile.overlay_mapping('cities', {'trade_regions': _read_trade_regions(image)}, str(target))

    def ship_types():
        profile.overlay_mapping('fleet', _read_ship_types(image), str(target))

    def items():
        master_rows, item_stats = _read_items(image)
        profile.overlay_mapping('master_data', {'item_master_db': master_rows, 'item_stats_table': item_stats}, str(target))

    def figurehead_effects():
        profile.overlay_mapping('fleet', {'figurehead_effects': _read_figurehead_effects(image)}, str(target))

    def cities():
        records = _read_cities(image)
        profile.overlay_records('cities', records, str(target), id_key='index')
        profile.overlay_mapping('cities', _city_profile_mappings(records), str(target))

    def map_locations():
        city_points, discovery_regions = _read_map_locations(image)
        profile.overlay_mapping('map_locations', {'city_points': city_points, 'discovery_regions': discovery_regions}, str(target))

    def game_limits():
        nonlocal limits
        limits, limit_warnings = _read_limits(image)
        warnings.extend(('자금·명성 상한: {0}'.format(warning) for warning in limit_warnings))
        if not limits:
            raise ExecutableFormatError('검증된 자금·명성 상한이 없습니다.')
        player_limits = dict(profile.limits['player'])
        player_limits.update((key, min(99999999, value)) for key, value in limits.items())
        profile.overlay_mapping('limits', {'player': player_limits}, str(target))
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
    attempt('자금·명성 상한', game_limits)
    if not loaded:
        detail = warnings[0] if warnings else '지원되는 정적 테이블이 없습니다.'
        raise ExecutableFormatError('CDS III 실행 파일로 확인하지 못했습니다. {0}'.format(detail))
    return ExecutableProfileResult(profile, tuple(loaded), tuple(warnings), limits)
