"""Plan deterministic candidate groups from a fixed set of synthetic bundles."""

from collections import defaultdict

from ...contracts import instant, validate_bundle


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
