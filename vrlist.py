import csv
from urllib.parse import urlparse

import requests


def screen_transform_report(src, screen, transform=None, report=None):
    rows = []
    uniq = set()
    for row in src:
        still_good = True
        for col, val in screen.items():
            if col not in row or row[col] != val:
                still_good = False
        if not still_good:
            continue

        if transform:
            new = {}
            for orig, des in transform.items():
                new[des] = row[orig]
            rows.append(new)
        else:
            rows.append(row)

        if report:
            uniq.add(tuple([row[col] for col in report]))

    return rows, uniq


def screen_regex(src, col, pat):
    rows = []
    prog = re.compile(pat)
    for row in src:
        if prog.fullmatch(row[col]):
            rows.append(row)
    return row


def screen_range(src, col, ranges):
    rows = []
    for row in src:
        for low, high in ranges:
            if low <= int(row[col]) <= high:
                rows.append(row)
                break
    return row


def get_csv_from_loc(path_or_url):
    parse_res = urlparse(path_or_url)
    if parse_res.scheme in ('http', 'https'):
        r = requests.get(path_or_url)
        # observed because someone has a German mailing address in the database
        r.encoding = 'iso-8859-1'
        return csv.DictReader(r.text.splitlines())
    else:
        return csv.DictReader(open(path_or_url, encoding='iso-8859-1'))


def make_pseudonumber_sortable(pseudonumber):
    # For the normal case (a number), just return the number
    if pseudonumber.isdigit():
        return (int(pseudonumber),)

    # Empty string: return 0
    if not pseudonumber:
        return (0,)

    # Otherwise, remove any prefix, then return (number, prefix, suffix)
    # (if it's entirely text, return (0, string))
    num_idx = 0
    while num_idx <= len(pseudonumber) and not pseudonumber[num_idx].isdigit():
        num_idx += 1
    if num_idx == len(pseudonumber):
        return (0, pseudonumber)
    suf_idx = num_idx
    while suf_idx <= len(pseudonumber) and pseudonumber[suf_idx].isdigit():
        suf_idx += 1

    pre = pseudonumber[:num_idx]
    num = pseudonumber[num_idx:suf_idx]
    suf = pseudonumber[suf_idx:]
    return (int(num), pre, suf)


def parse_ranges(range_string):
    ret = []
    components = [rang.split('-') for rang in range_string.split(',')]
    for rang in components:
        if len(rang) == 1:
            ret.append((int(rang[0]), int(rang[0])))
        elif len(rang) == 2:
            ret.append((int(rang[0]), int(rang[1])))
        else:
            raise ValueError('invalid range specification')
    return ret


def select_streets(streets):
    print('We found {} streets in this precinct. Here they are:'.format(len(streets)))
    for idx, street in enumerate(streets):
        print('{:3d}.  {:>2s}  {}  {}'.format(idx + 1, *street))

    res = [False] * len(streets)
    just_checked = True  # if true, pressing 0 returns

    print('Which ones do you want to use? Input a number to add it,')
    print('its negative to remove it, and nothing to check what you have selected.')
    print('Or, press Enter immediately to use the entire precinct.')

    query = input()
    while query or not just_checked:
        if not query:
            just_checked = True
            print('You\'ve selected these streets:')
            tot = 0
            for idx, street in enumerate(streets):
                if res[idx]:
                    tot += 1
                    print('{:3d}.  {:>2s}  {}  {}'.format(idx + 1, *street))
            if not tot:
                print('      FULL PRECINCT (none currently selected)')
            print('Press Enter again to use these streets.')
        else:
            try:
                qr = int(query)
                just_checked = False
                if qr == 0 or abs(qr) > len(streets):
                    print('That street doesn\'t exist.')
                else:
                    remove = (qr < 0)
                    qr = abs(qr)

                    if remove:
                        if res[qr - 1]:
                            res[qr - 1] = False
                            print('Removed {}. {} {} {}.'.format(qr, *streets[qr - 1]))
                        else:
                            print('That street is already deselected.')
                    else:
                        if not res[qr - 1]:
                            res[qr - 1] = True
                            print('Added {}. {} {} {}.'.format(qr, *streets[qr - 1]))
                        else:
                            print('That street is already selected.')
            except ValueError:
                print('I don\'t know what that is, but it\'s not a number.')

        query = input()

    print('All right, we\'ll use those streets.')
    # Returns empty if all streets used
    ret = [pair[1] for pair in zip(res, streets) if pair[0]]
    if not ret:
        print('You selected no streets, so we\'ll use the whole precinct.')
    return ret


def main():
    print('Welcome to the voter-registration-list generator!')

    print('Where should I obtain the voter file? (URL or local file path)')
    vfile = get_csv_from_loc(input())
    print()

    print('Got the voter file. We\'ll check its format in a bit.')
    print('What precinct are you working in?')
    precinct = input().strip()
    print('Filtering the list. This will take a while.')

    # Filter by precinct and also give us a more reasonable address format
    precinct_matches, precinct_streets = screen_transform_report(
        vfile,
        {'PCTCOD': precinct},
        {
            'VUIDNO': 'vuid',
            'EDRDAT': 'edr_date',
            'LSTNAM': 'name_last',
            'NAMPFX': 'name_prefix',
            'FSTNAM': 'name_first',
            'MIDNAM': 'name_middle',
            'BLKNUM': 'address_number',
            'STRDIR': 'address_street_prefix',
            'STRNAM': 'address_street_name',
            'STRTYP': 'address_street_suffix',
            'UNITNO': 'address_unit',
            'SUSIND': 'suspense',
        },
        ('STRDIR', 'STRNAM', 'STRTYP'),
    )

    if not precinct_streets:
        print('Whoops... looks like nobody lives in that precinct.')
        print('Or maybe the list is malformed.')
        return

    print('There are {} registered voters here.'.format(len(precinct_matches)))
    print()

    precinct_streets = list(precinct_streets)
    precinct_streets.sort(key=lambda street: street[1] + '  ' + street[2] + '  ' + street[0])
    print(select_streets(precinct_streets))


if __name__ == '__main__':
    main()
