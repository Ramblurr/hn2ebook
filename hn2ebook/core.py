import subprocess
import os
import math
import json
import io
import tempfile
import shutil
import locale
import importlib.resources
import traceback
import urllib
import multiprocessing
import cgi
from pathlib import Path
from datetime import datetime, timezone

import PIL.Image
import requests
import lxml.etree
import lxml.html


from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from flask import Flask, request, jsonify
from flask.templating import render_template
from ebooklib import epub

from hn2ebook.misc.log import logger

log = logger.get_logger("hn2ebook")
app = Flask(__name__, template_folder="resources")

ALLOWED_MIMETYPES = ["text/html", "text/plain"]


def fetch_mimetype(url):
    h = requests.head(url, allow_redirects=True)
    header = h.headers
    content_type = header.get("content-type")
    mimetype, _ = cgi.parse_header(content_type)
    return mimetype


def chrome_get(driver_path, url, wait_seconds=3):
    opts = Options()
    opts.headless = True
    browser = Chrome(executable_path=driver_path, options=opts)
    browser.implicitly_wait(wait_seconds)
    browser.get(url)
    source = browser.page_source
    browser.close()
    return source


def parse_srcset(cfg, srcset):
    cmd = [cfg["srcsetparser_bin"], srcset]

    log.debug("running srcsetparser cmd: %s" % " ".join(cmd))
    result = subprocess.run(cmd, timeout=2, capture_output=True)
    try:
        result_json = json.loads(result.stdout)
        log.debug("srcset-parser returned result")
        return result_json
    except json.decoder.JSONDecodeError:
        raise Exception(
            "srcset-parser was not able to parse the srcset",
            result.stdout + result.stderr,
        )


def readable(cfg, url):
    if cfg["use_chrome"]:
        text = chrome_get(cfg["chromedriver_bin"], url)
    else:
        response = requests.get(url, allow_redirects=True)
        response.raise_for_status()
        if response.encoding == "ISO-8859-1":
            response.encoding = response.apparent_encoding
        text = response.text
    temp_doc = tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8", delete=True)
    temp_doc.write(text)

    cmd = [
        cfg["readability_bin"],
        temp_doc.name,
        url,
    ]

    # log.debug("running readability cmd: %s" % " ".join(cmd))
    result = subprocess.run(cmd, timeout=10, capture_output=True)
    try:
        result_json = json.loads(result.stdout)
        log.debug("readability returned result")
        return result_json
    except json.JSONDecodeError:
        raise Error(
            "Readability was not able to extract the article from the page",
            result.stdout + result.stderr,
        )
    finally:
        temp_doc.close()


def url_for_item(id):
    return f"https://hacker-news.firebaseio.com/v0/item/{id}.json?print=pretty"


def get_item(id):
    # log.debug(f"getting item {id}")
    r = requests.get(url_for_item(id))
    r.raise_for_status()
    return r.json()


def expand_item(pool, self, parent=None):
    if not self and parent:
        log.error("nil item encountered under parent %s" % parent["id"])
        return None
    if "kids" in self:
        # children = [expand_item(get_item(kid)) for kid in self["kids"][:10]]
        items = pool.map(get_item, self["kids"][:10])
        children = [expand_item(pool, item, self) for item in items]
    else:
        children = []

    self["children"] = [c for c in children if c]
    return self


def readable_failed(url, msg=""):
    return f'<p>Failed to extract the article text from the <a href="{url}">original link</a></p><pre>{url}</pre><pre>{msg}</pre>'


def invalid_mimetype(url, mimetype):
    return f'<p>The <a href="{url}">original link</a> is to content of type <code>{mimetype}</code>, which isn\'t supported.</p><pre>{url}</pre>'


def expand_body(cfg, story):
    mimetype = fetch_mimetype(story["url"])
    try:
        if not mimetype in ALLOWED_MIMETYPES:
            log.info(f"skipping non-text content {mimetype}")
            return invalid_mimetype(story["url"], mimetype)
        else:
            log.info(f"extracting article content")
            result = readable(cfg, story["url"])
            if not result or "content" not in result:
                log.error("content missing in readable result for %s" % story["url"])
                return readable_failed(story["url"], "content missing")
            return result["content"]
    except Exception as e:
        readable_failed(story["url"], str(e))
        log.error("readable failed for %s" % story["url"])
        print("story is", story)
        log.error(e)
        traceback.print_exc()


def expand_story(cfg, story_id, summary_only):
    if summary_only:
        log.debug(f"fetching story summary id={story_id}")
    else:
        log.info(f"fetching story with comments and article id={story_id}")
    story = get_item(story_id)

    if "text" in story:
        story["url"] = f"https://news.ycombinator.com/item?id={story_id}"

    if summary_only:
        return story

    if "text" in story:
        story["body"] = story["text"]
        del story["text"]
    else:
        story["body"] = expand_body(cfg, story)

    log.info("walking descendants tree for comments")
    with multiprocessing.Pool(cfg["n_concurrent_requests"]) as pool:
        story["comments"] = expand_item(pool, story)
    return story


comment_template = """
<div id={kid} class="hn2ebook-comment-meta">
<span class="number">{number}</span> <span class="author">{by}</span> <span class="date">{date}</span> {descendants}
<div class="comment-links">{links}</div>
</div>
<div class="comment-body">
{text}
</div>
<ol>{children}</ol>
"""

comment_op_template = """
<footer class="hn2ebook-op">{by}</footer>
{text}
<ol>{children}</ol>
"""


def load_resource_text(file_name):
    return importlib.resources.read_text("hn2ebook.resources", file_name)


def load_resource_path(file_name):
    return importlib.resources.path("hn2ebook.resources", file_name)


def to_link(href, label):
    if href:
        return f'<a href="#{href}">{label}</a>'
    else:
        return ""


def indices_to_heading(indices):
    return ".".join([str(i) for i in indices])


def to_html_numbers(indices, comment, op, story_id, sibling_pre, sibling_story):
    children = []
    for idx, reply in enumerate(comment["children"]):
        child_sibling_pre = when_index(comment["children"], idx - 1)
        child_sibling_story = when_index(comment["children"], idx + 1)
        human_index = idx + 1
        child_indices = indices.copy()
        child_indices.append(human_index)
        if "by" in reply:
            children.append(
                "<li>"
                + to_html_numbers(
                    child_indices,
                    reply,
                    op,
                    story_id,
                    child_sibling_pre,
                    child_sibling_story,
                )
                + "</li>"
            )
    if "by" in comment:
        tmpl = comment_op_template if op == comment["by"] else comment_template
        text_body = comment["text"]
    elif "deleted" in comment and comment["deleted"]:
        tmpl = comment_template
        text_body = "deleted"
    descendants = "<span>(%d)</span>" % (len(children)) if len(children) > 0 else ""
    return tmpl.format(
        **{
            "number": indices_to_heading(indices),
            "kid": comment["id"],
            "text": text_body,
            "by": comment.get("by"),
            "date": datetime.fromtimestamp(comment["time"]).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "descendants": descendants,
            "children": "".join(children),
            "links": "{} {} {}".format(
                to_link(sibling_pre.get("id") if sibling_pre else None, "previous"),
                to_link(comment["parent"], "parent")
                if str(comment["parent"]) != str(story_id)
                else "",
                to_link(sibling_story.get("id") if sibling_story else None, "next"),
            ),
        }
    )


def is_index(a, i):
    return 0 <= i < len(a)


def when_index(a, i):
    if is_index(a, i):
        return a[i]
    return None


def comments_to_html(story_id, comments):
    comments_style = "numbers"
    out = "<ol>"
    op = "op"
    for idx, comment in enumerate(comments):
        sibling_pre = when_index(comments, idx - 1)
        sibling_story = when_index(comments, idx + 1)
        human_idx = idx + 1
        out += (
            "<li>"
            + to_html_numbers(
                [human_idx], comment, op, story_id, sibling_pre, sibling_story
            )
            + "</li>"
        )
    return out + ("</ol>" if comments_style == "numbers" else "")


def story_to_html(story):
    body = story["body"]
    comments_html = comments_to_html(story["id"], story["children"])

    with app.app_context():
        attachment = render_template(
            "comments.html",
            title=story["title"],
            story_id=story["id"],
            body=body,
            author=story["by"],
            comments=comments_html,
            source=story["url"],
        )
        return attachment


def story_to_data(cfg, story_id, summary_only):
    story = expand_story(cfg, story_id, summary_only)
    data = {
        "title": story["title"],
        "id": str(story["id"]),
        "points": story["score"],
        "num_comments": story["descendants"],
        "time": story["time"],
        "datetime": datetime.fromtimestamp(story["time"], tz=timezone.utc),
        "author": story["by"],
        "source": story["url"],
    }
    if not summary_only:
        data["html"] = story_to_html(story)
    return data


def calc_width(n):
    return min(2, len(str(n)))


def image_to_svg_string(image_url):
    response = requests.get(image_url)
    response.raise_for_status()
    return response.text


def image_to_png_bytes(image_url):
    try:
        if image_url.startswith("data:"):
            with urllib.request.urlopen(image_url) as response:
                data = response.read()
        else:
            mimetype = fetch_mimetype(image_url)
            if not mimetype.startswith("image"):
                log.debug(f"skipping src with mimetype {mimetype}")
                return None
            response = requests.get(image_url, stream=True)
            response.raise_for_status()
            response.raw.decode_content = True
            data = response.raw
        with tempfile.SpooledTemporaryFile() as tmpfile:
            shutil.copyfileobj(data, tmpfile)
            img = PIL.Image.open(tmpfile)
            b = io.BytesIO()
            img.save(b, "png")
            return b.getvalue()
    except PIL.UnidentifiedImageError as e:
        log.error(f"cannot extract image at url {image_url}")
        log.error(e)
        traceback.print_exc()


def extract_image(prefix, idx, orig_url):
    extension = os.path.splitext(orig_url)[1].lower()
    if extension in [".svg"]:
        filename = f"{prefix}{idx}.svg"
        log.debug(f"extracting img src {orig_url} -> {filename}")
        return (
            filename,
            {
                "idx": idx,
                "url": orig_url,
                "filename": filename,
                "mimetype": "image/svg+xml",
                "payload": image_to_svg_string(orig_url),
            },
        )
    else:
        filename = f"{prefix}{idx}.png"
        log.debug(f"extracting img src {orig_url} -> {filename}")
        payload = image_to_png_bytes(orig_url)
        if payload:
            return (
                filename,
                {
                    "idx": idx,
                    "url": orig_url,
                    "filename": filename,
                    "mimetype": "image/png",
                    "payload": payload,
                },
            )
        return None, None


def choose_srcset(cfg, srcset):
    r = parse_srcset(cfg, srcset)
    widths = [
        src["url"]
        for src in r
        if "width" in src and src["width"] >= 500 and src["width"] <= 1000
    ]
    print(widths)
    if len(widths) == 0:
        return r[0]["url"]
    else:
        return widths[0]


def choose_img_url(cfg, node):
    if "src" in node.attrib:
        return node.attrib["src"]
    elif "srcset" in node.attrib:
        return choose_srcset(cfg, node.attrib["srcset"])
    elif "data-srcset" in node.attrib:
        return choose_srcset(cfg, node.attrib["data-srcset"])
    return None


def rewrite_images(cfg, prefix, html):
    tree = lxml.html.fromstring(html)
    images = []
    for idx, node in enumerate(tree.xpath(".//img | .//source")):
        orig_url = choose_img_url(cfg, node)
        if not orig_url:
            log.debug("skipping missing src/srcset in ")
            log.debug(node.attrib.keys())
            log.debug(lxml.etree.tostring(node))
            continue
        try:
            filename, image = extract_image(prefix, idx, orig_url)
            if image:
                images.append(image)
                node.attrib["src"] = filename
            else:
                message = lxml.html.fromstring(f"<p>image could not be loaded</p>")
                node.getparent().replace(node, message)
        except requests.exceptions.HTTPError as e:
            log.error(
                "failed to extract image status_code=%s, url=%s"
                % (e["status_code"], orig_url)
            )

    return lxml.etree.tostring(tree), images


def remove_rich_media(html):
    tree = lxml.html.fromstring(html)

    disallowed = ["video", "iframe", "audio", "object"]
    xpath = " | ".join(f".//{tag}" for tag in disallowed)
    for idx, node in enumerate(tree.xpath(xpath)):
        tag = node.tag
        message = lxml.html.fromstring(
            f"<p>&lt;{tag}&gt; REMOVED FOR E-BOOK VERSION</p>"
        )
        node.getparent().replace(node, message)

    return lxml.etree.tostring(tree)


def build_chapter(cfg, book, number, total_chapters, story):
    log.info("building chapter for story id=%s" % (story["id"]))
    filename = "chap_%s.xhtml" % (str(number).zfill(calc_width(total_chapters)))
    c1 = epub.EpubHtml(title=story["title"], file_name=filename, lang="en")
    story_id = story["id"]
    html, images = rewrite_images(cfg, f"images/image_{story_id}_", story["html"])
    html = remove_rich_media(html)
    for image in images:
        idx = image["idx"]
        uid = f"image_{story_id}_{idx}"
        image_item = epub.EpubItem(
            uid=uid,
            file_name=image["filename"],
            media_type=image["mimetype"],
            content=image["payload"],
        )
        book.add_item(image_item)

    c1.content = html
    return c1


def read_comments_css():
    style = load_resource_text("styles.css")
    return epub.EpubItem(
        uid="style_nav",
        file_name="style/comments.css",
        media_type="text/css",
        content=style,
    )


def epub_description(metadata):
    title = metadata["title"]
    subtitle = metadata["subtitle"]
    start = f"{title} {subtitle}"
    description = "There are %d stories in this issue:" % metadata["num_stories"]
    headlines_txt = "\n\n".join(metadata["headlines"])

    return f"{start}\n\n{description}\n\n{headlines_txt}"


def epub_cover(metadata):
    from PIL import Image, ImageDraw, ImageFont

    title, _, subtitle = metadata["title"].rpartition(" ")

    bold = "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf"
    regular = "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf"

    with load_resource_path("cover.png") as cover_path:
        img = Image.open(cover_path)
        W, H = img.size
        draw = ImageDraw.Draw(img)

        font = ImageFont.truetype(bold, 110)
        w, h = draw.textsize(title, font=font)
        draw.text(((W - w) / 2, 260), title, fill=(255, 255, 255), font=font)

        w, h = draw.textsize(subtitle, font=font)
        draw.text(((W - w) / 2, 441), subtitle, fill=(255, 255, 255), font=font)

        subsubtitle = metadata["subtitle"]
        font = ImageFont.truetype(bold, 40)
        w, h = draw.textsize(subsubtitle, font=font)
        draw.text(((W - w) / 2, 1162), subsubtitle, fill=(255, 255, 255), font=font)
        b = io.BytesIO()
        img.save(b, "png")
        return b.getvalue()


def build_epub(cfg, stories, metadata, out_path):
    comments_css = read_comments_css()
    book = epub.EpubBook()
    book.set_identifier(metadata["identifier"])
    book.set_title(metadata["title"])
    for author in metadata["authors"]:
        book.add_author(author)
    book.set_language(metadata["language"])

    for k, v in metadata["DC"].items():
        book.add_metadata("DC", k, v)

    book.add_metadata("DC", "description", epub_description(metadata))

    book.add_item(comments_css)
    book.set_cover("cover.png", epub_cover(metadata))

    chapters = []
    for idx, story in enumerate(stories):
        chapters.append(build_chapter(cfg, book, idx, len(stories), story))
    toc = []
    for chapter in chapters:
        chapter.add_item(comments_css)
        book.add_item(chapter)
        toc.append(chapter)

    book.toc = toc

    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    book.spine = ["nav"] + chapters
    return book


def sort_stories(stories, criteria):
    if criteria == "time":
        return sorted(stories, key=lambda p: p["datetime"])
    elif criteria == "time-reverse":
        return sorted(stories, key=lambda p: p["datetime"], reverse=True)
    elif criteria == "points":
        return sorted(stories, key=lambda p: p["points"], reverse=True)
    elif criteria == "total-comments":
        return sorted(stories, key=lambda p: p["num_comments"], reverse=True)


def resolve_stories(cfg, story_ids, limit, criteria):
    stories = [story_to_data(cfg, story_id, True) for story_id in story_ids]
    sorted_stories = sort_stories(stories, criteria)
    sliced_stories = sorted_stories[0:limit]
    log.info("winnowed %d stories down to %d" % (len(stories), len(sliced_stories)))
    log.info("extracting article and comments from %d stories" % len(sliced_stories))
    return [story_to_data(cfg, story["id"], False) for story in sliced_stories]


def epub_from_stories(cfg, stories, metadata, output):
    book = build_epub(cfg, stories, metadata, output)
    log.info(f"writing epub: {output}")
    epub.write_epub(output, book, {})
    return output


def entry_description(metadata):
    title = metadata["title"]
    subtitle = metadata["subtitle"]
    start = f"{title}<br/>{subtitle}"
    description = (
        '<p class="description">There are %d stories in this issue:</p>'
        % metadata["num_stories"]
    )
    headlines_xhtml = "\n".join(
        [f'<p class="description">{title}</p>' for title in metadata["headlines"]]
    )

    return f'<div xmlns="http://www.w3.org/1999/xhtml">{start}\n{description}\n{headlines_xhtml}</div>'


def book_to_entry(root_url, book):
    metadata = book["meta"]
    content_xhtml = entry_description(metadata)

    return {
        "title": metadata["title"],
        "id": metadata["identifier"],
        "atom_timestamp": metadata["DC"]["date"],
        "authors": [{"name": name} for name in metadata["authors"]],
        "publishers": [{"name": metadata["DC"]["publisher"]}],
        "issued": metadata["DC"]["date"][0:10],
        "language": metadata["language"],
        "summary": "The %s periodical %s. There are %d stories in this issue."
        % (metadata["title"], metadata["subtitle"], metadata["num_stories"]),
        "content_xhtml": content_xhtml,
        # "content": metadata[""]
        "has_cover": False,
        "cover_url": "",
        "formats": [
            {
                "url": "/books/%s" % f["file_name"],
                "size": f["file_size"],
                "mimetype": f["mimetype"],
            }
            for f in book["formats"]
        ],
    }


def generate_opds(cfg, instance, feed, books):
    root_url = instance["root_url"]
    entries = [book_to_entry(root_url, book) for book in books]
    feed_path = Path(cfg["data_dir"]).joinpath(feed["url"][1:])
    log.info(f"writing feed {feed_path} with {len(books)}")
    with app.app_context():
        current_time = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")
        xml = render_template(
            "opds-feed.xml.j2",
            current_time=current_time,
            root_url=root_url,
            feed=feed,
            instance=instance,
            entries=entries,
        )
        with open(feed_path, "w") as f:
            f.write(xml)


def generate_opds_index(cfg, instance, feeds):
    feed_path = Path(cfg["data_dir"]).joinpath(instance["url"][1:])
    log.info(f"writing feed {feed_path} as index")
    with app.app_context():
        current_time = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")
        xml = render_template(
            "opds-index.xml.j2",
            current_time=current_time,
            root_url=instance["root_url"],
            feeds=feeds,
            instance=instance,
        )
        with open(feed_path, "w") as f:
            f.write(xml)
