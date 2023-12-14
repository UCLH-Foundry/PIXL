"""
Collection of functions for deidentifaction of text
#  Copyright (c) University College London Hospitals NHS Foundation Trust
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
"""
import re
from pathlib import Path

import requests
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

_anonymizer = AnonymizerEngine()
_analyzer = AnalyzerEngine()


def deidentify_text(text: str) -> str:
    """Query the cogstack redact API to deidentify input text."""
    url = "http://cogstack-api:8000/redact"
    response = requests.post(
        url, data=text, headers={"Content-Type": "text/plain"}, timeout=10
    )
    return response.text


def _presidio_anonymise(text: str) -> str:
    results = _analyzer.analyze(
        text=text,
        entities=["DATE_TIME", "PERSON"],
        language="en",
        allow_list=["XR Skull", "nasogastric tube", "lungs"],
    )

    result = _anonymizer.anonymize(text=text, analyzer_results=results)
    return str(result.text)


def _remove_case_insensitive_patterns(text: str) -> str:
    patterns = (
        r"reporting corresponds to ([^:]+)",  # Remove any words between ...to and :
        r"(\S+@\S+)",  # Matches any email address
        r"GMC[\s\S]?: (\d+)",  # Matches GMC numbers
        r"HCPC: (\d+)",  # Matches HCPC numbers
        r"RRV(\d+)",  # Accession numbers
        r"(\d+[\s]?[:/][\s]\d+)",  # Date or time like things
        r"(\d{4,100})",  # Remove any long numeric values (7 is GMC)
        r"(\d+[\/|:]\d+)",  # Remove any partial dates seperated by : or /
        r"Typed by: ((?:\w+\s?){1,2})",  # Remove one or two words after Typed by
        r"([0-9]{1,2} (?:" + _partial_date_str() + "))",  # Remove partial dates
        r"([0-9]{1,2}) <DATE_TIME>",  # Remove digits before a Presidio anon datetime
    )
    return re.sub("|".join(patterns), repl="XXX", string=text, flags=re.IGNORECASE)


def _remove_case_sensitive_patterns(text: str) -> str:
    patterns = (
        r"((?:[A-Z][a-z]+) (?:[A-Z][a-z]+)-(?:[A-Z][a-z]+))",  # Hyphenated full names
        r"\.\s{0,2}((?:[A-Z][a-z]+\s?){2})",  # Remove two title case after a full stop
        r"Dr\.? ((?:\b[A-Z][a-z]+\s?){0,3})",  # Remove any names after Dr
        # Remove title case words before professions
        r"(?:\b)((?:\b[A-Z][a-z]+ ){2,}(?=.*(?:" + _possible_professions_str() + ")))",
        r"([A-Z]{2}\s*$)",  # Remove initials at the end of a string
        # Any title case word directly preceding a profession
        rf"(\b[A-Z][a-z]+)\s(?:{_possible_professions_str()})",
        r"Signed by:\s?([A-Z]{3,},?\s?[A-Z]\w{2,})",  # Surname,Forename after signed by
        r"Signed by:?\s?\n?((?:[A-Z]\w+\s?-?){2,3})",  # Any part-capitalised post SB
        r",\s?((?:[A-Z]\w+){1,2} (?:[A-Z]{3,}))",  # Any 2-3 words with the second upper
        r"Signed by:?\s?\n?(\S*\s?[A-Z]\w+)",  # More generic two words after signed by
        r"signed(?: by:?)?\s?\n?((?:[A-Z]\w*\s)+)",  # Capitalised words after signed by
    )
    return re.sub("|".join(patterns), repl="XXX", string=text)


def _remove_any_excluded_words(text: str) -> str:
    return re.sub("|".join(_exclusions), repl=" XXX ", string=text, flags=re.IGNORECASE)


def _remove_any_trailing_tags(text: str) -> str:
    return re.sub("XXX>", repl="XXX", string=text)


def _possible_professions_str() -> str:
    titlecase_professions = [
        "Radiologist",
        "Professor",
        "Fellow",
        "Radiographer",
        "Radiologist",
        "Registrar",
        "ST5",
        "GMC",
        "ST3",
        "FRCR",
    ]
    return "|".join(titlecase_professions + [p.lower() for p in titlecase_professions])


def _remove_linebreaks_after_title_case_lines(text: str) -> str:
    lines = text.split("\n")
    text = ""
    for i, line in enumerate(lines):
        is_final_line = i == len(lines) - 1
        if all(word[0].isupper() for word in line.split() if len(word) > 0):
            text += f"{line.strip()}{' ' if not is_final_line else ''}"
        else:
            text += line + ("\n" if not is_final_line else "")

    return text


def _partial_date_str() -> str:
    return (
        r"Jan\w*|Feb\w*|Mar\w*|Apr\w*|May\w*|Jun\w*|"
        r"Jul\w*|Aug\w*|Sep\w*|Oct\w*|Nov\w*|Dec\w*"
    )


_this_dir = Path(Path(__file__).parent)
_exclusions = [
    rf"[\s|,]{line.strip()}[\s|,]"
    for line in Path.open(_this_dir / "exclusions.txt")
    if len(line.strip()) > 0  # skip any blank lines
]
