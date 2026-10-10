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
let installPrompt = null;
let spoilerObserver = null;
let mode = 'episode';
let persona = 'midoriya';
let busy = false;
let step = 0;
const RECORD_KEY = 'aniwhere-demo-watch-record';
let hasRecord = localStorage.getItem(RECORD_KEY) === '1';

const mock = {
  record: { series_id: 'tmdb:65930', title: '나의 히어로 아카데미아', seen_ep: 49, season: 3, episode: 11, rating: null },
  providers: [{ name: '시즌 3', providers: ['Laftel', 'Netflix'], checked_at: '2026-10-05' }],
  characters: [
    ['미도리야 이즈쿠', '올마이트에게 힘을 물려받은 학생. 위험한 순간 먼저 몸이 움직여요.'],
    ['올마이트', '평화의 상징이라 불리는 히어로이자 미도리야의 스승이에요.'],
    ['바쿠고 카츠키', '폭발 능력을 가진 미도리야의 소꿉친구이자 라이벌이에요.']
  ]
};

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

function setSuggestions(labels = []) {
  suggestions.replaceChildren();
  labels.forEach(label => {
    const button = document.createElement('button');
    button.type = 'button'; button.textContent = label;
    button.addEventListener('click', () => send(label));
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
  mode = nextMode; persona = 'midoriya'; step = 0; busy = false; messages.replaceChildren(); setSuggestions();
  $$('.mode-chips button').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
  const intros = {
    episode: [hasRecord ? '저장된 작품에서 어디까지 보셨는지 함께 찾아보겠습니다! 마지막으로 기억나는 장면을 말해주세요!' : '어떤 작품인지 몰라도 괜찮습니다! 기억나는 장면부터 하나씩 찾아볼게요!', ['올마이트가 마지막에 손가락을 가리켰어', '학교 축제 전까지 봤어']],
    title: ['제목이 기억나지 않아도 괜찮습니다! 인물의 생김새나 능력, 장면을 말해주세요. 제가 열심히 찾아보겠습니다!', ['키 작은 아저씨가 칼 들고 날아다녀', '노란 머리에 번개를 쓰는 겁 많은 아이']],
    recap: hasRecord ? ['저장된 기록은 시즌 3 · 11화예요. 어떤 방식으로 복습할까요?', ['전체 이야기', '인물 관계', '마지막 화 상황']] : ['스포일러 없이 복습하려면 어디까지 봤는지 먼저 알아야 해요. 기억나는 마지막 장면을 말해주세요.', ['올마이트가 손가락을 가리켰어', '샘플 기록 불러오기']],
    providers: ['어떤 작품의 시청처를 찾을까요? 현재 기록된 작품을 바로 확인할 수도 있어요.', ['나의 히어로 아카데미아', '진격의 거인', '귀멸의 칼날']]
  };
  addMessage('agent', intros[mode][0]); setSuggestions(intros[mode][1]);
}

function send(value) {
  const text = value.trim(); if (!text || busy) return;
  if (text === '샘플 기록 불러오기') { setRecordState(true); resetChat('recap'); showToast('나의 히어로 아카데미아 샘플 기록을 불러왔어요.'); return; }
  if (text === '3분 복습') { if (hasRecord) openRecap('직전 내용'); else showToast('복습할 시청 지점을 먼저 찾아주세요.'); return; }
  if (text === '시청처 보기') { openProviders(); return; }
  addMessage('user', text); question.value = '';
  if (mode === 'episode') {
    if (step === 0) { step = 1; reply('시즌 3 · 11화일 가능성이 가장 높아요. 여기까지 본 것으로 기록할까요?', ['여기까지 봤어요', '조금 더 확인할래요'], '<div class="result-card"><small>회차 후보 · 높은 일치</small><h3>시즌 3 · 11화</h3><p>올마이트와 올 포 원의 결전 후 손가락을 가리키는 장면</p></div>'); return; }
    if (/여기까지|기록|봤어요/.test(text)) { step = 2; setRecordState(true); reply('시즌 3 · 11화까지 본 것으로 저장했어요. 이후 내용은 검색 전에 제외할게요.', ['3분 복습', '시청처 보기'], '', ['시청 기록 저장 중…', '스포일러 기준을 49화로 설정 중…']); return; }
    reply('비슷한 전투 장면이 있어요. 그 장면에서 올마이트의 모습이 평소와 달랐나요?', ['힘이 빠진 모습이었어요', '잘 기억나지 않아요']); return;
  }
  if (mode === 'title') { const answer = persona === 'l' ? '분석이 끝났습니다. 가장 가능성이 높은 작품은 「진격의 거인」, 해당 인물은 리바이입니다. 현재 단서 기준 제 추리가 맞을 확률은 높습니다.' : '가장 가까운 작품은 「진격의 거인」입니다! 말씀하신 인물은 리바일 가능성이 높아요!'; reply(answer, ['이 작품이 맞아요', '다른 후보도 볼래요'], '<div class="result-card"><small>작품 후보 1</small><h3>진격의 거인</h3><p>리바이 · 입체기동장치 · 쌍날 검</p></div>', ['인물·외형 단서 분석 중…', '작품 후보를 비교 중…']); return; }
  if (mode === 'recap') { openRecap(text); return; }
  if (mode === 'providers') { openProviders(); return; }
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
function closeDrawer() { drawer.classList.remove('open'); drawer.setAttribute('aria-hidden','true'); }
function openRecap(selected = '전체 이야기') {
  openDrawer('FEATURE 09 · EP49까지', `스포일러 없는 ${selected}`, `<div class="drawer-card"><h3>처음의 약속</h3><p>무개성이던 미도리야는 위험에 뛰어드는 용기를 인정받아 올마이트의 힘을 이어받았어요.</p></div><div class="drawer-card"><h3>유에이에서의 성장</h3><p>친구들과 훈련하고 위기를 겪으며 힘을 다루는 방법과 함께 싸우는 법을 배웠어요.</p></div><div class="drawer-card"><h3>마지막으로 본 상황</h3><p>올마이트가 올 포 원과의 결전을 마치고 다음 세대에게 메시지를 남겼어요.</p></div><div class="drawer-card safe"><h3>⌾ 보호 범위</h3><p>전체 49화까지만 사용했어요. 이 아래는 실제 내용을 받지 않은 보호 구간입니다.</p></div><div class="spoiler-gate" data-spoiler-gate><span>49화</span><i></i><b>TIME STOP</b><i></i><span>50화</span></div><section class="spoiler-protected-card" aria-label="미시청 내용 보호 구간"><h3>⚠️ 스포일러 보호 중 ⚠️</h3><img src="assets/eren-spoiler-user.png" alt="스포일러를 구축해주마고 말하는 에렌 예거"></section>`);
  watchSpoilerGate();
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
function openProviders() { openDrawer('FEATURE 07', '시청처 안내', `<div class="drawer-card"><h3>나의 히어로 아카데미아 · 시즌 3</h3><div class="providers"><span>Laftel</span><span>Netflix</span></div><p>국내 제공처 기준이며 실제 편성은 서비스에서 다시 확인해주세요.</p><small>정보 제공: JustWatch · 확인일 2026-10-05</small></div>`); }
function openDictionary() { openDrawer('PROTOTYPE · FEATURE 08', '49화까지의 인물·용어', mock.characters.map(([n,d]) => `<div class="drawer-card"><h3>${n}</h3><p>${d}</p></div>`).join('') + '<div class="drawer-card"><h3>원 포 올</h3><p>힘을 축적해 다음 계승자에게 전달하는 특별한 개성이에요.</p></div>'); }
function openRecord() { openDrawer('FEATURE 13', '시청 기록 수정', `<form class="record-form" id="record-form"><label>상태<select><option>시청 중</option><option>보고 싶어요</option><option>완료</option></select></label><label>시즌<input type="number" value="3" min="1"></label><label>회차<input type="number" value="11" min="1"></label><label>평점 (선택)<input type="number" min="0" max="5" step="0.5" placeholder="0–5"></label><button>기록 저장</button></form>`); $('#record-form').addEventListener('submit', e => { e.preventDefault(); setRecordState(true); closeDrawer(); showToast('시즌 3 · 11화 기록을 저장했어요. (프로토타입)'); }); }
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
$$('[data-action]').forEach(button => button.addEventListener('click', () => { const action = button.dataset.action; const needsRecord = ['recap','dictionary','watch-order','hook-guide','manga-link','season-alert','edit-record']; if (!hasRecord && needsRecord.includes(action)) { showToast('먼저 작품을 찾거나 샘플 시청 기록을 불러와주세요.'); return; } if (action === 'recap') openRecap(); else if (action === 'providers') openProviders(); else if (action === 'dictionary') openDictionary(); else if (action === 'edit-record') openRecord(); else if (action === 'similar') openSimilar(); else if (action === 'watch-order') openWatchOrder(); else if (action === 'hook-guide') openHookGuide(); else if (action === 'season-alert') openSeasonAlert(); else if (action === 'manga-link') openMangaLink(); else if (action === 'share-copy') openShareCopy(); else if (action === 'find-episode') { $('[data-view="chat"]').click(); resetChat('episode'); } else if (action === 'interview') { $('[data-view="chat"]').click(); resetChat('title'); persona = 'l'; messages.replaceChildren(); setSuggestions(); $('#chat-kicker').textContent = 'L · TASTE DETECTIVE'; $('#chat-title').innerHTML = '당신의 취향을<br>추리하겠습니다.'; addMessage('agent','저는 L입니다. 인류 최고의 두뇌로 당신에게 최고의 애니를 추리하겠습니다. 최근 몰입해서 본 작품 하나를 말씀해주시죠.', '<div class="result-card l-case"><img class="l-chat-panel" src="assets/l-detective-user.png" alt="취향을 추리하는 L"><small>CASE 001 · TASTE PROFILE</small><h3>추리를 시작합니다.</h3><p>분위기 · 전개 속도 · 인물 관계를 분석합니다.</p></div>'); setSuggestions(['진격의 거인 같은 반전물', '성장하는 주인공']); } }));
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
  $('#chat-kicker').textContent = next ? 'MIDORIYA GUIDE · WELCOME BACK' : 'MIDORIYA GUIDE · FIRST VISIT';
  $('#chat-title').innerHTML = next ? '12일 만이네요.<br>어디까지 기억나요?' : '오늘은 어떤 애니<br>이야기를 해볼까요?';
}

$$('[data-load-sample]').forEach(button => button.addEventListener('click', () => { setRecordState(true); $('[data-view="chat"]').click(); resetChat('episode'); showToast('나의 히어로 아카데미아 샘플 기록을 불러왔어요.'); }));
$$('[data-clear-record]').forEach(button => button.addEventListener('click', () => { setRecordState(false); resetChat('episode'); showToast('작품 선택을 해제했어요.'); }));
cutinReturn.addEventListener('click', closeSpoilerCutin);
document.addEventListener('keydown', event => { if (event.key === 'Escape' && !spoilerCutin.hidden) closeSpoilerCutin(); });
setRecordState(hasRecord);
resetChat('episode');

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
