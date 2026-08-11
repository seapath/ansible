<!--
Copyright (C) 2026, RTE (http://www.rte-france.com)
SPDX-License-Identifier: CC-BY-4.0
-->

# Python unit tests

Unit tests for every Python file this repository ships: the `cluster_vm`
Ansible module, the scripts deployed as role `files/` payloads, and the
OpenSCAP report converter used by the CI.

## Running them

```bash
tox -e unit                     # the whole suite, with coverage
tox -e unit -- -k snmp -v       # extra arguments go straight to pytest
tox -e unit -- --no-cov         # skip the coverage run while iterating
```

`tox -e unit` writes `coverage.xml` and `htmlcov/` at the repository root and
fails below the `COV_FAIL_UNDER` ratchet set in `tox.ini`. The ratchet exists
to stop regressions: **raise it when coverage improves, never lower it**.
`COV_FAIL_UNDER=0 tox -e unit` bypasses it locally.

Without tox: `pip install -r unit_requirements.txt && pytest tests/ --cov`.

The suite is hermetic. It never shells out, never opens a socket, and never
touches a path outside `tmp_path`.

## Where the numbers come from

`.coveragerc` scopes the measurement to the four directories holding shipped
Python and reports every file it finds there, so a new untested script appears
at 0% rather than not appearing at all. Coverage skips directories without an
`__init__.py`, and none of these are importable packages, hence
`include_namespace_packages`.

Excluded from the denominator, with the reason in `.coveragerc`: the three git
submodules (upstream projects with their own suites), the ctypes probes under
`deploy_cukinia_tests` (test material, not shipped code), and the three-line
`vmmgrapi` WSGI entrypoint.

Ansible roles and playbooks are not part of this measurement. They are covered
by the molecule scenarios and the integration jobs, and there is no established
free tool that reports statement coverage over Ansible tasks.

## Conventions

**Loading the code under test.** None of these files is an installable package,
so `tests/support.py` provides `load_script("relative/path.py")`, which imports
one by path. Every script guards its entry point with `if __name__ ==
"__main__"`, so importing one defines its functions and does nothing else.

**Stubbing what cannot be installed.** `install_stub_module(name)` registers an
empty module so a script importing it can load: `rados` and `rbd` ship with
Ceph, `vm_manager` lives in a submodule the unit job does not check out, and
`ansible.module_utils` would drag ansible-core into the test environment for no
gain. Tests then assert on the calls the code makes.

Note the fake `AnsibleModule` in `test_cluster_vm.py`: its `fail_json` and
`exit_json` raise exceptions deriving from `BaseException`, because the real
ones raise `SystemExit`. That is load-bearing. A `fail_json` raised inside the
command dispatch has to slip past the `except Exception` wrapped around it.

**Seams.** Prefer patching the module attribute the code reads
(`monkeypatch.setattr(snmp, "run_command", fake)`) over patching a library
globally. Where a script writes through a module-level file handle, point that
handle at a `StringIO`.

## OpenSSF Best Practices

The badge thresholds this suite answers to:

| Criterion | Level | Threshold |
|---|---|---|
| `test_statement_coverage80` | silver | 80% statements |
| `test_statement_coverage90` | gold | 90% statements |
| `test_branch_coverage80` | gold | 80% branches |

Current: **100% of statements, 98.7% of branches**. The remaining partial
branches are the unreachable fall-through of the last `elif` in the three
index-driven dispatch loops of `snmp_getdata.py`.
