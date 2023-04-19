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

class Selector {
    #visible; #hidden; #options; #oninput;
    constructor([hidden, visible], options, oninput) {
        this.#visible = visible;
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
    get active() { return document.activeElement === this.#visible; }
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
    constructor([currency, amount, span, input], currencyFixed) {
        this.#currency = currency;
        this.#amount = amount;
        this.#span = span;
        this.#input = input;
        this.#currencyFixed = currencyFixed;
        this.#refresh();
        this.#input.addEventListener('input', this.#parse.bind(this));
    }
    #refresh() {
        if (this.#currencyFixed) {
            this.#span.innerText = this.#currency.value;
            this.#span.className = "suggested currency";
            this.#input.value = this.#amount.value;
        } else {
            this.#span.innerText = "";
            this.#span.className = "";
            this.#input.value = this.#currency.value + " " + this.#amount.value;
        }
    }
    static #re = /(\p{L}*)\s*(.*)/u;
    #parse() {
        if (this.#currencyFixed) {
            this.#amount.value = this.#input.value;
        } else {
            let [, currency, amount] = this.#input.value.match(CurrencyInput.#re);
            this.#currency.value = currency;
            this.#amount.value = amount;
        }
    }
    clear() { this.#amount.value = this.#currency.value = ""; this.#refresh(); }
    set value(value) { this.#amount.value = value; this.#refresh(); }
    get value() { return this.#amount.value; }
    set currency(value) { this.#currency.value = value; this.#refresh(); }
    get currency() { return this.#currency.value; }
    set currencyFixed(value) { this.#currencyFixed = value; this.#refresh(); }
    get currencyFixed() { return this.#currencyFixed; }
    get active() { return document.activeElement === this.#input; }

    addEventListener(...args) { this.#input.addEventListener(...args); }
    get classList() { return this.#input.classList; }
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

function unsuggest(element) {
    if (element.classList.contains('suggested')) {
        element.value = '';
        element.classList.remove('suggested');
    }
}
function suggest(element, value) {
    if (element.value === "" && !element.active) {
        element.value = value;
        element.classList.add('suggested');
        return true;
    }
    return false;
}

function accountChanged({ target }) {
    // Enforce uniqueness
    if (target.value) {
        for (var { account } of rows) {
            if (account !== target && account.value === target.value) {
                account.value = "";
                accountChanged({ target: account });
            }
        }
    }

    var { category, transferred, moved } = rows[findRow(target)];
    unsuggest(category);
    if (target.value in data.budgets)
        suggest(category, target.value);
    else if (target.value && !(target.value in data.accounts))
        suggest(category, `[${target.value}]`);

    moved.disabled = !category.value;

    if (!target.value) transferred.clear();
    transferred.disabled = !target.value;

    suggestAmounts();
}

function categoryChanged({ target }) {
    target.classList.remove('suggested');

    // Enforce uniqueness
    if (target.value) {
        for (var { category } of rows) {
            if (category !== target && category.value === target.value) {
                category.value = "";
                categoryChanged({ target: category });
            }
        }
    }

    var { moved } = rows[findRow(target)];
    if (!target.value) moved.value = "";
    moved.disabled = !target.value;

    suggestAmounts();
}

function amountChanged({ target }) {
    target.classList.remove('suggested');
    suggestAmounts();
}

function suggestSums() {
    var to_category = {};
    var category_total = {};
    var to_account = {};
    var account_total = {};
    for (var { account, category, moved, transferred } of rows) {
        if (category.value) {
            if (moved.value) {
                category_total[moved.currency] =
                    (category_total[moved.currency] || Decimal.zero)
                        .plus(moved.value);
            } else {
                to_category[moved.currency].push(moved);
            }
        }
        if (account.value) {
            if (transferred.value) {
                account_total[transferred.currency] =
                    (account_total[transferred.currency] || Decimal.zero)
                        .plus(transferred.value);
            } else {
                to_account[transferred.currency].push(transferred);
            }
        }
    }
    var result = false;
    for (const currency of Object.keys(category_total)) {
        const to = 
        if (category_total.isFinite() && to_category.length === 1) {
            result |= suggest(to_category[0], category_total.negate());
        }
    }
    if (account_total.isFinite() && to_account.length === 1) {
        result |= suggest(to_account[0], account_total.negate());
    }
    return result;
}

function suggestRowConsistency(options) {
    var result = false;
    for (var { account, category, moved, transferred } of rows) {
        if (!account.value || !category.value) { continue; }
        if (options?.onlyExternal && category.value !== account.value)
            continue;
        if (transferred.value && Decimal.parse(transferred.value).isFinite())
            result |= suggest(moved, Decimal.parse(transferred.value));
        if (moved.value && Decimal.parse(moved.value).isFinite())
            result |= suggest(transferred, Decimal.parse(moved.value));
    }
    return result;
}

function suggestAmounts() {
    for (var { moved, transferred } of rows) {
        unsuggest(moved);
        unsuggest(transferred);
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
    var amounts = Object.entries(owed).filter(o => o[1].ne(0))
        .sort((a, b) => a[1].cmp(b[1]));
    var result = [];
    var [from, amount] = ['', Decimal.zero];
    while (amounts.length || amount.ne(0)) {
        if (amount.eq(0))
            [from, amount] = amounts.shift();
        if (!amounts.length)
            return [];  // Debts do not sum to zero
        const [to, other] = amounts.pop();
        const result_amount = amount.negate().min(other);
        result.push([from, to, result_amount]);
        amount = amount.plus(other);
        if (amount.gt(0)) {
            amounts.push([to, amount]);
            amount = Decimal.zero;
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
    var category_total = Decimal.zero;
    var account_total = Decimal.zero;
    var owed = {};
    for (var { account, category, moved, transferred } of rows) {
        account_total = account_total.plus(transferred.value);
        let budget = account.value in data.accounts
            ? data.budget : account.value;
        if (!owed[budget]) owed[budget] = Decimal.zero;
        owed[budget] = owed[budget].plus(transferred.value);

        category_total = category_total.plus(moved.value);
        budget = category.value in data.categories
            ? data.budget : stripBrackets(category.value);
        if (!owed[budget]) owed[budget] = Decimal.zero;
        owed[budget] = owed[budget].minus(moved.value);
    }
    valid = true;
    if (category_total.ne(0) && category_total.isFinite()) {
        category_sum.innerText = category_total + ' left to categorize';
        valid = false;
    } else {
        category_sum.innerText = '';
    }
    if (account_total.ne(0) && account_total.isFinite()) {
        account_sum.innerText = account_total + ' left to account for';
        valid = false;
    } else {
        account_sum.innerText = '';
    }
    debt.innerText = combineDebts(owed)
        .map(([from, to, amount]) =>
            `${data.budgets[to] || to} owes ${data.budgets[from] || from} ${amount}`)
        .join(', ');

    document.getElementById("submit-button").disabled = !valid;
}

function onSubmit(event) {
    if (!valid) event.preventDefault();
}
