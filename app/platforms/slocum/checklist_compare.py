"""
Compare two Slocum daily checklist submissions (form-to-form).

Diffs normalized item values. Identity fields are excluded. Item comments and
section notes are included only when ``include_notes`` is True. Verification
flags are never compared.
"""

from __future__ import annotations

from typing import Any, Optional

# Identity / always-different noise — never contribute to changed_item_ids.
EXCLUDED_VALUE_ITEM_IDS: frozenset[str] = frozenset(
    {
        "pilot_val",
        "dataset_id_val",
    }
)

# Empty / placeholder strings treated as equivalent for equality.
_EMPTY_EQUIVALENTS: frozenset[str] = frozenset(
    {
        "",
        "n/a",
        "na",
        "none",
        "null",
        "—",
        "-",
    }
)

SECTION_COMMENT_KEY_PREFIX = "section:"
SECTION_COMMENT_KEY_SUFFIX = ":comment"


def section_comment_key(section_id: str) -> str:
    """Stable key for a section-level note in changed_item_ids."""
    return f"{SECTION_COMMENT_KEY_PREFIX}{section_id}{SECTION_COMMENT_KEY_SUFFIX}"


def normalize_checklist_value(value: Any) -> str:
    """
    Normalize a checklist value for equality comparison.

    Trims whitespace, treats None / blank / common N/A placeholders as empty,
    and casefolds for comparison.
    """
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    folded = text.casefold()
    if folded in _EMPTY_EQUIVALENTS:
        return ""
    return folded


def flatten_checklist_sections(
    sections_data: Optional[list[Any]],
) -> dict[str, dict[str, Any]]:
    """
    Flatten ``sections_data`` into ``{item_id: item_dict}`` plus section notes.

    Section notes are stored under ``section:{section_id}:comment`` keys with
    ``value`` set to the note text (for normalize/diff reuse).
    """
    flat: dict[str, dict[str, Any]] = {}
    if not isinstance(sections_data, list):
        return flat

    for section in sections_data:
        if not isinstance(section, dict):
            continue
        section_id = section.get("id")
        if not section_id:
            continue
        sid = str(section_id)
        section_title = section.get("title") or sid

        for item in section.get("items") or []:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            if not item_id:
                continue
            flat[str(item_id)] = {
                "id": str(item_id),
                "label": item.get("label") or item_id,
                "value": item.get("value"),
                "comment": item.get("comment"),
                "is_verified": item.get("is_verified"),
                "section_id": sid,
                "section_title": section_title,
                "kind": "item",
            }

        if "section_comment" in section:
            key = section_comment_key(sid)
            flat[key] = {
                "id": key,
                "label": f"{section_title} (section notes)",
                "value": section.get("section_comment"),
                "comment": None,
                "is_verified": None,
                "section_id": sid,
                "section_title": section_title,
                "kind": "section_comment",
            }

    return flat


def _item_present(flat: dict[str, dict[str, Any]], item_id: str) -> bool:
    """True when the item exists in the flattened map (even if value is empty)."""
    return item_id in flat


def diff_checklists(
    reference_sections: Optional[list[Any]],
    other_sections: Optional[list[Any]],
    *,
    include_notes: bool = False,
) -> list[str]:
    """
    Return ordered list of changed keys between two checklist ``sections_data``.

    - Compares normalized values for item IDs not in ``EXCLUDED_VALUE_ITEM_IDS``.
    - When ``include_notes`` is True, also diffs item ``comment`` fields (as
      ``{item_id}__comment``) and section notes (``section:{id}:comment``).
    - Missing on one side and present on the other counts as changed.
    - Both missing is not changed.
    """
    ref_flat = flatten_checklist_sections(reference_sections)
    other_flat = flatten_checklist_sections(other_sections)

    changed: list[str] = []
    seen: set[str] = set()

    # Preserve reference section/item order, then append keys only on other.
    ordered_ids: list[str] = []
    for key in ref_flat:
        if key.startswith(SECTION_COMMENT_KEY_PREFIX) and key.endswith(
            SECTION_COMMENT_KEY_SUFFIX
        ):
            continue
        if key not in seen:
            ordered_ids.append(key)
            seen.add(key)
    for key in other_flat:
        if key.startswith(SECTION_COMMENT_KEY_PREFIX) and key.endswith(
            SECTION_COMMENT_KEY_SUFFIX
        ):
            continue
        if key not in seen:
            ordered_ids.append(key)
            seen.add(key)

    for item_id in ordered_ids:
        if item_id in EXCLUDED_VALUE_ITEM_IDS:
            if include_notes:
                _maybe_append_comment_diff(
                    changed, item_id, ref_flat, other_flat
                )
            continue

        ref_present = _item_present(ref_flat, item_id)
        other_present = _item_present(other_flat, item_id)
        if not ref_present and not other_present:
            continue
        if ref_present != other_present:
            changed.append(item_id)
        else:
            ref_val = normalize_checklist_value(ref_flat[item_id].get("value"))
            other_val = normalize_checklist_value(other_flat[item_id].get("value"))
            if ref_val != other_val:
                changed.append(item_id)

        if include_notes:
            _maybe_append_comment_diff(changed, item_id, ref_flat, other_flat)

    if include_notes:
        section_keys: list[str] = []
        section_seen: set[str] = set()
        for key in list(ref_flat.keys()) + list(other_flat.keys()):
            if (
                key.startswith(SECTION_COMMENT_KEY_PREFIX)
                and key.endswith(SECTION_COMMENT_KEY_SUFFIX)
                and key not in section_seen
            ):
                section_keys.append(key)
                section_seen.add(key)
        for key in section_keys:
            ref_present = _item_present(ref_flat, key)
            other_present = _item_present(other_flat, key)
            if not ref_present and not other_present:
                continue
            if ref_present != other_present:
                changed.append(key)
                continue
            ref_val = normalize_checklist_value(ref_flat[key].get("value"))
            other_val = normalize_checklist_value(other_flat[key].get("value"))
            if ref_val != other_val:
                changed.append(key)

    return changed


def _maybe_append_comment_diff(
    changed: list[str],
    item_id: str,
    ref_flat: dict[str, dict[str, Any]],
    other_flat: dict[str, dict[str, Any]],
) -> None:
    """Append ``{item_id}__comment`` when item comments differ."""
    comment_key = f"{item_id}__comment"
    ref_item = ref_flat.get(item_id)
    other_item = other_flat.get(item_id)
    ref_comment = normalize_checklist_value(
        ref_item.get("comment") if ref_item else None
    )
    other_comment = normalize_checklist_value(
        other_item.get("comment") if other_item else None
    )
    # Only flag when at least one side has the item or a non-empty comment.
    if not ref_item and not other_item and not ref_comment and not other_comment:
        return
    if ref_comment != other_comment:
        changed.append(comment_key)


def build_compare_result(
    reference_sections: Optional[list[Any]],
    other_sections: Optional[list[Any]],
    *,
    include_notes: bool = False,
) -> dict[str, Any]:
    """Return ``changed_item_ids`` and ``difference_count`` for an API payload."""
    changed = diff_checklists(
        reference_sections,
        other_sections,
        include_notes=include_notes,
    )
    return {
        "changed_item_ids": changed,
        "difference_count": len(changed),
    }
