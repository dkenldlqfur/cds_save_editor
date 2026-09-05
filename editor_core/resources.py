"""GUI에 의존하지 않는 JSON 리소스 및 공통 오류 문구 로더."""

import json
import os
import sys
from functools import lru_cache


def load_json_resource(filename, data_directory=True):
    """소스 실행과 PyInstaller 배포 환경 모두에서 JSON 리소스를 읽는다."""
    base_dirs = []
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            base_dirs.append(sys._MEIPASS)
        base_dirs.append(os.path.dirname(sys.executable))
    base_dirs.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
                with open(path, 'r', encoding='utf-8') as resource_file:
                    return json.load(resource_file)
            except FileNotFoundError:
                continue
    # 문구 리소스 로딩 전에도 실패할 수 있으므로 오류에는 파일명만 전달한다.
    raise FileNotFoundError(filename)


@lru_cache(maxsize=1)
def _error_messages():
    return load_json_resource('error_messages.json')['messages']


def error_text(key):
    """오류 문구는 처음 필요할 때만 읽고 중복 사용 지점에서는 공유한다."""
    return _error_messages()[key]
