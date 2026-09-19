import struct
import unittest

from editor_core.game_executable import (
    CHARACTER_RECORD_COUNT,
    CHARACTER_RECORD_SIZE,
    CHARACTER_TABLE_FILE_OFFSET,
    CITY_RECORD_COUNT,
    CITY_RECORD_SIZE,
    CITY_TABLE_VA,
    DISCOVERY_CONTIGUOUS_RECORD_COUNT,
    DISCOVERY_FINAL_COORDINATE_RECORD_VA,
    DISCOVERY_RECORD_SIZE,
    DISCOVERY_TABLE_VA,
    FIGUREHEAD_EFFECT_CONFIG_OFFSET,
    FIGUREHEAD_EFFECT_DEFAULT_VALUES,
    FIGUREHEAD_EFFECT_MAGIC,
    FIGUREHEAD_EFFECT_HOOK_TARGETS,
    FIGUREHEAD_EFFECT_VERSION,
    ITEM_NO_IMAGE_ID,
    ITEM_RECORD_COUNT,
    ITEM_RECORD_SIZE,
    ITEM_TABLE_VA,
    LIMIT_OPERANDS,
    PERSON_ABILITY_LIMIT_VA,
    PERSON_ABILITY_ORIGINAL_CODE,
    PERSON_VITALITY_LIMIT_VA,
    PERSON_VITALITY_ORIGINAL_PREFIX,
    PERSON_VITALITY_ORIGINAL_SUFFIX,
    PLAYER_FAME_LIMIT_CODE_OFFSET,
    PLAYER_FAME_LIMIT_HOOK_END_VA,
    PLAYER_FAME_LIMIT_HOOK_VA,
    SHIP_TYPE_RECORD_COUNT,
    SHIP_TYPE_RECORD_SIZE,
    SHIP_TYPE_TABLE_VA,
    SPONSOR_RECORD_COUNT,
    SPONSOR_RECORD_SIZE,
    SPONSOR_TABLE_VA,
    TRADE_GOOD_RECORD_COUNT,
    TRADE_GOOD_RECORD_SIZE,
    TRADE_GOOD_TABLE_VA,
    TRADE_REGION_COUNT,
    TRADE_REGION_GOODS_PER_REGION,
    TRADE_REGION_GOODS_TABLE_VA,
    _read_characters,
    _city_profile_mappings,
    _read_cities,
    _read_figurehead_effects,
    _read_items,
    _read_limits,
    _read_map_locations,
    _read_person_stat_limits,
    _read_player_fame_limits,
    _player_fame_limit_payload,
    _read_ship_types,
    _read_sponsors,
    _read_trade_regions,
)


class _MapImage:
    def __init__(self):
        city_offset = 16
        discovery_offset = city_offset + CITY_RECORD_COUNT * CITY_RECORD_SIZE + 16
        final_offset = (discovery_offset
                        + DISCOVERY_CONTIGUOUS_RECORD_COUNT * DISCOVERY_RECORD_SIZE + 16)
        self.data = bytearray(final_offset + 16)
        self.offsets = {
            CITY_TABLE_VA: city_offset,
            DISCOVERY_TABLE_VA: discovery_offset,
            DISCOVERY_FINAL_COORDINATE_RECORD_VA: final_offset,
        }
        for identifier in range(CITY_RECORD_COUNT):
            struct.pack_into('<ii', self.data,
                             city_offset + identifier * CITY_RECORD_SIZE + 4, 100, 200)
        for identifier in range(DISCOVERY_CONTIGUOUS_RECORD_COUNT):
            struct.pack_into('<4i', self.data,
                             discovery_offset + identifier * DISCOVERY_RECORD_SIZE,
                             -1, -1, -1, -1)
        struct.pack_into('<4i', self.data, final_offset, 2144, 375, 2145, 375)

    def va_to_offset(self, va):
        return self.offsets[va]


class _OperandImage:
    def __init__(self, values):
        self.data = bytearray(4096)
        self._offsets = {}
        offset = 32
        for name, operands in LIMIT_OPERANDS.items():
            for index, (value_va, prefix) in enumerate(operands):
                self._offsets[value_va] = offset
                self.data[offset - len(prefix):offset] = prefix
                value = values[name][index] if isinstance(values[name], tuple) else values[name]
                struct.pack_into('<I', self.data, offset, value)
                offset += 16

    def va_to_offset(self, va):
        return self._offsets[va]


class _PersonStatLimitImage:
    def __init__(self, ability_limit=100, vitality_limit=2000):
        self.data = bytearray(512)
        self._offsets = {
            PERSON_ABILITY_LIMIT_VA: 32,
            PERSON_VITALITY_LIMIT_VA: 160,
        }
        ability_offset = self._offsets[PERSON_ABILITY_LIMIT_VA]
        if ability_limit == 100:
            self.data[ability_offset:ability_offset + len(PERSON_ABILITY_ORIGINAL_CODE)] = (
                PERSON_ABILITY_ORIGINAL_CODE)
        else:
            code = bytearray(bytes.fromhex('8b 44 24 04 56 68'))
            code += struct.pack('<I', ability_limit)
            code += bytes.fromhex('6a 00 8d 34 81 8b 4c 24 14 51 8b 06 40 50')
            call_va = PERSON_ABILITY_LIMIT_VA + len(code)
            code += b'\xE8' + struct.pack('<i', 0x49E560 - (call_va + 5))
            code += bytes.fromhex('83 c4 10 48 89 06 5e c2 08 00')
            self.data[ability_offset:ability_offset + len(code)] = code
            self.data[ability_offset + len(code):ability_offset + 0x30] = b'\xCC' * (0x30 - len(code))

        vitality_offset = self._offsets[PERSON_VITALITY_LIMIT_VA]
        self.data[vitality_offset - 7:vitality_offset + 1] = PERSON_VITALITY_ORIGINAL_PREFIX
        struct.pack_into('<I', self.data, vitality_offset + 1, vitality_limit)
        self.data[vitality_offset + 5:vitality_offset + 5 + len(PERSON_VITALITY_ORIGINAL_SUFFIX)] = (
            PERSON_VITALITY_ORIGINAL_SUFFIX)

    def va_to_offset(self, va):
        return self._offsets[va]


class _FameLimitImage:
    def __init__(self, fame_limit, infamy_limit=None):
        self.data = bytearray(1024)
        hook_offset = 32
        self._offsets = {PLAYER_FAME_LIMIT_HOOK_VA: hook_offset}
        self.data[hook_offset - 5:hook_offset] = b'\x8B\x44\x24\x04\x56'
        self.data[hook_offset + 5:hook_offset + 14] = b'\x6A\x00\x8D\xB4\x81\xAC\x00\x00\x00'
        if infamy_limit is None:
            self.data[hook_offset:hook_offset + 5] = b'\x68' + struct.pack('<I', fame_limit)
            return

        slot_va, slot_offset = 0x600000, 256
        code_va = slot_va + PLAYER_FAME_LIMIT_CODE_OFFSET
        self._offsets[slot_va] = slot_offset
        self.data[slot_offset:slot_offset + 0x100] = _player_fame_limit_payload(
            slot_va, fame_limit, infamy_limit)
        self.data[hook_offset:hook_offset + 5] = b'\xE9' + struct.pack(
            '<i', code_va - PLAYER_FAME_LIMIT_HOOK_END_VA)

    def va_to_offset(self, va):
        return self._offsets[va]


class _SponsorImage:
    def __init__(self):
        self.table_offset = 16
        self.data = bytearray(
            self.table_offset + SPONSOR_RECORD_COUNT * SPONSOR_RECORD_SIZE)
        self.names = {}
        expected_names = ['조안 2세', '조안 1세']
        expected_names.extend(
            f'후원자 {index}' for index in range(2, SPONSOR_RECORD_COUNT))
        for identifier, name in enumerate(expected_names):
            offset = self.table_offset + identifier * SPONSOR_RECORD_SIZE
            name_pointer = 0x600000 + identifier * 0x20
            struct.pack_into('<I', self.data, offset - 4, name_pointer)
            struct.pack_into(
                '<14I', self.data, offset,
                identifier, identifier % 2, 0, 0, 0, 0, 0, 100,
                0, 0, 100, 100, 0, 0,
            )
            self.names[name_pointer] = name

    def va_to_offset(self, va):
        if va != SPONSOR_TABLE_VA:
            raise KeyError(va)
        return self.table_offset

    def c_string(self, pointer, fallback=''):
        return self.names.get(pointer, fallback)


class _SponsorFallback:
    def __init__(self):
        self.sponsor_by_id = {
            identifier: {'id': identifier, 'name': f'기본 {identifier}'}
            for identifier in range(SPONSOR_RECORD_COUNT)
        }


class _CharacterImage:
    def __init__(self):
        self.data = bytearray(
            CHARACTER_TABLE_FILE_OFFSET + CHARACTER_RECORD_COUNT * CHARACTER_RECORD_SIZE)
        self.names = {}
        for identifier in range(CHARACTER_RECORD_COUNT):
            offset = CHARACTER_TABLE_FILE_OFFSET + identifier * CHARACTER_RECORD_SIZE
            first_pointer = 0x600000 + identifier * 0x20
            last_pointer = first_pointer + 8
            values = [0] * 51
            values[0] = first_pointer
            values[1] = last_pointer
            values[3] = identifier % 2
            values[11] = 2 if identifier == 17 else 1
            values[12] = 0
            values[15] = 177
            values[22] = 88
            struct.pack_into('<51I', self.data, offset, *values)
            self.names[first_pointer] = f'이름{identifier}'
            self.names[last_pointer] = '성'

    def c_string(self, pointer, fallback=''):
        return self.names.get(pointer, fallback)


class _CityImage:
    def __init__(self):
        self.table_offset = 32
        self.data = bytearray(
            self.table_offset + CITY_RECORD_COUNT * CITY_RECORD_SIZE)
        self.names = {}
        for identifier in range(CITY_RECORD_COUNT):
            offset = self.table_offset + identifier * CITY_RECORD_SIZE
            name_pointer = 0x700000 + identifier * 0x20
            values = [0] * 34
            values[0] = name_pointer
            values[1:3] = [1000 + identifier, 300 + identifier]
            values[4:6] = [-1, -1]
            values[6] = 0x7E if identifier < 2 else 0x80
            values[7] = identifier % 27
            values[8] = identifier % 11
            values[9] = identifier % 16
            values[10] = identifier % 8
            values[11] = 100
            values[12] = identifier % 70
            values[13] = 50 + identifier
            values[14] = (identifier + 1) % 8
            values[15:23] = [identifier % 70, -1, -1, -1, -1, -1, -1, -1]
            values[23] = identifier % 14
            values[24] = ((9 << 16) | 0xF47B)
            struct.pack_into('<34i', self.data, offset, *values)
            self.names[name_pointer] = f'도시 {identifier}'

    def va_to_offset(self, va):
        if va != CITY_TABLE_VA:
            raise KeyError(va)
        return self.table_offset

    def c_string(self, pointer, fallback=''):
        return self.names.get(pointer, fallback)


class _ShipTypeImage:
    def __init__(self):
        self.table_offset = 32
        self.data = bytearray(
            self.table_offset + SHIP_TYPE_RECORD_COUNT * SHIP_TYPE_RECORD_SIZE)
        self.names = {}
        for identifier in range(SHIP_TYPE_RECORD_COUNT):
            offset = self.table_offset + identifier * SHIP_TYPE_RECORD_SIZE
            name_pointer = 0x710000 + identifier * 0x20
            values = [
                name_pointer, 0, 10 + identifier,
                20, 30, 40, 50, 60, 70, 80, 90, 5, 10,
                identifier, 100 + identifier, 1 + identifier,
            ]
            struct.pack_into('<16I', self.data, offset, *values)
            self.names[name_pointer] = f'선종 {identifier}'

    def va_to_offset(self, va):
        if va != SHIP_TYPE_TABLE_VA:
            raise KeyError(va)
        return self.table_offset

    def c_string(self, pointer, fallback='', max_bytes=128):
        return self.names.get(pointer, fallback)


class _ItemImage:
    def __init__(self):
        self.table_offset = 64
        self.data = bytearray(
            self.table_offset + ITEM_RECORD_COUNT * ITEM_RECORD_SIZE)
        self.names = {}
        for identifier in range(ITEM_RECORD_COUNT):
            offset = self.table_offset + identifier * ITEM_RECORD_SIZE
            name_pointer = 0x720000 + identifier * 0x20
            image_id = ITEM_NO_IMAGE_ID if identifier == 0 else identifier
            category_id = 6 if identifier == 213 else 7 if identifier == 110 else 8 if identifier == 128 else 0
            struct.pack_into(
                '<7I', self.data, offset,
                name_pointer, image_id, 200 + identifier, 100 + identifier,
                identifier & 0xFF, category_id, 0,
            )
            self.names[name_pointer] = f'아이템 {identifier}'

    def va_to_offset(self, va):
        if va != ITEM_TABLE_VA:
            raise KeyError(va)
        return self.table_offset

    def c_string(self, pointer, fallback='', max_bytes=128):
        return self.names.get(pointer, fallback)


class _TradeRegionImage:
    def __init__(self):
        self.price_table_offset = 64
        self.goods_table_offset = (
            self.price_table_offset + TRADE_GOOD_RECORD_COUNT * TRADE_GOOD_RECORD_SIZE + 64)
        self.data = bytearray(
            self.goods_table_offset
            + TRADE_REGION_COUNT * TRADE_REGION_GOODS_PER_REGION * 4)
        for good_id in range(TRADE_GOOD_RECORD_COUNT):
            for region_id in range(TRADE_REGION_COUNT):
                struct.pack_into(
                    '<i', self.data,
                    self.price_table_offset + good_id * TRADE_GOOD_RECORD_SIZE + region_id * 4,
                    1000 + good_id * 100 + region_id,
                )
        for region_id in range(TRADE_REGION_COUNT):
            goods = [region_id, (region_id + 1) % TRADE_GOOD_RECORD_COUNT, -1, -1, -1]
            struct.pack_into(
                f'<{TRADE_REGION_GOODS_PER_REGION}i', self.data,
                self.goods_table_offset + region_id * TRADE_REGION_GOODS_PER_REGION * 4,
                *goods,
            )

    def va_to_offset(self, va):
        if va == TRADE_GOOD_TABLE_VA:
            return self.price_table_offset
        if va == TRADE_REGION_GOODS_TABLE_VA:
            return self.goods_table_offset
        raise KeyError(va)


class _FigureheadEffectImage:
    def __init__(self, values=None):
        self.data = bytearray(1024)
        self.magic_offset = 32
        self.slot_va = 0x600000
        self.hook_offsets = {
            hook_va: 160 + index * 8
            for index, (hook_va, _stub_offset, _opcode)
            in enumerate(FIGUREHEAD_EFFECT_HOOK_TARGETS)
        }
        if values is not None:
            offset = self.magic_offset
            self.data[offset:offset + len(FIGUREHEAD_EFFECT_MAGIC)] = FIGUREHEAD_EFFECT_MAGIC
            struct.pack_into('<I', self.data, offset + 8, FIGUREHEAD_EFFECT_VERSION)
            struct.pack_into(
                f'<{len(values)}I', self.data,
                offset + FIGUREHEAD_EFFECT_CONFIG_OFFSET, *values,
            )
            for hook_va, stub_offset, opcode in FIGUREHEAD_EFFECT_HOOK_TARGETS:
                hook_offset = self.hook_offsets[hook_va]
                self.data[hook_offset] = opcode
                struct.pack_into(
                    '<i', self.data, hook_offset + 1,
                    self.slot_va + stub_offset - (hook_va + 5),
                )

    def offset_to_va(self, offset):
        if offset == self.magic_offset:
            return self.slot_va
        raise KeyError(offset)

    def va_to_offset(self, va):
        return self.hook_offsets[va]


class GameExecutableLimitTests(unittest.TestCase):
    def test_limits_use_same_canonical_operand_as_executable_patcher(self):
        cash_values = [1_000_000] * len(LIMIT_OPERANDS['cash'])
        cash_values[0] = 9_999_999
        image = _OperandImage({
            'cash': tuple(cash_values),
            'deposit': 2_000_000,
        })

        limits, warnings = _read_limits(image)

        self.assertEqual(9_999_999, limits['cash'])
        self.assertEqual(2_000_000, limits['deposit'])
        self.assertEqual([], warnings)

    def test_player_fame_limits_use_shared_or_patcher_split_clamp(self):
        self.assertEqual((999_999, 999_999), _read_player_fame_limits(
            _FameLimitImage(999_999)))
        self.assertEqual((99_999_999, 10_000), _read_player_fame_limits(
            _FameLimitImage(99_999_999, 10_000)))

    def test_person_stat_limits_accept_original_and_patcher_caps(self):
        self.assertEqual((100, 2_000), _read_person_stat_limits(_PersonStatLimitImage()))
        self.assertEqual(
            (255, 9_999), _read_person_stat_limits(_PersonStatLimitImage(255, 9_999)))


class GameExecutableSponsorTests(unittest.TestCase):
    def test_sponsor_name_pointer_precedes_numeric_record(self):
        records = _read_sponsors(_SponsorImage(), _SponsorFallback())

        self.assertEqual('조안 2세', records[0]['name'])
        self.assertEqual('조안 1세', records[1]['name'])
        self.assertEqual('후원자 80', records[80]['name'])


class GameExecutableCharacterTests(unittest.TestCase):
    def test_character_hire_state_is_read_from_executable_master(self):
        records = _read_characters(_CharacterImage())

        self.assertEqual(1, records[0]['hire_state'])
        self.assertEqual(2, records[17]['hire_state'])
        self.assertEqual(177, records[0]['hire_cost_coefficient'])
        self.assertEqual(88, records[0]['vitality'])
        self.assertNotIn('liquor_capacity', records[0])


class GameExecutableCityTests(unittest.TestCase):
    def test_city_names_are_read_by_city_id(self):
        records = _read_cities(_CityImage())

        self.assertEqual('도시 0', records[0]['name'])
        self.assertEqual('도시 225', records[225]['name'])

    def test_city_basic_defaults_are_read_from_executable(self):
        records = _read_cities(_CityImage())
        city = records[3]

        self.assertEqual(3, city['default_state'])
        self.assertEqual(3, city['default_link_value'])
        self.assertEqual(3, city['shipyard_level'])
        self.assertEqual(3, city['default_value_a'])
        self.assertEqual(53, city['default_value_b'])
        self.assertEqual(200, city['default_value_c'])
        self.assertEqual(0xF47B, city['facility_flags'])
        self.assertEqual(9, city['default_flags'])
        self.assertEqual([3, -1, -1, -1, -1, -1, -1, -1], city['default_goods'])

    def test_city_profile_lookups_follow_each_city_record(self):
        mappings = _city_profile_mappings(_read_cities(_CityImage()))

        self.assertEqual(50, mappings['default_specialty_supplies'][0])
        self.assertEqual([0x7E, 2], mappings['ship_candidate_mask_runs'][0])
        self.assertEqual(3, mappings['trade_region_ids'][3])
        self.assertNotIn('0', mappings['inland_city_connections'])


class GameExecutableShipTypeTests(unittest.TestCase):
    def test_ship_type_master_fields_are_read_from_executable(self):
        tables = _read_ship_types(_ShipTypeImage())

        self.assertEqual('선종 3', tables['ship_types']['3'])
        self.assertEqual(13, tables['ship_raw_table']['3'][2])
        self.assertEqual(4, tables['default_mast_values']['3'])
        self.assertEqual(13, tables['default_min_crew']['3'])


class GameExecutableItemTests(unittest.TestCase):
    def test_item_master_fields_and_display_categories_are_read(self):
        master_rows, stats = _read_items(_ItemImage())

        self.assertEqual([0, '아이템 0', 0, 100, 200], master_rows[0])
        self.assertIsNone(stats['0']['image_id'])
        self.assertEqual(8, master_rows[213][2])
        self.assertEqual(6, master_rows[110][2])
        self.assertEqual(7, master_rows[128][2])
        self.assertEqual(213, stats['213']['stat'])
        self.assertEqual(6, stats['213']['cat_code'])


class GameExecutableTradeRegionTests(unittest.TestCase):
    def test_region_goods_and_matching_base_prices_are_read(self):
        regions = _read_trade_regions(_TradeRegionImage())

        self.assertEqual([3, 4, -1, -1, -1], regions[3]['goods'])
        self.assertEqual([1303, 1403, -1, -1, -1], regions[3]['base_prices'])
        self.assertEqual(26, regions[26]['region_id'])


class GameExecutableFigureheadEffectTests(unittest.TestCase):
    def test_original_executable_uses_verified_default_strengths(self):
        effects = _read_figurehead_effects(_FigureheadEffectImage())

        self.assertEqual(11, effects['disaster_grade1_chance'])
        self.assertEqual(150, effects['all_attack_percent'])

    def test_patcher_settings_are_read_from_embedded_config(self):
        values = list(FIGUREHEAD_EFFECT_DEFAULT_VALUES)
        values[0] = 25
        values[3] = 35
        values[6] = 175
        values[9] = 12
        values[10] = 3
        values[11] = 9
        effects = _read_figurehead_effects(_FigureheadEffectImage(values))

        self.assertEqual(25, effects['disaster_grade1_chance'])
        self.assertEqual(35, effects['cannon_damage_reduction'])
        self.assertEqual(175, effects['cannon_attack_percent'])
        self.assertEqual(12, effects['hull_recovery'])
        self.assertEqual(3, effects['movement_bonus'])
        self.assertEqual(9, effects['movement_maximum'])


class GameExecutableMapLocationTests(unittest.TestCase):
    def test_detached_bulguksa_coordinates_are_read_from_final_record(self):
        cities, discoveries = _read_map_locations(_MapImage())

        self.assertEqual(226, len(cities))
        self.assertEqual(231, len(discoveries))
        self.assertEqual({
            'id': 230, 'min_x': 2144, 'min_y': 375,
            'max_x': 2145, 'max_y': 375,
        }, discoveries[230])

if __name__ == '__main__':
    unittest.main()
