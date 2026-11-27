"""Validate Korean translation assessments separately from English definitions."""

from review_common import checked_korean, review_cli


if __name__ == "__main__":
    review_cli(checked_korean, __doc__)
