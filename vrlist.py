import csv
from urllib.parse import urlparse

import requests


def screen_transform_report(src, screen, transform, report):
    rows = []
    uniq = set()
    for row in src:
        still_good = True
        for col, val in screen.items():
            if col not in row or src[col] != val:
                still_good = False
        if not still_good:
            continue

        new = {}
        for orig, des in transform:
            new[des] = src[orig]
        rows.append(new)

        uniq.add(tuple([src[col] for col in report]))

    return rows, uniq


def get_csv_from_loc(path_or_url):
    parse_res = urlparse(path_or_url)
    if parse_res.scheme in ('http', 'https'):
        return csv.DictReader(requests.get(path_or_url).text.splitlines())
    else:
        return csv.DictReader(open(path_or_url))


def main():
    print('Welcome to the voter-registration-list generator!')

    print('Where should I obtain the voter file? (URL or local file path)')
    vfile = get_csv_from_loc(input())

    print('Got the voter file. We\'ll check its format in a bit.')
    print('What precinct are you working in?')
    precinct = input()

    # Filter by precinct and also give us a more reasonable address format
    precinct_matches, precinct_streets = screen_transform_report(
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


if __name__ == '__main__':
    main()
