import logging

import httpx

from .models import Analysis

log = logging.getLogger(__name__)

SEVERITY_ICON = {"critical": ":red_circle:", "warning": ":large_orange_circle:"}


def render(a: Analysis) -> dict:
    icon = SEVERITY_ICON.get(a.severity, ":white_circle:")
    where = " / ".join(a.labels[k] for k in ("namespace", "pod") if k in a.labels)
    header = f"{icon} *{a.alert}*" + (f"  `{where}`" if where else "")
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"{header}\n{a.summary}"}},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"likely cause: *{a.likely_cause}* | confidence: {a.confidence} | "
                    f"{a.provider}, {a.duration_s:.1f}s",
                }
            ],
        },
    ]
    if a.evidence:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Evidence*\n" + "\n".join(f"• {e}" for e in a.evidence),
                },
            }
        )
    if a.next_steps:
        steps = "\n".join(f"{i}. {s}" for i, s in enumerate(a.next_steps, 1))
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": "*Next steps*\n" + steps}}
        )
    return {"text": f"{a.alert}: {a.summary}", "blocks": blocks}


async def post(client: httpx.AsyncClient, url: str, a: Analysis) -> None:
    if not url:
        log.info("analysis for %s: %s", a.alert, a.summary)
        return
    resp = await client.post(url, json=render(a))
    if resp.status_code >= 300:
        log.error("slack returned %s: %s", resp.status_code, resp.text[:200])
