"""음소 단위 비교(app/phonemes.py). 모델·네트워크 없음.

실행: cd backend && python -m unittest tests.test_phonemes
"""
from __future__ import annotations

import gzip
import hashlib
import unittest

from app import phonemes as P


class LexiconTests(unittest.TestCase):
    def test_lexicon_hash_matches_readme(self):
        raw = gzip.decompress(P.LEXICON_PATH.read_bytes())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), P.LEXICON_SHA256)
        self.assertEqual(len(raw), 3618488)

    def test_stress_is_stripped_and_variants_kept(self):
        self.assertEqual(P.pronounce("seat"), (("S", "IY", "T"),))
        self.assertEqual(P.pronounce("read"), (("R", "EH", "D"), ("R", "IY", "D")))
        self.assertEqual(P.pronounce("Window"), (("W", "IH", "N", "D", "OW"),))   # 대소문자 무시
        self.assertEqual(P.pronounce("i’m"), P.pronounce("i'm"))                      # 둥근 따옴표

    def test_comment_tail_is_ignored(self):
        # 사전 원문 'aalborg AO1 L B AO0 R G # place, danish'
        self.assertEqual(P.pronounce("aalborg")[0], ("AO", "L", "B", "AO", "R", "G"))
        self.assertTrue(all("#" not in p and "," not in p for v in P.pronounce("aalborg") for p in v))

    def test_unknown_word_is_not_invented(self):
        self.assertEqual(P.pronounce("zzqxv"), ())
        self.assertEqual(P.pronounce(""), ())

    def test_every_phone_is_in_inventory_and_has_ipa(self):
        seen = {p for v in P.lexicon().values() for p in v.replace("|", " ").split()}
        self.assertEqual(seen, set(P.PHONES))
        self.assertEqual(set(P.ARPABET_IPA), set(P.PHONES))
        self.assertEqual(len(P.PHONES), 39)


class AlignTests(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(P.counts(P.align(["S", "IY", "T"], ["S", "IY", "T"])), {"eq": 3, "sub": 0, "del": 0, "ins": 0})
        self.assertEqual(P.per(["S", "IY", "T"], ["S", "IY", "T"]), 0)

    def test_substitution_deletion_insertion(self):
        ops = P.align(["S", "IY", "T"], ["S", "IH", "T"])
        self.assertEqual([(o["op"], o["ref"], o["hyp"]) for o in ops],
                         [("eq", "S", "S"), ("sub", "IY", "IH"), ("eq", "T", "T")])
        self.assertEqual(P.counts(P.align(["S", "IY", "T"], ["S", "T"]))["del"], 1)
        self.assertEqual(P.counts(P.align(["S", "T"], ["S", "IY", "T"]))["ins"], 1)

    def test_vowel_consonant_prefers_del_ins_over_cross_class_sub(self):
        # 모음↔자음 대치(1.6)보다 삭제+삽입(2)이 비싸므로 여전히 대치지만, 같은 부류 대치가 있으면 그쪽을 고른다
        ops = P.align(["B", "AE", "D"], ["B", "EH", "D"])
        self.assertEqual([o["op"] for o in ops], ["eq", "sub", "eq"])

    def test_per_definition(self):
        self.assertIsNone(P.per([], ["S"]))
        self.assertAlmostEqual(P.per(["S", "IY", "T"], []), 1.0)
        self.assertAlmostEqual(P.per(["S", "IY", "T"], ["S", "IY", "T", "S"]), 1 / 3)

    def test_deterministic(self):
        a = P.align(list("ABCD"), list("ACBD"))
        for _ in range(5):
            self.assertEqual(P.align(list("ABCD"), list("ACBD")), a)


class CompareTests(unittest.TestCase):
    def test_same_sentence_is_zero_per(self):
        r = P.compare("Here is my return ticket.", "here is my return ticket")
        self.assertEqual(r["per"], 0)
        self.assertTrue(all(w["status"] == "ok" for w in r["words"]))
        self.assertEqual(r["basis"], "transcript")

    def test_vowel_substitution_is_attributed_to_the_word(self):
        r = P.compare("Can I have a window seat, please?", "Can I have a window sit please")
        bad = [w for w in r["words"] if w["status"] != "ok"]
        self.assertEqual([w["word"] for w in bad], ["seat"])
        self.assertEqual([(o["op"], o["ref"], o["hyp"]) for o in bad[0]["ops"] if o["op"] != "eq"], [("sub", "IY", "IH")])
        self.assertEqual(bad[0]["heard"], "sit")
        self.assertEqual(r["counts"], {"ref_phones": 20, "sub": 1, "del": 0, "ins": 0})
        self.assertAlmostEqual(r["per"], 0.05)

    def test_dropped_syllable_is_deletion(self):
        # 발표 슬라이드 9번 실측 예: sightseeing → sighting
        r = P.compare("I am here for sightseeing.", "I am here for sighting.")
        w = next(x for x in r["words"] if x["word"] == "sightseeing")
        self.assertEqual(w["status"], "diff")
        self.assertEqual([(o["op"], o["ref"]) for o in w["ops"] if o["op"] != "eq"], [("del", "S"), ("del", "IY")])

    def test_missing_word_deletes_all_its_phones(self):
        r = P.compare("a window seat please", "a window please")
        w = next(x for x in r["words"] if x["word"] == "seat")
        self.assertEqual(w["status"], "missing")
        self.assertEqual(r["counts"]["del"], 3)

    def test_extra_word_is_listed_not_counted_as_target_error(self):
        r = P.compare("a window seat", "a window seat now")
        self.assertEqual([e["word"] for e in r["extra"]], ["now"])
        self.assertEqual(r["per"], 0)

    def test_unknown_word_is_excluded_not_guessed(self):
        r = P.compare("a table at Zzqxv please", "a table at zzqxv please")
        self.assertEqual(r["unknown_words"], ["zzqxv"])
        self.assertEqual(r["counts"]["ref_phones"], sum(len(P.pronounce(w)[0]) for w in ("a", "table", "at", "please")))

    def test_unknown_in_replaced_span_is_not_compared(self):
        r = P.compare("a seat please", "a zzqxv please")
        w = next(x for x in r["words"] if x["word"] == "seat")
        self.assertEqual(w["status"], "unknown")
        self.assertNotIn("ops", w)

    def test_variant_choice_minimises_errors(self):
        # 'read' 는 R EH D / R IY D 두 발음 — 'red' 로 들리면 R EH D 를 골라 오류 0
        r = P.compare("read", "red")
        self.assertEqual(r["per"], 0)
        self.assertEqual(r["words"][0]["phones"], ["R", "EH", "D"])

    def test_empty_inputs(self):
        self.assertIsNone(P.compare("", "")["per"])
        r = P.compare("seat", "")
        self.assertEqual(r["words"][0]["status"], "missing")
        self.assertEqual(r["per"], 1.0)

    def test_hyphenated_word_joins_only_when_in_lexicon(self):
        self.assertEqual(P.tokens("Could I get the Wi-Fi password?"), ["could", "i", "get", "the", "wifi", "password"])
        self.assertEqual(P.compare("the Wi-Fi password", "the wifi password")["per"], 0)
        self.assertEqual(P.tokens("Ess-a-Bagel"), ["ess", "a", "bagel"])          # 'essabagel' 은 사전에 없다 → 나눈다

    def test_matches_speech_compare_tokenisation(self):
        from app.speech_compare import words
        target = "I'd like a table for two, please — near the window?"
        self.assertEqual([w["word"] for w in P.compare(target, target)["words"]], words(target))


class ConsensusTests(unittest.TestCase):
    def test_agreeing_transcripts_keep_the_diff(self):
        r = P.consensus("a window seat", "a window sit", "a window sit")
        self.assertEqual([w["status"] for w in r["words"]], ["ok", "ok", "diff"])
        self.assertEqual(r["counts"]["sub"], 1)

    def test_disagreeing_transcripts_are_unsure(self):
        r = P.consensus("a window seat", "a window sit", "a window seat")
        self.assertEqual(r["unsure_words"], ["seat"])
        self.assertNotIn("ops", r["words"][2])
        self.assertEqual(r["per"], 0)

    def test_ops_carry_ipa(self):
        w = P.consensus("seat", "sit", "sit")["words"][0]
        self.assertEqual([(o["ref_ipa"], o["hyp_ipa"]) for o in w["ops"] if o["op"] == "sub"], [("i", "ɪ")])


class ComparePhonesTests(unittest.TestCase):
    """실제 소리에서 인식한 음소열을 붙일 자리. 인식기 출력은 ARPAbet 로 맞춰 넣는다."""

    def test_acoustic_substitution(self):
        r = P.compare_phones("seat please", ["S", "IH", "T", "P", "L", "IY", "Z"])
        self.assertEqual(r["basis"], "acoustic")
        self.assertEqual([w["status"] for w in r["words"]], ["diff", "ok"])
        self.assertAlmostEqual(r["per"], 1 / 7, places=4)   # 응답은 소수 넷째 자리로 반올림

    def test_whole_word_missing(self):
        r = P.compare_phones("seat please", ["P", "L", "IY", "Z"])
        self.assertEqual(r["words"][0]["status"], "missing")

    def test_unknown_target_word_blocks_comparison(self):
        r = P.compare_phones("zzqxv please", ["P", "L", "IY", "Z"])
        self.assertIsNone(r["per"])
        self.assertEqual(r["unknown_words"], ["zzqxv"])

    def test_non_inventory_symbols_are_dropped(self):
        r = P.compare_phones("seat", ["S", "IY", "T", "<pad>", "|"])
        self.assertEqual(r["per"], 0)


if __name__ == "__main__":
    unittest.main()
