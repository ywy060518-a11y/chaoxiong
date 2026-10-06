#!/usr/bin/env python3
"""Validate declared production data and copy blocks; does not inspect media."""
import argparse
import json
import math
import re
from pathlib import Path

HEADINGS = ["全局核心要求", "前缀", "组头", "关联剧情", "出境人物", "场景", "道具", "绝对空间锚点（POS）", "影视级光线摄影", "影视级音效，声音", "对白资产", "分镜组", "完整后缀", "负面提示词"]
START, END = "【可复制执行区 START】", "【可复制执行区 END】"


def audit(data, prompt=None):
    errors = []

    def fail(message):
        errors.append(message)

    def number(value, where):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            fail(f"{where}: finite number required")
            return 0.0
        return float(value)

    def index(items, where):
        result = {}
        if not isinstance(items, list):
            fail(f"{where}: list required")
            return result
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
                fail(f"{where}: nonempty id required")
                continue
            if item["id"] in result:
                fail(f"{where}: duplicate id {item['id']}")
            result[item["id"]] = item
        return result

    if not isinstance(data, dict):
        return {"ok": False, "errors": ["manifest object required"], "media_verified": False}
    if data.get("schema_version") != 1:
        fail("schema_version must be 1")
    if data.get("delivery_scope") not in ("complete", "partial"):
        fail("delivery_scope must be complete or partial")
    platform = data.get("platform", {})
    if not isinstance(platform, dict):
        platform = {}
        fail("platform object required")
    max_duration = number(platform.get("max_duration"), "platform.max_duration")
    if max_duration <= 0 or not platform.get("evidence"):
        fail("platform: positive max_duration and current evidence required")
    source = index(data.get("source_dialogue", []), "source_dialogue")
    ledger = index(data.get("dialogue_ledger", []), "dialogue_ledger")
    parameters = index(data.get("source_parameters", []), "source_parameters")
    parameter_ledger = index(data.get("parameter_ledger", []), "parameter_ledger")
    references = index(data.get("references", []), "references")
    calls = index(data.get("calls", []), "calls")
    groups = index(data.get("groups", []), "groups")
    if not groups:
        fail("at least one video group required")
    shots = {}
    global_starts = {}
    group_cursor = 0.0
    prior_state = None
    for group_id, group in groups.items():
        route = group.get("route")
        if route not in ("A", "B", "C/A", "C/B", "D"):
            fail(f"{group_id}: supported video route required")
        base = route[-1] if isinstance(route, str) and route.startswith("C/") else route
        duration = number(group.get("duration"), f"{group_id}.duration")
        if duration <= 0:
            fail(f"{group_id}: duration must be positive")
        group_shots = group.get("shots", [])
        if not isinstance(group_shots, list) or not group_shots:
            fail(f"{group_id}: nonempty shots required")
            group_shots = []
        if base == "D" and len(group_shots) != 1:
            fail(f"{group_id}: D requires exactly one shot")
        if base == "A" and (platform.get("native_cuts") is not True or not platform.get("cuts_evidence")):
            fail(f"{group_id}: A requires verified native cuts")
        controls = group.get("controls", [])
        if isinstance(route, str) and route.startswith("C/"):
            if not controls or not isinstance(controls, list):
                fail(f"{group_id}: C requires controls")
            for control in controls if isinstance(controls, list) else []:
                if control not in platform.get("supported_controls", []):
                    fail(f"{group_id}: unsupported control {control}")
        cursor = 0.0
        for shot in group_shots:
            if not isinstance(shot, dict) or not isinstance(shot.get("id"), str):
                fail(f"{group_id}: shot object with id required")
                continue
            sid = shot["id"]
            if sid in shots:
                fail(f"duplicate shot id {sid}")
            start = number(shot.get("start"), f"{sid}.start")
            stop = number(shot.get("end"), f"{sid}.end")
            if abs(start - cursor) > 1e-6 or stop <= start:
                fail(f"{sid}: timeline gap, overlap or nonpositive duration")
            cursor = stop
            state_in, state_out = shot.get("start_state"), shot.get("end_state")
            if not isinstance(state_in, dict) or not state_in or not isinstance(state_out, dict) or not state_out:
                fail(f"{sid}: nonempty complete state snapshots required")
            if prior_state is not None and state_in != prior_state:
                boundary = shot.get("boundary", {})
                if not isinstance(boundary, dict) or boundary.get("kind") not in ("time_jump", "scene_change", "flashback", "montage", "documented_transition") or not boundary.get("reason") or not boundary.get("source_ref"):
                    fail(f"{sid}: physical state discontinuity without sourced boundary")
            prior_state = state_out
            shots[sid] = {**shot, "group_id": group_id, "duration": stop - start}
            global_starts[sid] = group_cursor + start
        if abs(cursor - duration) > 1e-6:
            fail(f"{group_id}: shots do not sum to group duration")
        group_calls = [c for c in calls.values() if c.get("group_id") == group_id]
        expected_count = len(group_shots) if base == "B" else 1
        if len(group_calls) != expected_count:
            fail(f"{group_id}: route/call count mismatch")
        group_cursor += duration

    covered = {}
    for call_id, call in calls.items():
        gid = call.get("group_id")
        if gid not in groups:
            fail(f"{call_id}: unknown group")
            continue
        route = groups[gid].get("route")
        base = route[-1] if isinstance(route, str) and route.startswith("C/") else route
        assigned = call.get("shot_ids", [])
        if not isinstance(assigned, list) or not assigned:
            fail(f"{call_id}: nonempty shot_ids required")
            assigned = []
        if base == "B" and len(assigned) != 1:
            fail(f"{call_id}: B call must contain one shot")
        if base in ("A", "D") and assigned != [s.get("id") for s in groups[gid].get("shots", [])]:
            fail(f"{call_id}: group call must cover shots in order")
        edit_duration = 0.0
        for sid in assigned:
            if sid not in shots or shots[sid].get("group_id") != gid:
                fail(f"{call_id}: unknown or foreign shot {sid}")
                continue
            covered[sid] = covered.get(sid, 0) + 1
            edit_duration += shots[sid]["duration"]
        generated = number(call.get("generation_duration"), f"{call_id}.generation_duration")
        edit_in = number(call.get("edit_in"), f"{call_id}.edit_in")
        edit_out = number(call.get("edit_out"), f"{call_id}.edit_out")
        if generated <= 0 or generated > max_duration or edit_in < 0 or edit_out > generated or edit_out <= edit_in:
            fail(f"{call_id}: invalid generation duration or trim")
        if abs((edit_out - edit_in) - edit_duration) > 1e-6:
            fail(f"{call_id}: trim does not match editorial duration")
        if call.get("start_kind") != "independent":
            fail(f"{call_id}: independent START required")
        for rid in call.get("reference_ids", []):
            ref = references.get(rid)
            if not ref or ref.get("accessible") is not True or not ref.get("binding") or not ref.get("role"):
                fail(f"{call_id}: missing or unbound reference {rid}")
                continue
            if ref.get("kind") == "tail_frame" and (ref.get("source_group") != gid or (base == "B" and ref.get("source_call") != call_id)):
                fail(f"{call_id}: forbidden tail-frame dependency {rid}")
    for sid in shots:
        if covered.get(sid) != 1:
            fail(f"{sid}: call coverage must be exactly one")

    def check_ledger(original, recorded, label):
        for key in original:
            entry = recorded.get(key)
            if not entry:
                fail(f"{label}: missing {key}")
                continue
            status = entry.get("status")
            if status not in ("Executed", "Carried", "Authorized"):
                fail(f"{label}: invalid status for {key}")
            if status == "Carried" and (data.get("delivery_scope") == "complete" or not entry.get("destination")):
                fail(f"{label}: unresolved carried item {key}")
            if status == "Authorized" and not entry.get("authorization"):
                fail(f"{label}: authorization evidence required for {key}")
            if label == "PID" and status == "Executed" and not entry.get("carrier"):
                fail(f"PID: execution carrier required for {key}")
        for key in set(recorded) - set(original):
            fail(f"{label}: unknown item {key}")

    check_ledger(source, ledger, "DIA")
    check_ledger(parameters, parameter_ledger, "PID")
    segments = data.get("audio_segments", [])
    if not isinstance(segments, list):
        fail("audio_segments list required")
        segments = []
    fragments = {}
    ordered_segments = []
    track_ranges = {}
    for seg in segments:
        if not isinstance(seg, dict):
            fail("audio segment object required")
            continue
        did, sid = seg.get("dia_id"), seg.get("shot_id")
        if did not in source or sid not in shots:
            fail("audio segment: unknown dialogue or shot")
            continue
        src = source[did]
        text = src.get("text")
        left, right = seg.get("char_start"), seg.get("char_end")
        if not isinstance(text, str) or not isinstance(left, int) or isinstance(left, bool) or not isinstance(right, int) or isinstance(right, bool) or not (0 <= left < right <= len(text)):
            fail(f"{did}: invalid source or fragment range")
            continue
        if seg.get("text") != text[left:right]:
            fail(f"{did}: source dialogue rewritten or missing words")
        if seg.get("speaker") != src.get("speaker") or seg.get("audio_owner") != src.get("speaker"):
            fail(f"{did}: wrong speaker/audio owner")
        if seg.get("lip_sync_owner") not in (None, src.get("speaker")):
            fail(f"{did}: wrong lip-sync owner")
        if seg.get("lip_sync_owner") is not None and seg.get("on_screen") is not True:
            fail(f"{did}: off-screen audio cannot own visible lip sync")
        begin = number(seg.get("start"), f"{did}.audio_start")
        finish = number(seg.get("end"), f"{did}.audio_end")
        gid = shots[sid]["group_id"]
        if begin < 0 or finish <= begin or finish > groups[gid].get("duration", 0):
            fail(f"{did}: audio outside group timeline")
        if not seg.get("track") or not seg.get("master_track"):
            fail(f"{did}: audio track and master required")
        group_offset = global_starts[sid] - shots[sid]["start"]
        absolute = group_offset + begin
        ordered_segments.append((absolute, src.get("order", 0), did))
        track_ranges.setdefault(seg.get("track"), []).append((absolute, group_offset + finish, did))
        fragments.setdefault(did, []).append((absolute, left, right))
    for did, src in source.items():
        if not isinstance(src.get("text"), str) or not isinstance(src.get("speaker"), str) or not isinstance(src.get("order"), int):
            fail(f"{did}: source text, speaker and integer order required")
        if ledger.get(did, {}).get("status") == "Executed":
            cursor = 0
            for _, left, right in sorted(fragments.get(did, [])):
                if left != cursor:
                    fail(f"{did}: duplicated, missing or reordered dialogue fragment")
                cursor = right
            if cursor != len(src.get("text", "")):
                fail(f"{did}: executed dialogue not fully covered")
        elif fragments.get(did):
            fail(f"{did}: audio segments require Executed ledger status")
    prior_order = None
    for _, order, did in sorted(ordered_segments):
        if prior_order is not None and order < prior_order:
            fail(f"{did}: source dialogue order changed")
        prior_order = order
    for track, ranges in track_ranges.items():
        prior_end = None
        for begin, finish, did in sorted(ranges):
            if prior_end is not None and begin < prior_end - 1e-6:
                fail(f"{track}: overlapping audio segments")
            prior_end = max(prior_end or finish, finish)

    if prompt is not None:
        if prompt.count(START) != prompt.count(END):
            fail("prompt: unmatched copy boundaries")
        blocks = re.findall(re.escape(START) + r"(.*?)" + re.escape(END), prompt, re.S)
        if len(blocks) != len(calls):
            fail("prompt: copy block count must equal CALL count")
        for i, block in enumerate(blocks, 1):
            markers = re.findall(r"【([^】]+)】", block)
            recognized = [m for m in markers if m in HEADINGS]
            if recognized != HEADINGS:
                fail(f"prompt block {i}: fourteen headings missing, duplicate or out of order")
            if not block.lstrip().startswith("【全局核心要求】"):
                fail(f"prompt block {i}: global requirements must be first")
            header = block.split("【组头】", 1)[1].split("【", 1)[0] if "【组头】" in block else ""
            # Chinese prose may touch an ID; only ASCII ID characters extend it.
            found_calls = [cid for cid in calls if re.search(r"(?<![A-Za-z0-9_-])" + re.escape(cid) + r"(?![A-Za-z0-9_-])", header)]
            if len(found_calls) != 1 or (i <= len(calls) and found_calls[0] != list(calls)[i - 1]):
                fail(f"prompt block {i}: CALL identity missing, duplicated or out of order")
            for h in HEADINGS:
                token = "【" + h + "】"
                if token in block:
                    field = block.split(token, 1)[1].split("【", 1)[0].strip()
                    if not field and h != "分镜组":
                        fail(f"prompt block {i}: empty field {h}")
                    if field in ("同上", "同上。", "待定", "未填写", "保持上一组"):
                        fail(f"prompt block {i}: unresolved field {h}")
            if re.search(r"\{(?:项目|模型|风格|本地开始|开始|结束|Camera|Start|DIA|当前|本镜)[^{}\n]*\}", block):
                fail(f"prompt block {i}: unfilled template placeholder")
    counts = {s: sum(v.get("status") == s for v in ledger.values()) for s in ("Executed", "Carried", "Authorized")}
    return {"ok": not errors, "errors": errors, "dialogue": {"N": len(source), "E": counts["Executed"], "C": counts["Carried"], "A": counts["Authorized"]}, "groups": len(groups), "shots": len(shots), "calls": len(calls), "editorial_duration": group_cursor, "media_verified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--prompt", type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
        result = audit(data, args.prompt.read_text(encoding="utf-8") if args.prompt else None)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        result = {"ok": False, "errors": [f"invalid input: {exc}"], "media_verified": False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
