"""게임 문자열에 섞여 오는 Unity rich text (리모콘 src/richtext.js).

get_items 의 DisplayName 에 <color=#RRGGBB>★8</color>, 퀘스트 목표에 <color=orange>…</color> 가 온다.
색은 등급이라 화면에서는 살리고, 검색·비교에서는 벗긴다.
주의: DisplayName 은 게임에 되돌려 보내는 식별자다. 보낼 때는 항상 원문(name_raw) 그대로.
"""
import re

ANY_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
COLOR_OPEN = re.compile(r"^<color\s*=\s*(#[0-9a-fA-F]{3,8}|[a-zA-Z]+)\s*>$")
COLOR_CLOSE = re.compile(r"^</color\s*>$", re.I)


def strip(s):
    if not isinstance(s, str) or "<" not in s:
        return s
    return ANY_TAG.sub("", s)


def has_tags(s) -> bool:
    return isinstance(s, str) and bool(ANY_TAG.search(s))


def segments(s) -> list[tuple[str, str | None]]:
    """[(글자, 색 또는 None)] — 화면이 색을 살려 그릴 때 쓴다."""
    if not isinstance(s, str):
        return [("" if s is None else str(s), None)]
    if "<" not in s:
        return [(s, None)]
    out: list[list] = []
    stack: list[str] = []

    def push(text):
        if not text:
            return
        color = stack[-1] if stack else None
        if out and out[-1][1] == color:
            out[-1][0] += text
        else:
            out.append([text, color])

    last = 0
    for m in ANY_TAG.finditer(s):
        push(s[last:m.start()])
        tag = m.group(0)
        op = COLOR_OPEN.match(tag)
        if op:
            stack.append(op.group(1))
        elif COLOR_CLOSE.match(tag) and stack:
            stack.pop()
        last = m.end()
    push(s[last:])
    return [tuple(x) for x in out] or [("", None)]


def to_html(s) -> str:
    """Qt 서식 글자(QLabel 등)용. 글자는 이스케이프한다."""
    import html
    return "".join(f'<span style="color:{c}">{html.escape(t)}</span>' if c else html.escape(t) for t, c in segments(s))
