from analysis.analyzer import ISSUE_LABELS


def issues_to_actions(issues: list[dict], summary: dict) -> list[dict]:
    """Convert analysis issues into executable agent actions."""
    actions = []
    seen = set()

    for issue in issues:
        issue_type = issue.get("type")
        if issue_type == "pacing_stats":
            continue

        segment_id = issue.get("segment_id")
        key = (issue_type, segment_id, issue.get("transition_id"))
        if key in seen:
            continue
        seen.add(key)

        if issue_type == "quiet" and segment_id:
            actions.append({
                "action": "update_volume",
                "params": {"segment_id": segment_id, "volume": 1.0},
                "description": f'Boost volume on "{issue.get("clip", "clip")}"',
                "reason": issue.get("message"),
            })
        elif issue_type == "loud" and segment_id:
            actions.append({
                "action": "update_volume",
                "params": {"segment_id": segment_id, "volume": 0.7},
                "description": f'Lower volume on "{issue.get("clip", "clip")}"',
                "reason": issue.get("message"),
            })
        elif issue_type == "clipping" and segment_id:
            actions.append({
                "action": "update_volume",
                "params": {"segment_id": segment_id, "volume": 0.65},
                "description": f'Reduce clipping on "{issue.get("clip", "clip")}"',
                "reason": issue.get("message"),
            })
        elif issue_type == "low_volume" and segment_id:
            vol = issue.get("volume", 0.5)
            actions.append({
                "action": "update_volume",
                "params": {"segment_id": segment_id, "volume": min(1.0, vol + 0.3)},
                "description": f'Raise timeline volume on "{issue.get("clip", "clip")}"',
                "reason": issue.get("message"),
            })
        elif issue_type == "fast_speed" and segment_id:
            actions.append({
                "action": "update_clip_speed",
                "params": {"segment_id": segment_id, "speed": 1.0},
                "description": f'Reset speed to 1x on "{issue.get("clip", "clip")}"',
                "reason": issue.get("message"),
            })
        elif issue_type == "long_clip" and segment_id:
            actions.append({
                "action": "trim_clip",
                "params": {"segment_id": segment_id, "duration": 5_000_000},
                "description": f'Trim "{issue.get("clip", "clip")}" to ~5 seconds',
                "reason": issue.get("message"),
            })
        elif issue_type == "long_transition" and issue.get("transition_id"):
            actions.append({
                "action": "update_transition",
                "params": {"transition_id": issue["transition_id"], "duration": 500_000},
                "description": f'Shorten transition "{issue.get("clip", "")}" to 0.5s',
                "reason": issue.get("message"),
            })
        elif issue_type == "short_transition" and issue.get("transition_id"):
            actions.append({
                "action": "update_transition",
                "params": {"transition_id": issue["transition_id"], "duration": 800_000},
                "description": f'Lengthen transition "{issue.get("clip", "")}" to 0.8s',
                "reason": issue.get("message"),
            })

    return actions


def build_report_text(analysis: dict) -> str:
  score = analysis["score"]
  issues = [i for i in analysis["issues"] if i.get("type") != "pacing_stats"]

  grade = "Excellent" if score >= 85 else "Good" if score >= 70 else "Needs work" if score >= 50 else "Poor"

  lines = [
      f"## Analysis Report — Score: {score}/100 ({grade})",
      f"Analyzed {analysis['clips_analyzed']} of {analysis['total_clips']} clips with FFmpeg.",
      "",
  ]

  if not issues:
      lines.append("No major issues detected. Your project looks solid!")
      return "\n".join(lines)

  critical = [i for i in issues if i.get("severity") == "critical"]
  warnings = [i for i in issues if i.get("severity") == "warning"]
  info = [i for i in issues if i.get("severity") == "info"]

  if critical:
      lines.append("### Critical")
      for i in critical:
          lines.append(f"- {i['message']}")
      lines.append("")

  if warnings:
      lines.append("### Warnings")
      for i in warnings:
          clip = f' ({i["clip"]})' if i.get("clip") else ""
          lines.append(f"- {i['message']}{clip}")
      lines.append("")

  if info:
      lines.append("### Suggestions")
      for i in info[:8]:
          lines.append(f"- {i['message']}")
      lines.append("")

  suggestions = issues_to_actions(issues, analysis.get("summary", {}))
  if suggestions:
      lines.append(f"### {len(suggestions)} auto-fix(es) available")
      for s in suggestions:
          lines.append(f"- {s['description']}")

  return "\n".join(lines)
