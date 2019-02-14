import csv
from io import BytesIO
import re
from urllib.parse import urlparse
import zipfile

import requests

VOTER_FILE_URL = 'https://tax-office.traviscountytx.gov/pages/vrodffcc.php'


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


def screen_collection(src, cols, possibilities):
    rows = []
    for row in src:
        check = tuple([row[col] for col in cols])
        if check in possibilities:
            rows.append(row)
    return rows


def screen_regex(src, col, pat):
    rows = []
    prog = re.compile(pat)
    for row in src:
        if prog.fullmatch(row[col]):
            rows.append(row)
    return rows


def screen_pseudorange(src, col, ranges):
    rows = []
    for row in src:
        for low, high in ranges:
            if low <= make_pseudonumber_sortable(row[col])[0] <= high:
                rows.append(row)
                break
    return rows


def screen_regex_or_pseudorange(src, col, pat):
    if len(pat[0]) == 1:
        return screen_regex(src, col, pat)
    else:
        return screen_pseudorange(src, col, pat)


def uncompress_sole_file(blob):
    if blob[0] in ('"', 'S'):
        # CSV or section header
        return blob
    with zipfile.ZipFile(BytesIO(blob)) as zf:
        with zf.open(zf.namelist()[0]) as f:
            return f.read()


def get_csv_from_loc(path_or_url):
    parse_res = urlparse(path_or_url)
    if parse_res.scheme in ('http', 'https'):
        print('Downloading from the Internet.')
        r = requests.get(path_or_url)
        blob = uncompress_sole_file(r.content)

        # observed because someone has a German mailing address in the database
        text = blob.decode('iso-8859-1')

        # The download has a Section 18.009 header;
        # if it's there, print it and remove it.
        if text[0] == 'S':
            print('The file came with the following legal warning:')
            print(''.join(text.splitlines(True)[0:9]))
            return csv.DictReader(text.splitlines()[10:])

        return csv.DictReader(text.splitlines())
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
    while num_idx < len(pseudonumber) and not pseudonumber[num_idx].isdigit():
        num_idx += 1
    if num_idx == len(pseudonumber):
        return (0, pseudonumber)
    suf_idx = num_idx
    while suf_idx < len(pseudonumber) and pseudonumber[suf_idx].isdigit():
        suf_idx += 1

    pre = pseudonumber[:num_idx]
    num = pseudonumber[num_idx:suf_idx]
    suf = pseudonumber[suf_idx:]
    return (int(num), pre, suf)


def format_street(pre, name, suf):
    return '{} {} {}'.format(pre, name.title(), suf.title()).strip()


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


def validate_pattern(pattern):
    if not pattern:
        return '.*'

    # If it's a regex, see if it compiles
    if pattern[0] == '/' and pattern[-1] == '/' and pattern != '/':
        try:
            re.compile(pattern[1:-1])
            # it's valid!
            return pattern[1:-1]
        except re.error:
            return None
    else:
        # It's a range; try and parse it
        try:
            return parse_ranges(pattern)
        except ValueError:
            return None


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
                            print('Removed {}. {}.'.format(qr, format_street(*streets[qr - 1])))
                        else:
                            print('That street is already deselected.')
                    else:
                        if not res[qr - 1]:
                            res[qr - 1] = True
                            print('Added {}. {}.'.format(qr, format_street(*streets[qr - 1])))
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


def obtain_pat():
    print('Input a range or a regex with slashes (the regex matches the full number).')
    print('Or just press Enter to use no restrictions.')
    pat = validate_pattern(input())
    while not pat:
        print('Oops, that doesn\'t look valid. Try again.')
        pat = validate_pattern(input())
    return pat


def voter_sort_key(voter):
    return (
        voter['address_street_name'],
        voter['address_street_suffix'],
        voter['address_street_prefix'],
        make_pseudonumber_sortable(voter['address_number']),
        make_pseudonumber_sortable(voter['address_unit']),
        voter['edr_date'],
        voter['vuid'],
    )


def format_voter(voter):
    return '{:>6s} {:40s} #{:6s} {:1s}{:8s} {:40s}'.format(
        voter['address_number'],
        format_street(voter['address_street_prefix'], voter['address_street_name'], voter['address_street_suffix']),
        voter['address_unit'],
        voter['suspense'],
        voter['edr_date'],
        '{}, {} {}'.format(voter['name_last'], voter['name_first'], voter['name_middle']).strip().title())


def main():
    print('Welcome to the voter-registration-list generator!')

    print('Where should I obtain the voter file? (URL or local file path)')
    print('Or, press Enter to download the voter file from its usual location.')
    vfile = get_csv_from_loc(input() or VOTER_FILE_URL)
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

    print('There are {:,d} registered voters in Precinct {}.'.format(len(precinct_matches), precinct))
    print()

    precinct_streets = list(precinct_streets)
    precinct_streets.sort(key=lambda street: street[1] + '  ' + street[2] + '  ' + street[0])
    use_streets = select_streets(precinct_streets)

    primary_pat = '.*'  # string is regex (no slashes); list is ranges
    if len(use_streets) == 1:
        print('Do you want to use only certain primary numbers on {}?'.format(format_street(*use_streets[0])))
        primary_pat = obtain_pat()

    unit_pat = '.*'
    # If it's a single range of a single primary, do we want unit restrictions?
    if len(primary_pat) == 1 and len(primary_pat[0]) == 2 and primary_pat[0][0] == primary_pat[0][1]:
        print('Do you want to use only certain units at {} {}?'.format(primary_pat[0][0], format_street(*use_streets[0])))
        unit_pat = obtain_pat()

    print('Preparing your list.')

    street_matches = screen_collection(
        precinct_matches,
        ('address_street_prefix', 'address_street_name', 'address_street_suffix'), use_streets)
    primary_matches = screen_regex_or_pseudorange(street_matches, 'address_number', primary_pat)
    voters = screen_regex_or_pseudorange(primary_matches, 'address_unit', unit_pat)
    voters.sort(key=voter_sort_key)

    print()

    print('{:,d} voter(s): Precinct {} (selected)'.format(len(voters), precinct))
    for voter in voters:
        print(format_voter(voter))


if __name__ == '__main__':
    main()
