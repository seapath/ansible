#!/usr/bin/python3 -u

import snmp_passpersist as snmp
import subprocess

def my_setter(oid, type, value):
    try:
        subprocess.run(value.split(" "))
    except:
        pass
    return True

def update():
    pp.add_str('0.0', "seapath")
    file_path = "/tmp/snmpdata.txt"
    with open(file_path, "r") as file:
        for line in file:
            # Split the line at the first ":" character
            parts = line.split(":", 1)

            # Ensure that there is at least one ":" character in the line
            if len(parts) == 2:
                oid = parts[0].strip()
                value = parts[1].strip()
                pp.add_str("0"+oid, value[0:4000])

pp=snmp.PassPersist(".2.25.1936023920.1635018752")
pp.register_setter('.2.25.1936023920.1635018752.0.0', my_setter)
pp.start(update,300)
