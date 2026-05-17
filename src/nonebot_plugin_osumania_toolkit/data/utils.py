import json
import re
from pathlib import Path

def format_list(dans: list, items_per_line: int = 5) -> str:
    """
    格式化列表数据，每行显示指定数量的数据
    
    参数:
        dans: 列表
        items_per_line: 每行显示的数据数量
    
    返回:
        格式化后的字符串
    """
    formatted_lines = []
    for i in range(0, len(dans), items_per_line):
        line = dans[i:i + items_per_line]
        formatted_lines.append(", ".join(line))
    return "\n".join(formatted_lines)

def _get_dan_group_name(dan_name: str) -> str:
    """根据段位命名规则返回分组名。"""
    greek_names = {"alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "spz"}

    if dan_name.startswith("wds0_"):
        return "wds0"
    if dan_name.startswith("xfpsb"):
        return "xfpsb"
    if dan_name.startswith("7kln"):
        return "7kln"
    if dan_name.startswith("7k"):
        return "7k"
    if dan_name.startswith("ln"):
        return "ln"
    if dan_name.startswith("senpaiex"):
        return "senpaiex"
    if dan_name.startswith("senpai"):
        return "senpai"
    if dan_name.startswith("spex"):
        return "spex"
    if re.match(r"^ex(?:\d+v\d(?:\.\d+)?|fv\d)$", dan_name):
        return "ex"
    if re.match(r"^\d+danv\d$", dan_name):
        return "danv"
    if re.match(r"^rf\d+$", dan_name) or dan_name in greek_names:
        return "rf/reform"
    if dan_name == "haku":
        return "misc"
    return "other"

def format_dan_list_grouped(dans: list, items_per_line: int = 5) -> str:
    """按前缀分组并格式化段位列表。"""
    groups = {}
    for dan in sorted(dans):
        group_name = _get_dan_group_name(dan)
        groups.setdefault(group_name, []).append(dan)

    preferred_order = [
        "danv",
        "ex",
        "spex",
        "rf/reform",
        "ln",
        "xfpsb",
        "7k",
        "7kln",
        "senpai",
        "senpaiex",
        "wds0",
        "misc",
        "other",
    ]

    ordered_group_names = [name for name in preferred_order if name in groups]
    ordered_group_names.extend(sorted(name for name in groups if name not in preferred_order))

    formatted_sections = []
    for group_name in ordered_group_names:
        formatted_sections.append(f"[{group_name}]")
        formatted_sections.append(format_list(groups[group_name], items_per_line))

    return "\n\n".join(formatted_sections)


def _build_cvtscore_ruleset_listing_text() -> str:
    """构建 /cvtscore 可用模板与具体 ruleset 列表。"""
    root = Path(__file__).resolve().parent.parent / "rulesets"
    templates_dir = root / "templates"

    lines: list[str] = [""]

    template_rows: list[str] = []
    try:
        template_files = sorted(list(templates_dir.glob("*.ruleset")), key=lambda p: p.stem.lower())
    except Exception:
        template_files = []

    for template_file in template_files:
        name = template_file.stem
        summary = "(无说明)"

        try:
            content = template_file.read_text(encoding="utf-8-sig")
            raw = json.loads(content)
            template_meta = raw.get("Template") if isinstance(raw, dict) else None
            if isinstance(template_meta, dict):
                raw_name = template_meta.get("Name")
                raw_summary = template_meta.get("Summary")
                if isinstance(raw_name, str) and raw_name.strip():
                    name = raw_name.strip()
                if isinstance(raw_summary, str) and raw_summary.strip():
                    summary = raw_summary.strip()
        except Exception:
            pass
        
        if summary:
            template_rows.append(f"{name}: {summary}")
        else:
            template_rows.append(name)

    lines.append("[模板]")
    if template_rows:
        lines.extend(template_rows)
    else:
        lines.append("(无)")

    try:
        group_dirs = sorted(
            [d for d in root.iterdir() if d.is_dir() and d.name.lower() != "templates"],
            key=lambda d: d.name.lower(),
        )
    except Exception:
        group_dirs = []
    
    for group_dir in group_dirs:
        names = sorted([p.stem for p in group_dir.glob("*.ruleset")], key=lambda x: x.lower())
        lines.append("")
        lines.append(f"[{group_dir.name}]")
        lines.append(format_list(names, items_per_line=6) if names else "(无)")

    return "\n".join(lines)