"""Example indexing heuristic. faire loads this module from the stream's own history.

Each top-level entry of the received directory is one item. This example expects folders
named ``sub-<subject>_ses-<session>`` holding an ``instrument.txt`` with the instrument
identifier; a folder whose name ends with ``_pilot`` is a pilot session.
"""

from pathlib import Path


def instrument(item: Path) -> str:
    """Identifier of the instrument that produced the item, as declared in the ma-DMP."""
    return (item / "instrument.txt").read_text().strip()


def entities(item: Path) -> dict[str, str]:
    """Sample entities (names declared in the ma-DMP) of the item, as native values."""
    name = item.name.removesuffix("_pilot")
    parts = dict(part.split("-", 1) for part in name.split("_"))
    return {"subject": parts["sub"], "session": parts["ses"]}


def place(item: Path, entities: dict[str, str]) -> str:
    """Path of the item inside the stream instance."""
    return f"sub-{entities['subject']}/ses-{entities['session']}"


def pilot(item: Path, entities: dict[str, str]) -> bool:
    """True for pilot items, committed to the `pilot` branch."""
    return item.name.endswith("_pilot")
