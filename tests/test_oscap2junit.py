# Copyright (C) 2026, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0

"""Tests for .github/test-report/oscap2junit.py."""

import xml.etree.ElementTree as ET

import pytest

from support import load_script

oscap2junit = load_script(".github/test-report/oscap2junit.py")

# An XCCDF result document small enough to reason about, but carrying one
# rule-result per branch of the conversion: every outcome of RESULT_MAP, a
# rule missing from the benchmark, a rule without a title, and a rule with
# no severity attribute at all.
XCCDF = """<?xml version="1.0" encoding="UTF-8"?>
<Benchmark xmlns="http://checklists.nist.gov/xccdf/1.2" id="benchmark_seapath">
  <title>SEAPATH hardening benchmark</title>
  <Group id="group_partitions">
    <title>Partitions</title>
    <Rule id="rule_pass" severity="high">
      <title>/tmp is a separate partition</title>
    </Rule>
    <Rule id="rule_fail" severity="medium">
      <title>nodev is set on /tmp</title>
    </Rule>
  </Group>
  <Rule id="rule_notitle" severity="low"/>
  <Rule id="rule_notapplicable" severity="low">
    <title>Rule that does not apply here</title>
  </Rule>
  <TestResult id="xccdf_result_stig:1/2">
    <title>SEAPATH hardening</title>
    <target>hypervisor1</target>
    <rule-result idref="rule_pass" severity="high">
      <result>pass</result>
    </rule-result>
    <rule-result idref="rule_fail" severity="medium">
      <result>fail</result>
    </rule-result>
    <rule-result idref="rule_notapplicable" severity="low">
      <result>notapplicable</result>
    </rule-result>
    <rule-result idref="rule_notitle" severity="low">
      <result>notselected</result>
    </rule-result>
    <rule-result idref="rule_absent_from_benchmark">
      <result>error</result>
    </rule-result>
    <rule-result idref="rule_no_result" severity="high"/>
  </TestResult>
</Benchmark>
"""

NO_TESTRESULT = """<?xml version="1.0" encoding="UTF-8"?>
<Benchmark xmlns="http://checklists.nist.gov/xccdf/1.2" id="benchmark_seapath">
  <Rule id="rule_pass" severity="high"><title>A rule</title></Rule>
</Benchmark>
"""


@pytest.fixture
def xccdf_file(tmp_path):
    def write(content=XCCDF):
        path = tmp_path / "oscap-result.xml"
        path.write_text(content)
        return str(path)

    return write


@pytest.fixture
def run_main(monkeypatch, xccdf_file, tmp_path):
    """Drive main() the way the CI does, through sys.argv."""

    def run(*extra_args, content=XCCDF):
        out_dir = tmp_path / "junit"
        argv = ["oscap2junit", xccdf_file(content), "-o", str(out_dir)]
        monkeypatch.setattr(oscap2junit.sys, "argv", argv + list(extra_args))
        oscap2junit.main()
        return out_dir

    return run


def junit_cases(path):
    """Return the <testcase> elements of a JUnit file, whatever the root is."""
    root = ET.parse(path).getroot()
    return root.findall(".//testcase")


# --- pure helpers ---------------------------------------------------------


@pytest.mark.parametrize(
    "severity,minimum,expected",
    [
        ("high", None, True),
        ("low", None, True),
        ("high", "low", True),
        ("high", "high", True),
        ("medium", "high", False),
        ("low", "medium", False),
        ("unknown", "low", False),
        ("bogus", "low", False),
    ],
)
def test_severity_ok(severity, minimum, expected):
    assert oscap2junit.severity_ok(severity, minimum) is expected


def test_get_elem_base_tag_strips_the_namespace():
    elem = ET.Element("{http://checklists.nist.gov/xccdf/1.2}Rule")

    assert oscap2junit.get_elem_base_tag(elem) == "Rule"


def test_get_elem_base_tag_leaves_a_bare_tag_alone():
    assert oscap2junit.get_elem_base_tag(ET.Element("Rule")) == "Rule"


def test_get_elem_text_strips_surrounding_whitespace():
    elem = ET.Element("title")
    elem.text = "  a title\n"

    assert oscap2junit.get_elem_text(elem) == "a title"


def test_get_elem_text_defaults_when_the_element_is_missing():
    assert oscap2junit.get_elem_text(None, "fallback") == "fallback"
    assert oscap2junit.get_elem_text(None) == ""


def test_get_elem_text_defaults_when_the_element_is_empty():
    assert oscap2junit.get_elem_text(ET.Element("title"), "fallback") == "fallback"


def test_build_rule_titles_map_walks_nested_groups():
    root = ET.fromstring(XCCDF)

    titles = oscap2junit.build_rule_titles_map(root)

    assert titles["rule_pass"] == "/tmp is a separate partition"
    assert titles["rule_fail"] == "nodev is set on /tmp"


def test_build_rule_titles_map_falls_back_to_the_rule_id():
    root = ET.fromstring(XCCDF)

    titles = oscap2junit.build_rule_titles_map(root)

    assert titles["rule_notitle"] == "rule_notitle"


def test_escape_xml_escapes_the_five_predefined_entities():
    assert oscap2junit.escape_xml("""<a href="x">&'</a>""") == (
        "&lt;a href=&quot;x&quot;&gt;&amp;&apos;&lt;/a&gt;"
    )


# --- argument parsing -----------------------------------------------------


def test_parse_args_defaults(monkeypatch):
    monkeypatch.setattr(oscap2junit.sys, "argv", ["oscap2junit", "result.xml"])

    args = oscap2junit.parse_args()

    assert args.xccdf_result == "result.xml"
    assert args.output_dir == "oscap-junit"
    assert args.include_notselected is False
    assert args.severity is None


def test_parse_args_reads_every_option(monkeypatch):
    monkeypatch.setattr(
        oscap2junit.sys,
        "argv",
        ["oscap2junit", "r.xml", "-o", "out", "--include-notselected",
         "--severity", "high"],
    )

    args = oscap2junit.parse_args()

    assert args.output_dir == "out"
    assert args.include_notselected is True
    assert args.severity == "high"


def test_parse_args_rejects_an_unknown_severity(monkeypatch):
    monkeypatch.setattr(
        oscap2junit.sys,
        "argv",
        ["oscap2junit", "r.xml", "--severity", "critical"],
    )

    with pytest.raises(SystemExit):
        oscap2junit.parse_args()


# --- JUnit writing --------------------------------------------------------


def test_write_junit_maps_outcomes_onto_junit_results(tmp_path):
    suites = {
        "SEAPATH": [
            {"title": "a passing rule", "idref": "r1", "result": "pass",
             "result_raw": "pass", "severity": "high"},
            {"title": "a failing rule", "idref": "r2", "result": "fail",
             "result_raw": "fail", "severity": "medium"},
            {"title": "a skipped rule", "idref": "r3", "result": "skipped",
             "result_raw": "notapplicable", "severity": "low"},
        ]
    }
    output = tmp_path / "out.xml"

    oscap2junit.write_junit(suites, str(output), "hypervisor1")

    cases = {c.get("name"): c for c in junit_cases(output)}
    assert cases["a passing rule"].find("failure") is None
    assert cases["a passing rule"].find("skipped") is None
    failure = cases["a failing rule"].find("failure")
    assert failure.get("type") == "SecurityPolicyViolation"
    assert "r2" in failure.get("message")
    assert "medium" in failure.get("message")
    assert cases["a skipped rule"].find("skipped").get("message") == "notapplicable"


def test_write_junit_attaches_the_rule_metadata_as_properties(tmp_path):
    suites = {
        "SEAPATH": [
            {"title": "a rule", "idref": "r1", "result": "pass",
             "result_raw": "fixed", "severity": "high"},
        ]
    }
    output = tmp_path / "out.xml"

    oscap2junit.write_junit(suites, str(output), "hypervisor1")

    properties = {
        p.get("name"): p.get("value")
        for p in junit_cases(output)[0].findall(".//property")
    }
    assert properties == {
        "rule_id": "r1", "raw_result": "fixed", "severity": "high",
    }


def test_write_junit_stamps_the_target_on_suites_and_cases(tmp_path):
    suites = {"SEAPATH": [
        {"title": "a rule", "idref": "r1", "result": "pass",
         "result_raw": "pass", "severity": "high"},
    ]}
    output = tmp_path / "out.xml"

    oscap2junit.write_junit(suites, str(output), "hypervisor1")

    assert junit_cases(output)[0].get("classname") == "hypervisor1"
    root = ET.parse(output).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    assert suite.get("hostname") == "hypervisor1"


def test_write_junit_sorts_the_suites_by_name(tmp_path):
    suites = {"zeta": [], "alpha": []}
    output = tmp_path / "out.xml"

    oscap2junit.write_junit(suites, str(output), "hypervisor1")

    root = ET.parse(output).getroot()
    names = [s.get("name") for s in root.findall(".//testsuite")]
    assert names == ["alpha", "zeta"]


# --- end to end -----------------------------------------------------------


def test_main_writes_a_file_named_after_the_result_id(run_main):
    out_dir = run_main()

    # "/" and ":" are replaced so the id can be used as a file name.
    assert (out_dir / "xccdf_result_stig_1_2.xml").is_file()


def test_main_excludes_notselected_rules_by_default(run_main):
    out_dir = run_main()

    names = [c.get("name") for c in junit_cases(out_dir / "xccdf_result_stig_1_2.xml")]
    assert "rule_notitle" not in names


def test_main_can_include_notselected_rules(run_main):
    out_dir = run_main("--include-notselected")

    names = [c.get("name") for c in junit_cases(out_dir / "xccdf_result_stig_1_2.xml")]
    assert "rule_notitle" in names


def test_main_titles_the_cases_from_the_benchmark(run_main):
    out_dir = run_main()

    names = [c.get("name") for c in junit_cases(out_dir / "xccdf_result_stig_1_2.xml")]
    assert "/tmp is a separate partition" in names
    assert "nodev is set on /tmp" in names


def test_main_falls_back_to_the_idref_for_an_unknown_rule(run_main):
    out_dir = run_main()

    names = [c.get("name") for c in junit_cases(out_dir / "xccdf_result_stig_1_2.xml")]
    assert "rule_absent_from_benchmark" in names


def test_main_maps_error_to_a_failure(run_main):
    out_dir = run_main()

    cases = {c.get("name"): c
             for c in junit_cases(out_dir / "xccdf_result_stig_1_2.xml")}
    assert cases["rule_absent_from_benchmark"].find("failure") is not None


def test_main_treats_a_missing_result_element_as_unknown(run_main):
    out_dir = run_main()

    cases = {c.get("name"): c
             for c in junit_cases(out_dir / "xccdf_result_stig_1_2.xml")}
    skipped = cases["rule_no_result"].find("skipped")
    assert skipped.get("message") == "unknown"


def test_main_filters_on_severity(run_main):
    out_dir = run_main("--severity", "high")

    names = [c.get("name") for c in junit_cases(out_dir / "xccdf_result_stig_1_2.xml")]
    assert "/tmp is a separate partition" in names
    # medium and low are below the threshold, and the rule with no severity
    # attribute at all ranks below everything.
    assert "nodev is set on /tmp" not in names
    assert "rule_absent_from_benchmark" not in names


def test_main_creates_the_output_directory(run_main, tmp_path):
    assert not (tmp_path / "junit").exists()

    out_dir = run_main()

    assert out_dir.is_dir()


def test_main_reports_what_it_included_and_excluded(run_main, capsys):
    run_main()

    out = capsys.readouterr().out
    assert "Included: 5 rules (excluded 1 'notselected')." in out
    assert "1 passed, 2 failed, 2 skipped" in out


def test_main_reports_the_target_and_the_rule_count(run_main, capsys):
    run_main()

    out = capsys.readouterr().out
    assert "TestResult target: hypervisor1" in out
    assert "Found 4 rules in benchmark." in out
    assert "Found 6 rule-result entries." in out


def test_main_exits_on_malformed_xml(run_main, capsys):
    with pytest.raises(SystemExit) as excinfo:
        run_main(content="<Benchmark><unclosed></Benchmark>")

    assert excinfo.value.code == 1
    assert "Failed to parse XML" in capsys.readouterr().err


def test_main_exits_when_there_is_no_test_result(run_main, capsys):
    with pytest.raises(SystemExit) as excinfo:
        run_main(content=NO_TESTRESULT)

    assert excinfo.value.code == 1
    assert "No <TestResult> element found" in capsys.readouterr().err
