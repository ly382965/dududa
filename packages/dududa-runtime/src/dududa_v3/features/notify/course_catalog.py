BB_ORIGIN = "https://www.bb.ustc.edu.cn"
BB_PORTAL_URL = BB_ORIGIN + "/webapps/portal/execute/tabs/tabAction?tab_tab_group_id=_1_1"
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


def blackboard_course_id(url):
    """Recognize only course navigation URLs, never assessment/attempt links."""
    import re
    from urllib.parse import parse_qs, urlsplit

    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.hostname != "www.bb.ustc.edu.cn"
        or parts.username
        or parts.password
        or parts.port not in (None, 443)
    ):
        return None
    query = parse_qs(parts.query)
    if parts.path == "/webapps/blackboard/execute/launcher":
        if query.get("type") != ["Course"] or query.get("url") not in (None, [""]):
            return None
        values = query.get("id", [])
    elif parts.path in {
        "/webapps/blackboard/content/listContent.jsp",
        "/webapps/blackboard/execute/courseMain",
    }:
        values = query.get("course_id", [])
        if parts.path.endswith("/listContent.jsp") and not query.get("content_id"):
            return None
    else:
        return None
    if len(values) == 1 and re.fullmatch(r"_\d+_\d+", values[0]):
        return values[0]
    return None


def validate_courses(courses):
    from urllib.parse import urlsplit

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
            if not blackboard_course_id(course["url"]):
                raise ValueError("invalid_blackboard_course_url")
        elif course["kind"] == "website":
            if course["url"] not in {ALGORITHM_URL, NETWORK_URL}:
                raise ValueError("unsupported_course_website")
        elif course["kind"] not in {"graduate", "pending"}:
            raise ValueError("unsupported_course_source")
        if parts.username or parts.password or parts.port not in (None, 80, 443):
            raise ValueError("invalid_course_url")
    return courses
