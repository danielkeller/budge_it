"use strict";

function selectFromUrl() {
    const id = new URLSearchParams(window.location.search).get('t');
    document.querySelector('list-view').value = id;
}

function editItem(row) {
    location.href = `${row.dataset.url}?back=${location.pathname}`
}
