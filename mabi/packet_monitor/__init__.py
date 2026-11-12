"""게임 서버 → 클라이언트 패킷을 받아 상태(맵 이동, 던전 상태 등)를 알려 준다. 화면 인식을 보조하는 신호.

받기만 한다 — Npcap(wpcap.dll)의 수신 함수만 선언하고, 보내는 함수(pcap_sendpacket 등)는 쓰지 않는다.
필터는 'tcp src port 16000' (게임 서버가 보내는 쪽). 서버 주소는 맵(필드·던전 인스턴스)마다 바뀐다.

스트림: 연결 처음에 인사 블록 'MMCG'[길이 u32][내용] 하나, 그 뒤로 [메시지 번호 u32][길이 u32][압축 u8][본문],
압축 1 = Brotli. 해석은 packet_table, 어긋남 기록은 packet_diag.
Npcap 이 없거나 표·키가 없으면 꺼진 채(status)로 있고, 봇은 화면 인식만으로 돈다 — 패킷 신호는 늘 '있으면 빠르게'.

봇은 프로세스 하나에 감시 하나를 같이 쓴다 (shared). 큐는 카드마다 Bot 을 새로 만들기 때문.

나눈 자리:
  capture     Npcap 으로 TCP 조각 받기 (수신 함수만)
  stream      TCP 머리 벗기기(parse_tcp) · 조각 → 메시지(Stream)
  appearing   등장 캐릭터 메시지에서 이름·'내 캐릭터인가'
  state       PacketState · Seen · history 사본
  events      이벤트 → 상태 반영 (Events.apply)
  cli_sync    CLI 답과 맞추기 (merge_cli · reconcile · forget)
  link_watch  서버 연결 끊김 단서 로그
  monitor     PacketMonitor 본체 (캡처 스레드, wait·find·saw …) · shared · current

밖에서는 아래 이름을 이 패키지에서 가져다 쓴다. 낮은 부품(Stream·parse_tcp …)은 그 모듈에서.
"""
from .capture import NPCAP_DIR
from .cli_sync import CLI_LAG, map_contradicts
from .monitor import PacketMonitor, current, game_metadata, shared
from .state import PacketState, Seen

__all__ = ["NPCAP_DIR", "CLI_LAG", "map_contradicts", "PacketMonitor", "current", "game_metadata", "shared",
           "PacketState", "Seen"]
