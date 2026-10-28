from __future__ import annotations

import json
from pathlib import Path


MECHANIC_ID = "consent_gauntlet"
NEGATIVE_PREFIXES = (
    "Do not ", "Disable ", "Block ", "Refuse ", "Disallow ",
    "Prevent ", "Never ", "Stop ",
)


def _state(state_dir: Path) -> dict:
    return json.loads((state_dir / "public_state.json").read_text(encoding="utf-8"))


def _interaction(state: dict) -> str:
    return str((state.get("control_condition") or {}).get("interaction") or "full")


def _target(label: str) -> bool:
    return str(label).startswith(NEGATIVE_PREFIXES)


def _click_option(page, interaction: str, action: str) -> None:
    selector = f'[data-action="{action}"]'
    if interaction == "simplified":
        locator = page.locator(f'.consent-proxy {selector}')
    else:
        locator = page.locator(f'.consent-orbit {selector}')
    locator = locator.first
    if interaction == "simplified":
        locator.click()
        return
    for _ in range(80):
        box = locator.bounding_box()
        unobscured = box is not None and locator.evaluate(
            """node => {
              const rect = node.getBoundingClientRect();
              const top = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
              return top === node || node.contains(top);
            }"""
        )
        if unobscured:
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            return
        page.wait_for_timeout(50)
    raise AssertionError(f"moving {action} option never exposed an unobscured click point")


def fail_once(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    del state_dir, out_dir
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    interaction = "simplified" if page.locator(".consent-gauntlet.mode-simplified").count() else "full"
    if page.locator(f'.{"consent-proxy" if interaction == "simplified" else "consent-orbit"} [data-action="accept"]').count():
        _click_option(page, interaction, "accept")
    else:
        _click_option(page, interaction, "manage")
        page.locator("#consent-review").click()
        _click_option(page, interaction, "commit")
    page.locator(".consent-verdict.is-fail").wait_for(state="visible")


def _open_drawer(page, interaction: str, drawer: dict) -> None:
    if interaction == "full":
        page.locator(f'[data-drawer-tab="{drawer["id"]}"]').click()
        return
    for _ in range(8):
        if page.locator(".consent-drawer-proxy > b").inner_text().strip() == drawer["label"]:
            return
        page.locator("[data-drawer-next]").click()
    raise AssertionError(f"could not open drawer {drawer['id']}")


def _current(page, purpose_id: str) -> bool:
    return page.locator(f'[data-purpose-switch="{purpose_id}"]').get_attribute("aria-checked") == "true"


def _set_full(page, purpose_id: str, target: bool) -> None:
    rail = page.locator(f'[data-purpose-switch="{purpose_id}"]')
    current = rail.get_attribute("aria-checked") == "true"
    if current == target:
        return
    box = rail.bounding_box()
    if box is None:
        raise AssertionError(f"missing switch rail {purpose_id}")
    y = box["y"] + box["height"] / 2
    start = box["x"] + box["width"] * (0.82 if current else 0.18)
    end = box["x"] + box["width"] * (0.82 if target else 0.18)
    page.mouse.move(start, y)
    page.mouse.down()
    page.mouse.move(end, y, steps=5)
    page.mouse.up()


def _set_simplified(page, purpose_id: str, target: bool) -> None:
    if _current(page, purpose_id) == target:
        return
    page.locator(f'[data-purpose-answer="{purpose_id}:{str(target).lower()}"]').click()


def _set_purpose(page, interaction: str, purpose_id: str, target: bool) -> None:
    if interaction == "full":
        _set_full(page, purpose_id, target)
    else:
        _set_simplified(page, purpose_id, target)


def _solve_open_ledger(page, state: dict, interaction: str) -> None:
    surface = state["surface"]
    targets = {item["id"]: _target(item["label"]) for item in surface["purposes"]}
    by_id = {item["id"]: item for item in surface["purposes"]}
    source_ids = [item["source_id"] for item in surface.get("links") or []]
    ordered_ids = source_ids + [item["id"] for item in surface["purposes"] if item["id"] not in source_ids]

    for purpose_id in ordered_ids:
        purpose = by_id[purpose_id]
        drawer = next(item for item in surface["drawers"] if item["id"] == purpose["drawer_id"])
        _open_drawer(page, interaction, drawer)
        _set_purpose(page, interaction, purpose_id, targets[purpose_id])

    # A directed source can disturb a target that happened to be visited first.
    # Reconcile every visible statement once after all source switches are fixed.
    for purpose in surface["purposes"]:
        drawer = next(item for item in surface["drawers"] if item["id"] == purpose["drawer_id"])
        _open_drawer(page, interaction, drawer)
        _set_purpose(page, interaction, purpose["id"], targets[purpose["id"]])

    page.locator("#consent-review").wait_for(state="visible")


def prepare_solution(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    del out_dir
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    state = _state(state_dir)
    interaction = _interaction(state)
    _click_option(page, interaction, "manage")
    _solve_open_ledger(page, state, interaction)


def solve_open_ledger(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    """Finish a packet whose purpose ledger is already visible."""
    del out_dir
    if mechanic != MECHANIC_ID:
        raise AssertionError(f"unexpected mechanic {mechanic!r}")
    state = _state(state_dir)
    interaction = _interaction(state)
    _solve_open_ledger(page, state, interaction)
    page.locator("#consent-review").click()
    _click_option(page, interaction, "commit")
    page.locator(".consent-verdict.is-pass").wait_for(state="visible")


def solve(page, state_dir: Path, out_dir: Path, mechanic: str) -> None:
    state = _state(state_dir)
    interaction = _interaction(state)
    prepare_solution(page, state_dir, out_dir, mechanic)
    page.locator("#consent-review").click()
    _click_option(page, interaction, "commit")
    page.locator(".consent-verdict.is-pass").wait_for(state="visible")
