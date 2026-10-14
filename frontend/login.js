// 닉네임 로그인. 닉네임이 없으면 로그인 화면만 보여 주고, 정해지면 app.js를 불러옵니다.
// app.js는 window.ANIWHERE_USER로 저장 키를 나누고 API 요청 헤더(X-AniWhere-User)에 닉네임을 싣습니다.
// 비밀번호는 없습니다: 같은 닉네임이면 어느 기기에서든 같은 기록입니다 (발표 QR 시연용).
const NICKNAME_KEY = 'aniwhere-nickname';
const NICKNAME_RE = /^[0-9A-Za-z가-힣_-]{2,20}$/;   // 서버 aniwhere/api/main.py NICKNAME_RE와 같게

function savedNickname() {
  try { return localStorage.getItem(NICKNAME_KEY); } catch { return null; }
}

function startApp(nickname) {
  window.ANIWHERE_USER = nickname;
  const script = document.createElement('script');
  script.src = 'app.js';
  document.body.appendChild(script);
}

function showLogin() {
  const login = document.getElementById('login');
  const input = document.getElementById('login-nickname');
  const error = document.getElementById('login-error');
  login.hidden = false;
  document.body.classList.add('onboarding-open');
  input.focus();
  document.getElementById('login-form').addEventListener('submit', event => {
    event.preventDefault();
    const nickname = input.value.trim();
    if (!NICKNAME_RE.test(nickname)) {
      error.textContent = '닉네임은 한글·영문·숫자·_·- 2~20자로 정해 주세요. (띄어쓰기 불가)';
      error.hidden = false;
      return;
    }
    try { localStorage.setItem(NICKNAME_KEY, nickname); } catch {}
    login.hidden = true;
    document.body.classList.remove('onboarding-open');
    startApp(nickname);
  });
}

const nickname = savedNickname();
if (nickname && NICKNAME_RE.test(nickname)) startApp(nickname);
else showLogin();
