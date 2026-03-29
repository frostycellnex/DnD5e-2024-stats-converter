#!/usr/bin/env python3
"""
convert_statblock.py

Fetches a D&D 5e monster stat block from a URL, uses the Anthropic API
to convert it from 2014 rules to 2024 rules (with the persona of a senior
Wizards of the Coast designer), then outputs the result to the terminal
and as a PDF file.

Usage:
    python convert_statblock.py <URL> [--output PATH]

Requirements:
    pip install anthropic requests beautifulsoup4 reportlab

Credentials (checked in order):
    1. ~/.anthropic/api-key   — recommended: a private file containing only
                                the key, chmod 600, never in shell history
    2. ANTHROPIC_API_KEY      — environment variable (fallback)
"""

import argparse
import os
import re
import sys
import textwrap
from datetime import datetime

# ── third-party ──────────────────────────────────────────────────────────────
try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Missing dependencies. Run:  pip install requests beautifulsoup4")

try:
    import anthropic
except ImportError:
    sys.exit("Missing dependency. Run:  pip install anthropic")

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer,
        HRFlowable, Table, TableStyle,
    )
except ImportError:
    sys.exit("Missing dependency. Run:  pip install reportlab")


# ─────────────────────────────────────────────────────────────────────────────
# 0.  CREDENTIAL LOADING
# ─────────────────────────────────────────────────────────────────────────────

CREDENTIALS_FILE = os.path.expanduser("~/.anthropic/api-key")

def load_api_key() -> str:
    """
    Resolve the Anthropic API key without requiring it on the command line
    (which would expose it in shell history).

    Resolution order:
      1. ~/.anthropic/api-key  — a private file containing only the key.
                                 Create with:
                                   mkdir -p ~/.anthropic
                                   echo 'sk-ant-...' > ~/.anthropic/api-key
                                   chmod 600 ~/.anthropic/api-key
      2. ANTHROPIC_API_KEY environment variable — acceptable when set via a
                                 shell profile or secret manager rather than
                                 typed interactively.
    """
    # 1. Private credentials file
    if os.path.exists(CREDENTIALS_FILE):
        try:
            stat = os.stat(CREDENTIALS_FILE)
            # Warn if the file is readable by group or others (unix only)
            if hasattr(stat, "st_mode") and (stat.st_mode & 0o077):
                print(
                    f"⚠️   Warning: {CREDENTIALS_FILE} has loose permissions. "
                    "Run:  chmod 600 ~/.anthropic/api-key",
                    file=sys.stderr,
                )
            with open(CREDENTIALS_FILE, "r") as fh:
                key = fh.read().strip()
            if key:
                return key
            print(f"⚠️   {CREDENTIALS_FILE} is empty — falling back to env var.", file=sys.stderr)
        except OSError as exc:
            print(f"⚠️   Could not read {CREDENTIALS_FILE}: {exc}", file=sys.stderr)

    # 2. Environment variable
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key

    # Nothing found — give the user clear setup instructions
    sys.exit(
        "\n❌  No Anthropic API key found.\n\n"
        "    Recommended setup (keeps key out of shell history):\n"
        "      mkdir -p ~/.anthropic\n"
        "      echo 'sk-ant-...' > ~/.anthropic/api-key\n"
        "      chmod 600 ~/.anthropic/api-key\n\n"
        "    Alternatively, set the ANTHROPIC_API_KEY environment variable\n"
        "    in your shell profile (~/.zshrc, ~/.bashrc, etc.).\n"
    )


# ── colour constants ──────────────────────────────────────────────────────────
DARK_RED  = colors.HexColor("#8B0000")
MID_TAN   = colors.HexColor("#E8D5B7")
MUTED     = colors.HexColor("#555555")
NOTE_FG   = colors.HexColor("#444444")


# ─────────────────────────────────────────────────────────────────────────────
# 1.  FETCH & CLEAN PAGE TEXT
# ─────────────────────────────────────────────────────────────────────────────

def fetch_statblock(url: str) -> str:
    """Download the page and return the cleaned visible text."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; statblock-converter/1.0)"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        sys.exit(f"Failed to fetch URL: {exc}")

    soup = BeautifulSoup(resp.text, "html.parser")

    # Drop nav / footer / script noise
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    # Collapse blank lines
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 2.  CALL ANTHROPIC API
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a senior game designer at Wizards of the Coast with more than
20 years of experience working on Dungeons & Dragons. You have worked on every edition
from 3rd edition onward and were deeply involved in the 2024 revision of the Monster Manual.

Your task is to adapt monster stat blocks written for the 2014 D&D 5e rules to the
updated 2024 rules. You are meticulous, knowledgeable, and care about both mechanical
accuracy and the flavour of each creature.

When converting a stat block you must:
- Identify the monster's Challenge Rating and use the 2024 CR benchmarks for
  AC, HP, attack bonus, and damage per round.
- Add an explicit Proficiency Bonus line.
- Add a Saving Throws line listing any saves appropriate for the creature type and role.
- Recalculate skill bonuses against the updated Proficiency Bonus.
- Update Stone Fist / natural weapon damage dice to meet the 2024 DPR target.
- Apply the 2024 standardised "Construct Nature" (or equivalent) trait language where relevant.
- Add Magic Resistance if the creature's CR and type warrant it and it was missing.
- Add a Bonus Action if the creature's role benefits from action-economy texture.
- Update all attack formatting to the 2024 "Melee Attack Roll / Hit" convention.
- Improve Recharge abilities if their recharge number is too conservative for the CR.
- Preserve all original flavour text, lore, and thematic intent.
- After the stat block, include a clearly labelled "Designer Notes" section that
  explains every change made and why, referencing specific 2024 benchmarks.

Output format — use EXACTLY this structure so it can be parsed:

===MONSTER NAME===
<name of monster>

===TYPE LINE===
<size, type, alignment>

===CORE STATS===
Armor Class: <value>
Hit Points: <value>
Speed: <value>
Initiative: <value>
Proficiency Bonus: <value>

===ABILITY SCORES===
STR: <score> (<modifier>)
DEX: <score> (<modifier>)
CON: <score> (<modifier>)
INT: <score> (<modifier>)
WIS: <score> (<modifier>)
CHA: <score> (<modifier>)

===SECONDARY STATS===
Saving Throws: <list>
Skills: <list>
Resistances: <list or None>
Immunities: <list or None>
Senses: <list>
Languages: <value>
Challenge: <value>

===TRAITS===
<Name>. <text>
<Name>. <text>

===ACTIONS===
<Name>. <text>
<Name>. <text>

===BONUS ACTIONS===
<Name>. <text>

===LORE===
<flavour paragraph(s)>

===DESIGNER NOTES===
<detailed explanation of every change>
"""

def convert_with_api(raw_text: str, api_key: str) -> str:
    """Send the raw page text to Claude and return the structured conversion."""
    client = anthropic.Anthropic(api_key=api_key)

    user_message = (
        "Below is the raw text scraped from a web page containing a D&D 5e monster "
        "stat block written for the 2014 rules.\n\n"
        "Please convert it to the 2024 rules following your design expertise.\n\n"
        "--- RAW PAGE TEXT ---\n"
        f"{raw_text[:12000]}"          # stay well within context limits
    )

    print("\n⚔  Calling Anthropic API … this may take 20–40 seconds.\n")

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return message.content[0].text


# ─────────────────────────────────────────────────────────────────────────────
# 3.  PARSE STRUCTURED OUTPUT
# ─────────────────────────────────────────────────────────────────────────────

# All known section tags in the order we expect them.
SECTION_TAGS = [
    "MONSTER NAME", "TYPE LINE", "CORE STATS", "ABILITY SCORES",
    "SECONDARY STATS", "TRAITS", "ACTIONS", "BONUS ACTIONS", "LORE",
    "DESIGNER NOTES",
]


def parse_all_sections(text: str) -> dict:
    """
    Split the API response into {TAG: content} by locating each ===TAG===
    marker and capturing only the text up to the NEXT marker.  This prevents
    any section from bleeding into the next one, and keeps only the FIRST
    occurrence of each tag so a model that repeats itself doesn't corrupt the
    output.

    Special case: if the monster name appears BEFORE the first === marker
    (a common model formatting slip), capture it as MONSTER NAME.
    """
    marker_re = re.compile(r"===([A-Z][A-Z ]+)===")
    markers = [(m.start(), m.end(), m.group(1).strip()) for m in marker_re.finditer(text)]

    sections = {tag: "" for tag in SECTION_TAGS}

    # If there's text before the first marker, treat it as the monster name
    if markers:
        preamble = text[:markers[0][0]].strip()
        if preamble:
            # Take the last non-empty line (avoids blank padding at top)
            candidate = next(
                (ln.strip() for ln in reversed(preamble.splitlines()) if ln.strip()), ""
            )
            if candidate:
                sections["MONSTER NAME"] = candidate

    for i, (start, end, tag) in enumerate(markers):
        if tag not in sections:
            continue
        content_end = markers[i + 1][0] if i + 1 < len(markers) else len(text)
        content = text[end:content_end].strip()
        # Only store the FIRST occurrence — guards against repeated blocks
        if not sections[tag]:
            sections[tag] = content

    return sections


def parse_section(text: str, tag: str) -> str:
    """Convenience wrapper: parse all sections and return the requested one."""
    return parse_all_sections(text).get(tag, "")


def parse_ability_scores(section: str) -> list:
    scores = []
    for stat in ["STR", "DEX", "CON", "INT", "WIS", "CHA"]:
        m = re.search(rf"{stat}:\s*(\d+\s*\([^)]+\))", section)
        scores.append((stat, m.group(1).strip() if m else "—"))
    return scores


def parse_key_value_block(section: str) -> list:
    """Return (key, value) pairs from 'Key: value' lines.
    Ignores lines where the key looks like a freeform sentence."""
    pairs = []
    for line in section.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        # Reject keys that are clearly prose sentences (more than 4 words)
        if k and v and len(k.split()) <= 4:
            pairs.append((k, v))
    return pairs


def parse_trait_list(section: str) -> list:
    """Split a section into [(trait name incl. period, body text)] pairs."""
    # Strip leading list markers like "1. " or "- "
    cleaned = re.sub(r'(?m)^\s*\d+\.\s+', '', section)
    cleaned = re.sub(r'(?m)^\s*[-•]\s+', '', cleaned)

    # Split on blank lines or at the start of a new capitalised trait name
    parts = re.split(r'\n{2,}|\n(?=[A-Z][^\n]{0,60}\.\s)', cleaned)

    traits = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        m = re.match(r'^(.+?\)?)\.[ \t]+(.*)', part, re.DOTALL)
        if m:
            traits.append((m.group(1).strip() + ".", m.group(2).strip()))
        else:
            traits.append(("", part))
    return traits


def safe_xml(text: str, allow_bold: bool = False) -> str:
    """Escape special XML chars for ReportLab, optionally converting **bold**."""
    escaped = (text
               .replace("&", "&amp;")
               .replace("<", "&lt;")
               .replace(">", "&gt;"))
    if allow_bold:
        escaped = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', escaped)
    return escaped


# ─────────────────────────────────────────────────────────────────────────────
# 4.  TERMINAL OUTPUT
# ─────────────────────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
RED    = "\033[31m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
DIM    = "\033[2m"

def print_divider(char="─", width=72, colour=RED):
    print(f"{colour}{char * width}{RESET}")

def print_section(title: str, content: str):
    print(f"\n{YELLOW}{BOLD}{title}{RESET}")
    print_divider("─", 72, CYAN)
    for line in content.splitlines():
        print(f"  {line}")

def terminal_output(api_response: str):
    name    = parse_section(api_response, "MONSTER NAME")
    type_   = parse_section(api_response, "TYPE LINE")
    core    = parse_section(api_response, "CORE STATS")
    ability = parse_section(api_response, "ABILITY SCORES")
    second  = parse_section(api_response, "SECONDARY STATS")
    traits  = parse_section(api_response, "TRAITS")
    actions = parse_section(api_response, "ACTIONS")
    bonus   = parse_section(api_response, "BONUS ACTIONS")
    lore    = parse_section(api_response, "LORE")
    notes   = parse_section(api_response, "DESIGNER NOTES")

    width = 72
    print("\n")
    print_divider("═", width, RED)
    print(f"{RED}{BOLD}  {name.upper()}{RESET}")
    print(f"  {DIM}{type_}{RESET}")
    print_divider("═", width, RED)

    print_section("CORE STATS", core)
    print_section("ABILITY SCORES", ability)
    print_section("SECONDARY STATS", second)
    print_section("TRAITS", traits)
    print_section("ACTIONS", actions)
    if bonus:
        print_section("BONUS ACTIONS", bonus)
    print_section("LORE", lore)

    print(f"\n{YELLOW}{BOLD}DESIGNER NOTES{RESET}")
    print_divider("─", width, CYAN)
    for line in textwrap.wrap(notes, width=70):
        print(f"  {line}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# 5.  PDF OUTPUT
# ─────────────────────────────────────────────────────────────────────────────

def build_pdf(api_response: str, output_path: str):
    # Parse once — prevents any section from being re-parsed with stale data
    secs      = parse_all_sections(api_response)
    name      = next((ln.strip() for ln in secs["MONSTER NAME"].splitlines() if ln.strip()), "Unknown Monster")
    type_line = secs["TYPE LINE"]
    core_raw  = secs["CORE STATS"]
    ab_raw    = secs["ABILITY SCORES"]
    sec_raw   = secs["SECONDARY STATS"]
    traits_raw= secs["TRAITS"]
    actions_r = secs["ACTIONS"]
    bonus_raw = secs["BONUS ACTIONS"]
    lore_raw  = secs["LORE"]
    notes_raw = secs["DESIGNER NOTES"]

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        rightMargin=0.75*inch,
        leftMargin=0.75*inch,
        topMargin=0.75*inch,
        bottomMargin=0.75*inch,
        title=f"{name} — 2024 D&D Stat Block",
        author="WotC Designer Tool",
    )

    S = {
        "name":    ParagraphStyle("name",    fontName="Times-Bold",      fontSize=20, textColor=DARK_RED, spaceAfter=2),
        "type":    ParagraphStyle("type",    fontName="Times-Italic",    fontSize=12, spaceAfter=4),
        "prop":    ParagraphStyle("prop",    fontName="Times-Roman",     fontSize=11, leading=16, spaceAfter=2),
        "section": ParagraphStyle("section", fontName="Times-BoldItalic",fontSize=13, textColor=DARK_RED, spaceBefore=6, spaceAfter=2),
        "trait":   ParagraphStyle("trait",   fontName="Times-Roman",     fontSize=11, leading=16, spaceAfter=4),
        "lore":    ParagraphStyle("lore",    fontName="Times-Italic",    fontSize=10, leading=14, textColor=MUTED, spaceBefore=6, spaceAfter=4),
        "note":    ParagraphStyle("note",    fontName="Times-Roman",     fontSize=9,  leading=13, textColor=NOTE_FG, spaceBefore=4),
        "sname":   ParagraphStyle("sname",   fontName="Times-Bold",      fontSize=10, textColor=DARK_RED, alignment=TA_CENTER),
        "sval":    ParagraphStyle("sval",    fontName="Times-Roman",     fontSize=11, alignment=TA_CENTER),
    }

    def prop(label, value):
        return Paragraph(
            f'<font name="Times-Bold" color="#8B0000">{safe_xml(label)}</font> {safe_xml(value)}',
            S["prop"])

    def trait_p(tname, tbody):
        return Paragraph(
            f'<font name="Times-BoldItalic">{safe_xml(tname)}</font> {safe_xml(tbody)}',
            S["trait"])

    def divider(thick=1.5):
        return HRFlowable(width="100%", thickness=thick, color=DARK_RED, spaceAfter=4, spaceBefore=4)

    def thin_div():
        return HRFlowable(width="100%", thickness=0.5, color=MID_TAN, spaceAfter=4, spaceBefore=4)

    story = []

    # Header
    story.append(Paragraph(name, S["name"]))
    story.append(Paragraph(type_line, S["type"]))
    story.append(HRFlowable(width="100%", thickness=4, color=DARK_RED, spaceAfter=4, spaceBefore=2))

    # Core stats
    for k, v in parse_key_value_block(core_raw):
        story.append(prop(k + ":", v))

    story.append(divider())

    # Ability scores
    scores = parse_ability_scores(ab_raw)
    col_w = doc.width / 6
    score_data = [
        [Paragraph(s, S["sname"]) for s, _ in scores],
        [Paragraph(v, S["sval"])  for _, v in scores],
    ]
    tbl = Table(score_data, colWidths=[col_w]*6, rowHeights=[18, 20])
    tbl.setStyle(TableStyle([
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ("TOPPADDING",    (0,0), (-1,-1), 2),
    ]))
    story.append(tbl)

    story.append(divider())

    # Secondary stats
    for k, v in parse_key_value_block(sec_raw):
        story.append(prop(k + ":", v))

    story.append(divider())

    # Traits
    story.append(Paragraph("Traits", S["section"]))
    for tname, tbody in parse_trait_list(traits_raw):
        story.append(trait_p(tname, tbody))

    story.append(divider())

    # Actions
    story.append(Paragraph("Actions", S["section"]))
    for tname, tbody in parse_trait_list(actions_r):
        story.append(trait_p(tname, tbody))

    # Bonus actions (optional)
    if bonus_raw.strip():
        story.append(divider())
        story.append(Paragraph("Bonus Actions", S["section"]))
        for tname, tbody in parse_trait_list(bonus_raw):
            story.append(trait_p(tname, tbody))

    story.append(thin_div())

    # Lore — preserve **bold** subheadings (e.g. **Protector of Secrets.**)
    story.append(Paragraph(safe_xml(lore_raw, allow_bold=True), S["lore"]))

    story.append(thin_div())

    # Designer notes — preserve **bold** labels
    story.append(Paragraph(
        f'<font name="Times-Bold">Designer Notes (2024 Adaptation):</font> '
        f'{safe_xml(notes_raw, allow_bold=True)}',
        S["note"]
    ))

    # Timestamp footer note
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        f'<font name="Times-Italic">Generated {ts} via convert_statblock.py</font>',
        ParagraphStyle("ts", fontName="Times-Italic", fontSize=8,
                       textColor=colors.HexColor("#999999"), spaceAfter=0)
    ))

    doc.build(story)


# ─────────────────────────────────────────────────────────────────────────────
# 6.  ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Convert a 2014 D&D 5e stat block (URL) to 2024 rules via Claude API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python convert_statblock.py https://www.5esrd.com/database/creature/sentinel-in-darkness/
              python convert_statblock.py <URL> --output my_monster.pdf

            Credentials are loaded from ~/.anthropic/api-key (recommended) or
            the ANTHROPIC_API_KEY environment variable — never from the command
            line, so the key is never written to your shell history.
        """),
    )
    parser.add_argument("url", help="URL of the 5e stat block page to convert")
    parser.add_argument(
        "--output", "-o", default=None,
        help="Output PDF path (default: <monster-name>_2024.pdf in current directory)"
    )
    args = parser.parse_args()

    api_key = load_api_key()

    print(f"🌐  Fetching: {args.url}")
    raw_text = fetch_statblock(args.url)
    print(f"    Retrieved {len(raw_text):,} characters of page text.")

    api_response = convert_with_api(raw_text, api_key)

    # Terminal output
    terminal_output(api_response)

    # Determine PDF output path
    if args.output:
        pdf_path = args.output
    else:
        secs = parse_all_sections(api_response)
        raw_name = secs.get("MONSTER NAME", "")
        # First non-empty line only — never use multi-line content as a filename
        monster_name = next((ln.strip() for ln in raw_name.splitlines() if ln.strip()), "")
        # Sanitise and hard-cap at 64 chars
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", monster_name.lower()).strip("_")[:64]
        pdf_path = f"{safe_name}_2024.pdf" if safe_name else "statblock_2024.pdf"

    print(f"📄  Writing PDF → {pdf_path}")
    build_pdf(api_response, pdf_path)
    print(f"✅  Done! PDF saved to: {pdf_path}\n")


if __name__ == "__main__":
    main()
