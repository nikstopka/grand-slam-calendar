// Grand Slam Calendar - Frontend Logic
// Data is fetched from data/matches.json (auto-updated by GitHub Actions)

const STATE = {
    matches: null,
    activeTab: 'main',
    statusFilter: 'all',
    genderFilter: 'all',
};

const FLAG_FALLBACK = '🏳️';

// Country code to emoji flag
function countryFlag(code) {
    if (!code || code.length !== 3 || code === 'Neutral') return FLAG_FALLBACK;
    try {
        const codes = code.toUpperCase().split('').map(c =>
            String.fromCodePoint(0x1F1E6 - 65 + c.charCodeAt(0))
        );
        return codes.join('');
    } catch {
        return FLAG_FALLBACK;
    }
}

// Format date in Russian
function formatDateRU(dateStr) {
    const d = new Date(dateStr);
    const months = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
    const day = d.getDate();
    const month = months[d.getMonth()];
    const hours = String(d.getHours()).padStart(2, '0');
    const mins = String(d.getMinutes()).padStart(2, '0');
    return `${day} ${month}, ${hours}:${mins}`;
}

function formatDateTimeRU(dateStr) {
    const d = new Date(dateStr);
    const days = ['воскресенье', 'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота'];
    const months = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
    const day = d.getDate();
    const month = months[d.getMonth()];
    const dayName = days[d.getDay()];
    const hours = String(d.getHours()).padStart(2, '0');
    const mins = String(d.getMinutes()).padStart(2, '0');
    return `${dayName}, ${day} ${month}, ${hours}:${mins}`;
}

// Calculate time until match
function timeUntilMatch(dateStr) {
    const now = new Date();
    const matchTime = new Date(dateStr);
    const diff = matchTime - now;

    if (diff <= 0) return null;

    const days = Math.floor(diff / (1000 * 60 * 60 * 24));
    const hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
    const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));

    return { days, hours, minutes, total: diff };
}

// Get match status info
function getStatusInfo(match) {
    const status = match.status;
    if (status === 'live') {
        return { class: 'live', text: 'LIVE', icon: '🔴' };
    }
    if (status === 'closed') {
        return { class: 'finished', text: 'Завершён', icon: '✅' };
    }
    // not_started
    return { class: 'upcoming', text: 'Предстоит', icon: '⏰' };
}

// Determine winner of a set
function isSetWinner(player, period, qualifier) {
    if (!period) return false;
    const isHome = qualifier === 'home';
    const homeScore = period.home;
    const awayScore = period.away;
    if (isHome) return homeScore > awayScore;
    return awayScore > homeScore;
}

// Render a single match card
function renderMatchCard(match) {
    const statusInfo = getStatusInfo(match);
    const players = match.players || [];
    const homePlayer = players.find(p => p.qualifier === 'home') || {};
    const awayPlayer = players.find(p => p.qualifier === 'away') || {};
    const scores = match.scores || {};
    const periods = scores.periods || [];
    const isFinished = match.status === 'closed';
    const isLive = match.status === 'live';
    const isUpcoming = match.status === 'not_started';

    // Determine winners
    const homeWon = isFinished && match.winner_id === homePlayer.id;
    const awayWon = isFinished && match.winner_id === awayPlayer.id;

    // Build score display for finished/live matches
    let scoreHTML = '';
    if (!isUpcoming && periods.length > 0) {
        scoreHTML = periods.map((period, i) => {
            const isCurrent = isLive && i === periods.length - 1;
            const homeWonSet = period.home > period.away;
            const awayWonSet = period.home < period.away;
            const homeTb = period.home_tb !== undefined ? ` <span class="tb">(${period.home_tb})</span>` : '';
            const awayTb = period.away_tb !== undefined ? ` <span class="tb">(${period.away_tb})</span>` : '';
            return `
                <div class="set-score ${isCurrent ? 'current' : ''} ${homeWonSet ? 'won' : ''}">
                    <span class="set-num">С${period.number}</span>
                    <span class="set-points">${period.home}${homeTb}</span>
                </div>
            `;
        }).join('');
    }

    // Activity widget
    let activityWidget = '';
    if (isUpcoming) {
        const countdown = timeUntilMatch(match.start_time);
        if (countdown) {
            let timerText = '';
            if (countdown.days > 0) timerText += `${countdown.days}д `;
            timerText += `${String(countdown.hours).padStart(2, '0')}:`;
            timerText += `${String(countdown.minutes).padStart(2, '0')}`;
            activityWidget = `
                <div class="countdown">
                    <div class="countdown-label">⏰ До начала матча</div>
                    <div class="countdown-timer" data-match-time="${match.start_time}">${timerText}</div>
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
                        <div class="activity-sub">Идёт ${periods.length} сет${periods.length === 1 ? '' : periods.length < 5 ? 'а' : 'ов'}</div>
                    </div>
                </div>
            </div>
        `;
    }

    // Venue info
    const venueText = match.venue ? `${match.venue}` : '';
    const cityText = match.city ? `${match.city}` : '';

    // Score summary for finished matches
    let scoreSummary = '';
    if (isFinished && scores.home !== undefined) {
        scoreSummary = `Счёт по сетам: ${scores.home} - ${scores.away}`;
    }

    return `
        <div class="match-card ${isLive ? 'live' : ''}" data-match-id="${match.id}">
            <div class="match-header">
                <div class="match-tournament">
                    <span>${match.tournament_short || match.tournament}</span>
                    <span class="gender-badge ${match.gender}">${match.category}</span>
                </div>
                <div class="match-round">${match.round_display || match.round}</div>
            </div>

            <div class="status-badge ${statusInfo.class}">
                <span class="dot"></span>
                ${statusInfo.text}
            </div>

            <div class="players" style="margin-top: 12px;">
                <div class="player ${homeWon ? 'winner' : ''}">
                    <div class="player-info">
                        <span class="player-flag">${countryFlag(homePlayer.country_code)}</span>
                        <span class="player-name">${homePlayer.name || 'TBD'}</span>
                        ${homePlayer.seed ? `<span class="player-seed">#${homePlayer.seed}</span>` : ''}
                        ${homeWon ? '<span class="winner-indicator">✓</span>' : ''}
                    </div>
                    <div class="score-display">
                        ${!isUpcoming && periods.length > 0 ? periods.map((p, i) => {
                            const won = p.home > p.away;
                            return `<div class="set-score ${won ? 'won' : ''}"><span class="set-num">С${p.number}</span><span class="set-points">${p.home}${p.home_tb !== undefined ? `(${p.home_tb})` : ''}</span></div>`;
                        }).join('') : ''}
                        ${isFinished && scores.home !== undefined ? `<div class="set-score won"><span class="set-num">Итог</span><span class="set-points">${scores.home}</span></div>` : ''}
                    </div>
                </div>

                <div class="player ${awayWon ? 'winner' : ''}">
                    <div class="player-info">
                        <span class="player-flag">${countryFlag(awayPlayer.country_code)}</span>
                        <span class="player-name">${awayPlayer.name || 'TBD'}</span>
                        ${awayPlayer.seed ? `<span class="player-seed">#${awayPlayer.seed}</span>` : ''}
                        ${awayWon ? '<span class="winner-indicator">✓</span>' : ''}
                    </div>
                    <div class="score-display">
                        ${!isUpcoming && periods.length > 0 ? periods.map((p, i) => {
                            const won = p.away > p.home;
                            return `<div class="set-score ${won ? 'won' : ''}"><span class="set-num">С${p.number}</span><span class="set-points">${p.away}${p.away_tb !== undefined ? `(${p.away_tb})` : ''}</span></div>`;
                        }).join('') : ''}
                        ${isFinished && scores.away !== undefined ? `<div class="set-score ${awayWon ? 'won' : ''}"><span class="set-num">Итог</span><span class="set-points">${scores.away}</span></div>` : ''}
                    </div>
                </div>
            </div>

            ${activityWidget}

            <div class="match-info">
                <div class="match-info-item">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                    ${formatDateTimeRU(match.start_time)}
                </div>
                ${venueText ? `<div class="match-info-item">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
                    ${venueText}
                </div>` : ''}
                ${match.best_of ? `<div class="match-info-item">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
                    Формат: best of ${match.best_of}
                </div>` : ''}
            </div>
        </div>
    `;
}

// Filter matches
function filterMatches(matches) {
    return matches.filter(m => {
        // Status filter
        if (STATE.statusFilter !== 'all') {
            if (STATE.statusFilter === 'upcoming' && m.status !== 'not_started') return false;
            if (STATE.statusFilter === 'live' && m.status !== 'live') return false;
            if (STATE.statusFilter === 'finished' && m.status !== 'closed') return false;
        }
        // Gender filter
        if (STATE.genderFilter !== 'all' && m.gender !== STATE.genderFilter) return false;
        return true;
    });
}

// Sort matches: upcoming first (by start time), then live, then finished (by start time descending)
function sortMatches(matches) {
    const statusOrder = { 'not_started': 0, 'live': 1, 'closed': 2 };
    return matches.sort((a, b) => {
        const sOrder = (statusOrder[a.status] ?? 3) - (statusOrder[b.status] ?? 3);
        if (sOrder !== 0) return sOrder;
        // Within same status, sort by start time
        return new Date(a.start_time) - new Date(b.start_time);
    });
}

// Render matches
function renderMatches() {
    if (!STATE.matches) return;

    const mainMatches = sortMatches(filterMatches(STATE.matches.main_matches || []));
    const secondaryMatches = sortMatches(filterMatches(STATE.matches.secondary_matches || []));

    const mainGrid = document.getElementById('mainMatchesGrid');
    const secondaryGrid = document.getElementById('secondaryMatchesGrid');

    mainGrid.innerHTML = mainMatches.length > 0
        ? mainMatches.map(renderMatchCard).join('')
        : '<p style="color: var(--text-muted); padding: 20px;">Нет матчей по выбранным фильтрам</p>';

    secondaryGrid.innerHTML = secondaryMatches.length > 0
        ? secondaryMatches.map(renderMatchCard).join('')
        : '<p style="color: var(--text-muted); padding: 20px;">Нет матчей по выбранным фильтрам</p>';

    // Update badges
    document.getElementById('mainBadge').textContent = mainMatches.length;
    document.getElementById('secondaryBadge').textContent = secondaryMatches.length;

    // Show/hide empty state
    const emptyState = document.getElementById('emptyState');
    const hasMatches = mainMatches.length > 0 || secondaryMatches.length > 0;
    emptyState.style.display = hasMatches ? 'none' : 'block';
    document.querySelector('.content').style.display = hasMatches ? 'block' : 'none';
}

// Update last updated timestamp
function updateLastUpdated(timestamp) {
    const el = document.getElementById('lastUpdated');
    if (!timestamp) {
        el.textContent = 'Время обновления неизвестно';
        return;
    }
    const d = new Date(timestamp);
    const now = new Date();
    const diffMin = Math.floor((now - d) / (1000 * 60));
    if (diffMin < 1) {
        el.textContent = 'Обновлено только что';
    } else if (diffMin < 60) {
        el.textContent = `Обновлено ${diffMin} мин назад`;
    } else {
        const hours = Math.floor(diffMin / 60);
        const mins = diffMin % 60;
        el.textContent = `Обновлено ${hours}ч ${mins}мин назад`;
    }
}

// Load matches data
async function loadMatches() {
    try {
        // Cache busting to always get fresh data
        const response = await fetch('data/matches.json?v=' + Date.now());
        if (!response.ok) throw new Error('HTTP ' + response.status);
        STATE.matches = await response.json();
        updateLastUpdated(STATE.matches.last_updated);
        renderMatches();
    } catch (err) {
        console.error('Failed to load matches:', err);
        document.getElementById('lastUpdated').textContent = 'Ошибка загрузки';
        // Show error state
        const mainGrid = document.getElementById('mainMatchesGrid');
        mainGrid.innerHTML = '<p style="color: var(--live); padding: 20px;">Ошибка загрузки данных. Попробуйте обновить страницу.</p>';
    }
}

// Update countdown timers
function updateCountdowns() {
    const timers = document.querySelectorAll('.countdown-timer');
    timers.forEach(el => {
        const matchTime = el.dataset.matchTime;
        const countdown = timeUntilMatch(matchTime);
        if (!countdown) {
            // Match has started - reload data to get updated status
            loadMatches();
            return;
        }
        let text = '';
        if (countdown.days > 0) text += `${countdown.days}д `;
        text += `${String(countdown.hours).padStart(2, '0')}:`;
        text += `${String(countdown.minutes).padStart(2, '0')}`;
        el.textContent = text;
    });
}

// Tab switching
function setupTabs() {
    const tabs = document.querySelectorAll('.tab');
    const sections = document.querySelectorAll('.matches-section');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const target = tab.dataset.tab;
            STATE.activeTab = target;

            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            sections.forEach(s => s.classList.remove('active'));
            document.getElementById(target + 'Matches').classList.add('active');
        });
    });
}

// Filter buttons
function setupFilters() {
    // Status filters
    document.querySelectorAll('[data-filter]').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('[data-filter]').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            STATE.statusFilter = btn.dataset.filter;
            renderMatches();
        });
    });

    // Gender filters
    document.querySelectorAll('[data-gender]').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('[data-gender]').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            STATE.genderFilter = btn.dataset.gender;
            renderMatches();
        });
    });
}

// Refresh button
function setupRefresh() {
    document.getElementById('refreshBtn').addEventListener('click', () => {
        loadMatches();
    });
}

// Auto-refresh: every 5 minutes if there are live matches, every 30 minutes otherwise
function setupAutoRefresh() {
    let refreshInterval = 30 * 60 * 1000; // 30 min default

    function checkAndRefresh() {
        if (STATE.matches) {
            const allMatches = [
                ...(STATE.matches.main_matches || []),
                ...(STATE.matches.secondary_matches || [])
            ];
            const hasLive = allMatches.some(m => m.status === 'live');
            const hasUpcoming = allMatches.some(m => m.status === 'not_started');
            refreshInterval = (hasLive || hasUpcoming) ? 5 * 60 * 1000 : 30 * 60 * 1000;
        }
        loadMatches();
        setTimeout(checkAndRefresh, refreshInterval);
    }

    setTimeout(checkAndRefresh, refreshInterval);
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    setupTabs();
    setupFilters();
    setupRefresh();
    loadMatches();

    // Update countdowns every minute
    setInterval(updateCountdowns, 60000);

    // Setup auto-refresh
    setupAutoRefresh();
});
