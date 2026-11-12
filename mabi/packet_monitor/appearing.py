"""등장 캐릭터 메시지(char.appearing) 본문 읽기 — 표가 읽지 못하는 캐릭터 이름과 '내 캐릭터인가'."""
import struct

_WEAPON = struct.pack("<I", 12) + "Weapon".encode("utf-16le")  # 등장 캐릭터의 도구 목록 첫 항목
_ONE = bytes.fromhex("0000803f00000000")                          # 도구 목록 뒤, 이름 바로 앞 (f32 1.0 + 0)


def _ascii16_end(b: bytes, i: int) -> int | None:
    """i 에 u32 바이트 길이 + UTF-16 영문 문자열이 있으면 그 끝 위치."""
    if i + 4 > len(b):
        return None
    n = struct.unpack_from("<I", b, i)[0]
    if not (2 <= n <= 64 and n % 2 == 0) or i + 4 + n > len(b):
        return None
    s = b[i + 4:i + 4 + n]
    if any(s[x + 1] or not 0x41 <= s[x] <= 0x7A for x in range(0, n, 2)):
        return None
    return i + 4 + n


def appearing_name(body: bytes) -> str | None:
    """등장 캐릭터 메시지에서 캐릭터 이름. 이름 앞에 길이가 들쭉날쭉한 도구 목록이 있어 항목을 따라간다:
    [영문 도구 이름][u32 칸][u32 n][n×u32][u32 c][c×8 색] … 다음 [00 00 80 3f 00 00 00 00][u32 바이트 길이][UTF-16 이름].
    캡처 5개의 등장 메시지 427건 모두 이렇게 읽힘 (2026-10-25). 모양이 다르면 None."""
    try:
        i = body.find(_WEAPON)
        if i < 0:
            return None
        while (j := _ascii16_end(body, i)) is not None:
            n = struct.unpack_from("<I", body, j + 4)[0]
            if n > 16:
                return None
            j += 8 + 4 * n
            c = struct.unpack_from("<I", body, j)[0]
            if c > 32:
                return None
            i = j + 4 + 8 * c
        k = body.find(_ONE, i, i + 64)
        if k < 0:
            return None
        n = struct.unpack_from("<I", body, k + 8)[0]
        if not (2 <= n <= 40 and n % 2 == 0):
            return None
        return body[k + 12:k + 12 + n].decode("utf-16le")
    except (struct.error, UnicodeDecodeError):
        return None


def appearing_is_mine(body: bytes, char_id: int | None) -> bool:
    """등장 캐릭터 메시지가 내 캐릭터의 것인지. 캐릭터 자신의 기록은 [u64 고유 번호][u32 3][u32 바이트 길이][UTF-16 이름].
    파티원 등장에도 파티 명단에 내 고유 번호가 들어 있지만 그 뒤는 [u32 2] — 고유 번호만 찾으면 파티원을 '나' 로 안다
    (11-03 abyss_runs 8개: 내 등장 43건 모두 3, 파티원 등장의 내 번호는 2. 파티원 자신의 기록도 3)."""
    return char_id is not None and struct.pack("<QI", char_id, 3) in body
