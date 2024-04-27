"use strict";

// The "j" is for "jank"
class Decimal {
    e = 0;
    m = 0;

    constructor() { }
    static parse(string) {
        const match = string.trim().match(Decimal.#re);
        let [, int, sep, frac] = match.filter(c => c !== undefined);
        int = int.replaceAll(sep || Decimal.#point, "fail");
        int = int.replaceAll(/[,.' ]/g, "");
        return Decimal.fromParts(frac.length, +(int + frac));
    }
    static zero = new Decimal();
    static NaN = Decimal.fromParts(0, NaN);

    toString() {
        if (!isFinite(this.m) || this.e === 0) return this.m;
        const sign = this.m < 0 ? "-" : "";
        const int = Math.abs(Math.trunc(this.m / (10 ** this.e)));
        let frac = Math.abs(this.m % (10 ** this.e)) || '';
        frac = frac.toString().padStart(this.e, '0');
        return `${sign}${int}${Decimal.#point}${frac}`
    }
    toFloat() { // not valueOf since this loses information
        return this.m / (10 ** this.e);
    }
    toInt(places) {
        return this.round(places).m;
    }
    static fromParts(e, m) {
        let result = new Decimal();
        result.e = Math.max(0, Math.trunc(e));
        if (m > 2 ** 53) result.m = Infinity;
        else if (m < -(2 ** 53)) result.m = -Infinity;
        else result.m = Math.trunc(m);
        return result;
    }
    static roundFromParts(e, m) {
        const frac = m / 2;
        const rnd = Math.abs(frac % 1);
        const offs = Math.sign(frac) * ((rnd > .25) + (rnd >= .75));
        return Decimal.fromParts(e, Math.trunc(frac) * 2 + offs);
    }

    plus(other) {
        other = Decimal.#coerce(other);
        return Decimal.fromParts(Math.max(this.e, other.e),
            this.#aligned(other.e) + other.#aligned(this.e))
    }
    negate() { return Decimal.fromParts(this.e, -this.m); }
    minus(other) { return this.plus(Decimal.#coerce(other).negate()); }
    times(other) {
        other = Decimal.#coerce(other);
        return Decimal.fromParts(this.e + other.e, this.m * other.m);
    }
    // Rounded division
    div(other) {
        other = Decimal.#coerce(other);
        const ext = this.#aligned(this.e + other.e);
        return Decimal.roundFromParts(this.e, ext / other.m);
    }
    round(places) {
        places = Math.trunc(places);
        if (this.e < places) return this.plus(Decimal.fromParts(places, 0));
        else return Decimal.roundFromParts(places, this.m / 10 ** (this.e - places));
    }
    // Floored division and remainder
    divrem(int) {
        int = Math.trunc(int);
        const div = Decimal.fromParts(this.e, Math.trunc(this.m / int));
        const rem = this.minus(Decimal.fromParts(this.e, div.m * int));
        return [div, rem];
    }
    cmp(other) { return this.minus(other).m; }
    eq(other) { return this.cmp(other) === 0; }
    ne(other) { return this.cmp(other) !== 0; }
    lt(other) { return this.cmp(other) < 0; }
    gt(other) { return this.cmp(other) > 0; }
    min(other) { return this.lt(other) ? this : other; }
    isFinite() { return isFinite(this.m); }

    static #point = new Intl.NumberFormat(navigator.language)
        .formatToParts(1.1)[1].value;
    static #re =
        new RegExp(`(.*)([,.·])([0-9]{0,2})$|(.*)(\\${Decimal.#point})([0-9]*)$|(.*)()()$`);
    static #coerce(other) {
        if (other instanceof Decimal) return other;
        if (typeof other === "string") return Decimal.parse(other);
        if (typeof other === "number" && Math.trunc(other) === other)
            return Decimal.fromParts(0, other);
        return Decimal.NaN;
    }
    #aligned(to) {
        let { e, m } = this;
        for (; e < to; ++e) m *= 10;
        return m;
    }
}

function parse(input, minPlaces) {
    function num(str) {
        const num = str.match(/^[,.·' 0-9]+/);
        if (!num) return [Decimal.NaN, str];
        let parsed = Decimal.parse(num[0]).plus(Decimal.fromParts(minPlaces, 0));
        return [parsed, str.substring(num[0].length)];
    }

    function paren(str) {
        str = str.trimStart();
        if (str[0] === '(') {
            let [result, rest] = add(str.substring(1));
            rest = rest.trimStart();
            if (rest[0] === ')')
                return [result, rest.substring(1)];
            return [result, rest];
        }
        return num(str);
    }

    function prefix(str) {
        str = str.trimStart();
        if (str[0] === '-' || str[0] === '+') {
            let [num, rest] = prefix(str.substring(1));
            if (str[0] === '-') num = num.negate();
            return [num, rest];
        }
        return paren(str);
    }

    function mul(str) {
        let [result, rest] = prefix(str);
        while (true) {
            rest = rest.trimStart();
            if (rest[0] !== '*' && rest[0] !== '/') break;
            const [rhs, rest1] = prefix(rest.substring(1));
            if (rest[0] === '*') result = result.times(rhs);
            else result = result.div(rhs);
            rest = rest1;
        }
        return [result, rest];
    }

    function add(str) {
        let [result, rest] = mul(str);
        while (true) {
            rest = rest.trimStart();
            if (rest[0] !== '+' && rest[0] !== '-') break;
            const [rhs, rest1] = mul(rest.substring(1));
            if (rest[0] === '+') result = result.plus(rhs);
            else result = result.minus(rhs);
            rest = rest1;
        }
        return [result, rest];
    }

    const [result, rest] = add(input);
    if (rest.trimStart() !== '') return Decimal.NaN;
    return result;
}