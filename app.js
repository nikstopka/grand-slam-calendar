// Tennis Calendar - Frontend Logic (v2)
// Данные: data/index.json (каталог турниров), data/tournaments/*.json (сетки матчей),
// data/rankings.json (мировой рейтинг), data/players.json (фотографии игроков).
// Всё обновляется автоматически через GitHub Actions.

const STATE = {
    index: null,
    rankings: null,
    photos: {},
    tournaments: {},      // slug -> загруженные данные турнира
    activeTab: null,      // slug турнира либо 'rankings'
    genderFilter: 'all',
    statusFilter: 'all',
    lastUpdated: '',
    loading: false,
    isDemo: false,        // показываем демонстрационные данные
    year: null,           // выбранный год
    yearsByTab: {},       // slug -> доступные годы
    view: 'list',         // list | bracket
    bracketGender: 'men', // чей сетка показана
    bracketFrom: 'auto',  // с какого раунда показывать
};

const ACTIVE_REFRESH_MS = 5 * 60 * 1000;   // есть live / предстоящие матчи
const DEFAULT_REFRESH_MS = 30 * 60 * 1000; // иначе
const RANKINGS_LIMIT = 100;               // сколько строк показываем в рейтинге

// === УТИЛИТЫ ===

// Экранирование HTML — данные приходят из внешнего API
function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// Country code to emoji flag
function countryFlag(code) {
    if (!code || typeof code !== 'string') return '🏳️';
    const normalized = code.trim().toUpperCase();
    if (!/^[A-Z]{3}$/.test(normalized)) return '🏳️';
    return String.fromCodePoint(
        ...[...normalized].map(ch => 0x1F1E6 - 65 + ch.charCodeAt(0))
    );
}

// Инициалы для заглушки вместо фотографии
function playerInitials(name) {
    const parts = String(name || '')
        .split(/[,\s]+/)
        .map(p => p.trim())
        .filter(Boolean);
    if (!parts.length) return '?';
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[1][0]).toUpperCase();
}

// Фото игрока с заглушкой (инициалы) на случай, если картинки нет
function playerAvatar(player) {
    const photo = STATE.photos[player.id];
    const initials = escapeHtml(playerInitials(player.name));
    const img = photo
        ? `<img src="${escapeHtml(photo)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">`
        : '';
    return `<span class="player-avatar">${img}<span class="avatar-fallback">${initials}</span></span>`;
}

// Format date in Russian (локальное время пользователя)
function formatDateTimeRU(dateStr) {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return '—';
    const days = ['воскресенье', 'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота'];
    const months = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля',
        'августа', 'сентября', 'октября', 'ноября', 'декабря'];
    const day = d.getDate();
    const month = months[d.getMonth()];
    const dayName = days[d.getDay()];
    const hours = String(d.getHours()).padStart(2, '0');
    const mins = String(d.getMinutes()).padStart(2, '0');
    return `${dayName}, ${day} ${month}, ${hours}:${mins}`;
}

// Время по часовому поясу арены
function formatVenueTime(match) {
    if (!match.timezone || !match.start_time) return '';
    try {
        return new Intl.DateTimeFormat('ru-RU', {
            timeZone: match.timezone,
            hour: '2-digit',
            minute: '2-digit',
        }).format(new Date(match.start_time));
    } catch {
        return '';
    }
}

// Calculate time until match
function timeUntilMatch(dateStr) {
    const matchTime = new Date(dateStr);
    if (isNaN(matchTime.getTime())) return null;
    const diff = matchTime - new Date();
    if (diff <= 0) return null;

    const days = Math.floor(diff / (1000 * 60 * 60 * 24));
    const hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
    const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
    return { days, hours, minutes, total: diff };
}

function formatCountdown(countdown) {
    let text = '';
    if (countdown.days > 0) text += `${countdown.days}д `;
    text += `${String(countdown.hours).padStart(2, '0')}:${String(countdown.minutes).padStart(2, '0')}`;
    return text;
}

// Get match status info
function getStatusInfo(status) {
    switch (status) {
        case 'live': return { class: 'live', text: 'LIVE' };
        case 'closed':
        case 'ended': return { class: 'finished', text: 'Завершён' };
        case 'canceled':
        case 'cancelled': return { class: 'canceled', text: 'Отменён' };
        case 'postponed': return { class: 'postponed', text: 'Перенесён' };
        default: return { class: 'upcoming', text: 'Предстоит' };
    }
}

// Текст live-виджета
function liveStatusText(match, periodsCount) {
    const ms = String(match.match_status || '').toLowerCase();
    const setMatch = ms.match(/^set(\d)/);
    if (setMatch) return `Идёт ${setMatch[1]}-й сет`;
    if (ms.includes('break')) return 'Перерыв';
    if (periodsCount > 0) return `Идёт ${periodsCount}-й сет`;
    return 'Матч начался';
}

// Счёт по сетам для одной стороны
function renderSetScores(periods, side, isCurrent) {
    return periods.map((p, i) => {
        const mine = side === 'home' ? p.home : p.away;
        const theirs = side === 'home' ? p.away : p.home;
        const won = mine > theirs;
        const current = isCurrent && i === periods.length - 1;
        const tb = p[`${side}_tb`];
        const tbHtml = tb !== undefined ? `<span class="tb">${escapeHtml(tb)}</span>` : '';
        return `<div class="set-score ${won ? 'won' : 'lost'} ${current ? 'current' : ''}">
                    <span class="set-num">С${escapeHtml(p.number)}</span>
                    <span class="set-points">${escapeHtml(mine)}${tbHtml}</span>
                </div>`;
    }).join('');
}

// === КАРТОЧКА МАТЧА ===

function renderMatchCard(match) {
    const status = match.status || 'not_started';
    const statusInfo = getStatusInfo(status);
    const players = Array.isArray(match.players) ? match.players : [];
    const homePlayer = players.find(p => p.qualifier === 'home') || {};
    const awayPlayer = players.find(p => p.qualifier === 'away') || {};
    const scores = match.scores || {};
    const periods = Array.isArray(scores.periods) ? scores.periods : [];

    const isFinished = status === 'closed' || status === 'ended';
    const isLive = status === 'live';
    const isUpcoming = status === 'not_started';

    const hasWinner = Boolean(match.winner_id);
    const homeWon = isFinished && hasWinner && match.winner_id === homePlayer.id;
    const awayWon = isFinished && hasWinner && match.winner_id === awayPlayer.id;

    const showSets = !isUpcoming && periods.length > 0;

    const homeSets = showSets ? renderSetScores(periods, 'home', isLive) : '';
    const awaySets = showSets ? renderSetScores(periods, 'away', isLive) : '';
    const homeTotal = isFinished && scores.home !== undefined
        ? `<div class="set-score ${homeWon ? 'won' : 'lost'}"><span class="set-num">Итог</span><span class="set-points">${escapeHtml(scores.home)}</span></div>`
        : '';
    const awayTotal = isFinished && scores.away !== undefined
        ? `<div class="set-score ${awayWon ? 'won' : 'lost'}"><span class="set-num">Итог</span><span class="set-points">${escapeHtml(scores.away)}</span></div>`
        : '';

    let activityWidget = '';
    if (isUpcoming) {
        const countdown = timeUntilMatch(match.start_time);
        if (countdown) {
            activityWidget = `
                <div class="countdown">
                    <div class="countdown-label">⏰ До начала матча</div>
                    <div class="countdown-timer" data-match-time="${escapeHtml(match.start_time)}">${formatCountdown(countdown)}</div>
                </div>
            `;
        }
    } else if (isLive) {
        activityWidget = `
            <div class="activity-widget">
                <div class="activity-bar">
                    <span class="activity-icon">🔴</span>
                    <div class="activity-status">
                        <div class="activity-text">Матч в прямом эфире</div>
                        <div class="activity-sub">${escapeHtml(liveStatusText(match, periods.length))}</div>
                    </div>
                </div>
            </div>
        `;
    }

    const localTime = formatDateTimeRU(match.start_time);
    const venueTime = formatVenueTime(match);
    const showVenueTime = venueTime && venueTime !== localTime.slice(-5);
    const timeHtml = `
        <div class="match-info-item">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
            <span>${escapeHtml(localTime)} <span class="tz-hint">(ваше время)</span></span>
            ${showVenueTime ? `<span class="venue-time">по времени арены: ${escapeHtml(venueTime)}</span>` : ''}
        </div>
    `;

    const venueText = match.venue ? escapeHtml(match.venue) : '';
    const cityText = match.city ? escapeHtml(match.city) : '';

    return `
        <div class="match-card ${isLive ? 'live' : ''}">
            <div class="match-header">
                <div class="match-tournament">
                    <span class="gender-badge ${escapeHtml(match.gender || 'men')}">${escapeHtml(match.category || '')}</span>
                    <span class="round-badge">${escapeHtml(match.round_display || match.round || '')}</span>
                </div>
                <div class="status-badge ${statusInfo.class}">
                    <span class="dot"></span>
                    ${statusInfo.text}
                </div>
            </div>

            <div class="players">
                <div class="player ${homeWon ? 'winner' : ''}">
                    <div class="player-info">
                        ${playerAvatar(homePlayer)}
                        <span class="player-flag">${countryFlag(homePlayer.country_code)}</span>
                        <span class="player-name">${escapeHtml(homePlayer.name || 'TBD')}</span>
                        ${homePlayer.seed ? `<span class="player-seed">#${escapeHtml(homePlayer.seed)}</span>` : ''}
                        ${homeWon ? '<span class="winner-indicator">✓</span>' : ''}
                    </div>
                    <div class="score-display">${homeSets}${homeTotal}</div>
                </div>

                <div class="player ${awayWon ? 'winner' : ''}">
                    <div class="player-info">
                        ${playerAvatar(awayPlayer)}
                        <span class="player-flag">${countryFlag(awayPlayer.country_code)}</span>
                        <span class="player-name">${escapeHtml(awayPlayer.name || 'TBD')}</span>
                        ${awayPlayer.seed ? `<span class="player-seed">#${escapeHtml(awayPlayer.seed)}</span>` : ''}
                        ${awayWon ? '<span class="winner-indicator">✓</span>' : ''}
                    </div>
                    <div class="score-display">${awaySets}${awayTotal}</div>
                </div>
            </div>

            ${activityWidget}

            <div class="match-info">
                ${timeHtml}
                ${venueText ? `<div class="match-info-item">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
                    ${venueText}${cityText ? `, ${cityText}` : ''}
                </div>` : ''}
                ${match.best_of ? `<div class="match-info-item">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
                    Лучшая из ${escapeHtml(match.best_of)}
                </div>` : ''}
            </div>
        </div>
    `;
}

// === ФИЛЬТРЫ ===

function matchPassesFilters(match) {
    if (STATE.statusFilter === 'upcoming' && match.status !== 'not_started') return false;
    if (STATE.statusFilter === 'live' && match.status !== 'live') return false;
    if (STATE.statusFilter === 'finished' && !['closed', 'ended'].includes(match.status)) return false;
    if (STATE.genderFilter === 'men' && match.gender !== 'men') return false;
    if (STATE.genderFilter === 'women' && match.gender !== 'women') return false;
    return true;
}

function sortMatches(matches) {
    const statusOrder = { 'not_started': 0, 'live': 1, 'closed': 2, 'ended': 2 };
    return matches.slice().sort((a, b) => {
        const sOrder = (statusOrder[a.status] ?? 3) - (statusOrder[b.status] ?? 3);
        if (sOrder !== 0) return sOrder;
        const diff = new Date(a.start_time) - new Date(b.start_time);
        return sOrder === 2 ? -diff : diff;
    });
}

// === ВЫБОР ГОДА ===

function availableYears(data) {
    return Object.keys(data.years || {}).sort((a, b) => b.localeCompare(a));
}

// Год по умолчанию: текущий календарный, иначе ближайший доступный
function defaultYear(years) {
    if (!years.length) return '';
    const current = String(new Date().getFullYear());
    if (years.includes(current)) return current;
    return years[0];
}

function renderYearSelect(years, selected) {
    const group = document.getElementById('yearFilterGroup');
    const select = document.getElementById('yearSelect');
    if (!group || !select) return;

    if (!years.length) {
        group.style.display = 'none';
        return;
    }
    group.style.display = 'flex';
    select.innerHTML = years
        .map(y => `<option value="${escapeHtml(y)}"${y === selected ? ' selected' : ''}>${escapeHtml(y)}</option>`)
        .join('');
    select.value = selected;
}

// Год, который показываем для активного турнира
function currentYearFor(data) {
    const years = availableYears(data);
    if (STATE.year && years.includes(STATE.year)) return STATE.year;
    return defaultYear(years);
}

// === СЕТКА (СКОБКА) ===

// Раунды от раннего к позднему
const BRACKET_ROUNDS = [
    ['round_of_128', '1/64'],
    ['round_of_64', '1/32'],
    ['round_of_32', '1/16'],
    ['round_of_16', '1/8'],
    ['quarterfinal', '1/4'],
    ['semifinal', '1/2'],
    ['final', 'Финал'],
];

const BRACKET_FROM_OPTIONS = [
    ['auto', 'С 1/8 финала'],
    ['quarterfinal', 'С 1/4 финала'],
    ['round_of_32', 'С 1/16 финала'],
    ['all', 'Все раунды'],
];

// Геометрия сетки (в пикселях)
const BRACKET_GEOM = {
    colW: 228,    // ширина блока матча
    colGap: 46,   // зазор между колонками
    rowH: 25,     // высота строки игрока
    boxPad: 5,    // внутренний отступ блока
    vGap: 12,     // зазор между соседними матчами по вертикали
    topPad: 34,   // место под заголовки раундов
};
BRACKET_GEOM.boxH = BRACKET_GEOM.rowH * 2 + BRACKET_GEOM.boxPad * 2;
BRACKET_GEOM.leafStep = BRACKET_GEOM.boxH + BRACKET_GEOM.vGap;
BRACKET_GEOM.colStep = BRACKET_GEOM.colW + BRACKET_GEOM.colGap;

// Победа в матче: id игрока-победителя
function matchWinnerId(match) {
    return match.winner_id || null;
}

// Строит дерево сетки: раунды + связи «кто в кого играет»
function buildBracketTree(matches) {
    const rounds = new Map();
    for (const match of matches) {
        if (!match.round || !match.id) continue;
        if (!rounds.has(match.round)) rounds.set(match.round, []);
        rounds.get(match.round).push(match);
    }

    const levels = BRACKET_ROUNDS.map(r => r[0]).filter(r => rounds.has(r));
    if (!levels.length) return null;

    // children: матч → какие матчи предыдущего раунда в него вышли.
    // Важно: карта «победитель → матч» строится ОТДЕЛЬНО для каждого перехода
    // между раундами, иначе игрок, выигравший несколько раундов, попадёт
    // в карту от последнего своего матча и связи разорвутся.
    const children = new Map();
    const parent = new Map();
    for (let i = 0; i < levels.length - 1; i++) {
        const prev = rounds.get(levels[i]);
        const next = rounds.get(levels[i + 1]);

        const byWinner = new Map();
        for (const match of prev) {
            const winner = matchWinnerId(match);
            if (winner) byWinner.set(winner, match);
        }

        for (const p of next) {
            const kids = [];
            for (const player of p.players || []) {
                const kid = byWinner.get(player.id);
                if (kid) {
                    kids.push(kid);
                    parent.set(kid.id, p.id);
                }
            }
            children.set(p.id, kids);
        }
    }
    for (const level of levels) {
        for (const match of rounds.get(level)) {
            if (!children.has(match.id)) children.set(match.id, []);
        }
    }

    return { levels, rounds, children, parent };
}

// Определяет, с какого раунда показываем сетку (индекс в levels)
function bracketStartIndex(levels) {
    if (STATE.bracketFrom === 'all') return 0;
    const wanted = STATE.bracketFrom === 'auto' ? 'round_of_16' : STATE.bracketFrom;
    const found = levels.indexOf(wanted);
    if (found >= 0) return found;
    // такого раунда нет (турнир с меньшей сеткой) — берём последние 4 уровня
    return Math.max(0, levels.length - 4);
}

// Раскладывает дерево по вертикали: лист i стоит на позиции i * leafStep,
// а матч центрируется относительно своих «листьев» (потомков).
function layoutBracket(tree, startIdx) {
    const { levels, rounds, children } = tree;
    const G = BRACKET_GEOM;

    // Дети в порядке участников родителя (левый — первый участник)
    const orderedKids = (match) => {
        const kids = children.get(match.id) || [];
        if (kids.length < 2) return kids;
        const players = match.players || [];
        const indexOf = (kid) => {
            const winner = matchWinnerId(kid);
            const idx = players.findIndex(pl => pl.id === winner);
            return idx < 0 ? 99 : idx;
        };
        return kids.slice().sort((a, b) => indexOf(a) - indexOf(b));
    };

    const firstLeaf = new Map();
    const lastLeaf = new Map();
    let cursor = 0;

    // Обход сверху вниз: самый ранний показываемый раунд — это «листья»
    const walk = (match, levelIdx) => {
        if (levelIdx <= startIdx) {
            firstLeaf.set(match.id, cursor);
            lastLeaf.set(match.id, cursor);
            cursor += 1;
            return;
        }
        firstLeaf.set(match.id, cursor);
        for (const kid of orderedKids(match)) walk(kid, levelIdx - 1);
        lastLeaf.set(match.id, Math.max(cursor - 1, firstLeaf.get(match.id)));
    };

    const top = levels[levels.length - 1];
    const topMatches = (rounds.get(top) || []).slice().sort((a, b) =>
        (a.start_time || '').localeCompare(b.start_time || ''));
    for (const match of topMatches) walk(match, levels.length - 1);

    // Позиция блока: верх = центр между крайними листьями
    const positions = new Map();
    let orphan = cursor;   // матчи без связей ставим в конец
    levels.forEach((level, levelIdx) => {
        if (levelIdx < startIdx) return;
        for (const match of rounds.get(level) || []) {
            const f = firstLeaf.get(match.id);
            const l = lastLeaf.get(match.id);
            let top;
            if (f === undefined || l === undefined) {
                top = orphan * G.leafStep;
                orphan += 1;
            } else {
                top = ((f + l) / 2) * G.leafStep;
            }
            positions.set(match.id, { x: levelIdx - startIdx, top });
        }
    });

    return { ...tree, positions, firstLeaf, lastLeaf, leafCount: cursor };
}

// Наборы, выигранные игроком
function playerSets(match, playerId) {
    const periods = (match.scores && match.scores.periods) || [];
    const players = match.players || [];
    const idx = players.findIndex(p => p.id === playerId);
    if (idx < 0) return '';
    const side = idx === 0 ? 'home' : 'away';
    const parts = periods.map(p => `${p[side]}-${side === 'home' ? p.away : p.home}`);
    return parts.join(' ');
}

// Короткое имя игрока: «Sinner, Jannik» → «Sinner J.»
function shortPlayerName(name) {
    const raw = String(name || '').trim();
    if (!raw) return '—';
    if (raw.includes(',')) {
        const [last, first] = raw.split(',', 2);
        return `${last.trim()} ${first.trim().charAt(0)}.`;
    }
    const parts = raw.split(/\s+/);
    if (parts.length === 1) return raw;
    return `${parts[parts.length - 1]} ${parts[0].charAt(0)}.`;
}

function renderBracketPlayer(match, player, isWinner) {
    const G = BRACKET_GEOM;
    const sets = playerSets(match, player.id);
    const seed = player.seed ? `[${escapeHtml(player.seed)}]` : '';
    const full = player.name || '';
    return `
        <div class="bracket-player ${isWinner ? 'winner' : ''}" style="height:${G.rowH}px; line-height:${G.rowH}px;">
            <span class="bp-seed">${seed}</span>
            <span class="bp-name" title="${escapeHtml(full)}">${escapeHtml(shortPlayerName(full))}</span>
            <span class="bp-sets">${escapeHtml(sets)}</span>
        </div>
    `;
}

// Рисует сетку: колонки раундов + SVG-связи
function renderBracket(matches, gender) {
    const raw = buildBracketTree(matches);
    if (!raw) return '<p class="grid-message">Нет данных для сетки</p>';

    const startIdx = bracketStartIndex(raw.levels);
    const tree = layoutBracket(raw, startIdx);
    const { levels, rounds, parent, positions } = tree;
    const G = BRACKET_GEOM;

    const shown = levels.slice(startIdx);
    if (!shown.length) return '<p class="grid-message">Нет данных для сетки</p>';

    // Колонки: заголовок + матчи, отсортированные сверху вниз
    const columns = shown.map((level, colIdx) => {
        const title = BRACKET_ROUNDS.find(r => r[0] === level);
        const items = (rounds.get(level) || [])
            .map(m => ({ match: m, pos: positions.get(m.id) }))
            .filter(x => x.pos)
            .sort((a, b) => a.pos.top - b.pos.top);
        return { level, colIdx, title, items };
    });

    // Общая высота: самое нижнее содержимое + запас под заголовки раундов
    let maxBottom = 0;
    for (const col of columns) {
        for (const item of col.items) {
            maxBottom = Math.max(maxBottom, item.pos.top + G.boxH);
        }
    }
    const totalHeight = maxBottom + G.topPad + 12;
    const totalWidth = columns.length * G.colStep - G.colGap;

    // SVG-связи: от строки победителя к центру родительского блока
    const lines = [];
    for (const [childId, parentId] of parent) {
        const child = positions.get(childId);
        const par = positions.get(parentId);
        if (!child || !par) continue;
        if (child.x === par.x) continue;

        const childMatch = (rounds.get(levels[child.x + startIdx]) || []).find(m => m.id === childId);
        const winner = childMatch ? matchWinnerId(childMatch) : null;
        const players = (childMatch && childMatch.players) || [];
        const winnerIdx = winner ? players.findIndex(p => p.id === winner) : 0;

        // y строки победителя внутри блока
        const rowIndex = winnerIdx === 1 ? 1 : 0;
        const winnerY = child.top + G.boxPad + rowIndex * G.rowH + G.rowH / 2 + G.topPad;

        const x1 = (child.x + 1) * G.colStep - G.colGap;      // правый край блока
        const y1 = winnerY;
        const x2 = par.x * G.colStep;                          // левый край родителя
        const y2 = par.top + G.boxH / 2 + G.topPad;
        const mid = x1 + (x2 - x1) / 2;
        lines.push(`M ${x1} ${y1} H ${mid} V ${y2} H ${x2}`);
    }

    const columnsHtml = columns.map(col => {
        const cells = col.items.map(({ match, pos }) => {
            const players = match.players || [];
            const winner = matchWinnerId(match);
            const home = players[0] || { id: '', name: '' };
            const away = players[1] || { id: '', name: '' };
            const isLive = match.status === 'live';
            const isUpcoming = match.status === 'not_started';
            const statusClass = isLive ? 'live' : isUpcoming ? 'upcoming' : 'finished';
            return `
                <div class="bracket-match ${statusClass}"
                     style="top:${pos.top}px; width:${G.colW}px; height:${G.boxH}px;">
                    ${renderBracketPlayer(match, home, winner === home.id)}
                    ${renderBracketPlayer(match, away, winner === away.id)}
                    ${isLive ? '<span class="bracket-live">LIVE</span>' : ''}
                </div>
            `;
        }).join('');

        return `
            <div class="bracket-column" style="left:${col.colIdx * G.colStep}px; width:${G.colW}px; top:${G.topPad}px;">
                <div class="bracket-round-title">${escapeHtml(col.title ? col.title[1] : col.level)}</div>
                ${cells}
            </div>
        `;
    }).join('');

    return `
        <div class="bracket-toolbar">
            <div class="filter-group" role="group" aria-label="Тур в сетке">
                <button class="filter-btn ${gender === 'men' ? 'active' : ''}" data-bracket-gender="men">ATP</button>
                <button class="filter-btn ${gender === 'women' ? 'active' : ''}" data-bracket-gender="women">WTA</button>
            </div>
            <div class="filter-group" role="group" aria-label="Начало сетки">
                ${BRACKET_FROM_OPTIONS.map(([value, label]) =>
                    `<button class="filter-btn ${STATE.bracketFrom === value ? 'active' : ''}" data-bracket-from="${escapeHtml(value)}">${escapeHtml(label)}</button>`
                ).join('')}
            </div>
        </div>
        <div class="bracket-scroll">
            <div class="bracket" style="width:${totalWidth}px; height:${totalHeight}px;">
                <svg class="bracket-lines" width="${totalWidth}" height="${totalHeight}" viewBox="0 0 ${totalWidth} ${totalHeight}">
                    ${lines.map(d => `<path d="${d}"></path>`).join('')}
                </svg>
                ${columnsHtml}
            </div>
        </div>
    `;
}

function yearStateLabel(matches) {
    if (!matches.length) return '';
    const hasLive = matches.some(m => m.status === 'live');
    const hasUpcoming = matches.some(m => m.status === 'not_started');
    const hasFinished = matches.some(m => ['closed', 'ended'].includes(m.status));
    if (hasLive) return 'идёт';
    if (hasUpcoming && !hasFinished) return 'предстоящий';
    if (hasUpcoming && hasFinished) return 'в процессе';
    return 'завершён';
}

function renderTournamentPanel(data) {
    const years = availableYears(data);

    if (!years.length) {
        return `
            <div class="section-header">
                <h2>${escapeHtml(data.icon)} ${escapeHtml(data.name)} <span class="level-badge">${escapeHtml(data.level_label)}</span></h2>
            </div>
            <p class="grid-message">Расписание пока не опубликовано</p>
        `;
    }

    const year = currentYearFor(data);
    const yearData = data.years[year] || {};
    const genders = Object.keys(yearData).sort();
    const allMatches = genders.flatMap(g => [...yearData[g].main, ...yearData[g].secondary]);
    const label = yearStateLabel(allMatches);

    const mainMatches = sortMatches(genders.flatMap(g => yearData[g].main).filter(matchPassesFilters));
    const secondaryMatches = sortMatches(genders.flatMap(g => yearData[g].secondary).filter(matchPassesFilters));

    const sections = [];
    if (mainMatches.length) {
        sections.push(`
            <div class="subsection">
                <h4 class="subsection-title">🏆 Основные матчи <span class="subsection-count">${mainMatches.length}</span></h4>
                <div class="matches-grid">${mainMatches.map(renderMatchCard).join('')}</div>
            </div>
        `);
    }
    if (secondaryMatches.length) {
        sections.push(`
            <div class="subsection">
                <h4 class="subsection-title">📋 Ранние раунды <span class="subsection-count">${secondaryMatches.length}</span></h4>
                <div class="matches-grid">${secondaryMatches.map(renderMatchCard).join('')}</div>
            </div>
        `);
    }

    const empty = sections.length
        ? ''
        : '<p class="grid-message">Нет матчей по выбранным фильтрам</p>';

    const header = `
        <div class="section-header">
            <h2>${escapeHtml(data.icon)} ${escapeHtml(data.name)} <span class="level-badge">${escapeHtml(data.level_label)}</span></h2>
            <p class="section-desc">
                <span class="year-chip">${escapeHtml(year)}</span>
                ${label ? `<span class="year-badge ${escapeHtml(label)}">${escapeHtml(label)}</span>` : ''}
                <span class="section-desc-plain">${escapeHtml(data.level_label)} · одиночный разряд</span>
            </p>
            <div class="view-switch" role="group" aria-label="Вид расписания">
                <button class="view-btn ${STATE.view === 'list' ? 'active' : ''}" data-view="list">Список</button>
                <button class="view-btn ${STATE.view === 'bracket' ? 'active' : ''}" data-view="bracket">Сетка</button>
            </div>
        </div>
    `;

    if (STATE.view === 'bracket') {
        const gender = STATE.bracketGender;
        const bracketMatches = genders.flatMap(g => (yearData[g]?.main || []).concat(yearData[g]?.secondary || []))
            .filter(m => m.gender === gender);
        return header + renderBracket(bracketMatches, gender);
    }

    return header + sections.join('') + empty;
}

// === РЕНДЕР РЕЙТИНГА ===

function renderRankingsPanel() {
    const isWomen = STATE.genderFilter === 'women';
    const rows = (STATE.rankings?.[isWomen ? 'women' : 'men'] || []).slice(0, RANKINGS_LIMIT);

    if (!rows.length) {
        return '<p class="grid-message">Рейтинг пока недоступен</p>';
    }

    const body = rows.map(row => {
        const movement = row.movement || 0;
        const movementClass = movement > 0 ? 'up' : movement < 0 ? 'down' : 'same';
        const movementText = movement > 0 ? `▲ ${movement}` : movement < 0 ? `▼ ${Math.abs(movement)}` : '—';
        const player = { id: row.id, name: row.name };
        return `
            <tr>
                <td class="rank-cell">${escapeHtml(row.rank)}</td>
                <td class="avatar-cell">${playerAvatar(player)}</td>
                <td class="name-cell">${escapeHtml(row.name || 'TBD')}</td>
                <td class="country-cell">${countryFlag(row.country_code)}</td>
                <td class="points-cell">${escapeHtml(row.points)}</td>
                <td class="movement-cell ${movementClass}">${movementText}</td>
            </tr>
        `;
    }).join('');

    const title = isWomen ? 'WTA' : 'ATP';
    const week = STATE.rankings?.week || '';

    return `
        <div class="section-header">
            <h2>⭐ Текущий рейтинг ${title}</h2>
            <p class="section-desc">${week ? `Неделя ${escapeHtml(week)} · ` : ''}обновляется еженедельно</p>
        </div>
        <div class="rankings-wrap">
            <table class="rankings-table">
                <thead>
                    <tr>
                        <th>#</th>
                        <th></th>
                        <th>Игрок</th>
                        <th>Страна</th>
                        <th>Очки</th>
                        <th>Δ</th>
                    </tr>
                </thead>
                <tbody>${body}</tbody>
            </table>
        </div>
    `;
}

// === ВКЛАДКИ ===

function renderTabs() {
    const nav = document.getElementById('tournamentTabs');
    const tournaments = STATE.index?.tournaments || [];

    const tabs = tournaments.map(t => `
        <button class="tab" data-tab="${escapeHtml(t.slug)}" role="tab" aria-selected="false" aria-controls="content">
            <span class="tab-icon">${escapeHtml(t.icon)}</span>
            <span class="tab-text">${escapeHtml(t.name)}</span>
            <span class="tab-badge" data-count="${escapeHtml(t.slug)}">${t.counts ? t.counts.main + t.counts.secondary : 0}</span>
        </button>
    `).join('');

    const rankingsTab = `
        <button class="tab" data-tab="rankings" role="tab" aria-selected="false" aria-controls="content">
            <span class="tab-icon">⭐</span>
            <span class="tab-text">Рейтинг</span>
            <span class="tab-badge" id="rankingsBadge">—</span>
        </button>
    `;

    nav.innerHTML = tabs + rankingsTab;
}

function updateTabBadges() {
    const tournaments = STATE.index?.tournaments || [];
    tournaments.forEach(t => {
        const el = document.querySelector(`[data-count="${t.slug}"]`);
        if (el) el.textContent = (t.counts?.main || 0) + (t.counts?.secondary || 0);
    });
    const rankingsBadge = document.getElementById('rankingsBadge');
    if (rankingsBadge && STATE.rankings) {
        const list = STATE.genderFilter === 'women' ? STATE.rankings.women : STATE.rankings.men;
        rankingsBadge.textContent = (list || []).length;
    }
}

// === ЗАГРУЗКА ДАННЫХ ===

async function fetchJson(path) {
    const response = await fetch(path + '?v=' + Date.now(), { cache: 'no-store' });
    if (!response.ok) throw new Error('HTTP ' + response.status);
    return response.json();
}

function dataPath(path) {
    return STATE.isDemo ? `data/sample/${path}` : `data/${path}`;
}

async function loadTournament(slug) {
    if (STATE.tournaments[slug]) return STATE.tournaments[slug];
    const data = await fetchJson(dataPath(`tournaments/${slug}.json`));
    STATE.tournaments[slug] = data;
    return data;
}

async function loadCore() {
    const [index, rankings, photos] = await Promise.all([
        fetchJson(dataPath('index.json')),
        fetchJson(dataPath('rankings.json')).catch(() => null),
        fetchJson(dataPath('players.json')).catch(() => ({})),
    ]);
    STATE.index = index;
    STATE.rankings = rankings;
    STATE.photos = photos || {};
    STATE.lastUpdated = index.last_updated || '';
}

// Демонстрационные данные — показываем, если боевые ещё не загружены
async function loadDemoData() {
    STATE.isDemo = true;
    STATE.tournaments = {};
    await loadCore();
    renderTabs();
    updateTabBadges();
    const first = STATE.index.tournaments[0]?.slug;
    if (first) await activateTab(first);
    showDemoBanner();
}

function showDemoBanner() {
    const banner = document.getElementById('demoBanner');
    if (banner) banner.style.display = 'flex';
}

// Экран-заглушка: данных ещё нет
function showSetupNotice() {
    const container = document.getElementById('content');
    container.innerHTML = `
        <div class="notice">
            <div class="notice-icon">📡</div>
            <h2>Данные ещё не загружены</h2>
            <p>
                Календарь заполняется автоматически: скрипт в GitHub Actions раз в 6 часов
                забирает расписание турниров из Sportradar и обновляет эту страницу.
            </p>
            <p class="notice-hint">
                Если расписание долго не появляется, проверьте вкладку <b>Actions</b>:
                работает ли workflow «Обновление расписания турниров» и добавлен ли
                секрет <code>SPORTRADAR_API_KEY</code> (Settings → Secrets and variables → Actions).
            </p>
            <button class="notice-btn" id="demoBtn">Посмотреть демо-данные</button>
        </div>
    `;
    const btn = document.getElementById('demoBtn');
    if (btn) {
        btn.addEventListener('click', async () => {
            btn.disabled = true;
            btn.textContent = 'Загрузка…';
            try {
                await loadDemoData();
            } catch (err) {
                console.error(err);
                btn.disabled = false;
                btn.textContent = 'Посмотреть демо-данные';
            }
        });
    }
}

// === ОТРИСОВКА ===

function renderContent() {
    const container = document.getElementById('content');
    const tab = STATE.activeTab;

    if (!tab) {
        hideYearSelect();
        container.innerHTML = '<p class="grid-message">Выберите турнир</p>';
        return;
    }

    if (tab === 'rankings') {
        hideYearSelect();
        container.innerHTML = renderRankingsPanel();
        return;
    }

    const data = STATE.tournaments[tab];
    if (!data) {
        hideYearSelect();
        container.innerHTML = '<div class="matches-grid">' +
            Array.from({ length: 3 }, () => '<div class="skeleton skeleton-card"></div>').join('') +
            '</div>';
        return;
    }

    const years = availableYears(data);
    STATE.yearsByTab[tab] = years;
    renderYearSelect(years, currentYearFor(data));
    container.innerHTML = renderTournamentPanel(data);
}

function hideYearSelect() {
    const group = document.getElementById('yearFilterGroup');
    if (group) group.style.display = 'none';
}

async function activateTab(slug) {
    STATE.activeTab = slug;
    let activeBtn = null;
    document.querySelectorAll('.tab').forEach(t => {
        const isActive = t.dataset.tab === slug;
        t.classList.toggle('active', isActive);
        t.setAttribute('aria-selected', isActive ? 'true' : 'false');
        if (isActive) activeBtn = t;
    });
    // Показываем активную вкладку в зоне видимости при горизонтальной прокрутке
    if (activeBtn && activeBtn.scrollIntoView) {
        activeBtn.scrollIntoView({ inline: 'center', block: 'nearest' });
    }

    if (slug !== 'rankings' && !STATE.tournaments[slug]) {
        renderContent();
        if (!slug) return null;   // турниров ещё нет — грузить нечего
        try {
            const data = await loadTournament(slug);
            if (STATE.activeTab === slug) renderContent();
            return data;
        } catch (err) {
            console.error('Failed to load tournament:', err);
            document.getElementById('content').innerHTML =
                '<p class="grid-message error">Не удалось загрузить данные турнира</p>';
        }
    }
    renderContent();
    return null;
}

// Обновление относительного времени последнего обновления
function updateLastUpdated(timestamp) {
    const el = document.getElementById('lastUpdated');
    if (!timestamp) {
        el.textContent = 'Время обновления неизвестно';
        return;
    }
    const d = new Date(timestamp);
    if (isNaN(d.getTime())) {
        el.textContent = 'Время обновления неизвестно';
        return;
    }
    const diffMin = Math.floor((new Date() - d) / (1000 * 60));
    if (diffMin < 1) el.textContent = 'Обновлено только что';
    else if (diffMin < 60) el.textContent = `Обновлено ${diffMin} мин назад`;
    else el.textContent = `Обновлено ${Math.floor(diffMin / 60)}ч ${diffMin % 60}мин назад`;
}

// Обратные отсчёты
let reloadPending = false;
function updateCountdowns() {
    const timers = document.querySelectorAll('.countdown-timer');
    let expired = false;
    timers.forEach(el => {
        const countdown = timeUntilMatch(el.dataset.matchTime);
        if (!countdown) {
            expired = true;
            return;
        }
        el.textContent = formatCountdown(countdown);
    });
    if (expired && !reloadPending) {
        reloadPending = true;
        refreshData().finally(() => { reloadPending = false; });
    }
}

// Полное обновление данных
async function refreshData() {
    if (STATE.loading) return;
    STATE.loading = true;
    try {
        const activeTab = STATE.activeTab;
        STATE.tournaments = {};
        await loadCore();
        renderTabs();
        updateTabBadges();
        updateLastUpdated(STATE.lastUpdated);

        const tournaments = STATE.index.tournaments || [];
        if (!tournaments.length && !STATE.isDemo) {
            showSetupNotice();
            return;
        }
        const defaultTab = activeTab || tournaments[0]?.slug || 'rankings';
        await activateTab(defaultTab);
    } catch (err) {
        console.error('Failed to load data:', err);
        document.getElementById('lastUpdated').textContent = 'Ошибка загрузки';
        const content = document.getElementById('content');
        if (!content.innerHTML.trim()) {
            content.innerHTML = '<p class="grid-message error">Ошибка загрузки данных. Проверьте соединение и обновите страницу.</p>';
        }
    } finally {
        STATE.loading = false;
    }
}

// === ИНИЦИАЛИЗАЦИЯ ===

function setupTabs() {
    document.getElementById('tournamentTabs').addEventListener('click', e => {
        const btn = e.target.closest('.tab');
        if (!btn) return;
        activateTab(btn.dataset.tab);
    });
}

function setupFilters() {
    document.querySelectorAll('[data-filter]').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('[data-filter]').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            STATE.statusFilter = btn.dataset.filter;
            renderContent();
        });
    });

    document.querySelectorAll('[data-gender]').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('[data-gender]').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            STATE.genderFilter = btn.dataset.gender;
            updateTabBadges();
            renderContent();
        });
    });

    // Выбор года
    const yearSelect = document.getElementById('yearSelect');
    if (yearSelect) {
        yearSelect.addEventListener('change', () => {
            STATE.year = yearSelect.value;
            renderContent();
        });
    }

    // Переключение вида (список / сетка) и параметры сетки
    document.getElementById('content').addEventListener('click', (event) => {
        const viewBtn = event.target.closest('[data-view]');
        if (viewBtn) {
            STATE.view = viewBtn.dataset.view;
            renderContent();
            return;
        }
        const genderBtn = event.target.closest('[data-bracket-gender]');
        if (genderBtn) {
            STATE.bracketGender = genderBtn.dataset.bracketGender;
            renderContent();
            return;
        }
        const fromBtn = event.target.closest('[data-bracket-from]');
        if (fromBtn) {
            STATE.bracketFrom = fromBtn.dataset.bracketFrom;
            renderContent();
        }
    });
}

function setupRefresh() {
    document.getElementById('refreshBtn').addEventListener('click', refreshData);
}

function setupAutoRefresh() {
    function tick() {
        refreshData().finally(() => {
            const all = Object.values(STATE.tournaments)
                .flatMap(t => Object.values(t.years || {}))
                .flatMap(y => Object.values(y))
                .flatMap(g => [...g.main, ...g.secondary]);
            const hasLive = all.some(m => m.status === 'live');
            const hasUpcoming = all.some(m => m.status === 'not_started');
            const interval = (hasLive || hasUpcoming) ? ACTIVE_REFRESH_MS : DEFAULT_REFRESH_MS;
            setTimeout(tick, interval);
        });
    }
    setTimeout(tick, DEFAULT_REFRESH_MS);
}

document.addEventListener('DOMContentLoaded', () => {
    setupTabs();
    setupFilters();
    setupRefresh();

    refreshData();

    setInterval(() => {
        updateCountdowns();
        updateLastUpdated(STATE.lastUpdated);
    }, 30000);

    setupAutoRefresh();
});
