"""Ruleset resolution: catalog building, target/source ruleset detection."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from ..utils import parse_bid_or_url
from ...parser.mr_file_parser import mr_file
from ...parser.osr_file_parser import osr_file
from ...parser.osu_file_parser import osu_file
from ...parser.ruleset_file_parser import load_ruleset_json, ruleset_file

_SCOREV2_MOD_BIT = 536870912
_MR_RANK_TO_MALODY = {0: "A", 1: "B", 2: "C", 3: "D", 4: "E"}
_NUMBER_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
_PREFIX_NUMBER_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(?:=)?([+-]?\d+(?:\.\d+)?)$")
_CMD_PREFIX_RE = re.compile(r"^/?(?:cvtscore|转换)(?:\s+|$)", re.IGNORECASE)

def _rulesets_root() -> Path:
    return Path(__file__).resolve().parents[2] / "rulesets"


def _templates_dir() -> Path:
    return _rulesets_root() / "templates"


def _is_number_token(text: str) -> bool:
    return bool(_NUMBER_RE.fullmatch(text.strip()))


def _to_float(text: str) -> Optional[float]:
    try:
        return float(text)
    except Exception:
        return None


def parse_cvtscore_cmd(cmd_text: str) -> tuple[int | None, Optional[bool], str | None, list[str]]:
    """解析 /cvtscore 首轮命令。"""
    text = (cmd_text or "").strip()

    # 支持大小写不敏感命令前缀，并兼容无参数写法（如 /CVTSCORE）。
    text = _CMD_PREFIX_RE.sub("", text, count=1).strip()

    if not text:
        return None, None, None, []

    bid: int | None = None
    force_sv2: Optional[bool] = None
    errors: list[str] = []
    ruleset_tokens: list[str] = []

    parts = [p for p in re.split(r"\s+", text) if p]
    for part in parts:
        low = part.lower()

        if low in {"-sv2", "sv2", "+sv2"}:
            if force_sv2 is False:
                errors.append("sv2 参数冲突：已指定关闭 sv2，又收到开启 sv2。")
            force_sv2 = True
            continue

        if low in {"-nosv2", "nosv2", "sv1", "-sv1"}:
            if force_sv2 is True:
                errors.append("sv2 参数冲突：已指定开启 sv2，又收到关闭 sv2。")
            force_sv2 = False
            continue

        parsed_bid, bid_err = parse_bid_or_url(part)
        if bid_err is not None:
            errors.append(bid_err)
            continue
        if parsed_bid is not None:
            bid = parsed_bid
            continue

        ruleset_tokens.append(part)

    ruleset_spec = " ".join(ruleset_tokens).strip() or None
    return bid, force_sv2, ruleset_spec, errors


def _build_ruleset_catalog() -> dict[str, Any]:
    root = _rulesets_root()
    template_dir = _templates_dir()

    templates: dict[str, str] = {}
    concrete: dict[tuple[str, str], Path] = {}
    flat_concrete: dict[str, list[tuple[str, str, Path]]] = {}

    if template_dir.exists():
        for file_path in sorted(template_dir.glob("*.ruleset")):
            name = file_path.stem
            templates[name.lower()] = name

    if root.exists():
        for group_dir in sorted(root.iterdir()):
            if not group_dir.is_dir():
                continue
            if group_dir.name.lower() == "templates":
                continue

            group = group_dir.name
            for file_path in sorted(group_dir.glob("*.ruleset")):
                name = file_path.stem
                key = (group.lower(), name.lower())
                concrete[key] = file_path
                flat_concrete.setdefault(name.lower(), []).append((group, name, file_path))

    return {
        "templates": templates,
        "concrete": concrete,
        "flat_concrete": flat_concrete,
    }


def _extract_template_diff(tokens: list[str], template_meta: dict[str, Any]) -> tuple[Optional[float], Optional[str]]:
    arg_name = str(template_meta.get("ArgumentName", "diff") or "diff").strip().lower()
    aliases: set[str] = {"diff", arg_name}

    raw_aliases = template_meta.get("Aliases")
    if isinstance(raw_aliases, list):
        for alias in raw_aliases:
            if isinstance(alias, str) and alias.strip():
                aliases.add(alias.strip().lower())

    numeric_tokens: list[float] = []

    i = 0
    while i < len(tokens):
        token = tokens[i].strip()
        low = token.lower()

        if low in aliases:
            if i + 1 >= len(tokens):
                return None, f"模板参数 {token} 缺少数值。"
            value = _to_float(tokens[i + 1])
            if value is None:
                return None, f"模板参数 {token} 后面的值不是数字：{tokens[i + 1]}"
            return value, None

        m = _PREFIX_NUMBER_RE.fullmatch(token)
        if m:
            prefix = m.group(1).lower()
            value = _to_float(m.group(2))
            if prefix in aliases and value is not None:
                return value, None

        for alias in sorted(aliases, key=len, reverse=True):
            if not low.startswith(alias):
                continue
            suffix = token[len(alias) :]
            if not suffix:
                continue
            if suffix.startswith("="):
                suffix = suffix[1:]
            value = _to_float(suffix)
            if value is None:
                return None, f"模板参数格式无效：{token}"
            return value, None

        if _is_number_token(token):
            number = _to_float(token)
            if number is not None:
                numeric_tokens.append(number)

        i += 1

    if len(numeric_tokens) == 1:
        return numeric_tokens[0], None

    if len(numeric_tokens) > 1:
        return None, "检测到多个可能的模板参数，请使用 diff<num> 或别名<num> 明确指定。"

    return None, None


def get_ruleset_quick_help_text() -> str:
    return (
        "ruleset 输入示例:\n"
        "1. 模板优先: sc diff4 或 wife3 j7\n"
        "2. 具体规则: Quaver/chill\n"
        "3. 模板显式写法: template/sc diff4\n"
        "你可以使用/omtk cvtscore查看详细用法。"
    )


def resolve_target_ruleset(spec_text: str) -> tuple[Optional[ruleset_file], Optional[dict[str, Any]], Optional[str]]:
    spec = (spec_text or "").strip()
    if not spec:
        return None, None, "目标 ruleset 不能为空。"

    catalog = _build_ruleset_catalog()
    templates: dict[str, str] = catalog["templates"]
    concrete: dict[tuple[str, str], Path] = catalog["concrete"]
    flat_concrete: dict[str, list[tuple[str, str, Path]]] = catalog["flat_concrete"]

    parts = [p for p in re.split(r"\s+", spec) if p]
    head = parts[0]
    rest = parts[1:]

    selected_template: str | None = None
    selected_concrete: tuple[str, str, Path] | None = None

    if "/" in head:
        group_raw, name_raw = head.split("/", 1)
        group = group_raw.strip()
        name = name_raw.strip()
        if not group or not name:
            return None, None, "ruleset 写法不完整，请使用 Group/Name 形式。"

        if group.lower() == "template":
            key = name.lower()
            if key not in templates:
                return None, None, f"未找到模板 ruleset: {name}"
            selected_template = templates[key]
        else:
            key = (group.lower(), name.lower())
            path = concrete.get(key)
            if path is None:
                return None, None, f"未找到具体 ruleset: {group}/{name}"
            selected_concrete = (group, name, path)

    else:
        head_low = head.lower()

        if head_low in templates:
            selected_template = templates[head_low]
        elif head_low in flat_concrete:
            matched = flat_concrete[head_low]
            if len(matched) > 1:
                candidates = ", ".join(f"{g}/{n}" for g, n, _ in matched)
                return None, None, f"规则名 {head} 存在歧义，请使用 Group/Name。可选: {candidates}"
            selected_concrete = matched[0]
        elif len(parts) >= 2:
            # 兼容不带斜杠写法：Quaver chill
            key = (head_low, parts[1].lower())
            path = concrete.get(key)
            if path is not None:
                selected_concrete = (head, parts[1], path)
                rest = parts[2:]
            else:
                return None, None, f"未识别的 ruleset: {spec}"
        else:
            return None, None, f"未识别的 ruleset: {spec}"

    if selected_template is not None:
        template_path = _templates_dir() / f"{selected_template}.ruleset"
        if not template_path.exists():
            return None, None, f"模板文件不存在: {selected_template}.ruleset"

        try:
            data = load_ruleset_json(template_path)
        except Exception as exc:
            return None, None, f"读取模板失败: {exc}"

        template_meta = data.get("Template") if isinstance(data, dict) else None
        if not isinstance(template_meta, dict):
            return None, None, f"模板 {selected_template} 缺少 Template 元信息。"

        diff_value, diff_err = _extract_template_diff(rest, template_meta)
        if diff_err:
            return None, None, diff_err

        source: tuple[Any, ...]
        if diff_value is None:
            source = ("template", selected_template)
        else:
            source = ("template", selected_template, diff_value)

        rs = ruleset_file(source)
        if rs.status != "OK":
            reason = rs.errors[0] if rs.errors else f"状态={rs.status}"
            return None, None, f"模板 ruleset 构建失败: {reason}"

        info = {
            "type": "template",
            "display": f"template/{selected_template} (diff={rs.template_context.get('diff_text') or rs.template_context.get('diff')})",
            "template": selected_template,
            "diff": rs.template_context.get("diff"),
            "diff_text": rs.template_context.get("diff_text"),
            "path": rs.template_context.get("template_path", str(template_path)),
        }
        return rs, info, None

    assert selected_concrete is not None
    group, name, path = selected_concrete
    rs = ruleset_file(path)
    if rs.status != "OK":
        reason = rs.errors[0] if rs.errors else f"状态={rs.status}"
        return None, None, f"规则文件加载失败: {group}/{name} ({reason})"

    info = {
        "type": "concrete",
        "display": f"{group}/{name}",
        "group": group,
        "name": name,
        "path": str(path),
    }
    return rs, info, None


def detect_source_ruleset(
    *,
    replay_kind: str,
    osu_obj: osu_file,
    osr_obj: osr_file,
    mr_obj: Optional[mr_file],
    force_sv2: Optional[bool],
) -> tuple[Optional[ruleset_file], Optional[dict[str, Any]], Optional[str]]:
    replay_kind_lower = replay_kind.lower()

    if replay_kind_lower == "osr":
        od_value = float(getattr(osu_obj, "od", 8.0) or 8.0)

        mod_value = int(getattr(osr_obj, "mod", 0) or 0)
        mods = getattr(osr_obj, "mods", [])
        has_sv2_mod = bool(mod_value & _SCOREV2_MOD_BIT)
        if not has_sv2_mod and isinstance(mods, list):
            has_sv2_mod = any(str(m).lower() == "scorev2" for m in mods)

        if force_sv2 is True:
            use_sv2 = True
            reason = "用户强制启用 sv2"
        elif force_sv2 is False:
            use_sv2 = False
            reason = "用户强制关闭 sv2"
        else:
            use_sv2 = has_sv2_mod
            reason = "自动检测到 ScoreV2 模组" if has_sv2_mod else "自动检测为非 ScoreV2"

        template_name = "osu-sv2" if use_sv2 else "osu"
        rs = ruleset_file(("template", template_name, od_value))
        if rs.status != "OK":
            reason_text = rs.errors[0] if rs.errors else f"状态={rs.status}"
            return None, None, f"源 ruleset 构建失败: {reason_text}"

        info = {
            "display": f"template/{template_name} (od={rs.template_context.get('diff_text') or od_value})",
            "type": "template",
            "template": template_name,
            "od": od_value,
            "reason": reason,
            "replay_kind": "osr",
        }
        return rs, info, None

    if replay_kind_lower == "mr":
        if mr_obj is None:
            return None, None, "mr 回放对象为空，无法识别源规则。"

        rank = int(getattr(mr_obj, "rank", -1))
        malody_level = _MR_RANK_TO_MALODY.get(rank)
        if malody_level is None:
            return None, None, f"无法识别 mr 判定={rank}，仅支持 0~4。"

        ruleset_path = _rulesets_root() / "Malody" / f"{malody_level}.ruleset"
        rs = ruleset_file(ruleset_path)
        if rs.status != "OK":
            reason_text = rs.errors[0] if rs.errors else f"状态={rs.status}"
            return None, None, f"源 ruleset 加载失败: {reason_text}"

        reason = f"mr 判定={rank} -> Malody/{malody_level}.ruleset"
        if force_sv2 is not None:
            reason += "；sv2 选项对 mr 回放无效，已忽略"

        info = {
            "display": f"Malody/{malody_level}",
            "type": "concrete",
            "group": "Malody",
            "name": malody_level,
            "reason": reason,
            "replay_kind": "mr",
        }
        return rs, info, None

    return None, None, f"不支持的回放类型: {replay_kind}"

