/**
 * reports.js — HF Report Viewer
 * Gallery, conversation replay, critique popup, raw markdown modal.
 */

// ─── Object emoji map ─────────────────────────────────────────────────────────
const RV_EMOJI = {
    apple: '🍎', banana: '🍌', orange: '🍊', grape: '🍇', strawberry: '🍓',
    mango: '🥭', watermelon: '🍉', peach: '🍑', pear: '🍐', lemon: '🍋',
    carrot: '🥕', potato: '🥔', tomato: '🍅', broccoli: '🥦', corn: '🌽',
    onion: '🧅', garlic: '🧄', pepper: '🫑', mushroom: '🍄', avocado: '🥑',
    dog: '🐶', cat: '🐱', bird: '🐦', fish: '🐟', rabbit: '🐰',
    lion: '🦁', elephant: '🐘', penguin: '🐧', bear: '🐻', fox: '🦊',
    car: '🚗', bus: '🚌', bike: '🚲', plane: '✈️', boat: '⛵',
    book: '📚', ball: '⚽', chair: '🪑', table: '🪑', pencil: '✏️',
    flower: '🌸', tree: '🌳', leaf: '🍃', sun: '☀️', moon: '🌙',
    house: '🏠', school: '🏫', clock: '⏰', phone: '📱', computer: '💻',
};

function rvEmoji(name) {
    return RV_EMOJI[(name || '').toLowerCase()] || '🔵';
}

function rvDate(dateStr) {
    if (!dateStr) return '';
    try {
        const d = new Date(dateStr.replace('T', ' '));
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
            + ' · ' + d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    } catch (_) { return dateStr; }
}

function rvEsc(str) {
    if (str == null) return '';
    return String(str)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// ─── Module state ─────────────────────────────────────────────────────────────
let _rvAllReports   = [];
let _rvCurrentDate  = '';
let _rvCurrentFile  = '';
let _rvCritiques    = {};   // exchangeIdx → critique object
let _rvTurnsByExchange = {}; // exchangeIdx → model turn
let _rvFilterText   = '';

// ─── Entry / Exit ─────────────────────────────────────────────────────────────

function openReportsViewer() {
    window.paixuejiUi.showReportsPage();
    _rvFilterText = '';
    loadReportGallery();
}

function closeReportsViewer() {
    closeRvCritiquePopup();
    closeRvRawModal();
    _rvCurrentDate = '';
    _rvCurrentFile = '';
    _rvCritiques   = {};
    _rvTurnsByExchange = {};
    window.paixuejiUi.leaveReportsPage();
}

// ─── Gallery ──────────────────────────────────────────────────────────────────

async function loadReportGallery() {
    const rv = document.getElementById('reportViewer');
    rv.innerHTML = '<div class="rv-loading">Loading reports…</div>';
    try {
        const resp = await fetch('/api/reports/hf');
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        _rvAllReports = await resp.json();
    } catch (e) {
        rv.innerHTML = `<div class="rv-error">Failed to load reports: ${rvEsc(e.message)}</div>`;
        return;
    }
    renderGallery();
}

function renderGallery() {
    const filtered = _rvAllReports.filter(r =>
        !_rvFilterText || (r.meta.object || '').toLowerCase().includes(_rvFilterText.toLowerCase())
    );
    const totalDates = new Set(_rvAllReports.map(r => r.date)).size;

    const cards = filtered.length === 0
        ? '<div class="rv-empty">No reports match your search.</div>'
        : filtered.map(r => {
            const m = r.meta;
            const critCount = m.exchanges_critiqued || 0;
            const total     = m.exchanges_total     || 0;
            const critClass = critCount === total && total > 0
                ? 'rv-chip-green' : critCount > 0 ? 'rv-chip-amber' : 'rv-chip-gray';
            return `
                <div class="rv-card"
                     onclick="loadReportDetail('${rvEsc(r.date)}','${rvEsc(r.filename)}')">
                    <div class="rv-card-top">
                        <span class="rv-card-emoji">${rvEmoji(m.object)}</span>
                        <span class="rv-card-name">${rvEsc(m.object)}</span>
                        <span class="rv-chip rv-chip-slate">HF</span>
                    </div>
                    <div class="rv-card-date">${rvEsc(rvDate(m.date))}</div>
                    <div class="rv-card-chips">
                        <span class="rv-chip rv-chip-slate">${m.age ? 'Age ' + rvEsc(String(m.age)) : 'Age —'}</span>
                        ${m.key_concept ? `<span class="rv-chip rv-chip-green">${rvEsc(m.key_concept)}</span>` : ''}
                        <span class="rv-chip ${critClass}">${critCount}/${total} ✎</span>
                    </div>
                </div>`;
        }).join('');

    document.getElementById('reportViewer').innerHTML = `
        <div class="rv-gallery">
            <div class="rv-gallery-header">
                <div>
                    <h2 class="rv-gallery-title">Human Feedback Reports</h2>
                    <p class="rv-gallery-sub">${_rvAllReports.length} reports · ${totalDates} dates</p>
                </div>
                <input type="text" class="rv-search" placeholder="Search by object…"
                       value="${rvEsc(_rvFilterText)}" oninput="rvOnFilter(this.value)" autofocus>
            </div>
            <div class="rv-cards">${cards}</div>
        </div>`;
}

function rvOnFilter(val) {
    _rvFilterText = val;
    renderGallery();
    // restore focus after innerHTML replacement
    const inp = document.querySelector('.rv-search');
    if (inp) { inp.focus(); inp.selectionStart = inp.selectionEnd = val.length; }
}

// ─── Detail View ──────────────────────────────────────────────────────────────

async function loadReportDetail(date, filename) {
    _rvCurrentDate = date;
    _rvCurrentFile = filename;
    const rv = document.getElementById('reportViewer');
    rv.innerHTML = '<div class="rv-loading">Loading report…</div>';
    let report;
    try {
        const resp = await fetch(
            `/api/reports/hf/${encodeURIComponent(date)}/${encodeURIComponent(filename)}`
        );
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        report = await resp.json();
    } catch (e) {
        rv.innerHTML = `<div class="rv-error">Failed to load: ${rvEsc(e.message)}</div>`;
        return;
    }
    renderDetail(report);
}

function renderDetail(report) {
    const m = report.meta || {};

    // Build critiques lookup for popup access
    _rvCritiques = {};
    _rvTurnsByExchange = {};
    for (const turn of report.transcript || []) {
        if (turn.role === 'model' && turn.exchange_index != null) {
            _rvTurnsByExchange[turn.exchange_index] = turn;
        }
        if (turn.critique && turn.exchange_index != null) {
            _rvCritiques[turn.exchange_index] = turn.critique;
        }
    }
    const hasCritique = Object.keys(_rvCritiques).length > 0;

    // Build conversation bubbles
    let lastPhase = null;
    const bubbles = (report.transcript || []).map(turn => {
        if (turn.role === 'child') {
            return `
                <div class="rv-msg rv-msg-child">
                    <div class="rv-bubble rv-bubble-child">${rvEsc(turn.text)}</div>
                </div>`;
        }
        if (turn.role === 'model') {
            let sep = '';
            if (turn.phase && turn.phase !== lastPhase) {
                sep = `<div class="rv-phase-sep">── ${rvEsc(turn.phase)} PHASE ──</div>`;
                lastPhase = turn.phase;
            }
            const hasBridgeDebug = !!(turn.critique && (
                turn.critique.bridge_verdict
                || (turn.critique.bridge_debug && Object.keys(turn.critique.bridge_debug).length)
            ));
            const isCrit   = !!(turn.critique &&
                (turn.critique.expected || turn.critique.problematic || turn.critique.conclusion || hasBridgeDebug));
            const critClass = isCrit ? ' rv-bubble-critiqued' : '';
            const critBadge = isCrit ? '<span class="rv-crit-badge">📝 Critique</span>' : '';
            const dataAttr  = isCrit ? ` data-exchange-idx="${turn.exchange_index}"` : '';
            const nodesLabel = (turn.nodes || []).length
                ? `[${turn.nodes.join(' → ')}] (${turn.time_ms}ms)` : '';
            return `
                ${sep}
                <div class="rv-msg rv-msg-model">
                    <div class="rv-bubble rv-bubble-model${critClass}"${dataAttr}>
                        ${critBadge}
                        <div class="rv-bubble-text">${rvEsc(turn.text)}</div>
                    </div>
                    ${nodesLabel
                        ? `<details class="rv-trace">
                               <summary class="rv-trace-sum">${rvEsc(nodesLabel)}</summary>
                           </details>`
                        : ''}
                </div>`;
        }
        return '';
    }).join('');

    const globalConc = report.global_conclusion
        ? `<div class="rv-global-conclusion">
               <div class="rv-gc-label">📋 Global Conclusion</div>
               <div class="rv-gc-text">${rvEsc(report.global_conclusion)}</div>
           </div>` : '';

    const hintBanner = hasCritique
        ? `<div class="rv-hint-banner" id="rvHintBanner">
               💡 Highlighted bubbles have critique notes — click to view
               <button class="rv-hint-dismiss"
                       onclick="document.getElementById('rvHintBanner').style.display='none'">✕</button>
           </div>` : '';

    document.getElementById('reportViewer').innerHTML = `
        <div class="rv-detail">
            <div class="rv-detail-header">
                <div class="rv-detail-title">
                    ${rvEmoji(m.object)}
                    <strong>${rvEsc(m.object)}</strong>
                    <span class="rv-detail-date-label">${rvEsc(rvDate(m.date))}</span>
                </div>
                <div class="rv-detail-actions">
                    ${m.age ? `<span class="rv-chip rv-chip-slate">Age ${rvEsc(String(m.age))}</span>` : ''}
                    ${m.key_concept ? `<span class="rv-chip rv-chip-green">${rvEsc(m.key_concept)}</span>` : ''}
                    <button class="rv-btn-secondary" onclick="renderGallery()">← All Reports</button>
                    <button class="rv-raw-btn"
                            onclick="showRvRawModal('${rvEsc(_rvCurrentDate)}','${rvEsc(_rvCurrentFile)}')">
                        { } Raw
                    </button>
                </div>
            </div>
            ${hintBanner}
            <div class="rv-conversation" id="rvConversation">
                ${bubbles}
                ${globalConc}
            </div>
        </div>`;

    // Event delegation — handles clicks on critiqued bubbles
    document.getElementById('rvConversation').addEventListener('click', function (e) {
        const bubble = e.target.closest('[data-exchange-idx]');
        if (bubble) showRvCritiquePopup(parseInt(bubble.dataset.exchangeIdx, 10));
    });
}

// ─── Critique Popup ───────────────────────────────────────────────────────────

function showRvCritiquePopup(exchangeIdx) {
    const crit = _rvCritiques[exchangeIdx];
    const turn = _rvTurnsByExchange[exchangeIdx];
    if (!crit) return;

    const isProblematic = crit.problematic
        && crit.problematic.toLowerCase() !== 'none'
        && crit.problematic.trim() !== '';

    document.getElementById('rvPopupTitle').textContent =
        `Exchange ${exchangeIdx} — ${crit.phase || 'CHAT'} Phase`;

    document.getElementById('rvPopupCritiquedResponse').textContent =
        turn && turn.text ? turn.text : '—';
    document.getElementById('rvPopupExpected').textContent = crit.expected || '—';

    const probPanel = document.getElementById('rvPopupProbPanel');
    const probIcon  = document.getElementById('rvPopupProbIcon');
    const probText  = document.getElementById('rvPopupProblematic');
    if (isProblematic) {
        probText.textContent  = crit.problematic;
        probPanel.className   = 'rv-crit-panel rv-panel-red';
        probIcon.textContent  = '⚠️';
    } else {
        probText.textContent  = 'No issues ✓';
        probPanel.className   = 'rv-crit-panel rv-panel-green';
        probIcon.textContent  = '✅';
    }

    document.getElementById('rvPopupConclusion').textContent = crit.conclusion || '—';
    const bridgeVerdictLabel = 'Bridge Verdict';
    document.getElementById('rvPopupBridgeVerdict').textContent = crit.bridge_verdict || '—';
    const bridgeDebugEl = document.getElementById('rvPopupBridgeDebug');
    const bridgeDebug = crit.bridge_debug || {};
    const bridgeLines = Object.keys(bridgeDebug).length
        ? Object.entries(bridgeDebug).map(([key, value]) => `${key}: ${value}`).join('\n')
        : '—';
    bridgeDebugEl.textContent = bridgeLines;

    const traceRows = (crit.node_trace || []).map(n =>
        `<tr>
            <td class="rv-trace-td">${rvEsc(n.node)}</td>
            <td class="rv-trace-td">${n.time_ms}ms</td>
            <td class="rv-trace-td">${rvEsc(String(n.state_changes ?? '—'))}</td>
         </tr>`
    ).join('') || '<tr><td class="rv-trace-td" colspan="3" style="color:#94a3b8">No trace data</td></tr>';
    document.getElementById('rvPopupTraceBody').innerHTML = traceRows;

    document.getElementById('rvCritiquePopup').style.display = 'flex';
}

function closeRvCritiquePopup() {
    document.getElementById('rvCritiquePopup').style.display = 'none';
}

// Close popup on backdrop click
document.addEventListener('click', function (e) {
    const popup = document.getElementById('rvCritiquePopup');
    if (popup && e.target === popup) closeRvCritiquePopup();
});

// ─── Raw Markdown Modal ───────────────────────────────────────────────────────

async function showRvRawModal(date, filename) {
    document.getElementById('rvRawFilename').textContent = filename;
    document.getElementById('rvRawContent').textContent  = 'Loading…';
    document.getElementById('rvRawModal').style.display  = 'flex';
    try {
        const resp = await fetch(
            `/api/reports/hf/${encodeURIComponent(date)}/${encodeURIComponent(filename)}/raw`
        );
        document.getElementById('rvRawContent').textContent = await resp.text();
    } catch (e) {
        document.getElementById('rvRawContent').textContent = 'Error: ' + e.message;
    }
}

function closeRvRawModal() {
    document.getElementById('rvRawModal').style.display = 'none';
}

function rvCopyRaw() {
    const text = document.getElementById('rvRawContent').textContent;
    navigator.clipboard.writeText(text).then(() => {
        const btn = document.getElementById('rvCopyBtn');
        const orig = btn.textContent;
        btn.textContent = '✓ Copied!';
        setTimeout(() => (btn.textContent = orig), 2000);
    }).catch(() => {});
}

// Close raw modal on backdrop click
document.addEventListener('click', function (e) {
    const modal = document.getElementById('rvRawModal');
    if (modal && e.target === modal) closeRvRawModal();
});
