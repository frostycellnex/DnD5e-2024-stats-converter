# D&D Tools


## Getting started

Initialize Anthropic API key
```
mkdir -p ~/.anthropic
vi ~/.anthropic/api-key # add your API key into the file
chmod 600 ~/.anthropic/api-key
```

Initialize python environment
```
python -m venv venv
source venv/bin/activate
pip install anthropic requests beautifulsoup4 reportlab
export ANTHROPIC_API_KEY="sk-ant-..."
```

## 2024 Stats Converter

Tool to convert D&D monster stats blocks from 2014 rules to 2024 rules

```
# Basic — PDF named automatically from the monster name
python convert_statblock.py https://www.5esrd.com/database/creature/sentinel-in-darkness/

# Custom output path
python convert_statblock.py <URL> --output my_monster.pdf
```

### What it does, step by step:

1. Fetches the URL and strips nav/footer noise from the HTML, leaving clean stat block text
2. Sends that text to claude-opus-4-5 with the full WotC designer persona and 2024 conversion rules baked into the system prompt
3. Parses the structured response (using ===SECTION=== delimiters it instructs the model to use)
4. Prints a colour-formatted version to the terminal with ANSI colours (red headers, cyan dividers)
5. Builds a typeset PDF in the classic D&D red-and-tan stat block style, including the designer notes and a generation timestamp
This should work on any 5eSRD-style page or similar stat block sites, since it just feeds the cleaned page text to the model and lets Claude do the extraction and conversion.

