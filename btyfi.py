from __future__ import print_function
import argparse
import autopep8
import re
from subprocess import check_output, STDOUT, CalledProcessError
import sys
from sys import exit

try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO


__version__ = version = '0.5a'


DEFAULT_IGNORE = 'E24'
DEFAULT_INDENT_SIZE = 4


def main():
    description = ("Tidy up (autopep8) only the lines in the files touched "
                   "in the git branch/commit.")
    epilog = ("Run before you do a commit to tidy, "
              "or against a branch before merging.")
    parser = argparse.ArgumentParser(description=description,
                                     epilog=epilog)
    parser.add_argument('rev',
                        help='commit or name of branch to compare against',
                        nargs='?')

    group = parser.add_mutually_exclusive_group(required=False)

    group.add_argument('--version',
                       help='print version number and exit',
                       action='store_true')
    group.add_argument('-v', '--verbose',
                       help='print which files/lines are being pep8d',
                       action='store_true')
    parser.add_argument('-d', '--diff', action='store_true', dest='diff',
                        help='print the diff for the fixed source')
    parser.add_argument('-p', '--pep8-passes', metavar='n',
                        default=-1, type=int,
                        help='maximum number of additional pep8 passes '
                        '(default: infinite)')
    parser.add_argument('-a', '--aggressive', action='count', default=0,
                        help='enable non-whitespace changes; '
                        'multiple -a result in more aggressive changes')
    parser.add_argument('--experimental', action='store_true',
                        help='enable experimental fixes')
    parser.add_argument('--exclude', metavar='globs',
                        help='exclude file/directory names that match these '
                        'comma-separated globs')
    parser.add_argument('--list-fixes', action='store_true',
                        help='list codes for fixes; '
                        'used by --ignore and --select')
    parser.add_argument('--ignore', metavar='errors', default='',
                        help='do not fix these errors/warnings '
                        '(default: {0})'.format(DEFAULT_IGNORE))
    parser.add_argument('--select', metavar='errors', default='',
                        help='fix only these errors/warnings (e.g. E4,W)')
    parser.add_argument('--max-line-length', metavar='n', default=79, type=int,
                        help='set maximum allowed line length '
                        '(default: %(default)s)')
    parser.add_argument('--indent-size', default=DEFAULT_INDENT_SIZE,
                        type=int, metavar='n',
                        help='number of spaces per indent level '
                             '(default %(default)s)')
    args = parser.parse_args()

    if args.version:
        print(version)
        exit(0)

    try:
        r = Radius.new(rev=args.rev, options=args)
    except NotImplementedError as e:
        print(e.message)
        exit(1)
    except CalledProcessError as c:
        # cut off usage of git diff and exit
        output = c.output.splitlines()[0]
        print(output)
        exit(c.returncode)

    r.pep8radius()


class Radius:

    def __init__(self, rev=None, options=None):
        self.rev = rev if rev is not None else self.current_branch()
        self.options = options if options else autopep8.parse_args([''])
        self.verbose = self.options.verbose
        self.diff = self.options.diff

        if not self.options.exclude:
            self.options.exclude = []
        if not self.options.ignore:
            self.options.ignore = DEFAULT_IGNORE.split(',')

        self.options.verbose = False
        self.options.in_place = True
        self.options.diff = True
        self.options.in_place = False  # turn off when testing
        self.filenames_diff = self.get_filenames_diff()

    @staticmethod
    def new(rev=None, options=None, vc=None):
        """
        Create subclass instance of Radius with correct version control

        e.g. RadiusGit if using git

        """
        if vc is None:
            vc = which_version_control()

        try:
            r = radii[vc]
        except KeyError:
            return NotImplementedError("Unknown version control system.")

        return r(rev=rev, options=options)

    def pep8radius(self):
        "Better than you found it. autopep8 the diff lines in each py file"
        n = len(self.filenames_diff)

        self.p('Applying autopep8 to touched lines in %s file(s).'
               % len(self.filenames_diff))

        total_lines_changed = 0
        for i, f in enumerate(self.filenames_diff, start=1):
            self.p('%s/%s: %s: ' % (i, n, f), end='')

            pep8_diff = self.pep8radius_file(f, last_char=' ')
            lines_changed = udiff_lines_changes(pep8_diff)
            total_lines_changed += lines_changed
            self.p('fixed %s lines.' % lines_changed)

            if self.diff and  pep8_diff:
                #possibly we want to print a restricted version of diff
                print( pep8_diff)

        self.p('fixed %s lines in %s files.' % (total_lines_changed, i))

    def pep8radius_file(self, f, last_char='\n'):
        "Apply autopep8 to the diff lines of file f"
        # Presumably if was going to raise would have at get_filenames_diff
        cmd = self.file_diff_cmd(f)
        diff = check_output(cmd).decode('utf-8')

        pep8_diff = []
        for start, end in self.line_numbers_from_file_diff(diff):
            pep8_diff.append(self.autopep8_line_range(f, start, end))
            self.p('.', end='')
        self.p('', end=last_char)

        # reversed since pep8radius applies backwards
        pep8_diff = [diff for diff in pep8_diff if diff][::-1]

        for i, diff in enumerate(pep8_diff[1:], start=1):
            pep8_diff[i] = ''.join(diff.splitlines(True)[2:  ])

        # TODO possibly remove first two lines of not first diffs
        return '\n'.join(pep8_diff)

    def autopep8_line_range(self, f, start , end ):
        "Apply autopep8 between start and end of file f"
        self.options.line_range = [start, end]
        return autopep8.fix_file(f, self.options)

    def get_filenames_diff(self):
        "Get the py files which have been changed since rev"

        cmd = self.filenames_diff_cmd()

        # Note: This may raise a CalledProcessError
        diff_files_b = check_output(cmd, stderr=STDOUT)

        diff_files_u = diff_files_b.decode('utf-8')
        diff_files = self.parse_diff_filenames(diff_files_u)

        return [f for f in diff_files if f.endswith('.py')]

    def line_numbers_from_file_diff(self, diff):
        "Potentially this is vc specific (if not using udiff)"
        return line_numbers_from_file_udiff(diff)

    def p(self, something_to_print, end=None):
        if self.verbose:
            print(something_to_print, end=end)
            sys.stdout.flush()


#####   udiff parsing   #####
#############################

def line_numbers_from_file_udiff(udiff):
    """
    Parse a udiff, return iterator of tuples of (start, end) line numbers.

    Note: returned in descending order (as autopep8 can +- lines)

    """
    lines_with_line_numbers = [line for line in udiff.splitlines()
                               if line.startswith('@@')][::-1]
    # Note: we do this backwards, as autopep8 can add/remove lines

    for u in lines_with_line_numbers:
        start, end = map(int, udiff_line_start_and_end(u))
        yield (start, end)


def udiff_line_start_and_end(u):
    """
    Extract start line and end from udiff line

    Example
    -------
    '@@ -638,9 +638,17 @@ class GroupBy(PandasObject):'
    Returns the start line 638 and end line (638 + 17) (the lines added).

    """
    # I *think* we only care about the + lines?
    line_numbers = re.findall('(?<=[+])\d+,\d+', u)
    line_numbers = line_numbers[0].split(',')
    line_numbers = list(map(int, line_numbers))

    PADDING_LINES = 3  # TODO perhaps this is configuarable?

    return (line_numbers[0] + PADDING_LINES,
            sum(line_numbers) - PADDING_LINES)

def udiff_lines_changes(u):
    """
    Count line changes in udiff

    'fixed/btyfi.py\n@@ -157,7 +157,11 @@' will extract 7 - 2 * PADDING_LINES

    """
    removed_changes = re.findall('\n@@\s+\-(\d+,\d+)', u)
    removed_changes = [map(int, c.split(',')) for c in removed_changes]

    PADDING_LINES = 3  # TODO perhaps this is configuarable?
    padding = 2 * PADDING_LINES

    return sum(c[1] - padding for c in removed_changes)


#####   vc specific   #####
###########################

class RadiusGit(Radius):

    def current_branch(self):
        output = check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        return output.strip().decode('utf-8')

    def file_diff_cmd(self, f):
        "Get diff for one file, f"
        return ['git', 'diff', self.rev, f]

    def filenames_diff_cmd(self):
        "Get the names of the py files in diff"
        return ['git', 'diff', self.rev, '--name-only']

    @staticmethod
    def parse_diff_filenames(diff_files):
        "Parse the output of filenames_diff_cmd"
        return diff_files.splitlines()


class RadiusHg(Radius):

    def current_branch(self):
        output = check_output(["hg", "id", "-b"])
        return output.strip().decode('utf-8')

    def file_diff_cmd(self, f):
        "Get diff for one file, f"
        return ['hg', 'diff', '-c', self.rev, f]

    def filenames_diff_cmd(self):
        "Get the names of the py files in diff"
        return ["hg", "diff", "--stat", "-c", self.rev]

    @staticmethod
    def parse_diff_filenames(diff_files):
        "Parse the output of filenames_diff_cmd"
        # TODO promote this to Radius ?
        return re.findall('(?<=[$| |\n]).*\.py', diff_files)


radii = {'git': RadiusGit, 'hg': RadiusHg}


def using_git():
    try:
        git_log = check_output(["git", "log"], stderr=STDOUT)
        return True
    except CalledProcessError:
        return False


def using_hg():
    try:
        hg_log = check_output(["hg", "log"], stderr=STDOUT)
        return True
    except CalledProcessError:
        return False


def which_version_control():
    """
    Try to see if they are using git or hg.
    return git, hg or raise NotImplementedError.

    """
    if using_git():
        return 'git'

    if using_hg():
        return 'hg'

    # Not supported (yet)
    raise NotImplementedError("Unknown version control system. "
                              "Ensure you're in the project directory.")


if __name__ == "__main__":
    main()
