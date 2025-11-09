#!/usr/bin/env python3
"""
ADP Paystub PDF Data Extractor

Extracts structured data from ADP paystub PDFs and outputs to JSON or CSV format.
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import fnmatch

try:
    import pdfplumber
except ImportError:
    print("Error: pdfplumber is not installed. Please run: pip install pdfplumber", file=sys.stderr)
    sys.exit(1)


# Field ordering for CSV output
FIELD_ORDER = [
    "Pay Date",
    "Earnings Regular",
    "Earnings Rsu",
    "Taxable Wages This Period",
    "Deductions Federal Income Tax",
    "Deductions Social Security Tax",
    "Deductions Medicare Tax",
    "Deductions Medicare Surtax",
    "Deductions GA State Income Tax",
    "Deductions Rsu Net Value",
    "Deductions Accident",
    "Deductions Ad&D",
    "Deductions Ad&D Spouse",
    "Deductions After-Tax Ded",
    "Deductions Crit Ill Spouse",
    "Deductions Critical Illnes",
    "Deductions Dental Pretax",
    "Deductions Ee Life",
    "Deductions Espp",
    "Deductions Hsa",
    "Deductions Legal",
    "Deductions Medical Pretax",
    "Deductions Non Ca Std",
    "Deductions Roth 401K",
    "Deductions Spouse Life",
    "Deductions Vision Pretax",
    "Deductions Basic Life Inc",
    "Other Benefits Current Match",
    "Other Benefits Espp .*",
    "Other Benefits Ytd 401K Match",
    "Pay Period Beginning",
    "Pay Period Ending",
]


def clean_amount(amount_str: str) -> str:
    """
    Clean and format an amount string from the PDF.
    ADP formats amounts like "5 432 10" which should be "5432.10"
    The last two digits are cents.
    """
    # Remove spaces, commas, asterisks
    cleaned = amount_str.replace(' ', '').replace(',', '').replace('*', '').strip()
    cleaned = cleaned.rstrip('\n')

    if not cleaned:
        return ""

    # Check if it starts with a minus sign
    is_negative = cleaned.startswith('-')
    if is_negative:
        cleaned = cleaned[1:]

    # If we have at least 2 digits, insert decimal point before last 2 digits
    if cleaned and len(cleaned) >= 2 and cleaned.isdigit():
        # Insert decimal point before last 2 digits
        cleaned = cleaned[:-2] + '.' + cleaned[-2:]

    # Add back the negative sign if needed
    if is_negative:
        cleaned = '-' + cleaned

    return cleaned


def extract_first_amount_from_line(line: str, description: str) -> Optional[str]:
    """
    Extract the first amount from a line after the description.
    ADP format: "Description Amount1 Amount2" where amounts are space-separated digits.
    Amounts can be: "50" or "123 45" or "1 234 56" format.
    """
    # Remove description from line
    if description and description in line:
        remainder = line.split(description, 1)[1].strip()
    else:
        remainder = line.strip()

    # Split by spaces
    tokens = remainder.split()
    if not tokens:
        return None

    # Try 3 tokens first (e.g., "1 234 56" or "-1 234 56")
    if len(tokens) >= 3:
        potential = ' '.join(tokens[:3])
        # Check if it's format: X XXX XX (1-4 digits, 3 digits, 2 digits)
        if re.match(r'-?\d{1,4}\s\d{3}\s\d{2}\*?$', potential):
            return clean_amount(potential)

    # Try 2 tokens (e.g., "123 45" or "-123 45")
    if len(tokens) >= 2:
        potential = ' '.join(tokens[:2])
        # Check if it's format: XXX XX (1-4 digits, 2 digits)
        if re.match(r'-?\d{1,4}\s\d{2}\*?$', potential):
            return clean_amount(potential)

    # Try 1 token (e.g., "50")
    if len(tokens) >= 1:
        potential = tokens[0]
        if re.match(r'-?\d{2}\*?$', potential):
            return clean_amount(potential)

    return None


def extract_amounts_from_line(line: str, description: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract both "this period" and YTD amounts from a line after the description.
    Returns a tuple: (this_period_amount, ytd_amount)

    For earnings lines: "Description Rate Hours ThisPeriod YTD"
    For deduction lines: "Description ThisPeriod YTD"
    """
    # Remove description from line
    if description and description in line:
        remainder = line.split(description, 1)[1].strip()
    else:
        remainder = line.strip()

    # Split by spaces
    tokens = remainder.split()
    if not tokens:
        return (None, None)

    # Helper function to try extracting an amount starting at a given token index
    def try_extract_at(start_idx: int) -> Optional[str]:
        if start_idx >= len(tokens):
            return None

        # Try 4 tokens (e.g., "1 040 968 50" for amounts over 999,999.99)
        if start_idx + 3 < len(tokens):
            potential = ' '.join(tokens[start_idx:start_idx+4])
            if re.match(r'-?\d{1,4}\s\d{3}\s\d{3}\s\d{2}\*?$', potential):
                return clean_amount(potential)

        # Try 3 tokens (e.g., "1 234 56" or "-1 234 56")
        if start_idx + 2 < len(tokens):
            potential = ' '.join(tokens[start_idx:start_idx+3])
            if re.match(r'-?\d{1,4}\s\d{3}\s\d{2}\*?$', potential):
                return clean_amount(potential)

        # Try 2 tokens (e.g., "123 45" or "-123 45")
        if start_idx + 1 < len(tokens):
            potential = ' '.join(tokens[start_idx:start_idx+2])
            if re.match(r'-?\d{1,4}\s\d{2}\*?$', potential):
                return clean_amount(potential)

        # Try 1 token (e.g., "50")
        if start_idx < len(tokens):
            potential = tokens[start_idx]
            if re.match(r'-?\d{2}\*?$', potential):
                return clean_amount(potential)

        return None

    # Extract the first amount (this period)
    this_period = None
    this_period_end_idx = 0

    # Try to find the first amount
    idx = 0
    while idx < len(tokens):
        # Try 4 tokens (e.g., "1 040 968 50")
        if idx + 3 < len(tokens):
            potential = ' '.join(tokens[idx:idx+4])
            if re.match(r'-?\d{1,4}\s\d{3}\s\d{3}\s\d{2}\*?$', potential):
                this_period = clean_amount(potential)
                this_period_end_idx = idx + 4
                break

        # Try 3 tokens
        if idx + 2 < len(tokens):
            potential = ' '.join(tokens[idx:idx+3])
            if re.match(r'-?\d{1,4}\s\d{3}\s\d{2}\*?$', potential):
                this_period = clean_amount(potential)
                this_period_end_idx = idx + 3
                break

        # Try 2 tokens
        if idx + 1 < len(tokens):
            potential = ' '.join(tokens[idx:idx+2])
            if re.match(r'-?\d{1,4}\s\d{2}\*?$', potential):
                this_period = clean_amount(potential)
                this_period_end_idx = idx + 2
                break

        # Try 1 token
        potential = tokens[idx]
        if re.match(r'-?\d{2}\*?$', potential):
            this_period = clean_amount(potential)
            this_period_end_idx = idx + 1
            break

        idx += 1

    # Extract the second amount (YTD) starting after the first amount
    ytd = None
    if this_period is not None:
        ytd = try_extract_at(this_period_end_idx)

    return (this_period, ytd)


def extract_pay_period_dates(text: str) -> Dict[str, Optional[str]]:
    """Extract pay period beginning and ending dates."""
    dates = {
        "Pay Period Beginning": None,
        "Pay Period Ending": None,
        "Pay Date": None
    }

    # Match patterns like "Period Beginning: 01/01/2024"
    beginning_match = re.search(r'Period Beginning:\s*(\d{1,2}/\d{1,2}/\d{4})', text)
    if beginning_match:
        dates["Pay Period Beginning"] = beginning_match.group(1)

    ending_match = re.search(r'Period Ending:\s*(\d{1,2}/\d{1,2}/\d{4})', text)
    if ending_match:
        dates["Pay Period Ending"] = ending_match.group(1)

    pay_date_match = re.search(r'Pay Date:\s*(\d{1,2}/\d{1,2}/\d{4})', text)
    if pay_date_match:
        dates["Pay Date"] = pay_date_match.group(1)

    return dates


def extract_taxable_wages(text: str) -> Dict[str, Optional[str]]:
    """Extract taxable wages for this period."""
    result = {}

    # Look for the line with taxable wages
    lines = text.split('\n')
    for i, line in enumerate(lines):
        if 'federal taxable wages this period' in line.lower():
            # The amount might be on the same line after "are" or on the next few lines
            # Check same line first
            if ' are ' in line.lower():
                parts = line.lower().split(' are ')
                if len(parts) > 1:
                    amount_part = parts[1].strip()
                    # Remove $ if present
                    amount_part = amount_part.replace('$', '').strip()
                    if amount_part:
                        amount = extract_first_amount_from_line(amount_part, '')
                        if amount:
                            result["Taxable Wages This Period"] = amount
                            break

            # Also check if there's a $ amount on the same line (might be at the end)
            if '$' in line:
                amount_part = line.split('$')[-1].strip()
                amount = extract_first_amount_from_line(amount_part, '')
                if amount:
                    result["Taxable Wages This Period"] = amount
                    break

            # Check next few lines for an amount starting with $ (e.g., "$4 500 00")
            for j in range(i+1, min(i+4, len(lines))):
                next_line = lines[j].strip()
                if '$' in next_line:
                    # Extract everything after the $
                    amount_part = next_line.split('$')[-1].strip()
                    amount = extract_first_amount_from_line(amount_part, '')
                    if amount:
                        result["Taxable Wages This Period"] = amount
                        break
            if "Taxable Wages This Period" in result:
                break

    return result


def parse_earnings_section(text: str) -> Dict[str, str]:
    """Parse the Earnings section."""
    earnings = {}

    # Look for earnings section - typically has "rate hours this period year to date"
    # Then lines like "Regular 5000 00 80 00 5 000 00 5 000 00"
    # Format: Description Rate Hours ThisPeriod YTD
    lines = text.split('\n')

    in_earnings = False
    for i, line in enumerate(lines):
        # Start of earnings section
        if 'rate' in line.lower() and 'hours' in line.lower() and 'this period' in line.lower():
            in_earnings = True
            continue

        # End of earnings section (when we hit other sections)
        if in_earnings and any(keyword in line for keyword in ['Gross Pay', 'Federal Income Tax', 'Deductions', 'Net Check']):
            break

        if in_earnings and line.strip():
            # Try to parse earnings lines
            # Pattern: Description followed by numbers
            # Extract description (letters and spaces at the start)
            desc_match = re.match(r'^([A-Za-z\s]+)', line)
            if desc_match:
                description = desc_match.group(1).strip()
                # Skip non-earning lines like "Net Pay" and "Net Check"
                if description in ['Net Pay', 'Net Check']:
                    continue
                # For earnings, need to skip rate and hours and get the 3rd and 4th amounts
                # However, some earnings (like RSU) don't have rate/hours, just this period and YTD
                remainder = line.split(description, 1)[1].strip() if description in line else line.strip()
                tokens = remainder.split()

                # Extract all amounts in order
                amounts = []
                idx = 0
                consecutive_non_numbers = 0
                while idx < len(tokens):
                    # Try 4 tokens (e.g., "1 040 968 50")
                    if idx + 3 < len(tokens):
                        potential = ' '.join(tokens[idx:idx+4])
                        if re.match(r'-?\d{1,4}\s\d{3}\s\d{3}\s\d{2}\*?$', potential):
                            amounts.append(clean_amount(potential))
                            idx += 4
                            consecutive_non_numbers = 0
                            continue

                    # Try 3 tokens
                    if idx + 2 < len(tokens):
                        potential = ' '.join(tokens[idx:idx+3])
                        if re.match(r'-?\d{1,4}\s\d{3}\s\d{2}\*?$', potential):
                            amounts.append(clean_amount(potential))
                            idx += 3
                            consecutive_non_numbers = 0
                            continue

                    # Try 2 tokens
                    if idx + 1 < len(tokens):
                        potential = ' '.join(tokens[idx:idx+2])
                        if re.match(r'-?\d{1,4}\s\d{2}\*?$', potential):
                            amounts.append(clean_amount(potential))
                            idx += 2
                            consecutive_non_numbers = 0
                            continue

                    # Try 1 token
                    potential = tokens[idx]
                    if re.match(r'-?\d{2}\*?$', potential):
                        amounts.append(clean_amount(potential))
                        idx += 1
                        consecutive_non_numbers = 0
                        continue

                    # Not a number - check if it looks like a new field name
                    # If we see 2+ consecutive words (likely a new field), stop extraction
                    consecutive_non_numbers += 1
                    if consecutive_non_numbers >= 2:
                        # Likely encountered a new field name, stop extracting
                        break

                    idx += 1

                # Determine if this is a regular earnings line (with rate/hours) or RSU-style (without)
                # Regular lines have at least 4 amounts: Rate, Hours, This Period, YTD
                # RSU lines have 2 amounts: This Period, YTD
                # Lines with only YTD have 1 amount
                if len(amounts) >= 4:
                    # Regular earnings: skip rate and hours, use 3rd and 4th
                    earnings[f"Earnings {description}"] = amounts[2]
                    earnings[f"Earnings {description} YTD"] = amounts[3]
                elif len(amounts) == 2:
                    # RSU-style earnings: first is this period, second is YTD
                    earnings[f"Earnings {description}"] = amounts[0]
                    earnings[f"Earnings {description} YTD"] = amounts[1]
                elif len(amounts) == 1:
                    # Only YTD value present (no activity this period)
                    earnings[f"Earnings {description} YTD"] = amounts[0]
                elif len(amounts) == 3:
                    # Could be: Rate, Hours, ThisPeriod (with no YTD)
                    # Or: Hours, ThisPeriod, YTD (with no rate)
                    # Assume it's the latter for now
                    earnings[f"Earnings {description}"] = amounts[1]
                    earnings[f"Earnings {description} YTD"] = amounts[2]

    return earnings


def parse_deductions_section(text: str) -> Dict[str, str]:
    """Parse the Deductions section (taxes and other deductions)."""
    deductions = {}

    lines = text.split('\n')

    # Common deduction names to look for
    # NOTE: Order matters! More specific names must come before general ones
    # (e.g., "Ad&D Spouse" before "Ad&D", "Crit Ill Spouse" before any other Crit Ill)
    # NOTE: "State Income Tax" is intentionally excluded because it's a substring of "GA State Income Tax"
    deduction_names = [
        'Federal Income Tax',
        'Social Security Tax',
        'Medicare Tax',
        'Medicare Surtax',
        'GA State Income Tax',
        'Rsu Net Value',
        'Basic Life Inc',
        'Accident',
        'Ad&D Spouse',  # Must come before 'Ad&D'
        'Ad&D',
        'After-Tax Ded',
        'Crit Ill Spouse',  # Must come before 'Critical Illnes'
        'Critical Illnes',
        'Dental Pretax',
        'Ee Life',
        'Espp',
        'Hsa',
        'Legal',
        'Medical Pretax',
        'Non Ca Std',
        'Roth 401K',
        'Spouse Life',
        'Vision Pretax',
    ]

    # Track if we're past the main tax deductions (which typically have "this period" values)
    # After main taxes, benefit-related deductions often only show YTD values
    in_other_benefits_or_ytd_only_section = False
    # NOTE: "Espp" is NOT in this list because the "Espp" deduction line has both "this period" and YTD values
    # Only "Espp *" pattern matches in Other Benefits are YTD-only
    benefit_deductions_that_may_be_ytd_only = ['Basic Life Inc', 'Accident', 'Ad&D', 'Ad&D Spouse', 'After-Tax Ded', 'Crit Ill Spouse', 'Critical Illnes', 'Dental Pretax', 'Ee Life', 'Hsa', 'Legal', 'Medical Pretax', 'Non Ca Std', 'Roth 401K', 'Spouse Life', 'Vision Pretax']
    # Rsu Net Value special case: when it appears with single value on non-RSU paystubs, it's YTD
    always_ytd_when_single = ['Rsu Net Value']

    for i, line in enumerate(lines):
        # After we see "Other Benefits and", treat single values as YTD
        if 'Other Benefits and' in line or 'this period total to date' in line.lower():
            in_other_benefits_or_ytd_only_section = True

        # Find ALL matching deduction names on this line (some lines have multiple deductions)
        # Sort by position to process them in order
        matches = []
        for deduction_name in deduction_names:
            if deduction_name in line:
                pos = line.find(deduction_name)
                # Special check for "Espp": don't match if it's part of "Espp Refund" or "Espp <date>" or "Espp <positive_amount>"
                if deduction_name == 'Espp':
                    # Check if "Espp Refund" is at this specific position
                    if line[pos:pos+11] == 'Espp Refund':
                        # Skip this match
                        continue
                    # Check if this specific "Espp" is followed by a date pattern (e.g., "Espp 3/15-9/14")
                    # or a positive amount (e.g., "Espp 1 234 56")
                    # which is an Other Benefit, not a Deduction
                    # Deductions always have a negative sign (e.g., "Espp -100 00 100 00")
                    # Look at the text right after this "Espp" match
                    text_after = line[pos+4:pos+20]  # Get text after "Espp"
                    if re.match(r'\s+\d+/', text_after):
                        # Skip this match - it's an Other Benefit with date
                        continue
                    # Check if followed by a positive amount (digits without negative sign)
                    # This is an Other Benefit YTD value
                    if re.match(r'\s+\d+\s+\d+', text_after):
                        # Skip this match - it's an Other Benefit YTD
                        continue
                matches.append((pos, deduction_name))
        
        # Sort by position (process left to right)
        matches.sort()

        # Process each matched deduction on this line
        for best_match_position, matched_deduction in matches:
            # Skip if we've already processed this deduction
            if f"Deductions {matched_deduction}" in deductions or f"Deductions {matched_deduction} YTD" in deductions:
                continue
            
            deduction_name = matched_deduction
            this_period, ytd = extract_amounts_from_line(line, deduction_name)

            # Special handling for Social Security Tax when only one value
            # This happens when employee maxes out Social Security contributions
            if deduction_name == 'Social Security Tax' and this_period and not ytd:
                # Check if this is positive (indicating it's likely a YTD value, not "this period")
                # Social Security "this period" is always negative or has a '-' sign
                if not this_period.startswith('-'):
                    # This is YTD, not "this period"
                    ytd = this_period
                    this_period = None

            # Special handling for "Rsu Net Value" - when single value, it's always YTD
            if this_period and not ytd and deduction_name in always_ytd_when_single:
                ytd = this_period
                this_period = None
            # For benefit deductions that only have one value, treat as YTD
            # This happens in RSU paystubs where benefits show cumulative values only
            elif this_period and not ytd and deduction_name in benefit_deductions_that_may_be_ytd_only:
                # Check if we're in a section where single values should be YTD
                # OR if we've already seen an indicator we're in the YTD-only benefit section
                if in_other_benefits_or_ytd_only_section:
                    ytd = this_period
                    this_period = None
                # Also check: has this specific field appeared before with two values?
                # If this is the first time seeing it with one value, it's likely YTD
                elif f"Deductions {deduction_name} YTD" not in deductions:
                    # First encounter and only one value - assume YTD
                    ytd = this_period
                    this_period = None

            if this_period:
                deductions[f"Deductions {deduction_name}"] = this_period
            if ytd:
                deductions[f"Deductions {deduction_name} YTD"] = ytd

            # After processing a benefit deduction with only YTD, mark that we're in YTD-only section
            if deduction_name in benefit_deductions_that_may_be_ytd_only and ytd and not deductions.get(f"Deductions {deduction_name}"):
                in_other_benefits_or_ytd_only_section = True

    return deductions


def parse_other_benefits_section(text: str) -> Dict[str, str]:
    """Parse the Other Benefits and Information section."""
    benefits = {}

    lines = text.split('\n')

    # Common benefit names to look for (supports glob patterns)
    benefit_names = [
        'Current Match',
        'Espp *',  # Matches "Espp 3/15-9/14", "Espp 9/15-3/14", etc.
        # Note: We don't capture standalone "Espp <amount>" as it's just a summary line
        'Ytd 401K Match',
        'Sick Earned Bal',
    ]

    for line in lines:
        for benefit_pattern in benefit_names:
            # Check for exact match or glob pattern match
            matched_name = None
            if '*' in benefit_pattern or '?' in benefit_pattern or '[' in benefit_pattern:
                # Use glob pattern matching
                # Extract the benefit name from the line
                words = line.split()
                for i in range(len(words)):
                    # Try matching progressively longer sequences
                    for j in range(i+1, min(i+5, len(words)+1)):
                        candidate = ' '.join(words[i:j])
                        if fnmatch.fnmatch(candidate, benefit_pattern):
                            # Additional validation: make sure the candidate doesn't include a negative number
                            # (which would indicate it's a deduction, not a benefit)
                            # Check if any word in the candidate starts with '-' and is followed by digits
                            has_negative = any(word.startswith('-') and word.lstrip('-').replace(' ', '').isdigit() for word in words[i:j])
                            if has_negative:
                                # This is likely a deduction line, skip it
                                continue

                            # For patterns like "Espp *", ensure the wildcard part is not just a number
                            # (which would mean we're matching the amount, not the field name)
                            if benefit_pattern == 'Espp *':
                                # Get the part after "Espp "
                                if candidate.startswith('Espp '):
                                    suffix = candidate[5:]  # Everything after "Espp "
                                    # Check if the suffix looks like it could be a field name (contains /, -, or letters)
                                    if not any(c in suffix for c in ['/', '-']) and suffix.replace(' ', '').isdigit():
                                        # This is just a number, not a field name
                                        continue

                            matched_name = candidate
                            break
                    if matched_name:
                        break
            else:
                # Exact match
                if benefit_pattern in line:
                    matched_name = benefit_pattern

            if matched_name:
                # Benefits typically only show YTD values (single amount)
                amount = extract_first_amount_from_line(line, matched_name)
                if amount:
                    # Store as YTD since benefits are cumulative
                    benefits[f"Other Benefits {matched_name}"] = amount
                break  # Move to next line once we found a match

    return benefits


def parse_other_section(text: str) -> Dict[str, str]:
    """Parse the Other section (if any)."""
    # This section may vary by paystub
    # For now, return empty dict as the example doesn't have a clear "Other" table
    return {}


def extract_paystub_data(pdf_path: str) -> Optional[Dict[str, str]]:
    """
    Extract all relevant data from a single ADP paystub PDF.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        Dictionary containing all extracted data, or None if extraction failed
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            # Combine text from all pages
            full_text = ""
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    full_text += page_text + "\n"

            if not full_text.strip():
                print(f"Warning: No text extracted from {pdf_path}", file=sys.stderr)
                return None

            # Extract all data
            data = {"Source File": os.path.basename(pdf_path)}

            # Pay period dates
            data.update(extract_pay_period_dates(full_text))

            # Earnings
            data.update(parse_earnings_section(full_text))

            # Deductions
            data.update(parse_deductions_section(full_text))

            # Other section
            data.update(parse_other_section(full_text))

            # Taxable wages
            data.update(extract_taxable_wages(full_text))

            # Other benefits
            data.update(parse_other_benefits_section(full_text))

            return data

    except Exception as e:
        print(f"Error processing {pdf_path}: {str(e)}", file=sys.stderr)
        return None


def validate_and_fix_ytd_values(data: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Validate YTD values and fix common issues.
    YTD values should be monotonically non-decreasing (or at least stay constant).
    Also forward-fill missing YTD values from the most recent known value.

    Args:
        data: List of extracted paystub dictionaries sorted by date

    Returns:
        List with validated/corrected YTD values
    """
    if not data:
        return data

    # Get all YTD field names
    ytd_fields = set()
    for record in data:
        for key in record.keys():
            if key.endswith(' YTD'):
                ytd_fields.add(key)

    # For each YTD field, validate and fix values
    for ytd_field in ytd_fields:
        last_valid_value = None

        for i, record in enumerate(data):
            current_value_str = record.get(ytd_field, '')

            if current_value_str and current_value_str.strip():
                try:
                    current_value = float(current_value_str.replace(',', ''))

                    # Check against previous value
                    if last_valid_value is not None:
                        # YTD should not decrease (except possibly for new year or field resets)
                        # Allow small rounding differences
                        if current_value < last_valid_value - 0.01:
                            print(f"Warning: {ytd_field} decreased from {last_valid_value} to {current_value} "
                                  f"in {record.get('Source File', 'unknown file')}", file=sys.stderr)

                    last_valid_value = current_value
                except ValueError:
                    # Not a valid number, skip
                    pass
            else:
                # Missing YTD value - forward-fill from last known value
                if last_valid_value is not None:
                    record[ytd_field] = str(last_valid_value)

    return data


def process_pdfs(input_path: str) -> List[Dict[str, str]]:
    """
    Process one or more PDF files.

    Args:
        input_path: Path to a single PDF file or directory containing PDFs

    Returns:
        List of dictionaries containing extracted data
    """
    results = []
    path = Path(input_path)

    if path.is_file():
        if path.suffix.lower() == '.pdf':
            data = extract_paystub_data(str(path))
            if data:
                results.append(data)
        else:
            print(f"Error: {input_path} is not a PDF file", file=sys.stderr)
    elif path.is_dir():
        # Process all PDFs in the directory (non-recursive)
        pdf_files = sorted(path.glob('*.pdf'))
        if not pdf_files:
            print(f"Warning: No PDF files found in {input_path}", file=sys.stderr)

        for pdf_file in pdf_files:
            data = extract_paystub_data(str(pdf_file))
            if data:
                results.append(data)
    else:
        print(f"Error: {input_path} does not exist", file=sys.stderr)

    # Validate and fix YTD values
    results = validate_and_fix_ytd_values(results)

    return results


def output_json(data: List[Dict[str, str]], output_file: Optional[str] = None):
    """Output data as JSON."""
    json_str = json.dumps(data, indent=2)

    if output_file:
        with open(output_file, 'w') as f:
            f.write(json_str)
        print(f"Data written to {output_file}", file=sys.stderr)
    else:
        print(json_str)


def output_csv(data: List[Dict[str, str]], output_file: Optional[str] = None):
    """
    Output data as CSV in transposed format.
    Rows are fields, columns are paystubs.
    First row is pay dates, subsequent rows contain field values.
    """
    if not data:
        print("No data to output", file=sys.stderr)
        return

    # Collect all unique field names across all records
    all_fields = set()
    for record in data:
        all_fields.update(record.keys())

    # Remove "Source File" from the field list
    all_fields.discard("Source File")

    # Sort fields according to the specified order (with glob pattern support)
    # First, add fields from FIELD_ORDER that exist in the data
    ordered_fields = []
    for field_pattern in FIELD_ORDER:
        # Check if it's a glob pattern
        if '*' in field_pattern or '?' in field_pattern or '[' in field_pattern:
            # Find all matching fields
            matching_fields = [f for f in all_fields if fnmatch.fnmatch(f, field_pattern)]
            for matched_field in sorted(matching_fields):
                if matched_field in all_fields:
                    ordered_fields.append(matched_field)
                    all_fields.discard(matched_field)
        else:
            # Exact match
            if field_pattern in all_fields:
                ordered_fields.append(field_pattern)
                all_fields.discard(field_pattern)

    # Then add YTD versions of the same fields in the same order
    ytd_fields = []
    for field_pattern in FIELD_ORDER:
        ytd_pattern = f"{field_pattern} YTD"
        # Check if it's a glob pattern
        if '*' in ytd_pattern or '?' in ytd_pattern or '[' in ytd_pattern:
            # Find all matching fields
            matching_fields = [f for f in all_fields if fnmatch.fnmatch(f, ytd_pattern)]
            for matched_field in sorted(matching_fields):
                if matched_field in all_fields:
                    ytd_fields.append(matched_field)
                    all_fields.discard(matched_field)
        else:
            # Exact match
            if ytd_pattern in all_fields:
                ytd_fields.append(ytd_pattern)
                all_fields.discard(ytd_pattern)

    ordered_fields.extend(ytd_fields)

    # Finally, add any remaining fields that weren't in the predefined order (alphabetically)
    ordered_fields.extend(sorted(all_fields))

    # Build the transposed CSV
    rows = []

    # First row: pay dates for each paystub
    pay_date_row = ["Pay Date"]
    for record in data:
        pay_date = record.get("Pay Date", "Unknown")
        pay_date_row.append(pay_date)
    rows.append(pay_date_row)

    # Data rows: each field becomes a row (skip Pay Date since it's the header)
    for field in ordered_fields:
        if field == "Pay Date":
            continue  # Skip Pay Date as it's already the header row
        row = [field]
        for record in data:
            value = record.get(field, "")
            row.append(value)
        rows.append(row)

    # Write CSV
    if output_file:
        with open(output_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerows(rows)
        print(f"Data written to {output_file}", file=sys.stderr)
    else:
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerows(rows)
        print(output.getvalue().rstrip())


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Extract data from ADP paystub PDFs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s paystub.pdf
  %(prog)s paystubs/ --output-format csv
  %(prog)s paystub.pdf --output-format json --output-file output.json
        """
    )

    parser.add_argument(
        'input',
        help='Path to a single PDF file or directory containing PDFs'
    )

    parser.add_argument(
        '--output-format',
        choices=['json', 'csv'],
        default='json',
        help='Output format (default: json)'
    )

    parser.add_argument(
        '--output-file',
        help='Output file path (default: stdout)'
    )

    args = parser.parse_args()

    # Process PDFs
    data = process_pdfs(args.input)

    if not data:
        print("No data extracted", file=sys.stderr)
        sys.exit(1)

    # Output results
    if args.output_format == 'json':
        output_json(data, args.output_file)
    else:
        output_csv(data, args.output_file)


if __name__ == '__main__':
    main()

