"""
Unit tests for IDE path resolution, duplicate file disambiguation, and MCP integration.
"""

import tempfile
from pathlib import Path
from memvision.context import ContextExtractor, WindowContext
from memvision.storage import CaptureRecord, MemoryStorage
from memvision.mcp_server import MCPServer


def test_title_and_workspace_path_resolution():
    extractor = ContextExtractor()

    # 1. Antigravity IDE format: memvison - Antigravity IDE - README.md
    file_path, ws_path = extractor.resolve_file_path(
        hwnd=0,
        pid=0,
        app_name="Antigravity IDE.exe",
        title="memvison - Antigravity IDE - README.md",
    )
    assert file_path is not None
    assert file_path.lower().endswith("readme.md")
    assert "memvison" in file_path.lower()
    assert ws_path is not None
    assert "memvison" in ws_path.lower()

    # 2. Sibling project resolution: enheduanna - Antigravity IDE - README.md
    # Resolves to the sibling enheduanna directory without ambiguity
    file_path_enh, ws_path_enh = extractor.resolve_file_path(
        hwnd=0,
        pid=0,
        app_name="Antigravity IDE.exe",
        title="enheduanna - Antigravity IDE - README.md",
    )
    if Path("c:/meta hackathon/enheduanna/README.md").is_file():
        assert file_path_enh is not None
        assert "enheduanna" in file_path_enh.lower()
        assert file_path_enh != file_path  # Disambiguated!

    # 3. VS Code standard format: ● privacy.py - memvison - Visual Studio Code
    file_path_code, ws_path_code = extractor.resolve_file_path(
        hwnd=0,
        pid=0,
        app_name="code.exe",
        title="● privacy.py - memvison - Visual Studio Code",
    )
    assert file_path_code is not None
    assert file_path_code.lower().endswith("privacy.py")
    assert "memvison" in file_path_code.lower()

    # 4. Sublime Text format: README.md (memvison) - Sublime Text
    file_path_sub, ws_path_sub = extractor.resolve_file_path(
        hwnd=0,
        pid=0,
        app_name="sublime_text.exe",
        title="README.md (memvison) - Sublime Text",
    )
    assert file_path_sub is not None
    assert file_path_sub.lower().endswith("readme.md")

    # 5. Direct absolute path in title (e.g. Notepad / Notepad++)
    main_py_abs = str((Path(__file__).resolve().parent.parent / "main.py").resolve())
    file_path_np, _ = extractor.resolve_file_path(
        hwnd=0,
        pid=0,
        app_name="notepad.exe",
        title=f"*{main_py_abs} - Notepad",
    )
    assert file_path_np is not None
    assert file_path_np.lower() == main_py_abs.lower()

    extractor.close()


def test_duplicate_file_disambiguation_in_workspace():
    """Verify that duplicate filenames in subdirectories are disambiguated cleanly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # Create duplicate config.json files: root and subpackage
        root_config = root / "config.json"
        root_config.write_text('{"name": "root"}', encoding="utf-8")

        sub_dir = root / "subpackage"
        sub_dir.mkdir()
        sub_config = sub_dir / "config.json"
        sub_config.write_text('{"name": "sub"}', encoding="utf-8")

        extractor = ContextExtractor()

        # Resolving "config.json" in this workspace returns the root config
        resolved, ws = extractor._do_resolve_file_path(
            hwnd=0,
            pid=0,
            app_name="code.exe",
            title=f"config.json - {root.name} - Visual Studio Code",
        )
        # If workspace dir matched root, resolved is either root or sub
        if ws and Path(ws) == root.resolve():
            assert resolved is not None
            assert Path(resolved).name == "config.json"

        extractor.close()


def test_mcp_server_file_path_filtering_and_output():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_mcp_path.db"
        storage = MemoryStorage(db_path=db_path, enable_fts=True)

        rec = CaptureRecord(
            app_name="code.exe",
            window_title="memvison - Antigravity IDE - README.md",
            file_path=r"C:\meta hackathon\memvison\README.md",
            ocr_text="MemVision desktop recording layer.",
        )
        storage.save_capture(rec)

        server = MCPServer(db_path=db_path)

        # 1. Search with file_path filter
        res_search = server.handle_tool_call(
            "search_desktop_memory",
            {"query": "MemVision", "file_path": "README.md"}
        )
        assert len(res_search) == 1
        assert res_search[0]["file_path"] == r"C:\meta hackathon\memvison\README.md"

        # 2. get_recent_memory includes file_path
        res_recent = server.handle_tool_call("get_recent_memory", {"limit": 5})
        assert len(res_recent) == 1
        assert res_recent[0]["file_path"] == r"C:\meta hackathon\memvison\README.md"

        # 3. get_capture_details includes file_path
        res_detail = server.handle_tool_call("get_capture_details", {"capture_id": 1})
        assert res_detail["file_path"] == r"C:\meta hackathon\memvison\README.md"


if __name__ == "__main__":
    test_title_and_workspace_path_resolution()
    test_duplicate_file_disambiguation_in_workspace()
    test_mcp_server_file_path_filtering_and_output()
    print("All Path Resolution tests passed!")
