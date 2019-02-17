import collections
import csv
from io import BytesIO
import re
from urllib.parse import urlparse
import zipfile

from jinja2.loaders import FileSystemLoader
import latex
from latex.jinja2 import make_env
import requests

VOTER_FILE_URL = 'https://tax-office.traviscountytx.gov/pages/vrodffcc.php'
MONTHS = ['Jan.', 'Feb.', 'Mar.', 'Apr.', 'May', 'June', 'July', 'Aug.', 'Sept.', 'Oct.', 'Nov.', 'Dec.']


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
    """Return entries in a list of dicts where a set of fields match one of a set of possible values for those fields."""
    rows = []
    for row in src:
        check = tuple([row[col] for col in cols])
        if check in possibilities:
            rows.append(row)
    return rows


def screen_regex(src, col, pat):
    """Return entries in a list of dicts where a particular field full-string-matches a regex."""
    rows = []
    prog = re.compile(pat)
    for row in src:
        if prog.fullmatch(row[col]):
            rows.append(row)
    return rows


def screen_pseudorange(src, col, ranges):
    """Return entries in a list of dicts where a particular field satisfies one of a set of ranges.

    The ranges are a list of 2-tuples with an inclusive low and inclusive high.
    The test for inclusion is based on the first element of the tuple from make_pseudonumber_sortable.
    """
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
    """If the given binary blob is a ZIP file, return its sole member, uncompressed."""
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
    """For a quantity that may or may not be numeric, return something that is partially numeric.

    The method must always return a tuple containing a number, then zero or more strings.
    Other parts of the program assume that the first number is the numeric representation of the quantity given.
    """
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
    """Turn ranges (like you specify in a print dialog) into a list of inclusive bounds."""
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
    """Verify that something is either a regex in slashes or a set of ranges.

    Return the string if a regex, the parse_ranges output if a range, None otherwise.
    """
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


def format_pseudorange_or_regex(pat):
    if len(pat[0]) == 1:
        return '/{}/'.format(pat)

    return ', '.join(str(comp[0]) if comp[0] == comp[1] else '{}\u2013{}'.format(*comp) for comp in pat)


def format_report_title(precinct, streets, num_streets_in_precinct, primary, unit):
    if len(streets) == num_streets_in_precinct:
        return 'Precinct {}, full report ({} streets)'.format(precinct, len(streets))
    elif len(streets) > 1:
        return 'Precinct {}, {} of {} streets'.format(precinct, len(streets), num_streets_in_precinct)
    elif primary == '.*':
        return 'Precinct {}, {}'.format(precinct, format_street(*streets[0]))
    elif unit == '.*':
        # Cut down on long titles for ranges with three or more parts
        if len(primary) > 2 and len(primary[0]) == 2:
            return 'Precinct {}, portion of {}'.format(precinct, format_street(*streets[0]))
        else:
            return 'Precinct {}, {} {}'.format(precinct, format_pseudorange_or_regex(primary), format_street(*streets[0]))
    else:
        # Cut down on long titles for ranges with three or more parts
        if len(unit) > 2 and len(unit[0]) == 2:
            return 'Precinct {}, {} {} selected units'.format(precinct, format_pseudorange_or_regex(primary), format_street(*streets[0]))
        else:
            return 'Precinct {}, {} {} #{}'.format(precinct, format_pseudorange_or_regex(primary), format_street(*streets[0]), format_pseudorange_or_regex(unit))


def fix_latex_string(raw):
    # latex.escape only handles ASCII; this also handles ISO-8859-1 and dashes

    # We want to avoid depending on textcomp or math mode,
    # so some non-alphabetic characters just can't be represented.
    def bad_char(legend):
        return r'\guilsinglleft\textsc{' + legend + '}\guilsinglright{}'

    escapes = {
        # ASCII metacharacters
        '#': r'\#',
        '$': r'\$',
        '%': r'\%',
        '&': r'\&',
        '_': r'\_',
        '{': r'\{',
        '}': r'\}',
        '\\': r'\textbackslash{}',
        '^': r'\textasciicircum{}',
        '~': r'\textasciitilde{}',
        '[': '{[}',
        ']': '{]}',

        # Quotation marks
        '`': r'\`{}',
        '\'': r'\textsc{\char13}',  # https://tex.stackexchange.com/a/172878/120844 and the big list of LaTeX symbols
        '"': r'\textquotedbl',

        # ISO-8859-1
        '\xa0': '~',
        '¡': r'\textexclamdown',
        '¢': bad_char('cent'),
        '£': r'\pounds',
        '¤': bad_char('cur'),
        '¥': bad_char('yen'),
        '¦': bad_char('bar'),
        '§': r'\S{}',
        '¨': r'\"{}',
        '©': r'\copyright',
        'ª': r'\textordfeminine',
        '«': r'\guillemotleft',
        '¬': bad_char('not'),
        '­': r'\-',  # soft hyphen
        '®': r'\textregistered',
        '¯': r'\={}',
        '°': bad_char('deg'),
        '±': bad_char('pm'),
        '²': bad_char('sup2'),
        '³': bad_char('sup3'),
        '´': r'\'{}',
        'µ': bad_char('mu'),
        '¶': r'\P{}',
        '·': r'\textperiodcentered',
        '¸': r'\c{}',
        '¹': bad_char('sup1'),
        'º': r'\textordmasculine',
        '»': r'\guillemotright',
        '¼': bad_char('f14'),
        '½': bad_char('f12'),
        '¾': bad_char('f13'),
        '¿': r'\textquestiondown',
        'À': r'\`A',
        'Á': r'\'A',
        'Â': r'\^A',
        'Ã': r'\~A',
        'Ä': r'\"A',
        'Å': r'\AA{}',
        'Æ': r'\AE{}',
        'Ç': r'\c{C}',
        'È': r'\`E',
        'É': r'\'E',
        'Ê': r'\^E',
        'Ë': r'\"E',
        'Ì': r'\`I',
        'Í': r'\'I',
        'Î': r'\^I',
        'Ï': r'\"I',
        'Ð': r'\DH{}',
        'Ñ': r'\~N',
        'Ò': r'\`O',
        'Ó': r'\'O',
        'Ô': r'\^O',
        'Õ': r'\~O',
        'Ö': r'\"O',
        '×': bad_char('times'),
        'Ø': r'\O{}',
        'Ù': r'\`O',
        'Ú': r'\'O',
        'Û': r'\^O',
        'Ü': r'\"O',
        'Ý': r'\'Y',
        'Þ': r'\TH{}',
        'ß': r'\ss{}',
        'à': r'\`a',
        'á': r'\'a',
        'â': r'\^a',
        'ã': r'\~a',
        'ä': r'\"a',
        'å': r'\aa{}',
        'æ': r'\ae{}',
        'ç': r'\c{c}',
        'è': r'\`e',
        'é': r'\'e',
        'ê': r'\^e',
        'ë': r'\"e',
        'ì': r'\`i',
        'í': r'\'i',
        'î': r'\^i',
        'ï': r'\"i',
        'ð': r'\dh',
        'ñ': r'\~n',
        'ò': r'\`o',
        'ó': r'\'o',
        'ô': r'\^o',
        'õ': r'\~o',
        'ö': r'\"o',
        '÷': bad_char('div'),
        'ø': r'\o{}',
        'ù': r'\`o',
        'ú': r'\'o',
        'û': r'\^o',
        'ü': r'\"o',
        'ý': r'\'y',
        'þ': r'\th{}',
        'ÿ': r'\"y',

        # Em and en dashes
        '\u2013': '--',
        '\u2014': '---',
    }

    return ''.join((escapes[ch] if ch in escapes else ch) for ch in raw)


def prettify_yyyymmdd(yyyymmdd):
    if len(yyyymmdd) != 8:
        raise ValueError('Bad length of yyyymmdd date')
    year = yyyymmdd[0:4]
    mo_idx = int(yyyymmdd[4:6])
    day = yyyymmdd[7] if yyyymmdd[6] == '0' else yyyymmdd[6:]
    return '{} {}\xa0{}'.format(year, MONTHS[mo_idx - 1], day)


def hierarchize_and_latexify_voters(voters):
    if len(voters) == 0:
        return {}

    # Structure: street, primary, unit, list of dict with vuid;edr_str;suspense;name_given;name_last
    ret = collections.OrderedDict()

    last_street_fmt = None
    last_primary = None
    last_unit = None

    for voter in voters:
        # This acts goofy if two adjacent streets are formatted the same, but should be fine in practice
        street_fmt = fix_latex_string(format_street(voter['address_street_prefix'], voter['address_street_name'], voter['address_street_suffix']))
        if street_fmt != last_street_fmt:
            ret[street_fmt] = collections.OrderedDict()
            last_primary = None
            last_unit = None
        if voter['address_number'] != last_primary:
            ret[street_fmt][voter['address_number']] = collections.OrderedDict()
            last_unit = None
        if voter['address_unit'] != last_unit:
            ret[street_fmt][voter['address_number']][voter['address_unit']] = []
        last_street_fmt = street_fmt
        last_primary = voter['address_number']
        last_unit = voter['address_unit']

        ret[street_fmt][voter['address_number']][voter['address_unit']].append({
            'vuid': voter['vuid'],
            'edr_str': prettify_yyyymmdd(voter['edr_date']),
            'suspense': voter['suspense'],
            'name_given': fix_latex_string('{name_first} {name_middle}'.format(**voter).strip().title()),
            'name_last': fix_latex_string(voter['name_last'].title()),
        })

    return ret


def create_report(voters, title, fname):
    latex.build_pdf(make_env(loader=FileSystemLoader('.')).get_template('vrlist-template.tex').render(
        records=hierarchize_and_latexify_voters(voters),
        num_voters=len(voters),
        title=fix_latex_string(title),
    )).save_to(fname)


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

    print()
    print('Do you want a PDF version? If so, enter a filename.')
    save_to = input()
    if save_to:
        create_report(voters, format_report_title(precinct, use_streets, len(precinct_streets), primary_pat, unit_pat), save_to)
        print('Saved.')
    else:
        print('All right. Goodbye!')


if __name__ == '__main__':
    main()
