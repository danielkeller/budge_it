"use strict";

function editItem(row) {
    location.href = `${row.dataset.url}?back=${location.pathname}`
}
