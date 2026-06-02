"""Fail-hard accessor for DB-seeded pipeline configuration.

Nodes import ``cfg`` from here instead of from ``graph`` to avoid circular
imports (graph.py imports node modules; node modules must not import graph.py).
"""

from typing import Any


def cfg(state: Any, section: str, key: str) -> Any:
    """Read state.country_config[section][key]. Raises RuntimeError if absent.

    Use this in every pipeline node instead of settings.* for operational config.
    Fail-hard: a missing key means the DB was not seeded — surface it immediately.
    """
    try:
        return state.country_config[section][key]
    except (KeyError, AttributeError):
        country_id = getattr(state, "country_id", "?")
        raise RuntimeError(
            f"Missing DB config: country_id={country_id} "
            f"section='{section}' key='{key}' — run seed first"
        )
