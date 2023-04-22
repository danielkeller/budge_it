"use strict";

// The "j" is for "jank"
class Decimal {
    e = 0;
    m = 0;

    constructor() { }
    static parse(string) {
        const match = string.trim().match(Decimal.#re);
        let [, int, frac] = match.filter(c => c !== undefined);
        int = int.replaceAll(/[,.' ]/g, "");
        return Decimal.#fromParts(frac.length, +(int + frac));
    }
    static zero = new Decimal();
    static NaN = Decimal.#fromParts(0, NaN);

    toString() {
        if (!isFinite(this.m)) return this.m;
        const int = Math.trunc(this.m / (10 ** this.e));
        let frac = Math.abs(this.m % (10 ** this.e)) || '';
        frac = frac.toString().padStart(this.e, '0');
        return `${int}${Decimal.#point}${frac}`
    }
    toFloat() { // not valueOf since this loses information
        return this.m / (10 ** this.e);
    }

    plus(other) {
        other = Decimal.#coerce(other);
        return Decimal.#fromParts(Math.max(this.e, other.e),
            this.#aligned(other) + other.#aligned(this))
    }
    negate() { return Decimal.#fromParts(this.e, -this.m); }
    minus(other) { return this.plus(Decimal.#coerce(other).negate()); }
    cmp(other) { return this.minus(other).m; }
    eq(other) { return this.cmp(other) === 0; }
    ne(other) { return this.cmp(other) !== 0; }
    lt(other) { return this.cmp(other) < 0; }
    gt(other) { return this.cmp(other) > 0; }
    min(other) { return this.lt(other) ? this : other; }
    isFinite() { return isFinite(this.m); }

    static #point = new Intl.NumberFormat().formatToParts(1.1)[1].value;
    static #re =
        new RegExp(`(.*)[,.·]([0-9]{0,2})$|(.*)\\${Decimal.#point}([0-9]*)$|(.*)()$`);
    static #fromParts(e, m) {
        let result = new Decimal();
        result.e = e;
        if (m > 2 ** 53) result.m = Infinity;
        else if (m < -(2 ** 53)) result.m = -Infinity;
        else result.m = m;
        return result;
    }
    static #coerce(other) {
        if (other instanceof Decimal) return other;
        if (typeof other === "string") return Decimal.parse(other);
        if (typeof other === "number" && Math.trunc(other) === other)
            return Decimal.#fromParts(0, other);
        return Decimal.NaN;
    }
    #aligned(to) {
        let { e, m } = this;
        for (; e < to.e; ++e) m *= 10;
        return m;
    }
}
