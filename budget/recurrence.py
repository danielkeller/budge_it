from dataclasses import dataclass, asdict
from datetime import date, datetime
from typing import Iterable, cast

from dateutil import rrule


@dataclass
class RRule:
    freq: str
    until: str | None = None
    count: int | None = None
    interval: int | None = None
    byweekday: list[str] | None = None
    bymonthday: list[int] | None = None
    byyearday: list[int] | None = None
    byweekno: list[int] | None = None
    bymonth: list[int] | None = None
    bysetpos: list[int] | None = None
    wkst: str | int | None = None

    def __str__(self):
        return ';'.join(f'{_partname(name)}={_partvalue(part)}'
                        for name, part in asdict(self).items()
                        if part)

    def rrule(self, start: date) -> rrule.rrule:
        return rrule.rrulestr(str(self), dtstart=start)  # type: ignore

    def iterate(self, start: date) -> Iterable[date]:
        dtstart = datetime(start.year, start.month, start.day)
        xafter = cast(Iterable[datetime],
                      self.rrule(dtstart).xafter(dtstart, inc=True))  # type: ignore
        for dt in xafter:
            yield dt.date()


def parse(val: str) -> RRule:
    rrule.rrulestr(val)  # Make sure it really parses
    parts = dict(part.split('=') for part in val.split(';'))
    result = RRule(
        freq=parts.pop('FREQ'),
        until=parts.pop('UNTIL', None),
        count=_int(parts.pop('COUNT', None)),
        interval=_int(parts.pop('INTERVAL', None)),
        byweekday=_strlist(parts.pop('BYDAY', None)),
        bymonthday=_intlist(parts.pop('BYMONTHDAY', None)),
        byyearday=_intlist(parts.pop('BYYEARDAY', None)),
        byweekno=_intlist(parts.pop('BYWEEKNO', None)),
        bymonth=_intlist(parts.pop('BYMONTH', None)),
        bysetpos=_intlist(parts.pop('BYSETPOS', None)),
        wkst=parts.pop('WKST', None)
    )
    if parts:
        raise ValueError(f'Unsupported option {next(iter(parts))}')
    return result


def _partname(field: str):
    if field == 'byweekday':
        return 'BYDAY'
    return field.upper()


def _partvalue(part: str | int | list[str | int] | None):
    if isinstance(part, list):
        return ','.join(str(item) for item in part)
    return str(part)


def _int(value: str | None):
    return int(value) if value else None


def _strlist(value: str | None):
    return [item for item in value.split(',')] if value else None


def _intlist(value: str | None):
    return [int(item) for item in value.split(',')] if value else None
