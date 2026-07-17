from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CourseListItem:
    id: int
    name: str
    url: str
    teachers: list[str] = field(default_factory=list)
    term_text: str | None = None
    rating_average: float | None = None
    review_count: int | None = None
    difficulty: str | None = None
    homework: str | None = None
    grading: str | None = None
    gain: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "teachers": self.teachers,
            "term_text": self.term_text,
            "rating_average": self.rating_average,
            "review_count": self.review_count,
            "difficulty": self.difficulty,
            "homework": self.homework,
            "grading": self.grading,
            "gain": self.gain,
        }


@dataclass
class Teacher:
    id: int | None
    name: str
    dept: str | None = None
    homepage: str | None = None
    image: str | None = None
    source_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "dept": self.dept,
            "homepage": self.homepage,
            "image": self.image,
            "source_url": self.source_url,
        }


@dataclass
class Review:
    id: int
    course_id: int
    url: str
    author_display: str | None = None
    is_anonymous: bool = False
    term: str | None = None
    rating_10: int | None = None
    difficulty: str | None = None
    homework: str | None = None
    grading: str | None = None
    gain: str | None = None
    content_html: str | None = None
    content_text: str | None = None
    publish_time: str | None = None
    update_time: str | None = None
    upvote_count: int | None = None
    comment_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "course_id": self.course_id,
            "url": self.url,
            "author_display": self.author_display,
            "is_anonymous": self.is_anonymous,
            "term": self.term,
            "rating_10": self.rating_10,
            "difficulty": self.difficulty,
            "homework": self.homework,
            "grading": self.grading,
            "gain": self.gain,
            "content_html": self.content_html,
            "content_text": self.content_text,
            "publish_time": self.publish_time,
            "update_time": self.update_time,
            "upvote_count": self.upvote_count,
            "comment_count": self.comment_count,
        }


@dataclass
class Course:
    id: int
    name: str
    url: str
    teachers: list[Teacher] = field(default_factory=list)
    term_text: str | None = None
    term_ids: list[str] = field(default_factory=list)
    courseries: str | None = None
    dept: str | None = None
    course_type: str | None = None
    join_type: str | None = None
    teaching_type: str | None = None
    course_level: str | None = None
    credit: float | None = None
    homepage: str | None = None
    introduction_html: str | None = None
    introduction_text: str | None = None
    summary_html: str | None = None
    summary_text: str | None = None
    rating_average: float | None = None
    review_count_site: int | None = None
    visible_review_count: int | None = None
    difficulty: str | None = None
    homework: str | None = None
    grading: str | None = None
    gain: str | None = None
    reviews: list[Review] = field(default_factory=list)

    def to_dict(self, include_reviews: bool = True) -> dict[str, Any]:
        data = {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "teachers": [teacher.to_dict() for teacher in self.teachers],
            "term_text": self.term_text,
            "term_ids": self.term_ids,
            "courseries": self.courseries,
            "dept": self.dept,
            "course_type": self.course_type,
            "join_type": self.join_type,
            "teaching_type": self.teaching_type,
            "course_level": self.course_level,
            "credit": self.credit,
            "homepage": self.homepage,
            "introduction_html": self.introduction_html,
            "introduction_text": self.introduction_text,
            "summary_html": self.summary_html,
            "summary_text": self.summary_text,
            "rating_average": self.rating_average,
            "review_count_site": self.review_count_site,
            "visible_review_count": self.visible_review_count,
            "missing_review_count_estimate": self.missing_review_count_estimate,
            "difficulty": self.difficulty,
            "homework": self.homework,
            "grading": self.grading,
            "gain": self.gain,
        }
        if include_reviews:
            data["reviews"] = [review.to_dict() for review in self.reviews]
        return data

    @property
    def missing_review_count_estimate(self) -> int | None:
        if self.review_count_site is None or self.visible_review_count is None:
            return None
        return max(self.review_count_site - self.visible_review_count, 0)
