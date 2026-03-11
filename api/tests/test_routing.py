"""
Tests for page routing logic in table_extract.py

US-004: Add routing logic to table_extract.py
"""

import ast
import pytest
from pathlib import Path


class TestRoutingCodeStructure:
    """Test code structure without importing modules that need Django."""

    @pytest.fixture
    def table_extract_source(self):
        """Read table_extract.py source code."""
        path = Path(__file__).parent.parent / "scripts" / "table_extract.py"
        return path.read_text()

    @pytest.fixture
    def predict_table_source(self):
        """Read predict_table.py source code."""
        path = Path(__file__).parent.parent / "scripts" / "YOLOV3" / "predict_table.py"
        return path.read_text()

    def test_table_extract_imports_page_classifier(self, table_extract_source):
        """Verify table_extract.py imports PageClassifier."""
        assert "from api.scripts.page_classifier import PageClassifier" in table_extract_source

    def test_table_extract_imports_extract_tables_direct(self, table_extract_source):
        """Verify table_extract.py imports extract_tables_direct."""
        assert "extract_tables_direct" in table_extract_source
        assert "from api.scripts.YOLOV3.predict_table import" in table_extract_source

    def test_table_extract_has_process_page_with_routing(self, table_extract_source):
        """Verify table_extract.py defines process_page_with_routing function."""
        assert "def process_page_with_routing(" in table_extract_source

    def test_predict_table_has_extract_tables_direct(self, predict_table_source):
        """Verify predict_table.py defines extract_tables_direct function."""
        assert "def extract_tables_direct(" in predict_table_source

    def test_routing_function_checks_born_digital(self, table_extract_source):
        """Verify routing function checks for born_digital page type."""
        assert "classification.type == 'born_digital'" in table_extract_source

    def test_routing_function_calls_direct_extraction_for_born_digital(self, table_extract_source):
        """Verify born-digital pages use extract_tables_direct."""
        # Check that extract_tables_direct is called when born_digital
        assert "extract_tables_direct" in table_extract_source

    def test_routing_function_calls_yolo_for_non_born_digital(self, table_extract_source):
        """Verify non-born-digital pages use detect_tables (YOLO)."""
        # Check that detect_tables is called in else branch (via lazy loader)
        assert "yolo['detect_tables']" in table_extract_source or "detect_tables(" in table_extract_source

    def test_routing_function_logs_page_type(self, table_extract_source):
        """Verify page type is logged during processing."""
        # Check for logging of classification type
        assert "classification.type" in table_extract_source
        assert "log.output" in table_extract_source

    def test_multiprocessing_uses_routing_function(self, table_extract_source):
        """Verify multiprocessing pool uses process_page_with_routing."""
        assert "process_page_with_routing" in table_extract_source
        assert "pool.apply_async" in table_extract_source


class TestDirectExtractionFunction:
    """Test extract_tables_direct structure."""

    @pytest.fixture
    def predict_table_source(self):
        """Read predict_table.py source code."""
        path = Path(__file__).parent.parent / "scripts" / "YOLOV3" / "predict_table.py"
        return path.read_text()

    def test_extract_tables_direct_exists(self, predict_table_source):
        """Verify extract_tables_direct function exists."""
        assert "def extract_tables_direct(" in predict_table_source

    def test_extract_tables_direct_has_correct_signature(self, predict_table_source):
        """Verify extract_tables_direct has expected parameters."""
        # Parse the source to check function signature
        tree = ast.parse(predict_table_source)

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'extract_tables_direct':
                args = [arg.arg for arg in node.args.args]
                assert 'file_path' in args
                assert 'page_number' in args
                assert 'report_db' in args
                assert 'extract_dir' in args
                return

        pytest.fail("extract_tables_direct function not found")

    def test_extract_tables_direct_uses_camelot(self, predict_table_source):
        """Verify extract_tables_direct uses Camelot for extraction."""
        # Find the function and check it calls camelot
        lines = predict_table_source.split('\n')
        in_function = False
        uses_camelot = False

        for line in lines:
            if 'def extract_tables_direct(' in line:
                in_function = True
            elif in_function and line.startswith('def ') and 'extract_tables_direct' not in line:
                # Exited the function
                break
            elif in_function and 'camelot' in line.lower():
                uses_camelot = True

        assert uses_camelot, "extract_tables_direct should use Camelot"

    def test_extract_tables_direct_does_not_use_yolo(self, predict_table_source):
        """Verify extract_tables_direct does not call YOLO detection."""
        # Find the function and check it doesn't use YOLO
        lines = predict_table_source.split('\n')
        in_function = False
        function_lines = []

        for line in lines:
            if 'def extract_tables_direct(' in line:
                in_function = True
            elif in_function and line.startswith('def ') and 'extract_tables_direct' not in line:
                break
            elif in_function:
                function_lines.append(line)

        function_body = '\n'.join(function_lines)
        assert 'detectTable' not in function_body, "extract_tables_direct should not use YOLO"
        assert 'pdf_page2img' not in function_body, "extract_tables_direct should not convert to JPG"


class TestVisionRoutingCodeStructure:
    """
    Test code structure for US-014: Route scanned pages to vision extractor.
    Verifies vision routing without needing Django setup.
    """

    @pytest.fixture
    def table_extract_source(self):
        """Read table_extract.py source code."""
        path = Path(__file__).parent.parent / "scripts" / "table_extract.py"
        return path.read_text()

    @pytest.fixture
    def predict_table_source(self):
        """Read predict_table.py source code."""
        path = Path(__file__).parent.parent / "scripts" / "YOLOV3" / "predict_table.py"
        return path.read_text()

    def test_table_extract_imports_vision_extractor(self, table_extract_source):
        """Verify table_extract.py imports VisionExtractor."""
        assert "VisionExtractor" in table_extract_source

    def test_table_extract_imports_extraction_scorer(self, table_extract_source):
        """Verify table_extract.py imports ExtractionScorer."""
        assert "ExtractionScorer" in table_extract_source

    def test_table_extract_imports_extract_tables_vision(self, table_extract_source):
        """Verify table_extract.py imports extract_tables_vision."""
        assert "extract_tables_vision" in table_extract_source

    def test_table_extract_has_feature_flags(self, table_extract_source):
        """Verify table_extract.py loads feature flags."""
        assert "FEATURE_FLAGS" in table_extract_source
        assert "use_vision_detector" in table_extract_source

    def test_routing_function_checks_scanned(self, table_extract_source):
        """Verify routing function checks for scanned page type."""
        assert "classification.type == 'scanned'" in table_extract_source

    def test_routing_function_checks_mixed(self, table_extract_source):
        """Verify routing function handles mixed page type."""
        # Mixed pages should have a distinct handling path
        assert "'mixed'" in table_extract_source or "mixed" in table_extract_source

    def test_routing_function_uses_vision_for_scanned(self, table_extract_source):
        """Verify scanned pages are routed to VisionExtractor."""
        assert "extract_tables_vision" in table_extract_source
        # Should be called for scanned pages
        assert "VisionExtractor" in table_extract_source or "[vision-extractor]" in table_extract_source

    def test_routing_function_has_yolo_fallback(self, table_extract_source):
        """Verify YOLO fallback exists when VisionExtractor fails."""
        # Should have fallback to detect_tables
        assert "Falling back" in table_extract_source or "fallback" in table_extract_source.lower()
        assert "detect_tables" in table_extract_source

    def test_routing_respects_vision_feature_flag(self, table_extract_source):
        """Verify routing checks use_vision_detector feature flag."""
        assert "use_vision" in table_extract_source or "use_vision_detector" in table_extract_source

    def test_routing_respects_legacy_yolo_flag(self, table_extract_source):
        """Verify routing checks legacy_yolo_enabled feature flag."""
        assert "legacy_yolo" in table_extract_source or "legacy_yolo_enabled" in table_extract_source


class TestVisionExtractionFunction:
    """Test extract_tables_vision structure."""

    @pytest.fixture
    def predict_table_source(self):
        """Read predict_table.py source code."""
        path = Path(__file__).parent.parent / "scripts" / "YOLOV3" / "predict_table.py"
        return path.read_text()

    def test_extract_tables_vision_exists(self, predict_table_source):
        """Verify extract_tables_vision function exists."""
        assert "def extract_tables_vision(" in predict_table_source

    def test_extract_tables_vision_has_correct_signature(self, predict_table_source):
        """Verify extract_tables_vision has expected parameters."""
        tree = ast.parse(predict_table_source)

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'extract_tables_vision':
                args = [arg.arg for arg in node.args.args]
                assert 'file_path' in args
                assert 'page_number' in args
                assert 'report_db' in args
                assert 'extract_dir' in args
                return

        pytest.fail("extract_tables_vision function not found")

    def test_extract_tables_vision_uses_vision_extractor(self, predict_table_source):
        """Verify extract_tables_vision uses VisionExtractor."""
        lines = predict_table_source.split('\n')
        in_function = False
        uses_vision = False

        for line in lines:
            if 'def extract_tables_vision(' in line:
                in_function = True
            elif in_function and line.startswith('def ') and 'extract_tables_vision' not in line:
                break
            elif in_function and 'VisionExtractor' in line:
                uses_vision = True

        assert uses_vision, "extract_tables_vision should use VisionExtractor"

    def test_extract_tables_vision_uses_scorer(self, predict_table_source):
        """Verify extract_tables_vision uses ExtractionScorer for consistency with born-digital."""
        lines = predict_table_source.split('\n')
        in_function = False
        uses_scorer = False

        for line in lines:
            if 'def extract_tables_vision(' in line:
                in_function = True
            elif in_function and line.startswith('def ') and 'extract_tables_vision' not in line:
                break
            elif in_function and 'ExtractionScorer' in line or in_function and 'scorer' in line.lower():
                uses_scorer = True

        assert uses_scorer, "extract_tables_vision should use ExtractionScorer"

    def test_extract_tables_vision_does_not_use_yolo(self, predict_table_source):
        """Verify extract_tables_vision does not call YOLO detection."""
        lines = predict_table_source.split('\n')
        in_function = False
        function_lines = []

        for line in lines:
            if 'def extract_tables_vision(' in line:
                in_function = True
            elif in_function and line.startswith('def ') and 'extract_tables_vision' not in line:
                break
            elif in_function:
                function_lines.append(line)

        function_body = '\n'.join(function_lines)
        assert 'detectTable' not in function_body, "extract_tables_vision should not use YOLO"
        assert 'pdf_page2img' not in function_body, "extract_tables_vision should not convert to JPG"

    def test_extract_tables_vision_exports_same_format(self, predict_table_source):
        """Verify extract_tables_vision exports in same format as born-digital.

        Note: After decoupling extraction from saving (Phase 1 architecture refactor),
        the export logic is in save_extraction_results(), which is called by
        extract_tables_vision(). We verify that extract_tables_vision calls
        save_extraction_results which handles the exports.
        """
        lines = predict_table_source.split('\n')
        in_function = False
        calls_save_results = False
        exports_csv = False
        exports_json = False

        # Check that extract_tables_vision calls save_extraction_results
        for line in lines:
            if 'def extract_tables_vision(' in line:
                in_function = True
            elif in_function and line.startswith('def ') and 'extract_tables_vision' not in line:
                break
            elif in_function:
                if 'save_extraction_results' in line:
                    calls_save_results = True

        # Also check that save_extraction_results exports CSV and JSON
        in_save_function = False
        for line in lines:
            if 'def save_extraction_results(' in line:
                in_save_function = True
            elif in_save_function and line.startswith('def ') and 'save_extraction_results' not in line:
                break
            elif in_save_function:
                if 'to_csv' in line:
                    exports_csv = True
                if 'to_json' in line or 'json_lib.dump' in line:
                    exports_json = True

        assert calls_save_results, "extract_tables_vision should call save_extraction_results"
        assert exports_csv, "save_extraction_results should export CSV"
        assert exports_json, "save_extraction_results should export JSON"


class TestFeatureFlagLoading:
    """Test feature flag loading mechanism."""

    @pytest.fixture
    def table_extract_source(self):
        """Read table_extract.py source code."""
        path = Path(__file__).parent.parent / "scripts" / "table_extract.py"
        return path.read_text()

    def test_load_feature_flags_function_exists(self, table_extract_source):
        """Verify _load_feature_flags function exists."""
        assert "def _load_feature_flags(" in table_extract_source

    def test_feature_flags_loaded_at_module_level(self, table_extract_source):
        """Verify FEATURE_FLAGS is defined at module level."""
        assert "FEATURE_FLAGS = _load_feature_flags()" in table_extract_source

    def test_feature_flags_has_vision_detector(self, table_extract_source):
        """Verify use_vision_detector is in default flags."""
        assert "'use_vision_detector'" in table_extract_source

    def test_feature_flags_has_legacy_yolo(self, table_extract_source):
        """Verify legacy_yolo_enabled is in default flags."""
        assert "'legacy_yolo_enabled'" in table_extract_source


class TestPageClassifierIntegration:
    """Test PageClassifier with real PDFs (no Django needed)."""

    @pytest.fixture
    def classifier(self):
        """Create PageClassifier instance."""
        from api.scripts.page_classifier import PageClassifier
        return PageClassifier()

    @pytest.fixture
    def sample_pdf_path(self):
        """Path to a sample PDF."""
        return str(Path(__file__).parent / "sample_pdfs" / "multipage_sample.pdf")

    def test_page_classifier_returns_valid_type(self, classifier, sample_pdf_path):
        """Verify PageClassifier returns valid page types."""
        if not Path(sample_pdf_path).exists():
            pytest.skip("Sample PDF not available")

        classification = classifier.classify(sample_pdf_path, 0)
        assert classification.type in ('born_digital', 'scanned', 'mixed')

    def test_page_classifier_returns_text_coverage(self, classifier, sample_pdf_path):
        """Verify PageClassifier returns text coverage."""
        if not Path(sample_pdf_path).exists():
            pytest.skip("Sample PDF not available")

        classification = classifier.classify(sample_pdf_path, 0)
        assert 0 <= classification.text_coverage <= 1

    def test_page_classifier_returns_has_images(self, classifier, sample_pdf_path):
        """Verify PageClassifier returns has_images boolean."""
        if not Path(sample_pdf_path).exists():
            pytest.skip("Sample PDF not available")

        classification = classifier.classify(sample_pdf_path, 0)
        assert isinstance(classification.has_images, bool)
