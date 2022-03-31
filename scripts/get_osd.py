#!/usr/bin/python3
import json
import subprocess
import os
import argparse


def print_osd_on_host(hostname):
    subprocess.run(
        "ceph osd getcrushmap > ./crushmap",
        shell=True,
        check=True,
        capture_output=True,
    )
    result = subprocess.run(
        [
            "crushtool",
            "-d",
            "./crushmap",
            "-f",
            "json",
            "--dump",
            "-o",
            "/dev/null",
        ],
        check=True,
        shell=False,
        stdout=subprocess.PIPE
    )

    curshmap = json.loads(result.stdout.decode("UTF-8"))
    found_ods = None

    for bucket in curshmap["buckets"]:
        if bucket["type_name"] == "host" and bucket["name"] == hostname:
            for osd in bucket["items"]:
                found_ods = (
                    str(osd["id"]) if not found_ods else found_ods + "," + str(osd["id"])
                )
            break
    if found_ods:
        print(found_ods)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Print OSD daemons found inside the given machine"
    )
    parser.add_argument(
        "hostname",
        help="The Machine hostname to seach OSD",
        type=str,
    )
    args = parser.parse_args()
    print_osd_on_host(args.hostname)
