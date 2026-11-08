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
SECTION_PROGRAMMES: Final = {
    "day_care": ("day_care",),
    "pre_primary": ("pre_primary",),
    "primary": ("primary",),
    "o_level": ("lower_secondary",),
    "secondary": ("lower_secondary", "upper_secondary"),
}

SECTION_NAMES: Final = {
    "day_care": "Day care section",
    "pre_primary": "Nursery section",
    "primary": "Primary section",
    "o_level": "O-Level section",
    "secondary": "Secondary section",
}


def section_identity(programme_codes: list[str]) -> tuple[str, str]:
    """Return the one operational school section represented by programme codes."""
    selected = tuple(dict.fromkeys(programme_codes))
    for unit_type, allowed in SECTION_PROGRAMMES.items():
        if set(selected) == set(allowed):
            return unit_type, SECTION_NAMES[unit_type]
    raise ValueError("Programme selection does not represent one school section")


def allowed_programmes(unit_type: str, configured: list[str]) -> tuple[str, ...]:
    """Use the declared section as authority, with legacy custom schools as fallback."""
    if unit_type in SECTION_PROGRAMMES:
        return SECTION_PROGRAMMES[unit_type]
    selected = tuple(code for code in dict.fromkeys(configured) if code in PROGRAMME_NAMES)
    return selected or tuple(PROGRAMME_NAMES)


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
