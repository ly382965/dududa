BB_ORIGIN = "https://www.bb.ustc.edu.cn"
ALGORITHM_URL = "http://home.ustc.edu.cn/~wx309/lecture/alg2026/"
NETWORK_URL = "https://acn-2026.github.io/"
DEFAULT_COURSES = [
    {
        "id": "algorithms",
        "name": "算法设计与分析",
        "kind": "website",
        "url": ALGORITHM_URL,
    },
    {
        "id": "math",
        "name": "计算机应用数学",
        "kind": "blackboard",
        "url": BB_ORIGIN
        + "/webapps/blackboard/content/listContent.jsp?course_id=_37248_1&content_id=_187100_1&mode=reset",
    },
    {
        "id": "ml",
        "name": "机器学习",
        "kind": "blackboard",
        "url": BB_ORIGIN
        + "/webapps/blackboard/content/listContent.jsp?course_id=_37268_1&content_id=_187140_1&mode=reset",
    },
    {
        "id": "ai",
        "name": "高级人工智能",
        "kind": "graduate",
        "url": "https://yjs1.ustc.edu.cn/gsapp/sys/wdzyappustc/*default/index.do",
    },
    {
        "id": "systems",
        "name": "计算机系统",
        "kind": "blackboard",
        "url": BB_ORIGIN
        + "/webapps/blackboard/content/listContent.jsp?course_id=_37252_1&content_id=_187108_1&mode=reset",
    },
    {"id": "combinatorics", "name": "组合数学", "kind": "pending", "url": ""},
    {
        "id": "networks",
        "name": "高级计算机网络",
        "kind": "website",
        "url": NETWORK_URL,
    },
]


def validate_courses(courses):
    from urllib.parse import parse_qs, urlsplit

    ids = set()
    for course in courses:
        if not isinstance(course, dict) or not all(
            isinstance(course.get(k), str) for k in ("id", "name", "kind", "url")
        ):
            raise ValueError("invalid_course_configuration")
        if not course["id"] or course["id"] in ids or not course["name"]:
            raise ValueError("duplicate_or_empty_course_id")
        ids.add(course["id"])
        parts = urlsplit(course["url"])
        if course["kind"] == "blackboard":
            if (
                parts.scheme != "https"
                or parts.hostname != "www.bb.ustc.edu.cn"
                or parts.path != "/webapps/blackboard/content/listContent.jsp"
                or not all(
                    parse_qs(parts.query).get(k) for k in ("course_id", "content_id")
                )
            ):
                raise ValueError("invalid_blackboard_course_url")
        elif course["kind"] == "website":
            if course["url"] not in {ALGORITHM_URL, NETWORK_URL}:
                raise ValueError("unsupported_course_website")
        elif course["kind"] not in {"graduate", "pending"}:
            raise ValueError("unsupported_course_source")
        if parts.username or parts.password or parts.port not in (None, 80, 443):
            raise ValueError("invalid_course_url")
    return courses
