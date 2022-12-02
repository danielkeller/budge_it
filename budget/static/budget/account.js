"use strict";

addEventListener("DOMContentLoaded", function () {
    window.data = JSON.parse(document.getElementById('data').textContent);
    document.addEventListener("keydown", key);
    window.tbody = document.getElementById("table").children[0];
    document.addEventListener('focusin', updateHash);
    document.addEventListener('focusout', updateHash);
    tbody.addEventListener('dblclick', edit);

    const hash = document.location.hash;
    if (hash) document.querySelector(`[data-id="${hash.substring(1)}"]`)?.focus();
});

function key(event) {
    if (event.key === "j" || event.key === "ArrowDown") {
        const current = currentRow();
        if (current && current.nextElementSibling) {
            current.nextElementSibling.focus();
        } else if (tbody.children.length >= 2) {
            tbody.children[1].focus();
        }
    } else if (event.key === "k" || event.key === "ArrowUp") {
        const current = currentRow();
        if (current && current != tbody.children[1]) {
            current.previousElementSibling.focus();
        } else if (tbody.children.length >= 2) {
            tbody.children[tbody.children.length - 1].focus();
        }
    } else if (event.key === "Enter" || event.key === "i") {
        edit();
    }
}

function updateHash() {
    const current = currentRow();
    document.location.hash = current ? current.dataset.id : "";
}

function edit() {
    const current = currentRow();
    if (current) {
        const id = current.dataset.id;
        const back = encodeURIComponent(
            window.location.pathname + window.location.hash);
        window.location.href =
            `/transaction/${data.budget}/${id}/?back=${back}`;
    }
}

function currentRow() {
    return document.querySelector("tr:focus-within");
}
