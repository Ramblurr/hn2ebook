import requests
import re
from datetime import timedelta

from hn2epub import db
from hn2epub.misc.log import logger

log = logger.get_logger("hn")


def best_post_ids():
    return requests.get(
        f"https://hacker-news.firebaseio.com/v0/beststories.json"
    ).json()


def best_post_ids_daemonology(day):
    regex = r"item\?id=(\d+)"

    date_str = day.strftime("%Y-%m-%d")
    url = f"http://www.daemonology.net/hn-daily/{date_str}.html"
    response = requests.get(url)
    response.raise_for_status()

    matches = re.finditer(regex, response.text, re.MULTILINE)
    return [match.group(1) for match in matches]


def update_best_stories(conn, day):
    current_post_ids = best_post_ids()
    tuples = [(item_id, day) for item_id in current_post_ids]
    db.insert_best_stories(conn, tuples)

    print(db.all_best_stories(conn))


def update_best_stories_daemonology(conn, day):
    log.info(f"backfill from daemonology {day}")
    post_ids = best_post_ids_daemonology(day)
    tuples = [(item_id, day) for item_id in post_ids]
    db.insert_best_stories(conn, tuples)


def backfill_daemonology(conn, start_date, end_date):
    """
    Backfills the best stories of the day  between [start,end)
    """
    current = start_date
    while current < end_date:
        update_best_stories_daemonology(conn, current)
        current = current + timedelta(day=1)
