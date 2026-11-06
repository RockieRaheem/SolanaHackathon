from typing import Final

PROGRAMME_NAMES: Final = {
    "day_care": "Day care",
    "pre_primary": "Pre-primary / nursery",
    "primary": "Primary",
    "lower_secondary": "Lower secondary (O-Level)",
    "upper_secondary": "Advanced secondary (A-Level)",
}

GRADE_TEMPLATES: Final = {
    "pre_primary": [
        ("BABY", "Baby Class"),
        ("MIDDLE", "Middle Class"),
        ("TOP", "Top Class"),
    ],
    "primary": [(f"P{i}", f"P.{i}") for i in range(1, 8)],
    "lower_secondary": [(f"S{i}", f"S.{i}") for i in range(1, 5)],
    "upper_secondary": [(f"S{i}", f"S.{i}") for i in range(5, 7)],
}


def template_classes(programme_codes: list[str]) -> list[tuple[str, str, str]]:
    """Return canonical code, editable default label, and programme code in national order."""
    rows: list[tuple[str, str, str]] = []
    for programme_code in PROGRAMME_NAMES:
        if programme_code not in programme_codes:
            continue
        rows.extend(
            (code, name, programme_code) for code, name in GRADE_TEMPLATES.get(programme_code, [])
        )
    return rows
