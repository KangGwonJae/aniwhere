const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const messages = $('#messages');
const suggestions = $('#suggestions');
const question = $('#question');
const composer = $('#composer');
const drawer = $('#drawer');
const toast = $('#toast');
const installButton = $('#install-app');
const onboardingInstallButton = $('#onboarding-install-app');
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
const tasteInterview = { active:false, step:0, answers:[] };
const tasteQuestions = [
  '최근 재미있게 본 영화·드라마·웹툰을 두세 개 말씀해주세요.',
  '그 작품들에서 가장 좋았던 분위기는 무엇이었나요?',
  '빠른 전개와 천천히 쌓이는 전개 중 어느 쪽을 선호하시나요?',
  '좋아하는 주인공이나 인물 관계 유형이 있나요?',
  '피하고 싶은 요소가 있다면 마지막으로 알려주세요.'
];
const CHAT_HISTORY_KEY = 'aniwhere-chat-history-v3';
const CHAT_MESSAGES_KEY = 'aniwhere-chat-messages-v3';
let chatHistory = [];
let visualConversation = [];
try { chatHistory = JSON.parse(localStorage.getItem(CHAT_HISTORY_KEY) || '[]'); } catch { chatHistory = []; }
try { visualConversation = JSON.parse(localStorage.getItem(CHAT_MESSAGES_KEY) || '[]'); } catch { visualConversation = []; }
let activeSeriesId = null;
let activeSeriesTitle = '';
let activeCandidateEp = null;
let latestReview = null;
let onboardingCatalogCache = [];
let railRecordsExpanded = false;
let railTipIndex = 0;
let railTipTimer = null;
let railTipMessages = [];
let recommendationSignature = '';
const RECORD_KEY = 'aniwhere-demo-watch-record';
const ONBOARDING_KEY = 'aniwhere-onboarding-completed-v3';
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

function onboardingImage(title) {
  return title.image?.startsWith('http') ? title.image : `assets/${title.image}`;
}

async function loadOnboardingCatalog() {
  const container = $('#onboarding-titles');
  const belt = $('#onboarding-poster-belt');
  try {
    const items = await api('/api/series?limit=200');
    const withPosters = items.filter(item => item.poster_url);
    if (!withPosters.length) throw new Error('포스터가 있는 작품이 없습니다.');
    withPosters.forEach(item => {
      onboardingTitles[item.series_id] = {
        title:item.name || item.title, image:item.poster_url,
        seasons:[['전체 회차', Math.max(1, item.total_episodes || 1)]], defaultSeason:1, defaultEpisode:1
      };
    });
    onboardingCatalogCache = withPosters;
    renderOnboardingCatalog(withPosters);
    const moving = withPosters.slice(0, 15);
    belt.innerHTML = `<div class="poster-belt-track">${[...moving, ...moving].map(item => `<img src="${escapeHtml(item.poster_url)}" alt="">`).join('')}</div>`;
    const backdropPosters = withPosters.slice(0, 21);
    $('.poster-atmosphere').innerHTML = [...backdropPosters, ...backdropPosters, ...backdropPosters].map(item => `<img src="${escapeHtml(item.poster_url)}" alt="">`).join('');
    updateOnboardingSelection();
  } catch (error) {
    container.innerHTML = `<p class="catalog-loading">작품 목록을 불러오지 못했어요. ${escapeHtml(error.message)}</p>`;
  }
}

function renderOnboardingCatalog(items) {
  const container = $('#onboarding-titles');
  const withPosters = items.filter(item => item.poster_url);
  withPosters.forEach(item => {
    if (!onboardingTitles[item.series_id]) onboardingTitles[item.series_id] = {
      title:item.name || item.title, image:item.poster_url,
      seasons:[['전체 회차', Math.max(1, item.total_episodes || 1)]], defaultSeason:1, defaultEpisode:1
    };
  });
  container.innerHTML = withPosters.length ? withPosters.map(item => `<article class="onboarding-title-card" data-onboarding-title="${escapeHtml(item.series_id)}" data-title="${escapeHtml(item.name || item.title)}"><button type="button" class="onboarding-title-select"><img src="${escapeHtml(item.poster_url)}" alt="${escapeHtml(item.name || item.title)} 포스터"><span><b>${escapeHtml(item.name || item.title)}</b><small>총 ${item.total_episodes || '?'}화</small><em data-onboarding-summary></em></span><i>✓</i></button><section class="onboarding-card-editor" hidden aria-live="polite"></section></article>`).join('') : '<p class="catalog-loading">검색 결과가 없어요. 다른 제목이나 줄임말로 찾아보세요.</p>';
  updateOnboardingSelection();
}

async function loadPersonalRecommendations(force = false) {
  const grid = $('#personal-recommendations');
  if (!grid) return;
  const titles = savedWatchRecords.map(record => record.title || record.name || onboardingTitles[record.series_id]?.title).filter(Boolean);
  const signature = titles.join('|');
  if (!force && recommendationSignature === signature && grid.querySelector('.recommend')) return;
  recommendationSignature = signature;
  if (!titles.length) {
    grid.innerHTML = '<p class="recommend-loading">시청 기록을 추가하면 취향에 맞는 작품을 추천해드려요.</p>';
    $('#recommend-basis').textContent = '시청 기록 기반 추천';
    return;
  }
  grid.innerHTML = '<p class="recommend-loading">내 시청 기록에 맞는 작품을 찾고 있어요…</p>';
  $('#recommend-basis').textContent = `${titles.slice(0, 2).join(', ')}${titles.length > 2 ? ` 외 ${titles.length - 2}개` : ''} 기반`;
  try {
    const data = await api('/api/recommend', { method:'POST', body:JSON.stringify({ likes:`재미있게 본 애니: ${titles.join(', ')}` }) });
    const picks = (data.picks || []).slice(0, 5);
    grid.innerHTML = picks.length ? picks.map(pick => `<article class="recommend" style="--recommend-poster:url('${String(pick.poster_url || '').replace(/[\\'\"]/g, '')}')"><small>${escapeHtml((pick.genres || []).slice(0, 2).join(' · ') || '취향 추천')}</small><h3>${escapeHtml(pick.title)}</h3><p>${escapeHtml(pick.reason)}</p></article>`).join('') : `<p class="recommend-loading">${escapeHtml(data.follow_up || '현재 기록에서 추천 후보를 찾지 못했어요.')}</p>`;
  } catch (error) {
    grid.innerHTML = `<p class="recommend-loading">추천을 불러오지 못했어요. ${escapeHtml(error.message)}</p>`;
  }
}
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
let onboardingEntryMode = 'first';

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    signal: options.signal || AbortSignal.timeout(70000),
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

function formatAgentText(value = '') {
  return escapeHtml(value).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>');
}

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
  $$('[data-onboarding-title]').forEach(card => {
    const record = onboardingSelection.get(card.dataset.onboardingTitle);
    card.classList.toggle('selected', Boolean(record?.status));
    const summary = $('[data-onboarding-summary]', card);
    if (!record) summary.textContent = '';
    else if (record.status === 'planned') summary.textContent = '보고 싶어요 · 아직 안 봄';
    else {
      const status = record.status === 'completed' ? '다 봤어요' : '시청 중';
      summary.textContent = `${status} · ${record.season_name} ${record.seen_ep}화`;
    }
  });
  const savedCount = [...onboardingSelection.values()].filter(record => record.status).length;
  $('#onboarding-selection-count').textContent = `${savedCount}개 저장`;
  $('#onboarding-to-details').disabled = savedCount === 0;
}

function onboardingEpisodeOptions(total, selected) {
  return Array.from({ length: total }, (_, index) => index + 1).map(episode => `<option value="${episode}"${episode === selected ? ' selected' : ''}>${episode}화</option>`).join('');
}

function recordAbsoluteEpisode(record) {
  const title = onboardingTitles[record.series_id];
  if (record.status === 'planned') return 0;
  if (!title) return Number(record.seen_ep || 0);
  const season = Math.max(1, Number(record.season) || 1);
  const before = title.seasons.slice(0, season - 1).reduce((sum, [, episodes]) => sum + Number(episodes || 0), 0);
  return before + Number(record.seen_ep || 0);
}

function findOnboardingMemoryMatch(id, question) {
  const normalized = question.replace(/\s+/g, '').toLowerCase();
  return (onboardingMemoryMatches[id] || []).map(match => ({
    ...match,
    score: match.keywords.filter(keyword => normalized.includes(keyword.replace(/\s+/g, '').toLowerCase())).length
  })).sort((a, b) => b.score - a.score).find(match => match.score > 0) || null;
}

function openOnboardingEditor(id, showWatchingPicker = false) {
  const title = onboardingTitles[id];
  if (!onboardingSelection.has(id)) onboardingSelection.set(id, {
    series_id:id, title:title.title, status:'', season:title.defaultSeason,
    season_name:title.seasons[title.defaultSeason - 1][0], seen_ep:title.defaultEpisode, rating:null
  });
  const record = onboardingSelection.get(id);
  const season = title.seasons[record.season - 1] || title.seasons[0];
  $$('.onboarding-card-editor').forEach(openEditor => {
    if (openEditor.closest('[data-onboarding-title]')?.dataset.onboardingTitle !== id) openEditor.hidden = true;
  });
  const card = $(`[data-onboarding-title="${CSS.escape(id)}"]`);
  const editor = $('.onboarding-card-editor', card);
  editor.hidden = false;
  editor.dataset.editing = id;
  editor.innerHTML = `<header><div><small>${showWatchingPicker ? '어디까지 봤나요?' : '시청 상태 설정'}</small><h3>${title.title}</h3></div><button type="button" data-editor-close aria-label="설정 닫기">×</button></header>${showWatchingPicker ? `
    <div class="onboarding-picker simple-picker">
      <label>시즌<select id="onboarding-season">${title.seasons.map(([name], index) => `<option value="${index + 1}"${index + 1 === record.season ? ' selected' : ''}>${name}</option>`).join('')}</select></label>
      <label>마지막으로 본 회차<select id="onboarding-episode">${onboardingEpisodeOptions(season[1], record.seen_ep || 1)}</select></label>
    </div>
    <button type="button" class="onboarding-watching-done" data-watching-done>여기까지 봤어요</button>
    <button type="button" class="onboarding-forgot" data-watching-forgot>기억 안 나요</button>` : `
    <div class="onboarding-status simple-status" role="group" aria-label="시청 상태">
      <button type="button" data-watch-status="completed">다 봤어요<small>시청 완료</small></button>
      <button type="button" data-watch-status="watching">시청 중<small>어디까지 봤는지 선택</small></button>
      <button type="button" data-watch-status="planned">보고 싶어요<small>나중에 볼 작품</small></button>
    </div>`}`;
  $$('[data-watch-status]', editor).forEach(button => button.addEventListener('click', () => {
    record.status = button.dataset.watchStatus;
    if (record.status === 'completed') {
      record.season = title.seasons.length;
      record.season_name = title.seasons.at(-1)[0];
      record.seen_ep = title.seasons.at(-1)[1];
      editor.hidden = true;
      updateOnboardingSelection();
      showToast(`${title.title}을 다 본 작품으로 저장했어요.`);
    } else if (record.status === 'planned') {
      record.seen_ep = 0;
      editor.hidden = true;
      updateOnboardingSelection();
      showToast(`${title.title}을 보고 싶은 작품으로 저장했어요.`);
    } else {
      if (!record.seen_ep) record.seen_ep = 1;
      openOnboardingEditor(id, true);
    }
  }));
  $('#onboarding-season', editor)?.addEventListener('change', event => {
    const selectedSeason = Number(event.target.value);
    record.season = selectedSeason;
    record.season_name = title.seasons[selectedSeason - 1][0];
    record.seen_ep = Math.min(record.seen_ep || 1, title.seasons[selectedSeason - 1][1]);
    openOnboardingEditor(id, true);
  });
  $('[data-watching-done]', editor)?.addEventListener('click', () => {
    record.status = 'watching';
    record.seen_ep = Number($('#onboarding-episode', editor).value);
    record.rating = null;
    editor.hidden = true;
    updateOnboardingSelection();
    showToast(`${title.title} 시청 지점을 저장했어요.`);
  });
  $('[data-watching-forgot]', editor)?.addEventListener('click', () => {
    record.status = 'watching'; record.seen_ep = 0; record.rating = null;
    editor.hidden = true;
    updateOnboardingSelection();
    showToast('메인 AI 대화에서 기억나는 장면을 말해주세요.');
  });
  $('[data-editor-close]', editor).addEventListener('click', () => {
    if (!record.status) onboardingSelection.delete(id);
    editor.hidden = true;
    updateOnboardingSelection();
  });
  updateOnboardingSelection();
  requestAnimationFrame(() => editor.scrollIntoView({ behavior:'smooth', block:'nearest' }));
}

function finishOnboarding(records = []) {
  localStorage.setItem(ONBOARDING_KEY, '1');
  if (records.length) {
    if (onboardingEntryMode === 'add') {
      const merged = new Map(savedWatchRecords.map(record => [record.series_id, record]));
      records.forEach(record => merged.set(record.series_id, { ...merged.get(record.series_id), ...record }));
      savedWatchRecords = [...merged.values()];
    } else savedWatchRecords = records;
    localStorage.setItem(WATCH_RECORDS_KEY, JSON.stringify(savedWatchRecords));
    setRecordState(true);
    renderLibrary();
  } else if (onboardingEntryMode !== 'add') {
    savedWatchRecords = [];
    localStorage.removeItem(WATCH_RECORDS_KEY);
    setRecordState(false);
    renderLibrary();
  }
  onboarding.hidden = true;
  document.body.classList.remove('onboarding-open');
  onboardingSelection.clear();
  updateOnboardingSelection();
  onboardingEntryMode = 'first';
}

function startOnboardingTasteInterview() {
  finishOnboarding();
  $('[data-action="interview"]').click();
  showToast('L이 취향 추리를 시작합니다.');
}

function initializeOnboarding() {
  const completed = localStorage.getItem(ONBOARDING_KEY) === '1';
  const preview = new URLSearchParams(location.search).get('onboarding') === '1';
  if (completed && !preview) return;
  onboardingEntryMode = 'first';
  setRecordState(false);
  onboarding.hidden = false;
  document.body.classList.add('onboarding-open');
  showOnboardingStep('welcome');
}

function openOnboardingForRecords() {
  onboardingEntryMode = 'add';
  onboardingSelection.clear();
  updateOnboardingSelection();
  onboarding.hidden = false;
  document.body.classList.add('onboarding-open');
  showOnboardingStep('titles');
}

function closeOnboardingWithoutChanges() {
  localStorage.setItem(ONBOARDING_KEY, '1');
  onboarding.hidden = true;
  document.body.classList.remove('onboarding-open');
}

function clearConversationContext() {
  activeSeriesId = null;
  activeSeriesTitle = '';
  activeCandidateEp = null;
  $('#conversation-empty').hidden = false;
  $('.rail-heading').hidden = true;
  $('.watch-context').hidden = true;
  $('.spoiler-lock').hidden = true;
  $$('[data-context-seen]').forEach(button => { button.hidden = true; });
  renderRailRecords();
}

async function applyConversationContext(seriesId, seenEp = null, fallbackTitle = '', candidateEp = null) {
  if (!seriesId) { clearConversationContext(); return; }
  activeSeriesId = seriesId;
  activeCandidateEp = seenEp == null && candidateEp != null ? Number(candidateEp) : null;
  const local = savedWatchRecords.find(record => record.series_id === seriesId);
  const localSeenEp = local && local.status !== 'planned' ? recordAbsoluteEpisode(local) : null;
  const effectiveSeenEp = Number(seenEp) > 0 ? Number(seenEp) : Number(localSeenEp) > 0 ? Number(localSeenEp) : null;
  let series = null;
  try { series = await api(`/api/series/${encodeURIComponent(seriesId)}`); } catch {}
  const title = series?.name || series?.title || local?.title || local?.name || fallbackTitle || '확인된 작품';
  activeSeriesTitle = title;
  const imageUrl = series?.poster_url || local?.poster_url || (onboardingTitles[seriesId] ? onboardingImage(onboardingTitles[seriesId]) : '');
  $('#conversation-empty').hidden = true;
  $('.rail-heading').hidden = false;
  $('.rail-heading h2').textContent = title;
  $('.watch-context').hidden = false;
  const image = $('.watch-context img');
  image.hidden = !imageUrl;
  if (imageUrl) { image.src = imageUrl; image.alt = `${title} 포스터`; }
  $('.watch-context b').textContent = effectiveSeenEp == null ? '대화에서 확인된 작품' : `전체 ${effectiveSeenEp}화까지 확인`;
  $('.watch-context span').textContent = effectiveSeenEp == null ? '질문에 따라 실시간으로 바뀌어요' : '이 지점 이후는 스포일러 보호';
  const hasSeen = Number.isFinite(Number(effectiveSeenEp));
  $('.spoiler-lock').hidden = !hasSeen;
  if (hasSeen) $('.spoiler-lock span').textContent = `${Number(effectiveSeenEp)}화 이후 청크는 검색 전에 제외`;
  $$('[data-context-seen]').forEach(button => { button.hidden = !hasSeen; });
  renderRailRecords();
}

function renderRailRecords() {
  const rail = $('#rail-posters');
  if (!rail) return;
  const records = savedWatchRecords;
  if (records.length <= 8) railRecordsExpanded = false;
  const posterButton = record => {
    const localTitle = onboardingTitles[record.series_id];
    const title = record.title || record.name || localTitle?.title || '작품';
    const image = record.poster_url || (localTitle ? onboardingImage(localTitle) : '');
    return `<button class="rail-record-poster ${record.series_id === activeSeriesId ? 'active' : ''}" type="button" data-rail-series="${escapeHtml(record.series_id)}" title="${escapeHtml(title)}">${image ? `<img src="${escapeHtml(image)}" alt="${escapeHtml(title)}">` : '<span>AW</span>'}</button>`;
  };
  const visible = railRecordsExpanded ? records : records.slice(0, 8);
  let html = visible.map(posterButton).join('');
  if (!railRecordsExpanded && records.length > 8) {
    const rotating = records.slice(8, 14).map((record, index) => {
      const localTitle = onboardingTitles[record.series_id];
      const image = record.poster_url || (localTitle ? onboardingImage(localTitle) : '');
      return image ? `<img src="${escapeHtml(image)}" alt="" style="--poster-index:${index}">` : '';
    }).join('');
    html += `<button type="button" class="rail-record-more-tile" data-rail-toggle="expand"><span class="rail-more-posters">${rotating}</span><span class="rail-more-shade"></span><b>${records.length - 8}개 작품<br>더보기</b></button>`;
  }
  rail.innerHTML = html;
  const more = $('#rail-records-more');
  if (more) {
    more.hidden = !railRecordsExpanded;
    more.textContent = '시청 기록 접기 ↑';
    more.dataset.railToggle = 'collapse';
  }
  const watching = records.filter(record => record.status === 'watching');
  const tip = $('#rail-watch-tip');
  if (tip) {
    const names = watching.slice(0, 2).map(record => record.title || record.name || onboardingTitles[record.series_id]?.title || '선택한 작품');
    const titleText = `${names.join(', ')}${watching.length > 2 ? ` 외 ${watching.length - 2}작품` : ''}`;
    const exampleTitle = records[0]?.title || records[0]?.name || onboardingTitles[records[0]?.series_id]?.title || '좋아하는 작품';
    railTipMessages = [
      watching.length ? `시청 중인 ${titleText}에서 어디까지 기억나는지 말해주시면, 어느 회차까지 봤는지 찾아드려요!` : '기억나는 장면을 말해주시면 어느 작품의 몇 화인지 찾아드려요!',
      `좋아하는 작품과 비슷한 애니를 찾으려면 “${exampleTitle} 같은 애니 알려줘”를 쳐보세요!`,
      '스포일러 없는 애니 추천 문구를 받아서 친구에게 바로 보내보세요!'
    ];
    tip.hidden = records.length === 0;
    railTipIndex %= railTipMessages.length;
    showRailTip();
    clearInterval(railTipTimer);
    railTipTimer = setInterval(() => advanceRailTip(1), 5500);
  }
}

function showRailTip() {
  const tip = $('#rail-watch-tip');
  if (!tip || tip.hidden || !railTipMessages.length) return;
  $('p', tip).textContent = railTipMessages[railTipIndex];
  $('.tip-index', tip).textContent = `${railTipIndex + 1}/${railTipMessages.length}`;
}

function advanceRailTip(direction) {
  if (!railTipMessages.length) return;
  railTipIndex = (railTipIndex + direction + railTipMessages.length) % railTipMessages.length;
  showRailTip();
}

async function persistOnboardingRecords(records) {
  const saved = [];
  for (const record of records) {
    const result = await api(`/api/records/${encodeURIComponent(record.series_id)}`, {
      method:'PUT',
      body:JSON.stringify({ seen_ep:recordAbsoluteEpisode(record), rating:record.rating ?? null })
    });
    saved.push({ ...record, ...result, title:record.title || result.name, seen_ep:record.seen_ep });
  }
  return saved;
}

function renderLibrary() {
  const grid = $('#library-grid');
  if (!grid) return;
  grid.replaceChildren();
  savedWatchRecords.forEach(record => {
    const localTitle = onboardingTitles[record.series_id];
    const title = record.title || record.name || localTitle?.title || '제목 정보 없음';
    const imageUrl = record.poster_url || (localTitle ? onboardingImage(localTitle) : '');
    const status = record.status === 'planned' ? '보고 싶어요' : record.status === 'completed' ? '완료' : '시청 중';
    const position = record.status === 'planned' ? '아직 시청 전' : `${record.season_name ? `${record.season_name} · ` : ''}${record.seen_ep || 0}화까지`;
    const article = document.createElement('article');
    article.className = `watch-card featured real-record record-${record.status || 'watching'}`;
    article.dataset.recordSeries = record.series_id;
    article.innerHTML = `<div class="record-poster-shell">${imageUrl ? `<img src="${escapeHtml(imageUrl)}" alt="${escapeHtml(title)} 포스터">` : '<div class="record-cover-fallback">AniWhere</div>'}<div class="record-card-overlay"><strong>${escapeHtml(title)}</strong>${record.status !== 'planned' ? '<button type="button" data-record-action="recap">3분 복습</button>' : ''}<button type="button" data-record-action="providers">시청처 보기</button><button type="button" data-record-action="edit">기록 수정</button></div></div><div class="watch-copy"><span class="watching record-status">${record.status === 'completed' ? '✓ 시청 완료' : status}</span><h2>${escapeHtml(title)}</h2><p>${escapeHtml(position)}</p><small>${record.status === 'planned' ? '시청을 시작하면 스포일러 보호 범위를 설정할 수 있어요.' : record.status === 'completed' ? '전 회차를 시청 완료한 작품입니다.' : '저장한 회차 이후 정보는 보호됩니다.'}</small><button type="button" class="record-edit-button" data-record-edit="${escapeHtml(record.series_id)}">기록 수정</button></div>`;
    grid.appendChild(article);
  });
  renderRailRecords();
  loadPersonalRecommendations();
}

function saveLocalRecord(record) {
  if (!record?.series_id) return;
  const normalized = { ...record, title:record.title || record.name, status:record.status || 'watching' };
  const index = savedWatchRecords.findIndex(item => item.series_id === normalized.series_id);
  if (index >= 0) savedWatchRecords[index] = { ...savedWatchRecords[index], ...normalized };
  else savedWatchRecords.unshift(normalized);
  localStorage.setItem(WATCH_RECORDS_KEY, JSON.stringify(savedWatchRecords));
  setRecordState(true); renderLibrary();
}

function persistConversation() {
  localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(chatHistory.slice(-20)));
  localStorage.setItem(CHAT_MESSAGES_KEY, JSON.stringify(visualConversation.slice(-40)));
}

function addMessage(role, text, card = '', persist = true) {
  const row = document.createElement('div');
  row.className = `message ${role}`;
  if (role === 'agent') row.innerHTML = persona === 'l'
    ? '<span class="avatar l-avatar"><img src="assets/L.png" alt="L"></span>'
    : '<span class="avatar midoriya-avatar"><img src="assets/midoriya-mascot.png?v=2" alt="미도리야"></span>';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.innerHTML = `<div>${text}</div>${card}`;
  row.appendChild(bubble);
  messages.appendChild(row);
  if (persist) {
    visualConversation.push({ role, text, card });
    persistConversation();
  }
  requestAnimationFrame(() => messages.scrollTo({ top: messages.scrollHeight, behavior: 'smooth' }));
}

function setPersona(next) {
  persona = next;
  const image = $('.agent-dot img');
  if (!image) return;
  if (next === 'l') {
    image.src = 'assets/L.png';
    image.alt = 'L 취향 탐정';
    $('.agent-dot').classList.add('l-agent-dot');
  } else {
    image.src = 'assets/midoriya-mascot.png?v=2';
    image.alt = 'AniWhere Agent';
    $('.agent-dot').classList.remove('l-agent-dot');
  }
}

function restoreConversation() {
  if (!visualConversation.length) return false;
  messages.replaceChildren();
  visualConversation.forEach(message => addMessage(message.role, message.text, message.card || '', false));
  $$('[data-series-id]', messages).forEach(card => { hydrateResultPoster(card.dataset.seriesId, card); hydrateWatchProviders(card.dataset.seriesId, card); });
  const lastContext = [...chatHistory].reverse().find(turn => turn.role === 'assistant' && turn.context?.series_id)?.context;
  if (lastContext) applyConversationContext(lastContext.series_id, lastContext.seen_ep ?? null, lastContext.title || '', lastContext.candidate_ep ?? null);
  else clearConversationContext();
  return true;
}

function setSuggestions(items = []) {
  suggestions.replaceChildren();
  items.forEach(item => {
    const label = typeof item === 'string' ? item : item.label;
    const message = typeof item === 'string' ? item : item.message;
    const action = typeof item === 'string' ? null : item.action;
    const button = document.createElement('button');
    button.type = 'button'; button.textContent = label;
    button.addEventListener('click', () => {
      if (action === 'dictionary') openDictionary();
      else if (action === 'recap') hasRecord ? openRecap() : showToast('복습할 시청 기록을 먼저 추가해 주세요.');
      else if (action === 'providers') activeSeriesId ? openProviders() : send('내 시청 기록 중 볼 수 있는 곳을 알려줘');
      else send(message || label);
    });
    suggestions.appendChild(button);
  });
}

function setQuickSuggestions() {
  setSuggestions([
    { label:'3분 복습', action:'recap' },
    { label:'시청처 보기', action:'providers' },
    { label:'인물 사전', action:'dictionary' }
  ]);
}

function reply(text, labels = [], card = '', actions = ['시청 기록 확인 중…', '관련 청크 찾는 중…']) {
  busy = true; setSuggestions();
  const typing = document.createElement('div'); typing.className = 'typing';
  typing.innerHTML = `<i></i><span>${actions[0]}</span>`; messages.appendChild(typing);
  let index = 0;
  const timer = setInterval(() => { index += 1; if (actions[index]) $('span', typing).textContent = actions[index]; }, 650);
  setTimeout(() => { clearInterval(timer); typing.remove(); addMessage('agent', text, card); setSuggestions(labels); busy = false; question.focus(); }, Math.max(1200, actions.length * 680));
}

function resetChat() {
  mode = 'chat'; setPersona('midoriya'); step = 0; busy = false; tasteInterview.active = false; tasteInterview.step = 0; tasteInterview.answers = []; chatHistory = []; visualConversation = [];
  latestReview = null; clearConversationContext();
  localStorage.removeItem(CHAT_HISTORY_KEY); localStorage.removeItem(CHAT_MESSAGES_KEY);
  messages.replaceChildren(); setSuggestions();
  addMessage('agent', '애니에 관한 무엇이든 물어보세요! 흐릿하게 기억나는 장면도 작품과 회차까지 함께 찾아드릴게요.');
  setQuickSuggestions();
}

function startTasteInterview() {
  $('[data-view="chat"]').click();
  setPersona('l'); messages.replaceChildren(); visualConversation = []; chatHistory = [];
  tasteInterview.active = true; tasteInterview.step = 0; tasteInterview.answers = [];
  $('#chat-kicker').textContent = 'L · TASTE DETECTIVE';
  $('#chat-title').innerHTML = '당신의 취향을<br>추리하겠습니다.';
  addMessage('agent', `저는 L입니다. 다섯 가지 단서로 당신의 취향을 추리하겠습니다. ${tasteQuestions[0]}`, '<div class="result-card l-case"><img class="l-chat-panel" src="assets/l-detective-user.png" alt="취향을 추리하는 L"><small>CASE 001 · TASTE PROFILE</small><h3>추리를 시작합니다.</h3><p>분위기 · 전개 속도 · 인물 관계 · 제외 요소를 분석합니다.</p></div>');
  setSuggestions(['딱 떠오르는 작품이 없어요']);
}

function resultCardFromChat(data) {
  const results = data.results || {};
  const found = results.find;
  if (found?.candidates?.length) {
    const candidate = found.candidates[0];
    return `<div class="result-card result-with-poster" data-series-id="${escapeHtml(candidate.series_id)}"><div class="result-copy"><small>${found.status === 'episode' ? '회차 후보' : '작품 후보'}</small><h3>${escapeHtml(candidate.title || candidate.name || candidate.series_id)}</h3><p>${escapeHtml(candidate.label || (candidate.abs_ep ? `전체 ${candidate.abs_ep}화` : '추가 단서를 알려주세요.'))}</p></div><div class="result-poster-placeholder" aria-hidden="true">AniWhere</div></div>`;
  }
  const searched = results.search_series?.items || [];
  if (searched.length === 1) {
    const series = searched[0];
    return `<div class="result-card result-with-poster" data-series-id="${escapeHtml(series.series_id)}"><div class="result-copy"><small>작품 확인</small><h3>${escapeHtml(series.name || series.title || series.series_id)}</h3><p>이 작품에 대해 이어서 물어보세요.</p></div>${series.poster_url ? `<img class="result-poster" src="${escapeHtml(series.poster_url)}" alt="${escapeHtml(series.name || series.title || '')} 포스터">` : '<div class="result-poster-placeholder" aria-hidden="true">AniWhere</div>'}</div>`;
  }
  const review = results.review;
  if (review?.answer) return `<div class="result-card"><small>${review.seen_ep}화까지 복습</small><p>${escapeHtml(review.answer)}</p><button type="button" class="result-recap-button" data-open-review>3분 요약 열기 →</button></div>`;
  const watching = results.where_to_watch;
  if (watching?.seasons?.length) return `<div class="result-card provider-overview result-with-poster" data-series-id="${escapeHtml(watching.series_id || data.context?.series_id || '')}"><div class="result-copy"><small>시청처 안내</small><h3>${escapeHtml(watching.title)}</h3><p>${watching.seasons.map(season => `${escapeHtml(season.name)} · ${season.providers.map(escapeHtml).join(', ')}`).join('<br>')}</p></div><div class="result-poster-placeholder" aria-hidden="true">AniWhere</div><div class="result-providers">${providerButtons(watching)}</div></div>`;
  const recommended = results.recommend?.picks || [];
  if (recommended.length) return `<div class="recommendation-result-grid">${recommended.map(pick => `<div class="result-card taste-pick result-with-poster" data-series-id="${escapeHtml(pick.series_id)}"><div class="result-copy"><small>취향 추천</small><h3>${escapeHtml(pick.title)}</h3><p>${escapeHtml(pick.reason)}</p></div>${pick.poster_url ? `<img class="result-poster" src="${escapeHtml(pick.poster_url)}" alt="${escapeHtml(pick.title)} 포스터">` : '<div class="result-poster-placeholder" aria-hidden="true">AniWhere</div>'}</div>`).join('')}</div>`;
  return '';
}

const providerMeta = {
  netflix: { label:'Netflix', logo:'assets/netflix.png', search:title => `https://www.netflix.com/search?q=${encodeURIComponent(title)}` },
  '넷플릭스': { label:'Netflix', logo:'assets/netflix.png', search:title => `https://www.netflix.com/search?q=${encodeURIComponent(title)}` },
  crunchyroll: { label:'Crunchyroll', logo:'assets/crunchyroll.png', search:title => `https://www.crunchyroll.com/search?q=${encodeURIComponent(title)}` },
  tving: { label:'TVING', logo:'assets/tving.png', search:title => `https://www.tving.com/search?keyword=${encodeURIComponent(title)}` },
  '티빙': { label:'TVING', logo:'assets/tving.png', search:title => `https://www.tving.com/search?keyword=${encodeURIComponent(title)}` },
  watcha: { label:'왓챠', logo:'assets/watcha.png', search:title => `https://watcha.com/ko/search?query=${encodeURIComponent(title)}` },
  '왓챠': { label:'왓챠', logo:'assets/watcha.png', search:title => `https://watcha.com/ko/search?query=${encodeURIComponent(title)}` },
  wavve: { label:'Wavve', logo:'assets/wavve.png', search:title => `https://www.wavve.com/search?searchWord=${encodeURIComponent(title)}` },
  '웨이브': { label:'Wavve', logo:'assets/wavve.png', search:title => `https://www.wavve.com/search?searchWord=${encodeURIComponent(title)}` }
};

function providerInfo(name) {
  const key = String(name || '').trim().toLowerCase();
  if (key.includes('netflix')) return providerMeta.netflix;
  return providerMeta[key] || providerMeta[String(name || '').trim()] || null;
}

function safeExternalUrl(value) {
  try { const url = new URL(value); return ['http:','https:'].includes(url.protocol) ? url.href : ''; } catch { return ''; }
}

function providerButtons(data) {
  const providers = [];
  (data.seasons || []).forEach(season => (season.providers || []).forEach(name => {
    if (/laftel|라프텔/i.test(String(name || ''))) return;
    const meta = providerInfo(name);
    const identity = meta ? `known:${meta.label}` : `raw:${String(name).trim().toLowerCase()}`;
    if (!providers.some(item => item.identity === identity)) providers.push({ name, season, identity });
  }));
  providers.sort((a, b) => Number(Boolean(providerInfo(b.name))) - Number(Boolean(providerInfo(a.name))));
  const buttons = providers.map(({ name }) => {
    const meta = providerInfo(name);
    if (!meta) return `<span class="ott-button ott-unknown">${escapeHtml(name)}</span>`;
    return `<a class="ott-button" href="${meta.search(data.title)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(data.title)} ${meta.label}에서 검색"><img src="${meta.logo}" alt=""><span>${meta.label}</span></a>`;
  }).join('');
  const checked = [...new Set((data.seasons || []).map(season => season.checked_at).filter(Boolean))].sort().at(-1);
  const sourceLink = safeExternalUrl((data.seasons || []).find(season => season.link)?.link);
  return providers.length ? `<div class="ott-actions">${buttons}</div><div class="provider-meta">${checked ? `확인일 ${escapeHtml(checked)}` : ''}${sourceLink ? `<a href="${sourceLink}" target="_blank" rel="noopener noreferrer">전체 제공처 확인 ↗</a>` : ''}</div>` : '<p class="provider-empty">현재 확인된 국내 구독형 시청처가 없어요.</p>';
}

async function hydrateWatchProviders(seriesId, card = null) {
  if (!seriesId) return;
  const target = card || $(`.result-card[data-series-id="${CSS.escape(seriesId)}"]:last-of-type`, messages);
  if (!target || target.querySelector('.result-providers')) return;
  const area = document.createElement('div');
  area.className = 'result-providers loading'; area.textContent = '시청 가능한 OTT 확인 중…';
  target.appendChild(area);
  try {
    const data = await api(`/api/series/${encodeURIComponent(seriesId)}/where-to-watch`);
    area.classList.remove('loading'); area.innerHTML = providerButtons(data);
  } catch { area.remove(); }
}

async function hydrateResultPoster(seriesId, card = null) {
  if (!seriesId) return;
  const target = card || $(`.result-card[data-series-id="${CSS.escape(seriesId)}"]:last-of-type`, messages);
  if (!target) return;
  try {
    const series = await api(`/api/series/${encodeURIComponent(seriesId)}`);
    if (!series.poster_url) return;
    const image = document.createElement('img');
    image.className = 'result-poster'; image.src = series.poster_url; image.alt = `${series.name || series.title || '애니'} 포스터`;
    target.querySelector('.result-poster-placeholder')?.replaceWith(image);
  } catch {}
}

async function handleTasteInterview(text) {
  addMessage('user', escapeHtml(text)); question.value = ''; resizeComposer();
  tasteInterview.answers.push(text); tasteInterview.step += 1;
  if (tasteInterview.step < tasteQuestions.length) {
    reply(tasteQuestions[tasteInterview.step], ['잘 모르겠어요']);
    return;
  }
  busy = true; setSuggestions();
  const typing = document.createElement('div'); typing.className = 'typing';
  typing.innerHTML = '<i></i><span>L이 취향의 공통점을 추리하고 있어요…</span>'; messages.appendChild(typing);
  const likes = tasteQuestions.map((promptText, index) => `${promptText} ${tasteInterview.answers[index]}`).join('\n');
  try {
    const data = await api('/api/recommend', { method:'POST', body:JSON.stringify({ likes }) });
    typing.remove(); tasteInterview.active = false;
    const cards = (data.picks || []).map(pick => `<div class="result-card taste-pick result-with-poster" data-series-id="${escapeHtml(pick.series_id)}"><div class="result-copy"><small>L · RECOMMENDATION</small><h3>${escapeHtml(pick.title)}</h3><p>${escapeHtml(pick.reason)}</p></div>${pick.poster_url ? `<img class="result-poster" src="${escapeHtml(pick.poster_url)}" alt="${escapeHtml(pick.title)} 포스터">` : '<div class="result-poster-placeholder">AniWhere</div>'}</div>`).join('');
    addMessage('agent', data.picks?.length ? `추리가 끝났습니다. ${escapeHtml(data.mood || '당신의 취향')}에 가까운 작품들이에요.` : escapeHtml(data.follow_up || '추천 후보를 찾지 못했습니다.'), cards);
    const pickCount = (data.picks || []).length;
    if (pickCount) $$('[data-series-id]', messages).slice(-pickCount).forEach(card => hydrateWatchProviders(card.dataset.seriesId, card));
    setSuggestions(['다시 추리하기', 'AI 대화로 돌아가기']);
  } catch (error) {
    typing.remove(); tasteInterview.active = false; addMessage('agent', `추천을 불러오지 못했어요. ${escapeHtml(error.message)}`);
  } finally { busy = false; question.focus(); }
}

async function send(value) {
  const text = value.trim(); if (!text || busy) return;
  if (text === '다시 추리하기') { startTasteInterview(); return; }
  if (text === 'AI 대화로 돌아가기') { resetChat(); return; }
  if (persona === 'l' && tasteInterview.active) { handleTasteInterview(text); return; }
  if (text === '3분 복습') { if (hasRecord) openRecap('직전 내용'); else showToast('복습할 시청 지점을 먼저 찾아주세요.'); return; }
  if (text === '시청처 보기') { openProviders(); return; }
  addMessage('user', escapeHtml(text)); question.value = ''; resizeComposer();
  busy = true; setSuggestions();
  const typing = document.createElement('div'); typing.className = 'typing';
  typing.innerHTML = '<i></i><span>Agent가 답변을 생각하고 있어요…</span>'; messages.appendChild(typing);
  try {
    const apiMessage = persona === 'l' ? `추천: ${text}` : text;
    const data = await api('/api/chat', { method:'POST', body:JSON.stringify({ message:apiMessage, history:chatHistory.slice(-20) }) });
    typing.remove();
    latestReview = data.results?.review || null;
    addMessage('agent', formatAgentText(data.answer), resultCardFromChat(data));
    const foundCandidates = data.results?.find?.candidates || [];
    const foundSeriesId = foundCandidates[0]?.series_id;
    if (foundSeriesId) { hydrateResultPoster(foundSeriesId); hydrateWatchProviders(foundSeriesId); }
    $$('[data-series-id]', messages).slice(-8).forEach(card => {
      if (!card.dataset.seriesId) return;
      hydrateResultPoster(card.dataset.seriesId, card);
      if (!card.querySelector('.result-providers')) hydrateWatchProviders(card.dataset.seriesId, card);
    });
    const nextSuggestions = data.suggestions || [];
    if (!nextSuggestions.length && activeCandidateEp != null && /^(응|네|맞아|맞아요|그래|그거야)[.! ]*$/.test(text)) {
      nextSuggestions.push({ label:`${activeCandidateEp}화까지 봤어요`, message:`${activeSeriesTitle} ${activeCandidateEp}화까지 봤어` });
    }
    setQuickSuggestions();
    chatHistory.push({ role:'user', content:apiMessage }, { role:'assistant', content:data.answer, context:data.context || null });
    persistConversation();
    if (data.results?.save_record) saveLocalRecord(data.results.save_record);
    const contextSeriesId = data.context?.series_id || (foundCandidates.length === 1 ? foundSeriesId : null);
    const seenEp = data.context?.seen_ep ?? data.results?.save_record?.seen_ep ?? data.results?.review?.seen_ep ?? null;
    const contextTitle = data.context?.title || data.results?.find?.candidates?.[0]?.title || '';
    if (contextSeriesId) applyConversationContext(contextSeriesId, seenEp, contextTitle, data.context?.candidate_ep ?? null);
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
  if (!activeSeriesId) { showToast('먼저 대화에서 작품을 찾아주세요.'); return; }
  const modes = { '전체 이야기':'summary', '인물 관계':'characters', '마지막 화 상황':'last', '직전 내용':'last' };
  openDrawer('FEATURE 09', `스포일러 없는 ${selected}`, '<div class="drawer-card"><p>저장된 시청 기록을 확인하고 있어요…</p></div>');
  try {
    const localRecord = savedWatchRecords.find(record => record.series_id === activeSeriesId && record.status !== 'planned');
    if (localRecord) {
      await api(`/api/records/${encodeURIComponent(activeSeriesId)}`, {
        method:'PUT',
        body:JSON.stringify({ seen_ep:recordAbsoluteEpisode(localRecord), rating:localRecord.rating ?? null })
      });
    }
    const data = await api('/api/review', { method:'POST', body:JSON.stringify({ series_id:activeSeriesId, seen_ep:null, mode:modes[selected] || 'summary' }) });
    if (data.seen_ep == null) {
      const series = await api(`/api/series/${encodeURIComponent(activeSeriesId)}`).catch(() => null);
      const title = series?.name || series?.title || activeSeriesTitle || '현재 작품';
      const max = Number(series?.total_episodes || 9999);
      $('#drawer-content').innerHTML = `<div class="drawer-card recap-checkpoint"><small>현재 확인된 작품</small><h3>${escapeHtml(title)}</h3><p>작품과 회차를 찾은 것만으로는 그 회차까지 시청했다고 판단하지 않아요. 스포일러 없는 복습 범위를 알려주세요.</p>${activeCandidateEp != null ? `<button type="button" class="copy-button recap-candidate" data-recap-episode="${activeCandidateEp}">찾은 ${activeCandidateEp}화까지 봤어요</button>` : ''}<form id="recap-checkpoint-form"><label>마지막으로 본 전체 회차<input id="recap-checkpoint-episode" type="number" min="1" max="${max}" required placeholder="예: 34"></label><button type="submit">기록하고 3분 복습 열기</button></form></div>`;
      const saveAndReview = async episode => {
        const seenEp = Number(episode);
        const saved = await api(`/api/records/${encodeURIComponent(activeSeriesId)}`, { method:'PUT', body:JSON.stringify({ seen_ep:seenEp, rating:null }) });
        saveLocalRecord({ ...saved, title:saved.name || title, poster_url:saved.poster_url || series?.poster_url || '', status:'watching', season_name:'전체 회차', seen_ep:seenEp });
        await applyConversationContext(activeSeriesId, seenEp, title);
        openRecap(selected);
      };
      $('[data-recap-episode]')?.addEventListener('click', event => saveAndReview(event.currentTarget.dataset.recapEpisode).catch(error => showToast(error.message)));
      $('#recap-checkpoint-form')?.addEventListener('submit', event => { event.preventDefault(); saveAndReview($('#recap-checkpoint-episode').value).catch(error => showToast(error.message)); });
      return;
    }
    showRecapData(data);
  } catch (error) {
    const message = error.name === 'TimeoutError' ? '응답 시간이 길어졌어요. 대화에 표시된 요약은 그대로 볼 수 있고, 잠시 뒤 다시 시도해 주세요.' : error.message;
    $('#drawer-content').innerHTML = `<div class="drawer-card"><h3>복습을 불러오지 못했어요.</h3><p>${escapeHtml(message)}</p><button type="button" class="copy-button" data-retry-recap>다시 시도</button></div>`;
    $('[data-retry-recap]')?.addEventListener('click', () => openRecap(selected));
  }
}

function showRecapData(data) {
  openDrawer('FEATURE 09', '스포일러 없는 3분 요약', '');
  const cleanAnswer = String(data.answer || data.follow_up || '요약 내용이 없습니다.').replace(/\s*(?:\[\d+\])+/g, '').trim();
  const koreanDetail = text => {
    const lines = String(text || '').split(/\n+/).slice(1).filter(line => /[가-힣]/.test(line));
    return lines.slice(1).join(' ').trim() || lines.join(' ').trim() || '한국어 상세 설명이 준비되지 않았어요.';
  };
  const sources = (data.sources || []).map(source => `<article class="drawer-card recap-source"><small>${escapeHtml(source.episode_label || `${activeSeriesTitle || '작품'} 전체 ${source.abs_ep}화`)}</small><p>${escapeHtml(koreanDetail(source.text))}</p></article>`).join('');
  const details = sources ? `<details class="recap-details"><summary>더 자세히 복습할래요 <span>${data.sources.length}개 회차</span></summary><div class="recap-source-list">${sources}</div></details>` : '';
  $('#drawer-content').innerHTML = `<div class="drawer-card recap-summary"><h3>${data.seen_ep}화까지의 복습</h3><p>${escapeHtml(cleanAnswer)}</p></div>${details}<section class="recap-safety-card"><div class="recap-safety-visual"><img src="assets/eren-spoiler-user.png" alt="스포일러를 막는 에렌 예거"><strong><i>!</i> 스포 금지</strong></div><div class="recap-safety-copy"><small>SPOILER BLOCKED</small><h3>여기부터는 철벽 보호 중</h3><p>전체 ${data.seen_ep}화까지만 사용했어요.<br>${data.seen_ep}화 이후 내용은 검색 전에 차단합니다.</p></div></section>`;
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
    $('#drawer-content').innerHTML = `<div class="drawer-card provider-overview"><h3>${escapeHtml(data.title)}</h3>${providerButtons(data)}</div>` + data.seasons.map(season => `<div class="drawer-card"><h3>${escapeHtml(season.name)}</h3><p>${(season.providers || []).map(escapeHtml).join(' · ') || '확인된 구독형 제공처 없음'}</p><small>확인일 ${escapeHtml(season.checked_at || '정보 없음')}</small></div>`).join('') + `<div class="drawer-card"><small>${escapeHtml(data.attribution)}</small></div>`;
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
  $('#hunter-detail').innerHTML = `<small>SPOILER SAFE · EP ${episode}</small><h3>${hunterCheckpoints[episode] || `내 시청 기록 · ${episode}화`}</h3><p>이 시점까지 확인된 인물과 관계만 연결했어요. 노드나 선을 선택해 설명을 확인하세요.</p><span>${episode < 139 ? '잠긴 실루엣은 이후 회차에 공개됩니다.' : '준비된 모든 관계가 공개됐어요.'}</span>`;
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

function openHunterDictionary(seenEp = 63) {
  const safeEpisode = Math.max(0, Number(seenEp ?? 63));
  const checkpointOptions = Object.entries(hunterCheckpoints).filter(([episode]) => Number(episode) <= safeEpisode);
  if (!checkpointOptions.some(([episode]) => Number(episode) === safeEpisode)) checkpointOptions.push([String(safeEpisode), `내 시청 기록 · ${safeEpisode}화`]);
  checkpointOptions.sort((a, b) => Number(a[0]) - Number(b[0]));
  const categories = ['전체', ...new Set(hunterDictionary.map(([, category]) => category))];
  openDrawer('PROTOTYPE · FEATURE 08', '헌터×헌터 관계도·용어 사전', `
    <div class="dictionary-toolbar">
      <div><small>시청 기록과 연동된 지점</small><select id="dictionary-checkpoint">${checkpointOptions.map(([episode, label]) => `<option value="${episode}"${Number(episode) === safeEpisode ? ' selected' : ''}>${label}</option>`).join('')}</select></div>
      <span class="dictionary-safe" id="dictionary-safe-label">${safeEpisode}화까지 공개</span>
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

function isHunterTitle(title) { return /헌터\s*[×xX]?\s*헌터|hunter\s*[×xX]?\s*hunter/i.test(title || ''); }

const dictionaryKorean = {
  'Caesar Zeppeli':'윌 A. 체펠리의 손자이자 파문 전사입니다. 침착하고 세련된 성격이며 조셉과 함께 기둥 속 사내들과 맞섭니다.',
  'Dio Brando':'죠스타 가문과 깊은 악연으로 얽힌 인물입니다. 강한 야망과 집착을 지녔으며 이야기의 핵심 대립을 만듭니다.',
  'Jonathan Joestar':'정직하고 정의로운 죠스타 가문의 후계자입니다. 디오와의 갈등 속에서 신사로서의 신념을 지키며 성장합니다.',
  'Joseph Joestar':'재치와 임기응변이 뛰어난 죠스타 가문의 인물입니다. 상대의 수를 읽는 독특한 전투 방식으로 위기를 돌파합니다.',
  'Denji':'빚을 갚기 위해 데빌 헌터로 살아가던 소년입니다. 포치타와 계약한 뒤 체인소의 힘을 사용할 수 있게 됩니다.',
  'Makima':'공안 소속 데빌 헌터로 덴지를 조직에 받아들인 인물입니다. 차분하고 위압적인 분위기로 주변 사람들을 이끕니다.',
  'Aki Hayakawa':'공안 대마 특이과 소속 데빌 헌터입니다. 악마에게 가족을 잃은 뒤 복수를 목표로 싸우고 있습니다.',
  'Power':'피의 마인으로 덴지와 함께 공안에서 활동합니다. 제멋대로인 성격이지만 동료들과 함께하며 관계가 달라집니다.',
  'Bouryoku no Majin':'공안에서 활동하는 폭력의 마인입니다. 강한 힘을 억제하기 위해 항상 독성이 있는 가면을 착용합니다.'
};
const dictionaryKoreanNames = {
  'Caesar Zeppeli':'시저 안토니오 체펠리', 'Dio Brando':'디오 브란도',
  'Jonathan Joestar':'조나단 죠스타', 'Joseph Joestar':'죠셉 죠스타',
  'Denji':'덴지', 'Makima':'마키마', 'Aki Hayakawa':'하야카와 아키',
  'Power':'파워', 'Bouryoku no Majin':'폭력의 마인'
};

function koreanDictionaryDescription(entry) {
  if (dictionaryKorean[entry.name]) return dictionaryKorean[entry.name];
  if (/[가-힣]/.test(entry.text || '')) return entry.text;
  return '한국어 인물 설명을 준비하고 있어요. 현재는 이름과 최초 등장 회차를 기준으로 스포일러 없이 표시합니다.';
}

function hunterPrototypeTeaser() {
  return `<section class="hunter-prototype-teaser"><div><small>HUNTER × HUNTER · PROTOTYPE</small><h3>인물 관계도와 용어 사전</h3><p>열심히 만든 기존 관계선·인물 사진·회차별 공개 범위를 그대로 확인할 수 있어요.</p></div><img src="assets/zoldyck-family-map.png" alt="헌터×헌터 인물 관계도 미리보기"><button type="button" data-open-hunter-prototype>관계도·용어 사전 열기 →</button></section>`;
}

async function showSeriesDictionary(seriesId, title, posterUrl, seenEp = null) {
  if (isHunterTitle(title)) { openHunterDictionary(seenEp); return; }
  if (seenEp == null) {
    openDrawer('FEATURE 08 · SPOILER SAFE', `${title} 인물 사전`, `<div class="dictionary-series-head">${posterUrl ? `<img src="${escapeHtml(posterUrl)}" alt="">` : ''}<div><h3>어디까지 봤나요?</h3><p>선택한 회차까지 등장한 인물만 보여드려요.</p></div></div><form class="dictionary-episode-form" id="dictionary-episode-form"><label>전체 기준 회차<input id="dictionary-episode-input" type="number" min="1" value="1" required></label><button>인물 사전 열기</button></form><button class="text-button" data-dictionary-browse>← 다른 작품 찾기</button>${hunterPrototypeTeaser()}`);
    $('#dictionary-episode-form').addEventListener('submit', event => { event.preventDefault(); showSeriesDictionary(seriesId, title, posterUrl, Number($('#dictionary-episode-input').value)); });
    $('[data-dictionary-browse]').addEventListener('click', openDictionary);
    $('[data-open-hunter-prototype]')?.addEventListener('click', openHunterDictionary);
    return;
  }
  openDrawer('FEATURE 08 · SPOILER SAFE', `${title} 인물 사전`, '<div class="drawer-card"><p>현재 회차까지의 인물을 불러오고 있어요…</p></div>');
  try {
    const suffix = seenEp == null ? '' : `?seen_ep=${encodeURIComponent(seenEp)}`;
    const data = await api(`/api/series/${encodeURIComponent(seriesId)}/dictionary${suffix}`);
    if (data.seen_ep == null) { showSeriesDictionary(seriesId, title, posterUrl, null); return; }
    const characters = (data.entries || []).filter(entry => ['character','appearance'].includes(entry.kind));
    const entries = characters.map(entry => `<article class="dictionary-api-entry"><small>인물 · ${entry.first_ep || '?'}화 공개</small><h3>${escapeHtml(dictionaryKoreanNames[entry.name] || entry.name)}</h3><p>${escapeHtml(koreanDictionaryDescription(entry))}</p></article>`).join('');
    $('#drawer-content').innerHTML = `<div class="dictionary-series-head">${posterUrl ? `<img src="${escapeHtml(posterUrl)}" alt="${escapeHtml(title)} 포스터">` : ''}<div><small>${data.seen_ep}화까지 공개</small><h3>${escapeHtml(title)}</h3><p>이후 회차에 처음 등장하는 인물은 숨겼어요.</p></div></div>${entries || '<div class="drawer-card"><p>이 작품은 아직 준비된 인물 데이터가 없어요.</p></div>'}<button class="text-button" data-dictionary-browse>← 더 많은 작품의 인물 사전 찾기</button>${hunterPrototypeTeaser()}`;
    $('[data-dictionary-browse]').addEventListener('click', openDictionary);
    $('[data-open-hunter-prototype]')?.addEventListener('click', openHunterDictionary);
  } catch (error) { $('#drawer-content').innerHTML = `<div class="drawer-card"><h3>사전을 불러오지 못했어요.</h3><p>${escapeHtml(error.message)}</p></div><button class="text-button" data-dictionary-browse>← 다른 작품 찾기</button>`; $('[data-dictionary-browse]').addEventListener('click', openDictionary); }
}

async function loadDictionaryCatalog(query = '') {
  const grid = $('#dictionary-catalog-grid');
  if (!grid) return;
  grid.innerHTML = '<p>작품을 불러오는 중…</p>';
  try {
    const items = await api(`/api/series?limit=200${query ? `&q=${encodeURIComponent(query)}` : ''}`);
    grid.innerHTML = items.map(item => `<button type="button" data-dictionary-series="${escapeHtml(item.series_id)}" data-title="${escapeHtml(item.name || item.title)}" data-poster="${escapeHtml(item.poster_url || '')}">${item.poster_url ? `<img src="${escapeHtml(item.poster_url)}" alt="">` : '<span>AW</span>'}<b>${escapeHtml(item.name || item.title)}</b></button>`).join('') || '<p>검색 결과가 없어요.</p>';
  } catch (error) { grid.innerHTML = `<p>${escapeHtml(error.message)}</p>`; }
}

function openDictionary() {
  const records = savedWatchRecords.filter(record => record.status !== 'planned');
  const current = records.find(record => record.series_id === activeSeriesId) || records[0];
  const others = current ? records.filter(record => record.series_id !== current.series_id) : records;
  const dictionaryCard = (record, featured = false) => { const safeEpisode = Number(recordAbsoluteEpisode(record)); const title = record.title || record.name || onboardingTitles[record.series_id]?.title || '작품'; const poster = record.poster_url || (onboardingTitles[record.series_id] ? onboardingImage(onboardingTitles[record.series_id]) : ''); return `<button type="button" class="${featured ? 'dictionary-current-card' : ''}" data-dictionary-series="${escapeHtml(record.series_id)}" data-title="${escapeHtml(title)}" data-poster="${escapeHtml(poster)}" data-seen="${safeEpisode}">${poster ? `<img src="${escapeHtml(poster)}" alt="${escapeHtml(title)} 포스터">` : '<span>AW</span>'}<b>${escapeHtml(title)}</b><small>전체 ${safeEpisode}화까지 공개</small></button>`; };
  openDrawer('FEATURE 08 · SPOILER SAFE', '인물 사전', `<section class="dictionary-library"><div class="dictionary-library-head"><div><small>현재 대화 중인 작품</small><h3>저장한 회차까지만 인물을 공개해요.</h3></div></div>${current ? `<div class="dictionary-current">${dictionaryCard(current, true)}</div>` : '<p>저장된 시청 기록이 없어요.</p>'}${others.length ? `<div class="dictionary-saved-divider"><span>다른 저장 작품</span></div><div class="dictionary-record-strip dictionary-record-grid">${others.map(record => dictionaryCard(record)).join('')}</div>` : ''}<div class="dictionary-more-head"><div><small>MORE CHARACTERS</small><h3>더 많은 작품의 인물 사전</h3></div><form id="dictionary-catalog-search"><input id="dictionary-catalog-query" type="search" placeholder="작품명 검색"><button>검색</button></form></div><div class="dictionary-catalog-grid" id="dictionary-catalog-grid"></div>${hunterPrototypeTeaser()}</section>`);
  const content = $('#drawer-content');
  content.addEventListener('click', event => { const card = event.target.closest('[data-dictionary-series]'); if (!card) return; showSeriesDictionary(card.dataset.dictionarySeries, card.dataset.title, card.dataset.poster, card.dataset.seen ? Number(card.dataset.seen) : null); });
  $('#dictionary-catalog-search').addEventListener('submit', event => { event.preventDefault(); loadDictionaryCatalog($('#dictionary-catalog-query').value.trim()); });
  $('#dictionary-catalog-query').addEventListener('input', event => { if (!event.target.value.trim()) loadDictionaryCatalog(); });
  $('[data-open-hunter-prototype]')?.addEventListener('click', openHunterDictionary);
  loadDictionaryCatalog();
}

function openRecordActions(record) {
  if (!record) return;
  activeSeriesId = record.series_id;
  activeSeriesTitle = record.title || record.name || '선택한 작품';
  const localTitle = onboardingTitles[record.series_id];
  const imageUrl = record.poster_url || (localTitle ? onboardingImage(localTitle) : '');
  const seenEp = record.status === 'planned' ? null : Number(recordAbsoluteEpisode(record));
  openDrawer('MY WATCH HISTORY', activeSeriesTitle, `<div class="record-quick-head">${imageUrl ? `<img src="${escapeHtml(imageUrl)}" alt="${escapeHtml(activeSeriesTitle)} 포스터">` : ''}<div><small>${record.status === 'completed' ? '✓ 시청 완료' : record.status === 'planned' ? '보고 싶어요' : '시청 중'}</small><h3>${escapeHtml(activeSeriesTitle)}</h3><p>${seenEp == null ? '아직 시청 전' : `전체 ${seenEp}화까지 기록`}</p></div></div><div class="record-quick-actions">${seenEp != null ? '<button type="button" data-record-quick="recap"><b>3분 복습</b><span>저장한 회차까지만 안전하게</span></button>' : ''}<button type="button" data-record-quick="providers"><b>시청처 보기</b><span>지금 볼 수 있는 OTT 확인</span></button><button type="button" data-record-quick="edit"><b>기록 수정</b><span>상태·회차·평점 변경</span></button></div>`);
  $('[data-record-quick="recap"]')?.addEventListener('click', () => openRecap());
  $('[data-record-quick="providers"]')?.addEventListener('click', () => openProviders());
  $('[data-record-quick="edit"]')?.addEventListener('click', () => openRecord());
}

async function openRecord() {
  const local = savedWatchRecords.find(record => record.series_id === activeSeriesId) || {};
  openDrawer('FEATURE 13', '시청 기록 수정', '<div class="drawer-card"><p>현재 작품의 기록을 불러오고 있어요…</p></div>');
  try {
    const [series, stored] = await Promise.all([api(`/api/series/${encodeURIComponent(activeSeriesId)}`), api(`/api/records/${encodeURIComponent(activeSeriesId)}`).catch(() => null)]);
    const seen = Number(stored?.seen_ep ?? recordAbsoluteEpisode(local) ?? 0);
    const totalEpisodes = Number(series.total_episodes || 0);
    const status = local.status || (totalEpisodes > 0 && seen >= totalEpisodes ? 'completed' : seen > 0 ? 'watching' : 'planned');
    $('#drawer-content').innerHTML = `<form class="record-form" id="record-form"><div class="record-edit-title">${series.poster_url ? `<img src="${escapeHtml(series.poster_url)}" alt="">` : ''}<div><small>현재 선택 작품</small><h3>${escapeHtml(series.name || series.title)}</h3><p>총 ${series.total_episodes || '?'}화</p></div></div><label>상태<select id="record-status"><option value="watching"${status === 'watching' ? ' selected' : ''}>시청 중</option><option value="planned"${status === 'planned' ? ' selected' : ''}>보고 싶어요</option><option value="completed"${status === 'completed' ? ' selected' : ''}>완료</option></select></label><label>마지막으로 본 전체 회차<input id="record-episode" type="number" value="${seen}" min="0" max="${series.total_episodes || 9999}"></label><label>평점 (선택)<input id="record-rating" type="number" value="${stored?.rating ?? local.rating ?? ''}" min="0.5" max="5" step="0.5" placeholder="0.5–5"></label><button>이 작품 기록 저장</button></form>`;
    const syncStatus = () => { const chosen = $('#record-status').value; $('#record-episode').disabled = chosen !== 'watching'; if (chosen === 'completed') $('#record-episode').value = totalEpisodes || seen; if (chosen === 'planned') $('#record-episode').value = 0; };
    $('#record-status').addEventListener('change', syncStatus); syncStatus();
    $('#record-form').addEventListener('submit', async event => {
      event.preventDefault(); const chosen = $('#record-status').value; const ratingValue = $('#record-rating').value;
      const seenEp = chosen === 'completed' ? (totalEpisodes || Number($('#record-episode').value)) : chosen === 'planned' ? 0 : Number($('#record-episode').value);
      try {
        const saved = await api(`/api/records/${encodeURIComponent(activeSeriesId)}`, { method:'PUT', body:JSON.stringify({ seen_ep:seenEp, rating:ratingValue ? Number(ratingValue) : null }) });
        const localSaved = { ...local, ...saved, status:chosen, title:saved.name || series.name, poster_url:saved.poster_url || series.poster_url, season_name:'전체 회차', seen_ep:seenEp };
        saveLocalRecord(localSaved); renderRailRecords(); closeDrawer(); showToast(`${localSaved.title} 기록을 수정했어요.`);
      } catch (error) { showToast(error.message); }
    });
  } catch (error) { $('#drawer-content').innerHTML = `<div class="drawer-card"><h3>기록을 불러오지 못했어요.</h3><p>${escapeHtml(error.message)}</p></div>`; }
}
function openSimilar() { openDrawer('확장 프로토타입 · FEATURE 02', '“진격의 거인 같은 거”', `<div class="drawer-card"><h3>강철의 연금술사</h3><p>거대한 세계의 비밀, 군과 권력의 음모, 뒤집히는 진실이 가까워요.</p></div><div class="drawer-card"><h3>86 -에이티식스-</h3><p>전쟁 속에서 감춰진 사회 구조와 인물들의 선택을 따라가요.</p></div><div class="drawer-card"><h3>메이드 인 어비스</h3><p>미지의 세계를 탐험할수록 새로운 진실이 드러나는 작품이에요.</p></div>`); }
function openWatchOrder() { openDrawer('확장 프로토타입 · FEATURE 03', '나의 히어로 아카데미아 시청 순서', `<div class="character-scene finished-scene light-scene"><img src="assets/light-card-user.png" alt="시청 순서를 계획하는 라이토"></div><div class="order-flow"><article class="order-step"><b>1</b><strong>TV 애니 1기</strong><span>먼저 보기 · 필수</span><em>13화</em></article><i>→</i><article class="order-step"><b>2</b><strong>TV 애니 2기</strong><span>이어서 보기 · 필수</span><em>25화</em></article><i>→</i><article class="order-step optional"><b>3</b><strong>극장판<br>두 명의 히어로</strong><span>2기 이후 추천</span><em>영화</em></article><i>→</i><article class="order-step current"><b>4</b><strong>TV 애니 3기</strong><span>현재 시청 중</span><em>EP11</em></article></div>`); }
function openHookGuide() { openDrawer('확장 프로토타입 · FEATURE 04', '몇 화부터 재밌어져요?', `<div class="character-scene finished-scene okabe-scene"><img src="assets/okabe-card-user.png" alt="여기서부터 재미있어진다고 안내하는 오카베 린타로"></div><div class="drawer-card"><h3>슈타인즈 게이트</h3><p><strong>8화까지</strong> 인물과 설정을 차근차근 쌓고, <strong>9화부터</strong> 앞서 등장한 요소들이 맞물리면서 긴장감과 이야기의 속도가 본격적으로 높아져요.</p></div><p class="feature-note"><b>스포일러 없이</b> 구체적인 사건이나 결과는 숨기고, 이야기의 속도와 분위기가 바뀌는 지점만 알려줘요.</p>`); }
function openSeasonAlert() { openDrawer('확장 프로토타입 · FEATURE 10', '새 시즌이 시작됐어요', `<div class="drawer-card"><h3>나의 히어로 아카데미아 · 다음 시즌</h3><p>마지막 기록이 시즌 3 · 11화라서, 바로 새 시즌으로 이동하기 전에 보던 시즌부터 이어보는 것을 추천해요.</p><button class="copy-button" data-alert-recap>직전 내용 3분 복습</button></div>`); $('[data-alert-recap]').addEventListener('click', () => openRecap('직전 내용')); }
function openMangaLink() { openDrawer('확장 프로토타입 · FEATURE 12', '애니 다음은 원작 어디부터?', `<div class="character-scene finished-scene gon-scene"><img src="assets/gon-card-user.png" alt="애니메이션 다음 이야기를 원작으로 보려는 곤"></div><div class="drawer-card manga-link-result"><h3>헌터×헌터 · 2011년판 완주 기준</h3><p>애니메이션 마지막 이후의 이야기는 원작 <strong class="manga-volume">32권</strong>부터 이어서 확인할 수 있어요.</p></div>`); }
function openShareCopy() { const copy = '평범한 능력물 같지만, 주인공이 힘의 의미를 배워가는 과정과 주변 인물의 성장이 정말 좋은 작품이야. 초반 설정만 알고 보면 더 재미있어!'; openDrawer('확장 프로토타입 · FEATURE 14', '스포일러 없는 추천 문구', `<div class="drawer-card"><h3>친구에게 보내기</h3><div class="share-box" id="share-copy">${copy}</div><button class="copy-button" id="copy-share">문구 복사</button></div><div class="drawer-card"><p>저장된 시청 회차 이후의 인물·사건은 추천 문구 생성 전에 제외하는 구조를 가정했어요.</p></div>`); $('#copy-share').addEventListener('click', async () => { try { await navigator.clipboard.writeText(copy); showToast('추천 문구를 복사했어요.'); } catch { showToast('문구를 선택해서 복사해주세요.'); } }); }
function showToast(text) { toast.textContent = text; toast.classList.add('show'); clearTimeout(showToast.timer); showToast.timer = setTimeout(() => toast.classList.remove('show'), 2300); }

$$('[data-view]').forEach(button => button.addEventListener('click', () => {
  const view = button.dataset.view;
  playTransitionSfx('ゴゴゴゴ');
  $$('.view').forEach(v => v.classList.toggle('active', v.id === `${view}-view`));
  $$('.topbar nav button').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  if (view === 'discover') loadPersonalRecommendations();
  scrollPageToTop();
  requestAnimationFrame(scrollPageToTop);
}));
$$('[data-action]').forEach(button => button.addEventListener('click', () => { const action = button.dataset.action; const needsRecord = ['recap','watch-order','hook-guide','manga-link','season-alert','edit-record']; if (!hasRecord && needsRecord.includes(action)) { showToast('먼저 작품과 시청 지점을 기록해 주세요.'); return; } if (action === 'recap') openRecap(); else if (action === 'providers') openProviders(); else if (action === 'dictionary') openDictionary(); else if (action === 'edit-record') openRecord(); else if (action === 'similar') openSimilar(); else if (action === 'watch-order') openWatchOrder(); else if (action === 'hook-guide') openHookGuide(); else if (action === 'season-alert') openSeasonAlert(); else if (action === 'manga-link') openMangaLink(); else if (action === 'share-copy') openShareCopy(); else if (action === 'find-episode') { $('[data-view="chat"]').click(); resetChat(); } else if (action === 'interview') startTasteInterview(); }));
$$('[data-close]').forEach(b => b.addEventListener('click', closeDrawer));
$('#new-chat').addEventListener('click', resetChat);
$('#rail-watch-tip').addEventListener('click', event => {
  const button = event.target.closest('[data-tip-direction]');
  if (!button) return;
  clearInterval(railTipTimer);
  advanceRailTip(button.dataset.tipDirection === 'prev' ? -1 : 1);
  railTipTimer = setInterval(() => advanceRailTip(1), 5500);
});
composer.addEventListener('submit', e => { e.preventDefault(); send(question.value); });
function resizeComposer() {
  question.style.height = 'auto';
  question.style.height = `${Math.min(question.scrollHeight, 180)}px`;
}
question.addEventListener('input', resizeComposer);
messages.addEventListener('click', event => {
  if (!event.target.closest('[data-open-review]')) return;
  if (latestReview?.answer) showRecapData(latestReview);
  else openRecap();
});
question.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); composer.requestSubmit(); } });

function setRecordState(next) {
  hasRecord = next;
  if (next) localStorage.setItem(RECORD_KEY, '1'); else localStorage.removeItem(RECORD_KEY);
  $('#empty-context').hidden = next;
  $('#record-context').hidden = !next;
  $('#empty-library').hidden = next;
  $('#library-content').hidden = !next;
  $('#record-greeting').hidden = !next;
  $$('[data-requires-record]:not([data-context-seen])').forEach(element => { element.hidden = !next; });
  $('#chat-kicker').textContent = 'ANIWHERE AGENT';
  $('#chat-title').textContent = '애니에 관한 무엇이든 물어보세요!';
}

$$('[data-clear-record]').forEach(button => button.addEventListener('click', () => { setRecordState(false); resetChat('episode'); showToast('작품 선택을 해제했어요.'); }));
$$('[data-onboarding-next]').forEach(button => button.addEventListener('click', () => showOnboardingStep(button.dataset.onboardingNext)));
$$('[data-onboarding-back]').forEach(button => button.addEventListener('click', () => showOnboardingStep(button.dataset.onboardingBack)));
$$('[data-onboarding-l]').forEach(button => button.addEventListener('click', startOnboardingTasteInterview));
$$('[data-onboarding-skip]').forEach(button => button.addEventListener('click', closeOnboardingWithoutChanges));
$('#add-watch-record').addEventListener('click', openOnboardingForRecords);
$('#library-grid').addEventListener('click', event => {
  const button = event.target.closest('[data-record-edit]');
  const action = event.target.closest('[data-record-action]');
  const poster = event.target.closest('.record-poster-shell');
  const card = event.target.closest('[data-record-series]');
  const seriesId = button?.dataset.recordEdit || card?.dataset.recordSeries;
  if (!seriesId) return;
  const record = savedWatchRecords.find(item => item.series_id === seriesId);
  if (!record) return;
  activeSeriesId = record.series_id;
  activeSeriesTitle = record.title || record.name || '선택한 작품';
  if (button || action?.dataset.recordAction === 'edit') openRecord();
  else if (action?.dataset.recordAction === 'recap') openRecap();
  else if (action?.dataset.recordAction === 'providers') openProviders();
  else if (poster) {
    $$('.watch-card.actions-open').forEach(item => { if (item !== card) item.classList.remove('actions-open'); });
    card.classList.toggle('actions-open');
  }
});
$('#rail-posters').addEventListener('click', event => {
  const toggle = event.target.closest('[data-rail-toggle]');
  if (toggle) { railRecordsExpanded = true; renderRailRecords(); return; }
  const button = event.target.closest('[data-rail-series]');
  if (!button) return;
  const record = savedWatchRecords.find(item => item.series_id === button.dataset.railSeries);
  if (record) { activeSeriesId = record.series_id; openRecord(); }
});
$('#rail-records-more').addEventListener('click', event => {
  if (!event.currentTarget.dataset.railToggle) return;
  event.preventDefault(); event.stopPropagation();
  railRecordsExpanded = false;
  renderRailRecords();
});
$('#onboarding-search').addEventListener('submit', async event => {
  event.preventDefault();
  const queryText = $('#onboarding-search-input').value.trim();
  if (!queryText) return;
  $('#onboarding-titles').innerHTML = '<p class="catalog-loading">작품을 검색하고 있어요…</p>';
  try {
    const items = await api(`/api/series?q=${encodeURIComponent(queryText)}&limit=200`);
    renderOnboardingCatalog(items);
    $('#onboarding-search-reset').hidden = false;
  } catch (error) {
    $('#onboarding-titles').innerHTML = `<p class="catalog-loading">검색하지 못했어요. ${escapeHtml(error.message)}</p>`;
  }
});
$('#onboarding-search-reset').addEventListener('click', () => {
  $('#onboarding-search-input').value = '';
  $('#onboarding-search-reset').hidden = true;
  loadOnboardingCatalog();
});
$('#onboarding-search-input').addEventListener('input', event => {
  if (event.target.value.trim()) return;
  $('#onboarding-search-reset').hidden = true;
  renderOnboardingCatalog(onboardingCatalogCache);
});
$('#onboarding-titles').addEventListener('click', event => {
  const selectButton = event.target.closest('.onboarding-title-select');
  if (!selectButton) return;
  const card = selectButton.closest('[data-onboarding-title]');
  const id = card.dataset.onboardingTitle;
  if (onboardingSelection.get(id)?.status) {
    onboardingSelection.delete(id);
    const editor = $('.onboarding-card-editor', card);
    editor.hidden = true;
    updateOnboardingSelection();
    showToast(`${onboardingTitles[id].title} 선택을 해제했어요.`);
    return;
  }
  openOnboardingEditor(id);
});
$('#onboarding-to-details').addEventListener('click', async () => {
  const records = [...onboardingSelection.values()].filter(record => record.status).map(record => ({ ...record, seen_ep: record.status === 'planned' ? 0 : record.seen_ep }));
  const button = $('#onboarding-to-details');
  button.disabled = true;
  button.textContent = '기록 저장 중…';
  try {
    const saved = await persistOnboardingRecords(records);
    finishOnboarding(saved);
    $('[data-view="chat"]').click();
    resetChat('episode');
    showToast(`${saved.length}개 작품의 스포일러 기준을 저장했어요.`);
  } catch (error) {
    showToast(`기록을 저장하지 못했어요. ${error.message}`);
  } finally {
    button.textContent = '완료하고 시작';
    button.disabled = ![...onboardingSelection.values()].some(record => record.status);
  }
});
cutinReturn.addEventListener('click', closeSpoilerCutin);
document.addEventListener('keydown', event => { if (event.key === 'Escape' && !spoilerCutin.hidden) closeSpoilerCutin(); });
setRecordState(hasRecord);
renderLibrary();
if (!restoreConversation()) resetChat();
else setQuickSuggestions();
initializeOnboarding();
loadOnboardingCatalog();

// 로그인 전에는 공용 데모 DB의 기록을 개인 기록으로 취급하지 않습니다.

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
  onboardingInstallButton.hidden = true;
  installGuide.hidden = true;
}

window.addEventListener('beforeinstallprompt', event => {
  event.preventDefault();
  installPrompt = event;
  installButton.hidden = false;
  if (!sessionStorage.getItem('aniwhere-install-dismissed')) installGuide.hidden = false;
});
window.addEventListener('appinstalled', () => { installButton.hidden = true; onboardingInstallButton.hidden = true; installGuide.hidden = true; showToast('AniWhere 앱을 설치했어요.'); });
installButton.addEventListener('click', requestInstall);
onboardingInstallButton.addEventListener('click', requestInstall);
installGuideAction.addEventListener('click', requestInstall);
installGuideClose.addEventListener('click', hideInstallGuide);

if ('serviceWorker' in navigator) window.addEventListener('load', () => navigator.serviceWorker.register('./service-worker.js').catch(() => {}));
if (isStandalone()) { document.documentElement.classList.add('standalone-app'); onboardingInstallButton.hidden = true; }
