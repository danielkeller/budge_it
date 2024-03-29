"use strict";
// TODO: Calling a file 'util' is a bad idea.

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
    return Decimal.parse(value).toInt(currencyDecimals(currency));
}

function formatCurrencyField(value, currency) {
    return Decimal.fromParts(currencyDecimals(currency), value);
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
    const decimals = currencyDecimals(currency);
    const format = new Intl.NumberFormat(navigator.language,
        { maximumFractionDigits: decimals, minimumFractionDigits: decimals });
    return currency + " " + format.format(+value / 10 ** decimals);
}

function formatCurrencies(container) {
    container = container || document;
    const elements = container.dataset && container.dataset.currency
        ? [container]
        : container.querySelectorAll('[data-currency]');
    for (const element of elements) {
        if (element.classList.contains('shortcurrency'))
            element.textContent = element.textContent && formatCurrencyField(
                element.textContent, element.dataset.currency);
        else
            element.textContent = element.textContent && formatCurrency(
                element.textContent, element.dataset.currency);
        delete element.dataset['currency'];
    }
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

class EntryList extends HTMLElement {
    connectedCallback() {
        this.setAttribute('tabindex', 0);
        this.addEventListener('mousedown', ({ target }) => {
            if (target.tagName === "BUTTON" || target.tagName === "INPUT")
                return;
            const row = target.closest('[data-value]');
            if (row && this.checked !== row) this.select(row);
        });
        this.addEventListener('keydown', (event) => {
            if (event.key === 'ArrowUp') {
                this.prev();
                event.preventDefault();
            } else if (event.key === 'ArrowDown') {
                this.next();
                event.preventDefault();
            } else if (event.key === 'Home') {
                this.checked = null;
                this.next();
            } else if (event.key === 'End') {
                this.checked = null;
                this.prev();
            }
        });
        this.addEventListener('htmx:load', () => {
            // Content changed
            this.scrollIntoView();
        })
        // Wait for htmx to do its thing
        setTimeout(() => this.scrollIntoView(), 0);
    }
    get name() { return this.getAttribute('name'); }
    get checked() { return this.querySelector('.checked'); }
    set checked(row) {
        const prev = this.checked;
        if (prev) prev.classList.remove('checked');
        if (row) row.classList.add('checked');
        this.scrollIntoView();
    }
    get value() { return this.checked?.dataset.value; }
    set value(value) {
        this.checked = this.querySelector(`[data-value="${value}"]`);
    }
    select(row, source) {
        source = source || 'mouse';
        this.checked = row;
        (row || this).dispatchEvent(
            new CustomEvent(source + 'select', { bubbles: true }));
    }
    prev() {
        const items = Array.from(this.querySelectorAll('[data-value]'));
        const index = items.indexOf(this.checked);
        if (index !== -1 && index !== 0) {
            this.select(items[index - 1], 'kbd');
        } else if (items.length >= 1) {
            this.select(items[items.length - 1], 'kbd');
        }
    }
    next() {
        const items = Array.from(this.querySelectorAll('[data-value]'));
        const index = items.indexOf(this.checked);
        if (index !== -1 && index !== items.length - 1) {
            this.select(items[index + 1], 'kbd');
        } else if (items.length >= 1) {
            this.select(items[0], 'kbd');
        }
    }
    scrollIntoView() {
        if (!this.checked) return;
        const rowRect = this.checked.children[0].getBoundingClientRect();
        const viewRect = this.getBoundingClientRect();
        const sticky = this.querySelector('.sticky');
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
    /*class DummyRequest extends XMLHttpRequest {
        get status() { return 200; }
    }
    htmx.defineExtension('null-request', {
        onEvent: function (name, event) {
            if (name === 'htmx:beforeRequest') {
                event.preventDefault();
                let onload = event.detail.xhr.onload;
                event.detail.xhr = new DummyRequest();
                onload();
            }
        }
    });*/
})