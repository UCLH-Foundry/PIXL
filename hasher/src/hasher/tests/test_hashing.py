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
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st
import pytest

from hasher.hashing import generate_hash, generate_salt


def test_generate_hash_of_default_length(dummy_key):
    message = "test"
    digest = generate_hash(message)
    assert len(digest) == 64
    assert digest == "270426312ab76c2f0df60b6cef3d14aab6bc17219f1a76e63edf88a8f705c17a"


@given(length=st.integers(min_value=-10, max_value=1))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_generate_hash_enforces_min_length(length, dummy_key):
    message = "test"
    with pytest.raises(ValueError):
        generate_hash(message, length)


@given(length=st.integers(min_value=65, max_value=100))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_generate_hash_enforces_max_length(length, dummy_key):
    message = "test"
    with pytest.raises(ValueError):
        generate_hash(message, length)


def test_generate_hash_of_specific_length(dummy_key):
    message = "test"
    length = 16
    digest = generate_hash(message, length)
    assert len(digest) == length
    assert digest == "b88ea642703eed33"


@given(
    message=st.text(min_size=0, max_size=1024),
    length=st.integers(min_value=2, max_value=64),
)
@example(message="9876544321", length=12)
@example(message="1.2.840.10008", length=48)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_generate_hash_output_length(message, length, dummy_key):
    digest = generate_hash(message, length)
    assert len(digest) <= length


def test_generate_salt_of_default_length():
    salt = generate_salt()
    assert len(salt) == 16


@given(length=st.integers(min_value=-10, max_value=1))
def test_generate_salt_enforces_min_length(length):
    with pytest.raises(ValueError):
        generate_salt(length)


@given(length=st.integers(min_value=65, max_value=100))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_generate_salt_enforces_max_length(length):
    with pytest.raises(ValueError):
        generate_salt(length)


def test_generate_salt_of_specific_length(dummy_key):
    length = 9
    salt = generate_salt(length)
    assert len(salt) <= length


def test_generate_salt_produces_unique_outputs(dummy_key):
    salt_1 = generate_salt()
    salt_2 = generate_salt()
    assert salt_1 != salt_2
