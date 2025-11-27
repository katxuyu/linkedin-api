#!/usr/bin/env python3
"""
Convert browser extension cookies to encrypted format for direct database insertion.

This script:
1. Converts browser extension cookies to Playwright format
2. Converts to JSON string
3. Encrypts using FERNET (same as the application)
4. Outputs the encrypted string ready for database insertion

Usage:
    python scripts/prepare_cookies_for_db.py < cookies.json
    or
    python scripts/prepare_cookies_for_db.py --cookies-file cookies.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.settings import FERNET
from app.utils.cookie_sanitizer import sanitize_cookies  # noqa: E402


def encrypt_cookies_for_db(cookies_json_string: str) -> str:
    """
    Encrypt cookies JSON string using FERNET (same as application).
    
    Args:
        cookies_json_string: JSON string representation of cookies array
        
    Returns:
        Encrypted string ready for database insertion
    """
    encrypted_bytes = FERNET.encrypt(cookies_json_string.encode())
    return encrypted_bytes.decode()


def main():
    parser = argparse.ArgumentParser(
        description="Convert and encrypt browser extension cookies for database storage"
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
    parser.add_argument(
        "--show-json",
        action="store_true",
        help="Also show the JSON string before encryption"
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
    json_string = json.dumps(playwright_cookies)
    encrypted_string = encrypt_cookies_for_db(json_string)
    
    output_lines = []
    output_lines.append("=" * 80)
    output_lines.append("ENCRYPTED COOKIES FOR DATABASE")
    output_lines.append("=" * 80)
    output_lines.append("")
    output_lines.append("Copy this encrypted string and paste it into the 'cookies' column:")
    output_lines.append("")
    output_lines.append(encrypted_string)
    output_lines.append("")
    output_lines.append("=" * 80)
    output_lines.append("IMPORTANT NOTES:")
    output_lines.append("=" * 80)
    output_lines.append("1. This is the ENCRYPTED value - store it directly in the database")
    output_lines.append("2. The system will automatically decrypt it when reading")
    output_lines.append("3. Most important cookie: 'li_at' (LinkedIn authentication token)")
    output_lines.append("4. Make sure to also store a valid 'user_agent' string")
    output_lines.append("5. The FERNET_KEY from your environment must match for decryption")
    
    if args.show_json:
        output_lines.append("")
        output_lines.append("=" * 80)
        output_lines.append("JSON STRING (before encryption):")
        output_lines.append("=" * 80)
        output_lines.append(json.dumps(playwright_cookies, indent=2))
    
    output_text = "\n".join(output_lines)
    
    if args.output:
        with open(args.output, "w") as f:
            f.write(output_text)
        print(f"Output written to {args.output}")
    else:
        print(output_text)


if __name__ == "__main__":
    main()
