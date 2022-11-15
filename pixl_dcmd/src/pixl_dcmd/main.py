#  Copyright (c) 2022 University College London Hospitals NHS Foundation Trust
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
import hashlib
from io import BytesIO
import logging
from os import PathLike
import re
from typing import Any, BinaryIO, Union

from decouple import config
from pydicom import Dataset, dcmwrite
import requests

DicomDataSetType = Union[Union[str, bytes, PathLike[Any]], BinaryIO]


def write_dataset_to_bytes(dataset: Dataset) -> bytes:
    """Write pydicom DICOM dataset to byte array

    Original from:
    https://pydicom.github.io/pydicom/stable/auto_examples/memory_dataset.html
    """
    with BytesIO() as buffer:
        dcmwrite(buffer, dataset)
        buffer.seek(0)
        return buffer.read()


def remove_overlays(dataset: Dataset) -> Dataset:
    """Search for overlays planes and remove them.

    Overlay planes are repeating groups in [0x6000,xxxx].
    Up to 16 overlays can be stored in 0x6000 to 0x601E.
    See:
    https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.9.2.html
    for further details.
    """
    logging.info("Starting search for overlays...")

    for i in range(0x6000, 0x601F, 2):
        overlay = dataset.group_dataset(i)
        message = "Checking for overlay in: [0x{grp:04x}]".format(grp=i)
        logging.info(f"\t{message}")

        if overlay:
            message = "Found overlay in: [0x{grp:04x}]".format(grp=i)
            logging.info(f"\t{message}")
            # orthanc.LogWarning(message)
            message = "Deleting overlay in: [0x{grp:04x}]".format(grp=i)
            logging.info(f"\t{message}")
            for item in overlay:
                del dataset[item.tag]
        else:
            message = "No overlay in: [0x{grp:04x}]".format(grp=i)
            logging.info(f"\t{message}")
            # orthanc.LogWarning(message)

    return dataset


def get_encrypted_uid(uid: str, salt: bytes) -> str:
    """Hashes the suffix of a DICOM UID with the given salt.

    This function retains the prefix, while sha512-hashing the subcomponents
    of the suffix. The number of digits per subcomponent is retained in the
    encrypted UID. This also ensures that no UID is greater than 64 chars.
    No leading zeros are permitted in a subcomponent unless the subcomponent
    has a length of 1.

    Original UID:	    1.2.124.113532.10.122.1.203.20051130.122937.2950157
    Encrypted UID:	1.2.124.113532.74.696.4.703.80155569.949794.5833842

    Encrypting the UIDs this way ensures that no time information remains but
    that a input UID will always result in the same output UID, for a given salt.

    Note. that while no application should ever rely on the structure of a UID,
    there is a possibility that the were the anonyimised data to be push to the
    originating scanner (or scanner type), the data may not be recognised.
    """

    uid_elements = uid.split(".")

    prefix = ".".join(uid_elements[:4])
    suffix = ".".join(uid_elements[4:])
    logging.debug(f"\t\tPrefix: {prefix}")
    logging.debug(f"\t\tSuffix: {suffix}")

    # Get subcomponents of suffix as array.
    suffix_elements = uid_elements[4:]
    enc_element = [""] * len(suffix_elements)

    # For each subcomponent of the suffix:
    for idx, item in enumerate(suffix_elements):

        h = hashlib.sha512()
        h.update(item.encode("utf-8"))  # Add subcomponent.
        h.update(salt)  # Apply salt.

        # If subcomponent has a length of one, allow a leading zero, otherwise
        # strip leading zeros.
        # Regex removes any non-numeric chars.
        if len(item) == 1:
            enc_element[idx] = re.sub("[^0-9]", "", h.hexdigest())[: len(item)]
        else:
            enc_element[idx] = re.sub("[^0-9]", "", h.hexdigest()).lstrip("0")[
                : len(item)
            ]

    # Return original prefix and encrypted suffix.
    return prefix + "." + ".".join(enc_element[:])


def get_bounded_age(age: str) -> str:
    """Bounds patient age between 18 and 89"""
    if age[3] != "Y":
        return "018Y"
    else:
        age_as_int = int(age[0:3])
        if age_as_int < 18:
            return "018Y"
        elif age_as_int > 89:
            return "089Y"

    return age


def get_shifted_time(curr_time: str, study_time: str) -> Any:
    """Shift hour of current time relative to study time.

    Time fields in DICOM are in 24-hour clock and the following format:

    HHMMSS.FFFFFF

    Only HH is required as per the standard, but typically you will see:
    HHMMSS, HHMMSS.FF or # HHMMSS.FFFFFF
    """
    # Get HH as integer
    study_time_hr = int(study_time[0:2])
    curr_time_hr = int(curr_time[0:2])

    # If current time is greater than study time, use the difference.
    # If negative, then we've ticked over midnight.
    if curr_time_hr >= study_time_hr:
        hours_offset = curr_time_hr - study_time_hr
    else:
        hours_offset = curr_time_hr + 24 - study_time_hr

    # Form new time from offset and remaining parts of the current time (MMSS.FFFFFF)
    new_time = f"{hours_offset:02d}" + curr_time[2:]

    return new_time


def subtract_time_const(curr_time: str, time_const: int) -> Any:
    """Shift hour of current time by constant.

    Time fields in DICOM are in 24-hour clock and the following format:

    HHMMSS.FFFFFF

    Only HH is required as per the standard, but typically you will see:
    HHMMSS, HHMMSS.FF or # HHMMSS.FFFFFF
    """
    # Get HH as integer
    curr_time_hr = int(curr_time[0:2])

    # If current time minus offset is negative, wrap around midnight.
    if (curr_time_hr - time_const) < 0:
        hours_offset = curr_time_hr + 24 - time_const
    else:
        hours_offset = curr_time_hr - time_const

    # Form new time from offset and remaining parts of the current time (MMSS.FFFFFF)
    new_time = f"{hours_offset:02d}" + curr_time[2:]

    return new_time


def apply_tag_scheme(dataset: dict, tags: dict) -> dict:
    """Apply anoymisation operations for a given set of tags to a dataset"""

    # Keep the original study time before any operations are applied.
    # orig_study_time = dataset[0x0008, 0x0030].value

    # Set salt (this should be an ENV VAR).
    salt_plaintext = "PIXL"

    HASHER_API_AZ_NAME = config("HASHER_API_AZ_NAME")
    HASHER_API_PORT = config("HASHER_API_PORT")

    # TODO: Get offset from Hasher on study-by-study basis.
    TIME_OFFSET = int(config("TIME_OFFSET"))

    logging.info(b"TIME_OFFSET = %i}" % TIME_OFFSET)

    # Use hasher API to get hash of salt.
    hasher_host_url = "http://" + HASHER_API_AZ_NAME + ":" + HASHER_API_PORT
    payload = "/hash?message=" + salt_plaintext
    request_url = hasher_host_url + payload

    response = requests.get(request_url)

    logging.info(b"SALT = %a}" % response.content)
    salt = response.content

    # For every entry in the YAML:
    for i in range(0, len(tags)):

        name = tags[i]["name"]
        grp = tags[i]["group"]
        el = tags[i]["element"]
        op = tags[i]["op"]

        # If this tag should be kept.
        if op == "keep":
            if [grp, el] in dataset:
                message = "Keeping: {name} (0x{grp:04x},0x{el:04x})".format(
                    name=name, grp=grp, el=el
                )
                logging.info(f"\t{message}")
            else:
                message = "Missing: {name} (0x{grp:04x},0x{el:04x})\
                 - Operation ({op})".format(
                    name=name, grp=grp, el=el, op=op
                )
                logging.warn(f"\t{message}")
            # orthanc.LogWarning(message)

        # If this tag should be deleted.
        elif op == "delete":
            if [grp, el] in dataset:
                del dataset[grp, el]
                message = "Deleting: {name} (0x{grp:04x},0x{el:04x})".format(
                    name=name, grp=grp, el=el
                )
                logging.info(f"\t{message}")
            else:
                message = "Missing: {name} (0x{grp:04x},0x{el:04x})\
                 - Operation ({op})".format(
                    name=name, grp=grp, el=el, op=op
                )
                logging.debug(f"\t{message}")
            # orthanc.LogWarning(message)

        # Handle UIDs that should be encrypted.
        elif op == "hash-uid":

            if [grp, el] in dataset:

                message = "Changing: {name} (0x{grp:04x},0x{el:04x})".format(
                    name=name, grp=grp, el=el
                )
                logging.info(f"\t{message}")

                logging.info(f"\t\tCurrent UID:\t{dataset[grp,el].value}")
                new_uid = get_encrypted_uid(dataset[grp, el].value, salt)
                dataset[grp, el].value = new_uid
                logging.info(f"\t\tEncrypted UID:\t{new_uid}")

            else:
                message = "Missing: {name} (0x{grp:04x},0x{el:04x})\
                 - Operation ({op})".format(
                    name=name, grp=grp, el=el, op=op
                )
                logging.debug(f"\t{message}")
            # orthanc.LogWarning(message)

        # Shift time relative to the original study time.
        elif op == "time-shift":
            new_time = subtract_time_const(dataset[grp, el].value, TIME_OFFSET)
            logging.info(f"\tChanging {name}: {dataset[grp,el].value} -> {new_time}")
            dataset[grp, el].value = new_time

        # Modify specific tags (make blank).
        elif op == "fixed":
            if grp == 0x0020 and el == 0x0010:
                logging.info(f"\tRedacting Study ID: {dataset[grp,el].value}")
                dataset[grp, el].value = ""
            if grp == 0x0010 and el == 0x0020:
                logging.info(f"\tRedacting Patient ID: {dataset[grp,el].value}")
                dataset[grp, el].value = ""

        # Enforce a numerical range.
        elif op == "num-range":
            if grp == 0x0010 and el == 0x1010:
                new_age = get_bounded_age(dataset[grp, el].value)
                logging.info(
                    f"\tChanging Patient Age: {dataset[grp,el].value} -> {new_age}"
                )
                dataset[grp, el].value = new_age

        # Change value into hash from hasher API.
        elif op == "secure-hash":
            if [grp, el] in dataset:
                pat_value = str(dataset[grp, el].value)
                payload = "/hash?message=" + pat_value
                request_url = hasher_host_url + payload
                response = requests.get(request_url)
                logging.info(b"RESPONSE = %a}" % response.content)

                new_value = response.content

                if dataset[grp, el].VR == "SH":
                    new_value = new_value[:16]

                dataset[grp, el].value = new_value

                message = "Changing: {name} (0x{grp:04x},0x{el:04x})".format(
                    name=name, grp=grp, el=el
                )
                logging.info(f"\t{message}")
            else:
                message = "Missing: {name} (0x{grp:04x},0x{el:04x})\
                 - Operation ({op})".format(
                    name=name, grp=grp, el=el, op=op
                )
                logging.warn(f"\t{message}")
            # orthanc.LogWarning(message)

    return dataset
