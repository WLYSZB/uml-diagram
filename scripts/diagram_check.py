#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Optional semantic checks for tagged PlantUML diagrams.

Only files with a line like "' @diagram dfd-level0" are inspected.
Untagged legacy files deliberately remain outside this checker.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

DIAGRAM_RE = re.compile(r"^\s*'\s*@diagram\s+([A-Za-z0-9_-]+)\s*$")
PARENT_RE = re.compile(r"^\s*'\s*@parent\s+(.+?)\s*$")
PARENT_PROCESS_RE = re.compile(r"^\s*'\s*@parent-process\s+(\S+)\s*$")
NODE_RE = re.compile(
    r'^(rectangle|database)\s+"([^"]+)"\s+as\s+([A-Za-z_][A-Za-z0-9_]*)'
    r"(?:\s*<<([^>]+)>>)?"
)
EDGE_RE = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*)\s*(-->|->|\.\.>)\s*"
    r"([A-Za-z_][A-Za-z0-9_]*)(?:\s*:\s*(.+))?$"
)
OBJECT_RE = re.compile(r"^object\s+")


@dataclass
class Node:
    alias: str
    label: str
    kind: str
    line: int
    text: str


@dataclass
class Edge:
    src: str
    dst: str
    label: str | None
    line: int
    text: str


@dataclass
class Document:
    path: Path
    kind: str
    lines: list[tuple[int, str]]
    parent: str | None = None
    parent_process: str | None = None
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)


class CheckError(Exception):
    def __init__(self, path: Path, line: int, text: str, reason: str):
        super().__init__(reason)
        self.path = path
        self.line = line
        self.text = text
        self.reason = reason

    def format(self) -> str:
        return f"[错误] {self.path}:{self.line}: {self.reason}：{self.text}"


def error(path: Path, line: int, text: str, reason: str) -> CheckError:
    return CheckError(path, line, text, reason)


def read_document(path: Path, manifest: dict, visited: set[Path] | None = None) -> Document:
    path = path.resolve()
    visited = set() if visited is None else visited
    if path in visited:
        raise error(path, 0, "", "DFD 父文件循环引用")
    visited.add(path)
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise error(path, 0, "", f"无法读取文件：{exc}")
    lines = list(enumerate(raw.splitlines(), 1))
    kind = None
    parent = None
    parent_process = None
    for number, text in lines:
        match = DIAGRAM_RE.match(text)
        if match:
            if kind is not None:
                raise error(path, number, text, "@diagram 标记重复")
            kind = match.group(1)
        match = PARENT_RE.match(text)
        if match:
            parent = match.group(1)
        match = PARENT_PROCESS_RE.match(text)
        if match:
            parent_process = match.group(1)
    if kind is None:
        raise error(path, 0, "", "父文件缺少 @diagram 类型标记")
    if kind not in manifest:
        raise error(path, 0, kind, "未注册的图种类型")
    doc = Document(path, kind, lines, parent, parent_process)
    if manifest[kind].get("validator") == "dfd":
        parse_dfd(doc)
    return doc


def parse_dfd(doc: Document) -> None:
    for number, text in doc.lines:
        stripped = text.strip()
        match = NODE_RE.match(stripped)
        if match:
            shape, label, alias, stereo = match.groups()
            role = (stereo or "").strip().lower()
            if role not in {"external", "process", "store"}:
                raise error(doc.path, number, text,
                            "DFD 节点必须声明 <<external>>、<<process>> 或 <<store>>")
            if alias in doc.nodes:
                raise error(doc.path, number, text, f"DFD 节点别名重复：{alias}")
            doc.nodes[alias] = Node(alias, label, role, number, text)
            continue
        match = EDGE_RE.match(stripped)
        if match:
            src, _arrow, dst, label = match.groups()
            doc.edges.append(Edge(src, dst, label.strip() if label else None, number, text))


def manifest_for(path: Path) -> dict:
    manifest_path = Path(__file__).resolve().parent.parent / "diagram-types.json"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise error(manifest_path, 0, "", f"无法读取图种清单：{exc}")
    except json.JSONDecodeError as exc:
        raise error(manifest_path, exc.lineno, "", f"图种清单不是合法 JSON：{exc.msg}")
    result = {}
    for item in data.get("types", []):
        if not isinstance(item, dict) or not item.get("id"):
            raise error(manifest_path, 0, "", "图种清单存在无效条目")
        result[item["id"]] = item
    return result


def validate_dfd(doc: Document, manifest: dict, visited: set[Path]) -> list[CheckError]:
    errors: list[CheckError] = []
    nodes = doc.nodes
    if not nodes:
        return [error(doc.path, 0, "", "DFD 未声明任何节点")]
    degree = {alias: 0 for alias in nodes}
    for edge in doc.edges:
        if edge.src not in nodes or edge.dst not in nodes:
            errors.append(error(doc.path, edge.line, edge.text, "数据流端点未定义"))
            continue
        degree[edge.src] += 1
        degree[edge.dst] += 1
        if not edge.label:
            errors.append(error(doc.path, edge.line, edge.text, "数据流必须填写标签"))
        src_kind = nodes[edge.src].kind
        dst_kind = nodes[edge.dst].kind
        if src_kind == dst_kind == "external":
            errors.append(error(doc.path, edge.line, edge.text, "外部实体不能直接连接外部实体"))
        if src_kind == dst_kind == "store":
            errors.append(error(doc.path, edge.line, edge.text, "数据存储不能直接连接数据存储"))
    for alias, count in degree.items():
        if count == 0:
            node = nodes[alias]
            errors.append(error(doc.path, node.line, node.text, f"孤立 DFD 节点：{alias}"))

    processes = [n for n in nodes.values() if n.kind == "process"]
    stores = [n for n in nodes.values() if n.kind == "store"]
    externals = [n for n in nodes.values() if n.kind == "external"]
    if not externals and doc.kind in {"dfd-context", "dfd-level0"}:
        errors.append(error(doc.path, 0, "", "DFD 至少需要一个外部实体"))
    if doc.kind == "dfd-context":
        if len(processes) != 1:
            errors.append(error(doc.path, 0, "", "DFD 上下文图必须恰有一个系统处理过程"))
        if stores:
            errors.append(error(doc.path, 0, "", "DFD 上下文图不应声明数据存储"))
    elif doc.kind == "dfd-level0":
        if len(processes) < 2:
            errors.append(error(doc.path, 0, "", "DFD 0 层图至少需要两个子处理过程"))
        if not stores:
            errors.append(error(doc.path, 0, "", "DFD 0 层图至少需要一个数据存储"))
    elif doc.kind == "dfd-level1":
        if len(processes) < 2:
            errors.append(error(doc.path, 0, "", "DFD 1 层图至少需要两个子处理过程"))
        if not doc.parent_process:
            errors.append(error(doc.path, 0, "", "DFD 1 层图必须声明 @parent-process"))

    if doc.kind in {"dfd-level0", "dfd-level1"}:
        if not doc.parent:
            errors.append(error(doc.path, 0, "", "分解 DFD 必须声明 @parent"))
        else:
            parent_path = (doc.path.parent / doc.parent).resolve()
            expected = "dfd-context" if doc.kind == "dfd-level0" else "dfd-level0"
            try:
                parent = read_document(parent_path, manifest, visited)
                if parent.kind != expected:
                    errors.append(error(doc.path, 0, doc.parent,
                                        f"父图类型应为 {expected}，实际为 {parent.kind}"))
                if doc.kind == "dfd-level1" and doc.parent_process:
                    if doc.parent_process not in parent.nodes:
                        errors.append(error(doc.path, 0, doc.parent_process,
                                            "父图中不存在指定的父过程别名"))
                    elif parent.nodes[doc.parent_process].kind != "process":
                        errors.append(error(doc.path, 0, doc.parent_process,
                                            "@parent-process 必须指向父图处理过程"))
                if doc.kind == "dfd-level0" and parent.kind == expected:
                    errors.extend(balance_context(parent, doc))
            except CheckError as exc:
                errors.append(exc)
    return errors


def interface_flows(doc: Document) -> set[tuple[str, str, str]]:
    flows = set()
    for edge in doc.edges:
        if edge.src not in doc.nodes or edge.dst not in doc.nodes or not edge.label:
            continue
        src = doc.nodes[edge.src]
        dst = doc.nodes[edge.dst]
        if src.kind == "external" and dst.kind == "process":
            flows.add((src.alias, "out", edge.label))
        elif dst.kind == "external" and src.kind == "process":
            flows.add((dst.alias, "in", edge.label))
    return flows


def balance_context(parent: Document, child: Document) -> list[CheckError]:
    expected = interface_flows(parent)
    actual = interface_flows(child)
    errors = []
    for flow in sorted(expected - actual):
        errors.append(error(child.path, 0, str(flow), "子图缺少父上下文图的外部数据流"))
    for flow in sorted(actual - expected):
        errors.append(error(child.path, 0, str(flow), "子图新增外部数据流，未在父上下文图声明"))
    return errors


def validate_flow(doc: Document) -> list[CheckError]:
    errors = []
    starts = stops = 0
    lanes = 0
    # 块栈：元素 (kind, [分支是否已有动作])，kind 为 "if" 或 "switch"。
    # exception-flow 要求每个失败分支（else/elseif/case）之后出现处理动作。
    blocks: list[tuple[str, list[bool]]] = []
    for number, text in doc.lines:
        stripped = text.strip()
        if stripped == "start":
            starts += 1
        elif stripped == "stop":
            stops += 1
        if stripped.startswith("|") and stripped.endswith("|") and len(stripped) > 2:
            lanes += 1
        if re.match(r"^if\s*\(", stripped):
            if not re.search(r"\bthen\s*\([^)]*\)", stripped):
                errors.append(error(doc.path, number, text, "if 判断必须有 then 分支标签"))
            blocks.append(("if", []))
        elif re.match(r"^switch\s*\(", stripped):
            blocks.append(("switch", []))
        elif re.match(r"^switch\b", stripped):
            errors.append(error(doc.path, number, text, "switch 必须带条件括号，如 switch (成绩 ?)"))
        elif re.match(r"^case\s*\([^)]*\)", stripped):
            if not blocks or blocks[-1][0] != "switch":
                errors.append(error(doc.path, number, text, "case 只能出现在 switch 块内"))
            else:
                blocks[-1][1].append(False)
        elif re.match(r"^case\b", stripped):
            errors.append(error(doc.path, number, text, "case 分支必须有标签，如 case (成绩 >= 90 ?)"))
        elif re.match(r"^elseif\s*\(", stripped):
            if not blocks or blocks[-1][0] != "if":
                errors.append(error(doc.path, number, text, "elseif 没有对应 if"))
            elif not re.search(r"\bthen\s*\([^)]*\)", stripped):
                errors.append(error(doc.path, number, text, "elseif 判断必须有 then 分支标签"))
            else:
                blocks[-1][1].append(False)
        elif stripped == "else" or stripped.startswith("else ") or stripped == "default":
            if blocks and blocks[-1][0] == "switch":
                errors.append(error(doc.path, number, text,
                                    "switch 不支持 else/default 兜底分支（本机 PlantUML 1.2025.4 "
                                    "实测语法错误）：剩余情况写显式 case（如 case (g < 60 ?)），或改用 if/elseif"))
            elif not blocks:
                errors.append(error(doc.path, number, text, "else 没有对应 if"))
            else:
                if not re.search(r"^else(?:\s*\([^)]*\))?", stripped):
                    errors.append(error(doc.path, number, text, "else 分支标签格式无效"))
                blocks[-1][1].append(False)
        elif stripped == "endif":
            if not blocks or blocks[-1][0] != "if":
                errors.append(error(doc.path, number, text, "endif 没有对应 if"))
            else:
                _kind, values = blocks.pop()
                if doc.kind == "exception-flow" and any(not value for value in values):
                    errors.append(error(doc.path, number, text, "异常分支必须包含处理动作"))
        elif stripped == "endswitch":
            if not blocks or blocks[-1][0] != "switch":
                errors.append(error(doc.path, number, text, "endswitch 没有对应 switch"))
            else:
                _kind, values = blocks.pop()
                if doc.kind == "exception-flow" and any(not value for value in values):
                    errors.append(error(doc.path, number, text, "异常分支必须包含处理动作"))
        elif stripped.startswith(":"):
            for _kind, values in blocks:
                if values:
                    values[-1] = True
        if re.match(r"^while\s*\(", stripped) and not re.search(r"\bis\s*\([^)]*\)", stripped):
            errors.append(error(doc.path, number, text, "while 循环必须有 is 分支标签"))
        if "repeat while" in stripped and not re.search(r"\bis\s*\([^)]*\)", stripped):
            errors.append(error(doc.path, number, text, "repeat while 必须有 is 分支标签"))
    if starts != 1:
        errors.append(error(doc.path, 0, "", f"流程图必须恰有一个 start，实际 {starts}"))
    if stops < 1:
        errors.append(error(doc.path, 0, "", f"流程图至少需要一个 stop，实际 {stops}（允许多出口）"))
    if blocks:
        errors.append(error(doc.path, 0, "", "if/switch 分支未闭合"))
    if doc.kind == "business-process" and lanes < 2:
        errors.append(error(doc.path, 0, "",
                            "业务流程图至少需要两个泳道；单角色顺序流程请改用 program-flow 图种"))
    return errors


def validate_basic(doc: Document) -> list[CheckError]:
    if doc.kind == "object":
        count = sum(1 for _n, text in doc.lines if OBJECT_RE.match(text.strip()))
        return [] if count >= 2 else [error(doc.path, 0, "", "对象图至少需要两个 object")]
    if doc.kind == "communication":
        messages = [text for _n, text in doc.lines if re.search(r":\s*\d+(?:\.\d+)*\s*:", text)]
        return [] if messages else [error(doc.path, 0, "", "通信图至少需要一条带编号消息")]
    return []


def check(path: Path) -> list[CheckError]:
    manifest = manifest_for(path)
    doc = read_document(path, manifest)
    validator = manifest[doc.kind].get("validator")
    if validator == "dfd":
        return validate_dfd(doc, manifest, {doc.path.resolve()})
    if validator in {"flow", "business", "exception"}:
        return validate_flow(doc)
    return validate_basic(doc)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("用法：python diagram_check.py <file.puml>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        print(f"[错误] {path}:0: 无法读取文件：{exc}", file=sys.stderr)
        return 1
    if not any(DIAGRAM_RE.match(line) for line in raw.splitlines()):
        return 0
    try:
        errors = check(path)
    except CheckError as exc:
        errors = [exc]
    if errors:
        for exc in errors:
            print(exc.format(), file=sys.stderr)
        print(f"[失败] {path.name} 语义校验未通过（{len(errors)} 处错误）", file=sys.stderr)
        return 1
    print(f"  [语义通过] {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
