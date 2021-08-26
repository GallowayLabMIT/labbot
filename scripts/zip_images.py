"""
Script that processes directories and zips dated folders together.

This is chiefly useful for microscopy images. There tend to be thousands
and thousands of files created by microscopy data, which puts strain
on cloud syncing systems.

This sytem automatically zips folders named like YYYY.MM.DD, YYYY-MM-DD, etc
after a certain number of days have elapsed.

Additionally, there is the ability to override this default behavior by using
_indicators_: special files that are included in a directory to override.

Currently, there are two indicators: 'zip' ('zip.txt') and 'nozip.txt' ('nozip.txt')
which will unconditionally zip the containing folder or never zip it.
"""
import argparse
import binascii
from datetime import date
import json
import os
from pathlib import Path
import re
import shutil
import sys
import zipfile

parser = argparse.ArgumentParser(
        description='Configured to automatically zip files based on elapsed time')
parser.add_argument('--config', type=Path, default=Path('~/.zipimages.json').expanduser())
parser.add_argument('--retries', type=int, default=5)
parser.add_argument('--verbose', action='store_true', default=False)

def print_error_usage(error: str):
    """Prints an error to standard error and exits with the usage statement"""
    print(error, file=sys.stderr)
    parser.print_usage(sys.stderr)
    sys.exit(1)

def validate_zip_file(zipfilename: Path, basedir: Path, verbose=False) -> bool:
    """
    Validates that the contents of a zip file matches the
    files within basedir.
    """
    with zipfile.ZipFile(zipfilename, 'r') as current_zip:
        # Check all headers
        invalid_file = current_zip.testzip()
        if invalid_file is not None:
            print(f'Invalid file found in {str(zipfilename)}: {invalid_file}!')
            return False
        # Check that file hashes match on-disk
        for inner_file in current_zip.infolist():
            if verbose:
                print(f'Validating {inner_file.filename}: ', end='')
            zip_crc = inner_file.CRC
            with open(basedir / inner_file.filename, 'rb') as filesystem_file:
                filesystem_crc = binascii.crc32(filesystem_file.read()) & 0xffffffff
            if verbose:
                print(f'zip:{zip_crc}, filesystem:{zip_crc}')
            if zip_crc != filesystem_crc:
                print(
                    f'File {str(basedir / inner_file.filename)} does not match compressed file in {str(zipfilename)}')
                return False
    return True

if __name__ == '__main__':
    args = parser.parse_args()
    try:
        with open(args.config, 'r') as config_file:
            config = json.load(config_file)
    except FileNotFoundError:
        print_error_usage(f'Unable to locate config file: {args.config}')

    # Validate config
    for key in ['zip_delay_days', 'monitor_locations', 'indicators']:
        if key not in config:
            print_error_usage(f"Must include a '{key}' key in the configuration!")
    for key in ['nozip', 'zip']:
        if key not in config['indicators']:
            print_error_usage(f"Must include an indicator filename for the '{key}' indicator")

    monitor_locations = [
            Path(d).expanduser().resolve(strict=True) for d in config['monitor_locations']]

    # Actually start processing
    current_zip = None
    zip_filename = Path()
    for start_root in monitor_locations:
        for root, dirs, files in os.walk(start_root, topdown=True, followlinks=True):
            # Skip processing this folder and its descendents if it contains the nozip marker
            # and we are not processing a zip file
            if config['indicators']['nozip'] in files and current_zip is None:
                del dirs[:]
                continue

            dirpath = Path(root)
            if current_zip is not None:
                # Do zip processing. First, check if we are outside the zip base path
                if base_path not in dirpath.parents:
                    current_zip.close()
                    print('validating...', end='')
                    if not validate_zip_file(zip_filename, base_path, args.verbose):
                        print_error_usage('Validation failed.')
                    current_zip = None
                    print('done!')
                    shutil.rmtree(base_path)

            # If we aren't processing a zip file yet, do the zip check
            if current_zip is None:
                match = re.match(r'^(\d{4})([._-]?)(\d{2})\2(\d{2})', dirpath.name)
                if match is None:
                    # Not a date format we recognize
                    continue
                # Create a datetime object
                folder_date = date(
                        int(match.group(1)),
                        int(match.group(3)),
                        int(match.group(4)))
                if (config['indicators']['zip'] in files or
                    (date.today() - folder_date).days > config['zip_delay_days']):

                    zip_filename = dirpath.parent / (dirpath.name + '.zip')
                    print(f"Creating zip file {str(zip_filename)}...",
                          end='')
                    current_zip = zipfile.ZipFile(zip_filename, 'w')
                    base_path = dirpath

            if current_zip is not None:
                for filename in files:
                    full_filename = dirpath / filename
                    num_retries = 0
                    while num_retries < args.retries:
                        try:
                            current_zip.write(
                                full_filename,
                                arcname=full_filename.relative_to(base_path))
                            break
                        except OSError as e:
                            print('OS error: {str(e)}. Retrying...')
                        num_retries += 1
                    if num_retries == args.retries:
                        print_error_usage(
                            'Failed to read file after {args.retries} retries. Exiting :(')

        if current_zip is not None:
            current_zip.close()
            print('validating...', end='')
            if not validate_zip_file(zip_filename, base_path, args.verbose):
                print_error_usage('Validation failed.')
            print('done!')
            shutil.rmtree(base_path)
            current_zip = None
