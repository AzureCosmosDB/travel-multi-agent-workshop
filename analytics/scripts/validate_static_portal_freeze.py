"""Validate the mirrored analytics portal against its approved static layout."""

from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
PORTAL = ROOT / "02_completed" / "analytics-portal" / "index.html"
MIRROR = ROOT / "analytics" / "dashboard" / "index.html"
MANIFEST = ROOT / "analytics" / "config" / "static-portal-freeze.json"

MUTABLE_ATTRIBUTES = {
    "analyticsNote": {"aria-busy", "aria-live", "hidden"},
    "generateTraffic": {"aria-busy", "disabled", "hidden"},
    "recomputeInsights": {"aria-busy", "disabled", "hidden"},
    "refresh": {"aria-busy", "disabled"},
    "resetState": {"aria-busy", "disabled", "hidden"},
    "statusText": {"aria-busy", "aria-live"},
    "toast": {"aria-busy", "aria-live", "hidden"},
}
MUTABLE_TEXT_IDS = {
    "analyticsNote",
    "generateTraffic",
    "recomputeInsights",
    "refresh",
    "resetState",
    "statusText",
    "toast",
}
VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class PortalFreezeError(AssertionError):
    pass


def _digest(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class _PortalParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.events: list[dict[str, Any]] = []
        self.ids: list[dict[str, str]] = []
        self.classes: list[dict[str, str]] = []
        self.styles: list[str] = []
        self._stack: list[tuple[str, str | None]] = []
        self._style_chunks: list[str] | None = None

    def _start(
        self, tag: str, attrs: list[tuple[str, str | None]], self_closing: bool
    ) -> None:
        self_closing = self_closing or tag in VOID_ELEMENTS
        values = dict(attrs)
        element_id = values.get("id")
        mutable = MUTABLE_ATTRIBUTES.get(element_id or "", set())
        frozen_attrs = sorted(
            (name, value or "") for name, value in attrs if name not in mutable
        )
        event = {
            "event": "void" if self_closing else "start",
            "tag": tag,
            "attrs": frozen_attrs,
        }
        self.events.append(event)
        class_name = values.get("class") or ""
        if element_id:
            self.ids.append({"tag": tag, "id": element_id, "class": class_name})
        if class_name:
            self.classes.append(
                {"tag": tag, "id": element_id or "", "class": class_name}
            )
        if not self_closing:
            self._stack.append((tag, element_id))
        if tag == "style":
            self._style_chunks = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self._start(tag, attrs, False)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self._start(tag, attrs, True)

    def handle_endtag(self, tag: str) -> None:
        self.events.append({"event": "end", "tag": tag})
        if tag == "style" and self._style_chunks is not None:
            self.styles.append("".join(self._style_chunks))
            self._style_chunks = None
        if self._stack:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        if self._style_chunks is not None:
            self._style_chunks.append(data)
            return
        if any(tag == "script" for tag, _ in self._stack):
            return
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        current_id = next(
            (element_id for _, element_id in reversed(self._stack) if element_id),
            None,
        )
        self.events.append(
            {
                "event": "text",
                "value": "<lifecycle-state>"
                if current_id in MUTABLE_TEXT_IDS
                else text,
            }
        )


def build_manifest(source: str) -> dict[str, Any]:
    parser = _PortalParser()
    parser.feed(source)
    parser.close()
    return {
        "schema_version": 1,
        "mutable_lifecycle_attributes": {
            key: sorted(value) for key, value in sorted(MUTABLE_ATTRIBUTES.items())
        },
        "mutable_lifecycle_text_ids": sorted(MUTABLE_TEXT_IDS),
        "structural_event_count": len(parser.events),
        "structural_events_sha256": _digest(parser.events),
        "ordered_ids": parser.ids,
        "class_element_count": len(parser.classes),
        "class_elements_sha256": _digest(parser.classes),
        "stylesheets": [
            {
                "index": index,
                "bytes": len(style.encode("utf-8")),
                "sha256": hashlib.sha256(style.encode("utf-8")).hexdigest(),
            }
            for index, style in enumerate(parser.styles)
        ],
    }


def validate_sources(
    portal_source: str, mirror_source: str, manifest: dict[str, Any]
) -> None:
    failures: list[str] = []
    if portal_source.encode("utf-8") != mirror_source.encode("utf-8"):
        failures.append("portal mirror drift")
    actual = build_manifest(portal_source)
    if actual["ordered_ids"] != manifest["ordered_ids"]:
        failures.append("ordered ID/tag/class drift")
    if (
        actual["class_element_count"] != manifest["class_element_count"]
        or actual["class_elements_sha256"] != manifest["class_elements_sha256"]
    ):
        failures.append("class/order drift")
    if (
        actual["structural_event_count"] != manifest["structural_event_count"]
        or actual["structural_events_sha256"]
        != manifest["structural_events_sha256"]
    ):
        failures.append("element structure/order/attribute/text drift")
    if actual["stylesheets"] != manifest["stylesheets"]:
        failures.append("stylesheet block drift")
    if failures:
        raise PortalFreezeError("; ".join(failures))


def validate_checked_in_portals() -> None:
    portal_bytes = PORTAL.read_bytes()
    mirror_bytes = MIRROR.read_bytes()
    if portal_bytes != mirror_bytes:
        raise PortalFreezeError("portal mirror drift")
    validate_sources(
        portal_bytes.decode("utf-8"),
        mirror_bytes.decode("utf-8"),
        json.loads(MANIFEST.read_text(encoding="utf-8")),
    )


def self_test() -> None:
    source = PORTAL.read_bytes().decode("utf-8")
    manifest = build_manifest(source)
    validate_sources(source, source, manifest)
    approved_state_change = source.replace(
        '<button id="refresh">Refresh</button>',
        '<button id="refresh" disabled>Loading</button>',
        1,
    ).replace(
        '<span id="statusText">idle</span>',
        '<span id="statusText">loading</span>',
        1,
    )
    validate_sources(approved_state_change, approved_state_change, manifest)
    id_drift = source.replace('id="tenant"', 'id="tenantChanged"', 1)
    class_drift = source.replace(
        'class="tab active"', 'class="tab changed"', 1
    )
    css_drift = source.replace("--bg: #0f1420", "--bg: #000000", 1)
    element_drift = source.replace("<main>", "<main><aside></aside>", 1)
    mutations = {
        "mirror": (source, source + "\n", "portal mirror drift"),
        "id": (id_drift, id_drift, "ordered ID/tag/class drift"),
        "class": (class_drift, class_drift, "class/order drift"),
        "css": (css_drift, css_drift, "stylesheet block drift"),
        "element": (
            element_drift,
            element_drift,
            "element structure/order/attribute/text drift",
        ),
    }
    for name, (portal_source, mirror_source, expected) in mutations.items():
        try:
            validate_sources(portal_source, mirror_source, manifest)
        except PortalFreezeError as exc:
            if expected not in str(exc):
                raise AssertionError(
                    f"{name} drift reported the wrong invariant: {exc}"
                ) from exc
            continue
        raise AssertionError(f"negative fixture did not detect {name} drift")
    print(
        "static portal freeze self-test: PASS "
        "(1 approved-state fixture, 5 negative fixtures)"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()
    if args.write_manifest:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(
            json.dumps(
                build_manifest(PORTAL.read_bytes().decode("utf-8")),
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {MANIFEST.relative_to(ROOT)}")
    if args.self_test:
        self_test()
    if not args.write_manifest and not args.self_test:
        validate_checked_in_portals()
        print("Static portal freeze validation passed.")


if __name__ == "__main__":
    main()
