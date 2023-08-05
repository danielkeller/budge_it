"use strict";

addEventListener("DOMContentLoaded", function () {
    window.data = JSON.parse(document.getElementById('data').textContent);
    formatCurrencies();
    selectFromUrl();
});

function selectFromUrl() {
    const id = new URLSearchParams(window.location.search).get('t');
    if (id) {
        const listItem = document.querySelector(`.listview [data-id="${id}"]`);
        if (listItem) selectItem(listItem);
    }
}

function prev() {
    const items = document.querySelectorAll('.listview [data-id]');
    const current = currentRow();
    if (current && current != items[0]) {
        selectItem(current.previousElementSibling);
    } else if (items.length >= 1) {
        selectItem(items[items.length - 1]);
    }
}
function next() {
    const items = document.querySelectorAll('.listview [data-id]');
    const current = currentRow();
    if (current && current.nextElementSibling) {
        selectItem(current.nextElementSibling);
    } else if (items.length >= 1) {
        selectItem(items[0]);
    }

}

function listkey(event) {
    if (event.key === "ArrowUp") {
        prev();
        event.preventDefault();
    } else if (event.key === "ArrowDown") {
        next();
        event.preventDefault();
    }
}

function currentRow() {
    return document.querySelector(".listview .checked");
}

function selectItem(row) {
    const prev = currentRow();
    if (prev) prev.classList.remove('checked');

    const prev_item = document.querySelector('.transaction-details .checked');
    if (prev_item) prev_item.classList.remove('checked');

    if (!row) return;

    const id = row.dataset.id;
    row.classList.add('checked');
    history.replaceState({}, '', `?t=${id}`);

    const listview = document.querySelector('.listview');
    const rowRect = row.children[0].getBoundingClientRect();
    const viewRect = listview.getBoundingClientRect();
    const headerRect = listview.querySelector('.th').getBoundingClientRect();
    const border = 1; // Not nice but w/e
    if (rowRect.top < headerRect.bottom) {
        listview.scrollTop += rowRect.top - headerRect.bottom - border;
    } else if (rowRect.bottom > viewRect.bottom) {
        listview.scrollTop += rowRect.bottom - viewRect.bottom + border;
    }

    const item = document.querySelector(`.transaction-details [data-id="${id}"]`);
    item.classList.add('checked');
}

function editItem(row) {
    location.href = `${row.dataset.url}?back=${location.pathname}`
}

function key(event) {
    if (['INPUT', 'BUTTON'].includes(document.activeElement.tagName)) return;
    if (event.key === "j") {
        next();
    } else if (event.key === "k") {
        prev();
    } else if (event.key === "g") {
        selectItem(null);
        next();
    } else if (event.key === "Enter" || event.key === "i") {
        const row = currentRow();
        if (row) editItem(row);
    } else if (event.key === "o") {
        create();
    }
}

function create() {
    // TODO: This should auto fill the account
    const back = window.location.pathname;
    window.location.href =
        `/transaction/${data.budget}/?back=${back}`;
}
