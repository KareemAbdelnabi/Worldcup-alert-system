# World Cup SMS MVP

This MVP turns live match changes into emails. Your iPhone receives those emails, and an iOS Shortcut sends the email text as an SMS from your SIM.

Flow:

```text
World Cup watcher -> email to your iPhone -> iOS Shortcut -> SMS to target number
```

## 1. iPhone Shortcut Setup

Open the Shortcuts app:

1. Go to `Automation`.
2. Tap `+`.
3. Choose `Email`.
4. Set:
   - Sender: the email account used by the script.
   - Subject contains: `WC_ALERT`
   - Account: the email account on your iPhone.
5. Choose `Run Immediately`.
6. Add action: `Send Message`.
7. Before `Send Message`, add `Get Details of Emails`.
8. Set it to get `Body` from `Shortcut Input`.
9. Message: use the `Body` result.
10. Recipient: the target phone number.
11. Open the message action options and turn off `Show Compose Sheet` if it appears.
12. Save it.

Test it by sending yourself an email with:

Subject:

```text
WC_ALERT
```

Body:

```text
TEST | World Cup SMS automation is working
```

If the SMS is sent automatically, the iPhone side is ready.

## 2. Configure Email

Copy `.env.example` to `.env` and fill it.

For Gmail, use an App Password, not your normal Gmail password.

```bash
cp .env.example .env
```

## 3. Send A Test Email

```bash
python3 worldcup_sms_watcher.py --send-test
```

## 4. Run Demo Mode

This does not need a live data source. It sends a fake World Cup event so you can test the full email-to-SMS path.

```bash
python3 worldcup_sms_watcher.py --provider demo --once
```

## 5. Run Live Watcher

The ESPN-style provider watches score and status changes. It can alert kickoff, goals by team, halftime, and fulltime.

```bash
python3 worldcup_sms_watcher.py --provider espn --interval 15
```

If that live source is blocked from your network, use a custom JSON endpoint:

```bash
python3 worldcup_sms_watcher.py --provider json-url --interval 15
```

The endpoint should return:

```json
{
  "matches": [
    {
      "id": "match-1",
      "home": "Argentina",
      "away": "Morocco",
      "home_score": 1,
      "away_score": 0,
      "status_state": "in",
      "status_name": "STATUS_IN_PROGRESS",
      "status_detail": "23'"
    }
  ]
}
```

Notes:

- The first run records the current scoreboard and usually does not alert old events.
- Keep the script running during matches.
- iOS/email delivery may add delay. This is near-instant, not guaranteed real-time.
- If the live endpoint is blocked or changes, only the provider function needs changing.
