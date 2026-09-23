"""两次审计结果对比：按 包名@版本 配对节点与冲突，输出新增 / 消失 / 状态变化。

对比是纯计算：只读取两次既有审计结果（``analyzer`` 的输出字典），
不向数据库写入任何新记录。冲突按 ``(ancestor, node)`` 配对——同一对
“祖先 → 节点”在两次审计中视为同一逻辑冲突，其判定级别、原因或许可证
发生变化时归入“状态变化”，并同时附上双方各自的最短依赖路径。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

_SEVERITY_RANK = {"error": 0, "warning": 1}


def _conflict_key(conflict: Dict[str, Any]) -> Tuple[str, str]:
    """同一对 (祖先, 节点) 视为同一逻辑冲突，用于跨审计配对。"""
    return (str(conflict.get("ancestor", "")), str(conflict.get("node", "")))


def _conflict_side(conflict: Dict[str, Any]) -> Dict[str, Any]:
    """提取单侧冲突快照（含该次审计的最短路径），用于 diff 输出。"""
    return {
        "severity": conflict.get("severity"),
        "status": conflict.get("status"),
        "ancestor_license": conflict.get("ancestor_license"),
        "node_license": conflict.get("node_license"),
        "distance": conflict.get("distance"),
        "path": list(conflict.get("path") or []),
        "reason": conflict.get("reason"),
    }


def _entry_sort_key(entry: Dict[str, Any]) -> Tuple[Any, ...]:
    side = entry.get("target") or entry.get("base") or {}
    distance = side.get("distance")
    return (
        _SEVERITY_RANK.get(str(side.get("severity")), 2),
        distance if isinstance(distance, int) else 99,
        entry["ancestor"],
        entry["node"],
    )


def _diff_conflicts(
    base_conflicts: List[Dict[str, Any]],
    target_conflicts: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    base_map = {_conflict_key(c): c for c in base_conflicts}
    target_map = {_conflict_key(c): c for c in target_conflicts}

    added: List[Dict[str, Any]] = []
    removed: List[Dict[str, Any]] = []
    changed: List[Dict[str, Any]] = []

    for key in sorted(set(base_map) | set(target_map)):
        ancestor, node = key
        old = base_map.get(key)
        new = target_map.get(key)
        if old is None:
            added.append({"ancestor": ancestor, "node": node, "base": None,
                          "target": _conflict_side(new)})
            continue
        if new is None:
            removed.append({"ancestor": ancestor, "node": node,
                            "base": _conflict_side(old), "target": None})
            continue
        changes: List[str] = []
        if old.get("severity") != new.get("severity") or old.get("status") != new.get("status"):
            changes.append("status")
        if (old.get("ancestor_license") != new.get("ancestor_license")
                or old.get("node_license") != new.get("node_license")):
            changes.append("license")
        if old.get("reason") != new.get("reason"):
            changes.append("reason")
        if list(old.get("path") or []) != list(new.get("path") or []):
            changes.append("path")
        if changes:
            changed.append(
                {
                    "ancestor": ancestor,
                    "node": node,
                    "base": _conflict_side(old),
                    "target": _conflict_side(new),
                    "changes": changes,
                }
            )

    added.sort(key=_entry_sort_key)
    removed.sort(key=_entry_sort_key)
    changed.sort(key=_entry_sort_key)
    return {"added": added, "removed": removed, "changed": changed}


def _node_brief(node: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": node.get("id"),
        "name": node.get("name"),
        "version": node.get("version"),
        "license_display": node.get("license_display"),
        "license_category": node.get("license_category"),
    }


def _diff_nodes(
    base_nodes: List[Dict[str, Any]],
    target_nodes: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """按 包名@版本（节点 id）配对：新增 / 消失 / 许可证变化。"""
    base_map = {n["id"]: n for n in base_nodes}
    target_map = {n["id"]: n for n in target_nodes}

    added = [_node_brief(target_map[nid]) for nid in target_map if nid not in base_map]
    removed = [_node_brief(base_map[nid]) for nid in base_map if nid not in target_map]
    license_changed = []
    for nid in sorted(set(base_map) & set(target_map)):
        old, new = base_map[nid], target_map[nid]
        if old.get("license") != new.get("license"):
            license_changed.append(
                {
                    "id": nid,
                    "name": new.get("name") or old.get("name"),
                    "version": new.get("version") or old.get("version"),
                    "base_license": old.get("license_display"),
                    "target_license": new.get("license_display"),
                    "base_category": old.get("license_category"),
                    "target_category": new.get("license_category"),
                }
            )

    added.sort(key=lambda n: str(n["id"]))
    removed.sort(key=lambda n: str(n["id"]))
    return {"added": added, "removed": removed, "license_changed": license_changed}


def _diff_warnings(
    base_warnings: List[str], target_warnings: List[str]
) -> Dict[str, List[str]]:
    base_set = set(base_warnings)
    target_set = set(target_warnings)
    return {
        "added": [w for w in target_warnings if w not in base_set],
        "removed": [w for w in base_warnings if w not in target_set],
    }


def _side_meta(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "audit_id": result.get("audit_id"),
        "manifest_name": result.get("manifest_name"),
        "status": result.get("status"),
        "created_at": result.get("created_at"),
        "summary": result.get("summary", {}),
    }


def diff_results(
    base: Dict[str, Any],
    target: Dict[str, Any],
    base_id: Optional[int] = None,
    target_id: Optional[int] = None,
) -> Dict[str, Any]:
    """对比两次审计结果，返回新增 / 消失 / 状态变化的冲突、节点与告警。

    ``base`` 为基准（旧）审计，``target`` 为对比（新）审计；
    两者均为 ``analyzer.analyze_manifest`` 的输出字典（可含 audit_id）。
    """
    base_meta = _side_meta(base)
    target_meta = _side_meta(target)
    if base_id is not None:
        base_meta["audit_id"] = base_id
    if target_id is not None:
        target_meta["audit_id"] = target_id

    conflicts = _diff_conflicts(base.get("conflicts", []), target.get("conflicts", []))
    nodes = _diff_nodes(base.get("nodes", []), target.get("nodes", []))
    warnings = _diff_warnings(base.get("warnings", []), target.get("warnings", []))

    return {
        "base": base_meta,
        "target": target_meta,
        "summary": {
            "conflicts_added": len(conflicts["added"]),
            "conflicts_removed": len(conflicts["removed"]),
            "conflicts_changed": len(conflicts["changed"]),
            "nodes_added": len(nodes["added"]),
            "nodes_removed": len(nodes["removed"]),
            "nodes_license_changed": len(nodes["license_changed"]),
            "warnings_added": len(warnings["added"]),
            "warnings_removed": len(warnings["removed"]),
        },
        "conflicts": conflicts,
        "nodes": nodes,
        "warnings": warnings,
    }
