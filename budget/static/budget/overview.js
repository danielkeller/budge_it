"use strict";

addEventListener("DOMContentLoaded", function () {
    let dragging = null;
    let findTarget;

    window.form = document.getElementById('form');
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
        if (dragging.dataset.group) {
            reorderGroup(dragging, element);
        } else {
            reorder(dragging, element);
        }
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
    return findAncestor(element, element => element.dataset.ind);
}

function reorder(source, target) {
    const source_ind = +source.dataset.ind;
    const target_ind = +target.dataset.ind;
    form.elements[`form-${source_ind}-group`].value =
        form.elements[`form-${target_ind}-group`].value;
    reorderImpl(new Set([source_ind]), target_ind);
}

function reorderGroup(source, target) {
    const source_inds = new Set([...source.children].slice(1)
        .map(tr => +tr.dataset.ind));
    const target_ind = +target.children[1].dataset.ind;
    reorderImpl(source_inds, target_ind);
}

function reorderImpl(source_inds, target_ind) {
    const num = +form.elements['form-TOTAL_FORMS'].value;
    let j = 0;
    for (let i = 0; i < num; ++i) {
        if (i === target_ind)
            for (let k of source_inds)
                form.elements[`form-${k}-order`].value = j++;
        if (!source_inds.has(i))
            form.elements[`form-${i}-order`].value = j++;
    }
    form.submit();
}
