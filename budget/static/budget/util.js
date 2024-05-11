"use strict";
// TODO: Calling a file 'util' is a bad idea.

function keyNotCaptured() {
    return ['INPUT', 'TEXTAREA', 'SELECT']
        .indexOf(document.activeElement.tagName) === -1;
}

function currencyDecimals(currency) {
    const currencyRe = /.*\.([0-9])|.*/;
    const forced = currency.match(currencyRe)[1];
    if (forced) return +forced;
    try {
        const format = new Intl.NumberFormat(navigator.language,
            { style: 'currency', currency });
        return format.resolvedOptions().maximumFractionDigits;
    } catch (invalid) {
        return 2;
    }
}

function parseCurrency(value, currency) {
    const places = currencyDecimals(currency);
    return parse(value, places).toInt(places);
}

function formatCurrencyField(value, currency) {
    const decimals = currencyDecimals(currency);
    const format = new Intl.NumberFormat(navigator.language,
        { maximumFractionDigits: decimals, minimumFractionDigits: decimals });
    return format.format(+value / 10 ** decimals);
}

function formatCurrency(value, currency) {
    if (currency && !isNaN(+value)) {
        try {
            const format = new Intl.NumberFormat(navigator.language,
                { style: 'currency', currency });
            const decimals = format.resolvedOptions().maximumFractionDigits;
            return format.format(+value / 10 ** decimals);
        } catch (invalidCurrency) { }
    }
    return currency + " " + formatCurrencyField(value, currency);
}

function findAncestor(element, predicate) {
    for (; element && (!element.tagName || !(predicate(element)));
        element = element.parentElement);
    return element;
}

function whenContentIsReady(element, callback) {
    if (element.children.length) callback();
    else setTimeout(callback, 0);
}

class ShortCurrency extends HTMLElement {
    connectedCallback() {
        const value = this.getAttribute('value');
        const currency = this.getAttribute('currency');
        this.textContent = value && this.formatter(value, currency);
    }
    get formatter() { return formatCurrencyField; }
    get value() { return this.getAttribute('value'); }
    set value(value) {
        this.setAttribute('value', value);
        const currency = this.getAttribute('currency');
        this.textContent = value && this.formatter(value, currency);
    }
}
class LongCurrency extends ShortCurrency {
    get formatter() { return formatCurrency; }
}
customElements.define('short-currency', ShortCurrency);
customElements.define('long-currency', LongCurrency);

function isBetween(node, a, b) {
    const p1 = ~node.compareDocumentPosition(a);
    const p2 = ~node.compareDocumentPosition(b);
    return p1 & 2 && p2 & 4 || p2 & 2 && p1 & 4;
}

class EntryList extends HTMLElement {
    #touching = false;
    connectedCallback() {
        this.setAttribute('tabindex', 0);
        this.addEventListener('touchstart', () => this.#touching = true);
        this.addEventListener('touchend', () => this.#touching = false);
        this.addEventListener('touchcancel', () => this.#touching = false);
        this.addEventListener('click', (event) => {
            if (event.target.tagName === 'A' && event.target.classList.contains('td')
                && event.button === 0) {
                event.preventDefault();
            }
        });
        this.addEventListener('mousedown', (event) => {
            const { target } = event;
            if (this.#touching || event.button !== 0)
                return;
            if (target.tagName === "BUTTON" || target.tagName === "INPUT")
                return;
            event.preventDefault(); // Don't focus the link.
            this.focus();
            const row = target.closest('[data-value]');
            if (row) {
                this.select(row, 'mouse', {
                    shift: event.shiftKey,
                    ctrl: event.ctrlKey || event.metaKey
                });
            }
        });
        this.addEventListener('keydown', (event) => {
            const modifiers = { shift: event.shiftKey };
            if (event.key === 'ArrowUp') {
                this.prev(modifiers);
                event.preventDefault();
            } else if (event.key === 'ArrowDown') {
                this.next(modifiers);
                event.preventDefault();
            } else if (event.key === 'Home') {
                const items = this.items;
                this.select(items[0], 'kbd', modifiers);
            } else if (event.key === 'End') {
                const items = this.items;
                this.select(items[items.length - 1], 'kbd', modifiers);
            } else if (event.key === 'a' && (event.ctrlKey || event.metaKey)) {
                event.preventDefault();
                const items = this.items;
                this.tail = items[0];
                this.select(items[items.length - 1], 'kbd', { shift: true });
            }
        });
        this.addEventListener('htmx:load', () => {
            // Content changed
            this.scrollIntoView();
        })
        // Wait for htmx to do its thing
        setTimeout(() => this.scrollIntoView(), 0);
    }
    uncheck() {
        for (const prev of this.querySelectorAll('.checked'))
            prev.classList.remove('checked');
    }
    select(row, source = 'mouse', { shift, ctrl } = {}) {
        const prev_value = this.value;
        if (ctrl) {
            row.classList.toggle('checked');
        } else if (shift) {
            for (let other of this.items) {
                if (isBetween(other, this.tail, this.active))
                    other.classList.remove('checked');
                if (isBetween(other, this.tail, row))
                    other.classList.add('checked');
            }
        } else {
            this.uncheck();
            row.classList.add('checked');
        }
        this.active = row;
        if (!shift) this.tail = row;
        if (prev_value.toString() !== this.value.toString()) {
            (row || this).dispatchEvent(
                new CustomEvent(source + 'select', { bubbles: true }));
        }
    }
    prev(modifiers = {}) {
        const items = this.items;
        const index = items.indexOf(this.active);
        if (index !== -1 && index !== 0) {
            this.select(items[index - 1], 'kbd', modifiers);
        } else if (items.length >= 1) {
            this.select(items[items.length - 1], 'kbd', modifiers);
        }
    }
    next(modifiers = {}) {
        const items = this.items;
        const index = items.indexOf(this.active);
        if (index !== -1 && index !== items.length - 1) {
            this.select(items[index + 1], 'kbd', modifiers);
        } else if (items.length >= 1) {
            this.select(items[0], 'kbd', modifiers);
        }
    }
    get items() { return Array.from(this.querySelectorAll('[data-value]')); }
    get active() { return this.querySelector('.active'); }
    set active(row) {
        for (const prev of this.querySelectorAll('.active'))
            prev.classList.remove('active');
        if (row) row.classList.add('active');
        this.scrollIntoView();
    }
    get tail() { return this.querySelector('.tail'); }
    set tail(row) {
        for (const prev of this.querySelectorAll('.tail'))
            prev.classList.remove('tail');
        if (row) row.classList.add('tail');
    }
    get name() { return this.getAttribute('name'); }
    get value() {
        let result = [];
        for (const row of this.querySelectorAll('.checked'))
            result.push(row.dataset.value);
        return result;
    }
    scrollIntoView() {
        if (!this.active) return;
        const rowRect = this.active.children[0].getBoundingClientRect();
        const viewRect = this.getBoundingClientRect();
        const sticky = this.querySelector('.th1');
        const border = 1; // Not nice but w/e
        const visibleTop = sticky ? sticky.getBoundingClientRect().bottom : viewRect.top;
        if (rowRect.top < visibleTop) {
            this.scrollTop += rowRect.top - visibleTop - border;
        } else if (rowRect.bottom > viewRect.bottom) {
            this.scrollTop += rowRect.bottom - viewRect.bottom + border;
        }
    }
}
customElements.define("entry-list", EntryList);

document.addEventListener('DOMContentLoaded', () => {
    htmx.defineExtension('event-header', {
        onEvent: function (name, evt) {
            if (name === "htmx:configRequest") {
                if (evt.detail.triggeringEvent) {
                    evt.detail.headers['HX-Event'] = evt.detail.triggeringEvent.type;
                }
            }
        }
    });
})