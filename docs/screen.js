const byId = (id) => document.getElementById(id);
const cloud = byId('cloud');
const status = byId('status');
const hint = byId('hint');
const bot = byId('bot');
const params = new URLSearchParams(location.search);
const server = params.get('server');
const local = ['localhost', '127.0.0.1'].includes(location.hostname);
const demo = !server && !local && params.get('live') !== '1';
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
  messages.forEach(({id, text}, index) => {
    let card = cards.get(id);
    if (!card) {
      card = document.createElement('article');
      card.className = 'card';
      card.dataset.color = id % 4;
      cards.set(id, card);
    }
    if (card.textContent !== text) card.textContent = text;
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
    render(data.messages);
    for (const reaction of data.reactions) {
      if (lastReaction !== null && reaction.id > lastReaction) animate(reaction.emoji);
    }
    lastReaction = Math.max(lastReaction || 0, ...data.reactions.map(({id}) => id));
    status.textContent = '● Прямой эфир';
    hint.textContent = data.messages.length ? 'Напишите боту в MAX, чтобы ваше сообщение увидел зал.' : 'Ждём первые сообщения от участников.';
    if (typeof data.botUrl === 'string' && /^https:\/\/max\.ru\//.test(data.botUrl)) {
      bot.href = data.botUrl;
      bot.hidden = false;
    }
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
  hint.textContent = 'Пример экрана для мероприятия. Попробуйте реакции внизу.';
  const examples = [
    'Привет из зала!', 'Было очень интересно!', 'Спасибо за встречу ✨',
    'Ждём следующую!', 'Отличная идея!', 'Аплодируем всей командой 👏',
  ];
  render(examples.map((text, index) => ({id: index + 1, text})));
  for (const emoji of ['❤️', '🔥', '👏', '👍']) {
    const button = document.createElement('button');
    button.textContent = emoji;
    button.setAttribute('aria-label', 'Запустить реакцию ' + emoji);
    button.onclick = () => animate(emoji);
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
