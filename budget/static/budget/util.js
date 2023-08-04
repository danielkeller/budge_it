"use strict";

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
    }
}

function findAncestor(element, predicate) {
    for (; element && (!element.tagName || !(predicate(element)));
        element = element.parentElement);
    return element;
}
