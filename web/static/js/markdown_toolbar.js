/**
 * Lightweight Markdown insert helpers for announcement (and similar) textareas.
 * Supports wrap markers and line-prefix lists; Unicode emoji pass through as plain text.
 */

/**
 * @param {HTMLTextAreaElement} textarea
 * @param {string} before
 * @param {string} after
 */
export function wrapSelection(textarea, before, after = '') {
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const value = textarea.value;
    const selected = value.slice(start, end) || 'text';
    const next = value.slice(0, start) + before + selected + after + value.slice(end);
    textarea.value = next;
    const cursorStart = start + before.length;
    const cursorEnd = cursorStart + selected.length;
    textarea.focus();
    textarea.setSelectionRange(cursorStart, cursorEnd);
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
}

/**
 * Prefix each selected line (or the current line) with ``prefix``.
 * @param {HTMLTextAreaElement} textarea
 * @param {string} prefix  e.g. "- " or "1. "
 * @param {{ numbered?: boolean }} [opts]
 */
export function prefixSelectedLines(textarea, prefix, opts = {}) {
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const value = textarea.value;
    const lineStart = value.lastIndexOf('\n', Math.max(0, start - 1)) + 1;
    let lineEnd = value.indexOf('\n', end);
    if (lineEnd === -1) lineEnd = value.length;
    const block = value.slice(lineStart, lineEnd) || '';
    const lines = block.length ? block.split('\n') : [''];
    const numbered = Boolean(opts.numbered);
    const rewritten = lines.map((line, idx) => {
        const stripped = line.replace(/^\s*([-*+]|\d+\.)\s+/, '');
        if (numbered) return `${idx + 1}. ${stripped}`;
        return `${prefix}${stripped}`;
    }).join('\n');
    textarea.value = value.slice(0, lineStart) + rewritten + value.slice(lineEnd);
    textarea.focus();
    textarea.setSelectionRange(lineStart, lineStart + rewritten.length);
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
}

/**
 * Mount a Bootstrap btn-group toolbar above ``textarea``.
 * @param {HTMLTextAreaElement} textarea
 * @returns {HTMLElement | null}
 */
export function mountMarkdownToolbar(textarea) {
    if (!textarea || textarea.dataset.mdToolbarMounted === '1') return null;
    const wrap = document.createElement('div');
    wrap.className = 'btn-group btn-group-sm mb-2 announcement-md-toolbar';
    wrap.setAttribute('role', 'group');
    wrap.setAttribute('aria-label', 'Text formatting');

    /** @type {Array<{ title: string, label: string, action: () => void }>} */
    const buttons = [
        { title: 'Bold', label: '<strong>B</strong>', action: () => wrapSelection(textarea, '**', '**') },
        { title: 'Italic', label: '<em>I</em>', action: () => wrapSelection(textarea, '*', '*') },
        { title: 'Underline', label: '<u>U</u>', action: () => wrapSelection(textarea, '<u>', '</u>') },
        { title: 'Strikethrough', label: '<s>S</s>', action: () => wrapSelection(textarea, '~~', '~~') },
        { title: 'Bulleted list', label: '• List', action: () => prefixSelectedLines(textarea, '- ') },
        { title: 'Numbered list', label: '1. List', action: () => prefixSelectedLines(textarea, '1. ', { numbered: true }) },
    ];

    buttons.forEach((spec) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-outline-secondary';
        btn.title = spec.title;
        btn.setAttribute('aria-label', spec.title);
        btn.innerHTML = spec.label;
        btn.addEventListener('click', (ev) => {
            ev.preventDefault();
            spec.action();
        });
        wrap.appendChild(btn);
    });

    textarea.parentElement?.insertBefore(wrap, textarea);
    textarea.dataset.mdToolbarMounted = '1';
    return wrap;
}

/**
 * Shared Showdown options for announcement markdown (home + admin).
 * @returns {Record<string, boolean>}
 */
export function announcementShowdownOptions() {
    return {
        strikethrough: true,
        simplifiedAutoLink: true,
        excludeTrailingPunctuationFromURLs: true,
        openLinksInNewWindow: true,
        emoji: false, // keep Unicode emoji as-is; avoid :shortcode: surprises
        ghCodeBlocks: false,
        tables: false,
    };
}
