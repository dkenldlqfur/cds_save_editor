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
from functools import lru_cache
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import tkinter.font as tkfont
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
    raise FileNotFoundError(f'필수 데이터 파일을 찾을 수 없습니다: {filename}')


GAME_MASTER_DATA = load_json_resource('master_data.json')
CHARACTER_DATA = load_json_resource('character_database.json')
FLEET_DATA = load_json_resource('fleet_data.json')
CITY_DATA = load_json_resource('city_data.json')
GAME_STRINGS = load_json_resource('game_strings.json')
TRADE_GOODS_DATA = load_json_resource('trade_goods.json')
DISCOVERY_TRADE_GOOD_DATA = load_json_resource('discovery_trade_goods.json')
DATA_CATEGORIES = load_json_resource('data_categories.json')
DISCOVERY_REWARD_DATA = load_json_resource('discovery_reward_items.json')
APP_CONFIG = load_json_resource('app_config.json')
UI_TEXTS = load_json_resource('ui_texts.json')['texts']

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


DISCOVERY_STATE_TEXT_KEYS = {0: 'ui_0112', 1: 'ui_0110', 2: 'ui_0071'}
DISCOVERY_STATE_ACTION_KEYS = {0: 'ui_0111', 1: 'ui_0110', 2: 'ui_0109'}


def discovery_state_text(state, action=False, menu=False):
    """세이브의 발견물 상태값을 화면용 문구 하나로 변환한다."""
    if menu and state == 0:
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
    options = [discovery_state_text(state) for state in (2, 1, 0)]
    return [ui('ui_0291'), *options] if include_all else options


def event_state_text(state, menu=False):
    if menu and not state:
        return ui('ui_0186')
    return ui('ui_0185') if state else ui('ui_0206')

BARMAID_DATABASE = GAME_MASTER_DATA['barmaid_database']
BARMAID_BY_ID = {int(record['id']): record for record in BARMAID_DATABASE}
BARMAID_BY_NAME = {record['name']: record for record in BARMAID_DATABASE}
CHARACTER_BY_ID = {int(record['id']): record for record in CHARACTER_DATA['records']}
# 세이브 파일의 승무원 역할 슬롯. 역할 판정·복원·목록 필터에서 공통으로 사용한다.
ROLE_SLOT_OFFSETS = (0xA5, 0xA7, 0xA9, 0xAB)
ROLE_SLOT_BY_KEY = {'officer': 0xA5, 'navigator': 0xA7, 'surveyor': 0xA9, 'interpreter': 0xAB}
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
APP_TITLE = f'대항해시대 3 세이브 에디터 v{APP_VERSION}'
_PHOTO_CACHE: dict = {}


class CalendarDatePicker(tk.Frame):
    """날짜를 직접 입력하지 않고 팝업 달력에서 고르는 컨트롤."""

    WEEKDAYS = ('일', '월', '화', '수', '목', '금', '토')

    def __init__(self, parent, get_date, set_date, font=None, min_year=1000, max_year=3000):
        super().__init__(parent)
        self._get_date = get_date
        self._set_date = set_date
        self._popup = None
        self._shown_year = 1480
        self._shown_month = 1
        self._shown_day = 1
        self._min_year = int(min_year)
        self._max_year = int(max_year)
        self.button = tk.Button(
            self, relief='sunken', bd=1, anchor='w', padx=7,
            font=font or ('Malgun Gothic', 8), command=self.open_calendar,
        )
        self.button.pack(fill=tk.X)
        self.refresh()

    def refresh(self):
        try:
            year, month, day = (int(value) for value in self._get_date())
            self.button.config(text=f'{year}년 {month}월 {day}일   ▾')
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
        tk.Button(
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
        tk.Button(header, text='‹', width=3, command=lambda: self._move_month(-1)).pack(side=tk.LEFT)
        self._year_var = tk.StringVar(value=str(self._shown_year))
        year_spin = ttk.Spinbox(header, textvariable=self._year_var, from_=self._min_year, to=self._max_year, width=5, justify='center', command=self._apply_shown_year)
        year_validate = self._calendar_body.register(
            lambda value: value == '' or (value.isdigit() and (len(value) < 4 or self._min_year <= int(value) <= self._max_year))
        )
        year_spin.configure(validate='key', validatecommand=(year_validate, '%P'))
        year_spin.pack(side=tk.LEFT, padx=(8, 1))
        year_spin.bind('<Return>', self._apply_shown_year, add='+')
        year_spin.bind('<FocusOut>', self._apply_shown_year, add='+')
        tk.Label(header, text=ui('ui_0233'), font=('Malgun Gothic', 9, 'bold')).pack(side=tk.LEFT, padx=(0, 5))
        self._month_var = tk.StringVar(value=str(self._shown_month))
        month_spin = ttk.Spinbox(header, textvariable=self._month_var, from_=1, to=12, width=3, justify='center', command=self._apply_shown_month)
        month_validate = self._calendar_body.register(
            lambda value: value == '' or (value.isdigit() and (len(value) < 2 or 1 <= int(value) <= 12))
        )
        month_spin.configure(validate='key', validatecommand=(month_validate, '%P'))
        month_spin.pack(side=tk.LEFT)
        month_spin.bind('<Return>', self._apply_shown_month, add='+')
        month_spin.bind('<FocusOut>', self._apply_shown_month, add='+')
        tk.Label(header, text=ui('ui_0234'), font=('Malgun Gothic', 9, 'bold')).pack(side=tk.LEFT, padx=(0, 5))
        self._day_var = tk.StringVar(value=str(self._shown_day))
        day_spin = ttk.Spinbox(header, textvariable=self._day_var, from_=1, to=calendar.monthrange(self._shown_year, self._shown_month)[1], width=3, justify='center', command=self._apply_shown_day)
        max_day = calendar.monthrange(self._shown_year, self._shown_month)[1]
        day_validate = self._calendar_body.register(
            lambda value: value == '' or (value.isdigit() and (len(value) < 2 or 1 <= int(value) <= max_day))
        )
        day_spin.configure(validate='key', validatecommand=(day_validate, '%P'))
        day_spin.pack(side=tk.LEFT)
        day_spin.bind('<Return>', self._apply_shown_day, add='+')
        tk.Label(header, text=ui('ui_0235'), font=('Malgun Gothic', 9, 'bold')).pack(side=tk.LEFT, expand=True)
        tk.Button(header, text='›', width=3, command=lambda: self._move_month(1)).pack(side=tk.RIGHT)
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
            tk.Label(self._calendar_days, text=weekday, width=3, fg=color, font=('Malgun Gothic', 8, 'bold')).grid(row=0, column=column, pady=(0, 2))
        selected = (self._shown_year, self._shown_month, self._shown_day)
        for row, week in enumerate(calendar.monthcalendar(self._shown_year, self._shown_month), start=1):
            for column, day in enumerate(week):
                if not day:
                    tk.Label(self._calendar_days, text='', width=3).grid(row=row, column=column, padx=1, pady=1)
                    continue
                chosen = selected == (self._shown_year, self._shown_month, day)
                button = tk.Button(
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
    fn = f'sailer_{int(character_id)}.png'
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
        tk.Label(info_f, text=ui('ui_0212'), font=('Malgun Gothic', 9, 'bold'), bg='#F0F0F0').pack(anchor='w', pady=2)
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
            tk.Button(
                btn_bar, text=ui('ui_0382'), font=('Malgun Gothic', 10, 'bold'),
                bg='#E6F4EA', fg='#137333', padx=16, pady=5,
                command=self.apply_selection,
            ).pack()
        else:
            tk.Button(
                top_bar, text=ui('ui_0098'), font=('Malgun Gothic', 10, 'bold'),
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
        discoveries.append({'index': i, 'name': DISCOVERY_NAME_BY_NO[int(i)], 'category': DISCOVERY_CATEGORY_NAMES[category_code],
                            'value': val, 'save_offset': off, 'disc_id': did,
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
        self.lbl_title = tk.Label(hdr_f, text=f'[{item_info['id']:03d}] {item_info['name']} ({item_info.get('category', '')})', font=('Malgun Gothic', 10, 'bold'), fg='#FFFFFF', bg='#1A237E')
        self.lbl_title.pack(side=tk.LEFT, anchor='w')
        f_nav = tk.Frame(hdr_f, bg='#1A237E')
        f_nav.pack(side=tk.RIGHT)
        self.btn_prev = tk.Button(f_nav, text=ui('ui_0106'), font=('Malgun Gothic', 8, 'bold'), bg='#283593', fg='#FFFFFF', activebackground='#3949AB', activeforeground='#FFFFFF', relief='flat', padx=6, pady=1, cursor='hand2', command=self._go_prev)
        self.btn_prev.pack(side=tk.LEFT, padx=(0, 4))
        self.lbl_page = tk.Label(f_nav, text=f'{self.current_list_index + 1} / {len(self.items_list)}', font=('Malgun Gothic', 8), fg='#B0BEC5', bg='#1A237E')
        self.lbl_page.pack(side=tk.LEFT, padx=2)
        self.btn_next = tk.Button(f_nav, text=ui('ui_0107'), font=('Malgun Gothic', 8, 'bold'), bg='#283593', fg='#FFFFFF', activebackground='#3949AB', activeforeground='#FFFFFF', relief='flat', padx=6, pady=1, cursor='hand2', command=self._go_next)
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
        self.lbl_price = tk.Label(f_info, text='', font=('Malgun Gothic', 9, 'bold'), fg='#B06000')
        self.lbl_price.pack(side=tk.LEFT, padx=(0, 16))
        self.lbl_stat = tk.Label(f_info, text='', font=('Malgun Gothic', 9, 'bold'), fg='#1A73E8')
        self.lbl_stat.pack(side=tk.LEFT)
        self.lbl_reward_discovery = tk.Label(f_info, text='', font=('Malgun Gothic', 8, 'bold'), fg='#7B1FA2')
        tk.Label(f_right_info, text=ui('ui_0216'), font=('Malgun Gothic', 9, 'bold')).pack(anchor='w', pady=(2, 3))
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
            btn_move = tk.Button(self.action_f, text=inventory_text('ui_0290', 'ui_0282'), font=('Malgun Gothic', 9, 'bold'), bg='#E6F4EA', fg='#137333', padx=8, pady=3, command=lambda: self._do_action('move_to_storage'))
            btn_move.pack(side=tk.LEFT, padx=4)
            btn_del = tk.Button(self.action_f, text=ui('ui_0192'), font=('Malgun Gothic', 9, 'bold'), bg='#FCE8E6', fg='#D93025', padx=8, pady=3, command=lambda: self._do_action('delete_pocket'))
            btn_del.pack(side=tk.LEFT, padx=4)
        else:
            if self.source_view == 'storage':
                btn_move = tk.Button(self.action_f, text=inventory_text('ui_0290', 'ui_0281'), font=('Malgun Gothic', 9, 'bold'), bg='#E8F0FE', fg='#1A73E8', padx=8, pady=3, command=lambda: self._do_action('move_to_pocket'))
                btn_move.pack(side=tk.LEFT, padx=4)
                btn_del = tk.Button(self.action_f, text=ui('ui_0192'), font=('Malgun Gothic', 9, 'bold'), bg='#FCE8E6', fg='#D93025', padx=8, pady=3, command=lambda: self._do_action('delete_storage'))
                btn_del.pack(side=tk.LEFT, padx=4)
            else:
                btn_pocket = tk.Button(self.action_f, text=inventory_text('ui_0285', 'ui_0281'), font=('Malgun Gothic', 9, 'bold'), bg='#E8F0FE', fg='#1A73E8', padx=8, pady=3, command=lambda: self._do_action('add_pocket'))
                btn_pocket.pack(side=tk.LEFT, padx=4)
                btn_storage = tk.Button(self.action_f, text=inventory_text('ui_0285', 'ui_0282'), font=('Malgun Gothic', 9, 'bold'), bg='#E6F4EA', fg='#137333', padx=8, pady=3, command=lambda: self._do_action('add_storage'))
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
    def __init__(self, parent, disc_info, disc_desc, current_state=0, disc_date=UI_EMPTY_VALUE, rep_date=UI_EMPTY_VALUE, discoverer=UI_EMPTY_VALUE, on_state_change_callback=None, items_list=None, current_list_index=0, get_disc_info_fn=None, on_navigate_callback=None, state_index=None):
        # ***<module>.DiscoveryInfoModal.__init__: Failure: Different bytecode
        super().__init__(parent)
        self.parent = parent
        self._previous_focus = parent.focus_get()
        self._focus_restored = False
        self.on_state_change_callback = on_state_change_callback
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
        self.lbl_title = tk.Label(hdr_f, text=f"[No. {disc_info['index']:03d} | ID {disc_info['disc_id']:03d}] {disc_info['name']} ({disc_info['category']})", font=('Malgun Gothic', 10, 'bold'), fg='#FFFFFF', bg='#1A237E')
        self.lbl_title.pack(side=tk.LEFT, anchor='w')
        f_nav = tk.Frame(hdr_f, bg='#1A237E')
        f_nav.pack(side=tk.RIGHT)
        self.btn_prev = tk.Button(f_nav, text=ui('ui_0106'), font=('Malgun Gothic', 8, 'bold'), bg='#283593', fg='#FFFFFF', activebackground='#3949AB', activeforeground='#FFFFFF', relief='flat', padx=6, pady=1, cursor='hand2', command=self._go_prev)
        self.btn_prev.pack(side=tk.LEFT, padx=(0, 4))
        self.lbl_page = tk.Label(f_nav, text=f'{self.current_list_index + 1} / {len(self.items_list)}', font=('Malgun Gothic', 8), fg='#B0BEC5', bg='#1A237E')
        self.lbl_page.pack(side=tk.LEFT, padx=2)
        self.btn_next = tk.Button(f_nav, text=ui('ui_0107'), font=('Malgun Gothic', 8, 'bold'), bg='#283593', fg='#FFFFFF', activebackground='#3949AB', activeforeground='#FFFFFF', relief='flat', padx=6, pady=1, cursor='hand2', command=self._go_next)
        self.btn_next.pack(side=tk.LEFT, padx=(4, 0))
        btn_f = tk.Frame(self, bg='#F0F0F0', padx=12, pady=6)
        btn_f.pack(side=tk.BOTTOM, fill=tk.X)
        action_f = tk.Frame(btn_f, bg='#F0F0F0')
        action_f.pack(anchor='center')
        btn_rep = tk.Button(action_f, text=discovery_state_text(2, action=True), font=('Malgun Gothic', 9, 'bold'), bg='#E6F4EA', fg='#137333', padx=6, pady=3, command=lambda: self._do_change(2))
        btn_rep.pack(side=tk.LEFT, padx=3)
        btn_disc = tk.Button(action_f, text=discovery_state_text(1, action=True), font=('Malgun Gothic', 9, 'bold'), bg='#E8F0FE', fg='#1A73E8', padx=6, pady=3, command=lambda: self._do_change(1))
        btn_disc.pack(side=tk.LEFT, padx=3)
        btn_undisc = tk.Button(action_f, text=discovery_state_text(0, action=True), font=('Malgun Gothic', 9, 'bold'), bg='#FCE8E6', fg='#D93025', padx=6, pady=3, command=lambda: self._do_change(0))
        btn_undisc.pack(side=tk.LEFT, padx=3)
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
        self.lbl_state = tk.Label(f_info1, text='', font=('Malgun Gothic', 9, 'bold'))
        self.lbl_state.pack(side=tk.LEFT, padx=(0, 14))
        self.lbl_value = tk.Label(f_info1, text='', font=('Malgun Gothic', 9, 'bold'), fg='#B06000')
        self.lbl_value.pack(side=tk.LEFT, padx=(0, 14))
        self.lbl_reward = tk.Label(f_info1, text='', font=('Malgun Gothic', 8, 'bold'), fg='#7B1FA2')
        self.f_info2 = tk.Frame(f_right_info)
        self.f_info2.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))
        self.lbl_dates = tk.Label(self.f_info2, text='', font=('Malgun Gothic', 8), fg='#5F6368')
        self.lbl_dates.pack(side=tk.LEFT)
        tk.Label(f_right_info, text=ui('ui_0218'), font=('Malgun Gothic', 9, 'bold')).pack(anchor='w', pady=(2, 2))
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
        st_fg = '#137333' if current_state == 2 else '#1A73E8' if current_state == 1 else '#5F6368'
        self.lbl_state.config(text=ui('ui_0014', st_text), fg=st_fg)
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
class FleetVideoPreview(tk.Frame):
    """VLC vmem 출력으로 별도 창 없이 함선 영상을 Tk 안에서 재생한다."""
    WIDTH, HEIGHT = 80, 60

    def __init__(self, parent, frame_height=None):
        height = frame_height if frame_height is not None else self.HEIGHT + 4
        super().__init__(parent, width=self.WIDTH + 4, height=height, bg='#222222', relief='ridge', bd=2)
        self.pack_propagate(False)
        self.label = tk.Label(self, bg='#222222', text=ui('ui_0113'), fg='#888888', font=('Malgun Gothic', 7))
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
        self.fleet_original_buffer = None
        self.city_original_buffer = None
        self.pocket_ids = []
        self.storage_ids = []
        self.discovery_state = [0] * len(self.discovery_db)
        self.discovery_original_state = list(self.discovery_state)
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

    def on_close(self):
        """VLC 작업 스레드가 남아도 에디터 프로세스를 즉시 종료한다."""
        if self._is_closing:
            return
        self._is_closing = True
        # libVLC의 stop/release는 드물게 디코더 스레드를 기다리며 멈춘다.
        # mainloop만 끝내고 __main__의 즉시 종료 경로에 맡긴다.
        self.root.quit()

    def setup_styles(self):
        # ***<module>.CDS3SaveEditorApp.setup_styles: Failure: Different bytecode
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TNotebook.Tab', padding=[10, 4], font=('Malgun Gothic', 9, 'bold'))
        style.configure('Treeview.Heading', font=('Malgun Gothic', 9, 'bold'))
        style.configure('Treeview', rowheight=22, font=('Malgun Gothic', 9))

    def _enable_notebook_redraw_batching(self):
        """기존 화면을 유지한 채 새 탭을 뒤에서 모두 그린 뒤 보여 준다."""
        self._notebook_redraw_pending = False
        self._notebook_transition_overlay = None

        def on_tab_press(event):
            notebook = event.widget
            try:
                if notebook.identify(event.x, event.y) != 'tab' or self._notebook_redraw_pending:
                    return
                self._notebook_redraw_pending = True
                # 별도 네이티브 자식 컨트롤은 WM_SETREDRAW를 무시할 수 있다.
                # 현재 화면의 스냅샷을 잠시 덮어 둬야 새 탭의 모든 컨트롤이
                # 준비되기 전의 순차 그리기가 보이지 않는다.
                self._show_notebook_transition_overlay(notebook)
            except (tk.TclError, OSError, ImportError):
                self._notebook_redraw_pending = False

        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, ttk.Notebook):
                    # 위젯 바인딩은 ttk 클래스의 탭 선택 처리보다 먼저 실행된다.
                    child.bind('<ButtonPress-1>', on_tab_press, add='+')
                walk(child)
        walk(self.root)

    def _finish_notebook_redraw_batch(self):
        self._notebook_redraw_pending = False
        try:
            overlay, self._notebook_transition_overlay = self._notebook_transition_overlay, None
            if overlay is not None and overlay.winfo_exists():
                overlay.destroy()
        except tk.TclError:
            pass

    def _show_notebook_transition_overlay(self, notebook):
        """클릭한 Notebook 영역만 90ms 유지해 탭 전환의 중간 프레임을 가린다."""
        from PIL import ImageGrab, ImageTk
        self.root.update_idletasks()
        x, y = notebook.winfo_rootx(), notebook.winfo_rooty()
        width, height = notebook.winfo_width(), notebook.winfo_height()
        if width <= 1 or height <= 1:
            self.root.after_idle(self._finish_notebook_redraw_batch)
            return
        image = ImageGrab.grab(bbox=(x, y, x + width, y + height))
        overlay = tk.Toplevel(self.root)
        overlay.overrideredirect(True)
        overlay.transient(self.root)
        overlay.attributes('-topmost', True)
        overlay.geometry(f'{width}x{height}+{x}+{y}')
        photo = ImageTk.PhotoImage(image)
        label = tk.Label(overlay, image=photo, borderwidth=0, highlightthickness=0)
        label.image = photo
        label.pack(fill=tk.BOTH, expand=True)
        overlay.lift()
        self._notebook_transition_overlay = overlay
        self.root.after(90, self._finish_notebook_redraw_batch)
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
        btn_open = tk.Button(top_bar, text=ui('ui_0114'), font=('Malgun Gothic', 9, 'bold'), command=self.on_open_file, bg='#E8F0FE', padx=8)
        btn_open.pack(side=tk.LEFT, padx=4)
        self.btn_save = tk.Button(top_bar, text=ui('ui_0115'), font=('Malgun Gothic', 9, 'bold'), command=self.on_save_file, bg='#E6F4EA', fg='#137333', padx=8)
        self.btn_save.pack(side=tk.LEFT, padx=4)
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
            (self.spn_batch_reputation, 0, 99999), (self.spn_batch_tech, 0, 3), (self.spn_batch_lang, 0, 3),
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
                             width=16, justify='center', font=('Malgun Gothic', 10))
        digits_only = self.root.register(
            lambda proposed, low=minimum: (proposed == '' or
            (proposed == '-' and low < 0) or proposed.lstrip('-').isdigit()))
        entry.configure(validate='key', validatecommand=(digits_only, '%P'))
        entry.bind('<KeyRelease>', lambda _event: self._clamp_spinbox(entry, minimum, maximum), add='+')
        entry.pack(anchor='center', pady=(8, 2))
        error_var = tk.StringVar(value='')
        tk.Label(body, textvariable=error_var, fg='#B3261E', font=('Malgun Gothic', 8)).pack(anchor='center')
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

        tk.Button(buttons, text=ui('ui_0175'), width=8, command=confirm).pack(side=tk.LEFT)
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
        for column in range(3):
            parent.columnconfigure(column, weight=1, uniform='fleet_columns')
        parent.rowconfigure(0, weight=1)

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
        tk.Button(fleet_list_actions, text=ui('ui_0338'), width=9, bg='#E6F4EA', fg='#137333', command=self.add_fleet_ship).pack(
            side=tk.LEFT, padx=(0, 4))
        tk.Button(fleet_list_actions, text=ui('ui_0334'), width=9, bg='#FCE8E6', fg='#D93025', command=self.remove_selected_fleet_ship).pack(
            side=tk.LEFT, padx=(4, 0))

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
            (ui('ui_0062'), 'name'), (ui('ui_0126'), 'ship_type'),
            (fleet_label('ui_0130', 'ui_0127'), 'crew'),
            (ui('ui_0132'), 'max_weight'),
            (ui('ui_0133'), 'max_capacity'),
            (ui('ui_0136'), 'cannon_type'), (ui('ui_0137'), 'figurehead'),
        ]
        paired_fields = [
            (ui('ui_0131'), 'max_power', 'current_power'),
            (ui('ui_0134'), 'max_durability', 'current_durability'),
            (ui('ui_0135'), 'max_cannons', 'current_cannons'),
        ]
        tk.Label(editor, text=ui('ui_0219'), anchor='e', font=('Malgun Gothic', 9, 'bold')).grid(
            row=1, column=0, sticky='e', padx=(0, 7), pady=3)
        self.fleet_flagship_var = tk.BooleanVar(value=False)
        tk.Checkbutton(editor, text='', variable=self.fleet_flagship_var,
                       font=('Malgun Gothic', 9)).grid(row=1, column=1, sticky='w', pady=3)

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

        form_rows = (
            ('single', *single_fields[0]), ('single', *single_fields[1]), ('single', *single_fields[2]),
            ('single', *single_fields[3]), ('single', *single_fields[4]),
            ('pair', *paired_fields[0]),
            ('pair', *paired_fields[1]), ('pair', *paired_fields[2]),
            ('single', *single_fields[5]), ('single', *single_fields[6]),
        )
        row = 2
        for row_type, label, *keys in form_rows:
            tk.Label(editor, text=label + ':', anchor='e', font=('Malgun Gothic', 9, 'bold')).grid(
                row=row, column=0, sticky='e', padx=(0, 7), pady=3)
            if row_type == 'single':
                widget = create_fleet_widget(editor, keys[0])
                widget.grid(row=row, column=1, sticky='ew', pady=3)
            else:
                pair = tk.Frame(editor)
                pair.grid(row=row, column=1, sticky='ew', pady=3)
                pair.columnconfigure(1, minsize=62)
                pair.columnconfigure(3, minsize=62)
                tk.Label(pair, text=ui('ui_0129'), font=('Malgun Gothic', 8)).grid(
                    row=0, column=0, sticky='w', padx=(0, 3))
                max_box = tk.Frame(pair, width=62, height=23)
                max_box.grid(row=0, column=1, sticky='nsew')
                max_box.grid_propagate(False)
                max_box.columnconfigure(0, weight=1)
                max_box.rowconfigure(0, weight=1)
                create_fleet_widget(max_box, keys[0], width=6).grid(sticky='nsew')
                tk.Label(pair, text=ui('ui_0130'), font=('Malgun Gothic', 8)).grid(
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
        tk.Label(editor, text=ui('ui_0332') + ':', anchor='e', font=('Malgun Gothic', 9, 'bold')).grid(
            row=mast_row, column=0, sticky='e', padx=(0, 7), pady=3)
        mast_group = tk.Frame(editor)
        mast_group.grid(row=mast_row, column=1, sticky='ew', pady=3)
        self.fleet_mast_rows = {}
        for column, (label, key, options) in enumerate(mast_controls):
            mast_group.columnconfigure(column, weight=1)
            mast_slot = tk.Frame(mast_group)
            mast_slot.grid(row=0, column=column, sticky='ew', padx=1)
            tk.Label(mast_slot, text=label, font=('Malgun Gothic', 8, 'bold')).pack(anchor='center')
            value = tk.StringVar(value=options[0])
            self.fleet_edit_vars[key] = value
            combo = ttk.Combobox(mast_slot, textvariable=value, values=options, state='readonly',
                                 width=5, justify='center', font=('Malgun Gothic', 8))
            combo.pack(fill=tk.X)
            combo.bind('<<ComboboxSelected>>', lambda _event: self._apply_fleet_live())
            self.fleet_mast_rows[key] = (mast_slot, combo)
        fleet_actions = tk.Frame(editor)
        fleet_actions.grid(row=mast_row + 1, column=0, columnspan=2, pady=(12, 0))
        tk.Button(fleet_actions, text=ui('ui_0222'), width=9, bg='#E8F0FE', fg='#1A73E8', command=self.reset_fleet_edits).pack(
            side=tk.LEFT)

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
        tooltip_texts = {
            'unknown_38': (
                '함선 가격 계산식\n'
                '기본 구매가 = 가격 계수 × 600 G\n'
                '실제 구매가 = 기본 구매가 × 도시 시세 ÷ 100'
            ),
            'shipyard_requirement': (
                '함선 출시 연도 계산식\n'
                '출시 가능 연도 = 1476 + 출시 계수 − (도시 규모 × 5)\n'
                '현재 연도가 이 값 이상일 때 조선소에 표시됩니다.\n'
                '규모 1 기준 출시 연도 = 1471 + 출시 계수'
            ),
        }
        tooltip_text = tooltip_texts.get(row)
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

    def _hide_fleet_basic_tooltip(self, _event=None):
        tooltip = getattr(self, '_fleet_basic_tooltip', None)
        self._fleet_basic_tooltip = None
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
        return sum(1 for index in range(3) if ((value >> (index * 2)) & 0x03) != 0)

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
        self._schedule_treeview_autofit(self.lst_fleet, self.lst_fleet_basic)

    def on_fleet_select(self, _event=None):
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
            self.fleet_flagship_var.set(self._fleet_flagship_position() == (fleet_no - 1 if fleet_no else -1))
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
        """Restore the selected ship record to the state from the first file load."""
        selected = self.lst_fleet.selection() if hasattr(self, 'lst_fleet') else ()
        if (not selected or not selected[0].isdigit() or not getattr(self, 'fleet_active_indices', [])
                or not getattr(self, 'fleet_original_buffer', None)):
            return self._populate_fleet_editor(None)
        position = int(selected[0])
        if 0 <= position < len(self.fleet_active_indices):
            ship_index = self.fleet_active_indices[position]
            base = self._fleet_slot_offset(ship_index)
            record_end = base + 0x64
            if record_end <= len(self.file_buffer) and record_end <= len(self.fleet_original_buffer):
                self.file_buffer[base:record_end] = self.fleet_original_buffer[base:record_end]
                self.file_buffer[0x48D9:0x48DD] = self.fleet_original_buffer[0x48D9:0x48DD]
                self.refresh_fleet_list()
                self.lbl_status.config(text=ui('ui_0225'))

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

        tk.Label(body, text=ui('ui_0126') + ':', font=('Malgun Gothic', 9, 'bold')).grid(
            row=0, column=0, sticky='e', padx=(0, 7), pady=3)
        type_var = tk.StringVar(value=self._fleet_ship_type_name(0))
        type_combo = ttk.Combobox(body, textvariable=type_var, state='readonly', width=18,
                                  values=self._fleet_ship_type_options(), font=('Malgun Gothic', 9))
        type_combo.grid(row=0, column=1, sticky='ew', pady=3)
        tk.Label(body, text=ui('ui_0226'), font=('Malgun Gothic', 9, 'bold')).grid(
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
        tk.Label(body, textvariable=error_var, fg='#B3261E', font=('Malgun Gothic', 8)).grid(
            row=2, column=0, columnspan=2, pady=(2, 0))
        tk.Label(body, text=ui('ui_0345'), fg='#8B3A00', font=('Malgun Gothic', 8)).grid(
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

        tk.Button(buttons, text=ui('ui_0175'), width=8, command=confirm).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(buttons, text=ui('ui_0102'), width=8, command=dialog.destroy).pack(side=tk.LEFT, padx=(4, 0))
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
            mast = 0
            for index, key in enumerate(('mast_main', 'mast_sub', 'mast_stern')):
                mast |= self._fleet_combo_code(
                    self.fleet_edit_vars[key].get(),
                    self._fleet_mast_name_map()) << (index * 2)
            values['mast'] = mast
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
    CITY_VALUE_FORMATS = {'u8': '<B', 'u16': '<H', 'u32': '<I', 'i16': '<h', 'i32': '<i'}
    CITY_VALUE_LIMITS = {
        'u8': (0, 0xFF), 'u16': (0, 0xFFFF), 'u32': (0, 0xFFFFFFFF),
        'i16': (-0x8000, 0x7FFF), 'i32': (-0x80000000, 0x7FFFFFFF),
    }

    def build_cities_tab(self):
        """Build a save-city editor alongside the EXE-derived city defaults."""
        parent = self.tab_cities
        for column in range(3):
            parent.columnconfigure(column, weight=1, uniform='city_columns')
        parent.rowconfigure(0, weight=1)
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
        basic_tab = tk.Frame(city_tabs, padx=8, pady=8)
        market_tab = tk.Frame(city_tabs, padx=8, pady=8)
        trade_tab = tk.Frame(city_tabs, padx=8, pady=8)
        city_tabs.add(basic_tab, text=ui('ui_0128'))
        city_tabs.add(market_tab, text=ui('ui_0357'))
        city_tabs.add(trade_tab, text=ui('ui_0359'))
        city_tabs.bind('<<NotebookTabChanged>>', self._on_city_editor_tab_changed)
        self.city_tabs = city_tabs
        self.city_trade_tab = trade_tab

        self.city_flag_active_var = tk.BooleanVar(value=False)
        tk.Label(basic_tab, text=ui('ui_0314') + ':', anchor='e',
                 font=('Malgun Gothic', 9, 'bold')).grid(
                     row=0, column=0, sticky='e', padx=(0, 6), pady=(2, 4))
        tk.Checkbutton(basic_tab, text='', variable=self.city_flag_active_var,
                       font=('Malgun Gothic', 9), command=self.apply_city_edits,
                       takefocus=0, highlightthickness=0).grid(
                           row=0, column=1, sticky='w', pady=(2, 4))

        self.city_name_var = tk.StringVar(value='')
        tk.Label(basic_tab, text=ui('ui_0344') + ':', font=('Malgun Gothic', 9, 'bold')).grid(row=1, column=0, sticky='e', padx=(0, 6), pady=5)
        tk.Label(basic_tab, textvariable=self.city_name_var, anchor='w', font=('Malgun Gothic', 9)).grid(
            row=1, column=1, columnspan=3, sticky='ew', pady=5)

        tk.Label(basic_tab, text=ui('ui_0300') + ':', font=('Malgun Gothic', 9, 'bold')).grid(row=2, column=0, sticky='e', padx=(0, 6), pady=5)
        self.cbo_city_nation = ttk.Combobox(basic_tab, values=NATION_NAMES, state='readonly', width=20, font=('Malgun Gothic', 9))
        self.cbo_city_nation.grid(row=2, column=1, columnspan=3, sticky='ew', pady=5)
        self.cbo_city_nation.bind('<<ComboboxSelected>>', lambda _event: self.apply_city_edits())
        basic_tab.columnconfigure(1, weight=1)
        basic_tab.columnconfigure(3, weight=1)

        culture_definition = self._city_definition('link_value')
        self.city_culture_var = tk.StringVar(value='')
        self.city_culture_options = [self.CITY_CULTURE_NAMES[code] for code in sorted(self.CITY_CULTURE_NAMES)]
        self.city_culture_codes_by_name = {name: code for code, name in self.CITY_CULTURE_NAMES.items()}
        tk.Label(basic_tab, text=self._city_field_label(culture_definition) + ':', font=('Malgun Gothic', 9, 'bold')).grid(
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
                 font=('Malgun Gothic', 9, 'bold')).grid(row=4, column=0, sticky='e', padx=(0, 6), pady=4)
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
            checkbox = tk.Checkbutton(facility_box, text=name, variable=variable, font=('Malgun Gothic', 8),
                                      command=self.apply_city_edits)
            checkbox.grid(row=position // 3, column=position % 3, sticky='w', padx=(0, 10), pady=1)
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
                                      font=('Malgun Gothic', 8),
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
            tk.Label(market_goods_box, text=ui('ui_0309', number + 1), font=('Malgun Gothic', 9, 'bold')).grid(
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
                 font=('Malgun Gothic', 9, 'bold')).grid(row=2, column=0, sticky='e', padx=(0, 6), pady=4)
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

        tk.Button(center, text=ui('ui_0222'), width=9, bg='#E8F0FE', fg='#1A73E8', command=self.reset_city_edits).grid(
            row=1, column=0, pady=(8, 0))
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
            font = tkfont.Font(font=('Malgun Gothic', 9, 'bold'))
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
        return cls.CITY_SAVE_OFFSET + city_index * cls.CITY_RECORD_SIZE

    @staticmethod
    def _city_read(buffer, offset, kind):
        return struct.unpack_from(CDS3SaveEditorApp.CITY_VALUE_FORMATS[kind], buffer, offset)[0]

    @staticmethod
    def _city_write(buffer, offset, kind, value):
        low, high = CDS3SaveEditorApp.CITY_VALUE_LIMITS[kind]
        struct.pack_into(CDS3SaveEditorApp.CITY_VALUE_FORMATS[kind], buffer, offset,
                         max(low, min(high, int(value))))

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
        label = tk.Label(parent, text=self._city_field_label(definition) + ':', font=('Malgun Gothic', 9, 'bold'))
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
        tooltip_text = (
            '특산품 최종 구매가 계산식\n'
            '시세 반영 가격 = 특산품 가격 × 도시 시세 ÷ 100 (소수점 버림)\n'
            '최종 구매가 = 시세 반영 가격 × 3 ÷ 2 (소수점 버림)\n'
            f'현재: {price} × {market} ÷ 100 = {market_price} → {market_price} × 3 ÷ 2 = {buy_price} G'
        )
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
        tk.Label(parent, text=self._city_field_label(definition) + ':', font=('Malgun Gothic', 9, 'bold')).grid(
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
        _key, _text_key, _offset, _kind, default_key, *optional_index = definition
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

    def refresh_all_city_shipyards(self):
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
        self.lbl_status.config(text=ui('ui_0380', changed))

    def _schedule_city_shipyard_refresh(self, _event=None):
        """현재일 입력 중에는 잠시 기다렸다가 유효한 연도로 조선소 목록을 갱신한다."""
        pending_job = getattr(self, '_city_shipyard_refresh_job', None)
        if pending_job is not None:
            self.root.after_cancel(pending_job)
        self._city_shipyard_refresh_job = self.root.after(250, self._refresh_city_shipyards_for_current_date)

    def _refresh_city_shipyards_for_current_date(self):
        self._city_shipyard_refresh_job = None
        try:
            int(self.spn_game_y.get())
            int(self.spn_game_m.get())
            int(self.spn_game_d.get())
        except (AttributeError, ValueError, tk.TclError):
            return
        self.refresh_all_city_shipyards()

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


    @staticmethod
    def _open_editable_combo_dropdown(combo, should_open=True):
        """검색 입력 뒤 후보 목록을 표시한다. 키 입력 처리가 끝난 뒤 실행해야 한다."""
        if not should_open:
            return

        def post_dropdown():
            try:
                if combo.winfo_exists() and combo.focus_get() == combo:
                    combo.event_generate('<Alt-Down>')
            except tk.TclError:
                pass
        combo.after_idle(post_dropdown)

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
            return
        record, base = self.CITY_RECORDS[index], self._city_record_offset(index)
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
        """선택 도시의 저장 레코드를 세이브 파일 최초 로드본으로 복원한다."""
        city_index = self._selected_city_index()
        if city_index is None or not self.file_buffer or not self.city_original_buffer:
            return
        base = self._city_record_offset(city_index)
        end = base + self.CITY_RECORD_SIZE
        if end > len(self.file_buffer) or end > len(self.city_original_buffer):
            return
        self.file_buffer[base:end] = self.city_original_buffer[base:end]
        self.on_city_select()
        self.lbl_status.config(text=ui('ui_0333', self.CITY_RECORDS[city_index]['name']))

    def build_profile_tab(self):
        # ***<module>.CDS3SaveEditorApp.build_profile_tab: Failure: Different bytecode
        parent = self.tab_profile
        LBL_FONT = ('Malgun Gothic', 8, 'bold')
        VAL_FONT = ('Malgun Gothic', 8)
        parent.columnconfigure(0, weight=1, uniform='profile_columns')
        parent.columnconfigure(1, weight=1, uniform='profile_columns')
        parent.rowconfigure(0, weight=1)
        profile_left = tk.LabelFrame(parent, text=ui('ui_0414'), font=('Malgun Gothic', 9, 'bold'), padx=4, pady=4)
        profile_left.grid(row=0, column=0, sticky='nsew', padx=(10, 5), pady=4)
        profile_right = tk.LabelFrame(parent, text=ui('ui_0392'), font=('Malgun Gothic', 9, 'bold'), padx=4, pady=4)
        profile_right.grid(row=0, column=1, sticky='nsew', padx=(5, 10), pady=4)
        self.profile_companion_tabs = ttk.Notebook(profile_right, style='Editor.TNotebook')
        self.profile_companion_tabs.pack(fill=tk.BOTH, expand=True)

        self.profile_details = ttk.Notebook(profile_left, style='Editor.TNotebook')
        self.profile_page_stats = ttk.Frame(self.profile_details)
        self.profile_page_money = ttk.Frame(self.profile_details)
        self.profile_page_reputation = ttk.Frame(self.profile_details)
        self.profile_page_tech = ttk.Frame(self.profile_details)
        self.profile_page_lang = ttk.Frame(self.profile_details)
        self.profile_details.add(self.profile_page_stats, text=ui('ui_0385'))
        self.profile_details.add(self.profile_page_money, text=ui('ui_0386'))
        self.profile_details.add(self.profile_page_reputation, text=ui('ui_0387'))
        self.profile_details.add(self.profile_page_tech, text=ui('ui_0388'))
        self.profile_details.add(self.profile_page_lang, text=ui('ui_0389'))
        self.profile_page_officer = ttk.Frame(self.profile_companion_tabs)
        self.profile_page_navigator = ttk.Frame(self.profile_companion_tabs)
        self.profile_page_surveyor = ttk.Frame(self.profile_companion_tabs)
        self.profile_page_interpreter = ttk.Frame(self.profile_companion_tabs)
        self.profile_page_spouse = ttk.Frame(self.profile_companion_tabs)
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

        grp_player = tk.Frame(profile_left, height=174)
        grp_player.pack(fill=tk.X, pady=(0, 9))
        grp_player.pack_propagate(False)
        self.profile_details.pack(fill=tk.BOTH, expand=True)
        f_p_face_box = tk.Frame(grp_player, width=84, height=100, bg='#222222', relief='ridge', bd=2)
        f_p_face_box.pack_propagate(False)
        f_p_face_box.place(x=0, y=4)
        self.lbl_player_face = tk.Label(f_p_face_box, bg='#222222')
        self.lbl_player_face.pack(fill=tk.BOTH, expand=True)
        self.btn_player_face_change = tk.Button(
            grp_player, text=ui('ui_0382'), font=('Malgun Gothic', 8, 'bold'),
            bg='#E6F4EA', fg='#137333', command=self.open_player_face_picker,
        )
        self.btn_player_face_change.place(x=0, y=110, width=84, height=25)
        # 별도 Frame을 두면 그 배경이 LabelFrame 테두리를 덮는다. 오른쪽 항목은
        # 그룹에 직접 grid 배치하고 첫 열만 얼굴 영역만큼 비워 둔다.
        f_p_right = grp_player
        grp_player.grid_columnconfigure(0, minsize=92)
        COL_LBL_W = 55
        tk.Label(f_p_right, text=ui('ui_0226'), font=LBL_FONT, anchor='e').grid(row=0, column=1, padx=(0, 4), pady=3, sticky='e')
        f_name = tk.Frame(f_p_right)
        f_name.grid(row=0, column=2, columnspan=3, padx=0, pady=3, sticky='w')
        tk.Label(f_name, text=ui('ui_0227'), font=VAL_FONT, fg='#666666').pack(side=tk.LEFT)
        last_name_host = tk.Frame(f_name, width=116, height=23)
        last_name_host.pack(side=tk.LEFT, padx=(3, 8))
        self.txt_last_name = NativeWinEdit(last_name_host, lambda: None, width=116, height=23)
        tk.Label(f_name, text=ui('ui_0228'), font=VAL_FONT, fg='#666666').pack(side=tk.LEFT)
        first_name_host = tk.Frame(f_name, width=116, height=23)
        first_name_host.pack(side=tk.LEFT, padx=(3, 0))
        self.txt_first_name = NativeWinEdit(first_name_host, lambda: None, width=116, height=23)
        tk.Label(f_p_right, text=ui('ui_0231'), font=LBL_FONT, anchor='e').grid(row=1, column=1, padx=(0, 4), pady=3, sticky='e')
        f_nat = tk.Frame(f_p_right)
        f_nat.grid(row=1, column=2, columnspan=3, pady=3, sticky='w')
        self.cbo_nation = ttk.Combobox(f_nat, values=BASIC_NATIONS, state='readonly', width=26, font=VAL_FONT)
        self.cbo_nation.pack(side=tk.LEFT, padx=(0, 4))
        self.chk_all_nations = tk.BooleanVar(value=False)
        self.chk_nat_widget = tk.Checkbutton(f_nat, text=ui('ui_0156'), variable=self.chk_all_nations, command=self.toggle_all_nations, font=VAL_FONT)
        self.chk_nat_widget.pack(side=tk.LEFT)
        tk.Label(f_p_right, text=ui('ui_0229'), font=LBL_FONT, anchor='e').grid(row=2, column=1, padx=(0, 4), pady=3, sticky='e')
        self.cbo_job = ttk.Combobox(f_p_right, values=JOB_NAMES, state='readonly', width=9, font=VAL_FONT)
        self.cbo_job.grid(row=2, column=2, pady=3, sticky='w')
        tk.Label(f_p_right, text=ui('ui_0230'), font=LBL_FONT, anchor='e').grid(row=2, column=3, padx=(8, 2), pady=3, sticky='e')
        self.cbo_blood = ttk.Combobox(f_p_right, values=BLOOD_NAMES, state='readonly', width=4, font=VAL_FONT)
        self.cbo_blood.grid(row=2, column=4, pady=3, sticky='w')
        self.cbo_blood.bind('<<ComboboxSelected>>', lambda e: self.update_wife_combo_options())
        tk.Label(f_p_right, text=ui('ui_0232'), font=LBL_FONT, anchor='e').grid(row=3, column=1, padx=(0, 4), pady=3, sticky='e')
        f_birth = tk.Frame(f_p_right)
        f_birth.grid(row=3, column=2, pady=3, sticky='w')
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
        tk.Label(f_p_right, text=ui('ui_0236'), font=LBL_FONT, anchor='e', fg='#1A73E8').grid(row=3, column=3, padx=(8, 2), pady=3, sticky='e')
        f_game = tk.Frame(f_p_right)
        f_game.grid(row=3, column=4, pady=3, sticky='w')
        self.spn_game_y = ttk.Spinbox(f_game, from_=1480, to=1559, width=5)
        self.spn_game_m = ttk.Spinbox(f_game, from_=1, to=12, width=3)
        self.spn_game_d = ttk.Spinbox(f_game, from_=1, to=31, width=3)
        self.set_spin_val(self.spn_game_y, 1480)
        self.set_spin_val(self.spn_game_m, 1)
        self.set_spin_val(self.spn_game_d, 1)
        for spinner in (self.spn_game_y, self.spn_game_m, self.spn_game_d):
            spinner.bind('<Return>', self._on_game_date_changed, add='+')
            spinner.bind('<FocusOut>', self._on_game_date_changed, add='+')
            spinner.bind('<<Increment>>', self._on_game_date_changed, add='+')
            spinner.bind('<<Decrement>>', self._on_game_date_changed, add='+')
        self.game_date_picker = CalendarDatePicker(
            f_game, self._get_game_date, self._set_game_date_from_calendar,
            font=VAL_FONT, min_year=1480, max_year=1559,
        )
        self.game_date_picker.pack(side=tk.LEFT)
        tk.Label(f_p_right, text=ui('ui_0399'), font=LBL_FONT, anchor='e').grid(row=4, column=1, padx=(0, 4), pady=3, sticky='e')
        self.lbl_birth_zodiac = tk.Label(f_p_right, text='', font=('Malgun Gothic', 8, 'bold'), fg='#000000', anchor='w')
        self.lbl_birth_zodiac.grid(row=4, column=2, pady=3, sticky='w')
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
        btn_wife_book = tk.Button(f_w_right, text=ui('ui_0158'), font=('Malgun Gothic', 8, 'bold'), command=self.open_barmaid_guide_html, bg='#FFF8E1', fg='#B06000', padx=4, pady=1)
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
        self.lbl_wife_city = tk.Label(f_w_right, text=UI_EMPTY_VALUE, font=('Malgun Gothic', 8, 'bold'), anchor='w')
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
        self.lbl_wife_compat = tk.Label(f_w_right, text=UI_EMPTY_VALUE, font=('Malgun Gothic', 8, 'bold'), anchor='w')
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
        tk.Label(f_stats_top, text=ui('ui_0390', 255), font=('Malgun Gothic', 9, 'bold')).pack(side=tk.LEFT, padx=2)
        self.spn_batch_stats = ttk.Spinbox(f_stats_top, from_=0, to=255, width=5, justify='center', font=('Malgun Gothic', 9, 'bold'))
        self.spn_batch_stats.set('255')
        self.spn_batch_stats.pack(side=tk.LEFT, padx=4)
        tk.Button(f_stats_top, text=ui('ui_0243'), bg='#E6F4EA', fg='#137333', font=('Malgun Gothic', 9, 'bold'), command=self.apply_batch_stats).pack(side=tk.LEFT, padx=4)
        cols_stat = ('index', 'field', 'value', 'description')
        f_tree_s = tk.Frame(grp_stats)
        f_tree_s.pack(fill=tk.BOTH, expand=True, pady=2)
        self.tree_stats = ttk.Treeview(f_tree_s, columns=cols_stat, show='headings', height=7)
        col_defs_stat = [('index', 35, 'center', False), ('field', 105, 'center', False), ('value', 90, 'center', False), ('description', 200, 'w', True)]
        for c, w, a, s in col_defs_stat:
            self.tree_stats.heading(c, text=TREE_COLUMN_TITLES['stats'][c])
            self.tree_stats.column(c, width=w, anchor=a, stretch=s)
        self.tree_stats.pack(fill=tk.BOTH, expand=True, pady=2)
        self.tree_stats.bind('<Return>', lambda e: self.on_stat_edit_request())
        self.tree_stats.bind('<Double-1>', self.on_stat_edit_request)
        self.tree_stats.bind('<Button-3>', self.on_stat_edit_request)
        grp_money = tk.Frame(self.profile_page_money, padx=8, pady=6)
        grp_money.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        f_money_top = tk.Frame(grp_money)
        f_money_top.pack(side=tk.TOP, fill=tk.X, pady=2)
        tk.Label(f_money_top, text=ui('ui_0390', '99,999,999'), font=('Malgun Gothic', 9, 'bold')).pack(side=tk.LEFT, padx=2)
        self.spn_batch_money = ttk.Spinbox(f_money_top, from_=0, to=99999999, width=11, justify='center', font=('Malgun Gothic', 9, 'bold'))
        self.spn_batch_money.set('99999999')
        self.spn_batch_money.pack(side=tk.LEFT, padx=4)
        tk.Button(f_money_top, text=ui('ui_0243'), bg='#E6F4EA', fg='#137333', font=('Malgun Gothic', 9, 'bold'), command=self.apply_batch_money).pack(side=tk.LEFT, padx=4)
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
        grp_reputation = tk.Frame(self.profile_page_reputation, padx=8, pady=6)
        grp_reputation.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        f_reputation_top = tk.Frame(grp_reputation)
        f_reputation_top.pack(side=tk.TOP, fill=tk.X, pady=2)
        tk.Label(f_reputation_top, text=ui('ui_0390', '99,999'), font=('Malgun Gothic', 9, 'bold')).pack(side=tk.LEFT, padx=2)
        self.spn_batch_reputation = ttk.Spinbox(f_reputation_top, from_=0, to=99999, width=8, justify='center', font=('Malgun Gothic', 9, 'bold'))
        self.spn_batch_reputation.set('99999')
        self.spn_batch_reputation.pack(side=tk.LEFT, padx=4)
        tk.Button(f_reputation_top, text=ui('ui_0243'), bg='#E6F4EA', fg='#137333', font=('Malgun Gothic', 9, 'bold'), command=self.apply_batch_reputation).pack(side=tk.LEFT, padx=4)
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
        self.stat_values = [255] * 6 + [0x7FFFFFFF]
        self.money_values = [0] * 5
        self.update_player_face_display()
        self.update_wife_display()
        self.refresh_officer_display()

    def build_crew_profile(self, key, page, role_offset, role_name):
        """항해사·측량사·통역에 공통으로 쓰는 승무원 선택 화면을 만든다."""
        label_font, value_font = ('Malgun Gothic', 8, 'bold'), ('Malgun Gothic', 8)
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
        pages = [ttk.Frame(details) for _ in range(5)]
        for tab, title in zip(pages, (ui('ui_0406'), ui('ui_0385'), ui('ui_0407'), ui('ui_0388'), ui('ui_0389'))):
            details.add(tab, text=title)
        trees = (
            self._make_officer_tree(pages[0], ('index', 'field', 'value'), (('No', 38, 'center', False), ('항목', 120, 'w', True), ('기본값', 170, 'w', True)), 7),
            self._make_officer_tree(pages[1], ('index', 'field', 'value'), (('No', 38, 'center', False), ('항목', 150, 'w', True), ('수치', 100, 'center', False)), 8),
            self._make_officer_tree(pages[2], ('index', 'field', 'value'), (('No', 38, 'center', False), ('항목', 150, 'w', True), ('수치', 100, 'center', False)), 2),
            self._make_officer_tree(pages[3], ('index', 'field', 'value'), (('No', 38, 'center', False), ('기술', 150, 'w', True), ('레벨', 100, 'center', False)), 13),
            self._make_officer_tree(pages[4], ('index', 'field', 'value'), (('No', 38, 'center', False), ('언어', 150, 'w', True), ('레벨', 100, 'center', False)), 12),
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
        previous_id = previous - 0x1000 if (previous & 0xFF00) == 0x1000 else None
        struct.pack_into('<H', self.file_buffer, role_offset, 0xFFFF)
        if previous_id is not None:
            self._restore_officer_static_location(previous_id)
        if key == 'officer':
            self._officer_selected_id = None
            self._officer_preview_id = None
        self._refresh_role_display(key)
        self.lbl_status.config(text=f"{profile['name']}을(를) 해제했습니다.")

    def assign_role(self, key, character_id):
        """네 역할에 공통으로 적용되는 즉시 지정 처리다."""
        profile = self._crew_profiles.get(key)
        if profile is None or not self.file_buffer or character_id not in CHARACTER_BY_ID:
            return
        role_offset, role_name = profile['offset'], profile['name']
        previous = struct.unpack_from('<H', self.file_buffer, role_offset)[0]
        previous_id = previous - 0x1000 if (previous & 0xFF00) == 0x1000 else None
        struct.pack_into('<H', self.file_buffer, role_offset, 0x1000 | character_id)
        record_offset = 0x924A + character_id * 0x90
        if record_offset + 0x63 <= len(self.file_buffer):
            self.file_buffer[record_offset + 0x2E] = self.file_buffer[0x57] if len(self.file_buffer) > 0x57 else 0xFF
            self.file_buffer[record_offset + 0x30] = 0xFF
        if previous_id is not None and previous_id != character_id:
            self._restore_officer_static_location(previous_id)
        if key == 'officer':
            self._officer_selected_id = character_id
            self._officer_preview_id = character_id
        self._refresh_role_display(key)
        self.lbl_status.config(text=f'{role_name}을(를) {CHARACTER_BY_ID[character_id].get("name", character_id)}(으)로 변경했습니다.')

    def refresh_crew_display(self, key):
        profile = self._crew_profiles.get(key)
        if profile is None:
            return
        trees = profile['trees']
        for tree in trees:
            tree.delete(*tree.get_children())
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
        try:
            age = int(character['age_at_1480']) + (int(self.spn_game_y.get()) - 1480)
        except (KeyError, TypeError, ValueError, tk.TclError):
            age = struct.unpack_from('<b', record, record_offset + 0x5C)[0]
        city_id = int(character.get('city_id', record[record_offset + 0x2E]))
        building_id = int(character.get('building_id', record[record_offset + 0x30]))
        hire_state = self._character_hire_state(character_id, character, record_offset)
        name = character.get('name', UI_EMPTY_VALUE)
        basic_rows = ((ui('ui_0062'), name), ('나이', f'{age}세' if age >= 0 else '미등장'),
                      ('국적', NATION_NAMES[int(character.get('nation_id', -1))] if 0 <= int(character.get('nation_id', -1)) < len(NATION_NAMES) else UI_EMPTY_VALUE),
                      ('직업', JOB_NAMES[int(character.get('job_id', -1))] if 0 <= int(character.get('job_id', -1)) < len(JOB_NAMES) else UI_EMPTY_VALUE),
                      (ui('ui_0354'), '함대 소속' if city_id == 0xFF else CITY_NAME_BY_ID.get(city_id, UI_EMPTY_VALUE)),
                      (ui('ui_0409'), {4: ui('ui_0412'), 5: ui('ui_0413')}.get(building_id, '-')),
                      (ui('ui_0410'), {1: ui('ui_0403'), 2: ui('ui_0404'), 3: ui('ui_0405')}.get(hire_state, UI_EMPTY_VALUE)),
                      (ui('ui_0411'), '미등장' if age < 18 else '은퇴' if age > 60 else '등장'))
        for index, row in enumerate(basic_rows): trees[0].insert('', tk.END, values=(index, *row))
        stats = (('체력', record[record_offset]), ('지력', record[record_offset+1]), ('무력', record[record_offset+2]), ('매력', record[record_offset+3]), ('운', record[record_offset+4]), ('신앙심', record[record_offset+5]), ('생명력', record[record_offset+0x66]), ('주량', record[record_offset+6]))
        for index, row in enumerate(stats): trees[1].insert('', tk.END, values=(index, *row))
        trees[2].insert('', tk.END, values=(0, '명성', f"{struct.unpack_from('<H', record, record_offset + 0x26)[0]:,}"))
        trees[2].insert('', tk.END, values=(1, '악명', f"{struct.unpack_from('<H', record, record_offset + 0x2A)[0]:,}"))
        for index, (skill_name, _offset, _description) in enumerate(SKILLS_DATA):
            target, row = (trees[3], index) if index < 13 else (trees[4], index - 13)
            target.insert('', tk.END, values=(row, skill_name, record[record_offset + 0x0B + index]))
        self._schedule_treeview_autofit(*trees)

    def _active_role_character_ids(self):
        """현재 세이브의 네 역할 슬롯을 한 번 읽어 고용 중 인물 ID 집합으로 만든다."""
        if not self.file_buffer:
            return frozenset()
        return frozenset(
            code - 0x1000
            for role_offset in ROLE_SLOT_OFFSETS
            if len(self.file_buffer) >= role_offset + 2
            for code in (struct.unpack_from('<H', self.file_buffer, role_offset)[0],)
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
        label_font = ('Malgun Gothic', 8, 'bold')
        value_font = ('Malgun Gothic', 8)

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
        self.officer_page_basic = ttk.Frame(self.officer_details)
        self.officer_page_stats = ttk.Frame(self.officer_details)
        self.officer_page_fame = ttk.Frame(self.officer_details)
        self.officer_page_tech = ttk.Frame(self.officer_details)
        self.officer_page_lang = ttk.Frame(self.officer_details)
        for tab, title in ((self.officer_page_basic, '기본 정보'), (self.officer_page_stats, '능력치'), (self.officer_page_fame, '명성'),
                           (self.officer_page_tech, '기술'), (self.officer_page_lang, '언어')):
            self.officer_details.add(tab, text=title)
        self.officer_details.grid(row=1, column=0, sticky='nsew', padx=3, pady=(0, 4))

        self.tree_officer_basic = self._make_officer_tree(
            self.officer_page_basic, ('index', 'field', 'value'),
            (('No', 38, 'center', False), ('항목', 120, 'w', True), ('기본값', 170, 'w', True)), 7)
        self.tree_officer_stats = self._make_officer_tree(
            self.officer_page_stats, ('index', 'field', 'value'),
            (('No', 38, 'center', False), ('항목', 150, 'w', True), ('수치', 100, 'center', False)), 8)
        self.tree_officer_fame = self._make_officer_tree(
            self.officer_page_fame, ('index', 'field', 'value'),
            (('No', 38, 'center', False), ('항목', 150, 'w', True), ('수치', 120, 'e', True)), 2)
        self.tree_officer_tech = self._make_officer_tree(
            self.officer_page_tech, ('index', 'field', 'level'),
            (('No', 38, 'center', False), ('항목', 170, 'w', True), ('레벨', 90, 'center', False)), 8)
        self.tree_officer_lang = self._make_officer_tree(
            self.officer_page_lang, ('index', 'field', 'level'),
            (('No', 38, 'center', False), ('언어', 180, 'w', True), ('레벨', 90, 'center', False)), 8)

    @staticmethod
    def _make_officer_tree(parent, columns, definitions, height):
        frame = tk.Frame(parent, padx=8, pady=6)
        frame.pack(fill=tk.BOTH, expand=True)
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
        if query == '없음':
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


    def _restore_officer_static_location(self, character_id):
        """해제된 부관을 정적 표의 도시·건물·고용 상태로 되돌린다."""
        character = CHARACTER_BY_ID.get(character_id)
        record_offset = 0x924A + character_id * 0x90
        if not character or record_offset + 0x63 > len(self.file_buffer):
            return
        # 다른 승무원 역할에 남아 있으면 함대 소속 상태를 유지한다.
        for role_offset in ROLE_SLOT_OFFSETS:
            role_code = struct.unpack_from('<H', self.file_buffer, role_offset)[0]
            if role_code == (0x1000 | character_id):
                return
        city_id = int(character.get('city_id', -1))
        self.file_buffer[record_offset + 0x2E] = city_id if 0 <= city_id <= 0xFF else 0xFF
        self.file_buffer[record_offset + 0x30] = int(character.get('building_id', 0xFF)) & 0xFF
        self.file_buffer[record_offset + 0x62] = int(character.get('hire_state', 0)) & 0xFF


    def update_player_face_display(self):
        """주인공 얼굴 초상화 라벨 갱신"""
        if not self.file_buffer or self.player_face_id is None:
            self.lbl_player_face.config(image='')
            return
        else:
            img_p = get_face_image_path('male', self.player_face_id)
            if img_p and os.path.exists(img_p):
                    photo = get_cached_photo(img_p)
                    if photo:
                        self.player_face_photo = photo
                        self.lbl_player_face.config(image=self.player_face_photo)

    def refresh_officer_display(self, preview_character_id=None):
        """세이브의 부관 참조(0xA5)를 읽어 읽기 전용 인물 탭을 갱신한다."""
        trees = tuple(getattr(self, name, None) for name in (
            'tree_officer_basic', 'tree_officer_stats', 'tree_officer_fame', 'tree_officer_tech', 'tree_officer_lang'))
        for tree in trees:
            if tree is not None:
                tree.delete(*tree.get_children())
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
        if search_tree is not None and search_tree.exists(str(character_id)):
            if search_tree.selection() != (str(character_id),):
                search_tree.selection_set(str(character_id))
            search_tree.focus(str(character_id))
            search_tree.see(str(character_id))

        record = self.file_buffer
        character = CHARACTER_BY_ID.get(character_id, {})
        first_name = record[record_offset + 0x32:record_offset + 0x32 + 20].split(b'\0')[0].decode('cp949', errors='ignore').strip()
        last_name = record[record_offset + 0x45:record_offset + 0x45 + 19].split(b'\0')[0].decode('cp949', errors='ignore').strip()
        name = ' '.join(part for part in (first_name, last_name) if part) or character.get('name', UI_EMPTY_VALUE)
        nation_id = int(character.get('nation_id', -1))
        job_id = int(character.get('job_id', -1))
        # 정적 표의 1480년 기준 나이로 생년을 보존하므로, 현재 연도에 맞춰 계산한다.
        try:
            current_year = int(self.spn_game_y.get())
            age = int(character['age_at_1480']) + (current_year - 1480)
        except (KeyError, TypeError, ValueError, tk.TclError):
            age = struct.unpack_from('<b', record, record_offset + 0x5C)[0]
        # 기본 정보 탭은 등장인물 표의 기본값을 표시한다. 부관으로 지정한 직후의
        # 세이브 레코드는 소재지가 함대, 건물이 0xFF, 고용 상태가 3으로 바뀌므로
        # 그것을 그대로 표시하면 어떤 인물을 선택해도 "- / 고용 중"만 보이게 된다.
        default_city_id = int(character.get('city_id', record[record_offset + 0x2E]))
        default_building_id = int(character.get('building_id', record[record_offset + 0x30]))
        default_hire_state = int(character.get('hire_state', record[record_offset + 0x62]))
        city_name = '함대 소속' if default_city_id == 0xFF else CITY_NAME_BY_ID.get(default_city_id, UI_EMPTY_VALUE)
        building_name = {4: '주점', 5: '여관'}.get(default_building_id, '')
        hire_text = {1: '대화 가능', 2: '고용 가능', 3: '고용 중'}.get(default_hire_state, UI_EMPTY_VALUE)
        self._officer_selected_id = character_id
        appearance_text = '미등장' if age < 18 else '은퇴' if age > 60 else '등장'
        basic_rows = (
            ('이름', name),
            ('나이', f'{age}세' if age >= 0 else '미등장'),
            ('국적', NATION_NAMES[nation_id] if 0 <= nation_id < len(NATION_NAMES) else UI_EMPTY_VALUE),
            ('직업', JOB_NAMES[job_id] if 0 <= job_id < len(JOB_NAMES) else UI_EMPTY_VALUE),
            ('도시', city_name),
            ('건물', building_name or '-'),
            ('고용', hire_text),
            ('등장', appearance_text),
        )
        for index, (field, value) in enumerate(basic_rows):
            self.tree_officer_basic.insert('', tk.END, values=(index, field, value))

        image_path = get_sailer_image_path(character_id)
        if image_path:
            photo = get_cached_photo(image_path)
            if photo:
                self.officer_face_photo = photo
                self.lbl_officer_face.config(image=photo)

        stat_rows = (
            ('체력', record[record_offset + 0x00]),
            ('지력', record[record_offset + 0x01]),
            ('무력', record[record_offset + 0x02]),
            ('매력', record[record_offset + 0x03]),
            ('운', record[record_offset + 0x04]),
            ('신앙심', record[record_offset + 0x05]),
            ('생명력', record[record_offset + 0x66]),
            ('주량', record[record_offset + 0x06]),
        )
        for index, (stat_name, value) in enumerate(stat_rows):
            self.tree_officer_stats.insert('', tk.END, values=(index, stat_name, value))
        fame = struct.unpack_from('<H', record, record_offset + 0x26)[0]
        infamy = struct.unpack_from('<H', record, record_offset + 0x2A)[0]
        self.tree_officer_fame.insert('', tk.END, values=(0, '명성', f'{fame:,}'))
        self.tree_officer_fame.insert('', tk.END, values=(1, '악명', f'{infamy:,}'))
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
        tree.item(rows[1], values=(1, '나이', f'{age}세' if age >= 0 else '미등장'))
        tree.item(rows[7], values=(7, ui('ui_0411'), '미등장' if age < 18 else '은퇴' if age > 60 else '등장'))

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

    def _refresh_wife_languages(self, barmaid=None):
        """선택한 부인의 신상정보와 전수 언어를 하단 목록에 표시한다."""
        tree = getattr(self, 'tree_wife_languages', None)
        if tree is None:
            return
        tree.delete(*tree.get_children())
        if barmaid is None:
            for index, field in enumerate(('도시', '등장', '별자리', '혈액형', '성격', ui('ui_0061'), '전수 언어')):
                tree.insert('', tk.END, values=(index, field, '-'))
            return
        flags = int(barmaid.get('language_flags', 0))
        languages = [name for bit, name in enumerate(LANGUAGE_NAMES) if flags & (1 << bit)]
        fortune = self.lbl_wife_compat.cget('text') if hasattr(self, 'lbl_wife_compat') else '-'
        rows = (
            ('도시', get_barmaid_city_name(barmaid)),
            ('등장', f"{barmaid['year']}년"),
            ('별자리', get_barmaid_zodiac_name(barmaid)),
            ('혈액형', get_barmaid_blood_name(barmaid)),
            ('성격', get_barmaid_personality(barmaid)),
            (ui('ui_0061'), fortune or '-'),
            ('전수 언어', ', '.join(languages) if languages else '-'),
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
                self.lbl_wife_year.config(text=f"{b['year']}년")
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
            font=('Malgun Gothic', 8), padx=8, pady=6,
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
        if query == '없음':
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
        if selection[0] == '__none__':
            self._wife_selected_id = None
            self.update_wife_display()
            self.lbl_status.config(text=ui('ui_0415'))
            return
        barmaid = BARMAID_BY_ID.get(int(selection[0]))
        if barmaid is None:
            return
        self._wife_selected_id = barmaid['id']
        self.update_wife_display()
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
    def refresh_stats_table(self):
        self.tree_stats.delete(*self.tree_stats.get_children())
        stat_defs = EDITOR_MAPPINGS['profile_stat_definitions']
        for i, (name, desc) in enumerate(stat_defs):
            val = self.stat_values[i] if self.file_buffer else UI_EMPTY_VALUE
            self.tree_stats.insert('', tk.END, iid=str(i), values=(i, name, val, desc))
        self._schedule_treeview_autofit(self.tree_stats)
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
                max_value = 0x7FFFFFFF if idx == 6 else 255
                prompt = (ui('ui_0034', stat_names[idx], max_value)
                          if idx == 6 else ui('ui_0033', stat_names[idx]))
                new_v = self.ask_bounded_integer(ui('ui_0201'), prompt, self.stat_values[idx], 0, max_value)
                if new_v is not None:
                    self.stat_values[idx] = new_v
                    if idx == 0:
                        # 주인공 생명력은 체력 변경에 맞춰 게임의 기본 비율(체력 × 20)로 갱신한다.
                        self.stat_values[6] = new_v * 20
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
        self.stat_values[6] = self.stat_values[0] * 20
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
            target_v = min(99999, max(0, int(self.spn_batch_reputation.get())))
        except (TypeError, ValueError):
            target_v = 99999
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
    def build_skills_tab(self):
        # ***<module>.CDS3SaveEditorApp.build_skills_tab: Failure: Different bytecode
        f_tech = tk.Frame(self.profile_page_tech, padx=8, pady=6)
        f_tech.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        f_tech_top = tk.Frame(f_tech)
        f_tech_top.pack(side=tk.TOP, fill=tk.X, pady=4)
        tk.Label(f_tech_top, text=ui('ui_0247'), font=('Malgun Gothic', 9, 'bold')).pack(side=tk.LEFT, padx=2)
        self.spn_batch_tech = ttk.Spinbox(f_tech_top, from_=0, to=3, width=4, justify='center', font=('Malgun Gothic', 9, 'bold'))
        self.spn_batch_tech.set('3')
        self.spn_batch_tech.pack(side=tk.LEFT, padx=4)
        tk.Button(f_tech_top, text=ui('ui_0243'), bg='#E6F4EA', fg='#137333', font=('Malgun Gothic', 9, 'bold'), command=self.apply_batch_tech).pack(side=tk.LEFT, padx=4)
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
        f_lang_top.pack(side=tk.TOP, fill=tk.X, pady=4)
        tk.Label(f_lang_top, text=ui('ui_0247'), font=('Malgun Gothic', 9, 'bold')).pack(side=tk.LEFT, padx=2)
        self.spn_batch_lang = ttk.Spinbox(f_lang_top, from_=0, to=3, width=4, justify='center', font=('Malgun Gothic', 9, 'bold'))
        self.spn_batch_lang.set('3')
        self.spn_batch_lang.pack(side=tk.LEFT, padx=4)
        tk.Button(f_lang_top, text=ui('ui_0243'), bg='#E6F4EA', fg='#137333', font=('Malgun Gothic', 9, 'bold'), command=self.apply_batch_lang).pack(side=tk.LEFT, padx=4)
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
        self.lbl_pocket_count = tk.Label(f_pocket_hdr, text=inventory_text('ui_0283', 'ui_0281', 0, 16), font=('Malgun Gothic', 9, 'bold'), fg='#1A73E8')
        self.lbl_pocket_count.pack(side=tk.LEFT)
        tk.Button(f_pocket_hdr, text=ui('ui_0376'), bg='#FCE8E6', fg='#D93025', command=self.clear_pocket).pack(side=tk.RIGHT, padx=(8, 0))
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
        self.lbl_storage_count = tk.Label(f_storage_hdr, text=inventory_text('ui_0283', 'ui_0282', 0, 99), font=('Malgun Gothic', 9, 'bold'), fg='#1A73E8')
        self.lbl_storage_count.pack(side=tk.LEFT)
        tk.Button(f_storage_hdr, text=ui('ui_0376'), bg='#FCE8E6', fg='#D93025', command=self.clear_storage).pack(side=tk.RIGHT, padx=(8, 0))
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
        category_counts = {name: sum(d['category'] == name for d in self.discovery_db) for name in DISCOVERY_CATEGORY_NAMES}
        category_values = [ui('ui_0365', len(self.discovery_db))]
        category_values.extend(f'{name} ({category_counts[name]})' for name in DISCOVERY_CATEGORY_NAMES)
        self.cbo_disc_cat = ttk.Combobox(top_f, values=category_values, state='readonly', width=18)
        self.cbo_disc_cat.current(0)
        self.cbo_disc_cat.pack(side=tk.LEFT, padx=2)
        self.cbo_disc_cat.bind('<<ComboboxSelected>>', lambda e: self.refresh_discoveries_table())
        tk.Label(top_f, text=ui('ui_0260')).pack(side=tk.LEFT, padx=2)
        self.cbo_disc_status = ttk.Combobox(top_f, values=discovery_status_options(include_all=True), state='readonly', width=12)
        self.cbo_disc_status.current(0)
        self.cbo_disc_status.pack(side=tk.LEFT, padx=2)
        self.cbo_disc_status.bind('<<ComboboxSelected>>', lambda e: self.refresh_discoveries_table())
        tk.Label(top_f, text=ui('ui_0251')).pack(side=tk.LEFT, padx=2)
        disc_search_host = tk.Frame(top_f, width=78, height=23)
        disc_search_host.pack(side=tk.LEFT, padx=2)
        self.txt_disc_search = NativeWinEdit(
            disc_search_host,
            lambda: self._schedule_search_refresh('discoveries', self.refresh_discoveries_table),
            width=78, height=23,
        )
        self.lbl_disc_count = tk.Label(top_f, text=ui('ui_0036', 0, 0, len(self.discovery_db), 0.0), font=('Malgun Gothic', 9, 'bold'), fg='#1A73E8')
        self.lbl_disc_count.pack(side=tk.LEFT, padx=6)
        self.cbo_batch_status = ttk.Combobox(top_f, values=discovery_status_options(), state='readonly', width=13)
        self.cbo_batch_status.current(0)
        self.cbo_batch_status.pack(side=tk.LEFT, padx=4)
        tk.Button(top_f, text=ui('ui_0243'), font=('Malgun Gothic', 9, 'bold'), bg='#E6F4EA', fg='#137333', command=self.apply_batch_discovery_state).pack(side=tk.LEFT, padx=2)
        tree_f = tk.Frame(parent)
        tree_f.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        cols = ('index', 'game_id', 'category', 'name', 'status', 'found_date', 'reported_date', 'reporter')
        self.tree_disc = ttk.Treeview(tree_f, columns=cols, show='headings', height=18)
        self.tree_disc.heading('index', text=TREE_COLUMN_TITLES['discovery']['index'])
        self.tree_disc.heading('game_id', text=TREE_COLUMN_TITLES['discovery']['game_id'])
        self.tree_disc.heading('category', text=TREE_COLUMN_TITLES['discovery']['category'])
        self.tree_disc.heading('name', text=TREE_COLUMN_TITLES['discovery']['name'])
        self.tree_disc.heading('status', text=TREE_COLUMN_TITLES['discovery']['status'])
        self.tree_disc.heading('found_date', text=TREE_COLUMN_TITLES['discovery']['found_date'])
        self.tree_disc.heading('reported_date', text=TREE_COLUMN_TITLES['discovery']['reported_date'])
        self.tree_disc.heading('reporter', text=TREE_COLUMN_TITLES['discovery']['reporter'])
        col_defs_disc = [('index', 55, 'center', False), ('game_id', 55, 'center', False), ('category', 120, 'center', False), ('name', 170, 'w', True), ('status', 135, 'center', False), ('found_date', 115, 'center', False), ('reported_date', 115, 'center', False), ('reporter', 125, 'center', False)]
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
        rep_cnt = 0
        disc_cnt = 0
        for i, d, search_key in self._discovery_search_index:
            st = discovery_states[i] if self.file_buffer else 0
            if self.file_buffer:
                if st == 2:
                    rep_cnt += 1
                else:
                    if st == 1:
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
                d_name = discovery_discoverers[i] if discovery_discoverers[i] else p_name if st > 0 else UI_EMPTY_VALUE
                disc_d = discovery_dates[i]
                rep_d = report_dates[i]
            else:
                st_text = UI_EMPTY_VALUE
                d_name = UI_EMPTY_VALUE
                disc_d = UI_EMPTY_VALUE
                rep_d = UI_EMPTY_VALUE
            self.tree_disc.insert('', tk.END, iid=str(i), values=(d['index'], d['disc_id'], d['category'], d['name'], st_text, disc_d, rep_d, d_name))
        total = len(self.discovery_db)
        if self.file_buffer:
            pct = (rep_cnt + disc_cnt) / total * 100.0 if total > 0 else 0
            self.lbl_disc_count.config(text=ui('ui_0036', rep_cnt, disc_cnt, total, pct))
        else:
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
            if target_st == 2:
                self.discovery_discoverer[idx] = p_name
                if self.discovery_disc_date[idx] == UI_EMPTY_VALUE:
                    self.discovery_disc_date[idx] = cur_date_str
                self.discovery_rep_date[idx] = cur_date_str
            else:
                if target_st == 1:
                    self.discovery_discoverer[idx] = p_name
                    self.discovery_disc_date[idx] = cur_date_str
                    self.discovery_rep_date[idx] = UI_EMPTY_VALUE
                else:
                    self.discovery_discoverer[idx] = ''
                    self.discovery_disc_date[idx] = UI_EMPTY_VALUE
                    self.discovery_rep_date[idx] = UI_EMPTY_VALUE
            self.sync_sea_monster_from_discovery(self.discovery_db[idx]['index'], target_st > 0)
            self._discovery_view_revision += 1
            self.refresh_discoveries_table()
            self.tree_disc.selection_set(str(idx))
    def cycle_selected_discovery_state(self, _event=None):
        """Enter: 미발견 → 발견 → 보고 완료 → 미발견으로 즉시 전환한다."""
        if not self.file_buffer:
            return 'break'
        sel = self.tree_disc.selection()
        if sel:
            idx = int(sel[0])
            self.set_discovery_single_state(idx, (self.discovery_state[idx] + 1) % 3)
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
                    d_name = self.discovery_discoverer[d_idx] if self.file_buffer and self.discovery_discoverer[d_idx] else p_name if st > 0 else UI_EMPTY_VALUE
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
        d, desc, st, disc_d, rep_d, d_name = get_disc_info_fn(idx)
        if d:
            DiscoveryInfoModal(
                self.root, d, desc, current_state=st, disc_date=disc_d,
                rep_date=rep_d, discoverer=d_name,
                on_state_change_callback=on_state_change if self.file_buffer else None,
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
        menu.tk_popup(x, y)
    def apply_batch_discovery_state(self):
        if not self.file_buffer:
            return
        else:
            target_st = discovery_state_from_text(self.cbo_batch_status.get())
            if target_st is None:
                return
            self.batch_set_discovery_state(target_st)
    def batch_set_discovery_state(self, target_st):
        if not self.file_buffer:
            return
        else:
            p_name = self.get_player_full_name()
            cur_date_str = self.get_current_game_date_str()
            for i in range(len(self.discovery_db)):
                self.discovery_state[i] = target_st
                if target_st == 2:
                    self.discovery_discoverer[i] = p_name
                    if self.discovery_disc_date[i] == UI_EMPTY_VALUE:
                        self.discovery_disc_date[i] = cur_date_str
                    self.discovery_rep_date[i] = cur_date_str
                else:
                    if target_st == 1:
                        self.discovery_discoverer[i] = p_name
                        self.discovery_disc_date[i] = cur_date_str
                        self.discovery_rep_date[i] = UI_EMPTY_VALUE
                    else:
                        self.discovery_discoverer[i] = ''
                        self.discovery_disc_date[i] = UI_EMPTY_VALUE
                        self.discovery_rep_date[i] = UI_EMPTY_VALUE
                self.sync_sea_monster_from_discovery(self.discovery_db[i]['index'], target_st > 0)
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
        tk.Button(top_f, text=ui('ui_0243'), font=('Malgun Gothic', 9, 'bold'), bg='#E6F4EA', fg='#137333', command=self.apply_batch_event_state).pack(side=tk.LEFT, padx=4)
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
        for attr_name in ('txt_last_name', 'txt_first_name', 'cbo_wife', 'cbo_officer_name'):
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
                min(99999, struct.unpack_from('<I', self.file_buffer, offset)[0])
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
                # 세이브에 기록하는 상태 마커는 미발견 0x0C, 발견 0x4C,
                # 보고 완료 0xCC이다. 상위 비트만 검사하면 기존 0x40/0xC0
                # 형식도 함께 읽을 수 있다.
                has_rep = (marker & 0xC0) == 0xC0
                has_disc = (marker & 0x40) != 0
                if has_disc:
                    dy = struct.unpack_from('<H', self.file_buffer, off + 40)[0]
                    self.discovery_disc_date[i] = format_game_date(dy if dy > 0 else gy, gm, gd)
                if has_rep:
                    ry = struct.unpack_from('<H', self.file_buffer, off + 134)[0]
                    self.discovery_rep_date[i] = format_game_date(ry if ry > 0 else gy, gm, gd)
                    self.discovery_state[i] = 2
                    self.discovery_discoverer[i] = read_cp949(self.file_buffer, off + 95, 18) or read_cp949(self.file_buffer, off + 1, 18)
                elif has_disc:
                    self.discovery_state[i] = 1
                    self.discovery_discoverer[i] = read_cp949(self.file_buffer, off + 1, 18)
            # 카바신전은 접근 차단 이벤트의 조건 플래그이므로, 사용자가 상태를
            # 바꾸지 않았다면 저장 과정에서 해당 세이브 레코드를 건드리지 않는다.
            self.discovery_original_state = list(self.discovery_state)
            self._discovery_view_revision += 1
            self.refresh_discoveries_table()
            self.refresh_fleet_list()
            self.refresh_cities_list()
            # 다른 목록·탭의 갱신이 끝난 다음 배우자 선택 표시를 확정한다.
            self.root.after_idle(self._focus_loaded_wife_in_list)
            self.lbl_status.config(text=ui('ui_0366', os.path.basename(file_path)))
            self.root.title(f'{APP_TITLE} - [{os.path.basename(file_path)}]')
        except Exception as exc:
            messagebox.showerror(ui('ui_0367'), ui('ui_0368', exc))
        finally:
            self._is_loading_save = False
            self._suspend_tree_autofit = False
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
                        bak_msg = f'\n(백업 파일 생성됨: {bak_path})'
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
            struct.pack_into('<I', self.file_buffer, 51, min(0x7FFFFFFF, max(0, self.stat_values[6])))
            struct.pack_into('<I', self.file_buffer, 153, min(99999999, max(0, self.money_values[0])))
            struct.pack_into('<I', self.file_buffer, 157, min(99999999, max(0, self.money_values[1])))
            struct.pack_into('<I', self.file_buffer, 161, min(99999999, max(0, self.money_values[2])))
            struct.pack_into('<I', self.file_buffer, 83, min(99999, max(0, self.money_values[3])))
            struct.pack_into('<I', self.file_buffer, 87, min(99999, max(0, self.money_values[4])))
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
                # 카바신전(No.63)은 미수정 상태면 원본 바이트를 그대로 보존한다.
                # 그래야 일반 발견물 저장으로 인해 접근 차단 플래그가 바뀌지 않는다.
                if (d['index'] == 63 and
                        i < len(getattr(self, 'discovery_original_state', ())) and
                        self.discovery_state[i] == self.discovery_original_state[i]):
                    continue
                if d_off + 164 <= len(self.file_buffer):
                    st = self.discovery_state[i]
                    marker_off = d_off - 1
                    # 카바신전은 일반 미발견(0x0C)이 아니라 완전 미등록(0x00)
                    # 상태여야 백과사전에 빈 항목으로 남지 않는다. 다음 발견물의
                    # 공유 상태 마커(d_off + 163)는 보존한다.
                    if d['index'] == 63 and st == 0:
                        self.file_buffer[marker_off] = 0
                        self.file_buffer[d_off:d_off + 163] = b'\x00' * 163
                        # 일반 미발견 레코드와 동일하게 날짜 미설정 필드는 FF로
                        # 남겨 둔다. 이 값까지 0으로 만들면 원래의 미등록 레코드와
                        # 달라져 백과사전 순서 판정에 영향을 줄 수 있다.
                        self.file_buffer[d_off + 40:d_off + 48] = b'\xff' * 8
                        self.file_buffer[d_off + 134:d_off + 142] = b'\xff' * 8
                        continue
                    if st == 2:
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
                        if st == 1:
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
