import json
import os
import urllib.request
import urllib.error
import urllib.parse


def send_sms(phone, message):
    username = os.environ.get("AT_USERNAME")
    api_key = os.environ.get("AT_API_KEY")
    if not username or not api_key or not phone:
        return "not_configured", None

    payload = urllib.parse.urlencode({"username": username, "to": phone, "message": message}).encode()
    request = urllib.request.Request(
        "https://api.africastalking.com/version1/messaging",
        data=payload,
        headers={"apiKey": api_key, "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
        recipients = result.get("SMSMessageData", {}).get("Recipients", [])
        if recipients and recipients[0].get("status") in {"Success", "Sent"}:
            return "sent", recipients[0].get("messageId")
        return "failed", None
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
        return "failed", None