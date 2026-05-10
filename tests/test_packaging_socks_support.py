from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_requirements_include_socksio_runtime_dependency() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "socksio" in requirements


def test_pyinstaller_specs_include_socksio_hiddenimport() -> None:
    spec_paths = [
        ROOT / "onlineworker.spec",
        ROOT / "onlineworker-x86_64.spec",
    ]
    for spec_path in spec_paths:
        spec_text = spec_path.read_text(encoding="utf-8")
        assert "'socksio'" in spec_text, spec_path.name
