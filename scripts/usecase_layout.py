#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用例图 · 坐标化渲染器（v1 · 步骤 3：严格解析 + SVG 完整性）
------------------------------------------------------------
解决 PlantUML 自动布局在用例图上的固有缺陷：
  · 1 个 actor 连多个用例时，用例会被排成横排并产生放射状交叉
  · 支撑用例（被 include）会被甩到系统边界外

输入：PlantUML 用例图子集，白名单见 SKILL_V1_SPEC.md §2.4
输出：坐标全部算好的 SVG；加 --png 时再经 Edge 无头截图产出同尺寸 PNG

处理顺序（任何一步失败都不打开或覆盖正式输出，错误写 stderr，exit != 0）：
  读取主文件及 include → 逐行白名单校验 → 检查别名和关系引用
  → 分类与布局 → 检查所有元素、关系均可渲染 → 生成并解析验证 SVG
  → [SVG-only] 原子替换 output.svg
  → [--png]  解析 viewBox → Edge 生成临时 PNG 并校验尺寸
             → 双产物原子提交（备份 → 替换 → 失败回滚）

用法：
  python usecase_layout.py in.puml out.svg [--png out.png] [--title "标题"]
环境变量：
  UML_EDGE   显式指定 msedge.exe 路径；无效直接失败，不会换用其他浏览器
"""

import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import namedtuple
from pathlib import Path

# ---------- 几何常量（单位 px，保持既有布局规则不变） ----------
PAD_X, PAD_TOP, PAD_BOT = 205, 60, 90
ACTOR_RX = 22          # 火柴人半宽
UC_RX, UC_RY = 88, 34  # 椭圆半径
ROW_GAP = 120          # 业务用例纵向间距
COL_BIZ, COL_SUP = 405, 700
COL_ACTOR_R = 955
FONT = "'Microsoft YaHei','SimHei','SimSun',sans-serif"

# 配色：只用一个强调色 + 灰阶（克制）
C_LINE, C_TEXT, C_MUTED = "#334155", "#0f172a", "#64748b"
C_UC_FILL, C_UC_STROKE = "#eef2ff", "#4f46e5"
C_BOUND = "#334155"

Edge = namedtuple("Edge", "src dst kind file lineno text")


class ParseError(Exception):
    """携带全部错误行的解析失败。"""

    def __init__(self, errors):
        super().__init__("; ".join(errors[:3]))
        self.errors = errors


def err(file, lineno, text, reason):
    return f"[错误] {file}:{lineno}: {reason}：{text}"


# ---------- Edge 转换与双产物提交（--png 模式） ----------

class EdgeError(Exception):
    pass


EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_edge():
    """UML_EDGE 显式指定即强制使用；无效直接失败，不得悄悄换用其他浏览器。"""
    env = os.environ.get("UML_EDGE", "").strip()
    if env:
        if not Path(env).is_file():
            raise EdgeError(f"UML_EDGE 指定的 Edge 不存在：{env}")
        return env
    for c in EDGE_CANDIDATES:
        if Path(c).is_file():
            return c
    raise EdgeError("未找到 Edge（msedge.exe），可用 UML_EDGE 环境变量显式指定路径")


def png_ihdr(path):
    """读取 PNG IHDR 尺寸；不是合法 PNG 返回 None。"""
    try:
        data = Path(path).read_bytes()[:24]
    except OSError:
        return None
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", data[16:24])
    return w, h


def parse_viewbox(root):
    """从 SVG 根元素取 viewBox，返回正整数 (w, h)；无效或缺失明确失败。"""
    vb = (root.get("viewBox") or "").split()
    if len(vb) != 4:
        raise EdgeError(f"SVG 根元素 viewBox 缺失或格式无效：{root.get('viewBox')!r}")
    try:
        w, h = int(vb[2]), int(vb[3])
    except ValueError:
        raise EdgeError(f"SVG viewBox 宽高不是整数：{root.get('viewBox')!r}")
    if w <= 0 or h <= 0:
        raise EdgeError(f"SVG viewBox 宽高必须为正整数：{w}x{h}")
    return w, h


def edge_screenshot(svg_file, png_dst, w, h, edge_exe):
    """Edge 无头截图：返回临时 PNG 路径（调用方在成功消费前负责保留）。
    失败抛 EdgeError 并自行清理临时 PNG。stderr 非空不作为失败依据。"""
    try:
        fd, tmp_name = tempfile.mkstemp(dir=str(Path(png_dst).parent),
                                        prefix=Path(png_dst).name + ".",
                                        suffix=".tmp.png")
    except OSError as exc:
        raise EdgeError(f"无法创建临时 PNG 文件：{exc}")
    os.close(fd)
    tmp_png = Path(tmp_name)
    profile = tempfile.mkdtemp(prefix="uml_edge_profile_")
    try:
        cmd = [
            edge_exe,
            "--headless",
            "--disable-gpu",
            "--disable-extensions",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            "--no-first-run",
            f"--window-size={w},{h}",
            f"--screenshot={tmp_png.resolve()}",
            f"--user-data-dir={Path(profile).resolve()}",
            Path(svg_file).resolve().as_uri(),
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=120)
        except subprocess.TimeoutExpired:
            raise EdgeError("Edge 转换超时（120s）")
        if r.returncode != 0:
            tail = [l for l in (r.stderr or r.stdout or "").strip().splitlines() if l][-5:]
            raise EdgeError(f"Edge 退出码 {r.returncode}" + ("：" + "；".join(tail) if tail else ""))
        if not tmp_png.exists() or tmp_png.stat().st_size == 0:
            raise EdgeError("Edge 未生成 PNG 或产物为空")
        ihdr = png_ihdr(tmp_png)
        if ihdr is None:
            raise EdgeError("Edge 产物不是合法 PNG 文件")
        if ihdr != (w, h):
            raise EdgeError(f"PNG 尺寸 {ihdr[0]}x{ihdr[1]} 与 viewBox {w}x{h} 不一致")
        return tmp_png
    except EdgeError:
        if tmp_png.exists():
            tmp_png.unlink()
        raise
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def commit_products(products):
    """双产物原子提交。products: [(tmp_path, target_path)]。
    目标预检 → 备份既有产物（各自目录内） → 逐个替换并验证 → 任一失败回滚。
    全部成功返回 True（临时文件已被消费）；失败返回 False（回滚，备份保留视情况）。"""
    for tmp, tgt in products:
        if Path(tgt).is_dir():
            print(f"[错误] 输出目标已是目录：{tgt}", file=sys.stderr)
            return False
    tag = os.getpid()
    backups = []   # (bak_path 或 None, target, existed)
    for tmp, tgt in products:
        tgt = Path(tgt)
        if tgt.exists():
            bak = tgt.with_name(tgt.name + f".tmpbak{tag}")
            try:
                shutil.copy2(tgt, bak)
            except OSError as exc:
                print(f"[错误] 备份既有产物失败：{tgt}（{exc}）", file=sys.stderr)
                for b, _, _ in backups:
                    if b is not None and b.exists():
                        b.unlink()
                return False
            backups.append((bak, tgt, True))
        else:
            backups.append((None, tgt, False))
    touched = []
    ok = True
    for tmp, tgt in products:
        tgt = Path(tgt)
        try:
            os.replace(tmp, tgt)
        except OSError as exc:
            print(f"[错误] 替换正式产物失败：{tgt}（{exc}）", file=sys.stderr)
            ok = False
            break
        if not tgt.exists() or tgt.stat().st_size == 0:
            print(f"[错误] 替换后目标不是非空文件：{tgt}", file=sys.stderr)
            ok = False
            break
        touched.append(tgt)
    if not ok:
        rb_ok = True
        for bak, tgt, existed in backups:
            if existed:
                try:
                    os.replace(bak, tgt)
                except OSError as exc:
                    print(f"[错误] 回滚失败：{tgt}（{exc}），备份保留在 {bak}", file=sys.stderr)
                    rb_ok = False
            elif tgt in touched:
                try:
                    tgt.unlink()
                except OSError as exc:
                    print(f"[错误] 回滚失败（删除本次新建文件）：{tgt}（{exc}）", file=sys.stderr)
                    rb_ok = False
        if rb_ok:
            print("[中止] 已回滚，正式产物保持原状。", file=sys.stderr)
        else:
            print(f"[中止] 回滚未完全成功，备份保留在原目标旁（*.tmpbak{tag}），请人工恢复。",
                  file=sys.stderr)
        return False
    for bak, _, existed in backups:
        if existed and bak.exists():
            bak.unlink()
    return True


def parse_args(args):
    """返回 ((src, svg_dst, png_dst, title), None) 或 (None, 用法错误信息)。"""
    src = svg_dst = png_dst = title = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--title":
            if i + 1 >= len(args):
                return None, "--title 缺少参数"
            title, i = args[i + 1], i + 2
        elif a == "--png":
            if i + 1 >= len(args):
                return None, "--png 后必须跟输出路径"
            png_dst, i = args[i + 1], i + 2
        elif a.startswith("-"):
            return None, f"未知参数：{a}"
        else:
            if src is None:
                src, i = a, i + 1
            elif svg_dst is None:
                svg_dst, i = a, i + 1
            else:
                return None, f"多余的位置参数：{a}"
    if src is None or svg_dst is None:
        return None, "用法：python usecase_layout.py in.puml out.svg [--png out.png] [--title 标题]"
    return (src, svg_dst, png_dst, title), None


# ---------- 词法 ----------

STYLE_RE = re.compile(
    r"^(?:skinparam(?:\s|$)|!pragma(?:\s|$)|hide(?:\s|$)|title(?:\s|$)"
    r"|left to right(?:\s|$)|top to bottom(?:\s|$))")

RE_ACTOR = re.compile(r'^actor\s+(?:"([^"]+)"|([^\s]+))(?:\s+as\s+([^\s]+))?\s*$')
RE_USECASE = re.compile(r'^usecase\s+(?:"([^"]+)"|([^\s]+))(?:\s+as\s+([^\s]+))?\s*$')
RE_BOUND = re.compile(r'^(?:rectangle|package)\s+(?:"([^"]+)"|([^\s{]+))\s*\{$')
RE_REL = re.compile(r'^(\S+)\s*(-->|\.\.>|--|\.\.)\s*(\S+?)(?:\s*:\s*(.+?))?\s*$')
RE_INCLUDE = re.compile(r'^!include\s+(\S+)\s*$')
RE_REMOTE = re.compile(r'^[a-zA-Z][a-zA-Z0-9+.-]*://')

STEREO = {"<<include>>": "include", "«include»": "include",
          "<<extend>>": "extend", "«extend»": "extend"}


def is_style(text):
    return bool(STYLE_RE.match(text))


def read_lines(path):
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise ParseError([err(str(path), 0, "", "文件不是 UTF-8 编码，无法解析")])
    except OSError as exc:
        raise ParseError([err(str(path), 0, "", f"无法读取文件：{exc}")])
    return [(str(path), i + 1, line.strip())
            for i, line in enumerate(text.splitlines())]


def expand(lines, mode, visited, errors):
    """递归展开 !include（相对引用它的文件解析），返回 [(file, lineno, text, mode)]。"""
    out = []
    for f, ln, text in lines:
        if text.startswith("!include"):
            m = RE_INCLUDE.match(text)
            if not m:
                errors.append(err(f, ln, text,
                                  "不支持的 include 语法（仅支持 !include <本地路径>）"))
                continue
            target = m.group(1)
            if RE_REMOTE.match(target) or target.startswith("<") or target.endswith("!"):
                errors.append(err(f, ln, text, "不支持非本地 include（URL / 标准库）"))
                continue
            ipath = Path(f).parent / target
            if not ipath.is_file():
                errors.append(err(f, ln, text, f"include 文件不存在：{ipath}"))
                continue
            real = str(ipath.resolve())
            if real in visited:
                errors.append(err(f, ln, text, "include 循环引用"))
                continue
            visited.add(real)
            try:
                sub = read_lines(ipath)
            except ParseError as pe:
                errors.extend(pe.errors)
                visited.discard(real)
                continue
            out.extend(expand(sub, "include", visited, errors))
            visited.discard(real)
            continue
        out.append((f, ln, text, mode))
    return out


def relation_kind(op, label):
    """返回 (kind, None) 或 (None, 失败原因)。"""
    dotted = op in ("..>", "..")
    if label is None:
        if op in ("--", "-->"):
            return "assoc", None
        return None, "虚线关系缺少构造型标签（应为 <<include>> 或 <<extend>>）"
    norm = re.sub(r"\s+", "", label).lower()
    kind = STEREO.get(norm)
    if kind is None:
        return None, "不支持的构造型或标签（关联行不允许带标签）"
    if not dotted:
        return None, f"{kind} 关系必须用虚线写法（..> / ..）"
    return kind, None


def validate(flat):
    """逐行白名单校验，返回 (model, errors)。每行都必须有明确处置。"""
    errors = []
    model = {"actors": {}, "usecases": {}, "edges": [], "bound": None}
    bound_open = None
    seen_start = seen_end = 0
    in_rect = False

    def add_element(table, alias, label, kind_cn, f, ln, text):
        if alias in table:
            errors.append(err(f, ln, text, f"{kind_cn}别名重复：{alias}"))
        elif alias in model["actors"] or alias in model["usecases"]:
            errors.append(err(f, ln, text, f"别名 {alias} 已被其他元素占用"))
        else:
            table[alias] = label

    for f, ln, text, mode in flat:
        if not text or text.startswith("'"):
            continue
        if mode == "include":
            if is_style(text):
                continue
            errors.append(err(f, ln, text,
                              "include 文件只能包含空行、注释和纯样式指令（出现模型定义）"))
            continue
        # ---- 主文件 ----
        if text == "@startuml":
            seen_start += 1
            if seen_start > 1:
                errors.append(err(f, ln, text, "@startuml 出现多次"))
            continue
        if text == "@enduml":
            seen_end += 1
            if seen_end > 1:
                errors.append(err(f, ln, text, "@enduml 出现多次"))
            continue
        if text.startswith("@"):
            errors.append(err(f, ln, text, "不支持的语法"))
            continue
        if is_style(text):
            continue
        if text.startswith("!"):
            errors.append(err(f, ln, text, "不支持的预处理指令（仅支持 !include）"))
            continue
        if text == "}":
            if not in_rect:
                errors.append(err(f, ln, text, "多余的右花括号（当前没有打开的系统边界）"))
            else:
                in_rect = False
            continue
        m = RE_BOUND.match(text)
        if m:
            if in_rect:
                errors.append(err(f, ln, text, "不支持嵌套系统边界"))
                continue
            if model["bound"] is not None:
                errors.append(err(f, ln, text, "只支持一个系统边界"))
                continue
            model["bound"] = m.group(1) or m.group(2)
            bound_open = (f, ln, text)
            in_rect = True
            continue
        m = RE_ACTOR.match(text)
        if m:
            add_element(model["actors"], m.group(3) or m.group(1) or m.group(2),
                        m.group(1) or m.group(2), "actor", f, ln, text)
            continue
        m = RE_USECASE.match(text)
        if m:
            add_element(model["usecases"], m.group(3) or m.group(1) or m.group(2),
                        m.group(1) or m.group(2), "usecase", f, ln, text)
            continue
        m = RE_REL.match(text)
        if m:
            src, op, dst, label = m.group(1), m.group(2), m.group(3), m.group(4)
            kind, reason = relation_kind(op, label)
            if kind is None:
                errors.append(err(f, ln, text, reason))
                continue
            model["edges"].append(Edge(src, dst, kind, f, ln, text))
            continue
        errors.append(err(f, ln, text, "不支持的语法（不在用例图白名单内）"))

    fname = flat[0][0] if flat else "<未知>"
    if seen_start == 0:
        errors.append(err(fname, 0, "", "缺少 @startuml"))
    if seen_end == 0:
        errors.append(err(fname, 0, "", "缺少 @enduml"))
    if in_rect and bound_open:
        errors.append(err(bound_open[0], bound_open[1], bound_open[2], "系统边界未闭合"))
    return model, errors


def check_refs(model):
    """关系端点必须已定义；未定义指向原关系行。"""
    errors = []
    known = set(model["actors"]) | set(model["usecases"])
    for e in model["edges"]:
        for end in (e.src, e.dst):
            if end not in known:
                errors.append(err(e.file, e.lineno, e.text, f"关系端点未定义：{end}"))
    return errors


def load_model(src):
    errors = []
    lines = read_lines(src)
    visited = {str(Path(src).resolve())}
    flat = expand(lines, "main", visited, errors)
    model, verrs = validate(flat)
    errors.extend(verrs)
    if errors:
        raise ParseError(errors)
    errors = check_refs(model)
    if errors:
        raise ParseError(errors)
    return model


def classify(model):
    """把用例分成 业务 / 支撑 / 扩展 三类，找出主/次 actor（规则不变）。"""
    assoc = [(e.src, e.dst) for e in model["edges"] if e.kind == "assoc"]
    inc = [(e.src, e.dst) for e in model["edges"] if e.kind == "include"]
    ext = [(e.src, e.dst) for e in model["edges"] if e.kind == "extend"]

    # actor 关联的用例数 → 最多的为主 actor
    a_count = {}
    for s, d in assoc:
        if s in model["actors"]:
            a_count[s] = a_count.get(s, 0) + 1
        elif d in model["actors"]:
            a_count[d] = a_count.get(d, 0) + 1
    primary = max(a_count, key=a_count.get) if a_count else None
    secondary = [a for a in model["actors"] if a != primary]

    # 业务用例 = 主 actor 直接关联的
    biz = []
    for s, d in assoc:
        if primary is not None:
            if s == primary and d in model["usecases"]:
                biz.append(d)
            elif d == primary and s in model["usecases"]:
                biz.append(s)

    # 支撑用例 = 被 include 指向的
    sup = []
    for s, d in inc:
        if d not in sup:
            sup.append(d)

    # 扩展用例 = 发起 extend 的
    extd = []
    for s, d in ext:
        if s not in extd:
            extd.append(s)

    # 剩余兜底归业务
    for u in model["usecases"]:
        if u not in biz and u not in sup and u not in extd:
            biz.append(u)

    return {
        "primary": primary, "secondary": secondary,
        "biz": biz, "sup": sup, "ext": extd,
        "assoc": assoc, "inc": inc, "ext_e": ext,
    }


def check_classifiable(model, cls):
    """布局前置检查：模型必须可分类、可布局，不允许靠异常崩溃兜底。"""
    if not model["usecases"]:
        return "没有解析到 usecase，检查文件是否符合用例图子集"
    if not model["actors"]:
        return "没有 actor，无法确定主参与者"
    if cls["primary"] is None:
        return "没有任何 actor 与用例的关联，无法确定主 actor"
    if not cls["biz"]:
        return "无法布局：缺少业务用例（所有用例均为支撑/扩展用例）"
    return None


def layout(model, cls):
    """计算所有元素坐标（规则不变）。"""
    pos = {}  # alias -> (cx, cy, kind)

    top = PAD_TOP + 85
    for i, u in enumerate(cls["biz"]):
        pos[u] = (COL_BIZ, top + i * ROW_GAP, "usecase")

    # 支撑用例：y = 其 include 源的质心
    for u in cls["sup"]:
        srcs = [s for s, d in cls["inc"] if d == u and s in pos]
        y = sum(pos[s][1] for s in srcs) / len(srcs) if srcs else top
        pos[u] = (COL_SUP, y, "usecase")

    # 扩展用例：放在顶部之上
    for i, u in enumerate(cls["ext"]):
        pos[u] = (COL_SUP, top - ROW_GAP - i * ROW_GAP, "usecase")

    # 主 actor：纵向中点
    biz_ys = [pos[u][1] for u in cls["biz"]]
    if cls["primary"]:
        pos[cls["primary"]] = (95, (min(biz_ys) + max(biz_ys)) / 2, "actor")

    # 次 actor：y 对齐其关联用例
    for a in cls["secondary"]:
        ys = []
        for s, d in cls["assoc"]:
            other = d if s == a else (s if d == a else None)
            if other in pos:
                ys.append(pos[other][1])
        y = sum(ys) / len(ys) if ys else (min(biz_ys) + max(biz_ys)) / 2
        pos[a] = (COL_ACTOR_R, y, "actor")

    # 系统边界
    uc_pts = [pos[u] for u in model["usecases"] if u in pos]
    if uc_pts:
        x0 = min(p[0] for p in uc_pts) - UC_RX - 60
        x1 = max(p[0] for p in uc_pts) + UC_RX + 60
        y0 = min(p[1] for p in uc_pts) - UC_RY - 55
        y1 = max(p[1] for p in uc_pts) + UC_RY + 60
    else:
        x0, y0, x1, y1 = PAD_X, PAD_TOP, PAD_X + 640, PAD_TOP + 640

    # 归一化：保证顶部留出标题/边界空间，整体下移
    min_y = min(p[1] for p in pos.values()) - UC_RY - 90
    if min_y < 40:
        shift = 40 - min_y
        pos = {k: (x, y + shift, t) for k, (x, y, t) in pos.items()}
        y0 += shift
        y1 += shift

    return pos, (x0, y0, x1, y1)


def verify_renderable(model, pos):
    """渲染前置检查：所有元素均有坐标、所有关系均可渲染。"""
    problems = []
    for alias in model["actors"]:
        if alias not in pos:
            problems.append(f"actor 无坐标：{alias}")
    for alias in model["usecases"]:
        if alias not in pos:
            problems.append(f"用例无坐标：{alias}")
    for e in model["edges"]:
        if e.src not in pos or e.dst not in pos:
            problems.append(f"关系无法渲染：{e.src} — {e.dst}（{e.file}:{e.lineno}）")
    return problems


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def edge_pt(cx, cy, rx, ry, tx, ty):
    """从椭圆中心指向 (tx,ty) 的边缘交点。"""
    dx, dy = tx - cx, ty - cy
    if dx == 0 and dy == 0:
        return cx, cy
    t = 1.0 / math.hypot(dx / rx, dy / ry)
    return cx + dx * t, cy + dy * t


def render(model, cls, pos, box, title=None):
    """生成 SVG；每条关系恰好渲染一次，返回 (svg_text, drawn)。"""
    W = COL_ACTOR_R + 85
    H = max(p[1] for p in pos.values()) + UC_RY + 150
    x0, y0, x1, y1 = box

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
           f'viewBox="0 0 {W:.0f} {H:.0f}" font-family="{FONT}">',
           f'<rect width="{W:.0f}" height="{H:.0f}" fill="#ffffff"/>',
           '<defs><marker id="arw" viewBox="0 0 10 10" refX="9" refY="5" '
           'markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
           f'<path d="M 0 0 L 10 5 L 0 10" fill="none" stroke="{C_MUTED}" stroke-width="1.8"/>'
           '</marker></defs>']

    if title:
        out.append(f'<text x="{W/2:.0f}" y="34" font-size="20" font-weight="700" '
                   f'fill="{C_TEXT}" text-anchor="middle">{esc(title)}</text>')

    # 系统边界
    out.append(f'<rect x="{x0:.0f}" y="{y0:.0f}" width="{x1-x0:.0f}" height="{y1-y0:.0f}" '
               f'rx="6" fill="#fff" stroke="{C_BOUND}" stroke-width="1.6"/>')
    if model["bound"]:
        out.append(f'<text x="{x0+10:.0f}" y="{y0+24:.0f}" font-size="15" font-weight="700" '
                   f'fill="{C_TEXT}">{esc(model["bound"])}</text>')

    # 连线（先画，压在图形下）；前置检查已保证端点必有坐标，不再静默跳过
    drawn = 0
    for e in model["edges"]:
        sx, sy, sk = pos[e.src]
        dx_, dy_, dk = pos[e.dst]
        if sk == "actor":
            p1 = (sx + ACTOR_RX, sy)
        else:
            p1 = edge_pt(sx, sy, UC_RX, UC_RY, dx_, dy_)
        if dk == "actor":
            p2 = (dx_ - ACTOR_RX, dy_)
        else:
            p2 = edge_pt(dx_, dy_, UC_RX, UC_RY, sx, sy)

        if e.kind == "assoc":
            out.append(f'<line x1="{p1[0]:.1f}" y1="{p1[1]:.1f}" x2="{p2[0]:.1f}" '
                       f'y2="{p2[1]:.1f}" stroke="{C_LINE}" stroke-width="1.4"/>')
        else:
            out.append(f'<line x1="{p1[0]:.1f}" y1="{p1[1]:.1f}" x2="{p2[0]:.1f}" '
                       f'y2="{p2[1]:.1f}" stroke="{C_MUTED}" stroke-width="1.4" '
                       f'stroke-dasharray="6 5" marker-end="url(#arw)"/>')
            # 构造型标签，放在线中点偏上
            mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
            txt = "«include»" if e.kind == "include" else "«extend»"
            out.append(f'<text x="{mx:.0f}" y="{my-7:.0f}" font-size="11" fill="{C_MUTED}" '
                       f'text-anchor="middle" font-style="italic" stroke="#ffffff" '
                       f'stroke-width="3" paint-order="stroke">{txt}</text>')
        drawn += 1

    # 用例椭圆
    for alias, label in model["usecases"].items():
        cx, cy, _ = pos[alias]
        out.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{UC_RX}" ry="{UC_RY}" '
                   f'fill="{C_UC_FILL}" stroke="{C_UC_STROKE}" stroke-width="1.6"/>')
        out.append(f'<text x="{cx}" y="{cy+4.5}" font-size="13" fill="{C_TEXT}" '
                   f'text-anchor="middle">{esc(label)}</text>')

    # actor 火柴人
    for alias, label in model["actors"].items():
        cx, cy, _ = pos[alias]
        hx, hy = cx, cy - 54          # 头心
        out.append(f'<circle cx="{hx}" cy="{hy}" r="13" fill="#fff" stroke="{C_BOUND}" stroke-width="2"/>')
        out.append(f'<line x1="{hx}" y1="{hy+13}" x2="{hx}" y2="{hy+54}" stroke="{C_BOUND}" stroke-width="2"/>')
        out.append(f'<line x1="{hx-22}" y1="{hy+26}" x2="{hx+22}" y2="{hy+26}" stroke="{C_BOUND}" stroke-width="2"/>')
        out.append(f'<line x1="{hx}" y1="{hy+54}" x2="{hx-18}" y2="{hy+86}" stroke="{C_BOUND}" stroke-width="2"/>')
        out.append(f'<line x1="{hx}" y1="{hy+54}" x2="{hx+18}" y2="{hy+86}" stroke="{C_BOUND}" stroke-width="2"/>')
        out.append(f'<text x="{cx}" y="{hy+108}" font-size="14" fill="{C_TEXT}" '
                   f'text-anchor="middle" font-weight="600">{esc(label)}</text>')

    out.append("</svg>")
    return "\n".join(out), drawn


def print_stats(model, cls):
    n_assoc = sum(1 for e in model["edges"] if e.kind == "assoc")
    n_inc = sum(1 for e in model["edges"] if e.kind == "include")
    n_ext = sum(1 for e in model["edges"] if e.kind == "extend")
    print(f"  主 actor: {model['actors'].get(cls['primary'])}  次 actor: "
          f"{[model['actors'][a] for a in cls['secondary']]}")
    print(f"  业务用例 {len(cls['biz'])} 个 / 支撑 {len(cls['sup'])} 个 / 扩展 {len(cls['ext'])} 个")
    print(f"  关系 {len(model['edges'])} 条（关联 {n_assoc} / include {n_inc} / extend {n_ext}）")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    parsed, usage_err = parse_args(sys.argv[1:])
    if usage_err:
        print(f"[错误] {usage_err}", file=sys.stderr)
        sys.exit(2)
    src, svg_dst, png_dst, title = parsed

    # 1-6. 读取、逐行校验、引用检查、分类布局、渲染前置检查、生成并验证 SVG（共用）
    try:
        model = load_model(src)
    except ParseError as pe:
        for line in pe.errors:
            print(line, file=sys.stderr)
        print(f"[失败] 解析未通过（{len(pe.errors)} 处错误），未生成任何输出。", file=sys.stderr)
        sys.exit(1)

    cls = classify(model)
    fatal = check_classifiable(model, cls)
    if fatal:
        print(f"[错误] {src}: {fatal}", file=sys.stderr)
        print("[失败] 未生成任何输出。", file=sys.stderr)
        sys.exit(1)

    pos, box = layout(model, cls)
    problems = verify_renderable(model, pos)
    if problems:
        for p in problems:
            print(f"[错误] 渲染前置检查失败：{p}", file=sys.stderr)
        print("[失败] 未生成任何输出。", file=sys.stderr)
        sys.exit(1)

    svg, drawn = render(model, cls, pos, box, title)
    if drawn != len(model["edges"]):
        print(f"[错误] 内部一致性失败：应渲染 {len(model['edges'])} 条关系，实际 {drawn} 条",
              file=sys.stderr)
        print("[失败] 未生成任何输出。", file=sys.stderr)
        sys.exit(1)
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        print(f"[错误] 生成的 SVG 不是合法 XML：{exc}", file=sys.stderr)
        print("[失败] 未生成任何输出。", file=sys.stderr)
        sys.exit(1)

    if png_dst is None:
        # ---- SVG-only：行为与第 3 步一致 ----
        tmp_path = None
        try:
            fd, tmp_name = tempfile.mkstemp(
                dir=str(Path(svg_dst).parent) if str(Path(svg_dst).parent) else ".",
                prefix=Path(svg_dst).name + ".", suffix=".tmp.svg")
            tmp_path = Path(tmp_name)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(svg)
            os.replace(tmp_name, svg_dst)
            tmp_path = None
        except OSError as exc:
            print(f"[错误] 写出 SVG 失败：{exc}", file=sys.stderr)
            print("[失败] 未生成任何输出；已有输出保持不变。", file=sys.stderr)
            sys.exit(1)
        finally:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink()
        print(f"[完成] {svg_dst}")
        print_stats(model, cls)
        return

    # ---- SVG + PNG 双产物 ----
    for label, p in (("SVG", svg_dst), ("PNG", png_dst)):
        if Path(p).is_dir():
            print(f"[错误] {label} 输出路径已是目录：{p}", file=sys.stderr)
            sys.exit(1)
    try:
        w, h = parse_viewbox(root)
        edge_exe = find_edge()
    except EdgeError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        sys.exit(1)

    tmp_svg = tmp_png = None
    try:
        try:
            fd, tmp_name = tempfile.mkstemp(
                dir=str(Path(svg_dst).parent) if str(Path(svg_dst).parent) else ".",
                prefix=Path(svg_dst).name + ".", suffix=".tmp.svg")
        except OSError as exc:
            print(f"[错误] 无法创建临时 SVG：{exc}", file=sys.stderr)
            sys.exit(1)
        tmp_svg = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(svg)
        try:
            tmp_png = edge_screenshot(tmp_svg, png_dst, w, h, edge_exe)
        except EdgeError as exc:
            print(f"[错误] {exc}", file=sys.stderr)
            print("[失败] 未生成任何输出；已有产物保持不变。", file=sys.stderr)
            sys.exit(1)
        # 双产物原子提交：目标预检 → 备份 → 替换 → 失败回滚
        if not commit_products([(tmp_svg, svg_dst), (tmp_png, png_dst)]):
            print("[失败] 未生成任何输出；已有产物保持不变。", file=sys.stderr)
            sys.exit(1)
        tmp_svg = tmp_png = None
    finally:
        for t in (tmp_svg, tmp_png):
            if t is not None and Path(t).exists():
                Path(t).unlink()

    print(f"[完成] {svg_dst}")
    print(f"[完成] {png_dst}")
    print_stats(model, cls)


if __name__ == "__main__":
    main()
