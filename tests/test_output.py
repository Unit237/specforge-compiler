from pathlib import Path

import pytest

from spec_compiler.output import (
    OutputError,
    parse_file_blocks,
    write_outputs,
)


SAMPLE = """
Some commentary the compiler will ignore.

<file path="src/hello.py">
def main():
    print("Hello")
</file>

More commentary.

<file path='README.md'>
# Hello
</file>
"""


def test_parse_two_blocks():
    files = parse_file_blocks(SAMPLE)
    assert [f.path for f in files] == ["src/hello.py", "README.md"]
    assert "def main" in files[0].content
    assert "# Hello" in files[1].content


def test_parse_no_blocks():
    assert parse_file_blocks("nothing here") == []


def test_write_outputs_writes(tmp_path):
    files = parse_file_blocks(SAMPLE)
    written = write_outputs(tmp_path, files)
    assert (tmp_path / "src" / "hello.py").is_file()
    assert (tmp_path / "README.md").is_file()
    assert len(written) == 2


def test_write_outputs_blocks_escape(tmp_path):
    files = parse_file_blocks('<file path="../oops.txt">x</file>')
    with pytest.raises(OutputError):
        write_outputs(tmp_path, files)
