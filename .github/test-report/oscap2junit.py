#!/usr/bin/env python3
#
# oscap2junit.py — Convert an OpenSCAP XCCDF result XML file to JUnit XML
# so it can be fed into test-report-pdf as a test input.
#
# Usage:
#   ./oscap2junit.py oscap-result.xml -o output_dir/

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from junitparser import Failure, JUnitXml, Properties, Property, Skipped, TestCase, TestSuite

XCCDF_NS = "http://checklists.nist.gov/xccdf/1.2"
NS = {"x": XCCDF_NS}

# XCCDF result values → JUnit outcome
# notselected: rule was not part of the selected profile subset — excluded by default
# notapplicable: rule does not apply to this platform → skipped
# notchecked: no check could be performed → skipped
RESULT_MAP = {
    "pass": "pass",
    "fail": "fail",
    "notapplicable": "skipped",
    "notchecked": "skipped",
    "error": "fail",
    "unknown": "skipped",
    "informational": "skipped",
    "fixed": "pass",
}


def parse_args():
    p = argparse.ArgumentParser(
        prog="oscap2junit",
        description=(
            "Convert an OpenSCAP XCCDF result XML file to JUnit XML files "
            "compatible with compile.py."
        ),
    )
    p.add_argument("xccdf_result", help="Path to the XCCDF result XML file.")
    p.add_argument(
        "-o",
        "--output_dir",
        default="oscap-junit",
        help="Directory to write JUnit XML file(s) into. Created if absent. "
        "Default: oscap-junit/",
    )
    p.add_argument(
        "--include-notselected",
        action="store_true",
        default=False,
        help="Include 'notselected' rules as skipped tests (noisy; off by default).",
    )
    p.add_argument(
        "--severity",
        choices=["low", "medium", "high"],
        default=None,
        help="Only include rules at or above this severity level.",
    )
    return p.parse_args()


SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "unknown": -1}


def severity_ok(rule_severity, min_severity):
    if min_severity is None:
        return True
    return SEVERITY_RANK.get(rule_severity, -1) >= SEVERITY_RANK[min_severity]

def get_elem_base_tag(elem):
    """
    Given an XML element with a tag like "{namespace}TagName", return "TagName".
    If no namespace, return the tag as-is.
    """
    tag = elem.tag
    if "}" in tag:
        return tag.split("}")[-1]

    return tag

def get_elem_text(elem, default=""):
    """
    Return the text content of an XML element, or a default value if the element is None or has no text.
    """
    if elem is not None and elem.text:
        return elem.text.strip()

    return default

def build_rule_titles_map(root):
    """
    Walk the benchmark tree and return a dict:
        rule_id → title
    """
    rule_titles = {}

    def walk(elem, group_title="Ungrouped"):

        local = get_elem_base_tag(elem)

        if local == "Rule":
            rule_id = elem.get("id", "")
            rule_title = get_elem_text(elem.find("x:title", NS), rule_id)

            rule_titles[rule_id] = rule_title
        else:
            for child in elem:
                walk(child, group_title)

    walk(root)
    return rule_titles


def escape_xml(text):
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def write_junit(suites, output_path, target):
    """
    suites: dict of group_title → list of {title, result, severity, idref}
    Writes a single JUnit XML file with one <testsuite> per group.
    """
    xml = JUnitXml()

    for suite_name, tests in sorted(suites.items()):
        suite = TestSuite(suite_name)
        suite.hostname = target

        for t in tests:
            case = TestCase(t["title"])
            case.classname = target
            properties = Properties()
            properties.add_property(Property("rule_id", t["idref"]))
            properties.add_property(Property("raw_result", t["result_raw"]))
            properties.add_property(Property("severity", t["severity"]))
            case.append(properties)

            if t["result"] == "fail":
                case.result = [
                    Failure(
                        f'Rule: {t["idref"]}\nSeverity: {t["severity"]}',
                        "SecurityPolicyViolation",
                    )
                ]
            elif t["result"] == "skipped":
                case.result = [Skipped(t["result_raw"])]

            suite.add_testcase(case)

        xml.add_testsuite(suite)

    xml.write(output_path, pretty=True)


def main():
    args = parse_args()

    print(f"Parsing {args.xccdf_result} ...")
    try:
        tree = ET.parse(args.xccdf_result)
    except ET.ParseError as e:
        print(f"ERROR: Failed to parse XML: {e}", file=sys.stderr)
        sys.exit(1)

    root = tree.getroot()

    print("Building rule title/group map ...")
    rule_titles = build_rule_titles_map(root)
    print(f"  Found {len(rule_titles)} rules in benchmark.")

    test_result = root.find("x:TestResult", NS)
    if test_result is None:
        print("ERROR: No <TestResult> element found in the file.", file=sys.stderr)
        sys.exit(1)

    result_id = test_result.get("id", "oscap")
    target = get_elem_text(test_result.find("x:target", NS), "unknown")
    result_title = get_elem_text(test_result.find("x:title", NS), "OpenSCAP tests")
    rule_results = test_result.findall("x:rule-result", NS)

    print(f"  TestResult target: {target}")
    print(f"  Found {len(rule_results)} rule-result entries.")

    results = []
    skipped_count = 0

    # Associate rule names to test results
    for rr in rule_results:
        idref = rr.get("idref", "")

        result_raw = get_elem_text(rr.find("x:result", NS), "unknown")
        if result_raw == "notselected" and not args.include_notselected:
            skipped_count += 1
            continue

        severity = rr.get("severity", "unknown")
        if not severity_ok(severity, args.severity):
            continue

        outcome = RESULT_MAP.get(result_raw, "skipped")

        results.append(
            {
                "title": rule_titles.get(idref, idref),
                "idref": idref,
                "result": outcome,
                "result_raw": result_raw,
                "severity": severity,
            }
        )

    print(
        f"Included: {len(results)} rules "
        f"(excluded {skipped_count} 'notselected')."
    )

    # Generate JUnitXML file
    os.makedirs(args.output_dir, exist_ok=True)

    safe_name = result_id.replace("/", "_").replace(":", "_") + ".xml"
    output_path = os.path.join(args.output_dir, safe_name)

    print(f"Writing JUnit XML to {output_path} ...")
    write_junit({result_title: results}, output_path, target)


    all_tests = [t for t in results]
    passed = sum(1 for t in all_tests if t["result"] == "pass")
    failed = sum(1 for t in all_tests if t["result"] == "fail")
    skipped = sum(1 for t in all_tests if t["result"] == "skipped")
    print(f"\nSummary: {passed} passed, {failed} failed, {skipped} skipped/notapplicable")


if __name__ == "__main__":
    main()
