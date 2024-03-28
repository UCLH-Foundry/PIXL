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
from __future__ import annotations

from io import BytesIO
from logging import getLogger
from os import PathLike
from typing import Any, BinaryIO, Union

from core.exceptions import PixlSkipMessageError
from core.project_config import load_project_config

from core.dicom_tags import DICOM_TAG_PROJECT_NAME

import requests
from core.project_config import load_tag_operations
from decouple import config
from pydicom import Dataset, dcmwrite

from pixl_dcmd._tag_schemes import merge_tag_schemes
from pixl_dcmd._database import add_hashed_identifier_and_save, query_db
from pixl_dcmd._datetime import combine_date_time, format_date_time
from pixl_dcmd._deid_helpers import get_bounded_age, get_encrypted_uid

DicomDataSetType = Union[Union[str, bytes, PathLike[Any]], BinaryIO]

logger = getLogger(__name__)


def write_dataset_to_bytes(dataset: Dataset) -> bytes:
    """
    Write pydicom DICOM dataset to byte array

    Original from:
    https://pydicom.github.io/pydicom/stable/auto_examples/memory_dataset.html
    """
    with BytesIO() as buffer:
        dcmwrite(buffer, dataset)
        buffer.seek(0)
        return buffer.read()


def should_exclude_series(dataset: Dataset) -> bool:
    slug = get_project_name_as_string(dataset)

    series_description = dataset.get("SeriesDescription")
    cfg = load_project_config(slug)
    if cfg.is_series_excluded(series_description):
        logger.warning("FILTERING OUT series description: %s", series_description)
        return True
    return False


def anonymise_dicom(dataset: Dataset) -> Dataset:
    """
    Anonymises a DICOM dataset as Received by Orthanc.
    Finds appropriate configuration based on project name and anonymises by
    - dropping datasets of the wrong modality
    - removing private tags
    - removing overlays
    - applying tag operations based on the config file
    Returns anonymised dataset.
    """
    slug = get_project_name_as_string(dataset)

    project_config = load_project_config(slug)
    logger.debug(f"Received instance for project {slug}")
    if dataset.Modality not in project_config.project.modalities:
        msg = f"Dropping DICOM Modality: {dataset.Modality}"
        raise PixlSkipMessageError(msg)

    logger.info("Anonymising received instance")

    # Rip out overlays/
    dataset = remove_overlays(dataset)
    logger.info("Removed overlays")

    # Merge tag schemes
    tag_operations = load_tag_operations(project_config)
    all_tags = merge_tag_schemes(tag_operations, manufacturer=dataset.Manufacturer)

    # Apply scheme to instance
    dataset = apply_tag_scheme(dataset, all_tags)
    # Apply whitelist
    dataset = enforce_whitelist(dataset, all_tags)

    logger.info(
        f"DICOM tag anonymisation applied according to {project_config.tag_operation_files}"
    )
    # Write anonymised instance to disk.
    return dataset


def get_project_name_as_string(dataset: Dataset) -> str:
    raw_slug = dataset.get_private_item(
        DICOM_TAG_PROJECT_NAME.group_id,
        DICOM_TAG_PROJECT_NAME.offset_id,
        DICOM_TAG_PROJECT_NAME.creator_string,
    ).value
    # Get both strings and bytes, which is fun
    if isinstance(raw_slug, bytes):
        logger.debug(f"Bytes slug {raw_slug!r}")
        slug = raw_slug.decode("utf-8").strip()
    else:
        logger.debug(f"String slug '{raw_slug}'")
        slug = raw_slug
    return slug


def remove_overlays(dataset: Dataset) -> Dataset:
    """
    Search for overlays planes and remove them.

    Overlay planes are repeating groups in [0x6000,xxxx].
    Up to 16 overlays can be stored in 0x6000 to 0x601E.
    See:
    https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.9.2.html
    for further details.
    """
    logger.debug("Starting search for overlays...")

    for i in range(0x6000, 0x601F, 2):
        overlay = dataset.group_dataset(i)
        message = f"Checking for overlay in: [0x{i:04x}]"
        logger.debug(f"\t{message}")

        if overlay:
            message = f"Found overlay in: [0x{i:04x}]"
            logger.debug(f"\t{message}")

            message = f"Deleting overlay in: [0x{i:04x}]"
            logger.debug(f"\t{message}")
            for item in overlay:
                del dataset[item.tag]
        else:
            message = f"No overlay in: [0x{i:04x}]"
            logger.debug(f"\t{message}")

    return dataset


def enforce_whitelist(dataset: Dataset, tags: list[dict]) -> Dataset:
    """Delete any tags not in the tagging scheme."""
    # For every element:
    logger.debug("Enforcing whitelist")
    for de in dataset:
        keep_el = False
        # For every entry in the YAML:
        for i in range(len(tags)):
            grp = tags[i]["group"]
            el = tags[i]["element"]
            op = tags[i]["op"]

            if de.tag.group == grp and de.tag.element == el:
                if op != "delete":
                    keep_el = True

        if not keep_el:
            del_grp = de.tag.group
            del_el = de.tag.element

            del dataset[del_grp, del_el]
            message = "Whitelist - deleting: {name} (0x{grp:04x},0x{el:04x})".format(
                name=de.keyword, grp=del_grp, el=del_el
            )
            logger.debug(f"\t{message}")

    return dataset


def apply_tag_scheme(dataset: Dataset, tags: list[dict]) -> Dataset:
    """
    Apply anonymisation operations for a given set of tags to a dataset.
    The original study time is kept before any operations are applied.
    For example: orig_study_time = `dataset[0x0008, 0x0030].value`
    """
    logger.debug("Applying tag scheme")

    mrn = dataset[0x0010, 0x0020].value  # Patient ID
    accession_number = dataset[0x0008, 0x0050].value  # Accession Number

    # Set salt based on ENV VAR
    salt_plaintext = config("SALT_VALUE")

    HASHER_API_AZ_NAME = config("HASHER_API_AZ_NAME")
    HASHER_API_PORT = config("HASHER_API_PORT")

    # TODO: Get offset from external source on study-by-study basis.
    # https://github.com/UCLH-Foundry/PIXL/issues/152
    try:
        TIME_OFFSET = int(config("TIME_OFFSET"))
    except ValueError as exc:
        msg = "Failed to set the time offset in hours from the $TIME_OFFSET env var"
        raise RuntimeError(msg) from exc

    logger.debug(b"TIME_OFFSET = %i}" % TIME_OFFSET)

    # Use hasher API to get hash of salt.
    hasher_host_url = "http://" + HASHER_API_AZ_NAME + ":" + HASHER_API_PORT
    payload = "/hash?message=" + salt_plaintext
    request_url = hasher_host_url + payload

    response = requests.get(request_url)

    logger.debug(b"SALT = %a}" % response.content)
    salt = response.content

    # For every entry in the YAML:
    for i in range(len(tags)):
        name = tags[i]["name"]
        grp = tags[i]["group"]
        el = tags[i]["element"]
        op = tags[i]["op"]

        # If this tag should be kept.
        if op == "keep":
            if [grp, el] in dataset:
                message = f"Keeping: {name} (0x{grp:04x},0x{el:04x})"
                logger.debug(f"\t{message}")
            else:
                message = f"Missing: {name} (0x{grp:04x},0x{el:04x})\
                 - Operation ({op})"
                logger.debug(f"\t{message}")

        # If this tag should be deleted.
        elif op == "delete":
            if [grp, el] in dataset:
                del dataset[grp, el]
                message = f"Deleting: {name} (0x{grp:04x},0x{el:04x})"
                logger.debug(f"\t{message}")
            else:
                message = f"Missing: {name} (0x{grp:04x},0x{el:04x})\
                 - Operation ({op})"
                logger.debug(f"\t{message}")

        # Handle UIDs that should be encrypted.
        elif op == "hash-uid":
            if [grp, el] in dataset:
                message = f"Changing: {name} (0x{grp:04x},0x{el:04x})"
                logger.debug(f"\t{message}")

                logger.debug(f"\t\tCurrent UID:\t{dataset[grp,el].value}")
                new_uid = get_encrypted_uid(dataset[grp, el].value, salt)
                dataset[grp, el].value = new_uid
                logger.debug(f"\t\tEncrypted UID:\t{new_uid}")

            else:
                message = f"Missing: {name} (0x{grp:04x},0x{el:04x})\
                 - Operation ({op})"
                logger.debug(f"\t{message}")

        # Shift time relative to the original study time.
        elif op == "time-shift":
            if [grp, el] in dataset:
                # Study date
                if grp == 0x0008 and el == 0x0020:
                    study_date_time = combine_date_time(
                        dataset[0x0008, 0x0020].value, dataset[0x0008, 0x0030].value
                    )
                    new_date = study_date_time.shift(hours=TIME_OFFSET).format(
                        "YYYYMMDD"
                    )
                    logger.debug(
                        f"\tChanging {name}: {dataset[grp,el].value} -> {new_date}"
                    )
                    dataset[grp, el].value = new_date
                # Series date
                if grp == 0x0008 and el == 0x0021:
                    series_date_time = combine_date_time(
                        dataset[0x0008, 0x0021].value, dataset[0x0008, 0x0031].value
                    )
                    new_date = series_date_time.shift(hours=TIME_OFFSET).format(
                        "YYYYMMDD"
                    )
                    logger.debug(
                        f"\tChanging {name}: {dataset[grp,el].value} -> {new_date}"
                    )
                    dataset[grp, el].value = new_date
                # Acq date
                if grp == 0x0008 and el == 0x0022:
                    acq_date_time = combine_date_time(
                        dataset[0x0008, 0x0022].value, dataset[0x0008, 0x0032].value
                    )
                    new_date = acq_date_time.shift(hours=TIME_OFFSET).format("YYYYMMDD")
                    logger.debug(
                        f"\tChanging {name}: {dataset[grp,el].value} -> {new_date}"
                    )
                    dataset[grp, el].value = new_date
                # Image date
                if grp == 0x0008 and el == 0x0023:
                    image_date_time = combine_date_time(
                        dataset[0x0008, 0x0023].value, dataset[0x0008, 0x0033].value
                    )
                    new_date = image_date_time.shift(hours=TIME_OFFSET).format(
                        "YYYYMMDD"
                    )
                    logger.debug(
                        f"\tChanging {name}: {dataset[grp,el].value} -> {new_date}"
                    )
                    dataset[grp, el].value = new_date

                # Study time
                if grp == 0x0008 and el == 0x0030:
                    study_date_time = combine_date_time(
                        dataset[0x0008, 0x0020].value, dataset[0x0008, 0x0030].value
                    )
                    new_time = study_date_time.shift(hours=TIME_OFFSET).format(
                        "HHmmss.SSSSSS"
                    )
                    logger.debug(
                        f"\tChanging {name}: {dataset[grp,el].value} -> {new_time}"
                    )
                    dataset[grp, el].value = new_time
                # Series time
                if grp == 0x0008 and el == 0x0031:
                    series_date_time = combine_date_time(
                        dataset[0x0008, 0x0021].value, dataset[0x0008, 0x0031].value
                    )
                    new_time = series_date_time.shift(hours=TIME_OFFSET).format(
                        "HHmmss.SSSSSS"
                    )
                    logger.debug(
                        f"\tChanging {name}: {dataset[grp,el].value} -> {new_time}"
                    )
                    dataset[grp, el].value = new_time
                # Acq time
                if grp == 0x0008 and el == 0x0032:
                    acq_date_time = combine_date_time(
                        dataset[0x0008, 0x0022].value, dataset[0x0008, 0x0032].value
                    )
                    new_time = acq_date_time.shift(hours=TIME_OFFSET).format(
                        "HHmmss.SSSSSS"
                    )
                    logger.debug(
                        f"\tChanging {name}: {dataset[grp,el].value} -> {new_time}"
                    )
                    dataset[grp, el].value = new_time
                # Image time
                if grp == 0x0008 and el == 0x0033:
                    acq_date_time = combine_date_time(
                        dataset[0x0008, 0x0023].value, dataset[0x0008, 0x0033].value
                    )
                    new_time = acq_date_time.shift(hours=TIME_OFFSET).format(
                        "HHmmss.SSSSSS"
                    )
                    logger.debug(
                        f"\tChanging {name}: {dataset[grp,el].value} -> {new_time}"
                    )
                    dataset[grp, el].value = new_time

                # Acq date+time
                if grp == 0x0008 and el == 0x002A:
                    logger.debug(f"\tChanging {name}: {dataset[grp,el].value}")

                    acq_date_time = format_date_time(dataset[grp, el].value)
                    new_date_time = acq_date_time.shift(hours=TIME_OFFSET).format(
                        "YYYYMMDDHHmmss.SSSSSS"
                    )
                    logger.debug(
                        f"\tChanging {name}: {dataset[grp,el].value} -> {new_date_time}"
                    )
                    dataset[grp, el].value = new_date_time

        # Modify specific tags (make blank).
        elif op == "fixed":
            if grp == 0x0020 and el == 0x0010:
                logger.debug(f"\tRedacting Study ID: {dataset[grp,el].value}")
                dataset[grp, el].value = ""
            if grp == 0x0010 and el == 0x0020:
                logger.debug(f"\tRedacting Patient ID: {dataset[grp,el].value}")
                dataset[grp, el].value = ""

        # Enforce a numerical range.
        elif op == "num-range" and [grp, el] in dataset:
            if grp == 0x0010 and el == 0x1010:
                new_age = get_bounded_age(dataset[grp, el].value)
                logger.debug(
                    f"\tChanging Patient Age: {dataset[grp,el].value} -> {new_age}"
                )
                dataset[grp, el].value = new_age

        # Change value into hash from hasher API.
        elif op == "secure-hash":
            if [grp, el] in dataset:
                if grp == 0x0010 and el == 0x0020:  # Patient ID
                    pat_value = mrn + accession_number

                    hashed_value = _hash_values(grp, el, pat_value, hasher_host_url)
                    # Query PIXL database
                    existing_image = query_db(mrn, accession_number)
                    # Insert the hashed_value into the PIXL database
                    add_hashed_identifier_and_save(existing_image, hashed_value)
                else:
                    pat_value = str(dataset[grp, el].value)

                    hashed_value = _hash_values(grp, el, pat_value, hasher_host_url)
                if dataset[grp, el].VR == "SH":
                    hashed_value = hashed_value[:16]

                dataset[grp, el].value = hashed_value

                message = f"Changing: {name} (0x{grp:04x},0x{el:04x})"
                logger.debug(f"\t{message}")
            else:
                message = f"Missing: {name} (0x{grp:04x},0x{el:04x})\
                 - Operation ({op})"
                logger.debug(f"\t{message}")

    return dataset


def hash_endpoint_path_for_tag(group: bytes, element: bytes) -> str:
    """Call a hasher endpoint depending on the dicom tag group and emement"""
    if group == 0x0010 and element == 0x0020:  # Patient ID
        return "/hash-mrn"
    if group == 0x0008 and element == 0x0050:  # Accession Number
        return "/hash-accession-number"

    return "/hash"


def _hash_values(grp: bytes, el: bytes, pat_value: str, hasher_host_url: str) -> str:
    ep_path = hash_endpoint_path_for_tag(group=grp, element=el)
    payload = ep_path + "?message=" + pat_value
    request_url = hasher_host_url + payload
    response = requests.get(request_url)
    # All three hashing endpoints return application/text so should be fine to
    # use response.text here
    logger.debug("RESPONSE = %s}" % response.text)
    return response.text
