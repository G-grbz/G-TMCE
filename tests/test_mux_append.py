from pathlib import Path

from src.gtmce.core import TrackItem, append_source_options, remove_items_consumed_as_appends


def _item(path: Path, *, append_paths=()):
    return TrackItem(
        entry={"tracks": {"0": {"id": 0, "language": "tr"}}},
        path=path,
        template_index=None,
        append_paths=tuple(append_paths),
    )


def test_manual_append_source_is_not_emitted_as_separate_track(tmp_path):
    base = tmp_path / "tur.eac3"
    append = tmp_path / "sessiz.eac3"
    base.touch()
    append.touch()

    items = remove_items_consumed_as_appends([
        _item(base, append_paths=(append,)),
        _item(append),
    ])

    assert [item.path for item in items] == [base]
    args = []
    append_source_options(args, items[0])
    assert args[-3:] == [str(base), "+", str(append)]
