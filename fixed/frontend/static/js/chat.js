/**
 * Prescriptio Chat System
 * Real-time polling chat:
 *  - Loads previous messages on open
 *  - Polls every 3s for new messages
 *  - Online/offline presence
 *  - Delivery & read ticks
 *  - Auto-scroll, auto-resize textarea
 *  - Retry on send failure (no false "check your connection" errors)
 */

(function () {
    'use strict';

    // ── State ──────────────────────────────────────────
    let currentApptId  = null;
    let myId           = null;
    let otherOnline    = false;
    let lastMsgCount   = -1;
    const knownUnread = {};    // { apptId: count } — track per-appointment unread
    let pollTimer      = null;
    let pingTimer      = null;
    let isSending      = false;
    let retryQueue     = [];   // { text, attempts }
    let networkOk      = true;

    // ── DOM refs ───────────────────────────────────────
    const overlay      = document.getElementById('chatOverlay');
    const closeBtn     = document.getElementById('chatCloseBtn');
    const msgArea      = document.getElementById('chatMessages');
    const textarea     = document.getElementById('chatTextarea');
    const sendBtn      = document.getElementById('chatSendBtn');
    const headerName   = document.getElementById('chatHeaderName');
    const headerStatus = document.getElementById('chatHeaderStatus');
    const onlineDot    = document.getElementById('chatOnlineDot');
    const avatarLetter = document.getElementById('chatAvatarLetter');
    const apptBar      = document.getElementById('chatApptBar');

    if (!overlay) return;

    // ── Open Chat ──────────────────────────────────────
    window.openChat = function (apptId, otherName, apptDate, apptTime) {
        currentApptId = apptId;
        overlay.classList.add('open');
        document.body.style.overflow = 'hidden';

        if (headerName)   headerName.textContent = otherName;
        if (avatarLetter) avatarLetter.textContent = (otherName || '?').replace(/^Dr\.\s*/i,'').charAt(0).toUpperCase();
        if (apptBar)      apptBar.innerHTML =
            '<i class="fa-solid fa-calendar-check"></i> Appointment on <strong>' + apptDate + '</strong> at <strong>' + apptTime + '</strong>';

        msgArea.innerHTML =
            '<div class="chat-loading">' +
            '<div class="chat-spinner"></div>' +
            '<span>Loading conversation\u2026</span>' +
            '</div>';

        lastMsgCount = -1;
        textarea.value = '';
        autoResize();
        removeNetworkBanner();

        startPolling();
        startPing();
    };

    // ── Close Chat ─────────────────────────────────────
    function closeChat() {
        overlay.classList.remove('open');
        document.body.style.overflow = '';
        currentApptId = null;
        stopPolling();
        stopPing();
    }

    if (closeBtn) closeBtn.addEventListener('click', closeChat);
    overlay.addEventListener('click', e => { if (e.target === overlay) closeChat(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && currentApptId) closeChat(); });

    // ── Polling ────────────────────────────────────────
    function startPolling() { fetchMessages(); pollTimer = setInterval(fetchMessages, 3000); }
    function stopPolling()  { clearInterval(pollTimer); pollTimer = null; }

    // ── Presence ping ──────────────────────────────────
    function startPing() { sendPing(); pingTimer = setInterval(sendPing, 20000); }
    function stopPing()  { clearInterval(pingTimer); pingTimer = null; }
    function sendPing()  { fetch('/api/presence/ping', { method: 'POST', credentials: 'same-origin' }).catch(() => {}); }

    // ── Fetch Messages ─────────────────────────────────
    async function fetchMessages() {
        if (!currentApptId) return;
        try {
            const res = await fetch('/api/chat/' + currentApptId + '/messages', {
                credentials: 'same-origin',
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });

            if (res.redirected || res.url.includes('/login')) {
                showError('Session expired. Please <a href="/login" style="color:#2563eb">log in again</a>.');
                stopPolling();
                return;
            }

            const ct = res.headers.get('content-type') || '';
            if (!ct.includes('application/json')) { console.warn('Non-JSON from messages endpoint'); return; }

            const data = await res.json();
            if (res.status === 401 || data.login_required) {
                showError('Session expired. Please <a href="/login" style="color:#2563eb">log in again</a>.');
                stopPolling();
                return;
            }
            if (!res.ok) { showError(data.error || 'Error loading messages.'); return; }

            // Network is back
            if (!networkOk) { networkOk = true; removeNetworkBanner(); }

            myId        = data.my_id;
            otherOnline = data.other_online;

            updatePresenceUI(otherOnline);
            renderMessages(data.messages);

            // If chat is NOT open, check for unread messages and notify
            if (!currentApptId) {
                notifyUnreadMessages(data.messages);
            }

        } catch (err) {
            // Silent poll failure — don't spam the user, just show a quiet banner
            console.warn('Chat poll error:', err);
            if (networkOk) {
                networkOk = false;
                showNetworkBanner();
            }
        }
    }

    // ── Network banner (non-blocking) ──────────────────
    function showNetworkBanner() {
        if (document.getElementById('chatNetworkBanner')) return;
        const banner = document.createElement('div');
        banner.id = 'chatNetworkBanner';
        banner.style.cssText =
            'background:#fef3c7;color:#92400e;font-size:12px;padding:6px 14px;' +
            'text-align:center;border-bottom:1px solid #fde68a;';
        banner.innerHTML = '<i class="fa-solid fa-wifi" style="margin-right:5px;"></i>Reconnecting\u2026';
        msgArea.parentNode.insertBefore(banner, msgArea);
    }
    function removeNetworkBanner() {
        const b = document.getElementById('chatNetworkBanner');
        if (b) b.remove();
    }

    // ── Presence UI ────────────────────────────────────
    function updatePresenceUI(online) {
        if (onlineDot) onlineDot.classList.toggle('is-online', online);
        if (headerStatus) {
            const dot  = headerStatus.querySelector('.chat-header-status-dot');
            const text = headerStatus.querySelector('.chat-status-text');
            headerStatus.classList.toggle('online-status', online);
            if (dot)  dot.style.background = online ? '#10b981' : '#94a3b8';
            if (text) text.textContent      = online ? 'Online now' : 'Offline';
        }
    }

    // ── Render Messages ────────────────────────────────
    function renderMessages(messages) {
        if (messages.length === lastMsgCount && lastMsgCount !== -1) return;
        lastMsgCount = messages.length;

        if (messages.length === 0) {
            msgArea.innerHTML =
                '<div class="chat-empty">' +
                '<i class="fa-regular fa-comments"></i>' +
                '<p>No messages yet.<br>Start the conversation below.</p>' +
                '</div>';
            return;
        }

        const wasAtBottom = isScrolledToBottom();
        msgArea.innerHTML = '';

        let lastDate     = null;
        let lastSenderId = null;

        messages.forEach(msg => {
            const date = msg.created_at.split(' ')[0];
            if (date !== lastDate) {
                const div = document.createElement('div');
                div.className = 'chat-date-divider';
                div.innerHTML = '<span>' + formatDate(date) + '</span>';
                msgArea.appendChild(div);
                lastDate = date;
                lastSenderId = null;
            }

            const isMine     = msg.is_mine;
            const sameSender = msg.sender_id === lastSenderId;

            const row = document.createElement('div');
            row.className  = 'msg-row ' + (isMine ? 'mine' : 'theirs') + (sameSender ? ' same-sender' : '');
            row.dataset.msgId = msg.id;

            const initial = (msg.sender_name || '?').charAt(0).toUpperCase();
            const ticks   = isMine ? buildTicks(msg) : '';
            const receivedLabel = !isMine
                ? '<span class="msg-received-label" title="Received">' +
                  '<i class="fa-solid fa-check"></i> Received</span>'
                : '';

            row.innerHTML =
                '<div class="msg-mini-avatar">' + initial + '</div>' +
                '<div class="msg-bubble-wrap">' +
                '<div class="msg-bubble">' + escapeHtml(msg.message) + '</div>' +
                '<div class="msg-meta">' +
                '<span class="msg-time">' + formatTime(msg.created_at) + '</span>' +
                ticks +
                receivedLabel +
                '</div></div>';

            msgArea.appendChild(row);
            lastSenderId = msg.sender_id;
        });

        if (wasAtBottom || lastMsgCount === messages.length) scrollToBottom();
    }

    // ── Tick Logic ─────────────────────────────────────
    function buildTicks(msg) {
        if (msg.is_read) {
            // Double blue tick = read
            return '<span class="msg-ticks tick-double-read" title="Read">' +
                   '<i class="fa-solid fa-check"></i><i class="fa-solid fa-check"></i></span>';
        } else if (otherOnline) {
            // Double grey tick = delivered (online but not read yet)
            return '<span class="msg-ticks tick-double-grey" title="Delivered">' +
                   '<i class="fa-solid fa-check"></i><i class="fa-solid fa-check"></i></span>';
        } else {
            // Single grey tick = sent (doctor offline)
            return '<span class="msg-ticks tick-single" title="Sent">' +
                   '<i class="fa-solid fa-check"></i></span>';
        }
    }

    // ── Send Message ───────────────────────────────────
    async function sendMessage() {
        if (isSending || !currentApptId) return;
        const text = textarea.value.trim();
        if (!text) return;

        isSending = true;
        sendBtn.disabled = true;
        const savedText = textarea.value;
        textarea.value = '';
        autoResize();

        // Optimistic bubble
        const tempId  = 'temp-' + Date.now();
        const tempRow = document.createElement('div');
        tempRow.className    = 'msg-row mine';
        tempRow.id           = tempId;
        tempRow.style.opacity = '0.6';
        tempRow.innerHTML =
            '<div class="msg-mini-avatar">\u2026</div>' +
            '<div class="msg-bubble-wrap">' +
            '<div class="msg-bubble">' + escapeHtml(text) + '</div>' +
            '<div class="msg-meta"><span class="msg-time">Sending\u2026</span></div>' +
            '</div>';
        msgArea.appendChild(tempRow);
        scrollToBottom();

        try {
            const res = await fetch('/api/chat/' + currentApptId + '/send', {
                method:  'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify({ message: text }),
                credentials: 'same-origin'
            });

            // Remove optimistic bubble
            const t = document.getElementById(tempId);
            if (t) t.remove();

            if (res.redirected || res.url.includes('/login')) {
                showInlineError('Session expired. Please <a href="/login">log in again</a>.');
                textarea.value = savedText;
                autoResize();
                return;
            }

            const ct = res.headers.get('content-type') || '';
            let data = {};
            if (ct.includes('application/json')) {
                data = await res.json();
            } else {
                const body = await res.text();
                console.error('Non-JSON send response:', body.substring(0, 200));
                // Restore text and show soft error — don't say "check your connection"
                showInlineError('Server error. Please try again in a moment.');
                textarea.value = savedText;
                autoResize();
                return;
            }

            if (!res.ok) {
                if (res.status === 401 || data.login_required) {
                    showInlineError('Session expired. Please <a href="/login">log in again</a>.');
                } else {
                    showInlineError(data.error || 'Message could not be sent. Please try again.');
                }
                textarea.value = savedText;
                autoResize();
                return;
            }

            // Success — force re-render
            lastMsgCount = -1;
            await fetchMessages();

        } catch (err) {
            // True network failure — restore text silently, show retry option
            console.warn('Send network error:', err);
            const t = document.getElementById(tempId);
            if (t) t.remove();
            textarea.value = savedText;
            autoResize();
            showInlineError('Message not sent \u2014 tap send again to retry.');
        } finally {
            isSending = false;
            sendBtn.disabled = false;
            textarea.focus();
        }
    }

    // ── Inline error (auto-removes after 5s) ──────────
    function showInlineError(htmlMsg) {
        // Remove any existing inline error first
        document.querySelectorAll('.chat-inline-error').forEach(el => el.remove());

        const div = document.createElement('div');
        div.className = 'chat-inline-error';
        div.style.cssText =
            'background:#fee2e2;color:#991b1b;font-size:13px;padding:8px 14px;' +
            'border-radius:8px;margin:6px 12px;text-align:center;';
        div.innerHTML = '<i class="fa-solid fa-circle-exclamation"></i> ' + htmlMsg;
        msgArea.appendChild(div);
        scrollToBottom();
        setTimeout(() => div.remove(), 6000);
    }

    if (sendBtn)  sendBtn.addEventListener('click', sendMessage);
    if (textarea) {
        textarea.addEventListener('keydown', e => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
        });
        textarea.addEventListener('input', autoResize);
    }

    // ── Helpers ────────────────────────────────────────
    function autoResize() {
        if (!textarea) return;
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
    }

    function scrollToBottom() { if (msgArea) msgArea.scrollTop = msgArea.scrollHeight; }

    function isScrolledToBottom() {
        if (!msgArea) return true;
        return msgArea.scrollHeight - msgArea.scrollTop - msgArea.clientHeight < 80;
    }

    function formatDate(dateStr) {
        const d    = new Date(dateStr + 'T00:00:00');
        const now  = new Date();
        const diff = Math.floor((now - d) / 86400000);
        if (diff === 0) return 'Today';
        if (diff === 1) return 'Yesterday';
        return d.toLocaleDateString('en-KE', { day: 'numeric', month: 'short', year: 'numeric' });
    }

    function formatTime(ts) {
        return new Date(ts).toLocaleTimeString('en-KE', { hour: '2-digit', minute: '2-digit', hour12: true });
    }

    function escapeHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/\n/g, '<br>');
    }

    function showError(msg) {
        if (msgArea) msgArea.innerHTML =
            '<div class="chat-empty">' +
            '<i class="fa-solid fa-triangle-exclamation" style="color:#ef4444"></i>' +
            '<p>' + msg + '</p></div>';
    }

    // ── Global ping on page load ───────────────────────
    // ── Global presence ping (page-level) ────────────────
    // Ping while the tab is active; pause when hidden so users go properly offline
    let _globalPingTimer = null;
    function startGlobalPing() {
        if (_globalPingTimer) return;
        sendPing();
        _globalPingTimer = setInterval(sendPing, 20000);
    }
    function stopGlobalPing() {
        clearInterval(_globalPingTimer);
        _globalPingTimer = null;
    }
    startGlobalPing();
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) stopGlobalPing();
        else startGlobalPing();
    });

    // Mark offline immediately when tab is closed
    window.addEventListener('beforeunload', () => {
        stopGlobalPing();
        // Use sendBeacon so the request fires even as the page unloads
        if (navigator.sendBeacon) {
            navigator.sendBeacon('/api/presence/offline');
        }
    });

    // ── Background unread polling (when no chat is open) ──
    // Polls all accepted appointments for new messages every 5s
    setInterval(pollUnreadInBackground, 5000);

    function pollUnreadInBackground() {
        if (currentApptId) return;
        const chatBtns = document.querySelectorAll('button.btn-chat[onclick]');
        chatBtns.forEach(btn => {
            const match = btn.getAttribute('onclick').match(/openChat\((\d+)/);
            if (!match) return;
            const apptId = match[1];
            fetch('/api/chat/' + apptId + '/messages', {
                credentials: 'same-origin',
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            })
            .then(r => r.ok ? r.json() : null)
            .then(data => {
                if (!data || !data.messages) return;
                notifyUnreadMessages(apptId, data.messages);
            })
            .catch(() => {});
        });
    }

    // ── Per-appointment unread notification logic ───────────────────────────
    function notifyUnreadMessages(apptId, messages) {
        const unread    = messages.filter(m => !m.is_mine && !m.is_read).length;
        const prevCount = (knownUnread[apptId] !== undefined) ? knownUnread[apptId] : -1;

        knownUnread[apptId] = unread;
        const totalUnread = Object.values(knownUnread).reduce((a, b) => a + b, 0);
        updateChatBadge(totalUnread);

        // First load: just record baseline silently, no alert
        if (prevCount === -1) return;
        // No new messages
        if (unread <= prevCount) return;

        // New messages arrived — fire all alerts
        const newMsgs = messages.filter(m => !m.is_mine && !m.is_read);
        const latest  = newMsgs[newMsgs.length - 1];
        const sender  = latest ? latest.sender_name : 'Someone';
        const preview = latest ? latest.message    : '';

        triggerBrowserNotification(sender, preview);
        showDashboardToast(sender, preview, apptId);
        flashPageTitle('\u{1F4AC} New message from ' + sender);
        playNotificationSound();
    }

    // ── Page title flasher ─────────────────────────────
    let _titleFlashInterval = null;
    let _originalTitle      = document.title;
    function flashPageTitle(alertText) {
        if (_titleFlashInterval) return; // already flashing
        let toggle = false;
        _titleFlashInterval = setInterval(() => {
            document.title = toggle ? _originalTitle : alertText;
            toggle = !toggle;
        }, 1200);
        // Stop after 12s or when tab gains focus
        const stop = () => {
            clearInterval(_titleFlashInterval);
            _titleFlashInterval = null;
            document.title = _originalTitle;
            window.removeEventListener('focus', stop);
        };
        setTimeout(stop, 12000);
        window.addEventListener('focus', stop);
    }

    // ── Browser notification ───────────────────────────
    function triggerBrowserNotification(sender, preview) {
        if (!('Notification' in window)) return;
        if (Notification.permission === 'granted') {
            new Notification('New message from ' + sender, {
                body: preview ? preview.substring(0, 100) : '',
                icon: '/static/favicon.ico'
            });
        } else if (Notification.permission === 'default') {
            Notification.requestPermission();
        }
    }

    // ── Subtle notification sound ──────────────────────
    function playNotificationSound() {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.type = 'sine';
            osc.frequency.setValueAtTime(880, ctx.currentTime);
            osc.frequency.exponentialRampToValueAtTime(660, ctx.currentTime + 0.15);
            gain.gain.setValueAtTime(0.15, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
            osc.start(ctx.currentTime);
            osc.stop(ctx.currentTime + 0.4);
        } catch (e) { /* audio not available */ }
    }

    function updateChatBadge(count) {
        // Works for both patient and doctor dashboards
        const badge = document.getElementById('patientChatBadge') ||
                      document.getElementById('doctorChatBadge');
        if (!badge) return;
        if (count > 0) {
            badge.textContent = count > 9 ? '9+' : count;
            badge.style.cssText =
                'display:inline-flex;align-items:center;justify-content:center;' +
                'background:#ef4444;color:#fff;border-radius:50%;' +
                'width:18px;height:18px;font-size:11px;font-weight:700;' +
                'margin-left:6px;animation:badgePop .2s ease;';
        } else {
            badge.textContent = '';
            badge.style.display = 'none';
        }
    }

    // ── WhatsApp-style notification toast ─────────────────────────────
    function showDashboardToast(sender, preview, apptId) {
        let container = document.getElementById('msgToastContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'msgToastContainer';
            container.style.cssText =
                'position:fixed;bottom:24px;right:24px;z-index:99999;' +
                'display:flex;flex-direction:column;gap:10px;pointer-events:none;' +
                'max-width:340px;';
            document.body.appendChild(container);
        }

        // Avoid duplicate toasts for the same appointment
        const existing = document.getElementById('msg-toast-' + apptId);
        if (existing) existing.remove();

        const initial = (sender || '?').replace(/^Dr\.\s*/i,'').charAt(0).toUpperCase();
        const shortPreview = preview ? (preview.length > 60 ? preview.substring(0,60)+'\u2026' : preview) : '';

        const toast = document.createElement('div');
        toast.id = 'msg-toast-' + apptId;
        toast.style.cssText =
            'background:#fff;border-radius:14px;padding:0;' +
            'box-shadow:0 4px 24px rgba(0,0,0,.18);pointer-events:auto;cursor:pointer;' +
            'opacity:0;transform:translateY(16px);' +
            'transition:opacity .22s ease,transform .22s ease;overflow:hidden;width:320px;';

        toast.innerHTML =
            // Green header bar like WhatsApp
            '<div style="background:#25d366;padding:8px 14px;display:flex;align-items:center;gap:8px;">' +
            '  <span style="font-size:13px;">\uD83D\uDCAC</span>' +
            '  <span style="color:#fff;font-size:12px;font-weight:700;letter-spacing:.3px;">NEW MESSAGE</span>' +
            '  <span style="margin-left:auto;color:rgba(255,255,255,.8);font-size:11px;">MediCare</span>' +
            '</div>' +
            // Body
            '<div style="padding:12px 14px;display:flex;align-items:center;gap:12px;">' +
            '  <div style="width:42px;height:42px;border-radius:50%;background:#25d366;' +
            '    display:flex;align-items:center;justify-content:center;' +
            '    color:#fff;font-size:18px;font-weight:700;flex-shrink:0;">' + initial + '</div>' +
            '  <div style="flex:1;min-width:0;">' +
            '    <div style="font-size:14px;font-weight:700;color:#111;margin-bottom:2px;' +
            '      white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' + escapeHtml(sender) + '</div>' +
            '    <div style="font-size:13px;color:#555;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">' +
            (shortPreview ? escapeHtml(shortPreview) : '<em style="color:#999;">Tap to open</em>') +
            '    </div>' +
            '  </div>' +
            '</div>' +
            // Action row
            '<div style="border-top:1px solid #f0f0f0;display:flex;">' +
            '  <button style="flex:1;padding:10px;background:none;border:none;' +
            '    color:#25d366;font-size:13px;font-weight:600;cursor:pointer;"' +
            '    onclick="(function(){' +
            '      document.getElementById(\'msg-toast-' + apptId + '\').remove();' +
            '      var nav=document.querySelector(\'.nav-item[data-section=\"chats\"]\');' +
            '      if(nav)nav.click();' +
            '    })()">' +
            '    Open Chat' +
            '  </button>' +
            '  <button style="flex:1;padding:10px;background:none;border:none;border-left:1px solid #f0f0f0;' +
            '    color:#999;font-size:13px;cursor:pointer;"' +
            '    onclick="document.getElementById(\'msg-toast-' + apptId + '\').remove()">' +
            '    Dismiss' +
            '  </button>' +
            '</div>';

        // Click body to open chat
        toast.querySelector('div:nth-child(2)').addEventListener('click', () => {
            toast.remove();
            const nav = document.querySelector('.nav-item[data-section="chats"]');
            if (nav) nav.click();
        });

        container.appendChild(toast);
        requestAnimationFrame(() => requestAnimationFrame(() => {
            toast.style.opacity = '1';
            toast.style.transform = 'translateY(0)';
        }));
        // Auto-dismiss after 12s
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(16px)';
            setTimeout(() => { if (toast.parentNode) toast.remove(); }, 300);
        }, 12000);
    }
    // Clear badge + per-appointment count when chat is opened
    const _origOpenChat = window.openChat;
    window.openChat = function(apptId, otherName, apptDate, apptTime) {
        // Mark this appointment as read locally
        if (apptId) knownUnread[apptId] = 0;
        // Remove its toast if showing
        const t = document.getElementById('msg-toast-' + apptId);
        if (t) t.remove();
        // Recalculate total badge
        const total = Object.values(knownUnread).reduce((a,b) => a+b, 0);
        updateChatBadge(total);
        _origOpenChat(apptId, otherName, apptDate, apptTime);
    };

})();
