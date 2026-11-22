"""Render a validated synthetic weekly summary for readers."""

_COUNT_COLUMNS = ("total", "calculated", "pending", "unavailable")


def _row(*cells):
    return "| " + " | ".join(map(str, cells)) + " |"


def render_synthetic_week_markdown(summary):
    """Render the output of summarize_synthetic_week without recounting samples."""
    counts = summary["counts"]
    lines = [
        "# Synthetic weekly review",
        "",
        f"Receipt week starting {summary['week_monday']} (Asia/Shanghai)",
        "",
        "Counts describe synthetic evaluation results, with one result per prediction.",
        "",
        _row("Total", "Calculated", "Pending", "Unavailable"),
        _row("---", "---", "---", "---"),
        _row(*(counts[key] for key in _COUNT_COLUMNS)),
        "",
        "## Evaluation protocols",
        "",
        "Mean CAR uses calculated results within each protocol and is expressed as a ratio.",
        "",
    ]
    protocols = summary["protocols"]
    if not protocols:
        return "\n".join([*lines, "No evaluation protocols."])

    lines.extend([
        _row("Protocol SHA-256", "Total", "Calculated", "Pending", "Unavailable", "Mean CAR"),
        _row("---", "---", "---", "---", "---", "---"),
    ])
    for protocol in protocols:
        counts = protocol["counts"]
        mean = protocol["mean_car"]
        lines.append(_row(
            f"`{protocol['evaluation_protocol_sha256']}`",
            *(counts[key] for key in _COUNT_COLUMNS),
            mean if mean is not None else "N/A",
        ))
    return "\n".join(lines)
