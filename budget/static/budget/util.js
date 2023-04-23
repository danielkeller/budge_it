"use strict";

function formatCurrency(value, currency) {
    const amount = typeof Decimal !== 'undefined' && value instanceof Decimal ?
        value.toFloat() : +value;
    if (currency && !isNaN(amount)) {
        try {
            const format = new Intl.NumberFormat(navigator.language,
                { style: 'currency', currency });
            return format.format(amount);
            return;
        } catch (invalidCurrency) { }
    }
    return currency + " " + value;
}

function formatCurrencies() {
    for (const element of document.querySelectorAll('[data-currency]')) {
        element.textContent = formatCurrency(
            element.textContent, element.dataset.currency);
    }
}
