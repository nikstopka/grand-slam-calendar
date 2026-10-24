// Tennis Calendar - Frontend Logic (v2)
// Данные: data/index.json (каталог турниров), data/tournaments/*.json (сетки матчей),
// data/rankings.json (мировой рейтинг), data/players.json (фотографии игроков).
// Всё обновляется автоматически через GitHub Actions.

const STATE = {
    index: null,
    rankings: null,
    photos: {},
    tournamentPhotos: {},   // slug -> {photo, caption}
    profiles: {},           // id игрока -> профиль (страна, возраст, награды, факты)
    tournaments: {},      // slug -> загруженные данные турнира
    activeTab: null,      // slug турнира, 'home' (титульная), 'rankings' либо 'news'
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
    rankingExpanded: false, // развёрнут ли полный рейтинг на титульной странице
    news: { items: [], updated_at: '' },
};

const ACTIVE_REFRESH_MS = 3 * 60 * 1000;   // идут live-матчи
const DEFAULT_REFRESH_MS = 10 * 60 * 1000;  // обычный режим
const FALLBACK_REFRESH_MS = 15 * 60 * 1000; // резервный источник (обновление раз в 12 ч)
const RANKINGS_LIMIT = 50;                // сколько строк показываем в рейтинге

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

// Коды стран: теннисные трёхбуквенные → двухбуквенные ISO (для флагов).
// В коде вида «ITA» нельзя просто превратить буквы в эмодзи: получится
// мусор из трёх региональных индикаторов, а не флаг.
const COUNTRY_ALPHA2 = {
    ARG: 'AR', AUS: 'AU', AUT: 'AT', BEL: 'BE', BLR: 'BY', BIH: 'BA', BRA: 'BR',
    BUL: 'BG', CAN: 'CA', CHI: 'CL', CHN: 'CN', COL: 'CO', CRO: 'HR', CZE: 'CZ',
    DEN: 'DK', ECU: 'EC', EGY: 'EG', ESP: 'ES', EST: 'EE', FIN: 'FI', FRA: 'FR',
    GBR: 'GB', GEO: 'GE', GER: 'DE', GRE: 'GR', HKG: 'HK', HUN: 'HU', INA: 'ID',
    IRE: 'IE', ISR: 'IL', ITA: 'IT', JPN: 'JP', KAZ: 'KZ', KOR: 'KR', LAT: 'LV',
    LTU: 'LT', LUX: 'LU', MAR: 'MA', MDA: 'MD', MEX: 'MX', NED: 'NL', NOR: 'NO',
    NZL: 'NZ', PAR: 'PY', PHI: 'PH', POL: 'PL', POR: 'PT', ROU: 'RO', RSA: 'ZA',
    RUS: 'RU', SLO: 'SI', SRB: 'RS', SUI: 'CH', SVK: 'SK', SWE: 'SE', THA: 'TH',
    TUR: 'TR', UAE: 'AE', UKR: 'UA', URU: 'UY', USA: 'US', UZB: 'UZ', VEN: 'VE',
    ZIM: 'ZW', TUN: 'TN', BMR: 'BM', CAY: 'KY', IVB: 'VG', TRI: 'TT',
};

// Название страны (из профиля или рейтинга) → код для флага
const COUNTRY_NAME_ALPHA2 = {
    'Argentina': 'AR', 'Australia': 'AU', 'Austria': 'AT', 'Belarus': 'BY',
    'Belgium': 'BE', 'Brazil': 'BR', 'Bulgaria': 'BG', 'Canada': 'CA',
    'Chile': 'CL', 'China': 'CN', 'Colombia': 'CO', 'Croatia': 'HR',
    'Czech Republic': 'CZ', 'Czechia': 'CZ', 'Denmark': 'DK', 'Ecuador': 'EC',
    'Egypt': 'EG', 'Estonia': 'EE', 'Finland': 'FI', 'France': 'FR',
    'Georgia': 'GE', 'Germany': 'DE', 'Greece': 'GR', 'Hong Kong': 'HK',
    'Hungary': 'HU', 'India': 'IN', 'Indonesia': 'ID', 'Ireland': 'IE',
    'Israel': 'IL', 'Italy': 'IT', 'Japan': 'JP', 'Kazakhstan': 'KZ',
    'South Korea': 'KR', 'Korea': 'KR', 'Latvia': 'LV', 'Lithuania': 'LT',
    'Luxembourg': 'LU', 'Madagascar': 'MG', 'Morocco': 'MA', 'Moldova': 'MD',
    'Mexico': 'MX', 'Netherlands': 'NL', 'New Zealand': 'NZ', 'Norway': 'NO',
    'Paraguay': 'PY', 'Peru': 'PE', 'Philippines': 'PH', 'Poland': 'PL',
    'Portugal': 'PT', 'Romania': 'RO', 'Russia': 'RU', 'Serbia': 'RS',
    'Slovakia': 'SK', 'Slovenia': 'SI', 'South Africa': 'ZA', 'Spain': 'ES',
    'Sweden': 'SE', 'Switzerland': 'CH', 'Taiwan': 'TW', 'Thailand': 'TH',
    'Tunisia': 'TN', 'Turkey': 'TR', 'Ukraine': 'UA',
    'United Arab Emirates': 'AE', 'United Kingdom': 'GB', 'Great Britain': 'GB',
    'United States': 'US', 'Uruguay': 'UY', 'Uzbekistan': 'UZ',
    'Venezuela': 'VE', 'Vietnam': 'VN', 'Zimbabwe': 'ZW',
};

// Двухбуквенный код страны по коду ATP/WTA или по названию
function countryAlpha2(code, name) {
    let alpha2 = '';
    if (code && typeof code === 'string') {
        const c = code.trim().toUpperCase();
        if (/^[A-Z]{2}$/.test(c)) alpha2 = c;
        else if (/^[A-Z]{3}$/.test(c)) alpha2 = COUNTRY_ALPHA2[c] || '';
    }
    if (!alpha2 && name && typeof name === 'string') {
        alpha2 = COUNTRY_NAME_ALPHA2[name.trim()] || '';
    }
    return /^[A-Z]{2}$/.test(alpha2) ? alpha2 : '';
}

// Флаг эмодзи (Windows такие не рисует — показывает буквы)
function countryFlag(code, name) {
    const alpha2 = countryAlpha2(code, name);
    if (!alpha2) return '🏳️';
    return String.fromCodePoint(
        ...[...alpha2].map(ch => 0x1F1E6 - 65 + ch.charCodeAt(0))
    );
}

// Флаг картинкой — рисуется одинаково в любом браузере
function countryFlagImg(code, name, size) {
    const alpha2 = countryAlpha2(code, name);
    if (!alpha2) return '<span class="country-flag fallback">🏳️</span>';
    // у flagcdn есть только размеры w20, w40, w80 и 16x12 — других нет
    const width = size === 40 ? 40 : 20;
    return `<img class="country-flag" src="https://flagcdn.com/w${width}/${alpha2.toLowerCase()}.png" ` +
           `alt="${alpha2}" title="${alpha2}" loading="lazy" referrerpolicy="no-referrer" ` +
           `onerror="this.outerHTML='🏳️'">`;
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
                        <span class="player-flag">${countryFlagImg(homePlayer.country_code, null, 20)}</span>
                        <span class="player-name">${escapeHtml(homePlayer.name || 'TBD')}</span>
                        ${homePlayer.seed ? `<span class="player-seed">#${escapeHtml(homePlayer.seed)}</span>` : ''}
                        ${homeWon ? '<span class="winner-indicator">✓</span>' : ''}
                    </div>
                    <div class="score-display">${homeSets}${homeTotal}</div>
                </div>

                <div class="player ${awayWon ? 'winner' : ''}">
                    <div class="player-info">
                        ${playerAvatar(awayPlayer)}
                        <span class="player-flag">${countryFlagImg(awayPlayer.country_code, null, 20)}</span>
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
        ${renderTournamentHero(data, year, label)}
        <div class="tournament-toolbar">
            <div class="view-switch" role="group" aria-label="Вид расписания">
                <button class="view-btn ${STATE.view === 'list' ? 'active' : ''}" data-view="list">Результаты</button>
                <button class="view-btn ${STATE.view === 'bracket' ? 'active' : ''}" data-view="bracket">Сетка</button>
            </div>
            <p class="tournament-toolbar-meta">
                <span class="year-chip">${escapeHtml(year)}</span>
                ${label ? `<span class="year-badge ${escapeHtml(label)}">${escapeHtml(label)}</span>` : ''}
                <span class="section-desc-plain">${escapeHtml(data.level_label)} · одиночный разряд</span>
            </p>
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

// Шапка карточки турнира: фото, название, краткое описание
function renderTournamentHero(data, year, label) {
    const photo = (STATE.tournamentPhotos || {})[data.slug]?.photo;
    const description = data.description || '';
    const style = photo ? ` style="--hero-image: url('${escapeHtml(photo)}')"` : '';
    return `
        <button class="back-btn" type="button" data-go="home">← К турнирам</button>
        <div class="tournament-hero${photo ? ' has-photo' : ''}"${style}>
            <div class="tournament-hero-content">
                <h2>${escapeHtml(data.icon)} ${escapeHtml(data.name)} <span class="level-badge">${escapeHtml(data.level_label)}</span></h2>
                ${description ? `<p class="tournament-description">${escapeHtml(description)}</p>` : ''}
            </div>
        </div>`;
}

// === РЕНДЕР РЕЙТИНГА ===

function renderRankingsPanel() {
    const isWomen = STATE.genderFilter === 'women';
    const rows = (STATE.rankings?.[isWomen ? 'women' : 'men'] || []).slice(0, RANKINGS_LIMIT);

    if (!rows.length) {
        return '<p class="grid-message">Рейтинг пока недоступен</p>';
    }

    const title = isWomen ? 'WTA' : 'ATP';
    const week = STATE.rankings?.week || '';

    return `
        <div class="section-header">
            <h2>⭐ Текущий рейтинг ${title}</h2>
            <p class="section-desc">${week ? `Неделя ${escapeHtml(week)} · ` : ''}обновляется еженедельно · нажмите на игрока, чтобы открыть профиль</p>
        </div>
        <button class="back-btn" type="button" data-go="home">← На главную</button>
        ${renderRankTable(rows)}
    `;
}

// === ВКЛАДКИ ===

function renderTabs() {
    // Полоса вкладок с турнирами убрана: навигация идёт через карусель
    // на титульной странице. Здесь только счётчики для совместимости.
    const nav = document.getElementById('tournamentTabs');
    if (!nav) return;
    const tournaments = STATE.index?.tournaments || [];
    nav.innerHTML = tournaments.map(t => `
        <button class="tab" data-tab="${escapeHtml(t.slug)}" role="tab">
            <span class="tab-text">${escapeHtml(t.name)}</span>
            <span class="tab-badge" data-count="${escapeHtml(t.slug)}">${t.counts ? t.counts.main + t.counts.secondary : 0}</span>
        </button>`).join('');
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

// === БЛИЖАЙШИЕ ТУРНИРЫ ===

const LEVEL_LABELS = {
    grand_slam: 'Большой шлем',
    atp_1000: 'Masters 1000',
    wta_1000: 'WTA 1000',
    atp_finals: 'ATP Finals',
    wta_finals: 'WTA Finals',
};

// Плашка источника данных
function renderSourceBadge(source) {
    const badge = document.getElementById('sourceBadge');
    if (!badge) return;
    if (!source || source === 'sportradar') {
        badge.style.display = 'none';
        return;
    }
    badge.textContent = 'резервный источник';
    badge.className = 'source-badge';
    badge.title = 'Данные берутся из бесплатных открытых источников: обновление раз в 12 часов';
    badge.style.display = 'inline-block';
}

// === ТИТУЛЬНАЯ СТРАНИЦА ===

const RU_MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля',
    'августа', 'сентября', 'октября', 'ноября', 'декабря'];

// Сколько дней до даты
function daysUntil(dateStr) {
    const target = new Date(dateStr + 'T00:00:00');
    if (isNaN(target.getTime())) return null;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return Math.round((target - today) / 86400000);
}

// «19–26 января 2026»
function formatDateRange(startStr, endStr) {    const start = new Date(startStr + 'T00:00:00');
    if (isNaN(start.getTime())) return { text: startStr || '', start: startStr };
    const end = new Date((endStr || startStr) + 'T00:00:00');
    const validEnd = !isNaN(end.getTime());
    let text;
    if (!validEnd) {
        text = `${start.getDate()} ${RU_MONTHS[start.getMonth()]}`;
    } else if (end.getMonth() === start.getMonth() && end.getFullYear() === start.getFullYear()) {
        text = end.getDate() === start.getDate()
            ? `${start.getDate()} ${RU_MONTHS[start.getMonth()]} ${start.getFullYear()}`
            : `${start.getDate()}–${end.getDate()} ${RU_MONTHS[start.getMonth()]} ${start.getFullYear()}`;
    } else {
        text = `${start.getDate()} ${RU_MONTHS[start.getMonth()]} — ` +
               `${end.getDate()} ${RU_MONTHS[end.getMonth()]} ${end.getFullYear()}`;
    }
    return { text, start: startStr, end: endStr || startStr };
}

// Ближайшая дата проведения турнира (из календаря сезона)
function nearestTournamentDate(slug) {
    const items = (STATE.calendar || []).filter(item => item.slug === slug);
    if (!items.length) return null;
    const today = new Date().toISOString().slice(0, 10);
    const upcoming = items.filter(item => item.start >= today);
    const item = upcoming.length ? upcoming[0] : items[items.length - 1];
    return formatDateRange(item.start, item.end);
}

// Хронологический порядок турниров: сначала идущие в данный момент, затем по дате
function tournamentsInOrder() {
    const tournaments = (STATE.index?.tournaments || []).slice();
    const dates = {};
    const calendarBySlug = {};
    (STATE.calendar || []).forEach(item => {
        if (!item.slug) return;
        if (!calendarBySlug[item.slug]) calendarBySlug[item.slug] = [];
        calendarBySlug[item.slug].push(item);
        if (!dates[item.slug] || item.start < dates[item.slug]) {
            dates[item.slug] = item.start;
        }
    });
    const now = new Date();
    return tournaments.sort((a, b) => {
        const itemsA = calendarBySlug[a.slug] || [];
        const itemsB = calendarBySlug[b.slug] || [];
        const inProgressA = itemsA.some(item => {
            const start = new Date(item.start + 'T00:00:00');
            if (isNaN(start.getTime())) return false;
            const end = item.end ? new Date(item.end + 'T23:59:59') : new Date(start.getTime());
            if (isNaN(end.getTime())) end.setTime(start.getTime() + 86400000 - 1);
            return start <= now && end >= now;
        });
        const inProgressB = itemsB.some(item => {
            const start = new Date(item.start + 'T00:00:00');
            if (isNaN(start.getTime())) return false;
            const end = item.end ? new Date(item.end + 'T23:59:59') : new Date(start.getTime());
            if (isNaN(end.getTime())) end.setTime(start.getTime() + 86400000 - 1);
            return start <= now && end >= now;
        });
        if (inProgressA && !inProgressB) return -1;
        if (!inProgressA && inProgressB) return 1;
        const da = dates[a.slug] || '9999-99-99';
        const db = dates[b.slug] || '9999-99-99';
        if (da === db) return a.name.localeCompare(b.name, 'ru');
        return da < db ? -1 : 1;
    });
}

// Ближайшие турниры — только предстоящие, без идущих в данный момент
function renderUpcomingBlock() {
    const today = new Date();
    const todayStr = today.toISOString().slice(0, 10);
    const known = new Set((STATE.index?.tournaments || []).map(t => t.slug));
    const items = (STATE.calendar || [])
        .filter(item => {
            if (!item.start) return false;
            const startDate = new Date(item.start + 'T00:00:00');
            if (isNaN(startDate.getTime())) return false;
            const endDate = item.end ? new Date(item.end + 'T23:59:59') : startDate;
            if (isNaN(endDate.getTime())) {
                endDate.setTime(startDate.getTime());
                endDate.setHours(23, 59, 59, 999);
            }
            // Исключаем уже начавшиеся/идущие турниры
            if (endDate < today) return false;
            if (startDate <= today) return false;
            return item.start >= todayStr;
        })
        .sort((a, b) => (a.start < b.start ? -1 : 1))
        .slice(0, 6);
    if (!items.length) return '';

    const rows = items.map(item => {
        const date = formatDateRange(item.start, item.end);
        const days = daysUntil(item.start);
        const countdown = days === null ? ''
            : days === 0 ? 'сегодня'
            : days === 1 ? 'завтра'
            : `через ${days} дн.`;
        const level = LEVEL_LABELS[item.level] || item.level;
        const inner = `
            <span class="upcoming-date">${escapeHtml(date.text)}</span>
            <span class="upcoming-name">${escapeHtml(item.name)}</span>
            <span class="upcoming-place">${escapeHtml(item.place || '')} · ${escapeHtml(level)}</span>
            ${countdown ? `<span class="upcoming-countdown">${escapeHtml(countdown)}</span>` : ''}`;
        // ссылка — только если у турнира есть отдельная страница
        return item.slug && known.has(item.slug)
            ? `<a class="upcoming-item ${escapeHtml(item.level)}" href="#${escapeHtml(item.slug)}" data-tournament="${escapeHtml(item.slug)}">${inner}</a>`
            : `<div class="upcoming-item plain ${escapeHtml(item.level)}">${inner}</div>`;
    }).join('');

    return `
        <section class="upcoming-block">
            <h3 class="upcoming-title">Ближайшие турниры</h3>
            <div class="upcoming-list">${rows}</div>
        </section>`;
}

// --- Карусель турниров ---

function renderHeroCarousel() {
    const tournaments = tournamentsInOrder();
    if (!tournaments.length) return '';

    const photos = STATE.tournamentPhotos || {};
    const todayStr = new Date().toISOString().slice(0, 10);
    const now = new Date();
    const calendarBySlug = {};
    (STATE.calendar || []).forEach(item => {
        if (!item.slug) return;
        if (!calendarBySlug[item.slug]) calendarBySlug[item.slug] = [];
        calendarBySlug[item.slug].push(item);
    });

    const cards = tournaments.map(t => {
        const photo = photos[t.slug]?.photo;
        const date = nearestTournamentDate(t.slug);
        const days = date ? daysUntil(date.start) : null;
        const soon = days !== null && days >= 0 && days <= 45;
        const items = calendarBySlug[t.slug] || [];
        const inProgress = items.some(item => {
            const start = new Date(item.start + 'T00:00:00');
            if (isNaN(start.getTime())) return false;
            const end = item.end ? new Date(item.end + 'T23:59:59') : new Date(start.getTime());
            if (isNaN(end.getTime())) end.setTime(start.getTime() + 86400000 - 1);
            return start <= now && end >= now;
        });
        const media = photo
            ? `<img class="carousel-img" src="${escapeHtml(photo)}" alt="${escapeHtml(t.name)}" ` +
              `loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">`
            : `<span class="carousel-img carousel-img-fallback">${escapeHtml(t.icon || '🎾')}</span>`;
        return `
            <article class="carousel-card" data-slug="${escapeHtml(t.slug)}" data-inprogress="${inProgress ? '1' : '0'}">
                <a class="carousel-link" href="#${escapeHtml(t.slug)}" data-tournament="${escapeHtml(t.slug)}">
                    <div class="carousel-media">
                        ${media}
                        <span class="carousel-badge">${escapeHtml(t.level_label || '')}</span>
                        ${inProgress ? '<span class="carousel-inprogress">идёт</span>' : ''}
                        ${!inProgress && soon ? '<span class="carousel-live-dot" title="скоро"></span>' : ''}
                    </div>
                    <div class="carousel-body">
                        <h3 class="carousel-title">${escapeHtml(t.name)}</h3>
                        <p class="carousel-date">${date ? escapeHtml(date.text) : ''}</p>
                        <span class="carousel-more">Смотреть результаты →</span>
                    </div>
                    <span class="carousel-shine" aria-hidden="true"></span>
                    <span class="carousel-spotlight" aria-hidden="true"></span>
                </a>
            </article>`;
    }).join('');

    return `
        <section class="hero">
            <div class="hero-intro">
                <h2 class="hero-title">Турниры сезона</h2>
                <p class="hero-sub">Большой шлем, Masters 1000 и WTA 1000 — расписание, сетки и результаты по годам</p>
            </div>
            <div class="carousel" id="carousel">
                <button class="carousel-arrow carousel-prev" id="carouselPrev" type="button" aria-label="Предыдущий турнир">‹</button>
                <div class="carousel-track" id="carouselTrack">${cards}</div>
                <button class="carousel-arrow carousel-next" id="carouselNext" type="button" aria-label="Следующий турнир">›</button>
            </div>
            <div class="carousel-dots" id="carouselDots"></div>
        </section>`;
}

// Поведение карусели: активная карточка по центру, стрелки, перетаскивание
function setupCarousel() {
    const track = document.getElementById('carouselTrack');
    if (!track) return;
    const cards = Array.from(track.querySelectorAll('.carousel-card'));
    if (!cards.length) return;

    let activeIndex = 0;
    let dragging = false;
    let dragStartX = 0;
    let dragScrollLeft = 0;
    let moved = false;
    let velocity = 0;
    let animationId = null;

    function step() {
        if (cards.length < 2) return cards[0].offsetWidth || 280;
        const gap = Math.abs(cards[1].offsetLeft - cards[0].offsetLeft);
        return gap || (cards[0].offsetWidth + 24);
    }

    function updateActive() {
        const center = track.scrollLeft + track.clientWidth / 2;
        let best = 0;
        let bestDist = Infinity;
        cards.forEach((card, i) => {
            const cardCenter = card.offsetLeft + card.offsetWidth / 2;
            const dist = Math.abs(cardCenter - center);
            if (dist < bestDist) {
                bestDist = dist;
                best = i;
            }
        });
        if (best !== activeIndex) {
            activeIndex = best;
            cards.forEach((card, i) => card.classList.toggle('active', i === best));
            updateCarouselDots(best);
        }
    }

    function scrollToIndex(index) {
        const card = cards[Math.max(0, Math.min(cards.length - 1, index))];
        if (!card) return;
        const left = card.offsetLeft - (track.clientWidth - card.offsetWidth) / 2;
        track.scrollTo({ left, behavior: 'smooth' });
    }

    function easeOutQuad(t) {
        return t * (2 - t);
    }

    function animateInertia() {
        if (!dragging && Math.abs(velocity) > 0.5) {
            track.scrollLeft += velocity;
            velocity *= 0.92; // трение
            animationId = requestAnimationFrame(animateInertia);
        } else {
            velocity = 0;
            cancelAnimationFrame(animationId);
            animationId = null;
            updateActive();
        }
    }

    document.getElementById('carouselPrev')?.addEventListener('click', () => scrollToIndex(activeIndex - 1));
    document.getElementById('carouselNext')?.addEventListener('click', () => scrollToIndex(activeIndex + 1));

    // точки-индикаторы
    const dots = document.getElementById('carouselDots');
    if (dots) {
        dots.innerHTML = cards.map((card, i) =>
            `<button class="carousel-dot" data-index="${i}" type="button" ` +
            `aria-label="Турнир ${i + 1}"></button>`).join('');
        dots.addEventListener('click', e => {
            const dot = e.target.closest('.carousel-dot');
            if (!dot) return;
            scrollToIndex(Number(dot.dataset.index));
        });
    }

    track.addEventListener('scroll', () => requestAnimationFrame(updateActive), { passive: true });

    // Эффекты: наклон 3D и световое пятно следуют за курсором
    track.addEventListener('pointermove', (event) => {
        if (event.pointerType === 'touch') return;
        const card = event.target.closest('.carousel-card');
        cards.forEach(c => c.classList.remove('hovered'));
        if (!card) return;
        const rect = card.getBoundingClientRect();
        const x = (event.clientX - rect.left) / rect.width;
        const y = (event.clientY - rect.top) / rect.height;
        card.classList.add('hovered');
        card.style.setProperty('--mx', `${(x * 100).toFixed(1)}%`);
        card.style.setProperty('--my', `${(y * 100).toFixed(1)}%`);
        card.style.setProperty('--tilt-x', `${((0.5 - y) * 9).toFixed(2)}deg`);
        card.style.setProperty('--tilt-y', `${((x - 0.5) * 12).toFixed(2)}deg`);
    });

    track.addEventListener('pointerleave', () => {
        cards.forEach(c => {
            c.classList.remove('hovered');
            c.style.setProperty('--tilt-x', '0deg');
            c.style.setProperty('--tilt-y', '0deg');
        });
    });

    // перетаскивание мышью
    track.addEventListener('pointerdown', e => {
        dragging = true;
        moved = false;
        dragStartX = e.clientX;
        dragScrollLeft = track.scrollLeft;
        velocity = 0;
        if (animationId) {
            cancelAnimationFrame(animationId);
            animationId = null;
        }
        track.classList.add('dragging');
    });
    window.addEventListener('pointermove', e => {
        if (!dragging) return;
        const delta = e.clientX - dragStartX;
        if (Math.abs(delta) > 6) moved = true;
        // уменьшаем чувствительность на 30% для более плавного управления
        track.scrollLeft = dragScrollLeft - delta * 0.7;
        // вычисляем скорость для инерции
        velocity = delta * 0.7;
    });
    window.addEventListener('pointerup', () => {
        if (!dragging) return;
        dragging = false;
        track.classList.remove('dragging');
        // инерция при отпускании
        if (Math.abs(velocity) > 1) {
            cancelAnimationFrame(animationId);
            animationId = requestAnimationFrame(animateInertia);
        } else {
            updateActive();
        }
    });
    track.addEventListener('click', e => {
        if (moved) {
            e.preventDefault();
            e.stopPropagation();
            moved = false;
        }
    }, true);

    // первая карточка — активная и по центру
    cards[0].classList.add('active');
    updateCarouselDots(0);
    // поля позволяют центрировать первую и последнюю карточку
    const pad = Math.max(0, (track.clientWidth - cards[0].offsetWidth) / 2);
    track.style.paddingLeft = pad + 'px';
    track.style.paddingRight = pad + 'px';
    requestAnimationFrame(updateActive);
}

function updateCarouselDots(active) {
    const dots = document.querySelectorAll('#carouselDots .carousel-dot');
    dots.forEach((dot, i) => dot.classList.toggle('active', i === active));
}

// --- Рейтинг на титульной странице ---

function rankingRows() {
    const isWomen = STATE.genderFilter === 'women';
    return (STATE.rankings?.[isWomen ? 'women' : 'men'] || []).slice(0, RANKINGS_LIMIT);
}

function playerProfileFor(player) {
    const direct = STATE.profiles?.[player.id];
    if (direct) return direct;
    // запасной путь: по нормализованному имени
    const key = String(player.name || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
    const found = Object.values(STATE.profiles || {}).find(p => p.name_key === key);
    return found || null;
}

function renderRankCard(row) {
    const profile = playerProfileFor(row);
    const photo = profile?.photo || STATE.photos?.[row.id];
    const avatar = photo
        ? `<img src="${escapeHtml(photo)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">`
        : `<span class="avatar-fallback">${escapeHtml(playerInitials(row.name))}</span>`;
    const movement = row.movement || 0;
    const movementClass = movement > 0 ? 'up' : movement < 0 ? 'down' : 'same';
    const movementText = movement > 0 ? `▲${movement}` : movement < 0 ? `▼${Math.abs(movement)}` : '—';
    return `
        <div class="rank-card">
            <span class="rank-card-pos">${escapeHtml(row.rank)}</span>
            <span class="player-avatar rank-card-avatar">${avatar}</span>
            <div class="rank-card-body">
                <button class="player-link" type="button" data-player="${escapeHtml(row.id)}">${escapeHtml(row.name || 'TBD')}</button>
                <span class="rank-card-meta">
                    ${countryFlagImg(row.country_code, row.country_name || profile?.country, 20)}
                    <b>${escapeHtml(row.points)}</b>
                    <span class="movement-cell ${movementClass}">${movementText}</span>
                </span>
            </div>
        </div>`;
}

function renderRankTable(rows) {
    const body = rows.map(row => {
        const movement = row.movement || 0;
        const movementClass = movement > 0 ? 'up' : movement < 0 ? 'down' : 'same';
        const movementText = movement > 0 ? `▲ ${movement}` : movement < 0 ? `▼ ${Math.abs(movement)}` : '—';
        const profile = playerProfileFor(row);
        const photo = profile?.photo || STATE.photos?.[row.id];
        const avatar = photo
            ? `<img src="${escapeHtml(photo)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">`
            : `<span class="avatar-fallback">${escapeHtml(playerInitials(row.name))}</span>`;
        return `
            <tr>
                <td class="rank-cell">${escapeHtml(row.rank)}</td>
                <td class="avatar-cell"><span class="player-avatar">${avatar}</span></td>
                <td class="name-cell">
                    <button class="player-link" type="button" data-player="${escapeHtml(row.id)}">${escapeHtml(row.name || 'TBD')}</button>
                </td>
                <td class="country-cell">${countryFlagImg(row.country_code, row.country_name || profile?.country, 20)}</td>
                <td class="points-cell">${escapeHtml(row.points)}</td>
                <td class="movement-cell ${movementClass}">${movementText}</td>
            </tr>`;
    }).join('');

    return `
        <div class="rankings-wrap">
            <table class="rankings-table">
                <thead>
                    <tr>
                        <th>#</th><th></th><th>Игрок</th><th>Страна</th><th>Очки</th><th>Δ</th>
                    </tr>
                </thead>
                <tbody>${body}</tbody>
            </table>
        </div>`;
}

function renderLandingRanking() {
    const rows = rankingRows();
    if (!rows.length) return '';

    const top = rows.slice(0, 7);
    const rest = rows.slice(7);
    const week = STATE.rankings?.week || '';

    return `
        <section class="landing-ranking">
            <div class="section-header">
                <div class="landing-rank-title">
                    <h2>⭐ Мировой рейтинг</h2>
                    <div class="view-switch compact" role="group" aria-label="Тур">
                        <button class="view-btn ${STATE.genderFilter !== 'women' ? 'active' : ''}" data-gender="men">ATP</button>
                        <button class="view-btn ${STATE.genderFilter === 'women' ? 'active' : ''}" data-gender="women">WTA</button>
                    </div>
                </div>
                <p class="section-desc">${week ? `Неделя ${escapeHtml(week)} · ` : ''}обновляется еженедельно</p>
                <div class="landing-ranking-actions">
                    ${rest.length ? `
                        <button class="collapse-btn" id="rankingToggle" type="button" aria-expanded="${STATE.rankingExpanded}">
                            ${STATE.rankingExpanded ? 'Свернуть' : 'Показать весь рейтинг'} <span class="chevron">▾</span>
                        </button>` : ''}
                    <button class="collapse-btn ghost" type="button" data-go="rankings">Весь рейтинг →</button>
                </div>
            </div>
            <div class="ranking-top">${top.map(renderRankCard).join('')}</div>
            ${rest.length ? `
                <div class="ranking-rest ${STATE.rankingExpanded ? 'expanded' : 'collapsed'}" id="rankingRest">
                    ${renderRankTable(rest)}
                </div>` : ''}
        </section>`;
}

// --- Титульная страница целиком ---

function renderNewsPreview() {
    const items = (STATE.news?.items || []).slice(0, 3);
    if (!items.length) return '';
    const cards = items.map(item => {
        const img = item.image
            ? `<img class="news-preview-img" src="${escapeHtml(item.image)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">`
            : '';
        return `
            <a class="news-preview-card" href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">
                <div class="news-preview-media">${img}</div>
                <div class="news-preview-body">
                    <div class="news-preview-meta">
                        <span class="news-source">${escapeHtml(item.source)}</span>
                    </div>
                    <h4 class="news-preview-title">${escapeHtml(item.title_ru || item.title_orig || '')}</h4>
                </div>
            </a>`;
    }).join('');
    return `
        <section class="news-preview">
            <div class="section-header">
                <div>
                    <h2>📰 Новости тенниса</h2>
                    <p class="section-desc">ATP, WTA, Tennis.com — переведено на русский</p>
                </div>
                <button class="collapse-btn ghost" type="button" data-go="news">Все новости →</button>
            </div>
            <div class="news-preview-grid">${cards}</div>
        </section>`;
}

function renderNewsPage() {
    const items = STATE.news?.items || [];
    if (!items.length) {
        return `
            <div class="landing">
                <button class="back-btn" type="button" data-go="home">← На главную</button>
                <section class="news-page">
                    <div class="section-header">
                        <h2>📰 Новости тенниса</h2>
                        <p class="section-desc">ATP, WTA, Tennis.com — переведено на русский</p>
                    </div>
                    <p class="grid-message">Новости пока не загружены. Они появятся после обновления через GitHub Actions.</p>
                </section>
            </div>`;
    }
    const rows = items.map(item => {
        const img = item.image
            ? `<img class="news-row-img" src="${escapeHtml(item.image)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">`
            : '';
        return `
            <a class="news-row" href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">
                <div class="news-row-media">${img}</div>
                <div class="news-row-body">
                    <div class="news-row-meta">
                        <span class="news-source">${escapeHtml(item.source)}</span>
                        <span class="news-arrow">Оригинал →</span>
                    </div>
                    <h3 class="news-row-title">${escapeHtml(item.title_ru || item.title_orig || '')}</h3>
                    ${item.title_orig && item.title_ru && item.title_orig !== item.title_ru ? `<p class="news-row-orig">${escapeHtml(item.title_orig)}</p>` : ''}
                </div>
            </a>`;
    }).join('');
    return `
        <div class="landing">
            <button class="back-btn" type="button" data-go="home">← На главную</button>
            <section class="news-page">
                <div class="section-header">
                    <h2>📰 Новости тенниса</h2>
                    <p class="section-desc">ATP, WTA, Tennis.com — переведено на русский</p>
                </div>
                <div class="news-list">${rows}</div>
            </section>
        </div>`;
}

function renderLandingPage() {
    return `
        <div class="landing">
            ${renderHeroCarousel()}
            ${renderUpcomingBlock()}
            ${renderNewsPreview()}
            ${renderLandingRanking()}
        </div>`;
}

// --- Профиль игрока ---

function openPlayerProfile(playerId) {
    const rows = (STATE.rankings?.men || []).concat(STATE.rankings?.women || []);
    const row = rows.find(r => r.id === playerId) || { id: playerId, name: playerId };
    const profile = playerProfileFor(row) || {};
    const photo = profile.photo || STATE.photos?.[playerId];
    const modal = document.getElementById('profileModal');
    if (!modal) return;

    const facts = [];
    if (profile.country) facts.push(profile.country);
    if (profile.age) facts.push(`${profile.age} ${pluralYears(profile.age)}`);
    if (profile.height) facts.push(profile.height);
    if (profile.turned_pro) facts.push(`профи с ${profile.turned_pro}`);
    if (profile.plays) facts.push(profile.plays);

    // предложение о титулах уже показано отдельно — убираем его из текста
    let summary = profile.summary || '';
    if (profile.titles && summary.includes(profile.titles)) {
        summary = summary.replace(profile.titles, '').replace(/\s+/g, ' ').trim();
        summary = summary.replace(/^[\s,;:.]+/, '');
    }

    modal.querySelector('.profile-modal-inner').innerHTML = `
        <button class="modal-close" type="button" data-close-modal aria-label="Закрыть">×</button>
        <div class="profile-photo-wrap">
            ${photo
                ? `<img class="profile-photo" src="${escapeHtml(photo)}" alt="${escapeHtml(row.name || '')}" referrerpolicy="no-referrer">`
                : `<div class="profile-photo profile-photo-fallback">${escapeHtml(playerInitials(row.name))}</div>`}
        </div>
        <div class="profile-info">
            <h3 class="profile-name">${escapeHtml(row.name || '')} ${countryFlagImg(row.country_code, profile?.country, 40)}</h3>
            ${facts.length ? `<p class="profile-facts">${facts.map(escapeHtml).join(' · ')}</p>` : ''}
            ${profile.residence ? `<p class="profile-sub">Живёт: ${escapeHtml(profile.residence)}</p>` : ''}
            ${profile.titles ? `<p class="profile-titles">🏆 ${escapeHtml(profile.titles)}</p>` : ''}
            ${summary ? `<p class="profile-summary">${escapeHtml(summary)}</p>` : ''}
            ${profile.wiki_url ? `<a class="profile-link" href="${escapeHtml(profile.wiki_url)}" target="_blank" rel="noopener noreferrer">Статья в Википедии →</a>` : ''}
            ${!profile.summary && !profile.titles ? '<p class="profile-sub">Профиль собирается…</p>' : ''}
        </div>`;
    modal.classList.add('open');
    document.body.classList.add('modal-open');
}

function pluralYears(age) {
    const n = Number(age) % 100;
    if (n >= 11 && n <= 14) return 'лет';
    const last = Number(age) % 10;
    if (last === 1) return 'год';
    if (last >= 2 && last <= 4) return 'года';
    return 'лет';
}

function closePlayerProfile() {
    const modal = document.getElementById('profileModal');
    if (!modal) return;
    modal.classList.remove('open');
    document.body.classList.remove('modal-open');
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
    const [index, rankings, photos, calendar, tourPhotos, profiles] = await Promise.all([
        fetchJson(dataPath('index.json')),
        fetchJson(dataPath('rankings.json')).catch(() => null),
        fetchJson(dataPath('players.json')).catch(() => ({})),
        fetchJson(dataPath('calendar.json')).catch(() => null),
        fetchJson(dataPath('tournament_photos.json')).catch(() => ({})),
        fetchJson(dataPath('player_profiles.json')).catch(() => ({})),
    ]);
    STATE.index = index;
    STATE.rankings = rankings;
    STATE.photos = photos || {};
    STATE.calendar = (calendar && calendar.tournaments) || [];
    STATE.tournamentPhotos = tourPhotos || {};
    STATE.profiles = profiles || {};
    STATE.lastUpdated = index.last_updated || '';
    renderSourceBadge(index.source);
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

    // Титульная страница
    if (tab === 'home') {
        hideYearSelect();
        container.innerHTML = renderLandingPage();
        setupCarousel();
        return;
    }

    if (tab === 'news') {
        hideYearSelect();
        container.innerHTML = renderNewsPage();
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
    if (slug === 'home') {
        history.replaceState(null, '', window.location.pathname);
    } else if (slug) {
        history.replaceState(null, '', '#' + slug);
    }
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

    // На титульной странице, в новостях и рейтинге фильтры не нужны
    const statusGroup = document.getElementById('statusFilterGroup');
    if (statusGroup) statusGroup.style.display = (slug === 'home' || slug === 'news') ? 'none' : 'flex';
    const allGender = document.querySelector('[data-gender="all"]');
    if (allGender) allGender.style.display = (slug === 'home' || slug === 'news') ? 'none' : '';
    const filtersBar = document.getElementById('filtersBar');
    if (filtersBar) filtersBar.style.display = (slug === 'home' || slug === 'news') ? 'none' : 'flex';
    if (slug === 'home' && STATE.genderFilter === 'all') {
        setGenderFilter('men');
    }

    if (slug !== 'rankings' && slug !== 'home' && slug !== 'news' && !STATE.tournaments[slug]) {
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

// Переключатель ATP / WTA / Все
function setGenderFilter(value) {
    STATE.genderFilter = value;
    document.querySelectorAll('[data-gender]').forEach(b => {
        b.classList.toggle('active', b.dataset.gender === value);
    });
    updateTabBadges();
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
        const hash = (location.hash || '').replace(/^#/, '');
        const known = tournaments.some(t => t.slug === hash) || hash === 'news' || hash === 'rankings';
        const defaultTab = activeTab
            || (known ? hash : 'home')
            || tournaments[0]?.slug
            || 'rankings';
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
    const nav = document.getElementById('tournamentTabs');
    if (nav) {
        nav.addEventListener('click', e => {
            const btn = e.target.closest('.tab');
            if (!btn) return;
            activateTab(btn.dataset.tab);
        });
    }

    // Ссылки на турниры с титульной страницы: #slug
    document.addEventListener('click', e => {
        const link = e.target.closest('[data-tournament]');
        if (link) {
            e.preventDefault();
            activateTab(link.dataset.tournament);
            window.scrollTo({ top: 0, behavior: 'smooth' });
            return;
        }
        // Переключатель ATP / WTA — и в панели фильтров, и в блоке рейтинга
        const genderBtn = e.target.closest('[data-gender]');
        if (genderBtn) {
            setGenderFilter(genderBtn.dataset.gender);
            renderContent();
        }
    });

    window.addEventListener('hashchange', () => {
        const slug = (location.hash || '').replace(/^#/, '');
        if (slug && slug !== STATE.activeTab) activateTab(slug);
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

    // Выбор года
    const yearSelect = document.getElementById('yearSelect');
    if (yearSelect) {
        yearSelect.addEventListener('change', () => {
            STATE.year = yearSelect.value;
            renderContent();
        });
    }

    // Переключение вида (результаты / сетка) и параметры сетки
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
            return;
        }
        // Развернуть/свернуть полный рейтинг на титульной странице
        const toggleBtn = event.target.closest('#rankingToggle');
        if (toggleBtn) {
            STATE.rankingExpanded = !STATE.rankingExpanded;
            renderContent();
            return;
        }
        // Профиль игрока
        const playerBtn = event.target.closest('.player-link');
        if (playerBtn) {
            openPlayerProfile(playerBtn.dataset.player);
            return;
        }
        // Кнопки «← К турнирам», «Весь рейтинг →», «Все новости →»
        const goBtn = event.target.closest('[data-go]');
        if (goBtn) {
            activateTab(goBtn.dataset.go);
            location.hash = goBtn.dataset.go === 'home' ? '' : '#' + goBtn.dataset.go;
            window.scrollTo({ top: 0, behavior: 'smooth' });
            return;
        }
    });
}

function setupProfileModal() {
    const modal = document.getElementById('profileModal');
    if (!modal) return;
    modal.addEventListener('click', (event) => {
        if (event.target.closest('[data-close-modal]') || event.target === modal) {
            closePlayerProfile();
        }
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') closePlayerProfile();
    });
}

function setupRefresh() {
    document.getElementById('refreshBtn').addEventListener('click', refreshData);
}

// Частота опроса подстраивается под реальную частоту обновления данных:
// файл меняется, когда отработает workflow, поэтому чаще 5 минут опрашивать
// бессмысленно, а при живых матчах — наоборот, нужно ждать быстрее.
function refreshInterval() {
    const all = Object.values(STATE.tournaments)
        .flatMap(t => Object.values(t.years || {}))
        .flatMap(y => Object.values(y))
        .flatMap(g => [...g.main, ...g.secondary]);
    const hasLive = all.some(m => m.status === 'live');
    if (hasLive) return ACTIVE_REFRESH_MS;
    if (STATE.index?.source && STATE.index.source !== 'sportradar') {
        return FALLBACK_REFRESH_MS;   // резервный источник обновляется раз в 12 часов
    }
    return DEFAULT_REFRESH_MS;
}

function setupAutoRefresh() {
    function tick() {
        refreshData().finally(() => {
            setTimeout(tick, refreshInterval());
        });
    }
    setTimeout(tick, DEFAULT_REFRESH_MS);
}

document.addEventListener('DOMContentLoaded', () => {
    setupTabs();
    setupFilters();
    setupRefresh();
    setupProfileModal();

    refreshData();

    setInterval(() => {
        updateCountdowns();
        updateLastUpdated(STATE.lastUpdated);
    }, 30000);

    setupAutoRefresh();
});
