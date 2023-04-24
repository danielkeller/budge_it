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
        return parseCurrency(this.#input.value, this.#currency);
    }
    set value(value) {
        this.#amount.value = value;
        this.#input.value = value
            && formatCurrencyField(this.#amount.value, this.#currency);
    }
}

addEventListener("DOMContentLoaded", function () {
    formatCurrencies();
    window.data = JSON.parse(document.getElementById("data").textContent);
    window.form = document.getElementById("form");
    window.num_input = document.getElementById("id_form-TOTAL_FORMS");
    window.tbody = document.getElementById("table").children[0];
    window.rows = {};
    for (const tr of tbody.children) {
        const category = tr.dataset.category;
        if (!category) continue;
        const currency = data.currencies[category];
        var row = [];
        var cell = {};
        for (const td of tr.children) {
            const j = row.length;
            const [amount, input] = td.children;
            if (input) {
                if (data.inboxes.includes(category)) {
                    input.classList.add("suggested");
                    input.readOnly = true;
                } else {
                    input.addEventListener('input', () => edited(j, category));
                }
                cell.input = new CurrencyInput(currency, amount, input);
            } else if (td.classList.contains("spent")) {
                cell.spent = Decimal.parse(td.dataset.value);
            } else if (td.classList.contains("total")) {
                cell.total = td;
                row.push(cell);
                cell = {};
            }
        }
        window.rows[category] = row;
        updateRow(category);
    }

    document.getElementById('add-next').addEventListener('click', newColumnNext);
    document.getElementById('add-prev').addEventListener('click', newColumnPrev);
});

function edited(j, category) {
    updateRow(category);
    updateColumn(j);
    for (const inbox of data.inboxes)
        updateRow(inbox);
}

function updateColumn(j) {
    for (const inbox of data.inboxes) {
        const currency = data.currencies[inbox];
        var sum = 0;
        for (const [id, row] of Object.entries(rows)) {
            const { input } = row[j];
            if (data.currencies[id] === currency && id !== inbox) {
                sum += +input.value;
            }
        }
        rows[inbox][j].input.value = sum && isFinite(sum) ? -sum : '';
    }
}

function updateRow(i) {
    var sum = 0;
    for (const { input, spent, total } of rows[i]) {
        if (isFinite(+input.value))
            sum += +input.value;
        sum += spent;
        total.textContent = formatCurrency(sum, data.currencies[i]);
    }
}

function nextMonth(d) {
    d = new Date(d);
    let d1 = new Date(+d + 1000 * 60 * 60 * 24 * 31);
    d1.setUTCDate(1);
    return d1.toISOString().split('T')[0];
}

function prevMonth(d) {
    d = new Date(d);
    let d1 = new Date(+d - 1);
    d1.setUTCDate(1);
    return d1.toISOString().split('T')[0];
}

function newColumnNext() {
    const date = data.next_month;
    data.next_month = nextMonth(data.next_month);
    const datePosition = { before: tbody.children[0].lastElementChild };
    const headerPosition = { before: tbody.children[1].lastElementChild };
    const rowPosition = tr => ({ endOf: tr });
    const j = Object.values(rows)[0].length;
    newColumn(j, date, datePosition, headerPosition, rowPosition);
}

function newColumnPrev() {
    const date = data.prev_month;
    data.prev_month = prevMonth(data.prev_month);
    const datePosition = { before: tbody.children[0].children[1] };
    const headerPosition = { before: tbody.children[1].children[1] };
    const rowPosition = tr => ({ before: tr.children[1] });
    newColumn(0, date, datePosition, headerPosition, rowPosition);
}

function insertAt(element, { before, endOf }) {
    if (before)
        before.parentElement.insertBefore(element, before);
    else
        endOf.appendChild(element);
}

function newColumn(j, date, datePosition, headerPosition, rowPosition) {
    const n = +num_input.value;
    num_input.value = n + 1;
    const date_input = document.createElement('input');
    date_input.type = "hidden";
    date_input.name = `form-${n}-date`;
    date_input.value = date;
    form.appendChild(date_input);

    const date_th = document.createElement("th");
    date_th.innerText = dtf.format(new Date(date_input.value));
    date_th.colSpan = 3;
    insertAt(date_th, datePosition);

    const budget_th = document.createElement("th");
    budget_th.innerText = "Budgeted";
    insertAt(budget_th, headerPosition);
    const spent_th = document.createElement("th");
    spent_th.innerText = "Spent";
    insertAt(spent_th, headerPosition);
    const total_th = document.createElement("th");
    total_th.innerText = "Total";
    insertAt(total_th, headerPosition);

    for (const tr of tbody.children) {
        const category = tr.dataset.category;
        if (!category) continue;
        const budgeted = tr.children[1].cloneNode(true);
        const input = budgeted.children[0];
        const spent = tr.children[2].cloneNode(true);
        const total = tr.children[3].cloneNode(true);
        input.id = '';
        input.name = `form-${n}-${category}`
        input.value = '';
        if (category != data.inbox)
            input.addEventListener('input',
                () => {
                    updateRow(category);
                    updateColumn(j);
                    updateRow(data.inbox);
                });
        spent.innerText = '';
        rows[category].splice(j, 0, { input, spent: 0, total });
        updateRow(category);
        const position = rowPosition(tr)
        insertAt(budgeted, position);
        insertAt(spent, position);
        insertAt(total, position);
    }
}
