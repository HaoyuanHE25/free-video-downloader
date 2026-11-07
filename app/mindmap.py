"""把结构化摘要转成前端可直接渲染的思维导图。

节点结构固定：{id, label, detail, children}，前端按 children 递归渲染。
"""

from __future__ import annotations

import re

from app.downloader import UserFacingError
from app.subtitles_proc import clock

MAX_LABEL = 48
MAX_POINTS = 8
MAX_CHAPTERS = 12
_MERMAID_UNSAFE = re.compile(r'[()\[\]{}<>"\'`:;|#&]')
_BULLET = re.compile(r"^[-*+]\s+|^\d+[.)、]\s*")


def build_mindmap(result: dict, title: str | None = None) -> dict:
    outline = str(result.get("outline") or "").strip()
    points = [str(item).strip() for item in result.get("points") or [] if str(item).strip()][:MAX_POINTS]
    chapters = [item for item in result.get("chapters") or [] if isinstance(item, dict)][:MAX_CHAPTERS]

    root_label = (title or "").strip() or "视频内容"
    children: list[dict] = []

    if outline:
        children.append(
            {
                "id": "summary",
                "label": "摘要",
                "detail": "",
                "children": [{"id": "summary-text", "label": _short(outline), "detail": outline, "children": []}],
            }
        )

    if points:
        children.append(
            {
                "id": "points",
                "label": f"核心要点（{len(points)}）",
                "detail": "",
                "children": [
                    {"id": f"point-{index}", "label": _short(text), "detail": text, "children": []}
                    for index, text in enumerate(points)
                ],
            }
        )

    if chapters:
        chapter_nodes = []
        for index, chapter in enumerate(chapters):
            name = str(chapter.get("title") or "").strip() or f"第 {index + 1} 段"
            summary = str(chapter.get("summary") or "").strip()
            chapter_nodes.append(
                {
                    "id": f"chapter-{index}",
                    "label": f"{clock(chapter.get('start'))} {_short(name, 32)}",
                    "detail": summary,
                    "children": [],
                }
            )
        children.append(
            {
                "id": "chapters",
                "label": f"章节脉络（{len(chapters)}）",
                "detail": "",
                "children": chapter_nodes,
            }
        )

    return {
        "id": "root",
        "label": _short(root_label, 32),
        "detail": outline[:200],
        "children": children,
    }


def count_nodes(node: dict) -> int:
    if not isinstance(node, dict):
        return 0
    return 1 + sum(count_nodes(child) for child in node.get("children") or [])


def to_mermaid(tree: dict) -> str:
    """生成 Mermaid mindmap 语法。标签会清洗掉会破坏语法的字符。"""
    lines = ["mindmap"]

    def walk(node: dict, depth: int, root: bool = False) -> None:
        label = _mermaid_label(node.get("label"))
        if root:
            lines.append(f"{'  ' * depth}root(({label}))")
        else:
            lines.append(f"{'  ' * depth}{label}")
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child, depth + 1)

    walk(tree, 1, root=True)
    return "\n".join(lines)


def build_tree_from_text(text: str) -> dict:
    """把缩进式提纲转成节点树，方便用户在思维导图模块直接粘贴内容。"""
    lines = [line.rstrip() for line in (text or "").splitlines()]
    root_label = "内容提纲"
    body: list[tuple[int, str]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                root_label = title
            continue
        expanded = line.expandtabs(4)
        indent = len(expanded) - len(expanded.lstrip(" "))
        label = _BULLET.sub("", stripped).strip()
        if label:
            body.append((indent, label))
    if not body:
        raise UserFacingError("没有可用的提纲内容，请粘贴文字后再试", 400)

    root = {"id": "root", "label": root_label, "detail": "", "children": []}
    stack: list[tuple[int, dict]] = [(-1, root)]
    order = 0
    for indent, label in body:
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        order += 1
        node = {
            "id": f"outline-{order}",
            "label": _short(label, 40),
            "detail": "",
            "children": [],
        }
        parent["children"].append(node)
        stack.append((indent, node))
    return root


def _mermaid_label(text) -> str:
    clean = " ".join(str(text or "").split())
    clean = _MERMAID_UNSAFE.sub(" ", clean).strip()
    clean = clean or "未命名"
    return _short(clean, 40)


def _short(text: str, limit: int = MAX_LABEL) -> str:
    clean = " ".join(str(text or "").split())
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"
