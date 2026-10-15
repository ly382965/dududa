from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .models import Course, CourseListItem, Review, Teacher

COURSE_LINK_RE = re.compile(r"^/course/(\d+)/$")
TEACHER_LINK_RE = re.compile(r"^/teacher/(\d+)/$")
USER_LINK_RE = re.compile(r"^/user/(\d+)$")
REVIEW_LINK_RE = re.compile(r"^/course/(\d+)/#review-(\d+)$")
COURSE_TITLE_RE = re.compile(r"^(?P<name>.+?)（(?P<teachers>.+)）$")
COURSE_COUNT_RE = re.compile(r"共\s*(\d+)\s*门课")
REVIEW_COUNT_RE = re.compile(r"\((\d+)\s*人评价\)")
REVIEW_SEARCH_COUNT_RE = re.compile(r"共\s*(\d+)\s*个点评")
USER_REVIEW_COUNT_RE = re.compile(r"写了\s*(\d+)\s*条点评")
COURSE_NO_RE = re.compile(r"课程号：\s*([^\s]+)")
RANKING_REVIEW_LINK_RE = re.compile(r"^/course/(\d+)/#review-(\d+)$")


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = unescape(value).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.search(r"-?\d+", value)
    return int(match.group(0)) if match else None


def parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    return float(match.group(0)) if match else None


def normalize_url(base_url: str, path_or_url: str | None) -> str | None:
    if not path_or_url:
        return None
    return urljoin(base_url.rstrip("/") + "/", path_or_url)


def inner_html(tag: Tag | None) -> str | None:
    if not tag:
        return None
    html = "".join(str(child) for child in tag.contents).strip()
    return html or None


def text_from_html_container(tag: Tag | None) -> str | None:
    if not tag:
        return None
    return clean_text(tag.get_text("\n", strip=True))


def parse_labeled_items(container: Tag | BeautifulSoup) -> dict[str, str]:
    labels: dict[str, str] = {}
    for node in container.find_all(["li", "td"]):
        text = clean_text(node.get_text(" ", strip=True))
        if not text or "：" not in text:
            continue
        label, value = text.split("：", 1)
        label = clean_text(label)
        value = clean_text(value)
        if label and value:
            labels.setdefault(label.replace(" ", ""), value)
    return labels


def parse_course_title(text: str | None) -> tuple[str, list[str]]:
    text = clean_text(text) or ""
    match = COURSE_TITLE_RE.match(text)
    if not match:
        return text, []
    teachers = [item.strip() for item in match.group("teachers").split(",") if item.strip()]
    return match.group("name").strip(), teachers


def parse_list_page(html: str, base_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    total_courses = None
    total_text = soup.find(string=COURSE_COUNT_RE)
    if total_text:
        total_courses = int(COURSE_COUNT_RE.search(total_text).group(1))  # type: ignore[union-attr]

    items: list[CourseListItem] = []
    seen: set[int] = set()
    for link in soup.select('a.px16[href^="/course/"]'):
        href = link.get("href")
        match = COURSE_LINK_RE.match(href or "")
        if not match:
            continue
        course_id = int(match.group(1))
        if course_id in seen:
            continue
        seen.add(course_id)

        name, teachers = parse_course_title(link.get_text(" ", strip=True))
        block = link.find_parent("div", class_=lambda value: value and "dashed" in value)
        text_block = block or link.parent or soup
        labels = parse_labeled_items(text_block)

        term_span = link.find_next("span", class_=lambda value: value and "text-muted" in value)
        term_text = clean_text(term_span.get_text(" ", strip=True)) if term_span else None

        rating = None
        rating_node = text_block.find("span", class_=lambda value: value and "h4" in value)
        if rating_node:
            rating = parse_float(rating_node.get_text(" ", strip=True))

        review_count = None
        count_text = text_block.find(string=REVIEW_COUNT_RE)
        if count_text:
            review_count = int(REVIEW_COUNT_RE.search(count_text).group(1))  # type: ignore[union-attr]

        items.append(
            CourseListItem(
                id=course_id,
                name=name,
                url=normalize_url(base_url, href) or "",
                teachers=teachers,
                term_text=term_text,
                rating_average=rating,
                review_count=review_count,
                difficulty=labels.get("课程难度"),
                homework=labels.get("作业多少"),
                grading=labels.get("给分好坏"),
                gain=labels.get("收获大小"),
            )
        )

    return {"total_courses": total_courses, "items": [item.to_dict() for item in items]}


def parse_review_search_page(html: str, base_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    total = _matched_count(soup, REVIEW_SEARCH_COUNT_RE)
    items: list[dict[str, Any]] = []
    for block in soup.select("div.ud-pd-md.dashed"):
        author_link = block.find("a", href=USER_LINK_RE)
        review_link = block.find("a", href=REVIEW_LINK_RE)
        if not isinstance(review_link, Tag):
            continue
        review_match = REVIEW_LINK_RE.match(str(review_link.get("href") or ""))
        if not review_match:
            continue
        user_match = (
            USER_LINK_RE.match(str(author_link.get("href") or ""))
            if isinstance(author_link, Tag)
            else None
        )
        author_display = (
            clean_text(author_link.get_text(" ", strip=True))
            if isinstance(author_link, Tag)
            else _anonymous_search_author(block)
        )
        content_node = block.select_one("p.review-content")
        items.append(
            {
                "id": int(review_match.group(2)),
                "course_id": int(review_match.group(1)),
                "course_name": clean_text(review_link.get_text(" ", strip=True)),
                "author_display": author_display,
                "user_id": int(user_match.group(1)) if user_match else None,
                "is_anonymous": user_match is None,
                "content_text": _review_excerpt(content_node),
                "content_is_excerpt": True,
                "update_time": _first_localtime(block),
                "url": normalize_url(base_url, str(review_link.get("href") or "")),
            }
        )
    return {"total": total if total is not None else len(items), "items": items}


def parse_user_reviews_page(
    html: str,
    base_url: str,
    user_id: int,
) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    profile_link = soup.find("a", href=f"/user/{user_id}")
    author_display = (
        clean_text(profile_link.get_text(" ", strip=True))
        if isinstance(profile_link, Tag)
        else None
    )
    total = None
    description = soup.find("meta", attrs={"property": "og:description"})
    if isinstance(description, Tag):
        match = USER_REVIEW_COUNT_RE.search(str(description.get("content") or ""))
        if match:
            total = int(match.group(1))
    if total is None:
        count_text = soup.find(string=re.compile(r"（\s*\d+\s*门\s*）"))
        total = parse_int(str(count_text)) if count_text else None

    items: list[dict[str, Any]] = []
    for block in soup.select("div.ud-pd-md.dashed"):
        review_link = block.find("a", href=REVIEW_LINK_RE)
        if not isinstance(review_link, Tag):
            continue
        review_match = REVIEW_LINK_RE.match(str(review_link.get("href") or ""))
        if not review_match:
            continue
        course_id = int(review_match.group(1))
        review_id = int(review_match.group(2))
        course_link = block.find("a", href=f"/course/{course_id}/")
        term_node = block.find("span", class_=lambda value: value and "grey" in value)
        term = clean_text(term_node.get_text(" ", strip=True)) if term_node else None
        if term:
            term = term.removeprefix("学期：")
        upvote_node = block.select_one(f"#review-upvote-count-{review_id}")
        comment_node = block.select_one(f"#review-comment-count-{review_id}")
        items.append(
            {
                "id": review_id,
                "course_id": course_id,
                "course_name": (
                    clean_text(course_link.get_text(" ", strip=True))
                    if isinstance(course_link, Tag)
                    else None
                ),
                "author_display": author_display,
                "user_id": user_id,
                "is_anonymous": False,
                "term": term,
                "content_text": _review_excerpt(block.select_one("p.dark-grey")),
                "content_is_excerpt": True,
                "update_time": _first_localtime(block),
                "upvote_count": (
                    parse_int(upvote_node.get_text(" ", strip=True))
                    if upvote_node
                    else None
                ),
                "comment_count": (
                    parse_int(comment_node.get_text(" ", strip=True))
                    if comment_node
                    else None
                ),
                "url": normalize_url(base_url, str(review_link.get("href") or "")),
            }
        )
    return {
        "total": total if total is not None else len(items),
        "items": items,
        "profile": {
            "user_id": user_id,
            "author_display": author_display,
            "url": normalize_url(base_url, f"/user/{user_id}"),
        },
    }


def find_exact_user_reference(html: str, query: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(html, "html.parser")
    expected = "".join(query.split()).casefold()
    for link in soup.find_all("a", href=USER_LINK_RE):
        name = clean_text(link.get_text(" ", strip=True))
        if not name or "".join(name.split()).casefold() != expected:
            continue
        match = USER_LINK_RE.match(str(link.get("href") or ""))
        if match:
            return {"user_id": int(match.group(1)), "author_display": name}
    return None


def parse_site_stats_page(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    labels: dict[str, str] = {}
    for row in soup.select("table tr"):
        cells = [clean_text(cell.get_text(" ", strip=True)) for cell in row.find_all("td")]
        if len(cells) == 2 and cells[0] and cells[1]:
            labels[cells[0]] = cells[1]
    return {
        "source": "live_site_stats",
        "average_review_rating": parse_float(labels.get("平均评分")),
        "coverage": {
            "courses": parse_int(labels.get("课程数")) or 0,
            "courses_with_detail": 0,
            "public_reviews": parse_int(labels.get("点评数")) or 0,
            "last_detail_crawled_at": None,
            "last_list_crawled_at": None,
        },
    }


def parse_site_rankings_page(html: str, base_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, Any] = {"source": "live_site_rankings"}
    title_keys = {
        "最受欢迎的课程": "top_courses",
        "不受欢迎的课程": "low_courses",
        "点评最多的课程": "popular_courses",
        "点赞最多的点评": "top_reviews",
        "最长的点评": "longest_reviews",
    }
    for table in soup.find_all("table"):
        title_node = table.find_previous("span", class_=lambda value: value and "h4" in value)
        title = clean_text(title_node.get_text(" ", strip=True)) if title_node else None
        key = title_keys.get(title or "")
        if key is None:
            continue
        items: list[dict[str, Any]] = []
        for row in table.find_all("tr")[1:]:
            if key in {"top_courses", "low_courses", "popular_courses"}:
                item = _ranking_course_row(row, base_url, key)
            else:
                item = _ranking_review_row(row, base_url, key)
            if item is not None:
                items.append(item)
        result[key] = items

    page_text = clean_text(soup.get_text(" ", strip=True)) or ""
    formula_match = re.search(
        r"全站点评的平均分为\s*(\d+(?:\.\d+)?).*?平均点评数为\s*(\d+(?:\.\d+)?)",
        page_text,
    )
    if formula_match:
        result["formula"] = {
            "name": "bayesian_normalized_rating",
            "global_average": float(formula_match.group(1)),
            "prior_review_count": float(formula_match.group(2)),
        }
    return result


def _ranking_course_row(row: Tag, base_url: str, key: str) -> dict[str, Any] | None:
    link = row.find("a", href=COURSE_LINK_RE)
    if not isinstance(link, Tag):
        return None
    match = COURSE_LINK_RE.match(str(link.get("href") or ""))
    cells = [clean_text(cell.get_text(" ", strip=True)) for cell in row.find_all("td")]
    if not match or len(cells) < 3:
        return None
    item = {
        "id": int(match.group(1)),
        "name": clean_text(link.get_text(" ", strip=True)) or "",
        "url": normalize_url(base_url, str(link.get("href") or "")) or "",
        "review_count_site": parse_int(cells[1]),
        "rating_average": parse_float(cells[2]),
    }
    if key != "popular_courses" and len(cells) >= 4:
        item["normalized_rating"] = parse_float(cells[3])
    return item


def _ranking_review_row(row: Tag, base_url: str, key: str) -> dict[str, Any] | None:
    link = row.find("a", href=RANKING_REVIEW_LINK_RE)
    if not isinstance(link, Tag):
        return None
    match = RANKING_REVIEW_LINK_RE.match(str(link.get("href") or ""))
    cells = [clean_text(cell.get_text(" ", strip=True)) for cell in row.find_all("td")]
    if not match or len(cells) < 3:
        return None
    author_link = row.find("a", href=USER_LINK_RE)
    author_display = (
        clean_text(author_link.get_text(" ", strip=True))
        if isinstance(author_link, Tag)
        else cells[1]
    )
    item = {
        "id": int(match.group(2)),
        "course_id": int(match.group(1)),
        "course_name": clean_text(link.get_text(" ", strip=True)),
        "author_display": author_display,
        "is_anonymous": not isinstance(author_link, Tag),
        "upvote_count": parse_int(cells[2]),
        "url": normalize_url(base_url, str(link.get("href") or "")),
    }
    if key == "longest_reviews" and len(cells) >= 4:
        item["content_length"] = parse_int(cells[3])
    return item


def _matched_count(soup: BeautifulSoup, pattern: re.Pattern[str]) -> int | None:
    value = soup.find(string=pattern)
    match = pattern.search(str(value)) if value else None
    return int(match.group(1)) if match else None


def _first_localtime(block: Tag) -> str | None:
    node = block.select_one("span.localtime")
    return clean_text(node.get_text(" ", strip=True)) if node else None


def _review_excerpt(node: Tag | None) -> str | None:
    text = clean_text(node.get_text(" ", strip=True)) if node else None
    if not text:
        return None
    return re.sub(r"\s*>>\s*(?:more|更多)\s*$", "", text, flags=re.IGNORECASE).strip()


def _anonymous_search_author(block: Tag) -> str | None:
    header = block.find("div", class_=lambda value: value and "grey" in value)
    text = clean_text(header.get_text(" ", strip=True)) if header else None
    if not text:
        return None
    return clean_text(re.split(r"(?:更新了点评|点评了)", text, maxsplit=1)[0])


def parse_course_detail(html: str, base_url: str, course_id: int) -> Course:
    soup = BeautifulSoup(html, "html.parser")
    source_url = normalize_url(base_url, f"/course/{course_id}/") or ""
    title_node = soup.select_one("div.col-md-8.inline-h3 > span.blue.h3")
    if not title_node:
        title_node = soup.find("span", class_=lambda value: value and "h3" in value and "blue" in value)
    name = clean_text(title_node.get_text(" ", strip=True) if title_node else None) or f"course-{course_id}"

    header_text = None
    header_node = soup.select_one("span.small.grey.align-bottom.left-pd-sm.desktop")
    if header_node:
        header_text = clean_text(header_node.get_text(" ", strip=True))

    courseries = None
    term_text = None
    term_ids: list[str] = []
    if header_text:
        no_match = COURSE_NO_RE.search(header_text)
        if no_match:
            courseries = no_match.group(1)
            term_text = clean_text(header_text[: no_match.start()])
        else:
            term_text = header_text
        if term_text:
            term_ids = [item for item in term_text.split(" ") if item]

    labels = parse_labeled_items(soup)
    rating_average, review_count = parse_course_rating(soup)
    homepage = parse_homepage(soup, base_url)
    intro_node = soup.select_one("#course-intro")
    summary_node = soup.select_one("#course-summary")
    reviews = parse_reviews(soup, base_url, course_id)
    teachers = parse_teachers(soup, base_url)

    return Course(
        id=course_id,
        name=name,
        url=source_url,
        teachers=teachers,
        term_text=term_text,
        term_ids=term_ids,
        courseries=courseries,
        dept=labels.get("开课单位"),
        course_type=labels.get("课程类别"),
        join_type=labels.get("选课类别"),
        teaching_type=labels.get("教学类型"),
        course_level=labels.get("课程层次"),
        credit=parse_float(labels.get("学分")),
        homepage=homepage,
        introduction_html=inner_html(intro_node),
        introduction_text=text_from_html_container(intro_node),
        summary_html=inner_html(summary_node),
        summary_text=text_from_html_container(summary_node),
        rating_average=rating_average,
        review_count_site=review_count,
        visible_review_count=len(reviews),
        difficulty=labels.get("课程难度"),
        homework=labels.get("作业多少"),
        grading=labels.get("给分好坏"),
        gain=labels.get("收获大小"),
        reviews=reviews,
    )


def parse_course_rating(soup: BeautifulSoup) -> tuple[float | None, int | None]:
    for h4 in soup.find_all("span", class_=lambda value: value and "h4" in value):
        rating = parse_float(h4.get_text(" ", strip=True))
        count_text = h4.find_next(string=REVIEW_COUNT_RE)
        if rating is not None and count_text:
            count = int(REVIEW_COUNT_RE.search(count_text).group(1))  # type: ignore[union-attr]
            return rating, count
    count_text = soup.find(string=REVIEW_COUNT_RE)
    count = int(REVIEW_COUNT_RE.search(count_text).group(1)) if count_text else None  # type: ignore[union-attr]
    return None, count


def parse_homepage(soup: BeautifulSoup, base_url: str) -> str | None:
    label = soup.find("strong", string=lambda value: bool(value and "课程主页" in value))
    if not label:
        return None
    parent = label.parent
    if not isinstance(parent, Tag):
        return None
    link = parent.find("a", href=True)
    if not link:
        return None
    return normalize_url(base_url, link.get("href"))


def parse_teachers(soup: BeautifulSoup, base_url: str) -> list[Teacher]:
    teachers: list[Teacher] = []
    seen: set[int | str] = set()
    for link in soup.select('h3.blue a[href^="/teacher/"]'):
        href = link.get("href")
        match = TEACHER_LINK_RE.match(href or "")
        teacher_id = int(match.group(1)) if match else None
        name = clean_text(link.get_text(" ", strip=True)) or ""
        if not name:
            continue
        key: int | str = teacher_id if teacher_id is not None else name
        if key in seen:
            continue
        seen.add(key)

        card = link.find_parent("div", class_=lambda value: value and "dashed" in value)
        dept = None
        homepage = None
        image = None
        if card:
            img = card.find("img")
            if img:
                image = normalize_url(base_url, img.get("src"))
            p_nodes = card.find_all("p")
            if p_nodes:
                dept = clean_text(p_nodes[0].get_text(" ", strip=True))
            home_label = card.find(string=lambda value: bool(value and "教师主页" in value))
            if home_label:
                parent = home_label.parent if isinstance(home_label.parent, Tag) else card
                home_link = parent.find("a", href=True) if isinstance(parent, Tag) else None
                if home_link:
                    homepage = normalize_url(base_url, home_link.get("href"))

        teachers.append(
            Teacher(
                id=teacher_id,
                name=name,
                dept=dept,
                homepage=homepage,
                image=image,
                source_url=normalize_url(base_url, href),
            )
        )
    return teachers


def parse_reviews(soup: BeautifulSoup, base_url: str, course_id: int) -> list[Review]:
    reviews: list[Review] = []
    for review_node in soup.select('div.review[id^="review-"]'):
        raw_id = review_node.get("id") or ""
        id_match = re.match(r"review-(\d+)$", raw_id)
        review_id = int(id_match.group(1)) if id_match else parse_int(raw_id)
        if review_id is None:
            continue

        header = review_node.find("div", class_=lambda value: value and "blue" in value)
        author_display = None
        is_anonymous = False
        if header:
            author_node = header.find("span", class_=lambda value: value and "right-pd-sm" in value)
            if author_node:
                author_link = author_node.find("a")
                if author_link:
                    author_display = clean_text(author_link.get_text(" ", strip=True))
                else:
                    author_display = clean_text(author_node.get_text(" ", strip=True))
                    is_anonymous = True

        rating_10 = parse_star_rating(header)
        term = None
        if header:
            term_node = header.find("span", class_=lambda value: value and "left-pd-md" in value)
            if term_node:
                term = clean_text(term_node.get_text(" ", strip=True))

        labels = parse_labeled_items(review_node)
        content_node = review_node.select_one(f"#review-content-{review_id}")
        footer_node = review_node.find("div", id=f"review-{review_id}", class_=lambda value: value and "grey" in value)
        time_nodes = footer_node.select("span.localtime") if footer_node else []
        publish_time = clean_text(time_nodes[0].get_text(" ", strip=True)) if time_nodes else None
        update_time = clean_text(time_nodes[1].get_text(" ", strip=True)) if len(time_nodes) > 1 else publish_time

        reviews.append(
            Review(
                id=review_id,
                course_id=course_id,
                url=(normalize_url(base_url, f"/course/{course_id}/#review-{review_id}") or ""),
                author_display=author_display,
                is_anonymous=is_anonymous,
                term=term,
                rating_10=rating_10,
                difficulty=labels.get("课程难度") or labels.get("难度"),
                homework=labels.get("作业多少") or labels.get("作业"),
                grading=labels.get("给分好坏") or labels.get("给分"),
                gain=labels.get("收获大小") or labels.get("收获"),
                content_html=inner_html(content_node),
                content_text=text_from_html_container(content_node),
                publish_time=publish_time,
                update_time=update_time,
                upvote_count=parse_int(
                    review_node.select_one(f"#review-upvote-count-{review_id}").get_text(" ", strip=True)
                    if review_node.select_one(f"#review-upvote-count-{review_id}")
                    else None
                ),
                comment_count=parse_int(
                    review_node.select_one(f"#review-comment-count-{review_id}").get_text(" ", strip=True)
                    if review_node.select_one(f"#review-comment-count-{review_id}")
                    else None
                ),
            )
        )
    return reviews


def parse_star_rating(container: Tag | None) -> int | None:
    if not container:
        return None
    rating = 0
    found = False
    for icon in container.find_all("span", class_=lambda value: value and "glyphicon-star" in value):
        classes = icon.get("class", [])
        if "glyphicon-star" in classes:
            rating += 2
            found = True
        elif "glyphicon-star-half" in classes:
            rating += 1
            found = True
    return rating if found else None
