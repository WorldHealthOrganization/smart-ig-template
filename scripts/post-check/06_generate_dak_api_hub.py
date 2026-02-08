#!/usr/bin/env python3
"""
DAK API Documentation Hub Generator

Post-process IG-generated HTML to inject DAK API content and produce a hub.

Workflow:
1) Detect JSON schemas (ValueSet and Logical Model schemas) in output/schemas
2) Create minimal OpenAPI 3.0 wrappers for each JSON schema (output/schemas/*.openapi.json)
3) Detect existing OpenAPI files in input/images/openapi and output/images/openapi
4) Optionally extract content from an existing OpenAPI index.html and embed into hub
5) Post-process output/dak-api.html by replacing <div id="dak-api-content-placeholder">...</div>
6) Merge QA with existing IG qa.json

Usage:
    python generate_dak_api_hub.py [ig_root]
    python generate_dak_api_hub.py [output_dir] [openapi_dir]

Author: SMART Guidelines Team
"""

import json
import os
import sys
import logging
import re
import tempfile
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    return logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# QA Reporter
# ---------------------------------------------------------------------------

class QAReporter:
    """Handles QA reporting for post-processing steps and merging with FHIR IG publisher QA."""

    def __init__(self, phase: str = "postprocessing"):
        self.phase = phase
        self.timestamp = datetime.now().isoformat()
        self.report = {
            "phase": phase,
            "timestamp": self.timestamp,
            "status": "running",
            "summary": {},
            "details": {
                "successes": [],
                "warnings": [],
                "errors": [],
                "files_processed": [],
                "files_expected": [],
                "files_missing": [],
            },
        }
        self.ig_publisher_qa = None
        self._stored_preprocessing_reports: List[Dict[str, Any]] = []

    def load_existing_ig_qa(self, qa_file_path: str) -> bool:
        try:
            if os.path.exists(qa_file_path):
                with open(qa_file_path, "r", encoding="utf-8") as f:
                    self.ig_publisher_qa = json.load(f)
                print(f"Loaded existing IG publisher QA file: {qa_file_path}")
                return True
            print(f"No existing IG publisher QA file found at: {qa_file_path}")
            return False
        except Exception as e:
            print(f"Error loading existing IG publisher QA file: {e}")
            return False

    def add_success(self, message: str, details: Optional[Dict[str, Any]] = None):
        entry: Dict[str, Any] = {"message": message, "timestamp": datetime.now().isoformat()}
        if details:
            entry["details"] = details
        self.report["details"]["successes"].append(entry)

    def add_warning(self, message: str, details: Optional[Dict[str, Any]] = None):
        entry: Dict[str, Any] = {"message": message, "timestamp": datetime.now().isoformat()}
        if details:
            entry["details"] = details
        self.report["details"]["warnings"].append(entry)

    def add_error(self, message: str, details: Optional[Dict[str, Any]] = None):
        entry: Dict[str, Any] = {"message": message, "timestamp": datetime.now().isoformat()}
        if details:
            entry["details"] = details
        self.report["details"]["errors"].append(entry)

    def add_file_processed(self, file_path: str, status: str = "success", details: Optional[Dict[str, Any]] = None):
        entry: Dict[str, Any] = {
            "file": file_path,
            "status": status,
            "timestamp": datetime.now().isoformat(),
        }
        if details:
            entry["details"] = details
        self.report["details"]["files_processed"].append(entry)

    def add_file_expected(self, file_path: str, found: bool = False):
        self.report["details"]["files_expected"].append(file_path)
        if not found:
            self.report["details"]["files_missing"].append(file_path)

    def merge_preprocessing_report(self, preprocessing_report: Dict[str, Any]):
        # Store for merge step (and also fold high-level entries into ours for quick summary)
        self._stored_preprocessing_reports.append(preprocessing_report)

        component_name = preprocessing_report.get("component", preprocessing_report.get("phase", "Unknown"))
        details = preprocessing_report.get("details", {})

        for success in details.get("successes", []):
            self.add_success(f"[{component_name}] {success.get('message', '')}", success.get("details"))
        for warning in details.get("warnings", []):
            self.add_warning(f"[{component_name}] {warning.get('message', '')}", warning.get("details"))
        for error in details.get("errors", []):
            self.add_error(f"[{component_name}] {error.get('message', '')}", error.get("details"))
        for file_proc in details.get("files_processed", []):
            self.add_file_processed(
                f"[{component_name}] {file_proc.get('file', '')}",
                file_proc.get("status", "unknown"),
                file_proc.get("details"),
            )

    def finalize_report(self, status: str = "completed") -> Dict[str, Any]:
        self.report["status"] = status
        self.report["summary"] = {
            "total_successes": len(self.report["details"]["successes"]),
            "total_warnings": len(self.report["details"]["warnings"]),
            "total_errors": len(self.report["details"]["errors"]),
            "files_processed_count": len(self.report["details"]["files_processed"]),
            "files_expected_count": len(self.report["details"]["files_expected"]),
            "files_missing_count": len(self.report["details"]["files_missing"]),
            "completion_timestamp": datetime.now().isoformat(),
        }

        if self.ig_publisher_qa:
            return self.merge_with_ig_publisher_qa()
        return self.report

    def merge_with_ig_publisher_qa(self) -> Dict[str, Any]:
        try:
            merged = dict(self.ig_publisher_qa)

            preprocessing_reports: Dict[str, Any] = {}
            for i, rep in enumerate(self._stored_preprocessing_reports):
                name = rep.get("component", rep.get("phase", f"component_{i}"))
                preprocessing_reports[name] = rep

            merged["dak_api_processing"] = {
                "preprocessing_reports": preprocessing_reports,
                "postprocessing": self.report,
                "summary": {
                    "total_dak_api_successes": self.report["summary"]["total_successes"],
                    "total_dak_api_warnings": self.report["summary"]["total_warnings"],
                    "total_dak_api_errors": self.report["summary"]["total_errors"],
                    "dak_api_completion_timestamp": self.report["summary"]["completion_timestamp"],
                },
            }
            return merged
        except Exception as e:
            print(f"Error merging with IG publisher QA: {e}")
            return self.report

    def save_to_file(self, output_path: str, payload: Optional[Dict[str, Any]] = None) -> bool:
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            to_write = payload if payload is not None else self.report
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(to_write, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving QA report to {output_path}: {e}")
            return False


# ---------------------------------------------------------------------------
# Schema / JSON-LD Detection
# ---------------------------------------------------------------------------

class SchemaDetector:
    """Detects and categorizes schema files in the output directory."""

    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def find_schema_files(self, schema_dir: str) -> Dict[str, List[str]]:
        schemas: Dict[str, List[str]] = {"valueset": [], "logical_model": [], "other": []}

        if not os.path.exists(schema_dir):
            self.logger.warning(f"Schema directory does not exist: {schema_dir}")
            return schemas

        self.logger.info(f"Scanning directory for schema files: {schema_dir}")
        all_files = os.listdir(schema_dir)
        schema_count = 0

        for file in all_files:
            if not file.endswith(".schema.json"):
                continue
            schema_count += 1
            file_path = os.path.join(schema_dir, file)
            self.logger.info(f"Found schema file: {file}")

            if file.startswith("ValueSet-"):
                schemas["valueset"].append(file_path)
                self.logger.info("  -> Categorized as ValueSet schema")
            elif file in ["ValueSets.schema.json", "LogicalModels.schema.json"]:
                if file == "ValueSets.schema.json":
                    schemas["valueset"].append(file_path)
                    self.logger.info("  -> Categorized as ValueSet enumeration schema")
                else:
                    schemas["logical_model"].append(file_path)
                    self.logger.info("  -> Categorized as Logical Model enumeration schema")
            elif not file.startswith("ValueSet-") and not file.startswith("CodeSystem-"):
                schemas["logical_model"].append(file_path)
                self.logger.info("  -> Categorized as Logical Model schema")
            else:
                schemas["other"].append(file_path)
                self.logger.info("  -> Categorized as other schema")

        self.logger.info("Schema detection summary:")
        self.logger.info(f"  Total schema files found: {schema_count}")
        self.logger.info(f"  ValueSet schemas: {len(schemas['valueset'])}")
        self.logger.info(f"  Logical Model schemas: {len(schemas['logical_model'])}")
        self.logger.info(f"  Other schemas: {len(schemas['other'])}")

        if schema_count == 0:
            self.logger.warning(f"No .schema.json files found in {schema_dir}")
            self.logger.info(f"Directory contents: {', '.join(all_files)}")

        return schemas

    def find_jsonld_files(self, schema_dir: str) -> List[str]:
        jsonld_files: List[str] = []

        if not os.path.exists(schema_dir):
            self.logger.warning(f"Schema directory does not exist: {schema_dir}")
            return jsonld_files

        self.logger.info(f"Scanning directory for JSON-LD files: {schema_dir}")
        all_files = os.listdir(schema_dir)
        jsonld_count = 0

        for file in all_files:
            if not file.endswith(".jsonld"):
                continue
            jsonld_count += 1
            file_path = os.path.join(schema_dir, file)
            self.logger.info(f"Found JSON-LD file: {file}")

            if file.startswith("ValueSet-"):
                jsonld_files.append(file_path)
                self.logger.info("  -> Added ValueSet JSON-LD vocabulary")
            else:
                self.logger.info("  -> Skipped non-ValueSet JSON-LD file")

        self.logger.info("JSON-LD detection summary:")
        self.logger.info(f"  Total JSON-LD files found: {jsonld_count}")
        self.logger.info(f"  ValueSet JSON-LD vocabularies: {len(jsonld_files)}")

        return jsonld_files


# ---------------------------------------------------------------------------
# OpenAPI Detection + Existing HTML extraction
# ---------------------------------------------------------------------------

class OpenAPIDetector:
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def find_openapi_files(self, openapi_dir: str) -> List[str]:
        openapi_files: List[str] = []

        if not os.path.exists(openapi_dir):
            self.logger.info(f"OpenAPI directory does not exist: {openapi_dir}")
            return openapi_files

        self.logger.info(f"Scanning for OpenAPI files in: {openapi_dir}")

        for root, _, files in os.walk(openapi_dir):
            for file in files:
                if file.lower() == "index.html":
                    continue
                if not file.endswith((".json", ".yaml", ".yml")):
                    continue

                name = file.lower()
                if (
                    "openapi" in name
                    or "swagger" in name
                    or "api" in name
                    or name.endswith(".openapi.json")
                    or name.endswith(".openapi.yaml")
                ):
                    full = os.path.join(root, file)
                    openapi_files.append(full)
                    self.logger.info(f"Found OpenAPI file: {file}")

        self.logger.info(f"Found {len(openapi_files)} OpenAPI/Swagger files total")
        return openapi_files

    def find_existing_html_content(self, openapi_dir: str) -> Optional[str]:
        index_html_path = os.path.join(openapi_dir, "index.html")
        if not os.path.exists(index_html_path):
            self.logger.info(f"No existing index.html found in: {openapi_dir}")
            return None

        try:
            from bs4 import BeautifulSoup  # type: ignore

            self.logger.info(f"Found existing OpenAPI HTML content at: {index_html_path}")
            with open(index_html_path, "r", encoding="utf-8") as f:
                html_content = f.read()

            soup = BeautifulSoup(html_content, "html.parser")
            body = soup.find("body")
            if not body:
                self.logger.warning("No <body> tag found in existing index.html")
                return None

            for script in body.find_all(["script", "noscript"]):
                script.decompose()

            content_container = (
                body.find("div", class_=lambda x: x and "container" in x.lower())
                or body.find("div", class_=lambda x: x and "content" in x.lower())
                or body.find("main")
                or body.find("div", id=lambda x: x and "content" in x.lower())
                or body
            )

            extracted = str(content_container)
            if content_container == body:
                extracted = extracted.replace("<body>", "").replace("</body>", "")
                if extracted.startswith("<body "):
                    end_tag = extracted.find(">")
                    if end_tag != -1:
                        extracted = extracted[end_tag + 1 :]

            self.logger.info(f"Extracted {len(extracted)} characters of HTML content from existing index.html")
            return extracted.strip()

        except ImportError:
            self.logger.error("BeautifulSoup not available. Please install beautifulsoup4: pip install beautifulsoup4")
            return None
        except Exception as e:
            self.logger.error(f"Error parsing existing HTML content: {e}")
            return None


# ---------------------------------------------------------------------------
# OpenAPI Wrappers for JSON Schema
# ---------------------------------------------------------------------------

class OpenAPIWrapper:
    def __init__(self, logger: logging.Logger, canonical_base: str = "http://smart.who.int/base"):
        self.logger = logger
        self.canonical_base = canonical_base

    def create_wrapper_for_schema(self, schema_path: str, schema_type: str, output_dir: str) -> Optional[str]:
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                schema = json.load(f)

            schema_filename = os.path.basename(schema_path)
            schema_name = schema_filename.replace(".schema.json", "")

            endpoint_path = f"/{schema_filename}"
            if schema_type == "valueset":
                summary = f"JSON Schema definition for the enumeration {schema_name}"
                description = f"This endpoint serves the JSON Schema definition for the enumeration {schema_name}."
            else:
                summary = f"JSON Schema definition for the Logical Model {schema_name}"
                description = f"This endpoint serves the JSON Schema definition for the Logical Model {schema_name}."

            openapi_spec = {
                "openapi": "3.0.3",
                "info": {
                    "title": f"{schema.get('title', schema_name)} API",
                    "description": schema.get("description", f"API for {schema_name} schema"),
                    "version": "1.0.0",
                },
                "paths": {
                    endpoint_path: {
                        "get": {
                            "summary": summary,
                            "description": description,
                            "responses": {
                                "200": {
                                    "description": f"The JSON Schema for {schema_name}",
                                    "content": {
                                        "application/schema+json": {
                                            "schema": {"$ref": f"./{schema_filename}"}
                                        }
                                    },
                                }
                            },
                        }
                    }
                },
                "components": {"schemas": {schema_name: schema}},
            }

            wrapper_filename = f"{schema_name}.openapi.json"
            wrapper_path = os.path.join(output_dir, wrapper_filename)
            with open(wrapper_path, "w", encoding="utf-8") as f:
                json.dump(openapi_spec, f, indent=2, ensure_ascii=False)

            self.logger.info(f"Created OpenAPI wrapper: {wrapper_path}")
            return wrapper_path

        except Exception as e:
            self.logger.error(f"Error creating OpenAPI wrapper for {schema_path}: {e}")
            return None

    def create_enumeration_wrapper(self, enum_schema_path: str, schema_type: str, output_dir: str) -> Optional[str]:
        try:
            with open(enum_schema_path, "r", encoding="utf-8") as f:
                enum_schema = json.load(f)

            if schema_type == "valueset":
                endpoint_path = "/ValueSets.schema.json"
                api_title = "ValueSets Enumeration API"
                api_description = "API endpoint providing an enumeration of all available ValueSet schemas"
                wrapper_filename = "ValueSets-enumeration.openapi.json"
            else:
                endpoint_path = "/LogicalModels.schema.json"
                api_title = "LogicalModels Enumeration API"
                api_description = "API endpoint providing an enumeration of all available Logical Model schemas"
                wrapper_filename = "LogicalModels-enumeration.openapi.json"

            openapi_spec = {
                "openapi": "3.0.3",
                "info": {"title": api_title, "description": api_description, "version": "1.0.0"},
                "paths": {
                    endpoint_path: {
                        "get": {
                            "summary": f"Get enumeration of all {schema_type} schemas",
                            "description": f"Returns a list of all available {schema_type} schemas with metadata",
                            "responses": {
                                "200": {
                                    "description": f"Successfully retrieved {schema_type} enumeration",
                                    "content": {
                                        "application/json": {
                                            "schema": {"$ref": "#/components/schemas/EnumerationResponse"},
                                            "example": enum_schema.get("example", {}),
                                        }
                                    },
                                }
                            },
                        }
                    }
                },
                "components": {"schemas": {"EnumerationResponse": enum_schema}},
            }

            wrapper_path = os.path.join(output_dir, wrapper_filename)
            with open(wrapper_path, "w", encoding="utf-8") as f:
                json.dump(openapi_spec, f, indent=2, ensure_ascii=False)

            self.logger.info(f"Created enumeration OpenAPI wrapper: {wrapper_path}")
            return wrapper_path

        except Exception as e:
            self.logger.error(f"Error creating enumeration OpenAPI wrapper for {enum_schema_path}: {e}")
            return None


# ---------------------------------------------------------------------------
# HTML Processor
# ---------------------------------------------------------------------------

class HTMLProcessor:
    def __init__(self, logger: logging.Logger, output_dir: str):
        self.logger = logger
        self.output_dir = output_dir

    def inject_content_at_comment_marker(self, html_file_path: str, content: str) -> bool:
        try:
            self.logger.info(f"🔍 Starting content injection into: {html_file_path}")
            self.logger.info(f"📏 Content to inject length: {len(content)} characters")

            if not os.path.exists(html_file_path):
                self.logger.error(f"❌ HTML file does not exist: {html_file_path}")
                return False

            with open(html_file_path, "r", encoding="utf-8") as f:
                html_content = f.read()

            self.logger.info(f"📖 Read HTML file, original length: {len(html_content)} characters")

            placeholder_pattern = r'<div\s+id="dak-api-content-placeholder"[^>]*>.*?</div>'
            if not re.search(placeholder_pattern, html_content, re.DOTALL):
                comment_marker = "<!-- DAK_API_CONTENT -->"
                if comment_marker in html_content:
                    self.logger.info("✅ Found legacy DAK_API_CONTENT comment marker")
                    new_html = html_content.replace(comment_marker, content)
                else:
                    self.logger.error(f"❌ DAK API placeholder div not found in {html_file_path}")
                    self.logger.info('Looking for: <div id="dak-api-content-placeholder">')
                    self.logger.info("Available content sample for debugging:")
                    sample = html_content[:1000] if len(html_content) > 1000 else html_content
                    self.logger.info(sample)
                    return False
            else:
                self.logger.info("✅ Found DAK API placeholder div")
                new_html = re.sub(placeholder_pattern, content, html_content, flags=re.DOTALL)

            self.logger.info(f"📏 Content replacement: original={len(html_content)}, new={len(new_html)}")
            with open(html_file_path, "w", encoding="utf-8") as f:
                f.write(new_html)

            size_increase = len(new_html) - len(html_content)
            self.logger.info(f"💾 Successfully wrote modified HTML back to {html_file_path}")
            self.logger.info(f"📏 Final HTML file size: {len(new_html)} characters (increased by {size_increase})")

            if size_increase > 100:
                self.logger.info("✅ Content injection appears successful (substantial size increase)")
                return True
            self.logger.warning(f"⚠️  Content injection may have failed (minimal size increase: {size_increase})")
            return False

        except Exception as e:
            self.logger.error(f"❌ Error injecting content into {html_file_path}: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False


# ---------------------------------------------------------------------------
# Schema Documentation Renderer (OpenAPI injection into existing HTML)
# ---------------------------------------------------------------------------

class SchemaDocumentationRenderer:
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def _find_injection_point(self, html_content: str, schema_type: str) -> Optional[int]:
        try:
            if schema_type == "logical_model":
                patterns = [
                    r"<h3[^>]*>Formal Views of Profile Content</h3>.*?</div>\s*</div>",
                    r"<h2[^>]*>Formal Views of Profile Content</h2>.*?</div>\s*</div>",
                    r"<h3[^>]*>Formal Views</h3>.*?</div>\s*</div>",
                    r"<h2[^>]*>Formal Views</h2>.*?</div>\s*</div>",
                ]
                for p in patterns:
                    m = re.search(p, html_content, re.DOTALL | re.IGNORECASE)
                    if m:
                        self.logger.info("Found 'Formal Views' section for injection point")
                        return m.end()

            if schema_type == "valueset":
                patterns = [
                    r"<h3[^>]*>Expansion</h3>.*?</div>\s*</div>",
                    r"<h2[^>]*>Expansion</h2>.*?</div>\s*</div>",
                    r"<h4[^>]*>Expansion</h4>.*?</div>\s*</div>",
                ]
                for p in patterns:
                    m = re.search(p, html_content, re.DOTALL | re.IGNORECASE)
                    if m:
                        self.logger.info("Found 'Expansion' section for injection point")
                        return m.end()

            fallback = [
                r"</main>",
                r"</body>",
            ]
            for p in fallback:
                m = re.search(p, html_content, re.IGNORECASE)
                if m:
                    self.logger.info("Using fallback injection point")
                    return m.start()

            self.logger.warning("No suitable injection point found")
            return None
        except Exception as e:
            self.logger.error(f"Error finding injection point: {e}")
            return None

    def _generate_html_content(self, spec_data: dict) -> str:
        info = spec_data.get("info", {})
        paths = spec_data.get("paths", {})
        components = spec_data.get("components", {})
        schemas = components.get("schemas", {})

        html = [
            '<div class="dak-api-content">',
            "<h2>API Information</h2>",
            '<div class="card"><div class="card-body">',
            f"<h5>{info.get('title', 'API')}</h5>",
            f"<p>{info.get('description', 'No description available')}</p>",
            f"<p><strong>Version:</strong> {info.get('version', 'Unknown')}</p>",
            "</div></div>",
        ]

        if paths:
            html.append("<h2>Endpoints</h2>")
            for path, methods in paths.items():
                for method, op in methods.items():
                    html.append('<div class="endpoint-card">')
                    html.append(f"<h3><span class='badge badge-{method.lower()}'>{method.upper()}</span> {path}</h3>")
                    html.append(f"<h4>{op.get('summary', 'No summary')}</h4>")
                    html.append(f"<p>{op.get('description', 'No description available')}</p>")
                    html.append("</div>")

        if schemas:
            html.append("<h2>Schema Definition</h2>")
            for name, sdef in schemas.items():
                html.append('<div class="schema-card">')
                html.append(f"<h3>{name}</h3>")
                html.append(f"<p><strong>Description:</strong> {sdef.get('description', 'No description')}</p>")
                html.append(f"<p><strong>Type:</strong> {sdef.get('type', 'unknown')}</p>")
                html.append("<details class='schema-details'><summary>Full Schema (JSON)</summary>")
                html.append("<pre><code class='language-json'>")
                html.append(json.dumps(sdef, indent=2))
                html.append("</code></pre></details>")
                html.append("</div>")

        html.append("</div>")
        html.append("""
<style>
.dak-api-content { margin: 1rem 0; }
.card, .schema-card, .endpoint-card { background:#f8f9fa; border:1px solid #dee2e6; border-radius:0.375rem; padding:1rem; margin:1rem 0; }
.badge-get { background-color:#28a745; }
.badge-post { background-color:#007bff; }
.badge-put { background-color:#ffc107; color:#212529; }
.badge-delete { background-color:#dc3545; }
.badge-patch { background-color:#6f42c1; }
.schema-details { margin:1rem 0; border:1px solid #dee2e6; border-radius:4px; }
.schema-details summary { background:#f8f9fa; padding:0.75rem; cursor:pointer; border-bottom:1px solid #dee2e6; font-weight:500; }
.schema-details pre { margin:1rem; background:#f8f9fa; border:1px solid #e9ecef; border-radius:4px; padding:1rem; overflow-x:auto; }
</style>
<p><em>This documentation is automatically generated from the OpenAPI specification.</em></p>
""")
        return "\n".join(html)

    def inject_into_html(self, openapi_path: str, output_dir: str, title: Optional[str] = None) -> Optional[str]:
        try:
            openapi_filename = os.path.basename(openapi_path)
            spec_name = (
                openapi_filename.replace(".openapi.json", "")
                .replace(".openapi.yaml", "")
                .replace(".yaml", "")
                .replace(".yml", "")
                .replace(".json", "")
            )

            if title is None:
                title = f"{spec_name} API Documentation"

            with open(openapi_path, "r", encoding="utf-8") as f:
                spec_data = json.load(f)

            html_filename = f"{spec_name}.html"
            html_path = os.path.join(output_dir, html_filename)
            if not os.path.exists(html_path):
                self.logger.warning(f"HTML file not found: {html_path}")
                return None

            with open(html_path, "r", encoding="utf-8") as f:
                html_content = f.read()

            # attempt placeholder marker, else heuristic injection point
            placeholder_marker = f"<!-- DAK_API_PLACEHOLDER: {spec_name} -->"
            if placeholder_marker in html_content:
                injection_point = html_content.find(placeholder_marker)
                doc = self._generate_html_content(spec_data)
                updated = html_content.replace(placeholder_marker, doc)
            else:
                # guess schema type
                if spec_name.startswith("ValueSet-"):
                    schema_type = "valueset"
                elif spec_name.startswith("StructureDefinition-") or spec_name.startswith("LogicalModel-"):
                    schema_type = "logical_model"
                else:
                    schema_type = "unknown"

                injection_point = self._find_injection_point(html_content, schema_type)
                if injection_point is None:
                    self.logger.error(f"No suitable injection point found in {html_path}")
                    return None
                doc = self._generate_html_content(spec_data)
                updated = html_content[:injection_point] + doc + html_content[injection_point:]

            with open(html_path, "w", encoding="utf-8") as f:
                f.write(updated)

            self.logger.info(f"Injected OpenAPI content into HTML file: {html_path}")
            return html_filename

        except Exception as e:
            self.logger.error(f"Error injecting content into HTML for {openapi_path}: {e}")
            return None


# ---------------------------------------------------------------------------
# Hub Generator
# ---------------------------------------------------------------------------

class DAKApiHubGenerator:
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def create_enumeration_schema(self, schema_type: str, schema_files: List[str], output_dir: str) -> Optional[str]:
        try:
            schemas_list: List[Dict[str, Any]] = []
            for schema_path in schema_files:
                try:
                    with open(schema_path, "r", encoding="utf-8") as f:
                        schema = json.load(f)

                    schema_filename = os.path.basename(schema_path)
                    entry: Dict[str, Any] = {
                        "filename": schema_filename,
                        "id": schema.get("$id", ""),
                        "title": schema.get("title", schema_filename),
                        "description": schema.get("description", ""),
                        "url": f"./{schema_filename}",
                    }

                    if schema_type == "valueset":
                        if "fhir:valueSet" in schema:
                            entry["valueSetUrl"] = schema["fhir:valueSet"]
                        if "enum" in schema:
                            entry["codeCount"] = len(schema["enum"])
                    else:
                        if "fhir:logicalModel" in schema:
                            entry["logicalModelUrl"] = schema["fhir:logicalModel"]
                        if "properties" in schema:
                            entry["propertyCount"] = len(schema["properties"])

                    schemas_list.append(entry)
                except Exception as e:
                    self.logger.warning(f"Error reading schema {schema_path}: {e}")

            if schema_type == "valueset":
                enum_filename = "ValueSets.schema.json"
                enum_title = "ValueSet Enumeration Schema"
                enum_description = "JSON Schema defining the structure of the ValueSet enumeration endpoint response"
            else:
                enum_filename = "LogicalModels.schema.json"
                enum_title = "Logical Model Enumeration Schema"
                enum_description = "JSON Schema defining the structure of the Logical Model enumeration endpoint response"

            enumeration_schema: Dict[str, Any] = {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": f"#/{enum_filename}",
                "title": enum_title,
                "description": enum_description,
                "type": "object",
                "properties": {
                    "type": {"type": "string", "const": schema_type},
                    "count": {"type": "integer"},
                    "schemas": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "filename": {"type": "string"},
                                "id": {"type": "string"},
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                                "url": {"type": "string"},
                            },
                            "required": ["filename", "title", "url"],
                        },
                    },
                },
                "required": ["type", "count", "schemas"],
                "example": {"type": schema_type, "count": len(schemas_list), "schemas": schemas_list},
            }

            if schema_type == "valueset":
                enumeration_schema["properties"]["schemas"]["items"]["properties"]["valueSetUrl"] = {"type": "string"}
                enumeration_schema["properties"]["schemas"]["items"]["properties"]["codeCount"] = {"type": "integer"}
            else:
                enumeration_schema["properties"]["schemas"]["items"]["properties"]["logicalModelUrl"] = {"type": "string"}
                enumeration_schema["properties"]["schemas"]["items"]["properties"]["propertyCount"] = {"type": "integer"}

            enum_path = os.path.join(output_dir, enum_filename)
            with open(enum_path, "w", encoding="utf-8") as f:
                json.dump(enumeration_schema, f, indent=2, ensure_ascii=False)

            self.logger.info(f"Created enumeration schema: {enum_path}")
            return enum_path

        except Exception as e:
            self.logger.error(f"Error creating enumeration schema for {schema_type}: {e}")
            return None

    def generate_hub_html_content(
        self,
        schema_docs: Dict[str, List[Dict[str, Any]]],
        openapi_docs: List[Dict[str, Any]],
        enumeration_docs: Optional[List[Dict[str, Any]]] = None,
        jsonld_docs: Optional[List[Dict[str, Any]]] = None,
        existing_openapi_html_content: Optional[str] = None,
    ) -> str:
        enumeration_docs = enumeration_docs or []
        jsonld_docs = jsonld_docs or []

        html: List[str] = []
        html.append('<div class="dak-api-hub">')

        # Enumeration endpoints
        if enumeration_docs:
            html.append("<h3>API Enumeration Endpoints</h3>")
            html.append("<p>These endpoints provide lists of all available schemas and vocabularies of each type:</p>")
            html.append('<div class="enumeration-endpoints">')

            for enum_doc in enumeration_docs:
                if enum_doc["type"] == "enumeration-valueset":
                    valueset_list = []
                    for s in schema_docs.get("valueset", []):
                        name = s["schema_file"].replace("schemas/", "").replace(".schema.json", "")
                        valueset_list.append(
                            f'<li><a href="{s["schema_file"]}">{name}.schema.json</a> - JSON Schema for {s["title"]}</li>'
                        )
                        if s.get("jsonld_file"):
                            jname = s["jsonld_file"].replace("schemas/", "").replace(".jsonld", "")
                            valueset_list.append(
                                f'<li><a href="{s["jsonld_file"]}">{jname}.jsonld</a> - JSON-LD vocabulary for {s["title"]}</li>'
                            )

                    html.append('<div class="endpoint-card">')
                    html.append(f'<h4><a href="{enum_doc["html_file"]}">{enum_doc["title"]}</a></h4>')
                    html.append(f"<p>{enum_doc['description']}</p>")
                    html.append('<div class="endpoint-list"><h5>Available Endpoints:</h5>')
                    html.append("<ul>")
                    html.extend(valueset_list)
                    html.append("</ul></div></div>")

                elif enum_doc["type"] == "enumeration-logicalmodel":
                    lm_list = []
                    for s in schema_docs.get("logical_model", []):
                        name = s["schema_file"].replace("schemas/", "").replace(".schema.json", "")
                        lm_list.append(
                            f'<li><a href="{s["schema_file"]}">{name}.schema.json</a> - JSON Schema for {s["title"]}</li>'
                        )
                    html.append('<div class="endpoint-card">')
                    html.append(f'<h4><a href="{enum_doc["html_file"]}">{enum_doc["title"]}</a></h4>')
                    html.append(f"<p>{enum_doc['description']}</p>")
                    html.append('<div class="endpoint-list"><h5>Available Endpoints:</h5>')
                    html.append("<ul>")
                    html.extend(lm_list)
                    html.append("</ul></div></div>")

            html.append("</div>")

        # ValueSet Schemas
        if schema_docs.get("valueset"):
            html.append(f"<h3>ValueSet Schemas ({len(schema_docs['valueset'])} available)</h3>")
            html.append("<p>JSON Schema definitions for FHIR ValueSets, providing structured enumeration of allowed code values:</p>")
            html.append('<div class="schema-grid">')
            for s in schema_docs["valueset"]:
                html.append('<div class="schema-card">')
                html.append(f'<h4><a href="{s["html_file"]}">{s["title"]}</a></h4>')
                html.append(f"<p>{s['description']}</p>")
                html.append('<div class="schema-links">')
                html.append(f'<a href="{s["html_file"]}" class="schema-link fhir-link" title="FHIR Resource Definition">🩺 FHIR</a>')
                html.append(f'<a href="{s["schema_file"]}" class="schema-link" title="JSON Schema Definition">📄 JSON Schema</a>')
                if s.get("displays_file"):
                    html.append(f'<a href="{s["displays_file"]}" class="schema-link" title="Display Names">🏷️ Displays</a>')
                if s.get("jsonld_file"):
                    html.append(f'<a href="{s["jsonld_file"]}" class="schema-link" title="JSON-LD Vocabulary">🗂️ JSON-LD</a>')
                if s.get("openapi_file"):
                    html.append(f'<a href="{s["openapi_file"]}" class="schema-link" title="OpenAPI Specification">🔗 OpenAPI</a>')
                html.append("</div></div>")
            html.append("</div>")

        # Logical Model Schemas
        if schema_docs.get("logical_model"):
            html.append(f"<h3>Logical Model Schemas ({len(schema_docs['logical_model'])} available)</h3>")
            html.append("<p>JSON Schema definitions for FHIR Logical Models, defining structured data elements and their relationships:</p>")
            html.append('<div class="schema-grid">')
            for s in schema_docs["logical_model"]:
                html.append('<div class="schema-card">')
                html.append(f'<h4><a href="{s["html_file"]}">{s["title"]}</a></h4>')
                html.append(f"<p>{s['description']}</p>")
                html.append('<div class="schema-links">')
                html.append(f'<a href="{s["html_file"]}" class="schema-link fhir-link" title="FHIR Resource Definition">🩺 FHIR</a>')
                html.append(f'<a href="{s["schema_file"]}" class="schema-link" title="JSON Schema Definition">📄 JSON Schema</a>')
                if s.get("displays_file"):
                    html.append(f'<a href="{s["displays_file"]}" class="schema-link" title="Display Names">🏷️ Displays</a>')
                if s.get("openapi_file"):
                    html.append(f'<a href="{s["openapi_file"]}" class="schema-link" title="OpenAPI Specification">🔗 OpenAPI</a>')
                html.append("</div></div>")
            html.append("</div>")

        # OpenAPI Documentation
        if openapi_docs or schema_docs.get("valueset") or schema_docs.get("logical_model"):
            html.append("<h3>OpenAPI Documentation</h3>")
            html.append("<p>Complete API specification documentation for all available endpoints:</p>")
            html.append('<div class="schema-grid">')

            # Schema endpoints cards
            for s in schema_docs.get("valueset", []):
                base = s["schema_file"].replace("schemas/", "").replace(".schema.json", "")
                html.append('<div class="schema-card">')
                html.append(f"<h4>{base} Endpoints</h4>")
                html.append(f"<p>API endpoints for {s['title']}</p>")
                html.append('<div class="schema-links">')
                html.append(f'<a href="{s["schema_file"]}" class="schema-link" title="JSON Schema Definition">📄 JSON Schema</a>')
                if s.get("jsonld_file"):
                    html.append(f'<a href="{s["jsonld_file"]}" class="schema-link" title="JSON-LD Vocabulary">🗂️ JSON-LD</a>')
                if s.get("openapi_file"):
                    html.append(f'<a href="{s["openapi_file"]}" class="schema-link" title="OpenAPI Specification">🔗 OpenAPI</a>')
                html.append("</div></div>")

            for s in schema_docs.get("logical_model", []):
                base = s["schema_file"].replace("schemas/", "").replace(".schema.json", "")
                html.append('<div class="schema-card">')
                html.append(f"<h4>{base} Endpoints</h4>")
                html.append(f"<p>API endpoints for {s['title']}</p>")
                html.append('<div class="schema-links">')
                html.append(f'<a href="{s["schema_file"]}" class="schema-link" title="JSON Schema Definition">📄 JSON Schema</a>')
                if s.get("openapi_file"):
                    html.append(f'<a href="{s["openapi_file"]}" class="schema-link" title="OpenAPI Specification">🔗 OpenAPI</a>')
                html.append("</div></div>")

            # Enumeration cards
            for e in enumeration_docs:
                if e["type"] == "enumeration-valueset":
                    html.append('<div class="schema-card"><h4>ValueSets Enumeration Endpoint</h4>')
                    html.append("<p>Complete list of all available ValueSet schemas</p>")
                    html.append('<div class="schema-links">')
                    html.append('<a href="ValueSets.schema.json" class="schema-link" title="JSON Schema Definition">📄 JSON Schema</a>')
                    html.append('<a href="ValueSets-enumeration.openapi.json" class="schema-link" title="OpenAPI Specification">🔗 OpenAPI</a>')
                    html.append("</div></div>")
                if e["type"] == "enumeration-logicalmodel":
                    html.append('<div class="schema-card"><h4>LogicalModels Enumeration Endpoint</h4>')
                    html.append("<p>Complete list of all available Logical Model schemas</p>")
                    html.append('<div class="schema-links">')
                    html.append('<a href="LogicalModels.schema.json" class="schema-link" title="JSON Schema Definition">📄 JSON Schema</a>')
                    html.append('<a href="LogicalModels-enumeration.openapi.json" class="schema-link" title="OpenAPI Specification">🔗 OpenAPI</a>')
                    html.append("</div></div>")

            # OpenAPI file cards
            for a in openapi_docs:
                html.append('<div class="schema-card">')
                html.append(f"<h4>{a['title']}</h4>")
                html.append(f"<p>{a['description']}</p>")
                html.append('<div class="schema-links">')
                if a.get("html_file"):
                    html.append(f'<a href="{a["html_file"]}" class="schema-link" title="API Documentation">📖 Documentation</a>')
                html.append(f'<a href="{a["file_path"]}" class="schema-link" title="OpenAPI Specification">🔗 OpenAPI Spec</a>')
                html.append("</div></div>")

            html.append("</div>")

        # Existing OpenAPI HTML content
        if existing_openapi_html_content:
            html.append("<h3>Existing API Documentation</h3>")
            html.append('<div class="existing-openapi-content">')
            html.append(existing_openapi_html_content)
            html.append("</div>")

        # Usage info
        html.append("""
<h3>Using the DAK API</h3>
<div class="usage-info">
  <h4>Schema Validation</h4>
  <p>Each JSON Schema can be used to validate data structures in your applications.</p>
  <ul>
    <li>Type definitions and constraints</li>
    <li>Property descriptions and examples</li>
    <li>Required field specifications</li>
    <li>Enumeration values with links to definitions</li>
  </ul>

  <h4>JSON-LD Semantic Integration</h4>
  <p>The JSON-LD vocabularies provide semantic web integration for ValueSet enumerations.</p>

  <h4>Integration with FHIR</h4>
  <p>All schemas are derived from the FHIR definitions in this implementation guide.</p>

  <h4>API Endpoints</h4>
  <p>The enumeration endpoints provide machine-readable lists of all available schemas.</p>
</div>

<style>
.dak-api-hub { margin: 1rem 0; }
.enumeration-endpoints, .schema-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 1rem;
  margin: 1rem 0;
}
.endpoint-card, .schema-card {
  border: 1px solid #dee2e6;
  border-radius: 4px;
  padding: 1rem;
  background: #f8f9fa;
  transition: box-shadow 0.2s ease;
}
.endpoint-card:hover, .schema-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
.endpoint-card h4, .schema-card h4 { margin: 0 0 0.5rem 0; color: #00477d; }
.endpoint-card h4 a, .schema-card h4 a { color: #00477d; text-decoration: none; }
.endpoint-card h4 a:hover, .schema-card h4 a:hover { color:#0070A1; text-decoration: underline; }
.endpoint-card p, .schema-card p { margin: 0 0 0.5rem 0; color:#6c757d; font-size: 0.9rem; }
.schema-links { margin-top: 0.75rem; display: flex; flex-wrap: wrap; gap: 0.5rem; }
.schema-link {
  display:inline-block; background:#17a2b8; color:white; padding:0.25rem 0.5rem;
  border-radius:3px; text-decoration:none; font-size:0.8rem; font-weight:500;
}
.schema-link:hover { background:#138496; color:white; text-decoration:none; }
.schema-link.fhir-link { background:#28a745; }
.schema-link.fhir-link:hover { background:#218838; }
.usage-info { background:#e7f3ff; border:1px solid #b8daff; border-radius:4px; padding:1.5rem; margin:1.5rem 0; }
.usage-info h4 { color:#00477d; margin-top:1rem; }
.usage-info h4:first-child { margin-top:0; }
</style>

<hr>
<p><em>This documentation hub is automatically generated from the available schema and API definitions.</em></p>
""")

        html.append("</div>")
        return "\n".join(html)

    def post_process_dak_api_html(
        self,
        output_dir: str,
        schema_docs: Dict[str, List[Dict[str, Any]]],
        openapi_docs: List[Dict[str, Any]],
        enumeration_docs: Optional[List[Dict[str, Any]]] = None,
        jsonld_docs: Optional[List[Dict[str, Any]]] = None,
        existing_openapi_html_content: Optional[str] = None,
        html_target_dir: Optional[str] = None,
    ) -> bool:
        try:
            target_dir = html_target_dir or output_dir
            self.logger.info(f"HTML target directory: {target_dir}")

            dak_api_html_path = os.path.join(target_dir, "dak-api.html")
            if not os.path.exists(dak_api_html_path):
                self.logger.error(f"dak-api.html not found in {target_dir}")
                return False

            self.logger.info(f"Found DAK API template at: {dak_api_html_path}")
            hub_content = self.generate_hub_html_content(
                schema_docs, openapi_docs, enumeration_docs, jsonld_docs, existing_openapi_html_content
            )
            self.logger.info(f"Generated hub content length: {len(hub_content)} characters")

            html_processor = HTMLProcessor(self.logger, target_dir)
            self.logger.info("Injecting content into dak-api.html...")
            ok = html_processor.inject_content_at_comment_marker(dak_api_html_path, hub_content)

            if ok:
                self.logger.info(f"✅ Successfully post-processed DAK API hub: {dak_api_html_path}")
                self.logger.info(f"Final file size: {os.path.getsize(dak_api_html_path)} bytes")
            else:
                self.logger.error("❌ Failed to inject content into dak-api.html")

            return ok

        except Exception as e:
            self.logger.error(f"Error post-processing DAK API hub: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    logger = setup_logging()

    # Argument handling
    if len(sys.argv) == 1:
        ig_root = Path(".")
        output_dir = str(ig_root / "output")
        openapi_dir = str(ig_root / "input" / "images" / "openapi")
    elif len(sys.argv) == 2:
        ig_root = Path(sys.argv[1])
        output_dir = str(ig_root / "output")
        openapi_dir = str(ig_root / "input" / "images" / "openapi")
    else:
        output_dir = sys.argv[1]
        openapi_dir = sys.argv[2]
        ig_root = Path(output_dir).parent

    schema_output_dir = os.path.join(output_dir, "schemas")
    html_target_dir = output_dir  # post-check phase targets final HTML under output/

    logger.info("Post-check phase: targeting output directory for HTML injection")
    logger.info(f"IG root: {ig_root}")
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Schema output directory: {schema_output_dir}")
    logger.info(f"HTML target directory: {html_target_dir}")
    logger.info(f"OpenAPI directory: {openapi_dir}")

    qa_reporter = QAReporter("postprocessing")
    qa_reporter.add_success("Starting generate_dak_api_hub.py post-processing")
    qa_reporter.add_success(f"Configured directories - Output: {output_dir}, OpenAPI: {openapi_dir}")

    qa_output_path = os.path.join(output_dir, "qa.json")
    if qa_reporter.load_existing_ig_qa(qa_output_path):
        qa_reporter.add_success("Loaded existing FHIR IG publisher QA file for merging")
    else:
        qa_reporter.add_warning("No existing FHIR IG publisher QA file found - will create new one")

    # Merge preprocessing QA files if present
    def try_merge(path1: str, path2: str, label: str):
        picked = path1 if os.path.exists(path1) else path2
        if os.path.exists(picked):
            try:
                with open(picked, "r", encoding="utf-8") as f:
                    rep = json.load(f)
                qa_reporter.merge_preprocessing_report(rep)
                qa_reporter.add_success(f"Merged {label} QA report from {picked}")
                logger.info(f"Successfully merged {label} QA report from {picked}")
            except Exception as e:
                qa_reporter.add_warning(f"Failed to merge {label} QA report: {e}")
                logger.warning(f"Failed to merge {label} QA report: {e}")
        else:
            qa_reporter.add_warning(f"No {label} QA report found")
            logger.info(f"No {label} QA report found at {path1} or {path2}")

    temp_dir = tempfile.gettempdir()
    try_merge("input/temp/qa_preprocessing.json", os.path.join(temp_dir, "qa_preprocessing.json"), "preprocessing")
    try_merge("input/temp/qa_valueset_schemas.json", os.path.join(temp_dir, "qa_valueset_schemas.json"), "ValueSet schema generation")
    try_merge("input/temp/qa_logical_model_schemas.json", os.path.join(temp_dir, "qa_logical_model_schemas.json"), "Logical Model schema generation")
    try_merge("input/temp/qa_jsonld_vocabularies.json", os.path.join(temp_dir, "qa_jsonld_vocabularies.json"), "JSON-LD vocabulary generation")

    # Validate output dir
    qa_reporter.add_file_expected(output_dir)
    if not os.path.exists(output_dir):
        logger.error(f"Output directory does not exist: {output_dir}")
        qa_reporter.add_error(f"Output directory does not exist: {output_dir}")
        merged = qa_reporter.finalize_report("failed")
        qa_reporter.save_to_file(os.path.join("output", "qa.json"), merged)
        sys.exit(1)

    logger.info(f"Output directory exists with {len(os.listdir(output_dir))} items")
    qa_reporter.add_success(f"Output directory exists with {len(os.listdir(output_dir))} items")
    sample_files = os.listdir(output_dir)[:10]
    logger.info(f"Sample files in output directory: {sample_files}")
    qa_reporter.add_success("Output directory contents sampled", {"sample_files": sample_files})

    # Ensure schema dir exists (not fatal if empty, but should exist)
    os.makedirs(schema_output_dir, exist_ok=True)

    # Initialize components
    schema_detector = SchemaDetector(logger)
    openapi_detector = OpenAPIDetector(logger)
    openapi_wrapper = OpenAPIWrapper(logger)
    schema_doc_renderer = SchemaDocumentationRenderer(logger)
    hub_generator = DAKApiHubGenerator(logger)
    html_processor = HTMLProcessor(logger, output_dir)

    qa_reporter.add_success("All components initialized successfully")

    # Detect schema files
    logger.info("=== SCHEMA FILE DETECTION PHASE ===")
    schemas = schema_detector.find_schema_files(schema_output_dir)

    for p in schemas["valueset"]:
        qa_reporter.add_file_processed(p, "valueset_schema_detected")
    for p in schemas["logical_model"]:
        qa_reporter.add_file_processed(p, "logical_model_schema_detected")
    for p in schemas["other"]:
        qa_reporter.add_file_processed(p, "other_schema_detected")

    # Detect JSON-LD
    logger.info("=== JSON-LD FILE DETECTION PHASE ===")
    jsonld_files = schema_detector.find_jsonld_files(schema_output_dir)

    # Also check output/vocabulary/ (where 05_generate_jsonld_vocabularies writes)
    vocabulary_dir = os.path.join(output_dir, "vocabulary")
    if os.path.exists(vocabulary_dir):
        jsonld_files_vocab = schema_detector.find_jsonld_files(vocabulary_dir)
        # Deduplicate by filename
        existing_names = {os.path.basename(f) for f in jsonld_files}
        for f in jsonld_files_vocab:
            if os.path.basename(f) not in existing_names:
                jsonld_files.append(f)
                existing_names.add(os.path.basename(f))

    # Detect existing OpenAPI
    logger.info("=== OPENAPI FILE DETECTION PHASE ===")
    openapi_files_source = openapi_detector.find_openapi_files(openapi_dir)
    output_openapi_dir = os.path.join(output_dir, "images", "openapi")
    openapi_files_output_images = openapi_detector.find_openapi_files(output_openapi_dir)

    # Existing OpenAPI HTML content extraction
    logger.info("=== EXISTING OPENAPI HTML CONTENT DETECTION ===")
    existing_openapi_html_content = openapi_detector.find_existing_html_content(openapi_dir)
    if not existing_openapi_html_content:
        existing_openapi_html_content = openapi_detector.find_existing_html_content(output_openapi_dir)

    # Validate dak-api.html exists (final HTML)
    dak_api_html_path = os.path.join(html_target_dir, "dak-api.html")
    logger.info(f"Checking for dak-api.html at: {dak_api_html_path}")

    if not os.path.exists(dak_api_html_path):
        if os.path.exists(html_target_dir):
            all_files = os.listdir(html_target_dir)
            html_files = [f for f in all_files if f.endswith(".html")]
            logger.info(f"Total files in HTML target directory: {len(all_files)}")
            logger.info(f"HTML files: {len(html_files)} found")
            logger.info(f"Files containing 'dak': {[f for f in all_files if 'dak' in f.lower()]}")
        logger.error("❌ Cannot find dak-api.html in output directory")
        logger.error("Make sure the IG publisher ran first and created dak-api.html from dak-api.md placeholder.")
        sys.exit(1)

    with open(dak_api_html_path, "r", encoding="utf-8") as f:
        template_content = f.read()

    if 'id="dak-api-content-placeholder"' in template_content:
        logger.info("✅ Found DAK API placeholder div for content injection")
    elif "<!-- DAK_API_CONTENT -->" in template_content:
        logger.info("✅ Found legacy DAK_API_CONTENT comment marker for content injection")
    else:
        logger.warning("⚠️ No DAK API placeholder found - content injection may fail")

    # -----------------------------------------------------------------------
    # Build schema_docs with artifact references + generate OpenAPI wrappers
    # -----------------------------------------------------------------------

    schema_docs: Dict[str, List[Dict[str, Any]]] = {"valueset": [], "logical_model": []}

    # ValueSet schemas
    logger.info(f"Processing {len(schemas['valueset'])} ValueSet schemas...")
    for i, schema_path in enumerate(schemas["valueset"], 1):
        logger.info(f"Processing ValueSet schema {i}/{len(schemas['valueset'])}: {schema_path}")
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                schema = json.load(f)

            schema_filename = os.path.basename(schema_path)
            schema_name = schema_filename.replace(".schema.json", "")
            title = schema.get("title", f"{schema_name} Schema Documentation")
            description = schema.get("description", "ValueSet schema documentation")

            # Generate OpenAPI wrapper next to schema artifacts (output/schemas)
            wrapper_path = openapi_wrapper.create_wrapper_for_schema(schema_path, "valueset", schema_output_dir)
            if wrapper_path:
                logger.info(f"  ✅ Created OpenAPI wrapper: {wrapper_path}")
            else:
                logger.warning(f"  ⚠️ Failed to create OpenAPI wrapper for {schema_name}")

            html_filename = f"{schema_name}.html"  # IG-generated page

            displays_filename = f"{schema_name}.displays.json"
            openapi_filename = f"{schema_name}.openapi.json"
            jsonld_filename = f"{schema_name}.jsonld"

            displays_path = os.path.join(schema_output_dir, displays_filename)
            openapi_path = os.path.join(schema_output_dir, openapi_filename)
            jsonld_path = os.path.join(schema_output_dir, jsonld_filename)

            entry: Dict[str, Any] = {
                "title": title,
                "description": description,
                "html_file": html_filename,
                "schema_file": f"schemas/{schema_filename}",
            }

            if os.path.exists(displays_path):
                entry["displays_file"] = f"schemas/{displays_filename}"
                logger.info(f"  Found displays file: {displays_filename}")

            if os.path.exists(openapi_path):
                entry["openapi_file"] = f"schemas/{openapi_filename}"
                logger.info(f"  Found OpenAPI file: {openapi_filename}")

            if os.path.exists(jsonld_path):
                entry["jsonld_file"] = f"schemas/{jsonld_filename}"
                logger.info(f"  Found JSON-LD file: {jsonld_filename}")

            schema_docs["valueset"].append(entry)
            logger.info(f"  ✅ Added ValueSet schema to hub documentation: {schema_name}")

        except Exception as e:
            logger.error(f"  ❌ Error processing ValueSet schema {schema_path}: {e}")
            import traceback
            logger.error(traceback.format_exc())

    # Logical Model schemas
    logger.info(f"Processing {len(schemas['logical_model'])} Logical Model schemas...")
    for i, schema_path in enumerate(schemas["logical_model"], 1):
        logger.info(f"Processing Logical Model schema {i}/{len(schemas['logical_model'])}: {schema_path}")
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                schema = json.load(f)

            schema_filename = os.path.basename(schema_path)
            schema_name = schema_filename.replace(".schema.json", "")
            title = schema.get("title", f"{schema_name} Schema Documentation")
            description = schema.get("description", "Logical Model schema documentation")

            # Generate OpenAPI wrapper next to schema artifacts (output/schemas)
            wrapper_path = openapi_wrapper.create_wrapper_for_schema(schema_path, "logical_model", schema_output_dir)
            if wrapper_path:
                logger.info(f"  ✅ Created OpenAPI wrapper: {wrapper_path}")
            else:
                logger.warning(f"  ⚠️ Failed to create OpenAPI wrapper for {schema_name}")

            html_filename = f"{schema_name}.html"  # IG-generated page

            displays_filename = f"{schema_name}.displays.json"
            openapi_filename = f"{schema_name}.openapi.json"

            displays_path = os.path.join(schema_output_dir, displays_filename)
            openapi_path = os.path.join(schema_output_dir, openapi_filename)

            entry: Dict[str, Any] = {
                "title": title,
                "description": description,
                "html_file": html_filename,
                "schema_file": f"schemas/{schema_filename}",
            }

            if os.path.exists(displays_path):
                entry["displays_file"] = f"schemas/{displays_filename}"
                logger.info(f"  Found displays file: {displays_filename}")

            if os.path.exists(openapi_path):
                entry["openapi_file"] = f"schemas/{openapi_filename}"
                logger.info(f"  Found OpenAPI file: {openapi_filename}")

            schema_docs["logical_model"].append(entry)
            logger.info(f"  ✅ Added Logical Model schema to hub documentation: {schema_name}")

        except Exception as e:
            logger.error(f"  ❌ Error processing Logical Model schema {schema_path}: {e}")
            import traceback
            logger.error(traceback.format_exc())

    # -----------------------------------------------------------------------
    # Enumeration endpoints + OpenAPI wrappers for them
    # -----------------------------------------------------------------------

    logger.info("=== ENUMERATION ENDPOINT CREATION PHASE ===")
    enumeration_docs: List[Dict[str, Any]] = []

    if schemas["valueset"]:
        valueset_enum_path = hub_generator.create_enumeration_schema("valueset", schemas["valueset"], output_dir)
        if valueset_enum_path:
            enum_openapi = openapi_wrapper.create_enumeration_wrapper(valueset_enum_path, "valueset", output_dir)
            if enum_openapi:
                logger.info(f"✅ Created ValueSets enumeration OpenAPI wrapper: {enum_openapi}")
            enumeration_docs.append(
                {
                    "title": "ValueSets.schema.json",
                    "description": "Enumeration of all available ValueSet schemas",
                    "html_file": "ValueSets-enumeration.html",
                    "type": "enumeration-valueset",
                }
            )

    if schemas["logical_model"]:
        logical_enum_path = hub_generator.create_enumeration_schema("logical_model", schemas["logical_model"], output_dir)
        if logical_enum_path:
            enum_openapi = openapi_wrapper.create_enumeration_wrapper(logical_enum_path, "logical_model", output_dir)
            if enum_openapi:
                logger.info(f"✅ Created LogicalModels enumeration OpenAPI wrapper: {enum_openapi}")
            enumeration_docs.append(
                {
                    "title": "LogicalModels.schema.json",
                    "description": "Enumeration of all available Logical Model schemas",
                    "html_file": "LogicalModels-enumeration.html",
                    "type": "enumeration-logicalmodel",
                }
            )

    # JSON-LD docs (metadata)
    logger.info("=== JSON-LD VOCABULARY PROCESSING PHASE ===")
    jsonld_docs: List[Dict[str, Any]] = []
    for jsonld_path in jsonld_files:
        try:
            with open(jsonld_path, "r", encoding="utf-8") as f:
                vocab = json.load(f)
            fname = os.path.basename(jsonld_path)

            title = fname
            description = "JSON-LD vocabulary for ValueSet enumeration"

            graph = vocab.get("@graph")
            if isinstance(graph, list):
                for item in graph:
                    if isinstance(item, dict) and item.get("type") == "schema:Enumeration":
                        if "name" in item:
                            title = f"{item['name']} JSON-LD Vocabulary"
                        if "comment" in item:
                            description = item["comment"]
                        break

            jsonld_docs.append({"title": title, "description": description, "filename": fname})
        except Exception as e:
            logger.error(f"Error processing JSON-LD vocabulary {jsonld_path}: {e}")

    # -----------------------------------------------------------------------
    # OpenAPI docs collection (existing + generated)
    # -----------------------------------------------------------------------

    logger.info("=== OPENAPI DOCUMENTATION COLLECTION PHASE ===")

    # 1) generated wrappers in output/schemas
    openapi_files_generated = openapi_detector.find_openapi_files(schema_output_dir)

    # 2) existing in source input/images/openapi
    # 3) existing copied to output/images/openapi
    all_openapi_paths: List[str] = []
    seen = set()

    def add_paths(paths: List[str]):
        for p in paths:
            name = os.path.basename(p)
            if name in seen:
                continue
            seen.add(name)
            all_openapi_paths.append(p)

    add_paths(openapi_files_generated)
    add_paths(openapi_files_source)
    add_paths(openapi_files_output_images)

    openapi_docs: List[Dict[str, Any]] = []

    for openapi_path in all_openapi_paths:
        try:
            filename = os.path.basename(openapi_path)
            clean_name = (
                filename.replace(".openapi.json", "")
                .replace(".openapi.yaml", "")
                .replace(".yaml", "")
                .replace(".yml", "")
                .replace(".json", "")
            )

            # relative link: if it's inside output/images/openapi => images/openapi/...
            # if it's inside output/schemas => schemas/...
            normalized = openapi_path.replace("\\", "/")
            if "/output/images/openapi/" in normalized or "/images/openapi/" in normalized and os.path.exists(output_openapi_dir):
                relative_path = f"images/openapi/{filename}"
            elif normalized.replace("\\", "/").endswith(f"/output/schemas/{filename}") or "/schemas/" in normalized:
                relative_path = f"schemas/{filename}"
            else:
                # fallback: link just filename (may still work if IG copied it)
                relative_path = filename

            openapi_html_filename = schema_doc_renderer.inject_into_html(openapi_path, output_dir, f"{clean_name} API Documentation")

            openapi_docs.append(
                {
                    "title": f"{clean_name} API",
                    "description": f"OpenAPI specification for {clean_name}",
                    "file_path": relative_path,
                    "filename": filename,
                    "html_file": openapi_html_filename,
                }
            )

        except Exception as e:
            logger.error(f"Error processing OpenAPI file {openapi_path}: {e}")

    # Summary + hub injection
    logger.info("=== DOCUMENTATION SUMMARY ===")
    logger.info(f"ValueSet schema docs: {len(schema_docs['valueset'])}")
    logger.info(f"Logical Model schema docs: {len(schema_docs['logical_model'])}")
    logger.info(f"Enumeration endpoints: {len(enumeration_docs)}")
    logger.info(f"JSON-LD vocabularies: {len(jsonld_docs)}")
    logger.info(f"OpenAPI docs: {len(openapi_docs)}")

    qa_reporter.add_success(
        "Documentation summary completed",
        {
            "valueset_schema_docs": len(schema_docs["valueset"]),
            "logical_model_schema_docs": len(schema_docs["logical_model"]),
            "enumeration_endpoints": len(enumeration_docs),
            "jsonld_vocabularies": len(jsonld_docs),
            "openapi_docs": len(openapi_docs),
        },
    )

    logger.info("=== DAK API HUB POST-PROCESSING PHASE ===")
    success = hub_generator.post_process_dak_api_html(
        output_dir=output_dir,
        schema_docs=schema_docs,
        openapi_docs=openapi_docs,
        enumeration_docs=enumeration_docs,
        jsonld_docs=jsonld_docs,
        existing_openapi_html_content=existing_openapi_html_content,
        html_target_dir=html_target_dir,
    )

    if success:
        logger.info("✅ DAK API documentation generation completed successfully")
    else:
        logger.warning("⚠️ DAK API documentation generation completed with errors - see QA report for details")

    # Write merged QA
    qa_status = "completed" if success else "completed_with_errors"
    merged_qa = qa_reporter.finalize_report(qa_status)

    qa_path = os.path.join(output_dir, "qa.json")
    if qa_reporter.save_to_file(qa_path, merged_qa):
        logger.info(f"Final merged QA report saved to {qa_path}")
    else:
        backup = os.path.join(output_dir, "dak-api-qa.json")
        if qa_reporter.save_to_file(backup, merged_qa):
            logger.info(f"QA report saved to backup location: {backup}")
        else:
            logger.error("Failed to save QA report to any location")

    # Optional debug pause
    if os.environ.get("DEBUG_PAUSE"):
        logger.info("=" * 60)
        logger.info("DEBUG_PAUSE is set - pausing for file inspection")
        logger.info(f"Output directory: {output_dir}")
        logger.info(f"Working directory: {os.getcwd()}")
        logger.info("=" * 60)
        input("Press ENTER to continue (or Ctrl+C to abort)...")
        logger.info("Continuing after pause...")

    logger.info("Exiting with success code 0 - check qa.json for detailed status")
    sys.exit(0)


if __name__ == "__main__":
    main()
