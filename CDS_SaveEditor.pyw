# Decompiled with PyLingual (https://pylingual.io)
# Internal filename: 'CDS3_SaveEditor.pyw'
# Bytecode version: 3.14rc3 (3627)
# Source timestamp: 1970-01-01 00:00:00 UTC (0)

# ***<module>: Failure: Compilation Error
"""\n대항해시대 3 세이브 에디터 (Uncharted Waters 3 Save Editor) v0.98\nPython / Tkinter GUI (.pyw) 단독 실행 버전\n"""
import sys
import os
import json
import struct
import ctypes
import filecmp
import calendar
import hashlib
import re
import subprocess
import tempfile
import threading
import zipfile
from functools import lru_cache
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import tkinter.font as tkfont

from editor_core.save_records import (
    read_character_name,
    read_character_stat_values,
    read_value,
    record_offset,
    write_value,
)
from editor_core.fleet_records import mast_count, pack_mast_slots
from editor_core.tab_layout import configure_equal_columns
from editor_core.treeview import clear_rows


class EditorButton(tk.Button):
    """화면 전체에서 같은 높이를 유지하는 공통 버튼."""

    def __init__(self, master=None, cnf=None, **kwargs):
        # 기존 화면별 설정을 하나의 기준으로 맞춰 버튼 행의 높이가 흔들리지 않게 한다.
        kwargs['font'] = ('Malgun Gothic', 9)
        kwargs['pady'] = 2
        kwargs['height'] = 1
        kwargs['bd'] = 1
        super().__init__(master, cnf or {}, **kwargs)

# VLC DLL은 번들 리소스 경로를 설정한 뒤 지연 로드한다.
vlc = None


def load_json_resource(filename, data_directory=True):
    """소스 실행과 PyInstaller 배포 환경 모두에서 JSON 리소스를 읽는다."""
    base_dirs = []
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            base_dirs.append(sys._MEIPASS)
        base_dirs.append(os.path.dirname(sys.executable))
    base_dirs.append(os.path.dirname(os.path.abspath(__file__)))

    relative_paths = []
    if data_directory:
        relative_paths.append(os.path.join('Resources', 'data', filename))
        relative_paths.append(os.path.join('CDS3SaveEditor', 'Resources', 'data', filename))
    relative_paths.extend((os.path.join('Resources', filename),
                           os.path.join('CDS3SaveEditor', 'Resources', filename)))
    for base_dir in base_dirs:
        for relative_path in relative_paths:
            path = os.path.join(base_dir, relative_path)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except FileNotFoundError:
                continue
    # UI 문자열 자체가 아직 로드되기 전에도 호출될 수 있으므로 파일명만 넘긴다.
    raise FileNotFoundError(filename)


GAME_MASTER_DATA = load_json_resource('master_data.json')
CHARACTER_DATA = load_json_resource('character_database.json')
SPONSOR_DATA = load_json_resource('sponsor_data.json')
FLEET_DATA = load_json_resource('fleet_data.json')
CITY_DATA = load_json_resource('city_data.json')
GAME_STRINGS = load_json_resource('game_strings.json')
TRADE_GOODS_DATA = load_json_resource('trade_goods.json')
DISCOVERY_TRADE_GOOD_DATA = load_json_resource('discovery_trade_goods.json')
DATA_CATEGORIES = load_json_resource('data_categories.json')
DISCOVERY_REWARD_DATA = load_json_resource('discovery_reward_items.json')
DISCOVERY_HINT_DATA = load_json_resource('discovery_hint_data.json')
APP_CONFIG = load_json_resource('app_config.json')
UI_TEXTS = load_json_resource('ui_texts.json')['texts']

# CDS_95.EXE 후원자 표(+0x34)의 실제 비트 순서. 기존 JSON의
# preference_flags는 화면용으로 재배열된 값이므로, 게임 EXE를 찾으면
# 반드시 이 순서의 원본 값을 우선한다.
SPONSOR_EXE_PREFERENCE_NAMES = ('지리', '역사', '보물', '종교', '교역품', '미신', '생물', '민족')
# 후원자 알현의 요구 명성 배율은 직업이 아니라 해당 후원자가 있는 시설 객체가 정한다.
# CDS_95.EXE: 시설 객체의 알현 전처리(vtbl+0x08) → 0x0044E740.
SPONSOR_FAME_MULTIPLIER_BY_BUILDING = {
    2: 100,  # 왕궁
    3: 80,   # 교회
    12: 70,  # 저택
    13: 70,  # 상관
    14: 70,  # 대사관
    15: 70,  # 학자저택
}
SPONSOR_BUILDING_NAME_BY_ID = {
    int(building_id): UI_TEXTS.get(name, name)
    for building_id, name in CITY_DATA['facility_names'].items()
}


def normalized_sponsor_preference_to_exe(mask):
    """기존 JSON의 표시용 취향 마스크를 EXE 원본 비트 순서로 되돌린다."""
    mask = int(mask) & 0xFF
    # JSON: 지리·역사·종교·민족·생물·미신·교역품·보물
    # EXE : 지리·역사·보물·종교·교역품·미신·생물·민족
    return ((mask & 0x01) |
            (mask & 0x02) |
            ((mask & 0x80) >> 5) |
            ((mask & 0x04) << 1) |
            ((mask & 0x40) >> 2) |
            (mask & 0x20) |
            ((mask & 0x10) << 2) |
            ((mask & 0x08) << 4))


def _pe_rva_to_file_offset(data, rva):
    """PE 파일의 RVA를 파일 오프셋으로 변환한다. 올바른 EXE가 아니면 None."""
    try:
        pe_offset = struct.unpack_from('<I', data, 0x3C)[0]
        if data[pe_offset:pe_offset + 4] != b'PE\x00\x00':
            return None
        section_count = struct.unpack_from('<H', data, pe_offset + 6)[0]
        optional_size = struct.unpack_from('<H', data, pe_offset + 20)[0]
        section_offset = pe_offset + 24 + optional_size
        for index in range(section_count):
            offset = section_offset + index * 40
            virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from('<IIII', data, offset + 8)
            if virtual_address <= rva < virtual_address + max(virtual_size, raw_size):
                return raw_offset + rva - virtual_address
    except (IndexError, struct.error):
        pass
    return None


def read_sponsor_preferences_from_game_exe(save_directory):
    """세이브와 같은 폴더의 CDS_95.EXE에서 후원자 취향 원본 마스크를 읽는다."""
    if not save_directory:
        return None
    exe_path = next((os.path.join(save_directory, name)
                     for name in ('CDS_95.EXE', 'cds_95.exe')
                     if os.path.isfile(os.path.join(save_directory, name))), None)
    if exe_path is None:
        return None
    try:
        with open(exe_path, 'rb') as exe_file:
            data = exe_file.read()
        source = SPONSOR_DATA['source']
        table_offset = _pe_rva_to_file_offset(data, int(source['table_rva'], 0))
        row_size, row_count = int(source['row_size']), int(source['row_count'])
        if table_offset is None or table_offset + row_size * row_count > len(data):
            return None
        masks = {}
        for sponsor_id in range(row_count):
            row_offset = table_offset + sponsor_id * row_size
            # 얼굴 코드까지 대조해 엉뚱한 EXE/테이블을 적용하지 않는다.
            sponsor = SPONSOR_BY_ID.get(sponsor_id)
            if sponsor is None or struct.unpack_from('<I', data, row_offset)[0] != int(sponsor['face_code']):
                return None
            masks[sponsor_id] = struct.unpack_from('<I', data, row_offset + 0x34)[0] & 0xFF
        return masks
    except (OSError, KeyError, ValueError, struct.error):
        return None

# 함선 데이터에서 공통 표기(없음)는 한 번만 저장하고, 로드 시 각 선택지에 적용한다.
FLEET_NONE_NAME = UI_TEXTS.get(FLEET_DATA['common_names']['none'], FLEET_DATA['common_names']['none'])
for _fleet_name_table in ('cannon_types', 'figureheads', 'mast_names'):
    for _fleet_code, _fleet_name in FLEET_DATA[_fleet_name_table].items():
        if _fleet_name is None:
            FLEET_DATA[_fleet_name_table][_fleet_code] = FLEET_NONE_NAME


def resolve_ui_references(value):
    """설정 JSON의 ui_XXXX 참조를 실제 UI 문구로 재귀 해석한다."""
    if isinstance(value, str):
        return UI_TEXTS.get(value, value)
    if isinstance(value, list):
        return [resolve_ui_references(item) for item in value]
    if isinstance(value, dict):
        return {key: resolve_ui_references(item) for key, item in value.items()}
    return value


EDITOR_MAPPINGS = resolve_ui_references(load_json_resource('editor_mappings.json'))
GROUP_TITLES = EDITOR_MAPPINGS['group_titles']
TAB_TITLES = EDITOR_MAPPINGS['tab_titles']
TREE_COLUMN_TITLES = EDITOR_MAPPINGS['tree_column_titles']


def ui(key, *args):
    """UI 문자열을 JSON 키로 조회하고 필요한 값만 서식화한다."""
    return UI_TEXTS[key].format(*args) if args else UI_TEXTS[key]


UI_EMPTY_VALUE = ui('ui_0244')
ITEM_CATEGORY_WEAPON = ui('ui_0069')
ITEM_CATEGORY_ARMOR = ui('ui_0108')


def format_game_date(year, month, day):
    return ui('ui_0009', year, month, day)


def fleet_label(prefix_key, field_key):
    """함선 수치의 접두어(기본/최대/현재)와 항목명을 조합한다."""
    return f"{ui(prefix_key)} {ui(field_key)}"


def inventory_text(template_key, location_key, *args):
    """소지품/보관함 이름을 공통 템플릿에 적용한다."""
    return ui(template_key, ui(location_key), *args)


def inventory_full_message(location_key, capacity):
    return inventory_text('ui_0288', location_key), inventory_text('ui_0289', location_key, capacity)


# 발견물 상태는 세이브 상태 마커와 1:1로 대응한다.
# 0x00(미등장), 0x0C(미발견), 0x4C(발견), 0xCC(보고 완료)
DISCOVERY_STATE_TEXT_KEYS = {0: 'ui_0466', 1: 'ui_0112', 2: 'ui_0110', 3: 'ui_0071'}
DISCOVERY_STATE_ACTION_KEYS = {0: 'ui_0467', 1: 'ui_0111', 2: 'ui_0110', 3: 'ui_0109'}


def discovery_state_text(state, action=False, menu=False):
    """세이브의 발견물 상태값을 화면용 문구 하나로 변환한다."""
    if menu and state == 1:
        return ui('ui_0184')
    key_map = DISCOVERY_STATE_ACTION_KEYS if action else DISCOVERY_STATE_TEXT_KEYS
    return ui(key_map.get(state, DISCOVERY_STATE_TEXT_KEYS[0]))


def discovery_state_from_text(text):
    """콤보박스의 상태 문구를 세이브 상태값으로 역변환한다."""
    normalized = text.strip()
    for state in DISCOVERY_STATE_TEXT_KEYS:
        if normalized == discovery_state_text(state):
            return state
    return None


def discovery_status_options(include_all=False):
    options = [discovery_state_text(state) for state in (3, 2, 1, 0)]
    return [ui('ui_0291'), *options] if include_all else options


def hint_state_text(buffer, hint_id):
    """발견물에 연결된 힌트의 세이브 상태를 화면용 문구로 변환한다."""
    if hint_id < 0:
        return '-'
    if buffer is None or not 0 <= hint_id < len(HINT_STATE_OFFSETS):
        return UI_EMPTY_VALUE
    offset = HINT_STATE_OFFSETS[hint_id]
    if not 0 <= offset < len(buffer):
        return UI_EMPTY_VALUE
    state = buffer[offset]
    if state & 0x02:
        return ui('ui_0471')
    if state & 0x01:
        return ui('ui_0472')
    return ui('ui_0473')


def event_state_text(state, menu=False):
    if menu and not state:
        return ui('ui_0186')
    return ui('ui_0185') if state else ui('ui_0206')

BARMAID_DATABASE = GAME_MASTER_DATA['barmaid_database']
BARMAID_BY_ID = {int(record['id']): record for record in BARMAID_DATABASE}
BARMAID_BY_NAME = {record['name']: record for record in BARMAID_DATABASE}
CHARACTER_BY_ID = {int(record['id']): record for record in CHARACTER_DATA['records']}
SPONSOR_BY_ID = {int(record['id']): record for record in SPONSOR_DATA['records']}
# 고용불가(경쟁자·대화 가능) 목록의 이미지 파일은 인물 ID가 아니라 목록 순번을 쓴다.
UNEMPLOYABLE_CHARACTER_IDS = tuple(sorted(
    int(record['id']) for record in CHARACTER_DATA['records']
    if int(record.get('hire_state', 0)) in (0, 1)
))
UNEMPLOYABLE_FACE_INDEX_BY_CHARACTER_ID = {
    character_id: index for index, character_id in enumerate(UNEMPLOYABLE_CHARACTER_IDS)
}
# 세이브 파일의 승무원 역할 슬롯. 역할 판정·복원·목록 필터에서 공통으로 사용한다.
ROLE_SLOT_OFFSETS = (0xA5, 0xA7, 0xA9, 0xAB)
ROLE_SLOT_BY_KEY = {'officer': 0xA5, 'navigator': 0xA7, 'surveyor': 0xA9, 'interpreter': 0xAB}
# 세이브에 동적으로 기록되는 일반 인물 표. 정적 EXE 인물 표와는 별개다.
CHARACTER_SAVE_TABLE_OFFSET = 0x924A
CHARACTER_SAVE_RECORD_SIZE = 0x90
CHARACTER_SPECIAL_STAT_OFFSET = 0x06
# 주인공·일반 인물 공통 생명력은 EXE에서 0~2000으로 제한된다.
CHARACTER_SPECIAL_STAT_MAX = 2000
CHARACTER_SAVE_TABLE_END = CHARACTER_SAVE_TABLE_OFFSET + (
    max(CHARACTER_BY_ID, default=-1) + 1) * CHARACTER_SAVE_RECORD_SIZE
# 세이브의 동적 스폰서 표. 계약 중인 스폰서의 +0x08은 0x00010000이다.
# 에디터의 계약 해제는 계약 상태를 0으로 비운다.
SPONSOR_SAVE_TABLE_OFFSET = 0x13D90
SPONSOR_SAVE_RECORD_SIZE = 0x1C
SPONSOR_CONTRACT_ACTIVE_STATE = 0x00010000
SPONSOR_CONTRACT_CANCELLED_STATE = 0x00000000
# 조안 2세 계약 상태/인게임 계약 해제 세이브 비교로 검증한 종료 보조값이다.
SPONSOR_CONTRACT_CANCEL_AUX_VALUES = {0: 0x00010001}
SPONSOR_CONTRACT_CANCEL_SIDE_EFFECTS = {
    # (오프셋, 값) — 인게임 계약 해제가 함께 비우는 계약 전용 참조/플래그.
    0: {'u16': ((0xA5, 0xFFFF), (0x49C7, 0xFFFF), (0x4A24, 0xFFFF), (0x1A613, 0)),
        'u8': ((0xFD5A, 0x04),)},
}
# 계약으로 지급되는 대여선은 스폰서별 고정 함선 풀 슬롯을 쓴다. 조안 2세 계약은
# 0·1번 슬롯의 대여선 두 척을 만들며, 선박 종류 상위 워드 0x3000이 대여 표식이다.
SPONSOR_LOANED_SHIP_SLOTS = {0: (0, 1)}
CITY_NAME_BY_ID = {city_id: record['name'] for city_id, record in enumerate(CITY_DATA['records'])}
BLOOD_NAMES = GAME_MASTER_DATA['blood_names']
DISCOVERY_DESCRIPTIONS = {int(k): v for k, v in GAME_MASTER_DATA['discovery_descriptions'].items()}
DISCOVERY_MASTER_DB = GAME_MASTER_DATA['discovery_master_db']
EVENT_MASTER_DB = [
    (event_id, name, DATA_CATEGORIES['event_categories'][int(category_id)], value, save_offset, game_id)
    for event_id, name, category_id, value, save_offset, game_id in GAME_MASTER_DATA['event_master_db']
]
ITEM_DESCRIPTION_VALUES = {int(k): v for k, v in GAME_MASTER_DATA['item_descriptions'].items()}
ITEM_MASTER_DB = GAME_MASTER_DATA['item_master_db']
ITEM_CATEGORY_NAMES = [UI_TEXTS.get(name, name) for name in GAME_MASTER_DATA['item_category_names']]
ITEM_STATS_TABLE = {int(k): v for k, v in GAME_MASTER_DATA['item_stats_table'].items()}
TRADE_GOOD_NAME_BY_ID = {int(entry['id']): entry['name'] for entry in TRADE_GOODS_DATA['records']}
DISCOVERY_TRADE_GOOD_REFS = {
    int(discovery_no): int(trade_good_id)
    for discovery_no, trade_good_id in DISCOVERY_TRADE_GOOD_DATA['discovery_trade_good_ids'].items()
}
DISCOVERY_NAME_BY_NO = {
    int(discovery_no): name if name is not None else TRADE_GOOD_NAME_BY_ID.get(DISCOVERY_TRADE_GOOD_REFS.get(int(discovery_no)), '')
    for discovery_no, name, *_ in DISCOVERY_MASTER_DB
}
DISCOVERY_REWARD_ITEM_IDS = {
    int(discovery_no): int(item_id)
    for discovery_no, item_id in DISCOVERY_REWARD_DATA['discovery_reward_item_ids'].items()
}
DISCOVERY_HINT_IDS = tuple(int(hint_id) for hint_id in DISCOVERY_HINT_DATA['discovery_hint_ids'])
HINT_STATE_OFFSETS = tuple(int(record['state_offset'], 0) for record in DISCOVERY_HINT_DATA['hints'])
ITEM_DISCOVERY_NAME_REFS = {item_id: discovery_no for discovery_no, item_id in DISCOVERY_REWARD_ITEM_IDS.items()}
ITEM_NAME_BY_ID = {
    int(item_id): name if name is not None else DISCOVERY_NAME_BY_NO.get(ITEM_DISCOVERY_NAME_REFS.get(int(item_id)), '')
    for item_id, name, *_ in ITEM_MASTER_DB
}
ITEM_DESCRIPTION_REFS = {int(item_id): int(reference_id) for item_id, reference_id in GAME_MASTER_DATA.get('item_description_refs', {}).items()}
ITEM_DESCRIPTIONS = {
    item_id: description if description is not None else ITEM_DESCRIPTION_VALUES.get(
        ITEM_DESCRIPTION_REFS.get(item_id), DISCOVERY_DESCRIPTIONS.get(ITEM_DISCOVERY_NAME_REFS.get(item_id), ''))
    for item_id, description in ITEM_DESCRIPTION_VALUES.items()
}
REWARD_DISCOVERIES_BY_ITEM = {}
for _discovery_no, _item_id in DISCOVERY_REWARD_ITEM_IDS.items():
    REWARD_DISCOVERIES_BY_ITEM.setdefault(_item_id, []).append(_discovery_no)
JOB_NAMES = GAME_MASTER_DATA['job_names']
NATION_NAMES = GAME_MASTER_DATA['nation_names']
PERSON_STAT_NAMES = tuple(name for name, _description in EDITOR_MAPPINGS['profile_stat_definitions']) + (
    ui('ui_0496'), ui('ui_0508'))
PERSON_TAB_TITLES = (ui('ui_0406'), ui('ui_0385'), ui('ui_0407'), ui('ui_0388'), ui('ui_0389'))
PERSON_BASIC_COLUMNS = ((ui('ui_0346'), 38, 'center', False), (ui('ui_0348'), 120, 'w', True),
                        (ui('ui_0378'), 170, 'w', True))
PERSON_STAT_COLUMNS = ((ui('ui_0346'), 38, 'center', False), (ui('ui_0348'), 150, 'w', True),
                       (ui('ui_0350'), 100, 'center', False))
PERSON_FAME_COLUMNS = ((ui('ui_0346'), 38, 'center', False), (ui('ui_0348'), 150, 'w', True),
                       (ui('ui_0350'), 120, 'e', True))
PERSON_LEVEL_COLUMNS = ((ui('ui_0346'), 38, 'center', False), (ui('ui_0348'), 170, 'w', True),
                        (ui('ui_0490'), 100, 'center', False))
BASIC_NATIONS = NATION_NAMES[:2]
SEA_MONSTERS = GAME_MASTER_DATA['sea_monsters']
SKILLS_DATA = [
    (name, offset, description)
    for name, offset, description in GAME_MASTER_DATA['skills_data']
]
LANGUAGE_NAMES = [skill[0] for skill in SKILLS_DATA[13:27]]


def get_barmaid_city_name(barmaid):
    """여급 레코드의 도시 번호를 도시 기본 데이터의 이름으로 표시한다."""
    return CITY_NAME_BY_ID.get(int(barmaid['city_id']), '')


def get_barmaid_zodiac_name(barmaid):
    """여급 레코드의 별자리 번호를 공통 게임 문자열로 표시한다."""
    zodiac_id = int(barmaid['zodiac_id'])
    return GAME_STRINGS['zodiac_names'][zodiac_id] if 0 <= zodiac_id < len(GAME_STRINGS['zodiac_names']) else ''


def get_birth_zodiac_name(month, day):
    """양력 생일의 월·일을 게임의 별자리 명칭으로 변환한다."""
    try:
        month, day = int(month), int(day)
    except (TypeError, ValueError):
        return ''
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return ''
    # 물병자리부터 시작하는 별자리 경계일. 1월 1~19일은 전년도 염소자리다.
    boundaries = ((1, 20, 10), (2, 19, 11), (3, 21, 0), (4, 20, 1),
                  (5, 21, 2), (6, 21, 3), (7, 23, 4), (8, 23, 5),
                  (9, 23, 6), (10, 23, 7), (11, 23, 8), (12, 22, 9))
    zodiac_id = 9
    for boundary_month, boundary_day, candidate_id in boundaries:
        if (month, day) >= (boundary_month, boundary_day):
            zodiac_id = candidate_id
        else:
            break
    return GAME_STRINGS['zodiac_names'][zodiac_id]


def get_barmaid_blood_name(barmaid):
    """여급 혈액형 번호를 공통 혈액형 목록의 표시명으로 변환한다."""
    blood_id = int(barmaid['blood_id'])
    if not 0 <= blood_id < len(BLOOD_NAMES):
        return ''
    return BLOOD_NAMES[blood_id]


def get_barmaid_personality(barmaid):
    """여급 레코드의 성격 ID 목록을 공용 성격명으로 표시한다."""
    return ', '.join(GAME_MASTER_DATA['personality_names'][int(personality_id)]
                     for personality_id in barmaid['personality_ids'])
APP_VERSION = APP_CONFIG['version']
# CDS_95.EXE는 주인공 명성·악명을 9,999,999(0x0098967F)로 제한한다.
# 일반 인물 레코드의 두 값은 각각 unsigned short로 저장된다.
PLAYER_REPUTATION_MAX = 9_999_999
PERSON_REPUTATION_MAX = 0xFFFF
APP_TITLE = f'대항해시대 3 세이브 에디터 v{APP_VERSION}'
UPDATE_CONFIG = APP_CONFIG.get('update', {})
UPDATE_REPOSITORY = str(UPDATE_CONFIG.get('repository', '')).strip()
UPDATE_ASSET_NAME = str(UPDATE_CONFIG.get('asset_name', 'CDS_SaveEditor_v{version}.zip')).strip()
UPDATE_EXECUTABLE_NAME = 'CDS_SaveEditor.exe'
UPDATE_LATEST_URL = (f'https://api.github.com/repos/{UPDATE_REPOSITORY}/releases/latest'
                     if UPDATE_REPOSITORY else '')
_PHOTO_CACHE: dict = {}


def parse_release_version(value):
    """Release 태그를 비교 가능한 (주, 부, 패치) 버전으로 변환한다."""
    match = re.fullmatch(r'[vV]?(\d+)(?:\.(\d+))?(?:\.(\d+))?', str(value).strip())
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())


class CalendarDatePicker(tk.Frame):
    """날짜를 직접 입력하지 않고 팝업 달력에서 고르는 컨트롤."""

    WEEKDAYS = tuple(ui(f'ui_{index:04d}') for index in range(474, 481))

    def __init__(self, parent, get_date, set_date, font=None, min_year=1000, max_year=3000,
                 display_width=14):
        super().__init__(parent)
        self._get_date = get_date
        self._set_date = set_date
        self._popup = None
        self._shown_year = 1480
        self._shown_month = 1
        self._shown_day = 1
        self._min_year = int(min_year)
        self._max_year = int(max_year)
        self.button = EditorButton(
            self, relief='sunken', bd=1, anchor='w', padx=7,
            font=font or ('Malgun Gothic', 9), width=display_width, command=self.open_calendar,
        )
        self.button.pack(fill=tk.X)
        self.refresh()

    def refresh(self):
        try:
            year, month, day = (int(value) for value in self._get_date())
            self.button.config(text=ui('ui_0481', year, month, day))
        except (TypeError, ValueError, tk.TclError):
            self.button.config(text=f"{ui('ui_0401')}   ▾")

    def open_calendar(self):
        if self._popup is not None and self._popup.winfo_exists():
            self._popup.lift()
            self._popup.focus_force()
            return
        try:
            self._shown_year, self._shown_month, self._shown_day = (int(value) for value in self._get_date())
        except (TypeError, ValueError, tk.TclError):
            self._shown_year, self._shown_month, self._shown_day = 1480, 1, 1
        self._shown_year = min(self._max_year, max(self._min_year, self._shown_year))
        self._shown_month = min(12, max(1, self._shown_month))
        self._shown_day = min(calendar.monthrange(self._shown_year, self._shown_month)[1], max(1, self._shown_day))
        popup = tk.Toplevel(self)
        self._popup = popup
        popup.title(ui('ui_0401'))
        popup.transient(self.winfo_toplevel())
        popup.resizable(False, False)
        popup.protocol('WM_DELETE_WINDOW', self._close_popup)
        self._calendar_body = tk.Frame(popup, padx=7, pady=7)
        self._calendar_body.pack(fill=tk.BOTH, expand=True)
        self._render_calendar()
        # 날짜 선택 영역과 실제 적용 동작을 분리한다.
        self._calendar_footer = tk.Frame(popup, padx=7, pady=6, relief='groove', bd=1)
        self._calendar_footer.pack(fill=tk.X)
        EditorButton(
            self._calendar_footer, text=ui('ui_0382'), width=8,
            command=self._confirm_date, bg='#E6F4EA', fg='#137333',
            activebackground='#C8E6C9', activeforeground='#0B5D2A',
        ).pack(side=tk.RIGHT)
        popup.update_idletasks()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 2
        popup.geometry(f'+{x}+{y}')
        popup.grab_set()

    def _close_popup(self):
        popup, self._popup = self._popup, None
        if popup is not None and popup.winfo_exists():
            try:
                popup.grab_release()
            except tk.TclError:
                pass
            popup.destroy()

    def _move_month(self, delta):
        month = self._shown_month + delta
        year = self._shown_year
        if month < 1:
            year, month = year - 1, 12
        elif month > 12:
            year, month = year + 1, 1
        if not self._min_year <= year <= self._max_year:
            return
        self._shown_year = min(self._max_year, max(self._min_year, year))
        self._shown_month = month
        self._shown_day = min(calendar.monthrange(self._shown_year, self._shown_month)[1], self._shown_day)
        self._render_days()

    def _apply_shown_year(self, _event=None):
        try:
            year = int(self._year_var.get())
        except (TypeError, ValueError, tk.TclError):
            self._year_var.set(str(self._shown_year))
            return
        self._shown_year = min(self._max_year, max(self._min_year, year))
        self._shown_day = min(calendar.monthrange(self._shown_year, self._shown_month)[1], self._shown_day)
        self._render_days()

    def _apply_shown_month(self, _event=None):
        try:
            month = int(self._month_var.get())
        except (TypeError, ValueError, tk.TclError):
            self._month_var.set(str(self._shown_month))
            return
        self._shown_month = min(12, max(1, month))
        self._shown_day = min(calendar.monthrange(self._shown_year, self._shown_month)[1], self._shown_day)
        self._render_days()

    def _apply_shown_day(self, _event=None):
        try:
            day = int(self._day_var.get())
        except (TypeError, ValueError, tk.TclError):
            self._day_var.set(str(self._shown_day))
            return
        day = min(calendar.monthrange(self._shown_year, self._shown_month)[1], max(1, day))
        self._shown_day = day
        self._render_days()

    def _choose_day(self, day):
        """달력에서 날짜만 선택한다. 적용은 하단 변경 버튼이 담당한다."""
        self._shown_day = day
        self._render_days()

    def _confirm_date(self):
        """팝업에서 고른 임시 날짜를 실제 날짜 컨트롤에 적용한다."""
        self._set_date(self._shown_year, self._shown_month, self._shown_day)
        self.refresh()
        self._close_popup()

    def _render_calendar(self):
        """팝업을 처음 열 때만 헤더와 날짜 영역의 틀을 만든다."""
        for child in self._calendar_body.winfo_children():
            child.destroy()
        header = tk.Frame(self._calendar_body)
        header.grid(row=0, column=0, columnspan=7, sticky='ew', pady=(0, 5))
        EditorButton(header, text='‹', width=3, command=lambda: self._move_month(-1)).pack(side=tk.LEFT)
        self._year_var = tk.StringVar(value=str(self._shown_year))
        year_spin = ttk.Spinbox(header, textvariable=self._year_var, from_=self._min_year, to=self._max_year, width=5, justify='center', command=self._apply_shown_year)
        year_validate = self._calendar_body.register(
            lambda value: value == '' or (value.isdigit() and (len(value) < 4 or self._min_year <= int(value) <= self._max_year))
        )
        year_spin.configure(validate='key', validatecommand=(year_validate, '%P'))
        year_spin.pack(side=tk.LEFT, padx=(8, 1))
        year_spin.bind('<Return>', self._apply_shown_year, add='+')
        year_spin.bind('<FocusOut>', self._apply_shown_year, add='+')
        tk.Label(header, text=ui('ui_0233'), font=('Malgun Gothic', 9)).pack(side=tk.LEFT, padx=(0, 5))
        self._month_var = tk.StringVar(value=str(self._shown_month))
        month_spin = ttk.Spinbox(header, textvariable=self._month_var, from_=1, to=12, width=3, justify='center', command=self._apply_shown_month)
        month_validate = self._calendar_body.register(
            lambda value: value == '' or (value.isdigit() and (len(value) < 2 or 1 <= int(value) <= 12))
        )
        month_spin.configure(validate='key', validatecommand=(month_validate, '%P'))
        month_spin.pack(side=tk.LEFT)
        month_spin.bind('<Return>', self._apply_shown_month, add='+')
        month_spin.bind('<FocusOut>', self._apply_shown_month, add='+')
        tk.Label(header, text=ui('ui_0234'), font=('Malgun Gothic', 9)).pack(side=tk.LEFT, padx=(0, 5))
        self._day_var = tk.StringVar(value=str(self._shown_day))
        day_spin = ttk.Spinbox(header, textvariable=self._day_var, from_=1, to=calendar.monthrange(self._shown_year, self._shown_month)[1], width=3, justify='center', command=self._apply_shown_day)
        max_day = calendar.monthrange(self._shown_year, self._shown_month)[1]
        day_validate = self._calendar_body.register(
            lambda value: value == '' or (value.isdigit() and (len(value) < 2 or 1 <= int(value) <= max_day))
        )
        day_spin.configure(validate='key', validatecommand=(day_validate, '%P'))
        day_spin.pack(side=tk.LEFT)
        day_spin.bind('<Return>', self._apply_shown_day, add='+')
        tk.Label(header, text=ui('ui_0235'), font=('Malgun Gothic', 9)).pack(side=tk.LEFT, expand=True)
        EditorButton(header, text='›', width=3, command=lambda: self._move_month(1)).pack(side=tk.RIGHT)
        self._day_spin = day_spin
        self._calendar_days = tk.Frame(self._calendar_body)
        self._calendar_days.grid(row=1, column=0, columnspan=7)
        self._render_days()

    def _render_days(self):
        """헤더를 건드리지 않고 월별 날짜 칸만 다시 그린다."""
        if not hasattr(self, '_calendar_days'):
            return
        self._year_var.set(str(self._shown_year))
        self._month_var.set(str(self._shown_month))
        self._day_var.set(str(self._shown_day))
        max_day = calendar.monthrange(self._shown_year, self._shown_month)[1]
        self._day_spin.configure(to=max_day)
        for child in self._calendar_days.winfo_children():
            child.destroy()
        for column, weekday in enumerate(self.WEEKDAYS):
            color = '#C62828' if column == 0 else '#1565C0' if column == 6 else '#333333'
            tk.Label(self._calendar_days, text=weekday, width=3, fg=color, font=('Malgun Gothic', 9)).grid(row=0, column=column, pady=(0, 2))
        selected = (self._shown_year, self._shown_month, self._shown_day)
        for row, week in enumerate(calendar.monthcalendar(self._shown_year, self._shown_month), start=1):
            for column, day in enumerate(week):
                if not day:
                    tk.Label(self._calendar_days, text='', width=3).grid(row=row, column=column, padx=1, pady=1)
                    continue
                chosen = selected == (self._shown_year, self._shown_month, day)
                button = EditorButton(
                    self._calendar_days, text=str(day), width=3, padx=0, pady=1,
                    command=lambda value=day: self._choose_day(value),
                )
                if chosen:
                    button.config(bg='#D6EAF8', relief='sunken')
                button.grid(row=row, column=column, padx=1, pady=1)




class NativeWinEdit:
    """Tk 레이아웃 안에 배치하는 Windows 네이티브 EDIT 컨트롤.

    Tk의 Entry는 한글 IME 조합 문자열을 늦게 반영할 수 있다. 이 컨트롤은
    실제 Win32 EDIT를 사용하고 텍스트가 바뀌는 즉시 콜백을 호출한다.
    """
    _WS_CHILD = 0x40000000
    _WS_VISIBLE = 0x10000000
    _WS_TABSTOP = 0x00010000
    _ES_AUTOHSCROLL = 0x0080
    _WS_EX_CLIENTEDGE = 0x00000200
    _SWP_NOZORDER = 0x0004
    _SWP_NOACTIVATE = 0x0010
    _WM_SETFONT = 0x0030
    _EM_SETSEL = 0x00B1
    _DEFAULT_GUI_FONT = 17

    def __init__(self, host, on_change, width=104, height=23):
        self.host = host
        self.root = host.winfo_toplevel()
        self.on_change = on_change
        self.width = width
        self.height = height
        self.hwnd = None
        self._last_text = ''
        self._poll_job = None
        self.max_bytes = None
        self.enabled = True
        self._user32 = None
        host.configure(width=width, height=height)
        host.pack_propagate(False)
        host.bind('<Configure>', self._resize, add='+')
        # 숨겨진 탭의 EDIT는 입력을 받을 수 없으므로 저빈도 대기하다가, 탭이
        # 다시 표시되는 즉시 폴링을 재개한다.
        host.bind('<Map>', self._wake_poll, add='+')
        self.root.after_idle(self._create)

    def _create(self):
        if self.hwnd or not self.host.winfo_exists():
            return
        user32 = ctypes.windll.user32
        self._user32 = user32
        gdi32 = ctypes.windll.gdi32
        user32.CreateWindowExW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p,
                                            ctypes.c_wchar_p, ctypes.c_uint32,
                                            ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                            ctypes.c_int, ctypes.c_void_p,
                                            ctypes.c_void_p, ctypes.c_void_p,
                                            ctypes.c_void_p]
        user32.CreateWindowExW.restype = ctypes.c_void_p
        user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                        ctypes.c_void_p, ctypes.c_void_p]
        user32.SendMessageW.restype = ctypes.c_void_p
        user32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.SetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        user32.SetWindowTextW.restype = ctypes.c_bool
        user32.EnableWindow.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        user32.EnableWindow.restype = ctypes.c_bool
        user32.GetFocus.argtypes = []
        user32.GetFocus.restype = ctypes.c_void_p
        user32.DestroyWindow.argtypes = [ctypes.c_void_p]
        user32.DestroyWindow.restype = ctypes.c_bool
        gdi32.GetStockObject.argtypes = [ctypes.c_int]
        gdi32.GetStockObject.restype = ctypes.c_void_p
        self.hwnd = user32.CreateWindowExW(
            self._WS_EX_CLIENTEDGE, 'EDIT', '',
            self._WS_CHILD | self._WS_VISIBLE | self._WS_TABSTOP | self._ES_AUTOHSCROLL,
            0, 0, max(1, self.host.winfo_width()), max(1, self.host.winfo_height()),
            ctypes.c_void_p(self.host.winfo_id()), None, None, None)
        if not self.hwnd:
            raise ctypes.WinError()
        user32.EnableWindow(ctypes.c_void_p(self.hwnd), self.enabled)
        font = gdi32.GetStockObject(self._DEFAULT_GUI_FONT)
        user32.SendMessageW(ctypes.c_void_p(self.hwnd), self._WM_SETFONT, font, ctypes.c_void_p(True))
        self._poll()

    def _resize(self, _event=None):
        if self.hwnd:
            ctypes.windll.user32.SetWindowPos(
                ctypes.c_void_p(self.hwnd), None, 0, 0,
                max(1, self.host.winfo_width()), max(1, self.host.winfo_height()),
                self._SWP_NOZORDER | self._SWP_NOACTIVATE)

    def _poll(self):
        try:
            if not self.hwnd or not self.host.winfo_exists():
                return
            # 사용자가 입력 중일 때만 빠르게 확인한다. 포커스 없는 EDIT는
            # 프로그램이 set()으로 값을 바꿀 때 _last_text도 동기화되므로
            # 저빈도 점검만으로 충분하다.
            visible = bool(self.host.winfo_ismapped())
            focused = self.enabled and visible and self._user32.GetFocus() == self.hwnd
            if focused:
                raw_text = self.get()
                text = raw_text
                if self.max_bytes is not None:
                    text = self._limit_cp949_bytes(text)
                    if text != raw_text:
                        self._set_text_and_place_cursor_at_end(text)
                if text != self._last_text:
                    self._last_text = text
                    self.on_change()
            delay = 50 if focused else (250 if self.enabled and visible else 1000)
            self._poll_job = self.root.after(delay, self._poll)
        except tk.TclError:
            self._poll_job = None

    def _wake_poll(self, _event=None):
        """탭 표시·활성화 직후 숨김 상태의 긴 폴링 대기를 깨운다."""
        if self._poll_job is not None:
            try:
                self.root.after_cancel(self._poll_job)
            except tk.TclError:
                pass
        self._poll_job = self.root.after_idle(self._poll)

    def get(self):
        if not self.hwnd or self._user32 is None:
            return ''
        length = self._user32.GetWindowTextLengthW(ctypes.c_void_p(self.hwnd))
        buffer = ctypes.create_unicode_buffer(length + 1)
        self._user32.GetWindowTextW(ctypes.c_void_p(self.hwnd), buffer, len(buffer))
        return buffer.value

    def set(self, value):
        value = str(value)
        if self.hwnd and self._user32 is not None:
            self._user32.SetWindowTextW(ctypes.c_void_p(self.hwnd), value)
        # 파일 로드 등 프로그램 내부의 값 설정은 검색 목록을 다시 만들 필요가 없다.
        # 다음 폴링에서 사용자 입력으로 오인하지 않도록 마지막 값도 함께 맞춘다.
        self._last_text = value

    def _set_text_and_place_cursor_at_end(self, value):
        """자르기로 인한 SetWindowTextW 후에도 IME 입력 커서를 유지한다."""
        self.set(value)
        if self.hwnd:
            end = len(value)
            ctypes.windll.user32.SendMessageW(
                ctypes.c_void_p(self.hwnd), self._EM_SETSEL,
                ctypes.c_void_p(end), ctypes.c_void_p(end))

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        if self.hwnd and self._user32 is not None:
            self._user32.EnableWindow(ctypes.c_void_p(self.hwnd), self.enabled)
        if self.enabled:
            self._wake_poll()

    @staticmethod
    def _limit_cp949_bytes(text, max_bytes):
        accepted = []
        size = 0
        for character in text:
            try:
                encoded = character.encode('cp949')
            except UnicodeEncodeError:
                continue
            if size + len(encoded) > max_bytes:
                break
            accepted.append(character)
            size += len(encoded)
        return ''.join(accepted)

    def destroy(self):
        if self._poll_job is not None:
            self.root.after_cancel(self._poll_job)
        if self.hwnd and self._user32 is not None:
            self._user32.DestroyWindow(ctypes.c_void_p(self.hwnd))
            self.hwnd = None




@lru_cache(maxsize=1)
def get_app_icon_path():
    """소스 실행과 PyInstaller 단일 EXE 실행 모두에서 창 아이콘을 찾는다."""
    base_dirs = []
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            base_dirs.append(sys._MEIPASS)
        base_dirs.append(os.path.dirname(sys.executable))
    base_dirs.append(os.path.dirname(os.path.abspath(__file__)))
    for base_dir in base_dirs:
        for path in (os.path.join(base_dir, 'Resources', 'Icon.ico'),
                     os.path.join(base_dir, 'CDS3SaveEditor', 'Resources', 'Icon.ico')):
            if os.path.isfile(path):
                return path
    return None


def get_cached_photo(img_p: str):
    """이미지 경로에 대한 tk.PhotoImage를 글로벌 캐시에서 반환 (없으면 로드 후 저장)"""
    # ***<module>.get_cached_photo: Failure: Different bytecode
    if img_p not in _PHOTO_CACHE:
        try:
            _PHOTO_CACHE[img_p] = tk.PhotoImage(file=img_p)
        except Exception:
            return None
    return _PHOTO_CACHE[img_p]


def get_black_photo(width, height):
    """이미지가 없는 영역에 쓸 검은색 PhotoImage를 캐시에서 반환한다."""
    cache_key = f'__black__{width}x{height}'
    if cache_key not in _PHOTO_CACHE:
        photo = tk.PhotoImage(width=width, height=height)
        photo.put('#000000', to=(0, 0, width, height))
        _PHOTO_CACHE[cache_key] = photo
    return _PHOTO_CACHE[cache_key]


@lru_cache(maxsize=None)
def get_city_image_path(city_index):
    """도시 순번에 대응하는 추출 CITYCG 이미지를 찾는다."""
    base_dirs = []
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            base_dirs.append(sys._MEIPASS)
        base_dirs.append(os.path.dirname(sys.executable))
    base_dirs.append(os.path.dirname(os.path.abspath(__file__)))
    for base_dir in base_dirs:
        path = os.path.join(base_dir, 'Resources', 'city', f'city_{int(city_index):03d}.png')
        if os.path.isfile(path):
            return path
    return None


def get_city_preview_photo(city_index):
    """기본 탭용으로 준비된 100x80 도시 CG를 반환한다."""
    path = get_city_image_path(city_index)
    if not path:
        return None
    return get_cached_photo(path)
@lru_cache(maxsize=None)
def get_face_image_path(gender, face_id):
    """얼굴 초상화 이미지 경로 조회 (female_### / player_###)."""
    sub = 'female' if gender == 'female' else 'player'
    # male 폴더의 이미지는 주인공 얼굴임을 드러내도록 player_###.png 으로 관리한다.
    prefix = 'female' if gender == 'female' else 'player'
    fn = f'{prefix}_{face_id:03d}.png'
    base_dirs = []
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            base_dirs.append(sys._MEIPASS)
        base_dirs.append(os.path.dirname(sys.executable))
    base_dirs.append(os.path.dirname(os.path.abspath(__file__)))
    for b in base_dirs:
        p1 = os.path.join(b, 'Resources', 'faces', sub, fn)
        if os.path.exists(p1):
            return p1
        else:
            p2 = os.path.join(b, 'CDS3SaveEditor', 'Resources', 'faces', sub, fn)
            if os.path.exists(p2):
                return p2
    return
@lru_cache(maxsize=None)
def get_barmaid_image_path(barmaid_id):
    """여급 전용 기본 초상화 이미지 경로 조회"""
    fn = f'barmaid_{barmaid_id:03d}.png'
    base_dirs = []
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            base_dirs.append(sys._MEIPASS)
        base_dirs.append(os.path.dirname(sys.executable))
    base_dirs.append(os.path.dirname(os.path.abspath(__file__)))
    for b in base_dirs:
        p1 = os.path.join(b, 'Resources', 'faces', 'barmaids', fn)
        if os.path.exists(p1):
            return p1
        else:
            p2 = os.path.join(b, 'CDS3SaveEditor', 'Resources', 'faces', 'barmaids', fn)
            if os.path.exists(p2):
                return p2
    return
@lru_cache(maxsize=None)
def get_item_image_path(item_id):
    """아이템 이미지 경로 조회 (Resources/item 폴더)"""
    base_dirs = []
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            base_dirs.append(sys._MEIPASS)
        base_dirs.append(os.path.dirname(sys.executable))
    base_dirs.append(os.path.dirname(os.path.abspath(__file__)))
    for b in base_dirs:
        for fld in ['item', 'Item']:
            folder = os.path.join(b, 'Resources', fld)
            if not os.path.exists(folder):
                folder = os.path.join(b, 'CDS3SaveEditor', 'Resources', fld)
            if os.path.exists(folder):
                for fn in [f'{item_id:03d}.png', f'{item_id}.png']:
                    p = os.path.join(folder, fn)
                    if os.path.exists(p):
                        return p
    return


@lru_cache(maxsize=None)
def get_sailer_image_path(character_id):
    """정적 등장인물 ID에 대응하는 항해사 초상화 경로를 조회한다."""
    fn = f'sailer_{int(character_id):03d}.png'
    base_dirs = []
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            base_dirs.append(sys._MEIPASS)
        base_dirs.append(os.path.dirname(sys.executable))
    base_dirs.append(os.path.dirname(os.path.abspath(__file__)))
    for base_dir in base_dirs:
        for relative_dir in (os.path.join('Resources', 'faces', 'sailer'),
                             os.path.join('CDS3SaveEditor', 'Resources', 'faces', 'sailer')):
            path = os.path.join(base_dir, relative_dir, fn)
            if os.path.isfile(path):
                return path
    return None


@lru_cache(maxsize=None)
def get_unemployable_image_path(character_id):
    """경쟁자·대화 가능처럼 등용할 수 없는 인물의 초상화 경로를 조회한다."""
    image_index = UNEMPLOYABLE_FACE_INDEX_BY_CHARACTER_ID.get(int(character_id))
    if image_index is None:
        return None
    file_name = f'unemployable_{image_index:03d}.png'
    base_dirs = []
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            base_dirs.append(sys._MEIPASS)
        base_dirs.append(os.path.dirname(sys.executable))
    base_dirs.append(os.path.dirname(os.path.abspath(__file__)))
    for base_dir in base_dirs:
        for relative_dir in (os.path.join('Resources', 'faces', 'unemployable'),
                             os.path.join('CDS3SaveEditor', 'Resources', 'faces', 'unemployable')):
            path = os.path.join(base_dir, relative_dir, file_name)
            if os.path.isfile(path):
                return path
    return None


@lru_cache(maxsize=None)
def get_sponsor_image_path(sponsor_id):
    """스폰서 순번에 대응하는 전용 초상화 경로를 조회한다."""
    fn = f'sponsor_{int(sponsor_id):03d}.png'
    base_dirs = []
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            base_dirs.append(sys._MEIPASS)
        base_dirs.append(os.path.dirname(sys.executable))
    base_dirs.append(os.path.dirname(os.path.abspath(__file__)))
    for base_dir in base_dirs:
        for relative_dir in (os.path.join('Resources', 'faces', 'sponsor'),
                             os.path.join('CDS3SaveEditor', 'Resources', 'faces', 'sponsor')):
            path = os.path.join(base_dir, relative_dir, fn)
            if os.path.isfile(path):
                return path
    return None


@lru_cache(maxsize=None)
def get_trade_good_image_path(good_id):
    """교역품 종류 ID에 대응하는 ITEM.CDS 추출 이미지를 반환한다."""
    base_dirs = []
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            base_dirs.append(sys._MEIPASS)
        base_dirs.append(os.path.dirname(sys.executable))
    base_dirs.append(os.path.dirname(os.path.abspath(__file__)))
    for base_dir in base_dirs:
        for folder in ('trade', 'Trade'):
            for relative in (os.path.join('Resources', folder, f'{good_id:03d}.png'),
                             os.path.join('CDS3SaveEditor', 'Resources', folder, f'{good_id:03d}.png')):
                path = os.path.join(base_dir, relative)
                if os.path.isfile(path):
                    return path
    return None
@lru_cache(maxsize=None)
def get_discovery_image_path(disc_index):
    """발견물 No에 대응하는 정지 이미지 경로를 반환한다.

    No.203~229의 교역품 발견물은 전용 발견물 CG 대신 대응 아이템
    (아이템 ID = 발견물 No - 17)의 아이콘을 사용한다.
    """
    base_dirs = []
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            base_dirs.append(sys._MEIPASS)
        base_dirs.append(os.path.dirname(sys.executable))
    base_dirs.append(os.path.dirname(os.path.abspath(__file__)))
    for base_dir in base_dirs:
        for folder in ('discovery', 'Discovery'):
            path = os.path.join(base_dir, 'Resources', folder, f'{disc_index:03d}.png')
            if os.path.exists(path):
                return path
            path = os.path.join(base_dir, 'CDS3SaveEditor', 'Resources', folder, f'{disc_index:03d}.png')
            if os.path.exists(path):
                return path

    # 쌀~노예 발견물은 아이템 이미지와 공용이다. 대응 파일이 없으면
    # 대응 리소스가 없으면 None을 반환해 이미지 영역을 숨긴다.
    if 203 <= disc_index <= 229:
        return get_item_image_path(disc_index - 17)
    return None


@lru_cache(maxsize=None)
def get_discovery_video_path(disc_index):
    """발견물 No에 대응하는 MP4 영상 경로를 반환한다."""
    base_dirs = []
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            base_dirs.append(sys._MEIPASS)
        base_dirs.append(os.path.dirname(sys.executable))
    base_dirs.append(os.path.dirname(os.path.abspath(__file__)))
    for base_dir in base_dirs:
        for folder in ('discovery', 'Discovery'):
            path = os.path.join(base_dir, 'Resources', folder, f'{disc_index:03d}.mp4')
            if os.path.exists(path):
                return path
            path = os.path.join(base_dir, 'CDS3SaveEditor', 'Resources', folder, f'{disc_index:03d}.mp4')
            if os.path.exists(path):
                return path
    return None


def load_item_discovery_map():
    """Resources/item_discovery_map.json에서 아이템→발견물 No. 연결을 읽는다."""
    base_dirs = []
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            base_dirs.append(sys._MEIPASS)
        base_dirs.append(os.path.dirname(sys.executable))
    base_dirs.append(os.path.dirname(os.path.abspath(__file__)))

    for base_dir in base_dirs:
        for path in (
            os.path.join(base_dir, 'Resources', 'item_discovery_map.json'),
            os.path.join(base_dir, 'CDS3SaveEditor', 'Resources', 'item_discovery_map.json'),
        ):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                mapping = data.get('item_to_discovery_no', data)
                return {int(item_id): int(discovery_no)
                        for item_id, discovery_no in mapping.items()}
            except (OSError, ValueError, TypeError, AttributeError):
                continue
    return {}


# 발견물 테이블의 보상 필드와는 별도로, 실제로 발견물 리소스를 공용으로
# 쓰는 것이 확인된 항목만 Resources/item_discovery_map.json에 기록한다.
ITEM_DISCOVERY_NO = load_item_discovery_map()

def get_item_discovery_no(item_id):
    """아이템에 대응하는 발견물 No.를 반환한다."""
    return ITEM_DISCOVERY_NO.get(item_id)


@lru_cache(maxsize=None)
def get_ship_video_path(ship_type):
    """선박 종류 코드에 대응하는 함선 영상 경로를 반환한다."""
    base_dirs = []
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            base_dirs.append(sys._MEIPASS)
        base_dirs.append(os.path.dirname(sys.executable))
    base_dirs.append(os.path.dirname(os.path.abspath(__file__)))
    filename = f'S{ship_type:02d}_0001.mp4'
    for base_dir in base_dirs:
        for folder in ('ship', 'Ship'):
            path = os.path.join(base_dir, 'Resources', folder, filename)
            if os.path.isfile(path):
                return path
            path = os.path.join(base_dir, 'CDS3SaveEditor', 'Resources', folder, filename)
            if os.path.isfile(path):
                return path
    return None


@lru_cache(maxsize=1)
def get_vlc_runtime_dir():
    """번들 VLC 런타임(libvlc.dll)의 폴더를 반환한다."""
    base_dirs = []
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            base_dirs.append(sys._MEIPASS)
        base_dirs.append(os.path.dirname(sys.executable))
    base_dirs.append(os.path.dirname(os.path.abspath(__file__)))
    for base_dir in base_dirs:
        root = os.path.join(base_dir, 'Resources', 'vlc')
        if not os.path.isdir(root):
            continue
        # 경량 배포본은 libvlc.dll을 Resources/vlc 바로 아래에 둔다.
        if os.path.isfile(os.path.join(root, 'libvlc.dll')):
            return root
        for name in os.listdir(root):
            candidate = os.path.join(root, name)
            if os.path.isfile(os.path.join(candidate, 'libvlc.dll')):
                return candidate
    return None
class FacePickerModal(tk.Toplevel):
    """얼굴 그래픽 썸네일 그리드 갤러리 선택창 (모달 팝업)"""
    def __init__(self, parent, title, gender='female', current_face_id=0, on_select_callback=None, max_faces=None):
        # ***<module>.FacePickerModal.__init__: Failure: Different bytecode
        super().__init__(parent)
        self.title(title)
        self.geometry('640x540')
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.gender = gender
        self.on_select_callback = on_select_callback
        default_max_faces = 145 if gender == 'female' else 410
        self.max_faces = max(1, min(default_max_faces, int(max_faces))) if max_faces is not None else default_max_faces
        self.selected_face_id = current_face_id if 0 <= current_face_id < self.max_faces else 0
        self._compact_grid = self.max_faces <= 16
        self.photo_cache = {}
        top_bar = tk.Frame(self, bg='#F0F0F0', padx=10, pady=8)
        top_bar.pack(side=tk.TOP, fill=tk.X)
        self.lbl_preview = tk.Label(top_bar, width=80, height=96, relief='ridge', bd=2, bg='#222222')
        self.lbl_preview.pack(side=tk.LEFT, padx=6)
        info_f = tk.Frame(top_bar, bg='#F0F0F0')
        info_f.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=8)
        tk.Label(info_f, text=ui('ui_0212'), font=('Malgun Gothic', 9), bg='#F0F0F0').pack(anchor='w', pady=2)
        f_in = tk.Frame(info_f, bg='#F0F0F0')
        f_in.pack(anchor='w', pady=3)
        tk.Label(f_in, text=ui('ui_0044', self.max_faces - 1), font=('Malgun Gothic', 9), bg='#F0F0F0').pack(side=tk.LEFT)
        self.spn_id = ttk.Spinbox(f_in, from_=0, to=self.max_faces - 1, width=5, command=self.on_spin_change)
        digits_only = self.register(lambda proposed: proposed == '' or proposed.isdigit())
        self.spn_id.configure(validate='key', validatecommand=(digits_only, '%P'))
        self.spn_id.set(str(self.selected_face_id))
        self.spn_id.pack(side=tk.LEFT, padx=4)
        self.spn_id.bind('<KeyRelease>', lambda _event: self._clamp_face_spin(), add='+')
        self.spn_id.bind('<FocusOut>', lambda _event: self._clamp_face_spin(), add='+')
        self.spn_id.bind('<Return>', lambda e: self.on_spin_change())
        grid_f = tk.Frame(self)
        if self._compact_grid:
            grid_f.pack(anchor='nw', padx=8, pady=6)
            self.canvas = None
            self.scroll_frame = tk.Frame(grid_f, bg='#FFFFFF')
            self.scroll_frame.pack(anchor='nw')
        else:
            grid_f.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)
            self.canvas = tk.Canvas(grid_f, bg='#FFFFFF', highlightthickness=0)
            sb = ttk.Scrollbar(grid_f, orient=tk.VERTICAL, command=self.canvas.yview)
            self.scroll_frame = tk.Frame(self.canvas, bg='#FFFFFF')
            self.scroll_frame.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
            self.canvas.create_window((0, 0), window=self.scroll_frame, anchor='nw')
            self.canvas.configure(yscrollcommand=sb.set)
            self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            sb.pack(side=tk.RIGHT, fill=tk.Y)
            self.canvas.bind_all('<MouseWheel>', self._on_mousewheel)
        cols = 6
        self.cell_frames = {}
        for fid in range(self.max_faces):
            r = fid // cols
            c = fid % cols
            cell = tk.Frame(self.scroll_frame, bg='#FFFFFF', padx=3, pady=3, relief='groove', bd=1)
            cell.grid(row=r, column=c, padx=3, pady=3)
            img_p = get_face_image_path(self.gender, fid)
            if img_p and os.path.exists(img_p):
                photo = get_cached_photo(img_p)
                self.photo_cache[fid] = photo
                lbl_img = tk.Label(cell, image=photo, width=80, height=96, bg='#222222', cursor='hand2')
            else:
                lbl_img = tk.Label(cell, text=f'#{fid}', width=10, height=5, bg='#E0E0E0', cursor='hand2')
            lbl_img.pack(side=tk.TOP)
            lbl_img.bind('<Button-1>', lambda e, f_id=fid: self.select_face(f_id))
            cell.bind('<Button-1>', lambda e, f_id=fid: self.select_face(f_id))
            self.cell_frames[fid] = cell
        if self._compact_grid:
            btn_bar = tk.Frame(self)
            btn_bar.pack(fill=tk.X, pady=(0, 8))
            EditorButton(
                btn_bar, text=ui('ui_0382'), font=('Malgun Gothic', 9),
                bg='#E6F4EA', fg='#137333', padx=16, pady=5,
                command=self.apply_selection,
            ).pack()
        else:
            EditorButton(
                top_bar, text=ui('ui_0098'), font=('Malgun Gothic', 9),
                bg='#E6F4EA', fg='#137333', padx=12, pady=6,
                command=self.apply_selection,
            ).pack(side=tk.RIGHT, padx=8)
        self.select_face(self.selected_face_id)
        if self._compact_grid:
            self.update_idletasks()
            popup_w = self.winfo_reqwidth()
            popup_h = self.winfo_reqheight()
            parent.update_idletasks()
            popup_x = parent.winfo_rootx() + (parent.winfo_width() - popup_w) // 2
            popup_y = parent.winfo_rooty() + (parent.winfo_height() - popup_h) // 2
            self.geometry(f'{popup_w}x{popup_h}+{max(0, popup_x)}+{max(0, popup_y)}')
    def _on_mousewheel(self, event):
        try:
            self.canvas.yview_scroll(int((-1) * (event.delta / 120)), 'units')
        except Exception:
            return None
    def on_spin_change(self):
        try:
            fid = int(self.spn_id.get())
            if 0 <= fid < self.max_faces:
                self.select_face(fid)
        except Exception:
            return None

    def _clamp_face_spin(self):
        """얼굴 코드 직접 입력도 선택 가능한 코드 범위로 즉시 보정한다."""
        try:
            face_id = int(self.spn_id.get())
        except (TypeError, ValueError):
            return
        face_id = max(0, min(self.max_faces - 1, face_id))
        if self.spn_id.get() != str(face_id):
            self.spn_id.delete(0, tk.END)
            self.spn_id.insert(0, str(face_id))
        self.on_spin_change()
    def select_face(self, fid):
        self.selected_face_id = fid
        self.spn_id.set(str(fid))
        for f, c in self.cell_frames.items():
            if f == fid:
                c.config(bg='#1A73E8', bd=2)
            else:
                c.config(bg='#FFFFFF', bd=1)
        self.update_preview()
    def update_preview(self):
        fid = self.selected_face_id
        img_p = get_face_image_path(self.gender, fid)
        if img_p and os.path.exists(img_p):
                self.preview_photo = get_cached_photo(img_p)
                self.lbl_preview.config(image=self.preview_photo)
    def apply_selection(self):
        if self.on_select_callback:
            self.on_select_callback(self.selected_face_id)
        self.destroy()
def get_player_age(game_year, game_month, game_day, birth_year, birth_month, birth_day):
    """게임의 나이 계산과 같이 생일이 지나기 전에는 한 살을 뺀다."""
    age = int(game_year) - int(birth_year)
    if (int(game_month), int(game_day)) < (int(birth_month), int(birth_day)):
        age -= 1
    return age


def get_fortune_face_code(face_code, age):
    """운명의 반려자 비교에 쓰는 주인공 얼굴 코드."""
    return int(face_code) + (16 if int(age) >= 36 else 0)


def is_fortune_spouse(barmaid, fortune_face_code):
    """여급 테이블의 반려자 비교 코드가 주인공의 표시 얼굴 코드와 같은지 확인한다."""
    return int(barmaid.get('fortune_face_code', -1)) == int(fortune_face_code)


def autofit_columns(tree, min_w=45, max_w=None, padding=28):
    """내용 폭을 기준으로 열을 맞추되, Treeview의 실제 폭을 넘지 않게 한다."""
    # ***<module>.autofit_columns: Failure: Different bytecode
    try:
        # 표를 갱신할 때마다 Tcl 폰트 객체를 만들지 않는다.
        fonts = getattr(autofit_columns, '_fonts', None)
        if fonts is None:
            fonts = (tkfont.Font(font=('Malgun Gothic', 9)),
                     tkfont.Font(font=('Malgun Gothic', 9, 'bold')))
            autofit_columns._fonts = fonts
        font, bold_font = fonts
        measure_cache = getattr(autofit_columns, '_measure_cache', None)
        if measure_cache is None:
            measure_cache = {}
            autofit_columns._measure_cache = measure_cache
        # 항목명·분류·반복 수치처럼 같은 텍스트가 여러 표에서 반복된다. Tcl의
        # Font.measure 호출을 캐시해 대량 목록을 다시 그릴 때 비용을 줄인다.
        def measure(value, bold=False):
            key = (bold, value)
            width = measure_cache.get(key)
            if width is None:
                width = (bold_font if bold else font).measure(value)
                measure_cache[key] = width
            return width
        if len(measure_cache) > 8192:
            measure_cache.clear()
        cols = tuple(tree['columns'])
        rows = tree.get_children()
        headers = tuple(tree.heading(col)['text'] for col in cols)
        # 내용이 같은 표는 다시 Font.measure를 호출할 필요가 없다. Treeview는
        # 목록을 재생성해도 동일한 값을 보이는 경우가 많으므로, 현재 폭까지 포함한
        # 가벼운 서명으로 열너비 계산을 건너뛴다.
        cell_values = tuple(
            tuple(str(tree.set(item, col)) for col in cols)
            for item in rows
        )
        available_width = tree.winfo_width()
        signature = (min_w, max_w, padding, available_width, headers, cell_values)
        if getattr(tree, '_autofit_signature', None) == signature:
            return
        widths = []
        for idx, col in enumerate(cols):
            hdr = headers[idx]
            extra_pad = 20 if idx == len(cols) - 1 else 0
            max_len = measure(hdr, bold=True) + padding + extra_pad
            for values in cell_values:
                val = values[idx]
                w = measure(val) + padding + extra_pad
                if w > max_len:
                    max_len = w
            if max_w:
                max_len = min(max_len, max_w)
            max_len = max(max_len, min_w)
            widths.append(max_len)
        total_width = sum(widths)
        if available_width > len(cols) * min_w and total_width > available_width:
            excess = total_width - available_width
            shrinkable = sum(max(0, width - min_w) for width in widths)
            if shrinkable:
                widths = [max(min_w, width - round(excess * max(0, width - min_w) / shrinkable))
                          for width in widths]
        for col, width in zip(cols, widths):
            tree.column(col, width=width)
        tree._autofit_signature = signature
    except Exception:
        return None

def load_item_database():
    counterfeit_ids = set(range(249, 277))
    return [
        {
            'id': i,
            'name': ITEM_NAME_BY_ID[int(i)],
            'category': ui('ui_0105') if i in counterfeit_ids else ITEM_CATEGORY_NAMES[int(cat)],
            'sell_price': sell_p,
            'buy_price': buy_p,
        }
        for i, name, cat, sell_p, buy_p in ITEM_MASTER_DB
    ]


DISCOVERY_CATEGORY_NAMES = tuple(EDITOR_MAPPINGS['discovery_category_names'])


def center_treeview_columns(parent):
    """하위 Treeview의 모든 열과 열 제목을 가운데 정렬한다."""
    for widget in parent.winfo_children():
        if isinstance(widget, ttk.Treeview):
            for column in widget['columns']:
                widget.column(column, anchor='center')
                widget.heading(column, anchor='center')
        center_treeview_columns(widget)


# CDS_95.EXE 발견물 원본 레코드의 +0x04 카테고리 코드(0~7)를 사용한다.
def load_discovery_database():
    discoveries = []
    for i, name, category_code, val, off, did in DISCOVERY_MASTER_DB:
        category_code = int(category_code)
        if not 0 <= category_code < len(DISCOVERY_CATEGORY_NAMES):
            category_code = 7
        reward_item_id = DISCOVERY_REWARD_ITEM_IDS.get(int(i))
        hint_id = DISCOVERY_HINT_IDS[int(i)] if 0 <= int(i) < len(DISCOVERY_HINT_IDS) else -1
        discoveries.append({'index': i, 'name': DISCOVERY_NAME_BY_NO[int(i)], 'category': DISCOVERY_CATEGORY_NAMES[category_code],
                            'value': val, 'save_offset': off, 'disc_id': did,
                            'hint_id': hint_id,
                            'reward_item_id': reward_item_id,
                            'reward_item_name': ITEM_NAME_BY_ID.get(reward_item_id) if reward_item_id is not None else None})
    return discoveries


def load_event_database():
    return [{'index': i, 'name': name, 'category': cat, 'value': val, 'save_offset': off, 'disc_id': did}
            for i, name, cat, val, off, did in EVENT_MASTER_DB]


SHOP_PURCHASABLE_ITEM_IDS = set(EDITOR_MAPPINGS['shop_purchasable_item_ids'])
NON_PURCHASABLE_ITEM_IDS = set(range(286)) - SHOP_PURCHASABLE_ITEM_IDS
class ItemInfoModal(tk.Toplevel):
    """아이템 상세 정보 및 설명 모달 팝업 (이전/다음 탐색 지원)"""
    def __init__(self, parent, item_info, item_desc, source_view='catalog', slot_index=None, on_action_callback=None, click_pos=None, items_list=None, current_list_index=0, get_item_info_fn=None, on_navigate_callback=None):
        # ***<module>.ItemInfoModal.__init__: Failure: Different bytecode
        super().__init__(parent)
        self.parent = parent
        self._previous_focus = parent.focus_get()
        self._focus_restored = False
        self.on_action_callback = on_action_callback
        self.source_view = source_view
        self.items_list = items_list or [(item_info['id'], slot_index)]
        self.current_list_index = current_list_index
        self.get_item_info_fn = get_item_info_fn
        self.on_navigate_callback = on_navigate_callback
        self.item_id = item_info['id']
        self.slot_index = slot_index
        self.title(ui('ui_0002', item_info['name']))
        w, h = (520, 280)
        self.resizable(False, False)
        self.transient(parent)
        try:
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            px = parent.winfo_rootx() + (pw - w) // 2
            py = parent.winfo_rooty() + (ph - h) // 2
        except Exception:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            px = (sw - w) // 2
            py = (sh - h) // 2
        self.geometry(f'{w}x{h}+{px}+{py}')
        hdr_f = tk.Frame(self, bg='#1A237E', padx=12, pady=6)
        hdr_f.pack(side=tk.TOP, fill=tk.X)
        self.lbl_title = tk.Label(hdr_f, text=f'[{item_info['id']:03d}] {item_info['name']} ({item_info.get('category', '')})', font=('Malgun Gothic', 9), fg='#FFFFFF', bg='#1A237E')
        self.lbl_title.pack(side=tk.LEFT, anchor='w')
        f_nav = tk.Frame(hdr_f, bg='#1A237E')
        f_nav.pack(side=tk.RIGHT)
        self.btn_prev = EditorButton(f_nav, text=ui('ui_0106'), font=('Malgun Gothic', 9), bg='#283593', fg='#FFFFFF', activebackground='#3949AB', activeforeground='#FFFFFF', relief='flat', padx=6, pady=1, cursor='hand2', command=self._go_prev)
        self.btn_prev.pack(side=tk.LEFT, padx=(0, 4))
        self.lbl_page = tk.Label(f_nav, text=f'{self.current_list_index + 1} / {len(self.items_list)}', font=('Malgun Gothic', 9), fg='#B0BEC5', bg='#1A237E')
        self.lbl_page.pack(side=tk.LEFT, padx=2)
        self.btn_next = EditorButton(f_nav, text=ui('ui_0107'), font=('Malgun Gothic', 9), bg='#283593', fg='#FFFFFF', activebackground='#3949AB', activeforeground='#FFFFFF', relief='flat', padx=6, pady=1, cursor='hand2', command=self._go_next)
        self.btn_next.pack(side=tk.LEFT, padx=(4, 0))
        self.btn_f = tk.Frame(self, bg='#F0F0F0', padx=12, pady=6)
        self.btn_f.pack(side=tk.BOTTOM, fill=tk.X)
        self.action_f = tk.Frame(self.btn_f, bg='#F0F0F0')
        self.action_f.pack(anchor='center')
        self._build_action_buttons()
        body_f = tk.Frame(self, padx=14, pady=8)
        body_f.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        # 아이템 아이콘과 연결된 발견물 매체를 세로로 표시한다.
        # 이미지가 없는 경우에는 이 영역 전체를 숨겨 설명 영역을 넓게 쓴다.
        self.item_visuals = tk.Frame(self, width=84)
        self.item_left_spacer = tk.Frame(body_f, width=96)
        self.item_left_spacer.pack(side=tk.LEFT, fill=tk.Y)
        self.item_preview = FleetVideoPreview(self.item_visuals, frame_height=84)
        self.item_discovery_preview = FleetVideoPreview(self.item_visuals, frame_height=84)
        f_right_info = tk.Frame(body_f)
        f_right_info.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.item_info_frame = f_right_info
        f_info = tk.Frame(f_right_info)
        f_info.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))
        self.lbl_price = tk.Label(f_info, text='', font=('Malgun Gothic', 9), fg='#B06000')
        self.lbl_price.pack(side=tk.LEFT, padx=(0, 16))
        self.lbl_stat = tk.Label(f_info, text='', font=('Malgun Gothic', 9), fg='#1A73E8')
        self.lbl_stat.pack(side=tk.LEFT)
        self.lbl_reward_discovery = tk.Label(f_info, text='', font=('Malgun Gothic', 9), fg='#7B1FA2')
        tk.Label(f_right_info, text=ui('ui_0216'), font=('Malgun Gothic', 9)).pack(anchor='w', pady=(2, 3))
        self.desc_box = tk.Text(f_right_info, font=('Malgun Gothic', 9), wrap='word', height=6, bg='#F8F9FA', relief='solid', bd=1, padx=8, pady=6)
        self.desc_box.pack(side=tk.TOP, fill=tk.X)
        self._update_item_view(item_info, item_desc)
        self.bind('<Left>', self._on_prev_key)
        self.bind('<Right>', self._on_next_key)
        self.bind('<Up>', lambda _event: 'break')
        self.bind('<Down>', lambda _event: 'break')
        self.bind('<Destroy>', self._on_destroy, add='+')
        self.grab_set()
        self.after_idle(self._focus_popup_control)
    def _build_action_buttons(self):
        # ***<module>.ItemInfoModal._build_action_buttons: Failure: Different bytecode
        for widget in self.action_f.winfo_children():
            widget.destroy()
        if self.source_view == 'pocket':
            btn_move = EditorButton(self.action_f, text=inventory_text('ui_0290', 'ui_0282'), font=('Malgun Gothic', 9), bg='#E6F4EA', fg='#137333', padx=8, pady=3, command=lambda: self._do_action('move_to_storage'))
            btn_move.pack(side=tk.LEFT, padx=4)
            btn_del = EditorButton(self.action_f, text=ui('ui_0192'), font=('Malgun Gothic', 9), bg='#FCE8E6', fg='#D93025', padx=8, pady=3, command=lambda: self._do_action('delete_pocket'))
            btn_del.pack(side=tk.LEFT, padx=4)
        else:
            if self.source_view == 'storage':
                btn_move = EditorButton(self.action_f, text=inventory_text('ui_0290', 'ui_0281'), font=('Malgun Gothic', 9), bg='#E8F0FE', fg='#1A73E8', padx=8, pady=3, command=lambda: self._do_action('move_to_pocket'))
                btn_move.pack(side=tk.LEFT, padx=4)
                btn_del = EditorButton(self.action_f, text=ui('ui_0192'), font=('Malgun Gothic', 9), bg='#FCE8E6', fg='#D93025', padx=8, pady=3, command=lambda: self._do_action('delete_storage'))
                btn_del.pack(side=tk.LEFT, padx=4)
            else:
                btn_pocket = EditorButton(self.action_f, text=inventory_text('ui_0285', 'ui_0281'), font=('Malgun Gothic', 9), bg='#E8F0FE', fg='#1A73E8', padx=8, pady=3, command=lambda: self._do_action('add_pocket'))
                btn_pocket.pack(side=tk.LEFT, padx=4)
                btn_storage = EditorButton(self.action_f, text=inventory_text('ui_0285', 'ui_0282'), font=('Malgun Gothic', 9), bg='#E6F4EA', fg='#137333', padx=8, pady=3, command=lambda: self._do_action('add_storage'))
                btn_storage.pack(side=tk.LEFT, padx=4)
    def _update_item_view(self, item_info, item_desc):
        self.item_id = item_info['id']
        self.title(ui('ui_0002', item_info['name']))
        self.lbl_title.config(text=f'[{item_info['id']:03d}] {item_info['name']} ({item_info.get('category', '')})')
        img_p = get_item_image_path(self.item_id)
        discovery_no = get_item_discovery_no(self.item_id)
        if discovery_no is None:
            reward_discoveries = REWARD_DISCOVERIES_BY_ITEM.get(self.item_id, [])
            discovery_no = reward_discoveries[0] if reward_discoveries else None
        self._show_item_media(img_p, discovery_no)
        stat_val = ITEM_STATS_TABLE.get(self.item_id, {}).get('stat', 0)
        cat_str = item_info.get('category', '')
        if cat_str == ITEM_CATEGORY_WEAPON:
            self.lbl_stat.config(text=ui('ui_0026', stat_val))
        else:
            if cat_str == ITEM_CATEGORY_ARMOR:
                self.lbl_stat.config(text=ui('ui_0049', stat_val))
            else:
                self.lbl_stat.config(text='')
        reward_discovery_names = [
            DISCOVERY_NAME_BY_NO[discovery_no]
            for discovery_no in REWARD_DISCOVERIES_BY_ITEM.get(self.item_id, [])
            if discovery_no in DISCOVERY_NAME_BY_NO
        ]
        if reward_discovery_names:
            self.lbl_reward_discovery.config(text=ui('ui_0027', ' / '.join(reward_discovery_names)))
            self.lbl_reward_discovery.pack(side=tk.LEFT, padx=(14, 0))
        else:
            self.lbl_reward_discovery.pack_forget()
        self.lbl_price.config(text=ui('ui_0013', item_info['sell_price']))
        self.desc_box.config(state='normal')
        self.desc_box.delete('1.0', tk.END)
        desc_text = item_desc if item_desc else ui('ui_0070')
        self.desc_box.insert('1.0', desc_text)
        self.desc_box.config(state='disabled')
        total = len(self.items_list)
        self.lbl_page.config(text=f'{self.current_list_index + 1} / {total}')
        self.btn_prev.config(state='normal' if self.current_list_index > 0 else 'disabled')
        self.btn_next.config(state='normal' if self.current_list_index < total - 1 else 'disabled')

    def _show_item_media(self, item_image_path, discovery_no):
        """아이템 아이콘과 연결 발견물의 이미지/영상을 겹치지 않게 표시한다."""
        primary = self.item_preview
        discovery = self.item_discovery_preview
        primary.stop()
        discovery.stop()
        primary.pack_forget()
        discovery.pack_forget()
        self.item_photo = None
        self.item_discovery_photo = None

        item_image_path = item_image_path if item_image_path and os.path.exists(item_image_path) else None
        discovery_image_path = get_discovery_image_path(discovery_no) if discovery_no is not None else None
        discovery_video_path = get_discovery_video_path(discovery_no) if discovery_no is not None else None
        has_primary = has_discovery = False

        if item_image_path:
            self.item_photo = get_cached_photo(item_image_path)
            if self.item_photo:
                primary.label.config(image=self.item_photo, text='')
                primary.pack(side=tk.TOP)
                has_primary = True

            # 같은 정적 이미지라면 한 번만 표시한다. 영상은 별도 매체이므로 유지한다.
            same_static_image = bool(
                discovery_image_path and os.path.exists(discovery_image_path)
                and filecmp.cmp(item_image_path, discovery_image_path, shallow=False)
            )
            if discovery_video_path:
                discovery.pack(side=tk.TOP, pady=(8, 0))
                discovery.show(discovery_video_path)
                has_discovery = True
            elif discovery_image_path and not same_static_image:
                self.item_discovery_photo = get_cached_photo(discovery_image_path)
                if self.item_discovery_photo:
                    discovery.label.config(image=self.item_discovery_photo, text='')
                    discovery.pack(side=tk.TOP, pady=(8, 0))
                    has_discovery = True
        elif discovery_video_path:
            primary.pack(side=tk.TOP)
            primary.show(discovery_video_path)
            has_primary = True
        elif discovery_image_path:
            self.item_photo = get_cached_photo(discovery_image_path)
            if self.item_photo:
                primary.label.config(image=self.item_photo, text='')
                primary.pack(side=tk.TOP)
                has_primary = True

        # 이미지가 없어도 발견물 팝업과 같은 빈 80x80 영역을 유지한다.
        if not has_primary:
            primary.label.config(image='', text='')
            primary.pack(side=tk.TOP)
        if not self.item_left_spacer.winfo_manager():
            self.item_left_spacer.pack(side=tk.LEFT, fill=tk.Y, before=self.item_info_frame)
        self.item_visuals.place(x=14, y=42)
    def _go_prev(self):
        if self.current_list_index > 0:
            self.current_list_index -= 1
            it_id, s_idx = self.items_list[self.current_list_index]
            self.slot_index = s_idx
            if self.get_item_info_fn:
                info, desc = self.get_item_info_fn(it_id)
                self._update_item_view(info, desc)
            if self.on_navigate_callback:
                self.on_navigate_callback(it_id, s_idx)

    def _on_prev_key(self, _event):
        self._go_prev()
        return 'break'

    def _on_next_key(self, _event):
        self._go_next()
        return 'break'

    def _focus_popup_control(self):
        """메인 목록 대신 팝업 내부 컨트롤이 키보드 포커스를 받게 한다."""
        if self.winfo_exists():
            target = self.btn_prev if self.btn_prev.cget('state') != 'disabled' else self.btn_next
            (target if target.cget('state') != 'disabled' else self.desc_box).focus_set()

    def _restore_previous_focus(self):
        if self._focus_restored:
            return
        self._focus_restored = True
        try:
            self.grab_release()
        except tk.TclError:
            pass
        try:
            if self._previous_focus is not None and self._previous_focus.winfo_exists():
                self._previous_focus.focus_set()
        except tk.TclError:
            pass

    def _on_destroy(self, event):
        if event.widget is self:
            self.item_preview.stop()
            self.item_discovery_preview.stop()
            self._restore_previous_focus()

    def _go_next(self):
        if self.current_list_index < len(self.items_list) - 1:
            self.current_list_index += 1
            it_id, s_idx = self.items_list[self.current_list_index]
            self.slot_index = s_idx
            if self.get_item_info_fn:
                info, desc = self.get_item_info_fn(it_id)
                self._update_item_view(info, desc)
            if self.on_navigate_callback:
                self.on_navigate_callback(it_id, s_idx)
    def _do_action(self, action_type):
        if self.on_action_callback and self.on_action_callback(self.item_id, action_type, self.slot_index, parent_window=self):
                self.destroy()
class DiscoveryInfoModal(tk.Toplevel):
    """발견물 상세 정보 및 설명 모달 팝업 (이전/다음 탐색 지원)"""
    def __init__(self, parent, disc_info, disc_desc, current_state=0, disc_date=UI_EMPTY_VALUE, rep_date=UI_EMPTY_VALUE, discoverer=UI_EMPTY_VALUE, on_state_change_callback=None, on_hint_toggle_callback=None, on_contract_cancel_callback=None, is_contract_discovery_fn=None, get_hint_state_fn=None, items_list=None, current_list_index=0, get_disc_info_fn=None, on_navigate_callback=None, state_index=None):
        # ***<module>.DiscoveryInfoModal.__init__: Failure: Different bytecode
        super().__init__(parent)
        self.parent = parent
        self._previous_focus = parent.focus_get()
        self._focus_restored = False
        self.on_state_change_callback = on_state_change_callback
        self.on_hint_toggle_callback = on_hint_toggle_callback
        self.on_contract_cancel_callback = on_contract_cancel_callback
        self.is_contract_discovery_fn = is_contract_discovery_fn
        self.get_hint_state_fn = get_hint_state_fn
        self.items_list = items_list or [disc_info['index']]
        self.current_list_index = current_list_index
        self.get_disc_info_fn = get_disc_info_fn
        self.on_navigate_callback = on_navigate_callback
        # disc_index는 원본 발견물 No.(이미지/영상용), state_index는 목록 내부 위치(상태 변경용)다.
        self.disc_index = disc_info['index']
        self.state_index = state_index if state_index is not None else disc_info['index']
        self.vlc_instance = None
        self.vlc_player = None
        self._vlc_dll_dir = None
        self._vlc_end_callback = None
        self._video_path = None
        self._video_buffer = None
        self._video_lock_callback = None
        self._video_display_callback = None
        self._video_frame_ready = False
        self._video_photo = None
        self._video_render_job = None
        self.title(ui('ui_0003', disc_info['name']))
        w, h = (520, 280)
        self.resizable(False, False)
        self.transient(parent)
        try:
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            px = parent.winfo_rootx() + (pw - w) // 2
            py = parent.winfo_rooty() + (ph - h) // 2
        except Exception:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            px = (sw - w) // 2
            py = (sh - h) // 2
        self.geometry(f'{w}x{h}+{px}+{py}')
        hdr_f = tk.Frame(self, bg='#1A237E', padx=12, pady=6)
        hdr_f.pack(side=tk.TOP, fill=tk.X)
        self.lbl_title = tk.Label(hdr_f, text=f"[No. {disc_info['index']:03d} | ID {disc_info['disc_id']:03d}] {disc_info['name']} ({disc_info['category']})", font=('Malgun Gothic', 9), fg='#FFFFFF', bg='#1A237E')
        self.lbl_title.pack(side=tk.LEFT, anchor='w')
        f_nav = tk.Frame(hdr_f, bg='#1A237E')
        f_nav.pack(side=tk.RIGHT)
        self.btn_prev = EditorButton(f_nav, text=ui('ui_0106'), font=('Malgun Gothic', 9), bg='#283593', fg='#FFFFFF', activebackground='#3949AB', activeforeground='#FFFFFF', relief='flat', padx=6, pady=1, cursor='hand2', command=self._go_prev)
        self.btn_prev.pack(side=tk.LEFT, padx=(0, 4))
        self.lbl_page = tk.Label(f_nav, text=f'{self.current_list_index + 1} / {len(self.items_list)}', font=('Malgun Gothic', 9), fg='#B0BEC5', bg='#1A237E')
        self.lbl_page.pack(side=tk.LEFT, padx=2)
        self.btn_next = EditorButton(f_nav, text=ui('ui_0107'), font=('Malgun Gothic', 9), bg='#283593', fg='#FFFFFF', activebackground='#3949AB', activeforeground='#FFFFFF', relief='flat', padx=6, pady=1, cursor='hand2', command=self._go_next)
        self.btn_next.pack(side=tk.LEFT, padx=(4, 0))
        btn_f = tk.Frame(self, bg='#F0F0F0', padx=12, pady=6)
        btn_f.pack(side=tk.BOTTOM, fill=tk.X)
        action_f = tk.Frame(btn_f, bg='#F0F0F0')
        action_f.pack(anchor='center')
        btn_rep = EditorButton(action_f, text=discovery_state_text(3, action=True), font=('Malgun Gothic', 9), bg='#E6F4EA', fg='#137333', padx=6, pady=3, command=lambda: self._do_change(3))
        btn_rep.pack(side=tk.LEFT, padx=3)
        btn_disc = EditorButton(action_f, text=discovery_state_text(2, action=True), font=('Malgun Gothic', 9), bg='#E8F0FE', fg='#1A73E8', padx=6, pady=3, command=lambda: self._do_change(2))
        btn_disc.pack(side=tk.LEFT, padx=3)
        btn_undisc = EditorButton(action_f, text=discovery_state_text(1, action=True), font=('Malgun Gothic', 9), bg='#FCE8E6', fg='#D93025', padx=6, pady=3, command=lambda: self._do_change(1))
        btn_undisc.pack(side=tk.LEFT, padx=3)
        btn_unspawn = EditorButton(action_f, text=discovery_state_text(0, action=True), font=('Malgun Gothic', 9), bg='#FCE8E6', fg='#D93025', padx=6, pady=3, command=lambda: self._do_change(0))
        btn_unspawn.pack(side=tk.LEFT, padx=3)
        self.btn_hint_toggle = None
        if self.on_hint_toggle_callback or self.on_contract_cancel_callback:
            self.btn_hint_toggle = EditorButton(
                action_f, font=('Malgun Gothic', 9), bg='#E6F4EA', fg='#137333',
                activebackground='#C8E6C9', activeforeground='#137333', padx=6, pady=3,
                command=self._toggle_hint)
        body_f = tk.Frame(self, padx=14, pady=8)
        body_f.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        # 두 이미지는 하단 버튼 영역과 세로 공간을 공유한다. 버튼은 중앙,
        # 이미지는 왼쪽에 있으므로 실제로 서로 가리지 않는다.
        f_left_visuals = tk.Frame(self, width=84)
        self.discovery_visuals = f_left_visuals
        f_left_spacer = tk.Frame(body_f, width=96)
        f_left_spacer.pack(side=tk.LEFT, fill=tk.Y)
        self.discovery_left_spacer = f_left_spacer
        # 2px 테두리 양쪽을 제외한 실제 이미지 표시 영역은 80x80이다.
        f_left_img = tk.Frame(f_left_visuals, width=84, height=84, bg='#222222', relief='ridge', bd=2)
        f_left_img.pack_propagate(False)
        f_left_img.pack(side=tk.TOP)
        self.discovery_img_frame = f_left_img
        self.video_frame = f_left_img
        self.lbl_disc_img = tk.Label(f_left_img, bg='#222222')
        self.lbl_disc_img.pack(fill=tk.BOTH, expand=True)
        self.reward_img_frame = tk.Frame(f_left_visuals, width=84, height=84, bg='#222222', relief='ridge', bd=2)
        self.reward_img_frame.pack_propagate(False)
        self.lbl_reward_img = tk.Label(self.reward_img_frame, bg='#222222')
        self.lbl_reward_img.pack(fill=tk.BOTH, expand=True)
        f_right_info = tk.Frame(body_f)
        f_right_info.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.discovery_info_frame = f_right_info
        f_info1 = tk.Frame(f_right_info)
        f_info1.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))
        self.lbl_state = tk.Label(f_info1, text='', font=('Malgun Gothic', 9))
        self.lbl_state.pack(side=tk.LEFT, padx=(0, 14))
        self.lbl_value = tk.Label(f_info1, text='', font=('Malgun Gothic', 9), fg='#B06000')
        self.lbl_value.pack(side=tk.LEFT, padx=(0, 14))
        self.lbl_reward = tk.Label(f_info1, text='', font=('Malgun Gothic', 9), fg='#7B1FA2')
        self.f_info2 = tk.Frame(f_right_info)
        self.f_info2.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))
        self.lbl_dates = tk.Label(self.f_info2, text='', font=('Malgun Gothic', 9), fg='#5F6368')
        self.lbl_dates.pack(side=tk.LEFT)
        tk.Label(f_right_info, text=ui('ui_0218'), font=('Malgun Gothic', 9)).pack(anchor='w', pady=(2, 2))
        self.desc_box = tk.Text(f_right_info, font=('Malgun Gothic', 9), wrap='word', height=6, bg='#F8F9FA', relief='solid', bd=1, padx=8, pady=6)
        self.desc_box.pack(side=tk.TOP, fill=tk.X)
        self._update_disc_view(disc_info, disc_desc, current_state, disc_date, rep_date, discoverer)
        self.bind('<Left>', self._on_prev_key)
        self.bind('<Right>', self._on_next_key)
        self.bind('<Up>', lambda _event: 'break')
        self.bind('<Down>', lambda _event: 'break')
        self.bind('<Destroy>', self._on_destroy, add='+')
        self.grab_set()
        self.after_idle(self._focus_popup_control)
    def _update_disc_view(self, disc_info, disc_desc, current_state, disc_date, rep_date, discoverer):
        self.disc_index = disc_info['index']
        self.title(ui('ui_0003', disc_info['name']))
        self.lbl_title.config(text=f"[No. {disc_info['index']:03d} | ID {disc_info['disc_id']:03d}] {disc_info['name']} ({disc_info['category']})")
        self._stop_video()
        video_path = get_discovery_video_path(self.disc_index)
        # Toplevel이 화면에 배치되기 전에는 VLC가 독립 창으로 폴백할 수 있다.
        # 먼저 정지 이미지를 보이고, idle 시점에 확정된 자식 HWND로 영상을 연결한다.
        self._video_request_id = getattr(self, '_video_request_id', 0) + 1
        request_id = self._video_request_id
        if video_path:
            self._show_discovery_image(keep_visible=True)
            self.after(50, lambda: self._start_video_after_layout(video_path, request_id))
        else:
            self._show_discovery_image()
        self.lbl_value.config(text=ui('ui_0013', disc_info['value']))
        st_text = discovery_state_text(current_state)
        st_fg = '#137333' if current_state == 3 else '#1A73E8' if current_state == 2 else '#5F6368'
        self.lbl_state.config(text=ui('ui_0014', st_text), fg=st_fg)
        if self.btn_hint_toggle is not None:
            hint_id = int(disc_info.get('hint_id', -1))
            if hint_id >= 0:
                hint_state = self.get_hint_state_fn(hint_id) if self.get_hint_state_fn else 0
                is_contract = bool(self.is_contract_discovery_fn and self.is_contract_discovery_fn(self.state_index))
                is_acquired = bool(hint_state & 0x01)
                self.btn_hint_toggle.config(
                    text=ui('ui_0459') if is_contract else (ui('ui_0441') if is_acquired else ui('ui_0440')),
                    bg='#FCE8E6' if (is_contract or is_acquired) else '#E6F4EA',
                    fg='#D93025' if (is_contract or is_acquired) else '#137333',
                    activebackground='#F8D7DA' if (is_contract or is_acquired) else '#C8E6C9',
                    activeforeground='#D93025' if (is_contract or is_acquired) else '#137333')
                if not self.btn_hint_toggle.winfo_manager():
                    self.btn_hint_toggle.pack(side=tk.LEFT, padx=3)
            else:
                self.btn_hint_toggle.pack_forget()
        reward_item_id = disc_info.get('reward_item_id')
        reward_item_name = disc_info.get('reward_item_name')
        if reward_item_id is not None and reward_item_name:
            self.lbl_reward.config(text=ui('ui_0028', reward_item_name))
            self.lbl_reward.pack(side=tk.LEFT)
            reward_image_path = get_item_image_path(reward_item_id)
            if reward_image_path:
                self.reward_photo = get_cached_photo(reward_image_path)
            else:
                self.reward_photo = None
            if self.reward_photo:
                self.lbl_reward_img.config(image=self.reward_photo, text='')
                self.reward_img_frame.pack(side=tk.TOP, pady=(8, 0))
            else:
                self.reward_img_frame.pack_forget()
        else:
            self.lbl_reward.pack_forget()
            self.reward_img_frame.pack_forget()
        # 이미지가 없어도 빈 80x80 영역을 유지하여 설명 영역 폭이 바뀌지 않게 한다.
        if not self.discovery_left_spacer.winfo_manager():
            self.discovery_left_spacer.pack(side=tk.LEFT, fill=tk.Y, before=self.discovery_info_frame)
        self.discovery_visuals.place(x=14, y=42)
        if current_state > 0:
            self.lbl_dates.config(text=ui('ui_0029', disc_date, rep_date, discoverer))
            self.f_info2.pack(side=tk.TOP, fill=tk.X, pady=(0, 6))
        else:
            self.lbl_dates.config(text='')
            self.f_info2.pack_forget()
        self.desc_box.config(state='normal')
        self.desc_box.delete('1.0', tk.END)
        desc_text = disc_desc if disc_desc else ui('ui_0070')
        self.desc_box.insert('1.0', desc_text)
        self.desc_box.config(state='disabled')
        total = len(self.items_list)
        self.lbl_page.config(text=f'{self.current_list_index + 1} / {total}')
        self.btn_prev.config(state='normal' if self.current_list_index > 0 else 'disabled')
        self.btn_next.config(state='normal' if self.current_list_index < total - 1 else 'disabled')

    def _show_discovery_image(self, keep_visible=False):
        if not self.lbl_disc_img.winfo_manager():
            self.lbl_disc_img.pack(fill=tk.BOTH, expand=True)
        image_path = get_discovery_image_path(self.disc_index)
        if image_path:
            photo = get_cached_photo(image_path)
            if photo:
                self.disc_photo = photo
                self.lbl_disc_img.config(image=self.disc_photo, text='')
                if not self.discovery_img_frame.winfo_manager():
                    if self.reward_img_frame.winfo_manager():
                        self.discovery_img_frame.pack(side=tk.TOP, before=self.reward_img_frame)
                    else:
                        self.discovery_img_frame.pack(side=tk.TOP)
                return
        self.lbl_disc_img.config(image='', text='')
        if keep_visible:
            if not self.discovery_img_frame.winfo_manager():
                if self.reward_img_frame.winfo_manager():
                    self.discovery_img_frame.pack(side=tk.TOP, before=self.reward_img_frame)
                else:
                    self.discovery_img_frame.pack(side=tk.TOP)
        else:
            if not self.discovery_img_frame.winfo_manager():
                if self.reward_img_frame.winfo_manager():
                    self.discovery_img_frame.pack(side=tk.TOP, before=self.reward_img_frame)
                else:
                    self.discovery_img_frame.pack(side=tk.TOP)

    def _start_video_after_layout(self, video_path, request_id, attempt=0):
        """표시 영역의 HWND가 화면에 배치된 뒤에만 VLC 재생을 시작한다."""
        if request_id != self._video_request_id or not self.winfo_exists():
            return
        # Toplevel의 첫 화면 배치는 idle 콜백보다 늦을 수 있다.
        if not self.video_frame.winfo_ismapped() and attempt < 10:
            self.after(50, lambda: self._start_video_after_layout(video_path, request_id, attempt + 1))
            return
        if not self.video_frame.winfo_ismapped() or not self._play_video(video_path):
            self._show_discovery_image()

    def _play_video(self, video_path):
        global vlc
        runtime_dir = get_vlc_runtime_dir()
        if not runtime_dir:
            return False
        try:
            if hasattr(os, 'add_dll_directory'):
                self._vlc_dll_dir = os.add_dll_directory(runtime_dir)
            os.environ['VLC_PLUGIN_PATH'] = os.path.join(runtime_dir, 'plugins')
            if vlc is None:
                os.environ['PYTHON_VLC_LIB_PATH'] = os.path.join(runtime_dir, 'libvlc.dll')
                import vlc as vlc_module
                vlc = vlc_module
            # vmem 출력은 VLC 창을 만들지 않고, 프레임을 Tk PhotoImage로 전달한다.
            self.vlc_instance = vlc.Instance('--vout=vmem', '--avcodec-hw=none', '--no-video-title-show', '--quiet', '--no-audio', '--input-repeat=-1')
            self.vlc_player = self.vlc_instance.media_player_new()
            width, height, pitch = (80, 60, 80 * 4)
            self._video_buffer = (ctypes.c_ubyte * (height * pitch))()
            lock_type = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
            display_type = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)
            self._video_lock_callback = lock_type(lambda opaque, planes: (planes.__setitem__(0, ctypes.cast(self._video_buffer, ctypes.c_void_p).value), None)[1])
            self._video_display_callback = display_type(lambda opaque, picture: setattr(self, '_video_frame_ready', True))
            self.vlc_player.video_set_callbacks(self._video_lock_callback, None, self._video_display_callback, None)
            self.vlc_player.video_set_format('RV32', width, height, pitch)
            self._video_photo = tk.PhotoImage(width=width, height=height)
            self.lbl_disc_img.config(image=self._video_photo, text='')
            if not self.lbl_disc_img.winfo_manager():
                self.lbl_disc_img.pack(fill=tk.BOTH, expand=True)
            self.vlc_player.set_media(self.vlc_instance.media_new(video_path))
            self._video_path = video_path
            self._vlc_end_callback = lambda event: self.after(150, self._restart_video)
            self.vlc_player.event_manager().event_attach(vlc.EventType.MediaPlayerEndReached, self._vlc_end_callback)
            if self.vlc_player.play() == -1:
                return False
            self._render_video_frame()
            return True
        except Exception:
            self._stop_video()
            return False

    def _render_video_frame(self):
        """VLC 디코더 스레드가 만든 RV32 프레임을 Tk 메인 스레드에서 표시한다."""
        if self.vlc_player is None or not self.winfo_exists():
            return
        if self._video_frame_ready and self._video_buffer is not None:
            self._video_frame_ready = False
            source = bytes(self._video_buffer)
            rgb = bytearray(80 * 60 * 3)
            rgb[0::3] = source[2::4]
            rgb[1::3] = source[1::4]
            rgb[2::3] = source[0::4]
            self._video_photo.configure(data=b'P6\n80 60\n255\n' + bytes(rgb), format='PPM')
        self._video_render_job = self.after(33, self._render_video_frame)

    def _stop_video(self):
        if self._video_render_job is not None:
            try:
                self.after_cancel(self._video_render_job)
            except Exception:
                pass
            self._video_render_job = None
        if self.vlc_player is not None:
            try:
                self.vlc_player.stop()
                self.vlc_player.release()
            except Exception:
                pass
            self.vlc_player = None
        self._video_path = None
        if self.vlc_instance is not None:
            try:
                self.vlc_instance.release()
            except Exception:
                pass
            self.vlc_instance = None
        self._video_buffer = None
        self._video_lock_callback = None
        self._video_display_callback = None
        self._video_frame_ready = False
        self._video_photo = None

    def _restart_video(self):
        """종료 상태가 해제된 뒤 미디어를 다시 설정해 반복 재생한다."""
        if self.vlc_player is None or self.vlc_instance is None or not self._video_path or not self.winfo_exists():
            return
        try:
            self.vlc_player.set_media(self.vlc_instance.media_new(self._video_path))
            self.vlc_player.play()
        except Exception:
            pass

    def _on_destroy(self, event):
        if event.widget is self:
            self._stop_video()
            self._restore_previous_focus()

    def _on_prev_key(self, _event):
        self._go_prev()
        return 'break'

    def _on_next_key(self, _event):
        self._go_next()
        return 'break'

    def _focus_popup_control(self):
        """메인 목록 대신 팝업 내부 컨트롤이 키보드 포커스를 받게 한다."""
        if self.winfo_exists():
            target = self.btn_prev if self.btn_prev.cget('state') != 'disabled' else self.btn_next
            (target if target.cget('state') != 'disabled' else self.desc_box).focus_set()

    def _restore_previous_focus(self):
        if self._focus_restored:
            return
        self._focus_restored = True
        try:
            self.grab_release()
        except tk.TclError:
            pass
        try:
            if self._previous_focus is not None and self._previous_focus.winfo_exists():
                self._previous_focus.focus_set()
        except tk.TclError:
            pass
    def _go_prev(self):
        if self.current_list_index > 0:
            self.current_list_index -= 1
            idx = self.items_list[self.current_list_index]
            if self.get_disc_info_fn:
                d_info, d_desc, st, d_d, r_d, d_name = self.get_disc_info_fn(idx)
                self.state_index = idx
                self._update_disc_view(d_info, d_desc, st, d_d, r_d, d_name)
            if self.on_navigate_callback:
                self.on_navigate_callback(idx)
    def _go_next(self):
        if self.current_list_index < len(self.items_list) - 1:
            self.current_list_index += 1
            idx = self.items_list[self.current_list_index]
            if self.get_disc_info_fn:
                d_info, d_desc, st, d_d, r_d, d_name = self.get_disc_info_fn(idx)
                self.state_index = idx
                self._update_disc_view(d_info, d_desc, st, d_d, r_d, d_name)
            if self.on_navigate_callback:
                self.on_navigate_callback(idx)
    def _do_change(self, target_st):
        if self.on_state_change_callback:
            self.on_state_change_callback(self.state_index, target_st)
            if self.get_disc_info_fn:
                d_info, d_desc, st, d_d, r_d, d_name = self.get_disc_info_fn(self.state_index)
                self._update_disc_view(d_info, d_desc, st, d_d, r_d, d_name)

    def _toggle_hint(self):
        is_contract = bool(self.is_contract_discovery_fn and self.is_contract_discovery_fn(self.state_index))
        if is_contract and self.on_contract_cancel_callback:
            self.on_contract_cancel_callback(self.state_index)
        elif self.on_hint_toggle_callback:
            self.on_hint_toggle_callback(self.state_index)
        if self.get_disc_info_fn:
            d_info, d_desc, st, d_d, r_d, d_name = self.get_disc_info_fn(self.state_index)
            self._update_disc_view(d_info, d_desc, st, d_d, r_d, d_name)
class FleetVideoPreview(tk.Frame):
    """VLC vmem 출력으로 별도 창 없이 함선 영상을 Tk 안에서 재생한다."""
    WIDTH, HEIGHT = 80, 60

    def __init__(self, parent, frame_height=None):
        height = frame_height if frame_height is not None else self.HEIGHT + 4
        super().__init__(parent, width=self.WIDTH + 4, height=height, bg='#222222', relief='ridge', bd=2)
        self.pack_propagate(False)
        self.label = tk.Label(self, bg='#222222', text=ui('ui_0113'), fg='#888888', font=('Malgun Gothic', 9))
        self.label.pack(fill=tk.BOTH, expand=True)
        self.vlc_instance = self.vlc_player = None
        self._video_path = self._video_buffer = self._video_photo = None
        self._video_lock_callback = self._video_display_callback = None
        self._video_frame_ready = False
        self._render_job = None
        self._end_callback = None
        self._vlc_dll_dir = None

    def _set_video_media(self, video_path):
        """기존 VLC 인스턴스를 유지한 채 재생할 미디어만 교체한다."""
        self.config(bg='#222222')
        self.label.config(image=self._video_photo, text='', bg='#222222')
        self._video_frame_ready = False
        self.vlc_player.set_media(self.vlc_instance.media_new(video_path))
        self._video_path = video_path
        if self.vlc_player.play() == -1:
            raise RuntimeError(ui('ui_0193'))
        if self._render_job is None:
            self._render()

    def show(self, video_path, blank_when_unavailable=False):
        if video_path == self._video_path and self.vlc_player is not None:
            self.config(bg='#222222')
            self.label.config(image=self._video_photo, text='', bg='#222222')
            if self._render_job is None:
                self._render()
            return
        if not video_path:
            self.label.config(image='', text=ui('ui_0113'))
            return
        if self.vlc_player is not None and self.vlc_instance is not None:
            try:
                self._set_video_media(video_path)
                return
            except Exception:
                self.show_blank()
                return
        global vlc
        runtime_dir = get_vlc_runtime_dir()
        if not runtime_dir:
            if blank_when_unavailable:
                self.show_blank()
                return
            self.label.config(image='', text=ui('ui_0113'))
            return
        try:
            if hasattr(os, 'add_dll_directory'):
                self._vlc_dll_dir = os.add_dll_directory(runtime_dir)
            os.environ['VLC_PLUGIN_PATH'] = os.path.join(runtime_dir, 'plugins')
            if vlc is None:
                os.environ['PYTHON_VLC_LIB_PATH'] = os.path.join(runtime_dir, 'libvlc.dll')
                import vlc as vlc_module
                vlc = vlc_module
            self.vlc_instance = vlc.Instance('--vout=vmem', '--avcodec-hw=none', '--no-video-title-show', '--quiet', '--no-audio', '--input-repeat=-1')
            self.vlc_player = self.vlc_instance.media_player_new()
            pitch = self.WIDTH * 4
            self._video_buffer = (ctypes.c_ubyte * (self.HEIGHT * pitch))()
            lock_type = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
            display_type = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)
            self._video_lock_callback = lock_type(lambda _opaque, planes: (planes.__setitem__(0, ctypes.cast(self._video_buffer, ctypes.c_void_p).value), None)[1])
            self._video_display_callback = display_type(lambda _opaque, _picture: setattr(self, '_video_frame_ready', True))
            self.vlc_player.video_set_callbacks(self._video_lock_callback, None, self._video_display_callback, None)
            self.vlc_player.video_set_format('RV32', self.WIDTH, self.HEIGHT, pitch)
            self._video_photo = tk.PhotoImage(width=self.WIDTH, height=self.HEIGHT)
            self._end_callback = lambda _event: self.after(150, self._restart)
            self.vlc_player.event_manager().event_attach(vlc.EventType.MediaPlayerEndReached, self._end_callback)
            self._set_video_media(video_path)
        except Exception:
            self._release_player()
            if blank_when_unavailable:
                self.show_blank()
                return
            self.label.config(image='', text=ui('ui_0113'))

    def show_blank(self):
        """선박 영상이 없을 때에도 80x80 검은 미리보기 영역을 유지한다."""
        if self._render_job is not None:
            try:
                self.after_cancel(self._render_job)
            except Exception:
                pass
            self._render_job = None
        self._video_path = None
        self._video_frame_ready = False
        if self.vlc_player is not None:
            try:
                self.vlc_player.pause()
            except Exception:
                pass
        self.config(bg='#000000')
        self.label.config(image='', text='', bg='#000000')

    def suspend_render_for_load(self):
        """세이브 로드 중에는 VLC 호출 없이 Tk 렌더링만 멈춘다."""
        if self._render_job is not None:
            try:
                self.after_cancel(self._render_job)
            except Exception:
                pass
            self._render_job = None
        self._video_frame_ready = False
        self.config(bg='#000000')
        self.label.config(image='', text='', bg='#000000')

    def _render(self):
        if self.vlc_player is None or not self.winfo_exists():
            return
        if self._video_frame_ready and self._video_buffer is not None:
            self._video_frame_ready = False
            source = bytes(self._video_buffer)
            rgb = bytearray(self.WIDTH * self.HEIGHT * 3)
            rgb[0::3], rgb[1::3], rgb[2::3] = source[2::4], source[1::4], source[0::4]
            self._video_photo.configure(data=b'P6\n80 60\n255\n' + bytes(rgb), format='PPM')
        self._render_job = self.after(33, self._render)

    def _restart(self):
        if self.vlc_player is None or self.vlc_instance is None or not self._video_path or not self.winfo_exists():
            return
        try:
            self.vlc_player.set_media(self.vlc_instance.media_new(self._video_path))
            self.vlc_player.play()
        except Exception:
            pass

    def stop(self):
        if self._render_job is not None:
            try:
                self.after_cancel(self._render_job)
            except Exception:
                pass
            self._render_job = None
        self._release_player()

    def _release_player(self):
        """앱 종료·초기화 시에만 VLC 객체를 해제한다."""
        if self.vlc_player is not None:
            try:
                self.vlc_player.stop()
                self.vlc_player.release()
            except Exception:
                pass
            self.vlc_player = None
        if self.vlc_instance is not None:
            try:
                self.vlc_instance.release()
            except Exception:
                pass
            self.vlc_instance = None
        self._video_path = self._video_buffer = self._video_photo = None
        self._video_lock_callback = self._video_display_callback = None
        self._video_frame_ready = False
        self._end_callback = None

    def destroy(self):
        self.stop()
        super().destroy()


class CDS3SaveEditorApp:
    # ***<module>.CDS3SaveEditorApp: Failure: Different bytecode
    """CDS3SaveEditorApp"""
    def __init__(self, root):
        self.root = root
        # 명시적으로 폰트를 지정하지 않은 기본 Tk 위젯도 9pt 일반체로 통일한다.
        self.root.option_add('*Font', ('Malgun Gothic', 9))
        self.root.title(APP_TITLE)
        window_width, window_height = (950, 640)
        x = max(0, (self.root.winfo_screenwidth() - window_width) // 2)
        y = max(0, (self.root.winfo_screenheight() - window_height) // 2)
        self.root.geometry(f'{window_width}x{window_height}+{x}+{y}')
        self.root.resizable(False, False)
        possible_icons = []
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
                possible_icons.append(os.path.join(sys._MEIPASS, 'Icon.ico'))
                possible_icons.append(os.path.join(sys._MEIPASS, 'CDS3SaveEditor', 'Icon.ico'))
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        possible_icons.append(os.path.join(exe_dir, 'CDS3SaveEditor', 'Icon.ico'))
        possible_icons.append(os.path.join(exe_dir, 'Icon.ico'))
        script_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else exe_dir
        possible_icons.append(os.path.join(script_dir, 'CDS3SaveEditor', 'Icon.ico'))
        possible_icons.append(os.path.join(script_dir, 'Icon.ico'))
        possible_icons.append('D:\\OldGames\\Games\\CDS95K_Win_220518\\CDS3SaveEditor\\Icon.ico')
        for ic_path in possible_icons:
            if os.path.exists(ic_path):
                try:
                    self.root.iconbitmap(default=ic_path)
                    self.root.iconbitmap(ic_path)
                except Exception:
                    continue
                break
        self.item_db = load_item_database()
        self.discovery_db = load_discovery_database()
        self.event_db = load_event_database()
        # 검색 때마다 모든 항목의 이름을 소문자 변환하지 않도록, 변하지 않는 검색용 문자열을 미리 만든다.
        self._item_search_index = [(item, item['name'].casefold()) for item in self.item_db]
        self._discovery_search_index = [
            (index, discovery, f"{discovery['name']}\n{discovery['category']}".casefold())
            for index, discovery in enumerate(self.discovery_db)
        ]
        self._character_search_index = [
            (int(character['id']), character.get('name') or UI_EMPTY_VALUE,
             (character.get('name') or UI_EMPTY_VALUE).casefold())
            for character in CHARACTER_DATA['records']
        ]
        def on_combobox_arrow(event, delta):
            try:
                w = event.widget
                values = w['values']
                if not values:
                    return 'break'
                cur = w.current()
                new_idx = max(0, min(len(values) - 1, cur + delta))
                if new_idx != cur:
                    w.current(new_idx)
                    w.event_generate('<<ComboboxSelected>>')
                return 'break'
            except Exception:
                return None
        self.root.bind_class('TCombobox', '<Down>', lambda e: on_combobox_arrow(e, 1))
        self.root.bind_class('TCombobox', '<Up>', lambda e: on_combobox_arrow(e, (-1)))
        self.root.bind_class('TCombobox', '<MouseWheel>', lambda e: 'break')
        self.root.bind_class('Combobox', '<MouseWheel>', lambda e: 'break')

        def move_treeview_selection(event, delta):
            """모든 목록에서 ↑/↓로 이전·다음 항목을 확실히 선택한다."""
            tree = event.widget
            try:
                items = tree.get_children('')
                if not items:
                    return 'break'
                selection = tree.selection()
                if selection and selection[0] in items:
                    current = items.index(selection[0])
                else:
                    focused = tree.focus()
                    current = items.index(focused) if focused in items else (0 if delta > 0 else len(items) - 1)
                target = items[max(0, min(len(items) - 1, current + delta))]
                tree.selection_set(target)
                tree.focus(target)
                tree.see(target)
                return 'break'
            except tk.TclError:
                return None
        self.root.bind_class('Treeview', '<Down>', lambda e: move_treeview_selection(e, 1))
        self.root.bind_class('Treeview', '<Up>', lambda e: move_treeview_selection(e, -1))
        self._move_treeview_selection = move_treeview_selection

        def clear_editable_combo_selection(event):
            """편집형 콤보박스에 남는 전체 텍스트 선택 표시를 제거한다."""
            widget = event.widget
            try:
                if str(widget.cget('state')) != 'normal':
                    return
                def clear_after_idle():
                    try:
                        widget.selection_clear()
                        widget.icursor(tk.END)
                    except tk.TclError:
                        pass
                widget.after_idle(clear_after_idle)
            except tk.TclError:
                pass
        self.root.bind_class('TCombobox', '<FocusIn>', clear_editable_combo_selection, add='+')
        self.root.bind_class('TCombobox', '<<ComboboxSelected>>', clear_editable_combo_selection, add='+')
        self.file_path = None
        self.file_buffer = None
        # 세이브를 연 폴더에서 검증한 CDS_95.EXE의 후원자 취향 원본값.
        # 게임 EXE를 찾지 못한 경우에는 기존 추출 JSON 값을 역변환해 표시한다.
        self._sponsor_exe_preference_flags = {}
        self._sponsor_contract_hint_resets = {}
        self.fleet_original_buffer = None
        self.city_original_buffer = None
        self.person_original_buffer = None
        # 인물 통합 화면은 편집 중인 file_buffer와 분리된 마지막 저장/로드 시점의
        # 스냅샷만 표시한다. 역할을 목록에서 지정해도 이 값은 저장 완료 전까지
        # 바뀌지 않는다.
        self.person_display_buffer = None
        self.pocket_ids = []
        self.storage_ids = []
        self.discovery_state = [0] * len(self.discovery_db)
        self.discovery_discoverer = [''] * len(self.discovery_db)
        self.discovery_disc_date = [UI_EMPTY_VALUE] * len(self.discovery_db)
        self.discovery_rep_date = [UI_EMPTY_VALUE] * len(self.discovery_db)
        self._discovery_view_revision = 0
        self.event_state = [0] * len(self.event_db)
        self.sea_monster_state = [False] * 4
        self.player_face_id = None
        self.player_face_photo = None
        self.wife_face_photo = None
        self.unmarried_photo = None
        self._img_cache = {}
        self._update_check_in_progress = False
        self._update_download_in_progress = False
        self._update_notice = self._consume_update_notice()
        self.setup_styles()
        self.create_widgets()
        self._enable_tree_zebra()
        self._enable_tree_auto_scrollbars()
        self._enable_tree_sorting()
        self.apply_hardware_acceleration()
        self.refresh_stats_table()
        self.refresh_money_table()
        self.refresh_skills_table()
        self.refresh_fleet_list()
        self.refresh_cities_list()
        self.refresh_discoveries_table()
        self.refresh_events_table()
        self._schedule_all_treeview_autofit()
        self.set_controls_enabled(False)
        self._is_closing = False
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)
        if self._update_notice is not None:
            self.root.after(400, self._show_update_notice)
        # 개발용 .pyw 실행에서는 네트워크 확인을 생략하고, 배포 EXE에서만 시작 시
        # 최신 릴리즈를 조용히 확인한다. 새 버전이 있을 때만 버튼을 표시한다.
        if getattr(sys, 'frozen', False):
            self.root.after(1500, lambda: self.check_for_updates(automatic=True))

    def on_close(self):
        """VLC 작업 스레드가 남아도 에디터 프로세스를 즉시 종료한다."""
        if self._is_closing:
            return
        self._is_closing = True
        # libVLC의 stop/release는 드물게 디코더 스레드를 기다리며 멈춘다.
        # mainloop만 끝내고 __main__의 즉시 종료 경로에 맡긴다.
        self.root.quit()

    @staticmethod
    def _release_asset(release):
        """Release 자산에서 해당 버전의 ZIP 배포 파일을 찾는다."""
        assets = release.get('assets', []) if isinstance(release, dict) else []
        release_version = str(release.get('tag_name', '')).strip().lstrip('vV')
        configured_asset_name = (UPDATE_ASSET_NAME.format(version=release_version)
                                 if release_version and '{version}' in UPDATE_ASSET_NAME
                                 else UPDATE_ASSET_NAME)
        versioned_asset_name = (f'CDS_SaveEditor_v{release_version}.zip'
                                if release_version else '')
        for asset in assets:
            if asset.get('name') in (configured_asset_name, versioned_asset_name):
                return asset
        return next((asset for asset in assets
                     if str(asset.get('name', '')).lower().endswith('.zip')), None)

    @staticmethod
    def _extract_update_executable(archive_path):
        """배포 ZIP 안의 단일 실행 파일을 임시 폴더로 안전하게 푼다."""
        extract_directory = tempfile.mkdtemp(prefix='CDS_SaveEditor_update_')
        try:
            with zipfile.ZipFile(archive_path) as archive:
                candidates = [info for info in archive.infolist()
                              if not info.is_dir()
                              and os.path.basename(info.filename).lower() == UPDATE_EXECUTABLE_NAME.lower()]
                if len(candidates) != 1:
                    raise ValueError(ui('ui_0482'))
                info = candidates[0]
                destination = os.path.abspath(os.path.join(extract_directory, info.filename))
                if os.path.commonpath((extract_directory, destination)) != extract_directory:
                    raise ValueError(ui('ui_0483'))
                archive.extract(info, extract_directory)
            if not os.path.isfile(destination):
                raise ValueError(ui('ui_0484'))
            return destination
        except (OSError, ValueError, zipfile.BadZipFile):
            try:
                for root, directories, filenames in os.walk(extract_directory, topdown=False):
                    for filename in filenames:
                        os.remove(os.path.join(root, filename))
                    for directory in directories:
                        os.rmdir(os.path.join(root, directory))
                os.rmdir(extract_directory)
            except OSError:
                pass
            raise

    @staticmethod
    def _consume_update_notice():
        """업데이터가 넘긴 일회용 릴리즈 노트를 읽고 즉시 제거한다."""
        try:
            marker_index = sys.argv.index('--update-notice')
            notice_path = sys.argv[marker_index + 1]
        except (ValueError, IndexError):
            return None
        try:
            with open(notice_path, 'r', encoding='utf-8') as notice_file:
                notice = json.load(notice_file)
        except (OSError, json.JSONDecodeError):
            return None
        finally:
            try:
                if 'notice_path' in locals() and os.path.isfile(notice_path):
                    os.remove(notice_path)
            except OSError:
                pass
        if not isinstance(notice, dict):
            return None
        version = str(notice.get('version', '')).strip()
        if parse_release_version(version) != parse_release_version(APP_VERSION):
            return None
        return version, str(notice.get('notes', '')).strip()

    def _show_update_notice(self):
        """자동 업데이트로 재시작된 경우에만 해당 릴리즈의 변경 내역을 안내한다."""
        if self._update_notice is None:
            return
        version, notes = self._update_notice
        self._update_notice = None
        messagebox.showinfo(APP_TITLE, ui('ui_0451', version, notes or ui('ui_0452')))

    def _set_update_button_state(self, state):
        try:
            self.btn_check_update.config(state=state)
        except (AttributeError, tk.TclError):
            pass

    def _show_update_button(self, visible):
        """새 버전이 확인된 경우에만 상단의 업데이트 버튼을 노출한다."""
        try:
            if visible:
                if not self.btn_check_update.winfo_manager():
                    self.btn_check_update.pack(side=tk.LEFT, padx=4, after=self.btn_save)
            else:
                self.btn_check_update.pack_forget()
        except (AttributeError, tk.TclError):
            pass

    def check_for_updates(self, automatic=False):
        """GitHub의 최신 정식 Release를 백그라운드에서 조회한다."""
        if self._update_check_in_progress or self._update_download_in_progress or not UPDATE_LATEST_URL:
            return
        self._update_check_in_progress = True
        self._set_update_button_state(tk.DISABLED)
        if not automatic:
            self.lbl_status.config(text=ui('ui_0418'))

        def worker():
            try:
                request = Request(UPDATE_LATEST_URL, headers={
                    'Accept': 'application/vnd.github+json',
                    'User-Agent': f'CDS-SaveEditor/{APP_VERSION}',
                })
                with urlopen(request, timeout=8) as response:
                    release = json.loads(response.read().decode('utf-8'))
                self.root.after(0, lambda: self._handle_update_release(release, automatic))
            except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
                try:
                    self.root.after(0, lambda: self._handle_update_error(error, automatic))
                except tk.TclError:
                    pass

        threading.Thread(target=worker, name='update-check', daemon=True).start()

    def _handle_update_error(self, error, automatic):
        self._update_check_in_progress = False
        self._set_update_button_state(tk.NORMAL)
        if not automatic:
            self.lbl_status.config(text=ui('ui_0117'))
            messagebox.showwarning(APP_TITLE, ui('ui_0423', str(error)))

    def _handle_update_release(self, release, automatic):
        self._update_check_in_progress = False
        self._set_update_button_state(tk.NORMAL)
        remote_tag = str(release.get('tag_name', '')).strip()
        local_version = parse_release_version(APP_VERSION)
        remote_version = parse_release_version(remote_tag)
        if not remote_version or not local_version or remote_version <= local_version:
            if not automatic:
                self.lbl_status.config(text=ui('ui_0117'))
                messagebox.showinfo(APP_TITLE, ui('ui_0419', APP_VERSION))
            return
        asset = self._release_asset(release)
        if not asset or not asset.get('browser_download_url'):
            if not automatic:
                self.lbl_status.config(text=ui('ui_0117'))
                messagebox.showwarning(APP_TITLE, ui('ui_0426'))
            return
        if automatic:
            # 시작 시에는 확인 창을 띄우지 않는다. 새 버전이 있을 때만 사용자가
            # 원할 때 다시 확인·설치를 진행할 수 있도록 버튼을 보여 준다.
            self._show_update_button(True)
            return
        if messagebox.askyesno(APP_TITLE, ui('ui_0420', remote_tag.lstrip('vV'), APP_VERSION)):
            self.download_and_install_update(asset, release)
        elif not automatic:
            self.lbl_status.config(text=ui('ui_0117'))

    def download_and_install_update(self, asset, release):
        """새 ZIP을 내려받아 해시를 검증·압축 해제한 뒤 종료 후 교체를 예약한다."""
        if self._update_download_in_progress:
            return
        if not getattr(sys, 'frozen', False):
            self.lbl_status.config(text=ui('ui_0117'))
            messagebox.showinfo(APP_TITLE, ui('ui_0425'))
            return
        self._update_download_in_progress = True
        self._set_update_button_state(tk.DISABLED)
        self.lbl_status.config(text=ui('ui_0421'))

        def worker():
            partial_path = None
            download_path = None
            try:
                asset_name = os.path.basename(str(asset.get('name', UPDATE_ASSET_NAME))) or UPDATE_ASSET_NAME
                partial_path = os.path.join(tempfile.gettempdir(), f'{asset_name}.{os.getpid()}.part')
                download_path = partial_path[:-5]
                digest = hashlib.sha256()
                request = Request(str(asset['browser_download_url']), headers={
                    'Accept': 'application/octet-stream',
                    'User-Agent': f'CDS-SaveEditor/{APP_VERSION}',
                })
                with urlopen(request, timeout=30) as response, open(partial_path, 'wb') as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        digest.update(chunk)
                expected_digest = str(asset.get('digest', ''))
                if expected_digest.startswith('sha256:') and digest.hexdigest().lower() != expected_digest[7:].lower():
                    raise ValueError(ui('ui_0485'))
                os.replace(partial_path, download_path)
                extracted_exe_path = self._extract_update_executable(download_path)
                try:
                    os.remove(download_path)
                except OSError:
                    pass
                self.root.after(0, lambda: self._launch_update_replacer(extracted_exe_path, release))
            except (HTTPError, URLError, TimeoutError, OSError, ValueError, zipfile.BadZipFile) as error:
                for path in (partial_path, download_path):
                    if not path or not os.path.exists(path):
                        continue
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                try:
                    self.root.after(0, lambda: self._handle_update_download_error(error))
                except tk.TclError:
                    pass

        threading.Thread(target=worker, name='update-download', daemon=True).start()

    def _handle_update_download_error(self, error):
        self._update_download_in_progress = False
        self._set_update_button_state(tk.NORMAL)
        self.lbl_status.config(text=ui('ui_0117'))
        messagebox.showerror(APP_TITLE, ui('ui_0424', str(error)))

    def _launch_update_replacer(self, download_path, release):
        """현재 EXE가 끝난 뒤 파일을 바꾸고 새 버전을 시작하는 작은 배치 파일을 실행한다."""
        target_path = os.path.abspath(sys.executable)
        script_path = os.path.join(tempfile.gettempdir(), f'CDS_SaveEditor_update_{os.getpid()}.cmd')
        notice_path = os.path.join(tempfile.gettempdir(), f'CDS_SaveEditor_update_notice_{os.getpid()}.json')
        try:
            # 새 EXE는 이 일회용 파일을 읽어 업데이트 직후에만 릴리즈 노트를 표시한다.
            with open(notice_path, 'w', encoding='utf-8') as notice_file:
                json.dump({
                    'version': str(release.get('tag_name', '')).lstrip('vV'),
                    'notes': str(release.get('body', '')).strip(),
                }, notice_file, ensure_ascii=False)
            # PID를 폴링하면 PID가 재사용된 경우 영구 대기할 수 있다. 현재 EXE의
            # 파일 잠금이 풀릴 때까지 실제 교체를 재시도하는 편이 안전하다.
            script = '\r\n'.join((
                '@echo off',
                'setlocal',
                f'set "UPDATE_SOURCE={download_path}"',
                f'set "UPDATE_TARGET={target_path}"',
                f'set "UPDATE_NOTICE={notice_path}"',
                f'set "UPDATE_DIRECTORY={os.path.dirname(download_path)}"',
                ':replace_editor',
                'move /Y "%UPDATE_SOURCE%" "%UPDATE_TARGET%" >nul 2>nul',
                'if errorlevel 1 (',
                '  timeout /t 1 /nobreak >nul',
                '  goto replace_editor',
                ')',
                # PyInstaller 6.9+에서는 부모 EXE의 _PYI_* 환경을 상속한 재시작을
                # 작업자 프로세스로 처리한다. 업데이트 후 새 EXE는 기존 one-file
                # 인스턴스보다 오래 살아야 하므로 독립 인스턴스로 초기화해야 한다.
                'set "PYINSTALLER_RESET_ENVIRONMENT=1"',
                'start "" "%UPDATE_TARGET%" --update-notice "%UPDATE_NOTICE%"',
                'rmdir "%UPDATE_DIRECTORY%" 2>nul',
                'del "%~f0"',
            ))
            with open(script_path, 'w', encoding='mbcs', newline='') as script_file:
                script_file.write(script)
            creationflags = (getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0) |
                             getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            subprocess.Popen(['cmd.exe', '/d', '/c', script_path], close_fds=True, creationflags=creationflags)
        except (OSError, ValueError) as error:
            self._handle_update_download_error(error)
            return
        self.lbl_status.config(text=ui('ui_0422'))
        self.root.after(100, self.on_close)

    def setup_styles(self):
        # ***<module>.CDS3SaveEditorApp.setup_styles: Failure: Different bytecode
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', font=('Malgun Gothic', 9))
        style.configure('TNotebook.Tab', padding=[10, 4], font=('Malgun Gothic', 9))
        style.configure('Treeview.Heading', font=('Malgun Gothic', 9, 'bold'))
        style.configure('Treeview', rowheight=22, font=('Malgun Gothic', 9))

    def apply_hardware_acceleration(self):
        return None

    def _schedule_treeview_autofit(self, *trees):
        """목록 갱신 직후 실제 배치 폭을 기준으로 열 너비를 다시 계산한다."""
        if getattr(self, '_suspend_tree_autofit', False):
            pending = getattr(self, '_pending_tree_autofit', None)
            if pending is None:
                pending = set()
                self._pending_tree_autofit = pending
            pending.update(tree for tree in trees if tree is not None and tree.winfo_exists())
            return
        # 여러 표가 같은 이벤트에서 갱신돼도 after 콜백을 표마다 만들지 않는다.
        # 한 번의 유휴 배치에서 중복 없는 표만 열너비를 계산한다.
        pending = getattr(self, '_scheduled_tree_autofit', None)
        if pending is None:
            pending = set()
            self._scheduled_tree_autofit = pending
        pending.update(tree for tree in trees if tree is not None and tree.winfo_exists())
        if getattr(self, '_scheduled_tree_autofit_job', None) is None:
            self._scheduled_tree_autofit_job = self.root.after(20, self._flush_scheduled_treeview_autofit)

    def _flush_scheduled_treeview_autofit(self):
        """동일 UI 주기에서 모인 열너비 요청을 한 번에 처리한다."""
        self._scheduled_tree_autofit_job = None
        trees = tuple(getattr(self, '_scheduled_tree_autofit', ()))
        self._scheduled_tree_autofit = set()
        for tree in trees:
            try:
                if tree.winfo_exists():
                    autofit_columns(tree)
            except tk.TclError:
                continue

    def _flush_pending_treeview_autofit(self):
        """배치 갱신 중 모아 둔 표의 열맞춤을 한 번씩만 예약한다."""
        pending = tuple(getattr(self, '_pending_tree_autofit', ()))
        self._pending_tree_autofit = set()
        self._schedule_treeview_autofit(*pending)

    def _schedule_all_treeview_autofit(self):
        trees = []

        def collect(widget):
            for child in widget.winfo_children():
                if isinstance(child, ttk.Treeview):
                    trees.append(child)
                collect(child)

        collect(self.root)
        self._schedule_treeview_autofit(*trees)

    def _enable_tree_zebra(self):
        """Apply alternating row colors to every Treeview, including future inserts."""
        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, ttk.Treeview):
                    child.tag_configure('zebra_odd', background='#FFFFFF')
                    child.tag_configure('zebra_even', background='#F0F0F0')
                    original_insert = child.insert
                    original_delete = child.delete
                    child._zebra_next_index = 0

                    def striped_insert(*args, _tree=child, _insert=original_insert, **kwargs):
                        custom_tags = tuple(kwargs.pop('tags', ()))
                        row_index = _tree._zebra_next_index
                        zebra_tag = 'zebra_odd' if row_index % 2 == 0 else 'zebra_even'
                        # 사용자 지정 강조 태그는 얼룩무늬 태그 뒤에 유지해 배경색을
                        # 덮어쓴다. 삽입 뒤 item()을 다시 호출하지 않아도 된다.
                        kwargs['tags'] = (zebra_tag, *custom_tags)
                        item = _insert(*args, **kwargs)
                        _tree._zebra_next_index = row_index + 1
                        return item

                    def striped_delete(*items, _tree=child, _delete=original_delete):
                        result = _delete(*items)
                        if not _tree.get_children(''):
                            _tree._zebra_next_index = 0
                        return result

                    child.insert = striped_insert
                    child.delete = striped_delete
                    self._refresh_tree_zebra(child)
                    child._zebra_next_index = len(child.get_children(''))
                walk(child)
        walk(self.root)

    def _enable_tree_auto_scrollbars(self):
        """스크롤바가 없는 모든 Treeview에 필요할 때만 나타나는 세로 스크롤을 붙인다."""
        def add_scrollbar(tree):
            try:
                if str(tree.cget('yscrollcommand')):
                    return
                parent = tree.master
                if tree.winfo_manager() != 'pack' or parent is None:
                    return
                scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=tree.yview)

                def sync(first, last, widget=tree, bar=scrollbar):
                    try:
                        should_show = float(first) > 0.0 or float(last) < 1.0
                    except (TypeError, ValueError):
                        return
                    bar.set(first, last)
                    visible = getattr(bar, '_auto_visible', None)
                    if visible is None:
                        visible = bool(bar.winfo_manager())
                    if should_show and not visible:
                        bar.pack(side=tk.RIGHT, fill=tk.Y, before=widget)
                        bar._auto_visible = True
                    elif not should_show and visible:
                        bar.pack_forget()
                        bar._auto_visible = False

                tree.configure(yscrollcommand=sync)
                tree._auto_vertical_scrollbar = scrollbar
            except tk.TclError:
                pass

        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, ttk.Treeview):
                    add_scrollbar(child)
                walk(child)
        walk(self.root)

    @staticmethod
    def _refresh_tree_zebra(tree):
        for index, item in enumerate(tree.get_children('')):
            custom_tags = tuple(tag for tag in tree.item(item, 'tags')
                                if tag not in ('zebra_odd', 'zebra_even'))
            zebra_tag = 'zebra_odd' if index % 2 == 0 else 'zebra_even'
            tree.item(item, tags=(zebra_tag, *custom_tags))

    def _enable_tree_sorting(self):
        """Enable ascending/descending sorting when a Treeview heading is clicked."""
        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, ttk.Treeview):
                    columns = tuple(child['columns'])
                    child._sort_header_texts = {
                        column: child.heading(column, 'text') or column for column in columns
                    }
                    child._sort_column = None
                    child._sort_reverse = False
                    for column in columns:
                        child.heading(
                            column,
                            command=lambda c=column, tree=child: self._sort_tree_by_column(tree, c),
                        )
                walk(child)
        walk(self.root)

    def _sort_tree_by_column(self, tree, column):
        """Sort one tree column; clicking the active heading reverses the direction."""
        reverse = not tree._sort_reverse if tree._sort_column == column else False

        def sort_key(item):
            value = str(tree.set(item, column)).strip()
            numeric_value = value.replace(',', '').split(' ')[0]
            try:
                return (0, int(numeric_value, 0))
            except ValueError:
                return (1, value.casefold())

        items = list(tree.get_children(''))
        items.sort(key=sort_key, reverse=reverse)
        for index, item in enumerate(items):
            tree.move(item, '', index)

        tree._sort_column = column
        tree._sort_reverse = reverse
        for current_column, header_text in tree._sort_header_texts.items():
            marker = (' ▼' if reverse else ' ▲') if current_column == column else ''
            tree.heading(current_column, text=f'{header_text}{marker}')
        self._refresh_tree_zebra(tree)

    def create_widgets(self):
        # ***<module>.CDS3SaveEditorApp.create_widgets: Failure: Different bytecode
        self.root.bind('<Control-o>', lambda e: self.on_open_file())
        self.root.bind('<Control-s>', lambda e: self.on_save_file())
        top_bar = tk.Frame(self.root, height=40, bg='#F0F0F0', padx=8, pady=6)
        top_bar.pack(side=tk.TOP, fill=tk.X)
        btn_open = EditorButton(top_bar, text=ui('ui_0114'), font=('Malgun Gothic', 9), command=self.on_open_file, bg='#E8F0FE', padx=8)
        btn_open.pack(side=tk.LEFT, padx=4)
        self.btn_save = EditorButton(top_bar, text=ui('ui_0115'), font=('Malgun Gothic', 9), command=self.on_save_file, bg='#E6F4EA', fg='#137333', padx=8)
        self.btn_save.pack(side=tk.LEFT, padx=4)
        self.btn_check_update = EditorButton(top_bar, text=ui('ui_0417'), font=('Malgun Gothic', 9), command=self.check_for_updates, padx=8)
        self.chk_auto_backup = tk.BooleanVar(value=True)
        self.chk_backup_widget = tk.Checkbutton(top_bar, text=ui('ui_0116'), variable=self.chk_auto_backup, font=('Malgun Gothic', 9), bg='#F0F0F0')
        self.chk_backup_widget.pack(side=tk.LEFT, padx=10)
        self.lbl_status = tk.Label(top_bar, text=ui('ui_0117'), font=('Malgun Gothic', 9), fg='#5F6368')
        self.lbl_status.pack(side=tk.RIGHT, padx=8)
        notebook_style = ttk.Style(self.root)
        notebook_style.configure('Editor.TNotebook', tabmargins=(2, 5, 2, 0))
        notebook_style.configure(
            'Editor.TNotebook.Tab', width=15, padding=(8, 5), font=('Malgun Gothic', 9),
            relief='flat', anchor='center')
        notebook_style.map(
            'Editor.TNotebook.Tab',
            relief=[('selected', 'raised'), ('!selected', 'flat')],
            padding=[('selected', (8, 7, 8, 6)), ('!selected', (8, 5))])
        self.notebook = ttk.Notebook(self.root, style='Editor.TNotebook')
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        # ttk.Notebook의 직접 자식 대신 Notebook 부모의 자식 프레임을 pane으로
        # 등록하는 Tkinter 깜빡임 우회 방식이다.
        self.tab_profile = ttk.Frame(self.root)
        self.tab_skills = ttk.Frame(self.notebook)
        self.tab_fleet = ttk.Frame(self.root)
        self.tab_cities = ttk.Frame(self.root)
        self.tab_items = ttk.Frame(self.root)
        self.tab_discoveries = ttk.Frame(self.root)
        self.tab_events = ttk.Frame(self.root)
        self.notebook.add(self.tab_profile, text=TAB_TITLES['profile'])
        self.notebook.add(self.tab_fleet, text=TAB_TITLES['fleet'])
        self.notebook.add(self.tab_cities, text=TAB_TITLES['cities'])
        self.notebook.add(self.tab_items, text=TAB_TITLES['items'])
        self.notebook.add(self.tab_discoveries, text=TAB_TITLES['discoveries'])
        self.notebook.add(self.tab_events, text=TAB_TITLES['events'])
        self.build_profile_tab()
        self.build_skills_tab()
        self.build_fleet_tab()
        self.build_cities_tab()
        self.build_items_tab()
        self.build_discoveries_tab()
        self.build_events_tab()
        center_treeview_columns(self.root)
        self._configure_text_byte_limit(self.txt_last_name, 18)
        self._configure_text_byte_limit(self.txt_first_name, 18)
        for spinbox, minimum, maximum in (
            (self.spn_birth_y, 1000, 3000), (self.spn_birth_m, 1, 12), (self.spn_birth_d, 1, 31),
            (self.spn_game_y, 1000, 3000), (self.spn_game_m, 1, 12), (self.spn_game_d, 1, 31),
            (self.spn_batch_money, 0, 99999999),
            (self.spn_batch_reputation, 0, PLAYER_REPUTATION_MAX), (self.spn_batch_tech, 0, 3), (self.spn_batch_lang, 0, 3),
        ):
            self._configure_bounded_spinbox(spinbox, minimum, maximum)

    def _configure_text_byte_limit(self, entry, max_bytes):
        """Enforce a fixed CP949 field without breaking Korean IME composition."""
        if isinstance(entry, NativeWinEdit):
            entry.max_bytes = max_bytes
            return
        entry.configure(validate='none')
        enforce = lambda _event=None: self._trim_entry_to_cp949_bytes(entry, max_bytes)
        entry.bind('<KeyRelease>', enforce, add='+')
        entry.bind('<<Paste>>', lambda _event: self.root.after_idle(enforce), add='+')
        entry.bind('<FocusOut>', enforce, add='+')

    @staticmethod
    def _trim_entry_to_cp949_bytes(entry, max_bytes):
        original = entry.get()
        encoded_length = 0
        accepted = []
        for character in original:
            try:
                character_bytes = character.encode('cp949')
            except UnicodeEncodeError:
                continue
            if encoded_length + len(character_bytes) > max_bytes:
                break
            accepted.append(character)
            encoded_length += len(character_bytes)
        trimmed = ''.join(accepted)
        if trimmed != original:
            cursor = min(entry.index(tk.INSERT), len(trimmed))
            entry.delete(0, tk.END)
            entry.insert(0, trimmed)
            entry.icursor(cursor)

    def _configure_bounded_spinbox(self, spinbox, minimum, maximum):
        """스핀 상한을 넘는 직접 입력도 즉시 최대값으로 보정한다."""
        command = self.root.register(
            lambda proposed: proposed == '' or proposed.isdigit())
        spinbox.configure(validate='key', validatecommand=(command, '%P'))
        spinbox.bind('<KeyRelease>', lambda _event: self._clamp_spinbox(spinbox, minimum, maximum), add='+')
        spinbox.bind('<FocusOut>', lambda _event: self._clamp_spinbox(spinbox, minimum, maximum), add='+')

    @staticmethod
    def _clamp_spinbox(spinbox, minimum, maximum):
        try:
            value = int(spinbox.get())
        except (TypeError, ValueError):
            return
        value = max(minimum, min(maximum, value))
        if spinbox.get() != str(value):
            spinbox.delete(0, tk.END)
            spinbox.insert(0, str(value))

    def ask_bounded_integer(self, title, prompt, initial_value, minimum, maximum):
        """Numeric-only replacement for tkinter.simpledialog.askinteger."""
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.withdraw()
        result = {'value': None}
        body = tk.Frame(dialog, padx=14, pady=12)
        body.pack(fill=tk.BOTH, expand=True)
        tk.Label(body, text=prompt, justify='left', font=('Malgun Gothic', 9)).pack(anchor='w')
        value_var = tk.StringVar(value=str(initial_value))
        entry = ttk.Spinbox(body, textvariable=value_var, from_=minimum, to=maximum,
                             width=16, justify='center', font=('Malgun Gothic', 9))
        digits_only = self.root.register(
            lambda proposed, low=minimum: (proposed == '' or
            (proposed == '-' and low < 0) or proposed.lstrip('-').isdigit()))
        entry.configure(validate='key', validatecommand=(digits_only, '%P'))
        entry.bind('<KeyRelease>', lambda _event: self._clamp_spinbox(entry, minimum, maximum), add='+')
        entry.pack(anchor='center', pady=(8, 2))
        error_var = tk.StringVar(value='')
        tk.Label(body, textvariable=error_var, fg='#B3261E', font=('Malgun Gothic', 9)).pack(anchor='center')
        buttons = tk.Frame(body)
        buttons.pack(anchor='center', pady=(8, 0))

        def confirm():
            try:
                value = int(value_var.get())
            except ValueError:
                error_var.set(ui('ui_0050', minimum, maximum))
                return
            if not minimum <= value <= maximum:
                error_var.set(ui('ui_0030', minimum, maximum))
                return
            result['value'] = value
            dialog.destroy()

        EditorButton(buttons, text=ui('ui_0175'), width=8, command=confirm).pack(side=tk.LEFT)
        dialog.bind('<Return>', lambda _event: confirm())
        dialog.bind('<Escape>', lambda _event: dialog.destroy())
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f'+{max(0, x)}+{max(0, y)}')
        dialog.deiconify()
        dialog.grab_set()
        entry.focus_set()
        entry.selection_range(0, tk.END)
        self.root.wait_window(dialog)
        return result['value']

    def build_fleet_tab(self):
        """Build the fleet list, editor, and read-only ship-base information panes."""
        parent = self.tab_fleet
        configure_equal_columns(parent, 3, 'fleet_columns')

        left = tk.LabelFrame(parent, text=GROUP_TITLES['fleet_list'], font=('Malgun Gothic', 9, 'bold'), padx=6, pady=6)
        left.grid(row=0, column=0, sticky='nsew', padx=(10, 5), pady=10)
        cols = ('index', 'name')
        self.lst_fleet = ttk.Treeview(left, columns=cols, show='headings', height=8, selectmode='browse')
        self.lst_fleet.heading('index', text=TREE_COLUMN_TITLES['fleet']['index'])
        self.lst_fleet.heading('name', text=TREE_COLUMN_TITLES['fleet']['name'])
        self.lst_fleet.column('index', width=45, anchor='center', stretch=False)
        self.lst_fleet.column('name', width=190, anchor='w', stretch=True)
        self.lst_fleet.pack(fill=tk.BOTH, expand=True)
        self.lst_fleet.bind('<<TreeviewSelect>>', self.on_fleet_select)
        # 이미 선택된 함선을 다시 눌러도, 로드 후 보류된 영상 미리보기를 갱신한다.
        self.lst_fleet.bind('<ButtonRelease-1>', self.on_fleet_select, add='+')
        fleet_list_actions = tk.Frame(left)
        fleet_list_actions.pack(pady=(7, 0))
        EditorButton(fleet_list_actions, text=ui('ui_0338'), width=9, bg='#E6F4EA', fg='#137333', command=self.add_fleet_ship).pack(
            side=tk.LEFT, padx=(0, 4))
        self.btn_fleet_reset = EditorButton(
            fleet_list_actions, text=ui('ui_0222'), width=9, bg='#E8F0FE', fg='#1A73E8',
            command=self.reset_fleet_edits,
        )
        self.btn_fleet_reset.pack(side=tk.LEFT, padx=4)
        self.btn_fleet_reset.pack_forget()
        self.btn_fleet_remove = EditorButton(
            fleet_list_actions, text=ui('ui_0334'), width=9, bg='#FCE8E6', fg='#D93025',
            command=self.remove_selected_fleet_ship,
        )
        self.btn_fleet_remove.pack(side=tk.LEFT, padx=(4, 0))

        editor = tk.LabelFrame(parent, text=GROUP_TITLES['fleet_editor'], font=('Malgun Gothic', 9, 'bold'), padx=10, pady=10)
        editor.grid(row=0, column=1, sticky='nsew', padx=5, pady=10)
        editor.columnconfigure(1, weight=1)
        preview = tk.Frame(editor)
        preview.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 8))
        video_column = tk.Frame(preview)
        video_column.pack(side=tk.LEFT)
        self.fleet_video_column = video_column
        # 표시 프레임은 선수상과 같은 80x80 이미지 영역(테두리 포함 84x84)으로 맞춘다.
        self.fleet_video_preview = FleetVideoPreview(video_column, frame_height=84)
        self.fleet_video_preview.pack()
        figurehead_column = tk.Frame(preview)
        figurehead_column.pack(side=tk.RIGHT)
        self.fleet_figurehead_column = figurehead_column
        figurehead_box = tk.Frame(figurehead_column, width=84, height=84, bg='#222222', relief='ridge', bd=2)
        figurehead_box.pack_propagate(False)
        figurehead_box.pack()
        self.fleet_figurehead_box = figurehead_box
        self.lbl_fleet_figurehead_img = tk.Label(figurehead_box, bg='#222222')
        self.lbl_fleet_figurehead_img.pack(fill=tk.BOTH, expand=True)
        self.fleet_edit_vars = {}
        single_fields = [
            (ui('ui_0062'), 'name'), (fleet_label('ui_0130', 'ui_0127'), 'crew'),
            (ui('ui_0132'), 'max_weight'),
            (ui('ui_0133'), 'max_capacity'),
            (ui('ui_0136'), 'cannon_type'), (ui('ui_0137'), 'figurehead'),
        ]
        paired_fields = [
            (ui('ui_0131'), 'max_power', 'current_power'),
            (ui('ui_0134'), 'max_durability', 'current_durability'),
            (ui('ui_0135'), 'max_cannons', 'current_cannons'),
        ]
        def create_fleet_widget(parent, key, width=18):
            value = tk.StringVar(value='')
            self.fleet_edit_vars[key] = value
            if key == 'ship_type':
                widget = ttk.Combobox(parent, textvariable=value, state='readonly', width=width,
                                      values=self._fleet_ship_type_options(), font=('Malgun Gothic', 9))
                self.fleet_ship_type_combo = widget
                widget.bind('<<ComboboxSelected>>', lambda _event: self._update_fleet_mast_controls())
            elif key == 'cannon_type':
                widget = ttk.Combobox(parent, textvariable=value, state='readonly', width=width,
                                      values=self._fleet_cannon_type_options(), font=('Malgun Gothic', 9))
            elif key == 'figurehead':
                widget = ttk.Combobox(parent, textvariable=value, state='readonly', width=width,
                                      values=self._fleet_figurehead_options(), font=('Malgun Gothic', 9))
            else:
                if key == 'name':
                    widget = tk.Entry(parent, textvariable=value, width=width, font=('Malgun Gothic', 9))
                else:
                    upper_bound = {'max_power': 255, 'max_durability': 0x7FFFFFFF}.get(key, 0xFFFFFFFF)
                    widget = ttk.Spinbox(parent, textvariable=value, from_=0, to=upper_bound,
                                         width=width, font=('Malgun Gothic', 9), justify='right')
                    widget.configure(validate='key',
                                     validatecommand=(self.root.register(self._validate_fleet_number_input), '%P'))
                    widget.configure(command=lambda field=key: self._limit_fleet_spin_value(field))
                    widget.bind('<KeyRelease>', lambda _event, control=widget, maximum=upper_bound:
                                self._clamp_spinbox(control, 0, maximum), add='+')
                if key == 'crew':
                    self.fleet_crew_entry = widget
                    widget.bind('<KeyRelease>', lambda _event: self._limit_fleet_crew_input())
                elif key in ('current_power', 'current_durability', 'current_cannons'):
                    widget.bind('<KeyRelease>', lambda _event, current=key: self._limit_fleet_current_value(current))
                elif key in ('max_power', 'max_durability', 'max_cannons'):
                    current = {'max_power': 'current_power', 'max_durability': 'current_durability',
                               'max_cannons': 'current_cannons'}[key]
                    if key == 'max_power':
                        widget.bind('<KeyRelease>', lambda _event, current=current: (
                            self._limit_fleet_max_value('max_power', 255),
                            self._limit_fleet_current_value(current)))
                    elif key == 'max_durability':
                        widget.bind('<KeyRelease>', lambda _event, current=current: (
                            self._limit_fleet_max_value('max_durability', 0x7FFFFFFF),
                            self._limit_fleet_current_value(current)))
                    else:
                        widget.bind('<KeyRelease>', lambda _event, current=current: self._limit_fleet_current_value(current))
            widget.bind('<FocusOut>', lambda _event: self._apply_fleet_live(), add='+')
            widget.bind('<KeyRelease>', lambda _event: self._schedule_fleet_live_apply(), add='+')
            if isinstance(widget, ttk.Combobox):
                widget.bind('<<ComboboxSelected>>', lambda _event: self._apply_fleet_live(), add='+')
            return widget

        # 함선 종류는 이름보다 위에 두고, 같은 줄 오른쪽에 기함을 배치한다.
        fleet_type_row = tk.Frame(editor)
        fleet_type_row.grid(row=1, column=0, columnspan=2, sticky='ew', pady=3)
        tk.Label(fleet_type_row, text=ui('ui_0126') + ':', font=('Malgun Gothic', 9)).pack(
            side=tk.LEFT, padx=(0, 7))
        create_fleet_widget(fleet_type_row, 'ship_type').pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.fleet_flagship_var = tk.BooleanVar(value=False)
        flagship_box = tk.Frame(fleet_type_row)
        flagship_box.pack(side=tk.RIGHT, padx=(8, 0))
        tk.Checkbutton(flagship_box, text=ui('ui_0219').rstrip(':'), variable=self.fleet_flagship_var,
                       font=('Malgun Gothic', 9), takefocus=0).pack(side=tk.LEFT)

        form_rows = (
            ('single', *single_fields[0]), ('single', *single_fields[1]), ('single', *single_fields[2]),
            ('single', *single_fields[3]),
            ('pair', *paired_fields[0]),
            ('pair', *paired_fields[1]), ('pair', *paired_fields[2]),
            ('single', *single_fields[4]), ('single', *single_fields[5]),
        )
        row = 2
        for row_type, label, *keys in form_rows:
            tk.Label(editor, text=label + ':', anchor='e', font=('Malgun Gothic', 9)).grid(
                row=row, column=0, sticky='e', padx=(0, 7), pady=3)
            if row_type == 'single':
                widget = create_fleet_widget(editor, keys[0])
                widget.grid(row=row, column=1, sticky='ew', pady=3)
            else:
                pair = tk.Frame(editor)
                pair.grid(row=row, column=1, sticky='ew', pady=3)
                pair.columnconfigure(1, minsize=62)
                pair.columnconfigure(3, minsize=62)
                tk.Label(pair, text=ui('ui_0129'), font=('Malgun Gothic', 9)).grid(
                    row=0, column=0, sticky='w', padx=(0, 3))
                max_box = tk.Frame(pair, width=62, height=23)
                max_box.grid(row=0, column=1, sticky='nsew')
                max_box.grid_propagate(False)
                max_box.columnconfigure(0, weight=1)
                max_box.rowconfigure(0, weight=1)
                create_fleet_widget(max_box, keys[0], width=6).grid(sticky='nsew')
                tk.Label(pair, text=ui('ui_0130'), font=('Malgun Gothic', 9)).grid(
                    row=0, column=2, sticky='w', padx=(8, 3))
                current_box = tk.Frame(pair, width=62, height=23)
                current_box.grid(row=0, column=3, sticky='nsew')
                current_box.grid_propagate(False)
                current_box.columnconfigure(0, weight=1)
                current_box.rowconfigure(0, weight=1)
                create_fleet_widget(current_box, keys[1], width=6).grid(sticky='nsew')
            row += 1
        mast_row = row
        mast_controls = (
            (ui('ui_0329'), 'mast_main', self._fleet_main_mast_options()),
            (ui('ui_0330'), 'mast_sub', self._fleet_mast_options()),
            (ui('ui_0331'), 'mast_stern', self._fleet_mast_options()),
        )
        tk.Label(editor, text=ui('ui_0332') + ':', anchor='e', font=('Malgun Gothic', 9)).grid(
            row=mast_row, column=0, sticky='e', padx=(0, 7), pady=3)
        mast_group = tk.Frame(editor)
        mast_group.grid(row=mast_row, column=1, sticky='ew', pady=3)
        self.fleet_mast_rows = {}
        for column, (label, key, options) in enumerate(mast_controls):
            mast_group.columnconfigure(column, weight=1)
            mast_slot = tk.Frame(mast_group)
            mast_slot.grid(row=0, column=column, sticky='ew', padx=1)
            tk.Label(mast_slot, text=label, font=('Malgun Gothic', 9)).pack(anchor='center')
            value = tk.StringVar(value=options[0])
            self.fleet_edit_vars[key] = value
            combo = ttk.Combobox(mast_slot, textvariable=value, values=options, state='readonly',
                                 width=5, justify='center', font=('Malgun Gothic', 9))
            combo.pack(fill=tk.X)
            combo.bind('<<ComboboxSelected>>', lambda _event: self._apply_fleet_live())
            self.fleet_mast_rows[key] = (mast_slot, combo)
        right = tk.LabelFrame(parent, text=GROUP_TITLES['fleet_basic'], font=('Malgun Gothic', 9, 'bold'), padx=12, pady=10)
        right.grid(row=0, column=2, sticky='nsew', padx=(5, 10), pady=10)
        fields = [
            (ui('ui_0126'), 'ship_type'),
            (ui('ui_0323'), 'shipyard_requirement'),
            (ui('ui_0142'), 'base_min_crew'),
            (fleet_label('ui_0128', 'ui_0131'), 'base_power'), (fleet_label('ui_0129', 'ui_0131'), 'power_limit'),
            (fleet_label('ui_0128', 'ui_0134'), 'base_durability'), (fleet_label('ui_0129', 'ui_0134'), 'durability_limit'),
            (fleet_label('ui_0128', 'ui_0132'), 'base_weight'), (fleet_label('ui_0129', 'ui_0132'), 'weight_limit'),
            (fleet_label('ui_0128', 'ui_0133'), 'base_capacity'), (fleet_label('ui_0129', 'ui_0133'), 'capacity_limit'),
            (fleet_label('ui_0128', 'ui_0135'), 'base_cannons'), (fleet_label('ui_0129', 'ui_0135'), 'cannon_limit'),
            (ui('ui_0325'), 'unknown_38'),
            (fleet_label('ui_0128', 'ui_0149'), 'base_masts'),
            (fleet_label('ui_0129', 'ui_0149'), 'max_masts'),
        ]
        self.fleet_detail_fields = fields
        self.lst_fleet_basic = ttk.Treeview(right, columns=('field', 'base_value'), show='headings',
                                             height=len(fields), selectmode='none')
        self.lst_fleet_basic.heading('field', text=TREE_COLUMN_TITLES['fleet_basic']['field'])
        self.lst_fleet_basic.heading('base_value', text=TREE_COLUMN_TITLES['fleet_basic']['base_value'])
        self.lst_fleet_basic.column('field', width=128, anchor='w', stretch=False)
        self.lst_fleet_basic.column('base_value', width=155, anchor='e', stretch=True)
        self.lst_fleet_basic.pack(fill=tk.BOTH, expand=True)
        for row, (label, key) in enumerate(fields):
            self.lst_fleet_basic.insert('', tk.END, iid=key, values=(label, UI_EMPTY_VALUE))
        self._fleet_basic_tooltip = None
        self.lst_fleet_basic.bind('<Motion>', self._on_fleet_basic_motion, add='+')
        self.lst_fleet_basic.bind('<Leave>', self._hide_fleet_basic_tooltip, add='+')
        self.lst_fleet_basic.bind('<ButtonPress>', self._hide_fleet_basic_tooltip, add='+')

    def _on_fleet_basic_motion(self, event):
        """계수 행에서 실제 조선소 계산식을 안내한다."""
        row = self.lst_fleet_basic.identify_row(event.y)
        is_field_column = self.lst_fleet_basic.identify_column(event.x) == '#1'
        if getattr(self, '_fleet_basic_tooltip_row', None) != row or not is_field_column:
            self._hide_fleet_basic_tooltip()
        if not is_field_column:
            return
        if row == 'base_capacity':
            tooltip_text = self._fleet_base_capacity_tooltip()
        else:
            tooltip_text = None
        tooltip_texts = {
            'unknown_38': ui('ui_0486'),
            'shipyard_requirement': ui('ui_0487'),
        }
        tooltip_text = tooltip_text or tooltip_texts.get(row)
        if tooltip_text is None:
            self._hide_fleet_basic_tooltip()
            return
        if self._fleet_basic_tooltip is not None:
            return

        tooltip = tk.Toplevel(self.root)
        tooltip.wm_overrideredirect(True)
        tooltip.attributes('-topmost', True)
        tk.Label(
            tooltip,
            text=tooltip_text,
            justify='left', anchor='w', bg='#FFF8D6', fg='#333333',
            relief='solid', bd=1, padx=8, pady=6, font=('Malgun Gothic', 9),
        ).pack()
        tooltip.geometry(f'+{event.x_root + 16}+{event.y_root + 18}')
        self._fleet_basic_tooltip = tooltip
        self._fleet_basic_tooltip_row = row

    def _fleet_base_capacity_tooltip(self):
        """함선 테이블 기준값과 선택한 함선의 저장된 용량 보정을 함께 표시한다."""
        record = self._fleet_ship_raw_table_values(getattr(self, '_fleet_basic_ship_code', None))
        if record is None:
            return ui('ui_0428')
        table_capacity, table_cannons = record[9], record[11]
        table_visible = self._fleet_visible_capacity(table_capacity, table_cannons)
        ship_index = getattr(self, '_fleet_basic_ship_index', None)
        if ship_index is None or not self.file_buffer:
            return ui('ui_0427', table_capacity, table_cannons, table_visible,
                      table_capacity, 0, table_cannons, table_visible)
        base = self._fleet_slot_offset(ship_index)
        if len(self.file_buffer) < base + 0x59:
            return ui('ui_0428')
        stored_capacity = struct.unpack_from('<I', self.file_buffer, base + 0x45)[0]
        current_cannons = struct.unpack_from('<I', self.file_buffer, base + 0x55)[0]
        adjustment = stored_capacity - table_capacity
        visible_capacity = self._fleet_visible_capacity(stored_capacity, current_cannons)
        return ui('ui_0427', table_capacity, table_cannons, table_visible,
                  table_capacity, adjustment, current_cannons, visible_capacity)

    def _hide_fleet_basic_tooltip(self, _event=None):
        tooltip = getattr(self, '_fleet_basic_tooltip', None)
        self._fleet_basic_tooltip = None
        self._fleet_basic_tooltip_row = None
        if tooltip is not None:
            try:
                tooltip.destroy()
            except tk.TclError:
                pass

    def _fleet_slot_offset(self, ship_index):
        """Return the ship-pool record address for a stored ship index."""
        return 0x499A + ship_index * 0x5D

    def _fleet_active_ship_indices(self):
        """Read the eight active-fleet references (FFFF marks an unused entry)."""
        if not self.file_buffer or len(self.file_buffer) < 0x48ED:
            return []
        indices = []
        for position in range(8):
            ship_index = struct.unpack_from('<H', self.file_buffer, 0x48DD + position * 2)[0]
            if ship_index == 0xFFFF:
                continue
            if 0 <= ship_index < 200 and self._fleet_slot_offset(ship_index) + 0x64 <= len(self.file_buffer):
                indices.append(ship_index)
        return indices

    def _fleet_flagship_position(self):
        """Return the zero-based active-fleet position selected as flagship."""
        if not self.file_buffer or len(self.file_buffer) < 0x48DD:
            return None
        position = struct.unpack_from('<I', self.file_buffer, 0x48D9)[0]
        return position if position < 8 else None

    @staticmethod
    @lru_cache(maxsize=16)
    def _fleet_ship_type_name(code):
        return FLEET_DATA['ship_types'].get(str(code), ui('ui_0004', code))

    @classmethod
    @lru_cache(maxsize=1)
    def _fleet_ship_type_options(cls):
        return tuple(cls._fleet_ship_type_name(code) for code in range(8))

    @classmethod
    def _fleet_ship_type_code(cls, value):
        for code in range(8):
            if value == cls._fleet_ship_type_name(code):
                return code
        raise ValueError(ui('ui_0075'))

    @staticmethod
    def _fleet_cannon_type_options():
        return tuple(CDS3SaveEditorApp._fleet_cannon_type_map().values())

    @staticmethod
    @lru_cache(maxsize=1)
    def _fleet_cannon_type_map():
        return {int(code): name for code, name in FLEET_DATA['cannon_types'].items()}

    @staticmethod
    def _fleet_figurehead_options():
        return tuple(CDS3SaveEditorApp._fleet_figurehead_map().values())

    @staticmethod
    @lru_cache(maxsize=1)
    def _fleet_figurehead_map():
        return {int(code): ITEM_NAME_BY_ID.get(name, ui('ui_0295', name)) if isinstance(name, int) else name
                for code, name in FLEET_DATA['figureheads'].items()}

    @staticmethod
    @lru_cache(maxsize=1)
    def _fleet_mast_options():
        return tuple(FLEET_DATA['mast_names'][str(code)] for code in range(3))

    @staticmethod
    @lru_cache(maxsize=1)
    def _fleet_main_mast_options():
        return tuple(FLEET_DATA['mast_names'][str(code)] for code in range(1, 3))

    @staticmethod
    @lru_cache(maxsize=1)
    def _fleet_mast_name_map():
        return {int(code): name for code, name in FLEET_DATA['mast_names'].items()}

    @staticmethod
    def _fleet_combo_code(value, mapping):
        """Convert a dropdown label back to its save-record code."""
        for code, label in mapping.items():
            if value == label:
                return code
        raise ValueError(ui('ui_0076'))

    @staticmethod
    def _fleet_ship_raw_table_values(code):
        """Return all sixteen dwords in the original EXE record (+0x00~+0x3C)."""
        record = FLEET_DATA.get('ship_raw_table', {}).get(str(code))
        return tuple(record) if record is not None else None

    @staticmethod
    def _fleet_default_mast_value(code):
        """Initial mast bits written by the EXE's ship-purchase initializer."""
        return FLEET_DATA['default_mast_values'].get(str(code), 0)

    @staticmethod
    def _fleet_default_min_crew(code):
        """Displayed minimum crew initialized by the EXE purchase routine."""
        return FLEET_DATA['default_min_crew'].get(str(code))

    @staticmethod
    def _fleet_max_mast_count(code):
        """The game hard-codes mast limits by ship type in the mast-add routine."""
        return str(FLEET_DATA['max_mast_counts'].get(str(code), 1))

    def _update_fleet_mast_controls(self):
        """Show only the mast slots supported by the selected ship type."""
        if not hasattr(self, 'fleet_mast_rows'):
            return
        try:
            ship_code = self._fleet_ship_type_code(self.fleet_edit_vars['ship_type'].get())
            count = int(self._fleet_max_mast_count(ship_code))
        except (KeyError, ValueError):
            ship_code = None
            count = 1
        base_count = self._fleet_mast_count(self._fleet_default_mast_value(ship_code)) if ship_code is not None else 1
        default_mast = self._fleet_default_mast_value(ship_code) if ship_code is not None else 0x01
        mast_names = self._fleet_mast_name_map()
        for number, key in enumerate(('mast_main', 'mast_sub', 'mast_stern'), start=1):
            slot, combo = self.fleet_mast_rows[key]
            required = number <= base_count
            options = self._fleet_main_mast_options() if required else self._fleet_mast_options()
            combo.configure(values=options)
            if self.fleet_edit_vars[key].get() not in options:
                default_state = (default_mast >> ((number - 1) * 2)) & 0x03
                self.fleet_edit_vars[key].set(
                    mast_names.get(default_state, mast_names[1]) if required else mast_names[0])
            if number <= count:
                slot.grid()
            else:
                # A type with fewer mast slots must not retain hidden mast bits.
                self.fleet_edit_vars[key].set(mast_names[0])
                slot.grid_remove()
        if ship_code is not None:
            selected = self.lst_fleet.selection() if hasattr(self, 'lst_fleet') else ()
            ship_index = None
            if selected and selected[0].isdigit():
                position = int(selected[0])
                if 0 <= position < len(getattr(self, 'fleet_active_indices', ())):
                    ship_index = self.fleet_active_indices[position]
            self._set_fleet_base_info(ship_code, ship_index)
            self._limit_fleet_crew_input()

    def _fleet_max_crew(self):
        """The game permits up to five times the type's initial minimum crew."""
        try:
            ship_code = self._fleet_ship_type_code(self.fleet_edit_vars['ship_type'].get())
        except (KeyError, ValueError):
            return None
        minimum = self._fleet_default_min_crew(ship_code)
        return minimum * 5 if minimum is not None else None

    @staticmethod
    def _validate_fleet_number_input(proposed):
        """선박 수치 입력에 0 이상의 10진 숫자만 허용한다."""
        return proposed == '' or proposed.isdecimal()

    def _limit_fleet_crew_input(self):
        """Keep the editable current-crew field within the selected type's limit."""
        if not hasattr(self, 'fleet_edit_vars'):
            return
        text = self.fleet_edit_vars['crew'].get().strip()
        try:
            crew = int(text, 10)
        except ValueError:
            return
        maximum = self._fleet_max_crew()
        if maximum is not None and crew > maximum:
            self.fleet_edit_vars['crew'].set(str(maximum))
            if hasattr(self, 'fleet_crew_entry'):
                self.fleet_crew_entry.icursor(tk.END)

    def _limit_fleet_current_value(self, current_key):
        """Keep a current ship stat no higher than its paired maximum stat."""
        maximum_key = {
            'current_power': 'max_power',
            'current_durability': 'max_durability',
            'current_cannons': 'max_cannons',
        }.get(current_key)
        if maximum_key is None:
            return
        try:
            current = int(self.fleet_edit_vars[current_key].get().strip(), 10)
            maximum = int(self.fleet_edit_vars[maximum_key].get().strip(), 10)
        except (KeyError, ValueError):
            return
        if current > maximum:
            self.fleet_edit_vars[current_key].set(str(maximum))

    def _limit_fleet_max_value(self, key, maximum):
        try:
            value = int(self.fleet_edit_vars[key].get().strip(), 10)
        except (KeyError, ValueError):
            return
        if value > maximum:
            self.fleet_edit_vars[key].set(str(maximum))

    def _limit_fleet_spin_value(self, key):
        """스핀 버튼 조작에도 함선 수치 간의 상한 관계를 적용한다."""
        if key == 'crew':
            self._limit_fleet_crew_input()
        elif key in ('current_power', 'current_durability', 'current_cannons'):
            self._limit_fleet_current_value(key)
        elif key == 'max_power':
            self._limit_fleet_max_value('max_power', 255)
            self._limit_fleet_current_value('current_power')
        elif key == 'max_durability':
            self._limit_fleet_current_value('current_durability')
        elif key == 'max_cannons':
            self._limit_fleet_current_value('current_cannons')
        # 스핀 버튼을 길게 누르면 명령이 연속 발생한다. 매 클릭마다 유휴 저장을
        # 쌓지 않고 키 입력과 같은 디바운스 경로로 묶는다.
        self._schedule_fleet_live_apply()

    def _apply_fleet_live(self):
        """유효한 선택 함선의 폼 값을 메모리 세이브에 즉시 반영한다."""
        pending_job = getattr(self, '_fleet_live_job', None)
        if pending_job is not None:
            try:
                self.root.after_cancel(pending_job)
            except tk.TclError:
                pass
        self._fleet_live_job = None
        selected = self.lst_fleet.selection() if hasattr(self, 'lst_fleet') else ()
        required = ('name', 'ship_type', 'crew', 'max_weight', 'max_capacity', 'max_power', 'current_power',
                    'max_durability', 'current_durability', 'max_cannons', 'current_cannons', 'cannon_type', 'figurehead')
        if (self.file_buffer and selected and selected[0].isdigit()
                and all(self.fleet_edit_vars.get(key, tk.StringVar()).get().strip() for key in required)):
            self.apply_fleet_edits(refresh_list=False)

    def _schedule_fleet_live_apply(self):
        if getattr(self, '_fleet_live_job', None) is not None:
            self.root.after_cancel(self._fleet_live_job)
        self._fleet_live_job = self.root.after(250, self._apply_fleet_live)

    @staticmethod
    def _fleet_mast_count(value):
        """Return the number of installed masts from the three 2-bit mast slots."""
        return mast_count(value)

    @staticmethod
    def _fleet_visible_capacity(stored_capacity, cannon_count):
        """Convert the save's internal capacity to the cargo value shown in-game."""
        return max(0, stored_capacity - cannon_count)

    def refresh_fleet_list(self):
        if not hasattr(self, 'lst_fleet'):
            return
        selected = self.lst_fleet.selection()
        selected_index = int(selected[0]) if selected and selected[0].isdigit() else 0
        slot_ids = tuple(str(index) for index in range(8))
        # 운용 함선 수와 상관없이 1~8번 슬롯 행은 유지한다.
        # 그래서 함선 제거 시 목록 자체가 사라지지 않고 이름만 빈칸으로 남는다.
        if tuple(self.lst_fleet.get_children()) != slot_ids:
            self.lst_fleet.delete(*self.lst_fleet.get_children())
            for index in range(8):
                self.lst_fleet.insert('', tk.END, iid=str(index), values=(index, ''))
        self.fleet_active_indices = self._fleet_active_ship_indices()
        for position in range(8):
            name = ''
            if self.file_buffer and position < len(self.fleet_active_indices):
                ship_index = self.fleet_active_indices[position]
                base = self._fleet_slot_offset(ship_index)
                raw_name = bytes(self.file_buffer[base + 0x08:base + 0x2D]).split(b'\x00')[0]
                name = raw_name.decode('cp949', errors='ignore').strip()
                if not name:
                    name = ui('ui_0268')
            self.lst_fleet.item(str(position), values=(position, name))
        if self.fleet_active_indices:
            selected_index = min(selected_index, len(self.fleet_active_indices) - 1)
            self.lst_fleet.selection_set(str(selected_index))
            self.lst_fleet.focus(str(selected_index))
            self.lst_fleet.see(str(selected_index))
            self._set_fleet_detail(self.fleet_active_indices[selected_index], selected_index)
        else:
            self.lst_fleet.selection_remove(*self.lst_fleet.selection())
            self._set_fleet_detail(None)
        self._update_fleet_reset_state()
        self._schedule_treeview_autofit(self.lst_fleet, self.lst_fleet_basic)

    def on_fleet_select(self, _event=None):
        self._update_fleet_reset_state()
        selected = self.lst_fleet.selection()
        if not selected or not selected[0].isdigit() or not getattr(self, 'fleet_active_indices', []):
            self._set_fleet_detail(None)
            return
        fleet_position = int(selected[0])
        if not 0 <= fleet_position < len(self.fleet_active_indices):
            self._set_fleet_detail(None)
            return
        self._set_fleet_detail(self.fleet_active_indices[fleet_position], fleet_position)

    def _set_fleet_detail(self, ship_index, fleet_no=None):
        if not hasattr(self, 'lst_fleet_basic'):
            return
        if ship_index is None or not self.file_buffer:
            for _label, key in self.fleet_detail_fields:
                self.lst_fleet_basic.set(key, 'base_value', ui('ui_0244'))
            if hasattr(self, 'fleet_flagship_var'):
                self.fleet_flagship_var.set(False)
            self._populate_fleet_editor(None)
            self._update_fleet_preview(None, None)
            return
        base = self._fleet_slot_offset(ship_index)
        if len(self.file_buffer) <= base + 0x64:
            return self._set_fleet_detail(None)
        read_u32 = lambda offset: struct.unpack_from('<I', self.file_buffer, offset)[0]
        ship_code = read_u32(base + 0x2D)
        self._set_fleet_base_info(ship_code, ship_index)
        if hasattr(self, 'fleet_flagship_var'):
            # 0x48D9 stores the zero-based position in the active-fleet slot table
            # (0x48DD).  fleet_no is that same table position.
            self.fleet_flagship_var.set(self._fleet_flagship_position() == fleet_no)
        figurehead = struct.unpack_from('<H', self.file_buffer, base + 0x5B)[0]
        self._update_fleet_preview(ship_code, figurehead)
        self._populate_fleet_editor(ship_index)

    def _update_fleet_preview(self, ship_code, figurehead_code):
        """Update the video and figurehead picture beneath the ship list."""
        if not hasattr(self, 'fleet_video_preview'):
            return
        if getattr(self, '_suspend_fleet_preview', False):
            # 파일 교체 중에는 libVLC에 stop/set_media/pause를 호출하지 않는다.
            # 재생 스레드의 ctypes 콜백과 충돌해 UI가 멈출 수 있기 때문이다.
            self.fleet_video_preview.suspend_render_for_load()
        elif ship_code is None or not 0 <= ship_code <= 7:
            self.fleet_video_preview.show_blank()
            if not self.fleet_video_column.winfo_manager():
                self.fleet_video_column.pack(side=tk.LEFT, padx=(8, 0))
        else:
            video_path = get_ship_video_path(ship_code)
            if video_path:
                self.fleet_video_preview.show(video_path, blank_when_unavailable=True)
                if not self.fleet_video_column.winfo_manager():
                    self.fleet_video_column.pack(side=tk.LEFT, padx=(8, 0))
            else:
                self.fleet_video_preview.show_blank()
                if not self.fleet_video_column.winfo_manager():
                    self.fleet_video_column.pack(side=tk.LEFT, padx=(8, 0))
        if not hasattr(self, 'lbl_fleet_figurehead_img'):
            return
        if figurehead_code is None or not 0 <= figurehead_code <= 0x23:
            self.fleet_figurehead_box.config(bg='#000000')
            self.lbl_fleet_figurehead_img.config(image='', text='', bg='#000000')
            self.fleet_figurehead_photo = None
            if not self.fleet_figurehead_column.winfo_manager():
                self.fleet_figurehead_column.pack(side=tk.RIGHT, padx=(0, 8))
            return
        image_path = get_item_image_path(213 + figurehead_code)
        photo = get_cached_photo(image_path) if image_path else None
        if photo:
            self.fleet_figurehead_photo = photo
            self.lbl_fleet_figurehead_img.config(image=photo, text='')
            if not self.fleet_figurehead_column.winfo_manager():
                self.fleet_figurehead_column.pack(side=tk.RIGHT, padx=(0, 8))
        else:
            self.fleet_figurehead_photo = None
            self.fleet_figurehead_box.config(bg='#000000')
            self.lbl_fleet_figurehead_img.config(image='', text='', bg='#000000')
            if not self.fleet_figurehead_column.winfo_manager():
                self.fleet_figurehead_column.pack(side=tk.RIGHT, padx=(0, 8))

    def _resume_fleet_preview_after_load(self):
        """세이브·목록 갱신이 끝난 뒤 선택 함선의 영상을 안전하게 다시 시작한다."""
        self._fleet_preview_resume_job = None
        self._suspend_fleet_preview = False
        selected = self.lst_fleet.selection() if hasattr(self, 'lst_fleet') else ()
        if not selected or not selected[0].isdigit() or not getattr(self, 'fleet_active_indices', []):
            return
        position = int(selected[0])
        if 0 <= position < len(self.fleet_active_indices):
            self._set_fleet_detail(self.fleet_active_indices[position], position)

    def _set_fleet_base_info(self, ship_code, ship_index=None):
        """Show the EXE table entry for the type currently selected in the editor."""
        if not hasattr(self, 'lst_fleet_basic'):
            return
        self._fleet_basic_ship_code = ship_code
        self._fleet_basic_ship_index = ship_index
        record = self._fleet_ship_raw_table_values(ship_code)
        if record is None:
            shipyard_requirement = UI_EMPTY_VALUE
            base_min_crew = base_power = power_limit = base_durability = durability_limit = UI_EMPTY_VALUE
            base_weight = weight_limit = base_capacity = capacity_limit = UI_EMPTY_VALUE
            base_cannons = cannon_limit = base_masts = UI_EMPTY_VALUE
            unknown_38 = UI_EMPTY_VALUE
        else:
            shipyard_requirement = record[2]
            base_min_crew = record[13] + 10
            base_power, power_limit = record[3], record[4]
            base_durability, durability_limit = record[5], record[6]
            base_weight, weight_limit = f'{record[7]:,}', f'{record[8]:,}'
            # 세이브/EXE 테이블의 용량에는 대포 설치 공간이 포함된다.
            # 인게임 화면은 기본 대포 수만큼을 뺀 적재용량을 표시한다.
            base_capacity = self._fleet_visible_capacity(record[9], record[11])
            capacity_limit = record[10]
            base_cannons, cannon_limit = record[11], record[12]
            unknown_38 = record[14]
            base_masts = self._fleet_mast_count(record[15])
        values = {
            'ship_type': self._fleet_ship_type_name(ship_code),
            'shipyard_requirement': str(shipyard_requirement),
            'base_min_crew': str(base_min_crew),
            'base_power': str(base_power),
            'power_limit': str(power_limit),
            'base_durability': str(base_durability),
            'durability_limit': str(durability_limit),
            'base_weight': str(base_weight),
            'weight_limit': str(weight_limit),
            'base_capacity': str(base_capacity),
            'capacity_limit': str(capacity_limit),
            'base_cannons': str(base_cannons),
            'cannon_limit': str(cannon_limit),
            'unknown_38': str(unknown_38),
            'base_masts': str(base_masts),
            'max_masts': self._fleet_max_mast_count(ship_code),
        }
        for key, text in values.items():
            self.lst_fleet_basic.set(key, 'base_value', text)

    def _populate_fleet_editor(self, ship_index):
        """Copy the selected active ship's save-record values into the edit pane."""
        if not hasattr(self, 'fleet_edit_vars'):
            return
        if ship_index is None or not self.file_buffer:
            for value in self.fleet_edit_vars.values():
                value.set('')
            return
        base = self._fleet_slot_offset(ship_index)
        if len(self.file_buffer) <= base + 0x64:
            return self._populate_fleet_editor(None)
        read_u16 = lambda offset: struct.unpack_from('<H', self.file_buffer, offset)[0]
        read_u32 = lambda offset: struct.unpack_from('<I', self.file_buffer, offset)[0]
        raw_name = bytes(self.file_buffer[base + 0x08:base + 0x2D]).split(b'\x00')[0]
        values = {
            'name': raw_name.decode('cp949', errors='ignore').strip(),
            'ship_type': self._fleet_ship_type_name(read_u32(base + 0x2D)),
            'crew': str(read_u32(base + 0x35)),
            'current_power': str(read_u32(base + 0x39)),
            'max_power': str(read_u32(base + 0x3D)),
            'max_weight': str(read_u32(base + 0x41)),
            'max_capacity': str(self._fleet_visible_capacity(
                read_u32(base + 0x45), read_u32(base + 0x55))),
            'current_durability': str(read_u32(base + 0x49)),
            'max_durability': str(read_u32(base + 0x4D)),
            'current_cannons': str(read_u32(base + 0x51)),
            'max_cannons': str(read_u32(base + 0x55)),
            'cannon_type': self._fleet_dropdown_value(
                self._fleet_cannon_type_map(), read_u16(base + 0x59)),
            'figurehead': self._fleet_dropdown_value(
                self._fleet_figurehead_map(), read_u16(base + 0x5B)),
        }
        for key, text in values.items():
            self.fleet_edit_vars[key].set(text)
        mast_value = self.file_buffer[base + 0x63]
        for index, key in enumerate(('mast_main', 'mast_sub', 'mast_stern')):
            mast_code = (mast_value >> (index * 2)) & 0x03
            self.fleet_edit_vars[key].set(self._fleet_dropdown_value(
                self._fleet_mast_name_map(), mast_code))
        self._update_fleet_mast_controls()

    @staticmethod
    def _fleet_dropdown_value(mapping, code):
        """Keep unfamiliar save values selectable instead of silently changing them."""
        return mapping.get(code, ui('ui_0297', code))

    def reset_fleet_edits(self):
        """함대 목록·기함·모든 함선 레코드를 최초 파일 로드 상태로 복원한다."""
        original = getattr(self, 'fleet_original_buffer', None)
        if not self.file_buffer or not original:
            return
        # 0x48D9~0x48EC는 기함 위치와 8개 운용 함선 참조, 0x499A~0x9249는
        # 200개 함선 풀이다. 둘을 함께 되돌려 추가·삭제도 완전히 취소한다.
        for start, end in ((0x48D9, 0x48ED), (0x499A, 0x924A)):
            if end <= len(self.file_buffer) and end <= len(original):
                self.file_buffer[start:end] = original[start:end]
        self.refresh_fleet_list()
        self.lbl_status.config(text=ui('ui_0225'))

    def _update_fleet_reset_state(self):
        """함대 목록·기함·함선 풀에 변경점이 있을 때 되돌리기를 켠다."""
        button = getattr(self, 'btn_fleet_reset', None)
        if button is None:
            return
        changed = False
        original = getattr(self, 'fleet_original_buffer', None)
        if self.file_buffer and original:
            for start, end in ((0x48D9, 0x48ED), (0x499A, 0x924A)):
                if (end <= len(self.file_buffer) and end <= len(original)
                        and self.file_buffer[start:end] != original[start:end]):
                    changed = True
                    break
        if changed:
            if not button.winfo_manager():
                button.pack(side=tk.LEFT, padx=4, before=self.btn_fleet_remove)
        else:
            button.pack_forget()

    def remove_selected_fleet_ship(self):
        """Remove the selected ship from the active eight-ship fleet list.

        Pool records are not compacted, so all other fleet references remain valid.
        The released pool slot is marked unused for a future ship-add operation.
        """
        selected = self.lst_fleet.selection() if hasattr(self, 'lst_fleet') else ()
        if (not self.file_buffer or not selected or not selected[0].isdigit()
                or not getattr(self, 'fleet_active_indices', [])):
            messagebox.showwarning(ui('ui_0151'), ui('ui_0152'))
            return
        position = int(selected[0])
        if not 0 <= position < len(self.fleet_active_indices):
            return

        ship_index = self.fleet_active_indices[position]
        base = self._fleet_slot_offset(ship_index)
        raw_name = bytes(self.file_buffer[base + 0x08:base + 0x2D]).split(b'\x00')[0]
        name = raw_name.decode('cp949', errors='ignore').strip() or ui('ui_0268')
        if not messagebox.askyesno(ui('ui_0334'), ui('ui_0336', name), parent=self.root):
            return

        active_indices = list(self.fleet_active_indices)
        del active_indices[position]
        for slot, active_index in enumerate(active_indices):
            struct.pack_into('<H', self.file_buffer, 0x48DD + slot * 2, active_index)
        for slot in range(len(active_indices), 8):
            struct.pack_into('<H', self.file_buffer, 0x48DD + slot * 2, 0xFFFF)

        old_flagship = self._fleet_flagship_position()
        if not active_indices:
            struct.pack_into('<I', self.file_buffer, 0x48D9, 0xFFFFFFFF)
        elif old_flagship == position:
            # 기함을 지우면 다음 배(마지막이었다면 앞 배)가 그 자리를 이어받는다.
            struct.pack_into('<I', self.file_buffer, 0x48D9, min(position, len(active_indices) - 1))
        elif old_flagship is not None and old_flagship > position:
            struct.pack_into('<I', self.file_buffer, 0x48D9, old_flagship - 1)

        # 비활성화된 슬롯의 나머지 필드는 새 함선 생성 시 모두 초기화한다.
        struct.pack_into('<I', self.file_buffer, base + 0x2D, 0xFFFFFFFF)
        self.refresh_fleet_list()
        self.lbl_status.config(text=ui('ui_0337', name))

    def _ask_new_fleet_ship(self):
        """Ask for the two values that are not supplied by the EXE ship table."""
        dialog = tk.Toplevel(self.root)
        dialog.title(ui('ui_0338'))
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.withdraw()
        result = {'value': None}
        body = tk.Frame(dialog, padx=14, pady=12)
        body.pack(fill=tk.BOTH, expand=True)

        tk.Label(body, text=ui('ui_0126') + ':', font=('Malgun Gothic', 9)).grid(
            row=0, column=0, sticky='e', padx=(0, 7), pady=3)
        type_var = tk.StringVar(value=self._fleet_ship_type_name(0))
        type_combo = ttk.Combobox(body, textvariable=type_var, state='readonly', width=18,
                                  values=self._fleet_ship_type_options(), font=('Malgun Gothic', 9))
        type_combo.grid(row=0, column=1, sticky='ew', pady=3)
        tk.Label(body, text=ui('ui_0226'), font=('Malgun Gothic', 9)).grid(
            row=1, column=0, sticky='e', padx=(0, 7), pady=3)
        name_var = tk.StringVar(value=ui('ui_0339'))
        name_entry = tk.Entry(body, textvariable=name_var, width=21, font=('Malgun Gothic', 9))
        def validate_name(proposed):
            try:
                return len(proposed.encode('cp949')) <= 36
            except UnicodeEncodeError:
                return False
        name_entry.configure(validate='key',
                             validatecommand=(self.root.register(validate_name), '%P'))
        name_entry.grid(row=1, column=1, sticky='ew', pady=3)
        error_var = tk.StringVar(value='')
        tk.Label(body, textvariable=error_var, fg='#B3261E', font=('Malgun Gothic', 9)).grid(
            row=2, column=0, columnspan=2, pady=(2, 0))
        tk.Label(body, text=ui('ui_0345'), fg='#8B3A00', font=('Malgun Gothic', 9)).grid(
            row=3, column=0, columnspan=2, pady=(5, 0))
        buttons = tk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=2, pady=(9, 0))

        def confirm():
            name = name_var.get().strip()
            try:
                encoded = name.encode('cp949')
            except UnicodeEncodeError:
                error_var.set(ui('ui_0197'))
                return
            if not encoded or len(encoded) > 36:
                error_var.set(ui('ui_0153'))
                return
            result['value'] = (self._fleet_ship_type_code(type_var.get()), name)
            dialog.destroy()

        EditorButton(buttons, text=ui('ui_0175'), width=8, command=confirm).pack(side=tk.LEFT, padx=(0, 4))
        EditorButton(buttons, text=ui('ui_0102'), width=8, command=dialog.destroy).pack(side=tk.LEFT, padx=(4, 0))
        dialog.bind('<Return>', lambda _event: confirm())
        dialog.bind('<Escape>', lambda _event: dialog.destroy())
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f'+{max(0, x)}+{max(0, y)}')
        dialog.deiconify()
        dialog.grab_set()
        name_entry.focus_set()
        name_entry.selection_range(0, tk.END)
        self.root.wait_window(dialog)
        return result['value']

    def _find_free_fleet_pool_slot(self):
        """Return an unused ship-pool index (type FFFFFFFF), if one exists."""
        active = set(self._fleet_active_ship_indices())
        for ship_index in range(200):
            if ship_index in active:
                continue
            base = self._fleet_slot_offset(ship_index)
            if base + 0x64 <= len(self.file_buffer) and struct.unpack_from('<I', self.file_buffer, base + 0x2D)[0] == 0xFFFFFFFF:
                return ship_index
        return None

    def add_fleet_ship(self):
        """Create a table-default ship record and append it to the active fleet."""
        if not self.file_buffer:
            messagebox.showwarning(ui('ui_0151'), ui('ui_0117'))
            return
        active_indices = self._fleet_active_ship_indices()
        if len(active_indices) >= 8:
            messagebox.showwarning(ui('ui_0338'), ui('ui_0340'))
            return
        ship_index = self._find_free_fleet_pool_slot()
        if ship_index is None:
            messagebox.showwarning(ui('ui_0338'), ui('ui_0341'))
            return
        selection = self._ask_new_fleet_ship()
        if selection is None:
            return
        ship_code, name = selection
        record = self._fleet_ship_raw_table_values(ship_code)
        if record is None:
            messagebox.showerror(ui('ui_0338'), ui('ui_0075'))
            return

        base = self._fleet_slot_offset(ship_index)
        name_bytes = name.encode('cp949')
        # 구매 직후 저장된 실제 레코드와 같은 기본값: 승선원/대포는 0,
        # 용량에는 조선소에서 생성되는 개별 보정 +5가 반영되어 있다.
        self.file_buffer[base + 0x08:base + 0x2D] = b'\x00' * 0x25
        self.file_buffer[base + 0x08:base + 0x08 + len(name_bytes)] = name_bytes
        struct.pack_into('<I', self.file_buffer, base + 0x2D, ship_code)
        struct.pack_into('<I', self.file_buffer, base + 0x31, record[13])
        struct.pack_into('<I', self.file_buffer, base + 0x35, 0)
        struct.pack_into('<I', self.file_buffer, base + 0x39, record[3])
        struct.pack_into('<I', self.file_buffer, base + 0x3D, record[3])
        struct.pack_into('<I', self.file_buffer, base + 0x41, record[7])
        struct.pack_into('<I', self.file_buffer, base + 0x45, record[9] + 5)
        struct.pack_into('<I', self.file_buffer, base + 0x49, record[5])
        struct.pack_into('<I', self.file_buffer, base + 0x4D, record[5])
        struct.pack_into('<I', self.file_buffer, base + 0x51, 0)
        struct.pack_into('<I', self.file_buffer, base + 0x55, record[11])
        struct.pack_into('<H', self.file_buffer, base + 0x59, 0xFFFF)
        struct.pack_into('<H', self.file_buffer, base + 0x5B, 0xFFFF)
        self.file_buffer[base + 0x5D:base + 0x63] = b'\x00' * 6
        self.file_buffer[base + 0x63] = self._fleet_default_mast_value(ship_code)

        fleet_position = len(active_indices)
        struct.pack_into('<H', self.file_buffer, 0x48DD + fleet_position * 2, ship_index)
        if self._fleet_flagship_position() is None:
            struct.pack_into('<I', self.file_buffer, 0x48D9, fleet_position)
        self.refresh_fleet_list()
        self.lst_fleet.selection_set(str(fleet_position))
        self.lst_fleet.focus(str(fleet_position))
        self.lst_fleet.see(str(fleet_position))
        self._set_fleet_detail(ship_index, fleet_position)
        self.lbl_status.config(text=ui('ui_0342', name))

    def apply_fleet_edits(self, save_after=False, refresh_list=True):
        """Write the edit pane back to the selected active ship record in memory."""
        selected = self.lst_fleet.selection() if hasattr(self, 'lst_fleet') else ()
        if not self.file_buffer or not selected or not selected[0].isdigit():
            messagebox.showwarning(ui('ui_0151'), ui('ui_0152'))
            return
        position = int(selected[0])
        if position >= len(getattr(self, 'fleet_active_indices', [])):
            return
        ship_index = self.fleet_active_indices[position]
        base = self._fleet_slot_offset(ship_index)

        try:
            name_bytes = self.fleet_edit_vars['name'].get().strip().encode('cp949')
        except UnicodeEncodeError:
            messagebox.showerror(ui('ui_0151'), ui('ui_0197'))
            return
        if not name_bytes or len(name_bytes) > 36:
            messagebox.showerror(ui('ui_0151'), ui('ui_0153'))
            return

        def decimal(key, label, minimum=0, maximum=0xFFFFFFFF):
            try:
                value = int(self.fleet_edit_vars[key].get().strip(), 10)
            except ValueError:
                raise ValueError(ui('ui_0051', label))
            if not minimum <= value <= maximum:
                raise ValueError(ui('ui_0032', label, minimum, maximum))
            return value

        try:
            values = {
                'ship_type': self._fleet_ship_type_code(self.fleet_edit_vars['ship_type'].get()),
                'crew': decimal('crew', fleet_label('ui_0130', 'ui_0127'), 0, self._fleet_max_crew() or 0),
                'current_power': decimal('current_power', fleet_label('ui_0130', 'ui_0131')),
                'max_power': decimal('max_power', fleet_label('ui_0129', 'ui_0131'), 0, 255),
                'max_weight': decimal('max_weight', fleet_label('ui_0129', 'ui_0132')),
                'max_capacity': decimal('max_capacity', fleet_label('ui_0129', 'ui_0133')),
                'current_durability': decimal('current_durability', fleet_label('ui_0130', 'ui_0134')),
                'max_durability': decimal('max_durability', fleet_label('ui_0129', 'ui_0134'), 0, 0x7FFFFFFF),
                'current_cannons': decimal('current_cannons', fleet_label('ui_0130', 'ui_0135')),
                'max_cannons': decimal('max_cannons', fleet_label('ui_0129', 'ui_0135')),
                'cannon_type': self._fleet_combo_code(
                    self.fleet_edit_vars['cannon_type'].get(), self._fleet_cannon_type_map()),
                'figurehead': self._fleet_combo_code(
                    self.fleet_edit_vars['figurehead'].get(), self._fleet_figurehead_map()),
            }
            values['mast'] = pack_mast_slots(
                self._fleet_combo_code(self.fleet_edit_vars[key].get(), self._fleet_mast_name_map())
                for key in ('mast_main', 'mast_sub', 'mast_stern')
            )
            for current_key, maximum_key, label in (
                ('current_power', 'max_power', fleet_label('ui_0130', 'ui_0131')),
                ('current_durability', 'max_durability', fleet_label('ui_0130', 'ui_0134')),
                ('current_cannons', 'max_cannons', fleet_label('ui_0130', 'ui_0135')),
            ):
                if values[current_key] > values[maximum_key]:
                    raise ValueError(ui('ui_0052', label))
        except ValueError as exc:
            messagebox.showerror(ui('ui_0151'), str(exc))
            return

        old_mast = self.file_buffer[base + 0x63]
        new_mast_count = self._fleet_mast_count(values['mast'])
        base_mast_count = self._fleet_mast_count(self._fleet_default_mast_value(values['ship_type']))
        max_mast_count = int(self._fleet_max_mast_count(values['ship_type']))
        if new_mast_count < base_mast_count:
            messagebox.showerror(
                ui('ui_0154'),
                ui('ui_0015', self._fleet_ship_type_name(values['ship_type']), base_mast_count))
            return
        if new_mast_count > max_mast_count:
            messagebox.showerror(ui('ui_0154'), ui('ui_0016', max_mast_count))
            return
        mast_delta = new_mast_count - self._fleet_mast_count(old_mast)
        if mast_delta:
            adjusted_capacity = values['max_capacity'] - mast_delta * 25
            if adjusted_capacity < 0:
                messagebox.showerror(ui('ui_0154'), ui('ui_0198'))
                return
            values['max_capacity'] = adjusted_capacity
            current_min_crew = struct.unpack_from('<I', self.file_buffer, base + 0x31)[0]
            adjusted_min_crew = current_min_crew + mast_delta * 2
            if adjusted_min_crew < 0:
                messagebox.showerror(ui('ui_0154'), ui('ui_0199'))
                return
        else:
            adjusted_min_crew = None

        self.file_buffer[base + 0x08:base + 0x2D] = b'\x00' * 0x25
        self.file_buffer[base + 0x08:base + 0x08 + len(name_bytes)] = name_bytes
        struct.pack_into('<I', self.file_buffer, base + 0x2D, values['ship_type'])
        if adjusted_min_crew is not None:
            struct.pack_into('<I', self.file_buffer, base + 0x31, adjusted_min_crew)
        for key, offset in (
            ('crew', 0x35), ('current_power', 0x39), ('max_power', 0x3D),
            ('max_weight', 0x41),
            ('current_durability', 0x49), ('max_durability', 0x4D),
            ('current_cannons', 0x51), ('max_cannons', 0x55),
        ):
            struct.pack_into('<I', self.file_buffer, base + offset, values[key])
        # 편집창의 용량은 인게임 표시값이므로 저장할 때 대포 설치 공간을 더한다.
        struct.pack_into('<I', self.file_buffer, base + 0x45,
                         values['max_capacity'] + values['max_cannons'])
        struct.pack_into('<H', self.file_buffer, base + 0x59, values['cannon_type'])
        struct.pack_into('<H', self.file_buffer, base + 0x5B, values['figurehead'])
        self.file_buffer[base + 0x63] = values['mast']
        if getattr(self, 'fleet_flagship_var', None) is not None and self.fleet_flagship_var.get():
            struct.pack_into('<I', self.file_buffer, 0x48D9, position)
        if refresh_list:
            self.refresh_fleet_list()
        else:
            self.lst_fleet.item(str(position), values=(position, self.fleet_edit_vars['name'].get().strip()))
        self._update_fleet_reset_state()
        self.lbl_status.config(text=ui('ui_0017', self.fleet_edit_vars['name'].get().strip()))
        if save_after:
            if not self.file_path:
                messagebox.showerror(ui('ui_0154'), ui('ui_0200'))
                return
            self.save_to_path(self.file_path)
    # 도시 레코드는 0x5B5부터 0x4C 바이트 단위로 226개가 이어진다.
    # EXE의 0x429C10/0x429AF0 직렬화 순서와 일치하는 오프셋이다.
    CITY_SAVE_OFFSET = CITY_DATA['record_offset']
    CITY_RECORD_SIZE = CITY_DATA['record_size']
    CITY_RECORDS = CITY_DATA['records']
    # EXE 정적 도시 테이블(+0x18)의 조선소 판매 후보 마스크. 세이브의 현재 판매 목록과 다르다.
    CITY_SHIP_CANDIDATE_MASKS = tuple(
        int(mask)
        for mask, count in CITY_DATA.get('ship_candidate_mask_runs', ())
        for _ in range(int(count))
    ) or tuple(int(value) for value in CITY_DATA.get('ship_candidate_masks', ()))
    # EXE 도시 기본정보(0x4D14B0 + 도시 ID * 0x88)의 +0x10/+0x14에서 추출한 값이다.
    # 세이브에는 저장되지 않으므로 표시 전용으로 둔다.
    CITY_INLAND_CONNECTIONS = {
        int(city_id): tuple(city_ids)
        for city_id, city_ids in CITY_DATA.get('inland_city_connections', {}).items()
    }
    CITY_FACILITY_NAMES = {int(bit): UI_TEXTS.get(name, name) for bit, name in CITY_DATA['facility_names'].items()}
    CITY_STATUS_NAMES = {int(code): name for code, name in CITY_DATA['status_names'].items()}
    CITY_CULTURE_NAMES = {int(entry['id']): entry['name'] for entry in GAME_STRINGS['city_cultures']}
    TRADE_GOOD_NAMES = {int(entry['id']): entry['name'] for entry in TRADE_GOODS_DATA['records']}
    CITY_GOODS_SUPPLY_BY_SIZE = (20, 50, 100, 200, 350, 500, 700, 1000)
    CITY_FIELD_DEFINITIONS = (
        ('state', 'ui_0300', 0x00, 'i16', 'default_state'),
        ('flags', 'ui_0301', 0x02, 'u16', 'default_flags'),
        ('shipyard_level', 'ui_0302', 0x04, 'u8', 'shipyard_level'),
        ('update_counter', 'ui_0303', 0x05, 'u8', 'default_update_counter'),
        ('value_a', 'ui_0304', 0x06, 'i16', 'default_value_a'),
        ('value_b', 'ui_0305', 0x08, 'u32', 'default_value_b'),
        ('value_c', 'ui_0306', 0x0C, 'u32', 'default_value_c'),
        ('facility_flags', 'ui_0307', 0x10, 'u16', 'facility_flags'),
        ('ship_mask', 'ui_0308', 0x12, 'u16', 'default_ship_mask'),
        *tuple((f'good_{number}', 'ui_0309', 0x14 + number * 4, 'i32', 'default_goods', number)
               for number in range(8)),
        ('city_status', 'ui_0310', 0x34, 'i16', 'default_city_value'),
        *tuple((f'economy_{number}', 'ui_0311', 0x36 + number * 4, 'u32', 'default_economy_values', number)
               for number in range(5)),
        ('link_value', 'ui_0312', 0x4A, 'i16', 'default_link_value'),
    )
    CITY_HIDDEN_FIELD_KEYS = frozenset()
    # 도시 선택/자동 적용 때마다 만들지 않도록 레코드 메타데이터를 클래스 단위로
    # 재사용한다.
    CITY_FIELD_BY_KEY = {definition[0]: definition for definition in CITY_FIELD_DEFINITIONS}
    def build_cities_tab(self):
        """Build a save-city editor alongside the EXE-derived city defaults."""
        parent = self.tab_cities
        configure_equal_columns(parent, 3, 'city_columns')
        left = tk.LabelFrame(parent, text=GROUP_TITLES['city_list'], font=('Malgun Gothic', 9, 'bold'), padx=6, pady=6)
        left.grid(row=0, column=0, sticky='nsew', padx=(10, 5), pady=10)
        city_filter = tk.Frame(left)
        city_filter.pack(fill=tk.X, pady=(0, 5))
        tk.Label(city_filter, text=ui('ui_0251')).pack(side=tk.LEFT, padx=(0, 3))
        city_search_host = tk.Frame(city_filter, width=138, height=23)
        city_search_host.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.txt_city_search = NativeWinEdit(
            city_search_host,
            lambda: self._schedule_search_refresh('cities', self.refresh_cities_list),
            width=138, height=23,
        )
        self.btn_city_reset = EditorButton(
            city_filter, text=ui('ui_0222'), width=8,
            bg='#E8F0FE', fg='#1A73E8', command=self.reset_city_edits,
        )
        self.btn_city_reset.pack(side=tk.RIGHT, padx=(5, 0))
        self.btn_city_reset.pack_forget()
        city_tree_frame = tk.Frame(left)
        city_tree_frame.pack(fill=tk.BOTH, expand=True)
        columns = ('index', 'name')
        self.lst_cities = ttk.Treeview(city_tree_frame, columns=columns, show='headings', height=22, selectmode='browse')
        for column in columns:
            self.lst_cities.heading(column, text=TREE_COLUMN_TITLES['cities'][column])
        self.lst_cities.column('index', width=42, anchor='center', stretch=False)
        self.lst_cities.column('name', width=160, anchor='w', stretch=True)
        city_scroll = ttk.Scrollbar(city_tree_frame, orient=tk.VERTICAL, command=self.lst_cities.yview)
        self.lst_cities.configure(yscrollcommand=city_scroll.set)
        self.lst_cities.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        city_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.lst_cities.bind('<<TreeviewSelect>>', self.on_city_select)
        center = tk.LabelFrame(parent, text=GROUP_TITLES['city_save'], font=('Malgun Gothic', 9, 'bold'), padx=8, pady=8)
        center.grid(row=0, column=1, sticky='nsew', padx=5, pady=10)
        center.rowconfigure(0, weight=1)
        center.columnconfigure(0, weight=1)
        self.city_edit_vars = {}
        self.city_field_widgets = {}
        self.city_goods_combos = []
        # 상단 에디터 탭과 같은 버튼형 탭 스타일을 사용한다.
        city_tabs = ttk.Notebook(center, style='Editor.TNotebook')
        city_tabs.grid(row=0, column=0, sticky='nsew')
        # Notebook의 직접 자식 대신 부모의 자식 pane을 등록해 탭 전환 깜빡임을 줄인다.
        basic_tab = tk.Frame(center, padx=8, pady=8)
        market_tab = tk.Frame(center, padx=8, pady=8)
        trade_tab = tk.Frame(center, padx=8, pady=8)
        city_tabs.add(basic_tab, text=ui('ui_0128'))
        city_tabs.add(market_tab, text=ui('ui_0357'))
        city_tabs.add(trade_tab, text=ui('ui_0359'))
        city_tabs.bind('<<NotebookTabChanged>>', self._on_city_editor_tab_changed)
        self.city_tabs = city_tabs
        self.city_trade_tab = trade_tab

        # 도시 CG를 연결할 자리. 원본 CITYCG의 400:320 비율을 유지한다.
        self.city_image_box = tk.Frame(basic_tab, width=100, height=80)
        self.city_image_box.grid(row=0, column=0, columnspan=4, pady=(0, 6))
        self.city_image_box.grid_propagate(False)
        self.city_image_photo = get_black_photo(100, 80)
        self.lbl_city_image = tk.Label(self.city_image_box, image=self.city_image_photo, bg='#000000')
        self.lbl_city_image.place(x=0, y=0, width=100, height=80)

        self.city_name_var = tk.StringVar(value='')
        tk.Label(basic_tab, text=ui('ui_0344') + ':', font=('Malgun Gothic', 9)).grid(row=1, column=0, sticky='e', padx=(0, 6), pady=5)
        tk.Label(basic_tab, textvariable=self.city_name_var, anchor='w', font=('Malgun Gothic', 9)).grid(
            row=1, column=1, columnspan=2, sticky='ew', pady=5)
        self.city_flag_active_var = tk.BooleanVar(value=False)
        tk.Checkbutton(basic_tab, text=ui('ui_0314').rstrip(':'), variable=self.city_flag_active_var,
                       font=('Malgun Gothic', 9), command=self.apply_city_edits,
                       takefocus=0, highlightthickness=0).grid(
                           row=1, column=3, sticky='e', pady=5)

        tk.Label(basic_tab, text=ui('ui_0300') + ':', font=('Malgun Gothic', 9)).grid(row=2, column=0, sticky='e', padx=(0, 6), pady=5)
        self.cbo_city_nation = ttk.Combobox(basic_tab, values=NATION_NAMES, state='readonly', width=20, font=('Malgun Gothic', 9))
        self.cbo_city_nation.grid(row=2, column=1, columnspan=3, sticky='ew', pady=5)
        self.cbo_city_nation.bind('<<ComboboxSelected>>', lambda _event: self.apply_city_edits())
        basic_tab.columnconfigure(1, weight=1)
        basic_tab.columnconfigure(3, weight=1)

        culture_definition = self._city_definition('link_value')
        self.city_culture_var = tk.StringVar(value='')
        self.city_culture_options = [self.CITY_CULTURE_NAMES[code] for code in sorted(self.CITY_CULTURE_NAMES)]
        self.city_culture_codes_by_name = {name: code for code, name in self.CITY_CULTURE_NAMES.items()}
        tk.Label(basic_tab, text=self._city_field_label(culture_definition) + ':', font=('Malgun Gothic', 9)).grid(
            row=3, column=0, sticky='e', padx=(0, 6), pady=5)
        self.cbo_city_culture = ttk.Combobox(basic_tab, textvariable=self.city_culture_var,
                                             values=self.city_culture_options, state='readonly', width=14,
                                             font=('Malgun Gothic', 9))
        self.cbo_city_culture.grid(row=3, column=1, columnspan=3, sticky='ew', pady=5)
        self.cbo_city_culture.bind('<<ComboboxSelected>>', lambda _event: self.apply_city_edits())

        status_definition = self._city_definition('city_status')
        self.city_status_var = tk.StringVar(value='')
        self.city_status_options = [self._city_status_option(code) for code in sorted(self.CITY_STATUS_NAMES)]
        self.city_status_codes_by_option = {
            self._city_status_option(code): code for code in self.CITY_STATUS_NAMES
        }
        tk.Label(basic_tab, text=self._city_field_label(status_definition) + ':',
                 font=('Malgun Gothic', 9)).grid(row=4, column=0, sticky='e', padx=(0, 6), pady=4)
        self.cbo_city_status = ttk.Combobox(basic_tab, textvariable=self.city_status_var,
                                            values=self.city_status_options, state='readonly', width=14,
                                            font=('Malgun Gothic', 9))
        self.cbo_city_status.grid(row=4, column=1, columnspan=3, sticky='ew', pady=4)
        self.cbo_city_status.bind('<<ComboboxSelected>>', lambda _event: self.apply_city_edits())

        self._build_city_numeric_form_field(basic_tab, 5, 0, 'shipyard_level')

        facility_box = tk.LabelFrame(basic_tab, text=ui('ui_0343'), font=('Malgun Gothic', 9, 'bold'), padx=8, pady=6)
        facility_box.grid(row=6, column=0, columnspan=4, sticky='ew', pady=(10, 0))
        self.city_facility_vars = {}
        self.city_facility_checks = {}
        for position, (bit, name) in enumerate(sorted(self.CITY_FACILITY_NAMES.items())):
            variable = tk.BooleanVar(value=False)
            self.city_facility_vars[bit] = variable
            checkbox = tk.Checkbutton(facility_box, text=name, variable=variable, font=('Malgun Gothic', 9),
                                      command=self.apply_city_edits)
            checkbox.grid(row=position // 3, column=position % 3, sticky='w', padx=(0, 4), pady=1)
            self.city_facility_checks[bit] = checkbox

        market_goods_box = tk.LabelFrame(market_tab, text=ui('ui_0358'), font=('Malgun Gothic', 9, 'bold'), padx=8, pady=6)
        market_goods_box.grid(row=0, column=0, sticky='ew', pady=(0, 8))
        ship_box = tk.LabelFrame(market_tab, text=ui('ui_0308'), font=('Malgun Gothic', 9, 'bold'), padx=8, pady=6)
        ship_box.grid(row=1, column=0, sticky='ew')
        self.city_market_goods_box = market_goods_box
        self.city_ship_box = ship_box
        self.city_ship_vars = [tk.BooleanVar(value=False) for _ in range(8)]
        self.city_ship_checks = []
        for code, var in enumerate(self.city_ship_vars):
            checkbox = tk.Checkbutton(ship_box, text=self._fleet_ship_type_name(code), variable=var,
                                      font=('Malgun Gothic', 9),
                                      command=self.apply_city_edits)
            checkbox.grid(
                row=code // 2, column=code % 2, sticky='w', padx=(0, 12) if code % 2 == 0 else 0)
            self.city_ship_checks.append(checkbox)
        self.city_good_options = [(ui('ui_0319'), -1)] + [
            (item['name'], item['id']) for item in self.item_db]
        self.city_good_values = [text for text, _item_id in self.city_good_options]
        self.city_good_text_by_id = {item_id: text for text, item_id in self.city_good_options}
        self.city_good_id_by_text = {text: item_id for text, item_id in self.city_good_options}
        self.city_good_ids_by_casefold = {}
        for text, item_id in self.city_good_options:
            if item_id >= 0:
                self.city_good_ids_by_casefold.setdefault(text.casefold(), []).append(item_id)
        for number in range(8):
            tk.Label(market_goods_box, text=ui('ui_0309', number + 1), font=('Malgun Gothic', 9)).grid(
                row=number, column=0, sticky='e', padx=(0, 6), pady=3)
            combo = ttk.Combobox(market_goods_box, values=self.city_good_values,
                                 state='readonly', width=22, font=('Malgun Gothic', 9))
            combo.grid(row=number, column=1, sticky='ew', pady=3)
            combo.bind('<<ComboboxSelected>>', lambda _event: self.apply_city_edits())
            self.city_goods_combos.append(combo)

        self._build_city_numeric_form_field(trade_tab, 0, 0, 'update_counter')
        specialty_definition = self._city_definition('value_a')
        self.city_specialty_var = tk.StringVar(value='')
        self.city_specialty_id = -1
        self.lbl_city_specialty_image = tk.Label(trade_tab, anchor='center')
        self.lbl_city_specialty_image.grid(row=1, column=0, columnspan=4, sticky='n', pady=(4, 2))
        default_specialty_photo = get_black_photo(80, 80)
        self.lbl_city_specialty_image.configure(image=default_specialty_photo)
        self.lbl_city_specialty_image.image = default_specialty_photo
        tk.Label(trade_tab, text=self._city_field_label(specialty_definition) + ':',
                 font=('Malgun Gothic', 9)).grid(row=2, column=0, sticky='e', padx=(0, 6), pady=4)
        tk.Label(trade_tab, textvariable=self.city_specialty_var, anchor='w', width=14,
                 font=('Malgun Gothic', 9)).grid(row=2, column=1, sticky='ew', pady=4)
        for row, key in enumerate(('value_b', 'value_c'), start=3):
            self._build_city_numeric_form_field(trade_tab, row, 0, key)
        for number in range(5):
            self._build_city_supply_form_field(trade_tab, number + 5, f'economy_{number}')

        market_goods_box.columnconfigure(1, weight=1)
        for tab in (basic_tab, market_tab, trade_tab):
            tab.columnconfigure(1, weight=1)
            tab.columnconfigure(3, weight=1)

        right = tk.LabelFrame(parent, text=GROUP_TITLES['city_basic'], font=('Malgun Gothic', 9, 'bold'), padx=8, pady=8)
        right.grid(row=0, column=2, sticky='nsew', padx=(5, 10), pady=10)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        self.lst_city_basic = ttk.Treeview(right, columns=('field', 'base_value'), show='headings', height=22, selectmode='none')
        self.lst_city_basic.heading('field', text=TREE_COLUMN_TITLES['cities']['field'])
        self.lst_city_basic.heading('base_value', text=TREE_COLUMN_TITLES['cities']['base_value'])
        self.lst_city_basic.column('field', width=165, anchor='w', stretch=True)
        self.lst_city_basic.column('base_value', width=120, anchor='e', stretch=True)
        self.scr_city_basic = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.lst_city_basic.yview)
        self.lst_city_basic.configure(yscrollcommand=lambda first, last: self._update_city_basic_scrollbar(first, last))
        self.lst_city_basic.grid(row=0, column=0, sticky='nsew')
        self._fit_city_field_label_columns()

    def _fit_city_field_label_columns(self):
        """도시 기본 정보 목록의 '항목' 열을 실제 항목명 폭에 맞춘다."""
        try:
            font = tkfont.Font(font=('Malgun Gothic', 9))
            labels = [self._city_basic_field_label(definition) for definition in self.CITY_FIELD_DEFINITIONS
                      if definition[0] not in self.CITY_HIDDEN_FIELD_KEYS]
            header = TREE_COLUMN_TITLES['cities']['field']
            width = max(font.measure(text) for text in (header, *labels)) + 24
            for tree_name in ('lst_city_basic',):
                tree = getattr(self, tree_name, None)
                if tree is not None:
                    tree.column('field', width=width, stretch=False)
        except tk.TclError:
            pass

    def _update_city_basic_scrollbar(self, first, last):
        """Show the city-base-information scrollbar only when its list can scroll."""
        try:
            should_show = float(first) > 0.0 or float(last) < 1.0
        except (TypeError, ValueError):
            return
        self.scr_city_basic.set(first, last)
        is_visible = getattr(self.scr_city_basic, '_auto_visible', None)
        if is_visible is None:
            is_visible = bool(self.scr_city_basic.winfo_manager())
        if should_show and not is_visible:
            self.scr_city_basic.grid(row=0, column=1, sticky='ns')
            self.scr_city_basic._auto_visible = True
        elif not should_show and is_visible:
            self.scr_city_basic.grid_remove()
            self.scr_city_basic._auto_visible = False

    @classmethod
    def _city_record_offset(cls, city_index):
        return record_offset(cls.CITY_SAVE_OFFSET, cls.CITY_RECORD_SIZE, city_index)

    @staticmethod
    def _city_read(buffer, offset, kind):
        return read_value(buffer, offset, kind)

    @staticmethod
    def _city_write(buffer, offset, kind, value):
        write_value(buffer, offset, kind, value)

    @staticmethod
    def _city_field_label(definition):
        key, text_key, offset, _kind, *_ = definition
        if key.startswith('good_'):
            return ui(text_key, int(key.removeprefix('good_')) + 1, offset)
        if key.startswith('economy_'):
            return ui(text_key, int(key.removeprefix('economy_')) + 1, offset)
        return ui(text_key)

    @classmethod
    def _city_basic_field_label(cls, definition):
        """도시 기본정보 목록에서만 시장 품목임을 명확히 표기한다."""
        label = cls._city_field_label(definition)
        return f'{ui("ui_0358")} {label}' if definition[0].startswith('good_') else label

    @classmethod
    def _city_definition(cls, key):
        return cls.CITY_FIELD_BY_KEY.get(key)

    def _build_city_numeric_form_field(self, parent, row, column, key, width=12, fixed_width=None):
        definition = self._city_definition(key)
        if definition is None:
            return
        _key, _text_key, _offset, kind, *_ = definition
        minimum, maximum = {
            'u8': (0, 0xFF), 'u16': (0, 0xFFFF), 'u32': (0, 0xFFFFFFFF),
            'i16': (-0x8000, 0x7FFF), 'i32': (-0x80000000, 0x7FFFFFFF),
        }[kind]
        if key == 'shipyard_level':
            minimum, maximum = 0, 7
        variable = tk.StringVar(value='')
        validate = self.root.register(
            lambda proposed, low=minimum: (proposed == '' or
            (proposed == '-' and low < 0) or proposed.lstrip('-').isdigit()))
        label = tk.Label(parent, text=self._city_field_label(definition) + ':', font=('Malgun Gothic', 9))
        label.grid(row=row, column=column, sticky='e', padx=(0, 6), pady=4)
        entry = ttk.Spinbox(parent, textvariable=variable, from_=minimum, to=maximum, width=width,
                            justify='right', font=('Malgun Gothic', 9), validate='key',
                            validatecommand=(validate, '%P'))
        entry.configure(command=self.apply_city_edits)
        entry.bind('<KeyRelease>', lambda _event, control=entry, low=minimum, high=maximum:
                   self._clamp_spinbox(control, low, high), add='+')
        entry.bind('<KeyRelease>', lambda _event: self._schedule_city_live_apply(), add='+')
        if fixed_width is None:
            entry.grid(row=row, column=column + 1, sticky='ew', pady=4)
        else:
            entry_box = tk.Frame(parent, width=fixed_width, height=23)
            entry_box.grid(row=row, column=column + 1, sticky='w', pady=4)
            entry_box.grid_propagate(False)
            entry_box.columnconfigure(0, weight=1)
            entry_box.rowconfigure(0, weight=1)
            entry.grid(row=0, column=0, sticky='nsew')
        self.city_edit_vars[key] = variable
        self.city_field_widgets[key] = entry
        if key == 'value_b':
            # 특산품 가격은 기준가이므로, 현재 도시 시세를 반영한 실제 구매가를 함께 안내한다.
            self._city_specialty_price_tooltip = None
            for widget in (label, entry):
                widget.bind('<Motion>', self._on_city_specialty_price_motion, add='+')
                widget.bind('<Leave>', self._hide_city_specialty_price_tooltip, add='+')
                widget.bind('<ButtonPress>', self._hide_city_specialty_price_tooltip, add='+')

    def _on_city_specialty_price_motion(self, event):
        """특산품 기준가에서 교역소 실제 구매가까지의 계산을 표시한다."""
        if getattr(self, '_city_specialty_price_tooltip', None) is not None:
            return
        try:
            price = int(self.city_edit_vars['value_b'].get())
            market = int(self.city_edit_vars['update_counter'].get())
        except (KeyError, TypeError, ValueError):
            return
        market_price = price * market // 100
        buy_price = market_price * 3 // 2
        tooltip_text = ui('ui_0488', price, market, market_price, buy_price)
        tooltip = tk.Toplevel(self.root)
        tooltip.wm_overrideredirect(True)
        tooltip.attributes('-topmost', True)
        tk.Label(
            tooltip, text=tooltip_text, justify='left', anchor='w', bg='#FFF8D6', fg='#333333',
            relief='solid', bd=1, padx=8, pady=6, font=('Malgun Gothic', 9),
        ).pack()
        tooltip.geometry(f'+{event.x_root + 16}+{event.y_root + 18}')
        self._city_specialty_price_tooltip = tooltip

    def _hide_city_specialty_price_tooltip(self, _event=None):
        tooltip = getattr(self, '_city_specialty_price_tooltip', None)
        self._city_specialty_price_tooltip = None
        if tooltip is not None:
            try:
                tooltip.destroy()
            except tk.TclError:
                pass

    def _build_city_supply_form_field(self, parent, row, key):
        """교역품 공급량 5개를 항목명과 함께 세로 입력칸으로 배치한다."""
        definition = self._city_definition(key)
        if definition is None:
            return
        _key, _text_key, _offset, kind, *_ = definition
        minimum, maximum = {
            'u8': (0, 0xFF), 'u16': (0, 0xFFFF), 'u32': (0, 0xFFFFFFFF),
            'i16': (-0x8000, 0x7FFF), 'i32': (-0x80000000, 0x7FFFFFFF),
        }[kind]
        variable = tk.StringVar(value='')
        validate = self.root.register(
            lambda proposed, low=minimum: (proposed == '' or
            (proposed == '-' and low < 0) or proposed.lstrip('-').isdigit()))
        tk.Label(parent, text=self._city_field_label(definition) + ':', font=('Malgun Gothic', 9)).grid(
            row=row, column=0, sticky='e', padx=(0, 6), pady=4)
        entry = ttk.Spinbox(parent, textvariable=variable, from_=minimum, to=maximum, width=12,
                            justify='right', font=('Malgun Gothic', 9), validate='key',
                            validatecommand=(validate, '%P'))
        entry.grid(row=row, column=1, sticky='ew', pady=4)
        entry.configure(command=self.apply_city_edits)
        entry.bind('<KeyRelease>', lambda _event, control=entry, low=minimum, high=maximum:
                   self._clamp_spinbox(control, low, high), add='+')
        entry.bind('<KeyRelease>', lambda _event: self._schedule_city_live_apply(), add='+')
        self.city_edit_vars[key] = variable

    @staticmethod
    def _city_default_value(record, definition):
        key, _text_key, _offset, _kind, default_key, *optional_index = definition
        if key == 'value_c':
            # CDS_95.EXE 도시 기본 레코드(+0x38)는 공급량 표(20~1000)의
            # 색인이다. 도시 규모 기반의 공용 교역품 공급량이 아니다.
            supplies = CITY_DATA.get('default_specialty_supplies', ())
            city_index = int(record['index'])
            if 0 <= city_index < len(supplies):
                return int(supplies[city_index])
        value = record[default_key]
        return value[optional_index[0]] if optional_index else value

    @staticmethod
    def _city_ship_names(mask):
        names = [CDS3SaveEditorApp._fleet_ship_type_name(code) for code in range(8) if mask & (1 << code)]
        return ', '.join(names) if names else ui('ui_0319')

    @staticmethod
    def _city_current_year(buffer):
        """세이브 헤더의 현재 연도를 안전하게 읽는다."""
        if buffer and len(buffer) >= 23:
            year = struct.unpack_from('<H', buffer, 21)[0]
            if 1400 <= year <= 1700:
                return year
        return 1480

    def _city_refresh_ship_mask(self, record, base, year):
        """EXE 0x42A340의 도시별 판매 선박 추가 판정을 세이브에 적용한다."""
        facility_mask = self._city_read(self.file_buffer, base + 0x10, 'u16')
        if not facility_mask & (1 << 6):
            return False

        city_scale = self._city_read(self.file_buffer, base + 0x04, 'u8')
        threshold = year + city_scale * 5 - 1475
        # 날짜를 되돌릴 수 있는 에디터에서는 최초 로드 시점의 목록을 기준으로 다시 만든다.
        original_buffer = getattr(self, 'city_original_buffer', None)
        if original_buffer is not None and base + self.CITY_RECORD_SIZE <= len(original_buffer):
            base_mask = self._city_read(original_buffer, base + 0x12, 'u16')
            base_year = self._city_current_year(original_buffer)
        else:
            base_mask = record['default_ship_mask']
            base_year = year
        new_mask = base_mask
        # EXE 0x42A340: 도시 정적 기본 판매 마스크에 들어 있는 8종만 검사한 뒤,
        # 출시된 후보 중 번호가 가장 높은 한 종만 도시 판매 목록에 추가한다. 에디터에서는
        # 연도를 한 번에 건너뛸 수 있으므로 최초 로드 연도부터 매년의 결과를 누적한다.
        city_index = record['index']
        candidate_mask = (self.CITY_SHIP_CANDIDATE_MASKS[city_index]
                          if 0 <= city_index < len(self.CITY_SHIP_CANDIDATE_MASKS)
                          else record['default_ship_mask'])
        # 도시 규모를 바꾸면 같은 해에도 EXE의 도시별 갱신을 한 번 실행해야 한다.
        # 따라서 최초 로드 연도도 포함해 목표 연도까지 시뮬레이션한다.
        for simulated_year in range(base_year, year + 1):
            simulated_threshold = simulated_year + city_scale * 5 - 1475
            candidate = -1
            for ship_code in range(8):
                if not candidate_mask & (1 << ship_code):
                    continue
                ship_record = self._fleet_ship_raw_table_values(ship_code)
                if ship_record is not None and ship_record[2] < simulated_threshold:
                    candidate = ship_code
            if candidate >= 0:
                new_mask |= 1 << candidate

        old_mask = self._city_read(self.file_buffer, base + 0x12, 'u16')
        if new_mask == old_mask:
            return False
        self._city_write(self.file_buffer, base + 0x12, 'u16', new_mask)
        return True

    def refresh_all_city_shipyards(self, completion_message=None):
        """현재 날짜 기준으로 모든 도시 조선소의 판매 선박 후보를 한 번 갱신한다."""
        if not self.file_buffer:
            return
        try:
            year = int(self.spn_game_y.get())
        except (AttributeError, ValueError, tk.TclError):
            year = self._city_current_year(self.file_buffer)
        changed = 0
        selected_city = self._selected_city_index()
        selected_changed = False
        for record in self.CITY_RECORDS:
            base = self._city_record_offset(record['index'])
            if base + self.CITY_RECORD_SIZE > len(self.file_buffer):
                break
            record_changed = self._city_refresh_ship_mask(record, base, year)
            changed += int(record_changed)
            selected_changed |= record_changed and record['index'] == selected_city
        # 도시 목록은 번호와 이름만 표시하므로 판매 선박 갱신과 무관하다. 선택된
        # 도시의 상세 화면도 실제로 달라진 경우에만 다시 구성한다.
        if selected_changed:
            self.on_city_select()
        status_message = ui('ui_0380', changed)
        if completion_message:
            status_message = f'{status_message}\n{completion_message}'
        self.lbl_status.config(text=status_message)

    def _schedule_city_shipyard_refresh(self, _event=None, completion_message=None):
        """현재일 입력 중에는 잠시 기다렸다가 유효한 연도로 조선소 목록을 갱신한다."""
        pending_job = getattr(self, '_city_shipyard_refresh_job', None)
        if pending_job is not None:
            self.root.after_cancel(pending_job)
        self._city_shipyard_refresh_job = self.root.after(
            250, lambda: self._refresh_city_shipyards_for_current_date(completion_message)
        )

    def _refresh_city_shipyards_for_current_date(self, completion_message=None):
        self._city_shipyard_refresh_job = None
        try:
            int(self.spn_game_y.get())
            int(self.spn_game_m.get())
            int(self.spn_game_d.get())
        except (AttributeError, ValueError, tk.TclError):
            return
        self.refresh_all_city_shipyards(completion_message)

    @staticmethod
    def _city_nation_name(nation_code):
        """도시 레코드의 소속 국가 코드를 국가명으로 표시한다."""
        return NATION_NAMES[nation_code] if 0 <= nation_code < len(NATION_NAMES) else ui('ui_0296', nation_code)

    @classmethod
    def _city_culture_name(cls, culture_code):
        """EXE 도시 기본 테이블의 문화권 번호를 원본 문자열로 표시한다."""
        return cls.CITY_CULTURE_NAMES.get(culture_code, ui('ui_0296', culture_code))

    @classmethod
    def _city_status_option(cls, status_code):
        """도시 상태 콤보에 EXE 상태명만 표시한다."""
        return cls.CITY_STATUS_NAMES.get(status_code, ui('ui_0296', status_code))

    @classmethod
    def _city_status_name(cls, status_code):
        """EXE 도시 상태 번호를 상태명으로 표시한다."""
        return cls.CITY_STATUS_NAMES.get(status_code, ui('ui_0296', status_code))

    @classmethod
    def _trade_good_name(cls, good_id):
        """EXE 교역품 테이블의 종류 번호를 원본 이름으로 표시한다."""
        if good_id < 0:
            return ui('ui_0319')
        return cls.TRADE_GOOD_NAMES.get(good_id, ui('ui_0296', good_id))

    def _refresh_city_specialty_image(self):
        """선택된 특산품의 ITEM.CDS 추출 이미지를 교역 탭에 표시한다."""
        label = getattr(self, 'lbl_city_specialty_image', None)
        if label is None:
            return
        good_id = getattr(self, 'city_specialty_id', -1)
        image_path = get_trade_good_image_path(good_id)
        photo = get_cached_photo(image_path) if image_path else None
        display_photo = photo or get_black_photo(80, 80)
        label.configure(image=display_photo)
        label.image = display_photo

    def _update_city_image(self, city_index=None):
        """도시 선택에 맞춰 기본 탭의 CITYCG 미리보기를 갱신한다."""
        label = getattr(self, 'lbl_city_image', None)
        if label is None:
            return
        photo = get_city_preview_photo(city_index) if city_index is not None else None
        self.city_image_photo = photo or get_black_photo(100, 80)
        label.configure(image=self.city_image_photo)
        label.image = self.city_image_photo

    def refresh_cities_list(self):
        if not hasattr(self, 'lst_cities'):
            return
        selected = self._selected_city_index()
        search = self.txt_city_search.get().strip().casefold() if hasattr(self, 'txt_city_search') else ''
        # 도시 목록의 행은 정적 번호·이름뿐이다. 같은 검색어로 중복 호출되면
        # 기존 목록과 선택을 유지하고 재삽입하지 않는다.
        if (getattr(self, '_city_list_filter_cache', object()) == search
                and self.lst_cities.get_children()):
            if selected is not None and self.lst_cities.exists(str(selected)):
                self.lst_cities.selection_set(str(selected))
                self.lst_cities.focus(str(selected))
            return
        self.lst_cities.delete(*self.lst_cities.get_children())
        if not self.file_buffer:
            self._city_list_filter_cache = search
            self._schedule_treeview_autofit(self.lst_cities)
            return
        for record in self.CITY_RECORDS:
            index = record['index']
            offset = self._city_record_offset(index)
            if offset + self.CITY_RECORD_SIZE > len(self.file_buffer):
                break
            if search and search not in str(index) and search not in record['name'].casefold():
                continue
            self.lst_cities.insert('', tk.END, iid=str(index), values=(index, record['name']))
        if selected is not None and self.lst_cities.exists(str(selected)):
            self.lst_cities.selection_set(str(selected))
            self.lst_cities.focus(str(selected))
        self._city_list_filter_cache = search
        self._schedule_treeview_autofit(self.lst_cities)

    def _selected_city_index(self):
        selection = self.lst_cities.selection() if hasattr(self, 'lst_cities') else ()
        return int(selection[0]) if selection else None


    def _city_good_id_from_text(self, value):
        """목록의 정확한 항목 또는 유일한 이름 입력을 시장 품목 ID로 변환한다."""
        text = value.strip()
        if not text:
            return None
        if text in self.city_good_id_by_text:
            return self.city_good_id_by_text[text]
        matches = self.city_good_ids_by_casefold.get(text.casefold(), ())
        return matches[0] if len(matches) == 1 else None

    def _set_city_facility_ui_state(self, facility_flags):
        """현재 보유 시설에 맞춰 시장·조선소·교역소 편집 컨트롤을 잠근다."""
        has_market = bool(facility_flags & (1 << 7))
        has_shipyard = bool(facility_flags & (1 << 6))
        has_trade_post = bool(facility_flags & (1 << 1))

        for combo in getattr(self, 'city_goods_combos', ()):
            combo.configure(state='readonly' if has_market else tk.DISABLED)
        for checkbox in getattr(self, 'city_ship_checks', ()):
            checkbox.configure(state=tk.NORMAL if has_shipyard else tk.DISABLED)

        for key in ('update_counter', 'value_b', 'value_c',
                    'economy_0', 'economy_1', 'economy_2', 'economy_3', 'economy_4'):
            widget = getattr(self, 'city_field_widgets', {}).get(key)
            if widget is not None:
                widget.configure(state=tk.NORMAL if has_trade_post else tk.DISABLED)
        if hasattr(self, 'city_tabs') and hasattr(self, 'city_trade_tab'):
            self.city_tabs.tab(self.city_trade_tab, state='normal' if has_trade_post else 'disabled')

    def _sync_city_goods_supply_with_size(self):
        """도시 규모 변경에 맞춰 공통 교역품 공급량 다섯 칸을 게임의 일일 재고값으로 맞춘다."""
        try:
            city_size = int(self.city_edit_vars['shipyard_level'].get())
        except (KeyError, TypeError, ValueError):
            return
        city_size = max(0, min(city_size, len(self.CITY_GOODS_SUPPLY_BY_SIZE) - 1))
        supply = str(self.CITY_GOODS_SUPPLY_BY_SIZE[city_size])
        for number in range(5):
            variable = self.city_edit_vars.get(f'economy_{number}')
            if variable is not None:
                variable.set(supply)

    def on_city_select(self, _event=None):
        index = self._selected_city_index()
        if index is None or not self.file_buffer:
            self._update_city_image()
            self._update_city_reset_state()
            return
        record, base = self.CITY_RECORDS[index], self._city_record_offset(index)
        self._update_city_image(record['index'])
        if hasattr(self, 'city_name_var'):
            self.city_name_var.set(record['name'])
        self.lst_city_basic.delete(*self.lst_city_basic.get_children())
        for definition in self.CITY_FIELD_DEFINITIONS:
            key, _text_key, relative_offset, kind, *_ = definition
            if key in self.CITY_HIDDEN_FIELD_KEYS:
                continue
            saved_value = self._city_read(self.file_buffer, base + relative_offset, kind)
            default_value = self._city_default_value(record, definition)
            if key == 'state':
                self.cbo_city_nation.current(saved_value if 0 <= saved_value < len(NATION_NAMES) else -1)
            elif key == 'flags':
                self.city_flag_active_var.set(bool(saved_value & 0x0001))
            elif key == 'ship_mask':
                pass
            elif key.startswith('good_'):
                good_index = int(key.removeprefix('good_'))
                combo = self.city_goods_combos[good_index]
                combo.configure(values=self.city_good_values)
                combo.set(self.city_good_text_by_id.get(saved_value, ui('ui_0319')))
            elif key == 'link_value':
                self.city_culture_var.set(self._city_culture_name(saved_value))
            elif key == 'city_status':
                self.city_status_var.set(self._city_status_option(saved_value))
            elif key == 'value_a':
                # current(-1)은 일부 Tk 버전에서 TclError를 내며 뒤의 기본정보 갱신까지 끊는다.
                # 저장된 특산품 이름을 텍스트 변수에 직접 넣으면 없는 ID도 안전하게 표시된다.
                self.city_specialty_id = saved_value
                self.city_specialty_var.set(self._trade_good_name(saved_value))
            elif key in self.city_edit_vars:
                self.city_edit_vars[key].set(str(saved_value))
            if key == 'ship_mask':
                default_text = self._city_ship_names(default_value)
            elif key == 'state':
                default_text = self._city_nation_name(default_value)
            elif key == 'link_value':
                default_text = self._city_culture_name(default_value)
            elif key == 'city_status':
                default_text = self._city_status_name(default_value)
            elif key == 'value_a':
                default_text = self._trade_good_name(default_value)
            elif key.startswith('good_'):
                default_text = self.city_good_text_by_id.get(default_value, ui('ui_0319'))
            else:
                default_text = str(default_value)
            label = self._city_basic_field_label(definition)
            self.lst_city_basic.insert('', tk.END, iid=key, values=(label, default_text))
        # EXE 고정 도시 기본정보다. 세이브 필드 뒤에 표시 전용으로 붙인다.
        inland_city_ids = self.CITY_INLAND_CONNECTIONS.get(record['index'], (-1, -1))
        for slot, inland_city_id in enumerate(inland_city_ids):
            inland_name = (self.CITY_RECORDS[inland_city_id]['name']
                           if 0 <= inland_city_id < len(self.CITY_RECORDS) else ui('ui_0319'))
            self.lst_city_basic.insert(
                '', tk.END, iid=f'inland_city_{slot}',
                values=(ui('ui_0383' if slot == 0 else 'ui_0384'), inland_name))
        mask = self._city_read(self.file_buffer, base + 0x12, 'u16')
        for code, variable in enumerate(self.city_ship_vars):
            variable.set(bool(mask & (1 << code)))
        if hasattr(self, 'city_facility_vars'):
            default_facility_flags = record['facility_flags']
            facility_flags = self._city_read(self.file_buffer, base + 0x10, 'u16')
            for bit, variable in self.city_facility_vars.items():
                if hasattr(self, 'city_facility_checks'):
                    self.city_facility_checks[bit].configure(
                        state=tk.NORMAL if default_facility_flags & (1 << bit) else tk.DISABLED)
                variable.set(bool(facility_flags & (1 << bit)))
            self._set_city_facility_ui_state(facility_flags)
        self._refresh_city_specialty_image()
        self._update_city_reset_state()
        self._schedule_treeview_autofit(self.lst_city_basic)

    def apply_city_edits(self):
        city_index = self._selected_city_index()
        if city_index is None or not self.file_buffer:
            return False
        base = self._city_record_offset(city_index)
        nation_code = self.cbo_city_nation.current()
        if nation_code < 0:
            messagebox.showerror(ui('ui_0154'), ui('ui_0051', ui('ui_0300')))
            return False
        self._city_write(self.file_buffer, base, 'i16', nation_code)
        city_size_definition = self._city_definition('shipyard_level')
        old_city_size = self._city_read(
            self.file_buffer, base + city_size_definition[2], city_size_definition[3])
        try:
            new_city_size = int(self.city_edit_vars['shipyard_level'].get())
        except (KeyError, TypeError, ValueError):
            new_city_size = old_city_size
        if new_city_size != old_city_size:
            self._sync_city_goods_supply_with_size()
        for key, variable in self.city_edit_vars.items():
            definition = self._city_definition(key)
            _key, _text_key, relative_offset, kind, *_ = definition
            try:
                value = int(variable.get())
            except ValueError:
                messagebox.showerror(ui('ui_0154'), ui('ui_0051', self._city_field_label(definition)))
                return False
            self._city_write(self.file_buffer, base + relative_offset, kind, value)
        flags_definition = self._city_definition('flags')
        saved_flags = self._city_read(self.file_buffer, base + flags_definition[2], flags_definition[3])
        flags = saved_flags
        if self.city_flag_active_var.get():
            flags |= 0x0001
        else:
            flags &= ~0x0001
        self._city_write(self.file_buffer, base + flags_definition[2], flags_definition[3], flags)
        culture_code = self.city_culture_codes_by_name.get(self.city_culture_var.get())
        if culture_code is None:
            messagebox.showerror(ui('ui_0154'), ui('ui_0051', self._city_field_label(self._city_definition('link_value'))))
            return False
        culture_definition = self._city_definition('link_value')
        self._city_write(self.file_buffer, base + culture_definition[2], culture_definition[3], culture_code)
        status_code = self.city_status_codes_by_option.get(self.city_status_var.get())
        if status_code is None:
            messagebox.showerror(ui('ui_0154'), ui('ui_0051', self._city_field_label(self._city_definition('city_status'))))
            return False
        status_definition = self._city_definition('city_status')
        self._city_write(self.file_buffer, base + status_definition[2], status_definition[3], status_code)
        for number, combo in enumerate(self.city_goods_combos):
            item_id = self._city_good_id_from_text(combo.get())
            if item_id is None:
                messagebox.showerror(ui('ui_0154'), ui('ui_0051', ui('ui_0309', number + 1)))
                return False
            self._city_write(self.file_buffer, base + 0x14 + number * 4, 'i32', item_id)
        mask = sum((1 << code) for code, variable in enumerate(self.city_ship_vars) if variable.get())
        self._city_write(self.file_buffer, base + 0x12, 'u16', mask)
        facility_mask = sum((1 << bit) for bit, variable in self.city_facility_vars.items() if variable.get())
        self._city_write(self.file_buffer, base + 0x10, 'u16', facility_mask)
        if new_city_size != old_city_size:
            self._city_refresh_ship_mask(
                self.CITY_RECORDS[city_index], base, self._city_current_year(self.file_buffer))
        self.on_city_select()
        self.lbl_status.config(text=ui('ui_0315', self.CITY_RECORDS[city_index]['name']))
        return True

    def _schedule_city_live_apply(self):
        if getattr(self, '_city_live_job', None) is not None:
            self.root.after_cancel(self._city_live_job)
        self._city_live_job = self.root.after(250, self._apply_city_live)

    def _on_city_editor_tab_changed(self, _event=None):
        """Do not treat a Basic/Advanced tab change as completion of a city edit."""
        pending_job = getattr(self, '_city_live_job', None)
        if pending_job is not None:
            self.root.after_cancel(pending_job)
            self._city_live_job = None

    def _apply_city_live(self):
        self._city_live_job = None
        if (self._selected_city_index() is not None and self.cbo_city_nation.current() >= 0
                and all(variable.get().strip() not in ('', '-') for variable in self.city_edit_vars.values())
                and all(self._city_good_id_from_text(combo.get()) is not None for combo in self.city_goods_combos)):
            self.apply_city_edits()

    def reset_city_edits(self):
        """모든 도시 저장 레코드를 최초 파일 로드 상태로 복원한다."""
        if not self.file_buffer or not self.city_original_buffer:
            return
        pending_job = getattr(self, '_city_live_job', None)
        if pending_job is not None:
            self.root.after_cancel(pending_job)
            self._city_live_job = None
        shipyard_job = getattr(self, '_city_shipyard_refresh_job', None)
        if shipyard_job is not None:
            self.root.after_cancel(shipyard_job)
            self._city_shipyard_refresh_job = None
        start = self.CITY_SAVE_OFFSET
        end = start + len(self.CITY_RECORDS) * self.CITY_RECORD_SIZE
        if end > len(self.file_buffer) or end > len(self.city_original_buffer):
            return
        self.file_buffer[start:end] = self.city_original_buffer[start:end]
        self.on_city_select()
        self.lbl_status.config(text=ui('ui_0333'))

    def _update_city_reset_state(self):
        """도시 표 전체에 변경점이 있을 때만 되돌리기를 켠다."""
        button = getattr(self, 'btn_city_reset', None)
        changed = False
        if button is not None and self.file_buffer and self.city_original_buffer:
            start = self.CITY_SAVE_OFFSET
            end = start + len(self.CITY_RECORDS) * self.CITY_RECORD_SIZE
            changed = (end <= len(self.file_buffer) and end <= len(self.city_original_buffer)
                       and self.file_buffer[start:end] != self.city_original_buffer[start:end])
        if button is not None:
            if changed:
                if not button.winfo_manager():
                    button.pack(side=tk.RIGHT, padx=(5, 0))
            else:
                button.pack_forget()

    def build_profile_tab(self):
        # ***<module>.CDS3SaveEditorApp.build_profile_tab: Failure: Different bytecode
        parent = self.tab_profile
        # 윈도우 네이티브 이름 입력칸(기본 9pt)과 맞춰 상단 모든 행을 9pt로 통일한다.
        LBL_FONT = ('Malgun Gothic', 9)
        VAL_FONT = ('Malgun Gothic', 9)
        configure_equal_columns(parent, 2, 'profile_columns')
        profile_left = tk.LabelFrame(parent, text=ui('ui_0414'), font=('Malgun Gothic', 9, 'bold'), padx=4, pady=4)
        profile_left.grid(row=0, column=0, sticky='nsew', padx=(10, 5), pady=4)
        # 상단 신상 영역은 고정 높이, 하단 Notebook은 남은 높이를 사용한다.
        # pack의 최소 크기 경쟁으로 상단 버튼이 잘리는 현상을 막기 위해 grid로
        # 두 영역을 명확히 나눈다.
        profile_left.columnconfigure(0, weight=1)
        profile_left.rowconfigure(1, weight=1)
        profile_right = tk.LabelFrame(parent, text=ui('ui_0392'), font=('Malgun Gothic', 9, 'bold'), padx=4, pady=4)
        profile_right.grid(row=0, column=1, sticky='nsew', padx=(5, 10), pady=4)
        # 기존 역할별 페이지는 세이브 갱신 로직을 그대로 재사용하기 위한 비표시 컨테이너다.
        # 실제 화면은 아래의 단일 인물 브라우저만 사용한다.
        self.profile_companion_tabs = ttk.Notebook(profile_right, style='Editor.TNotebook')

        self.profile_details = ttk.Notebook(profile_left, style='Editor.TNotebook')
        self.profile_page_stats = ttk.Frame(profile_left)
        self.profile_page_money = ttk.Frame(profile_left)
        self.profile_page_reputation = ttk.Frame(profile_left)
        self.profile_page_tech = ttk.Frame(profile_left)
        self.profile_page_lang = ttk.Frame(profile_left)
        self.profile_details.add(self.profile_page_stats, text=ui('ui_0385'))
        self.profile_details.add(self.profile_page_money, text=ui('ui_0386'))
        self.profile_details.add(self.profile_page_reputation, text=ui('ui_0387'))
        self.profile_details.add(self.profile_page_tech, text=ui('ui_0388'))
        self.profile_details.add(self.profile_page_lang, text=ui('ui_0389'))
        self.profile_page_officer = ttk.Frame(profile_right)
        self.profile_page_navigator = ttk.Frame(profile_right)
        self.profile_page_surveyor = ttk.Frame(profile_right)
        self.profile_page_interpreter = ttk.Frame(profile_right)
        self.profile_page_spouse = ttk.Frame(profile_right)
        self.profile_companion_tabs.add(self.profile_page_spouse, text=ui('ui_0393'))
        self.profile_companion_tabs.add(self.profile_page_officer, text=ui('ui_0394'))
        self.profile_companion_tabs.add(self.profile_page_navigator, text=ui('ui_0395'))
        self.profile_companion_tabs.add(self.profile_page_surveyor, text=ui('ui_0396'))
        self.profile_companion_tabs.add(self.profile_page_interpreter, text=ui('ui_0397'))
        self.build_officer_profile()
        self._crew_profiles = {}
        self._crew_profiles['officer'] = {
            'offset': ROLE_SLOT_BY_KEY['officer'], 'name': ui('ui_0394'),
            'category': self.cbo_officer_category, 'query': self.cbo_officer_name,
            'tree': self.tree_officer_search,
        }
        self.build_crew_profile('navigator', self.profile_page_navigator, ROLE_SLOT_BY_KEY['navigator'], ui('ui_0395'))
        self.build_crew_profile('surveyor', self.profile_page_surveyor, ROLE_SLOT_BY_KEY['surveyor'], ui('ui_0396'))
        self.build_crew_profile('interpreter', self.profile_page_interpreter, ROLE_SLOT_BY_KEY['interpreter'], ui('ui_0397'))
        self._build_person_browser(profile_right)

        # 얼굴 변경·되돌리기 버튼을 모두 표시할 수 있도록 상단 영역을 확보한다.
        # 우측 인물 브라우저의 상단 선택 영역(164px)과 같은 크기·여백을 쓴다.
        grp_player = tk.Frame(profile_left, height=164)
        grp_player.grid(row=0, column=0, sticky='ew', pady=(3, 4))
        # 내부 항목은 grid로 배치하므로 grid 전파를 막아야 지정 높이가 유지된다.
        grp_player.grid_propagate(False)
        self.profile_details.grid(row=1, column=0, sticky='nsew', pady=(0, 4))
        f_p_face_box = tk.Frame(grp_player, width=84, height=100, bg='#222222', relief='ridge', bd=2)
        f_p_face_box.pack_propagate(False)
        f_p_face_box.place(x=0, y=4)
        self.lbl_player_face = tk.Label(f_p_face_box, bg='#222222')
        self.lbl_player_face.pack(fill=tk.BOTH, expand=True)
        self.btn_player_face_change = EditorButton(
            grp_player, text=ui('ui_0382'), font=('Malgun Gothic', 9),
            bg='#E6F4EA', fg='#137333', command=self.open_player_face_picker,
        )
        self.btn_player_face_change.place(x=0, y=108, width=84, height=25)
        self.btn_player_restore = EditorButton(
            grp_player, text=ui('ui_0222'), font=('Malgun Gothic', 9),
            bg='#E8F0FE', fg='#1A73E8', activebackground='#D2E3FC',
            activeforeground='#174EA6', command=self.restore_player_edits,
        )
        self.btn_player_restore.place(x=0, y=136, width=84, height=25)
        self.btn_player_restore.place_forget()
        # 별도 Frame을 두면 그 배경이 LabelFrame 테두리를 덮는다. 오른쪽 항목은
        # 그룹에 직접 grid 배치하고 첫 열만 얼굴 영역만큼 비워 둔다.
        f_p_right = grp_player
        grp_player.grid_columnconfigure(0, minsize=92)
        grp_player.grid_columnconfigure(6, weight=1)
        COL_LBL_W = 55
        name_line = tk.Frame(f_p_right)
        name_line.grid(row=0, column=1, columnspan=6, pady=(1, 1), sticky='w')
        tk.Label(name_line, text=ui('ui_0226'), font=LBL_FONT, anchor='w').pack(side=tk.LEFT, padx=(0, 4))
        f_name = tk.Frame(name_line)
        f_name.pack(side=tk.LEFT)
        tk.Label(f_name, text=ui('ui_0227'), font=VAL_FONT, fg='#666666').pack(side=tk.LEFT)
        last_name_host = tk.Frame(f_name, width=116, height=23)
        last_name_host.pack(side=tk.LEFT, padx=(3, 8))
        self.txt_last_name = NativeWinEdit(last_name_host, self._update_player_restore_state, width=116, height=23)
        tk.Label(f_name, text=ui('ui_0228'), font=VAL_FONT, fg='#666666').pack(side=tk.LEFT)
        first_name_host = tk.Frame(f_name, width=116, height=23)
        first_name_host.pack(side=tk.LEFT, padx=(3, 0))
        self.txt_first_name = NativeWinEdit(first_name_host, self._update_player_restore_state, width=116, height=23)
        nation_line = tk.Frame(f_p_right)
        nation_line.grid(row=1, column=1, columnspan=6, pady=(2, 1), sticky='w')
        tk.Label(nation_line, text=ui('ui_0231'), font=LBL_FONT, anchor='w').pack(side=tk.LEFT, padx=(0, 4))
        f_nat = tk.Frame(nation_line)
        f_nat.pack(side=tk.LEFT)
        self.cbo_nation = ttk.Combobox(f_nat, values=BASIC_NATIONS, state='readonly', width=26, font=VAL_FONT)
        self.cbo_nation.pack(side=tk.LEFT, padx=(0, 4))
        self.cbo_nation.bind('<<ComboboxSelected>>', lambda _event: self._update_player_restore_state(), add='+')
        self.chk_all_nations = tk.BooleanVar(value=False)
        self.chk_nat_widget = tk.Checkbutton(f_nat, text=ui('ui_0156'), variable=self.chk_all_nations, command=self.toggle_all_nations, font=VAL_FONT)
        self.chk_nat_widget.pack(side=tk.LEFT)
        # 날짜를 먼저 두고, 직업·혈액형·별자리는 그 아래 한 행에 나란히 둔다.
        date_line = tk.Frame(f_p_right)
        date_line.grid(row=2, column=1, columnspan=6, pady=(2, 1), sticky='w')
        tk.Label(date_line, text=ui('ui_0232'), font=LBL_FONT, anchor='e').pack(side=tk.LEFT, padx=(0, 4))
        f_birth = tk.Frame(date_line)
        f_birth.pack(side=tk.LEFT)
        self.spn_birth_y = ttk.Spinbox(f_birth, from_=1000, to=3000, width=5)
        self.spn_birth_m = ttk.Spinbox(f_birth, from_=1, to=12, width=3)
        self.spn_birth_d = ttk.Spinbox(f_birth, from_=1, to=31, width=3)
        self.set_spin_val(self.spn_birth_y, 1450)
        self.set_spin_val(self.spn_birth_m, 1)
        self.set_spin_val(self.spn_birth_d, 1)
        self.birth_date_picker = CalendarDatePicker(
            f_birth, self._get_birth_date, self._set_birth_date_from_calendar, font=VAL_FONT,
        )
        self.birth_date_picker.pack(side=tk.LEFT)
        for spinner in (self.spn_birth_y, self.spn_birth_m, self.spn_birth_d):
            spinner.bind('<KeyRelease>', self._on_birth_date_changed, add='+')
            spinner.bind('<Return>', self._on_birth_date_changed, add='+')
            spinner.bind('<FocusOut>', self._on_birth_date_changed, add='+')
            spinner.bind('<<Increment>>', self._on_birth_date_changed, add='+')
            spinner.bind('<<Decrement>>', self._on_birth_date_changed, add='+')
        tk.Label(date_line, text=ui('ui_0236'), font=LBL_FONT, anchor='e', fg='#1A73E8').pack(side=tk.LEFT, padx=(8, 2))
        f_game = tk.Frame(date_line)
        f_game.pack(side=tk.LEFT)
        self.spn_game_y = ttk.Spinbox(f_game, from_=1480, to=1559, width=5)
        self.spn_game_m = ttk.Spinbox(f_game, from_=1, to=12, width=3)
        self.spn_game_d = ttk.Spinbox(f_game, from_=1, to=31, width=3)
        self.set_spin_val(self.spn_game_y, 1480)
        self.set_spin_val(self.spn_game_m, 1)
        self.set_spin_val(self.spn_game_d, 1)
        for spinner in (self.spn_game_y, self.spn_game_m, self.spn_game_d):
            spinner.bind('<KeyRelease>', self._on_game_date_changed, add='+')
            spinner.bind('<Return>', self._on_game_date_changed, add='+')
            spinner.bind('<FocusOut>', self._on_game_date_changed, add='+')
            spinner.bind('<<Increment>>', self._on_game_date_changed, add='+')
            spinner.bind('<<Decrement>>', self._on_game_date_changed, add='+')
        self.game_date_picker = CalendarDatePicker(
            f_game, self._get_game_date, self._set_game_date_from_calendar,
            font=VAL_FONT, min_year=1480, max_year=1559,
        )
        self.game_date_picker.pack(side=tk.LEFT)
        info_line = tk.Frame(f_p_right)
        info_line.grid(row=3, column=1, columnspan=6, pady=(2, 1), sticky='w')
        tk.Label(info_line, text=ui('ui_0229'), font=LBL_FONT, anchor='e').pack(side=tk.LEFT, padx=(0, 4))
        self.cbo_job = ttk.Combobox(info_line, values=JOB_NAMES, state='readonly', width=9, font=VAL_FONT)
        self.cbo_job.pack(side=tk.LEFT)
        self.cbo_job.bind('<<ComboboxSelected>>', lambda _event: self._update_player_restore_state(), add='+')
        tk.Label(info_line, text=ui('ui_0230'), font=LBL_FONT, anchor='e').pack(side=tk.LEFT, padx=(8, 2))
        self.cbo_blood = ttk.Combobox(info_line, values=BLOOD_NAMES, state='readonly', width=4, font=VAL_FONT)
        self.cbo_blood.pack(side=tk.LEFT)
        self.cbo_blood.bind('<<ComboboxSelected>>', lambda e: self.update_wife_combo_options())
        self.cbo_blood.bind('<<ComboboxSelected>>', lambda _event: self._update_player_restore_state(), add='+')
        tk.Label(info_line, text=ui('ui_0399'), font=LBL_FONT, anchor='e').pack(side=tk.LEFT, padx=(8, 2))
        self.lbl_birth_zodiac = tk.Label(info_line, text='', font=('Malgun Gothic', 9), fg='#000000', anchor='w')
        self.lbl_birth_zodiac.pack(side=tk.LEFT)
        self.sponsor_contract_line = tk.Frame(f_p_right)
        self.sponsor_contract_line.grid(row=4, column=1, columnspan=6, pady=(3, 1), sticky='ew')
        tk.Label(self.sponsor_contract_line, text=ui('ui_0448'), font=LBL_FONT, anchor='w').pack(side=tk.LEFT, padx=(0, 4))
        self.lbl_sponsor_contract = tk.Label(self.sponsor_contract_line, text='', font=VAL_FONT, anchor='w')
        self.lbl_sponsor_contract.pack(side=tk.LEFT)
        self.sponsor_remaining_line = tk.Frame(f_p_right)
        self.sponsor_remaining_line.grid(row=5, column=1, columnspan=6, pady=(2, 0), sticky='ew')
        self.lbl_sponsor_remaining_days = tk.Label(
            self.sponsor_remaining_line, text=ui('ui_0449'), font=LBL_FONT, anchor='w')
        self.lbl_sponsor_remaining_days.pack(side=tk.LEFT, padx=(0, 4))
        self.lbl_sponsor_remaining_day_unit = tk.Label(
            self.sponsor_remaining_line, text=ui('ui_0235'), font=VAL_FONT)
        self.sponsor_remaining_days_var = tk.StringVar(value='')
        sponsor_days_validate = self.root.register(self._validate_sponsor_remaining_days)
        self.spn_sponsor_remaining_days = ttk.Spinbox(
            self.sponsor_remaining_line, textvariable=self.sponsor_remaining_days_var,
            from_=0, to=0xFFFF, width=6, justify='right', font=VAL_FONT,
            command=self._apply_sponsor_remaining_days,
            validate='key', validatecommand=(sponsor_days_validate, '%P'),
        )
        self.spn_sponsor_remaining_days.pack(side=tk.LEFT, padx=(0, 2))
        self.lbl_sponsor_remaining_day_unit.pack(side=tk.LEFT)
        self.spn_sponsor_remaining_days.bind('<Return>', self._apply_sponsor_remaining_days, add='+')
        self.spn_sponsor_remaining_days.bind('<FocusOut>', self._apply_sponsor_remaining_days, add='+')
        self.sponsor_contract_button_host = tk.Frame(self.sponsor_remaining_line, width=84, height=25)
        self.sponsor_contract_button_host.pack_propagate(False)
        self.sponsor_contract_button_host.pack(side=tk.RIGHT, padx=(0, 2))
        self.btn_clear_sponsor_contract = EditorButton(
            self.sponsor_contract_button_host, text=ui('ui_0456'),
            command=self.clear_sponsor_contract, bg='#FCE8E6', fg='#D93025',
            font=('Malgun Gothic', 9), padx=5,
        )
        self.btn_clear_sponsor_contract.pack(fill=tk.BOTH, expand=True)
        self._refresh_sponsor_contract_display()
        # 상단의 여급 선택 영역과 하단 신상정보 영역이 내부 높이를 반씩 사용한다.
        self.profile_page_spouse.columnconfigure(0, weight=1)
        self.profile_page_spouse.rowconfigure(0, weight=2)
        self.profile_page_spouse.rowconfigure(1, weight=3)
        grp_wife = tk.Frame(self.profile_page_spouse)
        grp_wife.grid(row=0, column=0, sticky='nsew', padx=3, pady=4)
        f_w_face_box = tk.Frame(grp_wife, width=84, height=100, bg='#222222', relief='ridge', bd=2)
        f_w_face_box.pack_propagate(False)
        f_w_face_box.place(x=0, y=4)
        self.wife_face_box = f_w_face_box
        self.lbl_wife_face = tk.Label(f_w_face_box, bg='#222222')
        self.lbl_wife_face.pack(fill=tk.BOTH, expand=True)
        f_w_right = grp_wife
        grp_wife.grid_columnconfigure(0, minsize=92)
        grp_wife.grid_columnconfigure(1, weight=1, minsize=0)
        grp_wife.grid_rowconfigure(3, weight=1)
        wife_search_bar = tk.Frame(f_w_right)
        wife_search_bar.grid(row=0, column=1, columnspan=2, padx=(0, 4), pady=(4, 2), sticky='w')
        tk.Label(wife_search_bar, text=ui('ui_0251'), font=LBL_FONT, anchor='w').pack(side=tk.LEFT, padx=(0, 4))
        self._wife_selected_id = None
        self._wife_name_options = [b['name'] for b in BARMAID_DATABASE]
        wife_name_host = tk.Frame(wife_search_bar, width=110, height=23)
        wife_name_host.pack(side=tk.LEFT)
        self.cbo_wife = NativeWinEdit(wife_name_host, lambda: self._schedule_search_refresh('wife', self._refresh_wife_search_results), width=110, height=23)
        self.cbo_wife.set('')
        btn_wife_book = EditorButton(f_w_right, text=ui('ui_0158'), font=('Malgun Gothic', 9), command=self.open_barmaid_guide_html, bg='#FFF8E1', fg='#B06000', padx=4, pady=1)
        btn_wife_book.grid(row=0, column=3, padx=(0, 4), pady=(4, 2), sticky='e')
        wife_search_frame = tk.Frame(f_w_right)
        wife_search_frame.grid(row=1, column=1, columnspan=3, rowspan=3, padx=(0, 4), pady=(0, 4), sticky='nsew')
        self.tree_wife_search = ttk.Treeview(wife_search_frame, columns=('id', 'name'), show='headings', height=5, selectmode='browse')
        self.tree_wife_search.heading('id', text='No')
        self.tree_wife_search.heading('name', text=ui('ui_0062'))
        self.tree_wife_search.column('id', width=38, anchor='center', stretch=False)
        self.tree_wife_search.column('name', width=110, anchor='w', stretch=True)
        self.tree_wife_search.tag_configure('fortune_spouse', background='#FCE4EC')
        wife_search_scroll = ttk.Scrollbar(wife_search_frame, orient=tk.VERTICAL, command=self.tree_wife_search.yview)
        self.tree_wife_search.configure(yscrollcommand=lambda first, last: self._update_inventory_scrollbar(wife_search_scroll, first, last))
        self.tree_wife_search.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree_wife_search.bind('<<TreeviewSelect>>', self.on_wife_search_selected)
        self.lbl_wife_city_title = tk.Label(f_w_right, text=ui('ui_0238'), font=LBL_FONT, anchor='e')
        self.lbl_wife_city_title.grid(row=1, column=1, padx=(0, 4), pady=3, sticky='e')
        self.lbl_wife_city = tk.Label(f_w_right, text=UI_EMPTY_VALUE, font=('Malgun Gothic', 9), anchor='w')
        self.lbl_wife_city.grid(row=1, column=2, pady=3, sticky='w')
        self.lbl_wife_year_title = tk.Label(f_w_right, text=ui('ui_0398'), font=LBL_FONT, anchor='e')
        self.lbl_wife_year_title.grid(row=1, column=3, padx=(10, 4), pady=3, sticky='e')
        self.lbl_wife_year = tk.Label(f_w_right, text=UI_EMPTY_VALUE, font=VAL_FONT, fg='#444444', anchor='w')
        self.lbl_wife_year.grid(row=1, column=4, pady=3, sticky='w')
        self.lbl_wife_zodiac_title = tk.Label(f_w_right, text=ui('ui_0399'), font=LBL_FONT, anchor='e')
        self.lbl_wife_zodiac_title.grid(row=2, column=1, padx=(0, 4), pady=2, sticky='e')
        self.lbl_wife_zodiac = tk.Label(f_w_right, text=UI_EMPTY_VALUE, font=VAL_FONT, fg='#444444', anchor='w')
        self.lbl_wife_zodiac.grid(row=2, column=2, pady=2, sticky='w')
        self.lbl_wife_blood_title = tk.Label(f_w_right, text=ui('ui_0230'), font=LBL_FONT, anchor='e')
        self.lbl_wife_blood_title.grid(row=2, column=3, padx=(10, 4), pady=2, sticky='e')
        self.lbl_wife_blood = tk.Label(f_w_right, text=UI_EMPTY_VALUE, font=VAL_FONT, fg='#444444', anchor='w')
        self.lbl_wife_blood.grid(row=2, column=4, pady=2, sticky='w')
        self.lbl_wife_personality_title = tk.Label(f_w_right, text=ui('ui_0239'), font=LBL_FONT, anchor='e')
        self.lbl_wife_personality_title.grid(row=3, column=1, padx=(0, 4), pady=2, sticky='e')
        self.lbl_wife_personality = tk.Label(f_w_right, text=UI_EMPTY_VALUE, font=VAL_FONT, fg='#444444', anchor='w')
        self.lbl_wife_personality.grid(row=3, column=2, pady=2, sticky='w')
        self.lbl_wife_fortune_title = tk.Label(f_w_right, text=ui('ui_0241'), font=LBL_FONT, anchor='e', cursor='question_arrow')
        self.lbl_wife_fortune_title.grid(row=3, column=3, padx=(10, 4), pady=2, sticky='e')
        self.lbl_wife_compat = tk.Label(f_w_right, text=UI_EMPTY_VALUE, font=('Malgun Gothic', 9), anchor='w')
        self.lbl_wife_compat.grid(row=3, column=4, pady=2, sticky='w')
        self._wife_fortune_tooltip = None
        for widget in (self.lbl_wife_fortune_title, self.lbl_wife_compat):
            widget.bind('<Enter>', self._show_wife_fortune_tooltip, add='+')
            widget.bind('<Leave>', self._hide_wife_fortune_tooltip, add='+')
            widget.bind('<ButtonPress>', self._hide_wife_fortune_tooltip, add='+')
        wife_languages_frame = tk.Frame(self.profile_page_spouse, padx=6, pady=6)
        wife_languages_frame.grid(row=1, column=0, sticky='nsew', padx=3, pady=(0, 4))
        self.tree_wife_languages = ttk.Treeview(wife_languages_frame, columns=('index', 'field', 'value'), show='headings', height=12, selectmode='none')
        self.tree_wife_languages.heading('index', text='No')
        self.tree_wife_languages.heading('field', text=ui('ui_0348'))
        self.tree_wife_languages.heading('value', text=ui('ui_0378'))
        self.tree_wife_languages.column('index', width=40, anchor='center', stretch=False)
        self.tree_wife_languages.column('field', width=92, anchor='e', stretch=False)
        self.tree_wife_languages.column('value', anchor='w', stretch=True)
        self.tree_wife_languages.tag_configure('fortune_spouse', background='#FCE4EC')
        self.tree_wife_languages.pack(fill=tk.BOTH, expand=True)
        grp_stats = tk.Frame(self.profile_page_stats, padx=8, pady=6)
        grp_stats.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        f_stats_top = tk.Frame(grp_stats)
        f_stats_top.pack(side=tk.TOP, fill=tk.X, pady=2)
        tk.Label(f_stats_top, text=ui('ui_0390', 255), font=('Malgun Gothic', 9)).pack(side=tk.LEFT, padx=2)
        self.spn_batch_stats = ttk.Spinbox(f_stats_top, from_=0, to=255, width=5, justify='center', font=('Malgun Gothic', 9))
        self.spn_batch_stats.set('255')
        self.spn_batch_stats.pack(side=tk.LEFT, padx=4)
        EditorButton(f_stats_top, text=ui('ui_0243'), bg='#E6F4EA', fg='#137333', font=('Malgun Gothic', 9), command=self.apply_batch_stats).pack(side=tk.LEFT, padx=4)
        cols_stat = ('index', 'field', 'value', 'maximum')
        f_tree_s = tk.Frame(grp_stats)
        f_tree_s.pack(fill=tk.BOTH, expand=True, pady=2)
        self.tree_stats = ttk.Treeview(f_tree_s, columns=cols_stat, show='headings', height=7)
        col_defs_stat = [('index', 35, 'center', False), ('field', 115, 'center', False),
                         ('value', 90, 'center', False), ('maximum', 115, 'center', True)]
        for c, w, a, s in col_defs_stat:
            self.tree_stats.heading(c, text=TREE_COLUMN_TITLES['stats'][c])
            self.tree_stats.column(c, width=w, anchor=a, stretch=s)
        self.tree_stats.pack(fill=tk.BOTH, expand=True, pady=2)
        self.tree_stats.bind('<Return>', lambda e: self.on_stat_edit_request())
        self.tree_stats.bind('<Double-1>', self.on_stat_edit_request)
        self.tree_stats.bind('<Button-3>', self.on_stat_edit_request)
        self._stats_tooltip = None
        self._stats_tooltip_row = None
        self.tree_stats.bind('<Motion>', self._on_stats_table_motion, add='+')
        self.tree_stats.bind('<Leave>', self._hide_stats_tooltip, add='+')
        self.tree_stats.bind('<ButtonPress>', self._hide_stats_tooltip, add='+')
        grp_money = tk.Frame(self.profile_page_money, padx=8, pady=6)
        grp_money.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        f_money_top = tk.Frame(grp_money)
        f_money_top.pack(side=tk.TOP, fill=tk.X, pady=2)
        tk.Label(f_money_top, text=ui('ui_0390', '99,999,999'), font=('Malgun Gothic', 9)).pack(side=tk.LEFT, padx=2)
        self.spn_batch_money = ttk.Spinbox(f_money_top, from_=0, to=99999999, width=11, justify='center', font=('Malgun Gothic', 9))
        self.spn_batch_money.set('99999999')
        self.spn_batch_money.pack(side=tk.LEFT, padx=4)
        EditorButton(f_money_top, text=ui('ui_0243'), bg='#E6F4EA', fg='#137333', font=('Malgun Gothic', 9), command=self.apply_batch_money).pack(side=tk.LEFT, padx=4)
        cols_money = ('index', 'field', 'value', 'maximum')
        f_tree_m = tk.Frame(grp_money)
        f_tree_m.pack(fill=tk.BOTH, expand=True, pady=2)
        self.tree_money = ttk.Treeview(f_tree_m, columns=cols_money, show='headings', height=5)
        col_defs_money = [('index', 35, 'center', False), ('field', 145, 'center', False), ('value', 135, 'e', False), ('maximum', 115, 'center', True)]
        for c, w, a, s in col_defs_money:
            self.tree_money.heading(c, text=TREE_COLUMN_TITLES['money'][c])
            self.tree_money.column(c, width=w, anchor=a, stretch=s)
        self.tree_money.pack(fill=tk.BOTH, expand=True, pady=2)
        self.tree_money.bind('<Return>', lambda e: self.on_money_edit_request())
        self.tree_money.bind('<Double-1>', self.on_money_edit_request)
        self.tree_money.bind('<Button-3>', self.on_money_edit_request)
        self._money_tooltip = None
        self._money_tooltip_row = None
        self.tree_money.bind('<Motion>', self._on_money_table_motion, add='+')
        self.tree_money.bind('<Leave>', self._hide_money_tooltip, add='+')
        self.tree_money.bind('<ButtonPress>', self._hide_money_tooltip, add='+')
        grp_reputation = tk.Frame(self.profile_page_reputation, padx=8, pady=6)
        grp_reputation.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        f_reputation_top = tk.Frame(grp_reputation)
        f_reputation_top.pack(side=tk.TOP, fill=tk.X, pady=2)
        tk.Label(f_reputation_top, text=ui('ui_0390', f'{PLAYER_REPUTATION_MAX:,}'), font=('Malgun Gothic', 9)).pack(side=tk.LEFT, padx=2)
        self.spn_batch_reputation = ttk.Spinbox(f_reputation_top, from_=0, to=PLAYER_REPUTATION_MAX, width=11, justify='center', font=('Malgun Gothic', 9))
        self.spn_batch_reputation.set(str(PLAYER_REPUTATION_MAX))
        self.spn_batch_reputation.pack(side=tk.LEFT, padx=4)
        EditorButton(f_reputation_top, text=ui('ui_0243'), bg='#E6F4EA', fg='#137333', font=('Malgun Gothic', 9), command=self.apply_batch_reputation).pack(side=tk.LEFT, padx=4)
        f_tree_r = tk.Frame(grp_reputation)
        f_tree_r.pack(fill=tk.BOTH, expand=True, pady=2)
        self.tree_reputation = ttk.Treeview(f_tree_r, columns=cols_money, show='headings', height=5)
        for c, w, a, s in col_defs_money:
            self.tree_reputation.heading(c, text=TREE_COLUMN_TITLES['money'][c])
            self.tree_reputation.column(c, width=w, anchor=a, stretch=s)
        self.tree_reputation.pack(fill=tk.BOTH, expand=True, pady=2)
        self.tree_reputation.bind('<Return>', lambda e: self.on_money_edit_request(tree=self.tree_reputation))
        self.tree_reputation.bind('<Double-1>', lambda e: self.on_money_edit_request(e, self.tree_reputation))
        self.tree_reputation.bind('<Button-3>', lambda e: self.on_money_edit_request(e, self.tree_reputation))
        self.stat_values = [255] * 6 + [CHARACTER_SPECIAL_STAT_MAX]
        self.money_values = [0] * 5
        self.update_player_face_display()
        self.update_wife_display()
        self.refresh_officer_display()

    def _build_person_browser(self, parent):
        """부인·승무원·스폰서를 하나의 목록/상세 화면으로 표시한다."""
        browser = tk.Frame(parent)
        browser.pack(fill=tk.BOTH, expand=True)
        self._person_type_keys = ('spouse', 'officer', 'navigator', 'surveyor', 'interpreter', 'unhireable', 'sponsor')
        self._person_type_names = {
            'spouse': ui('ui_0393'), 'officer': ui('ui_0394'), 'navigator': ui('ui_0395'),
            'surveyor': ui('ui_0396'), 'interpreter': ui('ui_0397'),
            'unhireable': ui('ui_0453'),
            'sponsor': ui('ui_0429'),
        }
        self._person_active_type = 'spouse'
        self._person_selected_sponsor_id = None
        self._person_selected_unhireable_id = None
        self._person_browser_syncing = False

        # 상단 선택 영역: 왼쪽은 초상화와 배정 제어, 오른쪽은 유형·검색·인물 목록이다.
        upper = tk.Frame(browser, height=164)
        upper.pack(fill=tk.X, padx=4, pady=(3, 4))
        upper.pack_propagate(False)
        # 주인공 정보의 얼굴·변경 버튼 폭(84px)과 동일하게 맞춘다.
        left_panel = tk.Frame(upper, width=84)
        left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 6), pady=2)
        left_panel.pack_propagate(False)
        face_box = tk.Frame(left_panel, width=84, height=100, bg='#222222', relief='ridge', bd=2)
        face_box.pack(anchor='n')
        face_box.pack_propagate(False)
        self._person_face_label = tk.Label(face_box, bg='#222222')
        self._person_face_label.pack(fill=tk.BOTH, expand=True)
        self._person_face_photo = None
        self.btn_person_release = EditorButton(
            left_panel, text=ui('ui_0437'), font=('Malgun Gothic', 9),
            command=self._release_person_assignment,
            bg='#FCE8E6', fg='#D93025',
        )
        self.btn_person_release.pack(fill=tk.X, pady=(4, 3))
        self.btn_person_restore = EditorButton(
            left_panel, text=ui('ui_0438'), font=('Malgun Gothic', 9),
            command=self._restore_person_assignment,
            bg='#E8F0FE', fg='#1A73E8',
        )
        self.btn_person_restore.pack(fill=tk.X)

        right_panel = tk.Frame(upper)
        right_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=2)
        header = tk.Frame(right_panel)
        header.pack(fill=tk.X, pady=(0, 3))
        tk.Label(header, text=ui('ui_0430'), font=('Malgun Gothic', 9)).pack(side=tk.LEFT, padx=(0, 4))
        self.cbo_person_type = ttk.Combobox(
            header, values=[self._person_type_names[key] for key in self._person_type_keys],
            state='readonly', width=10, font=('Malgun Gothic', 9))
        self.cbo_person_type.current(0)
        self.cbo_person_type.pack(side=tk.LEFT, padx=(0, 8))
        self.cbo_person_type.bind('<<ComboboxSelected>>', self._on_person_type_changed)
        tk.Label(header, text=ui('ui_0251'), font=('Malgun Gothic', 9)).pack(side=tk.LEFT, padx=(0, 4))
        search_host = tk.Frame(header, width=120, height=23)
        search_host.pack(side=tk.LEFT, fill=tk.X, expand=True)
        search_host.pack_propagate(False)
        self.cbo_person_search = NativeWinEdit(
            search_host, lambda: self._schedule_search_refresh('person-browser', self._refresh_person_browser),
            width=120, height=23)
        self.cbo_person_search.set('')

        list_frame = tk.Frame(right_panel)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.tree_person_list = ttk.Treeview(list_frame, columns=('id', 'name'), show='headings', height=5, selectmode='browse')
        self.tree_person_list.heading('id', text='No')
        self.tree_person_list.heading('name', text=ui('ui_0062'))
        self.tree_person_list.column('id', width=42, anchor='center', stretch=False)
        self.tree_person_list.column('name', anchor='w', stretch=True)
        person_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree_person_list.yview)
        self.tree_person_list.configure(yscrollcommand=person_scroll.set)
        self.tree_person_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        person_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_person_list.bind('<<TreeviewSelect>>', self._on_person_list_selected)
        # 인물 목록은 역할을 즉시 지정하므로, 방향키 이동도 반드시 이 목록의
        # 선택 변경 이벤트를 거치게 명시적으로 연결한다.
        self.tree_person_list.bind('<Up>', lambda event: self._move_treeview_selection(event, -1))
        self.tree_person_list.bind('<Down>', lambda event: self._move_treeview_selection(event, 1))

        # 역할을 선택했을 때는 이전 화면의 상세 탭(기본 정보·능력치·명성·기술·언어)을
        # 그대로 보여 준다. 부인·스폰서는 기본 정보 탭 하나만 사용한다.
        self.person_detail_tabs = ttk.Notebook(browser, style='Editor.TNotebook')
        self.person_detail_tabs.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))
        self._person_detail_pages = [ttk.Frame(browser) for _ in range(5)]
        # 주인공 하단 탭과 같은 바깥 여백을 사용한다. 인물 탭의 일괄 적용 줄과
        # 목록이 서로 다른 부모 프레임에 있어 생기던 위치 차이를 없앤다.
        self._person_detail_bodies = []
        for page in self._person_detail_pages:
            body = tk.Frame(page, padx=8, pady=6)
            body.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
            self._person_detail_bodies.append(body)
        self._person_detail_titles = PERSON_TAB_TITLES
        self._person_batch_spinners = {}
        for detail_index, maximum, width, label_text in (
                (1, 255, 5, ui('ui_0390', 255)),
                (2, PERSON_REPUTATION_MAX, 8, ui('ui_0390', f'{PERSON_REPUTATION_MAX:,}')),
                (3, 3, 4, ui('ui_0247')),
                (4, 3, 4, ui('ui_0247'))):
            batch_bar = tk.Frame(self._person_detail_bodies[detail_index])
            batch_bar.pack(side=tk.TOP, fill=tk.X, pady=2)
            tk.Label(batch_bar, text=label_text, font=('Malgun Gothic', 9)).pack(side=tk.LEFT, padx=2)
            spinner = ttk.Spinbox(
                batch_bar, from_=0, to=maximum, width=width, justify='center', font=('Malgun Gothic', 9))
            spinner.set(str(maximum))
            spinner.pack(side=tk.LEFT, padx=4)
            EditorButton(
                batch_bar, text=ui('ui_0243'), bg='#E6F4EA', fg='#137333',
                command=lambda index=detail_index: self._apply_person_batch_detail(index),
            ).pack(side=tk.LEFT, padx=4)
            self._person_batch_spinners[detail_index] = spinner
        basic_tree = self._make_officer_tree(
            self._person_detail_bodies[0], ('index', 'field', 'value'),
            ((ui('ui_0346'), 38, 'center', False), (ui('ui_0348'), 120, 'w', True), (ui('ui_0378'), 170, 'w', True)), 8,
            frame_padx=0, frame_pady=0, pack_pady=2)
        stats_tree = self._make_officer_tree(
            self._person_detail_bodies[1], ('index', 'field', 'value', 'maximum'),
            ((ui('ui_0346'), 35, 'center', False), (ui('ui_0348'), 115, 'center', False), (ui('ui_0350'), 90, 'center', False),
             (TREE_COLUMN_TITLES['stats']['maximum'], 115, 'center', True)), 7,
            frame_padx=0, frame_pady=0, pack_pady=2)
        fame_tree = self._make_officer_tree(
            self._person_detail_bodies[2], ('index', 'field', 'value', 'maximum'),
            ((ui('ui_0346'), 35, 'center', False), (ui('ui_0348'), 145, 'center', False), (ui('ui_0350'), 135, 'e', False),
             (TREE_COLUMN_TITLES['money']['maximum'], 115, 'center', True)), 5,
            frame_padx=0, frame_pady=0, pack_pady=2)
        skill_tree = self._make_officer_tree(
            self._person_detail_bodies[3], ('index', 'field', 'value'),
            ((ui('ui_0346'), 35, 'center', False), (ui('ui_0348'), 190, 'w', True), (ui('ui_0490'), 150, 'center', False)), 13,
            frame_padx=0, frame_pady=0, pack_pady=2)
        language_tree = self._make_officer_tree(
            self._person_detail_bodies[4], ('index', 'field', 'value'),
            ((ui('ui_0346'), 35, 'center', False), (ui('ui_0348'), 195, 'w', True), (ui('ui_0490'), 155, 'center', False)), 14,
            frame_padx=0, frame_pady=0, pack_pady=2)
        self._person_detail_trees = (basic_tree, stats_tree, fame_tree, skill_tree, language_tree)
        self.tree_person_details = self._person_detail_trees[0]
        self.tree_person_stats = self._person_detail_trees[1]
        self._sponsor_fame_tooltip = None
        self._sponsor_fame_tooltip_row = None
        self.tree_person_details.bind('<Motion>', self._on_sponsor_fame_motion, add='+')
        self.tree_person_details.bind('<Leave>', self._hide_sponsor_fame_tooltip, add='+')
        self.tree_person_details.bind('<ButtonPress>', self._hide_sponsor_fame_tooltip, add='+')
        self._person_hire_cost_tooltip = None
        self._person_hire_cost_tooltip_row = None
        self.tree_person_stats.bind('<Motion>', self._on_person_detail_motion, add='+')
        self.tree_person_stats.bind('<Leave>', self._hide_person_hire_cost_tooltip, add='+')
        self.tree_person_stats.bind('<ButtonPress>', self._hide_person_hire_cost_tooltip, add='+')
        for detail_index, detail_tree in enumerate(self._person_detail_trees[1:], start=1):
            # 기본 _make_officer_tree는 읽기 전용 화면용으로 selectmode='none'을
            # 사용한다. 이 네 탭은 행 선택 후 수정해야 하므로 별도로 활성화한다.
            detail_tree.configure(selectmode='browse')
            detail_tree.bind(
                '<Return>', lambda _event, index=detail_index: self._edit_person_detail_value(index), add='+')
            detail_tree.bind(
                '<Double-1>',
                lambda event, index=detail_index: self._edit_person_detail_value(index, event), add='+')
        self._set_person_detail_mode(False)
        self._refresh_person_browser()

    def _set_person_detail_mode(self, role_mode):
        """역할은 기존의 5개 상세 탭을, 부인·스폰서는 단일 정보 탭을 표시한다."""
        if not hasattr(self, 'person_detail_tabs'):
            return
        tabs = self.person_detail_tabs
        pages = self._person_detail_pages
        if role_mode:
            for page, title in zip(pages, self._person_detail_titles):
                tabs.add(page, text=title)
        else:
            tabs.add(pages[0], text=ui('ui_0489'))
            for page in pages[1:]:
                # 최초 구성에서는 아직 Notebook에 추가되지 않은 페이지가 있다.
                if str(page) in tabs.tabs():
                    tabs.hide(page)

    def _on_person_type_changed(self, _event=None):
        index = self.cbo_person_type.current()
        if 0 <= index < len(self._person_type_keys):
            self._person_active_type = self._person_type_keys[index]
        self.cbo_person_search.set('')
        self._refresh_person_browser()

    def _set_person_assignment_buttons_visible(self):
        """배정 가능한 유형의 제거와 전체 인물 정보 되돌리기를 갱신한다."""
        kind = self._person_active_type
        editable = kind in ('spouse', 'officer', 'navigator', 'surveyor', 'interpreter')
        restore_supported = editable or kind == 'unhireable'
        if editable:
            if not self.btn_person_release.winfo_manager():
                self.btn_person_release.pack(fill=tk.X, pady=(4, 3))
        else:
            self.btn_person_release.pack_forget()
        self.btn_person_restore.pack_forget()
        if not restore_supported:
            return
        if editable and kind == 'spouse':
            # 인물 브라우저가 기존 부인 화면보다 먼저 만들어질 수 있다.
            assigned = getattr(self, '_wife_selected_id', None) is not None
        elif editable:
            assigned = self._person_role_id(kind) is not None
        if editable:
            # 이미 비어 있는 배정은 다시 해제할 수 없다.
            self.btn_person_release.config(state=tk.NORMAL if assigned else tk.DISABLED)
        if self._person_data_has_changes():
            self.btn_person_restore.pack(fill=tk.X)

    def _release_person_assignment(self):
        """현재 부인 또는 역할 배정을 없음 상태로 만든다."""
        kind = self._person_active_type
        if kind == 'spouse':
            if self._wife_selected_id is None:
                return
            self._wife_selected_id = None
            self.update_wife_display()
            self.lbl_status.config(text=ui('ui_0415'))
        elif kind in self._crew_profiles:
            self.clear_role(kind)
        else:
            return
        self._refresh_person_browser()

    def _restore_person_assignment(self):
        """인물 정보 전체를 최초 파일 로드 상태로 복원한다."""
        original = getattr(self, 'person_original_buffer', None)
        if not self.file_buffer or not original:
            return
        if CHARACTER_SAVE_TABLE_END > len(self.file_buffer) or CHARACTER_SAVE_TABLE_END > len(original):
            return
        self.file_buffer[173:175] = original[173:175]
        for offset in ROLE_SLOT_OFFSETS:
            self.file_buffer[offset:offset + 2] = original[offset:offset + 2]
        self.file_buffer[CHARACTER_SAVE_TABLE_OFFSET:CHARACTER_SAVE_TABLE_END] = (
            original[CHARACTER_SAVE_TABLE_OFFSET:CHARACTER_SAVE_TABLE_END])
        # 상세 목록도 원본 인물 스냅샷을 다시 기준으로 삼는다.
        self.person_display_buffer = bytes(original)
        spouse_code = struct.unpack_from('<H', original, 173)[0]
        self._wife_selected_id = (spouse_code & 0x7F) if (spouse_code & 0xFF00) == 0x2000 else None
        self.update_wife_display()
        self._refresh_all_crew_profiles(refresh_lists=True)
        self.refresh_officer_display()
        self.lbl_status.config(text=ui('ui_0455'))
        self._refresh_person_browser()

    def _person_data_has_changes(self):
        """부인·역할 슬롯·일반 인물 표 전체의 원본 대비 변경 여부를 반환한다."""
        original = getattr(self, 'person_original_buffer', None)
        if not self.file_buffer or not original or CHARACTER_SAVE_TABLE_END > len(self.file_buffer) or CHARACTER_SAVE_TABLE_END > len(original):
            return False
        if self.file_buffer[173:175] != original[173:175]:
            return True
        if any(self.file_buffer[offset:offset + 2] != original[offset:offset + 2] for offset in ROLE_SLOT_OFFSETS):
            return True
        return (self.file_buffer[CHARACTER_SAVE_TABLE_OFFSET:CHARACTER_SAVE_TABLE_END]
                != original[CHARACTER_SAVE_TABLE_OFFSET:CHARACTER_SAVE_TABLE_END])

    def _person_role_id(self, key):
        profile = getattr(self, '_crew_profiles', {}).get(key)
        if profile is None or not self.file_buffer:
            return None
        code = struct.unpack_from('<H', self.file_buffer, profile['offset'])[0]
        return code - 0x1000 if (code & 0xFF00) == 0x1000 else None

    def _refresh_person_browser(self):
        """선택 타입에 맞는 목록·초상화·상세 항목을 한 번에 갱신한다."""
        if not hasattr(self, 'tree_person_list'):
            return
        kind = self._person_active_type
        query = self.cbo_person_search.get().strip().casefold()
        tree = self.tree_person_list
        # 운명의 반려자는 얼룩무늬보다 뒤 태그로 넣어 핑크색이 우선되게 한다.
        tree.tag_configure('fortune_spouse', background='#FCE4EC')
        self._person_browser_syncing = True
        tree.delete(*tree.get_children())
        rows = []
        if kind == 'spouse':
            rows = [(int(item['id']), item['name']) for item in BARMAID_DATABASE]
            selected_id = self._wife_selected_id if self.file_buffer else None
            fortune_face_code = self._get_wife_fortune_face_code()
        elif kind == 'sponsor':
            rows = [(int(item['id']), item['name']) for item in SPONSOR_DATA['records']]
            selected_id = self._person_selected_sponsor_id
        elif kind == 'unhireable':
            # 경쟁자(0)와 대화만 가능한 인물(1)은 모두 등용할 수 없다.
            hire_states = self._character_hire_states()
            rows = [(int(item['id']), item['name']) for item in CHARACTER_DATA['records']
                    if hire_states.get(int(item['id']), 0) in (0, 1)]
            selected_id = self._person_selected_unhireable_id
        else:
            selected_id = self._person_role_id(kind)
            # 역할 배정 화면에는 고용 가능(2) 인물만 보인다. 현재 역할에 이미
            # 배정되어 고용 중(3)인 인물은 선택 표시를 유지할 수 있도록 예외로 둔다.
            hire_states = self._character_hire_states()
            rows = [
                (int(item['id']), item['name']) for item in CHARACTER_DATA['records']
                if hire_states.get(int(item['id']), 0) == 2 or int(item['id']) == selected_id
            ]
        if kind != 'spouse':
            fortune_face_code = None
        display_index = 0
        for item_id, name in rows:
            if query and query not in name.casefold():
                continue
            # 내부 iid는 실제 인물 ID를 유지하되, 목록 순번은 항상 0부터 연속 표기한다.
            tags = ()
            if (fortune_face_code is not None and
                    is_fortune_spouse(BARMAID_BY_ID.get(item_id, {}), fortune_face_code)):
                tags = ('fortune_spouse',)
            tree.insert('', tk.END, iid=str(item_id), values=(f'{display_index:03d}', name), tags=tags)
            display_index += 1
        target = str(selected_id) if selected_id is not None else ''
        if target and tree.exists(target):
            tree.selection_set(target)
            tree.focus(target)
            tree.see(target)
        elif kind in ('sponsor', 'rival') and tree.get_children():
            target = tree.get_children()[0]
            tree.selection_set(target)
            tree.focus(target)
        # Treeview의 선택 변경 가상 이벤트는 다음 idle에 전달될 수 있다.
        # 그때까지 잠금을 유지해 프로그램 선택이 사용자 선택으로 되돌아오는 순환을 막는다.
        self.root.after_idle(lambda: setattr(self, '_person_browser_syncing', False))
        self._set_person_assignment_buttons_visible()
        self._refresh_person_details(target)

    def _on_person_list_selected(self, _event=None):
        if self._person_browser_syncing:
            return
        selection = self.tree_person_list.selection()
        if not selection:
            return
        item_id, kind = selection[0], self._person_active_type
        if kind == 'sponsor':
            self._person_selected_sponsor_id = int(item_id)
        elif kind == 'unhireable':
            self._person_selected_unhireable_id = int(item_id)
        elif kind == 'spouse':
            previous_id = self._wife_selected_id
            self._wife_selected_id = int(item_id)
            self.update_wife_display()
            if previous_id != self._wife_selected_id and not getattr(self, '_is_loading_save', False):
                self.lbl_status.config(text=ui('ui_0415') if self._wife_selected_id is None
                                           else ui('ui_0416', BARMAID_BY_ID[self._wife_selected_id]['name']))
        elif kind in self._crew_profiles:
            self.assign_role(kind, int(item_id))
        self._refresh_person_browser()

    def _sponsor_preference_names(self, sponsor):
        """현재 게임 EXE의 취향 마스크를 원본 비트 순서로 풀어 쓴다."""
        sponsor_id = int(sponsor['id'])
        mask = self._sponsor_exe_preference_flags.get(
            sponsor_id, int(sponsor.get(
                'preference_flags_exe',
                normalized_sponsor_preference_to_exe(sponsor.get('preference_flags', 0)))))
        return ', '.join(name for bit, name in enumerate(SPONSOR_EXE_PREFERENCE_NAMES)
                         if mask & (1 << bit)) or '-'

    def _refresh_person_details(self, item_id):
        kind = self._person_active_type
        role_mode = kind in self._crew_profiles or kind == 'unhireable'
        self._set_person_detail_mode(role_mode)
        clear_rows(*self._person_detail_trees)
        tree = self.tree_person_details
        tree.tag_configure('fortune_spouse', background='#FCE4EC')
        # 상세 목록과 툴팁은 목록 선택 이벤트의 지연 여부와 무관하게 같은 후원자를 가리켜야 한다.
        self._person_detail_sponsor_id = None
        self._person_face_photo = None
        self._person_face_label.config(image='', bg='#222222')
        rows, image_path = [], None
        if kind == 'spouse' and item_id not in ('', None, '__none__'):
            barmaid = BARMAID_BY_ID.get(int(item_id))
            if barmaid:
                flags = int(barmaid.get('language_flags', 0))
                languages = ', '.join(name for bit, name in enumerate(LANGUAGE_NAMES) if flags & (1 << bit)) or '-'
                fortune_face_code = self._get_wife_fortune_face_code()
                fortune_text = (ui('ui_0272') if fortune_face_code is not None and
                                is_fortune_spouse(barmaid, fortune_face_code) else ui('ui_0277'))
                rows = ((ui('ui_0062'), barmaid['name']), (ui('ui_0354'), get_barmaid_city_name(barmaid)),
                        (ui('ui_0432'), f"{barmaid['year']}{ui('ui_0233')}"), (ui('ui_0399').rstrip(':'), get_barmaid_zodiac_name(barmaid)),
                        (ui('ui_0230').rstrip(':'), get_barmaid_blood_name(barmaid)), (ui('ui_0501'), get_barmaid_personality(barmaid)),
                        (ui('ui_0061'), fortune_text), (ui('ui_0068'), languages))
                image_path = get_barmaid_image_path(barmaid['id'])
        elif kind == 'sponsor' and item_id:
            sponsor = SPONSOR_BY_ID.get(int(item_id))
            if sponsor:
                self._person_detail_sponsor_id = int(sponsor['id'])
                preferences = self._sponsor_preference_names(sponsor)
                retire = int(sponsor['retirement_year'])
                rows = ((ui('ui_0062'), sponsor['name']), (ui('ui_0354'), sponsor['city']), (ui('ui_0491'), sponsor['nation']),
                        (ui('ui_0492'), sponsor['job']), (ui('ui_0432'), f"{sponsor['appearance_year']}{ui('ui_0233')}"),
                        (ui('ui_0433'), f"{retire}{ui('ui_0233')}" if retire else '-'), (ui('ui_0434'), str(int(sponsor['wealth_factor']))),
                        (ui('ui_0464'), str(int(sponsor['power']))),
                        (ui('ui_0431'), preferences))
                image_path = get_sponsor_image_path(sponsor['id'])
        elif role_mode and item_id not in ('', None, '__none__'):
            # 통합 인물 화면은 편집 버퍼가 아닌 마지막 저장/로드 시점의 별도
            # 스냅샷만 읽는다. 따라서 역할 지정은 file_buffer에 즉시 반영되어도
            # 여기의 기본 정보·능력치 등은 저장하기 전까지 바뀌지 않는다.
            self._populate_person_snapshot_details(int(item_id), include_hire_state=True)
            image_path = (get_unemployable_image_path(int(item_id)) if kind == 'unhireable'
                          else get_sailer_image_path(int(item_id)))
        if not role_mode:
            for index, (field, value) in enumerate(rows):
                tags = ('fortune_spouse',) if field == ui('ui_0061') and value == ui('ui_0272') else ()
                tree.insert('', tk.END, values=(index, field, value), tags=tags)
        if image_path:
            photo = get_cached_photo(image_path)
            if photo:
                self._person_face_photo = photo
                self._person_face_label.config(image=photo)
        if not role_mode:
            self._schedule_treeview_autofit(tree)

    def _on_sponsor_fame_motion(self, event):
        """후원자 명성 계수 행에 알현 요구 명성 계산식을 표시한다."""
        tree = self.tree_person_details
        row = tree.identify_row(event.y)
        is_field_column = tree.identify_column(event.x) == '#2'
        values = tree.item(row, 'values') if row else ()
        is_sponsor_field = (
            is_field_column and self._person_active_type == 'sponsor' and len(values) >= 3 and
            values[1] in (ui('ui_0464'), ui('ui_0434')))
        if getattr(self, '_sponsor_fame_tooltip_row', None) != row or not is_sponsor_field:
            self._hide_sponsor_fame_tooltip()
        if not is_sponsor_field or self._sponsor_fame_tooltip is not None:
            return
        try:
            coefficient = int(values[2])
        except (IndexError, TypeError, ValueError):
            coefficient = 0
        tooltip = tk.Toplevel(self.root)
        tooltip.wm_overrideredirect(True)
        tooltip.attributes('-topmost', True)
        sponsor_id = getattr(self, '_person_detail_sponsor_id', None)
        sponsor = SPONSOR_BY_ID.get(int(sponsor_id)) if sponsor_id is not None else None
        if values[1] == ui('ui_0434'):
            tooltip_text = ui('ui_0468', coefficient, coefficient * 10000)
        else:
            building_id = int(sponsor.get('building_id', -1)) if sponsor else -1
            multiplier = SPONSOR_FAME_MULTIPLIER_BY_BUILDING.get(building_id, 0)
            building_name = SPONSOR_BUILDING_NAME_BY_ID.get(building_id, UI_EMPTY_VALUE)
            required_fame = coefficient * multiplier
            tooltip_text = ui('ui_0465', building_name, coefficient, multiplier, required_fame)
        tk.Label(tooltip, text=tooltip_text,
                 justify='left', anchor='w',
                 bg='#FFF8D6', fg='#333333', relief='solid', bd=1,
                 padx=8, pady=6, font=('Malgun Gothic', 9)).pack()
        tooltip.geometry(f'+{event.x_root + 16}+{event.y_root + 18}')
        self._sponsor_fame_tooltip = tooltip
        self._sponsor_fame_tooltip_row = row

    def _hide_sponsor_fame_tooltip(self, _event=None):
        tooltip = getattr(self, '_sponsor_fame_tooltip', None)
        self._sponsor_fame_tooltip = None
        self._sponsor_fame_tooltip_row = None
        if tooltip is not None:
            try:
                tooltip.destroy()
            except tk.TclError:
                pass

    @staticmethod
    def _character_stat_rows(record, record_offset):
        """인물 레코드의 공통 능력치 필드를 화면 표시 순서로 읽는다."""
        values = read_character_stat_values(record, record_offset, CHARACTER_SPECIAL_STAT_OFFSET)
        return tuple(zip(PERSON_STAT_NAMES, values))

    @staticmethod
    def _character_record_name(record, record_offset, fallback=UI_EMPTY_VALUE):
        """세이브 인물 레코드의 성·이름 필드를 읽고 비어 있으면 기본명을 반환한다."""
        return read_character_name(record, record_offset, fallback)

    def _populate_person_snapshot_details(self, character_id, include_hire_state=True):
        """통합 인물 상세 탭을 마지막 저장/로드 스냅샷으로 채운다."""
        snapshot = getattr(self, 'person_display_buffer', None)
        character = CHARACTER_BY_ID.get(character_id, {})
        record_offset = 0x924A + character_id * 0x90
        if (not snapshot or character_id < 0 or
                record_offset + 0x90 > len(snapshot)):
            return

        record = snapshot
        name = self._character_record_name(record, record_offset, character.get('name', UI_EMPTY_VALUE))
        nation_id = int(character.get('nation_id', -1))
        job_id = int(character.get('job_id', -1))
        # 세이브 레코드의 나이는 저장 당시의 값이다. EXE는 해가 바뀔 때마다
        # 모든 인물의 나이를 1씩 올리므로, 편집 중인 현재 연도와의 차이만큼
        # 보정해 화면에 표시한다.
        saved_age = struct.unpack_from('<i', record, record_offset + 0x5C)[0]
        saved_year = struct.unpack_from('<H', record, 21)[0]
        try:
            current_year = int(self.spn_game_y.get())
        except (ValueError, tk.TclError):
            current_year = saved_year
        age = saved_age + (current_year - saved_year) if saved_year > 0 else saved_age
        blood_id = record[record_offset + 0x64]
        city_id = record[record_offset + 0x2E]
        building_id = record[record_offset + 0x30]
        raw_hire_state = record[record_offset + 0x62]
        # 고용 중 여부는 레코드의 원시 상태값이 아니라 세이브의 역할 슬롯으로 판정한다.
        hire_state = 3 if character_id in self._active_role_character_ids(snapshot) else raw_hire_state
        city_name = ui('ui_0498') if city_id == 0xFF else CITY_NAME_BY_ID.get(city_id, UI_EMPTY_VALUE)
        building_name = {4: ui('ui_0412'), 5: ui('ui_0413')}.get(building_id, UI_EMPTY_VALUE)
        blood_name = BLOOD_NAMES[blood_id] if 0 <= blood_id < len(BLOOD_NAMES) else UI_EMPTY_VALUE

        basic_rows = [
            (ui('ui_0062'), name),
            (ui('ui_0493'), ui('ui_0502', age)),
            (ui('ui_0463'), ui('ui_0466') if age < 18 else ui('ui_0500') if age > 60 else ui('ui_0499')),
            (ui('ui_0066'), blood_name),
            (ui('ui_0491'), NATION_NAMES[nation_id] if 0 <= nation_id < len(NATION_NAMES) else UI_EMPTY_VALUE),
            (ui('ui_0492'), JOB_NAMES[job_id] if 0 <= job_id < len(JOB_NAMES) else UI_EMPTY_VALUE),
            (ui('ui_0494'), city_name),
            (ui('ui_0409'), building_name),
        ]
        if include_hire_state:
            if hire_state == 2:
                # 게임은 인물의 고용비 계수(vitality)를 원금 계수로 사용한다.
                # 웅변술 할인이 적용되기 전 가격은 vitality * 10 // 3 이다.
                base_hire_cost = int(character.get('vitality', 0)) * 10 // 3
                basic_rows.append((ui('ui_0442'), f'{base_hire_cost:,} G'))
            hire_text = {
                0: ui('ui_0436'),
                1: ui('ui_0403'),
                2: ui('ui_0404'),
                3: ui('ui_0405'),
            }.get(hire_state, str(hire_state))
            basic_rows.append((ui('ui_0495'), hire_text))
        for index, row in enumerate(basic_rows):
            self._person_detail_trees[0].insert('', tk.END, values=(index, *row))

        stat_rows = self._character_stat_rows(record, record_offset)
        for index, row in enumerate(stat_rows):
            maximum = CHARACTER_SPECIAL_STAT_MAX if index == len(stat_rows) - 1 else 255
            self._person_detail_trees[1].insert('', tk.END, values=(index, *row, maximum))
        self._person_detail_trees[2].insert('', tk.END, values=(
            0, ui('ui_0407'), f"{struct.unpack_from('<H', record, record_offset + 0x26)[0]:,}", f'{PERSON_REPUTATION_MAX:,}'))
        self._person_detail_trees[2].insert('', tk.END, values=(
            1, ui('ui_0497'), f"{struct.unpack_from('<H', record, record_offset + 0x2A)[0]:,}", f'{PERSON_REPUTATION_MAX:,}'))
        for index, (skill_name, _offset, _description) in enumerate(SKILLS_DATA):
            target, row = (self._person_detail_trees[3], index) if index < 13 else (self._person_detail_trees[4], index - 13)
            target.insert('', tk.END, values=(row, skill_name, record[record_offset + 0x0B + index]))
        self._schedule_treeview_autofit(*self._person_detail_trees)

    def _on_person_detail_motion(self, event):
        """능력치 탭의 고용비 계수 항목에서만 계산식 툴팁을 표시한다."""
        tree = self.tree_person_stats
        row = tree.identify_row(event.y)
        is_field_column = tree.identify_column(event.x) == '#2'
        values = tree.item(row, 'values') if row else ()
        is_hire_cost = is_field_column and len(values) >= 2 and values[1] == ui('ui_0496')
        if getattr(self, '_person_hire_cost_tooltip_row', None) != row or not is_hire_cost:
            self._hide_person_hire_cost_tooltip()
        if not is_hire_cost or self._person_hire_cost_tooltip is not None:
            return
        tooltip = tk.Toplevel(self.root)
        tooltip.wm_overrideredirect(True)
        tooltip.attributes('-topmost', True)
        tk.Label(tooltip, text=ui('ui_0443'), justify='left', anchor='w',
                 bg='#FFF8D6', fg='#333333', relief='solid', bd=1,
                 padx=8, pady=6, font=('Malgun Gothic', 9)).pack()
        tooltip.geometry(f'+{event.x_root + 16}+{event.y_root + 18}')
        self._person_hire_cost_tooltip = tooltip
        self._person_hire_cost_tooltip_row = row

    def _hide_person_hire_cost_tooltip(self, _event=None):
        tooltip = getattr(self, '_person_hire_cost_tooltip', None)
        self._person_hire_cost_tooltip = None
        self._person_hire_cost_tooltip_row = None
        if tooltip is not None:
            try:
                tooltip.destroy()
            except tk.TclError:
                pass

    def _edit_person_detail_value(self, detail_index, event=None):
        """인물 능력치·명성·기술·언어를 편집 버퍼에 직접 기록한다."""
        kind = self._person_active_type
        if kind not in (*self._crew_profiles.keys(), 'unhireable') or not self.file_buffer:
            return 'break' if event is not None else None
        tree = self._person_detail_trees[detail_index]
        if event is not None:
            item = tree.identify_row(event.y)
            if item:
                tree.selection_set(item)
        selection = tree.selection()
        character_selection = self.tree_person_list.selection()
        if not selection or not character_selection or not character_selection[0].isdigit():
            return 'break' if event is not None else None
        character_id = int(character_selection[0])
        record_offset = 0x924A + character_id * 0x90
        if record_offset + 0x90 > len(self.file_buffer):
            return 'break' if event is not None else None
        values = tree.item(selection[0], 'values')
        try:
            # 이 트리는 Treeview IID를 지정하지 않아 Tk가 I001 같은 문자열을
            # 만든다. 실제 행 순번은 첫 번째 열의 표시값을 사용해야 한다.
            row_index = int(values[0])
        except (IndexError, TypeError, ValueError):
            return 'break' if event is not None else None
        field_name = values[1] if len(values) > 1 else ''

        if detail_index == 1:
            stat_offsets = (0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x66, CHARACTER_SPECIAL_STAT_OFFSET)
            if not 0 <= row_index < len(stat_offsets):
                return 'break' if event is not None else None
            is_special_stat = row_index == len(stat_offsets) - 1
            maximum = CHARACTER_SPECIAL_STAT_MAX if is_special_stat else 255
            current = (struct.unpack_from('<I', self.file_buffer, record_offset + stat_offsets[row_index])[0]
                       if is_special_stat else self.file_buffer[record_offset + stat_offsets[row_index]])
            value = self.ask_bounded_integer(ui('ui_0201'), ui('ui_0033', field_name),
                                             current, 0, maximum)
            if value is not None:
                if is_special_stat:
                    struct.pack_into('<I', self.file_buffer, record_offset + stat_offsets[row_index], value)
                else:
                    self.file_buffer[record_offset + stat_offsets[row_index]] = value
                tree.item(selection[0], values=(row_index, field_name, value, maximum))
        elif detail_index == 2:
            fame_offsets = (0x26, 0x2A)
            if not 0 <= row_index < len(fame_offsets):
                return 'break' if event is not None else None
            current = struct.unpack_from('<H', self.file_buffer, record_offset + fame_offsets[row_index])[0]
            value = self.ask_bounded_integer(ui('ui_0454'), ui('ui_0034', field_name, 0xFFFF),
                                             current, 0, 0xFFFF)
            if value is not None:
                struct.pack_into('<H', self.file_buffer, record_offset + fame_offsets[row_index], value)
                tree.item(selection[0], values=(row_index, field_name, f'{value:,}', f'{PERSON_REPUTATION_MAX:,}'))
        elif detail_index in (3, 4):
            skill_index = row_index if detail_index == 3 else row_index + 13
            if not 0 <= skill_index < len(SKILLS_DATA):
                return 'break' if event is not None else None
            offset = record_offset + 0x0B + skill_index
            title = ui('ui_0203') if detail_index == 3 else ui('ui_0204')
            value = self.ask_bounded_integer(title, ui('ui_0035', field_name), self.file_buffer[offset], 0, 3)
            if value is not None:
                self.file_buffer[offset] = value
                tree.item(selection[0], values=(row_index, field_name, value))
        self._set_person_assignment_buttons_visible()
        return 'break' if event is not None else None

    def _apply_person_batch_detail(self, detail_index):
        """선택한 인물의 능력치·명성·기술·언어 값을 한 번에 적용한다."""
        kind = self._person_active_type
        if kind not in (*self._crew_profiles.keys(), 'unhireable') or not self.file_buffer:
            return
        selection = self.tree_person_list.selection()
        if not selection or not selection[0].isdigit():
            return
        character_id = int(selection[0])
        record_offset = CHARACTER_SAVE_TABLE_OFFSET + character_id * CHARACTER_SAVE_RECORD_SIZE
        if record_offset + CHARACTER_SAVE_RECORD_SIZE > len(self.file_buffer):
            return
        limits = {1: 255, 2: PERSON_REPUTATION_MAX, 3: 3, 4: 3}
        spinner = self._person_batch_spinners.get(detail_index)
        if spinner is None or detail_index not in limits:
            return
        maximum = limits[detail_index]
        try:
            value = min(maximum, max(0, int(spinner.get())))
        except (TypeError, ValueError):
            value = maximum
        spinner.set(str(value))
        tree = self._person_detail_trees[detail_index]
        if detail_index == 1:
            offsets = (0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x66, CHARACTER_SPECIAL_STAT_OFFSET)
            for row_index, offset in enumerate(offsets):
                is_special_stat = row_index == len(offsets) - 1
                if is_special_stat:
                    struct.pack_into('<I', self.file_buffer, record_offset + offset, value)
                else:
                    self.file_buffer[record_offset + offset] = value
                item = tree.get_children()[row_index] if row_index < len(tree.get_children()) else None
                if item:
                    field_name = tree.item(item, 'values')[1]
                    maximum = CHARACTER_SPECIAL_STAT_MAX if is_special_stat else 255
                    tree.item(item, values=(row_index, field_name, value, maximum))
        elif detail_index == 2:
            for row_index, offset in enumerate((0x26, 0x2A)):
                struct.pack_into('<H', self.file_buffer, record_offset + offset, value)
                item = tree.get_children()[row_index] if row_index < len(tree.get_children()) else None
                if item:
                    field_name = tree.item(item, 'values')[1]
                    tree.item(item, values=(row_index, field_name, f'{value:,}', f'{PERSON_REPUTATION_MAX:,}'))
        else:
            start, end = (0, 13) if detail_index == 3 else (13, len(SKILLS_DATA))
            for row_index, skill_index in enumerate(range(start, end)):
                self.file_buffer[record_offset + 0x0B + skill_index] = value
                item = tree.get_children()[row_index] if row_index < len(tree.get_children()) else None
                if item:
                    field_name = tree.item(item, 'values')[1]
                    tree.item(item, values=(row_index, field_name, value))
        self._set_person_assignment_buttons_visible()

    def build_crew_profile(self, key, page, role_offset, role_name):
        """항해사·측량사·통역에 공통으로 쓰는 승무원 선택 화면을 만든다."""
        label_font, value_font = ('Malgun Gothic', 9), ('Malgun Gothic', 9)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=2)
        page.rowconfigure(1, weight=3)
        profile = tk.Frame(page)
        profile.grid(row=0, column=0, sticky='nsew', padx=3, pady=4)
        # 부관 탭과 같은 80×96 초상화 영역을 유지한다.
        photo_box = tk.Frame(profile, width=84, height=100, bg='#222222', relief='ridge', bd=2)
        photo_box.pack_propagate(False)
        photo_box.grid(row=0, column=0, rowspan=2, padx=(0, 4), pady=4, sticky='nw')
        face_label = tk.Label(photo_box, bg='#222222')
        face_label.pack(fill=tk.BOTH, expand=True)
        profile.columnconfigure(0, minsize=92)
        profile.columnconfigure(1, weight=1)
        profile.rowconfigure(1, weight=1)
        search_bar = tk.Frame(profile)
        search_bar.grid(row=0, column=1, padx=(0, 4), pady=(4, 2), sticky='w')
        tk.Label(search_bar, text=ui('ui_0400'), font=label_font).pack(side=tk.LEFT, padx=(0, 4))
        category = ttk.Combobox(search_bar, values=[ui('ui_0364'), ui('ui_0403'), ui('ui_0404'), ui('ui_0405')],
                                state='readonly', width=8, font=value_font)
        category.current(0)
        category.pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(search_bar, text=ui('ui_0251'), font=label_font).pack(side=tk.LEFT, padx=(0, 4))
        host = tk.Frame(search_bar, width=110, height=23)
        host.pack(side=tk.LEFT)
        query = NativeWinEdit(host, lambda: self._schedule_search_refresh(f'crew:{key}', lambda: self._refresh_crew_search_results(key)), width=110, height=23)
        host.pack_propagate(False)
        category.bind('<<ComboboxSelected>>', lambda _event: self._refresh_crew_search_results(key))

        list_frame = tk.Frame(profile)
        list_frame.grid(row=1, column=1, padx=(0, 4), pady=(0, 4), sticky='nsew')
        list_frame.columnconfigure(0, weight=1)
        tree = ttk.Treeview(list_frame, columns=('id', 'name'), show='headings', height=5, selectmode='browse')
        tree.heading('id', text=ui('ui_0346')); tree.heading('name', text=ui('ui_0062'))
        tree.column('id', width=38, anchor='center', stretch=False); tree.column('name', width=250, anchor='w', stretch=True)
        scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=lambda first, last: self._update_inventory_scrollbar(scroll, first, last))
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree.bind('<<TreeviewSelect>>', lambda _event: self.on_crew_search_selected(key))

        details = ttk.Notebook(page, style='Editor.TNotebook')
        details.grid(row=1, column=0, sticky='nsew', padx=3, pady=(0, 4))
        pages = [ttk.Frame(page) for _ in range(5)]
        for tab, title in zip(pages, PERSON_TAB_TITLES):
            details.add(tab, text=title)
        trees = (
            self._make_officer_tree(pages[0], ('index', 'field', 'value'), PERSON_BASIC_COLUMNS, 7),
            self._make_officer_tree(pages[1], ('index', 'field', 'value'), PERSON_STAT_COLUMNS, 8),
            self._make_officer_tree(pages[2], ('index', 'field', 'value'), PERSON_STAT_COLUMNS, 2),
            self._make_officer_tree(pages[3], ('index', 'field', 'value'), PERSON_LEVEL_COLUMNS, 13),
            self._make_officer_tree(pages[4], ('index', 'field', 'value'), PERSON_LEVEL_COLUMNS, 12),
        )
        self._crew_profiles[key] = {'offset': role_offset, 'name': role_name, 'category': category,
                                    'query': query, 'tree': tree, 'trees': trees,
                                    'face_label': face_label, 'face_photo': None}
        self._refresh_crew_search_results(key)

    def _schedule_search_refresh(self, key, callback, delay=120):
        """입력 중에는 목록 재생성을 묶어 UI 끊김을 줄인다."""
        job_attr = '_search_refresh_jobs'
        jobs = getattr(self, job_attr, None)
        if jobs is None:
            jobs = {}
            setattr(self, job_attr, jobs)
        previous_job = jobs.pop(key, None)
        if previous_job is not None:
            try:
                self.root.after_cancel(previous_job)
            except tk.TclError:
                pass
        def run():
            jobs.pop(key, None)
            callback()
        jobs[key] = self.root.after(delay, run)

    def _refresh_crew_search_results(self, key):
        profile = self._crew_profiles.get(key)
        if profile is None:
            return
        tree = profile['tree']
        query = profile['query'].get().strip().casefold()
        filter_codes = (None, 1, 2, 3)
        category_index = profile['category'].current()
        wanted_hire = filter_codes[category_index] if 0 <= category_index < len(filter_codes) else None
        hire_states = self._character_hire_states()
        tree.delete(*tree.get_children())
        tree.insert('', tk.END, iid='__none__', values=('-', ui('ui_0319')))
        for character_id, name, name_key in self._character_search_index:
            hire_state = hire_states.get(character_id, 0)
            if (wanted_hire is not None and hire_state != wanted_hire) or (query and query not in name_key):
                continue
            tree.insert('', tk.END, iid=str(character_id), values=(f'{character_id:03d}', name))

    def on_crew_search_selected(self, key):
        profile = self._crew_profiles.get(key)
        if profile is None or profile.get('syncing_selection'):
            return
        selection = profile['tree'].selection()
        if selection and selection[0] == '__none__':
            self.clear_role(key)
        elif selection:
            self.assign_role(key, int(selection[0]))

    def _refresh_role_display(self, key):
        """역할별 화면 차이는 유지하고, 역할 데이터 처리는 공통으로 사용한다."""
        if key == 'officer':
            self.refresh_officer_display()
        else:
            self.refresh_crew_display(key)

    def clear_role(self, key):
        """역할 슬롯을 비우고 이전 인물의 기본 위치를 복원한다."""
        profile = self._crew_profiles.get(key)
        if profile is None or not self.file_buffer:
            return
        role_offset = profile['offset']
        previous = struct.unpack_from('<H', self.file_buffer, role_offset)[0]
        # 목록을 다시 그리며 프로그램이 '없음' 행을 선택할 수 있다.
        # 이미 비어 있으면 세이브·상태 문구를 모두 그대로 유지한다.
        if previous == 0xFFFF:
            return
        previous_id = previous - 0x1000 if (previous & 0xFF00) == 0x1000 else None
        struct.pack_into('<H', self.file_buffer, role_offset, 0xFFFF)
        if previous_id is not None:
            self._restore_role_building(previous_id)
        if key == 'officer':
            self._officer_selected_id = None
            self._officer_preview_id = None
        self._refresh_role_display(key)
        self.lbl_status.config(text=ui('ui_0505', profile['name']))

    def assign_role(self, key, character_id):
        """네 역할에 공통으로 적용되는 즉시 지정 처리다.

        한 인물은 한 역할만 맡는다. 다른 역할에 이미 배정된 인물을 선택하면
        기존 역할을 비워 해당 역할로 이동시킨다.
        """
        profile = self._crew_profiles.get(key)
        if profile is None or not self.file_buffer or character_id not in CHARACTER_BY_ID:
            return
        role_offset, role_name = profile['offset'], profile['name']
        previous = struct.unpack_from('<H', self.file_buffer, role_offset)[0]
        previous_id = previous - 0x1000 if (previous & 0xFF00) == 0x1000 else None
        target_code = 0x1000 | character_id
        # 선택 인물이 맡고 있던 기존 역할을 찾아 비운다. 같은 역할은 제외한다.
        moved_from = []
        for other_key, other_profile in self._crew_profiles.items():
            if other_key == key:
                continue
            other_offset = other_profile['offset']
            if struct.unpack_from('<H', self.file_buffer, other_offset)[0] == target_code:
                struct.pack_into('<H', self.file_buffer, other_offset, 0xFFFF)
                moved_from.append(other_key)

        # 로드/목록 갱신으로 같은 역할의 같은 인물이 다시 선택된 경우에는
        # 중복 역할 정리만 하고 새 변경으로 취급하지 않는다.
        if previous == target_code and not moved_from:
            return
        struct.pack_into('<H', self.file_buffer, role_offset, 0x1000 | character_id)
        record_offset = 0x924A + character_id * 0x90
        if record_offset + 0x63 <= len(self.file_buffer):
            self.file_buffer[record_offset + 0x30] = 0xFF
        if previous_id is not None and previous_id != character_id:
            self._restore_role_building(previous_id)
        if key == 'officer':
            self._officer_selected_id = character_id
            self._officer_preview_id = character_id
        elif 'officer' in moved_from:
            self._officer_selected_id = None
            self._officer_preview_id = None
        self._refresh_all_crew_profiles()
        name = CHARACTER_BY_ID[character_id].get('name', character_id)
        if moved_from:
            previous_role_names = ', '.join(self._crew_profiles[moved_key]['name'] for moved_key in moved_from)
            self.lbl_status.config(text=ui('ui_0506', name, previous_role_names, role_name))
        else:
            self.lbl_status.config(text=ui('ui_0507', role_name, name))

    def refresh_crew_display(self, key):
        profile = self._crew_profiles.get(key)
        if profile is None:
            return
        trees = profile['trees']
        clear_rows(*trees)
        profile['face_photo'] = None
        profile['face_label'].config(image='', bg='#222222')
        if not self.file_buffer:
            return
        role_code = struct.unpack_from('<H', self.file_buffer, profile['offset'])[0]
        if role_code == 0xFFFF or (role_code & 0xFF00) != 0x1000:
            if profile['tree'].exists('__none__') and profile['tree'].selection() != ('__none__',):
                profile['syncing_selection'] = True
                profile['tree'].selection_set('__none__')
                self.root.after_idle(lambda p=profile: p.__setitem__('syncing_selection', False))
            return
        character_id = role_code - 0x1000
        record_offset = 0x924A + character_id * 0x90
        character = CHARACTER_BY_ID.get(character_id)
        if character is None or record_offset + 0x90 > len(self.file_buffer):
            return
        item_id = str(character_id)
        if profile['tree'].exists(item_id):
            if profile['tree'].selection() != (item_id,):
                # 로드/새로고침이 만드는 선택은 사용자의 목록 클릭이 아니다.
                profile['syncing_selection'] = True
                profile['tree'].selection_set(item_id)
                self.root.after_idle(lambda p=profile: p.__setitem__('syncing_selection', False))
            profile['tree'].focus(item_id)
            profile['tree'].see(item_id)
        record = self.file_buffer
        image_path = get_sailer_image_path(character_id)
        if image_path:
            photo = get_cached_photo(image_path)
            if photo:
                profile['face_photo'] = photo
                profile['face_label'].config(image=photo)
        age = struct.unpack_from('<b', record, record_offset + 0x5C)[0]
        city_id = record[record_offset + 0x2E]
        building_id = record[record_offset + 0x30]
        hire_state = self._character_hire_state(character_id, character, record_offset)
        name = self._character_record_name(record, record_offset, character.get('name', UI_EMPTY_VALUE))
        basic_rows = ((ui('ui_0062'), name), (ui('ui_0493'), ui('ui_0502', age)),
                      (ui('ui_0491'), NATION_NAMES[int(character.get('nation_id', -1))] if 0 <= int(character.get('nation_id', -1)) < len(NATION_NAMES) else UI_EMPTY_VALUE),
                      (ui('ui_0492'), JOB_NAMES[int(character.get('job_id', -1))] if 0 <= int(character.get('job_id', -1)) < len(JOB_NAMES) else UI_EMPTY_VALUE),
                      (ui('ui_0354'), ui('ui_0498') if city_id == 0xFF else CITY_NAME_BY_ID.get(city_id, UI_EMPTY_VALUE)),
                      (ui('ui_0409'), {4: ui('ui_0412'), 5: ui('ui_0413')}.get(building_id, '-')),
                      (ui('ui_0410'), {1: ui('ui_0403'), 2: ui('ui_0404'), 3: ui('ui_0405')}.get(hire_state, UI_EMPTY_VALUE)))
        for index, row in enumerate(basic_rows): trees[0].insert('', tk.END, values=(index, *row))
        stats = self._character_stat_rows(record, record_offset)
        for index, row in enumerate(stats): trees[1].insert('', tk.END, values=(index, *row))
        trees[2].insert('', tk.END, values=(0, ui('ui_0407'), f"{struct.unpack_from('<H', record, record_offset + 0x26)[0]:,}"))
        trees[2].insert('', tk.END, values=(1, ui('ui_0497'), f"{struct.unpack_from('<H', record, record_offset + 0x2A)[0]:,}"))
        for index, (skill_name, _offset, _description) in enumerate(SKILLS_DATA):
            target, row = (trees[3], index) if index < 13 else (trees[4], index - 13)
            target.insert('', tk.END, values=(row, skill_name, record[record_offset + 0x0B + index]))
        self._schedule_treeview_autofit(*trees)

    def _active_role_character_ids(self, buffer=None):
        """지정한 세이브 버퍼의 네 역할 슬롯에서 고용 중 인물 ID 집합을 만든다."""
        source = self.file_buffer if buffer is None else buffer
        if not source:
            return frozenset()
        return frozenset(
            code - 0x1000
            for role_offset in ROLE_SLOT_OFFSETS
            if len(source) >= role_offset + 2
            for code in (struct.unpack_from('<H', source, role_offset)[0],)
            if (code & 0xFF00) == 0x1000
        )

    def _character_hire_state(self, character_id, character=None, record_offset=None, assigned_ids=None):
        """고용 중은 인물의 상태 바이트가 아니라 실제 역할 슬롯 등록으로 판정한다."""
        if assigned_ids is not None:
            if int(character_id) in assigned_ids:
                return 3
            if character is None:
                character = CHARACTER_BY_ID.get(int(character_id), {})
            default_state = int(character.get('hire_state', 0))
            return default_state if default_state != 3 else 0
        return self._character_hire_states().get(int(character_id), 0)

    def _character_hire_states(self):
        """역할 슬롯 조합별 고용 상태를 캐시해 인물 목록 행마다 다시 계산하지 않는다."""
        assigned_ids = self._active_role_character_ids()
        cache = getattr(self, '_character_hire_state_cache', None)
        if cache is not None and cache[0] == assigned_ids:
            return cache[1]
        states = {
            int(character['id']): (
                3 if int(character['id']) in assigned_ids
                else (state if (state := int(character.get('hire_state', 0))) != 3 else 0)
            )
            for character in CHARACTER_DATA['records']
        }
        self._character_hire_state_cache = (assigned_ids, states)
        return states

    def _refresh_all_crew_profiles(self, reset_filters=False, refresh_lists=False):
        """모든 역할 탭의 목록/상세 화면 갱신을 한곳에서 관리한다."""
        for key, profile in getattr(self, '_crew_profiles', {}).items():
            if reset_filters:
                profile['category'].current(0)
                profile['query'].set('')
            if refresh_lists:
                self._refresh_crew_search_results(key)
            self._refresh_role_display(key)

    def build_officer_profile(self):
        """부관 슬롯(세이브 0xA5)의 인물 정보를 표시·변경하는 패널."""
        page = self.profile_page_officer
        label_font = ('Malgun Gothic', 9)
        value_font = ('Malgun Gothic', 9)

        # 상단 검색·인물 목록과 하단 상세 탭의 높이 비율은 부인 탭과 같다.
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=2)
        page.rowconfigure(1, weight=3)
        profile = tk.Frame(page)
        profile.grid(row=0, column=0, sticky='nsew', padx=3, pady=4)
        # 주인공·부인 초상화와 같은 외곽 크기(내부 80×96)를 사용한다.
        photo_box = tk.Frame(profile, width=84, height=100, bg='#222222', relief='ridge', bd=2)
        photo_box.pack_propagate(False)
        photo_box.place(x=0, y=4)
        self.lbl_officer_face = tk.Label(photo_box, bg='#222222')
        self.lbl_officer_face.pack(fill=tk.BOTH, expand=True)
        self.officer_face_photo = None

        profile.grid_columnconfigure(0, minsize=92)
        profile.grid_columnconfigure(1, weight=1, minsize=0)
        profile.grid_rowconfigure(3, weight=1)
        self._officer_character_ids = [int(character['id']) for character in CHARACTER_DATA['records']]
        self._officer_selected_id = None
        self._officer_character_names = [character.get('name') or UI_EMPTY_VALUE for character in CHARACTER_DATA['records']]
        search_bar = tk.Frame(profile)
        search_bar.grid(row=0, column=1, columnspan=3, padx=(0, 4), pady=(4, 2), sticky='w')
        tk.Label(search_bar, text=ui('ui_0400'), font=label_font, anchor='w').pack(side=tk.LEFT, padx=(0, 4))
        self._officer_hire_filter_codes = (None, 1, 2, 3)
        self.cbo_officer_category = ttk.Combobox(search_bar, values=[ui('ui_0364'), ui('ui_0403'), ui('ui_0404'), ui('ui_0405')],
                                                 state='readonly', width=8, font=value_font)
        self.cbo_officer_category.current(0)
        self.cbo_officer_category.pack(side=tk.LEFT, padx=(0, 8))
        self.cbo_officer_category.bind('<<ComboboxSelected>>', lambda _event: self._refresh_officer_search_results())
        tk.Label(search_bar, text=ui('ui_0251'), font=label_font, anchor='w').pack(side=tk.LEFT, padx=(0, 4))
        officer_search_host = tk.Frame(search_bar, width=110, height=23)
        officer_search_host.pack(side=tk.LEFT)
        self.cbo_officer_name = NativeWinEdit(officer_search_host, lambda: self._schedule_search_refresh('officer', self._refresh_officer_search_results), width=110, height=23)
        self.cbo_officer_name.set('')
        officer_search_frame = tk.Frame(profile)
        officer_search_frame.grid(row=1, column=1, columnspan=3, rowspan=3, padx=(0, 4), pady=(0, 4), sticky='nsew')
        self.tree_officer_search = ttk.Treeview(officer_search_frame, columns=('id', 'name'), show='headings', height=5, selectmode='browse')
        self.tree_officer_search.heading('id', text='No')
        self.tree_officer_search.heading('name', text=ui('ui_0062'))
        self.tree_officer_search.column('id', width=38, anchor='center', stretch=False)
        self.tree_officer_search.column('name', width=110, anchor='w', stretch=True)
        officer_search_scroll = ttk.Scrollbar(officer_search_frame, orient=tk.VERTICAL, command=self.tree_officer_search.yview)
        self.tree_officer_search.configure(yscrollcommand=lambda first, last: self._update_inventory_scrollbar(officer_search_scroll, first, last))
        self.tree_officer_search.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree_officer_search.bind('<<TreeviewSelect>>', self.on_officer_search_selected)
        self._refresh_officer_search_results()

        self.officer_details = ttk.Notebook(page, style='Editor.TNotebook')
        self.officer_page_basic = ttk.Frame(page)
        self.officer_page_stats = ttk.Frame(page)
        self.officer_page_fame = ttk.Frame(page)
        self.officer_page_tech = ttk.Frame(page)
        self.officer_page_lang = ttk.Frame(page)
        for tab, title in zip((self.officer_page_basic, self.officer_page_stats, self.officer_page_fame,
                               self.officer_page_tech, self.officer_page_lang), PERSON_TAB_TITLES):
            self.officer_details.add(tab, text=title)
        self.officer_details.grid(row=1, column=0, sticky='nsew', padx=3, pady=(0, 4))

        self.tree_officer_basic = self._make_officer_tree(
            self.officer_page_basic, ('index', 'field', 'value'),
            PERSON_BASIC_COLUMNS, 7)
        self.tree_officer_stats = self._make_officer_tree(
            self.officer_page_stats, ('index', 'field', 'value'),
            PERSON_STAT_COLUMNS, 8)
        self.tree_officer_fame = self._make_officer_tree(
            self.officer_page_fame, ('index', 'field', 'value'),
            PERSON_FAME_COLUMNS, 2)
        self.tree_officer_tech = self._make_officer_tree(
            self.officer_page_tech, ('index', 'field', 'level'),
            PERSON_LEVEL_COLUMNS, 8)
        self.tree_officer_lang = self._make_officer_tree(
            self.officer_page_lang, ('index', 'field', 'level'),
            PERSON_LEVEL_COLUMNS, 8)

    @staticmethod
    def _make_officer_tree(parent, columns, definitions, height, *, frame_padx=8, frame_pady=6,
                           pack_padx=0, pack_pady=0):
        frame = tk.Frame(parent, padx=frame_padx, pady=frame_pady)
        frame.pack(fill=tk.BOTH, expand=True, padx=pack_padx, pady=pack_pady)
        tree = ttk.Treeview(frame, columns=columns, show='headings', height=height, selectmode='none')
        for column, (title, width, anchor, stretch) in zip(columns, definitions):
            tree.heading(column, text=title)
            tree.column(column, width=width, anchor=anchor, stretch=stretch)
        tree.pack(fill=tk.BOTH, expand=True)
        return tree




    def _refresh_officer_search_results(self):
        """전체 인물 목록을 유지하고 검색어와 일치하는 인물로 포커스를 옮긴다."""
        tree = getattr(self, 'tree_officer_search', None)
        if tree is None:
            return
        query = self.cbo_officer_name.get().strip().casefold() if hasattr(self, 'cbo_officer_name') else ''
        selected_hire = None
        if hasattr(self, 'cbo_officer_category'):
            category_index = self.cbo_officer_category.current()
            if 0 <= category_index < len(self._officer_hire_filter_codes):
                selected_hire = self._officer_hire_filter_codes[category_index]
        tree.delete(*tree.get_children())
        tree.insert('', tk.END, iid='__none__', values=('-', ui('ui_0319')))
        if query == ui('ui_0319').casefold():
            query = ''
        hire_states = self._character_hire_states()
        for character_id, name, name_key in self._character_search_index:
            hire_state = hire_states.get(character_id, 0)
            if selected_hire is not None and hire_state != selected_hire:
                continue
            if query and query not in name_key:
                continue
            tree.insert('', tk.END, iid=str(character_id),
                        values=(f'{character_id:03d}', name))

    def on_officer_search_selected(self, _event=None):
        tree = getattr(self, 'tree_officer_search', None)
        selection = tree.selection() if tree is not None else ()
        if not selection:
            return
        if selection[0] == '__none__':
            self.clear_role('officer')
            return
        character = CHARACTER_BY_ID.get(int(selection[0]))
        if character is None:
            return
        self.assign_role('officer', int(character['id']))


    def _restore_role_building(self, character_id):
        """모든 역할에서 해제된 인물의 건물값을 로드 당시 값으로 되돌린다."""
        character = CHARACTER_BY_ID.get(character_id)
        record_offset = 0x924A + character_id * 0x90
        if not character or record_offset + 0x63 > len(self.file_buffer):
            return
        # 다른 승무원 역할에 남아 있으면 건물값을 계속 함대 소속으로 유지한다.
        for role_offset in ROLE_SLOT_OFFSETS:
            role_code = struct.unpack_from('<H', self.file_buffer, role_offset)[0]
            if role_code == (0x1000 | character_id):
                return
        original = getattr(self, 'person_original_buffer', None)
        if original is not None and record_offset + 0x31 <= len(original):
            self.file_buffer[record_offset + 0x30] = original[record_offset + 0x30]
        else:
            # 세이브 원본이 아직 없는 초기화 경로에서만 정적 기본값을 사용한다.
            self.file_buffer[record_offset + 0x30] = int(character.get('building_id', 0xFF)) & 0xFF


    def update_player_face_display(self):
        """주인공 얼굴 초상화 라벨 갱신"""
        if not self.file_buffer or self.player_face_id is None:
            self.lbl_player_face.config(image='')
            self._update_player_restore_state()
            return
        else:
            img_p = get_face_image_path('male', self.player_face_id)
            if img_p and os.path.exists(img_p):
                    photo = get_cached_photo(img_p)
                    if photo:
                        self.player_face_photo = photo
                        self.lbl_player_face.config(image=self.player_face_photo)
        self._update_player_restore_state()

    def refresh_officer_display(self, preview_character_id=None):
        """세이브의 부관 참조(0xA5)를 읽어 읽기 전용 인물 탭을 갱신한다."""
        trees = tuple(getattr(self, name, None) for name in (
            'tree_officer_basic', 'tree_officer_stats', 'tree_officer_fame', 'tree_officer_tech', 'tree_officer_lang'))
        clear_rows(*trees)
        empty_labels = ('lbl_officer_nation', 'lbl_officer_job',
                        'lbl_officer_age', 'lbl_officer_city', 'lbl_officer_hire',
                        'lbl_officer_appearance')
        for name in empty_labels:
            label = getattr(self, name, None)
            if label is not None:
                label.config(text=UI_EMPTY_VALUE)
        self.officer_face_photo = None
        if hasattr(self, 'lbl_officer_face'):
            self.lbl_officer_face.config(image='', bg='#222222')

        if hasattr(self, 'cbo_officer_name'):
            self.cbo_officer_name.set_enabled(False)

        if not self.file_buffer or len(self.file_buffer) < 0xA7:
            return
        role_code = struct.unpack_from('<H', self.file_buffer, 0xA5)[0]
        self.cbo_officer_name.set_enabled(True)
        is_preview = preview_character_id is not None
        if preview_character_id is None:
            preview_character_id = getattr(self, '_officer_preview_id', None)
        if preview_character_id is None:
            if role_code == 0xFFFF or role_code < 0x1000:
                search_tree = getattr(self, 'tree_officer_search', None)
                if search_tree is not None and search_tree.exists('__none__'):
                    if search_tree.selection() != ('__none__',):
                        search_tree.selection_set('__none__')
                    search_tree.focus('__none__')
                    search_tree.see('__none__')
                return
            character_id = role_code - 0x1000
        else:
            character_id = int(preview_character_id)
        record_offset = 0x924A + character_id * 0x90
        if character_id < 0 or record_offset + 0x90 > len(self.file_buffer):
            return
        self._officer_preview_id = character_id
        search_tree = getattr(self, 'tree_officer_search', None)
        # 경쟁자 상세를 보기 위한 미리보기는 부관 목록의 선택을 바꾸지 않는다.
        # 해당 목록의 선택 이벤트는 곧바로 부관 배정을 수행하므로, 여기서 건드리면
        # 경쟁자를 눌렀을 뿐인데 부관이 변경되는 부작용이 생긴다.
        if not is_preview and search_tree is not None and search_tree.exists(str(character_id)):
            if search_tree.selection() != (str(character_id),):
                search_tree.selection_set(str(character_id))
            search_tree.focus(str(character_id))
            search_tree.see(str(character_id))

        record = self.file_buffer
        character = CHARACTER_BY_ID.get(character_id, {})
        name = self._character_record_name(record, record_offset, character.get('name', UI_EMPTY_VALUE))
        nation_id = int(character.get('nation_id', -1))
        job_id = int(character.get('job_id', -1))
        age = struct.unpack_from('<b', record, record_offset + 0x5C)[0]
        # 국적·직업만 정적 표의 ID 매핑을 쓰며, 그 밖의 기본 정보는 세이브 레코드와
        # 역할 슬롯에서 읽는다.
        is_current_officer = not is_preview and role_code == (0x1000 | character_id)
        city_id = record[record_offset + 0x2E]
        building_id = record[record_offset + 0x30]
        hire_state = 3 if is_current_officer else record[record_offset + 0x62]
        city_name = ui('ui_0498') if city_id == 0xFF else CITY_NAME_BY_ID.get(city_id, UI_EMPTY_VALUE)
        building_name = {4: ui('ui_0412'), 5: ui('ui_0413')}.get(building_id, '')
        hire_text = {1: ui('ui_0403'), 2: ui('ui_0404'), 3: ui('ui_0405')}.get(hire_state, UI_EMPTY_VALUE)
        if not is_preview:
            self._officer_selected_id = character_id
        basic_rows = (
            (ui('ui_0062'), name),
            (ui('ui_0493'), ui('ui_0502', age)),
            (ui('ui_0491'), NATION_NAMES[nation_id] if 0 <= nation_id < len(NATION_NAMES) else UI_EMPTY_VALUE),
            (ui('ui_0492'), JOB_NAMES[job_id] if 0 <= job_id < len(JOB_NAMES) else UI_EMPTY_VALUE),
            (ui('ui_0354'), city_name),
            (ui('ui_0409'), building_name or '-'),
            (ui('ui_0410'), hire_text),
        )
        for index, (field, value) in enumerate(basic_rows):
            self.tree_officer_basic.insert('', tk.END, values=(index, field, value))

        image_path = get_sailer_image_path(character_id)
        if image_path:
            photo = get_cached_photo(image_path)
            if photo:
                self.officer_face_photo = photo
                self.lbl_officer_face.config(image=photo)

        stat_rows = self._character_stat_rows(record, record_offset)
        for index, (stat_name, value) in enumerate(stat_rows):
            self.tree_officer_stats.insert('', tk.END, values=(index, stat_name, value))
        fame = struct.unpack_from('<H', record, record_offset + 0x26)[0]
        infamy = struct.unpack_from('<H', record, record_offset + 0x2A)[0]
        self.tree_officer_fame.insert('', tk.END, values=(0, ui('ui_0407'), f'{fame:,}'))
        self.tree_officer_fame.insert('', tk.END, values=(1, ui('ui_0497'), f'{infamy:,}'))
        for skill_index, (skill_name, _offset, _description) in enumerate(SKILLS_DATA):
            target_tree = self.tree_officer_tech if skill_index < 13 else self.tree_officer_lang
            row_number = skill_index if skill_index < 13 else skill_index - 13
            level = record[record_offset + 0x0B + skill_index]
            target_tree.insert('', tk.END, values=(row_number, skill_name, level))
        self._schedule_treeview_autofit(*trees)

    def _get_birth_date(self):
        return (self.spn_birth_y.get(), self.spn_birth_m.get(), self.spn_birth_d.get())

    def _get_game_date(self):
        return (self.spn_game_y.get(), self.spn_game_m.get(), self.spn_game_d.get())

    def _set_birth_date_from_calendar(self, year, month, day):
        self.set_spin_val(self.spn_birth_y, year)
        self.set_spin_val(self.spn_birth_m, month)
        self.set_spin_val(self.spn_birth_d, day)
        self._on_birth_date_changed()

    def _set_game_date_from_calendar(self, year, month, day):
        self.set_spin_val(self.spn_game_y, year)
        self.set_spin_val(self.spn_game_m, month)
        self.set_spin_val(self.spn_game_d, day)
        self._on_game_date_changed()
        self._schedule_city_shipyard_refresh()

    def _on_game_date_changed(self, _event=None):
        """현재 연도를 기준으로 계산되는 부관 나이를 즉시 갱신한다."""
        if getattr(self, '_is_loading_save', False):
            return
        self._update_player_restore_state()
        pending = getattr(self, '_officer_age_refresh_job', None)
        if pending is not None:
            try:
                self.root.after_cancel(pending)
            except tk.TclError:
                pass
        self._officer_age_refresh_job = self.root.after_idle(self._refresh_officer_age_for_game_date)

    def _refresh_officer_age_for_game_date(self):
        self._officer_age_refresh_job = None
        for key in getattr(self, '_crew_profiles', {}):
            self._refresh_role_age_rows(key)
        self._refresh_wife_fortune_state()
        # 통합 인물 화면도 저장 당시 나이에 현재 연도 차이를 적용하므로,
        # 선택된 인물의 기본 정보를 날짜 변경 직후 다시 채운다.
        tree = getattr(self, 'tree_person_list', None)
        if (tree is not None and
                getattr(self, '_person_active_type', None) in self._crew_profiles):
            selection = tree.selection()
            if selection:
                self._refresh_person_details(selection[0])

    def _refresh_role_age_rows(self, key):
        """날짜 변경 시 변하는 나이·등장 행만 갱신해 역할 탭 전체 재생성을 피한다."""
        profile = self._crew_profiles.get(key)
        if profile is None or not self.file_buffer:
            return
        role_code = struct.unpack_from('<H', self.file_buffer, profile['offset'])[0]
        if role_code == 0xFFFF or (role_code & 0xFF00) != 0x1000:
            return
        character = CHARACTER_BY_ID.get(role_code - 0x1000)
        if character is None:
            return
        try:
            age = int(character['age_at_1480']) + (int(self.spn_game_y.get()) - 1480)
        except (KeyError, TypeError, ValueError, tk.TclError):
            return
        if key == 'officer':
            tree = getattr(self, 'tree_officer_basic', None)
        else:
            tree = profile['trees'][0]
        if tree is None:
            return
        rows = tree.get_children()
        if len(rows) < 8:
            # 아직 상세 표가 구성되지 않은 경우에만 전체 표시를 갱신한다.
            self._refresh_role_display(key)
            return
        tree.item(rows[1], values=(1, ui('ui_0493'), ui('ui_0502', age) if age >= 0 else ui('ui_0466')))
        tree.item(rows[7], values=(7, ui('ui_0411'), ui('ui_0466') if age < 18 else ui('ui_0500') if age > 60 else ui('ui_0499')))

    def _refresh_birth_zodiac(self):
        """주인공 생일 입력값에 맞춰 별자리 표시를 갱신한다."""
        label = getattr(self, 'lbl_birth_zodiac', None)
        if label is None:
            return
        try:
            zodiac = get_birth_zodiac_name(self.spn_birth_m.get(), self.spn_birth_d.get())
        except (AttributeError, tk.TclError):
            zodiac = ''
        label.config(text=zodiac)

    def _on_birth_date_changed(self, _event=None):
        """생일 변경 직후 별자리와 운명의 반려자 판정을 함께 갱신한다."""
        if getattr(self, '_is_loading_save', False):
            return
        self._refresh_birth_zodiac()
        self._refresh_wife_fortune_state()
        self._update_player_restore_state()

    def _get_wife_fortune_face_code(self):
        """현재 주인공의 나이를 반영한 운명의 반려자 비교 코드를 구한다."""
        try:
            if self.player_face_id is None:
                return None
            age = get_player_age(
                int(self.spn_game_y.get()), int(self.spn_game_m.get()), int(self.spn_game_d.get()),
                int(self.spn_birth_y.get()), int(self.spn_birth_m.get()), int(self.spn_birth_d.get()),
            )
            return get_fortune_face_code(self.player_face_id, age)
        except (TypeError, ValueError, tk.TclError):
            return None

    def _refresh_wife_fortune_state(self):
        """날짜 변경 시 반려자 문구·행 색상만 바꿔 초상화와 목록 재생성을 피한다."""
        fortune_face_code = self._get_wife_fortune_face_code()
        barmaid = self._wife_from_combo_text()
        if barmaid is None:
            fortune_text, fortune_color = '-', 'gray'
        elif fortune_face_code is None:
            fortune_text, fortune_color = UI_EMPTY_VALUE, 'gray'
        elif is_fortune_spouse(barmaid, fortune_face_code):
            fortune_text, fortune_color = ui('ui_0272'), '#D81B60'
        else:
            fortune_text, fortune_color = ui('ui_0277'), '#666666'
        if hasattr(self, 'lbl_wife_compat'):
            self.lbl_wife_compat.config(text=fortune_text, fg=fortune_color)

        # 검색 결과를 다시 삽입하지 않고, 이미 보이는 여급 행의 강조만 갱신한다.
        tree = getattr(self, 'tree_wife_search', None)
        if tree is not None:
            for item_id in tree.get_children():
                if item_id == '__none__':
                    continue
                candidate = BARMAID_BY_ID.get(int(item_id))
                tags = ('fortune_spouse',) if candidate is not None and fortune_face_code is not None and is_fortune_spouse(candidate, fortune_face_code) else ()
                tree.item(item_id, tags=tags)

        # 하단 신상 목록 중 운명의 반려자 행만 바꾼다.
        language_tree = getattr(self, 'tree_wife_languages', None)
        if language_tree is not None:
            rows = language_tree.get_children()
            if len(rows) >= 6:
                language_tree.item(rows[5], values=(5, ui('ui_0061'), fortune_text),
                                   tags=('fortune_spouse',) if fortune_text == ui('ui_0272') else ())

        # 통합 인물 화면도 현재 보이는 여급 목록과 상세 행만 갱신한다. 전체 목록을
        # 다시 만들면 날짜 스핀을 돌릴 때 선택·스크롤이 흔들리므로 태그만 바꾼다.
        if getattr(self, '_person_active_type', None) == 'spouse':
            person_tree = getattr(self, 'tree_person_list', None)
            if person_tree is not None:
                for item_id in person_tree.get_children():
                    candidate = BARMAID_BY_ID.get(int(item_id))
                    tags = tuple(tag for tag in person_tree.item(item_id, 'tags') if tag != 'fortune_spouse')
                    if candidate is not None and fortune_face_code is not None and is_fortune_spouse(candidate, fortune_face_code):
                        tags += ('fortune_spouse',)
                    person_tree.item(item_id, tags=tags)
            detail_tree = getattr(self, 'tree_person_details', None)
            if detail_tree is not None:
                for item_id in detail_tree.get_children():
                    values = detail_tree.item(item_id, 'values')
                    if len(values) >= 3 and values[1] == ui('ui_0061'):
                        tags = tuple(tag for tag in detail_tree.item(item_id, 'tags') if tag != 'fortune_spouse')
                        if fortune_text == ui('ui_0272'):
                            tags += ('fortune_spouse',)
                        detail_tree.item(item_id, values=(values[0], values[1], fortune_text), tags=tags)
                        break

    def _refresh_wife_languages(self, barmaid=None):
        """선택한 부인의 신상정보와 전수 언어를 하단 목록에 표시한다."""
        tree = getattr(self, 'tree_wife_languages', None)
        if tree is None:
            return
        tree.delete(*tree.get_children())
        if barmaid is None:
            for index, field in enumerate((ui('ui_0354'), ui('ui_0411'), ui('ui_0065'), ui('ui_0066'),
                                           ui('ui_0501'), ui('ui_0061'), ui('ui_0068'))):
                tree.insert('', tk.END, values=(index, field, '-'))
            return
        flags = int(barmaid.get('language_flags', 0))
        languages = [name for bit, name in enumerate(LANGUAGE_NAMES) if flags & (1 << bit)]
        fortune = self.lbl_wife_compat.cget('text') if hasattr(self, 'lbl_wife_compat') else '-'
        rows = (
            (ui('ui_0354'), get_barmaid_city_name(barmaid)),
            (ui('ui_0411'), f"{barmaid['year']}{ui('ui_0233')}"),
            (ui('ui_0065'), get_barmaid_zodiac_name(barmaid)),
            (ui('ui_0066'), get_barmaid_blood_name(barmaid)),
            (ui('ui_0501'), get_barmaid_personality(barmaid)),
            (ui('ui_0061'), fortune or '-'),
            (ui('ui_0068'), ', '.join(languages) if languages else '-'),
        )
        for index, (field, value) in enumerate(rows):
            tags = ('fortune_spouse',) if field == ui('ui_0061') and value == ui('ui_0272') else ()
            tree.insert('', tk.END, values=(index, field, value), tags=tags)

    def _set_wife_detail_fields_visible(self, visible):
        """신상정보는 하단 목록으로 옮겼으므로 상단의 기존 라벨은 숨긴다."""
        widgets = (
            self.lbl_wife_city_title, self.lbl_wife_city,
            self.lbl_wife_year_title, self.lbl_wife_year,
            self.lbl_wife_zodiac_title, self.lbl_wife_zodiac,
            self.lbl_wife_blood_title, self.lbl_wife_blood,
            self.lbl_wife_personality_title, self.lbl_wife_personality,
            self.lbl_wife_fortune_title, self.lbl_wife_compat,
        )
        for widget in widgets:
            widget.grid_remove()

    def update_wife_display(self):
        """아내(배우자) 정보 및 초상화 라벨 갱신"""
        self._refresh_birth_zodiac()
        if not self.file_buffer:
            self._set_wife_detail_fields_visible(True)
            self.wife_face_photo = None
            self.wife_face_box.config(bg='#000000')
            self.lbl_wife_face.config(image='', text='', bg='#000000')
            self.wife_face_box.place(x=0, y=4)
            self.lbl_wife_city.config(text='-')
            self.lbl_wife_year.config(text='-')
            self.lbl_wife_zodiac.config(text='-')
            self.lbl_wife_blood.config(text='-')
            self.lbl_wife_personality.config(text='-')
            self._refresh_wife_languages()
            if hasattr(self, 'lbl_wife_compat'):
                self.lbl_wife_compat.config(text='-', fg='gray')
            return None
        else:
            fortune_face_code = None
            try:
                if self.player_face_id is not None:
                    game_y = int(self.spn_game_y.get())
                    game_m = int(self.spn_game_m.get())
                    game_d = int(self.spn_game_d.get())
                    birth_y = int(self.spn_birth_y.get())
                    birth_m = int(self.spn_birth_m.get())
                    birth_d = int(self.spn_birth_d.get())
                    age = get_player_age(game_y, game_m, game_d, birth_y, birth_m, birth_d)
                    fortune_face_code = get_fortune_face_code(self.player_face_id, age)
            except Exception:
                pass
            b = self._wife_from_combo_text()
            if b is None:
                self._set_wife_detail_fields_visible(True)
                self.wife_face_photo = None
                self.unmarried_photo = None
                self.wife_face_box.config(bg='#000000')
                self.lbl_wife_face.config(image='', text='', bg='#000000')
                self.wife_face_box.place(x=0, y=4)
                self.lbl_wife_city.config(text='-')
                self.lbl_wife_year.config(text='-')
                self.lbl_wife_zodiac.config(text='-')
                self.lbl_wife_blood.config(text='-')
                self.lbl_wife_personality.config(text='-')
                self._refresh_wife_languages()
                if hasattr(self, 'lbl_wife_compat'):
                    self.lbl_wife_compat.config(text='-', fg='gray')
            else:
                self._set_wife_detail_fields_visible(True)
                self.wife_face_box.place(x=0, y=4)
                self.lbl_wife_city.config(text=get_barmaid_city_name(b))
                self.lbl_wife_year.config(text=f"{b['year']}{ui('ui_0233')}")
                self.lbl_wife_zodiac.config(text=get_barmaid_zodiac_name(b))
                self.lbl_wife_blood.config(text=get_barmaid_blood_name(b))
                self.lbl_wife_personality.config(text=get_barmaid_personality(b))
                if hasattr(self, 'lbl_wife_compat'):
                    if fortune_face_code is not None:
                        if is_fortune_spouse(b, fortune_face_code):
                            self.lbl_wife_compat.config(text=ui('ui_0272'), fg='#D81B60')
                        else:
                            self.lbl_wife_compat.config(text=ui('ui_0277'), fg='#666666')
                    else:
                        self.lbl_wife_compat.config(text=UI_EMPTY_VALUE, fg='gray')
                self._refresh_wife_languages(b)
                img_p = get_barmaid_image_path(b['id'])
                if img_p and os.path.exists(img_p):
                        photo = get_cached_photo(img_p)
                        if photo:
                            self.wife_face_photo = photo
                            self.lbl_wife_face.config(image=self.wife_face_photo)
                            return
                # 전용 여급 이미지가 없으면 이전 초상화 대신 검은 화면을 표시한다.
                self.wife_face_photo = None
                self.wife_face_box.config(bg='#000000')
                self.lbl_wife_face.config(image='', text='', bg='#000000')

    def _show_wife_fortune_tooltip(self, event):
        if getattr(self, '_wife_fortune_tooltip', None) is not None:
            return
        tooltip = tk.Toplevel(self.root)
        tooltip.wm_overrideredirect(True)
        tooltip.attributes('-topmost', True)
        tk.Label(
            tooltip, text=ui('ui_0381'), justify='left', anchor='w',
            bg='#FFF8D6', fg='#333333', relief='solid', borderwidth=1,
            font=('Malgun Gothic', 9), padx=8, pady=6,
        ).pack()
        tooltip.geometry(f'+{event.x_root + 16}+{event.y_root + 18}')
        self._wife_fortune_tooltip = tooltip

    def _hide_wife_fortune_tooltip(self, _event=None):
        tooltip = getattr(self, '_wife_fortune_tooltip', None)
        self._wife_fortune_tooltip = None
        if tooltip is not None:
            try:
                tooltip.destroy()
            except tk.TclError:
                pass

    def _wife_from_combo_text(self, text=None):
        """콤보박스에 표시된 이름으로 여급 데이터를 찾는다."""
        if text is None and getattr(self, '_wife_selected_id', None) is not None:
            return BARMAID_BY_ID.get(self._wife_selected_id)
        if text is None:
            text = self.cbo_wife.get() if hasattr(self, 'cbo_wife') else ''
        name = str(text).strip()
        return BARMAID_BY_NAME.get(name)

    def _set_wife_combo(self, barmaid_id=None):
        """여급 ID를 이름 입력칸 표시로 변환한다."""
        barmaid = BARMAID_BY_ID.get(barmaid_id)
        self._wife_selected_id = barmaid['id'] if barmaid else None
        self.cbo_wife.set('')
        self._refresh_wife_search_results()
        tree = getattr(self, 'tree_wife_search', None)
        if tree is not None:
            if barmaid is None:
                if tree.exists('__none__'):
                    tree.selection_set('__none__')
                    tree.focus('__none__')
                    tree.see('__none__')
                else:
                    tree.selection_remove(*tree.selection())
            else:
                item_id = str(barmaid['id'])
                tree.selection_set(item_id)
                tree.focus(item_id)
                tree.see(item_id)

    def _focus_loaded_wife_in_list(self):
        """로드가 끝난 뒤 세이브의 배우자 행을 목록에서 다시 선택한다."""
        tree = getattr(self, 'tree_wife_search', None)
        if tree is None or not self.file_buffer or len(self.file_buffer) < 175:
            return
        spouse_code = struct.unpack_from('<H', self.file_buffer, 173)[0]
        if (spouse_code & 0xFF00) != 0x2000:
            if tree.exists('__none__'):
                tree.selection_set('__none__')
                tree.focus('__none__')
                tree.see('__none__')
            return
        item_id = str(spouse_code & 0x7F)
        if not tree.exists(item_id):
            self._refresh_wife_search_results()
        if tree.exists(item_id):
            tree.selection_set(item_id)
            tree.focus(item_id)
            tree.see(item_id)



    def _refresh_wife_search_results(self):
        """여급 전체 목록을 유지하고, 검색어와 일치하는 행으로 포커스를 옮긴다."""
        tree = getattr(self, 'tree_wife_search', None)
        if tree is None:
            return
        query = self.cbo_wife.get().strip().casefold() if hasattr(self, 'cbo_wife') else ''
        fortune_face_code = None
        try:
            if self.player_face_id is not None:
                age = get_player_age(
                    int(self.spn_game_y.get()), int(self.spn_game_m.get()), int(self.spn_game_d.get()),
                    int(self.spn_birth_y.get()), int(self.spn_birth_m.get()), int(self.spn_birth_d.get()),
                )
                fortune_face_code = get_fortune_face_code(self.player_face_id, age)
        except (TypeError, ValueError, tk.TclError):
            pass
        tree.delete(*tree.get_children())
        tree.insert('', tk.END, iid='__none__', values=('-', ui('ui_0319')))
        if query == ui('ui_0319').casefold():
            query = ''
        for barmaid in BARMAID_DATABASE:
            if query and query not in barmaid['name'].casefold():
                continue
            tags = ('fortune_spouse',) if fortune_face_code is not None and is_fortune_spouse(barmaid, fortune_face_code) else ()
            tree.insert('', tk.END, iid=str(barmaid['id']), values=(f"{barmaid['id']:03d}", barmaid['name']), tags=tags)

    def on_wife_search_selected(self, _event=None):
        tree = getattr(self, 'tree_wife_search', None)
        selection = tree.selection() if tree is not None else ()
        if not selection:
            return
        previous_id = getattr(self, '_wife_selected_id', None)
        if selection[0] == '__none__':
            self._wife_selected_id = None
            self.update_wife_display()
            # 파일 로드·목록 재구성도 같은 선택 이벤트를 발생시킨다.
            # 실제 배우자가 있던 상태에서 사용자가 없음 행으로 바꾼 경우만 알린다.
            if previous_id is not None and not getattr(self, '_is_loading_save', False):
                self.lbl_status.config(text=ui('ui_0415'))
            return
        barmaid = BARMAID_BY_ID.get(int(selection[0]))
        if barmaid is None:
            return
        self._wife_selected_id = barmaid['id']
        self.update_wife_display()
        if previous_id != barmaid['id'] and not getattr(self, '_is_loading_save', False):
            self.lbl_status.config(text=ui('ui_0416', barmaid['name']))


    def open_player_face_picker(self):
        # ***<module>.CDS3SaveEditorApp.open_player_face_picker: Failure: Different bytecode
        if not self.file_buffer:
            messagebox.showinfo(ui('ui_0103'), ui('ui_0117'))
            return
        else:
            def on_pick(fid):
                self.player_face_id = fid
                struct.pack_into('<H', self.file_buffer, 133, fid)
                self.update_player_face_display()
                self.update_wife_display()
            FacePickerModal(
                self.root, ui('ui_0371'), gender='male',
                current_face_id=self.player_face_id if self.player_face_id is not None else 0,
                on_select_callback=on_pick, max_faces=16,
            )

    def _active_sponsor_contract(self):
        """현재 세이브의 계약 중 스폰서와 연결된 발견물 후보를 읽는다."""
        if not self.file_buffer:
            return None
        sponsor_id = None
        sponsor = None
        for sponsor_id, candidate in SPONSOR_BY_ID.items():
            offset = SPONSOR_SAVE_TABLE_OFFSET + sponsor_id * SPONSOR_SAVE_RECORD_SIZE
            if offset + 12 <= len(self.file_buffer) and struct.unpack_from('<I', self.file_buffer, offset + 8)[0] == SPONSOR_CONTRACT_ACTIVE_STATE:
                sponsor = candidate
                break
        if sponsor is None:
            return None
        # 계약 중 힌트는 획득(bit0)과 계약 연결(bit2)이 함께 설정된다.
        # 게임은 동시에 하나의 스폰서 계약만 허용하므로 첫 발견물 후보를 표시한다.
        contract_hint_ids = {
            hint_id for hint_id, offset in enumerate(HINT_STATE_OFFSETS)
            if 0 <= offset < len(self.file_buffer) and (self.file_buffer[offset] & 0x05) == 0x05
        }
        discovery = next((item for item in self.discovery_db
                          if int(item.get('hint_id', -1)) in contract_hint_ids), None)
        return sponsor_id, sponsor, discovery

    def _refresh_sponsor_contract_display(self):
        """계약 정보 행은 항상 표시하고, 계약 여부에 따라 입력만 전환한다."""
        contract = self._active_sponsor_contract()
        line = getattr(self, 'sponsor_contract_line', None)
        if contract is None:
            if line is not None:
                line.grid()
            self.lbl_sponsor_contract.config(text=UI_EMPTY_VALUE)
            self.sponsor_remaining_days_var.set('')
            remaining_line = getattr(self, 'sponsor_remaining_line', None)
            if remaining_line is not None:
                remaining_line.grid_remove()
            return
        sponsor_id, sponsor, discovery = contract
        discovery_name = discovery['name'] if discovery is not None else UI_EMPTY_VALUE
        self.lbl_sponsor_contract.config(text=f"{sponsor['name']} ({discovery_name})")
        offset = SPONSOR_SAVE_TABLE_OFFSET + sponsor_id * SPONSOR_SAVE_RECORD_SIZE
        self.sponsor_remaining_days_var.set(str(struct.unpack_from('<H', self.file_buffer, offset + 0x0E)[0]))
        self.spn_sponsor_remaining_days.configure(state='normal')
        if line is not None:
            line.grid()
        remaining_line = getattr(self, 'sponsor_remaining_line', None)
        if remaining_line is not None:
            remaining_line.grid()

    def _apply_sponsor_remaining_days(self, _event=None):
        """계약 중 스폰서의 +0x0E(남은 일수)를 입력값으로 갱신한다."""
        contract = self._active_sponsor_contract()
        if contract is None:
            return
        try:
            days = max(0, min(0xFFFF, int(self.sponsor_remaining_days_var.get())))
        except (TypeError, ValueError, tk.TclError):
            self._refresh_sponsor_contract_display()
            return
        sponsor_id, _sponsor, _discovery = contract
        offset = SPONSOR_SAVE_TABLE_OFFSET + sponsor_id * SPONSOR_SAVE_RECORD_SIZE
        struct.pack_into('<H', self.file_buffer, offset + 0x0E, days)
        self.sponsor_remaining_days_var.set(str(days))
        self._update_player_restore_state()
        return 'break' if _event is not None and getattr(_event, 'keysym', '') == 'Return' else None

    def _return_sponsor_loaned_ships(self, sponsor_id):
        """계약으로 대여된 함선을 함대·함선 풀에서 함께 회수한다."""
        loaned_slots = SPONSOR_LOANED_SHIP_SLOTS.get(int(sponsor_id), ())
        if not loaned_slots or not self.file_buffer:
            return False
        returned = set()
        for ship_index in loaned_slots:
            base = self._fleet_slot_offset(ship_index)
            if base + 0x5D > len(self.file_buffer):
                continue
            ship_code = struct.unpack_from('<I', self.file_buffer, base + 0x2D)[0]
            # 대여 표식이 붙은 배만 회수한다. 같은 슬롯에 사용자가 직접 만든 배는 보존한다.
            if (ship_code >> 16) != 0x3000:
                continue
            self.file_buffer[base:base + 0x5D] = b'\x00' * 0x5D
            struct.pack_into('<I', self.file_buffer, base + 0x2D, 0xFFFFFFFF)
            returned.add(ship_index)
        if not returned:
            return False

        active_indices = self._fleet_active_ship_indices()
        old_flagship = self._fleet_flagship_position()
        kept_indices = [index for index in active_indices if index not in returned]
        for position, ship_index in enumerate(kept_indices):
            struct.pack_into('<H', self.file_buffer, 0x48DD + position * 2, ship_index)
        for position in range(len(kept_indices), 8):
            struct.pack_into('<H', self.file_buffer, 0x48DD + position * 2, 0xFFFF)
        if not kept_indices:
            struct.pack_into('<I', self.file_buffer, 0x48D9, 0xFFFFFFFF)
        elif old_flagship is not None and old_flagship < len(active_indices):
            old_ship_index = active_indices[old_flagship]
            new_flagship = kept_indices.index(old_ship_index) if old_ship_index in kept_indices else 0
            struct.pack_into('<I', self.file_buffer, 0x48D9, new_flagship)
        return True

    def _reset_sponsor_contract(self, keep_hint=False):
        """현재 스폰서 계약을 해제하고, 필요하면 연결 힌트 획득 상태를 보존한다."""
        contract = self._active_sponsor_contract()
        if contract is None:
            return False
        sponsor_id, _sponsor, _discovery = contract
        sponsor_offset = SPONSOR_SAVE_TABLE_OFFSET + sponsor_id * SPONSOR_SAVE_RECORD_SIZE
        # 계약 상태를 비우고, 아래에서 선지급 원조금과 대여선까지 함께 회수한다.
        struct.pack_into('<I', self.file_buffer, sponsor_offset + 0x08, SPONSOR_CONTRACT_CANCELLED_STATE)
        struct.pack_into('<H', self.file_buffer, sponsor_offset + 0x0E, 0)
        cancel_aux = SPONSOR_CONTRACT_CANCEL_AUX_VALUES.get(sponsor_id)
        if cancel_aux is not None:
            struct.pack_into('<I', self.file_buffer, sponsor_offset + 0x14, cancel_aux)
        # 계약금은 빚으로 기록되어 있으며, 실제 지급된 선금은 빚의 절반이다.
        # 에디터의 계약 해제는 주인공·스폰서 양쪽 자금을 계약 전 상태로 되돌린다.
        debt = struct.unpack_from('<I', self.file_buffer, 161)[0]
        if debt:
            advance = debt // 2
            cash = struct.unpack_from('<I', self.file_buffer, 153)[0]
            cash = max(0, cash - advance)
            struct.pack_into('<I', self.file_buffer, 153, cash)
            struct.pack_into('<I', self.file_buffer, 161, 0)
            sponsor_money = struct.unpack_from('<I', self.file_buffer, sponsor_offset + 0x04)[0]
            struct.pack_into('<I', self.file_buffer, sponsor_offset + 0x04,
                             min(0xFFFFFFFF, sponsor_money + advance))
            if hasattr(self, 'money_values') and len(self.money_values) >= 3:
                self.money_values[0] = cash
                self.money_values[2] = 0
                self.refresh_money_table()
        returned_ships = self._return_sponsor_loaned_ships(sponsor_id)
        side_effects = SPONSOR_CONTRACT_CANCEL_SIDE_EFFECTS.get(sponsor_id, {})
        for offset, value in side_effects.get('u16', ()):
            if offset + 2 <= len(self.file_buffer):
                struct.pack_into('<H', self.file_buffer, offset, value)
        for offset, value in side_effects.get('u8', ()):
            if offset < len(self.file_buffer):
                self.file_buffer[offset] = value
        # 0x0D는 계약 표시가 아니라 게임이 사용하는 정상적인 "힌트 획득" 값이다.
        # 계약 여부는 스폰서 레코드로만 판단하므로 계약 해제 시 힌트 바이트는 보존한다.
        if _discovery is not None:
            hint_id = int(_discovery.get('hint_id', -1))
            if 0 <= hint_id < len(HINT_STATE_OFFSETS):
                hint_offset = HINT_STATE_OFFSETS[hint_id]
                if 0 <= hint_offset < len(self.file_buffer):
                    if not keep_hint:
                        self._sponsor_contract_hint_resets.setdefault(hint_offset, self.file_buffer[hint_offset])
                        self.file_buffer[hint_offset] &= ~0x05
        self._refresh_sponsor_contract_display()
        if returned_ships:
            self.refresh_fleet_list()
            self._update_fleet_reset_state()
        self._update_player_restore_state()
        return True

    def _complete_sponsor_contract_for_discovery(self, discovery_index):
        """계약 대상 발견물을 보고했을 때 계약을 완료 상태로 정산한다.

        계약 해제와 달리 이미 지급된 선금은 회수하지 않는다. 남은 절반만
        지급하고, 계약 상태와 계약 총액(세이브의 '빚' 필드)을 비운다.
        """
        contract = self._active_sponsor_contract()
        if contract is None:
            return False
        sponsor_id, _sponsor, discovery = contract
        if discovery is None or int(discovery['index']) != int(discovery_index):
            return False

        sponsor_offset = SPONSOR_SAVE_TABLE_OFFSET + sponsor_id * SPONSOR_SAVE_RECORD_SIZE
        debt = struct.unpack_from('<I', self.file_buffer, 161)[0]
        # 계약 때 선금은 debt // 2였으므로, 홀수 값도 보존되도록 잔금은 나머지로 계산한다.
        balance = debt - (debt // 2)
        cash = struct.unpack_from('<I', self.file_buffer, 153)[0]
        sponsor_money = struct.unpack_from('<I', self.file_buffer, sponsor_offset + 0x04)[0]
        struct.pack_into('<I', self.file_buffer, 153, min(0xFFFFFFFF, cash + balance))
        struct.pack_into('<I', self.file_buffer, 161, 0)
        struct.pack_into('<I', self.file_buffer, sponsor_offset + 0x04,
                         max(0, sponsor_money - balance))
        struct.pack_into('<I', self.file_buffer, sponsor_offset + 0x08,
                         SPONSOR_CONTRACT_CANCELLED_STATE)
        struct.pack_into('<H', self.file_buffer, sponsor_offset + 0x0E, 0)
        if hasattr(self, 'money_values') and len(self.money_values) >= 3:
            self.money_values[0] = min(0xFFFFFFFF, cash + balance)
            self.money_values[2] = 0
            self.refresh_money_table()
        self._refresh_sponsor_contract_display()
        self._update_player_restore_state()
        return True

    def clear_sponsor_contract(self):
        """현재 스폰서 계약만 해제하고 연결된 힌트 획득 상태는 유지한다."""
        if not self._reset_sponsor_contract(keep_hint=True):
            return
        self._discovery_view_revision += 1
        self.refresh_discoveries_table()
        self.lbl_status.config(text=ui('ui_0457'))

    def cancel_sponsor_contract_from_hint(self):
        """발견물 팝업에서 계약만 해지하고 힌트 획득 상태는 유지한다."""
        if not self._reset_sponsor_contract(keep_hint=True):
            return
        self.lbl_status.config(text=ui('ui_0460'))

    def _validate_sponsor_remaining_days(self, proposed):
        """남은 일수는 0~65,535까지만 입력되고, 초과값은 즉시 상한으로 보정한다."""
        if not proposed:
            return True
        if not proposed.isdigit():
            return False
        if int(proposed) <= 0xFFFF:
            return True
        # validatecommand 안에서 변수를 바로 바꾸면 재귀 검증이 일어날 수 있어
        # 현재 키 입력은 막고 다음 이벤트 루프에서 상한값을 반영한다.
        self.root.after_idle(lambda: self.sponsor_remaining_days_var.set(str(0xFFFF)))
        return False

    def _update_player_restore_state(self):
        """주인공 편집 UI와 최초 로드본을 비교해 되돌리기 상태를 갱신한다."""
        button = getattr(self, 'btn_player_restore', None)
        original = getattr(self, 'person_original_buffer', None)
        if button is None:
            return
        if not self.file_buffer or not original:
            button.place_forget()
            return

        def read_text(offset, length):
            return original[offset:offset + length].split(b'\x00')[0].decode('cp949', errors='ignore').strip()

        try:
            changed = (
                self.txt_first_name.get().strip() != read_text(95, 18)
                or self.txt_last_name.get().strip() != read_text(114, 18)
                or (int(self.spn_game_y.get()), int(self.spn_game_m.get()), int(self.spn_game_d.get()))
                   != (struct.unpack_from('<H', original, 21)[0], original[25], original[26])
                or (int(self.spn_birth_y.get()), int(self.spn_birth_m.get()), int(self.spn_birth_d.get()))
                   != (struct.unpack_from('<H', original, 149)[0], original[151], original[152])
                or self.cbo_job.current() != struct.unpack_from('<H', original, 137)[0]
                or self.cbo_blood.current() != struct.unpack_from('<H', original, 141)[0]
                or self.cbo_nation.current() != struct.unpack_from('<H', original, 139)[0]
                or self.player_face_id != struct.unpack_from('<H', original, 133)[0]
                or self.stat_values != list(original[45:51]) + [struct.unpack_from('<I', original, 51)[0]]
                or self.money_values != [
                    *[min(99999999, struct.unpack_from('<I', original, offset)[0]) for offset in (153, 157, 161)],
                    *[struct.unpack_from('<I', original, offset)[0] for offset in (83, 87)],
                ]
                or self.skill_levels != [min(3, max(0, original[56 + i])) for i in range(len(SKILLS_DATA))]
            )
            if not changed:
                for sponsor_id in SPONSOR_BY_ID:
                    offset = SPONSOR_SAVE_TABLE_OFFSET + sponsor_id * SPONSOR_SAVE_RECORD_SIZE
                    if (offset + 0x18 <= len(self.file_buffer) and offset + 0x18 <= len(original)
                            and self.file_buffer[offset + 0x04:offset + 0x18] != original[offset + 0x04:offset + 0x18]):
                        changed = True
                        break
            if not changed:
                for hint_offset, original_state in self._sponsor_contract_hint_resets.items():
                    if 0 <= hint_offset < len(self.file_buffer) and self.file_buffer[hint_offset] != original_state:
                        changed = True
                        break
        except (AttributeError, IndexError, ValueError, tk.TclError, struct.error):
            changed = True
        if changed:
            if not button.winfo_manager():
                button.place(x=0, y=136, width=84, height=25)
        else:
            button.place_forget()

    def restore_player_edits(self):
        """주인공 편집값만 마지막으로 불러온 세이브 상태로 되돌린다."""
        original = getattr(self, 'person_original_buffer', None)
        if not self.file_buffer or not original:
            return

        # 이 범위들은 저장 시 주인공 신상·능력치·자금/명성·기술/언어에 쓰는
        # 필드만 포함한다. 배우자, 역할 배정, 소지품 등 다른 편집은 보존한다.
        for start, end in (
            (21, 27),    # 현재일
            (45, 55),    # 능력치 및 생명력
            (56, 83),    # 기술·언어
            (83, 91),    # 명성·악명
            (95, 143),   # 이름·얼굴·직업·국적·혈액형
            (149, 165),  # 출생일·소지금·저금·빚
        ):
            self.file_buffer[start:end] = original[start:end]

        # 주인공 정보에서 편집하는 스폰서 계약 재력·상태·보조값·남은 일수를 마지막 로드 상태로 되돌린다.
        for sponsor_id in SPONSOR_BY_ID:
            offset = SPONSOR_SAVE_TABLE_OFFSET + sponsor_id * SPONSOR_SAVE_RECORD_SIZE
            if offset + 0x18 <= len(self.file_buffer) and offset + 0x18 <= len(original):
                self.file_buffer[offset + 0x04:offset + 0x18] = original[offset + 0x04:offset + 0x18]
        for hint_offset, original_state in self._sponsor_contract_hint_resets.items():
            if 0 <= hint_offset < len(self.file_buffer):
                self.file_buffer[hint_offset] = original_state
        self._sponsor_contract_hint_resets.clear()

        def read_cp949(buf, offset, max_len):
            return buf[offset:offset + max_len].split(b'\x00')[0].decode('cp949', errors='ignore').strip()

        self.set_entry_text(self.txt_first_name, read_cp949(original, 95, 18))
        self.set_entry_text(self.txt_last_name, read_cp949(original, 114, 18))

        game_year = struct.unpack_from('<H', original, 21)[0]
        self.set_spin_val(self.spn_game_y, game_year if game_year > 0 else 1480)
        self.set_spin_val(self.spn_game_m, original[25] if original[25] > 0 else 1)
        self.set_spin_val(self.spn_game_d, original[26] if original[26] > 0 else 1)
        birth_year = struct.unpack_from('<H', original, 149)[0]
        self.set_spin_val(self.spn_birth_y, birth_year if birth_year > 0 else 1450)
        self.set_spin_val(self.spn_birth_m, original[151] if original[151] > 0 else 1)
        self.set_spin_val(self.spn_birth_d, original[152] if original[152] > 0 else 1)

        self.cbo_job.current(min(max(struct.unpack_from('<H', original, 137)[0], 0), len(JOB_NAMES) - 1))
        self.cbo_blood.current(min(max(struct.unpack_from('<H', original, 141)[0], 0), len(BLOOD_NAMES) - 1))
        self.update_wife_combo_options()
        nation = struct.unpack_from('<H', original, 139)[0]
        self.chk_all_nations.set(nation > 1)
        self.toggle_all_nations()
        self.cbo_nation.current(nation if 0 <= nation < len(self.cbo_nation['values']) else 0)
        face_id = struct.unpack_from('<H', original, 133)[0]
        self.player_face_id = face_id if 0 <= face_id < 410 else 13
        self.update_player_face_display()

        self.stat_values = list(original[45:51]) + [struct.unpack_from('<I', original, 51)[0]]
        self.money_values = [
            min(99999999, struct.unpack_from('<I', original, offset)[0])
            for offset in (153, 157, 161)
        ] + [
            struct.unpack_from('<I', original, offset)[0]
            for offset in (83, 87)
        ]
        self.skill_levels = [min(3, max(0, original[56 + i])) for i in range(len(SKILLS_DATA))]
        self.refresh_stats_table()
        self.refresh_money_table()
        self.refresh_skills_table()
        self._refresh_birth_zodiac()
        self._on_game_date_changed()
        self._refresh_sponsor_contract_display()
        self._refresh_wife_fortune_state()
        self._schedule_city_shipyard_refresh(completion_message=ui('ui_0450'))
        self._update_player_restore_state()
    def refresh_stats_table(self):
        self.tree_stats.delete(*self.tree_stats.get_children())
        stat_defs = EDITOR_MAPPINGS['profile_stat_definitions']
        for i, (name, desc) in enumerate(stat_defs):
            val = self.stat_values[i] if self.file_buffer else UI_EMPTY_VALUE
            maximum = CHARACTER_SPECIAL_STAT_MAX if i == 6 else 255
            self.tree_stats.insert('', tk.END, iid=str(i), values=(i, name, val, f'{maximum:,}'))
        self._schedule_treeview_autofit(self.tree_stats)
        self._update_player_restore_state()

    def _on_stats_table_motion(self, event):
        """주인공 능력치 행의 기존 설명을 마우스 오버 툴팁으로 표시한다."""
        row = self.tree_stats.identify_row(event.y)
        is_field_column = self.tree_stats.identify_column(event.x) == '#2'
        if getattr(self, '_stats_tooltip_row', None) != row or not is_field_column:
            self._hide_stats_tooltip()
        if not is_field_column or not row or not row.isdigit():
            return
        stat_defs = EDITOR_MAPPINGS['profile_stat_definitions']
        index = int(row)
        if not 0 <= index < len(stat_defs) or self._stats_tooltip is not None:
            return
        tooltip = tk.Toplevel(self.root)
        tooltip.wm_overrideredirect(True)
        tooltip.attributes('-topmost', True)
        tooltip_text = (ui('ui_0469', self.stat_values[0], self.stat_values[6])
                        if index == 6 else stat_defs[index][1])
        tk.Label(tooltip, text=tooltip_text, justify='left', anchor='w',
                 bg='#FFF8D6', fg='#333333', relief='solid', bd=1,
                 padx=8, pady=6, font=('Malgun Gothic', 9)).pack()
        tooltip.geometry(f'+{event.x_root + 16}+{event.y_root + 18}')
        self._stats_tooltip = tooltip
        self._stats_tooltip_row = row

    def _hide_stats_tooltip(self, _event=None):
        tooltip = getattr(self, '_stats_tooltip', None)
        self._stats_tooltip = None
        self._stats_tooltip_row = None
        if tooltip is not None:
            try:
                tooltip.destroy()
            except tk.TclError:
                pass

    def _on_money_table_motion(self, event):
        """계약금 항목명 위에서만 선금·완료금 분할 정보를 표시한다."""
        row = self.tree_money.identify_row(event.y)
        is_field_column = self.tree_money.identify_column(event.x) == '#2'
        is_contract_amount = is_field_column and row == '2'
        if getattr(self, '_money_tooltip_row', None) != row or not is_contract_amount:
            self._hide_money_tooltip()
        if not is_contract_amount or self._money_tooltip is not None:
            return
        total = self.money_values[2] if len(self.money_values) > 2 else 0
        advance = total // 2
        balance = total - advance
        tooltip = tk.Toplevel(self.root)
        tooltip.wm_overrideredirect(True)
        tooltip.attributes('-topmost', True)
        tk.Label(tooltip, text=ui('ui_0462', total, advance, balance), justify='left', anchor='w',
                 bg='#FFF8D6', fg='#333333', relief='solid', bd=1,
                 padx=8, pady=6, font=('Malgun Gothic', 9)).pack()
        tooltip.geometry(f'+{event.x_root + 16}+{event.y_root + 18}')
        self._money_tooltip = tooltip
        self._money_tooltip_row = row

    def _hide_money_tooltip(self, _event=None):
        tooltip = getattr(self, '_money_tooltip', None)
        self._money_tooltip = None
        self._money_tooltip_row = None
        if tooltip is not None:
            try:
                tooltip.destroy()
            except tk.TclError:
                pass

    def refresh_money_table(self):
        self.tree_money.delete(*self.tree_money.get_children())
        money_defs = EDITOR_MAPPINGS['money_definitions']
        for i, (name, max_v) in enumerate(money_defs[:3]):
            val_str = f'{self.money_values[i]:,}' if self.file_buffer else UI_EMPTY_VALUE
            self.tree_money.insert('', tk.END, iid=str(i), values=(i, name, val_str, f'{max_v:,}'))
        if hasattr(self, 'tree_reputation'):
            self.tree_reputation.delete(*self.tree_reputation.get_children())
            for row, i in enumerate(range(3, len(money_defs))):
                name, max_v = money_defs[i]
                val_str = f'{self.money_values[i]:,}' if self.file_buffer else UI_EMPTY_VALUE
                self.tree_reputation.insert('', tk.END, iid=str(i), values=(row, name, val_str, f'{max_v:,}'))
            self._schedule_treeview_autofit(self.tree_money, self.tree_reputation)
        else:
            self._schedule_treeview_autofit(self.tree_money)
        self._update_player_restore_state()
    def on_stat_edit_request(self, event=None):
        if not self.file_buffer:
            return
        else:
            if event:
                item = self.tree_stats.identify_row(event.y)
                if item:
                    self.tree_stats.selection_set(item)
            sel = self.tree_stats.selection()
            if sel:
                idx = int(sel[0])
                stat_names = [definition[0] for definition in EDITOR_MAPPINGS['profile_stat_definitions']]
                max_value = CHARACTER_SPECIAL_STAT_MAX if idx == 6 else 255
                prompt = (ui('ui_0034', stat_names[idx], max_value)
                          if idx == 6 else ui('ui_0033', stat_names[idx]))
                new_v = self.ask_bounded_integer(ui('ui_0201'), prompt, self.stat_values[idx], 0, max_value)
                if new_v is not None:
                    self.stat_values[idx] = new_v
                    if idx == 0:
                        # 주인공 생명력은 체력 변경에 맞춰 게임의 기본 비율(체력 × 20)로 갱신한다.
                        self.stat_values[6] = min(CHARACTER_SPECIAL_STAT_MAX, new_v * 20)
                    self.refresh_stats_table()
                    self.tree_stats.selection_set(str(idx))
    def on_money_edit_request(self, event=None, tree=None):
        if not self.file_buffer:
            return
        else:
            tree = tree or self.tree_money
            if event:
                item = tree.identify_row(event.y)
                if item:
                    tree.selection_set(item)
            sel = tree.selection()
            if sel:
                idx = int(sel[0])
                names = [definition[0] for definition in EDITOR_MAPPINGS['money_definitions']]
                max_limits = [definition[1] for definition in EDITOR_MAPPINGS['money_definitions']]
                new_v = self.ask_bounded_integer(ui('ui_0202'), ui('ui_0034', names[idx], max_limits[idx]), self.money_values[idx], 0, max_limits[idx])
                if new_v is not None:
                    self.money_values[idx] = new_v
                    self.refresh_money_table()
                    tree.selection_set(str(idx))
    def apply_batch_stats(self):
        # ***<module>.CDS3SaveEditorApp.apply_batch_stats: Failure: Different control flow
        if not self.file_buffer:
            return
        try:
            target_v = min(255, max(0, int(self.spn_batch_stats.get())))
        except (TypeError, ValueError):
            target_v = 255
        for i in range(6):
            self.stat_values[i] = target_v
        self.stat_values[6] = min(CHARACTER_SPECIAL_STAT_MAX, self.stat_values[0] * 20)
        self.refresh_stats_table()
    def apply_batch_money(self):
        if not self.file_buffer:
            return
        try:
            target_v = min(99999999, max(0, int(self.spn_batch_money.get())))
        except (TypeError, ValueError):
            target_v = 99999999
        for i in range(3):
            self.money_values[i] = target_v
        self.refresh_money_table()
    def apply_batch_reputation(self):
        if not self.file_buffer:
            return
        try:
            target_v = min(PLAYER_REPUTATION_MAX, max(0, int(self.spn_batch_reputation.get())))
        except (TypeError, ValueError):
            target_v = PLAYER_REPUTATION_MAX
        for i in range(3, 5):
            self.money_values[i] = target_v
        self.refresh_money_table()
    def toggle_all_nations(self):
        if self.chk_all_nations.get():
            self.cbo_nation['values'] = NATION_NAMES
        else:
            self.cbo_nation['values'] = BASIC_NATIONS
            if self.cbo_nation.current() > 1:
                self.cbo_nation.current(0)
        self._update_player_restore_state()
    def build_skills_tab(self):
        # ***<module>.CDS3SaveEditorApp.build_skills_tab: Failure: Different bytecode
        f_tech = tk.Frame(self.profile_page_tech, padx=8, pady=6)
        f_tech.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        f_tech_top = tk.Frame(f_tech)
        f_tech_top.pack(side=tk.TOP, fill=tk.X, pady=2)
        tk.Label(f_tech_top, text=ui('ui_0247'), font=('Malgun Gothic', 9)).pack(side=tk.LEFT, padx=2)
        self.spn_batch_tech = ttk.Spinbox(f_tech_top, from_=0, to=3, width=4, justify='center', font=('Malgun Gothic', 9))
        self.spn_batch_tech.set('3')
        self.spn_batch_tech.pack(side=tk.LEFT, padx=4)
        EditorButton(f_tech_top, text=ui('ui_0243'), bg='#E6F4EA', fg='#137333', font=('Malgun Gothic', 9), command=self.apply_batch_tech).pack(side=tk.LEFT, padx=4)
        cols = ('index', 'field', 'level')
        f_tree_t = tk.Frame(f_tech)
        f_tree_t.pack(fill=tk.BOTH, expand=True, pady=2)
        self.tree_tech = ttk.Treeview(f_tree_t, columns=cols, show='headings', height=13)
        self.tree_tech.heading('index', text=TREE_COLUMN_TITLES['tech']['index'])
        self.tree_tech.heading('field', text=TREE_COLUMN_TITLES['tech']['field'])
        self.tree_tech.heading('level', text=TREE_COLUMN_TITLES['tech']['level'])
        for c, w, a, s in [('index', 35, 'center', False), ('field', 190, 'w', True), ('level', 150, 'center', False)]:
            self.tree_tech.column(c, width=w, anchor=a, stretch=s)
        tech_scrollbar = ttk.Scrollbar(f_tree_t, orient=tk.VERTICAL, command=self.tree_tech.yview)
        self.tree_tech.configure(yscrollcommand=tech_scrollbar.set)
        self.tree_tech.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=2)
        tech_scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=2)
        f_lang = tk.Frame(self.profile_page_lang, padx=8, pady=6)
        f_lang.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        f_lang_top = tk.Frame(f_lang)
        f_lang_top.pack(side=tk.TOP, fill=tk.X, pady=2)
        tk.Label(f_lang_top, text=ui('ui_0247'), font=('Malgun Gothic', 9)).pack(side=tk.LEFT, padx=2)
        self.spn_batch_lang = ttk.Spinbox(f_lang_top, from_=0, to=3, width=4, justify='center', font=('Malgun Gothic', 9))
        self.spn_batch_lang.set('3')
        self.spn_batch_lang.pack(side=tk.LEFT, padx=4)
        EditorButton(f_lang_top, text=ui('ui_0243'), bg='#E6F4EA', fg='#137333', font=('Malgun Gothic', 9), command=self.apply_batch_lang).pack(side=tk.LEFT, padx=4)
        cols_lang = ('index', 'field', 'level')
        f_tree_l = tk.Frame(f_lang)
        f_tree_l.pack(fill=tk.BOTH, expand=True, pady=2)
        self.tree_lang = ttk.Treeview(f_tree_l, columns=cols_lang, show='headings', height=14)
        self.tree_lang.heading('index', text=TREE_COLUMN_TITLES['language']['index'])
        self.tree_lang.heading('field', text=TREE_COLUMN_TITLES['language']['field'])
        self.tree_lang.heading('level', text=TREE_COLUMN_TITLES['language']['level'])
        for c, w, a, s in [('index', 35, 'center', False), ('field', 195, 'w', True), ('level', 155, 'center', False)]:
            self.tree_lang.column(c, width=w, anchor=a, stretch=s)
        lang_scrollbar = ttk.Scrollbar(f_tree_l, orient=tk.VERTICAL, command=self.tree_lang.yview)
        self.tree_lang.configure(yscrollcommand=lang_scrollbar.set)
        self.tree_lang.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=2)
        lang_scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=2)
        self.skill_levels = [0] * len(SKILLS_DATA)
        self.tree_tech.bind('<Return>', lambda e: self.on_tech_edit_request())
        self.tree_tech.bind('<Double-1>', lambda _event: self.on_tech_edit_request())
        self.tree_tech.bind('<Button-3>', self.show_tech_context_menu)
        self.tree_lang.bind('<Return>', lambda e: self.on_lang_edit_request())
        self.tree_lang.bind('<Double-1>', lambda _event: self.on_lang_edit_request())
        self.tree_lang.bind('<Button-3>', self.show_lang_context_menu)
    def refresh_skills_table(self):
        # irreducible cflow, using cdg fallback
        # ***<module>.CDS3SaveEditorApp.refresh_skills_table: Failure: Different control flow
        self.tree_tech.delete(*self.tree_tech.get_children())
        for i in range(13):
            name, off, desc = SKILLS_DATA[i]
            if self.file_buffer:
                lvl = self.skill_levels[i]
                lvl_str = str(lvl)
            else:
                lvl_str = UI_EMPTY_VALUE
            self.tree_tech.insert('', tk.END, iid=str(i), values=(i, name, lvl_str))
        self.tree_lang.delete(*self.tree_lang.get_children())
        for i in range(13, 27):
            name, off, desc = SKILLS_DATA[i]
            if self.file_buffer:
                lvl = self.skill_levels[i]
                lvl_str = str(lvl)
            else:
                lvl_str = UI_EMPTY_VALUE
            self.tree_lang.insert('', tk.END, iid=str(i), values=(i - 13, name, lvl_str))
        self._schedule_treeview_autofit(self.tree_tech, self.tree_lang)
        self._update_player_restore_state()
    def set_tech_level(self, idx, level):
        if not self.file_buffer:
            return
        else:
            self.skill_levels[idx] = level
            self.refresh_skills_table()
            self.tree_tech.selection_set(str(idx))
    def set_lang_level(self, idx, level):
        if not self.file_buffer:
            return
        else:
            self.skill_levels[idx] = level
            self.refresh_skills_table()
            self.tree_lang.selection_set(str(idx))
    def on_tech_edit_request(self):
        if not self.file_buffer:
            return
        else:
            sel = self.tree_tech.selection()
            if sel:
                idx = int(sel[0])
                name, off, desc = SKILLS_DATA[idx]
                new_v = self.ask_bounded_integer(ui('ui_0203'), ui('ui_0035', name), self.skill_levels[idx], 0, 3)
                if new_v is not None:
                    self.skill_levels[idx] = new_v
                    self.refresh_skills_table()
                    self.tree_tech.selection_set(str(idx))
    def on_lang_edit_request(self):
        if not self.file_buffer:
            return
        else:
            sel = self.tree_lang.selection()
            if sel:
                idx = int(sel[0])
                name, off, desc = SKILLS_DATA[idx]
                new_v = self.ask_bounded_integer(ui('ui_0204'), ui('ui_0035', name), self.skill_levels[idx], 0, 3)
                if new_v is not None:
                    self.skill_levels[idx] = new_v
                    self.refresh_skills_table()
                    self.tree_lang.selection_set(str(idx))
    def show_tech_context_menu(self, event):
        if not self.file_buffer:
            return
        else:
            item = self.tree_tech.identify_row(event.y)
            if item:
                self.tree_tech.selection_set(item)
                self._popup_tech_menu(int(item), event.x_root, event.y_root)
    def _popup_tech_menu(self, idx, x, y):
        # ***<module>.CDS3SaveEditorApp._popup_tech_menu: Failure: Different bytecode
        name = SKILLS_DATA[idx][0]
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label=ui('ui_0018', name), state='disabled')
        menu.add_separator()
        for level in range(4):
            menu.add_command(label=ui('ui_0377', level), command=lambda value=level: self.set_tech_level(idx, value))
        menu.tk_popup(x, y)
    def show_lang_context_menu(self, event):
        if not self.file_buffer:
            return
        else:
            item = self.tree_lang.identify_row(event.y)
            if item:
                self.tree_lang.selection_set(item)
                self._popup_lang_menu(int(item), event.x_root, event.y_root)
    def _popup_lang_menu(self, idx, x, y):
        # ***<module>.CDS3SaveEditorApp._popup_lang_menu: Failure: Different bytecode
        name = SKILLS_DATA[idx][0]
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label=ui('ui_0018', name), state='disabled')
        menu.add_separator()
        for level in range(4):
            menu.add_command(label=ui('ui_0377', level), command=lambda value=level: self.set_lang_level(idx, value))
        menu.tk_popup(x, y)
    def apply_batch_tech(self):
        # ***<module>.CDS3SaveEditorApp.apply_batch_tech: Failure: Compilation Error
        if not self.file_buffer:
            return
        else:
            try:
                target_lv = min(3, max(0, int(self.spn_batch_tech.get())))
            except:
                target_lv = 3
            for i in range(13):
                self.skill_levels[i] = target_lv
            self.refresh_skills_table()
    def apply_batch_lang(self):
        # ***<module>.CDS3SaveEditorApp.apply_batch_lang: Failure: Different control flow
        if not self.file_buffer:
            return
        else:
            try:
                target_lv = min(3, max(0, int(self.spn_batch_lang.get())))
            except:
                target_lv = 3
            for i in range(13, 27):
                self.skill_levels[i] = target_lv
            self.refresh_skills_table()
    def build_items_tab(self):
        # ***<module>.CDS3SaveEditorApp.build_items_tab: Failure: Different bytecode
        parent = self.tab_items
        f_pocket_hdr = tk.Frame(parent)
        tk.Label(f_pocket_hdr, text=GROUP_TITLES['items_pocket'], font=('Malgun Gothic', 9, 'bold')).pack(side=tk.LEFT)
        self.lbl_pocket_count = tk.Label(f_pocket_hdr, text=inventory_text('ui_0283', 'ui_0281', 0, 16), font=('Malgun Gothic', 9), fg='#1A73E8')
        self.lbl_pocket_count.pack(side=tk.LEFT)
        EditorButton(f_pocket_hdr, text=ui('ui_0376'), bg='#FCE8E6', fg='#D93025', command=self.clear_pocket).pack(side=tk.RIGHT, padx=(8, 0))
        self.f_pocket = tk.LabelFrame(parent, labelwidget=f_pocket_hdr, padx=6, pady=4)
        self.f_pocket.place(x=472, y=6, width=456, height=270)
        cols_ps = ('slot', 'game_id', 'name', 'category')
        f_tree_p = tk.Frame(self.f_pocket)
        f_tree_p.pack(fill=tk.BOTH, expand=True)
        self.tree_pocket = ttk.Treeview(f_tree_p, columns=cols_ps, show='headings', height=8)
        for c, w, a, s in [('slot', 42, 'center', False), ('game_id', 45, 'center', False), ('name', 215, 'w', True), ('category', 125, 'center', False)]:
            self.tree_pocket.heading(c, text=TREE_COLUMN_TITLES['pocket_storage'][c])
            self.tree_pocket.column(c, width=w, anchor=a, stretch=s)
        self.sb_pocket = ttk.Scrollbar(f_tree_p, orient=tk.VERTICAL, command=self.tree_pocket.yview)
        self.tree_pocket.configure(yscrollcommand=lambda first, last: self._update_inventory_scrollbar(self.sb_pocket, first, last))
        self.tree_pocket.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree_pocket.bind('<Return>', lambda e: self.move_pocket_to_storage())
        self.tree_pocket.bind('<Double-1>', self.on_pocket_double_click)
        self.tree_pocket.bind('<Delete>', lambda e: self.delete_selected_pocket_item())
        self.tree_pocket.bind('<BackSpace>', lambda e: self.delete_selected_pocket_item())
        self.tree_pocket.bind('<Button-3>', self.show_pocket_context_menu)
        f_storage_hdr = tk.Frame(parent)
        tk.Label(f_storage_hdr, text=GROUP_TITLES['items_storage'], font=('Malgun Gothic', 9, 'bold')).pack(side=tk.LEFT)
        self.lbl_storage_count = tk.Label(f_storage_hdr, text=inventory_text('ui_0283', 'ui_0282', 0, 99), font=('Malgun Gothic', 9), fg='#1A73E8')
        self.lbl_storage_count.pack(side=tk.LEFT)
        EditorButton(f_storage_hdr, text=ui('ui_0376'), bg='#FCE8E6', fg='#D93025', command=self.clear_storage).pack(side=tk.RIGHT, padx=(8, 0))
        self.f_storage = tk.LabelFrame(parent, labelwidget=f_storage_hdr, padx=6, pady=4)
        self.f_storage.place(x=472, y=282, width=456, height=270)
        f_tree_s = tk.Frame(self.f_storage)
        f_tree_s.pack(fill=tk.BOTH, expand=True)
        self.tree_storage = ttk.Treeview(f_tree_s, columns=cols_ps, show='headings', height=8)
        for c, w, a, s in [('slot', 42, 'center', False), ('game_id', 45, 'center', False), ('name', 215, 'w', True), ('category', 125, 'center', False)]:
            self.tree_storage.heading(c, text=TREE_COLUMN_TITLES['pocket_storage'][c])
            self.tree_storage.column(c, width=w, anchor=a, stretch=s)
        self.sb_storage = ttk.Scrollbar(f_tree_s, orient=tk.VERTICAL, command=self.tree_storage.yview)
        self.tree_storage.configure(yscrollcommand=lambda first, last: self._update_inventory_scrollbar(self.sb_storage, first, last))
        self.tree_storage.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree_storage.bind('<Return>', lambda e: self.move_storage_to_pocket())
        self.tree_storage.bind('<Double-1>', self.on_storage_double_click)
        self.tree_storage.bind('<Delete>', lambda e: self.delete_selected_storage_item())
        self.tree_storage.bind('<BackSpace>', lambda e: self.delete_selected_storage_item())
        self.tree_storage.bind('<Button-3>', self.show_storage_context_menu)
        f_db = tk.LabelFrame(parent, text=GROUP_TITLES['items_catalog'], font=('Malgun Gothic', 9, 'bold'), padx=6, pady=4)
        f_db.place(x=8, y=6, width=456, height=546)
        f_filter = tk.Frame(f_db)
        f_filter.pack(side=tk.TOP, fill=tk.X, pady=2)
        tk.Label(f_filter, text=ui('ui_0250')).pack(side=tk.LEFT, padx=3)
        category_ids = EDITOR_MAPPINGS['item_catalog_category_ids']
        category_values = [ui('ui_0364') if category_id == -1 else ui('ui_0105') if category_id == -2 else ITEM_CATEGORY_NAMES[category_id]
                           for category_id in category_ids]
        self.cbo_item_cat = ttk.Combobox(f_filter, values=category_values, state='readonly', width=13)
        self.cbo_item_cat.current(0)
        self.cbo_item_cat.pack(side=tk.LEFT, padx=2)
        self.cbo_item_cat.bind('<<ComboboxSelected>>', lambda e: self.refresh_item_catalog())
        tk.Label(f_filter, text=ui('ui_0251')).pack(side=tk.LEFT, padx=2)
        item_search_host = tk.Frame(f_filter, width=108, height=23)
        item_search_host.pack(side=tk.LEFT, padx=2)
        self.txt_item_search = NativeWinEdit(
            item_search_host,
            lambda: self._schedule_search_refresh('items', self.refresh_item_catalog),
            width=108, height=23,
        )
        cols_cat = ('game_id', 'name', 'category', 'sell_price')
        f_tree_c = tk.Frame(f_db)
        f_tree_c.pack(fill=tk.BOTH, expand=True)
        self.tree_catalog = ttk.Treeview(f_tree_c, columns=cols_cat, show='headings', height=9)
        for c, w, a, s in [('game_id', 55, 'center', False), ('name', 420, 'w', True), ('category', 220, 'center', False), ('sell_price', 180, 'e', False)]:
            self.tree_catalog.heading(c, text=TREE_COLUMN_TITLES['catalog'][c])
            self.tree_catalog.column(c, width=w, anchor=a, stretch=s)
        sb_cy = ttk.Scrollbar(f_tree_c, orient=tk.VERTICAL, command=self.tree_catalog.yview)
        self.tree_catalog.configure(yscrollcommand=sb_cy.set)
        sb_cy.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_catalog.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree_catalog.bind('<Return>', lambda e: self.show_catalog_menu_for_selected())
        self.tree_catalog.bind('<Double-1>', self.on_catalog_double_click)
        self.tree_catalog.bind('<Button-3>', self.show_catalog_context_menu)
        self.refresh_item_catalog()
    def get_item_info(self, item_id):
        if 0 <= item_id < len(self.item_db):
                return self.item_db[item_id]
        return {'id': item_id, 'name': ui('ui_0362', item_id), 'category': ui('ui_0363'), 'sell_price': 0, 'buy_price': 0}
    @staticmethod
    def _update_inventory_scrollbar(scrollbar, first, last):
        """Show an inventory scrollbar only when its list can actually scroll."""
        try:
            should_show = float(first) > 0.0 or float(last) < 1.0
        except (TypeError, ValueError):
            return
        scrollbar.set(first, last)
        is_visible = getattr(scrollbar, '_auto_visible', None)
        if is_visible is None:
            is_visible = bool(scrollbar.winfo_manager())
        if should_show and not is_visible:
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            scrollbar._auto_visible = True
        elif not should_show and is_visible:
            scrollbar.pack_forget()
            scrollbar._auto_visible = False

    def refresh_pocket_list(self):
        self.tree_pocket.delete(*self.tree_pocket.get_children())
        for i, item_id in enumerate(self.pocket_ids):
            info = self.get_item_info(item_id)
            self.tree_pocket.insert('', tk.END, values=(i, item_id, info['name'], info['category']))
        cnt = len(self.pocket_ids)
        self.lbl_pocket_count.config(text=inventory_text('ui_0283', 'ui_0281', cnt, 16), fg='#D93025' if cnt >= 16 else '#1A73E8')
        self._schedule_treeview_autofit(self.tree_pocket)
    def refresh_storage_list(self):
        self.tree_storage.delete(*self.tree_storage.get_children())
        for i, item_id in enumerate(self.storage_ids):
            info = self.get_item_info(item_id)
            self.tree_storage.insert('', tk.END, values=(i, item_id, info['name'], info['category']))
        cnt = len(self.storage_ids)
        self.lbl_storage_count.config(text=inventory_text('ui_0283', 'ui_0282', cnt, 99), fg='#D93025' if cnt >= 99 else '#1A73E8')
        self._schedule_treeview_autofit(self.tree_storage)
    def refresh_item_catalog(self):
        search = self.txt_item_search.get().strip().casefold()
        cat = self.cbo_item_cat.get()
        filter_key = (search, cat)
        if (getattr(self, '_item_catalog_filter_cache', object()) == filter_key
                and self.tree_catalog.get_children()):
            return
        self.tree_catalog.delete(*self.tree_catalog.get_children())
        for item, item_name_key in self._item_search_index:
            if search and search not in item_name_key:
                    continue
            if cat != ui('ui_0364') and item['category'] != cat:
                    continue
            self.tree_catalog.insert('', tk.END, iid=str(item['id']), values=(item['id'], item['name'], item['category'], f'{item['sell_price']:,} G'))
        self._item_catalog_filter_cache = filter_key
        self._schedule_treeview_autofit(self.tree_catalog)
    def open_item_info_modal(self, item_id, source_view='catalog', slot_index=None, click_pos=None):
        # ***<module>.CDS3SaveEditorApp.open_item_info_modal: Failure: Different bytecode
        items_list = []
        current_idx = 0
        if source_view == 'catalog':
            for iid in self.tree_catalog.get_children():
                try:
                    it_id = int(iid)
                    items_list.append((it_id, None))
                    if it_id == item_id:
                        current_idx = len(items_list) - 1
                except Exception:
                    continue
        else:
            if source_view == 'pocket':
                for s_idx, it_id in enumerate(self.pocket_ids):
                    items_list.append((it_id, s_idx))
                    if slot_index is not None and s_idx == slot_index:
                        current_idx = len(items_list) - 1
                    else:
                        if slot_index is None and it_id == item_id and (current_idx == 0):
                                    current_idx = len(items_list) - 1
            else:
                if source_view == 'storage':
                    for s_idx, it_id in enumerate(self.storage_ids):
                        items_list.append((it_id, s_idx))
                        if slot_index is not None and s_idx == slot_index:
                            current_idx = len(items_list) - 1
                        else:
                            if slot_index is None and it_id == item_id and (current_idx == 0):
                                        current_idx = len(items_list) - 1
        if not items_list:
            items_list = [(item_id, slot_index)]
            current_idx = 0
        info = self.get_item_info(item_id)
        desc = ITEM_DESCRIPTIONS.get(item_id, '')
        def get_item_info_fn(it_id):
            return (self.get_item_info(it_id), ITEM_DESCRIPTIONS.get(it_id, ''))
        def on_navigate_fn(it_id, s_idx):
            try:
                if source_view == 'catalog' and self.tree_catalog.exists(str(it_id)):
                    self.tree_catalog.selection_set(str(it_id))
                    self.tree_catalog.see(str(it_id))
                elif source_view == 'pocket':
                    children = self.tree_pocket.get_children()
                    if s_idx is not None and 0 <= s_idx < len(children):
                        self.tree_pocket.selection_set(children[s_idx])
                        self.tree_pocket.see(children[s_idx])
                elif source_view == 'storage':
                    children = self.tree_storage.get_children()
                    if s_idx is not None and 0 <= s_idx < len(children):
                        self.tree_storage.selection_set(children[s_idx])
                        self.tree_storage.see(children[s_idx])
            except Exception:
                return None
        def on_item_action(it_id, action_type, slot_idx, parent_window=None):
            # ***<module>.CDS3SaveEditorApp.open_item_info_modal.on_item_action: Failure: Different bytecode
            p_win = parent_window or self.root
            info = self.get_item_info(it_id)
            if action_type == 'add_pocket':
                if len(self.pocket_ids) >= 16:
                    messagebox.showwarning(*inventory_full_message('ui_0281', 16), parent=p_win)
                    return False
                self.pocket_ids.append(it_id)
                self.refresh_pocket_list()
                return True
            if action_type == 'add_storage':
                if len(self.storage_ids) >= 99:
                    messagebox.showwarning(*inventory_full_message('ui_0282', 99), parent=p_win)
                    return False
                self.storage_ids.append(it_id)
                self.refresh_storage_list()
                return True
            if action_type == 'move_to_storage':
                if len(self.storage_ids) >= 99:
                    messagebox.showwarning(*inventory_full_message('ui_0282', 99), parent=p_win)
                    return False
                if slot_idx is not None and 0 <= slot_idx < len(self.pocket_ids):
                    del_id = self.pocket_ids.pop(slot_idx)
                    self.storage_ids.append(del_id)
                    self.refresh_pocket_list()
                    self.refresh_storage_list()
                    return True
                return False
            if action_type == 'move_to_pocket':
                if len(self.pocket_ids) >= 16:
                    messagebox.showwarning(*inventory_full_message('ui_0281', 16), parent=p_win)
                    return False
                if slot_idx is not None and 0 <= slot_idx < len(self.storage_ids):
                    del_id = self.storage_ids.pop(slot_idx)
                    self.pocket_ids.append(del_id)
                    self.refresh_pocket_list()
                    self.refresh_storage_list()
                    return True
                return False
            if action_type == 'delete_pocket':
                if not messagebox.askyesno(ui('ui_0175'), inventory_text('ui_0284', 'ui_0281', info['name']), parent=p_win):
                    return False
                if slot_idx is not None and 0 <= slot_idx < len(self.pocket_ids):
                    self.pocket_ids.pop(slot_idx)
                    self.refresh_pocket_list()
                    return True
                return False
            if action_type == 'delete_storage':
                if not messagebox.askyesno(ui('ui_0175'), inventory_text('ui_0284', 'ui_0282', info['name']), parent=p_win):
                    return False
                if slot_idx is not None and 0 <= slot_idx < len(self.storage_ids):
                    self.storage_ids.pop(slot_idx)
                    self.refresh_storage_list()
                    return True
            return False
        ItemInfoModal(self.root, info, desc, source_view=source_view, slot_index=slot_index, on_action_callback=on_item_action, click_pos=click_pos, items_list=items_list, current_list_index=current_idx, get_item_info_fn=get_item_info_fn, on_navigate_callback=on_navigate_fn)
    def on_catalog_double_click(self, event):
        if not self.file_buffer:
            return
        else:
            item = self.tree_catalog.identify_row(event.y)
            if item:
                item_id = int(item)
                self.open_item_info_modal(item_id, source_view='catalog', click_pos=(event.x_root, event.y_root))
    def on_pocket_double_click(self, event):
        if not self.file_buffer:
            return
        else:
            item = self.tree_pocket.identify_row(event.y)
            if item:
                idx = self.tree_pocket.index(item)
                if 0 <= idx < len(self.pocket_ids):
                    item_id = self.pocket_ids[idx]
                    self.open_item_info_modal(item_id, source_view='pocket', slot_index=idx, click_pos=(event.x_root, event.y_root))
    def on_storage_double_click(self, event):
        if not self.file_buffer:
            return
        else:
            item = self.tree_storage.identify_row(event.y)
            if item:
                idx = self.tree_storage.index(item)
                if 0 <= idx < len(self.storage_ids):
                    item_id = self.storage_ids[idx]
                    self.open_item_info_modal(item_id, source_view='storage', slot_index=idx, click_pos=(event.x_root, event.y_root))
    def move_pocket_to_storage(self):
        # ***<module>.CDS3SaveEditorApp.move_pocket_to_storage: Failure: Different bytecode
        if not self.file_buffer:
            return
        else:
            sel = self.tree_pocket.selection()
            if not sel:
                return
            else:
                idx = self.tree_pocket.index(sel[0])
                if 0 <= idx < len(self.pocket_ids):
                    if len(self.storage_ids) >= 99:
                        messagebox.showwarning(*inventory_full_message('ui_0282', 99))
                        return
                    else:
                        item_id = self.pocket_ids.pop(idx)
                        self.storage_ids.append(item_id)
                        self.refresh_pocket_list()
                        self.refresh_storage_list()
                        children = self.tree_storage.get_children()
                        if children:
                            last_item = children[(-1)]
                            self.tree_storage.selection_set(last_item)
                            self.tree_storage.focus(last_item)
                            self.tree_storage.see(last_item)
    def move_storage_to_pocket(self):
        # ***<module>.CDS3SaveEditorApp.move_storage_to_pocket: Failure: Different bytecode
        if not self.file_buffer:
            return
        else:
            sel = self.tree_storage.selection()
            if not sel:
                return
            else:
                idx = self.tree_storage.index(sel[0])
                if 0 <= idx < len(self.storage_ids):
                    if len(self.pocket_ids) >= 16:
                        messagebox.showwarning(*inventory_full_message('ui_0281', 16))
                        return
                    else:
                        item_id = self.storage_ids.pop(idx)
                        self.pocket_ids.append(item_id)
                        self.refresh_pocket_list()
                        self.refresh_storage_list()
                        children = self.tree_pocket.get_children()
                        if children:
                            last_item = children[(-1)]
                            self.tree_pocket.selection_set(last_item)
                            self.tree_pocket.focus(last_item)
                            self.tree_pocket.see(last_item)
    def add_selected_item_to_pocket(self):
        # ***<module>.CDS3SaveEditorApp.add_selected_item_to_pocket: Failure: Different bytecode
        if not self.file_buffer:
            return
        else:
            sel = self.tree_catalog.selection()
            if not sel:
                return
            else:
                item_id = int(sel[0])
                if len(self.pocket_ids) >= 16:
                    messagebox.showwarning(*inventory_full_message('ui_0281', 16))
                    return
                else:
                    self.pocket_ids.append(item_id)
                    self.refresh_pocket_list()
                    children = self.tree_pocket.get_children()
                    if children:
                        last_item = children[(-1)]
                        self.tree_pocket.selection_set(last_item)
                        self.tree_pocket.focus(last_item)
                        self.tree_pocket.see(last_item)
    def add_selected_item_to_storage(self):
        # ***<module>.CDS3SaveEditorApp.add_selected_item_to_storage: Failure: Different bytecode
        if not self.file_buffer:
            return
        else:
            sel = self.tree_catalog.selection()
            if not sel:
                return
            else:
                item_id = int(sel[0])
                if len(self.storage_ids) >= 99:
                    messagebox.showwarning(*inventory_full_message('ui_0282', 99))
                    return
                else:
                    self.storage_ids.append(item_id)
                    self.refresh_storage_list()
                    children = self.tree_storage.get_children()
                    if children:
                        last_item = children[(-1)]
                        self.tree_storage.selection_set(last_item)
                        self.tree_storage.focus(last_item)
                        self.tree_storage.see(last_item)
    def delete_selected_pocket_item(self):
        # ***<module>.CDS3SaveEditorApp.delete_selected_pocket_item: Failure: Different bytecode
        if not self.file_buffer:
            return
        else:
            sel = self.tree_pocket.selection()
            if not sel:
                return
            else:
                idx = self.tree_pocket.index(sel[0])
                if 0 <= idx < len(self.pocket_ids):
                    item_id = self.pocket_ids[idx]
                    info = self.get_item_info(item_id)
                    if not messagebox.askyesno(ui('ui_0175'), inventory_text('ui_0284', 'ui_0281', info['name'])):
                        return
                    else:
                        self.pocket_ids.pop(idx)
                        self.refresh_pocket_list()
                        if len(self.pocket_ids) > 0:
                            next_idx = min(idx, len(self.pocket_ids) - 1)
                            children = self.tree_pocket.get_children()
                            if 0 <= next_idx < len(children):
                                self.tree_pocket.selection_set(children[next_idx])
    def delete_selected_storage_item(self):
        # ***<module>.CDS3SaveEditorApp.delete_selected_storage_item: Failure: Different bytecode
        if not self.file_buffer:
            return
        else:
            sel = self.tree_storage.selection()
            if not sel:
                return
            else:
                idx = self.tree_storage.index(sel[0])
                if 0 <= idx < len(self.storage_ids):
                    item_id = self.storage_ids[idx]
                    info = self.get_item_info(item_id)
                    if not messagebox.askyesno(ui('ui_0175'), inventory_text('ui_0284', 'ui_0282', info['name'])):
                        return
                    else:
                        self.storage_ids.pop(idx)
                        self.refresh_storage_list()
                        if len(self.storage_ids) > 0:
                            next_idx = min(idx, len(self.storage_ids) - 1)
                            children = self.tree_storage.get_children()
                            if 0 <= next_idx < len(children):
                                self.tree_storage.selection_set(children[next_idx])
    def show_pocket_context_menu(self, event):
        # ***<module>.CDS3SaveEditorApp.show_pocket_context_menu: Failure: Different bytecode
        if not self.file_buffer:
            return
        else:
            item = self.tree_pocket.identify_row(event.y)
            if item:
                self.tree_pocket.selection_set(item)
                menu = tk.Menu(self.root, tearoff=0)
                menu.add_command(label=inventory_text('ui_0290', 'ui_0282'), command=self.move_pocket_to_storage)
                menu.add_separator()
                menu.add_command(label=inventory_text('ui_0292', 'ui_0281'), command=self.delete_selected_pocket_item)
                menu.tk_popup(event.x_root, event.y_root)
    def show_storage_context_menu(self, event):
        # ***<module>.CDS3SaveEditorApp.show_storage_context_menu: Failure: Different bytecode
        if not self.file_buffer:
            return
        else:
            item = self.tree_storage.identify_row(event.y)
            if item:
                self.tree_storage.selection_set(item)
                menu = tk.Menu(self.root, tearoff=0)
                menu.add_command(label=inventory_text('ui_0290', 'ui_0281'), command=self.move_storage_to_pocket)
                menu.add_separator()
                menu.add_command(label=inventory_text('ui_0292', 'ui_0282'), command=self.delete_selected_storage_item)
                menu.tk_popup(event.x_root, event.y_root)
    def show_catalog_menu_for_selected(self):
        if not self.file_buffer:
            return
        else:
            sel = self.tree_catalog.selection()
            if not sel:
                return
            else:
                item_id = int(sel[0])
                bbox = self.tree_catalog.bbox(sel[0])
                x = self.tree_catalog.winfo_rootx() + (bbox[0] if bbox else 50) + 150
                y = self.tree_catalog.winfo_rooty() + (bbox[1] if bbox else 20) + 20
                self._popup_catalog_menu(item_id, x, y)
    def show_catalog_context_menu(self, event):
        if not self.file_buffer:
            return
        else:
            item = self.tree_catalog.identify_row(event.y)
            if item:
                self.tree_catalog.selection_set(item)
                self._popup_catalog_menu(int(item), event.x_root, event.y_root)
    def _popup_catalog_menu(self, item_id, x, y):
        # ***<module>.CDS3SaveEditorApp._popup_catalog_menu: Failure: Different bytecode
        info = self.get_item_info(item_id)
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label=ui('ui_0293', info['name']), state='disabled')
        menu.add_separator()
        menu.add_command(label=inventory_text('ui_0285', 'ui_0281'), command=self.add_selected_item_to_pocket)
        menu.add_command(label=inventory_text('ui_0285', 'ui_0282'), command=self.add_selected_item_to_storage)
        menu.tk_popup(x, y)
    def clear_pocket(self):
        # ***<module>.CDS3SaveEditorApp.clear_pocket: Failure: Different bytecode
        if not self.file_buffer:
            return
        else:
            if messagebox.askyesno(ui('ui_0175'), inventory_text('ui_0286', 'ui_0281')):
                self.pocket_ids.clear()
                self.refresh_pocket_list()
    def clear_storage(self):
        # ***<module>.CDS3SaveEditorApp.clear_storage: Failure: Different bytecode
        if not self.file_buffer:
            return
        else:
            if messagebox.askyesno(ui('ui_0175'), inventory_text('ui_0286', 'ui_0282')):
                self.storage_ids.clear()
                self.refresh_storage_list()
    def build_discoveries_tab(self):
        # ***<module>.CDS3SaveEditorApp.build_discoveries_tab: Failure: Different bytecode
        parent = self.tab_discoveries
        top_f = tk.Frame(parent, pady=4)
        top_f.pack(side=tk.TOP, fill=tk.X, padx=10)
        tk.Label(top_f, text=ui('ui_0250')).pack(side=tk.LEFT, padx=2)
        category_values = [ui('ui_0364'), *DISCOVERY_CATEGORY_NAMES]
        self.cbo_disc_cat = ttk.Combobox(top_f, values=category_values, state='readonly', width=9)
        self.cbo_disc_cat.current(0)
        self.cbo_disc_cat.pack(side=tk.LEFT, padx=2)
        self.cbo_disc_cat.bind('<<ComboboxSelected>>', lambda e: self.refresh_discoveries_table())
        tk.Label(top_f, text=ui('ui_0260')).pack(side=tk.LEFT, padx=2)
        self.cbo_disc_status = ttk.Combobox(top_f, values=discovery_status_options(include_all=True), state='readonly', width=13)
        self.cbo_disc_status.current(0)
        self.cbo_disc_status.pack(side=tk.LEFT, padx=2)
        self.cbo_disc_status.bind('<<ComboboxSelected>>', lambda e: self.refresh_discoveries_table())
        tk.Label(top_f, text=ui('ui_0251')).pack(side=tk.LEFT, padx=2)
        disc_search_host = tk.Frame(top_f, width=78, height=23)
        disc_search_host.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        self.txt_disc_search = NativeWinEdit(
            disc_search_host,
            lambda: self._schedule_search_refresh('discoveries', self.refresh_discoveries_table),
            width=78, height=23,
        )
        self.lbl_disc_count = None
        batch_f = tk.Frame(top_f)
        batch_f.pack(side=tk.RIGHT, padx=2)
        tk.Label(batch_f, text=ui('ui_0447')).pack(side=tk.LEFT, padx=(0, 2))
        self.cbo_batch_status = ttk.Combobox(batch_f, values=discovery_status_options(), state='readonly', width=13)
        self.cbo_batch_status.current(0)
        self.cbo_batch_status.pack(side=tk.LEFT, padx=(0, 2))
        EditorButton(batch_f, text=ui('ui_0243'), font=('Malgun Gothic', 9), bg='#E6F4EA', fg='#137333', command=self.apply_batch_discovery_state).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(batch_f, text=ui('ui_0444')).pack(side=tk.LEFT, padx=(0, 2))
        self.cbo_batch_hint_status = ttk.Combobox(batch_f, values=(ui('ui_0445'), ui('ui_0446')), state='readonly', width=8)
        self.cbo_batch_hint_status.current(0)
        self.cbo_batch_hint_status.pack(side=tk.LEFT, padx=(0, 2))
        EditorButton(batch_f, text=ui('ui_0243'), font=('Malgun Gothic', 9), bg='#E6F4EA', fg='#137333', command=self.apply_batch_discovery_hint_state).pack(side=tk.LEFT)
        tree_f = tk.Frame(parent)
        tree_f.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        cols = ('index', 'game_id', 'category', 'name', 'hint_state', 'status', 'found_date', 'reported_date', 'reporter')
        self.tree_disc = ttk.Treeview(tree_f, columns=cols, show='headings', height=18)
        self.tree_disc.heading('index', text=TREE_COLUMN_TITLES['discovery']['index'])
        self.tree_disc.heading('game_id', text=TREE_COLUMN_TITLES['discovery']['game_id'])
        self.tree_disc.heading('category', text=TREE_COLUMN_TITLES['discovery']['category'])
        self.tree_disc.heading('name', text=TREE_COLUMN_TITLES['discovery']['name'])
        self.tree_disc.heading('hint_state', text=TREE_COLUMN_TITLES['discovery']['hint_state'])
        self.tree_disc.heading('status', text=TREE_COLUMN_TITLES['discovery']['status'])
        self.tree_disc.heading('found_date', text=TREE_COLUMN_TITLES['discovery']['found_date'])
        self.tree_disc.heading('reported_date', text=TREE_COLUMN_TITLES['discovery']['reported_date'])
        self.tree_disc.heading('reporter', text=TREE_COLUMN_TITLES['discovery']['reporter'])
        col_defs_disc = [('index', 55, 'center', False), ('game_id', 55, 'center', False), ('category', 120, 'center', False), ('name', 170, 'w', True), ('hint_state', 115, 'center', False), ('status', 135, 'center', False), ('found_date', 115, 'center', False), ('reported_date', 115, 'center', False), ('reporter', 125, 'center', False)]
        for c, w, a, s in col_defs_disc:
            self.tree_disc.column(c, width=w, anchor=a, stretch=s)
        sb_dy = ttk.Scrollbar(tree_f, orient=tk.VERTICAL, command=self.tree_disc.yview)
        self.tree_disc.configure(yscrollcommand=sb_dy.set)
        sb_dy.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_disc.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree_disc.bind('<Return>', self.cycle_selected_discovery_state)
        self.tree_disc.bind('<Double-1>', self.on_discovery_double_click)
        self.tree_disc.bind('<Button-3>', self.show_discovery_context_menu)
    def get_player_full_name(self):
        f = self.txt_first_name.get().strip()
        l = self.txt_last_name.get().strip()
        if f and l:
            return f'{f}·{l}'
        else:
            return f if f else ui('ui_0374')
    def get_current_game_date_str(self):
        try:
            y = self.spn_game_y.get() if hasattr(self, 'spn_game_y') and self.spn_game_y.get() else '1480'
            m = self.spn_game_m.get() if hasattr(self, 'spn_game_m') and self.spn_game_m.get() else '1'
            d = self.spn_game_d.get() if hasattr(self, 'spn_game_d') and self.spn_game_d.get() else '1'
            return format_game_date(int(y), int(m), int(d))
        except Exception:
            return ui('ui_0375')
    def refresh_discoveries_table(self):
        # irreducible cflow, using cdg fallback
        # ***<module>.CDS3SaveEditorApp.refresh_discoveries_table: Failure: Different control flow
        cat_sel = self.cbo_disc_cat.get()
        stat_sel = self.cbo_disc_status.get()
        search = self.txt_disc_search.get().strip().casefold()
        p_name = self.get_player_full_name() if self.file_buffer else UI_EMPTY_VALUE
        view_key = (bool(self.file_buffer), cat_sel, stat_sel, search,
                    self._discovery_view_revision, p_name)
        if (getattr(self, '_discovery_view_cache', object()) == view_key
                and self.tree_disc.get_children()):
            return
        self.tree_disc.delete(*self.tree_disc.get_children())
        aliases = ()
        if search:
            aliases = [search]
            if '제로니모' in search:
                aliases.append(search.replace('제로니모', '제도니모'))
            if '제도니모' in search:
                aliases.append(search.replace('제도니모', '제로니모'))
            if '헤로니모' in search:
                aliases.append(search.replace('헤로니모', '제도니모'))
        # 아래 반복문에서 모든 행에 동일하게 적용되는 필터는 한 번만 해석한다.
        category_filter = None if cat_sel.startswith(ui('ui_0364')) else cat_sel.split(' ', 1)[0]
        selected_state = discovery_state_from_text(stat_sel) if self.file_buffer else None
        discovery_states = self.discovery_state
        discovery_discoverers = self.discovery_discoverer
        discovery_dates = self.discovery_disc_date
        report_dates = self.discovery_rep_date
        active_contract = self._active_sponsor_contract() if self.file_buffer else None
        active_contract_disc_index = (
            int(active_contract[2]['index'])
            if active_contract is not None and active_contract[2] is not None else None)
        rep_cnt = 0
        disc_cnt = 0
        for i, d, search_key in self._discovery_search_index:
            st = discovery_states[i] if self.file_buffer else 0
            if self.file_buffer:
                if st == 3:
                    rep_cnt += 1
                else:
                    if st == 2:
                        disc_cnt += 1
            if category_filter is not None and d['category'] != category_filter:
                continue
            if self.file_buffer:
                if selected_state is not None and st != selected_state:
                    continue
            if search:
                if not any(alias in search_key for alias in aliases):
                    continue
            if self.file_buffer:
                st_text = discovery_state_text(st)
                hint_text = hint_state_text(self.file_buffer, d['hint_id'])
                if active_contract_disc_index == int(d['index']):
                    hint_text = ui('ui_0458')
                d_name = discovery_discoverers[i] if discovery_discoverers[i] else p_name if st > 1 else UI_EMPTY_VALUE
                disc_d = discovery_dates[i]
                rep_d = report_dates[i]
            else:
                st_text = UI_EMPTY_VALUE
                hint_text = UI_EMPTY_VALUE
                d_name = UI_EMPTY_VALUE
                disc_d = UI_EMPTY_VALUE
                rep_d = UI_EMPTY_VALUE
            self.tree_disc.insert('', tk.END, iid=str(i), values=(d['index'], d['disc_id'], d['category'], d['name'], hint_text, st_text, disc_d, rep_d, d_name))
        total = len(self.discovery_db)
        if self.file_buffer:
            pct = (rep_cnt + disc_cnt) / total * 100.0 if total > 0 else 0
            if self.lbl_disc_count is not None:
                self.lbl_disc_count.config(text=ui('ui_0036', rep_cnt, disc_cnt, total, pct))
        else:
            if self.lbl_disc_count is not None:
                self.lbl_disc_count.config(text=ui('ui_0036', 0, 0, total, 0.0))
        self._discovery_view_cache = view_key
        self._schedule_treeview_autofit(self.tree_disc)
    def set_discovery_single_state(self, idx, target_st):
        if not self.file_buffer:
            return
        else:
            self.discovery_state[idx] = target_st
            p_name = self.get_player_full_name()
            cur_date_str = self.get_current_game_date_str()
            if target_st == 3:
                self.discovery_discoverer[idx] = p_name
                if self.discovery_disc_date[idx] == UI_EMPTY_VALUE:
                    self.discovery_disc_date[idx] = cur_date_str
                self.discovery_rep_date[idx] = cur_date_str
            else:
                if target_st == 2:
                    self.discovery_discoverer[idx] = p_name
                    self.discovery_disc_date[idx] = cur_date_str
                    self.discovery_rep_date[idx] = UI_EMPTY_VALUE
                else:
                    self.discovery_discoverer[idx] = ''
                    self.discovery_disc_date[idx] = UI_EMPTY_VALUE
                    self.discovery_rep_date[idx] = UI_EMPTY_VALUE
            self.sync_sea_monster_from_discovery(self.discovery_db[idx]['index'], target_st > 1)
            contract_completed = (
                target_st == 3 and
                self._complete_sponsor_contract_for_discovery(self.discovery_db[idx]['index']))
            self._discovery_view_revision += 1
            self.refresh_discoveries_table()
            self.tree_disc.selection_set(str(idx))
            if contract_completed:
                self.lbl_status.config(text=ui('ui_0461'))
    def cycle_selected_discovery_state(self, _event=None):
        """Enter: 미등장 → 미발견 → 발견 → 보고 완료 순으로 즉시 전환한다."""
        if not self.file_buffer:
            return 'break'
        sel = self.tree_disc.selection()
        if sel:
            idx = int(sel[0])
            self.set_discovery_single_state(idx, (self.discovery_state[idx] + 1) % 4)
        return 'break'
    def on_discovery_double_click(self, event):
        if not self.file_buffer:
            return
        else:
            item = self.tree_disc.identify_row(event.y)
            if item:
                idx = int(item)
                self.open_discovery_info_modal(idx)
    def open_discovery_info_modal(self, idx):
        # ***<module>.CDS3SaveEditorApp.open_discovery_info_modal: Failure: Compilation Error
        items_list = []
        current_idx = 0
        for iid in self.tree_disc.get_children():
            try:
                d_idx = int(iid)
                items_list.append(d_idx)
                if d_idx == idx:
                    current_idx = len(items_list) - 1
            except Exception:
                continue
        if not items_list:
            items_list = [idx]
            current_idx = 0
        def get_disc_info_fn(d_idx):
            if 0 <= d_idx < len(self.discovery_db):
                    d = self.discovery_db[d_idx]
                    desc = DISCOVERY_DESCRIPTIONS.get(d['index'], '')
                    st = self.discovery_state[d_idx] if self.file_buffer else 0
                    p_name = self.get_player_full_name() if self.file_buffer else UI_EMPTY_VALUE
                    d_name = self.discovery_discoverer[d_idx] if self.file_buffer and self.discovery_discoverer[d_idx] else p_name if st > 1 else UI_EMPTY_VALUE
                    disc_d = self.discovery_disc_date[d_idx] if self.file_buffer else UI_EMPTY_VALUE
                    rep_d = self.discovery_rep_date[d_idx] if self.file_buffer else UI_EMPTY_VALUE
                    return (d, desc, st, disc_d, rep_d, d_name)
            return (None, '', 0, UI_EMPTY_VALUE, UI_EMPTY_VALUE, UI_EMPTY_VALUE)
        def on_navigate_fn(d_idx):
            try:
                if self.tree_disc.exists(str(d_idx)):
                    self.tree_disc.selection_set(str(d_idx))
                    self.tree_disc.see(str(d_idx))
            except Exception:
                return None
        def on_state_change(d_idx, target_st):
            if self.file_buffer:
                self.set_discovery_single_state(d_idx, target_st)
        def get_hint_state(hint_id):
            if not self.file_buffer or not 0 <= hint_id < len(HINT_STATE_OFFSETS):
                return 0
            offset = HINT_STATE_OFFSETS[hint_id]
            return self.file_buffer[offset] if 0 <= offset < len(self.file_buffer) else 0
        def on_hint_toggle(d_idx):
            if not self.file_buffer or not 0 <= d_idx < len(self.discovery_db):
                return
            hint_id = int(self.discovery_db[d_idx].get('hint_id', -1))
            if not 0 <= hint_id < len(HINT_STATE_OFFSETS):
                return
            offset = HINT_STATE_OFFSETS[hint_id]
            if not 0 <= offset < len(self.file_buffer):
                return
            # 0x08(미획득)↔0x0D(획득)의 차이인 bit0·bit2를 함께 뒤집는다.
            # 발견 완료 비트(bit1)는 보존한다.
            self.file_buffer[offset] ^= 0x05
            self._discovery_view_revision += 1
            self.refresh_discoveries_table()
        def on_contract_cancel(_d_idx):
            self.cancel_sponsor_contract_from_hint()
            self._discovery_view_revision += 1
            self.refresh_discoveries_table()
        def is_contract_discovery(d_idx):
            contract = self._active_sponsor_contract()
            if contract is None or not 0 <= d_idx < len(self.discovery_db):
                return False
            _sponsor_id, _sponsor, discovery = contract
            return discovery is not None and int(discovery['index']) == int(self.discovery_db[d_idx]['index'])
        d, desc, st, disc_d, rep_d, d_name = get_disc_info_fn(idx)
        if d:
            DiscoveryInfoModal(
                self.root, d, desc, current_state=st, disc_date=disc_d,
                rep_date=rep_d, discoverer=d_name,
                on_state_change_callback=on_state_change if self.file_buffer else None,
                on_hint_toggle_callback=on_hint_toggle if self.file_buffer else None,
                on_contract_cancel_callback=on_contract_cancel if self.file_buffer else None,
                is_contract_discovery_fn=is_contract_discovery if self.file_buffer else None,
                get_hint_state_fn=get_hint_state,
                items_list=items_list, current_list_index=current_idx,
                get_disc_info_fn=get_disc_info_fn, on_navigate_callback=on_navigate_fn,
                state_index=idx,
            )
    def show_discovery_context_menu(self, event):
        if not self.file_buffer:
            return
        else:
            item = self.tree_disc.identify_row(event.y)
            if item:
                self.tree_disc.selection_set(item)
                self._popup_discovery_menu(int(item), event.x_root, event.y_root)
    def _popup_discovery_menu(self, idx, x, y):
        # ***<module>.CDS3SaveEditorApp._popup_discovery_menu: Failure: Different bytecode
        d_name = self.discovery_db[idx]['name']
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label=ui('ui_0294', d_name), state='disabled')
        menu.add_separator()
        menu.add_command(label=discovery_state_text(0, menu=True), command=lambda: self.set_discovery_single_state(idx, 0))
        menu.add_command(label=discovery_state_text(1, menu=True), command=lambda: self.set_discovery_single_state(idx, 1))
        menu.add_command(label=discovery_state_text(2, menu=True), command=lambda: self.set_discovery_single_state(idx, 2))
        menu.add_command(label=discovery_state_text(3, menu=True), command=lambda: self.set_discovery_single_state(idx, 3))
        menu.tk_popup(x, y)
    def apply_batch_discovery_state(self):
        if not self.file_buffer:
            return
        else:
            target_st = discovery_state_from_text(self.cbo_batch_status.get())
            if target_st is None:
                return
            self.batch_set_discovery_state(target_st)

    def apply_batch_discovery_hint_state(self):
        """힌트가 연결된 발견물 전체의 획득 여부만 일괄 변경한다."""
        if not self.file_buffer:
            return
        acquired = self.cbo_batch_hint_status.get() == ui('ui_0445')
        changed = False
        for discovery in self.discovery_db:
            hint_id = int(discovery.get('hint_id', -1))
            if not 0 <= hint_id < len(HINT_STATE_OFFSETS):
                continue
            offset = HINT_STATE_OFFSETS[hint_id]
            if not 0 <= offset < len(self.file_buffer):
                continue
            before = self.file_buffer[offset]
            # bit1(발견 완료)은 유지하고, bit0·bit2만 획득 여부로 맞춘다.
            self.file_buffer[offset] = (before | 0x05) if acquired else (before & ~0x05)
            changed = changed or before != self.file_buffer[offset]
        if changed:
            self._discovery_view_revision += 1
            self.refresh_discoveries_table()

    def batch_set_discovery_state(self, target_st):
        if not self.file_buffer:
            return
        else:
            p_name = self.get_player_full_name()
            cur_date_str = self.get_current_game_date_str()
            for i in range(len(self.discovery_db)):
                self.discovery_state[i] = target_st
                if target_st == 3:
                    self.discovery_discoverer[i] = p_name
                    if self.discovery_disc_date[i] == UI_EMPTY_VALUE:
                        self.discovery_disc_date[i] = cur_date_str
                    self.discovery_rep_date[i] = cur_date_str
                else:
                    if target_st == 2:
                        self.discovery_discoverer[i] = p_name
                        self.discovery_disc_date[i] = cur_date_str
                        self.discovery_rep_date[i] = UI_EMPTY_VALUE
                    else:
                        self.discovery_discoverer[i] = ''
                        self.discovery_disc_date[i] = UI_EMPTY_VALUE
                        self.discovery_rep_date[i] = UI_EMPTY_VALUE
                self.sync_sea_monster_from_discovery(self.discovery_db[i]['index'], target_st > 1)
                if target_st == 3:
                    self._complete_sponsor_contract_for_discovery(self.discovery_db[i]['index'])
            self._discovery_view_revision += 1
            self.refresh_discoveries_table()
    def sync_sea_monster_from_discovery(self, d_idx, is_encountered):
        for m_idx, (m_off, m_desc, m_didx) in enumerate(SEA_MONSTERS):
            if d_idx == m_didx:
                self.sea_monster_state[m_idx] = is_encountered
    def build_events_tab(self):
        # ***<module>.CDS3SaveEditorApp.build_events_tab: Failure: Different bytecode
        parent = self.tab_events
        top_f = tk.Frame(parent, pady=4)
        top_f.pack(side=tk.TOP, fill=tk.X, padx=10)
        tk.Label(top_f, text=ui('ui_0262'), font=('Malgun Gothic', 9)).pack(side=tk.LEFT, padx=4)
        self.cbo_batch_event_status = ttk.Combobox(top_f, values=EDITOR_MAPPINGS['event_batch_status_options'], state='readonly', width=16)
        self.cbo_batch_event_status.current(0)
        self.cbo_batch_event_status.pack(side=tk.LEFT, padx=4)
        EditorButton(top_f, text=ui('ui_0243'), font=('Malgun Gothic', 9), bg='#E6F4EA', fg='#137333', command=self.apply_batch_event_state).pack(side=tk.LEFT, padx=4)
        tree_f = tk.Frame(parent)
        tree_f.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        cols = ('game_id', 'name', 'status')
        self.tree_events = ttk.Treeview(tree_f, columns=cols, show='headings', height=10)
        self.tree_events.heading('game_id', text=TREE_COLUMN_TITLES['event']['game_id'])
        self.tree_events.heading('name', text=TREE_COLUMN_TITLES['event']['name'])
        self.tree_events.heading('status', text=TREE_COLUMN_TITLES['event']['status'])
        col_defs_events = [('game_id', 60, 'center', False), ('name', 530, 'w', True), ('status', 330, 'center', False)]
        for c, w, a, s in col_defs_events:
            self.tree_events.column(c, width=w, anchor=a, stretch=s)
        self.tree_events.pack(fill=tk.BOTH, expand=True)
        self.tree_events.bind('<Return>', self.toggle_selected_event_state)
        self.tree_events.bind('<Double-1>', self.toggle_selected_event_state)
        self.tree_events.bind('<Button-3>', self.show_event_context_menu)
    def refresh_events_table(self):
        self.tree_events.delete(*self.tree_events.get_children())
        for i, ev in enumerate(self.event_db):
            if self.file_buffer:
                st = self.event_state[i]
                st_str = event_state_text(st)
            else:
                st_str = UI_EMPTY_VALUE
            self.tree_events.insert('', tk.END, iid=str(i), values=(f'{ev['disc_id']:03d}', ev['name'], st_str))
        self._schedule_treeview_autofit(self.tree_events)
    def set_event_single_state(self, idx, target_st):
        if not self.file_buffer:
            return
        else:
            self.event_state[idx] = target_st
            self.refresh_events_table()
            self.tree_events.selection_set(str(idx))
    def toggle_selected_event_state(self, _event=None):
        """Enter: 이벤트 완료/미발생 상태를 즉시 서로 전환한다."""
        if not self.file_buffer:
            return 'break'
        sel = self.tree_events.selection()
        if sel:
            idx = int(sel[0])
            self.set_event_single_state(idx, 0 if self.event_state[idx] else 1)
        return 'break'
    def show_event_context_menu(self, event):
        if not self.file_buffer:
            return
        else:
            item = self.tree_events.identify_row(event.y)
            if item:
                self.tree_events.selection_set(item)
                self._popup_event_menu(int(item), event.x_root, event.y_root)
    def _popup_event_menu(self, idx, x, y):
        # ***<module>.CDS3SaveEditorApp._popup_event_menu: Failure: Different bytecode
        ev_name = self.event_db[idx]['name']
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label=ui('ui_0294', ev_name), state='disabled')
        menu.add_separator()
        menu.add_command(label=event_state_text(1, menu=True), command=lambda: self.set_event_single_state(idx, 1))
        menu.add_command(label=event_state_text(0, menu=True), command=lambda: self.set_event_single_state(idx, 0))
        menu.tk_popup(x, y)
    def apply_batch_event_state(self):
        if not self.file_buffer:
            return
        else:
            target_st = 0 if self.cbo_batch_event_status.current() == 1 else 1
            self.batch_set_event_state(target_st)
    def batch_set_event_state(self, target_st):
        if not self.file_buffer:
            return
        else:
            for i in range(len(self.event_db)):
                self.event_state[i] = target_st
            self.refresh_events_table()
    def _set_widget_state_recursive(self, widget, state):
        for child in widget.winfo_children():
            try:
                if isinstance(child, (ttk.Button, ttk.Entry, ttk.Checkbutton, ttk.Combobox, ttk.Spinbox)):
                    child.state(['!disabled' if state == tk.NORMAL else 'disabled'])
                else:
                    if isinstance(child, (tk.Button, tk.Entry, tk.Checkbutton, tk.Radiobutton, tk.Spinbox)):
                        child.config(state=state)
            except Exception:
                pass
            self._set_widget_state_recursive(child, state)
    def set_controls_enabled(self, enabled):
        state = tk.NORMAL if enabled else tk.DISABLED
        self.btn_save.config(state=state)
        self.chk_backup_widget.config(state=state)
        tabs = [self.tab_profile, self.tab_skills, self.tab_fleet, self.tab_cities, self.tab_items, self.tab_discoveries, self.tab_events]
        for tab in tabs:
            self._set_widget_state_recursive(tab, state)
        for attr_name in ('txt_last_name', 'txt_first_name', 'cbo_wife', 'cbo_officer_name', 'cbo_person_search'):
            entry = getattr(self, attr_name, None)
            if isinstance(entry, NativeWinEdit):
                entry.set_enabled(enabled)
    def set_entry_text(self, entry, text):
        if isinstance(entry, NativeWinEdit):
            entry.set(text)
            return
        prev_state = entry.cget('state') if 'state' in entry.keys() else None
        if prev_state == 'disabled':
            entry.config(state='normal')
        entry.delete(0, tk.END)
        entry.insert(0, str(text))
        if prev_state == 'disabled':
            entry.config(state='disabled')
    def set_spin_val(self, spin, val):
        prev_state = spin.state()
        if 'disabled' in prev_state:
            spin.state(['!disabled'])
        spin.delete(0, tk.END)
        spin.insert(0, str(val))
        if 'disabled' in prev_state:
            spin.state(['disabled'])
        if spin in (getattr(self, 'spn_birth_y', None), getattr(self, 'spn_birth_m', None), getattr(self, 'spn_birth_d', None)):
            picker = getattr(self, 'birth_date_picker', None)
            if picker is not None:
                picker.refresh()
        elif spin in (getattr(self, 'spn_game_y', None), getattr(self, 'spn_game_m', None), getattr(self, 'spn_game_d', None)):
            picker = getattr(self, 'game_date_picker', None)
            if picker is not None:
                picker.refresh()
    def on_open_file(self):
        # ***<module>.CDS3SaveEditorApp.on_open_file: Failure: Different bytecode
        file_path = filedialog.askopenfilename(title=ui('ui_0187'), filetypes=[(ui('ui_0265'), '*.CDS;*.SAV;*.cds;*.sav'), (ui('ui_0266'), '*.*')])
        if file_path:
            self.load_save_file(file_path)

    def load_save_file(self, file_path):
        """Load the original CDS offsets, matching the recovered bytecode."""
        # 함대 탭에서 영상이 재생 중일 수 있으므로, 로드 중에는 영상 갱신을 보류한다.
        self._suspend_fleet_preview = True
        # 컨트롤 채우기 중의 trace 갱신은 마지막 명시적 갱신 한 번으로 합친다.
        self._is_loading_save = True
        self._suspend_tree_autofit = True
        try:
            with open(file_path, 'rb') as f:
                self.file_buffer = bytearray(f.read())
            self.file_path = file_path
            self._sponsor_contract_hint_resets.clear()
            # 스폰서 취향은 세이브가 아니라 게임 EXE의 정적 표에 있다.
            # 같은 폴더의 EXE를 검증해 읽고, 없거나 다른 버전이면 JSON 백업값을 쓴다.
            self._sponsor_exe_preference_flags = (
                read_sponsor_preferences_from_game_exe(os.path.dirname(file_path)) or {})
            # 이전 목록에서 보고 있던 인물은 미리보기용 상태일 뿐이다. 새 파일을
            # 열 때 남아 있으면 0xA5의 실제 부관 대신 그 인물이 다시 선택된다.
            self._officer_preview_id = None
            self._officer_selected_id = None
            # 부인 목록도 이전 파일의 선택 상태를 버린 뒤 0xAD의 배우자 값으로
            # 다시 선택한다. 검색창은 검색 전용이므로 계속 비워 둔다.
            self._wife_selected_id = None
            # 함선 정보의 되돌리기는 이 최초 로드본을 기준으로 한다.
            self.fleet_original_buffer = bytes(self.file_buffer)
            self.city_original_buffer = bytes(self.file_buffer)
            self.person_original_buffer = bytes(self.file_buffer)
            # 통합 인물 목록은 로드한 세이브 원본을 별도 보관해 표시한다.
            self.person_display_buffer = bytes(self.file_buffer)
            self.set_controls_enabled(True)

            def read_cp949(buf, off, max_len):
                return buf[off:off + max_len].split(b'\x00')[0].decode('cp949', errors='ignore').strip()

            self.set_entry_text(self.txt_first_name, read_cp949(self.file_buffer, 95, 18))
            self.set_entry_text(self.txt_last_name, read_cp949(self.file_buffer, 114, 18))
            gy = struct.unpack_from('<H', self.file_buffer, 21)[0]
            gm, gd = self.file_buffer[25], self.file_buffer[26]
            self.set_spin_val(self.spn_game_y, gy if gy > 0 else 1480)
            self.set_spin_val(self.spn_game_m, gm if gm > 0 else 1)
            self.set_spin_val(self.spn_game_d, gd if gd > 0 else 1)
            by = struct.unpack_from('<H', self.file_buffer, 149)[0]
            bm, bd = self.file_buffer[151], self.file_buffer[152]
            self.set_spin_val(self.spn_birth_y, by if by > 0 else 1450)
            self.set_spin_val(self.spn_birth_m, bm if bm > 0 else 1)
            self.set_spin_val(self.spn_birth_d, bd if bd > 0 else 1)

            job = struct.unpack_from('<H', self.file_buffer, 137)[0]
            self.cbo_job.current(job if 0 <= job < len(JOB_NAMES) else 0)
            blood = struct.unpack_from('<H', self.file_buffer, 141)[0]
            self.cbo_blood.current(blood if 0 <= blood < len(BLOOD_NAMES) else 0)
            self.update_wife_combo_options()
            nation = struct.unpack_from('<H', self.file_buffer, 139)[0]
            if nation > 1:
                self.chk_all_nations.set(True)
                self.toggle_all_nations()
            self.cbo_nation.current(nation if 0 <= nation < len(self.cbo_nation['values']) else 0)
            face_id = struct.unpack_from('<H', self.file_buffer, 133)[0]
            self.player_face_id = face_id if 0 <= face_id < 410 else 13
            self.update_player_face_display()
            self._refresh_sponsor_contract_display()

            spouse_code = struct.unpack_from('<H', self.file_buffer, 173)[0]
            if spouse_code == 0xFFFF or (spouse_code & 0xFF00) != 0x2000:
                self._set_wife_combo()
            else:
                barmaid_id = spouse_code & 0x7F
                self._set_wife_combo(barmaid_id)
            self.update_wife_display()
            # 새 세이브를 열 때는 이전 파일에서 사용한 검색/고용 필터를 유지하지
            # 않는다. 목록을 새 버퍼 기준으로 만든 후 현재 부관 행을 선택해야 한다.
            if hasattr(self, 'cbo_officer_category'):
                self.cbo_officer_category.current(0)
            if hasattr(self, 'cbo_officer_name'):
                self.cbo_officer_name.set('')
            self._refresh_officer_search_results()
            self.refresh_officer_display()
            self._refresh_all_crew_profiles(reset_filters=True, refresh_lists=True)

            self.stat_values = list(self.file_buffer[45:51]) + [struct.unpack_from('<I', self.file_buffer, 51)[0]]
            self.refresh_stats_table()
            self.money_values = [
                min(99999999, struct.unpack_from('<I', self.file_buffer, offset)[0])
                for offset in (153, 157, 161)
            ] + [
                struct.unpack_from('<I', self.file_buffer, offset)[0]
                for offset in (83, 87)
            ]
            self.refresh_money_table()
            self.skill_levels = [min(3, max(0, self.file_buffer[56 + i])) for i in range(len(SKILLS_DATA))]
            self.refresh_skills_table()
            self.pocket_ids = [
                item_id for i in range(16)
                if (item_id := struct.unpack_from('<H', self.file_buffer, 175 + i * 2)[0]) != 0xFFFF
            ]
            self.storage_ids = [
                item_id for i in range(99)
                if (item_id := struct.unpack_from('<H', self.file_buffer, 207 + i * 2)[0]) != 0xFFFF
            ]
            self.refresh_pocket_list()
            self.refresh_storage_list()
            self.event_state = [int(self.file_buffer[e['save_offset']] != 0 or self.file_buffer[e['save_offset'] + 1] != 0)
                                for e in self.event_db]
            self.refresh_events_table()
            self.sea_monster_state = [bool(self.file_buffer[offset]) for offset, _, _ in SEA_MONSTERS]

            self.discovery_state = [0] * len(self.discovery_db)
            self.discovery_discoverer = [''] * len(self.discovery_db)
            self.discovery_disc_date = [UI_EMPTY_VALUE] * len(self.discovery_db)
            self.discovery_rep_date = [UI_EMPTY_VALUE] * len(self.discovery_db)
            for i, discovery in enumerate(self.discovery_db):
                off = discovery['save_offset']
                marker = self.file_buffer[off - 1]
                # 세이브의 상태 마커는 미등장 0x00, 미발견 0x0C, 발견 0x4C,
                # 보고 완료 0xCC이다. 상위 비트 검사는 기존 0x40/0xC0 형식도
                # 함께 읽기 위해 사용한다.
                has_rep = (marker & 0xC0) == 0xC0
                has_disc = (marker & 0x40) != 0
                if has_disc:
                    dy = struct.unpack_from('<H', self.file_buffer, off + 40)[0]
                    self.discovery_disc_date[i] = format_game_date(dy if dy > 0 else gy, gm, gd)
                if has_rep:
                    ry = struct.unpack_from('<H', self.file_buffer, off + 134)[0]
                    self.discovery_rep_date[i] = format_game_date(ry if ry > 0 else gy, gm, gd)
                    self.discovery_state[i] = 3
                    self.discovery_discoverer[i] = read_cp949(self.file_buffer, off + 95, 18) or read_cp949(self.file_buffer, off + 1, 18)
                elif has_disc:
                    self.discovery_state[i] = 2
                    self.discovery_discoverer[i] = read_cp949(self.file_buffer, off + 1, 18)
                elif marker != 0:
                    self.discovery_state[i] = 1
                    self.discovery_discoverer[i] = read_cp949(self.file_buffer, off + 1, 18)
            self._discovery_view_revision += 1
            self.refresh_discoveries_table()
            self.refresh_fleet_list()
            self.refresh_cities_list()
            # 다른 목록·탭의 갱신이 끝난 다음 배우자 선택 표시를 확정한다.
            self.root.after_idle(self._focus_loaded_wife_in_list)
            # 통합 인물 화면도 새 세이브의 배우자·역할 슬롯을 기준으로 다시 선택한다.
            self.root.after_idle(self._refresh_person_browser)
            self.lbl_status.config(text=ui('ui_0366', os.path.basename(file_path)))
            self.root.title(f'{APP_TITLE} - [{os.path.basename(file_path)}]')
        except Exception as exc:
            messagebox.showerror(ui('ui_0367'), ui('ui_0368', exc))
        finally:
            self._is_loading_save = False
            self._suspend_tree_autofit = False
            # 전체 컨트롤 활성화로 바뀐 뒤에도 각 되돌리기 버튼은 원본과의 실제
            # 차이만 반영한다.
            self._update_player_restore_state()
            self._update_fleet_reset_state()
            self._update_city_reset_state()
            self._set_person_assignment_buttons_visible()
            # 로드 도중 표마다 중복 예약된 열맞춤은 여기서 한 번씩만 실행한다.
            self.root.after_idle(self._flush_pending_treeview_autofit)
            # Treeview의 선택 이벤트가 끝난 뒤에만 새 미디어를 연결한다.
            previous_job = getattr(self, '_fleet_preview_resume_job', None)
            if previous_job is not None:
                self.root.after_cancel(previous_job)
            self._fleet_preview_resume_job = self.root.after(300, self._resume_fleet_preview_after_load)

    def on_save_file(self):
        if not self.file_path or not self.file_buffer:
            self.on_open_file()
        else:
            self.save_to_path(self.file_path)
    def save_to_path(self, target_path):
        # ***<module>.CDS3SaveEditorApp.save_to_path: Failure: Different bytecode
        if self._selected_city_index() is not None and not self.apply_city_edits():
            return
        try:
            bak_msg = ''
            if self.chk_auto_backup.get() and os.path.exists(target_path):
                    bak_path = target_path + '.bak'
                    try:
                        with open(target_path, 'rb') as sf:
                            with open(bak_path, 'wb') as df:
                                df.write(sf.read())
                        bak_msg = ui('ui_0509', bak_path)
                    except Exception as bak_err:
                        print('Backup creation error:', bak_err)
            first_bytes = self.txt_first_name.get().strip().encode('cp949')
            last_bytes = self.txt_last_name.get().strip().encode('cp949')
            self.file_buffer[95:113] = b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            self.file_buffer[114:132] = b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            self.file_buffer[95:95 + min(len(first_bytes), 18)] = first_bytes[:18]
            self.file_buffer[114:114 + min(len(last_bytes), 18)] = last_bytes[:18]
            struct.pack_into('<H', self.file_buffer, 21, int(self.spn_game_y.get()))
            self.file_buffer[25] = int(self.spn_game_m.get())
            self.file_buffer[26] = int(self.spn_game_d.get())
            struct.pack_into('<H', self.file_buffer, 149, int(self.spn_birth_y.get()))
            self.file_buffer[151] = int(self.spn_birth_m.get())
            self.file_buffer[152] = int(self.spn_birth_d.get())
            struct.pack_into('<H', self.file_buffer, 137, self.cbo_job.current())
            struct.pack_into('<H', self.file_buffer, 141, self.cbo_blood.current())
            struct.pack_into('<H', self.file_buffer, 139, self.cbo_nation.current())
            if 135 <= len(self.file_buffer):
                struct.pack_into('<H', self.file_buffer, 133, self.player_face_id)
            if 175 <= len(self.file_buffer):
                wife_data = self._wife_from_combo_text()
                if wife_data is None:
                    struct.pack_into('<H', self.file_buffer, 173, 65535)
                else:
                    struct.pack_into('<H', self.file_buffer, 173, 8192 | wife_data['id'])
            for i in range(6):
                self.file_buffer[45 + i] = min(255, max(0, self.stat_values[i]))
            struct.pack_into('<I', self.file_buffer, 51, min(CHARACTER_SPECIAL_STAT_MAX, max(0, self.stat_values[6])))
            struct.pack_into('<I', self.file_buffer, 153, min(99999999, max(0, self.money_values[0])))
            struct.pack_into('<I', self.file_buffer, 157, min(99999999, max(0, self.money_values[1])))
            struct.pack_into('<I', self.file_buffer, 161, min(99999999, max(0, self.money_values[2])))
            struct.pack_into('<I', self.file_buffer, 83, min(PLAYER_REPUTATION_MAX, max(0, self.money_values[3])))
            struct.pack_into('<I', self.file_buffer, 87, min(PLAYER_REPUTATION_MAX, max(0, self.money_values[4])))
            for i in range(len(SKILLS_DATA)):
                self.file_buffer[56 + i] = self.skill_levels[i]
            for i in range(16):
                val = self.pocket_ids[i] if i < len(self.pocket_ids) else 65535
                struct.pack_into('<H', self.file_buffer, 175 + i * 2, val)
            for i in range(99):
                val = self.storage_ids[i] if i < len(self.storage_ids) else 65535
                struct.pack_into('<H', self.file_buffer, 207 + i * 2, val)
            p_name_bytes = self.get_player_full_name().encode('cp949')
            for i, ev in enumerate(self.event_db):
                e_off = ev['save_offset']
                if e_off + 164 <= len(self.file_buffer):
                    if self.event_state[i] == 1:
                        self.file_buffer[e_off] = 1
                        self.file_buffer[e_off + 1:e_off + 19] = b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
                        self.file_buffer[e_off + 1:e_off + 1 + min(len(p_name_bytes), 18)] = p_name_bytes[:18]
                        self.file_buffer[e_off + 88] = 255
                    else:
                        self.file_buffer[e_off:e_off + 164] = b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
            for i, (m_off, m_desc, m_didx) in enumerate(SEA_MONSTERS):
                if m_off < len(self.file_buffer):
                    self.file_buffer[m_off] = 1 if self.sea_monster_state[i] else 0
            p_name_bytes = self.get_player_full_name().encode('cp949')
            try:
                cur_y = int(self.spn_game_y.get())
                cur_m = int(self.spn_game_m.get())
                cur_d = int(self.spn_game_d.get())
            except Exception:
                cur_y, cur_m, cur_d = (1480, 1, 1)
            cur_date_bytes = bytes([cur_y & 255, cur_y >> 8 & 255, 0, 0, 1, 0, 0, 0])
            for i, d in enumerate(self.discovery_db):
                d_off = d['save_offset']
                if d_off + 164 <= len(self.file_buffer):
                    st = self.discovery_state[i]
                    marker_off = d_off - 1
                    # 미등장은 미발견(0x0C)과 달리 레코드 전체가 미등록 형식이다.
                    # 다음 발견물의 공유 상태 마커(d_off + 163)는 보존한다.
                    if st == 0:
                        self.file_buffer[marker_off] = 0
                        self.file_buffer[d_off:d_off + 163] = b'\x00' * 163
                        # 일반 미발견 레코드와 동일하게 날짜 미설정 필드는 FF로
                        # 남겨 둔다. 이 값까지 0으로 만들면 원래의 미등록 레코드와
                        # 달라져 백과사전 순서 판정에 영향을 줄 수 있다.
                        self.file_buffer[d_off + 40:d_off + 48] = b'\xff' * 8
                        self.file_buffer[d_off + 134:d_off + 142] = b'\xff' * 8
                        continue
                    if st == 3:
                        self.file_buffer[marker_off] = 204
                        self.file_buffer[d_off] = 1
                        self.file_buffer[d_off + 1:d_off + 19] = b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
                        self.file_buffer[d_off + 1:d_off + 1 + min(len(p_name_bytes), 18)] = p_name_bytes[:18]
                        if self.file_buffer[d_off + 40:d_off + 48] == b'\xff\xff\xff\xff\xff\xff\xff\xff':
                            self.file_buffer[d_off + 40:d_off + 48] = cur_date_bytes
                        self.file_buffer[d_off + 95:d_off + 113] = b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
                        self.file_buffer[d_off + 95:d_off + 95 + min(len(p_name_bytes), 18)] = p_name_bytes[:18]
                        self.file_buffer[d_off + 134:d_off + 142] = cur_date_bytes
                        self.file_buffer[d_off + 88] = 255
                        self.file_buffer[d_off + 87] = 211
                        struct.pack_into('<H', self.file_buffer, d_off + 36, cur_y)
                        struct.pack_into('<H', self.file_buffer, d_off + 84, cur_y)
                        # d_off + 163은 다음 발견물의 상태 마커이므로 건드리지 않는다.
                    else:
                        if st == 2:
                            self.file_buffer[marker_off] = 76
                            self.file_buffer[d_off] = 1
                            self.file_buffer[d_off + 1:d_off + 19] = b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
                            self.file_buffer[d_off + 1:d_off + 1 + min(len(p_name_bytes), 18)] = p_name_bytes[:18]
                            self.file_buffer[d_off + 40:d_off + 48] = cur_date_bytes
                            self.file_buffer[d_off + 95:d_off + 113] = b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
                            self.file_buffer[d_off + 134:d_off + 142] = b'\xff\xff\xff\xff\xff\xff\xff\xff'
                            self.file_buffer[d_off + 88] = 0
                            struct.pack_into('<H', self.file_buffer, d_off + 36, cur_y)
                            struct.pack_into('<H', self.file_buffer, d_off + 84, 0)
                        else:
                            self.file_buffer[marker_off] = 12
                            self.file_buffer[d_off:d_off + 164] = b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
                            self.file_buffer[d_off + 40:d_off + 48] = b'\xff\xff\xff\xff\xff\xff\xff\xff'
                            self.file_buffer[d_off + 134:d_off + 142] = b'\xff\xff\xff\xff\xff\xff\xff\xff'
                            struct.pack_into('<H', self.file_buffer, d_off + 36, 0)
                            struct.pack_into('<H', self.file_buffer, d_off + 84, 0)
            with open(target_path, 'wb') as f:
                f.write(self.file_buffer)
            # 저장에 성공한 뒤에만 통합 인물 화면의 표시 스냅샷을 편집 버퍼로
            # 갱신한다. 저장 전 역할/인물 편집은 목록 상세에 반영되지 않는다.
            self.person_display_buffer = bytes(self.file_buffer)
            if hasattr(self, 'tree_person_list'):
                self._refresh_person_browser()
            messagebox.showinfo(ui('ui_0369'), ui('ui_0370', target_path, bak_msg))
            self.lbl_status.config(text=ui('ui_0041', os.path.basename(target_path)))
        except Exception as e:
            messagebox.showerror(ui('ui_0211'), ui('ui_0042', str(e)))
    def open_barmaid_guide_html(self):
        """JSON과 초상화 경로를 제공하는 로컬 웹 서버로 여급 도감을 연다."""
        try:
            from functools import partial
            from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
            from urllib.parse import quote
            import webbrowser
            candidates = [os.path.join(os.path.dirname(os.path.abspath(__file__)), '대항해시대3_여급도감.html'), os.path.join(getattr(sys, '_MEIPASS', ''), 'Resources', '대항해시대3_여급도감.html'), os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Resources', '대항해시대3_여급도감.html')]
            target_path = None
            for p in candidates:
                if p and os.path.exists(p):
                        target_path = p
                        break
            if target_path:
                face_code = self.player_face_id if self.player_face_id is not None else 0
                age = 0
                if self.file_buffer:
                    try:
                        age = get_player_age(int(self.spn_game_y.get()), int(self.spn_game_m.get()), int(self.spn_game_d.get()), int(self.spn_birth_y.get()), int(self.spn_birth_m.get()), int(self.spn_birth_d.get()))
                    except Exception:
                        pass
                resource_root = os.path.dirname(target_path)

                # file:// 환경에서는 fetch()가 JSON 읽기를 차단하므로, localhost에서
                # Resources 폴더를 제공한다. 서버 스레드는 에디터 종료와 함께 끝난다.
                server = getattr(self, '_barmaid_web_server', None)
                if server is None or getattr(self, '_barmaid_web_root', None) != resource_root:
                    class QuietResourceHandler(SimpleHTTPRequestHandler):
                        def log_message(self, _format, *_args):
                            pass

                    handler = partial(QuietResourceHandler, directory=resource_root)
                    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
                    self._barmaid_web_server = server
                    self._barmaid_web_root = resource_root
                    import threading
                    threading.Thread(target=server.serve_forever, daemon=True).start()

                filename = quote(os.path.basename(target_path))
                webbrowser.open(f'http://127.0.0.1:{server.server_port}/{filename}?face={face_code}&age={age}')
            else:
                messagebox.showinfo(ui('ui_0103'), ui('ui_0210'))
        except Exception as e:
            messagebox.showerror(ui('ui_0211'), ui('ui_0043', e))
    def update_wife_combo_options(self):
        # irreducible cflow, using cdg fallback
        """아내 콤보박스 항목 갱신"""
        # ***<module>.CDS3SaveEditorApp.update_wife_combo_options: Failure: Different control flow
        current = self._wife_from_combo_text() if hasattr(self, 'cbo_wife') else None
        current_id = current['id'] if current else getattr(self, '_wife_selected_id', None)
        self._wife_name_options = [barmaid['name'] for barmaid in BARMAID_DATABASE]
        if hasattr(self, 'cbo_wife'):
            self._set_wife_combo(current_id)
        self.update_wife_display()
if __name__ == '__main__':
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass
    root = tk.Tk()
    icon_path = get_app_icon_path()
    if icon_path:
        try:
            root.iconbitmap(default=icon_path)
        except tk.TclError:
            pass
    app = CDS3SaveEditorApp(root)

    # PyInstaller 단일 파일 실행 시: 메인 창이 화면에 준비된 뒤 로딩 화면을 닫는다.
    def close_startup_splash():
        try:
            import pyi_splash
            pyi_splash.close()
        except (ImportError, RuntimeError):
            pass

    root.after(0, close_startup_splash)
    root.mainloop()
    # libVLC가 만든 작업 스레드가 해제에 응답하지 않아도 창 닫기는 지연되지 않는다.
    os._exit(0)
