#!/usr/bin/env python3
"""
World Cup SMS MVP.

The script watches match changes, sends an email with subject WC_ALERT,
and an iPhone Shortcut can forward that email body as an SMS.
"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
import sys
import time
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent
STATE_PATH = BASE_DIR / "state.json"
DEFAULT_ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
DEFAULT_ESPN_SUMMARY_URL_TEMPLATE = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event={event_id}"
DEFAULT_EVENT_TYPES = "goal"
DEFAULT_SEND_DELAY_SECONDS = 12
EVENT_TEST_ALERTS = [
    "GOAL Portugal: Cristiano Ronaldo | Portugal 1-0 Congo DR | 23'",
    "GOAL Congo DR: Cedric Bakambu | Portugal 1-1 Congo DR | 66'",
    "Cancelled | Portugal 1-1 Congo DR",
    "Fulltime | Portugal 2-1 Congo DR",
]


@dataclass(frozen=True)
class MatchSnapshot:
    match_id: str
    home: str
    away: str
    home_score: int
    away_score: int
    status_state: str
    status_name: str
    status_detail: str


@dataclass(frozen=True)
class Alert:
    key: str
    text: str


@dataclass(frozen=True)
class MatchEvent:
    match_id: str
    event_id: str
    kind: str
    minute: str
    team: str
    player: str
    description: str


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"matches": {}, "sent_alerts": []}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def send_email(subject: str, body: str, dry_run: bool = False) -> None:
    if dry_run:
        print(f"[DRY RUN EMAIL]\nSubject: {subject}\n\n{body}\n")
        return

    required = [
        "WC_SMS_SMTP_HOST",
        "WC_SMS_SMTP_PORT",
        "WC_SMS_SMTP_USER",
        "WC_SMS_SMTP_PASSWORD",
        "WC_SMS_EMAIL_TO",
    ]
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise RuntimeError(f"Missing email config: {', '.join(missing)}")

    host = os.environ["WC_SMS_SMTP_HOST"]
    port = int(os.environ["WC_SMS_SMTP_PORT"])
    user = os.environ["WC_SMS_SMTP_USER"]
    password = os.environ["WC_SMS_SMTP_PASSWORD"]
    sender = os.environ.get("WC_SMS_EMAIL_FROM", user)
    recipient = os.environ["WC_SMS_EMAIL_TO"]

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls(context=context)
        server.login(user, password)
        server.send_message(msg)


def send_alert_messages(alert_texts: list[str], dry_run: bool, send_delay: float) -> int:
    for index, alert_text in enumerate(alert_texts):
        send_email("WC_ALERT", alert_text, dry_run=dry_run)
        print(f"Sent alert: {alert_text}")
        if index < len(alert_texts) - 1 and send_delay > 0:
            time.sleep(send_delay)
    return len(alert_texts)


def fetch_json(url: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 WorldCupSMSMVP/1.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_score(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def get_espn_snapshots(url: str) -> list[MatchSnapshot]:
    data = fetch_json(url)
    snapshots: list[MatchSnapshot] = []

    for event in data.get("events", []):
        competitions = event.get("competitions") or []
        if not competitions:
            continue

        competition = competitions[0]
        competitors = competition.get("competitors") or []
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue

        status_type = (competition.get("status") or {}).get("type") or {}
        snapshots.append(
            MatchSnapshot(
                match_id=str(event.get("id") or competition.get("id")),
                home=home.get("team", {}).get("shortDisplayName") or home.get("team", {}).get("displayName") or "Home",
                away=away.get("team", {}).get("shortDisplayName") or away.get("team", {}).get("displayName") or "Away",
                home_score=parse_score(home.get("score")),
                away_score=parse_score(away.get("score")),
                status_state=str(status_type.get("state") or ""),
                status_name=str(status_type.get("name") or ""),
                status_detail=str(status_type.get("detail") or status_type.get("shortDetail") or ""),
            )
        )

    return snapshots


def get_json_url_snapshots(url: str) -> list[MatchSnapshot]:
    data = fetch_json(url)
    raw_matches = data.get("matches", data if isinstance(data, list) else [])
    snapshots: list[MatchSnapshot] = []

    for item in raw_matches:
        snapshots.append(
            MatchSnapshot(
                match_id=str(item.get("id") or item.get("match_id")),
                home=str(item.get("home") or item.get("home_team") or "Home"),
                away=str(item.get("away") or item.get("away_team") or "Away"),
                home_score=parse_score(item.get("home_score")),
                away_score=parse_score(item.get("away_score")),
                status_state=str(item.get("status_state") or ""),
                status_name=str(item.get("status_name") or ""),
                status_detail=str(item.get("status_detail") or ""),
            )
        )

    return snapshots


def first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def nested_text(value: Any, *keys: str) -> str:
    if not isinstance(value, dict):
        return ""
    for key in keys:
        text = value.get(key)
        if isinstance(text, str) and text.strip():
            return text.strip()
    return ""


def extract_player_name(item: dict[str, Any]) -> str:
    athlete = item.get("athlete")
    if isinstance(athlete, dict):
        name = nested_text(athlete, "displayName", "shortName", "fullName", "name")
        if name:
            return name

    for key in ("participants", "athletes", "players"):
        people = item.get(key)
        if not isinstance(people, list):
            continue
        for person in people:
            if not isinstance(person, dict):
                continue
            person_athlete = person.get("athlete") if isinstance(person.get("athlete"), dict) else person
            name = nested_text(person_athlete, "displayName", "shortName", "fullName", "name")
            if name:
                return name

    return ""


def classify_event(type_text: str, description: str) -> str:
    haystack = f"{type_text} {description}".lower()
    if "var" in haystack or "video assistant" in haystack or "review" in haystack:
        return "var"
    if "red card" in haystack or "sent off" in haystack:
        return "red_card"
    if "yellow card" in haystack or "booking" in haystack:
        return "yellow_card"
    if "substitution" in haystack or "substitute" in haystack:
        return "substitution"
    if "penalty" in haystack and any(word in haystack for word in ("miss", "saved", "score", "goal")):
        return "penalty"
    if "goal" in haystack or "scores" in haystack:
        return "goal"
    return ""


def format_event_alert(event: MatchEvent, snapshot: MatchSnapshot) -> str:
    scoreline = f"{snapshot.home} {snapshot.home_score}-{snapshot.away_score} {snapshot.away}"
    minute = f" | {event.minute}" if event.minute else ""
    player = f": {event.player}" if event.player else ""
    team = f" {event.team}" if event.team else ""

    labels = {
        "goal": "GOAL",
        "red_card": "RED CARD",
        "yellow_card": "YELLOW CARD",
        "substitution": "SUB",
        "penalty": "PENALTY",
        "var": "VAR",
    }
    label = labels.get(event.kind, event.kind.upper())

    if event.kind in {"var", "substitution"} and event.description:
        return f"{label}{team} | {event.description} | {scoreline}{minute}"

    return f"{label}{team}{player} | {scoreline}{minute}"


def parse_espn_match_events(match_id: str, data: dict[str, Any]) -> list[MatchEvent]:
    competitions = data.get("competitions") or []
    competition = competitions[0] if competitions else {}
    raw_events = (
        competition.get("details")
        or data.get("details")
        or data.get("plays")
        or data.get("keyEvents")
        or []
    )
    events: list[MatchEvent] = []

    for index, item in enumerate(raw_events):
        if not isinstance(item, dict):
            continue

        event_type = item.get("type")
        type_text = nested_text(event_type, "text", "name", "abbreviation") if isinstance(event_type, dict) else str(event_type or "")
        description = first_text(
            item.get("text"),
            item.get("description"),
            item.get("displayName"),
            item.get("headline"),
            type_text,
        )
        kind = classify_event(type_text, description)
        if not kind:
            continue

        clock = item.get("clock")
        minute = nested_text(clock, "displayValue") if isinstance(clock, dict) else first_text(item.get("time"), item.get("minute"))
        team = nested_text(item.get("team"), "shortDisplayName", "displayName", "name") if isinstance(item.get("team"), dict) else ""
        player = extract_player_name(item)
        event_id = first_text(item.get("id"), item.get("sequenceNumber"), item.get("sequence"), f"{kind}:{minute}:{team}:{player}:{index}")

        events.append(
            MatchEvent(
                match_id=match_id,
                event_id=event_id,
                kind=kind,
                minute=minute,
                team=team,
                player=player,
                description=description,
            )
        )

    return events


def get_espn_event_alerts(snapshot: MatchSnapshot, enabled_types: set[str]) -> list[Alert]:
    template = os.environ.get("WC_SMS_ESPN_SUMMARY_URL_TEMPLATE") or DEFAULT_ESPN_SUMMARY_URL_TEMPLATE
    data = fetch_json(template.format(event_id=snapshot.match_id))
    alerts: list[Alert] = []

    for event in parse_espn_match_events(snapshot.match_id, data):
        if event.kind not in enabled_types:
            continue
        text = format_event_alert(event, snapshot)
        alerts.append(Alert(f"{snapshot.match_id}:event:{event.kind}:{event.event_id}", text))

    return alerts


def get_latest_goal_scorer(match_id: str, team_name: str, expected_count: int = 0) -> str:
    """Return the scorer for team_name's goal number ``expected_count``.

    The ESPN summary feed often lags the scoreboard, so a goal that just
    changed the score may not be listed in the match details yet. We retry a
    few times to let the feed catch up, and only return a name once the
    scoring team actually has that many goals on record. If we can't confirm
    the scorer we return "" rather than guess -- a missing name is far better
    than attributing the other team's previous scorer.
    """
    template = os.environ.get("WC_SMS_ESPN_SUMMARY_URL_TEMPLATE") or DEFAULT_ESPN_SUMMARY_URL_TEMPLATE
    target = team_name.strip().lower()

    for attempt in range(6):
        try:
            data = fetch_json(template.format(event_id=match_id))
        except (URLError, TimeoutError, json.JSONDecodeError, OSError):
            data = {}

        goals = [event for event in parse_espn_match_events(match_id, data) if event.kind == "goal"]
        team_goals = [
            g
            for g in goals
            if target and g.team.strip() and (g.team.strip().lower() in target or target in g.team.strip().lower())
        ]

        if expected_count > 0:
            if len(team_goals) >= expected_count:
                return team_goals[expected_count - 1].player
        elif team_goals:
            return team_goals[-1].player

        if attempt < 5:
            time.sleep(3)

    return ""


def get_demo_snapshots() -> list[MatchSnapshot]:
    state = load_state()
    already_demoed = state.get("demo_counter", 0)
    home_score = 1 if already_demoed == 0 else 2
    state["demo_counter"] = already_demoed + 1
    save_state(state)

    return [
        MatchSnapshot(
            match_id="demo-final",
            home="Argentina",
            away="Morocco",
            home_score=home_score,
            away_score=0,
            status_state="in",
            status_name="STATUS_IN_PROGRESS",
            status_detail="23'",
        )
    ]


def snapshot_to_state(snapshot: MatchSnapshot) -> dict[str, Any]:
    return {
        "home": snapshot.home,
        "away": snapshot.away,
        "home_score": snapshot.home_score,
        "away_score": snapshot.away_score,
        "status_state": snapshot.status_state,
        "status_name": snapshot.status_name,
        "status_detail": snapshot.status_detail,
    }


def build_alerts(
    previous: dict[str, Any] | None,
    current: MatchSnapshot,
    notify_existing: bool,
    scorer_lookup: Any = None,
) -> list[Alert]:
    scoreline = f"{current.home} {current.home_score}-{current.away_score} {current.away}"
    detail = f" | {current.status_detail}" if current.status_detail else ""

    if notify_existing:
        signature = f"{current.home_score}-{current.away_score}:{current.status_name}:{current.status_detail}"
        return [Alert(f"{current.match_id}:existing:{signature}", f"WC | {scoreline}{detail}")]

    if previous is None:
        return []

    alerts: list[Alert] = []

    prev_home_score = parse_score(previous.get("home_score"))
    prev_away_score = parse_score(previous.get("away_score"))
    prev_status_name = str(previous.get("status_name") or "")

    if current.home_score > prev_home_score:
        scorer = scorer_lookup(current, True) if scorer_lookup else ""
        who = f": {scorer}" if scorer else ""
        alerts.append(Alert(f"{current.match_id}:home_goal:{current.home_score}", f"GOAL {current.home}{who} | {scoreline}{detail}"))

    if current.away_score > prev_away_score:
        scorer = scorer_lookup(current, False) if scorer_lookup else ""
        who = f": {scorer}" if scorer else ""
        alerts.append(Alert(f"{current.match_id}:away_goal:{current.away_score}", f"GOAL {current.away}{who} | {scoreline}{detail}"))

    status_changed = prev_status_name != current.status_name
    status_text = current.status_name.upper()
    if status_changed and ("CANCEL" in status_text or "POSTPONED" in status_text or "ABANDON" in status_text):
        alerts.append(Alert(f"{current.match_id}:cancelled", f"Cancelled | {scoreline}{detail}"))

    if status_changed and current.status_state == "post" and "CANCEL" not in status_text and "POSTPONED" not in status_text and "ABANDON" not in status_text:
        alerts.append(Alert(f"{current.match_id}:fulltime", f"Fulltime | {scoreline}"))

    return alerts


def poll(provider: str, dry_run: bool, notify_existing: bool, event_alerts: bool, event_types: set[str], send_delay: float) -> int:
    state = load_state()
    matches_state = state.setdefault("matches", {})
    sent_alerts = set(state.setdefault("sent_alerts", []))

    if provider == "demo":
        snapshots = get_demo_snapshots()
        notify_existing = True
    elif provider == "espn":
        url = os.environ.get("WC_SMS_ESPN_URL") or DEFAULT_ESPN_URL
        snapshots = get_espn_snapshots(url)
    elif provider == "json-url":
        url = os.environ.get("WC_SMS_JSON_URL")
        if not url:
            raise RuntimeError("Missing WC_SMS_JSON_URL for json-url provider")
        snapshots = get_json_url_snapshots(url)
    else:
        raise ValueError(f"Unknown provider: {provider}")

    def scorer_lookup(snap: MatchSnapshot, is_home: bool) -> str:
        if provider != "espn":
            return ""
        team = snap.home if is_home else snap.away
        expected = snap.home_score if is_home else snap.away_score
        return get_latest_goal_scorer(snap.match_id, team, expected)

    alert_texts: list[str] = []
    for snapshot in snapshots:
        previous = matches_state.get(snapshot.match_id)
        alerts = build_alerts(previous, snapshot, notify_existing, scorer_lookup=scorer_lookup)
        if provider == "espn" and event_alerts and snapshot.status_state == "in":
            alerts.extend(get_espn_event_alerts(snapshot, event_types))
        matches_state[snapshot.match_id] = snapshot_to_state(snapshot)

        for alert in alerts:
            if alert.key in sent_alerts:
                continue
            sent_alerts.add(alert.key)
            alert_texts.append(alert.text)

    state["sent_alerts"] = sorted(sent_alerts)[-1000:]
    save_state(state)
    return send_alert_messages(alert_texts, dry_run=dry_run, send_delay=send_delay)


def main() -> int:
    load_dotenv(BASE_DIR / ".env")

    parser = argparse.ArgumentParser(description="World Cup email-to-iPhone SMS watcher")
    parser.add_argument("--provider", choices=["demo", "espn", "json-url"], default="espn")
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--notify-existing", action="store_true")
    parser.add_argument("--event-alerts", action="store_true")
    parser.add_argument("--event-types", default=os.environ.get("WC_SMS_EVENT_TYPES", DEFAULT_EVENT_TYPES))
    parser.add_argument("--send-delay", type=float, default=float(os.environ.get("WC_SMS_SEND_DELAY_SECONDS", DEFAULT_SEND_DELAY_SECONDS)))
    parser.add_argument("--send-event-test", action="store_true")
    parser.add_argument("--send-test", action="store_true")
    args = parser.parse_args()
    event_types = {event_type.strip().lower() for event_type in args.event_types.split(",") if event_type.strip()}

    if args.send_test:
        send_email("WC_ALERT", "TEST | World Cup SMS automation is working", dry_run=args.dry_run)
        print("Test email sent.")
        return 0

    if args.send_event_test:
        send_alert_messages(EVENT_TEST_ALERTS, dry_run=args.dry_run, send_delay=args.send_delay)
        return 0

    while True:
        try:
            sent_count = poll(args.provider, args.dry_run, args.notify_existing, args.event_alerts, event_types, args.send_delay)
            print(f"Poll complete. Alerts sent: {sent_count}")
        except (URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
            print(f"Poll failed: {exc}", file=sys.stderr)

        if args.once:
            break
        time.sleep(args.interval)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
