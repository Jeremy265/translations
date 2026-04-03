## Overview

Python script that automates the process of translating application strings from one language to another using the DeepL API. It extracts missing translations from a JSON file, processes them, and generates SQL statements to insert these translations into a database. This tool is particularly useful for developers looking to manage multilingual support in their applications efficiently.

## Features

- **Translation Extraction**: Automatically extracts missing translations from a database and saves them in a JSON format.
- **SQL Generation**: Converts translations into SQL `CALL` statements for easy database insertion.
- **Placeholder Management**: Preserves placeholders (e.g., `{{id}}`) during translation.
- **Batch Processing**: Sends translation requests to DeepL in batches to comply with API limits.
- **SQL Escaping**: Automatically escapes single quotes to prevent SQL injection.
- **Dynamic Module Handling**: Utilizes `module_id` from each JSON object and provides a default if not specified.
- **Validation**: Validates `module_id` to prevent injection attacks.
- **No-Translate Mode**: Option to skip translation and use existing values directly from the JSON file.
- **Configuration Options**: Supports configuration through command-line arguments, a `.env` file, or default values.

## Getting Started

### Prerequisites

Make sure you have Python 3 installed on your machine. You will also need to install the required dependencies:

```bash
pip install requests python-dotenv
```

### .env Configuration

Create a `.env` file in the root of your project directory with the following template. **Do not commit this file to a public repository.**

```plaintext
# .env template — DO NOT commit this file to a public repo
# DeepL API key
DEEPL_API_KEY=your_deepl_api_key_here

# Input / Output files (relative or absolute paths)
INPUT_FILE=translations_en.json
OUTPUT_FILE=translations_fr.sql

# Languages
SOURCE_LANG=en
TARGET_LANG=fr

# Batch size for DeepL requests
BATCH_SIZE=50

# DeepL API URL (use api-free.deepl.com for free tier, api.deepl.com for pro)
DEEPL_API_URL=https://api-free.deepl.com/v2/translate

# Default module id to use when an entry does not include module_id
# Must match pattern [A-Za-z0-9_.]+
DEFAULT_MODULE_ID=core

# If true, do not call DeepL (useful when JSON already contains French translations)
NO_TRANSLATE=false
```

### JSON Input Format

The input JSON file should contain an array of objects structured as follows:

```json
[
  {"module_id": "core", "key": "user.name", "value": "User name"},
  {"module_id": "services", "key": "service.description", "value": "Service description"}
]
```

### Running the Script

To run the script, execute the following command in your terminal:

```bash
python script.py
```

You can also specify additional options as needed, such as overriding the API key or changing the batch size.

## Options

- `--dotenv`: Path to the `.env` file (default: `.env`).
- `--api-key`: DeepL API key (overrides DEEPL_API_KEY in .env).
- `--input`: Input JSON file containing translations.
- `--output`: Output SQL file for generated SQL statements.
- `--default-module`: Default module_id if an entry lacks it.
- `--no-translate`: Use existing translations from JSON without calling DeepL.
- `--source-lang`: Source language (default: `en`).
- `--target-lang`: Target language (default: `fr`).
- `--batch-size`: Number of items per DeepL request (default: 50).
- `--deepl-url`: DeepL API URL (overrides DEEPL_API_URL in .env).
- `--on-missing-module`: Behavior when module_id is missing or invalid (options: `use-default`, `error`, `skip`).

## Acknowledgments

- [DeepL API](https://www.deepl.com/pro-api) for providing a powerful translation service.
- [Python](https://www.python.org/) for being a versatile programming language.
