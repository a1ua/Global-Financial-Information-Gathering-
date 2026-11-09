from copy import deepcopy
from itertools import permutations
import unittest

from market_intel.pipeline.candidates import select_candidates


CUTOFF = "2026-11-09T12:00:00Z"


def candidate(suffix, stamp="2026-11-09T11:00:00Z", **changes):
    result = {"candidate_id": "candidate_" + suffix, "available_at": stamp,
              "title": "Synthetic " + suffix, "is_synthetic": True}
    result.update(changes)
    return result


def batch(*candidates):
    return {"schema_version": "synthetic-candidate-batch/0.1", "candidates": list(candidates)}


class CandidateSelectionTests(unittest.TestCase):
    def test_counts_distinguish_duplicates_future_and_limited(self):
        first = candidate("a")
        result = select_candidates(batch(first, deepcopy(first), candidate("b"),
                                         candidate("future", "2026-11-09T12:00:01Z")), CUTOFF, 1)
        self.assertEqual({key: result[key] for key in (
            "input_count", "unique_count", "duplicate_count", "eligible_count", "future_count",
            "selected_count", "limited_count")}, {
                "input_count": 4, "unique_count": 3, "duplicate_count": 1, "eligible_count": 2,
                "future_count": 1, "selected_count": 1, "limited_count": 1})
        self.assertEqual(result["selected"], [first])

    def test_default_limit_zero_and_hundred_boundaries(self):
        value = batch(*(candidate(str(i)) for i in range(101)))
        self.assertEqual(select_candidates(value, CUTOFF)["selected_count"], 5)
        self.assertEqual(select_candidates(value, CUTOFF, 0)["selected_count"], 0)
        self.assertEqual(select_candidates(value, CUTOFF, 100)["selected_count"], 100)
        for invalid in (-1, 101, True, False, 1.0, "5", None):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "^candidate_limit_invalid$"):
                select_candidates(value, CUTOFF, invalid)

    def test_empty_batch_and_raw_count_limit_include_duplicates(self):
        self.assertEqual(select_candidates(batch(), CUTOFF)["selected"], [])
        repeated = [candidate("a") for _ in range(1000)]
        self.assertEqual(select_candidates(batch(*repeated), CUTOFF)["duplicate_count"], 999)
        with self.assertRaisesRegex(ValueError, "^candidate_batch_invalid$"):
            select_candidates(batch(*repeated, candidate("a")), CUTOFF)

    def test_chronological_sort_uses_instants_and_id_tiebreaker(self):
        value = batch(candidate("z", "2026-11-09T11:00:00Z"),
                      candidate("later", "2026-11-09T11:00:00.1Z"),
                      candidate("a", "2026-11-09T11:00:00.000000Z"))
        result = select_candidates(value, CUTOFF)
        self.assertEqual([row["candidate_id"] for row in result["selected"]],
                         ["candidate_a", "candidate_z", "candidate_later"])
        cutoff = "2026-11-09T11:00:00.000000Z"
        self.assertEqual(select_candidates(value, cutoff)["selected_count"], 2)
        self.assertEqual(select_candidates(value, cutoff)["cutoff"], cutoff)

    def test_permutation_does_not_change_output_or_input(self):
        rows = [candidate("c"), candidate("a"), candidate("b")]
        expected = select_candidates(batch(*rows), CUTOFF, 2)
        for perm in permutations(rows):
            value = batch(*perm)
            before = deepcopy(value)
            self.assertEqual(select_candidates(value, CUTOFF, 2), expected)
            self.assertEqual(value, before)
        value = batch(candidate("a"))
        selected = select_candidates(value, CUTOFF)["selected"]
        selected[0]["title"] = "changed result"
        self.assertEqual(value["candidates"][0]["title"], "Synthetic a")

    def test_all_records_validated_even_when_future_or_beyond_zero_limit(self):
        for invalid in (candidate("later", "2026-11-10T00:00:00Z", is_synthetic=False),
                        candidate("bad", title=""), candidate("bad", unexpected="private text")):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "^candidate_invalid$"):
                select_candidates(batch(candidate("a"), invalid), CUTOFF, 0)

    def test_conflicting_id_rejected_even_for_equivalent_instant_text(self):
        for changed in (candidate("a", title="different"),
                        candidate("a", "2026-11-09T11:00:00.000000Z")):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, "^candidate_conflict$"):
                select_candidates(batch(candidate("a"), changed), CUTOFF, 0)

    def test_utf8_title_limit_and_invalid_unicode(self):
        accepted = "中" * 1365 + "x"
        self.assertEqual(len(accepted.encode()), 4096)
        self.assertEqual(select_candidates(batch(candidate("a", title=accepted)), CUTOFF)["selected_count"], 1)
        for title in (accepted + "x", "\ud800", " \n\t", 3, None):
            with self.subTest(title=repr(title)), self.assertRaisesRegex(ValueError, "^candidate_invalid$"):
                select_candidates(batch(candidate("a", title=title)), CUTOFF)

    def test_timestamp_validation_for_cutoff_and_records(self):
        for invalid in ("2026-11-09T12:00:00+00:00", "2026-02-30T00:00:00Z",
                        "2026-11-09", "2026-11-09T12:00:00.0000001Z", True, None):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "^candidate_timestamp_invalid$"):
                select_candidates(batch(), invalid)
            with self.subTest(record=invalid), self.assertRaisesRegex(ValueError, "^candidate_timestamp_invalid$"):
                select_candidates(batch(candidate("a", invalid)), CUTOFF)

    def test_strict_fields_tags_and_ascii_identifier(self):
        for change in ({"is_synthetic": 1}, {"is_synthetic": False}, {"candidate_id": "candidate_"},
                       {"candidate_id": "candidate_中"}, {"candidate_id": "candidate_" + "a" * 97},
                       {"candidate_id": "candidate_a\n"}, {"title": float("nan")}, {"extra": None}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "^candidate_invalid$"):
                select_candidates(batch(candidate("a", **change)), CUTOFF)
        valid = candidate("A_0-" + "a" * 92)
        self.assertEqual(select_candidates(batch(valid), CUTOFF)["selected_count"], 1)
        missing = candidate("a")
        missing.pop("title")
        with self.assertRaisesRegex(ValueError, "^candidate_invalid$"):
            select_candidates(batch(missing), CUTOFF)

    def test_strict_batch_shape(self):
        for value in (None, [], {}, {"schema_version": "other", "candidates": []},
                      {"schema_version": "synthetic-candidate-batch/0.1", "candidates": ()},
                      {**batch(), "extra": "private"}, batch(None)):
            with self.subTest(value=value), self.assertRaises(ValueError) as caught:
                select_candidates(value, CUTOFF)
            self.assertNotIn("private", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
