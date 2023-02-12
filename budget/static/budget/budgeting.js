"use strict";

addEventListener("DOMContentLoaded", function () {
    const tbody = document.getElementById("parts").children[0];
    window.rows = [];
    for (const tr of Array.prototype.slice.call(tbody.children, 1)) {
        const td = tr.children[1];
        const input = td.children[0];
        if (td.dataset.inbox) {
            input.classList.add('suggested');
            input.disabled = true;
            window.inbox = input;
        } else {
            window.rows.push(input);
            input.addEventListener('input', fixInbox);
        }
    }
});

function fixInbox() {
    var total = 0;
    for (const row of window.rows) {
        total += +row.value;
    }
    if (!isNaN(total) && total !== 0) {
        window.inbox.value = -total;
    } else {
        window.inbox.value = "";
    }
}
