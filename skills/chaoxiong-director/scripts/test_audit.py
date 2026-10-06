#!/usr/bin/env python3
"""Adversarial regression tests for production omissions and continuity errors."""
import copy
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("audit_production", Path(__file__).with_name("audit_production.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture():
    state = {"CHAR-01": {"pos": "desk west", "right_hand": "empty", "left_hand": "empty"}, "PROP-01": {"owner": "table", "state": "intact"}, "LOC-01": {"window": "east", "door": "south"}}
    end = copy.deepcopy(state)
    end["CHAR-01"]["right_hand"] = "PROP-01"
    end["PROP-01"]["owner"] = "CHAR-01.right"
    source = [{"id": "DIA-01", "order": 1, "speaker": "CHAR-01", "text": "原件留下。"}]
    data = {
        "schema_version": 1, "delivery_scope": "complete",
        "platform": {"max_duration": 30, "evidence": "test fixture; no real platform claim", "native_cuts": True, "cuts_evidence": "declared input fixture", "supported_controls": ["first_frame"]},
        "source_dialogue": source, "dialogue_ledger": [{"id": "DIA-01", "status": "Executed"}],
        "source_parameters": [{"id": "PID-01", "category": "props", "value": "one intact original"}],
        "parameter_ledger": [{"id": "PID-01", "status": "Executed", "carrier": "CALL-01 text"}],
        "references": [{"id": "REF-01", "role": "identity", "binding": "fixture://identity", "accessible": True}],
        "groups": [{"id": "G001", "route": "B", "duration": 6,
            "shots": [{"id": "S001", "start": 0, "end": 3, "start_state": copy.deepcopy(state), "end_state": copy.deepcopy(end)},
                      {"id": "S002", "start": 3, "end": 6, "start_state": copy.deepcopy(end), "end_state": copy.deepcopy(end)}]}],
        "calls": [{"id": "CALL-01", "group_id": "G001", "shot_ids": ["S001"], "generation_duration": 4, "edit_in": 0.5, "edit_out": 3.5, "start_kind": "independent", "reference_ids": ["REF-01"]},
                  {"id": "CALL-02", "group_id": "G001", "shot_ids": ["S002"], "generation_duration": 4, "edit_in": 0.5, "edit_out": 3.5, "start_kind": "independent", "reference_ids": ["REF-01"]}],
        "audio_segments": [{"dia_id": "DIA-01", "shot_id": "S001", "char_start": 0, "char_end": 2, "text": "原件", "speaker": "CHAR-01", "audio_owner": "CHAR-01", "lip_sync_owner": "CHAR-01", "on_screen": True, "start": 1, "end": 3, "track": "AUD-01", "master_track": "MASTER-01"},
                           {"dia_id": "DIA-01", "shot_id": "S002", "char_start": 2, "char_end": 5, "text": "留下。", "speaker": "CHAR-01", "audio_owner": "CHAR-01", "lip_sync_owner": None, "on_screen": False, "start": 3, "end": 4.5, "track": "AUD-01", "master_track": "MASTER-01"}]
    }
    blocks = []
    for cid in ("CALL-01", "CALL-02"):
        fields = [f"【{h}】" + (f"{cid}；G001；本CALL3秒剪辑。" if h == "组头" else "确定执行内容。") for h in module.HEADINGS]
        blocks.append(module.START + "\n" + "\n".join(fields) + "\n" + module.END)
    return data, "\n\n".join(blocks)


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.data, self.prompt = fixture()

    def rejected(self, phrase):
        result = module.audit(self.data, self.prompt)
        self.assertFalse(result["ok"], result)
        self.assertTrue(any(phrase in e for e in result["errors"]), result)

    def test_split_dialogue_and_protected_generation_valid(self):
        result = module.audit(self.data, self.prompt)
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["media_verified"])
        self.assertEqual(result["dialogue"], {"N": 1, "E": 1, "C": 0, "A": 0})

    def test_omitted_source_line(self):
        self.data["source_dialogue"].append({"id": "DIA-02", "order": 2, "speaker": "CHAR-01", "text": "不能烧。"})
        self.rejected("missing DIA-02")

    def test_rewritten_word(self):
        self.data["audio_segments"][1]["text"] = "保留。"
        self.rejected("rewritten")

    def test_duplicate_fragment(self):
        self.data["audio_segments"].append(copy.deepcopy(self.data["audio_segments"][0]))
        self.rejected("duplicated")

    def test_missing_fragment(self):
        self.data["audio_segments"].pop()
        self.rejected("not fully covered")

    def test_wrong_speaker(self):
        self.data["audio_segments"][0]["audio_owner"] = "CHAR-02"
        self.rejected("wrong speaker")

    def test_listener_given_lip_sync(self):
        self.data["audio_segments"][1]["lip_sync_owner"] = "CHAR-02"
        self.rejected("wrong lip-sync")

    def test_offscreen_lip_owner(self):
        self.data["audio_segments"][1]["lip_sync_owner"] = "CHAR-01"
        self.rejected("off-screen")

    def test_state_hand_swap(self):
        self.data["groups"][0]["shots"][1]["start_state"]["CHAR-01"]["right_hand"] = "empty"
        self.rejected("state discontinuity")

    def test_sourced_scene_change_valid(self):
        shot = self.data["groups"][0]["shots"][1]
        shot["start_state"]["LOC-01"]["door"] = "north"
        shot["boundary"] = {"kind": "scene_change", "reason": "source moves to second room", "source_ref": "scene-02"}
        self.assertTrue(module.audit(self.data, self.prompt)["ok"])

    def test_timeline_gap(self):
        self.data["groups"][0]["shots"][1]["start"] = 3.1
        self.rejected("timeline gap")

    def test_invalid_trim(self):
        self.data["calls"][0]["edit_out"] = 4.5
        self.rejected("invalid generation")

    def test_a_call_count_mismatch(self):
        self.data["groups"][0]["route"] = "A"
        self.rejected("call count mismatch")

    def test_a_valid(self):
        self.data["groups"][0]["route"] = "A"
        self.data["calls"] = [{"id": "CALL-01", "group_id": "G001", "shot_ids": ["S001", "S002"], "generation_duration": 6, "edit_in": 0, "edit_out": 6, "start_kind": "independent", "reference_ids": ["REF-01"]}]
        self.prompt = self.prompt.split(module.END, 1)[0] + module.END
        self.assertTrue(module.audit(self.data, self.prompt)["ok"])

    def test_a_without_verified_cuts(self):
        self.data["groups"][0]["route"] = "A"
        self.data["platform"]["native_cuts"] = False
        self.rejected("verified native cuts")

    def test_d_30s_one_shot_valid(self):
        self.data["source_dialogue"] = []
        self.data["dialogue_ledger"] = []
        self.data["audio_segments"] = []
        self.data["groups"][0]["route"] = "D"
        self.data["groups"][0]["duration"] = 30
        self.data["groups"][0]["shots"] = [self.data["groups"][0]["shots"][0]]
        self.data["groups"][0]["shots"][0]["end"] = 30
        self.data["calls"] = [self.data["calls"][0]]
        self.data["calls"][0].update(generation_duration=30, edit_in=0, edit_out=30)
        self.prompt = self.prompt.split(module.END, 1)[0] + module.END
        self.assertTrue(module.audit(self.data, self.prompt)["ok"])

    def test_d_cannot_contain_multiple_shots(self):
        self.data["groups"][0]["route"] = "D"
        self.rejected("exactly one shot")

    def test_unsupported_control(self):
        self.data["groups"][0].update(route="C/B", controls=["depth"])
        self.rejected("unsupported control")

    def test_supported_control_valid(self):
        self.data["groups"][0].update(route="C/B", controls=["first_frame"])
        self.assertTrue(module.audit(self.data, self.prompt)["ok"])

    def test_unbound_reference(self):
        self.data["references"][0]["accessible"] = False
        self.rejected("unbound reference")

    def test_tail_frame_from_other_group(self):
        self.data["references"][0].update(kind="tail_frame", source_group="G000", source_call="OLD-CALL")
        self.rejected("forbidden tail-frame")

    def test_tail_frame_from_other_b_call(self):
        self.data["references"][0].update(kind="tail_frame", source_group="G001", source_call="CALL-01")
        self.rejected("forbidden tail-frame")

    def test_unresolved_carried_in_final(self):
        self.data["dialogue_ledger"][0].update(status="Carried", destination="G002")
        self.rejected("unresolved carried")

    def test_authorization_without_evidence(self):
        self.data["dialogue_ledger"][0]["status"] = "Authorized"
        self.rejected("authorization evidence")

    def test_missing_parameter(self):
        self.data["parameter_ledger"] = []
        self.rejected("PID: missing")

    def test_field_order(self):
        self.prompt = self.prompt.replace("【全局核心要求】确定执行内容。\n【前缀】确定执行内容。", "【前缀】确定执行内容。\n【全局核心要求】确定执行内容。")
        self.rejected("out of order")

    def test_missing_field(self):
        self.prompt = self.prompt.replace("【道具】确定执行内容。\n", "")
        self.rejected("headings missing")

    def test_repeated_call_card(self):
        self.prompt = self.prompt.replace("CALL-02", "CALL-01")
        self.rejected("CALL identity")

    def test_call_id_adjacent_chinese(self):
        self.prompt = self.prompt.replace("【组头】CALL-01；", "【组头】唯一调用CALL-01本组；")
        result = module.audit(self.data, self.prompt)
        self.assertTrue(result["ok"], result)

    def test_call_id_embedded_in_another_id(self):
        original = self.prompt
        for longer_id in ("XCALL-01", "CALL-01A", "CALL-01_02", "CALL-01-02"):
            with self.subTest(longer_id=longer_id):
                self.prompt = original.replace("【组头】CALL-01；", f"【组头】{longer_id}；")
                self.rejected("CALL identity")

    def test_unmatched_copy_boundary(self):
        self.prompt = self.prompt.replace(module.END, "", 1)
        self.rejected("unmatched")

    def test_nonfinite_duration(self):
        self.data["calls"][0]["generation_duration"] = float("nan")
        self.rejected("finite number")


if __name__ == "__main__":
    unittest.main(verbosity=2)
