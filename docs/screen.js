const byId = (id) => document.getElementById(id);
const cloud = byId('cloud');
const status = byId('status');
const hint = byId('hint');
const bot = byId('bot');
const params = new URLSearchParams(location.search);
const server = params.get('server');
const local = ['localhost', '127.0.0.1'].includes(location.hostname);
const host = params.get('host') === '1';
const demo = !server && !local && params.get('live') !== '1' && !host && location.hostname !== 'golos.it9tech.ru';
const botUrl = 'https://max.ru/se14925046_bot';
let hostKey = '';
let pendingPosition;
let sendingPosition = false;
let scrollTimer;
let appliedScroll = -1;
const bottom = {message_id: null, fraction: 0};

function readPosition() {
  if (cloud.scrollHeight - cloud.clientHeight - cloud.scrollTop < 8) return bottom;
  const top = cloud.getBoundingClientRect().top;
  const card = Array.from(cloud.children).find((element) => element.getBoundingClientRect().bottom > top);
  if (!card) return bottom;
  const bounds = card.getBoundingClientRect();
  return {message_id: Number(card.dataset.id), fraction: Math.max(0, (top - bounds.top) / bounds.height)};
}

function applyPosition(position) {
  const card = position && cards.get(position.message_id);
  if (card) {
    const bounds = card.getBoundingClientRect();
    cloud.scrollTop += bounds.top - cloud.getBoundingClientRect().top + bounds.height * position.fraction;
  } else {
    cloud.scrollTop = cloud.scrollHeight;
  }
  appliedScroll = cloud.scrollTop;
}

async function sendPosition(position) {
  pendingPosition = position;
  if (sendingPosition || !hostKey) return;
  sendingPosition = true;
  try {
    while (pendingPosition) {
      const next = pendingPosition;
      pendingPosition = undefined;
      const response = await fetch('/api/position', {
        method: 'POST',
        headers: {Authorization: 'Bearer ' + hostKey, 'Content-Type': 'application/json'},
        body: JSON.stringify(next),
        signal: AbortSignal.timeout(5000),
      });
      if (!response.ok) throw new Error(response.status === 401 ? 'Проверьте ключ ведущего' : 'Не удалось передать позицию');
      byId('hostStatus').textContent = 'Экран следует за вашей прокруткой';
    }
  } catch (error) {
    byId('hostStatus').textContent = error.message;
  } finally {
    sendingPosition = false;
  }
}

byId('latest').onclick = () => {
  applyPosition(bottom);
  sendPosition(bottom);
};
if (host) {
  byId('hostLogin').hidden = false;
  document.body.classList.add('host');
  byId('hostLogin').onsubmit = (event) => {
    event.preventDefault();
    hostKey = byId('hostKey').value;
    byId('hostKey').value = '';
    sendPosition(readPosition());
  };
  cloud.addEventListener('scroll', () => {
    if (Math.abs(cloud.scrollTop - appliedScroll) < 1) return;
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(() => sendPosition(readPosition()), 120);
  });
} else if (!demo && !server) {
  byId('hostLink').hidden = false;
}

function showBot() {
  bot.href = botUrl;
  bot.hidden = false;
  byId('qr').hidden = false;
}
const cards = new Map();
let lastReaction = null;

function render(messages) {
  const active = new Set(messages.map(({id}) => id));
  for (const [id, element] of cards) {
    if (!active.has(id)) {
      element.remove();
      cards.delete(id);
    }
  }
  messages.forEach(({id, text, author, avatar}, index) => {
    let card = cards.get(id);
    if (!card) {
      card = document.createElement('article');
      card.className = 'card';
      card.dataset.id = id;
      const name = author || 'Участник';
      const face = document.createElement('span');
      face.className = 'message-avatar';
      face.setAttribute('aria-hidden', 'true');
      const initials = name.replace(/^@/, '').split(/\s+/).slice(0, 2).map(word => [...word][0]).join('').toUpperCase();
      face.textContent = initials || 'У';
      if (avatar) {
        const photo = document.createElement('img');
        photo.alt = '';
        photo.referrerPolicy = 'no-referrer';
        photo.addEventListener('error', () => photo.remove(), {once: true});
        photo.src = avatar;
        face.append(photo);
      }
      const bubble = document.createElement('div');
      bubble.className = 'message-bubble';
      const signature = document.createElement('div');
      signature.className = 'message-author';
      signature.textContent = name;
      const content = document.createElement('div');
      content.className = 'message-text';
      content.textContent = text;
      bubble.append(signature, content);
      card.append(face, bubble);
      cards.set(id, card);
    }
    if (cloud.children[index] !== card) cloud.insertBefore(card, cloud.children[index] || null);
  });
}

function animate(emoji) {
  const element = document.createElement('span');
  element.className = 'reaction';
  element.style.left = (8 + Math.random() * 80) + '%';
  element.textContent = emoji;
  byId('reactions').append(element);
  setTimeout(() => element.remove(), 2600);
}

async function refresh(endpoint) {
  try {
    const response = await fetch(endpoint, {cache: 'no-store', signal: AbortSignal.timeout(5000)});
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const data = await response.json();
    const position = host ? readPosition() : data.position;
    render(data.messages);
    applyPosition(position);
    for (const reaction of data.reactions) {
      if (lastReaction !== null && reaction.id > lastReaction) animate(reaction.emoji);
    }
    lastReaction = Math.max(lastReaction || 0, ...data.reactions.map(({id}) => id));
    status.textContent = data.maxConnected ? '● Прямой эфир' : '● Тестовый режим';
    hint.textContent = data.messages.length ? 'Сообщения из чата MAX' : 'Ждём сообщения от участников';
    if (data.maxConnected && data.botUrl === botUrl) showBot();
  } catch {
    status.textContent = '○ Нет связи · переподключаемся';
  }
  setTimeout(() => refresh(endpoint), 900);
}

byId('full').onclick = async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.documentElement.requestFullscreen();
  } catch {
    byId('full').textContent = 'Полный экран недоступен';
  }
};
document.addEventListener('fullscreenchange', () => {
  byId('full').textContent = document.fullscreenElement ? 'Выйти из полного экрана' : 'На весь экран ⛶';
});

if (demo) {
  status.textContent = '● Демо';
  showBot();
  hint.textContent = 'Пример экрана для мероприятия. Попробуйте реакции внизу.';
  const examples = [
    'Привет из зала!', 'Было очень интересно!', 'Спасибо за встречу ✨',
    'Ждём следующую!', 'Отличная идея!', 'Аплодируем всей командой 👏',
  ];
  const authors = ["Анна", "@misha", "Ольга", "@natalia", "Андрей", "Елена"];
  render(examples.map((text, index) => ({id: index + 1, text, author: authors[index]})));
  applyPosition(bottom);
  let lastDemoReaction = 0;
  for (const emoji of ['❤️', '🔥', '👏', '👍']) {
    const button = document.createElement('button');
    button.textContent = emoji;
    button.setAttribute('aria-label', 'Запустить реакцию ' + emoji);
    button.onclick = () => {
      const now = performance.now();
      if (lastDemoReaction && now - lastDemoReaction < 1000) return;
      lastDemoReaction = now;
      animate(emoji);
    };
    byId('controls').append(button);
  }
} else {
  try {
    const endpoint = new URL('/api/screen', server || location.origin);
    if (endpoint.protocol !== 'https:' && !local) throw new Error('HTTPS required');
    refresh(endpoint);
  } catch {
    status.textContent = 'Проверьте HTTPS-адрес сервера';
  }
}
