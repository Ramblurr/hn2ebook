import os
import pprint
import math

from datetime import datetime

import requests
import requests_cache

from flask import Flask, request, jsonify
from flask.templating import render_template

from ebooklib import epub

app = Flask(__name__)

requests_cache.install_cache("hn2epub")


def url_for_item(id):
    return f"https://hacker-news.firebaseio.com/v0/item/{id}.json?print=pretty"


def get_item(id):
    # print(f"   get_item: {id}")
    r = requests.get(url_for_item(id))
    return r.json()


def expand_item(self):
    # print(self)
    if "kids" in self:
        children = [expand_item(get_item(kid)) for kid in self["kids"][:10]]
    else:
        children = []

    self["children"] = children
    return self


def expand_post(post_id):
    # print(f"FETCHING {post_id}")
    post = get_item(post_id)
    post["comments"] = expand_item(post)
    return post


pp = pprint.PrettyPrinter(indent=4)

comment_template = """
<div id={kid} class="comment-meta"><span class="author">{by}</span> <span class="date">{date}</span> <span>({descendants})</span></div>
<div class="comment-body">
{text}
</div>
<footer>{links}</footer>
<ol>{children}</ol>
"""

comment_op_template = """
<footer class="op">{by}</footer>
{text}
<ol>{children}</ol>
"""


def to_link(href, label):
    if href is not None:
        return f'<a href="#{href}">{label}</a>'
    else:
        return ""


def to_html_numbers(indices, comment, op, post_id, sibling_pre, sibling_post):
    children = []
    for idx, reply in enumerate(comment["children"]):
        child_sibling_pre = when_index(comment["children"], idx - 1)
        child_sibling_post = when_index(comment["children"], idx + 1)
        human_index = idx + 1
        child_indices = indices.copy()
        child_indices.append(human_index)
        if reply["by"] is not None:
            children.append(
                "<li>"
                + to_html_numbers(
                    child_indices,
                    reply,
                    op,
                    post_id,
                    child_sibling_pre,
                    child_sibling_post,
                )
                + "</li>"
            )
    tmpl = comment_op_template if op == comment["by"] else comment_template
    return tmpl.format(
        **{
            "kid": comment["id"],
            "text": comment["text"],
            "by": comment["by"],
            "date": datetime.fromtimestamp(comment["time"]).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "descendants": comment["descendants"]
            if "descendants" in comment
            else len(children),
            "children": "".join(children),
            "links": "{} {} {}".format(
                to_link(sibling_pre.get("id") if sibling_pre else None, "previous"),
                to_link(comment["parent"], "parent")
                if str(comment["parent"]) != str(post_id)
                else "",
                to_link(sibling_post.get("id") if sibling_post else None, "next"),
            ),
        }
    )


def is_index(a, i):
    return 0 <= i < len(a)


def when_index(a, i):
    if is_index(a, i):
        return a[i]
    return None


# def comments_to_html_psuedo(post_id, comments):
#    out = "<ol>"
#    op = "op"
#    for idx, comment in enumerate(comments):
#        sibling_pre = when_index(comments, idx - 1)
#        sibling_post = when_index(comments, idx + 1)
#        if comment["by"] is not None:
#            out += (
#                "<li>"
#                + to_html_numbers(
#                     comment, op, post_id, sibling_pre, sibling_post
#                )
#                + "</li>"
#            )
#    return out + "</ol>"


def comments_to_html(post_id, comments):
    comments_style = "numbers"
    out = "<ol>"
    op = "op"
    for idx, comment in enumerate(comments):
        sibling_pre = when_index(comments, idx - 1)
        sibling_post = when_index(comments, idx + 1)
        human_index = idx + 1
        if comment["by"] is not None:
            out += (
                "<li>"
                + to_html_numbers(
                    [human_idx], comment, op, post_id, sibling_pre, sibling_post
                )
                + "</li>"
            )
    return out + ("</ol>" if comments_style == "numbers" else "")


def hn2epub2(post_id):
    post = expand_post(post_id)
    body = ""
    if "text" in post:
        body = post["text"]
    comments_html = comments_to_html(post_id, post["children"])

    with app.app_context():
        attachment = render_template(
            "comments.html",
            title=post["title"],
            body=body,
            author=post["by"],
            comments=comments_html,
            source=post["url"],
        )
        return attachment


def post2data(post_id):
    post = expand_post(post_id)
    body = ""
    if "text" in post:
        body = post["text"]
    comments_html = comments_to_html(post_id, post["children"])
    return {
        "title": post["title"],
        "body": body,
        "comments_html": comments_html,
        "author": post["by"],
        "source": post["url"],
    }


def calc_width(n):
    return min(2, len(str(n)))


def data2chapter(number, total_chapters, post):
    filename = "chap_%s.xhtml" % (str(number).zfill(calc_width(total_chapters)))
    c1 = epub.EpubHtml(title=post["title"], file_name=filename, lang="en")
    c1.content = post["comments_html"]
    return c1


def hn2epub(post_id):
    book = epub.EpubBook()
    book.set_identifier("id123456")
    book.set_title("Sample book")
    book.set_language("en")
    book.add_author("Author Authorowski")

    data = post2data(post_id)
    chapter = data2chapter(1, 1, data)
    book.add_item(chapter)

    book.toc = (
        epub.Link("chap_01.xhtml", data["title"], "wtf"),
        (epub.Section("Simbple Book"), (chapter,)),
    )

    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    with open("styles.css", "r") as f:
        style = f.read()
        nav_css = epub.EpubItem(
            uid="style_nav",
            file_name="style/nav.css",
            media_type="text/css",
            content=style,
        )
        book.add_item(nav_css)

    book.spine = ["nav", chapter]
    epub.write_epub("test.epub", book, {})
    return "test.epub"


# r = hn2epub('22170395')
r = hn2epub("23525753")
print(r)
