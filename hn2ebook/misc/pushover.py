import requests

from hn2ebook.misc.log import logger

log = logger.get_logger("pushover")


class Notifier:
    def __init__(self, token, user):
        self.token = token
        self.user = user

    def send(self, message, high_priority=False, expire=3600, retry=60):
        try:
            payload = {
                "token": self.token,
                "user": self.user,
                "message": message,
                "priority": 0,
            }
            if high_priority:
                payload["priority"] = 2
                payload["expire"] = expire
                payload["retry"] = retry
            resp = requests.post(
                "https://api.pushover.net/1/messages.json", data=payload, timeout=30
            )
            if resp.status_code == 200:
                return True

            log.warn(f"pushover returned non-200 code={resp.status_code}")
            log.debug(resp.json())
            return False

        except Exception as e:
            log.error("Error sending notification")
            log.error(e)
        return False
