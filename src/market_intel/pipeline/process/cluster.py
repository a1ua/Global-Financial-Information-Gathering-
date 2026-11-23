"""Plan deterministic candidate groups from a fixed set of synthetic bundles."""

from collections import defaultdict

from ...contracts import choice, identifier, instant, record, validate_bundle
from ...contracts.candidate_snapshot import payload_sha256


def plan_synthetic_event_clusters(bundles, *, cutoff):
    """Preserve all visible versions and evidence; propose groups without merging."""
    members = []
    raws = {}
    versions = set()
    revisions = set()
    evidence_ids = set()
    exact = defaultdict(list)
    titles = defaultdict(list)
    excluded = 0
    try:
        cutoff_at = instant(cutoff, "cutoff")
        if type(bundles) is not list or len(bundles) > 1000:
            raise ValueError
        for bundle in bundles:
            validate_bundle(bundle)
            raw, event, evidence = bundle["raw"], bundle["event"], bundle["evidence"]
            if raw["is_synthetic"] is not True or raw["storage_policy"] != "full_text_fixture":
                raise ValueError
            raw_id = raw["raw_item_id"]
            event_id, version_id, version = event["event_id"], event["event_version_id"], event["version"]
            evidence_id = evidence["evidence_id"]
            revision = (event_id, version)
            if (version_id in versions or revision in revisions or evidence_id in evidence_ids
                    or raws.setdefault(raw_id, raw) != raw):
                raise ValueError
            versions.add(version_id)
            revisions.add(revision)
            evidence_ids.add(evidence_id)
            if any(instant(obj["available_at"], "available_at") > cutoff_at for obj in (raw, event, evidence)):
                excluded += 1
                continue
            members.append({
                "event_id": event_id,
                "event_version_id": version_id,
                "version": version,
                "raw_item_id": raw_id,
                "evidence_id": evidence_id,
                "relation": evidence["relation"],
            })
            scope = (event["category"], tuple(sorted(event["markets"])))
            content = raw["content_sha256"]
            exact[(*scope, raw["normalization_version"], content)].append((event_id, version_id))
            titles[(*scope, event["title"])].append((event_id, version_id, content))
    except ValueError:
        raise ValueError("synthetic_event_cluster_invalid") from None

    return {
        "schema_version": "synthetic-event-cluster-plan/0.1",
        "is_synthetic": True,
        "members": sorted(members, key=lambda member: (member["event_id"], member["version"])),
        "excluded_after_cutoff": excluded,
        "exact_duplicate_groups": sorted(
            sorted(version for _, version in group)
            for group in exact.values()
            if len({event for event, _ in group}) > 1
        ),
        "ambiguous_title_groups": sorted(
            sorted(version for _, version, _ in group)
            for group in titles.values()
            if len({event for event, _, _ in group}) > 1 and len({content for _, _, content in group}) > 1
        ),
    }


def _group_index(groups):
    return {
        version_id: number
        for number, group in enumerate(groups)
        for version_id in group
    }


def _same_group(group_ids, left, right):
    return left in group_ids and group_ids[left] == group_ids.get(right)


def _version_pair(ids, members):
    if type(ids) is not list or len(ids) != 2:
        raise ValueError
    for version_id in ids:
        identifier(version_id, "pair.event_version_id")
    left, right = sorted(ids)
    if (left not in members or right not in members
            or members[left]["event_id"] == members[right]["event_id"]):
        raise ValueError
    return left, right


def evaluate_synthetic_event_clusters(bundles, labels, *, cutoff, include_title_review=False):
    """Measure exact duplicate candidates against explicitly labeled visible pairs."""
    counts = dict.fromkeys(("true_positive", "false_positive", "false_negative", "true_negative"), 0)
    false_positive = []
    false_negative = []
    covered_false_negative = []
    different_event_candidates = 0
    seen = set()
    try:
        if type(labels) is not list or len(labels) > 1000 or type(include_title_review) is not bool:
            raise ValueError
        plan = plan_synthetic_event_clusters(bundles, cutoff=cutoff)
        members = {member["event_version_id"]: member for member in plan["members"]}
        group_ids = _group_index(plan["exact_duplicate_groups"])
        title_ids = _group_index(plan["ambiguous_title_groups"]) if include_title_review else {}
        for label in labels:
            record(label, {"event_version_ids", "same_event"}, "label")
            ids, same_event = label["event_version_ids"], label["same_event"]
            if type(same_event) is not bool:
                raise ValueError
            pair = _version_pair(ids, members)
            left, right = pair
            if pair in seen:
                raise ValueError
            seen.add(pair)
            predicted = _same_group(group_ids, left, right)
            if not predicted and _same_group(title_ids, left, right):
                if same_event:
                    covered_false_negative.append(pair)
                else:
                    different_event_candidates += 1
            if predicted == same_event:
                counts["true_positive" if same_event else "true_negative"] += 1
            elif predicted:
                counts["false_positive"] += 1
                false_positive.append(pair)
            else:
                counts["false_negative"] += 1
                false_negative.append(pair)
    except ValueError:
        raise ValueError("synthetic_event_cluster_evaluation_invalid") from None

    report = {
        "schema_version": "synthetic-event-cluster-evaluation/0.1",
        "is_synthetic": True,
        "counts": {"labeled_pairs": len(labels), **counts},
        "false_positive_pairs": [list(pair) for pair in sorted(false_positive)],
        "false_negative_pairs": [list(pair) for pair in sorted(false_negative)],
    }
    if include_title_review:
        covered_count = len(covered_false_negative)
        report["title_review"] = {
            "labeled_candidates": covered_count + different_event_candidates,
            "same_event_candidates": covered_count,
            "different_event_candidates": different_event_candidates,
            "uncovered_false_negatives": len(false_negative) - covered_count,
            "covered_false_negative_pairs": [list(pair) for pair in sorted(covered_false_negative)],
        }
    return report


def adjudicate_synthetic_event_clusters(bundles, decisions, *, cutoff):
    """Report explicit decisions for eligible title-review pairs."""
    counts = dict.fromkeys(("same_event", "different_event", "needs_more_evidence"), 0)
    adjudications = {}
    try:
        if type(decisions) is not list or len(decisions) > 1000:
            raise ValueError
        plan = plan_synthetic_event_clusters(bundles, cutoff=cutoff)
        members = {member["event_version_id"]: member for member in plan["members"]}
        bundles_by_version = {bundle["event"]["event_version_id"]: bundle for bundle in bundles}
        exact_ids = _group_index(plan["exact_duplicate_groups"])
        title_ids = _group_index(plan["ambiguous_title_groups"])
        for entry in decisions:
            record(entry, {"event_version_ids", "decision"}, "adjudication")
            decision = entry["decision"]
            choice(decision, counts, "adjudication.decision")
            pair = _version_pair(entry["event_version_ids"], members)
            left, right = pair
            if (pair in adjudications or not _same_group(title_ids, left, right)
                    or _same_group(exact_ids, left, right)):
                raise ValueError
            counts[decision] += 1
            adjudications[pair] = {
                "decision": decision,
                "members": [
                    {**members[version_id], "bundle_sha256": payload_sha256(bundles_by_version[version_id])}
                    for version_id in pair
                ],
            }
    except ValueError:
        raise ValueError("synthetic_event_cluster_adjudication_invalid") from None

    return {
        "schema_version": "synthetic-event-cluster-adjudication/0.1",
        "is_synthetic": True,
        "cutoff": cutoff,
        "counts": {"decisions": len(decisions), **counts},
        "adjudications": [adjudications[pair] for pair in sorted(adjudications)],
    }
