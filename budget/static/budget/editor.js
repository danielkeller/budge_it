"use strict";

addEventListener("DOMContentLoaded", function () {
    window.data = JSON.parse(document.getElementById('data').textContent);
    window.valid = true;
    window.rows = [];
    window.tbody = document.getElementById("parts").children[0];
    window.adder_row = document.getElementById("adder-row");
    window.category_sum = document.getElementById("category-sum");
    window.account_sum = document.getElementById("account-sum");
    window.debt = document.getElementById("debt");
    window.account_options = Array.from(
        document.getElementById("account-list").options)
        .map(option => [option.value, option.dataset.id]);
    window.category_options = Array.from(
        document.getElementById("category-list").options)
        .map(option => [option.value, option.dataset.id]);

    document.getElementById('addrow').addEventListener('click', addRow);
    document.getElementById('cancel').addEventListener('click', cancel);
    document.forms[0].addEventListener('submit', onSubmit);
    document.addEventListener("keydown", key);
    setUpRows();
    checkValid();
});

function key(event) {
    if (event.key === "Escape") {
        // The default behavior of "esc" is to stop page load
        // event.preventDefault();
        // cancel();
    } else if (event.key === "Enter") {
        if (document.activeElement.type !== "button"
            && document.activeElement.type !== "submit")
            if (valid) document.forms[0].submit();
    }
}

function cancel() {
    const back = new URLSearchParams(window.location.search).get('back');
    if (back)
        window.location.href = back;
    else
        history.back();
}

function findRow(input) {
    return rows.findIndex(
        ({ account, category, moved, transferred }) =>
            [account, category, moved, transferred].includes(input));
}

function ownAccount(value) {
    return value == data.budget
        || value in data.accounts || value in data.categories;
}

class Selector {
    #visible; #hidden; #sigil; #options; #oninput;
    constructor([hidden, sigil, visible], options, oninput) {
        this.#visible = visible;
        this.#sigil = sigil;
        this.#hidden = hidden;
        this.#options = options;
        this.#oninput = oninput;
        visible.addEventListener('input', this.#selectInput.bind(this));
        this.value = this.value;
    }
    set value(value) {
        value = String(value);
        this.#hidden.value = value;
        const option = this.#options.find(([_, optvalue]) => optvalue === value);
        this.#visible.value = option ? option[0] : value;
    }
    get value() { return this.#hidden.value; }
    set name(name) { this.#hidden.name = name; }
    unsuggest() {
        if (this.classList.contains('suggested')) {
            this.value = '';
            this.classList.remove('suggested');
        }
    }
    suggest(value) {
        if (this.value === "" && document.activeElement !== this.#visible) {
            this.value = value;
            this.classList.add('suggested');
            return true;
        }
        return false;
    }
    accept() {
        this.classList.remove('suggested');
    }
    set sigil(value) {
        if (value) {
            this.#sigil.classList.add('sigil');
            this.#sigil.textContent = '👤';
        } else {
            this.#sigil.classList.remove('sigil');
            this.#sigil.textContent = '';
        }
    }
    get classList() { return this.#visible.classList; }
    focus(args) { this.#visible.focus(args); }
    #selectInput() {
        const option = this.#options.find(([name, _]) => name === this.#visible.value);
        this.#hidden.value = option ? option[1] : this.#visible.value;
        this.#oninput({ target: this })
    }
}

class CurrencyInput {
    #currency; #amount; #span; #input; #currencyFixed;
    #currencySuggested; #amountSuggested;
    constructor([currency, amount, span, input], currencyFixed) {
        this.#currency = currency;
        this.#amount = amount;
        this.#currencySuggested = false;
        this.#amountSuggested = false;
        this.#span = span;
        this.#input = input;
        this.#currencyFixed = currencyFixed;
        this.#refresh();
        this.#input.addEventListener('input', this.#parse.bind(this));
    }
    #refresh() {
        const value = this.#amount.value
            ? formatCurrencyField(this.#amount.value, this.#currency.value)
            : "";
        if (this.#currencyFixed) {
            this.#span.innerText = this.#currency.value;
            this.#span.className = "suggested currency";
            this.#input.value = value;
        } else {
            this.#span.innerText = "";
            this.#span.className = "";
            this.#input.value = this.#currency.value + " " + value;
        }
        if (this.#amountSuggested || this.#currencySuggested) {
            this.classList.add('suggested');
        } else {
            this.classList.remove('suggested');
        }
    }
    static #re = /\s*(\p{L}*)\s*(.*)\s*/u;
    #parse() {
        if (this.#currencyFixed) {
            this.#amount.value = this.#input.value
                && parseCurrency(this.#input.value, this.#currency.value);
        } else {
            let [, currency, amount] = this.#input.value.match(CurrencyInput.#re);
            this.#currency.value = currency;
            this.#amount.value = amount && parseCurrency(amount, currency);
        }
    }
    clear() { this.#amount.value = this.#currency.value = ""; this.#refresh(); }
    set value(value) { this.#amount.value = value; this.#refresh(); }
    get value() { return this.#amount.value; }
    set currency(value) { this.#currency.value = value; this.#refresh(); }
    get currency() { return this.#currency.value; }
    set currencyFixed(value) {
        this.#currencyFixed = value;
        if (value) this.#currencySuggested = false;
        this.#refresh();
    }
    get currencyFixed() { return this.#currencyFixed; }
    get classList() { return this.#input.classList; }
    unsuggest() {
        if (this.#amountSuggested) {
            this.#amountSuggested = false;
            this.value = '';
        }
        if (this.#currencySuggested) {
            this.#currencySuggested = false;
            this.currency = '';
        }
    }
    suggest(value) {
        if (this.value === "" && document.activeElement !== this.#input) {
            this.#amountSuggested = true;
            this.value = value;
            return true;
        }
        return false;
    }
    suggestCurrency(value) {
        if (this.currency === "" && document.activeElement !== this.#input) {
            this.#currencySuggested = true;
            this.currency = value;
            return true;
        }
        return false;
    }
    accept() {
        this.#amountSuggested = this.#currencySuggested = false;
        this.classList.remove('suggested');
    }

    addEventListener(event, func) {
        this.#input.addEventListener(event, e => func({ target: this }));
    }
    set disabled(value) { this.#input.disabled = value; }
    set name(value) {
        this.#amount.name = value;
        this.#currency.name = value + "_currency";
    }
}

function setUpRow(tr) {
    var [account, category, transferred, moved] =
        Array.prototype.map.call(tr.children, n => n.children);
    account = new Selector(account, account_options, accountChanged);
    category = new Selector(category, category_options, categoryChanged);
    if (category.value === account.value)
        category.classList.add('suggested');
    account.sigil = ownAccount(account.value);
    category.sigil = ownAccount(category.value);
    transferred = new CurrencyInput(transferred, account.value in data.accounts);
    moved = new CurrencyInput(moved, category.value in data.categories);
    transferred.disabled = !account.value;
    moved.disabled = !category.value;
    transferred.addEventListener('input', amountChanged);
    transferred.addEventListener('blur', suggestAmounts);
    moved.addEventListener('input', amountChanged);
    moved.addEventListener('blur', suggestAmounts);
    const row = { account, category, moved, transferred };
    rows.push(row);
    return row;
}

function setUpRows() {
    const real_rows = Array.prototype.slice.call(tbody.children, 1, -1);
    for (var tr of real_rows) {
        setUpRow(tr);
    }
}

function addRow(event) {
    var tr = tbody.children[1].cloneNode(true);
    var { account, category, moved, transferred } = setUpRow(tr);
    const n = rows.length - 1;
    // TODO: refactor this to use <template>
    account.value = '';
    account.name = `tx-${n}-account`;
    category.value = '';
    category.name = `tx-${n}-category`;
    moved.clear();
    moved.disabled = true;
    moved.name = `tx-${n}-moved`;
    transferred.clear();
    transferred.disabled = true;
    transferred.name = `tx-${n}-transferred`;
    tbody.insertBefore(tr, adder_row);
    document.forms[0].elements["tx-TOTAL_FORMS"].value = rows.length;
    if (event) {
        account.focus({ focusVisible: true });
    }
}

function accountChanged({ target }) {
    // Enforce uniqueness ?
    // if (target.value) {
    //     for (var { account } of rows) {
    //         if (account !== target && account.value === target.value) {
    //             account.value = "";
    //             accountChanged({ target: account });
    //         }
    //     }
    // }

    var { category, transferred, moved } = rows[findRow(target)];
    category.unsuggest();
    if (!ownAccount(target.value)) {
        if (target.value in data.budgets) category.suggest(target.value);
        else if (target.value) category.suggest(`[${target.value}]`);
    }

    target.sigil = ownAccount(target.value);

    moved.disabled = !category.value;

    if (!target.value) transferred.clear();
    transferred.disabled = !target.value;
    const currency = data.accounts[target.value];
    if (currency) transferred.currency = currency;
    transferred.currencyFixed = !!currency;

    suggestAmounts();
}

function categoryChanged({ target }) {
    target.accept();

    // Enforce uniqueness ?
    // if (target.value) {
    //     for (var { category } of rows) {
    //         if (category !== target && category.value === target.value) {
    //             category.value = "";
    //             categoryChanged({ target: category });
    //         }
    //     }
    // }
    target.sigil = ownAccount(target.value);

    var { moved } = rows[findRow(target)];
    if (!target.value) moved.clear();
    moved.disabled = !target.value;
    const currency = data.categories[target.value];
    if (currency) moved.currency = currency;
    moved.currencyFixed = !!currency;

    suggestAmounts();
}

function amountChanged({ target }) {
    target.accept();
    suggestAmounts();
}

function suggestCurrenciesColumn() {
    const currencies = new Set(rows
        .filter(({ account }) => account.value)
        .map(({ transferred }) => transferred.currency)
        .concat(rows
            .filter(({ category }) => category.value)
            .map(({ moved }) => moved.currency)));
    if (currencies.delete("") && currencies.size === 1) {
        const currency = currencies.values().next().value;
        for (var { account, category, moved, transferred } of rows) {
            if (category.value) moved.suggestCurrency(currency);
            if (account.value) transferred.suggestCurrency(currency);
        }
    }
}

function suggestSums() {
    suggestCurrenciesColumn();
    var result = false;
    const currencies = new Set(
        rows.flatMap(({ transferred, moved }) =>
            [transferred.currency, moved.currency]));

    for (const currency of currencies) {
        var to_category = [];
        var category_total = 0;
        var to_account = [];
        var account_total = 0;
        for (var { account, category, moved, transferred } of rows) {
            if (category.value && moved.currency === currency) {
                if (moved.value) {
                    category_total += +moved.value;
                } else {
                    to_category.push(moved);
                }
            }
            if (account.value && transferred.currency === currency) {
                if (transferred.value) {
                    account_total += +transferred.value;
                } else {
                    to_account.push(transferred);
                }
            }
        }
        if (isFinite(category_total) && to_category.length === 1) {
            result |= to_category[0].suggest(category_total ? -category_total : "");
        }
        if (isFinite(account_total) && to_account.length === 1) {
            result |= to_account[0].suggest(account_total ? -account_total : "");
        }
    }
    return result;
}

function suggestRowConsistency(options) {
    var result = false;
    for (var { account, category, moved, transferred } of rows) {
        if (!account.value || !category.value)
            continue;
        if (options?.onlyExternal && category.value !== account.value &&
            category.value !== `[${account.value}]`)
            continue;
        if (transferred.currency && !moved.currency)
            moved.suggestCurrency(transferred.currency);
        if (moved.currency && !transferred.currency)
            transferred.suggestCurrency(moved.currency);
        if (moved.currency !== transferred.currency)
            continue;
        if (transferred.value && isFinite(+transferred.value))
            result |= moved.suggest(transferred.value);
        if (moved.value && isFinite(+moved.value))
            result |= transferred.suggest(moved.value);
    }
    return result;
}

function suggestAmounts() {
    for (var { moved, transferred } of rows) {
        moved.unsuggest();
        transferred.unsuggest();
    }
    // Try to make progress with each one, with this priority
    do {
        do {
            suggestSums();
        } while (suggestRowConsistency({ onlyExternal: true }));
    } while (suggestRowConsistency());

    checkValid();
}

function combineDebts(owed) {
    var amounts = Object.entries(owed).filter(o => o[1])
        .sort((a, b) => a[1] - b[1]);
    var result = [];
    var [from, amount] = ['', 0];
    while (amounts.length || amount) {
        if (amount === 0)
            [from, amount] = amounts.shift();
        if (!amounts.length)
            return [];  // Debts do not sum to zero
        const [to, other] = amounts.pop();
        const result_amount = Math.min(-amount, other);
        result.push([from, to, result_amount]);
        amount += other;
        if (amount > 0) {
            amounts.push([to, amount]);
            amount = 0;
        }
    }
    return result;
}

function stripBrackets(value) {
    if (value.startsWith('[') && value.endsWith(']'))
        return value.slice(1, -1);
    return value;
}

function checkValid() {
    const currencies = new Set(
        rows.flatMap(({ transferred, moved }) =>
            [transferred.currency, moved.currency]));

    var category_totals = [];
    var account_totals = [];
    var debts = []
    valid = true;

    for (const currency of currencies) {
        var category_total = 0;
        var account_total = 0;
        var owed = {};
        for (var { account, category, moved, transferred } of rows) {
            if (transferred.currency === currency) {
                account_total = account_total + +transferred.value;
                let budget = ownAccount(account.value)
                    ? data.budget : account.value;
                owed[budget] = (owed[budget] || 0) + +transferred.value;

            }
            if (moved.currency === currency) {
                category_total = category_total + +moved.value;
                let budget = ownAccount(category.value)
                    ? data.budget : stripBrackets(category.value);
                owed[budget] = (owed[budget] || 0) - +moved.value;
            }
        }
        if (category_total && isFinite(category_total)) {
            category_totals.push(formatCurrency(category_total, currency));
            valid = false;
        }
        if (account_total && isFinite(account_total)) {
            account_totals.push(formatCurrency(account_total, currency));
            valid = false;
        }
        debts = debts.concat(
            combineDebts(owed)
                .map(([from, to, amount]) =>
                    `${data.budgets[to] || to} owes `
                    + `${data.budgets[from] || from} `
                    + `${formatCurrency(amount, currency)}`));
    }
    category_sum.innerText = category_totals.length === 0 ? '' :
        category_totals.join(', ') + ' left to categorize';
    account_sum.innerText = account_totals.length === 0 ? '' :
        account_totals.join(', ') + ' left to account for';
    debt.innerText = debts.join(', ');
    document.getElementById("submit-button").disabled = !valid;
}

function onSubmit(event) {
    if (!valid) event.preventDefault();
}
