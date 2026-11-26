"""The CLI's parser and checks, which the desktop worker reuses."""

import pytest

import inference.realtime as realtime
from inference.opts import OPT_SPEC


@pytest.fixture
def assets(tmp_path, monkeypatch):
    """A complete assets folder in tmp_path, with a model and an index."""
    hubert = tmp_path / "hubert_base"
    hubert.mkdir()
    (hubert / "config.json").write_text("{}")
    (hubert / "pytorch_model.bin").write_bytes(b"")
    (tmp_path / "rmvpe").mkdir()
    (tmp_path / "rmvpe" / "rmvpe.pt").write_bytes(b"")
    (tmp_path / "voice.pth").write_bytes(b"")
    (tmp_path / "voice.index").write_bytes(b"")
    monkeypatch.setattr(realtime, "ASSETS", tmp_path)
    return tmp_path


def parse(*argv):
    return realtime.build_parser().parse_args(list(argv))


def test_every_spec_option_parses_to_its_default():
    args = parse()
    for spec in OPT_SPEC.values():
        attr = spec["flag"].lstrip("-").replace("-", "_")
        assert getattr(args, attr) == spec["default"], spec["flag"]


def test_integer_options_parse_as_int():
    assert parse("--key", "5").key == 5
    assert isinstance(parse("--key", "5").key, int)


def test_check_args_accepts_a_complete_setup(assets):
    args = parse("--model", str(assets / "voice.pth"), "--index", str(assets / "voice.index"))
    assert realtime.check_args(args) is None


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        ((), "--model is required"),
        (("--model", "missing.pth"), "Model not found"),
        (("--index", "missing.index"), "Index not found"),
        (("--f0-min", "500", "--f0-max", "400"), "--f0-min must be positive"),
        (("--input-channels", "0"), "Channel counts"),
        (("--index-neighbors", "0"), "--index-neighbors"),
    ],
)
def test_check_args_names_the_problem(assets, argv, message):
    if argv and argv[0] != "--model":
        argv = ("--model", str(assets / "voice.pth"), *argv)
    assert message in realtime.check_args(parse(*argv))


def test_missing_hubert_is_reported_with_the_download_command(assets):
    (assets / "hubert_base" / "pytorch_model.bin").unlink()
    message = realtime.missing_base_models("fcpe")
    assert "HuBERT model missing" in message and "hubert_base/*" in message


def test_rmvpe_is_required_only_when_it_is_the_tracker(assets):
    (assets / "rmvpe" / "rmvpe.pt").unlink()
    assert "RMVPE model missing" in realtime.missing_base_models("rmvpe")
    assert realtime.missing_base_models("fcpe") is None
    assert realtime.missing_base_models("pm") is None


def test_importing_the_cli_does_not_load_torch():
    import subprocess
    import sys

    code = "import sys, inference.realtime, inference.worker; print('torch' in sys.modules)"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "False"
