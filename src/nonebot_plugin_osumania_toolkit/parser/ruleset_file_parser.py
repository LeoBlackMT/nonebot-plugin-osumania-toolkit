from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nonebot.log import logger


_MAX_TIMING_WINDOW_ABS = 500.0
_ALLOWED_DECIMAL_PLACES = {"TWO", "THREE", "FOUR"}
_ALLOWED_NOTE_PRIORITIES = {"OsuMania", "Etterna"}
_OSUMANIA_LN_WINDOW_KEYS = {
    "Window320",
    "Window300",
    "Window200",
    "Window100",
    "Window50",
    "Window0",
    "WindowOverhold200",
    "WindowOverhold100",
}

_TEMPLATE_EXPR_RE = re.compile(r"\{\{\s*(.*?)\s*\}\}")
_TEMPLATE_ALLOWED_FUNCS = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "int": int,
    "float": float,
}


@dataclass(slots=True)
class ValidationResult:
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class RulesetValidationError(ValueError):
    pass


def _strip_jsonc_comments(content: str) -> str:
    """Remove // and /* */ comments while keeping JSON string content intact."""
    out: list[str] = []
    i = 0
    in_string = False
    escaped = False
    block_comment = False
    line_comment = False

    while i < len(content):
        ch = content[i]
        nxt = content[i + 1] if i + 1 < len(content) else ""

        if block_comment:
            if ch == "*" and nxt == "/":
                block_comment = False
                i += 2
            else:
                i += 1
            continue

        if line_comment:
            if ch == "\n":
                line_comment = False
                out.append(ch)
            i += 1
            continue

        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue

        if ch == "/" and nxt == "/":
            line_comment = True
            i += 2
            continue

        if ch == "/" and nxt == "*":
            block_comment = True
            i += 2
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_color(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, list) or len(value) != 4:
        errors.append(f"{path} 必须是包含 4 个整数的数组 (A,R,G,B)。")
        return
    for i, channel in enumerate(value):
        if not isinstance(channel, int):
            errors.append(f"{path}[{i}] 必须是整数，当前类型为 {type(channel).__name__}。")
            continue
        if channel < 0 or channel > 255:
            errors.append(f"{path}[{i}] 必须在 [0, 255] 范围内，当前值为 {channel}。")


def _validate_timing_window(
    value: Any,
    path: str,
    errors: list[str],
    *,
    allow_null: bool,
) -> tuple[float, float] | None:
    if value is None:
        if allow_null:
            return None
        errors.append(f"{path} 不能为 null。")
        return None

    if not isinstance(value, list) or len(value) != 2:
        errors.append(f"{path} 必须是 [early, late] 或 null。")
        return None

    early, late = value[0], value[1]
    if not _is_number(early) or not _is_number(late):
        errors.append(f"{path} 的两个值都必须是数字。")
        return None

    early_f = float(early)
    late_f = float(late)

    if abs(early_f) > _MAX_TIMING_WINDOW_ABS or abs(late_f) > _MAX_TIMING_WINDOW_ABS:
        errors.append(
            f"{path} 的绝对值不能超过 {_MAX_TIMING_WINDOW_ABS} ms。"
        )

    if early_f > late_f:
        errors.append(f"{path} 必须满足 early <= late。")

    return (early_f, late_f)


def load_ruleset_json(file_path: str | Path) -> dict[str, Any]:
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"未找到规则文件: {path}")

    raw = path.read_text(encoding="utf-8-sig")
    cleaned = _strip_jsonc_comments(raw)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RulesetValidationError(f"JSON 格式无效: {exc}") from exc

    if not isinstance(data, dict):
        raise RulesetValidationError("规则文件根节点必须是对象。")

    return data


def _validate_single_req(
    req: dict[str, Any], path: str, judgement_count: int, errors: list[str]
) -> None:
    """Validate a single requirement dict. Supports any combination of ComboBreaksAtMost/JudgementAtMost/Accuracy (AND logic)."""
    has_combo = "ComboBreaksAtMost" in req
    has_judgement = "JudgementAtMost" in req
    has_accuracy = "Accuracy" in req

    if not (has_combo or has_judgement or has_accuracy):
        errors.append(
            f"{path} 必须包含 ComboBreaksAtMost、JudgementAtMost 或 Accuracy 中至少一个。"
        )
        return

    if has_combo:
        combo_limit = req.get("ComboBreaksAtMost")
        if not isinstance(combo_limit, int) or combo_limit < 0:
            errors.append(f"{path}.ComboBreaksAtMost 必须是 >= 0 的整数。")

    if has_judgement:
        value = req.get("JudgementAtMost")
        if not isinstance(value, list) or len(value) != 2:
            errors.append(f"{path}.JudgementAtMost 必须是 [judgement_index, count]。")
            return
        j_idx, count = value[0], value[1]
        if not isinstance(j_idx, int) or not isinstance(count, int):
            errors.append(f"{path}.JudgementAtMost 的两个值都必须是整数。")
            return
        if j_idx < 0 or (judgement_count > 0 and j_idx >= judgement_count):
            errors.append(f"{path}.JudgementAtMost 的判定索引超出 Judgements 范围。")
        if count < 0:
            errors.append(f"{path}.JudgementAtMost 的数量必须 >= 0。")

    if has_accuracy:
        acc = req.get("Accuracy")
        if not _is_number(acc):
            errors.append(f"{path}.Accuracy 必须是 0.0~1.0 之间的数字。")
        else:
            acc_f = float(acc)
            if acc_f < 0.0 or acc_f > 1.0:
                errors.append(f"{path}.Accuracy 必须在 0.0~1.0 范围内。")


def _validate_requirement(
    requirement: Any, path: str, judgement_count: int, errors: list[str]
) -> None:
    """Validate a Requirement field. Supports dict or list of dicts (AND logic)."""
    if isinstance(requirement, list):
        if not requirement:
            errors.append(f"{path} 数组不能为空。")
            return
        for idx, req in enumerate(requirement):
            sub_path = f"{path}[{idx}]"
            if not isinstance(req, dict):
                errors.append(f"{sub_path} 必须是对象。")
                continue
            _validate_single_req(req, sub_path, judgement_count, errors)
    elif isinstance(requirement, dict):
        _validate_single_req(requirement, path, judgement_count, errors)
    else:
        errors.append(f"{path} 必须是对象或对象数组。")


def validate_ruleset_data(data: dict[str, Any]) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    required_top = {
        "Name",
        "Judgements",
        "Lamps",
        "Grades",
        "HitMechanics",
        "HoldMechanics",
        "Accuracy",
        "Formatting",
    }
    missing_top = [key for key in sorted(required_top) if key not in data]
    if missing_top:
        errors.append(f"缺少必填顶层字段: {', '.join(missing_top)}")
        return ValidationResult(False, errors, warnings)

    name = data.get("Name")
    if not isinstance(name, str) or not name.strip():
        errors.append("Name 必须是非空字符串。")

    description = data.get("Description")
    if description is not None and not isinstance(description, str):
        errors.append("Description 存在时必须是字符串。")

    judgements = data.get("Judgements")
    judgement_count = 0
    timed_widths: list[float] = []
    has_timed_judgements = False

    if not isinstance(judgements, list) or not judgements:
        errors.append("Judgements 必须是非空数组。")
    else:
        judgement_count = len(judgements)
        for idx, judgement in enumerate(judgements):
            path = f"Judgements[{idx}]"
            if not isinstance(judgement, dict):
                errors.append(f"{path} 必须是对象。")
                continue

            j_name = judgement.get("Name")
            if not isinstance(j_name, str) or not j_name.strip():
                errors.append(f"{path}.Name 必须是非空字符串。")

            _validate_color(judgement.get("Color"), f"{path}.Color", errors)

            breaks_combo = judgement.get("BreaksCombo")
            if not isinstance(breaks_combo, bool):
                errors.append(f"{path}.BreaksCombo 必须是布尔值。")

            tw = _validate_timing_window(
                judgement.get("TimingWindows"),
                f"{path}.TimingWindows",
                errors,
                allow_null=True,
            )
            if tw is not None:
                has_timed_judgements = True
                timed_widths.append(tw[1] - tw[0])

        if timed_widths:
            for i in range(1, len(timed_widths)):
                if timed_widths[i] < timed_widths[i - 1]:
                    errors.append(
                        "带 TimingWindows 的 Judgements 应按从严格到宽松排序。"
                    )
                    break

        if not has_timed_judgements:
            warnings.append("Judgements 中未找到显式 TimingWindows。")

    lamps = data.get("Lamps")
    if not isinstance(lamps, list):
        errors.append("Lamps 必须是数组。")
    else:
        for idx, lamp in enumerate(lamps):
            path = f"Lamps[{idx}]"
            if not isinstance(lamp, dict):
                errors.append(f"{path} 必须是对象。")
                continue

            l_name = lamp.get("Name")
            if not isinstance(l_name, str) or not l_name.strip():
                errors.append(f"{path}.Name 必须是非空字符串。")

            _validate_color(lamp.get("Color"), f"{path}.Color", errors)

            _validate_requirement(
                lamp.get("Requirement"), f"{path}.Requirement", judgement_count, errors
            )

    grades = data.get("Grades")
    if not isinstance(grades, list) or not grades:
        errors.append("Grades 必须是非空数组。")
    else:
        prev_acc: float | None = None
        for idx, grade in enumerate(grades):
            path = f"Grades[{idx}]"
            if not isinstance(grade, dict):
                errors.append(f"{path} 必须是对象。")
                continue

            g_name = grade.get("Name")
            if not isinstance(g_name, str) or not g_name.strip():
                errors.append(f"{path}.Name 必须是非空字符串。")

            has_req = "Requirement" in grade
            has_acc = "Accuracy" in grade

            if has_req and has_acc:
                errors.append(f"{path} 不能同时包含 Accuracy 和 Requirement。")

            if has_req:
                _validate_color(grade.get("Color"), f"{path}.Color", errors)
                _validate_requirement(
                    grade.get("Requirement"), f"{path}.Requirement", judgement_count, errors
                )
            elif has_acc:
                acc = grade.get("Accuracy")
                if not _is_number(acc):
                    errors.append(f"{path}.Accuracy 必须是数字。")
                else:
                    acc_f = float(acc)
                    if prev_acc is not None and acc_f <= prev_acc:
                        errors.append("Grades.Accuracy 必须严格递增。")
                    prev_acc = acc_f
                _validate_color(grade.get("Color"), f"{path}.Color", errors)
            else:
                errors.append(f"{path} 必须包含 Accuracy 或 Requirement。")

    hit_mechanics = data.get("HitMechanics")
    if not isinstance(hit_mechanics, dict):
        errors.append("HitMechanics 必须是对象。")
    else:
        note_priority = hit_mechanics.get("NotePriority")
        if isinstance(note_priority, str):
            if note_priority not in _ALLOWED_NOTE_PRIORITIES:
                errors.append(
                    "HitMechanics.NotePriority 为字符串时必须是 OsuMania 或 Etterna。"
                )
        elif isinstance(note_priority, dict):
            if set(note_priority.keys()) != {"Interlude"}:
                errors.append(
                    "HitMechanics.NotePriority 为对象时必须是 {\"Interlude\": number}。"
                )
            else:
                threshold = note_priority.get("Interlude")
                if not _is_number(threshold) or float(threshold) < 0:
                    errors.append(
                        "HitMechanics.NotePriority.Interlude 必须是 >= 0 的数字。"
                    )
        else:
            errors.append(
                "HitMechanics.NotePriority 必须是 OsuMania/Etterna 字符串，或 Interlude 对象。"
            )

        ghost_tap = hit_mechanics.get("GhostTapJudgement")
        if ghost_tap is not None:
            if not isinstance(ghost_tap, int):
                errors.append("HitMechanics.GhostTapJudgement 必须是整数或 null。")
            elif judgement_count > 0 and (ghost_tap < 0 or ghost_tap >= judgement_count):
                errors.append("HitMechanics.GhostTapJudgement 索引超出范围。")

    accuracy = data.get("Accuracy")
    uses_points_per_judgement = False
    uses_wife_curve = False

    if not isinstance(accuracy, dict):
        errors.append("Accuracy 必须是对象。")
    else:
        has_points = "PointsPerJudgement" in accuracy
        has_wife = "WifeCurve" in accuracy
        if has_points == has_wife:
            errors.append(
                "Accuracy 必须且只能包含 PointsPerJudgement 或 WifeCurve 其中之一。"
            )
        elif has_points:
            uses_points_per_judgement = True
            points = accuracy.get("PointsPerJudgement")
            if not isinstance(points, list) or not points:
                errors.append("Accuracy.PointsPerJudgement 必须是非空数组。")
            else:
                if judgement_count > 0 and len(points) != judgement_count:
                    errors.append(
                        "Accuracy.PointsPerJudgement 长度必须与 Judgements 长度一致。"
                    )
                for idx, point in enumerate(points):
                    if not _is_number(point):
                        errors.append(
                            f"Accuracy.PointsPerJudgement[{idx}] 必须是数字。"
                        )
        else:
            uses_wife_curve = True
            wife_curve = accuracy.get("WifeCurve")
            if not isinstance(wife_curve, int):
                errors.append("Accuracy.WifeCurve 必须是整数。")
            elif wife_curve < 2 or wife_curve > 9:
                warnings.append("Accuracy.WifeCurve 通常建议在 [2, 9] 范围内。")

    hold_mechanics = data.get("HoldMechanics")
    if not isinstance(hold_mechanics, dict):
        errors.append("HoldMechanics 必须是对象。")
    else:
        if len(hold_mechanics) != 1:
            errors.append("HoldMechanics 必须且只能包含一个变体键。")
        else:
            variant, payload = next(iter(hold_mechanics.items()))

            if variant == "OnlyRequireHold":
                if not _is_number(payload) or float(payload) < 0:
                    errors.append("HoldMechanics.OnlyRequireHold 必须是 >= 0 的数字。")

            elif variant == "JudgeReleasesSeparately":
                if not isinstance(payload, list) or len(payload) != 2:
                    errors.append(
                        "HoldMechanics.JudgeReleasesSeparately 必须是 [windows_array, judgement_if_overheld]。"
                    )
                else:
                    windows_array, overheld_idx = payload
                    if not isinstance(windows_array, list):
                        errors.append(
                            "HoldMechanics.JudgeReleasesSeparately[0] 必须是窗口数组。"
                        )
                    else:
                        if judgement_count > 0 and len(windows_array) != judgement_count:
                            errors.append(
                                "HoldMechanics.JudgeReleasesSeparately 的窗口数组长度必须与 Judgements 一致。"
                            )
                        for w_idx, window in enumerate(windows_array):
                            _validate_timing_window(
                                window,
                                f"HoldMechanics.JudgeReleasesSeparately[0][{w_idx}]",
                                errors,
                                allow_null=True,
                            )
                    if not isinstance(overheld_idx, int):
                        errors.append(
                            "HoldMechanics.JudgeReleasesSeparately[1] 必须是整数判定索引。"
                        )
                    elif judgement_count > 0 and (
                        overheld_idx < 0 or overheld_idx >= judgement_count
                    ):
                        errors.append(
                            "HoldMechanics.JudgeReleasesSeparately 的 overheld 索引超出范围。"
                        )

            elif variant == "OnlyJudgeReleases":
                if not isinstance(payload, int):
                    errors.append("HoldMechanics.OnlyJudgeReleases 必须是整数索引。")
                elif judgement_count > 0 and (payload < 0 or payload >= judgement_count):
                    errors.append("HoldMechanics.OnlyJudgeReleases 索引超出范围。")

            elif variant == "CombineHeadAndTail":
                if not isinstance(payload, dict) or len(payload) != 1:
                    errors.append(
                        "HoldMechanics.CombineHeadAndTail 必须且只能包含一个子变体。"
                    )
                else:
                    sub_variant, sub_payload = next(iter(payload.items()))

                    if sub_variant == "OsuMania":
                        if not isinstance(sub_payload, dict):
                            errors.append(
                                "HoldMechanics.CombineHeadAndTail.OsuMania 必须是对象。"
                            )
                        else:
                            missing = sorted(_OSUMANIA_LN_WINDOW_KEYS - set(sub_payload.keys()))
                            if missing:
                                errors.append(
                                    "HoldMechanics.CombineHeadAndTail.OsuMania 缺少键: "
                                    + ", ".join(missing)
                                )
                            for key in _OSUMANIA_LN_WINDOW_KEYS:
                                if key not in sub_payload:
                                    continue
                                value = sub_payload[key]
                                if not _is_number(value) or float(value) < 0:
                                    errors.append(
                                        f"HoldMechanics.CombineHeadAndTail.OsuMania.{key} 必须是 >= 0 的数字。"
                                    )
                                elif abs(float(value)) > _MAX_TIMING_WINDOW_ABS:
                                    errors.append(
                                        f"HoldMechanics.CombineHeadAndTail.OsuMania.{key} 不能超过 {_MAX_TIMING_WINDOW_ABS} ms。"
                                    )

                        if judgement_count != 6:
                            errors.append(
                                "CombineHeadAndTail.OsuMania 要求 Judgements 长度必须恰好为 6。"
                            )
                        if not uses_points_per_judgement:
                            errors.append(
                                "CombineHeadAndTail.OsuMania 要求必须使用 Accuracy.PointsPerJudgement。"
                            )

                    elif sub_variant == "HeadJudgementOr":
                        if not isinstance(sub_payload, list) or len(sub_payload) != 4:
                            errors.append(
                                "HoldMechanics.CombineHeadAndTail.HeadJudgementOr 必须是 [early, late, dropped_idx, overheld_idx]。"
                            )
                        else:
                            early, late, dropped_idx, overheld_idx = sub_payload
                            if not _is_number(early) or not _is_number(late):
                                errors.append(
                                    "HoldMechanics.CombineHeadAndTail.HeadJudgementOr 的 early/late 必须是数字。"
                                )
                            else:
                                if float(early) > float(late):
                                    errors.append(
                                        "HoldMechanics.CombineHeadAndTail.HeadJudgementOr 要求 early <= late。"
                                    )
                                if (
                                    abs(float(early)) > _MAX_TIMING_WINDOW_ABS
                                    or abs(float(late)) > _MAX_TIMING_WINDOW_ABS
                                ):
                                    errors.append(
                                        "HoldMechanics.CombineHeadAndTail.HeadJudgementOr 的值超过最大时间窗口限制。"
                                    )

                            for idx_name, idx_value in (
                                ("dropped_idx", dropped_idx),
                                ("overheld_idx", overheld_idx),
                            ):
                                if not isinstance(idx_value, int):
                                    errors.append(
                                        f"HoldMechanics.CombineHeadAndTail.HeadJudgementOr 的 {idx_name} 必须是整数。"
                                    )
                                elif judgement_count > 0 and (
                                    idx_value < 0 or idx_value >= judgement_count
                                ):
                                    errors.append(
                                        "HoldMechanics.CombineHeadAndTail.HeadJudgementOr 索引超出范围。"
                                    )
                    else:
                        errors.append(
                            "HoldMechanics.CombineHeadAndTail 的子变体必须是 OsuMania 或 HeadJudgementOr。"
                        )

            else:
                errors.append(
                    "HoldMechanics 变体必须是 OnlyRequireHold、JudgeReleasesSeparately、"
                    "OnlyJudgeReleases、CombineHeadAndTail 之一。"
                )

    formatting = data.get("Formatting")
    if not isinstance(formatting, dict):
        errors.append("Formatting 必须是对象。")
    else:
        decimal_places = formatting.get("DecimalPlaces")
        if not isinstance(decimal_places, str):
            errors.append("Formatting.DecimalPlaces 必须是字符串。")
        elif decimal_places not in _ALLOWED_DECIMAL_PLACES:
            errors.append(
                "Formatting.DecimalPlaces 必须是 TWO、THREE、FOUR 之一。"
            )

    if uses_wife_curve:
        ghost_tap = (
            data.get("HitMechanics", {}).get("GhostTapJudgement")
            if isinstance(data.get("HitMechanics"), dict)
            else None
        )
        if ghost_tap is not None:
            warnings.append(
                "GhostTapJudgement 通常与 PointsPerJudgement 精度规则搭配使用。"
            )

    return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=warnings)


def is_ruleset_data_valid(data: dict[str, Any]) -> bool:
    return validate_ruleset_data(data).is_valid


def _format_template_number(value: float) -> str:
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _evaluate_template_expression(expr: str, env: dict[str, Any]) -> Any:
    try:
        return eval(expr, {"__builtins__": {}}, {**_TEMPLATE_ALLOWED_FUNCS, **env})
    except Exception as exc:
        raise RulesetValidationError(f"模板表达式计算失败: {expr!r} ({exc})") from exc


def _render_template_string(value: str, env: dict[str, Any]) -> Any:
    matches = list(_TEMPLATE_EXPR_RE.finditer(value))
    if not matches:
        return value

    if len(matches) == 1 and matches[0].span() == (0, len(value)):
        expr = matches[0].group(1)
        return _evaluate_template_expression(expr, env)

    def _replace(match: re.Match[str]) -> str:
        result = _evaluate_template_expression(match.group(1), env)
        if isinstance(result, float):
            return _format_template_number(result)
        return str(result)

    return _TEMPLATE_EXPR_RE.sub(_replace, value)


def _render_template_node(node: Any, env: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        return {str(key): _render_template_node(value, env) for key, value in node.items()}
    if isinstance(node, list):
        return [_render_template_node(item, env) for item in node]
    if isinstance(node, str):
        return _render_template_string(node, env)
    return node


def _build_template_env(template_meta: dict[str, Any], diff_value: Any) -> dict[str, Any]:
    arg_name = str(template_meta.get("ArgumentName", "diff") or "diff")
    default_value = template_meta.get("Default", 5.0)

    source_value = default_value if diff_value is None else diff_value
    try:
        diff = float(source_value)
    except Exception as exc:
        raise RulesetValidationError(f"模板参数 diff 不是数字: {source_value!r}") from exc

    if _is_number(template_meta.get("Min")):
        diff = max(diff, float(template_meta["Min"]))
    if _is_number(template_meta.get("Max")):
        diff = min(diff, float(template_meta["Max"]))

    precision = template_meta.get("Precision", 3)
    if isinstance(precision, int) and precision >= 0:
        diff = round(diff, precision)

    env: dict[str, Any] = {
        arg_name: diff,
        "diff": diff,
        "diff_text": _format_template_number(diff),
    }

    aliases = template_meta.get("Aliases")
    if isinstance(aliases, list):
        for alias in aliases:
            if isinstance(alias, str) and alias.strip():
                env[alias.strip()] = diff

    variables = template_meta.get("Variables", {})
    if isinstance(variables, dict) and variables:
        pending = {str(k): v for k, v in variables.items()}
        for _ in range(len(pending) + 2):
            if not pending:
                break

            unresolved: dict[str, Any] = {}
            progress = False
            for key, expr in pending.items():
                if isinstance(expr, str):
                    try:
                        env[key] = _evaluate_template_expression(expr, env)
                    except RulesetValidationError as exc:
                        if "name" in str(exc).lower():
                            unresolved[key] = expr
                            continue
                        raise
                else:
                    env[key] = expr
                progress = True

            if not unresolved:
                pending = {}
                break

            if not progress:
                unresolved_keys = ", ".join(sorted(unresolved.keys()))
                raise RulesetValidationError(
                    f"模板变量无法解析: {unresolved_keys}"
                )
            pending = unresolved

    return env


def _get_template_ruleset_path(template_name: str) -> Path:
    package_root = Path(__file__).resolve().parents[1]
    template_dir = package_root / "rulesets" / "templates"
    return template_dir / f"{template_name}.ruleset"


def build_ruleset_from_template(
    template_name: str,
    diff_value: Any = None,
) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    template_path = _get_template_ruleset_path(template_name)
    data = load_ruleset_json(template_path)

    template_meta = data.get("Template")
    template_ruleset = data.get("Ruleset")

    if isinstance(template_meta, dict) and isinstance(template_ruleset, dict):
        env = _build_template_env(template_meta, diff_value)
        rendered = _render_template_node(template_ruleset, env)
        if not isinstance(rendered, dict):
            raise RulesetValidationError("模板渲染结果不是对象。")
        return rendered, template_path, env

    # 兼容旧式静态模板文件（不含 Template/Ruleset 包装）。
    if diff_value is not None:
        logger.warning(
            f"模板 {template_name} 不包含公式定义，已忽略 diff={diff_value!r} 并按静态 ruleset 读取。"
        )
    return data, template_path, {"diff": diff_value}


def _parse_template_source(source: Any) -> tuple[str, Any] | None:
    if not isinstance(source, (tuple, list)) or not source:
        return None

    mode = str(source[0]).strip().lower()
    if mode != "template":
        return None

    if len(source) < 2:
        raise RulesetValidationError("模板来源至少需要提供模板名。")

    template_name = str(source[1]).strip()
    if not template_name:
        raise RulesetValidationError("模板名不能为空。")

    diff_value = source[2] if len(source) >= 3 else None
    return template_name, diff_value


class ruleset_file:
    """规则文件解析器：严格校验并输出明确状态/错误信息。"""

    def __init__(self, file_path: str | Path | tuple[Any, ...] | list[Any]):
        self.source = file_path
        self.file_path = str(file_path)
        self.status = "init"
        self.raw_data: dict[str, Any] = {}
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.validation = ValidationResult(False)
        self.name = ""
        self.description = ""
        self.template_context: dict[str, Any] = {}
        self.process()

    def process(self) -> None:
        template_source: tuple[str, Any] | None = None
        try:
            template_source = _parse_template_source(self.source)
        except RulesetValidationError as exc:
            self.status = "TemplateError"
            self.errors = [str(exc)]
            logger.warning(self.errors[0])
            return

        if template_source is not None:
            template_name, diff_value = template_source
            try:
                self.raw_data, template_path, env = build_ruleset_from_template(
                    template_name,
                    diff_value,
                )
                self.template_context = {
                    "mode": "template",
                    "template": template_name,
                    "diff": env.get("diff", diff_value),
                    "diff_text": env.get("diff_text", ""),
                    "template_path": str(template_path),
                }
                diff_text = env.get("diff_text", "default")
                self.file_path = f"template://{template_name}/{diff_text}"
            except FileNotFoundError as exc:
                self.status = "FileNotFound"
                self.errors = [str(exc)]
                logger.warning(self.errors[0])
                return
            except RulesetValidationError as exc:
                self.status = "TemplateError"
                self.errors = [str(exc)]
                logger.warning(self.errors[0])
                return
            except Exception as exc:
                self.status = "ParseError"
                self.errors = [str(exc)]
                logger.error(f"构建模板 ruleset 失败 {template_name}: {exc}")
                return
        else:
            self.file_path = str(self.source)
            try:
                self.raw_data = load_ruleset_json(self.file_path)
            except FileNotFoundError as exc:
                self.status = "FileNotFound"
                self.errors = [str(exc)]
                logger.warning(self.errors[0])
                return
            except RulesetValidationError as exc:
                self.status = "JsonError"
                self.errors = [str(exc)]
                logger.warning(self.errors[0])
                return
            except Exception as exc:
                self.status = "ParseError"
                self.errors = [str(exc)]
                logger.error(f"解析规则文件失败 {self.file_path}: {exc}")
                return

        try:
            if not isinstance(self.raw_data, dict):
                raise RulesetValidationError("规则文件根节点必须是对象。")
        except RulesetValidationError as exc:
            self.status = "InvalidRuleset"
            self.errors = [str(exc)]
            return

        self.validation = validate_ruleset_data(self.raw_data)
        self.errors = list(self.validation.errors)
        self.warnings = list(self.validation.warnings)
        self.name = str(self.raw_data.get("Name", ""))
        self.description = str(self.raw_data.get("Description", ""))

        if self.validation.is_valid:
            self.status = "OK"
        else:
            self.status = "InvalidRuleset"

    def is_valid(self) -> bool:
        return self.status == "OK"

    def get_data(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "file_path": self.file_path,
            "name": self.name,
            "description": self.description,
            "validation": {
                "is_valid": self.validation.is_valid,
                "errors": list(self.errors),
                "warnings": list(self.warnings),
            },
            "template_context": dict(self.template_context),
            "ruleset": self.raw_data,
        }

    def get_summary(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "name": self.name,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }
