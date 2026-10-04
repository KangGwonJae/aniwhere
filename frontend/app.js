const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
let lastResult = null;

async function api(path) {
  const response = await fetch(path);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '요청을 처리하지 못했어요.');
  return data;
}

function setView(view) {
  $$('.view').forEach((el) => el.classList.toggle('active', el.id === view));
  $$('.nav-link').forEach((el) => el.classList.toggle('active', el.dataset.view === view));
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function toast(message) {
  const el = $('#toast'); el.textContent = message; el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2400);
}

function cardTemplate(anime) {
  return `<article class="anime-card" style="--accent:${anime.accent}" data-query="${anime.title}에서 기억나는 작품 내용을 찾아줘">
    <div class="art" ${anime.poster_url ? `style="background-image:linear-gradient(to top,rgba(48,20,12,.78),rgba(48,20,12,.02)),url('${anime.poster_url}')"` : ''}></div><span class="initial">${anime.initial}</span>
    <small>${anime.title_en.toUpperCase()}</small><h3>${anime.title}</h3><p>${anime.summary.slice(0, 50)}…</p>
    <div class="tags">${anime.genres.slice(0, 3).map((tag) => `<span>${tag}</span>`).join('')}</div>
  </article>`;
}

async function initialize() {
  try {
    const [health, catalog] = await Promise.all([api('/api/health'), api('/api/catalog')]);
    $('#catalog').innerHTML = catalog.map(cardTemplate).join('');
    $('#catalog').classList.remove('skeletons');
  } catch (error) { $('#chunk-count').textContent = 'OFFLINE'; toast(error.message); }
}

function renderResult(data) {
  lastResult = data;
  const top = data.top_candidate;
  if (!top) { toast(data.answer); return; }
  $('#result-query').textContent = data.query;
  const headings = {
    anime: ['검색 결과', '기억 속 단서로 찾은<br><em>가장 유력한 작품이에요</em>'],
    episode: ['회차 찾기', data.episode ? '마지막으로 본 지점은<br><em>이 회차로 보여요</em>' : '작품은 찾았지만<br><em>회차 단서가 더 필요해요</em>'],
    recap: ['안전한 복습', '선택한 시점까지만<br><em>안전하게 복습해요</em>'],
    streaming: ['시청 정보', '이 작품을 볼 수 있는<br><em>서비스를 확인했어요</em>'],
  };
  const [label, heading] = headings[data.intent] || headings.anime;
  $('#result-label').textContent = label;
  $('#result-title').innerHTML = heading;
  const episode = data.episode ? `<div class="episode-badge"><b>예상 시청 지점</b> · 시즌 ${data.episode.season} ${data.episode.episode}화 〈${data.episode.title}〉</div>` : data.intent === 'episode' ? `<div class="episode-badge unresolved"><b>회차 판단 보류</b> · 장면 단서가 더 필요합니다</div>` : '';
  const character = top.character_name ? `<div class="character-match">추정 캐릭터 <b>${top.character_name}</b></div>` : '';
  const posterStyle = top.poster_url ? `--accent:${top.accent};background-image:linear-gradient(to top,rgba(35,17,12,.68),transparent),url('${top.poster_url}')` : `--accent:${top.accent}`;
  $('#primary-result').innerHTML = `<div class="poster" style="${posterStyle}"><span>${top.initial}</span><small>${top.title_en.toUpperCase()}</small></div>
    <div class="match-copy"><div class="confidence"><i></i> 가장 유력한 결과</div>
    <h2>${top.title}</h2><div class="english">${top.title_en}</div>${character}${episode}<p class="answer">${data.answer}</p>
    <div class="actions">${data.episode ? '<button class="primary" data-action="recap">이 회차까지 복습</button>' : data.intent !== 'episode' ? '<button class="primary" data-action="find-episode">회차 찾고 복습하기</button>' : ''}<button data-action="streaming">어디서 볼 수 있나요?</button></div></div>`;
  const alternatives = data.candidates.slice(1).filter(item => item.score >= .25);
  $('#candidates').innerHTML = alternatives.length ? `<p class="alternative-label">혹시 이 작품을 찾으셨나요?</p>${alternatives.map((item) => `<article class="candidate"><div><h4>${item.title}</h4><p>${item.character_name || item.genres.slice(0, 2).join(' · ')}</p></div></article>`).join('')}` : '';
  const follow = $('#followup');
  follow.classList.toggle('hidden', !data.clarifying_question);
  follow.innerHTML = data.clarifying_question ? `<div><small>AGENT'S FOLLOW-UP</small><p>${data.clarifying_question}</p></div><button data-action="answer-followup">답변 추가하기</button>` : '';
  setView('result');
}

async function search(query) {
  const form = $('#search-form'); form.classList.add('loading');
  try { renderResult(await api(`/api/search?q=${encodeURIComponent(query)}`)); }
  catch (error) { toast(error.message); }
  finally { form.classList.remove('loading'); }
}

async function showRecap() {
  const id = lastResult.top_candidate.anime_id;
  if (!lastResult.episode) {
    startEpisodeSearch();
    return;
  }
  const until = lastResult.episode.global_episode;
  const data = await api(`/api/recap?anime_id=${id}&until=${until}`);
  $('#dialog-label').textContent = `${data.until_episode}화까지`;
  $('#dialog-title').textContent = `${data.anime.title} 복습 노트`;
  $('#dialog-description').textContent = `확인된 시청 지점까지만 정리했어요. 이후 내용은 검색 단계에서 제외했습니다.`;
  $('#evidence-list').innerHTML = `<div class="safety-banner">🛡 확인한 회차 이후의 내용은 숨겼어요.</div>
    <section class="recap-section"><h3>지금까지의 이야기</h3><p>${data.summary}</p></section>
    <section class="recap-section"><h3>기억해둘 인물</h3><div class="recap-people">${data.characters.map(c => `<b>${c}</b>`).join('')}</div></section>
    <section class="recap-section"><h3>세계관 한 줄 정리</h3><p>${data.world}</p></section>
    <section class="recap-section"><h3>주요 사건</h3><ol class="recap-events">${data.events.map(e => `<li><b>${e.season}기 ${e.episode}화</b><div><strong>${e.title}</strong><p>${e.text}</p></div></li>`).join('')}</ol></section>
    `;
  $('#evidence-dialog').showModal();
}

function startEpisodeSearch() {
  const title = lastResult?.top_candidate?.title || '';
  setView('home');
  $$('.mode').forEach(m => m.classList.toggle('active', m.dataset.prefix.startsWith('어디까지')));
  $('#query').value = `${title}에서 마지막으로 기억나는 장면은 `;
  $('#query').focus();
  toast('스포일러 없는 복습을 위해 먼저 시청 지점을 찾아주세요.');
}

async function showStreaming() {
  const data = await api(`/api/streaming?anime_id=${lastResult.top_candidate.anime_id}`);
  $('#dialog-label').textContent = '시청 정보';
  $('#dialog-title').textContent = `${data.anime.title} 시청 정보`;
  $('#dialog-description').textContent = '국내 제공처 기준이며 실제 편성은 해당 서비스에서 다시 확인해주세요.';
  $('#evidence-list').innerHTML = `<article class="evidence-item"><div><span>정보 제공: JustWatch</span><b>확인일 ${data.checked_at}</b></div><h3>${data.anime.title}</h3><div class="meta">${data.providers.map(p => `<span>${p}</span>`).join('')}</div><p>${data.note}</p></article>`;
  $('#evidence-dialog').showModal();
}

document.addEventListener('click', async (event) => {
  const viewButton = event.target.closest('[data-view]'); if (viewButton) setView(viewButton.dataset.view);
  const queryButton = event.target.closest('[data-query]'); if (queryButton) { $('#query').value = queryButton.dataset.query; search(queryButton.dataset.query); }
  const mode = event.target.closest('.mode'); if (mode) { $$('.mode').forEach(m => m.classList.remove('active')); mode.classList.add('active'); $('#query').placeholder = mode.dataset.prefix + '기억나는 내용을 적어보세요...'; }
  const action = event.target.closest('[data-action]')?.dataset.action;
  if (action === 'recap') showRecap();
  if (action === 'find-episode') startEpisodeSearch();
  if (action === 'streaming') showStreaming();
  if (action === 'answer-followup') { setView('home'); $('#query').focus(); $('#query').value = `${lastResult.query} / 추가로 기억나는 점: `; }
});

$('#search-form').addEventListener('submit', (event) => { event.preventDefault(); const prefix = $('.mode.active').dataset.prefix; search(prefix + $('#query').value.trim()); });
$('#query').addEventListener('keydown', (event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); $('#search-form').requestSubmit(); } });
$('#close-dialog').addEventListener('click', () => $('#evidence-dialog').close());
initialize();
