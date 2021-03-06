import requests
import re
from datetime import timedelta

from hn2ebook import db
from hn2ebook.misc.log import logger

log = logger.get_logger("hn")


def best_story_ids():
    return requests.get(
        f"https://hacker-news.firebaseio.com/v0/beststories.json"
    ).json()


def best_story_ids_daemonology(day):
    """
    Returns the story ids from cperciva's hn daily for the given day
    """
    regex = r"item\?id=(\d+)"

    date_str = day.strftime("%Y-%m-%d")
    url = f"http://www.daemonology.net/hn-daily/{date_str}.html"
    response = requests.get(url)
    response.raise_for_status()

    matches = re.finditer(regex, response.text, re.MULTILINE)
    return [match.group(1) for match in matches]


def update_best_stories(conn, day):
    """
    Records the best hn stories from the current hn best stories feed for the given day.
    """
    current_story_ids = best_story_ids()
    tuples = [(item_id, day) for item_id in current_story_ids]
    n = db.insert_best_stories(conn, tuples)

    log.info("Processed %d stories with %d new entries" % (len(current_story_ids), n))


def update_best_stories_daemonology(conn, day):
    """
    Records the best hn stories from cperciva's hn daily for the given day.
    """
    story_ids = best_story_ids_daemonology(day)
    tuples = [(item_id, day) for item_id in story_ids]
    db.insert_best_stories(conn, tuples)


def backfill_daemonology(conn, start_date, end_date):
    """
    Backfills the best stories of the day  between [start,end) using cperciva's daily best feed.
    """
    current = start_date
    while current < end_date:
        log.info(f"backfill from daemonology {current}")
        update_best_stories_daemonology(conn, current)
        current = current + timedelta(days=1)


def best_story_ids_frontpage(day, pages=3):
    """
    Returns the story ids from hn's /front for the given day
    """
    regex = r"<span class=\"age\"><a href=\"item\?id=(\d+)"

    date_str = day.strftime("%Y-%m-%d")
    ids = set()
    for page in range(pages + 1):
        url = f"https://news.ycombinator.com/front?day={date_str}?pg={page}"
        response = requests.get(url)
        if response.status_code in [401, 403, 404, 405]:
            log.debug("encountered {response.status_code} on {url}")
            continue
        else:
            response.raise_for_status()

        matches = re.finditer(regex, response.text, re.MULTILINE)
        page_ids = [match.group(1) for match in matches]
        ids.update(page_ids)
    return list(ids)


def update_best_stories_frontpage(conn, day):
    """
    Records the best hn stories from /front
    """
    story_ids = best_story_ids_frontpage(day)
    tuples = [(item_id, day) for item_id in story_ids]
    db.insert_best_stories(conn, tuples)


def backfill_frontpage(conn, start_date, end_date):
    """
    Backfills the best stories of the day  between [start,end) using the /front hn feature
    """
    current = start_date
    while current < end_date:
        log.info(f"backfill from /front {current}")
        update_best_stories_frontpage(conn, current)
        current = current + timedelta(days=1)


def story_ids_in_range(start, end):
    """
    Returns a list of story ids storyed in the interval [start,end) sorted by story date. start and end are numeric timestamps.
    """
    start = datetime.timestamp(start)
    end = datetime.timestamp(end)
    tags = "(story,show_hn,ask_hn)"
    url = f"https://hn.algolia.com/api/v1/search?tags={tags}&numericFilters=created_at_i>={start},created_at_i<{end}"
    response = requests.get(url)
    response.raise_for_status()
    payload = response.json()
    sorted_hits = sorted(payload["hits"], key=lambda k: k["created_at_i"])
    return [hit["objectID"] for hit in sorted_hits]
