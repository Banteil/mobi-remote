'use strict';
/**
 * 오류 코드 한국어화.
 *
 * 게임/CLI는 { error, message }를 영어로 돌려준다.
 * 여기서 코드를 한국어 설명과 "그래서 뭘 해야 하는지"로 바꾼다.
 *
 * 같은 코드라도 명령에 따라 뜻이 달라지는 경우가 있어(not_found 등)
 * BY_COMMAND에서 덮어쓴다. 표에 없는 코드일 때만 영어 원문을 함께 보여준다.
 */

/** 공통 코드 → { text, hint } */
const COMMON = {
  /* 전송 계층 (CLI가 게임에 닿지 못한 경우) */
  disconnected: {
    text: '게임에 연결할 수 없습니다',
    hint: '게임이 실행 중인지, 설정에서 "MM AI 에이전트 활성화"가 켜져 있는지 확인하세요.',
  },
  unknown_command: {
    text: '게임이 모르는 명령입니다',
    hint: '게임이 업데이트되었을 수 있습니다. 콘솔 탭에서 명령 목록을 갱신해 보세요.',
  },
  unsupported_command: {
    text: '지원하지 않는 명령입니다',
    hint: '',
  },
  usage_error: { text: '명령 사용법이 잘못되었습니다', hint: '' },
  spawn_failed: {
    text: 'CLI를 실행하지 못했습니다',
    hint: 'MabinogiMobile_CLI.exe 경로를 확인하세요.',
  },
  busy: { text: '다른 명령이 실행 중입니다', hint: '끝난 뒤 다시 시도하세요.' },
  canceled: { text: '다른 명령이 이 동작을 대체했습니다', hint: '' },
  timeout: { text: '시간이 초과되어 중단되었습니다', hint: '잠시 후 다시 시도하세요.' },

  /* 본문 / 대상 */
  invalid_body: {
    text: '명령 본문 형식이 잘못되었습니다',
    hint: '필수 항목이 빠졌거나 이름이 다릅니다.',
  },
  not_found: {
    text: '해당 이름을 찾을 수 없습니다',
    hint: '게임에 표시되는 이름과 정확히 같아야 합니다. 직접 입력하지 말고 표에서 골라 주세요.',
  },
  invalid_count: {
    text: '횟수가 시설 상한을 넘었습니다',
    hint: '더 적은 횟수로 나눠서 시도하세요. (거부된 것이라 정령의 날개는 소모되지 않았습니다)',
  },

  /* 상태 */
  invalid_state: {
    text: '지금 멈출 수 있는 동작이 없습니다',
    hint: '게임에 정지 버튼이 떠 있을 때만 동작합니다. 바닥에 앉은 상태라면 "일어나기"를 쓰세요.',
  },
  not_sitting: {
    text: '앉아 있지 않습니다',
    hint: '/앉기 로 앉은 상태에서만 일어날 수 있습니다. 의자에 앉았다면 "정지"를 쓰세요.',
  },
  no_control_object: { text: '조작할 캐릭터가 없습니다', hint: '' },
  // 던전·전장뿐 아니라 "허상의 정박지"처럼 자동 이동이 막힌 특수 지역도 여기에 걸린다.
  // 채집·제작·가공은 모두 자동 이동으로 목적지까지 가는 것이 첫 단계이기 때문이다.
  not_in_field: {
    text: '이곳에서는 자동 이동을 쓸 수 없습니다',
    hint: '던전·전장·하우징이나 일부 특수 지역에서는 불가합니다. 일반 필드로 나간 뒤 다시 시도하세요.',
  },
  blocked: {
    text: '게임 화면에 처리할 것이 있어 중단되었습니다',
    hint: '게임에서 뜬 창이나 선택지를 정리한 뒤 다시 시도하세요.',
  },
  requires_user_interaction: {
    text: '게임에서 직접 조작해야 합니다',
    hint: '게임 화면을 확인하세요.',
  },
  overweight: {
    text: '소지 무게를 초과했습니다',
    hint: '창고에 넣거나 정리한 뒤 다시 시도하세요.',
  },
  no_route: {
    text: '그 장소로 가는 경로를 찾을 수 없습니다',
    hint: '다른 지역에 있거나 이동이 막혀 있을 수 있습니다.',
  },

  /* 비용 */
  not_enough_currency: {
    text: '재화가 부족합니다',
    hint: '정령의 날개 잔량을 확인하세요.',
  },
  cost_payment_failed: { text: '비용 지불에 실패했습니다', hint: '' },
  insufficient_transfer_cost: {
    text: '이동 비용이 부족합니다',
    hint: '정령의 날개 잔량을 확인하세요.',
  },

  /* 자격 / 해금 */
  insufficient_living_skill_level: {
    text: '생활 스킬 레벨이 부족합니다',
    // 조회로는 요구 레벨을 알 수 없다. 이 거부가 숫자를 말해 주는 유일한 통로다.
    hint: '해당 생활 스킬을 더 올려야 합니다.',
  },
  insufficient_facility_level: { text: '시설 레벨이 부족합니다', hint: '' },
  insufficient_decor_score: { text: '데코 점수가 부족합니다', hint: '' },
  crafting_locked: { text: '제작 기능이 아직 해금되지 않았습니다', hint: '' },
  not_available: { text: '지금은 사용할 수 없습니다', hint: '' },
  facility_not_found: {
    text: '해당 시설을 찾을 수 없습니다',
    hint: '시설이 해금되지 않았거나 접근할 수 없습니다.',
  },

  /* 재료 / 도구 */
  not_enough_ingredient: {
    text: '재료가 부족합니다',
    hint: '↻ 갱신 후 해당 항목의 "부족 재료" 칸을 확인하세요.',
  },
  ingredient_locked: {
    text: '재료가 잠겨 있습니다',
    hint: '게임에서 해당 아이템의 잠금을 풀어 주세요.',
  },
  required_consumable_missing: {
    text: '필요한 소모품이 없습니다',
    hint: '빈 병처럼 채집에 함께 쓰이는 아이템이 필요합니다.',
  },
  tool_missing: {
    text: '채집 도구가 없습니다',
    hint: '해당 채집에 맞는 도구를 갖춰 주세요.',
  },
  tool_broken: { text: '채집 도구가 망가졌습니다', hint: '도구를 수리하거나 교체하세요.' },

  /* 가공 작업 */
  no_altering: { text: '가공 작업이 없습니다', hint: '' },
  no_completed_work: { text: '완료된 가공 작업이 없습니다', hint: '' },
  no_completed_work_at_facility: {
    text: '그 시설에 완료된 작업이 없습니다',
    hint: '다른 시설의 작업을 수령해 보세요.',
  },
  not_completed_yet: {
    text: '아직 완료되지 않았습니다',
    hint: '남은 시간이 지난 뒤 다시 수령하세요.',
  },

  /* 내부 */
  query_failed: { text: '조회에 실패했습니다', hint: '' },
  unknown_query: { text: '알 수 없는 조회입니다', hint: '' },
};

/** 명령별로 뜻이 달라지는 코드 */
const BY_COMMAND = {
  execute_gathering: {
    not_found: {
      text: '채집할 수 없는 대상입니다',
      hint: '채집 탭 목록에 있는 이름이어야 합니다. 생활 스킬 레벨이 모자라면 목록에 나오지 않습니다.',
    },
    overweight: {
      text: '소지 무게를 초과해 채집을 멈췄습니다',
      hint: '이미 모은 양은 유지됩니다. 정리 후 이어서 채집하세요.',
    },
  },
  execute_crafting: {
    not_found: {
      text: '그런 제작 레시피가 없습니다',
      hint: '제작 탭에서 검색해 정확한 이름을 확인하세요. 옷감·목재·가죽·철괴 등은 제작이 아니라 가공입니다.',
    },
    not_available: { text: '지금 제작할 수 없는 레시피입니다', hint: '' },
    // 목록의 ✔는 1회 기준이라, 여러 회를 시도하면 여기서 걸린다.
    not_enough_ingredient: {
      text: '재료가 부족합니다',
      hint: '목록의 ✔는 1회 기준입니다. 횟수를 줄여 보세요. (거부된 것이라 정령의 날개는 소모되지 않았습니다)',
    },
  },
  execute_altering: {
    not_found: {
      text: '그런 가공 레시피가 없습니다',
      hint: '가공 탭에서 검색해 정확한 이름을 확인하세요.',
    },
    not_enough_ingredient: {
      text: '재료가 부족합니다',
      hint: '가공 탭에서 ↻ 갱신하면 그 레시피의 "부족 재료" 칸에 무엇이 얼마나 모자란지 나옵니다.',
    },
  },
  complete_altering_work: {
    not_found: {
      text: '그런 가공 대상이 없습니다',
      hint: '수령은 시설 단위입니다. 그 시설에서 만드는 아이템 이름을 지정하세요.',
    },
  },
  change_instrument: {
    not_found: { text: '보유하지 않은 악기입니다', hint: '연주 탭의 악기 목록에서 고르세요.' },
  },
  play_music_score: {
    not_found: { text: '보유하지 않은 악보입니다', hint: '연주 탭의 악보 목록에서 고르세요.' },
  },
};

/**
 * blocked 는 "게임 화면이 막고 있다"는 한 덩어리로 오지만, 본문의 kind 가 무엇이 막았는지
 * 알려 준다. 사용자가 할 일이 kind 마다 다르므로 (창 닫기 / 부활 고르기) 따로 푼다.
 */
const BLOCKED_KIND = {
  dead: {
    text: '커넥터가 쓰러진 상태로 보고 있습니다',
    hint: '실제로 쓰러져 있다면 게임에서 부활 방법을 고른 뒤 다시 시도하세요. 멀쩡히 살아 있는데도 계속 이 오류가 난다면 커넥터가 상태를 잘못 잡고 있는 것이니 게임에 다시 접속해 보세요.',
  },
};

/**
 * 오류를 한국어로 풀어 준다.
 * @param command 명령 이름 (없어도 됨)
 * @param error 오류 코드
 * @param rawMessage CLI가 준 영어 원문
 * @param data 응답 본문 (blocked의 kind, invalid_count의 maxCount 등을 꺼낸다)
 * @returns {{code, text, hint, raw, known}}
 */
function describe(command, error, rawMessage, data) {
  const code = String(error || '').trim();
  const entry = (BY_COMMAND[command] && BY_COMMAND[command][code]) || COMMON[code] || null;

  let text = entry ? entry.text : null;
  let hint = entry ? entry.hint : '';

  // 본문에 딸려 오는 값으로 설명을 구체화한다
  if (data && typeof data === 'object') {
    if (code === 'blocked' && data.kind) {
      const k = BLOCKED_KIND[data.kind];
      if (k) { text = k.text; hint = k.hint; }
      else hint = '막은 요소: ' + data.kind + '. ' + hint;
    }
    if (code === 'invalid_count' && data.maxCount !== undefined) {
      hint = '이 시설의 1회 상한은 ' + data.maxCount + '회입니다.';
    }
    if ((code === 'overweight' || code === 'blocked') && data.gained !== undefined) {
      hint = (hint ? hint + ' ' : '') + '중단 전까지 ' + data.gained + '개 획득했습니다.';
    }
  }

  // 생활 스킬 레벨은 **어느 조회로도 알 수 없다.** 이 거부 메시지가 요구 레벨을 말해 주는
  // 유일한 자리라(get_gatherable_items 명세: "returns insufficient_living_skill_level with
  // the required level"), 원문에 숫자가 있으면 그대로 붙여 준다. 한국어로 다듬다가
  // 숫자를 흘리면 얻을 수 있는 정보가 아예 사라진다.
  if (code === 'insufficient_living_skill_level' && /\d/.test(String(rawMessage || ''))) {
    hint = (hint ? hint + ' ' : '') + '게임 메시지: ' + rawMessage;
  }

  return {
    code: code,
    text: text || (code ? code : '알 수 없는 오류'),
    hint: hint || '',
    raw: rawMessage || '',
    known: !!entry,
  };
}

/**
 * 한 줄 요약 (토스트/로그용).
 * 번역이 있으면 한국어만 쓴다. 표에 없는 코드일 때만 영어 원문을 덧붙인다.
 */
function line(command, error, rawMessage, data) {
  const d = describe(command, error, rawMessage, data);
  const base = d.text + (d.hint ? ' — ' + d.hint : '');
  return d.known ? base : base + (d.raw ? ' (' + d.raw + ')' : '');
}

/**
 * 레시피가 왜 막혔는지.
 *
 * get_craftable_items / get_alterable_items 의 Reason 은 **분류만** 준다.
 * "생활 레벨 몇이 필요한가"도 "시설 레벨 몇인가"도 숫자로는 오지 않는다.
 * 그래도 무엇 때문에 막혔는지는 알 수 있으니, 코드를 그대로 내보내지 말고 풀어 준다.
 */
const RECIPE_REASON = {
  not_enough_ingredient: '재료 부족',
  insufficient_living_skill_level: '생활 레벨 부족',
  insufficient_facility_level: '시설 레벨 부족',
  insufficient_decor_score: '데코 점수 부족',
};

/** 모르는 코드는 그대로 돌려준다 — 정보를 지우는 것보다 낫다. */
function reasonText(code) {
  if (!code) return '';
  return RECIPE_REASON[code] || String(code);
}

module.exports = { describe, line, COMMON, BY_COMMAND, reasonText, RECIPE_REASON };
