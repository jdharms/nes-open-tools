"""Manifest JSON as the schemas before 3 stored it, for tests of the legacy loaders."""

import copy

#: settings fields schema 3 added
SCHEMA_3_SETTINGS = ("draw_rule", "wind_speed_profile", "wind_direction_profile")
#: hole fields schema 3 added
SCHEMA_3_HOLE = ("wind_direction", "wind_speed")


def as_schema(data: dict, schema: int) -> dict:
    """A current manifest's JSON reshaped as schema 1 or 2: the fields those lack removed.

    The manifest must have been generated as those schemas' seeds were, with a uniform
    draw and vanilla wind, or the result will not load.
    """
    data = copy.deepcopy(data)
    data["schema"] = schema
    if schema == 1:
        del data["build_version"], data["finish_abi_version"]
    for key in SCHEMA_3_SETTINGS:
        del data["settings"][key]
    for hole in data["course"]["holes"]:
        for key in SCHEMA_3_HOLE:
            del hole[key]
    return data
