# ADP Paystub PDF Data Extractor

A Python script that extracts structured data from ADP paystub PDFs and outputs the data in JSON or CSV format.

Disclaimers
- This likely only works for paystubs from my employer but YMMV.
- Check the output closely. There are almost surely parser errors.
- 99% of this work is from claude-sonnet-4.5.

## Features

- Extract data from single PDF or directory of PDFs
- Output in JSON or CSV format
- Extracts the following information:
  - Pay period dates (beginning, ending, pay date)
  - Earnings table data (both "this period" and year-to-date values)
  - Deductions table data (both "this period" and year-to-date values)
  - Other Benefits and Information table data
  - Taxable wages for the period
- CSV output in transposed format: fields as rows, paystubs as columns
- Handles errors gracefully (skips problematic PDFs and continues processing)
- Works with searchable PDFs (no OCR required)

## Installation

1. Create a virtual environment (recommended):

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

## Usage

### Basic Usage

Extract data from a single PDF (JSON output to stdout):

```bash
python3 adp_extractor.py paystub.pdf
```

Extract data from all PDFs in a directory:

```bash
python3 adp_extractor.py paystubs/
```

### Output Formats

Output as CSV:

```bash
python3 adp_extractor.py paystub.pdf --output-format csv
```

Output as JSON (default):

```bash
python3 adp_extractor.py paystub.pdf --output-format json
```

### Save to File

Save output to a file:

```bash
python3 adp_extractor.py paystub.pdf --output-file output.json
python3 adp_extractor.py paystubs/ --output-format csv --output-file output.csv
```

### Help

View all available options:

```bash
python3 adp_extractor.py --help
```

## Output Format

### JSON Output

The script outputs an array of objects, one per paystub. Each object contains both "this period" and YTD values where available:

```json
[
  {
    "Source File": "paystub.pdf",
    "Pay Period Beginning": "01/01/2024",
    "Pay Period Ending": "01/15/2024",
    "Pay Date": "01/22/2024",
    "Earnings Regular": "5000.00",
    "Earnings Regular YTD": "5000.00",
    "Deductions Federal Income Tax": "-750.00",
    "Deductions Federal Income Tax YTD": "750.00",
    "Deductions Social Security Tax": "-310.00",
    "Deductions Social Security Tax YTD": "310.00",
    "Deductions Medicare Tax": "-72.50",
    "Deductions Medicare Tax YTD": "72.50",
    "Taxable Wages This Period": "4500.00",
    "Other Benefits Current Match": "250.00"
  }
]
```

### CSV Output

The CSV output format is as follows:
- Each row represents a field
- Each column represents a paystub file
- The first column contains field names
- The first row shows pay dates for each paystub

Example:

```csv
Pay Date,01/22/2024,02/05/2024
Pay Period Beginning,01/01/2024,01/16/2024
Pay Period Ending,01/15/2024,01/31/2024
Earnings Regular,5000.00,5000.00
Earnings Regular YTD,5000.00,10000.00
Deductions Federal Income Tax,-750.00,-750.00
Deductions Federal Income Tax YTD,750.00,1500.00
```

This format makes it easy to compare values across multiple paystubs and analyze trends over time.

## Column Naming Convention

Extracted data columns are prefixed with their source table:

- `Earnings <field>` - "This period" data from the Earnings table
- `Earnings <field> YTD` - Year-to-date data from the Earnings table
- `Deductions <field>` - "This period" data from the Deductions table
- `Deductions <field> YTD` - Year-to-date data from the Deductions table
- `Other Benefits <field>` - Data from the Other Benefits and Information table
- `Taxable Wages This Period` - Federal taxable wages for the period
- `Pay Period Beginning`, `Pay Period Ending`, `Pay Date` - Date fields

### Field Ordering in CSV

Fields are ordered in a predefined sequence in CSV output:
1. Date fields (Pay Date, Pay Period Beginning, Pay Period Ending)
2. Earnings fields (in alphabetical order)
3. Taxable wages
4. Deductions fields (in alphabetical order)
5. Other Benefits fields (in alphabetical order)
6. All corresponding YTD fields (in the same order)
7. Any additional fields not in the predefined list (in alphabetical order)

## Error Handling

The script handles errors gracefully:

- If a PDF cannot be processed, it logs an error to stderr and continues with the next file
- If no text can be extracted from a PDF, it logs a warning and skips the file
- If a directory contains no PDF files, it logs a warning

## Requirements

- Python 3.6+
- pdfplumber

## Notes

- The script only processes PDFs in the top-level directory (non-recursive)
- PDFs must be searchable (contain text, not just images)
- The script is designed for standard ADP paystub format
- Different ADP formats may require adjustments to the extraction patterns
- Year-to-date (YTD) values are extracted separately from "this period" values
- ADP may leave fields blank if no value was recorded for "this period" while still showing a YTD value
- The extraction logic correctly distinguishes between blank "this period" values and YTD values

## Troubleshooting

### No data extracted

- Ensure the PDF is searchable (not a scanned image)
- Check that the PDF follows the standard ADP paystub format
- Try opening the PDF in a text editor to verify it contains extractable text

### Missing fields

- Some fields may not be present on all paystubs
- The script only extracts fields that are found in the PDF
- Check the PDF to verify the field exists and matches the expected format

### Incorrect amounts

- Verify the PDF text extraction is working correctly
- The script expects ADP's specific number format (space-separated digits with last 2 digits as cents)
- If your paystubs use a different format, the extraction patterns may need adjustment
