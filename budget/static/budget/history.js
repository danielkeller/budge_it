"use strict";

// Not 100% sure this is the same as the server
const dtf = new Intl.DateTimeFormat(navigator.language,
    { month: "short", year: "numeric", timeZone: "UTC" })

addEventListener("DOMContentLoaded", function () {
    window.data = JSON.parse(document.getElementById("data").textContent);
    window.form = document.getElementById("form");
    window.num_input = document.getElementById("id_form-TOTAL_FORMS");
    window.tbody = document.getElementById("table").children[0];
    window.rows = {};
    for (const tr of tbody.children) {
        const category = tr.dataset.category;
        if (!category) continue;
        var row = [];
        var cell = {};
        for (const td of tr.children) {
            const j = row.length;
            const input = td.children[0];
            if (input) {
                if (category === data.inbox) {
                    input.classList.add("suggested");
                    input.readOnly = true;
                } else {
                    input.addEventListener('input',
                        () => {
                            updateRow(category);
                            updateColumn(j);
                            updateRow(data.inbox);
                        })
                }
                cell.input = input;
            } else if (td.className === "spent") {
                cell.spent = +td.textContent;
            } else if (td.className === "total") {
                cell.total = td;
                row.push(cell);
                cell = {};
            }
        }
        window.rows[category] = row;
        updateRow(category);
    }

    document.getElementById('add-next').addEventListener('click', newColumn);
});

function updateColumn(j) {
    var sum = 0;
    var inbox;
    for (const row of Object.values(window.rows)) {
        const { input } = row[j];
        if (input.readOnly) {
            inbox = input;
        } else {
            sum += +input.value;
        }
    }
    inbox.value = isNaN(sum) || sum === 0 ? '' : -sum;
}

function updateRow(i) {
    var sum = 0;
    for (const { input, spent, total } of window.rows[i]) {
        if (!isNaN(input.value)) sum += +input.value;
        sum += spent;
        total.textContent = sum || "";
    }
}

function nextMonth(d) {
    d = new Date(d);
    let d1 = new Date(+d + 1000 * 60 * 60 * 24 * 31);
    d1.setUTCDate(1);
    return d1.toISOString().split('T')[0];
}

function newColumn() {
    const n = +num_input.value;
    num_input.value = n + 1;
    const date_input = document.createElement('input');
    date_input.type = "hidden";
    date_input.name = `form-${n}-date`;
    date_input.value = data.next_month;
    data.next_month = nextMonth(data.next_month);
    form.appendChild(date_input);

    const date_th = document.createElement("th");
    date_th.innerText = dtf.format(new Date(date_input.value));
    date_th.colSpan = 3;
    const date_row = tbody.children[0];
    date_row.insertBefore(date_th, date_row.children[date_row.children.length - 1]);
    const header_row = tbody.children[1];
    const spacer = header_row.children[header_row.children.length - 1];
    const budget_th = document.createElement("th");
    budget_th.innerText = "Budgeted";
    header_row.insertBefore(budget_th, spacer);
    const spent_th = document.createElement("th");
    spent_th.innerText = "Spent";
    header_row.insertBefore(spent_th, spacer);
    const total_th = document.createElement("th");
    total_th.innerText = "Total";
    header_row.insertBefore(total_th, spacer);

    for (const tr of tbody.children) {
        const category = tr.dataset.category;
        if (!category) continue;
        const j = rows[category].length;
        const budgeted = tr.children[tr.children.length - 3].cloneNode(true);
        const input = budgeted.children[0];
        const spent = tr.children[tr.children.length - 2].cloneNode(true);
        const total = tr.children[tr.children.length - 1].cloneNode(true);
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
        rows[category].push({ input, spent: 0, total });
        updateRow(category);
        tr.appendChild(budgeted);
        tr.appendChild(spent);
        tr.appendChild(total);
    }
}
