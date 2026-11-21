"""Compară structura a două XML-uri (taguri, ordine, atribute), nu și valorile.

Exemplele oficiale din docs/exemple-fisc/ sunt referința: un export al aplicației trebuie să aibă
aceleași elemente în aceeași ordine, cu aceleași atribute. Rândurile repetate (aceeași
structură, unul după altul) se contopesc într-unul singur, ca numărul de rânduri să nu conteze.
"""

from pathlib import Path
from xml.etree import ElementTree as ET

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "exemple-fisc"


def structure(el: ET.Element) -> tuple:
    children: list[tuple] = []
    for child in el:
        node = structure(child)
        if not children or children[-1] != node:
            children.append(node)
    return (el.tag, tuple(sorted(el.attrib)), tuple(children))


def example(name: str) -> ET.Element:
    return ET.fromstring((EXAMPLES / name).read_bytes())


def paths(node: tuple, prefix: str = "") -> list[str]:
    tag, attrs, children = node
    here = f"{prefix}/{tag}" + (f"[{','.join(attrs)}]" if attrs else "")
    return [here, *(p for child in children for p in paths(child, here))]


def assert_same_structure(xml: bytes, example_name: str) -> None:
    got, want = paths(structure(ET.fromstring(xml))), paths(structure(example(example_name)))
    assert got == want, f"structura diferă de {example_name}:\n" + "\n".join(
        f"  lipsește: {p}" for p in want if p not in got
    ) + "\n" + "\n".join(f"  în plus: {p}" for p in got if p not in want)


def assert_format(xml: bytes, example_name: str) -> None:
    """Declarația XML și rădăcina `<dec TypeName=...>` ca în exemplu."""
    want = (EXAMPLES / example_name).read_bytes()
    first = lambda b: b.decode().split("\n", 1)[0]  # noqa: E731
    assert first(xml) == first(want)
    assert ET.fromstring(xml).attrib == ET.fromstring(want).attrib
