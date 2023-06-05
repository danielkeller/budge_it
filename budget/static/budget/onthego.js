"use strict";

addEventListener("DOMContentLoaded", function () {
    const payees = Array.from(
        document.getElementById("payee-list").options)
        .map(option => [option.value, option.dataset.id]);
    const table = document.getElementById('table');
    const [amounttr, , currencytr] = table.rows;

    const currency = currencytr.children[1].children[0];
    const [hidden, visible] = amounttr.children[1].children;
    const update = () => {
        hidden.value = visible.value &&
            parseCurrency(visible.value, currency.value);
    };
    visible.addEventListener('input', update);
    currency.addEventListener('input', update);
});
