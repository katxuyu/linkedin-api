#!/usr/bin/env python3
"""
Convert browser extension cookies to Playwright format for database storage.

Usage:
    python scripts/convert_cookies_for_db.py < cookies.json
    or
    python scripts/convert_cookies_for_db.py --cookies-file cookies.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.cookie_sanitizer import sanitize_cookies  # noqa: E402


def main():
    parser = argparse.ArgumentParser(
        description="Convert browser extension cookies to Playwright format for database storage"
    )
    parser.add_argument(
        "--cookies-file",
        type=str,
        help="Path to JSON file containing cookies array"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file path (default: stdout)"
    )
    
    args = parser.parse_args()
    
    if args.cookies_file:
        with open(args.cookies_file, "r") as f:
            cookies = json.load(f)
    else:
        cookies = json.load(sys.stdin)
    
    if not isinstance(cookies, list):
        print("Error: Cookies must be a JSON array", file=sys.stderr)
        sys.exit(1)
    
    playwright_cookies = sanitize_cookies(cookies)
    if not playwright_cookies:
        print("Error: No valid cookies after sanitization", file=sys.stderr)
        sys.exit(1)
    json_string = json.dumps(playwright_cookies, indent=2)
    
    if args.output:
        with open(args.output, "w") as f:
            f.write(json_string)
        print(f"Converted cookies written to {args.output}")
        print(f"\nTo store in database, use this JSON string:")
        print(json.dumps(playwright_cookies))
    else:
        print("=" * 80)
        print("CONVERTED COOKIES (Playwright format)")
        print("=" * 80)
        print(json_string)
        print("\n" + "=" * 80)
        print("JSON STRING FOR DATABASE (single line)")
        print("=" * 80)
        print(json.dumps(playwright_cookies))
        print("\n" + "=" * 80)
        print("IMPORTANT NOTES:")
        print("=" * 80)
        print("1. Store the JSON string (single line) in the 'cookies' column")
        print("2. The system will automatically encrypt it using FERNET")
        print("3. Most important cookie: 'li_at' (LinkedIn authentication token)")
        print("4. Make sure to also store a valid 'user_agent' string")


if __name__ == "__main__":
    main()
