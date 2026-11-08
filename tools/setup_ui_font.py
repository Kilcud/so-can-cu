#!/usr/bin/env python3
"""Opt-in download of Nunito from Google Fonts. No application data is sent.

This package intentionally contains no font binaries. Run this script only
when allowed to access the public Internet. All font requests at runtime then
remain on localhost. A failed download leaves the existing file untouched.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://raw.githubusercontent.com/google/fonts/main/ofl/nunito/'
LIMIT = 4 * 1024 * 1024

def fetch(filename: str) -> bytes:
    req = Request(BASE + filename, headers={'User-Agent':'SoCanCu-FontSetup/1.0'})
    with urlopen(req, timeout=30) as response:
        data = response.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError('The font resource exceeded the configured size limit.')
    return data

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--yes', action='store_true', help='Allow a one-time Internet download.')
    args = p.parse_args()
    if not args.yes:
        answer = input('Download Nunito from Google Fonts now? [y/N] ').strip().lower()
        if answer not in ('y','yes'):
            print('No files changed. The application uses a locally installed fallback font.')
            return 0
    try:
        data = fetch('Nunito%5Bwght%5D.ttf')
        license_text = fetch('OFL.txt')
        if data[:4] not in (b'\x00\x01\x00\x00', b'OTTO', b'ttcf'):
            raise ValueError('Downloaded data is not an expected font format.')
        target = ROOT / 'static' / 'fonts'
        target.mkdir(exist_ok=True)
        tmp = target / 'nunito.ttf.part'
        tmp.write_bytes(data)
        tmp.replace(target / 'nunito.ttf')
        (target / 'OFL-Nunito.txt').write_bytes(license_text)
        print('Nunito installed for this application. Refresh the browser.')
        return 0
    except Exception as exc:
        print('Font setup did not finish: ' + str(exc))
        print('The application still runs with a locally installed fallback font.')
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
