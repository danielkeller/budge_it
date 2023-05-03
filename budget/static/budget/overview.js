"use strict";

addEventListener("DOMContentLoaded", function () {
    let dragging = null;
    let findTarget;

    const table = document.getElementById('categories');

    table.addEventListener('dragstart', (event) => {
        event.dataTransfer.dropEffect = "move";
        dragging = findDraggable(event.target);
        findTarget = dragging.dataset.group ? findGroup : findCategory;
    });
    table.addEventListener('dragover', (event) => {
        const element = findTarget(event.target);
        if (element) {
            event.preventDefault();
            element.classList.add('droppable');
        }
    });
    table.addEventListener('dragleave', (event) => {
        const element = findTarget(event.target);
        if (element && element !== findTarget(event.relatedTarget)) {
            element.classList.remove('droppable');
        }
    });

    table.addEventListener('drop', (event) => {
        const element = findTarget(event.target);
        element.classList.remove('droppable');
        // console.log(event);
    });

    formatCurrencies();
});

function findAncestor(element, predicate) {
    for (; element && (!element.tagName || !(predicate(element)));
        element = element.parentElement);
    return element;
}
function findDraggable(element) {
    return findAncestor(element, element => element.getAttribute('draggable'));
}
function findGroup(element) {
    return findAncestor(element, element => element.dataset.group);
}
function findCategory(element) {
    return findAncestor(element, element => element.dataset.id);
}
