"""两次审计对比逻辑的轻量自测（无测试框架依赖）：python -m tests.test_diff"""

from __future__ import annotations

from app import analyzer, diff


def _check(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError("%s %s" % (name, detail))
    print("ok -", name)


BASE_MANIFEST = {
    "name": "demo",
    "packages": [
        {"name": "app", "version": "1", "license": "GPL-3.0",
         "dependencies": ["shared@1", "gone@1", "duo@1"]},
        {"name": "shared", "version": "1", "license": "MIT",
         "dependencies": ["leaf@1"]},
        {"name": "leaf", "version": "1", "license": "Proprietary"},
        {"name": "gone", "version": "1", "license": "GPL-2.0",
         "dependencies": ["apache-lib@1"]},
        {"name": "apache-lib", "version": "1", "license": "Apache-2.0"},
        {"name": "duo", "version": "1", "license": "OFL-1.1"},
    ],
}

TARGET_MANIFEST = {
    "name": "demo",
    "packages": [
        {"name": "app", "version": "1", "license": "GPL-3.0",
         "dependencies": ["shared@1", "new-g@1", "duo@1", "ghost"]},
        {"name": "shared", "version": "1", "license": "MIT",
         "dependencies": ["leaf@1"]},
        {"name": "leaf", "version": "1", "license": "MIT"},
        {"name": "new-g", "version": "1", "license": "GPL-2.0",
         "dependencies": ["apache-lib@1"]},
        {"name": "apache-lib", "version": "1", "license": "Apache-2.0"},
        {"name": "duo", "version": "1", "license": "GPL-2.0"},
    ],
}


def _pair_keys(entries):
    return {(e["ancestor"], e["node"]) for e in entries}


def test_added_removed_changed() -> None:
    base = analyzer.analyze_manifest(BASE_MANIFEST)
    target = analyzer.analyze_manifest(TARGET_MANIFEST)
    result = diff.diff_results(base, target, base_id=1, target_id=2)

    added = _pair_keys(result["conflicts"]["added"])
    removed = _pair_keys(result["conflicts"]["removed"])
    changed = _pair_keys(result["conflicts"]["changed"])

    _check(
        "added conflicts are the new-g subtree",
        added == {("new-g@1", "apache-lib@1"), ("app@1", "new-g@1")},
        str(added),
    )
    _check(
        "removed conflicts cover gone subtree and fixed leaf",
        removed == {
            ("gone@1", "apache-lib@1"),
            ("app@1", "gone@1"),
            ("app@1", "leaf@1"),
            ("shared@1", "leaf@1"),
        },
        str(removed),
    )
    _check("duo escalated warning->error", changed == {("app@1", "duo@1")}, str(changed))

    entry = result["conflicts"]["changed"][0]
    _check("changed entry keeps both sides", entry["base"] and entry["target"])
    _check(
        "changed entry severity warning->error",
        entry["base"]["severity"] == "warning" and entry["target"]["severity"] == "error",
    )
    _check("changed entry flags status+license", "status" in entry["changes"]
           and "license" in entry["changes"], str(entry["changes"]))
    _check(
        "both sides expose shortest paths",
        entry["base"]["path"] == ["app@1", "duo@1"]
        and entry["target"]["path"] == ["app@1", "duo@1"],
        str(entry),
    )

    added_entry = next(
        e for e in result["conflicts"]["added"] if e["node"] == "apache-lib@1"
    )
    _check(
        "added conflict carries target shortest path only",
        added_entry["base"] is None
        and added_entry["target"]["path"] == ["new-g@1", "apache-lib@1"],
        str(added_entry),
    )
    removed_entry = next(
        e for e in result["conflicts"]["removed"] if e["node"] == "leaf@1"
        and e["ancestor"] == "app@1"
    )
    _check(
        "removed conflict carries base shortest path only",
        removed_entry["target"] is None
        and removed_entry["base"]["path"] == ["app@1", "shared@1", "leaf@1"],
        str(removed_entry),
    )


def test_node_and_warning_diff() -> None:
    base = analyzer.analyze_manifest(BASE_MANIFEST)
    target = analyzer.analyze_manifest(TARGET_MANIFEST)
    result = diff.diff_results(base, target)

    nodes = result["nodes"]
    _check("node added", [n["id"] for n in nodes["added"]] == ["new-g@1"])
    _check("node removed", [n["id"] for n in nodes["removed"]] == ["gone@1"])
    lic_changed = {n["id"]: n for n in nodes["license_changed"]}
    _check("license changed set", set(lic_changed) == {"leaf@1", "duo@1"}, str(lic_changed))
    _check(
        "license change detail",
        lic_changed["leaf@1"]["base_license"] == "Proprietary"
        and lic_changed["leaf@1"]["target_license"] == "MIT",
    )

    warnings = result["warnings"]
    _check(
        "unresolved ghost becomes an added warning",
        len(warnings["added"]) == 1 and "ghost" in warnings["added"][0],
        str(warnings),
    )
    _check("no removed warnings", warnings["removed"] == [])

    summary = result["summary"]
    _check(
        "summary counts match sections",
        summary["conflicts_added"] == len(result["conflicts"]["added"])
        and summary["conflicts_removed"] == len(result["conflicts"]["removed"])
        and summary["conflicts_changed"] == len(result["conflicts"]["changed"])
        and summary["nodes_added"] == 1
        and summary["nodes_removed"] == 1
        and summary["nodes_license_changed"] == 2
        and summary["warnings_added"] == 1
        and summary["warnings_removed"] == 0,
        str(summary),
    )


def test_self_diff_is_empty() -> None:
    result = analyzer.analyze_manifest(BASE_MANIFEST)
    same = diff.diff_results(result, result, base_id=7, target_id=7)
    _check(
        "self diff has no changes",
        not same["conflicts"]["added"]
        and not same["conflicts"]["removed"]
        and not same["conflicts"]["changed"]
        and not same["nodes"]["added"]
        and not same["nodes"]["removed"]
        and not same["nodes"]["license_changed"]
        and not same["warnings"]["added"]
        and not same["warnings"]["removed"],
    )
    _check("self diff keeps audit ids",
           same["base"]["audit_id"] == 7 and same["target"]["audit_id"] == 7)


def main() -> None:
    test_added_removed_changed()
    test_node_and_warning_diff()
    test_self_diff_is_empty()
    print("\nall diff tests passed.")


if __name__ == "__main__":
    main()
