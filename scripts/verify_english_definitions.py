"""Validate independently reviewed English definitions at the sense level."""

from review_common import checked_english, review_cli


def validate_english_only(record, catalog):
    # Preserve pending translation assessments for the separate Korean review step.
    return {**record, **checked_english(record, catalog)}


if __name__ == "__main__":
    review_cli(validate_english_only, __doc__)
