"""Runtime owner for the editor's static game data.

The bundled JSON files are the fallback profile.  A later EXE importer can fork
that profile and overlay only fields which were successfully verified in the
selected executable.  Keeping the fallback values in the fork is important:
not every table/string used by the editor has a documented EXE location yet.
"""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .resources import load_json_resource


GAME_RESOURCE_FILES = {
    'master_data': 'master_data.json',
    'characters': 'character_database.json',
    'sponsors': 'sponsor_data.json',
    'fleet': 'fleet_data.json',
    'cities': 'city_data.json',
    'game_strings': 'game_strings.json',
    'trade_goods': 'trade_goods.json',
    'discovery_trade_goods': 'discovery_trade_goods.json',
    'data_categories': 'data_categories.json',
    'discovery_rewards': 'discovery_reward_items.json',
    'discovery_hints': 'discovery_hint_data.json',
    'map_locations': 'map_locations.json',
    'city_discovery_locations': 'city_discovery_locations.json',
    'spouse_aptitudes': 'spouse_aptitudes.json',
    'personality_axes': 'personality_axes.json',
    # 게임 규칙 또는 세이브 필드 폭으로 결정되는 편집 상한. 선택한
    # EXE에서 검증된 값은 이 리소스의 해당 항목만 덮어쓴다.
    'limits': 'game_limits.json',
    # This file mixes display references with editable game limits.  It belongs
    # to the profile so an EXE-derived limit can replace the bundled fallback.
    'editor_mappings': 'editor_mappings.json',
}


def _synchronize_value(target: Any, source: Any) -> Any:
    """Copy source into target while retaining existing container identities."""
    if isinstance(target, dict) and isinstance(source, dict):
        for key in tuple(target):
            if key not in source:
                del target[key]
        for key, source_value in source.items():
            if key in target:
                target[key] = _synchronize_value(target[key], source_value)
            else:
                target[key] = deepcopy(source_value)
        return target
    if isinstance(target, list) and isinstance(source, list):
        shared_length = min(len(target), len(source))
        for index in range(shared_length):
            target[index] = _synchronize_value(target[index], source[index])
        if len(target) > len(source):
            del target[len(source):]
        elif len(source) > len(target):
            target.extend(deepcopy(source[len(target):]))
        return target
    return deepcopy(source)


@dataclass
class GameDataProfile:
    """One coherent set of static data used by every editor screen.

    ``resources`` always starts as a complete bundled profile.  EXE readers
    should call :meth:`fork` and then one of the overlay helpers; they must not
    mutate the fallback profile shared by the running application.
    """

    resources: dict[str, Any]
    source_kind: str = 'builtin'
    source_path: str | None = None
    provenance: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_builtin(
        cls,
        loader: Callable[[str], Any] = load_json_resource,
    ) -> 'GameDataProfile':
        resources = {
            resource_name: loader(filename)
            for resource_name, filename in GAME_RESOURCE_FILES.items()
        }
        profile = cls(resources=resources)
        profile.validate()
        return profile

    def validate(self) -> None:
        """Reject an incomplete profile before UI indexes are built from it."""
        missing = tuple(name for name in GAME_RESOURCE_FILES if name not in self.resources)
        if missing:
            raise ValueError('정적 데이터 프로필에 필요한 리소스가 없습니다: ' + ', '.join(missing))

        expected_collections = {
            'characters': 'records',
            'sponsors': 'records',
            'cities': 'records',
            'trade_goods': 'records',
        }
        for resource_name, collection_name in expected_collections.items():
            resource = self.resources[resource_name]
            if not isinstance(resource, dict) or not isinstance(resource.get(collection_name), list):
                raise ValueError(f'{resource_name}.{collection_name} 정적 데이터가 올바르지 않습니다.')

        required_limits = {
            'player': ('ability', 'vitality', 'skill', 'language', 'cash',
                       'deposit', 'contract', 'fame', 'infamy'),
            'person': ('ability', 'vitality', 'reputation', 'skill', 'language'),
            'sponsor': ('remaining_days',),
        }
        limits = self.resources['limits']
        if not isinstance(limits, dict):
            raise ValueError('limits 정적 데이터가 올바르지 않습니다.')
        for group, names in required_limits.items():
            values = limits.get(group)
            if not isinstance(values, dict):
                raise ValueError(f'limits.{group} 정적 데이터가 올바르지 않습니다.')
            for name in names:
                value = values.get(name)
                if not isinstance(value, int) or value < 0:
                    raise ValueError(f'limits.{group}.{name} 상한값이 올바르지 않습니다.')

    def resource(self, name: str) -> Any:
        return self.resources[name]

    def fork(self, source_kind: str, source_path: str | None = None) -> 'GameDataProfile':
        """Make an isolated profile which retains every bundled fallback."""
        return GameDataProfile(
            resources=deepcopy(self.resources),
            source_kind=str(source_kind),
            source_path=str(source_path) if source_path is not None else None,
            provenance=dict(self.provenance),
        )

    def apply_from(self, profile: 'GameDataProfile') -> None:
        """Activate another profile without invalidating existing UI aliases.

        The recovered editor still has several module/class aliases that point
        into nested JSON containers.  Synchronizing in place lets the EXE
        profile become active now; those aliases can be removed gradually.
        """
        profile.validate()
        for name in GAME_RESOURCE_FILES:
            self.resources[name] = _synchronize_value(
                self.resources[name], profile.resources[name])
        self.source_kind = profile.source_kind
        self.source_path = profile.source_path
        self.provenance.clear()
        self.provenance.update(profile.provenance)
        self.validate()

    def replace_resource(self, name: str, value: Any, source: str) -> None:
        """Replace one fully decoded resource and record its origin."""
        if name not in GAME_RESOURCE_FILES:
            raise KeyError(name)
        self.resources[name] = deepcopy(value)
        self.provenance[name] = source

    def overlay_mapping(
        self,
        resource_name: str,
        values: Mapping[str, Any],
        source: str,
    ) -> None:
        """Overlay verified top-level fields without discarding JSON fallbacks."""
        resource = self.resources[resource_name]
        if not isinstance(resource, dict):
            raise TypeError(f'{resource_name} 리소스는 매핑이 아닙니다.')
        for key, value in values.items():
            resource[key] = deepcopy(value)
            self.provenance[f'{resource_name}.{key}'] = source

    def overlay_records(
        self,
        resource_name: str,
        records: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
        source: str,
        collection_name: str = 'records',
        id_key: str = 'id',
    ) -> None:
        """Overlay verified fields of ID-addressed records.

        A decoded EXE record is allowed to contain only the fields established
        by its extractor.  The remaining fields continue to come from the
        bundled record with the same ID.
        """
        resource = self.resources[resource_name]
        collection = resource.get(collection_name) if isinstance(resource, dict) else None
        if not isinstance(collection, list):
            raise TypeError(f'{resource_name}.{collection_name} 리소스는 레코드 목록이 아닙니다.')

        by_id = {int(record[id_key]): record for record in collection}
        for overlay in records:
            record_id = int(overlay[id_key])
            target = by_id.get(record_id)
            if target is None:
                raise KeyError(f'{resource_name}.{collection_name}[{record_id}]')
            for key, value in overlay.items():
                if key == id_key:
                    continue
                target[key] = deepcopy(value)
                self.provenance[
                    f'{resource_name}.{collection_name}[{record_id}].{key}'
                ] = source

        self.validate()

    @property
    def master_data(self) -> dict[str, Any]:
        return self.resources['master_data']

    @property
    def characters(self) -> dict[str, Any]:
        return self.resources['characters']

    @property
    def sponsors(self) -> dict[str, Any]:
        return self.resources['sponsors']

    @property
    def fleet(self) -> dict[str, Any]:
        return self.resources['fleet']

    @property
    def cities(self) -> dict[str, Any]:
        return self.resources['cities']

    @property
    def game_strings(self) -> dict[str, Any]:
        return self.resources['game_strings']

    @property
    def trade_goods(self) -> dict[str, Any]:
        return self.resources['trade_goods']

    @property
    def editor_mappings(self) -> dict[str, Any]:
        return self.resources['editor_mappings']

    @property
    def limits(self) -> dict[str, Any]:
        return self.resources['limits']

    @property
    def barmaids(self) -> list[dict[str, Any]]:
        return self.master_data['barmaid_database']

    @property
    def character_by_id(self) -> dict[int, dict[str, Any]]:
        return {int(record['id']): record for record in self.characters['records']}

    @property
    def barmaid_by_id(self) -> dict[int, dict[str, Any]]:
        return {int(record['id']): record for record in self.barmaids}

    @property
    def barmaid_by_name(self) -> dict[str, dict[str, Any]]:
        return {str(record['name']): record for record in self.barmaids}

    @property
    def sponsor_by_id(self) -> dict[int, dict[str, Any]]:
        return {int(record['id']): record for record in self.sponsors['records']}

    @property
    def city_name_by_id(self) -> dict[int, str]:
        return {
            int(record.get('id', city_id)): str(record['name'])
            for city_id, record in enumerate(self.cities['records'])
        }

    @property
    def trade_good_name_by_id(self) -> dict[int, str]:
        return {
            int(record['id']): str(record['name'])
            for record in self.trade_goods['records']
        }
