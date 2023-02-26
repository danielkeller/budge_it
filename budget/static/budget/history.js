"use strict";

addEventListener("DOMContentLoaded", function () {
    const tbody = document.getElementById("table").children[0];
    window.rows = [];
    for (const tr of tbody.children) {
        const category = tr.dataset.category;
        if (!category) continue;
        const i = window.rows.length;
        var row = [];
        var cell = {};
        for (const td of tr.children) {
            const j = row.length;
            const input = td.children[0];
            if (input) {
                if (tr.dataset.inbox) {
                    input.classList.add("suggested");
                    input.readOnly = true;
                } else {
                    input.addEventListener('input',
                        () => { updateRow(i); updateColumn(j); updateRow(0); })
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
        window.rows.push(row);
        updateRow(i);
    }
});

function updateColumn(j) {
    var sum = 0;
    var inbox;
    for (const row of window.rows) {
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
