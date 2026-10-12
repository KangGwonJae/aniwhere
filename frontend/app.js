const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const messages = $('#messages');
const suggestions = $('#suggestions');
const question = $('#question');
const composer = $('#composer');
const drawer = $('#drawer');
const toast = $('#toast');
const installButton = $('#install-app');
const installGuide = $('#install-guide');
const installGuideAction = $('#install-guide-action');
const installGuideClose = $('#install-guide-close');
const spoilerCutin = $('#spoiler-cutin');
const cutinReturn = $('#cutin-return');
const transitionSfx = $('#transition-sfx');
const onboarding = $('#onboarding');
let installPrompt = null;
let spoilerObserver = null;
let mode = 'episode';
let persona = 'midoriya';
let busy = false;
let step = 0;
let chatHistory = [];
const HERO_SERIES_ID = 'tmdb:65930';
let activeSeriesId = HERO_SERIES_ID;
const RECORD_KEY = 'aniwhere-demo-watch-record';
const ONBOARDING_KEY = 'aniwhere-onboarding-completed';
const WATCH_RECORDS_KEY = 'aniwhere-watch-records';
let savedWatchRecords = [];
try { savedWatchRecords = JSON.parse(localStorage.getItem(WATCH_RECORDS_KEY) || '[]'); } catch { savedWatchRecords = []; }
let hasRecord = localStorage.getItem(RECORD_KEY) === '1' || savedWatchRecords.length > 0;

const onboardingTitles = {
  mha: { title:'나의 히어로 아카데미아', image:'my-hero-academia.jpg', seasons:[['1기',13],['2기',25],['3기',25],['4기',25],['5기',25],['6기',25],['7기',21]], defaultSeason:3, defaultEpisode:11 },
  aot: { title:'진격의 거인', image:'eren-spoiler-user.png', seasons:[['1기',25],['2기',12],['3기 Part 1',12],['3기 Part 2',10],['The Final Season',35]], defaultSeason:1, defaultEpisode:14 },
  hxh: { title:'헌터×헌터', image:'hxh-gon.png', seasons:[['2011년판',148]], defaultSeason:1, defaultEpisode:63 },
  steins: { title:'슈타인즈 게이트', image:'okabe-card-user.png', seasons:[['본편',24],['제로',23]], defaultSeason:1, defaultEpisode:12 },
  naruto: { title:'나루토', image:'naruto-history-user.png', seasons:[['나루토',220],['질풍전',500]], defaultSeason:1, defaultEpisode:50 }
};
const onboardingMemoryMatches = {
  mha: [
    { keywords:['올마이트','올 포 원','손가락','카미노'], season:3, episode:11, confidence:'높음', evidence:'올마이트와 올 포 원의 결전 뒤 화면을 향해 손가락을 가리키는 장면' },
    { keywords:['학교 축제','문화제','에리'], season:4, episode:23, confidence:'보통', evidence:'유에이를 배경으로 한 학교 축제와 에리의 장면' }
  ],
  aot: [
    { keywords:['여성형','숲','리바이반'], season:1, episode:22, confidence:'높음', evidence:'거대 나무 숲에서 여성형 거인과 마주하는 흐름' },
    { keywords:['바다','바닷가'], season:3, episode:22, confidence:'높음', evidence:'조사병단이 바다에 도착하는 장면' }
  ],
  hxh: [
    { keywords:['비스케','그리드','수련'], season:1, episode:63, confidence:'높음', evidence:'그리드 아일랜드에서 비스케가 곤과 키르아의 수련을 시작하는 구간' },
    { keywords:['히소카','천공','곤 싸움'], season:1, episode:36, confidence:'높음', evidence:'천공격투장에서 곤과 히소카가 대결하는 구간' }
  ],
  steins: [
    { keywords:['문자','메일','과거','전자레인지'], season:1, episode:9, confidence:'보통', evidence:'D메일과 과거 변화의 규칙을 확인해 가는 구간' },
    { keywords:['마유리','시계','멈춰'], season:1, episode:12, confidence:'높음', evidence:'마유리와 관련된 큰 전환점이 시작되는 구간' }
  ],
  naruto: [
    { keywords:['중급닌자','시험','가아라'], season:1, episode:67, confidence:'높음', evidence:'중급 닌자 시험과 가아라 관련 사건이 이어지는 구간' },
    { keywords:['사스케','탈환'], season:1, episode:110, confidence:'보통', evidence:'사스케를 쫓는 탈환 임무가 시작되는 구간' }
  ]
};
const onboardingSelection = new Map();

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }
  });
  if (!response.ok) {
    let detail = '서버 요청에 실패했습니다.';
    try { detail = (await response.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return response.status === 204 ? null : response.json();
}

function escapeHtml(value = '') {
  return String(value).replace(/[&<>'"]/g, character => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' })[character]);
}

const mock = {
  record: { series_id: 'tmdb:65930', title: '나의 히어로 아카데미아', seen_ep: 49, season: 3, episode: 11, rating: null },
  providers: [{ name: '시즌 3', providers: ['Laftel', 'Netflix'], checked_at: '2026-10-05' }],
  characters: [
    ['미도리야 이즈쿠', '올마이트에게 힘을 물려받은 학생. 위험한 순간 먼저 몸이 움직여요.'],
    ['올마이트', '평화의 상징이라 불리는 히어로이자 미도리야의 스승이에요.'],
    ['바쿠고 카츠키', '폭발 능력을 가진 미도리야의 소꿉친구이자 라이벌이에요.']
  ]
};

const hunterDictionary = [
  ['헌터','헌터·자격','희귀 생물, 보물, 유적, 범죄자 등 특정 대상을 탐색하거나 전문 분야를 연구하는 사람.',1],
  ['헌터 협회','헌터·자격','헌터 시험을 주관하고 헌터 자격을 관리하는 비정부 조직.',1],
  ['헌터 시험','헌터·자격','프로 헌터가 되기 위해 치르는 시험. 체력뿐 아니라 판단력·지식·관찰력도 평가한다.',1],
  ['헌터 라이선스','헌터·자격','헌터 시험 합격자에게 발급되는 자격증. 제한된 장소와 정보에 접근할 수 있다.',1],
  ['싱글 헌터','헌터·자격','특정 분야에서 뛰어난 업적을 인정받아 별 하나를 받은 헌터.',2],
  ['더블 헌터','헌터·자격','협회 요건을 충족하고 후배를 육성한 헌터에게 주어지는 별 두 개의 등급.',3],
  ['트리플 헌터','헌터·자격','여러 분야에서 뛰어난 업적을 남긴 헌터에게 주어지는 별 세 개의 등급.',3],
  ['쿠쿠르 마운틴','세계관','파도키아 공화국의 휴화산. 세계적인 암살자 가문 조르딕의 저택이 자리한다.',1],
  ['조르딕 가문','세계관','쿠쿠르 마운틴에 거주하는 암살자 가문. 가족들은 어려서부터 암살 기술을 훈련받는다.',1],
  ['시험의 문','세계관','조르딕 가문의 사유지로 들어가는 여러 겹의 거대한 정문.',1],
  ['천공격투장','세계관','격투가들이 대결하며 상위 층으로 올라가는 초고층 격투 시설.',2],
  ['쿠르타족','세계관','강한 감정에 반응해 눈이 선명한 붉은색으로 변하는 특징을 지닌 소수 민족.',3],
  ['붉은 눈 · 비색의 눈','세계관','쿠르타족이 격한 감정을 느낄 때 나타나는 특별한 눈의 색.',3],
  ['환영여단','세계관','강력한 넨 능력자들로 구성된 도적 집단. 단장과 단원을 거미에 비유한다.',3],
  ['거미','세계관','환영여단을 가리키는 별칭이자 조직의 상징.',3],
  ['유성가','세계관','버려진 물건과 사람들이 모여 형성된 거대한 공동체.',3],
  ['요크신 시티','세계관','대규모 경매가 열려 수집가와 상인이 모이는 도시.',3],
  ['십로두','세계관','마피아 사회를 이끄는 열 명의 수장.',3],
  ['음수','세계관','십로두가 선발한 최정예 부하들로 구성된 넨 전투 집단.',3],
  ['넨','넨 기본','몸에서 나오는 생명 에너지인 오라를 다루는 기술.',2],
  ['오라','넨 기본','생명체가 지닌 생명 에너지. 넨 수련자는 흐름과 양을 조절해 활용한다.',2],
  ['사대행','넨 기본','넨의 기초를 이루는 텐·제츠·렌·하츠 네 가지 수행의 총칭.',2],
  ['텐 · 纏','넨 기본','몸에서 흘러나오는 오라를 몸 주변에 머물게 하는 기술.',2],
  ['제츠 · 絶','넨 기본','몸 밖으로 나오는 오라를 차단해 기척을 숨기는 기술.',2],
  ['렌 · 練','넨 기본','평소보다 많은 양의 오라를 끌어내는 기술.',2],
  ['하츠 · 発','넨 기본','오라를 자신의 성질과 목적에 맞게 발휘하는 기술.',2],
  ['수견식','넨 기본','물과 잎에 오라를 가해 나타나는 변화로 자신의 넨 계통을 판별하는 방법.',2],
  ['육성도','넨 기본','여섯 넨 계통의 관계와 습득 효율을 나타낸 도표.',2],
  ['교 · 凝','넨 응용','오라를 눈이나 공격·방어 부위 같은 신체의 특정 부위에 집중시키는 기술.',2],
  ['인 · 隠','넨 응용','능력을 유지하면서 오라의 존재를 알아차리기 어렵게 숨기는 기술.',3],
  ['엔 · 円','넨 응용','오라를 넓게 펼쳐 범위 안 대상의 형태와 움직임을 감지하는 기술.',3],
  ['슈 · 周','넨 응용','도구나 물체를 오라로 감싸 강화하고 보호하는 기술.',3],
  ['코 · 硬','넨 응용','오라를 한 부위에 집중하는 대신 다른 부위가 무방비가 되는 기술.',3],
  ['켄 · 堅','넨 응용','많은 양의 오라를 몸 전체에 유지해 전신을 보호하는 기술.',3],
  ['류 · 流','넨 응용','상황에 맞춰 신체 각 부위의 오라 배분을 빠르게 바꾸는 기술.',3],
  ['강화계','넨 계통','몸이나 물건이 지닌 힘과 기능을 강화한다. 수견식에서는 물의 양이 늘어난다.',2],
  ['변화계','넨 계통','오라의 성질이나 형태를 바꾼다. 수견식에서는 물의 맛이 변한다.',2],
  ['구현화계','넨 계통','오라를 구체적인 물체로 만든다. 수견식에서는 물속에 불순물이 생긴다.',2],
  ['조작계','넨 계통','물체나 생물을 조종한다. 수견식에서는 잎이 움직인다.',2],
  ['특질계','넨 계통','다른 다섯 계통으로 분류할 수 없는 특수한 능력의 계통.',2],
  ['방출계','넨 계통','오라를 몸에서 분리해 멀리 보내고 유지하는 데 적합하다.',2],
  ['제약','조건·현상','능력의 대상, 상황, 횟수 등을 제한해 힘을 높이는 조건.',3],
  ['서약 · 맹세','조건·현상','규칙을 지키겠다는 강한 결의와 위반 시의 대가를 거는 원리.',3],
  ['제약과 서약','조건·현상','제한과 대가, 사용자의 결의를 통해 넨 능력을 강화하는 원리.',3],
  ['제넨','조건·현상','다른 사람이나 대상에 걸린 넨의 영향을 제거하거나 해소하는 행위.',4],
  ['사후 넨','조건·현상','사용자가 죽은 뒤에도 강한 감정이나 의지로 남아 있는 넨.',4],
  ['번지껌 · 번지검','대표 능력','히소카가 오라에 껌의 접착력과 고무의 탄성을 부여하는 능력.',2],
  ['도 깜짝 텍스처','대표 능력','히소카가 표면의 외관을 다른 재질이나 무늬처럼 보이게 하는 능력.',2],
  ['짜잔권 · 자잔권','대표 능력','곤이 가위바위보를 바탕으로 만든 넨 능력.',4],
  ['짜잔권 · 바위','대표 능력','주먹에 오라를 집중해 강력한 타격을 가하는 강화계 공격.',4],
  ['짜잔권 · 가위','대표 능력','손가락 끝에서 오라를 칼날처럼 뻗는 변화계 공격.',4],
  ['짜잔권 · 보','대표 능력','손바닥에서 오라 덩어리를 쏘는 방출계 공격.',4],
  ['칸무루 · 신속','대표 능력','키르아가 전기 성질의 오라로 움직임과 반응을 극도로 빠르게 하는 능력.',4],
  ['전광석화','대표 능력','칸무루의 사용 방식 중 하나로, 사용자의 의지에 따라 빠르게 이동한다.',4],
  ['질풍신뢰','대표 능력','외부 자극에 신체가 자동 반응하도록 하는 칸무루의 사용 방식.',4],
  ['그리드 아일랜드 · G.I.','그리드 아일랜드','넨 능력자가 플레이하며 지정 카드를 모아 공략하는 특별한 게임.',4],
  ['북 · Book','그리드 아일랜드','그리드 아일랜드에서 카드 바인더를 불러오는 명령어.',4],
  ['게인 · Gain','그리드 아일랜드','카드화된 물건을 원래 형태로 되돌리는 명령어.',4],
  ['지정 포켓 카드','그리드 아일랜드','게임 공략을 위해 정해진 슬롯에 수집해야 하는 100종의 카드.',4],
  ['스펠 카드 · 주문 카드','그리드 아일랜드','이동·연락·탐색·강탈 등 특별한 효과를 일으키는 카드.',4]
];

const hunterCheckpoints = {
  25: '초기 동료와 가족 · 25화',
  63: '요크신·그리드 아일랜드 · 63화',
  111: '키메라 앤트 작전 · 111화',
  139: '후반 관계 포함 · 139화'
};

const hunterTermEpisodes = { 1: 21, 2: 36, 3: 58, 4: 75 };

const hunterCharacters = {
  gon: { name:'곤', image:'hxh-gon.png', episode:1, x:40, y:38, group:'main', description:'아버지를 만나기 위해 헌터를 목표로 여행을 시작한 소년. 솔직하고 호기심이 많으며, 친구를 소중하게 여긴다.' },
  killua: { name:'키르아', image:'hxh-killua.png', episode:4, x:60, y:38, group:'main', description:'헌터 시험에서 곤과 만난 동갑내기 소년. 뛰어난 신체 능력과 냉정한 판단력을 지녔다.', later:'조르딕 가문의 셋째 아들. 가족이 정한 암살자의 삶에서 벗어나 곤과 함께 자신의 길을 찾고 싶어 한다.' },
  leorio: { name:'레오리오', image:'hxh-leorio.png', episode:4, x:40, y:62, group:'main', description:'의사가 되기를 꿈꾸는 헌터 지망생. 거친 말투와 달리 정이 많고 동료들을 적극적으로 돕는다.' },
  kurapika: { name:'크라피카', image:'hxh-kurapika.png', episode:4, x:60, y:62, group:'main', description:'쿠르타족 출신의 소년. 동족의 붉은 눈을 되찾고 환영여단을 추적하기 위해 헌터를 목표로 한다.' },
  netero: { name:'네테로', image:'hxh-netero.png', episode:7, x:17, y:21, group:'growth', description:'헌터 협회의 회장. 장난스러운 태도 뒤에 오랜 수련으로 쌓은 실력과 경험을 지녔다.' },
  biske: { name:'비스케', image:'hxh-biske.png', episode:63, x:18, y:78, group:'growth', description:'그리드 아일랜드에서 곤과 키르아를 지도하는 숙련된 헌터. 귀여운 외모와 달리 엄격하고 실전적인 스승이다.' },
  hisoka: { name:'히소카', image:'hxh-hisoka.png', episode:5, x:83, y:20, group:'tension', description:'강한 상대와 싸우는 것을 즐기는 위험한 인물. 재능 있는 사람의 성장을 지켜보며 흥미를 느낀다.' },
  illumi: { name:'이르미', image:'hxh-illumi.png', episode:20, x:84, y:47, group:'tension', description:'조르딕 가문의 장남이자 키르아의 형. 키르아가 암살자로 살아야 한다고 생각하며 동생의 선택에 개입한다.' },
  troupe: { name:'환영여단', image:'hxh-phantom-troupe.png', episode:41, x:82, y:78, group:'tension collective', description:'크로로가 이끄는 강력한 도적 집단. ‘거미’라는 상징으로 알려져 있으며, 단원들은 각자의 넨 능력을 사용한다.' },
  zeno: { name:'제노 조르딕', image:'hxh-zeno.png', episode:24, x:16, y:51, group:'family', description:'키르아의 할아버지이자 조르딕 가문의 베테랑 암살자. 풍부한 경험과 뛰어난 전투 능력을 지녔다.' }
};

const hunterRelations = [
  ['gon','killua','친구·동료','헌터 시험에서 만나 가까워진 동갑내기 친구. 함께 도전하고 서로를 도우며 성장한다.',4,'friend'],
  ['gon','leorio','친구·동료','헌터 시험을 향하는 여정에서 만난 사이. 서로의 목표를 존중하고 어려운 순간에 힘이 되어 준다.',4,'friend'],
  ['gon','kurapika','친구·동료','헌터 시험을 준비하며 만난 동료. 서로 다른 목표를 지녔지만 신뢰를 쌓아 간다.',4,'friend'],
  ['leorio','kurapika','티격태격하는 동료','처음에는 의견 충돌을 겪지만, 서로의 사정을 알게 되면서 이해와 신뢰를 쌓는다.',4,'friend'],
  ['killua','leorio','친구·동료','헌터 시험을 함께 겪은 동료. 이후 곤과 키르아를 돕는 관계로 이어진다.',25,'friend'],
  ['killua','kurapika','친구·동료','헌터 시험에서 만난 동료. 함께 어려움을 겪으며 서로를 신뢰하게 된다.',25,'friend'],
  ['netero','gon','실력 시험','곤과 공을 빼앗는 놀이를 하며 그의 도전 정신과 자질을 살펴본다.',7,'mentor'],
  ['netero','killua','실력 시험','키르아와 공을 빼앗는 놀이를 하며 실력 차이를 보여 준다.',7,'mentor'],
  ['illumi','killua','형·통제','키르아가 암살자로 살아야 한다고 주장하며, 동생의 친구 관계와 선택을 제한하려 한다.',20,'conflict'],
  ['killua','illumi','두려움','형의 압박에 위축되며 자신의 바람을 쉽게 주장하지 못한다.',20,'conflict'],
  ['gon','illumi','반발','키르아의 의사를 부정하는 이르미에게 맞서며 친구를 옹호한다.',21,'conflict'],
  ['zeno','killua','할아버지·손자','조르딕 가문의 가족 관계. 제노는 키르아의 친할아버지다.',24,'family'],
  ['hisoka','gon','성장에 대한 관심','곤의 잠재력을 높이 평가하며, 더 강해진 곤과 싸우기를 기대한다.',36,'mentor'],
  ['gon','hisoka','도전','히소카와의 실력 차이를 의식하면서도, 자신의 힘으로 맞서고 싶어 한다.',36,'conflict'],
  ['kurapika','troupe','복수·추적','동족을 해친 환영여단을 추적하고, 빼앗긴 붉은 눈을 되찾으려 한다.',41,'conflict'],
  ['biske','gon','스승·제자','곤의 재능을 알아보고 넨의 기초와 응용을 엄격하게 훈련시킨다.',63,'mentor'],
  ['biske','killua','스승·제자','키르아의 능력을 평가하고, 실전에서 활용할 수 있도록 넨 수련을 지도한다.',63,'mentor'],
  ['netero','zeno','임무 협력','네테로가 제노에게 일을 의뢰하며, 두 사람은 같은 작전에 참여한다.',111,'alliance'],
  ['hisoka','troupe','소속·개인적 목적','히소카는 여단에 속해 있지만, 조직에 대한 충성보다 단장과 싸우려는 개인적 목적이 앞선다.',45,'alliance'],
  ['hisoka','kurapika','이해관계에 따른 협력','환영여단과 관련된 서로의 목적을 위해 정보를 교환하고 협력한다.',45,'alliance'],
  ['hisoka','illumi','이해관계에 따른 협력','서로를 알고 지내며, 필요에 따라 도움을 주고받는다.',139,'alliance']
];

function showOnboardingStep(name) {
  $$('[data-onboarding-step]').forEach(step => {
    const active = step.dataset.onboardingStep === name;
    step.hidden = !active;
    step.classList.toggle('active', active);
  });
  const labels = { welcome:'처음 만나는 중 · 1/2', titles:'시청 목록 · 2/2' };
  $('#onboarding-progress').textContent = labels[name];
  $('.onboarding-shell').scrollTop = 0;
}

function updateOnboardingSelection() {
  $$('[data-onboarding-title]').forEach(button => {
    const record = onboardingSelection.get(button.dataset.onboardingTitle);
    button.classList.toggle('selected', Boolean(record));
    const summary = $('[data-onboarding-summary]', button);
    if (!record) summary.textContent = '';
    else if (record.status === 'planned') summary.textContent = '보고 싶어요 · 아직 안 봄';
    else {
      const status = record.status === 'completed' ? '다 봤어요' : '시청 중';
      summary.textContent = `${status} · ${record.season_name} ${record.seen_ep}화`;
    }
  });
  $('#onboarding-selection-count').textContent = `${onboardingSelection.size}개 저장`;
  $('#onboarding-to-details').disabled = onboardingSelection.size === 0;
}

function onboardingEpisodeOptions(total, selected) {
  return Array.from({ length: total }, (_, index) => index + 1).map(episode => `<option value="${episode}"${episode === selected ? ' selected' : ''}>${episode}화</option>`).join('');
}

function findOnboardingMemoryMatch(id, question) {
  const normalized = question.replace(/\s+/g, '').toLowerCase();
  return (onboardingMemoryMatches[id] || []).map(match => ({
    ...match,
    score: match.keywords.filter(keyword => normalized.includes(keyword.replace(/\s+/g, '').toLowerCase())).length
  })).sort((a, b) => b.score - a.score).find(match => match.score > 0) || null;
}

function openOnboardingEditor(id) {
  const title = onboardingTitles[id];
  if (!onboardingSelection.has(id)) onboardingSelection.set(id, {
    series_id:id, title:title.title, status:'watching', season:title.defaultSeason,
    season_name:title.seasons[title.defaultSeason - 1][0], seen_ep:title.defaultEpisode, rating:null
  });
  const record = onboardingSelection.get(id);
  const season = title.seasons[record.season - 1] || title.seasons[0];
  const editor = $('#onboarding-editor');
  editor.hidden = false;
  editor.dataset.editing = id;
  editor.innerHTML = `<header><div><small>시청 상태 설정</small><h3>${title.title}</h3></div><button type="button" data-editor-close aria-label="설정 닫기">×</button></header>
    <div class="onboarding-status" role="group" aria-label="시청 상태">
      <button type="button" data-watch-status="planned" class="${record.status === 'planned' ? 'active' : ''}">보고 싶어요<small>아직 안 봄</small></button>
      <button type="button" data-watch-status="watching" class="${record.status === 'watching' ? 'active' : ''}">시청 중<small>회차 기록</small></button>
      <button type="button" data-watch-status="completed" class="${record.status === 'completed' ? 'active' : ''}">다 봤어요<small>완료</small></button>
    </div>
    <div class="onboarding-picker ${record.status === 'planned' ? 'disabled' : ''}">
      <label>시즌<select id="onboarding-season">${title.seasons.map(([name], index) => `<option value="${index + 1}"${index + 1 === record.season ? ' selected' : ''}>${name}</option>`).join('')}</select></label>
      <label>마지막으로 본 회차<select id="onboarding-episode">${onboardingEpisodeOptions(season[1], record.seen_ep)}</select></label>
      <label>평점 · 선택<select id="onboarding-rating"><option value="">선택 안 함</option>${[1,1.5,2,2.5,3,3.5,4,4.5,5].map(score => `<option value="${score}"${score === record.rating ? ' selected' : ''}>${score}점</option>`).join('')}</select></label>
    </div>
    <section class="onboarding-agent-help">
      <header><span><img src="assets/midoriya-mascot.png?v=2" alt=""></span><div><b>AniWhere Agent에게 장면으로 말하기</b><small>시즌과 회차가 기억나지 않아도 괜찮아요.</small></div></header>
      <form id="onboarding-memory-form"><input id="onboarding-memory-input" autocomplete="off" placeholder="예: 비스케를 만나 수련하기 시작한 데까지 봤어"><button type="submit">장면 찾기 ↗</button></form>
      <div class="onboarding-agent-response" id="onboarding-agent-response"><p>기억나는 인물·장소·사건을 한 문장으로 말해주세요.</p></div>
    </section>
    <footer><button type="button" data-editor-remove>목록에서 제거</button><span>프로토타입 작품 데이터</span><button type="button" class="primary" data-editor-done>이 설정으로 저장</button></footer>`;
  const sync = () => {
    const current = onboardingSelection.get(id);
    const selectedSeason = Number($('#onboarding-season').value);
    current.season = selectedSeason;
    current.season_name = title.seasons[selectedSeason - 1][0];
    current.seen_ep = current.status === 'planned' ? 0 : Number($('#onboarding-episode').value);
    const rating = $('#onboarding-rating').value;
    current.rating = rating === '' ? null : Number(rating);
    updateOnboardingSelection();
  };
  $$('[data-watch-status]', editor).forEach(button => button.addEventListener('click', () => {
    record.status = button.dataset.watchStatus;
    openOnboardingEditor(id);
  }));
  $('#onboarding-season').addEventListener('change', event => {
    const selectedSeason = Number(event.target.value);
    record.season = selectedSeason;
    record.season_name = title.seasons[selectedSeason - 1][0];
    record.seen_ep = Math.min(record.seen_ep || 1, title.seasons[selectedSeason - 1][1]);
    openOnboardingEditor(id);
  });
  $('#onboarding-episode').addEventListener('change', sync);
  $('#onboarding-rating').addEventListener('change', sync);
  $('#onboarding-memory-form').addEventListener('submit', event => {
    event.preventDefault();
    const query = $('#onboarding-memory-input').value.trim();
    if (!query) return;
    const response = $('#onboarding-agent-response');
    response.innerHTML = '<p class="searching">시청 기록 후보를 찾는 중…</p>';
    setTimeout(() => {
      const match = findOnboardingMemoryMatch(id, query);
      if (!match) {
        response.innerHTML = '<p><b>조금만 더 알려주세요.</b><br>등장인물, 장소 또는 기억나는 행동을 함께 말하면 더 정확히 찾을 수 있어요.</p>';
        return;
      }
      const seasonName = title.seasons[match.season - 1][0];
      response.innerHTML = `<p><b>${seasonName} · ${match.episode}화일 가능성이 ${match.confidence === '높음' ? '높아요' : '있어요'}.</b><br>${match.evidence}과 가장 가까워요.</p><button type="button" data-apply-memory>여기까지 본 것으로 기록</button>`;
      $('[data-apply-memory]', response).addEventListener('click', () => {
        record.status = 'watching'; record.season = match.season; record.season_name = seasonName; record.seen_ep = match.episode;
        openOnboardingEditor(id);
        showToast(`${seasonName} · ${match.episode}화로 적용했어요.`);
      });
    }, 650);
  });
  $('[data-editor-close]', editor).addEventListener('click', () => { editor.hidden = true; });
  $('[data-editor-done]', editor).addEventListener('click', () => { sync(); editor.hidden = true; showToast(`${title.title} 기록을 저장했어요.`); });
  $('[data-editor-remove]', editor).addEventListener('click', () => { onboardingSelection.delete(id); editor.hidden = true; updateOnboardingSelection(); });
  updateOnboardingSelection();
  requestAnimationFrame(() => editor.scrollIntoView({ behavior:'smooth', block:'nearest' }));
}

function finishOnboarding(records = []) {
  localStorage.setItem(ONBOARDING_KEY, '1');
  if (records.length) {
    savedWatchRecords = records;
    localStorage.setItem(WATCH_RECORDS_KEY, JSON.stringify(records));
    setRecordState(true);
  }
  onboarding.hidden = true;
  document.body.classList.remove('onboarding-open');
}

function startOnboardingTasteInterview() {
  finishOnboarding();
  $('[data-action="interview"]').click();
  showToast('L이 취향 추리를 시작합니다.');
}

function initializeOnboarding() {
  const completed = localStorage.getItem(ONBOARDING_KEY) === '1';
  if (completed || hasRecord || savedWatchRecords.length) return;
  onboarding.hidden = false;
  document.body.classList.add('onboarding-open');
  showOnboardingStep('welcome');
}

function addMessage(role, text, card = '') {
  const row = document.createElement('div');
  row.className = `message ${role}`;
  if (role === 'agent') row.innerHTML = persona === 'l'
    ? '<span class="avatar l-avatar">L</span>'
    : '<span class="avatar midoriya-avatar"><img src="assets/midoriya-mascot.png?v=2" alt="미도리야"></span>';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.innerHTML = `<div>${text}</div>${card}`;
  row.appendChild(bubble);
  messages.appendChild(row);
  requestAnimationFrame(() => messages.scrollTo({ top: messages.scrollHeight, behavior: 'smooth' }));
}

function setSuggestions(items = []) {
  suggestions.replaceChildren();
  items.forEach(item => {
    const label = typeof item === 'string' ? item : item.label;
    const message = typeof item === 'string' ? item : item.message;
    const button = document.createElement('button');
    button.type = 'button'; button.textContent = label;
    button.addEventListener('click', () => send(message || label));
    suggestions.appendChild(button);
  });
}

function reply(text, labels = [], card = '', actions = ['시청 기록 확인 중…', '관련 청크 찾는 중…']) {
  busy = true; setSuggestions();
  const typing = document.createElement('div'); typing.className = 'typing';
  typing.innerHTML = `<i></i><span>${actions[0]}</span>`; messages.appendChild(typing);
  let index = 0;
  const timer = setInterval(() => { index += 1; if (actions[index]) $('span', typing).textContent = actions[index]; }, 650);
  setTimeout(() => { clearInterval(timer); typing.remove(); addMessage('agent', text, card); setSuggestions(labels); busy = false; question.focus(); }, Math.max(1200, actions.length * 680));
}

function resetChat(nextMode = mode) {
  mode = nextMode; persona = 'midoriya'; step = 0; busy = false; chatHistory = []; messages.replaceChildren(); setSuggestions();
  $$('.mode-chips button').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
  const intros = {
    episode: [hasRecord ? '저장된 작품에서 어디까지 보셨는지 함께 찾아보겠습니다! 마지막으로 기억나는 장면을 말해주세요!' : '어떤 작품인지 몰라도 괜찮습니다! 기억나는 장면부터 하나씩 찾아볼게요!', ['올마이트가 마지막에 손가락을 가리켰어', '학교 축제 전까지 봤어']],
    title: ['제목이 기억나지 않아도 괜찮습니다! 인물의 생김새나 능력, 장면을 말해주세요. 제가 열심히 찾아보겠습니다!', ['키 작은 아저씨가 칼 들고 날아다녀', '노란 머리에 번개를 쓰는 겁 많은 아이']],
    recap: hasRecord ? ['저장된 기록은 시즌 3 · 11화예요. 어떤 방식으로 복습할까요?', ['전체 이야기', '인물 관계', '마지막 화 상황']] : ['스포일러 없이 복습하려면 어디까지 봤는지 먼저 알아야 해요. 기억나는 마지막 장면을 말해주세요.', ['올마이트가 손가락을 가리켰어', '샘플 기록 불러오기']],
    providers: ['어떤 작품의 시청처를 찾을까요? 현재 기록된 작품을 바로 확인할 수도 있어요.', ['나의 히어로 아카데미아', '진격의 거인', '귀멸의 칼날']]
  };
  addMessage('agent', intros[mode][0]); setSuggestions(intros[mode][1]);
}

function resultCardFromChat(data) {
  const results = data.results || {};
  const found = results.find;
  if (found?.candidates?.length) {
    const candidate = found.candidates[0];
    return `<div class="result-card"><small>${found.status === 'episode' ? '회차 후보' : '작품 후보'}</small><h3>${escapeHtml(candidate.title || candidate.name || candidate.series_id)}</h3><p>${escapeHtml(candidate.label || (candidate.abs_ep ? `전체 ${candidate.abs_ep}화` : '추가 단서를 알려주세요.'))}</p></div>`;
  }
  const review = results.review;
  if (review?.answer) return `<div class="result-card"><small>${review.seen_ep}화까지 복습</small><p>${escapeHtml(review.answer)}</p></div>`;
  const watching = results.where_to_watch;
  if (watching?.seasons?.length) return `<div class="result-card"><small>시청처 안내</small><h3>${escapeHtml(watching.title)}</h3><p>${watching.seasons.map(season => `${escapeHtml(season.name)} · ${season.providers.map(escapeHtml).join(', ')}`).join('<br>')}</p></div>`;
  const recommended = results.recommend?.picks?.[0];
  if (recommended) return `<div class="result-card"><small>취향 추천</small><h3>${escapeHtml(recommended.title)}</h3><p>${escapeHtml(recommended.reason)}</p></div>`;
  return '';
}

async function send(value) {
  const text = value.trim(); if (!text || busy) return;
  if (text === '샘플 기록 불러오기') { setRecordState(true); resetChat('recap'); showToast('나의 히어로 아카데미아 샘플 기록을 불러왔어요.'); return; }
  if (text === '3분 복습') { if (hasRecord) openRecap('직전 내용'); else showToast('복습할 시청 지점을 먼저 찾아주세요.'); return; }
  if (text === '시청처 보기') { openProviders(); return; }
  addMessage('user', text); question.value = '';
  busy = true; setSuggestions();
  const typing = document.createElement('div'); typing.className = 'typing';
  typing.innerHTML = '<i></i><span>Agent가 필요한 도구를 선택하고 있어요…</span>'; messages.appendChild(typing);
  try {
    const apiMessage = persona === 'l' ? `추천: ${text}` : mode === 'recap' ? `복습: ${text}` : mode === 'providers' ? `시청처: ${text}` : text;
    const data = await api('/api/chat', { method:'POST', body:JSON.stringify({ message:apiMessage, history:chatHistory.slice(-20) }) });
    typing.remove();
    addMessage('agent', escapeHtml(data.answer), resultCardFromChat(data));
    setSuggestions(data.suggestions || []);
    chatHistory.push({ role:'user', content:apiMessage }, { role:'assistant', content:data.answer, context:data.context || null });
    if (data.context?.series_id) activeSeriesId = data.context.series_id;
    if (data.results?.save_record) setRecordState(true);
  } catch (error) {
    typing.remove();
    addMessage('agent', `연결 중 문제가 생겼어요. ${escapeHtml(error.message)}`);
    setSuggestions(['다시 시도할게요']);
  } finally {
    busy = false;
    question.focus();
  }
}

function playTransitionSfx(text = 'ゴゴゴゴ') {
  transitionSfx.textContent = text;
  transitionSfx.classList.remove('play');
  void transitionSfx.offsetWidth;
  transitionSfx.classList.add('play');
  clearTimeout(playTransitionSfx.timer);
  playTransitionSfx.timer = setTimeout(() => transitionSfx.classList.remove('play'), 720);
}

function scrollPageToTop() {
  const previousBehavior = document.documentElement.style.scrollBehavior;
  document.documentElement.style.scrollBehavior = 'auto';
  window.scrollTo(0, 0);
  document.documentElement.scrollTop = 0;
  document.body.scrollTop = 0;
  document.documentElement.style.scrollBehavior = previousBehavior;
}

function openDrawer(kicker, title, html) {
  playTransitionSfx('ドォーン!!');
  $('#drawer-kicker').textContent = kicker;
  $('#drawer-title').textContent = title;
  $('#drawer-content').innerHTML = html;
  $('.drawer-panel').scrollTop = 0;
  drawer.classList.add('open');
  drawer.setAttribute('aria-hidden','false');
  requestAnimationFrame(() => { $('.drawer-panel').scrollTop = 0; });
}
function closeDrawer() { drawer.classList.remove('open', 'dictionary-open'); drawer.setAttribute('aria-hidden','true'); }
async function openRecap(selected = '전체 이야기') {
  const modes = { '전체 이야기':'summary', '인물 관계':'characters', '마지막 화 상황':'last', '직전 내용':'last' };
  openDrawer('FEATURE 09', `스포일러 없는 ${selected}`, '<div class="drawer-card"><p>저장된 시청 기록을 확인하고 있어요…</p></div>');
  try {
    const data = await api('/api/review', { method:'POST', body:JSON.stringify({ series_id:activeSeriesId, seen_ep:null, mode:modes[selected] || 'summary' }) });
    const sources = (data.sources || []).map(source => `<div class="drawer-card"><small>${escapeHtml(source.name || '출처')} · ${source.abs_ep}화</small><p>${escapeHtml(source.text || '')}</p></div>`).join('');
    $('#drawer-content').innerHTML = `<div class="drawer-card"><h3>${data.seen_ep}화까지의 복습</h3><p>${escapeHtml(data.answer || data.follow_up)}</p></div>${sources}<div class="drawer-card safe"><h3>⌾ 보호 범위</h3><p>전체 ${data.seen_ep}화까지만 사용했어요. 이후 내용은 검색 전에 제외합니다.</p></div><div class="spoiler-gate" data-spoiler-gate><span>${data.seen_ep}화</span><i></i><b>TIME STOP</b><i></i><span>${Number(data.seen_ep) + 1}화</span></div><section class="spoiler-protected-card" aria-label="미시청 내용 보호 구간"><h3>⚠️ 스포일러 보호 중 ⚠️</h3><img src="assets/eren-spoiler-user.png" alt="스포일러를 구축해주마고 말하는 에렌 예거"></section>`;
    watchSpoilerGate();
  } catch (error) {
    $('#drawer-content').innerHTML = `<div class="drawer-card"><h3>복습을 불러오지 못했어요.</h3><p>${escapeHtml(error.message)}</p></div>`;
  }
}

function watchSpoilerGate() {
  spoilerObserver?.disconnect();
  const gate = $('[data-spoiler-gate]');
  if (!gate) return;
  spoilerObserver = new IntersectionObserver(entries => {
    if (!entries.some(entry => entry.isIntersecting)) return;
    spoilerObserver.disconnect();
    showSpoilerCutin();
  }, { root: $('.drawer-panel'), threshold: .65 });
  spoilerObserver.observe(gate);
}

function showSpoilerCutin() {
  spoilerCutin.hidden = false;
  document.body.classList.add('time-stopped');
  requestAnimationFrame(() => spoilerCutin.classList.add('active'));
  cutinReturn.focus({ preventScroll: true });
}

function closeSpoilerCutin() {
  spoilerCutin.classList.remove('active');
  document.body.classList.remove('time-stopped');
  setTimeout(() => {
    spoilerCutin.hidden = true;
    $('[data-spoiler-gate]')?.scrollIntoView({ block: 'start', behavior: 'smooth' });
  }, 240);
}
async function openProviders() {
  openDrawer('FEATURE 07', '시청처 안내', '<div class="drawer-card"><p>국내 시청처를 확인하고 있어요…</p></div>');
  try {
    const data = await api(`/api/series/${encodeURIComponent(activeSeriesId)}/where-to-watch`);
    $('#drawer-content').innerHTML = data.seasons.map(season => `<div class="drawer-card"><h3>${escapeHtml(data.title)} · ${escapeHtml(season.name)}</h3><div class="providers">${season.providers.map(provider => `<span>${escapeHtml(provider)}</span>`).join('')}</div><small>확인일 ${escapeHtml(season.checked_at)}</small></div>`).join('') + `<div class="drawer-card"><small>${escapeHtml(data.attribution)}</small></div>`;
  } catch (error) {
    $('#drawer-content').innerHTML = `<div class="drawer-card"><h3>시청처를 불러오지 못했어요.</h3><p>${escapeHtml(error.message)}</p></div>`;
  }
}
function dictionaryEntriesHtml() {
  return hunterDictionary.map(([name, category, description, level]) => `
    <article class="dictionary-entry" data-dictionary-entry data-name="${name.toLowerCase()}" data-category="${category}" data-level="${level}">
      <header><span>${category}</span><small>${level > 3 ? '🔒 이후 공개' : `EP ${level === 1 ? '1–21' : level === 2 ? '22–36' : '37–58'}`}</small></header>
      <h3>${name}</h3>
      <p>${description}</p>
      <div class="dictionary-lock"><b>스포일러 보호 중</b><span>${hunterTermEpisodes[level]}화 이후 공개되는 용어예요.</span></div>
    </article>`).join('');
}

function hunterGraphHtml() {
  const lines = hunterRelations.map(([from, to, label, description, episode, type], index) => {
    const start = hunterCharacters[from];
    const end = hunterCharacters[to];
    const centerX1 = start.x * 10;
    const centerY1 = start.y * 6.5;
    const centerX2 = end.x * 10;
    const centerY2 = end.y * 6.5;
    const dx = centerX2 - centerX1;
    const dy = centerY2 - centerY1;
    const distance = Math.hypot(dx, dy) || 1;
    const nodeGap = 48;
    const x1 = centerX1 + (dx / distance) * nodeGap;
    const y1 = centerY1 + (dy / distance) * nodeGap;
    const x2 = centerX2 - (dx / distance) * nodeGap;
    const y2 = centerY2 - (dy / distance) * nodeGap;
    const reciprocal = hunterRelations.some((relation, other) => other !== index && relation[0] === to && relation[1] === from);
    const bend = reciprocal ? (index % 2 ? -35 : 35) : 0;
    const cx = (x1 + x2) / 2 + bend;
    const cy = (y1 + y2) / 2 - bend;
    const path = `M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`;
    return `<g class="relation-edge ${type}" data-relation-index="${index}" data-required="${episode}" tabindex="0" role="button" aria-label="${start.name}에서 ${end.name}: ${label}">
      <title>${start.name} → ${end.name} · ${label}</title><path class="relation-hit" d="${path}"></path><path class="relation-line" d="${path}" marker-end="url(#arrow-${type})"></path>
    </g>`;
  }).join('');
  const markers = ['friend','family','mentor','conflict','alliance'].map(type => `<marker class="relation-arrow ${type}" id="arrow-${type}" markerUnits="userSpaceOnUse" markerWidth="16" markerHeight="16" refX="14" refY="8" orient="auto"><path d="M0,0 L16,8 L0,16 z"></path></marker>`).join('');
  const nodes = Object.entries(hunterCharacters).map(([id, character]) => `<button class="hunter-node ${character.group}" data-character="${id}" data-required="${character.episode}" style="--x:${character.x}%;--y:${character.y}%" aria-label="${character.name} 정보 보기">
    <span class="node-photo"><img src="assets/${character.image}" alt=""><i>🔒</i></span><b>${character.name}</b><small>${character.group.includes('collective') ? '집단' : `${character.episode}화 공개`}</small>
  </button>`).join('');
  return `<div class="hunter-graph-shell">
    <div class="hunter-graph" id="hunter-graph"><svg viewBox="0 0 1000 650" aria-label="헌터×헌터 인물 관계 연결선"><defs>${markers}</defs>${lines}</svg>${nodes}</div>
    <aside class="hunter-detail" id="hunter-detail"><small>RELATION MAP</small><h3>인물이나 관계선을 선택하세요</h3><p>선택한 인물의 소개와 두 인물 사이의 관계를 여기에서 확인할 수 있어요.</p><span>현재 시청 회차 이후 정보는 자동으로 잠깁니다.</span></aside>
  </div>`;
}

function showHunterCharacter(id) {
  const character = hunterCharacters[id];
  const episode = Number($('#dictionary-checkpoint')?.value || 63);
  const locked = character.episode > episode;
  $$('.hunter-node').forEach(node => node.classList.toggle('selected', node.dataset.character === id));
  $$('.relation-edge').forEach(edge => {
    const relation = hunterRelations[Number(edge.dataset.relationIndex)];
    edge.classList.toggle('related', !locked && (relation[0] === id || relation[1] === id));
    edge.classList.toggle('dimmed', !locked && relation[0] !== id && relation[1] !== id);
  });
  $('#hunter-detail').innerHTML = locked
    ? `<small>🔒 SPOILER SAFE</small><h3>${character.episode}화 이후 공개되는 인물</h3><p>현재 선택한 시청 지점에서는 이름과 설명을 숨겼어요.</p><span>상단에서 시청 지점을 변경하면 공개됩니다.</span>`
    : `<small>${character.group.includes('collective') ? 'GROUP NODE' : `CHARACTER · EP ${character.episode}`}</small><div class="hunter-detail-person"><img src="assets/${character.image}" alt="${character.name}"><h3>${character.name}</h3></div><p>${id === 'killua' && episode >= 24 ? character.later : character.description}</p><span>직접 연결된 관계선만 밝게 표시했어요.</span>`;
}

function showHunterRelation(index) {
  const [from, to, label, description, episode, type] = hunterRelations[index];
  const start = hunterCharacters[from];
  const end = hunterCharacters[to];
  $$('.hunter-node').forEach(node => node.classList.toggle('selected', [from, to].includes(node.dataset.character)));
  $$('.relation-edge').forEach(edge => {
    edge.classList.toggle('related', Number(edge.dataset.relationIndex) === index);
    edge.classList.toggle('dimmed', Number(edge.dataset.relationIndex) !== index);
  });
  $('#hunter-detail').innerHTML = `<small>RELATION · EP ${episode}</small><h3>${start.name} <i>→</i> ${end.name}</h3><b class="relation-badge ${type}">${label}</b><p>${description}</p><span>선을 다시 선택하거나 다른 인물을 눌러 탐색하세요.</span>`;
}

function updateHunterGraph() {
  const episode = Number($('#dictionary-checkpoint')?.value || 63);
  $$('.hunter-node').forEach(node => node.classList.toggle('locked', Number(node.dataset.required) > episode));
  $$('.relation-edge').forEach(edge => {
    edge.hidden = Number(edge.dataset.required) > episode;
    edge.classList.remove('related','dimmed');
  });
  $$('.hunter-node').forEach(node => node.classList.remove('selected'));
  $('#hunter-detail').innerHTML = `<small>SPOILER SAFE · EP ${episode}</small><h3>${hunterCheckpoints[episode]}</h3><p>이 시점까지 확인된 인물과 관계만 연결했어요. 노드나 선을 선택해 설명을 확인하세요.</p><span>${episode < 139 ? '잠긴 실루엣은 이후 회차에 공개됩니다.' : '준비된 모든 관계가 공개됐어요.'}</span>`;
}

function filterDictionary() {
  const query = ($('#dictionary-search')?.value || '').trim().toLowerCase();
  const category = $('[data-dictionary-filter].active')?.dataset.dictionaryFilter || '전체';
  const episode = Number($('#dictionary-checkpoint')?.value || 63);
  let visible = 0;
  $$('[data-dictionary-entry]').forEach(entry => {
    const matchesQuery = !query || entry.dataset.name.includes(query) || entry.textContent.toLowerCase().includes(query);
    const matchesCategory = category === '전체' || entry.dataset.category === category;
    entry.hidden = !(matchesQuery && matchesCategory);
    entry.classList.toggle('locked', hunterTermEpisodes[Number(entry.dataset.level)] > episode);
    if (!entry.hidden) visible += 1;
  });
  $('#dictionary-count').textContent = `${visible}개 용어`;
  $('#dictionary-safe-label').textContent = `${episode}화까지 공개`;
}

function openDictionary() {
  const categories = ['전체', ...new Set(hunterDictionary.map(([, category]) => category))];
  openDrawer('PROTOTYPE · FEATURE 08', '헌터×헌터 인물·용어 사전', `
    <div class="dictionary-toolbar">
      <div><small>현재 시청 지점</small><select id="dictionary-checkpoint">${Object.entries(hunterCheckpoints).map(([episode, label]) => `<option value="${episode}"${episode === '63' ? ' selected' : ''}>${label}</option>`).join('')}</select></div>
      <span class="dictionary-safe" id="dictionary-safe-label">63화까지 공개</span>
    </div>
    <div class="dictionary-tabs" role="tablist" aria-label="사전 보기 선택">
      <button class="active" data-dictionary-tab="relations" role="tab">인물 관계</button>
      <button data-dictionary-tab="terms" role="tab">용어 사전</button>
    </div>
    <section class="dictionary-pane active" data-dictionary-pane="relations">
      <div class="dictionary-intro"><small>HUNTER × HUNTER</small><h3>회차 기준 인물 관계도</h3><p>노드나 관계선을 선택하면 설명이 열려요. 아직 보지 않은 관계는 자동으로 숨깁니다.</p></div>
      <div class="relation-legend"><span class="friend">친구·동료</span><span class="family">가족</span><span class="mentor">지도·관심</span><span class="conflict">통제·대립</span><span class="alliance">임무·이해관계</span></div>
      ${hunterGraphHtml()}
    </section>
    <section class="dictionary-pane" data-dictionary-pane="terms" hidden>
      <label class="dictionary-search"><span class="sr-only">용어 검색</span><input id="dictionary-search" type="search" placeholder="넨, 번지껌, 쿠르타족 검색"><b>⌕</b></label>
      <div class="dictionary-filters">${categories.map((category, index) => `<button class="${index === 0 ? 'active' : ''}" data-dictionary-filter="${category}">${category}</button>`).join('')}</div>
      <div class="dictionary-result-head"><b id="dictionary-count">${hunterDictionary.length}개 용어</b><span>설명은 현재 회차까지만</span></div>
      <div class="dictionary-grid">${dictionaryEntriesHtml()}</div>
      <div class="dictionary-source"><b>프로토타입 데이터</b><p>첨부된 용어 정리를 바탕으로 구성했으며, 실제 연결 시 각 항목에 출처·공개 회차·다른 표기를 함께 저장합니다.</p></div>
    </section>`);
  drawer.classList.add('dictionary-open');

  $$('[data-dictionary-tab]').forEach(button => button.addEventListener('click', () => {
    $$('[data-dictionary-tab]').forEach(item => item.classList.toggle('active', item === button));
    $$('[data-dictionary-pane]').forEach(pane => {
      const active = pane.dataset.dictionaryPane === button.dataset.dictionaryTab;
      pane.classList.toggle('active', active);
      pane.hidden = !active;
    });
    $('.drawer-panel').scrollTo({ top: 0, behavior: 'smooth' });
  }));
  $$('[data-dictionary-filter]').forEach(button => button.addEventListener('click', () => {
    $$('[data-dictionary-filter]').forEach(item => item.classList.toggle('active', item === button));
    filterDictionary();
  }));
  $('#dictionary-search').addEventListener('input', filterDictionary);
  $('#dictionary-checkpoint').addEventListener('change', () => { filterDictionary(); updateHunterGraph(); });
  $$('[data-character]').forEach(node => node.addEventListener('click', () => showHunterCharacter(node.dataset.character)));
  $$('[data-relation-index]').forEach(edge => {
    edge.addEventListener('click', () => showHunterRelation(Number(edge.dataset.relationIndex)));
    edge.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); showHunterRelation(Number(edge.dataset.relationIndex)); } });
  });
  filterDictionary();
  updateHunterGraph();
}
function openRecord() {
  openDrawer('FEATURE 13', '시청 기록 수정', `<form class="record-form" id="record-form"><label>상태<select><option>시청 중</option><option>보고 싶어요</option><option>완료</option></select></label><label>시즌<input id="record-season" type="number" value="3" min="1"></label><label>회차<input id="record-episode" type="number" value="11" min="1"></label><label>평점 (선택)<input id="record-rating" type="number" min="0.5" max="5" step="0.5" placeholder="0.5–5"></label><button>기록 저장</button></form>`);
  $('#record-form').addEventListener('submit', async event => {
    event.preventDefault();
    const season = Number($('#record-season').value);
    const episode = Number($('#record-episode').value);
    const seasonOffsets = { 1:0, 2:13, 3:38, 4:63, 5:88, 6:113, 7:138 };
    const seenEp = (seasonOffsets[season] || 0) + episode;
    const ratingValue = $('#record-rating').value;
    try {
      await api(`/api/records/${encodeURIComponent(HERO_SERIES_ID)}`, { method:'PUT', body:JSON.stringify({ seen_ep:seenEp, rating:ratingValue ? Number(ratingValue) : null }) });
      setRecordState(true); closeDrawer(); showToast(`시즌 ${season} · ${episode}화 기록을 저장했어요.`);
    } catch (error) { showToast(error.message); }
  });
}
function openSimilar() { openDrawer('확장 프로토타입 · FEATURE 02', '“진격의 거인 같은 거”', `<div class="drawer-card"><h3>강철의 연금술사</h3><p>거대한 세계의 비밀, 군과 권력의 음모, 뒤집히는 진실이 가까워요.</p></div><div class="drawer-card"><h3>86 -에이티식스-</h3><p>전쟁 속에서 감춰진 사회 구조와 인물들의 선택을 따라가요.</p></div><div class="drawer-card"><h3>메이드 인 어비스</h3><p>미지의 세계를 탐험할수록 새로운 진실이 드러나는 작품이에요.</p></div>`); }
function openWatchOrder() { openDrawer('확장 프로토타입 · FEATURE 03', '나의 히어로 아카데미아 시청 순서', `<div class="character-scene finished-scene light-scene"><img src="assets/light-card-user.png" alt="시청 순서를 계획하는 라이토"></div><div class="order-list"><div class="order-item"><b>1</b><div><strong>TV 애니 1기</strong><br><span>먼저 보기 · 필수</span></div><em>13화</em></div><div class="order-item"><b>2</b><div><strong>TV 애니 2기</strong><br><span>이어서 보기 · 필수</span></div><em>25화</em></div><div class="order-item"><b>3</b><div><strong>극장판: 두 명의 히어로</strong><br><span>2기 이후 추천 · 건너뛰어도 본편 이해 가능</span></div><em>영화</em></div><div class="order-item"><b>4</b><div><strong>TV 애니 3기</strong><br><span>현재 시청 중</span></div><em>EP11</em></div></div><div class="drawer-card"><p>방영 순·시간 순 전환은 실제 AniList 관계 정보 연결 후 제공할 예정입니다.</p></div>`); }
function openHookGuide() { openDrawer('확장 프로토타입 · FEATURE 04', '몇 화부터 재밌어져요?', `<div class="character-scene finished-scene okabe-scene"><img src="assets/okabe-card-user.png" alt="여기서부터 재미있어진다고 안내하는 오카베 린타로"></div><div class="drawer-card"><h3>나의 히어로 아카데미아</h3><p><strong>3화까지</strong> 세계관과 주인공의 출발을 설명하고, <strong>4화부터</strong> 학교 입학 과정이 본격적으로 시작돼요.</p></div><div class="drawer-card safe"><h3>스포일러 없는 안내</h3><p>구체적인 사건이나 승패는 숨기고, 이야기의 속도와 분위기가 바뀌는 지점만 알려줘요.</p></div>`); }
function openSeasonAlert() { openDrawer('확장 프로토타입 · FEATURE 10', '새 시즌이 시작됐어요', `<div class="drawer-card"><h3>나의 히어로 아카데미아 · 다음 시즌</h3><p>마지막 기록이 시즌 3 · 11화라서, 바로 새 시즌으로 이동하기 전에 보던 시즌부터 이어보는 것을 추천해요.</p><button class="copy-button" data-alert-recap>직전 내용 3분 복습</button></div>`); $('[data-alert-recap]').addEventListener('click', () => openRecap('직전 내용')); }
function openMangaLink() { openDrawer('확장 프로토타입 · FEATURE 12', '애니 다음은 원작 어디부터?', `<div class="character-scene finished-scene gon-scene"><img src="assets/gon-card-user.png" alt="애니메이션이 12년째 안 나와 원작을 보려는 곤"></div><div class="drawer-card"><h3>시청 지점: 시즌 3 · 11화</h3><p>이 지점과 이어지는 원작 권·화 정보는 현재 예시 화면입니다. 실제 연결 전 팬 위키의 원작 대응 화수 검수가 필요해요.</p></div><div class="drawer-card"><h3>예시 연결</h3><p>원작 <strong>11권 전후</strong>에서 해당 장면을 확인할 수 있어요. 정확한 시작 화수는 데이터 검수 후 표시합니다.</p></div>`); }
function openShareCopy() { const copy = '평범한 능력물 같지만, 주인공이 힘의 의미를 배워가는 과정과 주변 인물의 성장이 정말 좋은 작품이야. 초반 설정만 알고 보면 더 재미있어!'; openDrawer('확장 프로토타입 · FEATURE 14', '스포일러 없는 추천 문구', `<div class="drawer-card"><h3>친구에게 보내기</h3><div class="share-box" id="share-copy">${copy}</div><button class="copy-button" id="copy-share">문구 복사</button></div><div class="drawer-card"><p>저장된 시청 회차 이후의 인물·사건은 추천 문구 생성 전에 제외하는 구조를 가정했어요.</p></div>`); $('#copy-share').addEventListener('click', async () => { try { await navigator.clipboard.writeText(copy); showToast('추천 문구를 복사했어요.'); } catch { showToast('문구를 선택해서 복사해주세요.'); } }); }
function showToast(text) { toast.textContent = text; toast.classList.add('show'); clearTimeout(showToast.timer); showToast.timer = setTimeout(() => toast.classList.remove('show'), 2300); }

$$('[data-view]').forEach(button => button.addEventListener('click', () => {
  const view = button.dataset.view;
  playTransitionSfx('ゴゴゴゴ');
  $$('.view').forEach(v => v.classList.toggle('active', v.id === `${view}-view`));
  $$('.topbar nav button').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  scrollPageToTop();
  requestAnimationFrame(scrollPageToTop);
}));
$$('[data-mode]').forEach(button => button.addEventListener('click', () => resetChat(button.dataset.mode)));
$$('[data-action]').forEach(button => button.addEventListener('click', () => { const action = button.dataset.action; const needsRecord = ['recap','watch-order','hook-guide','manga-link','season-alert','edit-record']; if (!hasRecord && needsRecord.includes(action)) { showToast('먼저 작품을 찾거나 샘플 시청 기록을 불러와주세요.'); return; } if (action === 'recap') openRecap(); else if (action === 'providers') openProviders(); else if (action === 'dictionary') openDictionary(); else if (action === 'edit-record') openRecord(); else if (action === 'similar') openSimilar(); else if (action === 'watch-order') openWatchOrder(); else if (action === 'hook-guide') openHookGuide(); else if (action === 'season-alert') openSeasonAlert(); else if (action === 'manga-link') openMangaLink(); else if (action === 'share-copy') openShareCopy(); else if (action === 'find-episode') { $('[data-view="chat"]').click(); resetChat('episode'); } else if (action === 'interview') { $('[data-view="chat"]').click(); resetChat('title'); persona = 'l'; messages.replaceChildren(); setSuggestions(); $('#chat-kicker').textContent = 'L · TASTE DETECTIVE'; $('#chat-title').innerHTML = '당신의 취향을<br>추리하겠습니다.'; addMessage('agent','저는 L입니다. 인류 최고의 두뇌로 당신에게 최고의 애니를 추리하겠습니다. 최근 몰입해서 본 작품 하나를 말씀해주시죠.', '<div class="result-card l-case"><img class="l-chat-panel" src="assets/l-detective-user.png" alt="취향을 추리하는 L"><small>CASE 001 · TASTE PROFILE</small><h3>추리를 시작합니다.</h3><p>분위기 · 전개 속도 · 인물 관계를 분석합니다.</p></div>'); setSuggestions(['진격의 거인 같은 반전물', '성장하는 주인공']); } }));
$$('[data-close]').forEach(b => b.addEventListener('click', closeDrawer));
$('#new-chat').addEventListener('click', () => resetChat(mode));
composer.addEventListener('submit', e => { e.preventDefault(); send(question.value); });
question.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); composer.requestSubmit(); } });

function setRecordState(next) {
  hasRecord = next;
  if (next) localStorage.setItem(RECORD_KEY, '1'); else localStorage.removeItem(RECORD_KEY);
  $('#empty-context').hidden = next;
  $('#record-context').hidden = !next;
  $('#empty-library').hidden = next;
  $('#library-content').hidden = !next;
  $('#record-greeting').hidden = !next;
  $('#chat-kicker').textContent = next ? 'ANIWHERE AGENT · WELCOME BACK' : 'ANIWHERE AGENT · FIRST VISIT';
  $('#chat-title').innerHTML = next ? '12일 만이네요.<br>어디까지 기억나요?' : '오늘은 어떤 애니<br>이야기를 해볼까요?';
}

$$('[data-load-sample]').forEach(button => button.addEventListener('click', () => { setRecordState(true); $('[data-view="chat"]').click(); resetChat('episode'); showToast('나의 히어로 아카데미아 샘플 기록을 불러왔어요.'); }));
$$('[data-clear-record]').forEach(button => button.addEventListener('click', () => { setRecordState(false); resetChat('episode'); showToast('작품 선택을 해제했어요.'); }));
$$('[data-onboarding-next]').forEach(button => button.addEventListener('click', () => showOnboardingStep(button.dataset.onboardingNext)));
$$('[data-onboarding-back]').forEach(button => button.addEventListener('click', () => showOnboardingStep(button.dataset.onboardingBack)));
$$('[data-onboarding-l]').forEach(button => button.addEventListener('click', startOnboardingTasteInterview));
$$('[data-onboarding-title]').forEach(button => button.addEventListener('click', () => {
  const id = button.dataset.onboardingTitle;
  if (onboardingSelection.has(id)) {
    onboardingSelection.delete(id);
    const editor = $('#onboarding-editor');
    if (editor.dataset.editing === id) { editor.hidden = true; delete editor.dataset.editing; }
    updateOnboardingSelection();
    showToast(`${onboardingTitles[id].title} 선택을 해제했어요.`);
    return;
  }
  openOnboardingEditor(id);
}));
$('#onboarding-to-details').addEventListener('click', () => {
  const records = [...onboardingSelection.values()].map(record => ({ ...record, seen_ep: record.status === 'planned' ? 0 : record.seen_ep }));
  finishOnboarding(records);
  $('[data-view="chat"]').click();
  resetChat('episode');
  showToast(`${records.length}개 작품의 스포일러 기준을 저장했어요.`);
});
cutinReturn.addEventListener('click', closeSpoilerCutin);
document.addEventListener('keydown', event => { if (event.key === 'Escape' && !spoilerCutin.hidden) closeSpoilerCutin(); });
setRecordState(hasRecord);
resetChat('episode');
initializeOnboarding();

api('/api/records').then(records => {
  if (Array.isArray(records)) setRecordState(records.length > 0 || hasRecord);
}).catch(() => showToast('백엔드 연결을 확인해주세요.'));

function isStandalone() { return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true; }
function hideInstallGuide() { installGuide.hidden = true; sessionStorage.setItem('aniwhere-install-dismissed', '1'); }
async function requestInstall() {
  if (!installPrompt) {
    const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
    showToast(isIOS ? 'Safari 공유 버튼 → 홈 화면에 추가를 누르세요.' : '브라우저 메뉴의 “앱 설치”를 선택해주세요.');
    return;
  }
  installPrompt.prompt();
  await installPrompt.userChoice;
  installPrompt = null;
  installButton.hidden = true;
  installGuide.hidden = true;
}

window.addEventListener('beforeinstallprompt', event => {
  event.preventDefault();
  installPrompt = event;
  installButton.hidden = false;
  if (!sessionStorage.getItem('aniwhere-install-dismissed')) installGuide.hidden = false;
});
window.addEventListener('appinstalled', () => { installButton.hidden = true; installGuide.hidden = true; showToast('AniWhere 앱을 설치했어요.'); });
installButton.addEventListener('click', requestInstall);
installGuideAction.addEventListener('click', requestInstall);
installGuideClose.addEventListener('click', hideInstallGuide);

if ('serviceWorker' in navigator) window.addEventListener('load', () => navigator.serviceWorker.register('./service-worker.js').catch(() => {}));
if (isStandalone()) document.documentElement.classList.add('standalone-app');
