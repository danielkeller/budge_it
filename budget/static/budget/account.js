"use strict";

addEventListener("DOMContentLoaded", function () {
    window.data = JSON.parse(document.getElementById('data').textContent);
    document.addEventListener("keydown", key);
    window.listview = document.querySelector('.listview');
    listview.addEventListener('dblclick', edit);
    document.getElementById('new').addEventListener('click', create);
    listview.addEventListener('mousedown', mousedown);
    listview.addEventListener('keydown', listkey);

    const id = new URLSearchParams(window.location.search).get('t');
    if (id) {
        const listItem = document.querySelector(`.listview [data-id="${id}"]`);
        if (listItem) listItem.classList.add('checked');
        const item = document.querySelector(`.transaction-details [data-id="${id}"]`);
        if (item) item.classList.add('checked');
    }
});

htmx.onLoad(formatCurrencies);

function mousedown(event) {
    selectItem(findAncestor(event.target, el => el.dataset.id));
}

function prev() {
    const items = listview.querySelectorAll('[data-id]');
    const current = currentRow();
    if (current && current != items[0]) {
        selectItem(current.previousElementSibling);
    } else if (items.length >= 1) {
        selectItem(items[items.length - 1]);
    }
}
function next() {
    const items = listview.querySelectorAll('[data-id]');
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
    return listview.querySelector(".checked");
}

function selectItem(row) {
    if (!row) return;
    const prev = currentRow();
    if (prev) prev.classList.remove('checked');
    const id = row.dataset.id;
    row.classList.add('checked');
    history.replaceState({}, '', `?t=${id}`);
    const rowRect = row.children[0].getBoundingClientRect();
    const viewRect = listview.getBoundingClientRect();
    const headerRect = listview.querySelector('.th').getBoundingClientRect();
    const border = 1; // Not nice but w/e
    if (rowRect.top < headerRect.bottom) {
        listview.scrollTop += rowRect.top - headerRect.bottom - border;
    } else if (rowRect.bottom > viewRect.bottom) {
        listview.scrollTop += rowRect.bottom - viewRect.bottom + border;
    }

    const prev_item = document.querySelector('.transaction-details .checked');
    if (prev_item) prev_item.classList.remove('checked');
    const item = document.querySelector(`.transaction-details [data-id="${id}"]`);
    item.classList.add('checked');
}

function key(event) {
    if (document.activeElement.type === "text") return;
    if (event.key === "j") {
        next();
    } else if (event.key === "k") {
        prev();
    } else if (event.key === "g") {
        if (tbody.children.length >= 2) {
            selectItem(tbody.children[1]);
        }
    } else if (event.key === "Enter" || event.key === "i") {
        edit({ target: currentRow() });
    } else if (event.key === "o") {
        create();
    }
}

function edit(event) {
    if (event.target.tagName === 'INPUT') return; // Yikes
    const item = findAncestor(event.target, el => el.dataset.id);
    if (item) {
        const back = window.location.pathname;
        const id = item.dataset.id;
        window.location.href = `/transaction/${data.budget}/${id}/?back=${back}`;
    }
    event.preventDefault();
}

function create() {
    // TODO: This should auto fill the account
    const back = window.location.pathname;
    window.location.href =
        `/transaction/${data.budget}/?back=${back}`;
}
