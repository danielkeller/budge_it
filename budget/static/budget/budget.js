"use strict";

// Not 100% sure this is the same as the server
const dtf = new Intl.DateTimeFormat(navigator.language,
    { month: "short", year: "numeric", timeZone: "UTC" })

class CurrencyInput {
    #currency; #amount; #input;
    constructor(currency, amount, input) {
        this.#currency = currency;
        this.#amount = amount;
        this.#input = input;
        this.#input.addEventListener('input', this.#parse.bind(this));
        this.value = this.#amount.value;
    }
    #parse() {
        this.#amount.value = this.#input.value
            && parseCurrency(this.#input.value, this.#currency);
    }
    get value() {
        return this.#amount.value;
    }
    set value(value) {
        this.#amount.value = value;
        this.#input.value = value === '' ? '' :
            formatCurrencyField(this.#amount.value, this.#currency);
    }
    get classList() {
        return this.#input.classList;
    }
    set readOnly(value) {
        return this.#input.readOnly = value;
    }
}

addEventListener("DOMContentLoaded", function () {
    formatCurrencies();
    window.data = JSON.parse(document.getElementById("data").textContent);
    window.tbody = document.getElementById("table").children[0];
    window.rows = {};
    tbody.addEventListener('input', update);
    document.forms.datepicker.addEventListener('change', updateDatePicker);

    for (const tr of tbody.children) {
        const category = tr.dataset.category;
        if (!category) continue;
        const currency = tr.dataset.categorycurrency;
        const [, , tdinput, , available] = tr.children;
        var row = {};
        row.currency = currency;
        row.input = new CurrencyInput(currency, ...tdinput.children);
        if (data.inboxes.includes(+category)) {
            row.input.classList.add("suggested");
            row.input.readOnly = true;
        }
        row.available = available;
        rows[category] = row;
    }
    update();
});

function updateDatePicker() {
    const year = document.forms.datepicker.year.value;
    for (const link of document.querySelectorAll(".months>a")) {
        const href = link.getAttribute('href').replace(/\d{4}/, year);
        if (href === window.location.pathname) {
            link.classList.add('current');
        } else {
            link.classList.remove('current');
        }
        link.setAttribute('href', href);
    }
}

function update() {
    var sums = {};
    for (const [category, row] of Object.entries(rows)) {
        if (sums[row.currency] === undefined)
            sums[row.currency] = 0;
        if (!data.inboxes.includes(+category))
            sums[row.currency] += +row.input.value;
    }
    for (const [category, row] of Object.entries(rows)) {
        if (data.inboxes.includes(+category))
            row.input.value = isFinite(sums[row.currency])
                ? -sums[row.currency] : '';

        const sum = +row.input.value + +row.available.dataset.value;
        row.available.innerText = isFinite(sum) ?
            formatCurrency(sum, row.currency) : '';
    }
}

